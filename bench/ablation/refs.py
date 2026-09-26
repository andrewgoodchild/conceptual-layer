#!/usr/bin/env python3
"""Ablations of reference inference on the 18 LiveSQLBench schemas that declare their keys.

The published pipeline this measures against (finding 118): statistics propose key
candidates and inclusion dependencies, a score thresholds them, an LLM judges what is left.
Each arm here is one of those steps switched on, scored against the 1,112 references the
catalogues declare, which the arms never see.

    names          rule 9c with name evidence, gated as `apply_references` gates it
    data           rule 9c on the data alone, preferred + significant, by score threshold
    approx         the same with approximate inclusion: TOLERANCE of the distinct values missing
    llm-export     the data arm's candidates at a low threshold, with blind evidence, for a judge
    llm-score      the candidates a judge kept (work/llm/<db>.verdicts.json), scored

    refs.py names|data|approx|llm-export|llm-score [--db NAME] [--eps 0.02] [--floor 2.0]

Results go to work/<arm>[@eps].json as the found sets per database, so arms can be compared
after the fact (union, intersection, what the judge added or removed).
"""
import argparse
import collections
import copy
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "reverse"))
import catalog as catalog_mod        # noqa: E402
import population as population_mod  # noqa: E402

DBDIR = os.path.join(ROOT, "bench", "livesql", "work", "db")
BIRD = os.path.join(ROOT, "bench", "bird", "minidev", "MINIDEV", "dev_databases")


def databases(dbdir):
    """(name, path) for a flat directory of <db>.sqlite or BIRD's <db>/<db>.sqlite."""
    out = []
    for f in sorted(os.listdir(dbdir)):
        if f.endswith(".sqlite"):
            out.append((f[:-7], os.path.join(dbdir, f)))
        elif os.path.isfile(os.path.join(dbdir, f, f + ".sqlite")):
            out.append((f, os.path.join(dbdir, f, f + ".sqlite")))
    return out
WORK = os.path.join(HERE, "work")
THRESHOLDS = (0.0, 2.0, 3.0, 3.5, 4.0)


def declared(cat):
    out = set()
    for t in cat.tables:
        for fk in t.foreign_keys:
            for c in fk.columns:
                out.add((t.name.casefold(), c.casefold(), fk.ref_table.casefold()))
    return out


def stripped_of(cat):
    s = copy.deepcopy(cat)
    for t in s.tables:
        t.foreign_keys = []
    return s


def key3(f):
    return (f.table.casefold(), f.columns[0].casefold(), f.target_table.casefold())


def samples(conn, table, col, n=5):
    try:
        rows = conn.execute('SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL LIMIT %d'
                            % (col.replace('"', '""'), table.replace('"', '""'),
                               col.replace('"', '""'), n)).fetchall()
        return [str(r[0])[:40] for r in rows]
    except sqlite3.Error:
        return []


