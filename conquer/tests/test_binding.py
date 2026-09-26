#!/usr/bin/env python3
"""A model is bound to one physical schema, and the binding is checked rather than assumed.

`conquer.py MODEL --db DB` used to trust that the two were about the same database. A name that
does not exist fails loudly enough on its own; the dangerous case is a *partially* overlapping
schema -- the same model against last quarter's extract, or one of two databases that share
half their tables -- which runs and returns wrong rows. The mapping names bare tables and has
no notion of a source, so nothing else can catch it.

    test_binding.py [--model M] [--db D] [-v]
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
DRIVER = os.path.join(HERE, "..", "conquer.py")
sys.path.insert(0, os.path.join(HERE, ".."))

import conquer as driver          # noqa: E402


def run(model, db, query="THE COUNT OF Employee"):
    return subprocess.run([sys.executable, DRIVER, model, "--db", db, query],
                          capture_output=True, text=True)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (os.path.exists(args.model) and os.path.exists(args.db)):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.db)
        return 2

    model = json.load(open(args.model))
    checks, tmp = [], tempfile.mkdtemp(prefix="conquer-binding-")
    try:
        out = run(args.model, args.db)
        checks.append(("the right database is accepted", out.returncode == 0,
                       out.stderr.strip()[:80] or "ran"))

        # a database with none of the model's tables
        other = os.path.join(tmp, "other.sqlite")
        with sqlite3.connect(other) as c:
            c.execute("CREATE TABLE atom (atom_id TEXT, element TEXT)")
        out = run(args.model, other)
        checks.append(("a different database is refused, by name", out.returncode == 2
                       and "does not describe this database" in out.stderr,
                       out.stderr.strip().split("\n")[0][:80]))

        # the dangerous one: half the model's tables are here, half are not
        half = os.path.join(tmp, "half.sqlite")
        names = [t["name"] for t in model["mapping"]["tables"] if not t.get("derived")]
        with sqlite3.connect(half) as c:
            for name in names[:len(names) // 2]:
                c.execute('CREATE TABLE "%s" (x)' % name)
        out = run(args.model, half)
        checks.append(("a partially overlapping schema is refused too",
                       out.returncode == 2, out.stderr.strip().split("\n")[0][:80]))

        with sqlite3.connect("file:%s?mode=ro" % args.db, uri=True) as c:
            checks.append(("the fixture itself has no unmapped tables",
                           driver.unmapped_tables(model, c) == [],
                           str(driver.unmapped_tables(model, c))[:60]))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    passed = failed = 0
    for name, ok, note in checks:
        if ok:
            passed += 1
            print("ok    %-56s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s" % (name, note))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
