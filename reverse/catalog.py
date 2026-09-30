"""Normalised relational catalog, and the backends that populate it.

The derivation rules in derive.py never see a database. They see a Catalog, so the same
rules run against a live connection, a SQLite file, or a hand-written JSON fixture.

Backends
    from_sqlite(path)              stdlib only; uses PRAGMA, since SQLite has no
                                   information_schema
    from_dbapi(conn, schema=...)   any PEP 249 connection whose server has a standard
                                   information_schema: PostgreSQL, MySQL, SQL Server
    from_json(path_or_dict)        a fixture in the same shape, for tests

Identifier comparison is case-insensitive throughout, because the dialects disagree about
folding and a reverse-engineered model should not depend on which one is in front of it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def _fold(name: str) -> str:
    return name.casefold()


@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool
    position: int
    default: Optional[str] = None
    # SQLite lets a column be created with no type at all, and several of Spider 2.0's local
    # databases do. `data_type` still reads TEXT there, because everything downstream needs a
    # type; this says the catalogue never gave one, so Bird's Step 9 may read it off the data
    # (population.py rule 6c) without ever second-guessing a type that was declared.
    declared: bool = True


@dataclass
class ForeignKey:
    columns: List[str]
    ref_table: str
    ref_columns: List[str]
    name: Optional[str] = None
    ref_schema: Optional[str] = None


@dataclass
class Check:
    expression: str
    name: Optional[str] = None


@dataclass
class Table:
    name: str
    columns: List[Column] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    uniques: List[List[str]] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    checks: List[Check] = field(default_factory=list)
    schema: Optional[str] = None
    is_view: bool = False

    def column(self, name: str) -> Optional[Column]:
        target = _fold(name)
        return next((c for c in self.columns if _fold(c.name) == target), None)

    def is_key(self, name: str) -> bool:
        target = _fold(name)
        return any(_fold(k) == target for k in self.primary_key)

    def fk_for(self, name: str) -> Optional[ForeignKey]:
        """The foreign key this column participates in, if any."""
        target = _fold(name)
        return next((fk for fk in self.foreign_keys
                     if any(_fold(c) == target for c in fk.columns)), None)


@dataclass
class Catalog:
    tables: List[Table] = field(default_factory=list)
    # names the source listed but could not describe: a view whose definition no longer
    # resolves. Reported so the worklist says what was skipped rather than silently losing it.
    unreadable: List[str] = field(default_factory=list)
    # declared foreign keys rebuilt because the declaration could not be taken as written
    # (`repair_crossed_keys`), each a sentence for the report
    repairs: List[str] = field(default_factory=list)

    def table(self, name: str) -> Optional[Table]:
        target = _fold(name)
        return next((t for t in self.tables if _fold(t.name) == target), None)

    def referencing(self, name: str) -> List[Table]:
        """Tables holding a foreign key onto `name`."""
        target = _fold(name)
        return [t for t in self.tables
                if any(_fold(fk.ref_table) == target for fk in t.foreign_keys)]


def repair_crossed_keys(catalog: "Catalog") -> "Catalog":
    """Rebuild a composite foreign key a catalogue has listed as a cross product.

    Some dumps declare a foreign key onto a composite key as one single-column reference per
    pair of columns -- `(ws_addr1) REFERENCES worksite(w_addr1)`, `(ws_addr1) REFERENCES
    worksite(wcity)`, ... sixteen of them for a four-column key. Taken as written, each says a
    column references something it does not, and a model built on them names worksites by
    columns that are not unique (finding 172). The pattern is unmistakable: the references
    from one table to another pair every one of n columns with every one of n columns that
    together are the target's primary key or a unique key. That is one n-column reference,
    and the columns pair by position -- the referencing table's column order against the
    key's.
    """
    for table in catalog.tables:
        groups = {}
        for fk in table.foreign_keys:
            if len(fk.columns) == 1 and len(fk.ref_columns) == 1:
                groups.setdefault(_fold(fk.ref_table), []).append(fk)
        for ref, fks in groups.items():
            cols = {_fold(fk.columns[0]) for fk in fks}
            refs = {_fold(fk.ref_columns[0]) for fk in fks}
            pairs = {(_fold(fk.columns[0]), _fold(fk.ref_columns[0])) for fk in fks}
            n = len(cols)
            if n < 2 or len(refs) != n or len(pairs) != n * n:
                continue
            target = catalog.table(ref)
            if target is None:
                continue
            keys = [target.primary_key] + list(target.uniques)
            key = next((k for k in keys if {_fold(c) for c in k} == refs), None)
            if key is None:
                continue
            ordered = [c.name for c in table.columns if _fold(c.name) in cols]
            if len(ordered) != n:
                continue
            table.foreign_keys = [fk for fk in table.foreign_keys if fk not in fks]
            table.foreign_keys.append(ForeignKey(columns=ordered, ref_table=fks[0].ref_table,
                                                 ref_columns=list(key),
                                                 ref_schema=fks[0].ref_schema))
            catalog.repairs.append(
                "%s: %d single-column references onto %s were one %d-column reference, "
                "(%s) -> (%s); rebuilt, pairing the columns by position"
                % (table.name, n * n, fks[0].ref_table, n, ", ".join(ordered), ", ".join(key)))
    return catalog


# --------------------------------------------------------------------------- SQLite

def from_sqlite(path: str) -> Catalog:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    info_cache = {}

    def table_info(name):
        """PRAGMA table_info, once per table. Implicit foreign keys ask for their target's
        columns, and a schema with many keys into a few hub tables re-asked every time.

        A view whose definition no longer resolves -- Spider 2.0's `oracle_sql` has one that
        selects `ehp.start_date` from something without that column -- makes PRAGMA raise.
        One such view used to take the whole schema down with it, which is thirty-eight
        tables lost to a broken definition nobody was going to query anyway."""
        if name not in info_cache:
            try:
                info_cache[name] = conn.execute('PRAGMA table_info("%s")' % name).fetchall()
            except sqlite3.Error:
                info_cache[name] = []
        return info_cache[name]

    try:
        catalog = Catalog()
        rows = conn.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

        for row in rows:
            table = Table(name=row["name"], is_view=(row["type"] == "view"))

            info = table_info(row["name"])
            if not info:
                catalog.unreadable.append(row["name"])
                continue                      # a view whose definition no longer resolves
            pk_ordered = []
            for col in info:
                table.columns.append(Column(
                    name=col["name"],
                    data_type=(col["type"] or "").strip() or "TEXT",
                    nullable=not col["notnull"],
                    position=col["cid"],
                    default=col["dflt_value"],
                    declared=bool((col["type"] or "").strip()),
                ))
                if col["pk"]:
                    pk_ordered.append((col["pk"], col["name"]))
            table.primary_key = [n for _, n in sorted(pk_ordered)]

            fks: Dict[int, ForeignKey] = {}
            for fk in conn.execute('PRAGMA foreign_key_list("%s")' % row["name"]).fetchall():
                entry = fks.setdefault(fk["id"], ForeignKey(columns=[], ref_table=fk["table"],
                                                            ref_columns=[]))
                entry.columns.append(fk["from"])
                # A SQLite FK may omit the referenced columns, meaning the target's PK.
                entry.ref_columns.append(fk["to"] if fk["to"] is not None else None)
            for entry in fks.values():
                if any(c is None for c in entry.ref_columns):
                    target = conn.execute('PRAGMA table_info("%s")' % entry.ref_table).fetchall()
                    # `pk` is the 1-based position in the key, not a flag: ordering by it
                    # rather than by column position is what keeps a composite key's legs
                    # paired with the right target columns.
                    entry.ref_columns = [c["name"] for c in
                                         sorted((r for r in target if r["pk"]),
                                                key=lambda r: r["pk"])]
                table.foreign_keys.append(entry)

            for index in conn.execute('PRAGMA index_list("%s")' % row["name"]).fetchall():
                if not index["unique"]:
                    continue
                if index["origin"] == "pk":
                    continue
                # A partial unique index constrains only the rows its WHERE admits, so it is
                # not a uniqueness constraint on the fact type. `partial` arrives with
                # SQLite 3.8.9; older builds simply do not report partial indexes.
                if "partial" in index.keys() and index["partial"]:
                    continue
                cols = [i["name"] for i in
                        conn.execute('PRAGMA index_info("%s")' % index["name"]).fetchall()]
                if cols and all(c is not None for c in cols):
                    table.uniques.append(cols)

            if row["sql"]:
                table.checks = _parse_checks(row["sql"])

            catalog.tables.append(table)
        return repair_crossed_keys(catalog)
    finally:
        conn.close()


_CHECK_RE = re.compile(r"\bCHECK\s*\(", re.IGNORECASE)


def _parse_checks(ddl: str) -> List[Check]:
    """Pull CHECK(...) bodies out of a CREATE TABLE statement by bracket matching."""
    out = []
    for match in _CHECK_RE.finditer(ddl):
        depth, i = 1, match.end()
        while i < len(ddl) and depth:
            if ddl[i] == "(":
                depth += 1
            elif ddl[i] == ")":
                depth -= 1
            i += 1
        if not depth:
            out.append(Check(expression=ddl[match.end():i - 1].strip()))
    return out


# --------------------------------------------------------------------- information_schema

_IS_TABLES = """
SELECT table_name, table_type FROM information_schema.tables
WHERE table_schema = %s ORDER BY table_name
"""
_IS_COLUMNS = """
SELECT table_name, column_name, data_type, is_nullable, ordinal_position,
       column_default, character_maximum_length, numeric_precision, numeric_scale
