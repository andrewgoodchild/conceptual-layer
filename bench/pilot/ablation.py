#!/usr/bin/env python3
"""The ablation table: each arm against the base it adds one thing to, question by question.

Reads results.json (after `score.py --merge`). For each ablation arm prints the score, the
questions it gained and lost against its base, and for the three independent writers the
oracle -- the score a perfect selector over their candidates would reach.

    ablation.py
"""
import collections, json, os

HERE = os.path.dirname(os.path.abspath(__file__))

# arm -> (base it is compared with, what it adds)
ABLATIONS = [
    ("conquer",             "direct",        "the model instead of the DDL (both with evidence)"),
    ("conquer_run2",        "conquer",       "a second independent writer, same prompt"),
    ("conquer_run3",        "conquer",       "a third"),
    ("conquer_vote",        "conquer",       "execution-consistency vote over the three writers"),
    ("conquer_select",      "conquer",       "a selector agent over the three writers' candidates"),
    ("conquer_verified",    "conquer",       "a verifier pass over the base arm's answers"),
    ("conquer_opus",        "conquer",       "a stronger writer (Opus for Sonnet)"),
    ("direct_opus",         "direct",        "a stronger writer, SQL from the DDL"),
    ("conquer_noev_lookup", "conquer_noev",  "a value-lookup tool, evidence withheld"),
    ("conquer_sem",         "conquer_noev",  "the definitions in the model, evidence withheld"),
    ("modelled_sem",        "direct_noev",   "the same definitions as English for a SQL writer"),
]


def main():
    R = json.load(open(os.path.join(HERE, "results.json")))
    qs = {q["question_id"]: q for q in json.load(open(os.path.join(HERE, "questions.json")))}
    by = collections.defaultdict(dict)
    for r in R:
        by[r["arm"]][r["question_id"]] = r
    ok = lambda arm, q: by[arm].get(q, {}).get("outcome") == "ok"
    score = lambda arm: sum(1 for q in qs if ok(arm, q))

    print("%-22s %-14s %5s %5s %6s %6s  %s" % ("arm", "base", "arm", "base", "gained", "lost", "adds"))
    print("-" * 100)
    for arm, base, adds in ABLATIONS:
        if not by.get(arm):
            continue
        gained = sorted(q for q in qs if ok(arm, q) and not ok(base, q))
        lost = sorted(q for q in qs if ok(base, q) and not ok(arm, q))
        print("%-22s %-14s %5d %5d %6d %6d  %s" % (arm, base, score(arm), score(base),
                                                   len(gained), len(lost), adds))
        if gained:
            print("%-22s gained: %s" % ("", " ".join(map(str, gained))))
        if lost:
            print("%-22s lost:   %s" % ("", " ".join(map(str, lost))))

    writers = ["conquer", "conquer_run2", "conquer_run3"]
    if all(by.get(a) for a in writers):
        union = sum(1 for q in qs if any(ok(a, q) for a in writers))
        allright = sum(1 for q in qs if all(ok(a, q) for a in writers))
        none = sum(1 for q in qs if not any(ok(a, q) for a in writers))
        print("\nthree writers: all right %d, none right %d, oracle (best of three) %d"
              % (allright, none, union))
        # agreement vs correctness, from the vote arm's records
        vote = {}
        for db in sorted({q["db_id"] for q in qs.values()}):
            p = os.path.join(HERE, "work", "conquer_vote", db, "answers.json")
            if os.path.exists(p):
                for a in json.load(open(p)):
                    vote[a["question_id"]] = a.get("agreement")
        if vote:
            print("agreement of the three writers' result sets, and how often the vote's pick is right:")
            for k in (3, 2, 1):
                qq = [q for q in qs if vote.get(q) == k]
                if qq:
                    print("  %d of 3 agree: %3d questions, vote right on %d"
                          % (k, len(qq), sum(1 for q in qq if ok("conquer_vote", q))))
    everything = [a for a in by if a != "conquer_vote" or True]
    union_all = sum(1 for q in qs if any(ok(a, q) for a in by))
    print("\noracle over every arm scored: %d of %d" % (union_all, len(qs)))


if __name__ == "__main__":
    main()
