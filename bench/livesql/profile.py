#!/usr/bin/env python3
"""SCALE4.md's metadata: a column profile, a value index, and the benchmark's own meanings.

Three things Shkapenyuk et al. (arXiv:2505.19988) used that no earlier round here did, built
once per database and each written as a file `conquer/annotate.py` reads:

* **The profile** (`profile/DB.txt`), per column and per field inside a JSON column: rows,
  nulls, distinct values, minimum and maximum, the range of lengths, and the most common
  values with their counts -- the mechanical English their LLM summarises. A describer agent
  (`DESCRIBE.md`) turns it into a short description of each column, `descriptions/DB.json`.
* **The value index** (`values/DB.json`): up to 10,000 distinct text values per column or
  JSON field, lower-cased, each mapped to the columns that hold it -- their literal index,
  exact rather than locality-sensitive, which at this size needs no approximation.
* **The column meanings** (`meanings/DB.json`): LiveSQLBench's `column_meaning_base.json`,
  the benchmark-supplied description of every column and JSON field, in the flat form
  `annotate.py --describe` reads: `"table|column"` or `"table|column|field.path"` -> text.

    profile.py DB [DB ...]
"""
import argparse
import ast
import re
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")
MODELS = os.path.join(HERE, "work", "models-profiled2")
OUT = os.path.join(HERE, "work", "pilot-scale4")
MAX_VALUES = 10000
TOP = 6


def targets(db):
    """(table, column, path, type) for every column and every JSON field the model maps."""
    m = json.load(open(os.path.join(MODELS, "%s.ccm.json" % db)))
    tables = {t["id"]: t["name"] for t in m["mapping"]["tables"]}
    out, seen = [], set()
    for c in m["mapping"]["columns"]:
        key = (tables.get(c["table"]), c["name"], tuple(c.get("path") or ()))
        if key in seen or key[0] is None:
            continue
        seen.add(key)
        out.append(key + ((c.get("dataType") or {}).get("name", ""),))
    return out


def expr(column, path):
    col = '"%s"' % column
    if not path:
        return col
    return col + "".join("->'%s'" % p.replace("'", "''") for p in path[:-1]) + \
        "->>'%s'" % path[-1].replace("'", "''")


def profile_one(conn, table, column, path, typ):
    e = expr(column, path)
    t = '"%s"' % table
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(%s), count(DISTINCT %s::text), min(%s::text), "
                    "max(%s::text), min(length(%s::text)), max(length(%s::text)) FROM %s"
                    % (e, e, e, e, e, e, t))
        n, nn, nd, lo, hi, lmin, lmax = cur.fetchone()
        top = []
        if nn and (typ or "").lower() not in ("jsonb", "json"):
            cur.execute("SELECT %s::text v, count(*) c FROM %s WHERE %s IS NOT NULL "
                        "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %d" % (e, t, e, TOP))
            top = cur.fetchall()
    return n, nn, nd, lo, hi, lmin, lmax, top


def say(table, column, path, typ, prof):
    n, nn, nd, lo, hi, lmin, lmax, top = prof
    name = "%s.%s" % (table, column) + ("->" + ".".join(path) if path else "")
    if not n:
        return "%s (%s): the table is empty." % (name, typ)
    s = "%s (%s): %d of %d rows null; %d distinct values." % (name, typ, n - nn, n, nd)
    if nn and (typ or "").lower() not in ("jsonb", "json"):
        clip = lambda v: (v if len(v) <= 40 else v[:37] + "...")
        s += " Minimum %r, maximum %r; %s to %s characters." % (clip(lo), clip(hi), lmin, lmax)
        if top:
            s += " Most common: %s." % ", ".join("%r (%d)" % (clip(v), c) for v, c in top)
    return s


