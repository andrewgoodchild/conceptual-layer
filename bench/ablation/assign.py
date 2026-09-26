#!/usr/bin/env python3
"""Where the correct target sits in each column's ranking, and what a shortlist would buy.

Finding 118 left one question open. 77% of the references the inclusion search misses are
columns it *did* propose, at a different target -- so the search finds the column and the
assignment picks the wrong parent. But knowing the right target is somewhere in the
candidate list is not the same as knowing it is reachable: if it ranks eleventh, a
shortlist of three does not help.

This reads what `refs.py rank` recorded -- every containment per source column, ranked by
score -- and asks:

    rank        where the declared target sits in that ranking (1 = the search already
                proposes it; absent = the search never found that containment at all)
    top-k       recall and precision if the best k targets per column were kept
    tie-breaks  the same, with the candidates reordered by evidence the score under-weights:
                `name` prefers a target the column is named after, `1to1` prefers a target
                whose key the column covers entirely, `both` applies name then 1to1

    assign.py work/livesql.rank.json [work/bird.rank.json ...]

No database is read: the ranking file has everything, so an ordering can be tried in a
second rather than a pass.
"""
import collections
import json
import os
import sys

KS = (1, 2, 3, 5, 10)


def orderings(cands):
    """The candidate orderings to compare, each a list ranked best-first."""
    # One entry per target: a table declaring its primary key as a unique constraint too
    # used to yield the same containment twice, which counted twice here.
    best = {}
    for c in cands:
        k = (c["target"].casefold(), c["key"].casefold())
        if k not in best or c["score"] > best[k]["score"]:
            best[k] = c
    cands = list(best.values())
    by_score = sorted(cands, key=lambda c: -c["score"])
    # A column named after the table it points at, which is the one signal Zhang et al. found
    # value distributions do not subsume -- and which the data-only weights score at zero.
    by_name = sorted(cands, key=lambda c: (-max(c["name_pk_table"], c["name_pk_col"]), -c["score"]))
    # Covering the target's key entirely is what a child table of a lookup does; a
    # coincidental containment usually covers a fraction.
    def cover(c):
        return 1.0 if c["distinct"] and c["rows"] and c["distinct"] >= c["rows"] else 0.0
    by_both = sorted(cands, key=lambda c: (-max(c["name_pk_table"], c["name_pk_col"]),
                                           -cover(c), -c["score"]))
    return {"score": by_score, "name": by_name, "both": by_both}


def main(argv=None):
    paths = (argv or sys.argv[1:]) or ["bench/ablation/work/livesql.rank.json"]
    for path in paths:
        if not os.path.exists(path):
            print("missing:", path)
            continue
        rec = json.load(open(path))
        ranks = collections.Counter()
        hits = collections.Counter()      # (ordering, k) -> right
        found = collections.Counter()     # (ordering, k) -> proposed
        truth_n = 0
        for db, e in rec["databases"].items():
            truth = {tuple(x) for x in e["truth"]}
            truth_n += len(truth)
            want = collections.defaultdict(set)
            for t, c, target in truth:
                want[(t, c)].add(target)
            for col, cands in e["columns"].items():
                t, c = col.rsplit(".", 1)
                key = (t.casefold(), c.casefold())
                targets = want.get(key, set())
                orders = orderings(cands)
                if targets:
                    pos = next((i + 1 for i, x in enumerate(orders["score"])
                                if x["target"].casefold() in targets), None)
                    ranks[pos if pos and pos <= 10 else ("11+" if pos else "absent")] += 1
                for name, order in orders.items():
                    for k in KS:
                        for x in order[:k]:
                            found[(name, k)] += 1
                            if x["target"].casefold() in targets:
                                hits[(name, k)] += 1
            # references whose source column the search never looked at
            seen = {tuple(col.rsplit(".", 1)) for col in e["columns"]}
            seen = {(t.casefold(), c.casefold()) for t, c in seen}
            for t, c, _ in truth:
                if (t, c) not in seen:
                    ranks["no candidate for the column"] += 1
        print("=== %s (%d declared references) ===" % (os.path.basename(path), truth_n))
        print("where the declared target sits in the score ranking:")
        for k in list(range(1, 11)) + ["11+", "absent", "no candidate for the column"]:
            if ranks.get(k):
                label = "rank %s" % k if isinstance(k, int) else str(k)
                print("   %-30s %5d  %3.0f%%" % (label, ranks[k], 100.0 * ranks[k] / max(truth_n, 1)))
        print("recall and precision of a shortlist of k, by ordering:")
        print("   %-8s %4s %8s %8s %9s %11s" % ("order", "k", "kept", "right", "recall", "precision"))
        for name in ("score", "name", "both"):
            for k in KS:
                f, r = found[(name, k)], hits[(name, k)]
                print("   %-8s %4d %8d %8d %8.0f%% %10.0f%%"
                      % (name, k, f, r, 100.0 * r / max(truth_n, 1), 100.0 * r / max(f, 1)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
