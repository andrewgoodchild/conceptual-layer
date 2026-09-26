#!/usr/bin/env python3
"""Score the scale round (SCALE.md): the three arms, question by question, against the gold.

The same execution-accuracy rule as `score_pg.py` -- it is imported, not reimplemented -- over
`work/pilot-scale/{sql,sqlddlk,sqldesc}`, reported as each arm's score, the pre-registered
comparison (`sqldesc` against `sqlddlk`) with its paired discordant counts and McNemar's
exact test, the same without `mental_healths` (where two arms shared draft files; see
SCALE.md), and a copy check: answers byte-identical between arms of one database, which is
what shared drafts would leave behind.

    score_scale.py [--json out.json]
    score_scale.py --work work/pilot-scale2 --arms sqlddlk,sqldesc,sqldesc2 \
                   --compare sqldesc2:sqldesc,sqldesc2:sqlddlk           # SCALE2.md
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_pg                                                            # noqa: E402

WORK = os.path.join(HERE, "work", "pilot-scale")
ARMS = ["sql", "sqlddlk", "sqldesc"]


def mcnemar(b, c):
    """Two-sided exact McNemar p for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--json")
    p.add_argument("--work", default=WORK)
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--compare", default="sqldesc:sqlddlk,sqldesc:sql,sqlddlk:sql",
                   help="pairs a:b to compare, the pre-registered one first")
    p.add_argument("--exclude", default="mental_healths",
                   help="a database prefix to report a sensitivity analysis without")
    args = p.parse_args(argv)
    work = os.path.abspath(args.work)
    arms = [a for a in args.arms.split(",") if a]
    pairs = [tuple(x.split(":")) for x in args.compare.split(",") if x]
    data = os.path.join(HERE, "data")
    gt = {r["instance_id"]: r for r in map(json.loads, open(os.path.join(
        data, "livesqlbench_large_v1_gt.jsonl")))}
    qs = {q["instance_id"]: q for q in map(json.loads, open(os.path.join(
        data, "livesqlbench_large_v1_data.jsonl")))}
    sample = json.load(open(os.path.join(work, "sample.json")))
    ids = [(db, qid) for db, lst in sample.items() for qid in lst]

    answers = {arm: score_pg.load_arm(os.path.join(work, arm)) for arm in arms}
    conns, verdict = {}, {arm: {} for arm in arms}
    for db, qid in ids:
        if db not in conns:
            conns[db] = score_pg.connect(score_pg.DSN, db)
        want = score_pg.rows(conns[db], score_pg.gold_sql(gt[qid]))
        ordered = (qs[qid].get("conditions") or {}).get("order")
        for arm in arms:
            ans = (answers[arm].get(qid) or (db, None))[1]
            if not ans:
                verdict[arm][qid] = "missing"
                continue
            if isinstance(want, str):
                verdict[arm][qid] = "no_gold"
                continue
            got = score_pg.rows(conns[db], ans)
            if isinstance(got, str):
                verdict[arm][qid] = "failed"
                continue
            same = got == want if ordered else sorted(got, key=str) == sorted(want, key=str)
            verdict[arm][qid] = "ok" if same else "wrong"

    scored = [q for _, q in ids if verdict[arms[0]][q] != "no_gold"]
    print("%d questions, %d with runnable gold" % (len(ids), len(scored)))
    for arm in arms:
        v = verdict[arm]
        ok = sum(v[q] == "ok" for q in scored)
        print("  %-8s %3d ok   %s" % (arm, ok, {k: sum(v[q] == k for q in scored)
                                                  for k in ("wrong", "failed", "missing")}))

    def compare(a, b, only):
        qq = [q for q in scored if only(q)]
        wa = sum(verdict[a][q] == "ok" and verdict[b][q] != "ok" for q in qq)
        wb = sum(verdict[b][q] == "ok" and verdict[a][q] != "ok" for q in qq)
        oa = sum(verdict[a][q] == "ok" for q in qq)
        ob = sum(verdict[b][q] == "ok" for q in qq)
        print("  %-8s v %-8s %3d v %3d of %d   %s wins %d, %s wins %d   McNemar p = %.2f"
              % (a, b, oa, ob, len(qq), a, wa, b, wb, mcnemar(wa, wb)))

    print("\nPre-registered comparison, and the others:")
    for a, b in pairs:
        compare(a, b, lambda q: True)
    if args.exclude and any(q.startswith(args.exclude) for q in scored):
        print("\nWithout %s:" % args.exclude)
        for a, b in pairs:
            compare(a, b, lambda q: not q.startswith(args.exclude))

    print("\nByte-identical answers between arms of one database (normalised whitespace):")
    norm = lambda s: " ".join((s or "").split()).rstrip(";").lower()
    same = 0
    for db, qid in ids:
        texts = {arm: norm((answers[arm].get(qid) or (db, None))[1]) for arm in arms}
        for i, a in enumerate(arms):
            for b in arms[i + 1:]:
                if texts[a] and texts[a] == texts[b]:
                    same += 1
                    print("   %-28s %s = %s" % (qid, a, b))
    print("   %d identical pair(s)" % same)

    if args.json:
        json.dump(verdict, open(args.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
