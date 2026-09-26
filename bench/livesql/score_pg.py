#!/usr/bin/env python3
"""Score answers against LiveSQLBench Large-v1's ground truth, on PostgreSQL.

The large tier is the one the benchmark is really about -- 54 tables a database, `jsonb`
columns, PostgreSQL -- and its gold is PostgreSQL SQL, so it cannot be scored through the
SQLite copies `load.py` makes for analysis. This is `score_sqlite.py` for a server: the same
arm layout, the same execution-accuracy rule, the rows fetched through `psycopg`.

The databases are the dataset's own dumps loaded by its own script into `<name>_template`
(see README, "Getting it"); read-only SELECTs run against those directly. Comparison follows
the benchmark's harness where it matters and says so where it does not: numbers are rounded
to two places (`preprocess_results` does), `Decimal` and `float` compare as numbers (gold
casts to `numeric`, the compiler to `double precision`), and a task whose `conditions.order`
is set is compared in order. What is *not* done: the harness strips every `DISTINCT` and
`ROUND` from both statements before running them, and runs a task's `test_cases` function
where it ships one. Both are visible in the SQLite tier's numbers (finding 157); neither is
reproduced here, so this is the stricter of the two scorers.

    score_pg.py --arm DIR [--sql] [--db NAME] [--model-dir DIR] [-v]
                [--dsn postgresql://root:root@localhost:5433]
"""
import argparse
import json
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DSN = os.environ.get("LIVESQL_PG", "postgresql://root:root@localhost:5433")
TIMEOUT_MS = 120000


def connect(dsn, db):
    import psycopg
    conn = psycopg.connect(dsn + "/" + db + "_template", autocommit=True)
    conn.execute("SET statement_timeout = %d" % TIMEOUT_MS)
    conn.execute("SET default_transaction_read_only = on")
    return conn


def norm(v):
    """A value as the harness compares it: numbers to two places, text as is."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        return round(float(v), 2)
    if isinstance(v, (list, dict)):
        return json.dumps(v, sort_keys=True, default=str)
    return v


def rows(conn, sql):
    """The result set as a list of normalised tuples, or the reason there is none."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [tuple(norm(v) for v in r) for r in cur.fetchall()]
    except Exception as e:                                             # noqa: BLE001
        return "pg: %s" % str(e).split("\n")[0][:100]


def candidate_sql(answer, model, as_sql):
    if as_sql:
        return answer, None
    import conquer as driver
    try:
        _, sql, params = driver.transpile(model, answer)
    except Exception as e:                                             # noqa: BLE001
        return None, "refused: %s" % str(e)[:60]
    for v in params:
        sql = sql.replace("?", "'%s'" % str(v).replace("'", "''") if isinstance(v, str)
                          else str(v), 1)
    return sql, None


def load_arm(arm, only_db=None):
    out = {}
    for db in sorted(os.listdir(arm)):
        if only_db and db != only_db:
            continue
        path = os.path.join(arm, db, "answers.json")
        if os.path.exists(path):
            for a in json.load(open(path)):
                # LiveSQLBench keys a task by instance_id; the BIRD pilot's files by question_id
                out[a.get("instance_id") or a["question_id"]] = (db, a.get("answer"))
    return out


def gold_sql(entry):
    s = entry.get("sol_sql")
    if isinstance(s, list):
        s = s[0] if s else None
    return s


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arm", required=True, help="directory of <database>/answers.json")
    p.add_argument("--db")
    p.add_argument("--sql", action="store_true", help="answers are SQL, not ConQuer")
    p.add_argument("--model-dir", default=os.path.join(HERE, "work", "models"))
    p.add_argument("--dsn", default=DSN)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    gt = {r["instance_id"]: r for r in
          (json.loads(l) for l in open(os.path.join(DATA, "livesqlbench_large_v1_gt.jsonl")))}
    qs = {q["instance_id"]: q for q in
          (json.loads(l) for l in open(os.path.join(DATA, "livesqlbench_large_v1_data.jsonl")))}
    if not args.sql:
        sys.path.insert(0, os.path.join(HERE, "..", "..", "conquer"))

    counts = {"ok": 0, "wrong": 0, "refused": 0, "failed": 0, "no_gold": 0}
    misses, conns = [], {}
    for qid, (db, answer) in sorted(load_arm(args.arm, args.db).items()):
        q, entry = qs.get(qid), gt.get(qid)
        if not q or not entry or not gold_sql(entry):
            counts["no_gold"] += 1
            continue
        if db not in conns:
            conns[db] = connect(args.dsn, db)
        model = None
        if not args.sql:
            mp = os.path.join(args.model_dir, "%s.ccm.json" % db)
            model = json.load(open(mp))
        sql, why = candidate_sql(answer or "", model, args.sql)
        if sql is None:
            counts["refused"] += 1
            misses.append((db, qid, why))
            continue
        got, want = rows(conns[db], sql), rows(conns[db], gold_sql(entry))
        if isinstance(want, str):
            counts["no_gold"] += 1                    # the gold itself does not run
            misses.append((db, qid, "gold " + want))
            continue
        if isinstance(got, str):
            counts["failed"] += 1
            misses.append((db, qid, got))
            continue
        ordered = (q.get("conditions") or {}).get("order")
        same = got == want if ordered else sorted(got, key=str) == sorted(want, key=str)
        counts["ok" if same else "wrong"] += 1
        if not same:
            misses.append((db, qid, "%d rows, gold %d" % (len(got), len(want))))
    n = counts["ok"] + counts["wrong"] + counts["refused"] + counts["failed"]
    print("%-12s %s" % (os.path.basename(args.arm.rstrip("/")), counts))
    if n:
        print("execution accuracy: %d of %d = %.0f%%" % (counts["ok"], n, 100.0 * counts["ok"] / n))
    if args.verbose:
        for m in misses:
            print("   %-40s %-28s %s" % m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
