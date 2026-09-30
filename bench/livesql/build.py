#!/usr/bin/env python3
"""Reverse engineer all 18 LiveSQLBench databases and measure what the abstraction ladder does.

Finding 69 measured Bird's level-2 summary as a prompt and got nothing -- 68 against the bare
DDL's 68 on BIRD. The standing objection was that BIRD is too small for a summary to matter:
7 tables, 54 columns, a 5 KB verbalisation anybody can read whole. These schemas are 54 tables
and 986 columns, so this is the regime the objection names.

Nothing here needs gold SQL, which is why it can run today. It answers three questions:

    does it build      52 PostgreSQL tables through a reverse engineer that has only ever
                       seen SQLite, via a catalogue fixture rather than a connection
    does it compress   fact types at each rung of the ladder, and the verbalisation in bytes
    what is lost       the worklist -- blockers and refinements -- at this scale

    build.py [--db NAME] [--level N]
    build.py --profiled [--db NAME]      the same models, profiled from the rows
"""

import argparse
import collections
import glob
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "data")
WORK = os.path.join(HERE, "work")
sys.path.insert(0, os.path.join(ROOT, "model"))

sys.path.insert(0, os.path.join(ROOT, "reverse"))

import abstract as abstract_mod       # noqa: E402
import forml as forml_mod             # noqa: E402
import catalog as catalog_mod         # noqa: E402
import derive as derive_mod           # noqa: E402
import jsonshape                      # noqa: E402


def databases():
    """Every database directory `fetch.sh` laid down.

    A database is a directory carrying the schema file the catalogue reads. `data/` also
    holds `dumps/`, which arrived later and is the PostgreSQL dumps rather than a database,
    and listing every subdirectory swept it in and failed the whole build on it.
    """
    return sorted(d for d in os.listdir(DATA)
                  if os.path.isdir(os.path.join(DATA, d))
                  and glob.glob(os.path.join(DATA, d, "*.txt"))
                  + glob.glob(os.path.join(DATA, d, "*.json")))


def json_shapes(db, cat):
    """The documents' shapes: the declared fields, typed from the rows where the copy has them."""
    declared = json.load(open(cat.replace(".json", ".jsonfields.json")))
    shapes = jsonshape.from_fields(
        {tuple(k.split("|", 1)): v for k, v in declared.items()})
    # The declaration names the fields; the copy `load.py` makes holds the rows. Read
    # the documents there and let the population type what the gloss did not: a
    # stellar mass whose gloss did not lead with REAL was declared text, and a text
    # mass projects as '1.05' against the gold's 1.05 (finding 162). The data types a
    # field only when it has seen a value; a declared type stands where it has not.
    copy = os.path.join(WORK, "db", "%s.sqlite" % db)
    if os.path.exists(copy):
        conn = sqlite3.connect("file:%s?mode=ro" % copy, uri=True)
        try:
            seen = jsonshape.read(conn, catalog_mod.from_json(cat))
        finally:
            conn.close()
        for key, (shape, fields, why) in seen.items():
            if shape != "record":
                continue
            typed = {tuple(f["path"]): f["dataType"] for f in fields
                     if f["dataType"] != "text"}
            if key not in shapes:
                shapes[key] = (shape, fields, why)
                continue
            merged = [dict(f, dataType=typed.get(tuple(f["path"]), f["dataType"]))
                      for f in shapes[key][1]]
            known = {tuple(f["path"]) for f in merged}
            merged += [f for f in fields if tuple(f["path"]) not in known]
            shapes[key] = ("record", merged, shapes[key][2] + "; typed from the rows")
    return shapes


# What a profiled model reads from the rows: the flags the SQLite tier's models were built
# with (finding 156), less the two that change the model's shape rather than describe it --
# `--infer-keys` and `--infer-json`, whose work the catalogue and `json_shapes` already do.
PROFILE = ["infer_domains", "infer_enforced", "infer_partitions", "merge_domains", "profile",
           "infer_keys",
           "expand_names", "infer_identifiers"]