def value_index(conn, targets_):
    """lower-cased text value -> ["table.column[->path]", ...], for text columns and fields."""
    idx = {}
    for table, column, path, typ in targets_:
        if (typ or "text").lower() not in ("text", "varchar", "character varying", "char",
                                           "character", "bpchar"):
            continue
        e = expr(column, path)
        where = "%s.%s" % (table, column) + ("->" + ".".join(path) if path else "")
        with conn.cursor() as cur:
            try:
                cur.execute('SELECT DISTINCT %s FROM "%s" WHERE %s IS NOT NULL LIMIT %d'
                            % (e, table, e, MAX_VALUES))
                vals = [r[0] for r in cur.fetchall()]
            except Exception:                                          # noqa: BLE001
                continue
        for v in vals:
            v = str(v).strip().lower()
            if 3 <= len(v) <= 60 and not v.replace(".", "").replace("-", "").isdigit():
                lst = idx.setdefault(v, [])
                if where not in lst:
                    lst.append(where)
    return idx


_TYPE = re.compile(r"^\s*[A-Za-z ()0-9,]+\.\s+")
_EXAMPLE = re.compile(r"\s*Example:.*$")


def tidy(text):
    """A meaning without the type it restates and the example the sample rows show:
    'REAL. Load value of the system overseer. Example: 0.99.' -> 'Load value of the
    system overseer.' The DDL beside it has both."""
    text = " ".join(str(text).split())
    body = _EXAMPLE.sub("", _TYPE.sub("", text, count=1)).strip()
    return body or text


def meanings(db):
    """The benchmark's column meanings, flattened to "table|column[|a.b]" -> text."""
    raw = json.load(open(os.path.join(DATA, db, "%s_column_meaning_base.json" % db)))
    out = {}

    def walk(prefix, fields):
        for k, v in (fields or {}).items():
            if isinstance(v, dict) and "fields_meaning" in v:
                if v.get("column_meaning"):
                    out[prefix + "|" + k if "|" not in prefix.split("|", 2)[-1] else
                        prefix + "." + k] = v["column_meaning"]
                walk(prefix + ("." if prefix.count("|") == 2 else "|") + k,
                     v["fields_meaning"])
            elif isinstance(v, dict):
                walk(prefix + ("." if prefix.count("|") == 2 else "|") + k, v)
            else:
                out[prefix + ("." if prefix.count("|") == 2 else "|") + k] = str(v)
    for key, value in raw.items():
        parts = key.split("|")
        if len(parts) != 3:
            continue
        base = "%s|%s" % (parts[1], parts[2])
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                value = ast.literal_eval(value.strip())
            except (ValueError, SyntaxError):
                pass
        if isinstance(value, dict):
            if value.get("column_meaning"):
                out[base] = value["column_meaning"]
            walk(base, value.get("fields_meaning"))
        else:
            out[base] = str(value)
    return {k: tidy(v) for k, v in out.items()}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("dbs", nargs="+")
    args = p.parse_args(argv)
    import score_pg
    for sub in ("profile", "values", "meanings"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    for db in args.dbs:
        conn = score_pg.connect(score_pg.DSN, db)
        tg = targets(db)
        lines, table = [], None
        for t, c, path, typ in tg:
            if t != table:
                lines += ["", "## %s" % t]
                table = t
            try:
                lines.append(say(t, c, path, typ, profile_one(conn, t, c, path, typ)))
            except Exception as e:                                     # noqa: BLE001
                lines.append("%s.%s: not profiled (%s)" % (t, c, str(e).split("\n")[0][:80]))
        open(os.path.join(OUT, "profile", "%s.txt" % db), "w").write(
            "# Column profile: %s\n\nMinimum and maximum compare values as text.\n" % db
            + "\n".join(lines) + "\n")
        idx = value_index(conn, tg)
        json.dump(idx, open(os.path.join(OUT, "values", "%s.json" % db), "w"))
        mean = meanings(db)
        json.dump(mean, open(os.path.join(OUT, "meanings", "%s.json" % db), "w"), indent=1)
        conn.close()
        print("%s: %d columns and fields profiled, %d indexed values, %d meanings"
              % (db, len(tg), len(idx), len(mean)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
