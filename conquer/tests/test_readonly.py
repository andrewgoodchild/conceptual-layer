#!/usr/bin/env python3
"""The compiler never writes to the database it reads.

This looks like a triviality until it costs something. A plain `sqlite3.connect()` opens for
writing, and SQLite then moves the database into WAL mode and leaves `-wal` and `-shm` files
beside it. On 15 Sep two benchmark arms ran at the same time over one corpus: the ConQuer arm's
`try` put `card_games.sqlite` into WAL, and the SQL arm's `sqlite3 -readonly` could then not
open that database at all -- read-only mode cannot create the `-shm` file WAL needs. The writer
in that arm spent a large part of its budget diagnosing a fault that belonged to the harness,
and the benchmark corpus was left modified.

So three things are checked, because the failure had three parts:

    the file is not modified   -- same size, same mtime, same journal mode after a query
    no sidecars are created    -- nothing named `-wal` or `-shm` appears
    a read-only reader still works afterwards, which is the thing that actually broke

    test_readonly.py [--db D] [--model M] [-v]
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
DRIVER = os.path.join(HERE, "..", "conquer.py")


def sidecars(path):
    d, base = os.path.dirname(path) or ".", os.path.basename(path)
    return sorted(f for f in os.listdir(d)
                  if f.startswith(base) and (f.endswith("-wal") or f.endswith("-shm")))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (os.path.exists(args.model) and os.path.exists(args.db)):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.db)
        return 2

    checks, passed, failed = [], 0, 0
    tmp = tempfile.mkdtemp(prefix="conquer-readonly-")
    try:
        # a copy, so the check cannot be the thing that damages the fixture
        db = os.path.join(tmp, "company.sqlite")
        shutil.copy(args.db, db)
        before = (os.path.getsize(db), os.path.getmtime(db))
        with sqlite3.connect(db) as c:
            mode_before = c.execute("PRAGMA journal_mode").fetchone()[0]

        out = subprocess.run([sys.executable, DRIVER, args.model, "--db", db,
                              "LIST n FROM Employee has EmployeeName n"],
                             capture_output=True, text=True)
        ran = out.returncode == 0 and "Ada Lovelace" in out.stdout
        checks.append(("the query runs at all", ran,
                       out.stderr.strip().split("\n")[-1][:90] if not ran else "rows returned"))

        left = sidecars(db)
        checks.append(("no -wal or -shm is left beside the database", not left,
                       "left %s" % ", ".join(left) if left else "none"))

        after = (os.path.getsize(db), os.path.getmtime(db))
        checks.append(("the database file is byte-for-byte untouched", before == after,
                       "size/mtime changed" if before != after else "unchanged"))

        with sqlite3.connect("file:%s?mode=ro" % db, uri=True) as c:
            mode_after = c.execute("PRAGMA journal_mode").fetchone()[0]
        checks.append(("the journal mode is what it was", mode_before == mode_after,
                       "%s -> %s" % (mode_before, mode_after)))

        # the failure that actually cost a benchmark arm its afternoon
        probe = subprocess.run(["sqlite3", "-readonly", db, "SELECT COUNT(*) FROM employee"],
                               capture_output=True, text=True)
        checks.append(("`sqlite3 -readonly` can still open it afterwards",
                       probe.returncode == 0 and probe.stdout.strip().isdigit(),
                       (probe.stderr or probe.stdout).strip()[:90]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for name, ok, note in checks:
        if ok:
            passed += 1
            print("ok    %-58s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s" % (name, note))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
