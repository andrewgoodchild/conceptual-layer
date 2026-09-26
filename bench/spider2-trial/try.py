#!/usr/bin/env python3
"""Compile one ConQuer query against a Spider 2.0 local model, run it, and score it against
the task's accepted result sets.

Spider 2.0 accepts several result sets per task (91 of the 135 local tasks do), which is a
better design than BIRD's single gold and is the reason this scores against all of them and
reports which one matched. The comparison is deliberately blunt -- the multiset of rows, each
cell as text, column names and column order ignored -- so a pass means the numbers are right
and says nothing about presentation.

    try.py <instance_id> --query "<conquer>" [--sql] [--rows N]
    try.py --all                       re-run every attempt in attempts.json and score it
"""

import argparse
import csv
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import conquer as driver          # noqa: E402

LITE = os.path.join(ROOT, "bench/spider2/spider2-lite")
DBS = os.path.join(LITE, "resource/databases/spider2-localdb")
MODELS = os.path.join(ROOT, "bench/spider2-models")
GOLD = os.path.join(LITE, "evaluation_suite/gold")
# the task list's db name is not always the file name, and a name that does not exist would
# be *created* as an empty database by sqlite3.connect rather than reported as missing
DB_FILE = {"Db-IMDB": "DB_IMDB"}


def task(iid):
    for line in open(os.path.join(LITE, "spider2-lite.jsonl")):
        row = json.loads(line)
        if row["instance_id"] == iid:
            return row
    raise SystemExit("no such task: %s" % iid)


def accepted(iid):
    """Every result set the benchmark accepts for this task, for *showing* a difference.
    Scoring goes through `official_score`."""
    out = []
    for name in sorted(os.listdir(os.path.join(GOLD, "exec_result"))):
        if not name.startswith(iid + "_") or not name.endswith(".csv"):
            continue
        with open(os.path.join(GOLD, "exec_result", name), newline="") as f:
            rows = list(csv.reader(f))
        out.append((name, rows[0], sorted(tuple(cell_text(c) for c in r) for r in rows[1:])))
    return out


def comparator():
    """Spider 2.0's own `compare_pandas_table`, lifted out of its evaluator.

    Scoring by a rule of one's own is scoring a different benchmark. Theirs is column-wise
    rather than row-wise: every *gold* column must appear somewhere in the prediction,
    matched element for element within 1e-2, extra predicted columns ignored, and row order
    required unless the task's own `ignore_order` says otherwise. A multiset-of-rows check --
    which is what this file used to do -- is stricter in one direction and looser in the
    other, and agrees with theirs only by luck.

    Lifted by hand because `evaluate.py` imports BigQuery and Snowflake clients at module
    level and the local slice needs neither.
    """
    import math
    import types
    import pandas as pd
    src = open(os.path.join(LITE, "evaluation_suite/evaluate.py")).read()
    a = src.index("def compare_multi_pandas_table")
    b = src.index("def get_bigquery_sql_result")
    mod = types.ModuleType("spider2_compare")
    mod.__dict__.update({"pd": pd, "math": math})
    exec(compile(src[a:b], "evaluate.py", "exec"), mod.__dict__)        # noqa: S102
    return mod


def official_score(iid, rows, columns):
    """1 or 0, by the benchmark's own rule and its own per-task settings; None if ungraded."""
    import pandas as pd
    golds = [pd.read_csv(os.path.join(GOLD, "exec_result", g))
             for g in sorted(os.listdir(os.path.join(GOLD, "exec_result")))
             if g.startswith(iid + "_")]
    if not golds:
        return None
    std = {}
    for line in open(os.path.join(GOLD, "spider2lite_eval.jsonl")):
        row = json.loads(line)
        if row["instance_id"] == iid:
            std = row
            break
    cmp, pred = comparator(), pd.DataFrame(rows, columns=columns)
    cols, order = std.get("condition_cols") or None, std.get("ignore_order", False)
    return (cmp.compare_multi_pandas_table(pred, golds, cols, order) if len(golds) > 1
            else cmp.compare_pandas_table(pred, golds[0], cols, order))


