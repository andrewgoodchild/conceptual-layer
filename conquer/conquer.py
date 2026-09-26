#!/usr/bin/env python3
"""ConQuer-92 to SQL transpiler, and a runner for the result.

    conquer.py MODEL.ccm.json --db company.sqlite "Employee has EmployeeName"
    conquer.py MODEL.ccm.json --db company.sqlite -f queries.cq
    conquer.py MODEL.ccm.json --sql-only "Employee has EmployeeSalary > 100000"
    conquer.py MODEL.ccm.json --normalise "Employee has Department: 'ENG'"   section 8
    conquer.py MODEL.ccm.json --db company.sqlite --repl
    conquer.py MODEL.ccm.json --schema          what the schema lets you say

The pipeline is the one in model/README.md:

    ConQuer-92 text                     parser.py    (schema-driven, grammar appendix B)
      -> path-expression AST            parser.py    (ConQuer's algebra; verbalisation lives here)
      -> Common Core Model block        lower.py     (flat, explicit; model/model.md)
      -> SQL-92                         sql.py       (model/binding-sql92.md)
      -> rows                           this file
"""

import argparse
import copy
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lower as lower_mod      # noqa: E402
import parser as parser_mod    # noqa: E402
import normalise as norm_mod   # noqa: E402
import sql as sql_mod          # noqa: E402
import verbalise as verb_mod   # noqa: E402


def expand_definitions(model, text, lexicon=None):
    """Take `DEFINE <Name> ::= <query>` off the front, adding each to a copy of the model.

    Returns (model, the query that is left, lexicon). Costs nothing when there is no DEFINE,
    which is every query in the corpus and every query in the suite.

    Each definition is parsed against a lexicon that already knows the ones before it, so a
    definition may be written in terms of an earlier one. That is also why the body is
    located by parsing rather than by splitting the text: only the parser knows where a
    query ends.
    """
    if "DEFINE" not in text:
        return model, text, lexicon, []
    model = copy.deepcopy(model)                 # the caller's model is not ours to extend
    lexicon, defined = None, []
    while True:
        lexicon = lexicon or parser_mod.Lexicon(model)
        p = parser_mod.Parser(lexicon, text)
        name = p.parse_definition()
        if name is None:
            return model, text, lexicon, defined
        start = p.toks[p.i].pos if p.i < len(p.toks) else len(text)
        try:
            p._parse_query_parts()
        except parser_mod.ParseError as e:
            raise type(e)("in the definition of %s: %s" % (name, e))
        end = p.toks[p.i].pos if p.i < len(p.toks) else len(text)
        lower_mod.define(model, name, text[start:end], lexicon)
        defined.append(name)
        text, lexicon = text[end:], None
        if not text.strip():
            raise parser_mod.ParseError(
                "%s is defined but nothing asks anything of it; a DEFINE comes before the "
                "query that uses it" % name)


def transpile(model, text, lexicon=None, emitter=None, permissive=False):
    """Text to (block, SQL, parameters).

    `lexicon` and `emitter` are optional so a caller running many queries against one model
    builds the indexes once. Without them a single query used to build two Lexicons and an
    Emitter, all over the same model.
    """
    extended, text, lexicon, _ = expand_definitions(model, text, lexicon)
    if extended is not model:
        model, emitter = extended, None          # the definitions changed the model
    lexicon = lexicon or parser_mod.Lexicon(model)
    lower_mod.lower_rules(model, lexicon)          # section 6.11, once per model
    ast = parser_mod.Parser(lexicon, text).parse_query()
    block = lower_mod.lower(model, ast, lexicon, permissive=permissive)
    statement, params = (emitter or sql_mod.Emitter(model)).emit(block)
    return block, statement, params


try:
    import psycopg
    DB_ERRORS = (sqlite3.Error, psycopg.Error)
except ImportError:                                                    # pragma: no cover
    DB_ERRORS = (sqlite3.Error,)


class _Server:
    """A PostgreSQL connection behind the calls the runner makes of sqlite3: `execute(sql,
    params)` with `?` markers, a cursor with `description` and `fetch*`, and `close()`.

    Read-only, as the SQLite path is, and with a statement timeout: a runner has no business
    writing to the database it reads, and a query that never ends would otherwise hold a
    writer's whole budget. Parameters are bound client-side, quoted by the driver, because
    the server cannot type a bare `(SELECT $1)` -- which is how a constant group key is
    spelled -- and every scorer inlines them the same way."""

    def __init__(self, dsn):
        import psycopg
        self.conn = psycopg.connect(dsn, autocommit=True, cursor_factory=psycopg.ClientCursor)
        self.conn.execute("SET default_transaction_read_only = on")
        self.conn.execute("SET statement_timeout = 120000")

    @staticmethod
    def placeholders(sql):
        """`?` to `%s` outside quoted text, and every `%` to `%%`: the driver reads the whole
        statement for markers, quotes included, so a LIKE pattern's `'%'` must be doubled."""
        out, quote = [], None
        for ch in sql:
            if ch == "%":
                out.append("%%")
            elif quote:
                out.append(ch)
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
                out.append(ch)
            elif ch == "?":
                out.append("%s")
            else:
                out.append(ch)
        return "".join(out)

    def execute(self, sql, params=()):
        return self.conn.execute(self.placeholders(sql), list(params))

    def close(self):
        self.conn.close()


