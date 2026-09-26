#!/usr/bin/env python3
"""Rule 9c against 1,122 real references: does reading the data beat reading the names?

Finding 84 measured name-based inference (rule 9) here at **3% recall**, and diagnosed it
exactly: 95% of these references are not spelled like the key they point at --
`personnel_skills.VerifiedBySupervisorRef` at `personnel.crewregistry`. The rule was doing
what it says; its premise does not hold on schemas named the way enterprises name them.

Rule 9c does not read names. It reads the population: every value of a candidate column
present in some table's key, scored on containment, coverage, spread and whether the column
is its own key. That is the rule that should survive, and until the dumps arrived it could not
be tested -- the public release ships three rows per table.

Strip every declared foreign key, run rule 9c over the real data, and compare with the 1,122
the catalogue declares. `--ignore-names` is the honest setting here for the same reason the
rule matters here: name evidence is worth nothing on this corpus, and leaving it on would
measure a hybrid rather than the data.

    refs_probe.py [--db NAME] [--names] [-v]
"""

import argparse
import collections
import copy
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "reverse"))

import catalog as catalog_mod        # noqa: E402
import population as population_mod  # noqa: E402

DBDIR = os.path.join(HERE, "work", "db")
THRESHOLDS = (0.0, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)


def declared(cat):
    out = set()
    for t in cat.tables:
        for fk in t.foreign_keys:
            for c in fk.columns:
                out.add((t.name.casefold(), c.casefold(), fk.ref_table.casefold()))
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("--names", action="store_true",
                   help="let rule 9c use name evidence too (default: data only)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    dbs = sorted(f[:-7] for f in os.listdir(DBDIR) if f.endswith(".sqlite"))
    if args.db:
        dbs = [d for d in dbs if args.db in d]

    print("%-34s %7s %7s %7s %8s %9s %7s" % (
        "database", "truth", "found", "right", "recall", "precision", "secs"))
    print("-" * 84)
    tot = collections.Counter()
    wrong = []
    for db in dbs:
        path = os.path.join(DBDIR, "%s.sqlite" % db)
        cat = catalog_mod.from_sqlite(path)
        truth = declared(cat)

        stripped = copy.deepcopy(cat)
        for t in stripped.tables:
            t.foreign_keys = []
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        t0 = time.time()
        try:
            analysis, _, refs = population_mod.recover(conn, stripped,
                                                       ignore_names=not args.names)
        except Exception as e:                                          # noqa: BLE001
            print("%-34s %7d  %s: %s" % (db[:34], len(truth), type(e).__name__, str(e)[:40]))
            conn.close()
            continue
        conn.close()
        secs = time.time() - t0

        # Two gates, from one analysis. `apply_references` requires `corroborated`, which is
        # name evidence -- so with --ignore-names it applies nothing at all, by construction.
        # The second gate is what the data alone supports.
        gates = {
            "applied": {(t.casefold(), c.casefold(), target.casefold())
                        for t, cols, target, _s, _sig in refs for c in cols},
            "data": {(f.table.casefold(), f.columns[0].casefold(), f.target_table.casefold())
                     for f in analysis.of_kind("inclusion")
                     if f.preferred and f.significant},
        }
        # The score is 0..6, how far the signals agree. `preferred + significant` takes every
        # candidate regardless; a threshold on top of it trades recall for precision, and the
        # question is whether any point on that curve is good enough to apply silently.
        for thr in THRESHOLDS:
            hits = {(f.table.casefold(), f.columns[0].casefold(), f.target_table.casefold())
                    for f in analysis.of_kind("inclusion")
                    if f.preferred and f.significant and f.score >= thr}
            tot["thr%.1f.found" % thr] += len(hits)
            tot["thr%.1f.right" % thr] += len(truth & hits)
        for name, found in gates.items():
            right = truth & found
            tot[name + ".found"] += len(found)
            tot[name + ".right"] += len(right)
            if name == "data":
                wrong += [(db,) + x for x in sorted(found - truth)]
        found, right = gates["data"], truth & gates["data"]
        print("%-34s %7d %7d %7d %7.0f%% %8.0f%% %7.0f" % (
            db[:34], len(truth), len(found), len(right),
            100.0 * len(right) / max(len(truth), 1),
            100.0 * len(right) / max(len(found), 1), secs))
        tot["truth"] += len(truth)
    print("-" * 84)
    for name, label in (("data", "preferred + significant (data alone)"),
                        ("applied", "what apply_references applies today")):
        f, r = tot[name + ".found"], tot[name + ".right"]
        print("%-38s %7d %7d %7.0f%% %8.0f%%" % (
            label, f, r, 100.0 * r / max(tot["truth"], 1), 100.0 * r / max(f, 1)))
    print("\nby score threshold (the gate `apply_references` could use instead of names):")
    print("   %-10s %8s %8s %8s %10s" % ("score >=", "found", "right", "recall", "precision"))
    for thr in THRESHOLDS:
        f, r = tot["thr%.1f.found" % thr], tot["thr%.1f.right" % thr]
        print("   %-10.1f %8d %8d %7.0f%% %9.0f%%" % (
            thr, f, r, 100.0 * r / max(tot["truth"], 1), 100.0 * r / max(f, 1)))
    print("\ntruth: %d declared references over %d databases" % (tot["truth"], len(dbs)))
    print("rule 9 (names only, finding 84) recovered 37 of 1,122 -- 3%% at 84%% precision.")
    if wrong and args.verbose:
        print("\nfound but not declared (a reference the catalogue does not have is not "
              "necessarily wrong -- it may be one nobody declared):")
        for db, t, c, r in wrong[:25]:
            print("   %-26s %s.%s -> %s" % (db.replace("_large", ""), t, c, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
