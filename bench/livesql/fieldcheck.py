#!/usr/bin/env python3
"""Check the data against what the documentation says it is.

Documentation goes stale and data acquires bugs that nobody notices, so a knowledge base
is a claim about the data rather than a description of it. Every claim here is testable
against the rows, and three kinds of failure change answers:

  decoy       a stored column named for a defined quantity whose values do not satisfy the
              definition. credit's `networth` is documented as assets minus liabilities and
              equals that on **0 of 1000 rows**; the gold computes it and ignores the
              column, so a writer who trusted the column would have been wrong every time.

  mixed       a numeric column holding both integers and reals. SQLite divides those two
              different ways, so one expression takes integer division on some rows and not
              others. 72 columns across the tier are like this, and the gold for polar_9
              computes `1 - environmentalimpactindex/10` -- right on the 893 real rows,
              wrong on the 107 integer ones. Of the 13 questions whose SQL divides by such
              a column, 2 are correct; elsewhere the rate is 41%.

  miscast     a column whose storage class contradicts its documented type -- documented
              REAL, stored as text.

    fieldcheck.py [--db NAME] [--kind decoy|mixed|miscast] [-v]
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DBS = os.path.join(DATA, "sqlite_tier")

DECL = re.compile(r"\b(VARCHAR|TEXT|CHAR|INTEGER|INT|BIGINT|SMALLINT|NUMERIC|DECIMAL|REAL|"
                  r"FLOAT|DOUBLE|BOOLEAN|DATE|TIMESTAMP|TIME|JSONB?)\b", re.I)
NUMERIC_DECL = {"INTEGER", "INT", "BIGINT", "SMALLINT", "NUMERIC", "DECIMAL", "REAL",
                "FLOAT", "DOUBLE"}
TEXT_DECL = {"VARCHAR", "TEXT", "CHAR"}


def databases():
    return sorted(f[:-len("_template.sqlite")] for f in os.listdir(DBS)
                  if f.endswith("_template.sqlite"))


def connect(db):
    return sqlite3.connect("file:%s?mode=ro" % os.path.join(DBS, "%s_template.sqlite" % db),
                           uri=True)


def tables(con):
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]


# -- LaTeX to SQL ----------------------------------------------------------------------
# The vocabulary is small and regular: 842 \text, 510 \times, 374 \frac, and a tail of
# \sqrt, \log, \cdot and absolute-value bars. A definition using \sum or set membership is
# an aggregate over rows the formula does not name, and is left untranslated rather than
# guessed at.
UNTRANSLATABLE = re.compile(r"\\(sum|in|mid|begin|end|max|min|mathcal|forall|exists)\b")


FUNCS = {"sqrt", "log", "abs", "power", "exp", "ln"}


def translate(segment, columns):
    """One side of an `=` as a SQL expression, or None if it is prose.

    A definition is often written as a chain -- `Net Worth = \\text{Total Assets} -
    \\text{Total Liabilities} = totassets - totliabs = networth` -- where the first
    segment is the term, a middle one is the formula in column names, and the last is the
    column that stores it. Each segment is translated on its own and the ones that are
    real expressions are compared against each other and against the stored column.
    """
    x = re.sub(r"\\left|\\right", "", segment)
    x = re.sub(r"\\(times|cdot)", "*", x)
    frac = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
    for _ in range(8):
        nxt = frac.sub(lambda m: "((%s)/(%s))" % (m.group(1), m.group(2)), x)
        if nxt == x:
            break
        x = nxt
    x = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"SQRT(\1)", x)
    x = re.sub(r"\\log\s*", "LOG", x)
    x = re.sub(r"\|([^|]+)\|", r"ABS(\1)", x)
    x = re.sub(r"(\d+(?:\.\d+)?)\s*\^\s*\{?(\d+)\}?",
               lambda m: repr(float(m.group(1)) ** int(m.group(2))), x)
    # \text{Col} and bare words alike resolve to a column when the table has one; the
    # spaces come out first, so `\text{Total Assets}` gets a chance to be `totalassets`.
    def name(m):
        w = m.group(1).strip()
        for cand in (w, w.replace(" ", "")):
            if cand.casefold() in columns:
                return '"%s"' % cand
        return w
    x = re.sub(r"\\(?:text|mathrm|mathit)\s*\{([^{}]*)\}", name, x)
    if "\\" in x or "{" in x or "}" in x or "$" in x:
        return None
    # Every remaining word has to be a column or a function; anything else is prose.
    out, used = [], set()
    for tok in re.finditer(r'"[^"]+"|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[-+*/()<>,.]|\s+', x):
        t = tok.group(0)
        if t.startswith('"'):
            used.add(t.strip('"').casefold())
        elif re.match(r"^[A-Za-z_]", t):
            if t.casefold() in columns:
                used.add(t.casefold())
                t = '"%s"' % t
            elif t.casefold() not in FUNCS:
                return None
        out.append(t)
    if "".join(out).strip() != x.strip().replace('"', '"'):
        pass                                  # the scan is a filter, not a parser
    expr = "".join(out).strip()
    return (expr, used) if expr and used else None


def split_definition(definition):
    """A definition's segments, split on `=` outside the prose tail."""
    # The prose tail is written several ways -- `$, where ...`, `, where ...`, and
    # `, \text{ where ...}` -- and leaving it in makes the whole formula untranslatable,
    # which silently dropped polar's `waterqualityindex / 100` from the truncation check.
    head = re.split(r"\$?\s*,?\s*\\text\s*\{\s*where\b|\$,\s*where\b|,\s*where\b",
                    definition, maxsplit=1)[0]
    head = head.replace("$", "")
    if UNTRANSLATABLE.search(head) or "=" not in head:
        return []
    return [s for s in head.split("=") if s.strip()]


