#!/usr/bin/env python3
"""Every ConQuer query the pilot produced, recompiled, against a recorded baseline.

The pilot left about eleven hundred queries written by agents who had never seen the
language, over eleven reverse-engineered schemas that between them have ring fact types,
objectified fact types, composite identifiers, subtypes and foreign keys that reference a
column other than the identifier. That is a far wider net than the company fixture, and it
is free: the queries are already written and already scored.

This recompiles all of them and diffs the emitted SQL, character for character, against the
last recorded baseline. A compiler change that alters any query's meaning has to alter its
SQL, so the text diff is the sensitive net; `--rows` then runs the old and the new SQL for
whichever queries changed and says whether the answer actually moved. The three outcomes a
change can have:

    same rows      a rewrite: the SQL differs, the answer does not
    rows differ    a fix or a regression. Read it.
    refused now    or compiled now: the language's surface moved

It needs the models (`bench/fetch.sh`, then the reverse engineering); `--rows` also needs
the BIRD databases. Neither is in the repository, so this is a bench tool rather than part
of `run-tests.sh`.

    corpus.py [--rows] [--arm A ...] [--update] [--baseline F] [-v]
"""

import argparse
import collections
import json
import re
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
DBS = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")
MODELS = os.path.join(ROOT, "bench/models")
BASELINE = os.path.join(HERE, "corpus-baseline.json")

import sqlite3                      # noqa: E402
import conquer as driver            # noqa: E402
import parser as parser_mod         # noqa: E402
import sql as sql_mod               # noqa: E402

SEMANTIC = {"conquer_sem"}          # arms that query the semantic-layer model
REFUSALS = (parser_mod.ParseError, parser_mod.Ambiguous, sql_mod.SqlError)
TIMEOUT = 120


def answers(arms=None):
    """(arm, db, question id, query text) for every ConQuer answer the pilot recorded."""
    work = os.path.join(HERE, "work")
    for arm in sorted(os.listdir(work)):
        if not arm.startswith("conquer") or (arms and arm not in arms):
            continue
        for db in sorted(os.listdir(os.path.join(work, arm))):
            path = os.path.join(work, arm, db, "answers.json")
            if not os.path.exists(path):
                continue
            try:
                got = json.load(open(path))
            except ValueError:
                continue
            for a in got:
                if a.get("answer"):
                    yield arm, db, a["question_id"], a["answer"]


def compile_all(entries, verbose=False):
    """key -> {sql, params} or {error}. One Lexicon and Emitter per model, one compilation
    per distinct (model, text): the corpus repeats itself across arms."""
    out, cache, tools = {}, {}, {}
    for arm, db, qid, text in entries:
        semantic = arm in SEMANTIC
        path = os.path.join(MODELS, "%s.%sccm.json" % (db, "semantic." if semantic else ""))
        if not os.path.exists(path):
            if verbose:
                print("no model for %s/%s" % (arm, db), file=sys.stderr)
            continue
        if path not in tools:
            model = json.load(open(path))
            tools[path] = (model, parser_mod.Lexicon(model), sql_mod.Emitter(model))
        model, lex, em = tools[path]
        ck = (path, text)
        if ck not in cache:
            try:
                _, statement, params = driver.transpile(model, text, lex, em)
                cache[ck] = {"sql": statement, "params": [str(p) for p in params]}
            except REFUSALS as e:
                cache[ck] = {"error": "%s: %s" % (type(e).__name__, e)}
            except Exception as e:                                    # noqa: BLE001
                # anything that is not a refusal is a crash, and a crash is a finding
                cache[ck] = {"error": "CRASH %s: %s" % (type(e).__name__, e)}
        out["%s/%s/%s" % (arm, db, qid)] = dict(cache[ck], db=db, text=text)
    return out


