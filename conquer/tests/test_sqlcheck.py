#!/usr/bin/env python3
"""The SQL checker: what an agent's own joins do to its aggregates, read off the model.

Every case is SQL a writer might send to `run_sql`, the findings it must get (by kind), and
-- where the finding is a claim about the answer -- the SQL that answers the question, run
against the fixture. A fan trap the checker reports must give a different answer from the
query that avoids it on these rows, and a query it passes must give the same one: a finding
that changes nothing would be noise, and a pass that hides a wrong number is the failure this
exists to catch.

Skips, saying so, when `sqlglot` is not installed: the checker is optional, like the server.

    test_sqlcheck.py [--model M] [--db DB] [-v]
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))

import sqlcheck                      # noqa: E402

# (name, sql, kinds it must report, a phrase one of them must contain, the right SQL or None)
CASES = [
 ("a sum over the one side of a one-to-many join is a fan trap",
  "SELECT d.dept_name, SUM(d.budget) FROM department d "
  "JOIN employee e ON e.dept_code = d.dept_code GROUP BY d.dept_name",
  {"fan trap"}, "once per matching e (employee)",
  "SELECT d.dept_name, SUM(d.budget) FROM department d GROUP BY d.dept_name"),

 ("a sum over the many side is not",
  "SELECT d.dept_name, SUM(e.salary) FROM department d "
  "JOIN employee e ON e.dept_code = d.dept_code GROUP BY d.dept_name",
  set(), None, None),

 ("an association multiplies the entity it hangs off",
  "SELECT SUM(e.salary) FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr",
  {"fan trap"}, "not make unique in assignment",
  "SELECT SUM(salary) FROM employee WHERE emp_nr IN (SELECT emp_nr FROM assignment)"),

 # A literal on the rest of the key makes the far side one row: the model's composite key
 # (emp_nr, proj_code) is covered by the join column and the filter together.
 ("a filter that completes the far side's key removes the fan",
  "SELECT SUM(e.salary) FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr "
  "WHERE a.proj_code = 'APOLLO'",
  set(), None, None),

 ("a COUNT over the multiplied side counts joined rows",
  "SELECT COUNT(d.dept_name) FROM department d JOIN employee e ON e.dept_code = d.dept_code",
  {"fan trap"}, "COUNT(DISTINCT",
  "SELECT COUNT(*) FROM department WHERE dept_code IN (SELECT dept_code FROM employee)"),

 # BIRD's gold writes `COUNT(T1.account_id)` over account JOIN loan to count loans, and it
 # does: the join column holds the same value on both sides, and on loan's side it is
 # counted once per loan.
 ("a COUNT of the join column counts the side it is not multiplied on",
  "SELECT COUNT(d.dept_code) FROM department d JOIN employee e ON e.dept_code = d.dept_code",
  set(), None, None),

 ("COUNT(*) along a chain of many-to-one joins counts the chain's start",
  "SELECT COUNT(*) FROM assignment a JOIN employee e ON e.emp_nr = a.emp_nr "
  "JOIN department d ON d.dept_code = e.dept_code",
  set(), None, None),

 ("a comma join with its condition in WHERE is a join",
  "SELECT SUM(e.salary) FROM department d, employee e WHERE e.dept_code = d.dept_code",
  set(), None, None),

 ("tables with nothing between them are a cross product",
  "SELECT COUNT(*) FROM department d, project p",
  {"cross product", "fan trap"}, "nothing joins", None),

 # docs/07: 3,738 rows where the question had 623, from a join used as a filter
 ("a join used as a filter repeats the rows it filters",
  "SELECT d.dept_name FROM department d JOIN employee e ON e.dept_code = d.dept_code "
  "WHERE e.salary > 90000",
  {"repeated rows"}, "EXISTS",
  "SELECT dept_name FROM department d WHERE EXISTS "
  "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code AND e.salary > 90000)"),

 ("a many-to-one join does not repeat anything",
  "SELECT e.emp_name, d.dept_name FROM employee e JOIN department d ON d.dept_code = e.dept_code",
  set(), None, None),

 ("an IN subquery is not a join",
  "SELECT emp_name FROM employee WHERE emp_nr IN (SELECT emp_nr FROM assignment)",
  set(), None, None),

 ("a self-reference the model knows is a good join",
  "SELECT e.emp_name, m.emp_name FROM employee e LEFT JOIN employee m ON m.emp_nr = e.manager_nr",
  set(), None, None),

 ("a subtype joined to its supertype on the identifier is a good join",
  "SELECT e.emp_name, m.car_space FROM manager m JOIN employee e ON e.emp_nr = m.emp_nr",
  set(), None, None),

 ("an equality the model has no reference for, where it has another, is a join key finding",
  "SELECT e.emp_name FROM employee e JOIN department d ON d.dept_name = e.dept_code",
  {"join key"}, "d.dept_code = e.dept_code", None),

 # The usual repair for a fan trap, and wrong: two employees on 98,000 would count once.
 ("SUM(DISTINCT) is reported",
  "SELECT SUM(DISTINCT e.salary) FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr",
  {"SUM(DISTINCT)"}, "equal", None),

 ("a subquery grouped by the join column is one row per key",
  "SELECT d.dept_name, x.total FROM department d JOIN "
  "(SELECT dept_code, SUM(salary) AS total FROM employee GROUP BY dept_code) x "
  "ON x.dept_code = d.dept_code",
  set(), None, None),

 ("and a fan trap inside a subquery is still found",
  "SELECT * FROM (SELECT d.dept_code, SUM(d.budget) AS b FROM department d "
  "JOIN employee e ON e.dept_code = d.dept_code GROUP BY d.dept_code) x",
  {"fan trap"}, "SUM(d.budget)", None),

 ("a table the model does not map is opaque, not an error",
  "SELECT SUM(e.salary) FROM employee e JOIN audit_log l ON l.note = e.emp_name",
  {"fan trap"}, "audit_log", None),

 ("SQL the parser cannot read gets no findings",
  "SELEC nonsense FROM", set(), None, None),
]


def rows(conn, sql):
    return sorted(conn.execute(sql).fetchall(), key=repr)


def run(model, keys, conn, case):
    name, sql, kinds, phrase, right = case
    found = sqlcheck.check(model, sql, "sqlite", keys)
    got = {f.kind for f in found}
    if got != kinds:
        return False, "expected %s, got %s\n        %s" % (sorted(kinds), sorted(got),
                                                        sqlcheck.render(found))
    if phrase and not any(phrase in f.message or phrase in f.fix for f in found):
        return False, "no finding says %r:\n        %s" % (phrase, sqlcheck.render(found))
    if right and conn is not None:
        if rows(conn, sql) == rows(conn, right):
            return False, "the finding changes nothing on the fixture: both give %r" % (
                rows(conn, sql)[:3],)
    return True, "; ".join(f.kind for f in found)


def additivity(model):
    """A value type marked non-additive is reported when summed, and only then."""
    m = json.loads(json.dumps(model))
    for c in m["concepts"]:
        if c["name"] == "ProjectPriority":
            c["additivity"] = "nonAdditive"
    keys = sqlcheck.Keys(m)
    bad = sqlcheck.check(m, "SELECT SUM(priority) FROM project", "sqlite", keys)
    fine = sqlcheck.check(m, "SELECT AVG(priority) FROM project", "sqlite", keys)
    ok = [f.kind for f in bad] == ["additivity"] and not fine
    return ok, sqlcheck.render(bad + fine)


def semi_additive(model):
    """A level summed across the role it is a level over, and the same grouped by it."""
    m = json.loads(json.dumps(model))
    for c in m["concepts"]:
        if c["name"] == "AssignmentHours":
            c["additivity"], c["additiveExcept"] = "semiAdditive", "r.Assignment.project"
    keys = sqlcheck.Keys(m)
    bad = sqlcheck.check(m, "SELECT SUM(hours) FROM assignment", "sqlite", keys)
    fine = sqlcheck.check(m, "SELECT proj_code, SUM(hours) FROM assignment GROUP BY proj_code",
                          "sqlite", keys)
    ok = [f.kind for f in bad] == ["additivity"] and not fine
    return ok, sqlcheck.render(bad + fine)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not sqlcheck.available():
        print("skip  sqlglot not installed: the SQL checker is untested here (pip install sqlglot)")
        return 0
    if not os.path.exists(args.model):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2
    model = json.load(open(args.model))
    keys = sqlcheck.Keys(model)
    conn = sqlite3.connect(args.db) if os.path.exists(args.db) else None
    checks = [(c[0], lambda c=c: run(model, keys, conn, c)) for c in CASES]
    checks.append(("a non-additive value summed is reported", lambda: additivity(model)))
    checks.append(("a semi-additive value summed across its time role is reported",
                   lambda: semi_additive(model)))
    passed = failed = 0
    for name, fn in checks:
        ok, note = fn()
        if ok:
            passed += 1
            print("ok    %-66s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s" % (name, note))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