def unmapped_tables(model, conn):
    """The mapping's tables that are not in this database.

    Nothing used to check that a model and its `--db` were about the same database. A name that
    does not exist fails loudly enough, but a *partially* overlapping schema -- the same model
    against last quarter's extract, or one of two databases that share half their tables --
    runs and returns wrong rows. A model is bound to one physical schema by construction: the
    mapping names bare tables and has no notion of a source, so the binding has to be checked
    rather than assumed. Derived tables are virtual and are skipped.
    """
    here = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        if isinstance(conn, _Server) else
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    if not here:
        return []                       # an empty database is someone else's problem to report
    want = [t for t in model.get("mapping", {}).get("tables", []) if not t.get("derived")]
    return [t["name"] for t in want if t["name"] not in here]


def identification(model):
    """What names an instance of each entity type, and every column that value is stored in.

    `{entity id: {"by", "stored", "referenced", "also"}}`: the preferred identifier as names;
    the keys that *are* the identity (the entity's own table, and any vertical partition
    absorbed into it); the columns elsewhere that refer to it; and the other values that
    identify it, each with whatever refers to an instance by that value instead.

    All of it was already in the model and none of it was shown. LiveSQLBench's credit
    questions ask for "customer IDs"; `CoreRecord` has `coreregistry`, the key six tables
    carry under six names, and `clientref`, a code nothing references. The listing printed
    both as `CoreRecord has ...`, a writer took the one named for clients, and five answers
    with every figure right were wrong. cross_db's writer did the same with a `flowtag` that
    is not even unique. The reference scheme is the first thing an ORM diagram shows and the
    one thing this listing never said.
    """
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    owner, player = {}, {}
    for c in model.get("concepts", []):
        for r in c.get("roles", []) if c["kind"] == "fact" else []:
            owner[r["id"]], player[r["id"]] = c, r["player"]
    mapping = model.get("mapping") or {}
    table = {t["id"]: t["name"] for t in mapping.get("tables", [])}
    column = {c["id"]: c for c in mapping.get("columns", [])}
    placed = {m["concept"]: m for m in mapping.get("conceptMap", [])}

    def spell(cols):
        """One key, as one entry: `t.c`, or `t.(a, b)` where it takes several columns --
        two columns of one key are one spelling of the identity, not two."""
        cols = [column[c] for c in cols if c in column and not column[c].get("isRowId")]
        if not cols:
            return []
        names = [c["name"] for c in cols]
        return ["%s.%s" % (table.get(cols[0]["table"], "?"),
                           names[0] if len(names) == 1 else "(%s)" % ", ".join(names))]

    def other(role_id):
        fact = owner.get(role_id)
        rest = [r for r in fact["roles"] if r["id"] != role_id] if fact else []
        return rest[0] if fact and len(fact["roles"]) == 2 else None

    out = {c["id"]: {"by": [], "stored": [], "referenced": [], "also": []}
           for c in model.get("concepts", []) if c["kind"] == "entity"}
    preferred = {}                       # entity -> the fact types of its reference scheme
    for eid, entry in out.items():
        for rid in concepts[eid].get("identifier") or []:
            far = other(rid)
            if far is not None:
                entry["by"].append(concepts.get(far["player"], {}).get("name", far["player"]))
                preferred.setdefault(eid, set()).add(owner[rid]["id"])

    by_value = {}           # a column holding a value -> (entity it is a fact about, value type)
    elsewhere = {}          # the same column -> what refers to an instance by it
    for rm in mapping.get("roleMap", []):
        rid, fact = rm["role"], owner.get(rm["role"])
        if fact is None:
            continue
        who = concepts.get(player[rid], {})
        if who.get("kind") == "value":
            far = other(rid)
            if far is not None and far["player"] in out and len(rm["columns"]) == 1:
                by_value[rm["columns"][0]] = (far["player"], who["name"])
        elif who.get("id") in out:
            entry, at = out[who["id"]], placed.get(fact["id"], {})
            if rm.get("references"):
                # a foreign key onto a column that is not the identifier: it refers to the
                # instance, but by the *other* value (`legalities.uuid -> cards.uuid`)
                elsewhere.setdefault(tuple(rm["references"]), []).extend(spell(rm["columns"]))
            elif at.get("table") == rm["table"] and \
                    at.get("identifyingColumns") == rm["columns"]:
                # the key of the table the fact lives in *is* this instance
                entry["stored"] += [s for s in spell(rm["columns"]) if s not in entry["stored"]]
            else:
                entry["referenced"] += [s for s in spell(rm["columns"])
                                        if s not in entry["referenced"]]

    unique = {}
    for k in model.get("constraints", []):
        seqs = k.get("roleSequences", [])
        if k["kind"] == "uniqueness" and len(seqs) == 1 and len(seqs[0]) == 1:
            unique[seqs[0][0]] = k
    seen = set()
    for rid in unique:
        far, who = other(rid), concepts.get(player.get(rid), {})
        if far is None or who.get("kind") != "value" or far["player"] not in out \
                or owner[rid]["id"] in preferred.get(far["player"], ()):
            continue
        cols = next((tuple(rm["columns"]) for rm in mapping.get("roleMap", [])
                     if rm["role"] == rid), ())
        out[far["player"]]["also"].append((who["name"], elsewhere.get(cols, []), True))
        seen.add(cols)
    for cols, referrers in elsewhere.items():
        # referenced and not known to be unique: still what other tables call the instance
        if cols not in seen and len(cols) == 1 and cols[0] in by_value:
            eid, name = by_value[cols[0]]
            out[eid]["also"].append((name, referrers, False))
    return out


