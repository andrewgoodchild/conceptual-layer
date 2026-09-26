#!/usr/bin/env python3
"""What is actually in LiveSQLBench Large-v1, before spending anything on it.

The public release withholds `sol_sql`, `test_cases` and `external_knowledge`, so nothing here
can be an accuracy measurement. What it can do is establish the four things that decide whether
this benchmark is worth adopting, none of which need gold:

    scale       tables and columns per database, against BIRD's 7 and 54
    keys        whether the schemas declare primary and foreign keys -- Spider 2.0's 7,860
                tables declare none, which is why strip-and-infer could not be scored there
    reach       how much of each schema our compiler could represent at all (jsonb, arrays)
    shape       Query against Management, since the compiler emits SELECT and nothing else

    survey.py [--db NAME] [-v]
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
TASKS = os.path.join(DATA, "livesqlbench_large_v1_data.jsonl")

# A column line inside CREATE TABLE: an optionally quoted name then its type.
COL = re.compile(r'^\s*("?)([A-Za-z_][A-Za-z0-9_]*)\1\s+(.+?)(?:\s+(?:NOT\s+)?NULL)?\s*,?\s*$')
TABLE = re.compile(r'^CREATE TABLE\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\(')


def parse_schema(path):
    """Tables, their columns and types, and the keys they declare."""
    tables, cur = {}, None
    for line in open(path):
        m = TABLE.match(line)
        if m:
            cur = {"name": m.group(1), "cols": [], "pk": [], "fk": []}
            tables[m.group(1)] = cur
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith(");") or s.startswith("First 3 rows"):
            cur = None
            continue
        if s.upper().startswith("PRIMARY KEY"):
            cur["pk"] = re.findall(r'"?([A-Za-z_][A-Za-z0-9_]*)"?', s[11:])
        elif s.upper().startswith("FOREIGN KEY"):
            cur["fk"].append(s)
        elif s.upper().startswith(("UNIQUE", "CHECK", "CONSTRAINT")):
            continue
        else:
            m = COL.match(line)
            if m and m.group(2).upper() not in ("PRIMARY", "FOREIGN", "UNIQUE"):
                cur["cols"].append((m.group(2), m.group(3).strip().rstrip(",").lower()))
    return tables


def style(name):
    """Which naming convention a column was written in."""
    if name != name.lower() and name != name.upper() and "_" not in name:
        return "camelCase"
    if name == name.upper() and len(name) > 2:
        return "UPPER_CASE"
    if name != name.lower():
        return "Mixed_Case"
    return "lower_snake"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    tasks = [json.loads(l) for l in open(TASKS)]
    dbs = sorted({t["selected_database"] for t in tasks})
    if args.db:
        dbs = [d for d in dbs if args.db in d]

    print("LiveSQLBench Large-v1: %d tasks over %d databases\n" % (len(tasks), len(dbs)))

    per_db = collections.Counter(t["selected_database"] for t in tasks)
    cat = collections.Counter(t["category"] for t in tasks)
    high = collections.Counter(bool(t.get("high_level")) for t in tasks)
    conds = collections.Counter()
    for t in tasks:
        for k, v in (t.get("conditions") or {}).items():
            if v not in (False, None, -1):
                conds[k] += 1

    print("%-34s %6s %6s %6s %7s %5s %5s %6s" % (
        "database", "tasks", "tables", "cols", "cols/tb", "pk", "fk", "exotic"))
    print("-" * 82)
    tot = collections.Counter()
    styles, types, keyless = collections.Counter(), collections.Counter(), []
    for db in dbs:
        path = os.path.join(DATA, db, "%s_schema.txt" % db)
        if not os.path.exists(path):
            continue
        tabs = parse_schema(path)
        ncol = sum(len(t["cols"]) for t in tabs.values())
        npk = sum(1 for t in tabs.values() if t["pk"])
        nfk = sum(len(t["fk"]) for t in tabs.values())
        exotic = 0
        for t in tabs.values():
            for name, ty in t["cols"]:
                styles[style(name)] += 1
                types[ty.split("(")[0].strip()] += 1
                if "json" in ty or "[]" in ty or "array" in ty:
                    exotic += 1
        keyless += [t["name"] for t in tabs.values() if not t["pk"]]
        print("%-34s %6d %6d %6d %7.1f %5d %5d %6d" % (
            db, per_db[db], len(tabs), ncol, ncol / max(len(tabs), 1), npk, nfk, exotic))
        tot["tables"] += len(tabs)
        tot["cols"] += ncol
        tot["pk"] += npk
        tot["fk"] += nfk
        tot["exotic"] += exotic
    print("-" * 82)
    print("%-34s %6d %6d %6d %7.1f %5d %5d %6d" % (
        "total", len(tasks), tot["tables"], tot["cols"],
        tot["cols"] / max(tot["tables"], 1), tot["pk"], tot["fk"], tot["exotic"]))

    print("\nkeys declared:   %d of %d tables carry a primary key (%.0f%%), %d foreign keys"
          % (tot["pk"], tot["tables"], 100.0 * tot["pk"] / tot["tables"], tot["fk"]))
    print("task category:   %s" % ", ".join("%s %d" % kv for kv in cat.most_common()))
    print("high_level:      %d true, %d false" % (high[True], high[False]))
    print("grading asks:    %s" % ", ".join("%s %d" % kv for kv in conds.most_common()))
    print("\ncolumn naming:   %s" % ", ".join(
        "%s %d (%.0f%%)" % (k, v, 100.0 * v / tot["cols"]) for k, v in styles.most_common()))
    print("column types:    %s" % ", ".join("%s %d" % kv for kv in types.most_common(10)))

    kbs = collections.Counter()
    deps = 0
    for db in dbs:
        path = os.path.join(DATA, db, "%s_kb.jsonl" % db)
        if not os.path.exists(path):
            continue
        for line in open(path):
            k = json.loads(line)
            kbs[k.get("type", "?")] += 1
            ch = k.get("children_knowledge")
            if ch not in (None, -1, [], [-1]):
                deps += 1
    print("\nknowledge base:  %d entries, %d with dependencies" % (sum(kbs.values()), deps))
    print("                 %s" % ", ".join("%s %d" % kv for kv in kbs.most_common()))
    if keyless and args.verbose:
        print("\ntables with no declared primary key: %s" % ", ".join(sorted(keyless)[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