def rows(db, statement, params):
    conn = sqlite3.connect("file:%s?mode=ro" % os.path.join(DBS, db, db + ".sqlite"), uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    end = time.time() + TIMEOUT
    conn.set_progress_handler(lambda: 1 if time.time() > end else 0, 20000)
    try:
        return set(conn.execute(statement, params).fetchall())
    except sqlite3.Error as e:
        return "sqlite: %s" % e
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


_ALIAS = re.compile(r"\b([a-z]{3,6})\d+\b")


def describe(entry):
    return _ALIAS.sub(r"\1#", entry.get("error") or entry.get("sql", ""))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--rows", action="store_true",
                   help="for each changed query, run the old and the new SQL and compare")
    p.add_argument("--arm", action="append", help="only this arm (repeatable)")
    p.add_argument("--update", action="store_true", help="write the baseline and stop")
    p.add_argument("--baseline", default=BASELINE)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    now = compile_all(answers(args.arm), args.verbose)
    if not now:
        print("no queries found: is bench/models built? (bench/fetch.sh, then reverse)")
        return 2
    kinds = collections.Counter("crash" if str(e.get("error", "")).startswith("CRASH")
                                else "refused" if e.get("error") else "compiled"
                                for e in now.values())
    print("%d queries: %d compile, %d refused, %d crash"
          % (len(now), kinds["compiled"], kinds["refused"], kinds["crash"]))

    if args.update:
        json.dump(now, open(args.baseline, "w"), indent=1, sort_keys=True)
        print("baseline written to %s" % os.path.relpath(args.baseline, ROOT))
        return 0

    if not os.path.exists(args.baseline):
        print("no baseline yet; run with --update to record one")
        return 2
    was = json.load(open(args.baseline))
    if args.arm:                      # compare like with like when only some arms are run
        was = {k: v for k, v in was.items() if k.split("/")[0] in set(args.arm)}

    # Alias serials are per-Emitter and the Emitter is shared across a model's queries, so
    # adding an *arm* renumbers every query that follows it alphabetically without changing a
    # thing about what they mean. Normalise the serials before diffing, or a new arm reports
    # four hundred false changes.
    gone = sorted(set(was) - set(now))
    fresh = sorted(set(now) - set(was))
    changed = sorted(k for k in set(was) & set(now)
                     if describe(was[k]) != describe(now[k]))
    print("against the baseline: %d unchanged, %d changed, %d new, %d gone"
          % (len(set(was) & set(now)) - len(changed), len(changed), len(fresh), len(gone)))

    moved = 0
    for k in changed:
        a, b = was[k], now[k]
        print("\n%s" % k)
        print("  was: %s" % describe(a)[:220])
        print("  now: %s" % describe(b)[:220])
        if not args.rows:
            continue
        if "sql" not in a or "sql" not in b:
            print("  rows: one side does not compile")
            moved += 1
            continue
        before = rows(b["db"], a["sql"], a["params"])
        after = rows(b["db"], b["sql"], b["params"])
        if isinstance(before, str) or isinstance(after, str):
            print("  rows: %s" % (before if isinstance(before, str) else after))
            moved += 1
        elif before == after:
            print("  rows: unchanged (%d)" % len(after))
        else:
            print("  rows: MOVED. %d row(s) before, %d after, %d differ"
                  % (len(before), len(after), len(before ^ after)))
            moved += 1
    for k in fresh:
        if args.verbose:
            print("\nnew  %s\n  %s" % (k, describe(now[k])[:220]))
    for k in gone:
        if args.verbose:
            print("\ngone %s" % k)

    if changed and args.rows:
        print("\n%d of %d changed queries moved their answer" % (moved, len(changed)))
    if kinds["crash"]:
        print("\n%d queries crashed the compiler rather than being refused:" % kinds["crash"])
        for k, e in sorted(now.items()):
            if str(e.get("error", "")).startswith("CRASH"):
                print("  %-46s %s" % (k, e["error"][:110]))
    return 1 if (changed or kinds["crash"]) else 0


if __name__ == "__main__":
    sys.exit(main())
