#!/usr/bin/env python3
"""Does a query against a value recovered from a document actually compile, at this scale?

`conquer/tests/test_json.py` proves the path end to end on a fixture of three rows. This asks
the harder question: over 18 industrial schemas, 971 tables and 1,683 fact types that rule 12
recovered from inside jsonb columns, does every one of them compile to SQL -- and does the SQL
carry the path rather than the whole document?

It does not execute anything. The public release ships no database, so nothing here is an
answer; it is a compilation and emission check over every derived fact type, which is what can
be established without the PostgreSQL dumps.

    json_probe.py [--db NAME] [-v]
"""

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(HERE, "work", "models")
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402


def path_roles(model):
    """Every (fact type, value role) whose value lives at a path inside a document."""
    paths = {c["id"] for c in model["mapping"]["columns"] if c.get("path")}
    by_role = {}
    for e in model["mapping"]["roleMap"]:
        if any(c in paths for c in e["columns"]):
            by_role[e["role"]] = True
    out = []
    for c in model["concepts"]:
        if c.get("kind") != "fact":
            continue
        for r in c["roles"]:
            if r["id"] in by_role:
                out.append((c, r))
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    files = sorted(f for f in os.listdir(WORK)
                   if f.endswith(".ccm.json") and "-nojson" not in f)
    if args.db:
        files = [f for f in files if args.db in f]

    print("%-34s %8s %8s %8s %8s" % ("database", "derived", "compiled", "pathed", "failed"))
    print("-" * 72)
    tot = collections.Counter()
    failures = []
    for f in files:
        model = json.load(open(os.path.join(WORK, f)))
        lex, em = parser_mod.Lexicon(model), sql_mod.Emitter(model)
        got = collections.Counter()
        for ft, role in path_roles(model):
            entity = next((r["player"] for r in ft["roles"] if r["id"] != role["id"]), None)
            ename = next((c["name"] for c in model["concepts"] if c["id"] == entity), None)
            vname = next((c["name"] for c in model["concepts"]
                          if c["id"] == role["player"]), None)
            if not (ename and vname):
                continue
            got["derived"] += 1
            query = "LIST v FROM %s has %s v" % (ename, vname)
            try:
                _, sql, _ = driver.transpile(model, query, lex, em)
            except Exception as e:                                      # noqa: BLE001
                got["failed"] += 1
                if len(failures) < 12:
                    failures.append((f[:-9], query, "%s: %s" % (type(e).__name__, str(e)[:90])))
                continue
            got["compiled"] += 1
            if "json_extract(" in sql:
                got["pathed"] += 1
            elif len(failures) < 12:
                failures.append((f[:-9], query, "compiled without a path read: %s" % sql[:90]))
        print("%-34s %8d %8d %8d %8d" % (
            f[:-9][:34], got["derived"], got["compiled"], got["pathed"], got["failed"]))
        tot.update(got)
    print("-" * 72)
    print("%-34s %8d %8d %8d %8d" % (
        "total", tot["derived"], tot["compiled"], tot["pathed"], tot["failed"]))
    if failures:
        print("\nfailures:")
        for db, q, why in failures:
            print("   %-24s %-52s %s" % (db, q[:52], why))
    return 1 if tot["failed"] or tot["pathed"] != tot["derived"] else 0


if __name__ == "__main__":
    sys.exit(main())
