#!/usr/bin/env python3
"""Strip the declared foreign keys and see how many rule 9 recovers.

This is the measurement Spider 2.0 could not support. Its format has no field for a key, so
all 7,860 of its tables declare none and there is nothing to score inference against; the
81%/100% on BIRD is over eleven small databases whose columns are named to match. These
schemas declare 1,228 foreign keys over 971 tables and are named the way an enterprise names
things -- `Reports_To_Tech` pointing at `TechNum`, `For_Contract_Num` at `ContractNum`, four
naming conventions in one database -- so this is the adversarial case for a name-based rule.

Rule 9 only: `--infer-keys` (rules 9b and 9c) reads the population, and the public release
ships three sample rows per table, which is not a population. Those rules are untested here,
not failing here.

    keys.py [--db NAME] [-v]
"""

import argparse
import collections
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(HERE, "work", "catalogs")
sys.path.insert(0, os.path.join(ROOT, "reverse"))

import catalog as catalog_mod         # noqa: E402
import derive as derive_mod           # noqa: E402


def reachable(cat):
    """How many declared references rule 9 could recover even in principle.

    The rule matches on exact name equality with the target's single-column primary key, so a
    reference whose column is not spelled that way is out of its reach before it runs. Quoting
    recall without this confuses a rule that is broken with a premise that does not hold.
    """
    pk = {t.name.casefold(): (t.primary_key[0] if len(t.primary_key) == 1 else None)
          for t in cat.tables}
    n = 0
    for t in cat.tables:
        for fk in t.foreign_keys:
            if len(fk.columns) != 1:
                continue
            target = pk.get(fk.ref_table.casefold())
            if target and fk.columns[0].casefold() == target.casefold():
                n += 1
    return n


def declared(cat):
    """The answer key: every declared reference, as (table, column, target)."""
    out = set()
    for t in cat.tables:
        for fk in t.foreign_keys:
            for c in fk.columns:
                out.add((t.name.casefold(), c.casefold(), fk.ref_table.casefold()))
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    files = sorted(f for f in os.listdir(WORK) if f.endswith(".json"))
    if args.db:
        files = [f for f in files if args.db in f]

    print("%-34s %7s %7s %7s %7s %8s %8s" % (
        "database", "truth", "reach", "found", "right", "recall", "precision"))
    print("-" * 86)
    tot = collections.Counter()
    wrong = []
    for f in files:
        cat = catalog_mod.from_json(os.path.join(WORK, f))
        truth = declared(cat)
        reach = reachable(cat)

        stripped = copy.deepcopy(cat)
        for t in stripped.tables:
            t.foreign_keys = []
        model, report = derive_mod.derive(stripped, infer_undeclared_fks=True)
        found = declared(stripped)

        right = truth & found
        db = f[:-5]
        print("%-34s %7d %7d %7d %7d %7.0f%% %8.0f%%" % (
            db, len(truth), reach, len(found), len(right),
            100.0 * len(right) / max(len(truth), 1),
            100.0 * len(right) / max(len(found), 1)))
        tot["reach"] += reach
        tot["truth"] += len(truth)
        tot["found"] += len(found)
        tot["right"] += len(right)
        wrong += [(db,) + x for x in sorted(found - truth)]
    print("-" * 86)
    print("%-34s %7d %7d %7d %7d %7.0f%% %8.0f%%" % (
        "total", tot["truth"], tot["reach"], tot["found"], tot["right"],
        100.0 * tot["right"] / max(tot["truth"], 1),
        100.0 * tot["right"] / max(tot["found"], 1)))
    print("\nmissed %d of %d declared references; %d of %d guesses were not declared."
          % (tot["truth"] - tot["right"], tot["truth"], len(wrong), tot["found"]))
    print("\nrule 9 matches on exact name equality with the target's primary key, and only %d of\n"
          "%d references (%.0f%%) are spelled that way. It recovered %d of those %d. The rule is\n"
          "doing what it says; the premise that a reference is named after what it points at is\n"
          "what fails here, and BIRD's 81%% was measured where that premise holds."
          % (tot["reach"], tot["truth"], 100.0 * tot["reach"] / max(tot["truth"], 1),
             tot["right"], tot["reach"]))
    if args.verbose and wrong:
        print("\nguessed but not declared (the expensive kind -- a wrong join):")
        for db, t, c, r in wrong[:25]:
            print("   %-28s %s.%s -> %s" % (db, t, c, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