def run_db(db, arm, args):
    path = dict(databases(args.dbdir))[db]
    cat = catalog_mod.from_sqlite(path)
    truth = declared(cat)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    population_mod.TOLERANCE = args.eps if arm == "approx" else 0.0
    if args.min_distinct is not None:
        population_mod.MIN_DISTINCT = args.min_distinct
    if args.min_rows is not None:
        population_mod.MIN_ROWS = args.min_rows
    if args.threshold is not None:
        # what `preferred` needs; the sweep starts here. The data-only path has a threshold
        # of its own (SHAPE_ONLY_THRESHOLD, 2.6) beside the one the named path uses (4.25).
        population_mod.THRESHOLD = args.threshold
        population_mod.SHAPE_ONLY_THRESHOLD = args.threshold
    t0 = time.time()
    analysis, _, refs = population_mod.recover(conn, stripped_of(cat), ignore_names=(arm != "names"))
    secs = time.time() - t0
    kinds = ("inclusion", "inclusion-1to1") if args.own_key else ("inclusion",)
    # A column that identifies its own table and is contained in another's key is the 1:1
    # subtype shape -- an entity split across tables sharing its id, which is how these
    # schemas are built -- and the rules file it apart from the evidence. `--own-key` lets
    # it count. It is the largest single class of misses on organ_transplant (30 of 47).
    incl = [f for k in kinds for f in analysis.of_kind(k) if f.preferred and f.significant]
    found = {}
    if arm == "names":
        found["applied"] = sorted({(t.casefold(), c.casefold(), target.casefold())
                                   for t, cols, target, _s, _sig in refs for c in cols})
    for thr in THRESHOLDS:
        found["thr%.1f" % thr] = sorted(key3(f) for f in incl if f.score >= thr)
    if arm == "llm-export":
        cands = []
        for f in incl:
            if f.score < args.floor:
                continue
            cands.append({
                "id": "%s.%s -> %s.%s" % (f.table, f.columns[0], f.target_table, f.target_columns[0]),
                "source_table": f.table, "source_column": f.columns[0],
                "target_table": f.target_table, "target_key": f.target_columns[0],
                "source_rows": f.rows, "source_distinct": f.distinct,
                "target_rows": analysis.row_counts.get(f.target_table),
                "score": round(f.score, 2), "signals": f.signals,
                "source_samples": samples(conn, f.table, f.columns[0]),
                "target_samples": samples(conn, f.target_table, f.target_columns[0]),
            })
        os.makedirs(os.path.join(WORK, "llm"), exist_ok=True)
        with open(os.path.join(WORK, "llm", "%s.candidates.json" % db), "w") as fh:
            json.dump({"database": db, "tables": sorted(t.name for t in cat.tables),
                       "candidates": cands}, fh, indent=1)
        found["exported"] = sorted((c["source_table"].casefold(), c["source_column"].casefold(),
                                    c["target_table"].casefold()) for c in cands)
    if arm == "llm-score":
        vpath = os.path.join(WORK, "llm", "%s.verdicts.json" % db)
        kept = set()
        if os.path.exists(vpath):
            verdicts = json.load(open(vpath))
            yes = {v["id"] for v in verdicts.get("verdicts", []) if str(v.get("verdict", "")).lower().startswith("y")}
            for f in incl:
                cid = "%s.%s -> %s.%s" % (f.table, f.columns[0], f.target_table, f.target_columns[0])
                if cid in yes:
                    kept.add(key3(f))
        found["judged"] = sorted(kept)
    conn.close()
    return truth, found, secs


def rank_db(db, args):
    """Every containment the search finds, per source column, ranked by score -- not just the
    one it would propose. `assign.py` reads this to ask where the *correct* target sits in
    that ranking, which is the question finding 118 left open: the misses are columns the
    search did propose, at another target, so is the right one second, or nowhere?"""
    path = dict(databases(args.dbdir))[db]
    cat = catalog_mod.from_sqlite(path)
    truth = declared(cat)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    population_mod.TOLERANCE = args.eps
    population_mod.THRESHOLD = population_mod.SHAPE_ONLY_THRESHOLD = 0.0
    population_mod.MIN_ROWS, population_mod.MIN_DISTINCT = 1, 1
    t0 = time.time()
    analysis, _, _ = population_mod.recover(conn, stripped_of(cat), ignore_names=True)
    secs = time.time() - t0
    by_name = {t.name.casefold(): t for t in cat.tables}
    columns = {}
    for kind in ("inclusion", "inclusion-1to1"):
        for f in analysis.of_kind(kind):
            src = by_name.get(f.table.casefold())
            col = next((c for c in src.columns if c.name == f.columns[0]), None) if src else None
            tgt = by_name.get(f.target_table.casefold())
            key = f.target_columns[0]
            # the name features, computed whether or not the data-only weights report them:
            # this is the evidence a tie-break would use, recorded so it can be tried offline
            name_table = max(population_mod._similar(f.columns[0], tgt.name),
                             population_mod._similar(f.columns[0], population_mod._stem(tgt.name)),
                             1.0 if population_mod._stem(tgt.name) in f.columns[0].casefold() else 0.0) if tgt else 0.0
            columns.setdefault("%s.%s" % (f.table, f.columns[0]), []).append({
                "target": f.target_table, "key": key, "score": round(f.score, 3),
                "signals": f.signals, "kind": kind,
                "name_pk_table": round(name_table, 3),
                "name_pk_col": round(population_mod._similar(f.columns[0], key), 3),
                "rows": f.rows, "distinct": f.distinct,
            })
    conn.close()
    for v in columns.values():
        v.sort(key=lambda c: -c["score"])
    return truth, columns, secs


