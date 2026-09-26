#!/usr/bin/env python3
"""Build the company fixture as a DuckDB database for the Malloy probe.

    python3 bench/malloy-probe/build.py [out.duckdb]

Foreign keys are dropped (DuckDB checks them eagerly and the fixture's rows reference later
ones) and `audit_log` is skipped (`at` is reserved). Neither matters: the probe is about
aggregate semantics over the same data the compiler's own tests use.
"""
import os
import re
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "reverse", "tests", "company.sql")


def main(out=None):
    out = out or os.path.join(HERE, "company.duckdb")
    if os.path.exists(out):
        os.remove(out)
    con = duckdb.connect(out)
    for stmt in [s.strip() for s in open(SRC).read().split(";") if s.strip()]:
        if "audit_log" in stmt:
            continue
        stmt = re.sub(r"\b(VARCHAR|CHAR)\(\d+\)", "VARCHAR", stmt)
        stmt = re.sub(r"\s*REFERENCES\s+\w+\s*\([^)]*\)", "", stmt)
        try:
            con.execute(stmt)
        except Exception as e:                                        # noqa: BLE001
            print("skipped: %s" % str(e).split("\n")[0][:70], file=sys.stderr)
    print("built %s: %s" % (out, con.execute(
        "SELECT (SELECT COUNT(*) FROM department), (SELECT COUNT(*) FROM employee), "
        "(SELECT COUNT(*) FROM assignment)").fetchall()[0]))
    con.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
