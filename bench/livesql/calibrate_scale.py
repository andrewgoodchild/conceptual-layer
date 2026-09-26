#!/usr/bin/env python3
"""SCALE.md's calibration: how much each narrower keeps, and whether it keeps what the gold uses.

For every question in `work/pilot-scale/sample.json`, given only the question text: the tables
`link.py`'s narrowing of the profiled description names, the tables `ddl_link.py` keeps, and
the tables the gold statement touches. Prints the median kept by each and the share of
questions for which each keeps every gold table. Run before the writers, to set
`ddl_link.DEFAULT_TABLES` so the two arms see about as much.

    calibrate_scale.py [--tables N]
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import ddl_link                                                           # noqa: E402

DATA = os.path.join(HERE, "data")
CQ = os.path.join(ROOT, "conquer", "conquer.py")


def tables_in(text, names):
    low = text.lower()
    return {n for n in names if re.search(r"(?<![\w.])\"?%s\"?(?![\w])" % re.escape(n.lower()), low)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--tables", type=int, default=ddl_link.DEFAULT_TABLES)
    args = p.parse_args(argv)
    sample = json.load(open(os.path.join(HERE, "work", "pilot-scale", "sample.json")))
    tasks = {t["instance_id"]: t for t in map(json.loads, open(os.path.join(
        DATA, "livesqlbench_large_v1_data.jsonl")))}
    gold = {g["instance_id"]: g for g in map(json.loads, open(os.path.join(
        DATA, "livesqlbench_large_v1_gt.jsonl")))}
    rows = []
    for db, ids in sample.items():
        schema = os.path.join(DATA, db, "%s_schema.txt" % db)
        linker = ddl_link.DdlLinker(open(schema).read())
        names = [n for n, _ in linker.blocks]
        model = os.path.join(HERE, "work", "models-profiled", "%s.ccm.json" % db)
        for qid in ids:
            q = tasks[qid]["normal_query"]
            sol = gold[qid]["sol_sql"]
            sol = " ".join(sol) if isinstance(sol, list) else sol
            want = tables_in(sol, names)
            desc = subprocess.run([sys.executable, CQ, model, "--schema", "--relational",
                                   "--for", q], capture_output=True, text=True).stdout
            got_desc = tables_in(desc, names)
            got_ddl = linker.relevant(q, args.tables)
            rows.append((db, qid, len(got_desc), len(got_ddl), want <= got_desc,
                         want <= got_ddl, len(desc), sum(len(b) for n, b in linker.blocks
                                                          if n in got_ddl)))
    n = len(rows)
    print("%d questions; description keeps median %s tables (%d chars), DDL keeps median %s "
          "(%d chars)" % (n, statistics.median(r[2] for r in rows),
                          statistics.median(r[6] for r in rows),
                          statistics.median(r[3] for r in rows),
                          statistics.median(r[7] for r in rows)))
    print("every gold table kept: description %d of %d, DDL %d of %d"
          % (sum(r[4] for r in rows), n, sum(r[5] for r in rows), n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