def _article(name):
    """`a` or `an`, well enough for type names: `an Order`, `a User`, `an Update`."""
    low = name[:1].lower()
    if low in "aeio" or (low == "u" and name[1:2].lower() in "nmp"):
        return "an " + name
    return "a " + name


def _some(items, limit=6):
    """A list short enough to read: the first few, and how many were left out."""
    items = list(items)
    if len(items) <= limit:
        return ", ".join(items)
    return "%s, and %d more" % (", ".join(items[:limit]), len(items) - limit)


def describe_identification(identified, shown):
    """The identification section of the listing, for the entity types in `shown`."""
    lines = []
    for c in sorted(shown, key=lambda c: c["name"]):
        entry = identified.get(c["id"])
        if entry is None or c.get("supertypes"):
            continue                    # a subtype is identified as its supertype is
        if not entry["by"]:
            lines.append("  %-28s (no identifier: no key is declared, so there is no value "
                         "to name an instance by)" % c["name"])
            continue
        used = [(n, r, u) for n, r, u in entry["also"] if r]
        if not entry["referenced"] and len(used) == 1:
            # The declared key is referenced by nothing and one other value is what every
            # foreign key holds. Two writers read the ordinary form of this line as a
            # contradiction -- headed by a key the next clause says nobody uses -- so it
            # leads with the value the schema uses, and says which is which.
            name, referrers, _ = used[0]
            lines.append("  %-28s %s -- what the rest of the schema names %s by: %s hold%s "
                         "it. Asked for its id, list this."
                         % (c["name"], name, _article(c["name"]),
                            _some(referrers, 4), "s" if len(referrers) == 1 else ""))
            lines.append("  %-28s   %s is the declared key, and nothing refers to %s by it."
                         % ("", " + ".join(entry["by"]), _article(c["name"])))
            for other, _, unique in entry["also"]:
                if other != name and unique:
                    lines.append("  %-28s   also unique: %s -- a third identifier, with its "
                                 "own values" % ("", other))
            continue
        lines.append("  %-28s %s" % (c["name"], " + ".join(entry["by"])))
        where = []
        if len(entry["stored"]) > 1:
            where.append("one value, stored as " + _some(entry["stored"]))
        if entry["referenced"]:
            where.append("other tables refer to it as " + _some(entry["referenced"], 4))
        if where:
            lines.append("  %-28s   %s" % ("", "; ".join(where)))
        for name, referrers, unique in entry["also"]:
            said = ("also unique: %s -- a second identifier, with its own values" % name
                    if unique else "also named by %s" % name)
            if referrers:
                said += ", which is what %s hold%s" % (_some(referrers, 4),
                                                      "s" if len(referrers) == 1 else "")
                if not entry["referenced"]:
                    said += "; nothing refers to %s" % " + ".join(entry["by"])
            elif not entry["referenced"] and len(entry["stored"]) < 2:
                pass                    # neither is referred to: nothing to tell them apart by
            else:
                said += "; nothing refers to %s by it" % _article(c["name"])
            lines.append("  %-28s   %s" % ("", said))
    return lines


