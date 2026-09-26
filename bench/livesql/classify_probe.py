#!/usr/bin/env python3
"""Does reading the documents agree with the field schema someone wrote down?

Until the dumps arrived, rule 12 on LiveSQLBench ran from `fields_meaning` -- metadata, not
data -- and `jsonshape.classify` had only ever seen a fixture. Now both are available over the
same columns, so they can be compared, and the comparison is the point: a declared type that
the data contradicts is a silently wrong answer waiting to happen.

`work_orders.costing.LABOR_COST` is declared REAL. The values are "$150.00", "EUR1,069.50",
"GBP82.00" -- three currencies and a thousands separator. `CAST('$150.00' AS REAL)` is **0.0**
in SQLite and an error in PostgreSQL, so a model built on the declaration reports every labour
cost as zero and says nothing.

    classify_probe.py [--db NAME] [-v]
"""

import argparse
import collections
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "reverse"))
sys.path.insert(0, HERE)

import catalog as cm                 # noqa: E402
import jsonshape as js               # noqa: E402
import catalogue                     # noqa: E402

DBDIR = os.path.join(HERE, "work", "db")
# Disagreements that do not change an answer: both are integers, or the classifier cannot see
# a date inside a string and says so.
BENIGN = {("bigint", "integer"), ("integer", "bigint"), ("smallint", "integer"),
          ("integer", "real"), ("date", "text"), ("text", "date"), ("real", "integer")}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    dbs = sorted(f[:-7] for f in os.listdir(DBDIR) if f.endswith(".sqlite"))
    if args.db:
        dbs = [d for d in dbs if args.db in d]

    print("%-34s %6s %6s %6s %6s %7s %7s" % (
        "database", "cols", "declrd", "found", "agree", "only 1", "bad type"))
    print("-" * 80)
    tot = collections.Counter()
    shapes = collections.Counter()
    dangerous = []
    for db in dbs:
        path = os.path.join(DBDIR, "%s.sqlite" % db)
        cat = cm.from_sqlite(path)
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        found = js.read(conn, cat)
        conn.close()
        for v in found.values():
            shapes[v[0]] += 1
        declared = catalogue.json_fields(os.path.join(HERE, "data", db), db)
        D = {k: {tuple(f["path"]): f["dataType"] for f in v} for k, v in declared.items()}
        F = {"%s|%s" % k: {tuple(f["path"]): f["dataType"] for f in v[1]}
             for k, v in found.items() if v[0] == "record"}
        got = collections.Counter()
        for key in set(D) | set(F):
            d, f = D.get(key, {}), F.get(key, {})
            both = set(d) & set(f)
            got["declared"] += len(d)
            got["found"] += len(f)
            got["only_one"] += len(set(d) ^ set(f))
            for k in both:
                if d[k] == f[k]:
                    got["agree"] += 1
                elif (d[k], f[k]) in BENIGN:
                    got["benign"] += 1
                else:
                    got["bad"] += 1
                    dangerous.append((db, key, ".".join(k), d[k], f[k]))
        print("%-34s %6d %6d %6d %6d %7d %7d" % (
            db[:34], len(set(D) | set(F)), got["declared"], got["found"],
            got["agree"] + got["benign"], got["only_one"], got["bad"]))
        tot.update(got)
    print("-" * 80)
    print("%-34s %6s %6d %6d %6d %7d %7d" % (
        "total", "", tot["declared"], tot["found"],
        tot["agree"] + tot["benign"], tot["only_one"], tot["bad"]))
    print("\nshape from the data: %s" % ", ".join("%s %d" % kv for kv in shapes.most_common()))
    print("paths the data found that the metadata did not, or the other way: %d"
          % tot["only_one"])
    print("type disagreements: %d harmless (integer widths, a date the data calls text), "
          "%d that change an answer" % (tot["benign"], tot["bad"]))
    if dangerous:
        print("\ndeclared numeric, actually text -- these cast to 0.0 in SQLite and raise in "
              "PostgreSQL:")
        for db, key, path, d, f in dangerous[:20] if not args.verbose else dangerous:
            print("   %-26s %-40s declared %-8s data says %s"
                  % (db.replace("_large", ""), (key + " -> " + path)[:40], d, f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
