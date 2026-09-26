#!/usr/bin/env python3
"""The large-schema round: does the model's English still help when the schema is big?

BIRD's databases are 7 tables and 54 columns, and there the level-2 abstraction was worth
exactly nothing over the bare DDL (finding 69). The obvious objection is that BIRD is too small
for a summary to matter -- its flat verbalisation is 5 KB, which anyone can read. Spider 2.0's
local slice is the other regime: 87 to 341 fact types, a flat verbalisation of 6 to 17 KB per
database, and the summary a third of that.

Three arms over the twelve largest, all written by SQL writers, differing in one material:

    direct      the DDL
    flat        the DDL and the full flat FORML verbalisation
    abstract    the DDL and the same model at Bird's second level of abstraction

All three run under one prompt, written once. That is not a detail: the first version of the
BIRD round compared a new arm against recorded arms whose prompt could not be reproduced, and
attributed to the material a gap that was mostly the prompt.

**What this round can and cannot settle.** Sixty questions, and `calibrate.py` reports that 9 of
the 24 local tasks that ship gold SQL cannot reproduce their own recorded answer. A two-point
difference is a question and a half and is not measurable here. A large difference is, and
after a zero on BIRD a large difference is the only interesting outcome.

    build.py [--arm A] [--min-facts N]
"""

import argparse
import collections
import json
import os
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))

import abstract as abstract_mod       # noqa: E402
import forml as forml_mod             # noqa: E402

LITE = os.path.join(ROOT, "bench/spider2/spider2-lite")
DBS = os.path.join(LITE, "resource/databases/spider2-localdb")
MODELS = os.path.join(ROOT, "bench/spider2-models")
WORK = os.path.join(HERE, "work")
DB_FILE = {"Db-IMDB": "DB_IMDB"}

ARMS = {"direct": ["ddl"], "flat": ["ddl", "forml"], "abstract": ["ddl", "forml_abstract"]}

TRY = """#!/bin/sh
# Run a candidate SQL statement and show what it returns. Says nothing about correctness.
exec sqlite3 -header -readonly "file:%s?mode=ro" "$1"
"""


def db_path(db):
    return os.path.join(DBS, DB_FILE.get(db, db) + ".sqlite")


def ddl_of(db):
    with sqlite3.connect("file:%s?mode=ro" % db_path(db), uri=True) as conn:
        rows = conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
                            "AND type IN ('table','view') ORDER BY type DESC, name").fetchall()
    return ";\n\n".join(r[0].strip() for r in rows) + ";\n"


def tasks(min_facts):
    """(db, [task]) for every local database whose model is at least this big."""
    out = collections.defaultdict(list)
    for line in open(os.path.join(LITE, "spider2-lite.jsonl")):
        row = json.loads(line)
        if not row["instance_id"].startswith("local"):
            continue
        model = os.path.join(MODELS, "%s.ccm.json" % row["db"])
        if not (os.path.exists(model) and os.path.exists(db_path(row["db"]))):
            continue
        out[row["db"]].append(row)
    keep = {}
    for db, rows in out.items():
        m = json.load(open(os.path.join(MODELS, "%s.ccm.json" % db)))
        if len([c for c in m["concepts"] if c.get("kind") == "fact"]) >= min_facts:
            keep[db] = rows
    return keep


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arm", action="append", choices=sorted(ARMS))
    p.add_argument("--min-facts", type=int, default=87,
                   help="only databases at least this large; 87 is the twelve biggest")
    args = p.parse_args(argv)

    corpus = tasks(args.min_facts)
    for arm in (args.arm or sorted(ARMS)):
        n = 0
        for db, rows in sorted(corpus.items()):
            d = os.path.join(WORK, arm, db)
            os.makedirs(d, exist_ok=True)
            if not os.path.exists(os.path.join(d, "answers.json")):
                json.dump([], open(os.path.join(d, "answers.json"), "w"))
            json.dump([{"instance_id": r["instance_id"], "question": r["question"],
                        **({"external_knowledge": r["external_knowledge"]}
                           if r.get("external_knowledge") not in (None, "", "None") else {})}
                       for r in rows],
                      open(os.path.join(d, "questions.json"), "w"), indent=1)
            # `external_knowledge` names a document, not a string: without it the question
            # cannot be answered at all, so it travels with the question.
            for r in rows:
                doc = r.get("external_knowledge")
                if doc in (None, "", "None"):
                    continue
                src = os.path.join(LITE, "resource/documents", doc)
                if os.path.exists(src):
                    shutil.copy(src, os.path.join(d, doc))
            model = json.load(open(os.path.join(MODELS, "%s.ccm.json" % db)))
            for want in ARMS[arm]:
                if want == "ddl":
                    open(os.path.join(d, "%s.ddl.sql" % db), "w").write(ddl_of(db))
                elif want == "forml":
                    open(os.path.join(d, "%s.forml.md" % db), "w").write(
                        "# What the model says\n\nEvery constraint in the conceptual model of "
                        "this database, as FORML 2 sentences.\n\n"
                        + "\n".join("- " + s for s in forml_mod.verbalize_model(model)) + "\n")
                else:
                    open(os.path.join(d, "%s.forml-abstract.md" % db), "w").write(
                        abstract_mod.summarise(model, 2) + "\n")
            script = os.path.join(d, "try")
            open(script, "w").write(TRY % db_path(db))
            os.chmod(script, 0o755)
            n += len(rows)
        print("%-10s %2d databases, %d questions" % (arm, len(corpus), n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
