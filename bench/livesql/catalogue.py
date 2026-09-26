#!/usr/bin/env python3
"""Turn a LiveSQLBench schema dump into the catalogue fixture `reverse.py --json` reads.

The public release ships each database as PostgreSQL DDL text with three sample rows per
table, not as a connection. `reverse/catalog.py` already accepts a fixture in exactly the
shape a live catalogue produces, so the DDL text is the only thing that needs parsing, and
the reverse engineer runs unchanged -- no PostgreSQL server, no driver.

What is lost by going through text rather than a connection: the population. Rules that read
data (6c type-from-values, 9c value containment) see three rows and should be treated as
unavailable, not as having run and found nothing.

    catalogue.py DB_DIR -o out.json
"""

import argparse
import ast
import json
import os
import re
import sys

TABLE = re.compile(r'^CREATE TABLE\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\(')
COL = re.compile(r'^\s*("?)([A-Za-z_][A-Za-z0-9_]*)\1\s+(.+?)\s*,?\s*$')
FK = re.compile(r'FOREIGN KEY\s*\(([^)]*)\)\s*REFERENCES\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\(([^)]*)\)',
                re.I)
NAMES = re.compile(r'"?([A-Za-z_][A-Za-z0-9_]*)"?')
# `id bigint NOT NULL DEFAULT nextval(...)` -- the serial spelling the dump uses.
DEFAULT = re.compile(r'\s+DEFAULT\s+(.*)$', re.I)


def parse(path):
    tables, cur = [], None
    for line in open(path):
        m = TABLE.match(line)
        if m:
            cur = {"name": m.group(1), "columns": [], "primary_key": [],
                   "uniques": [], "foreign_keys": [], "checks": []}
            tables.append(cur)
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith(");") or s.startswith("First 3 rows"):
            cur = None
            continue
        up = s.upper()
        if up.startswith("PRIMARY KEY"):
            cur["primary_key"] = NAMES.findall(s[len("PRIMARY KEY"):])
        elif up.startswith("FOREIGN KEY"):
            m = FK.search(s)
            if m:
                cur["foreign_keys"].append({
                    "columns": NAMES.findall(m.group(1)),
                    "ref_table": m.group(2),
                    "ref_columns": NAMES.findall(m.group(3))})
        elif up.startswith("UNIQUE"):
            cur["uniques"].append(NAMES.findall(s[len("UNIQUE"):]))
        elif up.startswith(("CHECK", "CONSTRAINT")):
            cur["checks"].append({"expression": s.rstrip(",")})
        else:
            m = COL.match(line)
            if not m or m.group(2).upper() in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK"):
                continue
            rest = m.group(3)
            nullable = "NOT NULL" not in rest.upper()
            default = None
            d = DEFAULT.search(rest)
            if d:
                default = d.group(1).rstrip(",")
                rest = rest[:d.start()]
            ty = re.sub(r'\s*(NOT\s+)?NULL\s*$', "", rest, flags=re.I).strip().rstrip(",")
            cur["columns"].append({"name": m.group(2), "data_type": ty or "text",
                                   "nullable": nullable, "default": default})
    return {"tables": tables}


# LiveSQLBench ships `fields_meaning` beside the schema: name and declared type per key,
# for two thirds of its jsonb columns. That is rule 12's input arriving as metadata rather
# than as a population -- which is the only way the rule can be measured here, since the
# public release has no database, only three sample rows per table.
TYPE = {"real": "real", "float": "real", "double": "real", "numeric": "real",
        "bigint": "bigint", "integer": "integer", "int": "integer", "smallint": "integer",
        "boolean": "boolean", "bool": "boolean", "date": "date", "timestamp": "text",
        "text": "text", "varchar": "text", "char": "text", "jsonb": "text", "json": "text"}


def _field_type(description) -> str:
    """The declared type is the first word of the gloss: `REAL. Latitude in degrees.`"""
    head = str(description).split(".", 1)[0].strip().casefold().split("(")[0].split()
    return TYPE.get(head[0], "text") if head else "text"


def _walk(fields, prefix=()):
    out = []
    for key, meaning in (fields or {}).items():
        if isinstance(meaning, dict) and "fields_meaning" not in meaning:
            out += _walk(meaning, prefix + (key,))
        elif isinstance(meaning, dict):
            out += _walk(meaning.get("fields_meaning"), prefix + (key,))
        else:
            out.append({"path": list(prefix + (key,)), "dataType": _field_type(meaning)})
    return out


def json_fields(db_dir, name):
    """{(table, column): [{path, dataType}, ...]} from the shipped column meanings."""
    path = os.path.join(db_dir, "%s_column_meaning_base.json" % name)
    if not os.path.exists(path):
        return {}
    raw = json.load(open(path))
    out = {}
    for key, value in raw.items():
        parts = key.split("|")
        if len(parts) != 3:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value.startswith("{"):
                continue
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                continue
        if not isinstance(value, dict):
            continue
        fields = _walk(value.get("fields_meaning"))
        if fields:
            out["%s|%s" % (parts[1], parts[2])] = fields
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("db_dir")
    p.add_argument("-o", "--out", required=True)
    args = p.parse_args(argv)
    name = os.path.basename(args.db_dir.rstrip("/"))
    cat = parse(os.path.join(args.db_dir, "%s_schema.txt" % name))
    fields = json_fields(args.db_dir, name)
    with open(args.out, "w") as fh:
        json.dump(cat, fh, indent=1)
    with open(args.out.replace(".json", ".jsonfields.json"), "w") as fh:
        json.dump(fields, fh, indent=1)
    print("%s: %d tables, %d columns, %d foreign keys, %d documented json columns" % (
        name, len(cat["tables"]), sum(len(t["columns"]) for t in cat["tables"]),
        sum(len(t["foreign_keys"]) for t in cat["tables"]), len(fields)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
