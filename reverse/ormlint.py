#!/usr/bin/env python3
"""Lint a reverse-engineered model for modelling quality.

`model/validate.py` asks whether a model is well-formed: ids unique, references resolve,
blocks typed. This asks a different question -- whether the model is any *good* as ORM.
A model can pass every structural check and still claim eight subtypes that hold the whole
population, or name a fact type after the foreign-key column it came from.

Some of those questions cannot be answered from the model alone. A subtype is a proper
subset by definition, and whether a partition is proper is a fact about the data, not the
schema. So the interesting checks take `--db` and measure.

    usage: ormlint.py MODEL.ccm.json [...] [--db DIR|FILE] [--verbose] [--json]

Severities follow validate.py: `error` fails the file, `warning` and `note` report only.
"""

import argparse
import collections
import glob
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.ccm import Index                                            # noqa: E402
from model.names import words as _words                                # noqa: E402

CHECKS = []


def check(name, severity, needs_data=False, needs_mapping=False):
    """Register a check.

    `needs_data` ones are skipped when no database is given; `needs_mapping` ones when the
    model carries no relational mapping. A hand-built model has no mapping and is not wrong
    for it, so a check that decides against columns has nothing to say about one.
    """
    def register(fn):
        fn.check_name, fn.severity = name, severity
        fn.needs_data, fn.needs_mapping = needs_data, needs_mapping
        CHECKS.append(fn)
        return fn
    return register


class Findings:
    def __init__(self):
        self.items = []

    def add(self, check, severity, where, message):
        self.items.append((severity, check, where, message))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "error"]

    def by_check(self):
        out = collections.OrderedDict()
        for severity, check, where, message in self.items:
            out.setdefault((severity, check), []).append((where, message))
        return out

    def __bool__(self):
        return bool(self.errors)


class Data:
    """The model's relational mapping joined to a live database.

    Every data-driven check goes through here, so a model whose mapping does not reach
    the database degrades to "cannot measure" rather than raising.
    """

    def __init__(self, model, conn=None):
        mp = model.get("relationalMapping") or model.get("mapping") or {}
        self.conn = conn
        self.has_mapping = bool(mp.get("roleMap"))
        self.table = {t["id"]: t["name"] for t in mp.get("tables", [])}
        self.column = {c["id"]: c for c in mp.get("columns", [])}
        self.role = {e["role"]: e for e in mp.get("roleMap", [])}
        self.concept = collections.defaultdict(list)
        for e in mp.get("conceptMap", []):
            if "table" in e:
                self.concept[e["concept"]].append(e)
        #  None means "no database to check against", which is not the same as "no tables":
        #  a mapping-only check must not filter its tables away for want of a connection.
        self.live = None if conn is None else {t.casefold() for (t,) in conn.execute(
            "select name from sqlite_master where type='table'")}

    def scalar(self, sql):
        if self.conn is None:
            return None
        try:
            return self.conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return None

    def table_of(self, concept_id):
        """The table a concept maps to, if it maps to exactly one that exists."""
        entries = self.concept.get(concept_id) or []
        names = {self.table.get(e["table"]) for e in entries}
        names = {n for n in names
                 if n and (self.live is None or n.casefold() in self.live)}
        return names.pop() if len(names) == 1 else None

    def rows(self, concept_id):
        t = self.table_of(concept_id)
        return self.scalar('select count(*) from "%s"' % t) if t else None

    def is_row_identified(self, concept_id):
        """Whether the mapping identifies this concept by row identity alone (rule 1c)."""
        for e in self.concept.get(concept_id) or []:
            ids = [self.column.get(c, {}) for c in e.get("identifyingColumns", [])]
            if ids and all(c.get("isRowId") for c in ids):
                return True
        return False

    def columns_for(self, role_id):
        """(table, [column names]) for a role, or None if it is not mapped to one table."""
        e = self.role.get(role_id)
        if not e:
            return None
        t = self.table.get(e["table"])
        if not t or (self.live is not None and t.casefold() not in self.live):
            return None
        cols = [self.column[c]["name"] for c in e["columns"] if c in self.column]
        return (t, cols) if cols else None


