#!/usr/bin/env python3
"""Downstream ablation: what the references an arm infers do to the queries people wrote.

For each BIRD database with recorded ConQuer answers, the model is rebuilt from a catalogue
with every declared reference removed and an arm's inferred references put in their place,
then every recorded answer is recompiled against it and run. Against the model built from
the declared schema, an answer either compiles and returns the same rows, compiles and
returns different rows, or no longer compiles -- because a column the arm did not recover
is a value in its model where the answer walked a relationship.

    downstream.py --sweep work/bird.sweep_0.json --gate '+1to1+md1+mr1+t0@0.0' [--db NAME]
"""
import argparse
import collections
import copy
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "reverse"))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
import catalog as catalog_mod        # noqa: E402
import derive as derive_mod          # noqa: E402
import conquer as driver             # noqa: E402
import parser as parser_mod          # noqa: E402
import sql as sql_mod                # noqa: E402

BIRD = os.path.join(ROOT, "bench", "bird", "minidev", "MINIDEV", "dev_databases")
ANSWERS = os.path.join(ROOT, "bench", "pilot", "work", "conquer")


def _name_fit(column, key):
    """How far a source column's name points at a particular target key. `setCode` against
    `code` beats `setCode` against `id`; a tie leaves the order the keys came in, which puts
    the primary key first."""
    c, k = column.casefold(), key.casefold()
    if c == k:
        return 3
    if k and (k in c or c.endswith(k)):
        return 2
    if k and c.replace("_", "") .endswith(k.replace("_", "")):
        return 1
    return 0


def canon(rows):
    return sorted((tuple(round(c, 6) if isinstance(c, float) else c for c in r) for r in rows),
                  key=lambda r: tuple((c is None, str(c)) for c in r))


def model_with(cat, refs):
    """A catalogue with only `refs` declared -- (table, column, target) triples -- and the
    model derived from it with name inference off: the arm's references, nothing else.

    The reference *columns* come from the catalogue wherever it declares that triple, and
    only fall back to the target's key where it does not. Rebuilding every reference onto
    the primary key instead looked harmless and was not: european_football_2 declares 28
    references to `Player.player_api_id` while Player is keyed on `id`, so the rebuilt
    control joined 119 of 11,060 players and the arm being measured was the builder, not
    the references. The writer of the declared arm found it by reading its own row counts.
    """
    declared_key = {}
    for t in cat.tables:
        for fk in t.foreign_keys:
            if len(fk.columns) == 1 and fk.ref_columns and len(fk.ref_columns) == 1:
                declared_key[(t.name.casefold(), fk.columns[0].casefold(),
                              fk.ref_table.casefold())] = list(fk.ref_columns)
    cat = copy.deepcopy(cat)
    by_name = {t.name.casefold(): t for t in cat.tables}
    for t in cat.tables:
        t.foreign_keys = []
    for table, column, target in refs:
        t, tgt = by_name.get(table), by_name.get(target)
        if t is None or tgt is None:
            continue
        col = next((c.name for c in t.columns if c.name.casefold() == column), None)
        key = declared_key.get((table, column, target))
        if key is None:
            # An inferred reference is a (table, column, target) triple with no target
            # *column*, and a target with two single-column keys makes that a choice: `sets`
            # has `id` and `code`, and `cards.setCode` means `code`. Taking the primary key
            # wired it to `id` and the join matched nothing -- a card_games writer found it
            # and bridged around it. Chosen by the same name evidence that settles the
            # assignment itself (finding 120), falling back to the primary key.
            keys = ([list(tgt.primary_key)] if len(tgt.primary_key) == 1 else []) + \
                   [list(u) for u in tgt.uniques if len(u) == 1]
            seen, uniq = set(), []
            for k in keys:
                if tuple(x.casefold() for x in k) not in seen:
                    seen.add(tuple(x.casefold() for x in k))
                    uniq.append(k)
            key = max(uniq, key=lambda k: _name_fit(column, k[0]), default=None)
        if col is None or not key:
            continue
        t.foreign_keys.append(catalog_mod.ForeignKey(columns=[col], ref_table=tgt.name,
                                                     ref_columns=list(key)))
    model, _report = derive_mod.derive(cat, infer_undeclared_fks=False, json_shapes={}, dialect="sqlite")
    return model


def run(db, gate, found, args):
    path = os.path.join(BIRD, db, db + ".sqlite")
    apath = os.path.join(ANSWERS, db, "answers.json")
    if not (os.path.exists(path) and os.path.exists(apath)):
        return None
    cat = catalog_mod.from_sqlite(path)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    declared = [(t.name.casefold(), c.casefold(), fk.ref_table.casefold())
                for t in cat.tables for fk in t.foreign_keys for c in fk.columns]
    base = model_with(cat, declared)
    arm = model_with(cat, [tuple(x) for x in found])
    tools = {"declared": (base, parser_mod.Lexicon(base), sql_mod.Emitter(base)),
             "arm": (arm, parser_mod.Lexicon(arm), sql_mod.Emitter(arm))}
    ans = json.load(open(apath))
    items = ans.items() if isinstance(ans, dict) else [(str(a.get("question_id")), a) for a in ans]
    tally = collections.Counter()
    for qid, a in items:
        text = a["answer"] if isinstance(a, dict) else a
        if not text:
            continue
        rows = {}
        for side, (m, lex, em) in tools.items():
            try:
                _, sql, params = driver.transpile(m, text, lex, em)
                rows[side] = canon(conn.execute(sql, params).fetchall())
            except Exception:                                           # noqa: BLE001
                rows[side] = None
        tally["answers"] += 1
        if rows["declared"] is None:
            tally["baseline itself fails"] += 1
        elif rows["arm"] is None:
            tally["no longer compiles"] += 1
        elif rows["arm"] == rows["declared"]:
            tally["same rows"] += 1
        else:
            tally["different rows"] += 1
    conn.close()
    return tally


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--sweep", required=True, help="a work/bird.*.json the sweep wrote")
    p.add_argument("--gate", required=True)
    p.add_argument("--db")
    args = p.parse_args(argv)
    rec = json.load(open(args.sweep))
    print("gate %s from %s" % (args.gate, os.path.relpath(args.sweep, ROOT)))
    print("%-26s %8s %10s %10s %12s %8s" % ("database", "answers", "same rows", "differ", "not compiled", "base ko"))
    total = collections.Counter()
    for db, entry in sorted(rec["databases"].items()):
        if args.db and args.db not in db:
            continue
        found = entry["found"].get(args.gate)
        if found is None:
            print("%-26s gate not recorded" % db); continue
        tally = run(db, args.gate, found, args)
        if tally is None:
            continue
        print("%-26s %8d %10d %10d %12d %8d" % (db[:26], tally["answers"], tally["same rows"], tally["different rows"],
                                               tally["no longer compiles"], tally["baseline itself fails"]), flush=True)
        total.update(tally)
    print("%-26s %8d %10d %10d %12d %8d" % ("all", total["answers"], total["same rows"], total["different rows"],
                                           total["no longer compiles"], total["baseline itself fails"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
