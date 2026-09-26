#!/usr/bin/env python3
"""Execution-consistency selection over several writers' candidates (the `conquer_vote` arm).

For each question, run every candidate the named arms wrote, group them by the result set
they return, and keep the candidate from the largest group -- the first arm's on a tie. No
model in the loop: this is the deterministic half of "generate candidates and select", the
half every leaderboard system starts with. Writes work/conquer_vote/<db>/answers.json in the
scorer's format, plus `chosen` (which arm) and `agreement` (how many agreed).

    vote.py [--arms conquer conquer_run2 conquer_run3] [--out-arm NAME]
"""
import json, os, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
DBS = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402

TIMEOUT = 120


def rows(conn, statement, params=()):
    deadline = time.time() + TIMEOUT
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    try:
        return conn.execute(statement, params).fetchall()
    finally:
        conn.set_progress_handler(None, 0)


def main():
    arms = ["conquer", "conquer_run2", "conquer_run3"]
    if "--arms" in sys.argv:
        arms = []
        for a in sys.argv[sys.argv.index("--arms") + 1:]:
            if a.startswith("--"):           # --out-arm may follow --arms
                break
            arms.append(a)
    qs = json.load(open(os.path.join(HERE, "questions.json")))
    out_arm = "conquer_vote"
    if "--out-arm" in sys.argv:          # a second trio needs a second arm to write into
        out_arm = sys.argv[sys.argv.index("--out-arm") + 1]
    for db in sorted({q["db_id"] for q in qs}):
        cands = {}
        for i, arm in enumerate(arms):
            path = os.path.join(HERE, "work", arm, db, "answers.json")
            for a in json.load(open(path)):
                cands.setdefault(a["question_id"], []).append((i, a.get("answer")))
        model = json.load(open(os.path.join(ROOT, "bench/models/%s.ccm.json" % db)))
        lex, em = parser_mod.Lexicon(model), sql_mod.Emitter(model)
        conn = sqlite3.connect(os.path.join(DBS, db, db + ".sqlite"))
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        chosen = []
        for q in [q for q in qs if q["db_id"] == db]:
            groups = {}                                   # frozenset(rows) -> [(i, answer)]
            for i, ans in cands.get(q["question_id"], []):
                if not ans:
                    continue
                try:
                    _, st, p = driver.transpile(model, ans, lex, em)
                    key = frozenset(rows(conn, st, p))
                except (parser_mod.ParseError, parser_mod.Ambiguous, sql_mod.SqlError,
                        sqlite3.Error):
                    continue                              # a failed candidate casts no vote
                groups.setdefault(key, []).append((i, ans))
            if not groups:
                chosen.append({"question_id": q["question_id"], "answer": None,
                               "note": "no candidate ran"})
                continue
            best = max(groups.values(), key=lambda g: (len(g), -g[0][0]))
            i, ans = best[0]
            chosen.append({"question_id": q["question_id"], "answer": ans, "attempts": 0,
                           "chosen": arms[i], "agreement": len(best),
                           "candidates": sum(len(g) for g in groups.values())})
            print("%-24s %5d  chose %-13s agreement %d of %d" % (
                db, q["question_id"], arms[i], len(best), sum(len(g) for g in groups.values())))
        d = os.path.join(HERE, "work", out_arm, db)
        os.makedirs(d, exist_ok=True)
        json.dump(chosen, open(os.path.join(d, "answers.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