# --------------------------------------------------------------------------- identity

@check("identifier-missing", "error")
def identifier_missing(m, ix, data, out):
    """An entity type with no reference scheme cannot be denoted, so nothing can be said
    about one. Reverse engineering produces these when a table has no key.

    A subtype declares none of its own and inherits, so an empty identifier is the correct
    spelling -- but only if some ancestor actually has one. The exemption therefore walks the
    chain: an entity type is identified if it or any supertype above it is. Stopping at the
    first supertype would let a chain of empty subtypes pass in silence, which is exactly how
    an eager identifier copy fails when the supertype is itself resolved later."""
    def identified(cid, seen=()):
        c = ix.concepts.get(cid)
        if c is None or cid in seen:
            return False
        if c.get("identifier") or c.get("referenceScheme"):
            return True
        # Row identity counts, and it is inherited like any other scheme: a subtype of a
        # keyless table's entity type is identified the same way its supertype is.
        if data.is_row_identified(cid):
            return True
        return any(identified(s, seen + (cid,)) for s in c.get("supertypes") or [])

    for c in m["concepts"]:
        if c["kind"] != "entity" or identified(c["id"]):
            continue
        # Rule 1c: a table with no key declared identifies its instances by row identity,
        # and the mapping says so with a rowid column. That is a deliberate, documented
        # reading of a keyless table rather than a gap -- there genuinely is no conceptual
        # reference scheme -- so it is worth saying and not worth failing the file over.
        if data.is_row_identified(c["id"]):
            out.add("identifier-missing", "note", c["id"],
                    "identified by row identity (rule 1c), so nothing names an instance in "
                    "the conceptual model. Declare a key to give it a reference scheme")
            continue
        how = "inherits none either" if c.get("supertypes") else "declares none"
        out.add("identifier-missing", "error", c["id"],
                "entity type has no identifier (%s): nothing can denote an instance" % how)


@check("identifier-not-played", "error")
def identifier_not_played(m, ix, data, out):
    """An entity type's preferred identifier must be roles it plays. A subtype that restates
    the supertype's identifier names a role whose player is the supertype -- a dangling
    reference in all but name. In ORM a subtype inherits identification and declares none.

    An entity type objectifying a fact type is the exception, and not a small one: it is
    identified by that fact type's roles, whose players are the *other* types the fact relates.
    `Assignment` identified by (Employee, Project) is objectification working correctly."""
    for c in m["concepts"]:
        if c["kind"] != "entity":
            continue
        mine = set(ix.roles_by_player.get(c["id"], []))
        twin = ix.twin.get(c["id"])
        if twin:
            mine |= {r["id"] for r in ix.concepts[twin].get("roles", [])}
        for rid in c.get("identifier") or []:
            if rid not in ix.roles:
                out.add("identifier-not-played", "error", c["id"],
                        "identifier names %r, which is not a role in this model" % rid)
            elif rid not in mine:
                owner = ix.concepts[ix.roles[rid]["player"]]["name"]
                out.add("identifier-not-played", "error", c["id"],
                        "identifier names %r, a role played by %s, not by this type"
                        % (rid, owner))


# --------------------------------------------------------------------------- subtyping

@check("subtype-undefined", "warning")
def subtype_undefined(m, ix, data, out):
    """A subtype needs a defining condition -- what makes an instance one. The CCM carries
    it as a derivation rule with `target.kind == "subtype"`. Without one the subtype asserts
    a partition it cannot describe, which is the one thing NORMA refuses to let pass."""
    rules = {r["target"]["ref"] for r in m.get("derivationRules", [])
             if r.get("target", {}).get("kind") == "subtype"}
    for c in m["concepts"]:
        for sup in c.get("supertypes") or []:
            if c["id"] not in rules:
                out.add("subtype-undefined", "warning", c["id"],
                        "subtype of %s with no defining condition"
                        % ix.concepts[sup]["name"])


