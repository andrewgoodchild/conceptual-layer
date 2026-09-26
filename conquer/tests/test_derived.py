#!/usr/bin/env python3
"""Sections 6.9 and 6.11: macros, and derivation rules -- derived fact types and derived
subtypes -- with the recursion the report deferred to SQL-3.

The company fixture gets three rules added at test time: a derived value (a taxed salary),
a recursive derived relationship (who reports up to whom, the transitive closure of
`has manager`), and a derived subtype (the employees who manage someone). Each is queried by
walking it like any other reading, and checked against the same relation written by hand
in SQL, recursive CTE included.

    test_derived.py [--model M] [--db D] [--only SUBSTRING] [-v]
"""

import argparse
import copy
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))

import conquer as driver           # noqa: E402
import forml                       # noqa: E402
import parser as parser_mod        # noqa: E402
import sql as sql_mod              # noqa: E402
import validate as validate_mod    # noqa: E402
import verbalise as verb_mod       # noqa: E402


def extend(model: dict) -> dict:
    """The fixture plus three derivation rules, written as section 6.11 writes them."""
    m = copy.deepcopy(model)
    m["concepts"] += [
        {"id": "vt.TaxedSalary", "name": "TaxedSalary", "kind": "value",
         "dataType": {"name": "numeric"}},
        {"id": "ft.EmployeeHasTaxedSalary", "name": "EmployeeHasTaxedSalary", "kind": "fact",
         "roles": [{"id": "r.EmployeeHasTaxedSalary.employee", "player": "et.Employee",
                    "name": "Employee", "ordinal": 0},
                   {"id": "r.EmployeeHasTaxedSalary.taxed", "player": "vt.TaxedSalary",
                    "name": "Taxed", "ordinal": 1}],
         "readings": [{"id": "rd.EmployeeHasTaxedSalary", "text": "{0} has {1}",
                       "roleSequence": ["r.EmployeeHasTaxedSalary.employee",
                                        "r.EmployeeHasTaxedSalary.taxed"]}],
         "derivation": "dr.taxed"},
        {"id": "ft.EmployeeReportsUpTo", "name": "EmployeeReportsUpTo", "kind": "fact",
         "roles": [{"id": "r.EmployeeReportsUpTo.employee", "player": "et.Employee",
                    "name": "Reporter", "ordinal": 0},
                   {"id": "r.EmployeeReportsUpTo.boss", "player": "et.Employee",
                    "name": "Superior", "ordinal": 1}],
         "readings": [{"id": "rd.EmployeeReportsUpTo", "text": "{0} reports up to {1}",
                       "roleSequence": ["r.EmployeeReportsUpTo.employee",
                                        "r.EmployeeReportsUpTo.boss"]}],
         "derivation": "dr.reports"},
        {"id": "et.Boss", "name": "Boss", "kind": "entity", "supertypes": ["et.Employee"],
         "derivation": "dr.boss"},
        # a derived subtype of a type identified by two columns (the pilot's Laboratory)
        {"id": "et.BigAssignment", "name": "BigAssignment", "kind": "entity",
         "supertypes": ["ft.Assignment"], "derivation": "dr.big"},
    ]
    m["macros"] = [
        {"id": "mc.taxed", "name": "Taxed", "parameters": ["s"], "kind": "scalar",
         "source": "s * 1.5"},
        {"id": "mc.wellpaid", "name": "WellPaid", "parameters": ["s"], "kind": "condition",
         "source": "s > 100000"},
        {"id": "mc.verywell", "name": "VeryWellPaid", "parameters": ["s"], "kind": "condition",
         "source": "Taxed(s) > 200000"},
        {"id": "mc.engineers", "name": "Engineers", "parameters": [], "kind": "path",
         "source": "Employee [has Department: 'ENG']"},
        {"id": "mc.loop", "name": "Loop", "parameters": ["s"], "kind": "scalar",
         "source": "Loop(s) + 1"},
    ]
    m["derivationRules"] = [
        {"id": "dr.taxed", "target": {"kind": "factType", "ref": "ft.EmployeeHasTaxedSalary"},
         "source": "LIST e, t FROM Employee e has EmployeeSalary s AND ALSO (s * 1.5) AS t"},
        {"id": "dr.reports", "target": {"kind": "factType", "ref": "ft.EmployeeReportsUpTo"},
         "source": "(LIST e, b FROM Employee e has manager Employee b) UNITED WITH "
                   "(LIST e, b FROM Employee e has manager Employee reports up to Employee b)"},
        {"id": "dr.boss", "target": {"kind": "subtype", "ref": "et.Boss"},
         "source": "Employee is manager of Employee"},
        {"id": "dr.big", "target": {"kind": "subtype", "ref": "et.BigAssignment"},
         "source": "Assignment [has AssignmentHours h WHERE h > 10]"},
    ]
    return m


