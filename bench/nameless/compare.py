#!/usr/bin/env python3
"""Score the round by BIRD's strict EX and make the comparisons PLAN.md fixed in advance.

An answer runs on the copy its arm saw and the gold on BIRD's own database: the rows are the
same, so a renamed copy needs no translated gold. Scoring, the McNemar test and the database
bootstrap are bench/minidev2026/compare.py's. Per-question rows go to the git-ignored
results.json.
"""
import importlib.util, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location(
    "october", os.path.join(ROOT, "bench/minidev2026/compare.py"))
october = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(october)
pilot = october.pilot

QUESTIONS = os.path.join(ROOT, "bench/bird/mini_dev_1024/questions.json")
ARMS = {"ddl_named": "named", "mcp_named": "named",
        "ddl_nameless": "nameless", "mcp_nameless": "nameless"}
PRIMARY = ("mcp_nameless", "ddl_nameless")
SECONDARY = (("mcp_named", "ddl_named"), ("ddl_nameless", "ddl_named"),
             ("mcp_nameless", "mcp_named"))


def connect(path):
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    c.text_factory = lambda b: b.decode("utf-8", "replace")
    return c


def score_arm(arm, qs, conns):
    out = {}
    for q in qs:
        db = q["db_id"]
        answers = json.load(open(os.path.join(HERE, "work", arm, db, "answers.json")))
        a = next((x for x in answers if x.get("question_id") == q["question_id"]), {})
        row = {"arm": arm, "question_id": q["question_id"], "db_id": db,
               "evidence": bool(q["evidence"]), "answer": a.get("answer"),
               "attempts": a.get("attempts")}
        out[q["question_id"]] = row
        if not a.get("answer"):
            row["outcome"] = "not_answered"
            continue
        copy = (ARMS[arm], db)
        if copy not in conns:
            conns[copy] = connect(os.path.join(HERE, "data", ARMS[arm], db + ".sqlite"))
        try:
            got = pilot.rows(conns[copy], a["answer"])
        except sqlite3.Error as e:
            row["outcome"], row["error"] = "failed_loudly", str(e)
            continue
        if ("bird", db) not in conns:
            conns["bird", db] = connect(os.path.join(pilot.DBS, db, db + ".sqlite"))
        want = pilot.rows(conns["bird", db], q["SQL"])
        row["outcome"] = "ok" if pilot.bird_ex(got, want) else "wrong_quietly"
        row["multiset"] = pilot.multiset_ex(got, want)
    return out


def main():
    qs = json.load(open(QUESTIONS))
    conns = {}
    scored = {arm: score_arm(arm, qs, conns) for arm in ARMS}
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump([r for arm in ARMS for r in scored[arm].values()], fh, indent=1)
    for arm in ARMS:
        rows = scored[arm].values()
        count = lambda o: sum(1 for r in rows if r["outcome"] == o)
        print("%-13s %3d ok of %d  wrong %d  failed %d  not answered %d  multiset %d" % (
            arm, count("ok"), len(rows), count("wrong_quietly"), count("failed_loudly"),
            count("not_answered"), sum(1 for r in rows if r.get("multiset"))))
    print("\nprimary")
    print(october.compare(*PRIMARY, scored))
    print("\nsecondary")
    for a, b in SECONDARY:
        print(october.compare(a, b, scored))
    named = {q: int(scored["mcp_named"][q]["outcome"] == "ok")
             - int(scored["ddl_named"][q]["outcome"] == "ok") for q in scored["mcp_named"]}
    nameless = {q: int(scored["mcp_nameless"][q]["outcome"] == "ok")
                - int(scored["ddl_nameless"][q]["outcome"] == "ok") for q in named}
    print("\nthe description's margin, nameless minus named: %+d (descriptive)"
          % (sum(nameless.values()) - sum(named.values())))


if __name__ == "__main__":
    main()