@check("subtype-identifier-differs", "error")
def subtype_identifier_differs(m, ix, data, out):
    """A subtype is identified by its supertype's scheme. If it restates a *different* one --
    or an empty one, which is how an eager copy fails when the supertype is itself a subtype
    resolved later -- the inheritance is broken rather than merely redundant.

    The comparison is against the identifier the chain actually supplies, not against the
    immediate supertype's stored field. A run of subtypes that all copied an empty list would
    otherwise agree with each other and report nothing, which is the shape the bug produces."""
    def inherited(cid, seen=()):
        c = ix.concepts.get(cid)
        if c is None or cid in seen:
            return None
        if c.get("identifier"):
            return c["identifier"]
        for s in c.get("supertypes") or []:
            got = inherited(s, seen + (cid,))
            if got:
                return got
        return None

    for c in m["concepts"]:
        if not c.get("supertypes") or c.get("identifier") is None:
            continue
        theirs = next((inherited(s) for s in c["supertypes"] if inherited(s)), None)
        if theirs and c["identifier"] != theirs:
            out.add("subtype-identifier-differs", "error", c["id"],
                    "identifier %s does not match the %s inherited from %s"
                    % (c["identifier"] or "[]", theirs,
                       ix.concepts[c["supertypes"][0]]["name"]))


@check("subtype-not-proper", "warning", needs_data=True)
def subtype_not_proper(m, ix, data, out):
    """A subtype is a *proper* subset. One holding every instance of its supertype is a
    vertical partition wearing a subtype's clothes -- the shape a 1:1 table whose primary key
    is its foreign key always takes. Only the data can tell the two apart."""
    for c in m["concepts"]:
        for sup in c.get("supertypes") or []:
            sub_n, sup_n = data.rows(c["id"]), data.rows(sup)
            if not sub_n or not sup_n:
                continue
            if sub_n >= sup_n:
                out.add("subtype-not-proper", "warning", c["id"],
                        "holds %d of %s's %d instances: not a subtype but a vertical "
                        "partition" % (sub_n, ix.concepts[sup]["name"], sup_n))


# --------------------------------------------------------------------------- constraints

@check("fact-type-no-uniqueness", "warning")
def fact_type_no_uniqueness(m, ix, data, out):
    """Every fact type needs at least one uniqueness constraint; without one it is a bag,
    and nothing downstream can tell how many times a thing may play a role.

    A *derived* fact type is the softer case. Its population comes from its rule, so the
    uniqueness is implied by the rule rather than declared, and every derived fact type a
    modeller writes would otherwise be reported -- 20 of 20 across the benchmark's semantic
    models. Still worth saying, because ORM wants the constraint either way, but as a note."""
    spanned = set()
    for k in m.get("constraints", []):
        if k.get("kind") != "uniqueness":
            continue
        for seq in k.get("roleSequences", []):
            if seq and seq[0] in ix.role_owner:
                spanned.add(ix.role_owner[seq[0]])
    for c in m["concepts"]:
        if c["kind"] != "fact" or c["id"] in spanned:
            continue
        if c.get("derivation"):
            out.add("fact-type-no-uniqueness", "note", c["id"],
                    "derived fact type carries no uniqueness constraint: its rule implies "
                    "one, but ORM wants it declared")
        else:
            out.add("fact-type-no-uniqueness", "warning", c["id"],
                    "fact type carries no uniqueness constraint")


@check("fact-type-no-mandatory-role", "note")
def fact_type_no_mandatory_role(m, ix, data, out):
    """A fact type no role of which is mandatory says nothing must ever be recorded. Often
    right -- an optional attribute is exactly this -- so it is a note, not a warning."""
    for c in m["concepts"]:
        if c["kind"] == "fact" and not any(r.get("isMandatory") for r in c.get("roles", [])):
            out.add("fact-type-no-mandatory-role", "note", c["id"],
                    "no role is mandatory: nothing obliges this fact to be recorded")


