#!/usr/bin/env python3
"""Does the SQL checker flag wrong answers, or just answers?

`conquer/sqlcheck.py` reads an agent's SQL against the model and reports what its joins do to
its aggregates. The claim worth testing is narrow: an answer it flags is more often wrong than
one it does not. The recorded SQL arms answer that without a new run -- every answer was
scored against the gold when it was made -- so this runs the checker over each one and
tabulates the flags against the outcome, kind by kind.

Two cautions on reading it. The arms answered the same hundred questions, so an answer is not
an independent draw: a question every arm gets wrong in the same way counts once per arm. And
"wrong" is BIRD's verdict, which compares result *sets* -- a kind that is about repeated rows
cannot show up as wrong here even where it is.

It also runs the checker over BIRD's own gold SQL for the 500-question mini-dev set, where a
flag is either a false alarm or a gold error, and lists them for reading.

    sqlcheck_eval.py [--gold] [-v]
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
MODELS = os.path.join(ROOT, "bench/models")
GOLD = os.path.join(ROOT, "bench/bird/mini_dev_sqlite.json")

import sqlcheck                   # noqa: E402

_SQL = re.compile(r"(?is)^\s*(select|with)\b")


class Models:
    def __init__(self):
        self.cache = {}

    def __call__(self, db):
        if db not in self.cache:
            m = json.load(open(os.path.join(MODELS, "%s.ccm.json" % db)))
            self.cache[db] = (m, sqlcheck.Keys(m))
        return self.cache[db]


def arms(models, verbose):
    results = json.load(open(os.path.join(HERE, "results.json")))
    table = collections.defaultdict(collections.Counter)
    questions = collections.defaultdict(set)
    used = collections.Counter()
    for r in results:
        sql = (r.get("answer") or "").strip()
        if not _SQL.match(sql) or r["outcome"] not in ("ok", "wrong_quietly"):
            continue
        used[r["arm"]] += 1
        model, keys = models(r["db_id"])
        found = sqlcheck.check(model, sql, "sqlite", keys)
        kinds = {f.kind for f in found} or {"(nothing)"}
        for k in kinds | {"(every answer)"}:
            table[k][r["outcome"]] += 1
            questions[k].add(r["question_id"])
        if verbose and found and r["outcome"] == "wrong_quietly":
            print("%s q%s %s\n  %s\n" % (r["arm"], r["question_id"], sql[:200],
                                       sqlcheck.render(found).replace("\n", "\n  ")))
    print("SQL answers from %d arms (%s), scored when they were made\n"
          % (len(used), ", ".join(sorted(used))))
    print("%-16s %8s %8s %7s %10s" % ("flag", "answers", "wrong", "wrong%", "questions"))
    for k in sorted(table, key=lambda k: (k.startswith("("), k)):
        v = table[k]
        n = v["ok"] + v["wrong_quietly"]
        print("%-16s %8d %8d %6.0f%% %10d" % (k, n, v["wrong_quietly"],
                                             100.0 * v["wrong_quietly"] / n, len(questions[k])))


def gold(models, verbose):
    rows = json.load(open(GOLD))
    count = collections.Counter()
    for g in rows:
        model, keys = models(g["db_id"])
        found = sqlcheck.check(model, g["SQL"], "sqlite", keys)
        for k in {f.kind for f in found}:
            count[k] += 1
        if found and verbose:
            print("q%s %s: %s\n  %s\n  %s\n" % (g["question_id"], g["db_id"], g["question"],
                                              g["SQL"][:300],
                                              sqlcheck.render(found).replace("\n", "\n  ")))
    print("\nBIRD mini-dev gold, %d queries: %s" % (
        len(rows), ", ".join("%s %d" % kv for kv in sorted(count.items()))))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--gold", action="store_true", help="also check BIRD's gold SQL")
    p.add_argument("-v", "--verbose", action="store_true", help="print each flagged query")
    args = p.parse_args(argv)
    if not sqlcheck.available():
        sys.exit("needs sqlglot: pip install sqlglot")
    models = Models()
    arms(models, args.verbose)
    if args.gold:
        gold(models, args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
