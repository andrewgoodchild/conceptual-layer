#!/usr/bin/env python3
"""Head-to-head harness: text-to-SQL against conceptual-model-to-ConQuer.

Two arms answer the same BIRD question against the same database.

  A  direct   an LLM writes SQL from the DDL and the question
  B  conquer  an LLM writes ConQuer-92 from the reverse-engineered conceptual model,
              and conquer/ transpiles it to SQL

Both are scored the way BIRD scores: execution accuracy, `set(pred) == set(gold)` over raw
result tuples -- see `bird_ex`. Two stricter readings are recorded alongside: `exact_ok`
(multiset, so duplicates count) and `ordered_ok` (row order too). The headline uses BIRD's.

Each question also carries BIRD's `evidence` -- the external knowledge the benchmark supplies
with the question, such as "Percent Eligible Free = Free Meal Count / Enrollment * 100". The
benchmark intends the query author to have it. Several early failures blamed on "gold
projecting columns the question did not ask for" were the evidence asking for them.

    harness.py answers.json --db-dir /tmp/bird/minidev/.../dev_databases -o results.json
"""

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "conquer"))
import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402


def db_path(db_dir, db_id):
    return os.path.join(db_dir, db_id, db_id + ".sqlite")


def run_sql(conn, statement, params=()):
    cur = conn.execute(statement, params)
    return cur.fetchall()


def bird_ex(got, want):
    """BIRD's execution accuracy, exactly as `evaluation_ex.py` in bird-bench/mini_dev computes
    it: `set(predicted_res) == set(ground_truth_res)` over the raw tuples fetchall returns.
    Native types, so 1 and 1.0 are equal and 1 and '1' are not; duplicates collapsed, so a
    query that forgets DISTINCT still passes; NULL stays NULL.

    The harness used to stringify values and compare sorted multisets. That was stricter on
    duplicates and int/float and looser on NULL, and disagreed with BIRD on 4 of 140 verdicts,
    all in the direction of marking a BIRD-correct answer wrong. It is kept below as
    `exact_ok`, because "returned the right set" and "returned the right rows" are different
    claims and a reader may want both.
    """
    return set(got) == set(want)


def norm(rows):
    return sorted(tuple("" if v is None else str(v) for v in r) for r in rows)


def compare(got, want):
    """(bird_ok, exact_ok, ordered_ok)."""
    return (bird_ex(got, want),
            norm(got) == norm(want),
            [tuple("" if v is None else str(v) for v in r) for r in got]
            == [tuple("" if v is None else str(v) for v in r) for r in want])


def evaluate(answers, db_dir, models_dir):
    results = []
    conns, models, lexicons, emitters = {}, {}, {}, {}

    for a in answers:
        db_id = a["db_id"]
        if db_id not in conns:
            conns[db_id] = sqlite3.connect(db_path(db_dir, db_id))
            conns[db_id].text_factory = lambda b: b.decode("utf-8", "replace")
        conn = conns[db_id]

        row = {"question_id": a["question_id"], "db_id": db_id,
               "question": a["question"], "difficulty": a.get("difficulty"),
               "in_scope": a.get("in_scope", True),
               "out_of_scope_reason": a.get("out_of_scope_reason")}

        try:
            gold = run_sql(conn, a["gold_sql"])
            row["gold_rows"] = len(gold)
        except sqlite3.Error as e:
            row["gold_error"] = str(e)
            results.append(row)
            continue

        # -- arm A: direct SQL ---------------------------------------------
        if a.get("direct_sql"):
            try:
                got = run_sql(conn, a["direct_sql"])
                ok, exact, om = compare(got, gold)
                row["direct"] = {"ok": ok, "exact_ok": exact, "ordered_ok": om, "rows": len(got)}
            except sqlite3.Error as e:
                row["direct"] = {"ok": False, "error": str(e)}
        else:
            row["direct"] = {"ok": False, "error": "no answer given"}

        # -- arm B: ConQuer -> SQL -----------------------------------------
        if a.get("conquer"):
            if db_id not in models:
                with open(os.path.join(models_dir, db_id + ".ccm.json")) as fh:
                    models[db_id] = json.load(fh)
                lexicons[db_id] = parser_mod.Lexicon(models[db_id])
                emitters[db_id] = sql_mod.Emitter(models[db_id])
            try:
                _, statement, params = driver.transpile(
                    models[db_id], a["conquer"], lexicons[db_id], emitters[db_id])
                row["conquer_sql"] = statement
                got = run_sql(conn, statement, params)
                ok, exact, om = compare(got, gold)
                row["conquer"] = {"ok": ok, "exact_ok": exact, "ordered_ok": om, "rows": len(got)}
            except parser_mod.Ambiguous as e:
                row["conquer"] = {"ok": False, "error": "ambiguous: %s" % e, "stage": "parse"}
            except parser_mod.ParseError as e:
                row["conquer"] = {"ok": False, "error": "parse: %s" % e, "stage": "parse"}
            except sql_mod.SqlError as e:
                row["conquer"] = {"ok": False, "error": "lower/emit: %s" % e, "stage": "emit"}
            except sqlite3.Error as e:
                row["conquer"] = {"ok": False, "error": "sqlite: %s" % e, "stage": "execute"}
        else:
            row["conquer"] = {"ok": False, "error": "no answer given",
                              "stage": "unexpressible" if not row["in_scope"] else "missing"}

        results.append(row)

    for c in conns.values():
        c.close()
    return results


def summarise(results):
    def rate(rows, arm):
        n = len(rows)
        ok = sum(1 for r in rows if r.get(arm, {}).get("ok"))
        return ok, n, (100.0 * ok / n if n else 0.0)

    scored = [r for r in results if "gold_error" not in r]
    in_scope = [r for r in scored if r["in_scope"]]

    lines = ["", "%-34s %8s %8s" % ("", "direct", "conquer"), "-" * 52]
    for label, rows in (("all questions", scored), ("in ConQuer's subset", in_scope)):
        d = rate(rows, "direct")
        c = rate(rows, "conquer")
        lines.append("%-34s %3d/%-4d %3d/%-4d   (%.0f%% vs %.0f%%)"
                     % (label, d[0], d[1], c[0], c[1], d[2], c[2]))

    by_diff = {}
    for r in in_scope:
        by_diff.setdefault(r["difficulty"], []).append(r)
    if by_diff:
        lines += ["", "in-subset by difficulty:"]
        for diff in ("simple", "moderate", "challenging"):
            rows = by_diff.get(diff)
            if rows:
                d, c = rate(rows, "direct"), rate(rows, "conquer")
                lines.append("  %-32s %3d/%-4d %3d/%-4d" % (diff, d[0], d[1], c[0], c[1]))

    stages = {}
    for r in scored:
        cq = r.get("conquer", {})
        if not cq.get("ok"):
            stages[cq.get("stage", "wrong answer")] = stages.get(cq.get("stage",
                                                                       "wrong answer"), 0) + 1
    if stages:
        lines += ["", "conquer failures by stage:"]
        for k, v in sorted(stages.items(), key=lambda kv: -kv[1]):
            lines.append("  %-32s %d" % (k, v))
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("answers")
    p.add_argument("--db-dir", required=True)
    p.add_argument("--models-dir", required=True)
    p.add_argument("-o", "--out")
    args = p.parse_args(argv)

    with open(args.answers) as fh:
        answers = json.load(fh)
    results = evaluate(answers, args.db_dir, args.models_dir)
    print(summarise(results))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2)
        print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