# -- the three checks ------------------------------------------------------------------

def check_decoys(db, con):
    """A stored column named by a definition: does it hold what the definition says?

    Also compares two formulas in the same definition against each other -- a chained
    definition states the same quantity twice, and they can disagree.
    """
    kb_path = os.path.join(DBS, "%s_kb.jsonl" % db)
    if not os.path.exists(kb_path):
        return []
    entries = [json.loads(l) for l in open(kb_path)
               if json.loads(l).get("type") == "calculation_knowledge"]
    out = []
    for t in tables(con):
        cols = {r[1].casefold() for r in con.execute('PRAGMA table_info("%s")' % t)}
        for e in entries:
            segs = [translate(s, cols) for s in split_definition(e.get("definition") or "")]
            segs = [s for s in segs if s]
            stored = [expr for expr, used in segs if len(used) == 1 and expr.strip('"').casefold() in cols
                      and re.fullmatch(r'"[^"]+"', expr.strip())]
            formulas = [expr for expr, used in segs if len(used) > 1]
            for col in stored:
                for f in formulas:
                    try:
                        agree, total = con.execute(
                            'SELECT SUM(CASE WHEN ABS(%s - (%s)) < 1e-6 THEN 1 ELSE 0 END), '
                            'COUNT(*) FROM "%s" WHERE %s IS NOT NULL' % (col, f, t, col)
                        ).fetchone()
                    except sqlite3.Error:
                        continue
                    if total:
                        out.append((t, col.strip('"'), e["knowledge"], agree or 0, total, f))
    return out


def check_mixed(db, con):
    """A numeric column holding integers on some rows and reals on others."""
    out = []
    for t in tables(con):
        for row in con.execute('PRAGMA table_info("%s")' % t):
            c = row[1]
            try:
                k = dict(con.execute('SELECT typeof("%s"), COUNT(*) FROM "%s" GROUP BY 1'
                                     % (c, t)).fetchall())
            except sqlite3.Error:
                continue
            if k.get("integer") and k.get("real"):
                out.append((t, c, k["integer"], k["real"]))
    return out


def check_miscast(db, con):
    """A column whose storage class contradicts the type its documentation names."""
    path = os.path.join(DBS, "%s_column_meaning_base.json" % db)
    if not os.path.exists(path):
        return []
    doc = json.load(open(path))
    out = []
    for key, text in doc.items():
        parts = str(key).split("|")
        if len(parts) != 3 or not isinstance(text, str):
            continue
        _, t, c = parts
        m = DECL.search(text)
        if not m:
            continue
        declared = m.group(1).upper()
        try:
            k = dict(con.execute('SELECT typeof("%s"), COUNT(*) FROM "%s" '
                                 'WHERE "%s" IS NOT NULL GROUP BY 1' % (c, t, c)).fetchall())
        except sqlite3.Error:
            continue
        if not k:
            continue
        if declared in NUMERIC_DECL and k.get("text"):
            out.append((t, c, declared, "text on %d rows" % k["text"]))
        elif declared in TEXT_DECL and (k.get("integer") or k.get("real")):
            out.append((t, c, declared, "numeric on %d rows"
                        % (k.get("integer", 0) + k.get("real", 0))))
    return out


# The range first, then the column named nearest before it. Scanning for the column first
# matches whatever word happens to come earliest -- "Debt" in "Debt-to-Income ratio
# (debincratio) ranges from 0-1" -- and then skips past the sentence that names the column.
RANGE = re.compile(r"\branges?\s+from\s+(-?\d+(?:\.\d+)?)\s*(?:to|-|–|through)\s*"
                   r"(-?\d+(?:\.\d+)?)", re.I)
WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def ranges_in(text, known):
    """`(column, low, high)` for each range the prose states about a known column."""
    out = []
    for m in RANGE.finditer(text):
        before = text[max(0, m.start() - 90):m.start()]
        cand = [w for w in WORDS.findall(before) if w.casefold() in known]
        if cand:
            out.append((cand[-1], m.group(1), m.group(2)))
    return out


def check_ranges(db, con):
    """The knowledge base states a column's range in prose. Does the data respect it?

    "Debt-to-Income ratio (debincratio) ranges from 0-1 (or above)" is a claim, and a
    column that leaves its stated range is either mis-scaled or mis-documented. The
    parenthetical "(or above)" is why the upper bound is reported rather than enforced:
    what matters is the size of the excursion, not that there is one.
    """
    kb_path = os.path.join(DBS, "%s_kb.jsonl" % db)
    if not os.path.exists(kb_path):
        return []
    where = {}
    for t in tables(con):
        for r in con.execute('PRAGMA table_info("%s")' % t):
            where.setdefault(r[1].casefold(), (t, r[1]))
    out = []
    seen = set()
    for line in open(kb_path):
        e = json.loads(line)
        text = " ".join(str(e.get(k) or "") for k in ("knowledge", "description", "definition"))
        for col, lo, hi in ranges_in(text, set(where)):
            if (db, col.casefold()) in seen:
                continue
            seen.add((db, col.casefold()))
            t, real = where[col.casefold()]
            # A range stated near a JSON column is about a field inside the document, not
            # the column: "ranges from 0-1" beside `detection_score_profile` is describing
            # one of its scores. Only a numeric column can leave a numeric range.
            try:
                kinds = {k for (k,) in con.execute(
                    'SELECT DISTINCT typeof("%s") FROM "%s" WHERE "%s" IS NOT NULL'
                    % (real, t, real))}
            except sqlite3.Error:
                continue
            if not kinds or kinds - {"integer", "real"}:
                continue
            try:
                below, above, total, mn, mx = con.execute(
                    'SELECT SUM(CASE WHEN "%s" < %s THEN 1 ELSE 0 END), '
                    'SUM(CASE WHEN "%s" > %s THEN 1 ELSE 0 END), COUNT(*), MIN("%s"), MAX("%s") '
                    'FROM "%s" WHERE "%s" IS NOT NULL'
                    % (real, lo, real, hi, real, real, t, real)).fetchone()
            except sqlite3.Error:
                continue
            if total and ((below or 0) or (above or 0)):
                out.append((t, real, lo, hi, below or 0, above or 0, total, mn, mx))
    return out


def check_truncation(db, con):
    """A knowledge-base formula that divides one whole number by another.

    `check_mixed` looks for a column storing both integers and reals, and two writers
    independently reported that it flags the smaller hazard. A column stored as an integer
    on *every* row truncates on every row rather than on a tenth of them, and it is
    invisible to that test. polar's `waterqualityindex / 100` is integer division on all
    1000 rows; vaccine's `TempDevCount / 100` and `CritEvents / 10` reduce two formulas to
    their other terms entirely.

    So the question is not what a column stores but what a formula does with it: a division
    whose numerator and denominator are both whole numbers is truncated by SQLite, whatever
    the quantity was meant to be.
    """
    kb_path = os.path.join(DBS, "%s_kb.jsonl" % db)
    if not os.path.exists(kb_path):
        return []
    # every column, and separately the ones holding only integers. The formula has to be
    # translated against the *whole* vocabulary -- restricting it to integer columns made
    # any formula that also mentions a real column untranslatable, which is most of them.
    whole, where, every = set(), {}, set()
    for t in tables(con):
        for row in con.execute('PRAGMA table_info("%s")' % t):
            c = row[1]
            every.add(c.casefold())
            try:
                kinds = {k for (k,) in con.execute(
                    'SELECT DISTINCT typeof("%s") FROM "%s" WHERE "%s" IS NOT NULL'
                    % (c, t, c))}
            except sqlite3.Error:
                continue
            if kinds == {"integer"}:
                whole.add(c.casefold())
                where.setdefault(c.casefold(), (t, c))
    if not whole:
        return []
    out, seen = [], set()
    for line in open(kb_path):
        e = json.loads(line)
        if e.get("type") != "calculation_knowledge":
            continue
        for seg in split_definition(e.get("definition") or ""):
            tr = translate(seg, every)
            if not tr:
                continue
            expr = tr[0]
            # `a / b` where a is a whole-number column and b is a whole number
            for m in re.finditer(r'"([^"]+)"\s*\)*\s*/\s*\(*\s*(?:"([^"]+)"|(\d+))(?!\.)',
                                 expr):
                num, den_col, den_lit = m.group(1), m.group(2), m.group(3)
                if num.casefold() not in whole:
                    continue
                if den_col and den_col.casefold() not in whole:
                    continue
                key = (e["knowledge"], num, den_col or den_lit)
                if key in seen:
                    continue
                seen.add(key)
                t, real = where[num.casefold()]
                out.append((t, real, e["knowledge"], den_col or den_lit))
    return out