def storage(model):
    """Where each concept lives, in a SQL writer's terms: an entity type as its table and
    key, a value type as its column -- or the document column and the field inside it --
    and a fact type as the columns that carry it, `referencing -> referenced` where it
    crosses tables. The listing's names are the model's; a reader who will write SQL needs
    the columns beside them, and this is that map, read off the mapping the compiler uses.
    """
    mapping = model.get("mapping") or {}
    table = {t["id"]: t["name"] for t in mapping.get("tables", [])}
    column = {c["id"]: c for c in mapping.get("columns", [])}
    placed = {m["concept"]: m for m in mapping.get("conceptMap", [])}
    role_map = {rm["role"]: rm for rm in mapping.get("roleMap", [])}
    concepts = {c["id"]: c for c in model.get("concepts", [])}

    def col(cid):
        c = column.get(cid)
        if c is None:
            return cid
        path = list(c.get("path") or [])
        # PostgreSQL's spelling: `->` steps into a document, `->>` reads the leaf as text
        name = c["name"] + "".join("->'%s'" % p for p in path[:-1]) + \
            ("->>'%s'" % path[-1] if path else "")
        return "%s.%s" % (table.get(c["table"], "?"), name)

    def cols(ids):
        return ", ".join(col(i) for i in ids)

    out = {}
    for cid, c in concepts.items():
        at = placed.get(cid)
        if c["kind"] == "entity" and at and at.get("table"):
            keys = [k for k in at.get("identifyingColumns", [])
                    if not column.get(k, {}).get("isRowId")]
            out[cid] = 'table "%s"' % table.get(at["table"], "?") + \
                (", key %s" % cols(keys) if keys else "")
    for cid, c in concepts.items():
        if c["kind"] != "fact" or not c.get("roles"):
            continue
        maps = [role_map.get(r["id"]) for r in c["roles"]]
        if any(m is None for m in maps):
            continue
        parts = []
        for r, m in zip(c["roles"], maps):
            p = concepts.get(r["player"], {})
            if p.get("kind") == "value":
                if m.get("columns"):
                    out.setdefault(p["id"], cols(m["columns"]))
                    parts.append(cols(m["columns"]))
                continue
            at = placed.get(p.get("id"), {})
            own_key = at.get("table") == m.get("table") and \
                at.get("identifyingColumns") == m.get("columns")
            if not own_key and m.get("columns"):
                # this role refers to the instance from elsewhere: a foreign key, onto the
                # identifier or onto whatever the mapping says it references
                target = m.get("references") or at.get("identifyingColumns") or []
                parts.append("%s -> %s" % (cols(m["columns"]), cols(target))
                             if target else cols(m["columns"]))
        out[cid] = "; ".join(parts) if parts else cols(maps[0].get("columns", []))
    return out


