#!/usr/bin/env python3
"""The corpora the recent key-recovery papers share, as SQLite with their keys declared.

HoPF, LLM-FK and DBAutoDoc all report on AdventureWorks and most on MusicBrainz, so `refs.py`
can be held to the same schemas instead of being compared across corpora. Nothing downloaded
is run: `fetch-corpora.sh` gets text and data, and this file reads Microsoft's T-SQL install
script and MusicBrainz's PostgreSQL DDL with regular expressions, for the tables, keys and
column order, then loads the rows. The declared foreign keys are the truth `refs.py` scores
against. Types are reduced to SQLite's four affinities. TPC-E is absent: its data comes only
from TPC's EGen, under a licence a person has to accept.

    corpora.py adventureworks SOURCE_DIR OUT.sqlite
    corpora.py musicbrainz SOURCE_DIR OUT.sqlite
    corpora.py destroy IN.sqlite OUT.sqlite        every table and column renamed, in a shuffle
"""
import csv
import os
import random
import re
import sqlite3
import sys

csv.field_size_limit(1 << 30)
INT = re.compile(r"int|serial|bit|bool", re.I)
REAL = re.compile(r"money|decimal|numeric|float|real|double", re.I)


def affinity(sql_type):
    return "INTEGER" if INT.search(sql_type) else "REAL" if REAL.search(sql_type) else "TEXT"


def build(path, tables, primary, foreign):
    """`tables`: name -> [(column, affinity)]. `foreign`: (table, [cols], target, [cols])."""
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=OFF")
    c.execute("PRAGMA synchronous=OFF")
    for name, cols in tables.items():
        body = ['"%s" %s' % col for col in cols]
        if primary.get(name):
            body.append("PRIMARY KEY (%s)" % ", ".join('"%s"' % k for k in primary[name]))
        for t, fk, target, to in foreign:
            if t == name and target in tables:
                body.append('FOREIGN KEY (%s) REFERENCES "%s" (%s)' % (
                    ", ".join('"%s"' % k for k in fk), target, ", ".join('"%s"' % k for k in to)))
        c.execute('CREATE TABLE "%s" (%s)' % (name, ", ".join(body)))
    return c


def bracketed(text):
    return re.findall(r"\[(\w+)\]", text)


def split_rows(text, field, row):
    return [r.split(field) for r in text.replace("\r\n", "\n").split(row) if r.strip()]


def mended(rows, width):
    """Rows whose text held the row terminator, put back together."""
    out, open_row = [], None
    for r in rows:
        if open_row is None:
            open_row = r
        else:
            open_row[-1] += "\n" + r[0]
            open_row += r[1:]
        if len(open_row) >= width:
            out.append(open_row)
            open_row = None
    return out


def adventureworks(source, out):
    sql = open(os.path.join(source, "instawdb.sql"), encoding="utf-8-sig").read()
    sql = re.sub(r"--.*", "", sql)
    tables, computed = {}, {}
    for name, body in re.findall(r"CREATE TABLE \[\w+\]\.\[(\w+)\]\s*\((.*?)\n\) ON", sql, re.S):
        cols, skip = [], set()
        for line in body.splitlines():
            m = re.match(r"\s*\[(\w+)\]\s+\[?(\w+)", line)
            if not m:
                continue
            if m.group(2).upper() == "AS":
                skip.add(m.group(1))
            cols.append((m.group(1), affinity(m.group(2))))
        tables[name], computed[name] = cols, skip
    primary, foreign = {}, []
    for name, body in re.findall(r"ALTER TABLE \[\w+\]\.\[(\w+)\](.*?)(?=;|ALTER TABLE)", sql, re.S):
        m = re.search(r"PRIMARY KEY\s+\w*\s*\((.*?)\)", body, re.S)
        if m:
            primary[name] = bracketed(m.group(1))
        for fk, target, to in re.findall(
                r"FOREIGN KEY\s*\((.*?)\)\s*REFERENCES\s*\[\w+\]\.\[(\w+)\]\s*\((.*?)\)", body, re.S):
            foreign.append((name, bracketed(fk), target, bracketed(to)))
    c = build(out, tables, primary, foreign)
    for name, filename, options in re.findall(
            r"BULK INSERT \[\w+\]\.\[(\w+)\] FROM '\$\(SqlSamplesSourceDataPath\)([\w.]+)'\s*"
            r"WITH \((.*?)\);", sql, re.S):
        field = re.search(r"FIELDTERMINATOR\s*=\s*'(.*?)'", options).group(1)
        row = re.search(r"ROWTERMINATOR\s*=\s*'(.*?)'", options).group(1)
        field = field.replace("\\t", "\t")
        row = "\n" if row == "0x0a" else row.replace("\\n", "\n")
        code = re.search(r"CODEPAGE\s*=\s*'(\w+)'", options)
        wide = "widechar" in options.lower() and not code
        with open(os.path.join(source, filename), encoding="utf-16" if wide else "utf-8-sig",
                  newline="") as fh:
            rows = split_rows(fh.read().replace("\x00", ""), field, row)
        cols = tables[name]
        stored = [i for i, (n, _) in enumerate(cols) if n not in computed[name]]
        width = len(rows[0]) if rows else 0
        slots = list(range(len(cols))) if width == len(cols) else stored
        rows = mended(rows, len(slots))
        names = ", ".join('"%s"' % cols[i][0] for i in slots)
        marks = ", ".join("?" * len(slots))
        for r in rows:
            if len(r) != len(slots):
                print("skipped a row of %s: %d fields, %d columns" % (name, len(r), len(slots)))
                continue
            c.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (name, names, marks),
                      [v.strip() or None for v in r])
    c.commit()
    c.close()