SWEEP_GATES = [
    # (label, own_key, min_rows, min_distinct, threshold): the data arms, from one analysis
    ("rules",            False, None, None, None),
    ("+1to1",            True,  None, None, None),
    ("+1to1+md1+mr1",    True,  1,    1,    None),
    ("+1to1+md1+mr1+t0", True,  1,    1,    0.0),
]


def sweep_db(db, args):
    """One analysis at threshold 0 and every data gate read off it: `significant` reads the
    floors when asked and `preferred` above a threshold is a filter, so the arms that differ
    only in floors and thresholds cost one pass instead of one each."""
    path = dict(databases(args.dbdir))[db]
    cat = catalog_mod.from_sqlite(path)
    truth = declared(cat)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    population_mod.TOLERANCE = args.eps
    population_mod.THRESHOLD = population_mod.SHAPE_ONLY_THRESHOLD = 0.0
    defaults = (population_mod.MIN_ROWS, population_mod.MIN_DISTINCT)
    t0 = time.time()
    analysis, _, _ = population_mod.recover(conn, stripped_of(cat), ignore_names=True)
    secs = time.time() - t0
    conn.close()
    found = {}
    for label, own, mr, md, thr in SWEEP_GATES:
        population_mod.MIN_ROWS = defaults[0] if mr is None else mr
        population_mod.MIN_DISTINCT = defaults[1] if md is None else md
        floor = 2.6 if thr is None else thr                      # the data path's own threshold
        kinds = ("inclusion", "inclusion-1to1") if own else ("inclusion",)
        incl = [f for k in kinds for f in analysis.of_kind(k) if f.preferred and f.significant]
        for t in THRESHOLDS:
            found["%s@%.1f" % (label, max(t, floor))] = sorted(key3(f) for f in incl if f.score >= max(t, floor))
    population_mod.MIN_ROWS, population_mod.MIN_DISTINCT = defaults
    return truth, found, secs


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("arm", choices=["names", "data", "approx", "llm-export", "llm-score", "sweep",
                                   "rank"])
    p.add_argument("--db")
    p.add_argument("--dbdir", default=DBDIR, help="where the databases are (default LiveSQL; BIRD: %s)" % BIRD)
    p.add_argument("--eps", type=float, default=0.02, help="approx: share of distinct values that may dangle")
    p.add_argument("--floor", type=float, default=2.0, help="llm-export: lowest score exported")
    p.add_argument("--own-key", action="store_true",
                   help="count a table's own key contained in another's key (the 1:1 shape)")
    p.add_argument("--threshold", type=float, default=None,
                   help="the score a candidate needs to be proposed at all (the rules' 3.0 otherwise)")
    p.add_argument("--min-rows", type=int, default=None,
                   help="the row floor a population needs to be evidence (the rules' default otherwise)")
    p.add_argument("--min-distinct", type=int, default=None,
                   help="the distinct-values floor a candidate needs (the rules' default otherwise)")
    args = p.parse_args(argv)
    dbs = [name for name, _ in databases(args.dbdir)]
    if args.db:
        dbs = [d for d in dbs if args.db in d]
    corpus = "bird" if os.path.abspath(args.dbdir) == os.path.abspath(BIRD) else "livesql"
    if args.arm == "rank":
        # one pass per database, everything recorded; the arms are computed by assign.py
        dbs = [name for name, _ in databases(args.dbdir)]
        if args.db:
            dbs = [d for d in dbs if args.db in d]
        corpus = "bird" if os.path.abspath(args.dbdir) == os.path.abspath(BIRD) else "livesql"
        record = {"arm": "rank", "databases": {}}
        print("%-34s %8s %10s %8s" % ("database", "truth", "columns", "secs"))
        for db in dbs:
            try:
                truth, columns, secs = rank_db(db, args)
            except Exception as e:                                      # noqa: BLE001
                print("%-34s %s: %s" % (db[:34], type(e).__name__, str(e)[:50]), flush=True)
                continue
            print("%-34s %8d %10d %8.0f" % (db[:34], len(truth), len(columns), secs), flush=True)
            record["databases"][db] = {"truth": sorted(truth), "columns": columns}
        os.makedirs(WORK, exist_ok=True)
        out = os.path.join(WORK, "%s.rank%s.json" % (corpus, ("." + args.db) if args.db else ""))
        with open(out, "w") as fh:
            json.dump(record, fh)
        print("recorded:", os.path.relpath(out, ROOT))
        return 0
    label = args.arm + ("@%g" % args.eps if args.arm == "approx" else "") \
        + ("+1to1" if args.own_key else "") \
        + ("+md%d" % args.min_distinct if args.min_distinct is not None else "") \
        + ("+mr%d" % args.min_rows if args.min_rows is not None else "") \
        + ("+t%g" % args.threshold if args.threshold is not None else "")
    gate = {"names": "applied", "data": "thr3.0", "approx": "thr3.0", "llm-export": "exported",
            "llm-score": "judged", "sweep": "+1to1+md1+mr1+t0@3.0"}[args.arm]
    if args.arm == "sweep":
        label = "sweep@%g" % args.eps
    print("arm %s (gate %s)" % (label, gate))
    print("%-34s %7s %7s %7s %8s %9s %7s" % ("database", "truth", "found", "right", "recall", "precision", "secs"))
    print("-" * 84)
    tot = collections.Counter()
    record = {"arm": label, "gate": gate, "databases": {}}
    for db in dbs:
        try:
            truth, found, secs = sweep_db(db, args) if args.arm == "sweep" else run_db(db, args.arm, args)
        except Exception as e:                                          # noqa: BLE001
            print("%-34s %s: %s" % (db[:34], type(e).__name__, str(e)[:50]))
            continue
        got = set(map(tuple, found.get(gate, [])))
        right = truth & got
        print("%-34s %7d %7d %7d %7.0f%% %8.0f%% %7.0f" % (
            db[:34], len(truth), len(got), len(right),
            100.0 * len(right) / max(len(truth), 1), 100.0 * len(right) / max(len(got), 1), secs), flush=True)
        tot["truth"] += len(truth)
        for g, items in found.items():
            s = set(map(tuple, items))
            tot[g + ".found"] += len(s)
            tot[g + ".right"] += len(truth & s)
        record["databases"][db] = {"truth": sorted(truth), "found": found, "secs": round(secs)}
    print("-" * 84)
    for g in sorted({k.rsplit(".", 1)[0] for k in tot if "." in k}):
        f, r = tot[g + ".found"], tot[g + ".right"]
        print("%-38s %7d %7d %7.0f%% %8.0f%%" % (g, f, r, 100.0 * r / max(tot["truth"], 1), 100.0 * r / max(f, 1)))
    print("truth: %d declared references over %d databases" % (tot["truth"], len(record["databases"])))
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, "%s.%s%s.json" % (corpus, label.replace("@", "_").replace("+", "_"), ("." + args.db) if args.db else ""))
    with open(out, "w") as fh:
        json.dump(record, fh, indent=1)
    print("recorded:", os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
