#!/usr/bin/env python3
"""Score an arm with LiveSQLBench's own evaluator.

Compiles each recorded ConQuer answer to SQL, merges it into the task file the official
harness reads, and runs that harness. Using theirs rather than ours is the point: `ex_base`
strips DISTINCT and ROUND from both sides, normalises dates, rounds decimals, compares as a
set unless the task's `conditions.order` says otherwise, and runs an explicit `test_cases`
function where a task ships one. A number from any other metric is not comparable to the
leaderboard, which is the only reason to have one (finding 143).

Two things the harness needs help with, neither of them ours to fix upstream:

  the interpreter   it spawns workers as a bare `python3`, and Python 3.10's SQLite is
                    3.35.5 -- too old for `->>` (3.38) and right joins (3.39), which 41 of
                    the 180 golds use. On a stock Python it scores its own ground truth at
                    77%. `--python` puts a newer one first on PATH; gold mode then gives
                    100%, which is the only ceiling worth measuring against.
  the working dir   its wrapper invokes `./single_instance_eval_sqlite.py` relatively, so it
                    only runs from inside its own directory. Run from anywhere else, every
                    instance fails and the score is 0.00% -- indistinguishable from a model
                    that answered nothing.

    official_eval.py --arm work/pilot-sqlite/conquer [--mode gold] [--sql]
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "data")
OFFICIAL = os.path.join(HERE, "work", "official")
EVAL = os.path.join(OFFICIAL, "harness", "evaluation")
NEWER_PYTHON = "/usr/local/opt/python@3.13/bin/python3.13"


def compile_answers(arm, model_dir):
    """instance_id -> the SQL a recorded ConQuer answer compiles to, parameters inlined."""
    sys.path.insert(0, os.path.join(ROOT, "conquer"))
    import conquer as driver
    out, refused = {}, {}
    for db in sorted(os.listdir(arm)):
        path = os.path.join(arm, db, "answers.json")
        mp = os.path.join(model_dir, "%s.ccm.json" % db)
        if not (os.path.exists(path) and os.path.exists(mp)):
            continue
        model = json.load(open(mp))
        for a in json.load(open(path)):
            if not a.get("answer"):
                continue
            try:
                _, sql, params = driver.transpile(model, a["answer"])
            except Exception as e:                                            # noqa: BLE001
                refused[a["question_id"]] = "%s: %s" % (type(e).__name__, str(e)[:90])
                continue
            # The harness executes plain SQL text, so a parameter has to be spelled in it.
            for v in params:
                sql = sql.replace("?", "'%s'" % str(v).replace("'", "''")
                                  if isinstance(v, str) else str(v), 1)
            out[a["question_id"]] = sql
    return out, refused


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arm", help="directory of <database>/answers.json")
    p.add_argument("--model-dir", default=os.path.join(HERE, "work", "models-sqlite-tier"))
    p.add_argument("--mode", choices=("gold", "pred"), default="pred")
    p.add_argument("--sql", action="store_true", help="answers are already SQL")
    p.add_argument("--python", default=NEWER_PYTHON)
    p.add_argument("--threads", type=int, default=4)
    args = p.parse_args(argv)

    gt = {r["instance_id"]: r for r in
          (json.loads(l) for l in
           open(os.path.join(DATA, "livesqlbench_base_lite_sqlite_gt.jsonl")))}
    tasks = [json.loads(l) for l in
             open(os.path.join(DATA, "livesqlbench_data_sqlite.jsonl"))]

    preds, refused = {}, {}
    if args.mode == "pred":
        if not args.arm:
            p.error("--mode pred needs --arm")
        if args.sql:
            for db in sorted(os.listdir(args.arm)):
                f = os.path.join(args.arm, db, "answers.json")
                if os.path.exists(f):
                    preds.update({a["question_id"]: a["answer"]
                                  for a in json.load(open(f)) if a.get("answer")})
        else:
            preds, refused = compile_answers(args.arm, args.model_dir)

    rows = []
    for t in tasks:
        if t.get("category") != "Query":
            continue
        g = gt.get(t["instance_id"])
        if not g or not g.get("sol_sql"):
            continue
        if args.mode == "pred" and t["instance_id"] not in preds:
            continue                       # scored below as answered-but-refused, or absent
        r = dict(t)
        r["sol_sql"] = g["sol_sql"]
        r["test_cases"] = g.get("test_cases") or []
        r["clean_up_sql"] = t.get("clean_up_sqls") or []
        if args.mode == "pred":
            r["pred_sqls"] = [preds[t["instance_id"]]]
        rows.append(r)

    os.makedirs(OFFICIAL, exist_ok=True)
    jsonl = os.path.join(OFFICIAL, "run_%s.jsonl" % args.mode)
    with open(jsonl, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    env = dict(os.environ)
    if os.path.exists(args.python):
        shim = os.path.join(OFFICIAL, "bin")
        os.makedirs(shim, exist_ok=True)
        link = os.path.join(shim, "python3")
        if not os.path.exists(link):
            os.symlink(args.python, link)
        env["PATH"] = shim + os.pathsep + env["PATH"]
    r = subprocess.run([sys.executable, "wrapper_evaluation_sqlite.py",
                        "--jsonl_file", jsonl,
                        "--db_path", os.path.join(OFFICIAL, "database"),
                        "--mode", args.mode, "--num_threads", str(args.threads)],
                       cwd=EVAL, env=env, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if any(k in line for k in ("Total instances", "Passed", "Failed", "errors",
                                   "Overall accuracy")):
            print(line)
    if refused:
        print("\nrefused by the compiler and therefore not submitted: %d" % len(refused))
        for k, v in list(refused.items())[:6]:
            print("   %-22s %s" % (k, v))
    scored = len(rows)
    if args.mode == "pred":
        print("\nsubmitted %d of %d SELECT tasks (%d refused, %d never answered)"
              % (scored, 180, len(refused), 180 - scored - len(refused)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