CLOSURE = ("WITH RECURSIVE r(e, b) AS (SELECT emp_nr, manager_nr FROM employee "
           "WHERE manager_nr IS NOT NULL UNION SELECT r.e, m.manager_nr FROM r "
           "JOIN employee m ON m.emp_nr = r.b WHERE m.manager_nr IS NOT NULL) ")


def same_as(sql):  return ("same_as", sql)
def sql_has(s):    return ("sql_has", s)
def refuses(s):    return ("refuses", s)


CASES = [
 # -- a derived value: f(p1:a1, p2:a2) ::= P ---------------------------------------------
 ("a derived fact type is walked like any other reading",
  "LIST n, t FROM Employee has EmployeeName n AND ALSO has TaxedSalary t",
  same_as("SELECT emp_name, salary * 1.5 FROM employee WHERE salary IS NOT NULL")),
 ("it is defined once, as a common table expression",
  "LIST n, t FROM Employee has EmployeeName n AND ALSO has TaxedSalary t",
  sql_has('WITH "EmployeeHasTaxedSalary"("Employee", "Taxed") AS (')),
 ("and can be filtered and aggregated as a fact",
  "THE COUNT OF Employee [has TaxedSalary t] WHERE t > 150000",
  same_as("SELECT COUNT(*) FROM employee WHERE salary * 1.5 > 150000")),
 ("its population is a set, whatever the path repeats",
  "THE COUNT OF Employee has TaxedSalary",
  same_as("SELECT COUNT(*) FROM employee WHERE salary IS NOT NULL")),

 # -- a recursive derived relationship: the transitive closure of `has manager` ----------
 ("a rule may mention its own target, and the population is the least fixpoint",
  "THE COUNT OF Employee reports up to Employee",
  same_as(CLOSURE + "SELECT COUNT(*) FROM r")),
 ("which is emitted as WITH RECURSIVE over the UNION the rule wrote",
  "THE COUNT OF Employee reports up to Employee",
  sql_has("WITH RECURSIVE")),
 ("everyone above a given employee",
  "LIST n FROM Employee: 5 reports up to Employee has EmployeeName n",
  same_as(CLOSURE + "SELECT m.emp_name FROM r JOIN employee m ON m.emp_nr = r.b WHERE r.e = 5")),
 ("and everyone below one, entering by the far role's name (B.2)",
  "LIST n FROM Employee: 1 has Superior has Reporter has EmployeeName n",
  same_as(CLOSURE + "SELECT m.emp_name FROM r JOIN employee m ON m.emp_nr = r.e WHERE r.b = 1")),

 # -- a derived subtype: t ::= P, the population is the heads of P ------------------------
 ("a derived subtype's population is the heads of its rule",
  "THE COUNT OF Boss",
  same_as("SELECT COUNT(DISTINCT manager_nr) FROM employee WHERE manager_nr IS NOT NULL")),
 ("and it inherits its supertype's fact types",
  "LIST n FROM Boss has EmployeeName n",
  same_as("SELECT emp_name FROM employee WHERE emp_nr IN "
          "(SELECT manager_nr FROM employee WHERE manager_nr IS NOT NULL)")),
 ("a subtype rule with a bad path fails at the rule, and says so",
  None, refuses("in the derivation rule for Broken")),

 # -- section 6.9 macros: abbreviations, expanded before parsing goes on -------------------
 ("a scalar macro stands for its body with the argument substituted",
  "LIST n, Taxed(s) FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  same_as("SELECT emp_name, salary * 1.5 FROM employee WHERE salary IS NOT NULL")),
 ("and keeps its precedence when it stands inside an expression",
  "LIST n, 2 * Taxed(s) FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  same_as("SELECT emp_name, salary * 3.0 FROM employee WHERE salary IS NOT NULL")),
 ("a condition macro stands in a WHERE",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE WellPaid(s)",
  same_as("SELECT emp_name FROM employee WHERE salary > 100000")),
 ("a macro may use another macro",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE VeryWellPaid(s)",
  same_as("SELECT emp_name FROM employee WHERE salary * 1.5 > 200000")),
 ("a path macro stands at the head of a path",
  "LIST n FROM Engineers() has EmployeeName n",
  same_as("SELECT emp_name FROM employee WHERE dept_code = 'ENG'")),
 # A DEFINE's computed column has no type the model can know, and saying "text" is not a
 # neutral default: `constant_value` takes a literal's SQL type from the value type it is
 # compared with, so `v > 200000` bound the string '200000', and SQLite orders every number
 # below every string -- zero rows where four are right. Found by a benchmark writer reading
 # its own row counts (finding 123). The same bug was fixed once for an aggregate's result;
 # the fix is the same, to declare no type and let the literal keep its own.
 ("a computed column compares against a number as a number",
  "DEFINE Taxed ::= LIST e, t FROM Employee e has EmployeeSalary s AND ALSO (s * 2) AS t "
  "LIST x FROM Employee has EmployeeName x AND ALSO has Taxed TaxedT v WHERE v > 200000",
  same_as("SELECT emp_name FROM employee WHERE salary * 2 > 200000")),

 ("and against a string as a string",
  "DEFINE Initial ::= LIST e, i FROM Employee e has EmployeeName n AND ALSO substr(n, 1, 1) AS i "
  "LIST x FROM Employee has EmployeeName x AND ALSO has Initial InitialI v WHERE v = 'A'",
  same_as("SELECT emp_name FROM employee WHERE substr(emp_name, 1, 1) = 'A'")),

 # -- a DEFINE that lists more than one value --------------------------------------------
 # Every test here listed a key and ONE value, and the three-column case shipped broken in
 # both directions: `reading_slots` yields a verb part only between *adjacent* slots, so the
 # single n-ary reading reached the second value only by walking through the first with the
 # verb "and has b", which nobody writes -- and `has <Name> <SecondValueType>` resolved
 # silently to the FIRST value and returned a plausible wrong number. Six writers on one
 # LiveSQLBench run hit it; none of them was told anything was wrong.
 ("DEFINE  a second listed value is reachable, and is not the first",
  "DEFINE Two ::= LIST d, a, b FROM Department d has DepartmentCode c "
  "AND ALSO (length(c) * 1) AS a AND ALSO (length(c) * 100) AS b "
  "LIST d, x, y FROM Department d has a TwoA x AND ALSO has b TwoB y",
  same_as("SELECT dept_code, LENGTH(dept_code) * 1, LENGTH(dept_code) * 100 "
          "FROM department")),
 ("DEFINE  the defined name still reaches the first value",
  "DEFINE Two ::= LIST d, a, b FROM Department d has DepartmentCode c "
  "AND ALSO (length(c) * 1) AS a AND ALSO (length(c) * 100) AS b "
  "LIST d, x FROM Department d has Two TwoA x",
  same_as("SELECT dept_code, LENGTH(dept_code) * 1 FROM department")),
 # The silent half. A step that names where it is going and does not get there must refuse:
 # with one candidate left it used to fall through to `return viable[0]`.
 ("DEFINE  naming a value the verb does not reach is refused, not quietly redirected",
  "DEFINE Two ::= LIST d, a, b FROM Department d has DepartmentCode c "
  "AND ALSO (length(c) * 1) AS a AND ALSO (length(c) * 100) AS b "
  "LIST d, y FROM Department d has Two TwoB y",
  refuses("does not reach TwoB")),

 # A DEFINE keyed on a VALUE type, which is the natural way to write "the busiest
 # department, and who is in it": the definition lists the code and the count, and the
 # question then asks for the maximum count over those codes. A value type has no table, so
 # heading a path with one used to refuse outright -- "cannot anchor node: its concept has
 # no table in the mapping" -- and two benchmark writers concluded the shape was
 # inexpressible (finding 127). The step says which population is meant: the value is the
 # role it is about to enter by, so the head ranges over that role's own table.
 ("a value type heads a path by the role it enters",
  "DEFINE Busy ::= LIST d, n FROM Employee has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF d GROUPED BY d AS n "
  "THE MAXIMUM DepartmentCode has Busy BusyN",
  same_as("SELECT MAX(n) FROM (SELECT COUNT(*) n FROM employee WHERE dept_code IS NOT NULL "
          "GROUP BY dept_code)")),

 ("and the whole shape it was blocking: the top group, and its members",
  "DEFINE Busy ::= LIST d, n FROM Employee has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF d GROUPED BY d AS n "
  "LIST c, nm FROM Employee has Department has DepartmentCode c AND ALSO has EmployeeName nm "
  "AND ALSO c has Busy BusyN n WHERE n = THE MAXIMUM DepartmentCode has Busy BusyN",
  same_as("SELECT d.dept_code, e.emp_name FROM department d JOIN employee e "
          "ON e.dept_code = d.dept_code WHERE d.dept_code = "
          "(SELECT dept_code FROM employee GROUP BY dept_code ORDER BY COUNT(*) DESC LIMIT 1)")),

 # -- a derived subtype of a composite-identified type ---------------------------------
 ("a derived subtype inherits a two-column identifier",
  "THE COUNT OF BigAssignment",
  same_as("SELECT COUNT(*) FROM assignment WHERE hours > 10")),
 ("and is walked through its supertype's readings",
  "LIST h FROM BigAssignment has AssignmentHours h",
  same_as("SELECT hours FROM assignment WHERE hours > 10")),
 # A derived subtype named at the end of a step, then walked on from. The lowering
 # unifies a subtype node with the Assignment node the step reached; the emitter used to
 # alias every step's anchor under the unification's root, and when the union settled on
 # the subtype node it inherited the row before anything narrowed it -- the pilot's
 # `is of BilirubinWithinNormalRangeLaboratory has LaboratoryDate d` joined every lab
 # (finding 114, found by the reference interpreter).
 ("a derived subtype named at a reached node narrows the row walked on from",
  "LIST h FROM Employee has BigAssignment has AssignmentHours h",
  same_as("SELECT hours FROM assignment WHERE hours > 10")),
 ("and does so beside other branches of the head",
  "LIST n, h FROM Employee has EmployeeName n AND ALSO has BigAssignment has AssignmentHours h "
  "WHERE h < 30",
  same_as("SELECT e.emp_name, a.hours FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr "
          "WHERE a.hours > 10 AND a.hours < 30")),
 ("and narrows a step that names it",
  "THE COUNT OF Employee [has BigAssignment]",
  same_as("SELECT COUNT(*) FROM employee e WHERE EXISTS (SELECT 1 FROM assignment a "
          "WHERE a.emp_nr = e.emp_nr AND a.hours > 10)")),
 ("and ordered by, as all of them",
  "LIST a FROM BigAssignment a ORDERED WITH a THE FIRST 2",
  same_as("SELECT emp_nr, proj_code FROM assignment WHERE hours > 10 "
          "ORDER BY emp_nr, proj_code LIMIT 2")),
 # A derived subtype at the head of a path ranges over its supertype's row, so the
 # supertype's relationships -- and a foreign key that references a non-identifier column
 # (card_games' uuid, finding 34) -- join as they do from the supertype.
 ("a derived subtype at the head walks the supertype's relationships",
  "THE COUNT OF Boss has Assignment",
  same_as("SELECT COUNT(*) FROM assignment a WHERE a.emp_nr IN "
          "(SELECT manager_nr FROM employee WHERE manager_nr IS NOT NULL)")),
 ("and a composite one leaves by its roles",
  "LIST n FROM BigAssignment has Project has ProjectName n",
  same_as("SELECT p.proj_name FROM assignment a JOIN project p ON p.proj_code = a.proj_code "
          "WHERE a.hours > 10")),
 ("a composite instance is listed as all of its identifying columns",
  "LIST a FROM BigAssignment a",
  same_as("SELECT emp_nr, proj_code FROM assignment WHERE hours > 10")),
 ("but never itself: recursion is a derivation rule's, not a macro's",
  "LIST n, Loop(s) FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  refuses("recursive")),
 ("the argument count is checked",
  "LIST n, Taxed(s, 2) FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  refuses("takes 1 argument")),
]


def run(model, conn, lexicon, emitter, query, expect):
    kind, arg = expect
    try:
        _, statement, params = driver.transpile(model, query, lexicon, emitter)
    except (parser_mod.ParseError, sql_mod.SqlError) as e:
        if kind == "refuses" and arg.lower() in str(e).lower():
            return True, "refused as expected"
        return False, "%s: %s" % (type(e).__name__, e)
    if kind == "refuses":
        return False, "expected a refusal mentioning %r" % arg
    if kind == "sql_has":
        return (arg in statement), statement
    got = conn.execute(statement, params).fetchall()
    want = conn.execute(arg).fetchall()
    row = lambda r: tuple("" if v is None else str(v) for v in r)
    if sorted(row(r) for r in got) == sorted(row(r) for r in want):
        return True, "%d rows, matches reference" % len(got)
    return False, "got %r, reference %r\n        %s" % (got[:6], want[:6], statement)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not os.path.exists(args.model):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2
    model = extend(json.load(open(args.model)))
    conn = sqlite3.connect(args.db)
    lexicon = parser_mod.Lexicon(model)
    emitter = sql_mod.Emitter(model)

    passed = total = 0
    for name, query, expect in CASES:
        if args.only and args.only.lower() not in name.lower():
            continue
        total += 1
        if query is None:
            # a broken rule: the failure must name the rule, not the query that touched it
            broken = copy.deepcopy(model)
            broken["concepts"].append({"id": "et.Broken", "name": "Broken", "kind": "entity",
                                       "supertypes": ["et.Employee"], "derivation": "dr.broken"})
            broken["derivationRules"].append(
                {"id": "dr.broken", "target": {"kind": "subtype", "ref": "et.Broken"},
                 "source": "Employee has NoSuchThing"})
            ok, detail = run(broken, conn, parser_mod.Lexicon(broken), sql_mod.Emitter(broken),
                             "THE COUNT OF Broken", expect)
        else:
            ok, detail = run(model, conn, lexicon, emitter, query, expect)
        passed += ok
        print(("ok    %-70s %s" % (name[:70], detail if args.verbose else "")) if ok
              else "FAIL  %s\n        %s\n        %s" % (name, query, detail))

    # FORML reads the rule back the way section 6.11 writes it
    total += 2
    sentences = forml.verbalize_model(model)
    want = "Employee e has TaxedSalary t IFF Employee e has EmployeeSalary s AND ALSO (s * 1.5) AS t."
    ok = want in sentences
    passed += ok
    print(("ok    %-70s" % "FORML: a derived fact type reads as its reading IFF its rule") if ok
          else "FAIL  FORML derived fact type\n        got: %s" % [s for s in sentences if "IFF" in s])
    want = "An Employee is a Boss IFF Employee is manager of Employee."
    ok = want in sentences
    passed += ok
    print(("ok    %-70s" % "FORML: a derived subtype reads as A Super is a Sub IFF its rule") if ok
          else "FAIL  FORML derived subtype\n        got: %s" % [s for s in sentences if "IFF" in s])

    # The keys a rule implies (lower.declare_derived_keys, finding 115): `dr.taxed` lists one
    # row per Employee and declares no constraint, so the lexicon infers one on construction
    # and the step into TaxedSalary is functional; `dr.reports` is a set expression over a
    # ring and implies nothing.
    total += 2
    ok = lexicon.is_functional("r.EmployeeHasTaxedSalary.employee")
    passed += ok
    print(("ok    %-70s" % "a rule listing one row per head makes its fact type functional") if ok
          else "FAIL  the Employee role of the derived TaxedSalary is not functional")
    ok = not lexicon.is_functional("r.EmployeeReportsUpTo.employee")
    passed += ok
    print(("ok    %-70s" % "and a rule over a ring, united, implies no key") if ok
          else "FAIL  the derived closure was rated functional")

    # a macro is an abbreviation: the normal form has it expanded, --explain says so
    total += 2
    import normalise as norm_mod
    import lower as lower_mod
    ast = parser_mod.Parser(lexicon, "LIST n, Taxed(s) FROM Employee has EmployeeName n "
                            "AND ALSO has EmployeeSalary s").parse_query()
    text = norm_mod.to_conquer(lower_mod.lower(model, ast, lexicon), lexicon)
    ok = "Taxed(" not in text and "* 1.5" in text
    passed += ok
    print(("ok    %-70s" % "--normalise expands a macro, being an abbreviation") if ok
          else "FAIL  normalise macro\n        %s" % text)
    interp = verb_mod.explain(model, "LIST n FROM Employee has EmployeeName n AND ALSO "
                              "has EmployeeSalary s WHERE WellPaid(s)", lexicon)
    ok = any("Macro" in e and "WellPaid ( s )" in e for e in interp.expanded)
    passed += ok
    print(("ok    %-70s" % "--explain says what a macro stood for") if ok
          else "FAIL  explain macro\n        %s" % interp.expanded)

    # --explain says a step through a derived fact type is derived, and how
    total += 1
    interp = verb_mod.explain(model, "LIST n, t FROM Employee has EmployeeName n AND ALSO "
                              "has TaxedSalary t", lexicon)
    ok = any("IFF" in e and "derived" in e for e in interp.expanded)
    passed += ok
    print(("ok    %-70s" % "--explain: a derived step is reported with its rule") if ok
          else "FAIL  --explain derived step\n        expanded: %s" % interp.expanded)

    # the extended model, rules and all, validates against the CCM schema and its rules
    total += 1
    import tempfile
    tmp = tempfile.mktemp(suffix=".ccm.json")
    json.dump(model, open(tmp, "w"))
    schema = json.load(open(os.path.join(HERE, "..", "..", "model", "ccm.schema.json")))
    findings = validate_mod.validate(tmp, schema)
    os.unlink(tmp)
    ok = not findings.errors
    passed += ok
    print(("ok    %-70s" % "model/validate accepts a model whose rules are still source text") if ok
          else "FAIL  validate\n        %s" % findings.errors[:4])

    print("\n%d passed, %d failed, %d total" % (passed, total - passed, total))
    conn.close()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
