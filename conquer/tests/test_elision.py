#!/usr/bin/env python3
"""Join elimination: which joins the compiler drops when the mapping says a reference holds.

A path step across a reference emits a join, and that join does two separate jobs. It
*fetches* the far row, and it *filters* the near row out when no far row is there. Where the
reference holds over every row the filtering is dead weight; where the step only wants a
value the near side is already standing on -- `Employee has Department has DepartmentCode`,
where the code IS the column the employee points with -- the fetching is dead weight too.
Malloy eliminates both by construction. What lets this compiler do it is `enforced` in the
roleMap, which the reverse engineer sets only after running the query that proves it.

A quarter of the inner joins in the recorded query corpus are one of those two.

The gate is the whole test. SQLite does not enforce a declared foreign key, so a declared
key is not evidence: 28% of the declared single-column keys in a 90-database Spider sample
are contradicted by their own rows, and across a *dangling* reference the filtering job is
real and dropping it changes the answer. The last two cases here build exactly that database
and prove both halves -- that the reverse engineer refuses to mark it, and that marking it
anyway would move rows. Without them every case above would still pass with the gate
deleted.

    test_elision.py [-v] [--only SUBSTRING]
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "reverse"))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402
import catalog as catalog_mod     # noqa: E402
import population as population_mod   # noqa: E402


# -- expectations --------------------------------------------------------------------------

def elides(joins, probes=0):
    """The enforced model emits `joins` fewer inner joins and `probes` fewer existence
    subqueries than the plain one, and returns exactly the same rows."""
    return ("elides", joins, probes)


def keeps(why):
    """One of the three conditions does not hold, so the statement must not change at all."""
    return ("keeps", why, None)


CASES = [
    # -- the fetching job: the value asked for is the column in hand ------------------------
    ("reading a department's code walks to no department",
     "LIST n, c FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode c",
     elides(1)),

    ("filtering on the code leaves an existence probe with nothing left in it",
     "LIST n FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode: 'ENG'",
     elides(0, probes=1)),

    ("a self-reference elides too: the manager's number is the column pointing at them",
     "LIST n, m FROM Employee has EmployeeName n AND ALSO has manager Employee has EmployeeNr m",
     elides(1)),

    ("two steps, and only the one that fetches nothing new goes",
     "LIST n, p FROM Employee has EmployeeName n AND ALSO has Project has ProjectCode p",
     elides(1)),

    # -- the filtering job: the referent is known to be there -------------------------------
    ("asserting a department exists needs no department",
     "LIST n FROM Employee has EmployeeName n AND ALSO has Department",
     elides(0, probes=1)),

    ("two assertions at once: one probe empties, the other keeps the step that fans",
     "LIST n FROM Employee has EmployeeName n AND ALSO has Department AND ALSO has Project",
     elides(1, probes=1)),

    # -- what must NOT elide ----------------------------------------------------------------
    ("a fact type with a role of its own still joins: the name is only over there",
     "LIST n, d FROM Employee has EmployeeName n AND ALSO has Department has DepartmentName d",
     keeps("DepartmentHasName maps a column the near side does not hold")),

    ("a budget is not a key either",
     "LIST n, b FROM Employee has EmployeeName n AND ALSO has Department has DepartmentBudget b",
     keeps("DepartmentHasBudget maps a column the near side does not hold")),

    ("walking the other way is not functional, so the join stands",
     "LIST c, n FROM Department has DepartmentCode c AND ALSO is of Employee has EmployeeName n",
     keeps("entering by a role that is not the fact type's identifier can multiply rows")),

    ("an optional step keeps its outer join",
     "LIST n, c FROM Employee has EmployeeName n AND ALSO OPTIONALLY has Department "
     "has DepartmentCode c",
     keeps("a LEFT JOIN that is dropped changes what an absent row projects")),
]


# -- the harness ----------------------------------------------------------------------------

def enforce(model, sqlite_path):
    """A copy of `model` with the references this database upholds marked, by the same code
    path `reverse.py --infer-enforced` runs. Never by hand: a test that sets the flag itself
    would pass with the reverse engineer's half of this deleted."""
    out = json.loads(json.dumps(model))
    conn = sqlite3.connect("file:%s?mode=ro" % sqlite_path, uri=True)
    cat = catalog_mod.from_sqlite(sqlite_path)
    live = [t for t in cat.tables if not t.is_view]
    analysis = population_mod.Analysis()
    analysis.row_counts = {
        t.name: conn.execute('SELECT COUNT(*) FROM "%s"' % t.name).fetchone()[0] for t in live}
    population_mod._violations(conn, live, analysis)
    conn.close()

    class Silent:
        def refine(self, *a):
            pass

    applied = population_mod.apply_enforced(analysis, out, Silent())
    return out, applied


def compile_with(model, query):
    lexicon, emitter = parser_mod.Lexicon(model), sql_mod.Emitter(model)
    _, statement, params = driver.transpile(model, query, lexicon, emitter)
    return statement, params


def rows(conn, statement, params):
    return sorted(tuple(str(v) for v in r) for r in conn.execute(statement, params).fetchall())