def describe(model, question=None, relational=False):
    """What the schema lets you say. With a question, only the part of it that question is
    about -- `link.py`, which keeps every table the answer needs for 94% of BIRD's questions
    while dropping three quarters of the model. `relational` puts where each thing is stored
    beside it, for a reader who will write SQL rather than ConQuer."""
    hidden = []
    where = storage(model) if relational else {}

    def tag(cid):
        return "   [%s]" % where[cid] if cid in where else ""
    # before the view is narrowed: what refers to a type is a fact about the whole schema,
    # and the narrowing drops the fact types that say it
    identified = identification(model)
    if question:
        import link as link_mod
        keep = link_mod.Linker(model).relevant(question)
        if keep:
            hidden = sorted(c["name"] for c in model["concepts"]
                            if c["kind"] == "entity" and c["id"] not in keep)
            model = dict(model, concepts=[c for c in model["concepts"] if c["id"] in keep])
    lex = parser_mod.Lexicon(model)
    lines = []
    if relational:
        lines += ["The conceptual model of this database, with where each thing is stored in "
                  "brackets beside it: a table and its key; a column; a field inside a JSON "
                  "column as column->>'field'; a relationship as the referencing column -> "
                  "the key it refers to. The names are the model's (a column's value type is "
                  "named TableColumn); the columns are the database's.", ""]
    lines += ["Types you can name:", ""]
    for kind, label in (("entity", "Entity types"), ("value", "Value types")):
        typed = sorted((c["name"], c["id"]) for c in model["concepts"] if c["kind"] == kind)
        names = [n + (" [%s]" % where[i] if i in where else "") for n, i in typed]
        lines += ["  %s (%d): %s" % (label, len(names), ", ".join(names)), ""]
    if hidden:
        # The filter scores the words the question uses, and a question names what it is about
        # rather than what it is computed from: "system unavailability" never says MTTR, so
        # the entity holding MTTR was dropped and a writer had to dump the whole model to find
        # it (finding 102). Nothing can recover a word nobody wrote -- but saying that the
        # view is partial, and that more words widen it, turns a silent omission into a
        # question the reader can answer. Naming what was left out turns it into one they
        # can answer without a second call: twenty-two writers over the MCP server said the
        # narrowed view had hidden the one table they needed (Tag, Driver, ForeignData),
        # and a bare count told them nothing about which (finding 164).
        lines += ["  Not shown, as the words you used did not reach %s: %s."
                  % ("it" if len(hidden) == 1 else "them", _some(hidden, 12)),
                  "   The view is scored on those words; add the terms a definition uses -- "
                  "the quantities",
                  "   a formula is built from, not just the name of the thing -- to widen it.",
                  ""]
    domains = [c for c in model["concepts"]
               if c["kind"] == "value" and (c.get("restriction") or {}).get("values")]
    if domains:
        lines += ["Value domains (every value the type is known to hold; a filter must spell "
                  "one of these exactly):"]
        for c in sorted(domains, key=lambda x: x["name"]):
            vals = c["restriction"]["values"]
            shown = ", ".join(repr(v) for v in vals[:10])
            if len(vals) > 10:
                shown += ", and %d more" % (len(vals) - 10)
            lines.append("  %-28s %s%s" % (c["name"], shown, tag(c["id"])))
        lines.append("")
    # Above the domains and the readings: which value names a thing is the first decision an
    # answer makes and the one a writer cannot recover from the readings, where the
    # identifier is one `has` among a hundred.
    naming = describe_identification(
        identified, [c for c in model["concepts"] if c["kind"] == "entity"])
    if naming:
        lines += ["Identification (the value that names an instance. Asked for a thing's id, "
                  "this is the value that answers it, unless the question names another. The "
                  "columns listed beside a value all hold that value, whatever they are "
                  "called):", ""]
        lines += naming + [""]
    subs = [c for c in model["concepts"]
            if c["kind"] != "fact" and c.get("supertypes") and not c.get("derivation")]
    if subs:
        lines += ["Subtypes (an instance of the subtype is an instance of its supertype, with "
                  "the same identifier: from the subtype, the supertype's readings apply; "
                  "from the supertype, name the subtype to narrow to it):"]
        for c in subs:
            sup = ", ".join(lex.concepts.get(s, {}).get("name", s) for s in c["supertypes"])
            lines.append("  %-28s is a %s" % (c["name"], sup))
        lines.append("")
    # What the terms mean, where anyone wrote it down. A model built by reverse engineering
    # has none of these; one that absorbed a data dictionary or a benchmark's knowledge base
    # has them, and they are the half a query author needs that a formula does not give --
    # `terms` lets the model match a word, this says what the word means. Finding 132
    # measured this listing as the surface that decides answers, so it goes above the
    # readings rather than beside them.
    # What the values are actually like, where anyone profiled them. Not constraints --
    # nothing enforces these -- but each one is a way an ordinary filter matches the wrong
    # rows without failing, which is the class of mistake this listing exists to prevent.
    cautioned = [c for c in model["concepts"] if c.get("dataQuality")]
    if cautioned:
        lines += ["Value cautions (what the data is like, from profiling it):", ""]
        for c in sorted(cautioned, key=lambda c: c["name"]):
            for i, said in enumerate(c["dataQuality"]):
                lines.append("  %-28s %s%s" % (c["name"] if i == 0 else "", said,
                                               tag(c["id"]) if i == 0 else ""))
        lines.append("")
    described = [c for c in model["concepts"] if c.get("description")]
    if described:
        lines += ["Defined terms (what the model means by them; use them like any other "
                  "type):", ""]
        for c in sorted(described, key=lambda c: c["name"]):
            lines.append("  %-30s %s%s" % (c["name"], " ".join(c["description"].split()),
                                           tag(c["id"])))
        lines.append("")
    lines += ["Predicate readings (the verb parts a path may use):", ""]
    rings = []
    rules = {r["id"]: r for r in model.get("derivationRules", [])}
    derived_types = [c for c in model["concepts"] if c["kind"] != "fact" and c.get("derivation")]
    for c in sorted((c for c in model["concepts"] if c["kind"] == "fact"),
                    key=lambda c: c["name"]):
        line = "  %-28s %s%s" % (c["name"], lex.verbalise(c), tag(c["id"]))
        if c.get("derivation") in rules:
            src = " ".join(rules[c["derivation"]].get("source", "").split())
            line += "   (derived: %s)" % src
        if len(c.get("roles", [])) == 1:
            # A unary fact type is a set, not a traversal: there is nothing on the other side
            # to walk to. The lexicon registers no verb for one, so the reading printed here
            # is not a verb part a path may use -- and saying so is the whole point, because
            # listing it unmarked advertises a step that comes back "'is' is neither a type
            # in this schema nor a variable" (finding 135).
            line += "   (unary: a property, not a step -- no path walks it)"
        players = [r["player"] for r in c.get("roles", [])]
        if len(set(players)) < len(players):
            # one type plays two roles: the reading alone cannot say which is which, and
            # Appendix B.2's role reference is how a query says it -- so name the roles
            names = [r.get("name") or "?" for r in c["roles"]]
            line += "   roles: " + ", ".join(names)
            rings.append((c, names))
        lines.append(line)
    lines += ["", "Verb parts in this schema: " + ", ".join(sorted(lex.verbs)), ""]
    if derived_types:
        lines += ["Derived types (a subtype whose population is a rule; use it like its supertype):"]
        for c in derived_types:
            sup = ", ".join(lex.concepts.get(s, {}).get("name", s) for s in c.get("supertypes", []))
            src = " ".join(rules.get(c["derivation"], {}).get("source", "").split())
            lines.append("  %-28s is a %s IFF %s" % (c["name"], sup, src))
        lines.append("")
    if model.get("macros"):
        lines += ["Macros (write name(args) where a %s goes; it stands for the body with the "
                  "arguments substituted):" % "/".join(sorted({m["kind"] for m in model["macros"]}))]
        for mc in model["macros"]:
            lines.append("  %-28s %s ::= %s" % ("%s(%s)" % (mc["name"], ", ".join(mc.get("parameters", []))),
                                                mc["kind"], " ".join(mc["source"].split())))
        lines.append("")
    if rings:
        c, names = rings[0]
        lines += ["A fact type whose roles are played by the same type is walked by role "
                  "name where the reading cannot say which role is meant: `has %s`, "
                  "`is of %s`. Its own reading walks it forward." % (names[0], names[-1]), ""]
    return "\n".join(lines)


