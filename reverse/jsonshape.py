"""Rule 12: recover the schema inside a JSON column.

A `jsonb` column is a catalogue that stopped short. The database says "one column of type
json" where it means "nine values of known type", and every rule in this directory exists to
recover schema a catalogue failed to declare -- rule 9 for references, 9b for identifiers,
9c for the references only the data shows. This is the same act, one level further in.

Three shapes come out of a document column, and only one of them is a record:

    record   the keys are the same row to row and name roles.
             {'location': {'city': 'Sakhir'}, 'coordinates': {'latitude': 26.03}}
             -> one fact type per leaf, mapped to a path. What this module derives.

    map      the keys vary row to row and are themselves data.
             {'clay': 15, 'quartz': 60}  then  {'calcite': 80, 'sandstone': 20}
             -> in ORM this is `Survey has Percentage for Mineral`, a fact type whose key
             plays a role. Detected and reported; NOT derived, because the mapping would
             have to unnest rather than read a path, and that is a different piece of work.

    bag      neither. Free-form notes, a change log, a payload nobody constrained.
             -> refused. There is no conceptual content to recover, and inventing fact
             types from one sample would be worse than saying so.

Asking "what is the elementary fact here?" is what separates them, which is the reason to do
this conceptually rather than by adding a JSON type to the query language: a record's keys
name roles, a map's keys play one, and a scalar JSON type flattens that distinction away.
"""

from __future__ import annotations

import collections
import json
from typing import Dict, List, Optional, Tuple

# A document with more distinct keys than this, or nesting deeper than this, is not a record
# anyone meant to query by name.
MAX_KEYS = 40
MAX_DEPTH = 4
# Share of rows a key must appear in for the document to read as a record rather than a map.
STABLE = 0.6
SAMPLE = 500


def _leaves(doc, prefix=(), out=None, depth=0):
    """Every scalar in a document, by the path that reaches it."""
    if out is None:
        out = {}
    if depth > MAX_DEPTH or not isinstance(doc, dict):
        return out
    for k, v in doc.items():
        if isinstance(v, dict):
            _leaves(v, prefix + (k,), out, depth + 1)
        elif isinstance(v, (list, tuple)):
            out[prefix + (k,)] = "list"
        else:
            out.setdefault(prefix + (k,), set()).add(type(v).__name__)
    return out


def _type_of(names) -> str:
    """The narrowest SQL type that holds everything seen at a path."""
    if names == "list":
        return "list"
    seen = {n for n in names if n != "NoneType"}
    if not seen:
        return "text"
    if seen <= {"bool"}:
        return "boolean"
    if seen <= {"int"}:
        return "integer"
    if seen <= {"int", "float"}:
        return "real"
    return "text"


def classify(values) -> Tuple[str, List[dict], str]:
    """Read a sample of a column's documents. Returns (shape, fields, why)."""
    docs = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", "replace")
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return "bag", [], "a value is not JSON"
        docs.append(v)
    if not docs:
        return "bag", [], "every value is null"
    if not all(isinstance(d, dict) for d in docs):
        return "bag", [], "not every value is an object"

    top = collections.Counter()
    for d in docs:
        top.update(d.keys())
    if len(top) > MAX_KEYS:
        return "bag", [], "%d distinct top-level keys over %d rows" % (len(top), len(docs))

    stable = [k for k, n in top.items() if n >= STABLE * len(docs)]
    if len(stable) < len(top) * STABLE:
        # Keys come and go. If what is under them is one kind of scalar, the keys are data
        # and this is a map -- `{'clay': 15, 'quartz': 60}` is a percentage *per mineral*.
        kinds = {type(v).__name__ for d in docs for v in d.values()}
        if not kinds - {"int", "float"} or not kinds - {"str"} or not kinds - {"bool"}:
            return "map", [], ("%d distinct keys of which %d are stable, every value a %s: "
                               "the keys are data, not roles"
                               % (len(top), len(stable), "/".join(sorted(kinds))))
        return "bag", [], "%d distinct keys, only %d stable" % (len(top), len(stable))
    if not stable:
        return "bag", [], "no key appears in as many as %.0f%% of rows" % (100 * STABLE)

    seen: Dict[tuple, object] = {}
    for d in docs:
        for path, kinds in _leaves(d).items():
            if path in seen and seen[path] != "list" and kinds != "list":
                seen[path] |= kinds
            else:
                seen.setdefault(path, kinds)
    fields = []
    for path in sorted(seen):
        ty = _type_of(seen[path])
        if ty == "list":
            continue                       # an array is a multi-valued fact: not a path read
        if path[0] not in stable:
            continue
        fields.append({"path": list(path), "dataType": ty})
    if not fields:
        return "bag", [], "no scalar leaf under a stable key"
    return "record", fields, "%d stable key(s), %d scalar leaf/leaves over %d rows" % (
        len(stable), len(fields), len(docs))


def is_json(column) -> bool:
    """Does the catalogue call this column JSON?

    PostgreSQL says so. SQLite has no JSON type and holds documents in TEXT, so a text
    column is a candidate and only its contents decide -- which is why `classify` refuses
    anything that does not parse rather than trusting the declaration.
    """
    t = (column.data_type or "").strip().casefold()
    return t.startswith("json") or t in ("jsonb", "json")


def read(conn, catalog, tables=None, sample: int = SAMPLE):
    """Classify every JSON column in the catalogue against its population.

    Returns {(table, column): (shape, fields, why)}. Text columns are probed too, because
    SQLite has nowhere else to put a document; a text column whose values do not parse comes
    back `bag` and costs one query.
    """
    out = {}
    for t in catalog.tables:
        if t.is_view or (tables and t.name not in tables):
            continue
        for col in t.columns:
            declared = is_json(col)
            if not declared and (col.data_type or "").strip().casefold() not in ("text", ""):
                continue
            try:
                rows = conn.execute(
                    'SELECT "%s" FROM "%s" WHERE "%s" IS NOT NULL LIMIT %d'
                    % (col.name.replace('"', '""'), t.name.replace('"', '""'),
                       col.name.replace('"', '""'), sample)).fetchall()
            except Exception:                                          # noqa: BLE001
                continue
            values = [r[0] for r in rows]
            # An undeclared text column has to look like JSON before it is worth a verdict.
            if not declared and not any(
                    isinstance(v, str) and v.lstrip()[:1] in ("{", "[") for v in values):
                continue
            shape, fields, why = classify(values)
            if shape != "bag" or declared:
                out[(t.name, col.name)] = (shape, fields, why)
    return out


def from_fields(declared: Dict[Tuple[str, str], List[dict]]):
    """The same verdict, from a declared field schema rather than a population.

    LiveSQLBench ships `fields_meaning` for two thirds of its jsonb columns -- name and type
    per key -- which is a catalogue by another name. Taking it lets the rule be measured
    where no database is running, and the shape is `record` by construction because someone
    wrote the keys down.
    """
    return {k: ("record", v, "declared field schema (%d field(s))" % len(v))
            for k, v in declared.items() if v}
