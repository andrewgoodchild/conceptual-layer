#!/usr/bin/env python3
"""Where does a literal live? `lookup "<text>"` searches every column of every table for a
value equal to, containing, or resembling the text (case-insensitive) and says which column
holds it -- as the model's value type and reading when a model is given -- with sample values
and row counts. It also lists the types whose names contain the text. It says nothing about
which one a question means.

    lookup "Czech Republic"      lookup "Death Touch"      lookup power
"""
import difflib, json, os, sqlite3, sys

DB = os.environ["DB"]
MODEL = os.environ.get("MODEL")


def type_names(model):
    """(table name, column name) -> (value type, reading) from the model's mapping."""
    sys.path.insert(0, os.path.join(os.environ["ROOT"], "conquer"))
    import parser as parser_mod                                   # noqa: E402
    lex = parser_mod.Lexicon(model)
    cols = {c["id"]: c for c in model["mapping"]["columns"]}
    tables = {t["id"]: t["name"] for t in model["mapping"]["tables"]}
    concepts = {c["id"]: c for c in model["concepts"]}
    owner = {}
    for c in model["concepts"]:
        for r in c.get("roles", []):
            owner[r["id"]] = (c, r)
    out = {}
    for rm in model["mapping"]["roleMap"]:
        fact, role = owner.get(rm["role"], (None, None))
        if fact is None:
            continue
        player = concepts.get(role["player"], {})
        if player.get("kind") != "value":
            continue
        for cid in rm["columns"]:
            c = cols.get(cid)
            if c is not None:
                out[(tables[c["table"]], c["name"])] = (player["name"], lex.verbalise(fact))
    return out


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        sys.exit(__doc__)
    text = sys.argv[1].strip()
    q = text.casefold()
    model = json.load(open(MODEL)) if MODEL else None
    names = type_names(model) if model else {}
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")

    def label(table, col):
        if names.get((table, col)):
            vt, reading = names[(table, col)]
            return "%-32s (%s)" % (vt, reading)
        if model:
            return None                       # a column the model does not read (a key)
        return "%s.%s" % (table, col)

    exact, contains, near = [], [], []
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        n = conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
        for row in conn.execute('PRAGMA table_info("%s")' % table):
            col = row[1]
            lab = label(table, col)
            if lab is None:
                continue
            base = 'FROM "%s" WHERE "%s" IS NOT NULL' % (table, col)
            try:
                hit = conn.execute('SELECT COUNT(*) %s AND lower(CAST("%s" AS TEXT)) = ?'
                                   % (base, col), (q,)).fetchone()[0]
                if hit:
                    exact.append((lab, hit, n))
                rows = conn.execute(
                    'SELECT CAST("%s" AS TEXT), COUNT(*) %s AND lower(CAST("%s" AS TEXT)) LIKE ? '
                    'AND lower(CAST("%s" AS TEXT)) <> ? GROUP BY 1 ORDER BY 2 DESC LIMIT 5'
                    % (col, base, col, col), ("%" + q + "%", q)).fetchall()
                if rows:
                    contains.append((lab, rows))
                # resemblance, over columns with few distinct values: codes and categories
                distinct = conn.execute('SELECT COUNT(DISTINCT "%s") %s' % (col, base)).fetchone()[0]
                if 0 < distinct <= 300:
                    vals = conn.execute('SELECT CAST("%s" AS TEXT), COUNT(*) %s GROUP BY 1'
                                        % (col, base)).fetchall()
                    for v, c in vals:
                        vl = v.casefold()
                        if vl == q or q in vl:
                            continue
                        r = difflib.SequenceMatcher(None, q, vl).ratio()
                        abbrev = len(vl) <= 4 and q.startswith(vl[:2]) and vl.isalpha()
                        if r >= 0.6 or abbrev:
                            near.append((r + (0.3 if abbrev else 0), lab, v, c))
            except sqlite3.Error:
                continue

    print("'%s'" % text)
    if exact:
        print("  is a value of:")
        for lab, hit, n in exact:
            print("    %s   %d of %d rows" % (lab, hit, n))
    if contains:
        print("  is contained in values of:")
        for lab, rows in contains:
            print("    %s" % lab)
            for v, c in rows:
                print("        %r  x%d" % (v[:60], c))
    near.sort(reverse=True)
    if near:
        print("  resembles a value of (codes and categories; check the meaning):")
        for _, lab, v, c in near[:8]:
            print("    %s   %r  x%d" % (lab, v[:60], c))
    if model:
        hits = sorted({vt for vt, _ in names.values() if q.replace(" ", "") in vt.casefold()}
                      | {c["name"] for c in model["concepts"] if c["kind"] != "fact"
                         and q.replace(" ", "") in c["name"].casefold()})
        if hits:
            print("  types whose name contains it: " + ", ".join(hits))
    if not (exact or contains or near):
        print("  no value equal to, containing, or resembling it in any column")


if __name__ == "__main__":
    main()
