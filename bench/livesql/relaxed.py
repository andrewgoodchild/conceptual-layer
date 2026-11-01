#!/usr/bin/env python3
"""What a declared relaxed rescoring would give a scale round, beside strict EX, by rule.

Finding 171 put 25 of SCALE4's wrong answers down to the scorer: rows tied on the sort key, a
rounding difference, an extra identifying column. This asks how much of that a rule stated in
advance recovers, and what else the rule lets in. The rule is `relaxed_ex` in
`bench/pilot/score.py`; values are compared before `score_pg.norm` rounds them, so a rounding
boundary is the tolerance's business. It prints counts by rule and names no question, and it
changes no verdict: strict EX is still the score. Needs the PostgreSQL `score_pg.py` needs.

    relaxed.py --work work/pilot-scale4 --arms ddlp4,ddlm,annm,annl
"""
import argparse
import collections
import json
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "pilot"))
import score_pg                                                            # noqa: E402
import score as pilot                                                      # noqa: E402

strict_norm = score_pg.norm


def raw(v):
    if isinstance(v, bool):
        return v
    return float(v) if isinstance(v, (int, float, Decimal)) else strict_norm(v)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--work", default=os.path.join(HERE, "work", "pilot-scale4"))
    p.add_argument("--arms", default="ddlp4,ddlm,annm,annl")
    args = p.parse_args(argv)
    work = os.path.abspath(args.work)
    arms = args.arms.split(",")
    data = os.path.join(HERE, "data")
    gt = {r["instance_id"]: r for r in map(json.loads, open(os.path.join(
        data, "livesqlbench_large_v1_gt.jsonl")))}
    qs = {q["instance_id"]: q for q in map(json.loads, open(os.path.join(
        data, "livesqlbench_large_v1_data.jsonl")))}
    sample = json.load(open(os.path.join(work, "sample.json")))
    answers = {arm: score_pg.load_arm(os.path.join(work, arm)) for arm in arms}
    conns, tally = {}, {arm: collections.Counter() for arm in arms}
    questions = collections.defaultdict(set)
    for db, ids in sample.items():
        conns[db] = score_pg.connect(score_pg.DSN, db)
        for qid in ids:
            gold = score_pg.gold_sql(gt[qid])
            ordered = bool((qs[qid].get("conditions") or {}).get("order"))
            score_pg.norm = strict_norm
            want = score_pg.rows(conns[db], gold)
            score_pg.norm = raw
            want_raw = score_pg.rows(conns[db], gold)
            if isinstance(want, str):
                continue
            for arm in arms:
                ans = (answers[arm].get(qid) or (db, None))[1]
                if not ans:
                    continue
                score_pg.norm = strict_norm
                got = score_pg.rows(conns[db], ans)
                score_pg.norm = raw
                got_raw = score_pg.rows(conns[db], ans)
                if isinstance(got, str):
                    continue
                strict = got == want if ordered else sorted(got, key=str) == sorted(want, key=str)
                if strict:
                    tally[arm]["strict"] += 1
                    continue
                rule = pilot.relaxed_ex(got_raw, want_raw, ordered=ordered)
                if rule is not None:
                    name = ",".join(rule) or "rounding at two places"
                    tally[arm][name] += 1
                    questions[name].add(qid)
    for arm in arms:
        t = tally[arm]
        print("%-8s strict %3d  relaxed adds %3d  %s" % (
            arm, t["strict"], sum(n for k, n in t.items() if k != "strict"),
            {k: n for k, n in sorted(t.items()) if k != "strict"}))
    added = sum(n for t in tally.values() for k, n in t.items() if k != "strict")
    print("%d answers added, on %d questions" % (added, len(set().union(*questions.values()))))


if __name__ == "__main__":
    main()
