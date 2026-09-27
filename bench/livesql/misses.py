#!/usr/bin/env python3
"""Why the answers at scale were wrong: retrieval, or reading?

Every wrong answer in the four scale rounds (SCALE.md to SCALE4.md), set beside the gold it
was scored against, and put in the first of these that applies:

    missing     no answer, or one that does not run
    table       the answer does not use every table the gold uses
    column      it uses every gold table, but not every column or JSON field the gold reads
    reading     it uses every table, column and field the gold does, and still returns
                something else -- a filter, a grain, a formula, an order, a rounding

`table` and `column` are what better retrieval (BM25, a Steiner tree over the model, Bird's
abstraction) could fix; `reading` is what it could not. The test is lexical -- a name in the
answer's text -- so a column named but used wrongly counts as used, which errs towards
`reading`; a gold column the answer reaches under another name (a view, an alias) counts as
missed, which errs the other way.

For the rounds whose views can be rebuilt (SCALE3's and SCALE4's `./schema`), also whether the
view for the question's own text showed every gold table -- the first thing a writer saw.

Reads the private gold and the per-question verdicts `score_scale.py --json` wrote; prints
counts only. Nothing per question is printed, since the gold is the benchmark's to release.

    misses.py
"""
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "conquer"))
import ddl_link                                                           # noqa: E402
import score_pg                                                           # noqa: E402
from calibrate_scale import tables_in                                     # noqa: E402

DATA = os.path.join(HERE, "data")
ROUNDS = [("SCALE", "pilot-scale"), ("SCALE2", "pilot-scale2"),
          ("SCALE3", "pilot-scale3"), ("SCALE4", "pilot-scale4")]
_KEY = re.compile(r"->>?\s*'([^']+)'")
CATS = ["missing", "table", "column", "reading"]


def columns_in(sql, cols):
    low = sql.lower()
    return {c for c in cols if re.search(r"(?<![\w])\"?%s\"?(?![\w])" % re.escape(c.lower()), low)}


def keys_in(sql):
    return {k.lower() for k in _KEY.findall(sql)}


def view_for(round_, arm, db, question, cache):
    """The `./schema` output for the question's text, where the arm's view can be rebuilt."""
    import annotate
    key = (round_, arm, db)
    if key not in cache and round_ not in ("SCALE3", "SCALE4"):
        cache[key] = None
    if key not in cache:
        text = open(os.path.join(DATA, db, "%s_schema.txt" % db)).read()
        model = json.load(open(os.path.join(HERE, "work", "models-profiled2",
                                            "%s.ccm.json" % db)))
        w4 = os.path.join(HERE, "work", "pilot-scale4")
        part = lambda sub: os.path.join(w4, sub, "%s.json" % db)
        if round_ == "SCALE3":
            ann, budget = (annotate.Annotator(text) if arm == "ddlp"
                           else annotate.Annotator(text, model)), 16000
        elif round_ == "SCALE4":
            if not os.path.exists(part("meanings")):
                cache[key] = None
                return None
            desc_m = annotate.Descriptions([("", part("meanings"))])
            desc_f = annotate.Descriptions([("documented", part("meanings")),
                                            ("profiled", part("descriptions"))])
            ann = {"ddlp4": lambda: annotate.Annotator(text),
                   "ddlm": lambda: annotate.Annotator(text, None, desc_m),
                   "annm": lambda: annotate.Annotator(text, model, desc_f),
                   "annl": lambda: annotate.Annotator(
                       text, model, desc_f, annotate.Values(part("values")),
                       annotate.Links(part("links")))}[arm]()
            budget = 20000
        else:
            cache[key] = None
            return None
        cache[key] = (ann, budget)
    if cache[key] is None:
        return None
    ann, budget = cache[key]
    return ann.view(question, budget)


def main():
    tasks = {t["instance_id"]: t for t in map(json.loads, open(os.path.join(
        DATA, "livesqlbench_large_v1_data.jsonl")))}
    gold = {g["instance_id"]: g for g in map(json.loads, open(os.path.join(
        DATA, "livesqlbench_large_v1_gt.jsonl")))}
    ddl = {}
    total, shown_all, per_round = Counter(), Counter(), {}
    by_round_arm = {}
    view_cache = {}
    for name, work in ROUNDS:
        w = os.path.join(HERE, "work", work)
        verdicts = json.load(open(os.path.join(w, "verdicts.json")))
        sample = json.load(open(os.path.join(w, "sample.json")))
        qdb = {q: db for db, ids in sample.items() for q in ids}
        for arm, v in verdicts.items():
            answers = score_pg.load_arm(os.path.join(w, arm))
            c = by_round_arm.setdefault((name, arm), Counter())
            for qid, verdict in v.items():
                if verdict == "ok" or verdict == "no_gold":
                    c["right"] += 1
                    continue
                db = qdb[qid]
                if db not in ddl:
                    linker = ddl_link.DdlLinker(open(os.path.join(
                        DATA, db, "%s_schema.txt" % db)).read())
                    ddl[db] = {n: ddl_link.columns(b) for n, b in linker.blocks}
                tables = ddl[db]
                sol = gold[qid]["sol_sql"]
                sol = " ".join(sol) if isinstance(sol, list) else sol
                ans = (answers.get(qid) or (db, None))[1] or ""
                if verdict in ("missing", "failed") or not ans.strip():
                    cat = "missing"
                else:
                    g_t = tables_in(sol, tables)
                    a_t = tables_in(ans, tables)
                    if not g_t <= a_t:
                        cat = "table"
                    else:
                        cols = {c for t in g_t for c in tables[t]}
                        g_c, a_c = columns_in(sol, cols), columns_in(ans, cols)
                        g_k, a_k = keys_in(sol), keys_in(ans)
                        cat = "column" if not (g_c <= a_c and g_k <= a_k) else "reading"
                c[cat] += 1
                total[cat] += 1
                view = view_for(name, arm, db, tasks[qid]["normal_query"], view_cache)
                if view is not None:
                    g_t = tables_in(sol, tables)
                    heads = "\n".join(l for l in view.splitlines() if l.startswith("CREATE TABLE"))
                    shown_all["seen" if g_t <= tables_in(heads, tables) else "not seen"] += 1
                    shown_all["%s|%s" % (cat, "seen" if g_t <= tables_in(heads, tables)
                                         else "not seen")] += 1
    n = sum(total.values())
    print("Wrong answers across the four scale rounds: %d" % n)
    for cat in CATS:
        print("  %-8s %4d  %3.0f%%" % (cat, total[cat], 100.0 * total[cat] / n))
    print("\nBy round and arm (right / missing / table / column / reading):")
    for (r, a), c in by_round_arm.items():
        print("  %-7s %-9s %3d / %3d / %3d / %3d / %3d"
              % (r, a, c["right"], c["missing"], c["table"], c["column"], c["reading"]))
    m = shown_all["seen"] + shown_all["not seen"]
    if m:
        print("\nSCALE3 and SCALE4 misses: was every gold table in the view for the question's "
              "own text?")
        print("  seen %d, not seen %d, of %d" % (shown_all["seen"], shown_all["not seen"], m))
        for cat in CATS:
            s, u = shown_all["%s|seen" % cat], shown_all["%s|not seen" % cat]
            if s or u:
                print("    %-8s seen %3d   not seen %3d" % (cat, s, u))
    return 0


if __name__ == "__main__":
    sys.exit(main())
