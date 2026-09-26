#!/usr/bin/env python3
"""Regenerate `material/<db>.*`: what a pilot arm is shown about each database.

Every per-database file here is a listing of one of BIRD's eleven databases -- its DDL, the
reverse-engineered model's schema listing and FORML sentences, and the semantic model's --
so none is distributed with this repository: the schemas are BIRD's, and each file is a
function of the models `bench/run.sh` builds from them. The strategy prompts and the frozen
primer beside them are this project's own and are tracked.

    bench/run.sh                       # bench/models/<db>.ccm.json and <db>.semantic.ccm.json
    python3 bench/pilot/material.py    # ddl.sql, schema.txt, schema-sem.txt, forml.md,
                                       # forml-full.md and forml-sem.md, per database
    python3 bench/ablation/models.py   # the three schema-refs-<variant>.txt listings

A regenerated listing is the current compiler's, not byte-for-byte what the recorded arms
were shown: `--schema` has grown an Identification section since. Each arm's `work/` copy was
the record of that text, and is local for the same reason this is.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MODELS = os.path.join(ROOT, "bench", "models")
DBS = os.path.join(ROOT, "bench", "bird", "minidev", "MINIDEV", "dev_databases")
MAT = os.path.join(HERE, "material")
CONQUER = os.path.join(ROOT, "conquer", "conquer.py")
sys.path.insert(0, os.path.join(ROOT, "model"))

HEAD = {
    "forml": "## What the model says\n\nEvery constraint above, in FORML 2 — the controlled "
             "English NORMA verbalizes into. Read these as claims about the business, and "
             "reject the ones that are not true of it.\n",
    "forml-full": "# What the model says\n\nEvery constraint in the conceptual model of this "
                  "database, as FORML 2 sentences, the controlled English NORMA verbalises "
                  "into. Read them as claims about the business. 'Each X has some Y' means "
                  "every X has a Y (the value is never absent); 'at most one' is a "
                  "uniqueness constraint (one-to-many the other way); 'at most one manager "
                  "Employee' binds the adjective to the far type, and the corresponding "
                  "reading is `has manager`. Where a sentence is missing for a value -- no "
                  "'has some' -- that value may be absent.\n",
    "forml-sem": "# What the model says\n\nEvery constraint and every definition in the "
                 "conceptual model of this database, as FORML 2 sentences. 'Each X has some "
                 "Y' means the value is never absent; 'at most one' is a uniqueness "
                 "constraint; a sentence with IFF is a *definition* the business has made -- "
                 "a derived fact type or subtype -- and the schema listing shows it as a "
                 "reading or a derived type you can use directly.\n",
}


def forml_text(kind, model):
    import forml
    return HEAD[kind] + "\n" + "\n".join("- " + s for s in forml.verbalize_model(model)) + "\n"


def schema_text(model_path):
    return subprocess.run([sys.executable, CONQUER, model_path, "--schema"], check=True,
                          capture_output=True, text=True).stdout


def ddl_text(db_path):
    return subprocess.run(["sqlite3", db_path, ".schema"], check=True,
                          capture_output=True, text=True).stdout


def main(argv=None):
    dbs = sorted(d for d in os.listdir(DBS) if os.path.isfile(os.path.join(DBS, d, d + ".sqlite"))) \
        if os.path.isdir(DBS) else []
    if not dbs:
        print("no databases under %s: run bench/run.sh first" % os.path.relpath(DBS))
        return 1
    os.makedirs(MAT, exist_ok=True)
    made = 0
    for db in dbs:
        base = os.path.join(MODELS, db + ".ccm.json")
        sem = os.path.join(MODELS, db + ".semantic.ccm.json")
        if not os.path.exists(base):
            print("skip  %-26s no model (bench/run.sh builds it)" % db)
            continue
        model = json.load(open(base))
        out = {"ddl.sql": ddl_text(os.path.join(DBS, db, db + ".sqlite")),
               "schema.txt": schema_text(base),
               "forml.md": forml_text("forml", model),
               "forml-full.md": forml_text("forml-full", model)}
        if os.path.exists(sem):
            out["schema-sem.txt"] = schema_text(sem)
            out["forml-sem.md"] = forml_text("forml-sem", json.load(open(sem)))
        else:
            print("note  %-26s no semantic model (pilot/semantic/build.sh): "
                  "schema-sem and forml-sem not made" % db)
        for suffix, text in out.items():
            with open(os.path.join(MAT, "%s.%s" % (db, suffix)), "w") as fh:
                fh.write(text)
            made += 1
        print("ok    %-26s %s" % (db, ", ".join(sorted(out))))
    print("wrote %d files into %s" % (made, os.path.relpath(MAT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