@check("uniqueness-violated", "error", needs_data=True)
def uniqueness_violated(m, ix, data, out):
    """A uniqueness constraint the data breaks. The model is then asserting something false,
    and the compiler will read it as licence to elide a join or a DISTINCT."""
    for k in m.get("constraints", []):
        if k.get("kind") != "uniqueness":
            continue
        for seq in k.get("roleSequences", []):
            mapped = [data.columns_for(r) for r in seq]
            if not seq or any(x is None for x in mapped):
                continue
            if len({t for t, _ in mapped}) != 1:
                continue
            table = mapped[0][0]
            cols = [c for _, cs in mapped for c in cs]
            sel = ", ".join('"%s"' % c for c in cols)
            dup = data.scalar('select count(*) from (select %s from "%s" group by %s '
                              "having count(*) > 1)" % (sel, table, sel))
            if dup:
                out.add("uniqueness-violated", "error", k["id"],
                        "%s(%s) is not unique: %d repeated value%s"
                        % (table, ", ".join(cols), dup, "" if dup == 1 else "s"))


@check("mandatory-role-empty", "error", needs_data=True)
def mandatory_role_empty(m, ix, data, out):
    """A mandatory role whose column is null somewhere: the model says every instance plays
    it and the data disagrees.

    Only roles played by *entity* types are checked. A value type's population is the column's
    values, which excludes null by construction, so a mandatory value role is vacuously true
    and reporting it produces one finding per nullable column and no information."""
    for c in m["concepts"]:
        if c["kind"] != "fact":
            continue
        for r in c.get("roles", []):
            if not r.get("isMandatory"):
                continue
            if ix.concepts[r["player"]]["kind"] != "entity":
                continue
            mapped = data.columns_for(r["id"])
            if not mapped:
                continue
            table, cols = mapped
            for col in cols:
                n = data.scalar('select count(*) from "%s" where "%s" is null' % (table, col))
                if n:
                    out.add("mandatory-role-empty", "error", r["id"],
                            "role is mandatory but %s.%s is null in %d row%s"
                            % (table, col, n, "" if n == 1 else "s"))


# --------------------------------------------------------------------------- readings

PLACEHOLDER = re.compile(r"\{(\d+)\}")
#  The adjective a hyphen binds to the object type -- FORML 2 section 1.2, and the form the
#  reverse engineer emits for a ring or a labelled reference: "{0} has manager- {1}".
BOUND_ADJECTIVE = re.compile(r"([A-Za-z][A-Za-z0-9 ]*?)[-_]\s*\{")
#  ... but the adjective should name the role, not the column that carried it. A name ending
#  in ref/key/registry/id is the foreign key leaking through: "{0} has jcdetref- {2}".
REFERENCE_SHAPED = re.compile(r"(ref|reference|registry|key|id|idx|no|num|code)$", re.I)


@check("reading-arity", "error")
def reading_arity(m, ix, data, out):
    """A reading must place every role exactly once, or verbalisation cannot use it."""
    for c in m["concepts"]:
        if c["kind"] != "fact":
            continue
        n = len(c.get("roles", []))
        for rd in c.get("readings", []):
            slots = [int(x) for x in PLACEHOLDER.findall(rd["text"])]
            if sorted(slots) != list(range(n)):
                out.add("reading-arity", "error", rd["id"],
                        "reading %r does not place each of %d role%s exactly once"
                        % (rd["text"], n, "" if n == 1 else "s"))


@check("reading-adjective-is-a-reference", "note")
def reading_adjective_is_a_reference(m, ix, data, out):
    """A hyphen-bound adjective that is the foreign-key column rather than the role.

    The hyphen itself is correct: FORML 2 section 1.2 binds the adjective to the object type
    so the quantifier reads "at most one manager Employee", and the query language drops it.
    `has manager- {1}` is right. `has jcdetref- {2}` is the same construction with the column
    name left in, so the reading names the key instead of what the role means.

    Checked narrowly on purpose -- the first draft flagged every hyphen and reported 177
    findings, all of them correct FORML."""
    for c in m["concepts"]:
        if c["kind"] != "fact":
            continue
        for rd in c.get("readings", []):
            for adjective in BOUND_ADJECTIVE.findall(rd["text"]):
                word = adjective.split()[-1]
                if REFERENCE_SHAPED.search(word):
                    out.add("reading-adjective-is-a-reference", "note", rd["id"],
                            "reading %r binds %r, a reference column, where the role's "
                            "meaning belongs" % (rd["text"], word))