PG_ESCAPES = {"\\t": "\t", "\\n": "\n", "\\r": "\r", "\\\\": "\\"}


def unescape(field):
    if field == "\\N":
        return None
    return re.sub(r"\\[tnr\\]", lambda m: PG_ESCAPES[m.group()], field)


def top_level(body):
    """A CREATE TABLE's items: its commas outside parentheses and quotes."""
    items, depth, quoted, start = [], 0, False, 0
    for i, ch in enumerate(body):
        quoted ^= ch == "'"
        if not quoted:
            depth += (ch == "(") - (ch == ")")
            if ch == "," and not depth:
                items.append(body[start:i])
                start = i + 1
    return items + [body[start:]]


def musicbrainz(source, out):
    ddl = open(os.path.join(source, "CreateTables.sql")).read()
    ddl = re.sub(r"--.*", "", ddl)
    tables = {}
    for name, body in re.findall(r"CREATE TABLE (\w+)\s*\((.*?)\)\s*;", ddl, re.S | re.I):
        cols = []
        for item in top_level(body):
            m = re.match(r"\s*(\w+)\s+(\w+)", item)
            if m and m.group(1).upper() not in ("CHECK", "CONSTRAINT", "PRIMARY", "UNIQUE",
                                                "FOREIGN", "EXCLUDE"):
                cols.append((m.group(1), affinity(m.group(2))))
        tables[name] = cols
    keys = re.sub(r"--.*", "", open(os.path.join(source, "CreatePrimaryKeys.sql")).read())
    primary = {t: [k.strip() for k in cols.split(",")] for t, cols in re.findall(
        r"ALTER TABLE (\w+) ADD CONSTRAINT \w+ PRIMARY KEY \((.*?)\)", keys)}
    fks = re.sub(r"--.*", "", open(os.path.join(source, "CreateFKConstraints.sql")).read())
    foreign = [(t, [k.strip() for k in a.split(",")], target, [k.strip() for k in b.split(",")])
               for t, a, target, b in re.findall(
                   r"ALTER TABLE (\w+)\s+ADD CONSTRAINT \w+\s+FOREIGN KEY \((.*?)\)\s+"
                   r"REFERENCES (?:musicbrainz\.)?(\w+)\((.*?)\)", fks)]
    dump = os.path.join(source, "mbdump")
    filled = {t: cols for t, cols in tables.items()
              if os.path.exists(os.path.join(dump, t)) and os.path.getsize(os.path.join(dump, t))}
    c = build(out, filled, primary, foreign)
    for name, cols in filled.items():
        marks = ", ".join("?" * len(cols))
        with open(os.path.join(dump, name), encoding="utf-8", newline="\n") as fh:
            for line in fh:
                fields = [unescape(f) for f in line.rstrip("\n").split("\t")]
                if len(fields) != len(cols):
                    print("skipped %s: %d fields, %d columns" % (name, len(fields), len(cols)))
                    break
                c.execute('INSERT INTO "%s" VALUES (%s)' % (name, marks), fields)
    c.commit()
    c.close()


def destroy(source, out):
    """The same rows with no name left: tables and columns renamed in a seeded shuffle, keys
    kept. Everything name evidence could read is gone, so what is recovered is the data's."""
    s = sqlite3.connect(source)
    rng = random.Random(20261101)
    names = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    rng.shuffle(names)
    table = {t: "t%04d" % i for i, t in enumerate(names)}
    folded = {t.casefold(): t for t in names}
    column, tables, primary, foreign = {}, {}, {}, []
    for t in names:
        info = s.execute('PRAGMA table_info("%s")' % t).fetchall()
        order = list(info)
        rng.shuffle(order)
        for i, col in enumerate(order):
            column[t.casefold(), col[1].casefold()] = "c%04d" % i
        tables[table[t]] = [(column[t.casefold(), col[1].casefold()], col[2]) for col in info]
        pk = sorted((col for col in info if col[5]), key=lambda col: col[5])
        primary[table[t]] = [column[t.casefold(), col[1].casefold()] for col in pk]
    for t in names:
        grouped = {}
        for fid, seq, target, col, to, *_ in s.execute('PRAGMA foreign_key_list("%s")' % t):
            target = folded.get(target.casefold())
            if to is not None and target and (target.casefold(), to.casefold()) in column:
                grouped.setdefault((fid, target), []).append(
                    (column[t.casefold(), col.casefold()], column[target.casefold(), to.casefold()]))
        for (_, target), pairs in grouped.items():
            foreign.append((table[t], [a for a, _ in pairs], table[target], [b for _, b in pairs]))
    c = build(out, tables, primary, foreign)
    c.execute("ATTACH ? AS src", (source,))
    for t in names:
        info = s.execute('PRAGMA table_info("%s")' % t).fetchall()
        c.execute('INSERT INTO "%s" SELECT %s FROM src."%s"' % (
            table[t], ", ".join('"%s"' % col[1] for col in info), t))
    c.commit()
    c.close()


if __name__ == "__main__":
    {"adventureworks": adventureworks, "musicbrainz": musicbrainz,
     "destroy": destroy}[sys.argv[1]](*sys.argv[2:])
