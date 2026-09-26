#!/usr/bin/env python3
"""A constraint carrying a `violation` query, run against the data.

Report §1 says the language serves two purposes -- a query facility, and "the specification of
derivation rules and constraints" in the modelling tool. A derivation rule has carried its
ConQuer in `source` since the beginning; a constraint had nowhere to put any, so the second
purpose was unimplemented (`model/model.md` §2.4 used to record that as a limitation).

`violation` is ConQuer whose result must be empty: the rows it returns are the counter-examples.
One text answers both questions, which is the shape Rel's integrity constraints take -- `ic X()
requires ...` asks whether it holds and `ic X(x) requires ...` hands back the x that break it
(Aref et al., arXiv:2504.10323 §3.5). Here emptiness is the first question and the rows are the
second, so nothing is written twice.

    test_constraints.py [--model M] [--db D] [-v]
"""

import argparse
import copy
import io
import json
import os
import sqlite3
import sys
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import conquer as driver              # noqa: E402
from model import validate             # noqa: E402

# (name, kind, violation query, expected failures, a phrase the output must carry)
CASES = [
 ("a constraint the population satisfies", "valueComparison",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s < 0",
  0, "holds"),

 ("a ring constraint nobody violates", "ring",
  "LIST n FROM Employee e has EmployeeName n AND ALSO has manager Employee e",
  0, "holds"),

 # The counter-examples are the point: a worklist entry a modeller can act on beats a
 # boolean, and it is the same query either way.
 ("a constraint the population breaks names who broke it", "mandatory",
  "LIST n FROM Employee has EmployeeName n BUT NOT has Assignment",
  1, "Betty Holberton"),

 ("and says how many", "mandatory",
  "LIST n FROM Employee has EmployeeName n BUT NOT has ManagerCarSpace",
  1, "counter-example"),

 # A constraint that does not compile is a defect in the model, not a violation of it, and
 # the two must not read alike.
 ("a violation query that does not compile is BROKEN, not FAILS", "uniqueness",
  "LIST n FROM Employee has NoSuchThing n",
  1, "BROKEN"),
]


def run(model, conn, case):
    name, kind, violation, want_failed, phrase = case
    m = copy.deepcopy(model)
    m.setdefault("constraints", []).append(
        {"id": "ic.test", "name": "the constraint under test", "kind": kind,
         "violation": violation})
    out = io.StringIO()
    with redirect_stdout(out):
        failed = driver.check_constraints(m, conn)
    text = out.getvalue()
    if failed != want_failed:
        return False, "expected %d failed, got %d: %s" % (want_failed, failed, text.strip()[:90])
    if phrase not in text:
        return False, "expected %r in the output, got: %s" % (phrase, text.strip()[:90])
    return True, text.strip().split("\n")[0][:70]


def schema_accepts_violation(model, conn):
    """The field has to be in the JSON Schema, or a model carrying one fails validation."""
    m = copy.deepcopy(model)
    m.setdefault("constraints", []).append(
        {"id": "ic.schema", "kind": "mandatory", "violation": "Employee has EmployeeName"})
    path = os.path.join(WORK, ".constraint-schema-check.ccm.json")
    json.dump(m, open(path, "w"))
    try:
        schema = json.load(open(os.path.join(HERE, "..", "..", "model", "ccm.schema.json")))
        findings = validate.validate(path, schema)
        return (not findings.errors), ("accepted" if not findings.errors
                                       else "%s" % findings.errors[:1])
    finally:
        os.remove(path)


def no_constraints_is_not_a_failure(model, conn):
    m = copy.deepcopy(model)
    m["constraints"] = [c for c in m.get("constraints", []) if not c.get("violation")]
    out = io.StringIO()
    with redirect_stdout(out):
        failed = driver.check_constraints(m, conn)
    return (failed == 0 and "no constraint" in out.getvalue()), out.getvalue().strip()[:60]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not os.path.exists(args.model) or not os.path.exists(args.db):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2

    model = json.load(open(args.model))
    conn = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    passed = failed = 0
    checks = [(c[0], lambda c=c: run(model, conn, c)) for c in CASES]
    checks.append(("the JSON Schema accepts a constraint's violation query",
                   lambda: schema_accepts_violation(model, conn)))
    checks.append(("a model with no violation queries is not a failure",
                   lambda: no_constraints_is_not_a_failure(model, conn)))
    try:
        for name, fn in checks:
            ok, note = fn()
            if ok:
                passed += 1
                print("ok    %-58s %s" % (name, note if args.verbose else ""))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, note))
    finally:
        conn.close()
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
