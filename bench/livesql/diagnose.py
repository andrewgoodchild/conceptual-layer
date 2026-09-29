#!/usr/bin/env python3
"""Evidence for finding each miss's cause: one folder per database, for an analyst agent.

For every SCALE4 question some arm got wrong: the question, its conditions, the gold statement
and its result, each arm's answer, verdict and result, and the writers' reports; beside them
the knowledge base, `./try` on the database, `./model` (the profiled model's description,
narrowed) and `./view` (the annotated view with both kinds of description), and the model file
itself. The folders hold the benchmark's private gold and are git-ignored; what comes out of
them is a classification with no gold in it.

    diagnose.py                                    SCALE4: work/pilot-scale4/diagnose/DB/
    diagnose.py --work pilot-scale --arms sql,sqlddlk,sqldesc
    diagnose.py --work pilot-scale2 --arms sqlddlk,sqldesc,sqldesc2

For the earlier rounds each arm's own `./schema` is copied as `view_ARM` (the tool that arm's
writer ran), and `./model` describes the profiled model its description arm read; SCALE2's
`sqldesc2` also gets `./model2`, the later profiled model. `sqldesc2`'s business-term hints
were removed from `conquer.py` after that round, so its view is rebuilt without them.
"""
import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pilot                                                              # noqa: E402
import score_pg                                                           # noqa: E402

W = os.path.join(HERE, "work", "pilot-scale4")
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="pilot-scale4")
    ap.add_argument("--arms", default=",".join(ARMS))
    args = ap.parse_args(argv)
    w = os.path.join(HERE, "work", args.work)
    arms = args.arms.split(",")
    scale4 = args.work == "pilot-scale4"
    out_root = os.path.join(w, "diagnose")
    pilot.TIER = dict(pilot.TIERS["large-pg"])
    tasks = {t["instance_id"]: t for t in map(json.loads, open(os.path.join(
        HERE, "data", "livesqlbench_large_v1_data.jsonl")))}
    gold = {g["instance_id"]: g for g in map(json.loads, open(os.path.join(
        HERE, "data", "livesqlbench_large_v1_gt.jsonl")))}
    v = json.load(open(os.path.join(w, "verdicts.json")))
    sample = json.load(open(os.path.join(w, "sample.json")))
    answers = {a: score_pg.load_arm(os.path.join(w, a)) for a in arms}
    for db, ids in sample.items():
        wrong = [q for q in ids if any(v[a][q] != "ok" for a in arms)]
        d = os.path.join(out_root, db)
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
            for a in arms:
                ans = (answers[a].get(q) or (db, None))[1] or ""
                case["arms"][a] = {"verdict": v[a][q], "answer": ans,
                                   "result": show(score_pg.rows(conn, ans)) if ans else ""}
            cases.append(case)
        conn.close()
        json.dump(cases, open(os.path.join(d, "cases.json"), "w"), indent=1, default=str)
        open(os.path.join(d, "knowledge.md"), "w").write(pilot.knowledge(db))
        open(os.path.join(d, "try"), "w").write(pilot.try_sql(db))
        schema = pilot.TIER["schema"] % (db, db)
        if scale4:
            model = os.path.join(pilot.TIER["models"] + "-profiled2", "%s.ccm.json" % db)
            open(os.path.join(d, "view"), "w").write(
                pilot.scale4_script("annm", db, model, schema))
            tools = ["try", "model", "view"]
        else:
            model = os.path.join(pilot.TIER["models"] + "-profiled", "%s.ccm.json" % db)
            tools = ["try", "model"]
            for a in arms:
                src = os.path.join(w, a, db, "schema")
                if os.path.exists(src):
                    text = open(src).read().replace(' --knowledge "', ' --ignored "')
                    if "--ignored" in text:
                        text = text.replace(re.search(r' --ignored "[^"]*"', text).group(0), "")
                    open(os.path.join(d, "view_" + a), "w").write(text)
                    tools.append("view_" + a)
                elif a == "sql":
                    open(os.path.join(d, "view_sql"), "w").write(
                        "#!/bin/sh\n# the sql arm had the full DDL in a file, schema.sql\n"
                        "exec cat \"%s\"\n" % schema)
                    tools.append("view_sql")
            if "sqldesc2" in arms:
                m2 = os.path.join(pilot.TIER["models"] + "-profiled2", "%s.ccm.json" % db)
                open(os.path.join(d, "model2"), "w").write(MODEL_SH % (pilot.CQ, m2))
                shutil.copy(m2, os.path.join(d, "model2.ccm.json"))
                tools.append("model2")
        shutil.copy(model, os.path.join(d, "model.ccm.json"))
        open(os.path.join(d, "model"), "w").write(MODEL_SH % (pilot.CQ, model))
        for f in tools:
            os.chmod(os.path.join(d, f), 0o755)
        rep = os.path.join(d, "reports")
        os.makedirs(rep)
        for a in arms:
            src = os.path.join(w, "reports", "%s_%s.md" % (a, db))
            if os.path.exists(src):
                shutil.copy(src, os.path.join(rep, "%s.md" % a))
        print("%s: %d cases" % (db, len(cases)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
