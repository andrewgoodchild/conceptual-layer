#!/usr/bin/env python3
"""Run ConQuer queries against a reference SQL query and compare the results.

A case file is a sequence of blocks:

    === a name for the case
    --- conquer
    <ConQuer-92 query text, one or more lines>
    --- sql
    <reference SQL, one or more lines>

Both sides are run against the same database and the rows compared as multisets, so column
order and row order do not matter but duplicates do. This is a correctness test, not a smoke
test: the reference SQL comes from published exercise sets, so a pass means the transpiler
produced the same answer a human did.

    compare.py MODEL.ccm.json DB.sqlite cases/chinook.cases [-v]
"""

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402


def load_cases(path):
    cases, name, section, buf = [], None, None, {"conquer": [], "sql": []}
    def flush():
        if name:
            cases.append({"name": name,
                          "conquer": "\n".join(buf["conquer"]).strip(),
                          "sql": "\n".join(buf["sql"]).strip()})
    for raw in open(path):
        line = raw.rstrip("\n")
        if line.startswith("==="):
            flush()
            name, section = line[3:].strip(), None
            buf = {"conquer": [], "sql": []}
        elif line.startswith("--- "):
            section = line[4:].strip()
        elif section in buf:
            buf[section].append(line)
    flush()
    return cases


def as_multiset(rows):
    """Normalise for comparison: stringify, keep column order, sort the rows.

    Row order does not matter (neither side promises one unless ORDERED is used) but column
    order does, and so do duplicates. Sorting the values *within* a row would make the suite
    blind to a transposition -- projecting the artist where the track name belongs would still
    compare equal. So a ConQuer LIST must name its columns in the reference query's order.
    """
    return sorted(tuple("" if v is None else str(v) for v in r) for r in rows)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("model")
    p.add_argument("db")
    p.add_argument("cases")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--only", help="run only cases whose name contains this")
    p.add_argument("--slow", action="store_true",
                   help="also run cases marked SLOW (correlated aggregates over large "
                        "unindexed tables; the reference SQL is just as slow)")
    args = p.parse_args(argv)

    model = json.load(open(args.model))
    conn = sqlite3.connect(args.db)
    lexicon = parser_mod.Lexicon(model)      # built once, not once per case
    emitter = sql_mod.Emitter(model)

    cases = load_cases(args.cases)
    if args.only:
        cases = [c for c in cases if args.only.lower() in c["name"].lower()]
    skipped = 0
    if not args.slow and not args.only:
        before = len(cases)
        cases = [c for c in cases if not c["name"].startswith("SLOW")]
        skipped = before - len(cases)

    passed = failed = 0
    for case in cases:
        label = case["name"]
        try:
            _, statement, params = driver.transpile(model, case["conquer"], lexicon, emitter)
        except (parser_mod.ParseError, sql_mod.SqlError) as e:
            print("FAIL  %s\n        %s: %s" % (label, type(e).__name__, e))
            failed += 1
            continue
        try:
            got = as_multiset(conn.execute(statement, params).fetchall())
        except sqlite3.Error as e:
            print("FAIL  %s\n        SQL error: %s\n        %s" % (label, e, statement))
            failed += 1
            continue
        try:
            want = as_multiset(conn.execute(case["sql"]).fetchall())
        except sqlite3.Error as e:
            print("FAIL  %s\n        reference SQL error: %s" % (label, e))
            failed += 1
            continue

        if got == want:
            passed += 1
            print("ok    %s  (%d rows)" % (label, len(got)))
            if args.verbose:
                print("        %s" % statement)
        else:
            failed += 1
            print("FAIL  %s\n        got %d rows, reference gives %d"
                  % (label, len(got), len(want)))
            print("        generated: %s" % statement)
            if params:
                print("        params: %r" % (params,))
            # Membership against a set: `r not in want` over a 25k-row list turned a failure
            # report into a hang.
            want_set, got_set = set(want), set(got)
            only_got = [r for r in got if r not in want_set][:3]
            only_want = [r for r in want if r not in got_set][:3]
            if only_got:
                print("        only in ours:     %r" % (only_got,))
            if only_want:
                print("        only in reference: %r" % (only_want,))

    print("\n%d passed, %d failed, %d total%s"
          % (passed, failed, len(cases),
             ", %d skipped as slow (use --slow)" % skipped if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
