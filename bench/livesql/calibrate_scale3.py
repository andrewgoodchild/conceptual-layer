#!/usr/bin/env python3
"""SCALE3.md's calibration: at one character budget, does the model's choice of tables keep
what the gold uses more often than the DDL retriever's?

Run on the *development* questions only -- the scale rounds' samples, on databases the test
round does not use -- with the question text alone. For each question: the characters each
view prints, and whether it keeps every table the gold statement touches.

    calibrate_scale3.py [--budget N] [--dbs a,b,...]
"""
import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "conquer"))
import annotate                                                           # noqa: E402
from calibrate_scale import tables_in                                     # noqa: E402

DATA = os.path.join(HERE, "data")
MODELS = os.path.join(HERE, "work", "models-profiled2")
SAMPLES = [os.path.join(HERE, "work", w, "sample.json") for w in ("pilot-scale", "pilot-scale2")]
TEST = {"museum_artifact_large", "planets_data_large", "solar_panel_large",
        "sports_events_large", "archeology_scan_large", "robot_fault_prediction_large"}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--budget", type=int, default=annotate.BUDGET)
    args = p.parse_args(argv)
    tasks = {t["instance_id"]: t for t in map(json.loads, open(os.path.join(
        DATA, "livesqlbench_large_v1_data.jsonl")))}
    gold = {g["instance_id"]: g for g in map(json.loads, open(os.path.join(
        DATA, "livesqlbench_large_v1_gt.jsonl")))}
    sample = {}
    for f in SAMPLES:
        for db, ids in json.load(open(f)).items():
            sample.setdefault(db, [])
            sample[db] += [i for i in ids if i not in sample[db]]
    rows = []
    for db, ids in sorted(sample.items()):
        model_path = os.path.join(MODELS, "%s.ccm.json" % db)
        if db in TEST or not os.path.exists(model_path):
            continue
        text = open(os.path.join(DATA, db, "%s_schema.txt" % db)).read()
        ann = annotate.Annotator(text, json.load(open(model_path)))
        plain = annotate.Annotator(text)
        names = [n for n, _ in ann.ddl.blocks]
        for qid in ids:
            q = tasks[qid]["normal_query"]
            sol = gold[qid]["sol_sql"]
            want = tables_in(" ".join(sol) if isinstance(sol, list) else sol, names)
            va, vp = ann.view(q, args.budget), plain.view(q, args.budget)
            # the tables *shown*: the "Not shown" line names the rest, so count CREATE TABLEs
            shown = lambda v: tables_in("\n".join(l for l in v.splitlines()
                                                   if l.startswith("CREATE TABLE")), names)
            rows.append((db, len(va), len(vp), want <= shown(va), want <= shown(vp),
                         len(shown(va)), len(shown(vp))))
    n = len(rows)
    print("%d development questions over %d databases, budget %d"
          % (n, len({r[0] for r in rows}), args.budget))
    print("  %-22s %10s %10s" % ("", "annotated", "plain"))
    print("  %-22s %10d %10d" % ("median characters", statistics.median(r[1] for r in rows),
                                 statistics.median(r[2] for r in rows)))
    print("  %-22s %10d %10d" % ("median tables", statistics.median(r[5] for r in rows),
                                 statistics.median(r[6] for r in rows)))
    print("  %-22s %10d %10d" % ("every gold table kept", sum(r[3] for r in rows),
                                 sum(r[4] for r in rows)))
    for db in sorted({r[0] for r in rows}):
        rr = [r for r in rows if r[0] == db]
        print("    %-40s %2d of %2d   %2d of %2d" % (db, sum(r[3] for r in rr), len(rr),
                                                   sum(r[4] for r in rr), len(rr)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