def build_profiled(db, out="models-profiled"):
    """The model `build` makes, and what the rows say about it: value domains, cautions,
    partitions, the references the data upholds. Written to `work/models-profiled/`.

    Finding 163 ran SQL writers on `build`'s models and found the description added nothing
    beside the DDL -- and those models were built from a catalogue fixture, so they carry
    no profiling at all, the part BIRD's models had and the SQL writers there used. This is
    the same model with that part added, so the arm can be re-run with nothing else moved:
    the catalogue and the documents are `build`'s own; only the population passes are new,
    and they read the rows from `load.py`'s SQLite copy, the same rows as the server's.
    """
    ccm = os.path.join(WORK, out, "%s.ccm.json" % db)
    if os.path.exists(ccm):
        return ccm
    build(db)                                   # the catalogue, if it is not there yet
    cat = os.path.join(WORK, "catalogs", "%s.json" % db)
    copy = os.path.join(WORK, "db", "%s.sqlite" % db)
    if not os.path.exists(copy):
        raise SystemExit("%s: no SQLite copy to profile; run load.py %s" % (db, db))
    import argparse as _ap
    import reverse as reverse_mod
    flags = {f: False for n, flag, _, _, _ in reverse_mod.PASSES
             for f in reverse_mod._flags_of(flag)}
    flags.update({f: True for f in PROFILE})
    args = _ap.Namespace(sqlite=copy, dialect="postgresql", glossary=None, infer_fks=False,
                         ignore_names=False, **flags)
    b = reverse_mod.Build(args, catalog_mod.from_json(cat), copy)
    b.json_shapes = json_shapes(db, cat)
    for name, flag, _, _, run in reverse_mod.PASSES:
        if reverse_mod.selected(args, flag):
            run(b)
    # The value domains inside the documents. The document-domains pass needs --infer-json,
    # which PROFILE leaves out because `json_shapes` has already opened the documents -- so
    # until finding 166 no profiled model carried a single domain inside a JSON column, which
    # is where these databases keep most of their codes.
    import population as population_mod
    population_mod.apply_document_domains(b.data(), b.model, b.report)
    b.conn.close()
    model = b.model
    model["name"] = db
    model["_comment"].append("Built by bench/livesql/build.py --profiled: the catalogue "
                             "fixture and documents of `build`, profiled from %s with %s"
                             % (os.path.basename(copy), ", ".join(PROFILE)))
    os.makedirs(os.path.dirname(ccm), exist_ok=True)
    json.dump(model, open(ccm, "w"), indent=1)
    json.dump(b.report.as_dict(), open(ccm.replace(".ccm.json", ".report.json"), "w"), indent=1)
    return ccm


