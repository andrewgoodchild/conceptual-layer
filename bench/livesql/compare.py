#!/usr/bin/env python3
"""Where do SQL and ConQuer give the same answer, and where do they differ?

There is no gold, so this scores nothing. Two independent writers answered the same questions
from the same database in different languages; agreement is evidence that both are right, and
disagreement means at least one is wrong. The disagreements are the output worth reading.

Every answer is executed against the same SQLite copy of the database, so a difference is a
difference in what was asked, never in where it was asked.

    compare.py [--db NAME] [-v] [--json out.json]
"""

import argparse
import collections
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402

WORK = os.path.join(HERE, "work", "pilot")
DBS = os.path.join(HERE, "work", "db")
MODELS = os.path.join(HERE, "work", "models")
TIMEOUT = 60


def deadline(seconds):
    import time
    end = time.time() + seconds
    return lambda: 1 if time.time() > end else 0


def run_sql(conn, sql):
    try:
        cur = conn.execute(sql)
        return cur.fetchall(), None
    except Exception as e:                                              # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:90])


def run_conquer(conn, model, lex, em, text):
    try:
        _, sql, params = driver.transpile(model, text, lex, em)
    except Exception as e:                                              # noqa: BLE001
        kind = "refused" if "Judgement" in type(e).__name__ or "refus" in str(e).lower() \
            else "parse"
        return None, "%s: %s" % (kind, str(e)[:90])
    try:
        return conn.execute(sql, params).fetchall(), None
    except Exception as e:                                              # noqa: BLE001
        return None, "exec: %s" % str(e)[:90]


def canon(rows, places=4):
    """A result set as a comparable value: order-insensitive, float-tolerant."""
    if rows is None:
        return None
    out = []
    for r in rows:
        cells = []
        for v in r:
            if isinstance(v, float):
                cells.append(round(v, places))
            elif isinstance(v, int):
                cells.append(float(v))
            else:
                cells.append(v)
        out.append(tuple(cells))
    return sorted(out, key=lambda t: tuple(str(x) for x in t))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--json")
    args = p.parse_args(argv)

    dbs = sorted(os.listdir(os.path.join(WORK, "sql")))
    if args.db:
        dbs = [d for d in dbs if args.db in d]

    verdicts, rows_out = collections.Counter(), []
    for db in dbs:
        sa = os.path.join(WORK, "sql", db, "answers.json")
        ca = os.path.join(WORK, "conquer", db, "answers.json")
        if not (os.path.exists(sa) and os.path.exists(ca)):
            print("%-40s not finished" % db)
            continue
        sql_ans = {a["instance_id"]: a for a in json.load(open(sa))}
        cq_ans = {a["instance_id"]: a for a in json.load(open(ca))}
        conn = sqlite3.connect("file:%s?mode=ro" % os.path.join(DBS, "%s.sqlite" % db),
                               uri=True)
        conn.set_progress_handler(deadline(TIMEOUT), 100000)
        # The SQLite build, because the copies `load.py` makes are what this executes
        # against. The PostgreSQL build beside it is the real target and does not run here:
        # `CAST(x AS DOUBLE PRECISION)` and `jsonb_path_query_first` are not SQLite. Both are
        # the same model -- same concepts, same readings, byte-identical schema listing --
        # differing only in the function templates.
        shim = os.path.join(MODELS, "%s-sqlite.ccm.json" % db)
        model = json.load(open(shim if os.path.exists(shim)
                               else os.path.join(MODELS, "%s.ccm.json" % db)))
        lex, em = parser_mod.Lexicon(model), sql_mod.Emitter(model)
        for iid in sorted(set(sql_ans) | set(cq_ans)):
            s, c = sql_ans.get(iid, {}), cq_ans.get(iid, {})
            srows, serr = run_sql(conn, s["answer"]) if s.get("answer") else (None, "blank")
            crows, cerr = (run_conquer(conn, model, lex, em, c["answer"])
                           if c.get("answer") else (None, "blank"))
            if serr and cerr:
                v = "both failed"
            elif serr:
                v = "only ConQuer answered"
            elif cerr:
                v = "only SQL answered"
            elif canon(srows) == canon(crows):
                v = "agree"
            else:
                v = "differ"
            verdicts[v] += 1
            rows_out.append({"db": db, "instance_id": iid, "verdict": v,
                             "sql": s.get("answer", ""), "conquer": c.get("answer", ""),
                             "sql_note": s.get("note", ""), "conquer_note": c.get("note", ""),
                             "sql_error": serr, "conquer_error": cerr,
                             "sql_rows": len(srows) if srows is not None else None,
                             "conquer_rows": len(crows) if crows is not None else None,
                             "sql_head": str(srows[:2])[:200] if srows else "",
                             "conquer_head": str(crows[:2])[:200] if crows else ""})
        conn.close()

    n = sum(verdicts.values())
    print("%d questions compared\n" % n)
    for v, k in verdicts.most_common():
        print("   %-24s %3d  (%.0f%%)" % (v, k, 100.0 * k / max(n, 1)))

    print("\nby database:")
    per = collections.defaultdict(collections.Counter)
    for r in rows_out:
        per[r["db"]][r["verdict"]] += 1
    print("   %-40s %6s %7s %9s %9s" % ("", "agree", "differ", "SQL only", "CQ only"))
    for db in sorted(per):
        c = per[db]
        print("   %-40s %6d %7d %9d %9d" % (
            db, c["agree"], c["differ"], c["only SQL answered"],
            c["only ConQuer answered"]))

    if args.verbose:
        for r in rows_out:
            if r["verdict"] == "agree":
                continue
            print("\n--- %s  %s  [%s]" % (r["db"].replace("_large", ""), r["instance_id"],
                                          r["verdict"]))
            print("    SQL     %s rows  %s" % (r["sql_rows"], r["sql_error"] or ""))
            print("            %s" % r["sql_head"][:140])
            print("    ConQuer %s rows  %s" % (r["conquer_rows"], r["conquer_error"] or ""))
            print("            %s" % r["conquer_head"][:140])
            if r["conquer_note"]:
                print("    note:   %s" % r["conquer_note"][:180])
    if args.json:
        json.dump(rows_out, open(args.json, "w"), indent=1)
        print("\nwritten: %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