# An empty result is the one thing a running query can say about itself that is worth
# saying. Measured across 3,162 recorded benchmark answers: of the 13 that returned no
# rows, 13 were wrong -- 100%, on 0.4% of answers. Every other row count is uninformative
# (the modal wrong answer returns exactly one row, 668 of 953), which is why this is the
# only such notice and not a family of them. Finding 128's rule: a caution that fires
# rarely and is right when it fires gets read; one that fires on most queries is wallpaper.
EMPTY = (
    "  No rows matched. That is nearly always a literal spelled differently from the data,\n"
    "  or a step that reaches nothing -- not a true \"none\". Try the query without its\n"
    "  filters, then add them back one at a time to see which one empties it. The schema\n"
    "  listing's value domains say how each code is spelled.")


def render_rows(cursor, limit=None):
    names = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    shown = rows[:limit] if limit else rows
    if not names:
        return "(no columns)"
    widths = [len(n) for n in names]
    for r in shown:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len("" if v is None else str(v)))
    out = ["  ".join(n.ljust(w) for n, w in zip(names, widths)),
           "  ".join("-" * w for w in widths)]
    for r in shown:
        out.append("  ".join(("" if v is None else str(v)).ljust(w)
                             for v, w in zip(r, widths)))
    tail = "\n(%d row%s)" % (len(rows), "" if len(rows) == 1 else "s")
    if limit and len(rows) > limit:
        tail = "\n(%d rows, first %d shown)" % (len(rows), limit)
    if not rows:
        tail += "\n" + EMPTY
    return "\n".join(out) + tail


def normalise(model, text, lexicon=None):
    """Text to the report's section 8 normal form: what the compiler understood, in ConQuer."""
    model, text, lexicon, defined = expand_definitions(model, text, lexicon)
    lexicon = lexicon or parser_mod.Lexicon(model)
    lower_mod.lower_rules(model, lexicon)
    parts = []
    for name in defined:
        # the rule's body, already lowered: the normal form has to carry the definitions or
        # it is not a query anyone could run
        rule = next(r for r in model["derivationRules"] if r["id"] == "rule." + name)
        parts.append("DEFINE %s ::= %s" % (name, norm_mod.to_conquer(rule["body"], lexicon)))
    ast = parser_mod.Parser(lexicon, text).parse_query()
    parts.append(norm_mod.to_conquer(lower_mod.lower(model, ast, lexicon), lexicon))
    return " ".join(parts)


def interpret(model, text, lexicon, as_json=False):
    """Return (rendered report, risk count), or (None, 0) if it will not parse."""
    # `explain` reads the query, `normalise` reads the whole thing: a definition is already
    # reported by the §6.11 machinery, as the rule it is, but the normal form has to carry it
    extended, body, lex, _ = expand_definitions(model, text, lexicon)
    interp = verb_mod.explain(extended, body, lex or lexicon)
    interp.query = text
    try:
        interp.normalised = normalise(model, text, lexicon)
    except (parser_mod.ParseError, sql_mod.SqlError):
        pass                        # the English still stands; the risks say why it fails
    if as_json:
        return json.dumps(interp.as_dict(), indent=2), len(interp.risks)
    return verb_mod.render(interp), len(interp.risks)


def run_one(model, conn, text, show_sql=False, sql_only=False, show_ccm=False, limit=None,
            lexicon=None, emitter=None, explain=False, check=False, strict=False,
            as_json=False, normalise_only=False, permissive=False):
    if normalise_only:
        try:
            print(normalise(model, text, lexicon))
            return 0
        except parser_mod.ParseError as e:
            print("parse error: %s" % e)
            return 1
        except sql_mod.SqlError as e:
            print("cannot compile: %s" % e)
            return 1
    if explain or check:
        try:
            report, risks = interpret(model, text, lexicon, as_json)
        except parser_mod.ParseError as e:
            print("parse error: %s" % e)
            return 1
        print(report)
        if explain:
            return 0
        if strict and risks:
            print("\n  not run: %d risk%s above. Re-read them, or drop --strict to run anyway."
                  % (risks, "" if risks == 1 else "s"))
            return 1
        print("")

    try:
        block, statement, params = transpile(model, text, lexicon, emitter, permissive)
    except parser_mod.Ambiguous as e:
        print("ambiguous: %s" % e)
        return 1
    except parser_mod.ParseError as e:
        print("parse error: %s" % e)
        return 1
    except sql_mod.SqlError as e:
        print("cannot compile: %s" % e)
        return 1

    for note in block.get("_suppressed", []):
        print("  suppressed (--permissive): %s" % note)
    if show_ccm:
        printable = json.loads(json.dumps(block, default=str))
        print(json.dumps(printable, indent=2))
    if show_sql or sql_only:
        print(statement + (";" if sql_only else ""))
        if params:
            print("-- parameters: %r" % (params,))
    if sql_only:
        return 0
    if conn is None:
        print("(no --db given, so nothing was executed)")
        return 0
    try:
        cur = conn.execute(statement, params)
    except DB_ERRORS as e:
        print("SQL error: %s\n  %s" % (e, statement))
        return 1
    print(render_rows(cur, limit))
    return 0


