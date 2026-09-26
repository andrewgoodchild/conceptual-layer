#!/usr/bin/env python3
"""Does Bird's abstraction summarise away the tables the questions need?

Finding 69 measured the level-2 summary as a *prompt* and got nothing: 68 against the bare
DDL's 68 on BIRD. The obvious next question is whether that is because BIRD's schemas are too
small for a summary to matter, or because the summary drops something questions need. The
second is checkable without asking a model anything at all.

For each question the benchmark gives gold SQL, and the gold names the tables the answer
touches. So: walk up the abstraction ladder and, at each rung, ask what share of questions have
every table they need still present. A summary that keeps 100% is lossless for querying and its
failure as a prompt is about *shape*; a summary that keeps 60% is simply missing things.

This is sound where an accuracy arm on Spider 2.0 is not. A gold query that cannot reproduce
its own recorded answer -- 9 of the 24 that ship SQL -- still names the right tables, so the
annotation problem that makes Spider 2.0 unscoreable does not touch this measurement.

    abstraction_recall.py [--corpus bird|spider2] [-v]
"""

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, HERE)

import abstract as abstract_mod       # noqa: E402
import linking                        # noqa: E402


def tables_at(model, level):
    """The table names a level's concepts can still reach."""
    s = abstract_mod.Schema(model)
    ladder = abstract_mod.levels(model)
    lvl = ladder[min(level, len(ladder)) - 1]
    ct = linking.concept_tables(model)
    seen = set()
    for oid in lvl.objects:
        seen |= ct.get(oid, set())
    for fid in lvl.facts:
        seen |= ct.get(fid, set())
        for r in s.roles(fid):
            seen |= ct.get(s.player[r], set())
    # everything clustered under a shown type is still described by that type's entry
    for owner, facts in lvl.clusters.items():
        if owner not in lvl.objects:
            continue
        seen |= ct.get(owner, set())
        for fid in facts:
            seen |= ct.get(fid, set())
            for r in s.roles(fid):
                seen |= ct.get(s.player[r], set())
    return seen, len(ladder)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", default="bird", choices=("bird", "spider2"))
    p.add_argument("--levels", type=int, default=4)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    corpus = list(linking.spider2() if args.corpus == "spider2" else linking.bird())
    if not corpus:
        print("no %s corpus here" % args.corpus)
        return 2

    models, cache = {}, {}
    kept = collections.Counter()
    asked = 0
    missing = collections.defaultdict(collections.Counter)
    for db, path, question, sql in corpus:
        if not os.path.exists(path):
            continue
        if db not in models:
            models[db] = json.load(open(path))
        model = models[db]
        tabs = set(linking.tables_of(model).values())
        want = linking.gold_tables(sql, tabs)
        if not want:
            continue
        asked += 1
        for level in range(1, args.levels + 1):
            key = (db, level)
            if key not in cache:
                cache[key] = tables_at(model, level)
            have, rungs = cache[key]
            if want <= have:
                kept[level] += 1
            else:
                for t in sorted(want - have):
                    missing[level][t] += 1

    print("%s: %d questions over %d databases\n" % (args.corpus, asked, len(models)))
    print("%-7s %-26s %s" % ("level", "every gold table present", "model size"))
    print("-" * 58)
    for level in range(1, args.levels + 1):
        sizes = [len(abstract_mod.levels(m)[min(level, len(abstract_mod.levels(m))) - 1].facts)
                 for m in models.values()]
        print("%-7d %3d%%  (%3d of %3d)          %d fact types shown"
              % (level, 100.0 * kept[level] / asked, kept[level], asked, sum(sizes)))
    if args.verbose:
        for level in range(2, args.levels + 1):
            if missing[level]:
                print("\nlevel %d most often missing: %s" % (
                    level, ", ".join("%s (%d)" % (t, n)
                                     for t, n in missing[level].most_common(6))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