def run(plain, strong, conn, query, expect, verbose):
    kind, a, b = expect
    try:
        base_sql, base_p = compile_with(plain, query)
        strong_sql, strong_p = compile_with(strong, query)
    except Exception as e:                                          # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)

    if kind == "keeps":
        if base_sql != strong_sql:
            return False, "the statement changed, and should not have (%s):\n        %s" % (
                a, strong_sql)
        return True, a

    dropped = base_sql.count(" JOIN ") - strong_sql.count(" JOIN ")
    probes = base_sql.count("EXISTS (SELECT 1 FROM") - strong_sql.count("EXISTS (SELECT 1 FROM")
    if dropped != a or probes != b:
        return False, ("dropped %d join(s) and %d probe(s), expected %d and %d:\n"
                       "        was %s\n        now %s" % (dropped, probes, a, b,
                                                           base_sql, strong_sql))
    got, want = rows(conn, strong_sql, strong_p), rows(conn, base_sql, base_p)
    if got != want:
        return False, "the answer moved: %s, was %s" % (got[:3], want[:3])
    if not want:
        return False, ("this query returns nothing, so equal answers prove nothing about "
                       "the join that was dropped")
    return True, "-%d join(s), -%d probe(s), %d rows either way" % (a, b, len(want))


# -- the gate: a reference the data does not uphold -----------------------------------------

def dangling(model, sqlite_path):
    """Copy the fixture, point one employee at a department that is not there, and check both
    halves of the gate."""
    tmp = tempfile.mkdtemp()
    try:
        broken = os.path.join(tmp, "company.sqlite")
        shutil.copy(sqlite_path, broken)
        conn = sqlite3.connect(broken)
        conn.execute("INSERT INTO employee (emp_nr, emp_name, hired, dept_code) "
                     "VALUES (999, 'Nobody', '2020-01-01', 'GHOST')")
        conn.commit()
        conn.close()

        results = []
        _, applied = enforce(model, broken)
        marked = {a[0] + "." + a[1] for a in applied}
        if "employee.dept_code" in marked:
            results.append((False, "the reverse engineer marked a reference the data breaks",
                            "a dangling reference is marked enforced"))
        else:
            results.append((True, "employee.dept_code -> department is not marked; %d other "
                            "reference(s) still are" % len(applied),
                            "a dangling reference is not marked enforced"))

        # ...and it matters. Mark it anyway and the answer moves, which is what makes every
        # case above a test of the gate rather than a test of the rewrite.
        forced = json.loads(json.dumps(model))
        for entry in forced["mapping"]["roleMap"]:
            if entry["role"] == "r.EmployeeHasDepartment.department":
                entry["enforced"] = True
        conn = sqlite3.connect("file:%s?mode=ro" % broken, uri=True)
        q = "LIST n, c FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode c"
        honest = rows(conn, *compile_with(model, q))
        wrong = rows(conn, *compile_with(forced, q))
        conn.close()
        if honest == wrong:
            results.append((False, "marking it made no difference, so these cases prove "
                            "nothing about the gate", "eliding a dangling reference is wrong"))
        else:
            results.append((True, "%d rows honestly, %d with the join elided"
                            % (len(honest), len(wrong)),
                            "eliding a dangling reference is wrong"))
        return results
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def through_the_cli(sqlite_path):
    """`reverse.py --infer-enforced` has to reach `apply_enforced`, which is three edits away
    from it and testable no other way: every case above calls the library directly."""
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "..", "..", "reverse", "reverse.py"),
             sqlite_path, "-o", tmp, "-n", "company", "--infer-enforced"],
            capture_output=True, text=True)
        path = os.path.join(tmp, "company.ccm.json")
        if not os.path.exists(path):
            return False, "reverse.py wrote no model: %s" % (r.stderr.strip()[:200] or r.stdout)
        built = json.load(open(path))
        marked = sorted(e["role"] for e in built["mapping"]["roleMap"] if e.get("enforced"))
        if not marked:
            return False, "the flag reached nothing: no role came back enforced"
        return True, ", ".join(marked)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (os.path.exists(args.model) and os.path.exists(args.db)):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.db)
        return 2

    plain = json.load(open(args.model))
    strong, applied = enforce(plain, args.db)
    conn = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)

    passed = failed = 0
    if not applied:
        print("FAIL  the reverse engineer marked no reference enforced, so nothing below "
              "tests anything")
        return 1
    print("ok    %-62s %s" % ("the fixture's upheld references are marked",
                              ", ".join("%s.%s" % (a[0], a[1]) for a in applied)))
    passed += 1

    cases = [c for c in CASES if not args.only or args.only.lower() in c[0].lower()]
    for name, query, expect in cases:
        ok, note = run(plain, strong, conn, query, expect, args.verbose)
        if ok:
            passed += 1
            print("ok    %-62s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s\n        %s" % (name, query, note))

    if not args.only:
        ok, note = through_the_cli(args.db)
        if ok:
            passed += 1
            print("ok    %-62s %s" % ("--infer-enforced reaches the model",
                                      note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  --infer-enforced reaches the model\n        %s" % note)
        for ok, note, name in dangling(plain, args.db):
            if ok:
                passed += 1
                print("ok    %-62s %s" % (name, note if args.verbose else ""))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, note))

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