# --------------------------------------------------------------------------- naming

@check("fact-type-named-for-column", "note", needs_mapping=True)
def fact_type_named_for_column(m, ix, data, out):
    """An entity-to-entity fact type named after the foreign-key column rather than the type
    it reaches: `TelescopeHasObservstation` for (Telescope, Observatory). The reading is built
    from the players and stays correct; it is the name beside it that carries no information.

    Decided against the mapping, not against the far type's name. A fact type whose name simply
    omits the type it reaches is usually *better* -- `TelescopeIsAt`, `SignalDetectedDuring` --
    and an earlier draft that asked only "is the far type's name in here?" reported both of
    those. What makes a name wrong is that it ends in the column the role is mapped to."""
    for c in m["concepts"]:
        if c["kind"] != "fact" or len(c.get("roles", [])) != 2:
            continue
        near, far = [ix.concepts[r["player"]] for r in c["roles"]]
        if near["kind"] != "entity" or far["kind"] != "entity":
            continue
        mapped = data.columns_for(c["roles"][1]["id"])
        if not mapped:
            continue
        name = c["name"].casefold()
        for col in mapped[1]:
            if name.endswith(col.casefold()) and far["name"].casefold() not in name:
                out.add("fact-type-named-for-column", "note", c["id"],
                        "named for the column %r, not for %s, which the role reaches"
                        % (col, far["name"]))
                break


#  Units that name a condition of the surroundings rather than a property of a thing. A
#  product's mass does not change; the air temperature at an observatory changes hourly.
#  Deliberately short: percentage was in it and dragged in scan coverage and battery charge,
#  which are not weather, and a check that fires on ten tables teaches nothing.
WEATHER_UNITS = frozenset(("degC", "K", "hPa", "m/s"))
TEMPORAL_WORDS = frozenset(("date", "time", "timestamp", "stamp", "when", "day", "month",
                            "year", "hour", "minute", "moment", "instant", "epoch"))


@check("entity-holds-a-reading", "note")
def entity_holds_a_reading(m, ix, data, out):
    """An entity type carrying environmental measurements and no time of its own.

    The conditions at an observatory -- air temperature, wind speed, pressure -- are facts
    about a *moment*, not properties of a building. Stored as attributes of the observatory
    they can only ever hold the latest reading, and the entity type ends up standing for two
    things at once: the station, and the weather there just now.

    The repair is to objectify: `SkyState` over (Observatory, Time), with the conditions
    hanging off that. It is not done automatically, and cannot be -- objectifying needs a
    time role to key on, and a table in this shape has no timestamp column to supply one.
    The schema has already lost the history; what is left is to say so.
    """
    for e in m["concepts"]:
        if e["kind"] != "entity":
            continue
        readings, temporal = [], False
        for f in m["concepts"]:
            if f["kind"] != "fact" or len(f.get("roles", [])) != 2:
                continue
            near, far = f["roles"]
            if near["player"] != e["id"]:
                continue
            v = ix.concepts[far["player"]]
            if v["kind"] != "value":
                continue
            if v.get("unit") in WEATHER_UNITS:
                readings.append(v["name"])
            # Whole words only. An earlier count matched `at` inside `Weath` and reported
            # 107 of 175 entity types, which is a check nobody would keep switched on.
            if TEMPORAL_WORDS & {w.casefold() for w in _words(v["name"])} \
                    or (v.get("dataType") or {}).get("name") in ("date", "time", "timestamp"):
                temporal = True
        if len(readings) >= 2 and not temporal:
            out.add("entity-holds-a-reading", "note", e["id"],
                    "carries %s and no time of its own: these are conditions at a moment, so "
                    "only the latest can be stored. The conditions belong to an objectified "
                    "(%s, Time), which this table has no timestamp to key."
                    % (", ".join(sorted(readings)), e["name"]))


@check("value-type-unplayed", "warning")
def value_type_unplayed(m, ix, data, out):
    """A value type no role plays is unreachable: nothing in the model can produce one."""
    for c in m["concepts"]:
        if c["kind"] == "value" and not ix.roles_by_player.get(c["id"]):
            out.add("value-type-unplayed", "warning", c["id"],
                    "value type is played by no role: unreachable")


