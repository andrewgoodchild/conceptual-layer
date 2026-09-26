#!/usr/bin/env python3
"""Check an answer against the knowledge base it is supposed to be reading.

The dominant failure on the SQLite tier is not a refusal and not an execution error: it is
an answer of exactly the right shape, returning exactly the right rows, with one computed
column carrying a different number (finding 154). That is a disagreement about what a
definition means, and the definitions are *written down* -- LiveSQLBench ships each
database's knowledge base as `<db>_kb.jsonl`, where a `calculation_knowledge` entry states
its formula in LaTeX.

So the disagreement is mechanically checkable. A question naming a defined term invokes
that formula; the formula names columns; the answer's SQL either reads those columns or it
does not. This is the ontology-based query checking of Sequeda, Allemang and Jacob (IEEE
Data Eng. Bull. 47(4), 2024), whose deterministic checker took their accuracy from 54% to
72.55% -- applied to a knowledge base of formulas rather than to an ontology of paths.

It checks *both sides*. Run against the gold and it says which golds contradict their own
knowledge base, which is the ceiling: an answer cannot be scored right against a gold that
is wrong. Run against ours and it says which of our answers to distrust.

*The definition check on its own does not discriminate.* It flags 26 of our 180 and 23 of
the golds, at 58% precision against a 61% base rate -- no better than guessing, and gold
violating its own knowledge base as often as we do is itself the finding. What does
discriminate is `--columns`: whether an answer reads the same database columns as the gold.
Reading gold's columns doubles the chance of being right (53% against 24%), and the columns
responsible recur within a database rather than scattering across questions.

That comparison needs the gold, so it is a diagnostic and not a runtime check. It is here
because it says where to look: a handful of column choices per database, not 110 separate
judgement calls.

    conformance.py --arm DIR [--db NAME] [--gold] [--columns] [-v]
"""
import argparse
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DBS = os.path.join(DATA, "sqlite_tier")

# `\text{SnrRatio}`, `\mathrm{...}`, or a bare CamelCase run inside the formula.
TEXT = re.compile(r"\\(?:text|mathrm|mathit|textit|textbf)\s*\{([^{}]*)\}")
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
# The abbreviation a definition is cited by: "Signal Stability Metric (SSM)".
ABBREV = re.compile(r"\(([A-Z][A-Za-z0-9]{1,9})\)\s*$")


def columns_of(db):
    """Every column name in the database, casefolded. The formula writes `SnrRatio` and
    the table declares `snrratio`; only the spelling differs."""
    path = os.path.join(DBS, "%s_template.sqlite" % db)
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        names = set()
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for row in con.execute('PRAGMA table_info("%s")' % t):
                names.add(row[1].casefold())
        return names
    finally:
        con.close()


def load_kb(db):
    path = os.path.join(DBS, "%s_kb.jsonl" % db)
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def formula_columns(entry, columns):
    """The database columns a definition's formula names.

    Only tokens that are really columns: a formula also names itself, its own abbreviation,
    and functions like `\\log`, none of which an answer has to mention.
    """
    text = entry.get("definition") or ""
    found = set()
    for token in TEXT.findall(text):
        for w in WORD.findall(token):
            if w.casefold() in columns:
                found.add(w.casefold())
    # Some definitions are written without \text{}; fall back to bare words.
    for w in WORD.findall(text):
        if w.casefold() in columns:
            found.add(w.casefold())
    return found


def expand(ids, by_id, seen=None):
    """A definition built on other definitions requires their columns too."""
    seen = seen if seen is not None else set()
    for i in list(ids):
        if i in seen or i not in by_id:
            continue
        seen.add(i)
        kids = by_id[i].get("children_knowledge")
        kids = kids if isinstance(kids, list) else ([kids] if isinstance(kids, int) else [])
        expand([k for k in kids if k != -1], by_id, seen)
    return seen


def invoked(question, kb):
    """The knowledge entries a question names, by full term or by abbreviation."""
    q = question.casefold()
    hits = []
    for e in kb:
        name = (e.get("knowledge") or "").strip()
        if not name:
            continue
        bare = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        m = ABBREV.search(name)
        if bare and bare.casefold() in q:
            hits.append(e["id"])
        elif m and re.search(r"\b%s\b" % re.escape(m.group(1)), question):
            hits.append(e["id"])
    return hits


def sql_identifiers(sql):
    """Every word the statement uses, casefolded -- column names among them. Crude on
    purpose: a false negative here (thinking the answer reads a column it does not) is
    worse than the noise of counting a keyword."""
    return {w.casefold() for w in WORD.findall(sql)}


def check(question, sql, kb, columns):
    """Complaints: a column a definition the question invokes names, that the SQL never
    reads. Returns a list of `(definition name, missing columns)`."""
    by_id = {e["id"]: e for e in kb}
    ids = expand(invoked(question, kb), by_id)
    used = sql_identifiers(sql)
    out = []
    for i in sorted(ids):
        e = by_id.get(i)
        if not e or e.get("type") != "calculation_knowledge":
            continue
        want = formula_columns(e, columns)
        missing = sorted(want - used)
        if want and missing:
            out.append((e.get("knowledge"), missing))
    return out


