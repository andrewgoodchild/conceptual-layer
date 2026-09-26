#!/usr/bin/env python3
"""Load a LiveSQLBench PostgreSQL dump into SQLite, so the population can be read.

Two experiments have been blocked on the same thing for weeks: `jsonshape.classify`, which
has to tell a record from a map from a bag and has only ever seen a fixture, and rule 9c,
which scores candidate references on value containment and is the only hope for the 3% that
name-based inference manages here (finding 84). Both need data, and the public release ships
three sample rows per table.

The dumps do not need PostgreSQL to be read. They are `pg_dump --inserts` output: plain
`CREATE TABLE`, plain `INSERT ... VALUES`, and constraints added afterwards by `ALTER TABLE`.
Folding the constraints back into the CREATE -- SQLite cannot add a key to an existing table
-- is the only real translation.

**This is for analysis, not for answers.** SQLite is not PostgreSQL: no jsonb, looser typing,
different functions. Classifying a document's shape and measuring value containment do not
care. Scoring a benchmark would, and that still wants the real server.

    load.py DATABASE [-o out.sqlite] [--limit N]
"""

import argparse
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DUMPS = os.path.join(HERE, "data", "dumps", "postgre_table_dumps_large")

CREATE = re.compile(r"^CREATE TABLE public\.(\S+)\s*\((.*)\)\s*$", re.S | re.I)
CONSTRAINT = re.compile(
    r"^ALTER TABLE (?:ONLY )?public\.(\S+)\s+ADD CONSTRAINT \S+\s+(.*)$", re.S | re.I)
INSERT = re.compile(r"^INSERT INTO public\.(\S+)", re.I)
SKIP = re.compile(r"^(SET |SELECT pg_catalog|\\restrict|\\unrestrict|ALTER TABLE .*OWNER TO|"
                  r"CREATE SEQUENCE|ALTER SEQUENCE|SELECT setval|CREATE INDEX|COMMENT ON|"
                  r"GRANT |REVOKE |CREATE SCHEMA|ALTER SCHEMA)", re.I)
# SQLite has no jsonb and no timestamptz, but it takes any type name and applies affinity by
# substring. Mapping the few that would land on the wrong affinity is enough. Never inside a
# quoted identifier: pg_dump writes a column named for a type as `"timestamp" timestamp
# without time zone`, and solar_panel's CleaningRobotTelemetry came out with a column called
# TEXT and none called timestamp.
_TYPE = r'(?<!")\b%s\b(?!")'
TYPES = [(re.compile(_TYPE % r"jsonb?", re.I), "TEXT"),
         (re.compile(_TYPE % r"timestamp(?: with(?:out)? time zone)?", re.I), "TEXT"),
         (re.compile(_TYPE % r"character varying", re.I), "TEXT"),
         (re.compile(_TYPE % r"double precision", re.I), "REAL"),
         (re.compile(r"\bUSING btree\b", re.I), "")]


def statements(text):
    """Split on semicolons that are not inside a string literal, dropping comments.

    Comments have to go in the same scan rather than before or after it. pg_dump's banner is
    `-- Name: certifications; Type: TABLE; Schema: public` -- it carries semicolons, so
    splitting first cuts it into pieces; and a `--` inside a JSON value is not a comment, so
    stripping first corrupts the data.
    """
    out, buf, quote = [], [], False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":       # '' is an escaped quote
                    buf.append("''")
                    i += 2
                    continue
                quote = False
            buf.append(ch)
        elif ch == "-" and text[i:i + 2] == "--":
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        elif ch == "'":
            quote = True
            buf.append(ch)
        elif ch == ";":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
        else:
            buf.append(ch)
        i += 1
    s = "".join(buf).strip()
    if s:
        out.append(s)
    return out


def clean(sql):
    # A schema-qualified type -- `visacls public.enum_visa_class`, a PostgreSQL enum -- is a
    # syntax error in SQLite because of the dot, and the whole CREATE TABLE is then lost.
    # Nine tables went missing this way, and the two central ones of
    # labor_certification_applications with them. The enum becomes a plain type name; SQLite
    # takes any type name and gives it affinity by substring, which for these is TEXT.
    sql = re.sub(r"\bpublic\.", "", sql)
    for pattern, repl in TYPES:
        sql = pattern.sub(repl, sql)
    # `id integer DEFAULT nextval('...')` -- the sequence is gone, so is its default.
    sql = re.sub(r"\s+DEFAULT\s+nextval\([^)]*\)", "", sql, flags=re.I)
    sql = re.sub(r"::[A-Za-z_][A-Za-z0-9_ ]*(\[\])?", "", sql)      # ::text casts
    return sql


