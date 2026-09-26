#!/usr/bin/env python3
"""Do the paths rule 12 derived actually reach a value in the real documents?

The rule was fed `fields_meaning`, which is metadata somebody wrote by hand. Whether it
matches the documents is a separate question, and the schema dumps answer it: each carries
three real rows per table. Those rows go into SQLite, the emitted `json_extract` runs against
them, and a path that reaches nothing is either a wrong declaration or a wrong derivation.

This is the only part of the LiveSQLBench work that executes anything. It is three rows per
table, so a path that misses here is certainly wrong while a path that hits is only probably
right -- the PostgreSQL dumps are what would settle it.

    execute_probe.py [--db NAME] [-v]
"""

import argparse
import ast
import collections
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "data")
WORK = os.path.join(HERE, "work", "models")
sys.path.insert(0, os.path.join(ROOT, "conquer"))
sys.path.insert(0, HERE)

import sql as sql_mod             # noqa: E402
import catalogue                  # noqa: E402

DOC = re.compile(r"(\{.*\})")


def samples(db):
    """{(table, column): [document, ...]} from the dump's `First 3 rows` blocks.

    The blocks are fixed-width text, so a document is found by its braces rather than by
    column position: good enough to tell a path that resolves from one that does not.
    """
    out = collections.defaultdict(list)
    table = None
    for line in open(os.path.join(DATA, db, "%s_schema.txt" % db)):
        m = re.match(r'^CREATE TABLE\s+"?(\w+)"?', line)
        if m:
            table = m.group(1)
            continue
        m = DOC.search(line)
        if table and m:
            raw = m.group(1)
            for parse in (json.loads, ast.literal_eval):
                try:
                    doc = parse(raw)
                except Exception:                                      # noqa: BLE001
                    continue
                if isinstance(doc, dict):
                    out[table].append(doc)
                break
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    dbs = sorted(d for d in os.listdir(DATA) if os.path.isdir(os.path.join(DATA, d)))
    if args.db:
        dbs = [d for d in dbs if args.db in d]

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE d (doc TEXT)")
    print("%-34s %8s %8s %8s   %s" % ("database", "paths", "tried", "resolved", "rate"))
    print("-" * 74)
    tot = collections.Counter()
    misses = []
    for db in dbs:
        declared = catalogue.json_fields(os.path.join(DATA, db), db)
        docs = samples(db)
        em = sql_mod.Emitter(json.load(open(os.path.join(WORK, "%s.ccm.json" % db))))
        got = collections.Counter()
        for key, fields in declared.items():
            table, column = key.split("|", 1)
            here = docs.get(table) or []
            for f in fields:
                got["paths"] += 1
                if not here:
                    continue
                # The same expression the emitter would put in a statement.
                expr = em.json_path('d."doc"', f["path"], {}, key)
                hit = False
                for doc in here:
                    conn.execute("DELETE FROM d")
                    conn.execute("INSERT INTO d VALUES (?)", (json.dumps(doc),))
                    try:
                        if conn.execute("SELECT %s FROM d" % expr).fetchone()[0] is not None:
                            hit = True
                            break
                    except sqlite3.Error:
                        break
                got["tried"] += 1
                got["resolved"] += hit
                if not hit and len(misses) < 15:
                    misses.append((db, table, column, ".".join(f["path"])))
        rate = 100.0 * got["resolved"] / got["tried"] if got["tried"] else 0.0
        print("%-34s %8d %8d %8d   %.0f%%" % (
            db[:34], got["paths"], got["tried"], got["resolved"], rate))
        tot.update(got)
    print("-" * 74)
    print("%-34s %8d %8d %8d   %.0f%%" % (
        "total", tot["paths"], tot["tried"], tot["resolved"],
        100.0 * tot["resolved"] / max(tot["tried"], 1)))
    print("\n%d declared path(s) had no sample document to test against."
          % (tot["paths"] - tot["tried"]))
    if misses and args.verbose:
        print("\ndeclared but not found in any sample row:")
        for db, t, c, path in misses:
            print("   %-28s %s.%s -> %s" % (db.replace("_large", ""), t, c, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