def repl(model, conn, args, lexicon=None, emitter=None):
    print("ConQuer-92. Type a query, or \\schema, \\explain <query>, \\normalise <query>, "
          "\\sql|\\ccm|\\check|\\strict on|off, \\q.")
    show_sql, show_ccm = args.show_sql, args.show_ccm
    check, strict = args.check, args.strict
    while True:
        try:
            line = input("cq> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("\\q", "\\quit", "quit", "exit"):
            return 0
        if line == "\\schema":
            print(describe(model))
            continue
        if line.startswith("\\sql"):
            show_sql = not line.endswith("off")
            print("sql %s" % ("on" if show_sql else "off"))
            continue
        if line.startswith("\\ccm"):
            show_ccm = not line.endswith("off")
            print("ccm %s" % ("on" if show_ccm else "off"))
            continue
        if line.startswith("\\check"):
            check = not line.endswith("off")
            print("check %s" % ("on" if check else "off"))
            continue
        if line.startswith("\\strict"):
            strict = not line.endswith("off")
            print("strict %s" % ("on" if strict else "off"))
            continue
        if line.startswith("\\explain "):
            print(interpret(model, line[9:].strip(), lexicon)[0])
            continue
        if line.startswith("\\normalise "):
            run_one(model, conn, line[11:].strip(), lexicon=lexicon, normalise_only=True)
            continue
        run_one(model, conn, line, show_sql, False, show_ccm, args.limit, lexicon, emitter, args.explain)


def check_constraints(model, conn, lexicon=None, emitter=None, limit=5, verbose=False):
    """Run every constraint that carries a `violation` query. Returns the number that fail.

    A constraint's `violation` is ConQuer whose result must be empty: the rows it returns are
    the counter-examples. One text serves both questions, which is the shape Rel's integrity
    constraints use -- `ic X() requires ...` asks whether it holds, `ic X(x) requires ...`
    hands back the x that break it (Aref et al., arXiv:2504.10323 §3.5). Here emptiness is the
    first question and the rows are the second, so nothing has to be written twice.

    This is the half of report §1 that was missing. The report claims the language serves "the
    specification of derivation rules and constraints"; derivation rules carry their ConQuer in
    `source` and have since the beginning, and a constraint had nowhere to put any.
    """
    lexicon = lexicon or parser_mod.Lexicon(model)
    emitter = emitter or (sql_mod.Emitter(model) if model.get("mapping") else None)
    checks = [c for c in model.get("constraints", []) if c.get("violation")]
    if not checks:
        print("no constraint in this model carries a `violation` query")
        return 0
    failed = 0
    for c in checks:
        name = c.get("name") or c["id"]
        try:
            _, statement, params = transpile(model, c["violation"], lexicon, emitter)
        except Exception as e:                                        # noqa: BLE001
            failed += 1
            print("BROKEN  %-28s %s: %s" % (name, type(e).__name__, str(e)[:90]))
            continue
        if conn is None:
            print("        %-28s compiles; give --db to run it" % name)
            continue
        try:
            rows = conn.execute(statement, params).fetchmany(limit + 1)
        except DB_ERRORS as e:
            failed += 1
            print("BROKEN  %-28s database: %s" % (name, str(e)[:90]))
            continue
        if not rows:
            print("holds   %-28s %s" % (name, c["violation"][:70] if verbose else ""))
            continue
        failed += 1
        more = " (and more)" if len(rows) > limit else ""
        print("FAILS   %-28s %d counter-example%s%s" % (name, min(len(rows), limit),
                                                        "" if len(rows) == 1 else "s", more))
        for r in rows[:limit]:
            print("            %s" % (", ".join("%s" % v for v in r))[:100])
    print("\n%d of %d constraint%s violated by this population"
          % (failed, len(checks), "" if len(checks) == 1 else "s"))
    return failed


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model", nargs="?", help="a .ccm.json model with a relational mapping")
    p.add_argument("query", nargs="*", help="ConQuer-92 query text")
    p.add_argument("--db", help="SQLite database to run against")
    p.add_argument("--dsn", help="a PostgreSQL URL to run against instead of --db "
                                 "(read-only, two-minute statement limit; needs psycopg)")
    p.add_argument("-f", "--file", help="read queries from a file, one per non-blank line "
                                        "(# starts a comment)")
    p.add_argument("--sql-only", action="store_true", help="print SQL, do not execute")
    p.add_argument("--show-sql", action="store_true", help="print SQL as well as rows")
    p.add_argument("--show-ccm", action="store_true", help="print the lowered CCM block")
    p.add_argument("--explain", action="store_true",
                   help="read the query back in English and report how it was interpreted, "
                        "without running it")
    p.add_argument("--permissive", action="store_true",
                   help="do not refuse what is merely meaningless: emit the SQL anyway and "
                        "print what would have been said. The instrument for measuring "
                        "whether refusing helps -- run the SQL a refusal prevented and see "
                        "whether it was the right answer. Never a good idea in earnest.")
    p.add_argument("--normalise", action="store_true",
                   help="print the query back in normalised ConQuer (report section 8): every "
                        "step explicit, every abbreviation expanded, every referenced thing "
                        "named -- what the compiler understood, in the language it was given")
    p.add_argument("--check", action="store_true",
                   help="print the interpretation, then run -- the check-then-run loop")
    p.add_argument("--strict", action="store_true",
                   help="with --check, refuse to run when the interpretation carries a risk: "
                        "a silently dropped optional fact, or an ambiguity resolved by taking "
                        "the first reading")
    p.add_argument("--json", action="store_true",
                   help="with --explain or --check, emit the interpretation as JSON")
    p.add_argument("--schema", action="store_true", help="describe what the schema allows")
    p.add_argument("--relational", action="store_true",
                   help="with --schema, say where each thing is stored -- table, column, "
                        "JSON field, foreign key -- for a reader who will write SQL")
    p.add_argument("--for", dest="about", metavar="QUESTION",
                   help="with --schema, show only the part of the model this question is "
                        "about. Schema linking is the largest single lever the text-to-SQL "
                        "leaderboards agree on, and a conceptual model is a better thing to "
                        "link against than a DDL: the readings are English and the value "
                        "domains are in the model")
    p.add_argument("--constraints", action="store_true",
                   help="run every constraint carrying a `violation` query -- ConQuer whose "
                        "result must be empty -- and report the counter-examples. Needs --db "
                        "to run them; without one it only checks that they compile")
    p.add_argument("--primer", action="store_true",
                   help="print the one-page language primer and the working method, which is "
                        "the whole prompt a writer needs beside `--schema --for QUESTION`. "
                        "In one session the method beat the base arm; the size did not "
                        "reproduce (docs/07-what-we-measured.md). Every example in the primer is "
                        "checked by conquer/tests/test_primer.py")
    p.add_argument("--repl", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    # parse_intermixed_args so options may follow the query text, which is the natural
    # order to type: conquer.py model.json "Employee has ..." --db x.sqlite --show-sql
    args = p.parse_intermixed_args(argv)

    if args.primer:
        here = os.path.dirname(os.path.abspath(__file__))
        for part in ("primer.md", "method.md"):
            with open(os.path.join(here, part)) as fh:
                print(fh.read().rstrip())
            print()
        return 0
    if not args.model:
        p.error("a model is required (or --primer, which needs none)")

    with open(args.model) as fh:
        model = json.load(fh)

    if args.schema:
        print(describe(model, args.about, relational=args.relational))
        return 0

    # Read-only, and read-only in the way that leaves the file alone: a plain connect()
    # opens for writing, and SQLite then puts the database into WAL mode and leaves a -wal
    # and a -shm beside it. On 15 Sep that turned a benchmark database into one that
    # `sqlite3 -readonly` could no longer open at all, and a writer in another arm spent
    # half its budget working out why. A query compiler has no business writing to the
    # database it is reading.
    conn = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True) if args.db else None
    if args.dsn:
        conn = _Server(args.dsn)
    if conn is not None:
        missing = unmapped_tables(model, conn)
        if missing:
            print("this model does not describe this database: %d of its tables are not here "
                  "(%s%s).\nA model is bound to one physical schema; check --db."
                  % (len(missing), ", ".join(missing[:4]),
                     ", ..." if len(missing) > 4 else ""), file=sys.stderr)
            return 2
    lexicon = parser_mod.Lexicon(model)
    emitter = sql_mod.Emitter(model) if model.get("mapping") else None
    try:
        if args.constraints:
            return 1 if check_constraints(model, conn, lexicon, emitter, args.limit,
                                          args.show_sql) else 0
        if args.repl:
            return repl(model, conn, args, lexicon, emitter)
        if args.file:
            failures = 0
            for raw in open(args.file):
                text = raw.split("#", 1)[0].strip()
                if not text:
                    continue
                print("\n\033[1m%s\033[0m" % text if sys.stdout.isatty() else "\n%s" % text)
                failures += run_one(model, conn, text, args.show_sql, args.sql_only,
                                    args.show_ccm, args.limit, lexicon, emitter,
                                    args.explain, args.check, args.strict, args.json,
                                    args.normalise, args.permissive)
            return 1 if failures else 0
        if not args.query:
            p.error("give a query, -f FILE, --repl or --schema")
        return run_one(model, conn, " ".join(args.query), args.show_sql, args.sql_only,
                       args.show_ccm, args.limit, lexicon, emitter,
                       args.explain, args.check, args.strict, args.json, args.normalise,
                       args.permissive)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