@check("value-type-never-shared", "note")
def value_type_never_shared(m, ix, data, out):
    """One value type per column means the model has no domains: `ObservatoryAirtempc` and
    `TelescopeDetecttempk` are both a temperature and share nothing. Reported once per model
    rather than once per value type, which would be thousands of findings and no signal."""
    vals = [c for c in m["concepts"] if c["kind"] == "value"]
    shared = [c for c in vals if len(ix.roles_by_player.get(c["id"], [])) > 1]
    if vals and not shared:
        out.add("value-type-never-shared", "note", m.get("id", "model"),
                "none of the %d value types is played by more than one role: the model has "
                "no shared domains" % len(vals))


# --------------------------------------------------------------------------- driver

def lint(path, db=None, only=None):
    model = json.load(open(path))
    ix = Index(model)
    out = Findings()
    conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True) if db else None
    data = Data(model, conn)
    for fn in CHECKS:
        if only and only not in fn.check_name:
            continue
        if fn.needs_data and conn is None:
            continue
        if fn.needs_mapping and not data.has_mapping:
            continue
        fn(model, ix, data, out)
    return out


def find_db(model_path, db_arg):
    """`--db` may be a file, or a directory laid out as <dir>/<name>/<name>.sqlite."""
    if not db_arg or os.path.isfile(db_arg):
        return db_arg
    name = os.path.basename(model_path).split(".")[0]
    #  `<dir>/<name>/<anything>.sqlite`, `<dir>/<name>.sqlite`, and the shape LiveSQLBench
    #  ships, `<dir>/<name>_template.sqlite`. Matching only the first two meant a whole tier
    #  linted with its data checks silently skipped.
    for pattern in (os.path.join(db_arg, name, "*.sqlite"),
                    os.path.join(db_arg, name + ".sqlite"),
                    os.path.join(db_arg, name + "_*.sqlite")):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[0]
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("models", nargs="+", help="one or more .ccm.json files")
    ap.add_argument("--db", help="a .sqlite file, or a directory of them, to measure against")
    ap.add_argument("--only", help="run only checks whose name contains this")
    ap.add_argument("--verbose", "-v", action="store_true", help="list every finding")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--quiet", "-q", action="store_true", help="totals only")
    args = ap.parse_args(argv)

    paths = [p for a in args.models for p in sorted(glob.glob(a))] or args.models
    total = collections.Counter()
    failed = 0
    report = {}

    for path in paths:
        db = find_db(path, args.db)
        out = lint(path, db, args.only)
        name = os.path.basename(path).split(".")[0]
        report[name] = [{"severity": s, "check": c, "where": w, "message": m}
                        for s, c, w, m in out.items]
        if out:
            failed += 1
        for severity, chk, _, _ in out.items:
            total[(severity, chk)] += 1
        if args.as_json or args.quiet:
            continue

        marks = out.by_check()
        head = "%-14s %s" % (name, "clean" if not marks else
                             "%d finding%s%s" % (len(out.items),
                                                 "" if len(out.items) == 1 else "s",
                                                 "" if db else "  (no --db: data checks skipped)"))
        print(head)
        for (severity, chk), items in sorted(marks.items()):
            print("  %-7s %-30s %4d" % (severity, chk, len(items)))
            show = items if args.verbose else items[:2]
            for where, message in show:
                print("          %s: %s" % (where, message))
            if len(items) > len(show):
                print("          ... and %d more" % (len(items) - len(show)))
        print()

    if args.as_json:
        print(json.dumps(report, indent=1))
    else:
        print("=" * 66)
        print("%-38s %s" % ("across %d model%s" % (len(paths), "" if len(paths) == 1 else "s"),
                            "%d clean" % (len(paths) - failed) if failed else "all clean"))
        for (severity, chk), n in sorted(total.items(), key=lambda kv: (-kv[1], kv[0])):
            print("  %-7s %-32s %6d" % (severity, chk, n))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
