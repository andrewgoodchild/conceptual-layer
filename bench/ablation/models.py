#!/usr/bin/env python3
"""Build a conceptual model per reference set, so model quality can be varied and measured.

Finding 118 measured reference inference against the references a catalogue declares. This
asks the question behind that one: does a model built from inferred references actually cost
an author anything? It writes, for each database, the same model derived three ways --

    declared   every reference the catalogue declares (the ceiling)
    rules      what rule 9c proposes on the data alone, as shipped
    judged     the fully relaxed candidates a blind judge kept (finding 118)

-- with name inference off in all three, so the only variable is the reference set. The
models go to bench/models/<db>.refs-<variant>.ccm.json and the schema text an author reads
to bench/pilot/material/<db>.schema-refs-<variant>.txt.

    models.py [--db NAME] [--variant declared|rules|judged]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "reverse"))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
import downstream as ds              # noqa: E402  (model_with, BIRD)
import catalog as catalog_mod        # noqa: E402
import conquer as driver             # noqa: E402

MODELS = os.path.join(ROOT, "bench", "models")
MATERIAL = os.path.join(ROOT, "bench", "pilot", "material")
SWEEP = os.path.join(HERE, "work", "bird.sweep_0.json")
JUDGED = os.path.join(HERE, "work", "bird.llm-score_1to1_md1_mr1_t0.json")


def reference_sets(db):
    """(variant -> [(table, column, target)]) for one database."""
    sweep = json.load(open(SWEEP))["databases"][db]
    judged = json.load(open(JUDGED))["databases"][db]
    return {
        "declared": [tuple(x) for x in sweep["truth"]],
        "rules": [tuple(x) for x in sweep["found"]["rules@2.6"]],
        "judged": [tuple(x) for x in judged["found"]["judged"]],
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("--variant", action="append")
    args = p.parse_args(argv)
    dbs = sorted(json.load(open(SWEEP))["databases"])
    if args.db:
        dbs = [d for d in dbs if args.db in d]
    print("%-26s %-10s %7s %8s %8s" % ("database", "variant", "refs", "concepts", "facts"))
    for db in dbs:
        cat = catalog_mod.from_sqlite(os.path.join(ds.BIRD, db, db + ".sqlite"))
        for variant, refs in reference_sets(db).items():
            if args.variant and variant not in args.variant:
                continue
            model = ds.model_with(cat, refs)
            mpath = os.path.join(MODELS, "%s.refs-%s.ccm.json" % (db, variant))
            with open(mpath, "w") as fh:
                json.dump(model, fh, indent=1)
            text = driver.describe(model)
            with open(os.path.join(MATERIAL, "%s.schema-refs-%s.txt" % (db, variant)), "w") as fh:
                fh.write(text)
            facts = sum(1 for c in model["concepts"] if c["kind"] == "fact")
            print("%-26s %-10s %7d %8d %8d"
                  % (db, variant, len(refs), len(model["concepts"]), facts), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