FROM information_schema.columns WHERE table_schema = %s ORDER BY table_name, ordinal_position
"""
_IS_CONSTRAINTS = """
SELECT tc.constraint_name, tc.table_name, tc.constraint_type,
       kcu.column_name, kcu.ordinal_position
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
WHERE tc.table_schema = %s AND tc.constraint_type IN ('PRIMARY KEY','UNIQUE','FOREIGN KEY')
ORDER BY tc.table_name, tc.constraint_name, kcu.ordinal_position
"""
_IS_FK_TARGETS = """
SELECT rc.constraint_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
FROM information_schema.referential_constraints rc
JOIN information_schema.constraint_column_usage ccu
  ON rc.unique_constraint_name = ccu.constraint_name
WHERE rc.constraint_schema = %s
"""
_IS_CHECKS = """
SELECT tc.table_name, cc.constraint_name, cc.check_clause
FROM information_schema.check_constraints cc
JOIN information_schema.table_constraints tc
  ON cc.constraint_name = tc.constraint_name AND cc.constraint_schema = tc.table_schema
WHERE cc.constraint_schema = %s
"""


def from_dbapi(conn, schema: str = "public", paramstyle: str = "%s") -> Catalog:
    """Read a live server's information_schema. `paramstyle` is '%s' or '?'."""
    def q(sql, *args):
        cur = conn.cursor()
        cur.execute(sql.replace("%s", paramstyle), args)
        rows = cur.fetchall()
        cur.close()
        return rows

    catalog = Catalog()
    by_name: Dict[str, Table] = {}
    for name, ttype in q(_IS_TABLES, schema):
        table = Table(name=name, schema=schema, is_view=(ttype == "VIEW"))
        by_name[_fold(name)] = table
        catalog.tables.append(table)

    for row in q(_IS_COLUMNS, schema):
        table = by_name.get(_fold(row[0]))
        if table is None:
            continue
        data_type = row[2]
        if row[6]:
            data_type = "%s(%s)" % (data_type, row[6])
        elif row[7] and row[8] is not None:
            data_type = "%s(%s,%s)" % (data_type, row[7], row[8])
        table.columns.append(Column(name=row[1], data_type=data_type,
                                    nullable=(row[3] == "YES"), position=row[4], default=row[5]))

    constraints: Dict[tuple, dict] = {}
    for cname, tname, ctype, col, _pos in q(_IS_CONSTRAINTS, schema):
        entry = constraints.setdefault((_fold(tname), cname),
                                       {"type": ctype, "columns": []})
        entry["columns"].append(col)

    targets: Dict[str, List[tuple]] = {}
    for cname, ref_table, ref_col in q(_IS_FK_TARGETS, schema):
        targets.setdefault(cname, []).append((ref_table, ref_col))

    for (tfold, cname), entry in constraints.items():
        table = by_name.get(tfold)
        if table is None:
            continue
        kind, cols = entry["type"], entry["columns"]
        if kind == "PRIMARY KEY":
            table.primary_key = cols
        elif kind == "UNIQUE":
            table.uniques.append(cols)
        elif kind == "FOREIGN KEY":
            pairs = targets.get(cname, [])
            if pairs:
                table.foreign_keys.append(ForeignKey(
                    name=cname, columns=cols, ref_table=pairs[0][0],
                    ref_columns=[c for _, c in pairs], ref_schema=schema))

    try:
        for tname, cname, clause in q(_IS_CHECKS, schema):
            table = by_name.get(_fold(tname))
            if table is not None:
                table.checks.append(Check(expression=clause, name=cname))
    except Exception:
        pass          # check_constraints is absent or restricted on some servers

    return repair_crossed_keys(catalog)


# --------------------------------------------------------------------------- JSON fixture

def from_json(source) -> Catalog:
    if isinstance(source, dict):
        data = source
    else:
        with open(source) as fh:
            data = json.load(fh)
    catalog = Catalog()
    for t in data["tables"]:
        catalog.tables.append(Table(
            name=t["name"],
            schema=t.get("schema"),
            is_view=t.get("is_view", False),
            columns=[Column(name=c["name"], data_type=c.get("data_type", "TEXT"),
                            nullable=c.get("nullable", True), position=i,
                            default=c.get("default"))
                     for i, c in enumerate(t.get("columns", []))],
            primary_key=t.get("primary_key", []),
            uniques=t.get("uniques", []),
            foreign_keys=[ForeignKey(columns=fk["columns"], ref_table=fk["ref_table"],
                                     ref_columns=fk["ref_columns"], name=fk.get("name"))
                          for fk in t.get("foreign_keys", [])],
            checks=[Check(expression=c["expression"], name=c.get("name"))
                    for c in t.get("checks", [])],
        ))
    return repair_crossed_keys(catalog)