def cell_text(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return ("%.4f" % v).rstrip("0").rstrip(".")
    s = str(v)
    try:                                   # 30 and 30.0 are the same number in a CSV
        return ("%.4f" % float(s)).rstrip("0").rstrip(".")
    except ValueError:
        return s


def score(instance_id, query):
    """(matched file or None, rows produced, error). The whole attempt, no printing."""
    t = task(instance_id)
    db = DB_FILE.get(t["db"], t["db"])
    path = os.path.join(DBS, db + ".sqlite")
    if not os.path.exists(path):
        return None, 0, "no database %s.sqlite" % db
    model = json.load(open(os.path.join(MODELS, "%s.ccm.json" % db)))
    try:
        _, statement, params = driver.transpile(model, query)
    except Exception as e:                                        # noqa: BLE001
        return None, 0, "%s: %s" % (type(e).__name__, str(e)[:140])
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    try:
        got = conn.execute(statement, params).fetchall()
    except sqlite3.Error as e:
        return None, 0, "sqlite: %s" % e
    cols = [d[0] for d in conn.execute(statement, params).description]
    return official_score(instance_id, got, cols), len(got), None


def run_all():
    """Every recorded attempt, re-scored. The point of recording them is that a change to the
    compiler or to the reverse engineering can be checked against real questions in seconds."""
    attempts = json.load(open(os.path.join(HERE, "attempts.json")))
    passed = 0
    for a in attempts:
        got, rows, err = score(a["instance_id"], a["query"])
        passed += 1 if got else 0
        print("%-5s %-10s %-52s %s"
              % ("PASS" if got else "fail", a["instance_id"], a["note"][:52],
                 err or "%d row(s)" % rows))
    print("\n%d of %d score 1 under Spider 2.0's own evaluator" % (passed, len(attempts)))
    return 0 if passed == len(attempts) else 1


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("instance_id", nargs="?")
    p.add_argument("--query")
    p.add_argument("--all", action="store_true", help="re-run every attempt in attempts.json")
    p.add_argument("--sql", action="store_true", help="print the emitted SQL")
    p.add_argument("--rows", type=int, default=5, help="how many result rows to show")
    args = p.parse_args(argv)
    if args.all:
        return run_all()
    if not args.instance_id or not args.query:
        p.error("give an instance id and --query, or --all")

    t = task(args.instance_id)
    db = DB_FILE.get(t["db"], t["db"])
    if not os.path.exists(os.path.join(DBS, db + ".sqlite")):
        raise SystemExit("no database %s.sqlite in %s -- see the README for the download"
                         % (db, os.path.relpath(DBS, ROOT)))
    model = json.load(open(os.path.join(MODELS, "%s.ccm.json" % db)))
    print("%s  [%s]\n%s\n" % (t["instance_id"], db, t["question"]))

    _, statement, params = driver.transpile(model, args.query)
    if args.sql:
        print(statement, "\n")
    conn = sqlite3.connect("file:%s?mode=ro" % os.path.join(DBS, db + ".sqlite"), uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    got = conn.execute(statement, params).fetchall()
    mine = sorted(tuple(cell_text(c) for c in r) for r in got)

    for r in got[:args.rows]:
        print("   ", r)
    print("    %d row(s)\n" % len(got))

    print("    Spider 2.0's own evaluator scores this %s\n"
          % official_score(args.instance_id, got, [d[0] for d in
                           conn.execute(statement, params).description]))
    for name, header, rows in accepted(args.instance_id):
        verdict = "same" if rows == mine else "no"
        print("  %-5s %-18s %d row(s)  %s" % (verdict, name, len(rows), ",".join(header)))
        if verdict == "no" and len(rows) == len(mine):
            diff = [(a, b) for a, b in zip(rows, mine) if a != b][:2]
            for a, b in diff:
                print("        gold %s\n        mine %s" % (a, b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