def build(db, with_json=True, dialect="postgresql"):
    """Catalogue then model. Returns the CCM path, rebuilding only what is missing.

    Rule 12 runs from the shipped `fields_meaning` rather than from a population: the public
    release has no database, only three sample rows per table, and three rows cannot tell a
    stable key from a coincidence. What it can do is take a field schema someone wrote down,
    which is what `jsonshape.from_fields` is for. Running it against the real PostgreSQL
    dumps would exercise the classifier as well, and would be the stronger test.
    """
    # PostgreSQL models go to the plain name: that is the engine these questions are graded
    # on. SQLite models go beside them because `load.py`'s copies are the only executor we
    # have until a server is up, and a Postgres model does not run on them -- three answers
    # in `solar_panel_large` stopped executing the moment the dialect was corrected.
    suffix = "" if with_json else "-nojson"
    suffix += "" if dialect == "postgresql" else "-" + dialect
    cat = os.path.join(WORK, "catalogs", "%s.json" % db)
    ccm = os.path.join(WORK, "models", "%s%s.ccm.json" % (db, suffix))
    if os.path.exists(ccm):
        return ccm
    os.makedirs(os.path.dirname(cat), exist_ok=True)
    os.makedirs(os.path.dirname(ccm), exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "catalogue.py"),
                    os.path.join(DATA, db), "-o", cat], check=True,
                   stdout=subprocess.DEVNULL)
    shapes = json_shapes(db, cat) if with_json else {}
    # LiveSQLBench runs on PostgreSQL, and the dialect seam is not cosmetic: `derive`
    # defaults to SQLite, which spells division `CAST(x AS DOUBLE)` (a *syntax error* on
    # Postgres, not a wrong answer), reads documents with `json_extract` (which Postgres does
    # not have), reads dates with `strftime` (likewise), and strips `fn.median` outright
    # because SQLite has no ordered-set aggregate. Every model here was built that way, and
    # it went unnoticed because the pilot executes against the SQLite copies `load.py` makes
    # for analysis. Nothing would have run against the server these questions are graded on.
    model, report = derive_mod.derive(catalog_mod.from_json(cat), json_shapes=shapes,
                                      dialect=dialect)
    model["name"] = db
    json.dump(model, open(ccm, "w"), indent=1)
    json.dump(report.as_dict(), open(ccm.replace(".ccm.json", ".report.json"), "w"), indent=1)
    return ccm


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("--dialect", default="postgresql",
                   help="engine the templates target. LiveSQLBench runs on "
                        "PostgreSQL, which is the default; `--dialect sqlite` "
                        "builds the models `compare.py` executes against the "
                        "copies load.py makes, which is all there is until a "
                        "server is up.")
    p.add_argument("--levels", type=int, default=4)
    p.add_argument("--no-json", action="store_true",
                   help="build without rule 12, to measure what it adds")
    p.add_argument("--profiled", action="store_true",
                   help="build the profiled models instead (`build_profiled`), into "
                        "work/models-profiled/, and stop")
    p.add_argument("--profiled-dir", default="models-profiled",
                   help="the directory under work/ the profiled models go in; a new one "
                        "leaves an earlier round's models as they were")
    args = p.parse_args(argv)

    dbs = [d for d in databases() if not args.db or args.db in d]
    if args.profiled:
        for db in dbs:
            print(build_profiled(db, args.profiled_dir))
        return 0
    print("%-34s %6s %7s %s" % ("database", "facts", "flat KB", "fact types by level"))
    print("-" * 84)
    tot = collections.Counter()
    rows = []
    for db in dbs:
        model = json.load(open(build(db, with_json=not args.no_json,
                                     dialect=args.dialect)))
        flat = "\n".join(forml_mod.verbalize_model(model))
        ladder = abstract_mod.levels(model)
        counts = [len(l.facts) for l in ladder[:args.levels]]
        print("%-34s %6d %7.1f %s" % (
            db, counts[0] if counts else 0, len(flat) / 1024.0,
            "  ".join("L%d %4d" % (i + 1, c) for i, c in enumerate(counts))))
        rows.append((db, counts, len(flat)))
        tot["facts"] += counts[0] if counts else 0
        tot["flat"] += len(flat)
        for i, c in enumerate(counts):
            tot["L%d" % (i + 1)] += c
    print("-" * 84)
    print("%-34s %6d %7.1f %s" % (
        "total", tot["facts"], tot["flat"] / 1024.0,
        "  ".join("L%d %4d" % (i + 1, tot["L%d" % (i + 1)]) for i in range(args.levels)
                  if tot["L%d" % (i + 1)])))
    base = tot["L1"] or 1
    print("\ncompression:     %s" % "  ".join(
        "L%d %.0f%%" % (i + 1, 100.0 * tot["L%d" % (i + 1)] / base)
        for i in range(args.levels) if tot["L%d" % (i + 1)]))

    blockers = refinements = 0
    rule12 = collections.Counter()
    for db in dbs:
        rep = os.path.join(WORK, "models", "%s%s.report.json"
                           % (db, "" if not args.no_json else "-nojson"))
        if not os.path.exists(rep):
            continue
        r = json.load(open(rep))
        blockers += len(r.get("blockers", []))
        refinements += len(r.get("refinements", []))
        for item in r.get("refinements", []):
            if item.get("rule") == "rule 12":
                rule12["record" if "read as a record" in item["message"]
                       else "map" if "keys are data" in item["message"] else "bag"] += 1
    print("worklist:        %d blockers, %d refinements over %d databases"
          % (blockers, refinements, len(dbs)))
    if rule12:
        print("rule 12:         %s" % ", ".join("%s %d" % kv for kv in rule12.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
