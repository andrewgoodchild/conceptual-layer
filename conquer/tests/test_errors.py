#!/usr/bin/env python3
"""What the compiler says when the query, or the model, is wrong.

`test_operators.py` covers what each operator *computes*, and refuses the handful the report
specifies but this transpiler does not build. Neither is the same as checking that ordinary
mistakes -- a mistyped type name, an unbound variable, a half-finished query, a model whose
mapping does not hold together -- are reported in terms the person who made the mistake can
act on.

Two things are asserted per case: the exception *class*, because a ParseError and a SqlError
mean different things to a caller and callers switch on them; and a phrase from the message,
because "cannot lower Seq" would satisfy the class and help nobody. A raw KeyError escaping
from a half-built model is the failure this file exists to catch -- one was, from an
incomplete relational mapping, and the case is below.

    test_errors.py [-v] [--only SUBSTRING] [--model M]
"""

import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402

ParseError, Ambiguous, SqlError = parser_mod.ParseError, parser_mod.Ambiguous, sql_mod.SqlError
Judgement = parser_mod.Judgement


# -- a bad query against a good model ---------------------------------------------------
QUERY_CASES = [
 # (name, query, expected exception, phrase the message must contain)

 # naming things that are not there
 ("a mistyped type name",
  "Employe has EmployeeName", ParseError, "neither a type in this schema"),
 ("a verb the head cannot follow",
  "Employee has EmployeeFoo", ParseError, "unconsumed input"),
 ("an unbound variable in a condition",
  "Employee has EmployeeName n WHERE q > 1", ParseError, "neither a type in this schema"),
 ("listing something the query never reaches",
  "LIST z FROM Employee has EmployeeName n", ParseError, "neither a variable nor a type"),
 ("a role reference the head cannot play",
  "Manager has Carspace", ParseError, "is not a role Manager can play"),
 ("a ring by its type alone: no reading says `has Employee`, so the message lists the "
  "verb parts that reach it",
  "Employee has Employee has EmployeeNr", Ambiguous,
  "Employee reaches Employee by 'has manager', 'is manager of'"),
 ("a function the model does not define",
  "LIST wibble(s) FROM Employee has EmployeeSalary s", ParseError, "no function"),
 # SQL's habit. The projection list stopped at AS, FROM was not next, and the parser backed
 # up and read `n, round(...) AS k FROM ...` as a path -- so the message named `n`, which
 # was fine, and two LiveSQLBench writers each spent a round trip on it.
 ("naming a listed column with AS, which belongs in the path",
  "LIST n, round(s, 1) AS k FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  ParseError, "LIST cannot name a column with AS"),

 # ambiguity, which must be reported rather than silently resolved
 ("a verb with several readings from the same head",
  "Employee has", Ambiguous, "is ambiguous between"),

 # half-finished input
 ("a comparison with nothing on the right",
  "Employee has EmployeeSalary > ", ParseError, "unexpected end of input"),
 ("an unclosed parenthesis",
  "(Employee has EmployeeName", ParseError, "expected ')'"),
 ("an unclosed sub-expression",
  "Employee has EmployeeName [", ParseError, "unexpected end of input"),
 ("AS with no name after it",
  "Employee has EmployeeName AS", ParseError, "AS must be followed by a variable name"),
 ("an abstract denotation with no variable",
  "EmployeeName: !", ParseError, "expected a variable name after '!'"),
 ("a character the lexer does not know",
  "Employee has EmployeeName #", ParseError, "unexpected character"),
 ("trailing input nothing consumed",
  "Employee has EmployeeName n extra", ParseError, "unconsumed input"),
 ("a path that starts with a verb",
  "has EmployeeName", ParseError, "needs something to continue from"),

 # denotations
 ("more denotations than the identifier has roles",
  "Department: 'ENG','X'", ParseError, "unconsumed input"),
 ("a denotation on a type with no preferred identifier",
  "Assignment: 4", ParseError, "has no preferred identifier"),

 # grouping and aggregation
 ("GROUPED BY something the query does not bind",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY zz AS c", ParseError, "is not bound by this query"),
 ("`x IN` naming an attribute the path does not bind",
  "THE COUNT OF x IN Employee has Department", ParseError,
  "names an attribute the path does not bind"),
 ("walking a verb off a computed value",
  "LIST n FROM Employee has EmployeeName n AND ALSO THE COUNT OF Employee AS c "
  "WHERE c has EmployeeName", ParseError, "was given a computed value"),

 # ordering, whose failure mode used to be silent (see test_operators.py)
 ("sorting by a name the query does not have",
  "LIST n FROM Employee has EmployeeName n ORDERED WITH typo DESCENDING", ParseError,
  "neither a variable this query binds"),

 # aggregate locality: the fan trap, judged from the uniqueness constraints (lower.py's
 # check_aggregate_locality). A grouped fan-out whose group keys do NOT pin the value: the
 # salary is determined by the Employee, and one Department has many, so the group holds
 # several distinct salaries and each is repeated once per assignment. A summed value in this
 # position is computed, not refused: it is re-lowered over a bag of its own and deduplicated
 # there (finding 117; see test_fanout.py). A COUNT keeps finding 78's reading -- counting a
 # fanned head is the author's business -- and so keeps the refusal and its message.
 ("counting a value the query multiplies, which the group keys do not pin",
  "LIST c, t FROM Department has DepartmentCode c AND ALSO is of Employee has EmployeeSalary s "
  "AND ALSO is of Employee has Assignment has AssignmentHours h "
  "AND ALSO THE COUNT OF s GROUPED BY c AS t", Judgement,
  "one Department has many Employee"),
 ("and the message names the bracket that fixes it, and its one condition",
  "LIST c, t FROM Department has DepartmentCode c AND ALSO is of Employee has EmployeeSalary s "
  "AND ALSO is of Employee has Assignment has AssignmentHours h "
  "AND ALSO THE COUNT OF h GROUPED BY c AS t", Judgement,
  "binds a name and joins"),
 # §11's query-local derivation rules
 ("DEFINE with a name the model already uses",
  "DEFINE Employee ::= LIST e FROM Employee e LIST n FROM Employee has EmployeeName n",
  ParseError, "already has something called that"),
 ("DEFINE with nothing after it",
  "DEFINE X ::= LIST e FROM Employee e", ParseError, "nothing asks anything of it"),
 ("DEFINE with no ::=",
  "DEFINE X LIST e FROM Employee e LIST e FROM Employee e", ParseError, "must be followed by ::="),
 ("DEFINE whose body does not parse says which definition",
  "DEFINE X ::= LIST e FROM Employe e LIST n FROM Employee has EmployeeName n",
  ParseError, "in the definition of X"),

 ("counting rows a second fan-out multiplies",
  "LIST d, c FROM Department has DepartmentCode d AND ALSO is of Employee e "
  "AND ALSO is of Employee e2 AND ALSO THE COUNT OF e GROUPED BY d AS c", Judgement,
  "computed over rows this query multiplies"),

 # The other two judgements, here rather than only in test_operators so that --permissive is
 # held to them: every Judgement in QUERY_CASES is replayed permissively below.
 ("a node the query joins to nothing",
  "LIST d, c FROM Employee has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF Project GROUPED BY d AS c", Judgement, "joined to nothing"),
 ("a value unified with an instance",
  "LIST n FROM Employee has EmployeeName n AND ALSO Department has DepartmentName n",
  Judgement, "cannot be the same thing"),
]


# -- a good query against a bad model ---------------------------------------------------
# Each mutation breaks the relational mapping the way a hand-edited or partially generated
# model plausibly would. model.md §6 makes the mapping mandatory for a query to compile.

def drop_mapping(m):
    m.pop("mapping")


def empty_role_map(m):
    m["mapping"]["roleMap"] = []


def empty_concept_map(m):
    m["mapping"]["conceptMap"] = []


def empty_tables(m):
    m["mapping"]["tables"] = []


def empty_columns(m):
    m["mapping"]["columns"] = []


def add_sibling_subtype(m):
    """A second subtype of Employee, so the model has a sibling pair. Two subtypes of one
    supertype are one instance seen twice: no fact type runs between them, so `Manager has
    Contractor` cannot work and neither can the inverse verb, which is what the message used
    to advise (finding 135)."""
    m["concepts"] += [
        {"id": "et.Contractor", "name": "Contractor", "kind": "entity",
         "identifier": ["r.EmployeeHasNr.employee"], "supertypes": ["et.Employee"]},
        {"id": "vt.ContractorRate", "name": "ContractorRate", "kind": "value",
         "dataType": {"name": "integer"}},
        {"id": "ft.ContractorHasRate", "name": "ContractorHasRate", "kind": "fact",
         "roles": [{"id": "r.ContractorHasRate.contractor", "player": "et.Contractor",
                    "ordinal": 0},
                   {"id": "r.ContractorHasRate.rate", "player": "vt.ContractorRate",
                    "ordinal": 1}],
         "readings": [{"id": "rd.ContractorHasRate", "text": "{0} has {1}",
                       "roleSequence": ["r.ContractorHasRate.contractor",
                                        "r.ContractorHasRate.rate"]}]}]
    mp = m["mapping"]
    mp["conceptMap"] += [
        {"concept": "et.Contractor", "table": "t.manager",
         "identifyingColumns": ["c.manager.emp_nr"]},
        {"concept": "ft.ContractorHasRate", "table": "t.manager",
         "identifyingColumns": ["c.manager.emp_nr"]}]
    mp["roleMap"] += [
        {"role": "r.ContractorHasRate.contractor", "table": "t.manager",
         "columns": ["c.manager.emp_nr"]},
        {"role": "r.ContractorHasRate.rate", "table": "t.manager",
         "columns": ["c.manager.car_space"]}]


MODEL_CASES = [
 # The message used to end "try the inverse verb", which is the answer for a ring and not for
 # a sibling. It now names the form that works: read the other subtype's value from here.
 ("a sibling subtype is not reached by the inverse verb",
  add_sibling_subtype, "Manager has Contractor has ContractorRate r", Ambiguous,
  "Name what you want from Contractor directly"),
 # (name, mutation, query, expected exception, phrase)
 ("no relational mapping at all",
  drop_mapping, "Employee has EmployeeName", SqlError, "carries no relational mapping"),
 ("a role with no mapping",
  empty_role_map, "Employee has EmployeeName", SqlError, "has no relational mapping"),
 ("a concept with no table",
  empty_concept_map, "Employee has EmployeeName", SqlError, "has no table in the mapping"),
 # Both of these used to escape as a bare KeyError carrying nothing but an internal id.
 ("a conceptMap naming a table the mapping never declares",
  empty_tables, "Employee has EmployeeName", SqlError, "which it does not declare"),
 ("a conceptMap naming columns the mapping never declares",
  empty_columns, "Employee has EmployeeName", SqlError, "which it does not declare"),
]


def attempt(model, query):
    """Compile, and report what came back out. Anything that is not one of the compiler's
    own exception types is a failure in itself -- that is the point of the file."""
    try:
        driver.transpile(model, query)
        return None, "it compiled"
    except (ParseError, Ambiguous, SqlError) as e:
        return type(e), str(e)
    except Exception as e:                     # noqa: BLE001 -- deliberately broad
        return type(e), "%s: %s" % (type(e).__name__, e)


def check(got_type, got_message, want_type, phrase):
    if got_type is None:
        return False, "expected %s, but the query compiled" % want_type.__name__
    if got_type is not want_type:
        return False, ("expected %s, got %s -- %s"
                       % (want_type.__name__, got_type.__name__, got_message[:90]))
    if phrase.lower() not in got_message.lower():
        return False, ("%s did not mention %r: %s"
                       % (want_type.__name__, phrase, got_message[:90]))
    return True, got_message[:72]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if not os.path.exists(args.model):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2
    model = json.load(open(args.model))
    passed = failed = 0

    cases = []
    for name, query, want, phrase in QUERY_CASES:
        cases.append((name, model, query, want, phrase))
    for name, mutate, query, want, phrase in MODEL_CASES:
        broken = copy.deepcopy(model)
        mutate(broken)
        cases.append((name, broken, query, want, phrase))

    for name, m, query, want, phrase in cases:
        if args.only and args.only.lower() not in name.lower():
            continue
        ok, note = check(*attempt(m, query), want, phrase)
        if ok:
            passed += 1
            if args.verbose:
                print("ok    %-52s %s" % (name, note))
        else:
            failed += 1
            print("FAIL  %s\n        %s\n        %s" % (name, query, note))

    # -- the one thing a *running* query says about itself ---------------------------------
    # Every other message here is a refusal. This one fires on a query that compiled and ran,
    # which is the class the benchmark loses answers to: 13 of 984 misses across 30 arms are
    # loud failures, and the rest ran fine and returned the wrong rows (finding 132). An
    # empty result is the only row count worth reporting -- of the 13 recorded answers that
    # returned none, 13 were wrong, against a 30% base rate; every other count is noise,
    # because the modal wrong answer returns exactly one row.
    for name, rows, want in (("an empty result says so", [], True),
                             ("a result with rows does not", [("x",)], False)):
        if args.only and args.only.lower() not in name.lower():
            continue

        class _Cursor:
            description = [("n",)]

            def __init__(self, rs):
                self._rs = rs

            def fetchall(self):
                return self._rs

        text = driver.render_rows(_Cursor(rows))
        if ("No rows matched" in text) == want:
            passed += 1
            if args.verbose:
                print("ok    %-52s %s" % (name, text.splitlines()[-1][:40]))
        else:
            failed += 1
            print("FAIL  %s\n        %s" % (name, text))

    # -- an aggregate the dialect does not have -------------------------------------------
    # THE MEDIAN is in the language; whether the model carries `fn.median` is the dialect's
    # business. SQLite has no ordered-set aggregate and no closed form for one, so naming it
    # must refuse in lowering rather than emit SQL no engine runs (finding 148).
    #
    # STANDARD DEVIATION used to be here beside it. It is not any more: SQLite has no STDDEV
    # either, but the sample form *is* a closed expression in SUM and COUNT, so the dialect
    # now spells it out rather than refusing. Both blind writers on the LiveSQLBench arm
    # wrote those moments by hand, identically, which is the argument for doing it for them.
    # A listed expression is named by its text, and the text was the token stream with a
    # space between every token: `round ( s / 1000 , 1 )` was every writer's column header.
    name = "a listed expression is named the way it was written"
    if not (args.only and args.only.lower() not in name.lower()):
        q = parser_mod.parse(model, "LIST n, round(s / 1000, 1), (s * 2) * (3), "
                                    "(THE COUNT OF Employee WHERE (s > 1)) FROM Employee "
                                    "has EmployeeName n AND ALSO has EmployeeSalary s")
        labels = [label for label, _ in q.projections]
        if labels == ["n", "round(s / 1000, 1)", "(s * 2) * (3)",
                      "(THE COUNT OF Employee WHERE (s > 1))"]:
            passed += 1
            if args.verbose:
                print("ok    %-52s %s" % (name, labels[1]))
        else:
            failed += 1
            print("FAIL  %s\n        %r" % (name, labels))

    # No dialect lacks the median any more -- SQLite spells it over the bag since finding
    # 158 -- so the principle is checked against a model with the function taken out.
    name = "an aggregate the dialect lacks is refused, not emitted"
    if not (args.only and args.only.lower() not in name.lower()):
        without = dict(model, functions=[f for f in model["functions"] if f["id"] != "fn.median"])
        try:
            driver.transpile(without, "LIST v FROM THE MEDIAN OF EmployeeSalary AS v")
            failed += 1
            print("FAIL  %s\n        it compiled against a SQLite model" % name)
        except (SqlError, parser_mod.ParseError) as e:
            if "no median" in str(e):
                passed += 1
                if args.verbose:
                    print("ok    %-52s %s" % (name, str(e)[:34]))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, str(e)[:90]))

    # -- what the model says about the data, and about itself -----------------------------
    # Two things the schema listing carries that no constraint enforces: a caution about the
    # values (finding 144) and a marker on a reading no path can walk (finding 135). Both
    # exist to stop a writer being misled, so both are asserted on the text they produce.
    marked = copy.deepcopy(model)
    vt = next(c for c in marked["concepts"] if c["name"] == "EmployeeGender")
    vt["dataQuality"] = ["Values arrive in mixed case."]
    vt["description"] = "How the employee is recorded for reporting."
    unary = {"id": "ft.EmployeeIsRetired", "name": "EmployeeIsRetired", "kind": "fact",
             "roles": [{"id": "r.EmployeeIsRetired.employee", "player": "et.Employee",
                        "ordinal": 0}],
             "readings": [{"id": "rd.EmployeeIsRetired", "text": "{0} is retired",
                           "roleSequence": ["r.EmployeeIsRetired.employee"]}]}
    marked["concepts"].append(unary)
    listing = driver.describe(marked, "")
    for name, want in (
            ("a value caution reaches the schema listing", "Values arrive in mixed case."),
            ("and so does a term's description", "How the employee is recorded"),
            ("a unary reading is marked as unwalkable", "unary: a property, not a step")):
        if args.only and args.only.lower() not in name.lower():
            continue
        if want in listing:
            passed += 1
            if args.verbose:
                print("ok    %-52s %s" % (name, want[:34]))
        else:
            failed += 1
            print("FAIL  %s\n        listing does not carry %r" % (name, want))

    name = "walking a unary reading says what it is"
    if not (args.only and args.only.lower() not in name.lower()):
        try:
            driver.transpile(marked, "LIST n FROM Employee has EmployeeName n AND ALSO is retired")
            failed += 1
            print("FAIL  %s\n        it compiled" % name)
        except parser_mod.ParseError as e:
            if "property rather than a step" in str(e):
                passed += 1
                if args.verbose:
                    print("ok    %-52s %s" % (name, str(e)[:34]))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, str(e)[:90]))

    # -- the same refusals, under --permissive --------------------------------------------
    # The instrument for "do refusals help?": each judgement the compiler makes has to be
    # suppressible, or the counterfactual cannot be run. A refusal that is still a refusal
    # under --permissive is one whose cost can never be measured.
    for name, query, want, phrase in QUERY_CASES:
        if args.only and args.only.lower() not in name.lower():
            continue
        if want is not Judgement:
            continue
        try:
            block, statement, _ = driver.transpile(model, query, permissive=True)
            ok = bool(block.get("_suppressed")) and bool(statement)
            note = "emits SQL and records: %s" % (block.get("_suppressed") or ["nothing"])[0][:60]
        except Exception as e:                                        # noqa: BLE001
            ok, note = False, "still refused: %s: %s" % (type(e).__name__, str(e)[:70])
        if ok:
            passed += 1
            if args.verbose:
                print("ok    %-52s %s" % ("permissive: " + name, note))
        else:
            failed += 1
            print("FAIL  permissive: %s\n        %s" % (name, note))

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
