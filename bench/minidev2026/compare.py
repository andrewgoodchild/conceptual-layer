#!/usr/bin/env python3
"""Score the round by BIRD's strict EX and make the comparisons PLAN.md fixed in advance.

Each answer is scored as `bench/pilot/score.py` scores it: `rows` and `bird_ex` are that
file's. The difference between two arms gets an exact McNemar test on the questions they
split and a bootstrap that resamples whole databases, since questions over one database are
not independent. The per-question rows go to the git-ignored results.json.
"""
import json, math, os, random, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "bench/pilot"))
import score as pilot             # noqa: E402

QUESTIONS = os.path.join(ROOT, "bench/bird/mini_dev_1024/questions.json")
ARMS = ("sql_ddl", "sql_mcp", "conquer_mcp")
PAIRS = (("sql_mcp", "sql_ddl"), ("conquer_mcp", "sql_mcp"), ("conquer_mcp", "sql_ddl"))
RESAMPLES, SEED = 10000, 20261031


def score_arm(arm, qs, conns, models):
    out = {}
    for q in qs:
        db = q["db_id"]
        answers = json.load(open(os.path.join(HERE, "work", arm, db, "answers.json")))
        a = next((x for x in answers if x.get("question_id") == q["question_id"]), {})
        c = conns.setdefault(db, sqlite3.connect(os.path.join(pilot.DBS, db, db + ".sqlite")))
        c.text_factory = lambda b: b.decode("utf-8", "replace")
        row = {"arm": arm, "question_id": q["question_id"], "db_id": db,
               "evidence": bool(q["evidence"]), "answer": a.get("answer"),
               "attempts": a.get("attempts")}
        out[q["question_id"]] = row
        if not a.get("answer"):
            row["outcome"] = "not_answered"
            continue
        try:
            if arm.startswith("conquer"):
                if db not in models:
                    m = json.load(open(os.path.join(ROOT, "bench/models/%s.ccm.json" % db)))
                    models[db] = (m, pilot.parser_mod.Lexicon(m), pilot.sql_mod.Emitter(m))
                m, lexicon, emitter = models[db]
                _, st, p = pilot.driver.transpile(m, a["answer"], lexicon, emitter)
                got = pilot.rows(c, st, p)
            else:
                got = pilot.rows(c, a["answer"])
        except (pilot.parser_mod.ParseError, pilot.parser_mod.Ambiguous, pilot.sql_mod.SqlError,
                sqlite3.Error) as e:
            row["outcome"], row["error"] = "failed_loudly", str(e)
            continue
        row["outcome"] = "ok" if pilot.bird_ex(got, pilot.rows(c, q["SQL"])) else "wrong_quietly"
    return out


def mcnemar(b, c):
    """Exact two-sided p on the questions exactly one arm got."""
    n = b + c
    if not n:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def clustered(diffs):
    """95% interval of the summed difference, resampling databases, scaled to the sample's size."""
    rng = random.Random(SEED)
    dbs, size, got = sorted(diffs), sum(len(v) for v in diffs.values()), []
    for _ in range(RESAMPLES):
        picks = [diffs[rng.choice(dbs)] for _ in dbs]
        n = sum(len(p) for p in picks)
        got.append(100.0 * sum(sum(p) for p in picks) / n * size / 100.0)
    got.sort()
    return got[int(.025 * RESAMPLES)], got[int(.975 * RESAMPLES)]


def compare(a, b, scored, keep=lambda q: True):
    diffs = {}
    for qid, row in scored[a].items():
        if keep(row):
            one = row["outcome"] == "ok"
            two = scored[b][qid]["outcome"] == "ok"
            diffs.setdefault(row["db_id"], []).append(int(one) - int(two))
    flat = [d for v in diffs.values() for d in v]
    gained, lost = flat.count(1), flat.count(-1)
    low, high = clustered(diffs)
    return ("%-11s vs %-11s  %+3d of %3d  (%d gained, %d lost)  McNemar p=%.3f  "
            "database bootstrap 95%% [%+.1f, %+.1f]"
            % (a, b, gained - lost, len(flat), gained, lost, mcnemar(gained, lost), low, high))


def main():
    qs = json.load(open(QUESTIONS))
    conns, models = {}, {}
    scored = {arm: score_arm(arm, qs, conns, models) for arm in ARMS}
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump([r for arm in ARMS for r in scored[arm].values()], fh, indent=1)
    for arm in ARMS:
        rows = scored[arm].values()
        count = lambda o: sum(1 for r in rows if r["outcome"] == o)
        print("%-11s %3d ok of %d  wrong %d  failed %d  not answered %d" % (
            arm, count("ok"), len(rows), count("wrong_quietly"), count("failed_loudly"),
            count("not_answered")))
    print("\nall questions")
    for a, b in PAIRS:
        print(compare(a, b, scored))
    for label, keep in (("no evidence", lambda r: not r["evidence"]),
                        ("with evidence", lambda r: r["evidence"])):
        print("\n" + label)
        print(compare("sql_mcp", "sql_ddl", scored, keep))


if __name__ == "__main__":
    main()