def load(db, out, limit=None):
    src = os.path.join(DUMPS, "%s_template" % db)
    if not os.path.isdir(src):
        raise SystemExit("no dump for %r under %s" % (db, DUMPS))
    tables, constraints, inserts = {}, {}, []
    # Each dump directory holds one `.sql` per table *and* a `<db>_full.sql`. The full file
    # repeats the schema, and for some databases the data as well -- reading both loads every
    # row twice, which passes in silence while no primary key is enforced and is exactly how
    # a 211,988-row database looked like 423,976 rows. The per-table files are the ones that
    # always carry data, so those are authoritative and the full file is skipped.
    for f in sorted(f for f in os.listdir(src)
                    if f.endswith(".sql") and not f.endswith("_full.sql")):
        text = open(os.path.join(src, f), encoding="utf-8", errors="replace").read()
        for s in statements(text):
            # Comments come first: pg_dump puts a banner above every statement, and the
            # banner is part of the same semicolon-delimited chunk.
            s = "\n".join(l for l in s.splitlines()
                           if not l.strip().startswith("--")).strip()
            if not s or SKIP.match(s):
                continue
            m = CREATE.match(s)
            if m:
                tables[m.group(1).strip('"')] = clean(m.group(2))
                continue
            m = CONSTRAINT.match(s)
            if m:
                body = m.group(2).strip()
                if re.match(r"(PRIMARY KEY|FOREIGN KEY|UNIQUE)", body, re.I):
                    # pg_dump writes a constraint into the file of *both* tables it touches,
                    # so the same PRIMARY KEY arrives twice and SQLite rejects the table --
                    # which is how 971 declared keys quietly became none.
                    constraints.setdefault(m.group(1).strip('"'), set()).add(
                        clean(body).replace("public.", ""))
                continue
            if INSERT.match(s):
                inserts.append(s.replace("public.", "", 1))

    if os.path.exists(out):
        os.remove(out)
    conn = sqlite3.connect(out)
    made = skipped = 0
    for name, body in tables.items():
        here = sorted(constraints.get(name, ()))
        # SQLite takes one PRIMARY KEY per table; a composite arrives as one clause already.
        keys = [c for c in here if c.upper().startswith("PRIMARY KEY")]
        parts = [body] + keys[:1] + [c for c in here if c not in keys]
        ddl = 'CREATE TABLE "%s" (%s)' % (name, ",\n".join(parts))
        try:
            conn.execute(ddl)
            made += 1
        except sqlite3.Error:
            try:                                   # keep the table, lose the constraints
                conn.execute('CREATE TABLE "%s" (%s)' % (name, body))
                made += 1
            except sqlite3.Error:
                skipped += 1
    # One table cannot be carried at all: `Control_Library` declares both `control_code` and
    # `"CONTROL_CODE"`, which PostgreSQL keeps apart (an unquoted identifier folds to lower
    # case, a quoted one does not) and SQLite cannot, because its identifiers are
    # case-insensitive. That is a real difference between the engines, not a defect here, and
    # renaming one would change what a query is allowed to name.
    rows = failed = 0
    for i, s in enumerate(inserts):
        if limit and i >= limit:
            break
        try:
            conn.execute(clean(s))
            rows += 1
        except sqlite3.Error:
            failed += 1
    conn.commit()
    conn.close()
    return {"tables": made, "skipped": skipped, "rows": rows, "failed": failed,
            "statements": len(inserts)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("database")
    p.add_argument("-o", "--out")
    p.add_argument("--limit", type=int)
    args = p.parse_args(argv)
    out = args.out or os.path.join(HERE, "work", "db", "%s.sqlite" % args.database)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = load(args.database, out, args.limit)
    print("%-34s %3d tables (%d skipped), %d of %d rows (%d failed)  %s"
          % (args.database, r["tables"], r["skipped"], r["rows"], r["statements"],
             r["failed"], out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
