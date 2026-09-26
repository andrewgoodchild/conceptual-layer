#!/usr/bin/env python3
"""The report's section 8: verbalising a path expression back to normalised ConQuer.

Two kinds of test. The **round trip** is the proof of faithfulness: every query in the
operator suite is compiled, normalised, and the normalised text compiled again -- the second
compilation must return exactly the rows of the first, and normalising *it* must give the
same text back (the normal form is a fixed point). That is what makes `--normalise` an
answer to "what did the compiler understand?" rather than a paraphrase.

The **form** cases pin the rules themselves: what a denotation folds back into, when a step
becomes a filter, how a ring is spelt, what gets a name. What it *says* is the contract.

    test_normalise.py [--model M] [--db D] [--only SUBSTRING] [-v]
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import conquer as driver             # noqa: E402
import normalise as norm_mod         # noqa: E402
import parser as parser_mod          # noqa: E402
import sql as sql_mod                # noqa: E402
import test_operators                # noqa: E402


def gives(text):   return ("gives", text)
def has(text):     return ("has", text)
def lacks(text):   return ("lacks", text)


# (name, query, expectation). `gives` is the whole normalised text; `has`/`lacks` a phrase.
FORM = [
 # §8.2 types and denotations
 ("a path without LIST lists its head and its tail; the normal form says so ([P56])",
  "Employee has Department", gives("LIST v1, v2 FROM Employee v1 has Department v2")),
 ("a constant only compared for equality folds back into a denotation ([V2])",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode: 'ENG'",
  has("has DepartmentCode: 'ENG'")),
 ("an entity denotation is spelt out through its reference scheme",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department: 'ENG'",
  has("has Department has DepartmentCode: 'ENG'")),
 ("a constant compared any other way stays a condition",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > 100000",
  has("WHERE v1 > 100000")),
 ("a node another clause refers to keeps a name, so it cannot fold",
  "LIST n, d FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d "
  "WHERE d = 'ENG'",
  has("WHERE d = 'ENG'")),
 ("a string that looks like a number is still a string",
  "LIST n FROM Employee has EmployeeName n WHERE substr(n, 1, 1) = '4'",
  has("= '4'")),
 ("a number is a number",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s = 100000",
  has("has EmployeeSalary: 100000")),

 # §8.3-8.4 steps and readings
 ("the verb is the reading's text between the two slots ([V14])",
  "LIST n FROM Employee has EmployeeName n", gives("LIST n FROM Employee has EmployeeName n")),
 ("a reading walked backwards uses the lexicon's inverse",
  "LIST n FROM Department is of Employee has EmployeeName n",
  gives("LIST n FROM Department is of Employee has EmployeeName n")),
 ("a ring with a reading of its own steps by it, adjective and all ([V14])",
  "LIST n, m FROM Employee [has EmployeeName n] has manager Employee has EmployeeNr m",
  has("has manager Employee has EmployeeNr m")),
 ("the other way round the ring is its inverse reading",
  "LIST n FROM Employee [has EmployeeName n] is manager of Employee has EmployeeNr",
  has("is manager of Employee has EmployeeNr")),
 ("a role reference walks the same ring; the normal form says it by the reading ([V15])",
  "LIST n, m FROM Employee [has EmployeeName n] has EmployeeHasManagerEmployee "
  "has EmployeeHasManagerManager has EmployeeNr m",
  has("has manager Employee has EmployeeNr m")),
 ("and the role names the other way round give the inverse reading",
  "LIST n FROM Employee [has EmployeeName n] has EmployeeHasManagerManager "
  "has EmployeeHasManagerEmployee has EmployeeNr",
  has("is manager of Employee has EmployeeNr")),
 ("an outer-joined step is OPTIONALLY, whichever way it was asked for ([V33])",
  "LIST n, s FROM Employee has EmployeeName n AND ALSO OPTIONALLY has EmployeeSalary s",
  has("OPTIONALLY has EmployeeSalary s")),
 ("a confluence element normalises to the same OPTIONALLY",
  "LIST n, s FROM has EmployeeSalary AS s EACH Employee has EmployeeName n",
  has("OPTIONALLY has EmployeeSalary s")),

 # §8.6-8.7 the line of the path; Fr operators; filters
 ("AND ALSO survives at the head, where it is the Fr operator ([V19])",
  "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  gives("LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s")),
 ("a filter on the head stays a filter, in front of the steps",
  "LIST n FROM Employee [has EmployeeGender: 'F'] has EmployeeName n",
  gives("LIST n FROM Employee [has EmployeeGender: 'F'] has EmployeeName n")),
 ("BUT NOT",
  "LIST n FROM Employee has EmployeeName n BUT NOT has Department: 'ENG'",
  has("BUT NOT has Department has DepartmentCode: 'ENG'")),
 ("OR OTHERWISE",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department: 'ENG' OR OTHERWISE "
  "has Department: 'OPS'",
  has("OR OTHERWISE [has Department has DepartmentCode: 'OPS']) has EmployeeName n")),
 ("a step off the line of a set comparison becomes a filter, so the compared node stays last",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "IS A SUBSET OF Employee: 4 has Assignment has Project",
  has("WHICH ARE ALL IN Employee [has EmployeeNr: 4] has Project")),
 ("a node of the enclosing block that a set comparison compares is named",
  "LIST dn FROM Department d [has DepartmentName dn] WHICH ARE ALL IN "
  "(LIST x FROM Employee e has Department x AND ALSO THE COUNT OF e GROUPED BY x AS c "
  "ORDERED WITH c DESCENDING THE FIRST 1)",
  has("WHERE d [has DepartmentName] WHICH ARE ALL IN (LIST x FROM")),

 # §8.10 group functions
 ("a grouped aggregate is declared with AS and referred to by its column's name ([V29])",
  "LIST d, c FROM Employee e has Department has DepartmentCode d AND ALSO "
  "THE COUNT OF e GROUPED BY d AS c ORDERED WITH c DESCENDING THE FIRST 1",
  gives("LIST d, c FROM Employee e has Department has DepartmentCode d AND ALSO "
        "THE COUNT OF e GROUPED BY d AS c ORDERED WITH c DESCENDING THE FIRST 1")),
 ("an aggregate over a path aggregates the path's last node, unnamed",
  "THE COUNT OF Assignment has Project has ProjectCode: 'APOLLO'",
  gives("THE COUNT OF Assignment has Project has ProjectCode: 'APOLLO'")),
 ("an aggregate over anything else names it: x IN (...) (B.2)",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s AND ALSO "
  "THE AVERAGE (s * 2) AS m WHERE s * 2 > m",
  has("THE AVERAGE v3 IN (Employee has EmployeeName AND ALSO has EmployeeSalary v2 "
      "AND ALSO v2 * 2 AS v3)")),
 # the IN path restates the head, so it is the head's (Fr), and the normal form says so:
 # the salary is a continuation of the same Employee, aggregated by name
 ("a grouped aggregate whose IN path restates the head folds into the head's path",
  "LIST d, t FROM Employee has Department has DepartmentCode d AND ALSO "
  "THE SUM OF s IN Employee has EmployeeSalary s GROUPED BY d AS t",
  gives("LIST d, t FROM Employee has Department has DepartmentCode d AND ALSO "
        "has EmployeeSalary v1 AND ALSO THE SUM OF v1 GROUPED BY d AS t")),
 ("a grouped aggregate whose path starts elsewhere keeps it inside the aggregate",
  "LIST d, t FROM Department d AND ALSO "
  "THE SUM OF s IN Employee [has Department d] has EmployeeSalary s GROUPED BY d AS t",
  has("THE SUM OF v1 IN Employee [has Department d] has EmployeeSalary v1 GROUPED BY d AS t")),
 ("an aggregate of a grouped aggregate (conquer-2026 item 7)",
  "THE AVERAGE c IN (Department d AND ALSO THE COUNT OF Employee [has Department d] "
  "GROUPED BY d AS c)",
  gives("THE AVERAGE c1 IN (Department d AND ALSO THE COUNT OF Employee [has Department d] "
        "GROUPED BY d AS c1)")),
 ("a correlated aggregate: the outer instance is !x ([V6])",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s AND ALSO "
  "has Department d WHERE s > THE AVERAGE Employee [has Department: !d] has EmployeeSalary",
  has("THE AVERAGE Employee [has Department: !v2] has EmployeeSalary")),
 ("DISTINCT ([V17])",
  "LIST d FROM DISTINCT Employee has Department has DepartmentCode d",
  gives("LIST d FROM DISTINCT Employee has Department has DepartmentCode d")),

 # §8.13-8.14 expressions and conditions
 ("an expression is bracketed only where precedence needs it",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE (s + 1) * 2 > s * (2 + 1)",
  has("WHERE (v1 + 1) * 2 > v1 * (2 + 1)")),
 ("left-associative operators need no brackets",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s * 1.0 / 2 > 1",
  has("WHERE v1 * 1.0 / 2 > 1")),
 ("a whole-query expression has no LIST ... FROM",
  "THE COUNT OF Employee [has EmployeeGender: 'F'] * 100 / THE COUNT OF Employee",
  gives("THE COUNT OF Employee [has EmployeeGender: 'F'] * 100 / THE COUNT OF Employee")),
 ("a set operation is a set operation of listed queries, each its own ([V19])",
  "Employee has EmployeeName UNITED WITH Department has DepartmentName",
  gives("(LIST v1, v2 FROM Employee v1 has EmployeeName v2) UNITED WITH "
        "(LIST v3, v4 FROM Department v3 has DepartmentName v4)")),
 ("several whole-query scalars keep their LIST, having no path to list them FROM",
  "LIST THE COUNT OF Employee, THE COUNT OF Department",
  gives("LIST THE COUNT OF Employee, THE COUNT OF Department")),
 ("an aggregate with its own WHERE is bracketed as an operand",
  "(THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 1) / 12",
  gives("(THE COUNT OF Employee [has EmployeeSalary v1] WHERE v1 > 1) / 12")),
 ("AND at the top of a WHERE is not bracketed, OR under AND is",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE (s > 1 OR s < 0) AND s <> 5",
  has("WHERE (v1 > 1 OR v1 < 0) AND v1 <> 5")),
 ("SOME: the comparison at the end of its path is a WHERE inside it",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department d "
  "WHERE SOME Employee [has Department: !d] has EmployeeSalary > 100000",
  has("WHERE SOME Employee has Department: !v1 AND ALSO has EmployeeSalary v2 "
      "WHERE v2 > 100000")),
 ("a boolean function stands as a condition",
  "LIST n FROM Employee has EmployeeName n WHERE starts_with(n, 'A')",
  has("WHERE starts_with(n, 'A')")),
 ("a scalar conditional",
  "LIST IF s > 100000 THEN 'high' ELSE 'low' FROM Employee has EmployeeSalary s",
  gives("LIST IF v1 > 100000 THEN 'high' ELSE 'low' FROM Employee has EmployeeSalary v1")),

 # [P56]-[P59] and the limit
 ("ORDERED alone sorts on the head, which is therefore named ([P57])",
  "LIST n FROM Employee has EmployeeName n ORDERED",
  gives("LIST n FROM Employee v1 has EmployeeName n ORDERED WITH v1 ASCENDING")),
 ("a sort key that was only bound gets a name",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING",
  gives("LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary v1 "
        "ORDERED WITH v1 DESCENDING")),
 ("THE FIRST n AFTER m PER x",
  "LIST d, n FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n "
  "AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 1 AFTER 1 PER d",
  has("ORDERED WITH v1 DESCENDING THE FIRST 1 AFTER 1 PER d")),
 ("a projected column named after its type gets a variable instead",
  "LIST Employee has EmployeeName", gives("LIST v1, v2 FROM Employee v1 has EmployeeName v2")),
 ("a projected column's name becomes the node's, when it can",
  "LIST n FROM Employee has EmployeeName n", gives("LIST n FROM Employee has EmployeeName n")),
]


def normalise(model, lexicon, text):
    ast = parser_mod.Parser(lexicon, text).parse_query()
    import lower as lower_mod
    return norm_mod.to_conquer(lower_mod.lower(model, ast, lexicon), lexicon)


def round_trip(model, conn, lexicon, emitter, query):
    """(ok, detail): compile, normalise, recompile, compare rows; then check the fixed point."""
    row = lambda r: tuple("" if v is None else str(v) for v in r)
    _, statement, params = driver.transpile(model, query, lexicon, emitter)
    want = sorted(row(r) for r in conn.execute(statement, params).fetchall())
    # `driver.normalise`, not `to_conquer` on the block: a query may define things for its
    # own duration (§11) and the normal form has to carry those, or it is not a query
    text = driver.normalise(model, query, lexicon)
    try:
        _, statement2, params2 = driver.transpile(model, text, lexicon, emitter)
    except (parser_mod.ParseError, sql_mod.SqlError) as e:
        return False, "normalised form does not compile: %s\n        %s" % (e, text)
    got = sorted(row(r) for r in conn.execute(statement2, params2).fetchall())
    if got != want:
        return False, "normalised form gives %d rows, original %d\n        %s" % (
            len(got), len(want), text)
    again = driver.normalise(model, text, lexicon)
    if again != text:
        return False, "not a fixed point:\n        %s\n        %s" % (text, again)
    return True, text


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
    model = json.load(open(args.model))
    conn = sqlite3.connect(args.db)
    lexicon = parser_mod.Lexicon(model)
    emitter = sql_mod.Emitter(model)

    passed = total = 0

    # -- the form ---------------------------------------------------------------------
    for name, query, (kind, arg) in FORM:
        if args.only and args.only.lower() not in name.lower():
            continue
        total += 1
        try:
            text = normalise(model, lexicon, query)
        except Exception as e:                                  # noqa: BLE001
            print("FAIL  %s\n        %s\n        %s: %s" % (name, query, type(e).__name__, e))
            continue
        ok = {"gives": text == arg, "has": arg in text, "lacks": arg not in text}[kind]
        passed += ok
        if ok:
            print("ok    %-70s %s" % (name[:70], text if args.verbose else ""))
        else:
            print("FAIL  %s\n        %s\n        got:  %s\n        want: %s %s"
                  % (name, query, text, kind, arg))

    # -- the round trip, over the whole operator suite -------------------------------------
    for name, query, (kind, _) in test_operators.CASES:
        if kind in ("refuses", "ambiguous"):
            continue
        if args.only and args.only.lower() not in name.lower():
            continue
        total += 1
        try:
            ok, detail = round_trip(model, conn, lexicon, emitter, query)
        except (parser_mod.ParseError, sql_mod.SqlError, sqlite3.Error):
            total -= 1                     # the original does not run here: not this test's
            continue
        passed += ok
        if ok:
            print("ok    round trip: %-58s %s" % (name[:58], detail if args.verbose else ""))
        else:
            print("FAIL  round trip: %s\n        %s\n        %s" % (name, query, detail))

    print("\n%d passed, %d failed, %d total" % (passed, total - passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