def identity_classes(db):
    """Columns that name the same instance, as a map from column to its class.

    These schemas split one entity across several tables and give every other table a
    foreign key to each half, so `recreg` and `botdetreg` are two spellings of one robot.
    A foreign key whose child has exactly one row per referenced value joins two names for
    the same thing; counting those as a disagreement makes an answer look wrong when only
    the spelling differs.
    """
    path = os.path.join(DBS, "%s_template.sqlite" % db)
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            for fk in con.execute('PRAGMA foreign_key_list("%s")' % t):
                frm, to_t, to_c = fk[3], fk[2], fk[4]
                try:
                    n_rows, n_vals = con.execute(
                        'SELECT COUNT(*), COUNT(DISTINCT "%s") FROM "%s"' % (frm, t)).fetchone()
                except sqlite3.Error:
                    continue
                if n_rows and n_rows == n_vals:
                    a, b = find((t, frm.casefold())), find((to_t, (to_c or "").casefold()))
                    if a != b:
                        parent[a] = b
        rep = {}
        for t in tables:
            for row in con.execute('PRAGMA table_info("%s")' % t):
                c = row[1].casefold()
                rep.setdefault(c, set()).add(find((t, c)))
        # A class is named for one member, as `table.column`, so the report reads.
        return {c: " / ".join(sorted("%s.%s" % r for r in v)) for c, v in rep.items()}
    finally:
        con.close()


def column_report(tasks, gt, only_db=None):
    """Does an answer read the columns the gold reads? The strongest predictor of
    correctness measured on this tier, and the one that says where to look."""
    import collections
    cols, classes, rows = {}, {}, []
    for iid, t in sorted(tasks.items()):
        db = t["selected_database"]
        if only_db and db != only_db:
            continue
        if db not in cols:
            cols[db], classes[db] = columns_of(db), identity_classes(db)
        cl = classes[db]
        g = {cl.get(c, c) for c in sql_identifiers(gt[iid]["sol_sql"][0]) & cols[db]}
        p = {cl.get(c, c) for c in sql_identifiers(t["pred_sqls"][0]) & cols[db]}
        rows.append({"id": iid, "db": db, "ok": t.get("status") == "success", "same": g == p,
                     "gold_only": sorted(g - p), "ours_only": sorted(p - g)})
    tab = collections.Counter((r["ok"], r["same"]) for r in rows)
    print("columns read, against the gold's (identity aliases collapsed)")
    print("                      same   different")
    for ok in (True, False):
        print("  %-16s %8d %11d" % ("correct" if ok else "wrong",
                                    tab[(ok, True)], tab[(ok, False)]))
    for label, same in (("same", True), ("different", False)):
        n = tab[(True, same)] + tab[(False, same)]
        if n:
            print("  P(correct | %-9s) %3.0f%%" % (label, 100.0 * tab[(True, same)] / n))
    # Which columns recur: a database's failures usually share a few, which is what makes
    # this worth acting on -- one modelling decision, several questions.
    c = collections.Counter()
    for r in rows:
        if not r["ok"]:
            for col in r["ours_only"] + r["gold_only"]:
                c[(r["db"], col)] += 1
    print("\n  columns implicated in 3 or more of a database's failures:")
    for (db, col), n in c.most_common():
        if n >= 3:
            print("    %-11s %-48s %d" % (db, col[:48], n))
    return rows


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arm", help="directory of <database>/answers.json (ConQuer answers)")
    p.add_argument("--gold", action="store_true", help="check the gold SQL instead")
    p.add_argument("--columns", action="store_true",
                   help="compare the columns read against the gold's, not the definitions")
    p.add_argument("--pred", help="a jsonl of predictions with pred_sqls, as the harness writes")
    p.add_argument("--db")
    p.add_argument("--model-dir", default=os.path.join(HERE, "work", "models-sqlite-tier"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    gt = {json.loads(l)["instance_id"]: json.loads(l) for l in
          open(os.path.join(DATA, "livesqlbench_base_lite_sqlite_gt.jsonl"))}
    src = args.pred or os.path.join(HERE, "work", "official",
                                    "run_pred_simple_output_with_status.jsonl")
    tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(src)}

    if args.columns:
        column_report(tasks, gt, args.db)
        return 0

    cache, flagged, clean = {}, [], []
    for iid, t in sorted(tasks.items()):
        db = t["selected_database"]
        if args.db and db != args.db:
            continue
        if db not in cache:
            cache[db] = (load_kb(db), columns_of(db))
        kb, columns = cache[db]
        sql = (gt[iid]["sol_sql"][0] if args.gold else t["pred_sqls"][0])
        if not sql:
            continue
        bad = check(t["query"], sql, kb, columns)
        (flagged if bad else clean).append((iid, t.get("status") == "success", bad))

    n = len(flagged) + len(clean)
    side = "gold" if args.gold else "ours"
    print("%s: %d of %d answers read every column their definitions name; %d do not"
          % (side, len(clean), n, len(flagged)))
    if not args.gold:
        tp = sum(1 for _, ok, _ in flagged if not ok)
        fp = sum(1 for _, ok, _ in flagged if ok)
        fn = sum(1 for _, ok, _ in clean if not ok)
        tn = sum(1 for _, ok, _ in clean if ok)
        print("  against the score:")
        print("    flagged and wrong   %3d   (a true warning)" % tp)
        print("    flagged and right   %3d   (a false alarm)" % fp)
        print("    clean and wrong     %3d   (missed)" % fn)
        print("    clean and right     %3d" % tn)
        if tp + fp:
            print("  precision %.0f%%  of what it flags is actually wrong" % (100.0 * tp / (tp + fp)))
        if tp + fn:
            print("  recall    %.0f%%  of the wrong answers it catches" % (100.0 * tp / (tp + fn)))
    if args.verbose:
        for iid, ok, bad in flagged[:40]:
            print("   %-14s %-7s %s" % (iid, "right" if ok else "WRONG",
                                        "; ".join("%s missing %s" % (n_, ",".join(m))
                                                  for n_, m in bad)[:150]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
