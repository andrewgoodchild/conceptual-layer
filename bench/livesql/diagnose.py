#!/usr/bin/env python3
"""Evidence for finding each miss's cause: one folder per database, for an analyst agent.

For every SCALE4 question some arm got wrong: the question, its conditions, the gold statement
and its result, each arm's answer, verdict and result, and the writers' reports; beside them
the knowledge base, `./try` on the database, `./model` (the profiled model's description,
narrowed) and `./view` (the annotated view with both kinds of description), and the model file
itself. The folders hold the benchmark's private gold and are git-ignored; what comes out of
them is a classification with no gold in it.

    diagnose.py            work/pilot-scale4/diagnose/DB/
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pilot                                                              # noqa: E402
import score_pg                                                           # noqa: E402

W = os.path.join(HERE, "work", "pilot-scale4")
OUT = os.path.join(W, "diagnose")
ARMS = ["ddlp4", "ddlm", "annm", "annl"]
MODEL_SH = """#!/bin/sh
# The profiled model's description of this database in relational terms, narrowed to words:
#   ./model "robot payload"        ./model  (everything)
exec python3 "%s" "%s" --schema --relational --for "$*"
"""


def show(rows, n=8):
    if isinstance(rows, str):
        return rows
    return "%d rows; first %d: %s" % (len(rows), min(n, len(rows)), json.dumps(rows[:n], default=str))


def main():
    pilot.TIER = dict(pilot.TIERS["large-pg"])
    tasks = {t["instance_id"]: t for t in map(json.loads, open(os.path.join(
        HERE, "data", "livesqlbench_large_v1_data.jsonl")))}
    gold = {g["instance_id"]: g for g in map(json.loads, open(os.path.join(
        HERE, "data", "livesqlbench_large_v1_gt.jsonl")))}
    v = json.load(open(os.path.join(W, "verdicts.json")))
    sample = json.load(open(os.path.join(W, "sample.json")))
    answers = {a: score_pg.load_arm(os.path.join(W, a)) for a in ARMS}
    for db, ids in sample.items():
        wrong = [q for q in ids if any(v[a][q] != "ok" for a in ARMS)]
        d = os.path.join(OUT, db)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        conn = score_pg.connect(score_pg.DSN, db)
        cases = []
        for q in wrong:
            sol = gold[q]["sol_sql"]
            sol = "\n".join(sol) if isinstance(sol, list) else sol
            case = {"question_id": q, "question": tasks[q]["normal_query"],
                    "conditions": tasks[q].get("conditions"),
                    "gold_sql": sol, "gold_result": show(score_pg.rows(conn, sol)),
                    "arms": {}}
            for a in ARMS:
                ans = (answers[a].get(q) or (db, None))[1] or ""
                case["arms"][a] = {"verdict": v[a][q], "answer": ans,
                                   "result": show(score_pg.rows(conn, ans)) if ans else ""}
            cases.append(case)
        conn.close()
        json.dump(cases, open(os.path.join(d, "cases.json"), "w"), indent=1, default=str)
        open(os.path.join(d, "knowledge.md"), "w").write(pilot.knowledge(db))
        open(os.path.join(d, "try"), "w").write(pilot.try_sql(db))
        model = os.path.join(pilot.TIER["models"] + "-profiled2", "%s.ccm.json" % db)
        shutil.copy(model, os.path.join(d, "model.ccm.json"))
        open(os.path.join(d, "model"), "w").write(MODEL_SH % (pilot.CQ, model))
        schema = pilot.TIER["schema"] % (db, db)
        open(os.path.join(d, "view"), "w").write(pilot.scale4_script("annm", db, model, schema))
        for f in ("try", "model", "view"):
            os.chmod(os.path.join(d, f), 0o755)
        rep = os.path.join(d, "reports")
        os.makedirs(rep)
        for a in ARMS:
            src = os.path.join(W, "reports", "%s_%s.md" % (a, db))
            if os.path.exists(src):
                shutil.copy(src, os.path.join(rep, "%s.md" % a))
        print("%s: %d cases" % (db, len(cases)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