def check_pins(db, con):
    """Terms the knowledge base pins to a stored column, by naming it in the chain.

    `DTI = \\frac{Total Monthly Debt Payments}{Monthly Income} = debincratio` states that
    the column *is* the quantity, without giving a formula over columns that could check
    it. That is the answer to "which column" for that term, which is worth saying even
    when there is nothing to verify."""
    kb_path = os.path.join(DBS, "%s_kb.jsonl" % db)
    if not os.path.exists(kb_path):
        return []
    cols = set()
    where = {}
    for t in tables(con):
        for r in con.execute('PRAGMA table_info("%s")' % t):
            cols.add(r[1].casefold())
            where.setdefault(r[1].casefold(), (t, r[1]))
    out = []
    for line in open(kb_path):
        e = json.loads(line)
        if e.get("type") != "calculation_knowledge":
            continue
        for seg in split_definition(e.get("definition") or ""):
            tr = translate(seg, cols)
            if tr and len(tr[1]) == 1 and re.fullmatch(r'"[^"]+"', tr[0].strip()):
                c = tr[0].strip().strip('"').casefold()
                out.append((where[c][0], where[c][1], e["knowledge"]))
                break
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("--kind", choices=("decoy", "mixed", "miscast", "range", "pin",
                                      "truncation"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    totals = collections.Counter()
    for db in databases():
        if args.db and db != args.db:
            continue
        con = connect(db)
        try:
            if args.kind in (None, "decoy"):
                for t, c, term, agree, total, sql in check_decoys(db, con):
                    totals["decoy" if agree < total else "derived"] += 1
                    if agree < total:
                        print("decoy   %-10s %s.%s holds %s on %d of %d rows"
                              % (db, t, c, term, agree, total))
                        if args.verbose:
                            print("          the definition is %s" % sql)
                    elif args.verbose:
                        print("derived %-10s %s.%s equals %s on every row -- safe to read"
                              % (db, t, c, term))
            if args.kind in (None, "mixed"):
                rows = check_mixed(db, con)
                totals["mixed"] += len(rows)
                if args.verbose:
                    for t, c, i, r in rows:
                        print("mixed   %-10s %s.%s  %d integer, %d real" % (db, t, c, i, r))
            if args.kind in (None, "truncation"):
                for t, c, term, den in check_truncation(db, con):
                    totals["truncation"] += 1
                    print("truncate %-10s %s.%s holds only whole numbers, and %s divides it "
                          "by %s -- SQLite truncates that on every row"
                          % (db, t, c, term, den))
            if args.kind in (None, "range"):
                for t, c, lo, hi, below, above, total, mn, mx in check_ranges(db, con):
                    totals["range"] += 1
                    print("range   %-10s %s.%s documented %s-%s, %d below and %d above "
                          "of %d (%s..%s)" % (db, t, c, lo, hi, below, above, total, mn, mx))
            if args.kind in (None, "pin"):
                rows = check_pins(db, con)
                totals["pin"] += len(rows)
                if args.verbose:
                    for t, c, term in rows:
                        print("pin     %-10s %s.%s is %s" % (db, t, c, term))
            if args.kind in (None, "miscast"):
                for t, c, declared, got in check_miscast(db, con):
                    totals["miscast"] += 1
                    print("miscast %-10s %s.%s documented %s, %s" % (db, t, c, declared, got))
        finally:
            con.close()
    print()
    print("decoy   %3d  a stored field that does not hold what its definition says"
          % totals["decoy"])
    print("derived %3d  a stored field that does, on every row -- read it directly"
          % totals["derived"])
    print("mixed   %3d  a numeric column SQLite will divide two different ways"
          % totals["mixed"])
    print("miscast %3d  a storage class contradicting the documented type" % totals["miscast"])
    print("range   %3d  a column leaving the range its documentation states" % totals["range"])
    print("truncate %2d  a formula dividing one whole number by another" % totals["truncation"])
    print("pin     %3d  a term the knowledge base pins to a stored column" % totals["pin"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
