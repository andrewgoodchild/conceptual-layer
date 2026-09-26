"""Emit SQL-92 from a Common Core Model query block.

This is model/binding-sql92.md. The mapping does the work: a node's value is
(alias, columns) under the RelationalMapping, so a step is a join only when the mapping
says the fact type lives in a different table from the node it came from.

Section 2 of that document is the part that matters here. An `enter` is at most one join;
an `exit` is never a join, it reads another column of the row already in hand; and when the
fact type is absorbed into the entity's own table -- which is what reverse-engineering rules
1 and 2 produce for every attribute -- neither step emits anything at all.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.ccm import Index                                            # noqa: E402


class SqlError(Exception):
    pass


class Frag:
    """SQL text and the parameters its placeholders bind, in the order they appear.

    Every renderer returns one. Composed with `+` (a str on either side is text with no
    parameters), so a fragment spliced into a clause other than the one it was rendered in
    carries its parameters with it -- which is the whole discipline. Parameters used to be
    sunk into one list per clause while the text was built elsewhere, and four silent
    wrong-answer defects were the two getting out of step: a window-filter wrap bound before
    the inner GROUP BY's parameters, a deferred expression bound before the projections',
    a computed value spliced into a clause it was not rendered in, and two expressions
    differing only in a parameter sharing one alias. Text order is parameter order here by
    construction; there is nothing left to remember.
    """
    __slots__ = ("text", "params")

    def __init__(self, text: str = "", params=()):
        self.text, self.params = text, list(params)

    @staticmethod
    def of(x) -> "Frag":
        return x if isinstance(x, Frag) else Frag(x)

    def __add__(self, other) -> "Frag":
        o = Frag.of(other)
        return Frag(self.text + o.text, self.params + o.params)

    def __radd__(self, other) -> "Frag":
        return Frag.of(other) + self

    @staticmethod
    def join(sep: str, parts) -> "Frag":
        out, first = Frag(), True
        for p in parts:
            out = out + (p if first else Frag(sep) + p)
            first = False
        return out

    @staticmethod
    def fmt(template: str, *parts) -> "Frag":
        """`template` with each `%s` replaced by the next part, parameters in text order."""
        pieces = template.split("%s")
        if len(pieces) != len(parts) + 1:
            raise SqlError("template %r takes %d part(s), given %d"
                           % (template, len(pieces) - 1, len(parts)))
        out = Frag(pieces[0])
        for piece, part in zip(pieces[1:], parts):
            out = out + part + piece
        return out

    @staticmethod
    def placeholders(template: str, parts) -> "Frag":
        """A `{0} {1}` template over parts, each part's parameters laid down once per
        placeholder in the order the placeholders appear -- SQLite's standard deviation
        names its argument six times, and `days_between` tests its date three times."""
        texts = [Frag.of(p).text for p in parts]
        params: list = []
        for m in re.finditer(r"\{(\d+)\}", template):
            i = int(m.group(1))
            if i < len(parts):
                params.extend(Frag.of(parts[i]).params)
        return Frag(template.format(*texts), params)

    def __eq__(self, other) -> bool:
        o = Frag.of(other) if isinstance(other, (Frag, str)) else None
        return o is not None and self.text == o.text and self.params == o.params

    def __hash__(self) -> int:
        return hash((self.text, tuple(map(str, self.params))))

    def __repr__(self) -> str:
        return "Frag(%r, %r)" % (self.text, self.params)


class Anchor:
    """Where a node's value lives: an alias and the column references in it.

    A reference is a *template* with `{0}` where the alias goes, not a bare column name.
    For nearly every column that is `{0}."city"` and the distinction does not show. It
    exists for the columns that are not a column: a value that lives at a path inside a
    JSON document renders as `json_extract({0}."meta", '$.location.city')`, and nothing
    downstream -- joins, equality, IS NOT NULL, projection -- needs to know the difference.
    """

    def __init__(self, alias: Optional[str], columns: List[str], table: Optional[str] = None,
                 references: Optional[List[str]] = None, enforced: bool = False,
                 translate: Optional[Dict[str, str]] = None):
        self.alias, self.columns, self.table = alias, columns, table
        # When this anchor holds a foreign key that points at something other than the
        # target's identifier, `references` names the columns over there that it matches.
        self.references = references
        # The mapping says every value this anchor holds is present in the table it points
        # at (`enforced` in the roleMap). Two joins become unnecessary when it does: the one
        # that checks the instance exists, and the one that would fetch back a value already
        # in hand. Never assumed -- absent, this is False and the compiler joins.
        self.enforced = enforced
        # Set when the fact type this anchor stands for was absorbed across such a
        # reference: the far column each of its roles maps to, against the template that
        # reads the same value on the near side. `{c.department.dept_code:
        # '{0}."dept_code"'}` with the alias of `employee`.
        self.translate = translate or {}

    def refs(self) -> List[str]:
        return [c.format(self.alias) for c in self.columns] if self.alias else []

    def scalar(self) -> str:
        r = self.refs()
        if len(r) != 1:
            raise SqlError("expected a single column, got %d" % len(r))
        return r[0]


class _ScalarAnchor(Anchor):
    """A node whose value is a scalar subquery (an aggregate), not a column."""

    def __init__(self, ctx, calc_id: str):
        super().__init__(None, [])
        self.ctx, self.calc_id = ctx, calc_id

    def scalar(self) -> Frag:
        return self.ctx.use_calc(self.calc_id)



# What the model calls text, and the functions that make it (a document read hands back
# text on every engine). Arithmetic over either is meant "as a number": SQLite converts on
# the quiet, PostgreSQL and DuckDB refuse `text - text`, and a writer who did not know a
# date was kept as text should not have to know either. The emitter casts what the model
# says is text; a literal never is.
TEXT_TYPES = {"text", "character", "character varying", "varchar", "char", "nchar",
              "nvarchar", "string", "clob"}
TEXT_RESULT = {"fn.substr", "fn.trim", "fn.ltrim", "fn.rtrim", "fn.lower", "fn.upper",
               "fn.concat", "fn.replace", "fn.jsonPath", "fn.join"}
NUMERIC_TYPES = {"integer", "bigint", "smallint", "int", "real", "double", "double precision",
                 "float", "numeric", "decimal"}
NUMERIC_ARGS = {"fn.add", "fn.subtract", "fn.multiply", "fn.divide", "fn.div", "fn.negate",
                "fn.abs", "fn.round", "fn.sqrt", "fn.power", "fn.exp", "fn.ln", "fn.log10"}
NUMERIC_AGGREGATES = {"fn.sum", "fn.avg", "fn.stddev", "fn.variance", "fn.median"}

_AGG_CALL = re.compile(r"\b(SUM|COUNT|AVG|MIN|MAX|TOTAL)\s*\(")


def distribute_over(sql: Frag, window: Frag) -> Frag:
    """Append `window` to every aggregate call in `sql`, innermost text left alone.

    For a dialect that spells an aggregate as an expression over other aggregates -- SQLite's
    standard deviation is SUM and COUNT -- the window form is each of those windowed, not the
    whole expression windowed. Parentheses are matched rather than counted so an argument
    carrying its own calls (`SUM(CAST(x AS REAL) * x)`) closes in the right place. The
    window's parameters go down once per insertion, which the old one-list-per-clause
    binding could not do: `WITHIN 1` on a SQLite standard deviation bound its constant
    once and inserted it six times.
    """
    sql, window = Frag.of(sql), Frag.of(window)
    text, params = sql.text, list(sql.params)
    out, i = Frag(), 0

    def segment(a, b):
        """The text between two cuts, with the parameters its placeholders bind."""
        piece = text[a:b]
        n = piece.count("?")
        taken, params[:n] = params[:n], []
        return Frag(piece, taken)

    while True:
        m = _AGG_CALL.search(text, i)
        if m is None:
            return out + segment(i, len(text))
        depth, j = 0, m.end() - 1
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out = out + segment(i, j + 1) + window
        i = j + 1


class Emitter:
    def __init__(self, model: dict, index=None):
        self.model = model
        mapping = model.get("mapping")
        if not mapping:
            raise SqlError(
                "this model carries no relational mapping, so there is nothing to query. "
                "model/model.md §6: reverse engineer the database, or add a mapping by hand.")
        self.tables = {t["id"]: t for t in mapping["tables"]}
        self.columns = {c["id"]: c for c in mapping["columns"]}
        self.concept_map = {m["concept"]: m for m in mapping["conceptMap"]}
        self.role_map = {m["role"]: m for m in mapping["roleMap"]}
        self.functions = {f["id"]: f for f in model.get("functions", [])}
        ix = index or Index(model)
        self.roles, self.role_owner = ix.roles, ix.role_owner
        self.concepts_by_id = ix.concepts
        self.is_functional = ix.is_functional
        self.alias_n = 0
        # Section 6.11: a derived concept has no table of its own; its population is a query.
        # It gets a virtual table in the mapping, rendered as a common table expression when
        # a statement touches it. Recursive when the rule mentions its own target.
        self.rules = {r["id"]: r for r in model.get("derivationRules", [])}
        self.derived: Dict[str, dict] = {}         # virtual table id -> rule
        self._ctes: Dict[str, tuple] = {}          # built for the statement in hand
        self._building: set = set()
        self._depth = 0
        self._contexts: List["Context"] = []       # the blocks being emitted, outermost first
        concepts = {c["id"]: c for c in model.get("concepts", [])}
        for c in concepts.values():
            self._virtual_table(c, concepts)

    def _identity_width(self, cid: str, concepts: dict) -> int:
        """How many columns identify an instance of `cid`. A derived subtype inherits its
        supertype's identifier -- Laboratory's (Patient, Date) as much as Patient's ID -- so
        its virtual table needs that many columns, or every join to it fails."""
        entry = self.concept_map.get(cid)
        if entry is not None:
            return len(entry["identifyingColumns"])
        c = concepts.get(cid, {})
        if c.get("derivation") in self.rules:
            self._virtual_table(c, concepts)          # a supertype that is itself derived
            return len(self.concept_map[cid]["identifyingColumns"])
        for s in c.get("supertypes", []):
            return self._identity_width(s, concepts)
        return 1

    def _virtual_table(self, c: dict, concepts: dict):
        rule = self.rules.get(c.get("derivation") or "")
        tid = "v." + c["id"]
        if rule is None or tid in self.tables:
            return
        self.tables[tid] = {"id": tid, "name": c["name"], "derived": rule["id"]}
        self.derived[tid] = rule
        cols = []
        if c["kind"] == "fact":
            for r in c.get("roles", []):
                base = r.get("name") or r["id"].split(".")[-1]
                width = self._identity_width(r["player"], concepts)
                mine = []
                for i in range(width):
                    cid = "%s.%s%s" % (tid, r["id"].split(".")[-1], "" if i == 0 else i + 1)
                    self.columns[cid] = {"id": cid, "table": tid, "nullable": False,
                                         "name": base if i == 0 else "%s_%d" % (base, i + 1)}
                    mine.append(cid)
                self.role_map[r["id"]] = {"role": r["id"], "table": tid, "columns": mine}
                cols += mine
        else:
            width = max(self._identity_width(s, concepts) for s in c.get("supertypes", [])) \
                if c.get("supertypes") else 1
            for i in range(width):
                cid = tid + (".id" if i == 0 else ".id%d" % (i + 1))
                self.columns[cid] = {"id": cid, "table": tid, "nullable": False,
                                     "name": "id" if i == 0 else "id_%d" % (i + 1)}
                cols.append(cid)
            # The CTE is a filter on the supertype's table, not a table of its own: a node
            # of the subtype is anchored at the supertype's row and semijoined to the CTE, so
            # every absorbed fact and every foreign key of the supertype -- including one
            # that references a column other than the identifier (finding 34) -- applies.
            for sup in c.get("supertypes", []):
                entry = self.concept_map.get(sup)
                if entry is None:
                    continue
                st = self.tables.get(entry["table"], {})
                self.tables[tid]["base"] = st.get("base") or entry["table"]
                self.tables[tid]["baseColumns"] = st.get("baseColumns") \
                    or list(entry["identifyingColumns"])
                break
        self.concept_map[c["id"]] = {"concept": c["id"], "table": tid,
                                     "identifyingColumns": cols}

    # -- naming ------------------------------------------------------------

    # SQL-92 had no way to return a nested relation, which is the reason ConQuer-92 gives
    # for flattening LISA-D's confluence (§6.5). SQLite does: json_group_array gathers a
    # column into one JSON array per group. `fn.list` is that group function, and it is
    # named here rather than in the model's function library so a model built before it
    # existed can still be queried.
    AGGREGATE_SQL = {"fn.list": "json_group_array"}

    def aggregate_sql(self, fid: str, spec, src, distinct: bool, extra=()) -> Frag:
        """One aggregate call, honouring the dialect's spelling.

        `aggregate_name` gives the function's name; a few aggregates are not a name applied to
        an argument at all. PostgreSQL's median is
        `percentile_cont(0.5) WITHIN GROUP (ORDER BY x)`, and rendering it as `MEDIAN(x)`
        produced SQL PostgreSQL does not have -- the template existed in the model and nothing
        read it, because only scalar functions went through `render_call`.

        `extra` is the rendered second operand of the two aggregates that take one: the
        separator of a join, the key of an object. `{1}` in a template, or the second
        argument of the call.
        """
        template = (spec or {}).get("sqlTemplate")
        if template and distinct:
            # A template is an expression over several aggregates, and DISTINCT belongs to
            # one call -- `SUM(DISTINCT x * x)` is not the distinct sum of squares. Falling
            # through to the name would have emitted STDDEV(DISTINCT x), which SQLite does
            # not have: the same silent-then-loud failure `aggregate_name` exists to stop.
            name = fid.split(".")[-1]
            raise SqlError(
                "this dialect has no distinct %s: it spells %s as an expression over SUM and "
                "COUNT, and DISTINCT belongs to a single aggregate call. Aggregate a bag "
                "that already yields each value once, or drop DISTINCT." % (name, name))
        if template:
            return Frag.placeholders(template, [src] + list(extra))
        return (Frag("%s(%s" % (self.aggregate_name(fid, spec), "DISTINCT " if distinct else ""))
                + Frag.join(", ", [Frag.of(src)] + [Frag.of(x) for x in extra]) + ")")

    def aggregate_name(self, fid: str, spec) -> str:
        if fid not in self.AGGREGATE_SQL and not spec:
            # An aggregate the model does not declare was being emitted as a bare SQL call on
            # the strength of its own name, so a model built for a dialect without `median`
            # still produced `MEDIAN(...)` and failed at the database. The model's function
            # table is what the model can say (model/model.md section 3); if it is not in
            # there, say so here rather than letting the engine say it later.
            name = fid.split(".")[-1]
            raise SqlError(
                "this model declares no %s, so it cannot be asked for one. A model's function "
                "table is built for its target dialect (model/model.md section 3), and %s is "
                "not in this one -- `median`, for instance, exists in DuckDB and PostgreSQL "
                "and not in SQLite, which has neither a median nor a percentile."
                % (name, name))
        return (self.AGGREGATE_SQL.get(fid)
                or (spec or {}).get("name") or fid.split(".")[-1]).upper()

    def alias(self, hint: str) -> str:
        # Aliases are generated, so strip anything needing quotes -- Northwind's
        # "Order Details" would otherwise produce the alias `order 1`.
        self.alias_n += 1
        clean = re.sub(r"[^A-Za-z0-9]", "", hint).lower()[:6]
        return "%s%d" % (clean or "t", self.alias_n)

    def table(self, tid: str) -> dict:
        """The one place a table id is resolved. A conceptMap or roleMap entry may name a
        table the mapping never declares; say so, rather than letting a bare KeyError out
        with nothing in it but an id."""
        t = self.tables.get(tid)
        if t is None:
            raise SqlError("the mapping refers to table %r, which it does not declare; the "
                           "model's conceptMap and tables disagree" % tid)
        return t

    def table_name(self, tid: str) -> str:
        t = self.table(tid)
        if t.get("derived"):
            self.require_cte(tid)
        name = _quote_ident(t["name"])
        return "%s.%s" % (_quote_ident(t["schema"]), name) if t.get("schema") else name

    def require_cte(self, tid: str):
        """Make sure the statement being built defines the derived table `tid`. A rule that
        reaches its own target while being built is recursive; the reference inside it is
        just the name, and the definition becomes WITH RECURSIVE."""
        if tid in self._ctes:
            return
        if tid in self._building:
            self._recursive.add(tid)
            return
        rule = self.derived[tid]
        body = rule.get("body")
        if body is None:
            raise SqlError("the derivation rule for %s has not been lowered; lower.lower_rules "
                           "(which conquer.transpile calls) turns its ConQuer into a body"
                           % self.tables[tid]["name"])
        self._building.add(tid)
        try:
            sql, params = self.emit(body, {})
        finally:
            self._building.discard(tid)
        cols = [self.columns[c]["name"] for c in self.concept_map_columns(tid)]
        self._ctes[tid] = (self.tables[tid]["name"], cols, sql, params)

    def unique_columns(self, cols: List[str]) -> bool:
        """Do these columns hold at most one row of their table?

        The mapping does not say so directly -- it records that a role's columns *reference*
        some other columns, never that the columns referenced are unique. The model does say
        so, one level up: a single-role uniqueness constraint over the role those columns map
        says each value fills the role at most once, which for an absorbed fact type is one
        row. `is_functional` is that question already asked and cached.

        It matters because alias reuse is gated on the join being functional. A foreign key
        aimed at a unique column that is not the primary key -- 32 of BIRD's 105 declared
        keys -- was failing that gate and emitting one join per value read: three joins to
        `cards` on `cards.uuid` where one does (finding 135).
        """
        want = list(cols)
        if not want:
            return False
        for m in self.role_map.values():
            if list(m["columns"]) == want and self.is_functional(m["role"]):
                return True
        return False

    def concept_map_columns(self, tid: str) -> List[str]:
        for m in self.concept_map.values():
            if m["table"] == tid:
                return list(m["identifyingColumns"])
        return []

    def col_refs(self, ids: List[str]) -> List[str]:
        """The SQL for each column, as a template with `{0}` for the table alias.

        Every reference in the emitted statement comes through here, which is why a column
        that is really a path into a document costs nothing anywhere else.
        """
        missing = [i for i in ids if i not in self.columns]
        if missing:
            raise SqlError("the mapping refers to column(s) %s, which it does not declare"
                           % ", ".join(repr(i) for i in missing))
        return [self.col_ref(self.columns[i]) for i in ids]

    def col_ref(self, col: dict) -> str:
        """One column's reference template.

        A mapping column this emitter does not fully understand is refused rather than
        approximated. Emitting the base column for a mapping that asked for something else
        is the failure this project exists to prevent: it does not error, it answers.
        """
        unknown = set(col) - _COLUMN_FIELDS
        if unknown:
            raise SqlError(
                "the mapping column %r carries %s, which this emitter does not understand. "
                "Emitting the bare column instead would answer the wrong question silently."
                % (col.get("id"), ", ".join(repr(u) for u in sorted(unknown))))
        path = col.get("path")
        if not path:
            return '{0}.%s' % _quote_ident(col["name"])
        # Build against a sentinel, then escape every brace the dialect's own SQL contains
        # before putting the alias slot back. PostgreSQL's path read ends `#>> '{}'`, and an
        # unescaped `{}` there is automatic field numbering beside the alias's `{0}` --
        # str.format refuses to mix them, so the dialect would have failed on its first query.
        expr = self.json_path(_ALIAS + "." + _quote_ident(col["name"]),
                              path, col.get("dataType") or {}, col.get("id"))
        return expr.replace("{", "{{").replace("}", "}}").replace(_ALIAS, "{0}")

    def json_path(self, base: str, path: List[str], datatype: dict, cid) -> str:
        """`fn.jsonPath` applied to a column, cast to the type the mapping declares.

        The spelling is the dialect's and so belongs in the model (model/model.md section 3),
        the same seam that carries `divide`. The cast is not optional: SQLite's json_extract
        preserves storage class but DuckDB and PostgreSQL hand back text, so an uncast
        latitude compares as a string and sorts 9 above 41.
        """
        spec = self.functions.get("fn.jsonPath")
        if spec is None or not spec.get("sqlTemplate"):
            raise SqlError(
                "the mapping column %r reads a path inside a document, but the model declares "
                "no `fn.jsonPath` to spell that in SQL. Reverse engineering writes one; a "
                "hand-written model has to carry it too (model/model.md section 3)." % cid)
        bad = [k for k in path if _JSON_UNSAFE.search(str(k))]
        if bad:
            raise SqlError(
                "the mapping column %r has path step(s) %s carrying a quote or a backslash, "
                "which cannot be spelled in a JSONPath literal" % (
                    cid, ", ".join(repr(b) for b in bad)))
        steps = "".join(("." + k) if _JSON_BARE.match(k) else '."%s"' % k
                        for k in (str(x) for x in path))
        # The template takes an *expression* for the path, because the other caller --
        # a user writing `jsonPath(doc, '$.x')` -- reaches it through `render_call`, which
        # has already rendered its argument to a bind marker. A template that quoted the
        # placeholder produced `json_extract(col, '?')`: a literal question mark, and a
        # parameter left over, so every user-written jsonPath failed to run. Rule 12 builds
        # its path here rather than in the query, so it supplies the quotes itself.
        expr = spec["sqlTemplate"].format(base, "'$%s'" % steps)
        cast = self.functions.get(_JSON_CAST.get((datatype.get("name") or "").casefold(), ""))
        return cast["sqlTemplate"].format(expr) if cast and cast.get("sqlTemplate") else expr

    # -- the main entry ----------------------------------------------------

    def emit(self, block: dict, outer: Optional[Dict[str, Anchor]] = None) -> Tuple[str, list]:
        """Emit a QueryExpr. The outermost call owns the statement: it collects the derived
        tables the statement touched and prefixes their definitions as a WITH clause, in the
        order they finished building, which is dependency order."""
        top = self._depth == 0
        if top:
            self._ctes, self._recursive = {}, set()
        self._depth += 1
        try:
            if block.get("nodeType") == "setExpr":
                sql, params = self.emit_setexpr(block, outer or {})
            else:
                ctx = Context(self, outer or {})
                self._contexts.append(ctx)
                try:
                    ctx.build(block)
                    sql, params = ctx.render(block)
                finally:
                    self._contexts.pop()
        finally:
            self._depth -= 1
        if top and self._ctes:
            defs, front = [], []
            for tid, (name, cols, csql, cparams) in self._ctes.items():
                defs.append("%s(%s) AS (%s)" % (_quote_ident(name),
                                                ", ".join(_quote_ident(c) for c in cols), csql))
                front.extend(cparams)
            sql = "WITH %s%s %s" % ("RECURSIVE " if self._recursive else "",
                                    ", ".join(defs), sql)
            params = front + params
        return sql, params

    def emit_decorrelated(self, block: dict, outer: Dict[str, Anchor]):
        """Emit an aggregate block as a grouped derived table over its correlation columns.
        Returns (sql, params, [(inner ref, outer ref)]) or None when the block is not
        correlated by equalities alone -- then the correlated subquery is the right form."""
        self._depth += 1
        try:
            ctx = Context(self, outer)
            ctx.decorrelate = True
            self._contexts.append(ctx)
            try:
                ctx.build(block)
                sql, params = ctx.render(block)
            finally:
                self._contexts.pop()
        except SqlError:
            return None
        finally:
            self._depth -= 1
        if not ctx.corr:
            return None
        # any other mention of an enclosing alias is a correlation the join cannot carry
        for alias in ctx.outer_aliases:
            if re.search(r'\b%s\."' % re.escape(alias), sql):
                return None
        return sql, params, ctx.corr

    SET_SQL = {"union": "UNION", "intersect": "INTERSECT", "except": "EXCEPT"}

    def emit_setexpr(self, expr: dict, outer: Dict[str, Anchor]) -> Tuple[str, list]:
        """A SetExpr as a compound SELECT. SQLite takes no parentheses around an operand
        and no ORDER BY or LIMIT inside one, so an operand that carries either -- a nested
        set expression, or a `(LIST ... THE FIRST n)` -- becomes a derived table."""
        parts, params = [], []
        for op in expr["operands"]:
            sql, p = self.emit(op, outer)
            if op.get("nodeType") == "setExpr" or op.get("_limit") or op.get("_ordering"):
                sql = "SELECT * FROM (%s)" % sql
            parts.append(sql)
            params.extend(p)
        word = self.SET_SQL[expr["op"]] + (" ALL" if expr.get("all") else "")
        sql = (" %s " % word).join(parts)
        ordering = expr.get("_ordering") or []
        if ordering:
            sql += " ORDER BY " + ", ".join("%s %s" % (_quote_ident(n), d.upper())
                                            for n, d in ordering)
        limit = expr.get("_limit")
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit["count"])
            if limit.get("offset"):
                sql += " OFFSET ?"
                params.append(limit["offset"])
        return sql, params


class Context:
    def __init__(self, em: Emitter, outer: Dict[str, Anchor]):
        self.em = em
        self.anchors: Dict[str, Anchor] = dict(outer)
        self.froms: List[str] = []
        # Every clause is a list of fragments (a plain str is a fragment with no parameters);
        # the statement is assembled from them in clause order at the end, and that is
        # where the parameters fall into place.
        self.joins: List[Tuple[str, object, object]] = []  # (kind, table AS alias, condition)
        self.where: List[object] = []
        # `WITHIN` conditions cannot sit in WHERE -- SQL evaluates windows after it -- so they
        # are deferred to a query wrapped around this one, exactly as `THE FIRST n PER` does.
        self.window_calcs: Dict[str, str] = {}      # calc id -> the alias it is selected as
        self.window_where: List[object] = []
        # While a deferred condition is being rendered, every ordinary value in it is selected
        # by the inner query under an alias too: the wrapping query cannot see inner columns,
        # only what the subquery returns. None when not deferring.
        # Keyed on the fragment -- expression AND parameters: `(nn + ?) / ?` bound [1, 2]
        # and the same text bound [2, 2] are two different values, and keying on the text
        # alone gave both the one alias -- `rk = "__c0" OR rk = "__c0"` -- so a median built
        # as "rank n/2 or rank n/2 + 1" silently returned half its rows (an alien writer).
        self._defer: Dict[Frag, str] = {}           # inner expression -> its alias
        self._deferring = False                     # true only while one is being rendered
        # Decorrelation (finding 15). An aggregate correlated to the enclosing row by an
        # equality -- `THE COUNT OF Post [has owner User: !u]` -- is a scalar subquery
        # re-run per outer row, which on a column with no index is (outer × inner) work:
        # two minutes and more on codebase_community. In `decorrelate` mode the context
        # records each (inner column, outer column) equality instead of emitting it, and
        # the caller turns the block into a grouped derived table joined on those columns.
        self.outer_aliases: set = {a.alias for a in outer.values() if a.alias}
        self.decorrelate = False
        # The top block of a derived table's body: its entity columns must be identifiers
        # (`identity_of`). A sub-block inside it arrives with outer anchors and is not.
        self.identity_out = bool(em._building) and not outer
        self.corr: List[Tuple[str, str]] = []      # (inner ref, outer ref)
        self.concept: Dict[str, str] = {}
        self.calc_sql: Dict[str, Frag] = {}
        self.optional: set = set()      # fact nodes reached by an outer join
        self.join_keys: Dict[tuple, str] = {}   # functional join -> the alias already joined
        self.groups: List[object] = []  # GROUP BY terms from in-place aggregates
        self.having: List[object] = []  # conditions over those aggregates
        self.grouped_calcs: set = set()  # calculation ids rendered in place, not as subqueries

    # -- construction ------------------------------------------------------

    def build(self, block: dict):
        for n in block.get("nodes", []):
            self.concept[n["id"]] = n["concept"]

        union = UnionFind()
        for u in block.get("unifications", []):
            for other in u["nodes"][1:]:
                union.join(u["nodes"][0], other)

        for s in block.get("steps", []):
            self.step(s, union)

        # Unified nodes are one instance. Usually that is one row, and a node reached by
        # no step borrows the row of one that was (narrowed by its CTE when it is a derived
        # subtype of it). A subtype with a table of its own keeps its own anchor and is
        # joined on identity below, so that naming it narrows the instance to that
        # population.
        for nid in self.concept:
            if nid not in self.anchors:
                self.borrow(nid, union, own_table=False)

        reached = {s["to"] for s in block.get("steps", [])}
        for nid, c in self.concept.items():
            if nid in self.anchors:
                continue
            entry = self.em.concept_map.get(c)
            if entry is None:
                if nid not in reached:
                    # A value type named with no path -- `THE AVERAGE EmployeeSalary`. It has
                    # no table of its own, but the fact type that carries it does.
                    self.anchors[nid] = self.anchor_value(c)
                continue                                  # a value node reached only by exit
            self.anchors[nid] = self.anchor_new(entry)
            # the root keeps the anchor it has, so a subtype's own table is equated to it
            self.anchors.setdefault(union.find(nid), self.anchors[nid])

        for u in block.get("unifications", []):
            present = [self.anchors[n] for n in u["nodes"] if n in self.anchors]
            for other in present[1:]:
                self.equate(present[0], other)

        for n in block.get("nodes", []):
            if n.get("restriction") and n["id"] in self.anchors:
                self.where.extend(self.restrict(self.anchors[n["id"]], n["restriction"]))

        # Calculations first: a condition may name one.
        self.calc_by_id = {c["id"]: c for c in block.get("calculations", [])}
        for calc in block.get("calculations", []):
            self.calculation(calc, block)

        for cond in block.get("conditions", []):
            # binding-sql92.md §4: a condition over an aggregate grouped in this block belongs
            # in HAVING, not WHERE -- SQL rejects an aggregate in WHERE outright. Decided by
            # comparing what the condition names against this block's grouping, never by
            # syntax.
            #
            # A conjunction is split first, so `c > 400 AND substr(name,1,9) = 'X'` puts only
            # the aggregate half in HAVING. Sending the whole thing there is not an error SQL
            # reports: a bare column in HAVING is evaluated against an arbitrary row of each
            # group, so the query returns confidently wrong rows.
            for part in self._conjuncts(cond):
                if self._names_window(part):
                    # Rendered against the *alias*, because in the wrapping query the inner
                    # columns the window was computed from are no longer in scope.
                    saved = {cid: self.calc_sql[cid] for cid in self.window_calcs
                             if cid in self.calc_sql}
                    for cid, alias in self.window_calcs.items():
                        self.calc_sql[cid] = Frag(alias)
                    self._deferring = True
                    try:
                        self.window_where.append(self.condition(part))
                    finally:
                        self._deferring = False
                    self.calc_sql.update(saved)
                    continue
                grouped = self._names_grouped(part)
                (self.having if grouped else self.where).append(self.condition(part))

        # Each sub-block carries the FrSetOper that attached it, folded left to match the
        # grammar's associativity. Ignoring it and always ANDing turned OR OTHERWISE into
        # AND ALSO -- silently, and with the opposite answer.
        expr = None
        for sub in block.get("subBlocks", []):
            term = self.exists(sub, negated=sub.get("negated", False))
            expr = term if expr is None else \
                Frag.fmt("(%s " + ("OR" if sub.get("_frOp") == "or" else "AND") + " %s)",
                         expr, term)
        if expr is not None:
            self.where.append(expr)

    def step(self, s, union):
        rmap = self.em.role_map.get(s["role"])
        if rmap is None:
            raise SqlError("role %s has no relational mapping" % s["role"])
        target_table = rmap["table"]
        cols = self.em.col_refs(rmap["columns"])

        if s["kind"] == "enter":
            src = self.value_head(s, union) or self.anchor_for(s["from"], union)

            fact_entry = self.em.concept_map.get(self.em.role_owner[s["role"]])
            identity = self.em.col_refs(fact_entry["identifyingColumns"]) \
                if fact_entry else cols

            # A foreign key may point at a column that is not the target's identifier, and
            # then neither side of the join is what it looks like. Two directions:
            #
            #   forward   `Legality has Card has CardId`. The value in hand came from
            #             `legalities.uuid`, which references `cards.uuid`; entering
            #             `Card has CardId` is mapped to `cards.id`. Join on `cards.uuid`.
            #   inverse   `Card is of Legality`. The value in hand is `cards.id`, the
            #             identifier; the role being entered is `legalities.uuid`, which
            #             references `cards.uuid`. Join to `cards.uuid`, not `cards.id`.
            #
            # Either way the referenced columns replace an identifier on one side. Get it
            # wrong and the join matches nothing, or matches the wrong rows and says nothing.
            join_cols, src_refs = cols, src.refs()
            far_ids = rmap["columns"]           # which far columns the join stands on
            far = self.em.col_refs(src.references) if src.references else None
            # The referenced columns replace the target's identifier only when they ARE
            # columns of the target. `Fund is of AnnualReturn` carries a reference to
            # `funds.tickersym`, and the table being entered is `annual_returns`: substituting
            # there emitted `annual2."tickersym" = annual1."portfolioref"` -- a join on a
            # column of the wrong table, which fails at SQL level. The inverse guard on `near`
            # below has always had this check; this side did not.
            if far and len(far) == len(src.columns) \
                    and self.em.columns[src.references[0]]["table"] == target_table:
                join_cols, far_ids = far, src.references
            near = self.em.col_refs(rmap["references"]) if rmap.get("references") else None
            if near and src.alias and len(near) == len(cols) \
                    and self.em.columns[rmap["references"][0]]["table"] == src.table:
                src_refs = [c.format(src.alias) for c in near]

            if self.absorbs_reference(s, src, cols, identity, rmap, fact_entry):
                # Absorbed across the reference. The join would have fetched back a value
                # the near side is already standing on -- `Employee has Department has
                # DepartmentCode` joins `department` to read `dept_code`, which IS the
                # column the employee row points with. Malloy drops that join; what lets
                # this one drop it is the mapping saying the reference holds over every
                # row, so the join it replaces could never have removed one either.
                self.anchors[s["to"]] = Anchor(
                    src.alias, list(src.columns), src.table,
                    translate=dict(zip(rmap["columns"], src.columns)))
            elif src.table == target_table and src.columns == join_cols \
                    and join_cols == identity:
                # Absorbed: the fact type lives in the entity's own table (binding-sql92 §2),
                # and the value in hand identifies the very instance being entered.
                #
                # That last clause is not decoration. `Employee has Department is of Employee`
                # stands on `employee.dept_code` and enters the same fact type by its
                # *department* role, which is also `employee.dept_code` -- same table, same
                # columns, so this read as absorbed and returned the row already in hand.
                # Every such round trip silently paired each row with itself: six rows where
                # the colleague pairs are fourteen, from a well-formed query. Three blind
                # benchmark writers hit it on three different schemas (finding 101).
                #
                # Standing on the fact type's identifying columns means standing on its row.
                # Standing on any other column of it -- a foreign key, a value -- means the
                # instances that share that value, which is a join.
                self.anchors[s["to"]] = Anchor(src.alias, identity, target_table)
                if s.get("join") == "outer":
                    self.optional.add(s["to"])
            else:
                kind = "LEFT JOIN" if s.get("join") == "outer" else "JOIN"
                if s.get("join") == "outer":
                    self.optional.add(s["to"])
                # Two paths reaching the same fact from the same row -- `Satscore
                # [has FrpmDistrictName dn] has FrpmCharterFundingType ft` -- used to join
                # `frpm` twice under different aliases. Reuse the first join when the target
                # is reached by its own identifying columns, which makes the join functional:
                # at most one row matches, so a second copy adds nothing. Without that test
                # the join could fan out, and dropping a copy would change the multiset.
                # Reuse needs the join to be functional -- at most one row matches, so a
                # second copy adds nothing and dropping it cannot change the multiset. Its
                # own identifier says that, and so does any other unique column the
                # reference happens to aim at.
                functional = join_cols == identity or self.em.unique_columns(far_ids)
                key = ((kind, target_table, tuple(join_cols), tuple(src_refs))
                       if functional else None)
                alias = self.join_keys.get(key) if key is not None else None
                if alias is None:
                    alias = self.em.alias(self.em.table(target_table)["name"])
                    cond = " AND ".join("%s = %s" % (c.format(alias), ref)
                                        for c, ref in zip(join_cols, src_refs))
                    self.joins.append((kind, "%s AS %s" % (self.em.table_name(target_table),
                                                           alias), cond))
                    if key is not None:
                        self.join_keys[key] = alias
                self.anchors[s["to"]] = Anchor(alias, identity, target_table)
        else:
            fact = self.anchor_for(s["from"], union)
            if fact.translate:
                # The fact type was absorbed across an enforced reference (`absorbs_reference`
                # below), so its row was never visited: every column it maps is one the near
                # side already holds, under the near side's own name.
                cols = [fact.translate.get(cid, c) for cid, c in zip(rmap["columns"], cols)]
            # An exit is a column read in the row already in hand: never a join.
            anchor = Anchor(fact.alias, cols, fact.table, rmap.get("references"),
                            enforced=bool(rmap.get("enforced"))
                            and s["from"] not in self.optional)

            # ...but reading a role asserts the fact instance HAS that role filled. When the
            # fact type is absorbed into the entity's table, no join enforces that, so a NULL
            # foreign key would otherwise pass as though the fact existed. ConQuer's semantics
            # are total (binding-sql92.md section 6); SQL's are not.
            if s["from"] not in self.optional:
                for cid, ref in zip(rmap["columns"], cols):
                    col = self.em.columns.get(cid)
                    if col is None or not col.get("nullable", True):
                        continue
                    # An absorbed read lands on a column an earlier step already reached and
                    # already guarded, so the same term arrives twice.
                    term = "%s IS NOT NULL" % ref.format(fact.alias)
                    if term not in self.where:
                        self.where.append(term)
                self.referent_exists(s, anchor)
            anchor = self.identity_of(s, anchor)
            existing = self.anchors.get(s["to"]) or self._peer(s["to"], union)
            if existing is not None and existing.alias is not None:
                self.equate(existing, anchor)
                # the node keeps its own column too: when the equality is a correlation
                # being decorrelated, nothing else anchors it and it would be re-ranged
                self.anchors.setdefault(s["to"], anchor)
            else:
                self.anchors[s["to"]] = anchor

    def absorbs_reference(self, s, src, cols, identity, rmap, fact_entry) -> bool:
        """Can this enter read everything it needs from the row already in hand?

        Three things have to be true, and the third is the one that costs a measurement.

        *Functional.* The columns entered by are the fact type's identifier, so at most one
        row of the target matches. Without it, dropping the join drops a multiplication.

        *Self-contained.* Every role of the fact type maps within those same columns, so
        nothing reachable through this node lives anywhere but on the near side. A fact type
        with a role of its own -- `Department has DepartmentName` -- fails here, because the
        name is only in the far table and the join really does fetch something.

        *Total.* Every value the near side holds is present over there, which is `enforced`
        in the roleMap. This is the half SQL cannot assume and ORM will not guess: a
        declared foreign key does not say it, because 28% of them are contradicted by their
        own rows, and a dangling value means the join removes a row that dropping it keeps.

        Restricted to a reference that points at the target's own identifier. A foreign key
        aimed at some other unique column is eliminable on the same argument, but the
        mapping does not record which other columns are unique, and `identity` is the only
        uniqueness it can read.
        """
        if s.get("join") == "outer" or not src.enforced or src.alias is None:
            return False
        # Neither side may be a reference to something other than an identifier. `src`
        # carrying one is out of scope (below); the entered role carrying one means the join
        # equates columns of the source that are not the ones `src` stands on, and the
        # near-for-far substitution this builds would then pair up the wrong two.
        if src.references is not None or rmap.get("references") or fact_entry is None:
            return False
        if cols != identity or len(src.columns) != len(cols):
            return False
        held = set(rmap["columns"])
        ft = self.em.concepts_by_id.get(self.em.role_owner.get(s["role"]) or "")
        if ft is None or not ft.get("roles"):
            return False
        maps = [self.em.role_map.get(r["id"]) for r in ft["roles"]]
        return all(m is not None and set(m["columns"]) <= held for m in maps)

    # Finding 124. Reading a role that reaches an ENTITY gives an instance identified by the
    # values in hand -- and nothing checks that instance is in its own table. Where a
    # database enforces the foreign key the two agree; where it does not, a dangling value
    # passes as though the instance existed. 11% of BIRD's declared single-column foreign
    # keys have dangling values, formula_1's three worst at 200-350 rows apiece.
    #
    # `REFERENT` selects what to do about it, so the options can be measured against each
    # other rather than argued:
    #   "join"    (the default) an inner join to the target on its identifying columns,
    #             which are unique, so it filters without multiplying and the planner uses
    #             the key's index. Reused through `join_keys`, so where a later step already
    #             joins that target the check collapses into it and costs nothing.
    #   "exists"  a semijoin. Measured strictly worse: the same correctness, but a
    #             correlated subquery per traversal timed out 13 recorded queries that ran
    #             before, against 1 for the join -- and that 1 times out with the check off
    #             too. Kept so the comparison in finding 126 can be re-run.
    #   "off"     what the compiler did until finding 124: trust the declared key.
    #
    # Measured over the 1,982 recorded queries: 386 statements change, 1 answer moves, and
    # that move is a correction -- card_games/416 goes from 12.976095 to 12.975290, which is
    # what the gold query returns, because the gold inner-joins the uuid exactly as this does.
    REFERENT = os.environ.get("CONQUER_REFERENT", "join")

    def referent_exists(self, s, anchor) -> None:
        """Assert that the instance an exit reaches is in its own table."""
        if self.REFERENT == "off" or self.decorrelate:
            return
        if anchor.enforced:
            # The mapping has already been shown this holds, over every row. Joining to
            # prove it again is the join Malloy eliminates: it filters nothing out.
            return
        entry = self.em.concept_map.get(self.concept.get(s["to"]))
        if entry is None or entry["table"] == anchor.table:
            return                      # a value, or an instance already standing on its row
        t = self.em.table(entry["table"])
        if t.get("derived") or t.get("base"):
            return                      # a derived subtype is narrowed by its own CTE already
        cols = self.em.col_refs(anchor.references or entry["identifyingColumns"])
        refs = anchor.refs()
        if len(cols) != len(refs):
            return
        if self.REFERENT == "exists":
            alias = self.em.alias(t["name"])
            cond = " AND ".join("%s = %s" % (c.format(alias), r) for c, r in zip(cols, refs))
            self.where.append("EXISTS (SELECT 1 FROM %s AS %s WHERE %s)"
                              % (self.em.table_name(entry["table"]), alias, cond))
            return
        # A join to the target's *identifying* columns is functional -- at most one row
        # matches -- so it filters without multiplying, and the planner uses the key's index
        # where a correlated EXISTS would not. Reused through `join_keys` like any other
        # functional join: two attributes of one entity asked for the same referent check
        # twice and emitted three joins to a table that should be joined once (finding 101's
        # invariant, caught by test_operators).
        # The same key shape the enter branch uses, so the two collapse: a later step that
        # joins this target on its identity IS the existence check, and emitting a second
        # join for it is the duplicate `test_operators` catches.
        key = ("JOIN", entry["table"], tuple(cols), tuple(refs))
        alias = self.join_keys.get(key)
        if alias is None:
            alias = self.em.alias(t["name"])
            cond = " AND ".join("%s = %s" % (c.format(alias), r) for c, r in zip(cols, refs))
            self.joins.append(("JOIN", "%s AS %s" % (self.em.table_name(entry["table"]), alias),
                               cond))
            self.join_keys[key] = alias

    def identity_of(self, s, anchor) -> Anchor:
        """In a derived table's body, stand an entity reached by reference on its identifier.

        A derived table's columns for an entity are that entity's identifying columns --
        `concept_map_columns` names them, and the query using it joins on them. An exit
        across a foreign key aimed at some other column leaves the node on the referencing
        column: `BondAllocation b has Fund f` stands on `bond_allocations.fundlink`, which
        holds the fund's *ticker* (`funds.tickersym`), not its `productnum`. Anywhere else
        `equate` and the enter branch translate through `references`; a CTE column cannot
        carry them, so `DEFINE Hq ::= LIST f, q FROM BondAllocation b has Fund f ...` put the
        ticker in `Hq.f` and the outer query joined it to `productnum` -- `character varying
        = bigint` on PostgreSQL, and on SQLite a join matching nothing (finding 162).

        So join the entity on the referenced columns, as `referent_exists` already does by
        default (the key is the same, so the two collapse), and stand on its identifier.
        Grouping follows the anchor, so `GROUPED BY f` groups by the identifier too.
        """
        if not self.identity_out or self.decorrelate or not anchor.references:
            return anchor
        entry = self.em.concept_map.get(self.concept.get(s["to"]))
        if entry is None or list(anchor.references) == list(entry["identifyingColumns"]):
            return anchor
        if self.em.columns[anchor.references[0]]["table"] != entry["table"]:
            return anchor
        t = self.em.table(entry["table"])
        if t.get("derived") or t.get("base"):
            return anchor
        cols = self.em.col_refs(anchor.references)
        refs = anchor.refs()
        if len(cols) != len(refs):
            return anchor
        kind = "LEFT JOIN" if s["from"] in self.optional else "JOIN"
        key = (kind, entry["table"], tuple(cols), tuple(refs))
        alias = self.join_keys.get(key)
        if alias is None:
            alias = self.em.alias(t["name"])
            cond = " AND ".join("%s = %s" % (c.format(alias), r) for c, r in zip(cols, refs))
            self.joins.append((kind, "%s AS %s" % (self.em.table_name(entry["table"]), alias),
                               cond))
            self.join_keys[key] = alias
        return Anchor(alias, self.em.col_refs(entry["identifyingColumns"]), entry["table"])

    def value_head(self, s, union) -> Optional[Anchor]:
        """A value type standing where a path starts, entering a fact type directly.

        `THE MAXIMUM DepartmentCode has Busy BusyN` -- the shape a DEFINE keyed on a value
        type forces, and the natural way to write "the busiest department's count". A value
        type has no table, so `anchor_for` refused it outright; `anchor_value` cannot help
        either, because the type is carried by its own fact type *and* by the derived one,
        which it reports as two populations. But the step says which is meant: the value is
        the role it is about to enter by, so range over that role's own table and stand on
        its column. Two writers hit this and both concluded the query was inexpressible
        (finding 127).
        """
        nid = s["from"]
        if nid in self.anchors or self._peer(nid, union) is not None:
            return None
        cid = self.concept.get(nid)
        kind = next((c.get("kind") for c in self.em.model.get("concepts", []) if c["id"] == cid), None)
        if kind != "value":
            return None
        if self.em.concept_map.get(cid) is not None:
            return None                       # a value type that does have a table of its own
        rmap = self.em.role_map.get(s["role"])
        if rmap is None or self.em.roles.get(s["role"], {}).get("player") != cid:
            return None                       # the value does not play the role being entered
        tid = rmap["table"]
        alias = self.em.alias(self.em.table(tid)["name"])
        self.froms.append("%s AS %s" % (self.em.table_name(tid), alias))
        anchor = Anchor(alias, self.em.col_refs(rmap["columns"]), tid)
        self.anchors[nid] = anchor
        return anchor

    def anchor_for(self, node_id, union) -> Anchor:
        """The anchor for a node, creating one from the mapping if this is where the query
        starts. Steps are processed before the root pass, so either end of a step may be the
        first mention of its node."""
        existing = self.anchors.get(node_id) or self.borrow(node_id, union)
        if existing is not None:
            return existing
        entry = self.em.concept_map.get(self.concept.get(node_id))
        if entry is None:
            raise SqlError("cannot anchor node %s: its concept has no table in the mapping"
                           % node_id)
        anchor = self.anchor_new(entry)
        self.anchors[node_id] = anchor
        return anchor

    def _peer(self, node_id, union) -> Optional[Anchor]:
        """The anchor of a node unified with this one, if any is anchored yet."""
        root = union.find(node_id)
        found = self.anchors.get(root)
        if found is None:
            found = next((a for nid, a in self.anchors.items() if union.find(nid) == root), None)
        return found

    def borrow(self, node_id, union, own_table: bool = True) -> Optional[Anchor]:
        """Anchor `node_id` at the row of a node it is unified with: one instance, one row.

        A derived subtype of that row is narrowed by its CTE on the way (item 16). Anchors
        used to be aliased under the unification's *root* by every step, and when the root
        was the subtype node -- reached by no step -- it inherited the row unnarrowed:
        `is of BilirubinWithinNormalRangeLaboratory has LaboratoryDate d` emitted a plain
        join to Laboratory and answered "any lab that month" (finding 114). With
        `own_table=False` a subtype that has a table of its own is left for the caller,
        which ranges over it and equates the two on identity."""
        peer = self._peer(node_id, union)
        if peer is None:
            return None
        entry = self.em.concept_map.get(self.concept.get(node_id))
        if entry is not None and entry["table"] != peer.table:
            t = self.em.table(entry["table"])
            if t.get("base") == peer.table:
                self.semijoin(entry, peer)          # a derived subtype of the row in hand
            elif not own_table:
                return None
        self.anchors[node_id] = peer
        return peer

    def anchor_value(self, concept: str) -> Anchor:
        """Range over a value type that was named without a path.

        `THE AVERAGE EmployeeSalary` says "of every EmployeeSalary there is", and a value type's
        population is by definition the values appearing in its fact types. It has no table of
        its own, so the range is over the table that carries the role it plays. Where several
        tables carry it -- one value domain held by two columns, which rule 6d exists to find --
        there is no single population to average and the query has to say which it means.
        """
        places = {}
        for rid, role in self.em.roles.items():
            if role.get("player") != concept:
                continue
            m = self.em.role_map.get(rid)
            if m:
                places[(m["table"], tuple(m["columns"]))] = self.em.role_owner.get(rid, rid)
        name = self.concept_name(concept)
        if not places:
            raise SqlError(
                "%s is not stored anywhere this query can read: it plays no role that the "
                "mapping puts in a table." % name)
        if len(places) > 1:
            raise SqlError(
                "%s is carried by %d different fact types, so \"every %s\" is not one "
                "population: %s. Say which by walking a path to it -- `THE AVERAGE v IN "
                "<Type> has %s v`." % (
                    name, len(places), name,
                    ", ".join(sorted(self.concept_name(f) for f in places.values())), name))
        (tid, columns), _ = next(iter(places.items()))
        alias = self.em.alias(self.em.table(tid)["name"])
        self.froms.append("%s AS %s" % (self.em.table_name(tid), alias))
        return Anchor(alias, self.em.col_refs(list(columns)), tid)

    def concept_name(self, cid: str) -> str:
        for c in self.em.model.get("concepts", []):
            if c["id"] == cid:
                return c.get("name", cid)
        return cid

    def anchor_new(self, entry) -> Anchor:
        """A fresh range over a concept's table. A derived subtype ranges over its
        supertype's table, narrowed by a semijoin to its CTE."""
        tid = entry["table"]
        t = self.em.table(tid)
        base = t.get("base")
        if base is None:
            alias = self.em.alias(t["name"])
            self.froms.append("%s AS %s" % (self.em.table_name(tid), alias))
            return Anchor(alias, self.em.col_refs(entry["identifyingColumns"]), tid)
        alias = self.em.alias(self.em.table(base)["name"])
        self.froms.append("%s AS %s" % (self.em.table_name(base), alias))
        anchor = Anchor(alias, self.em.col_refs(t["baseColumns"]), base)
        self.semijoin(entry, anchor)
        return anchor

    def semijoin(self, entry, anchor: Anchor):
        """Narrow `anchor`'s row to a derived subtype's population: join its CTE on
        identity."""
        tid = entry["table"]
        v = self.em.alias(self.em.table(tid)["name"])
        cols = self.em.col_refs(entry["identifyingColumns"])
        cond = " AND ".join("%s = %s" % (c.format(v), ref)
                            for c, ref in zip(cols, anchor.refs()))
        self.joins.append(("JOIN", "%s AS %s" % (self.em.table_name(tid), v), cond))

    def equate(self, a: Anchor, b: Anchor):
        if a.alias == b.alias and a.columns == b.columns:
            return
        ra, rb = a.refs(), b.refs()
        # A foreign key that references a column other than the identifier (legalities.uuid
        # -> cards.uuid) unified with a row of the referenced table: compare it with the
        # referenced columns, not the identifier. `Legality has UnknownPowerCard` equated
        # legalities.uuid with cards.id and returned nothing (finding 34).
        if a.references and b.alias \
                and self.em.columns[a.references[0]]["table"] == b.table:
            rb = [c.format(b.alias) for c in self.em.col_refs(a.references)]
        elif b.references and a.alias \
                and self.em.columns[b.references[0]]["table"] == a.table:
            ra = [c.format(a.alias) for c in self.em.col_refs(b.references)]
        if self.decorrelate and (a.alias in self.outer_aliases) != (b.alias in self.outer_aliases):
            inner, outer = (rb, ra) if a.alias in self.outer_aliases else (ra, rb)
            self.corr.extend(p for p in zip(inner, outer) if p not in self.corr)
            return
        for x, y in zip(ra, rb):
            self.where.append("%s = %s" % (x, y))

    def restrict(self, anchor: Anchor, restriction) -> List[Frag]:
        """The conditions a value restriction puts on the column, as fragments."""
        col = Frag.of(anchor.scalar())
        out = []
        if restriction.get("values"):
            out.append(col + " IN (%s)" % ", ".join("?" for _ in restriction["values"])
                       + Frag("", restriction["values"]))
        for r in restriction.get("ranges", []):
            if r.get("min") is not None:
                out.append(col + Frag(" >= ?", [r["min"]]))
            if r.get("max") is not None:
                out.append(col + Frag(" <= ?", [r["max"]]))
        return out

    # -- values and conditions ---------------------------------------------

    def count_source(self, v) -> Frag:
        """What to count. An entity or fact identified by several columns has no single
        column to count, but counting instances is exactly COUNT(*)."""
        if v.get("kind") == "node":
            anchor = self.anchors.get(v["node"])
            if anchor is not None and len(anchor.columns) > 1:
                return Frag("*")
        return self.value(v)

    def refs_of(self, v) -> List[Frag]:
        """A value as the column(s) that carry it: an instance identified by several columns
        is all of them, in order -- what ORDER BY a Laboratory means."""
        if v["kind"] == "node":
            anchor = self.anchors.get(v["node"])
            if anchor is not None and len(anchor.columns) > 1:
                return [Frag(r) for r in anchor.refs()]
        return [self.value(v)]

    def value(self, v) -> Frag:
        if v["kind"] == "node":
            anchor = self.anchors.get(v["node"])
            if anchor is None:
                raise SqlError("node %s has no anchor" % v["node"])
            ref = Frag.of(anchor.scalar())
            if self._deferring:
                # exported by the inner query so the wrapping one can compare against it
                return Frag(self._defer.setdefault(ref, '"__c%d"' % len(self._defer)))
            return ref
        if v["kind"] == "constant":
            return Frag("?", [_coerce(v)])
        if v["kind"] == "calculation":
            return self.use_calc(v["calculation"])
        if v["kind"] == "conditional":
            return Frag.fmt("CASE WHEN %s THEN %s ELSE %s END", self.condition(v["condition"]),
                            self.value(v["then"]), self.value(v["else"]))
        raise SqlError("cannot emit value %r" % v.get("kind"))

    @staticmethod
    def _conjuncts(cond):
        """Flatten a top-level `and` into the parts that may be routed independently.

        Only `and` distributes across WHERE and HAVING. A disjunction mixing an aggregate
        with a plain column cannot be split without changing what it means, so anything
        else is returned whole.
        """
        if cond.get("kind") == "logical" and cond.get("op") == "and":
            out = []
            for operand in cond.get("operands", []):
                out.extend(Context._conjuncts(operand))
            return out
        return [cond]

    def _names_any(self, cond, targets) -> bool:
        """Does this condition reach one of `targets` -- directly, or through a calculation
        built on one? `WHERE pct > 15` over `round(c * 100 / t, 2) AS pct` with `c` grouped
        names no aggregate itself, and reading only the direct references sent it to
        WHERE: "aggregate functions are not allowed in WHERE", on every engine (finding
        162). A calculation's arguments are followed, in this block and the enclosing
        ones, each once."""
        if not targets:
            return False
        seen = set()
        contexts = [self] + self.em._contexts[::-1]

        def walk(node):
            if isinstance(node, dict):
                if node.get("kind") == "calculation":
                    cid = node.get("calculation")
                    if cid in targets:
                        return True
                    if cid not in seen:
                        seen.add(cid)
                        for ctx in contexts:
                            calc = getattr(ctx, "calc_by_id", {}).get(cid)
                            if calc is not None:
                                return walk(calc.get("arguments", []))
                    return False
                return any(walk(v) for v in node.values())
            if isinstance(node, list):
                return any(walk(v) for v in node)
            return False

        return walk(cond)

    def _names_window(self, cond) -> bool:
        """Does this condition mention a `WITHIN` aggregate? Those are computed after WHERE,
        so the condition belongs to a query wrapped around this one."""
        return self._names_any(cond, self.window_calcs)

    def _names_grouped(self, cond) -> bool:
        """Does this condition mention an aggregate grouped in the enclosing block?"""
        return self._names_any(cond, self.grouped_calcs)

    # -- what the model says a value is -------------------------------------

    def _typed(self, arg, types, functions) -> bool:
        """Does the model put this argument's value in `types`? A node's value type declares
        a data type; a calculation's is its function's; an `AS`-bound name is the
        calculation it names. Enclosing blocks are in scope, as their anchors are."""
        if not isinstance(arg, dict):
            return False
        contexts = [self] + self.em._contexts[::-1]
        if arg.get("kind") == "node":
            for ctx in contexts:
                anchor = ctx.anchors.get(arg["node"])
                if isinstance(anchor, _ScalarAnchor):
                    return self._typed({"kind": "calculation", "calculation": anchor.calc_id},
                                       types, functions)
                cid = ctx.concept.get(arg["node"])
                if cid:
                    name = ((self.em.concepts_by_id.get(cid) or {}).get("dataType") or {}) \
                        .get("name", "")
                    return name.lower().split("(")[0].strip() in types
            return False
        if arg.get("kind") == "calculation":
            for ctx in contexts:
                calc = getattr(ctx, "calc_by_id", {}).get(arg["calculation"])
                if calc is not None:
                    return calc["function"] in functions and not calc.get("aggregation")
        return False

    def is_text(self, arg) -> bool:
        return self._typed(arg, TEXT_TYPES, TEXT_RESULT)

    def is_numeric(self, arg) -> bool:
        if isinstance(arg, dict) and arg.get("kind") == "constant":
            v = _coerce(arg)
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        if isinstance(arg, dict) and arg.get("kind") == "calculation":
            for ctx in [self] + self.em._contexts[::-1]:
                calc = getattr(ctx, "calc_by_id", {}).get(arg["calculation"])
                if calc is not None:
                    return calc["function"] in NUMERIC_ARGS or bool(calc.get("aggregation"))
        return self._typed(arg, NUMERIC_TYPES, NUMERIC_ARGS)

    def as_number(self, frag) -> Frag:
        """`fn.castNumber` around a fragment: the dialect's own spelling of the cast."""
        cast = self.em.functions.get("fn.castNumber")
        return self.render_call(cast, "fn.castNumber", [frag]) if cast else Frag.of(frag)

    def condition(self, cond) -> Frag:
        kind = cond["kind"]
        if kind == "compare":
            left, right = self.value(cond["left"]), self.value(cond["right"])
            # `latitude > 9` with latitude kept as text: SQLite orders every text above
            # every number and answers without a word, PostgreSQL refuses the comparison.
            # Text against a number is meant as a number.
            if self.is_text(cond["left"]) and self.is_numeric(cond["right"]):
                left = self.as_number(left)
            elif self.is_text(cond["right"]) and self.is_numeric(cond["left"]):
                right = self.as_number(right)
            return Frag.fmt("%s " + cond["op"] + " %s", left, right)
        if kind == "logical":
            joiner = {"and": " AND ", "or": " OR "}.get(cond["op"])
            if joiner:
                return "(" + Frag.join(joiner, [self.condition(o) for o in cond["operands"]]) + ")"
            # Both are chains, not strictly binary: the parser builds `A op B op C` as one
            # flat operand list, so folding is what keeps C from being dropped in silence.
            parts = [self.condition(o) for o in cond.get("operands", [])]
            if not parts:
                raise SqlError("logical %r has no operands" % cond["op"])
            if cond["op"] == "implies":
                return "(" + parts[0] + ")" if len(parts) == 1 else \
                    _fold(parts, lambda a, b: Frag.fmt("(NOT (%s) OR (%s))", a, b))
            if cond["op"] == "iff":
                # `parts` above already rendered the operands and collected their parameters;
                # rendering them again here duplicated every bound value.
                return "(" + parts[0] + ")" if len(parts) == 1 else \
                    _fold(parts, lambda a, b: Frag.fmt("((%s) = (%s))", a, b))
            if cond["op"] == "xor":
                return "(" + parts[0] + ")" if len(parts) == 1 else \
                    _fold(parts, lambda a, b: Frag.fmt("((%s) <> (%s))", a, b))
        if kind == "not":
            return "NOT (" + self.condition(cond["operand"]) + ")"
        if kind == "exists":
            return self.exists(cond["block"])
        if kind == "restriction":
            anchor = self.anchors[cond["node"]]
            return "(" + Frag.join(" AND ", self.restrict(anchor, cond["restriction"])) + ")"
        if kind == "setCompare":
            return self.set_compare(cond)
        if kind == "call":
            spec = self.em.functions.get(cond["function"])
            return self.call(spec, cond["function"], cond.get("arguments", []))
        raise SqlError("cannot emit condition %r" % kind)

    def exists(self, block, negated=False) -> Frag:
        sql, params = self.em.emit(_variant(block, _probe=True), self.anchors)
        return Frag("%sEXISTS (%s)" % ("NOT " if negated else "", sql), params)

    def set_compare(self, cond) -> Frag:
        """binding-sql92.md §5: emitted directly, not through a negation encoding."""
        left, right = cond["left"], cond["right"]
        op = cond["op"]

        def bag(side):
            block = dict(side["block"])
            node = side["node"]
            block["projections"] = [{"id": "p", "name": "v",
                                     "source": node if isinstance(node, dict)
                                     else {"kind": "node", "node": node}}]
            sql, params = self.em.emit(block, self.anchors)
            frag = Frag(sql, params)
            if block.get("_limit") or block.get("_ordering"):
                # In a compound SELECT, ORDER BY and LIMIT belong to the compound, not to
                # the operand they follow. A bag with its own limit -- `(LIST ... THE FIRST
                # 1)`, conquer-2026.md §8 -- has to be its own derived table.
                return 'SELECT "v" FROM (' + frag + ")"
            return frag

        def not_exists_except(a, b):
            return Frag.fmt("NOT EXISTS (%s EXCEPT %s)", bag(a), bag(b))

        if op == "subset":
            return not_exists_except(left, right)
        if op == "superset":
            return not_exists_except(right, left)
        if op == "match":
            return Frag.fmt("(%s AND %s)", not_exists_except(left, right),
                            not_exists_except(right, left))
        if op == "properSubset":
            return Frag.fmt("(%s AND NOT %s)", not_exists_except(left, right),
                            not_exists_except(right, left))
        if op == "properSuperset":
            return Frag.fmt("(%s AND NOT %s)", not_exists_except(right, left),
                            not_exists_except(left, right))
        if op == "disjoint":
            return Frag.fmt("NOT EXISTS (%s INTERSECT %s)", bag(left), bag(right))
        raise SqlError("unknown set comparison %r" % op)

    # -- aggregates --------------------------------------------------------

    def calculation(self, calc, block):
        self._calculation(calc, block)
        group = calc.get("_group")
        if group and calc.get("_block") is not None:
            # lower.regroup_grouped: a grouped aggregate re-lowered over a bag of its own,
            # correlated on the keys, so section 14b's deduplication applies inside it. The
            # bag yields one figure per group; the enclosing GROUP BY takes it with MIN,
            # which of a constant is that constant, and the keys group the block as before.
            self.calc_sql[calc["id"]] = "MIN(" + self.calc_sql[calc["id"]] + ")"
            self.grouped_calcs.add(calc["id"])
            self._group_terms(group)

    def _group_terms(self, keys):
        """The GROUP BY terms for these keys, each rendered once."""
        for key in keys:
            if isinstance(key, dict):
                # A computed key: rendered in GROUP BY, its parameters bound there. Two
                # grouped aggregates over the SAME computed key render it once -- the
                # GROUP BY list is deduplicated below -- so binding its parameters again
                # per aggregate left more supplied than the statement uses, and every
                # query with two grouped aggregates over a parameterised key failed with
                # "Incorrect number of bindings supplied". A fragment carries its own, so
                # a term already in the list is simply not added again.
                term = self.value(key)
                if term.text == "?":
                    # A constant key -- `1 AS g ... GROUPED BY g`, the writers' spelling of
                    # "over everything". Bound, `GROUP BY ?` groups by a constant; spelled
                    # into the text, as every scorer does, `GROUP BY 1` is SQL's ordinal for
                    # the first output column, and that column is an aggregate: "aggregate
                    # functions are not allowed in the GROUP BY clause", from a query that
                    # ran under `./try`. A scalar subquery is the same constant and never an
                    # ordinal, on every dialect here.
                    term = Frag("(SELECT ?)", term.params)
                if term in self.groups:
                    continue
                self.groups.append(term)
                continue
            anchor = self.anchors.get(key)
            if anchor is not None:
                self.groups.extend(anchor.refs())

    def _calculation(self, calc, block):
        spec = self.em.functions.get(calc["function"])
        agg = calc.get("aggregation") or {}
        inner = calc.get("_block")
        # DISTINCT written inside the bag an aggregate ranges over is the aggregate's
        # DISTINCT (conquer-2026 section 14a: distinct projected rows, and the bag projects
        # the one value). `THE COUNT OF DISTINCT Employee [... has EmployeeSalary s WHERE
        # s > 50000]` counted 14 joined rows for 6 employees, because the bag's DISTINCT
        # lived on the block and the flat aggregate never looked there. Found by the
        # reference interpreter (finding 114).
        distinct = bool(agg.get("distinct") or (inner or {}).get("distinct"))

        if inner is None and agg:
            # A grouped aggregate over the enclosing block (binding-sql92.md §4): the
            # aggregate is rendered in the SELECT list and the context nodes become GROUP BY.
            fn = self.em.aggregate_name(calc["function"], spec)
            # RANK takes no argument: what would be its argument is what the window is
            # ordered by, and lowering moved it there.
            arg = calc["arguments"][0] if calc["arguments"] else None
            src = Frag() if arg is None else (
                self.count_source(arg) if fn == "COUNT" else self.value(arg))
            if arg is not None and calc["function"] in NUMERIC_AGGREGATES and self.is_text(arg):
                src = self.as_number(src)         # SUM of text: as a number, as arithmetic is
            extra = [self.value(x) for x in calc["arguments"][1:]]
            if src == "*" and agg.get("distinct"):
                raise SqlError("a distinct count needs a single column, but this instance is "
                               "identified by several; count one of its roles instead")
            if agg.get("constant_in_group"):
                # The group keys pin what determines this value, so every row of the group
                # carries the same one and MIN returns it exactly. Provable, not heuristic:
                # lower.check_aggregate_locality only sets this when the keys settle the
                # argument's whole determinant chain.
                fn = "MIN"
            text = self.em.aggregate_sql(calc["function"], spec, src,
                                         bool(agg.get("distinct")), extra)
            if fn == "MIN" and agg.get("constant_in_group"):
                text = "MIN(" + src + ")"     # the pinned-value case above overrode `fn`
            if agg.get("window"):
                # `WITHIN d` -- the partition without the collapse. Every row keeps its own
                # identity and carries the group's figure beside it, which GROUP BY cannot do
                # because it returns one row per group.
                partition: List[Frag] = []
                for key in agg.get("context") or []:
                    if isinstance(key, dict):
                        partition.append(self.value(key))
                        continue
                    anchor = self.anchors.get(key)
                    if anchor is not None:
                        partition.extend(Frag(r) for r in anchor.refs())
                if not partition:
                    raise SqlError("WITHIN needs a partition this query binds")
                # Row-relative functions order the window, after the partition keys, which
                # is the order SQL reads them in.
                order = Frag()
                if agg.get("order"):
                    order = " ORDER BY " + Frag.join(", ", [
                        self.value(v) + " " + d.upper() for v, d in agg["order"]])
                window = " OVER (PARTITION BY " + Frag.join(", ", partition) + order + ")"
                # A template-spelled aggregate is an *expression*, not a call, so `OVER`
                # cannot hang off the end of it: SQLite answers "SQRT() may not be used as a
                # window function". SQLite has no STDDEV, so the sample form is SUM and
                # COUNT -- and the window form of that is each of those aggregates windowed
                # individually, which is valid. Distribute rather than refuse.
                text = (distribute_over(text, window)
                        if (spec or {}).get("sqlTemplate") and not agg.get("distinct")
                        else text + window)
                self.calc_sql[calc["id"]] = text
                self.window_calcs[calc["id"]] = '"__w%d"' % len(self.window_calcs)
                node = calc.get("_result")
                if node:
                    self.anchors[node] = _ScalarAnchor(self, calc["id"])
                return
            self.calc_sql[calc["id"]] = text
            self.grouped_calcs.add(calc["id"])
            self._group_terms(agg.get("context") or [])
            node = calc.get("_result")
            if node:
                self.anchors[node] = _ScalarAnchor(self, calc["id"])
            return

        if inner is None:
            # A scalar calculation: rendered in place from its arguments. Section 6.3's
            # f(P1..Pn), and the reason `LIST a * 100 / b FROM ...` can be written at all.
            # A calculation is BUILT here but USED wherever it is spliced, which may be a
            # different clause; the fragment carries its parameters to that point.
            self.calc_sql[calc["id"]] = self.call(spec, calc["function"],
                                                  calc.get("arguments", []))
            node = calc.get("_result")
            if node:
                self.anchors[node] = _ScalarAnchor(self, calc["id"])
            return

        fn = self.em.aggregate_name(calc["function"], spec)

        def bag_select(src, sql, distinct=False):
            """`(SELECT <the aggregate> FROM <the bag>)`, for each of the three shapes a bag
            can take below.

            Through `aggregate_sql` and not the bare name: an aggregate the dialect spells
            as a template -- SQLite's standard deviation, which is SUM, SUM of squares and
            COUNT -- has to be spelled that way over a derived table too. All three sites
            built the call from the name alone, so a standard deviation over a bag emitted
            STDDEV, which SQLite does not have.

            A template has nowhere to put DISTINCT either (`SUM(DISTINCT x * x)` is not the
            distinct sum of squares), but a bag is a derived table, so the distinct is taken
            there instead -- the same values, once each, which is what DISTINCT meant.
            """
            sql = Frag.of(sql)
            if distinct and ((spec or {}).get("sqlTemplate") or (spec or {}).get("sqlBagTemplate")
                             or extra_sql):
                # ...and a second operand has the same problem: `group_concat(DISTINCT x, sep)`
                # is refused by SQLite, so the distinct is taken in the derived table.
                sql, distinct = "SELECT DISTINCT %s FROM (" % src + sql + ")", False
            if (spec or {}).get("sqlBagTemplate") and src == '"v"':
                # The dialect spells this aggregate only over a derived table: SQLite's
                # median, the middle of the numbered bag. The bag's SQL is the template's
                # `{bag}`, once, so its parameters bind once.
                before, after = spec["sqlBagTemplate"].split("{bag}", 1)
                return before + sql + after
            if calc["function"] == "fn.list" and src == '"v"' and self._is_document(arg, block):
                # SQLite keeps the JSON subtype inside one expression and drops it through
                # a derived table, so a list gathered here holds each object as a quoted
                # string. Re-read it: this is the shape both LiveSQLBench writers who built
                # objects by hand ran into, and the one place the compiler can see it coming.
                reparse = self.em.functions.get("fn.json", {}).get("sqlTemplate")
                if reparse:
                    src = reparse.format(src)
            return ("(SELECT " + self.em.aggregate_sql(calc["function"], spec, src, distinct,
                                                       extra_sql) + " FROM (" + sql + "))")

        sub = dict(inner)
        arg = calc["arguments"][0]
        # The second operand of an OBJECT or a joined LIST. A key is a value of the bag's
        # own rows and rides out of the derived table under a name of its own, beside "v";
        # a separator is a constant, rendered into the aggregate call outside the bag.
        extra_sql, extra_projections = [], []
        for i, x in enumerate(calc["arguments"][1:]):
            if x.get("kind") == "constant":
                extra_sql.append(self.value(x))
            else:
                extra_projections.append({"id": "x%d" % i, "name": "__x%d" % i, "source": x})
                extra_sql.append('"__x%d"' % i)
        if (spec or {}).get("sqlBagTemplate") and (extra_sql or fn == "COUNT"):
            raise SqlError("%s cannot take a second operand" % self.em.aggregate_name(
                calc["function"], spec))

        # Four of the five shapes a bag can take are one shape: project the value, and
        # whatever else the aggregate needs beside it, emit the block as a derived table,
        # and aggregate over that outside. They differ only in what rides along, and each
        # used to be its own copy of the same twelve lines -- so every bag-shaped fix had to
        # be made three or four times, and one was not: the ordered path dropped DISTINCT,
        # so `THE DISTINCT LIST OF g ... ORDERED WITH g THE FIRST 2` gathered ["F","F"].
        #
        #   ordered        a nested relation with an order and a cut, "their three most
        #                  recent orders": SQLite takes no ORDER BY inside an aggregate call
        #                  and no LIMIT at all there, so the bag is ordered and trimmed as a
        #                  derived table. The distinct is taken there too, before the cut,
        #                  which is where SQL applies it.
        #   grouped_inner  conquer-2026.md §7: an aggregate over a grouped block. `THE
        #                  AVERAGE c IN Department d AND ALSO THE COUNT OF Employee [has
        #                  Department d] GROUPED BY d AS c` -- AVG(COUNT(..)) is not SQL, so
        #                  the grouped block is the derived table. The same when the thing
        #                  aggregated is a group key: `THE COUNT OF d IN (... GROUPED BY d AS
        #                  c WHERE c > 2)` counts the groups that pass, not the rows of the
        #                  first group, which is what SELECT COUNT(d) ... GROUP BY d HAVING
        #                  returned (finding 37).
        #   dedupe         the block repeats the value and `dedupe` names what determines
        #                  it: those ride along as keys, the rows are taken DISTINCT, and the
        #                  aggregate outside adds each value exactly once (finding 79).
        #   bag_only       a dialect that spells the aggregate only over a derived table
        #                  (SQLite's median), or a DISTINCT with a second operand, which
        #                  SQLite refuses as `GROUP_CONCAT(DISTINCT x, sep)`.
        ordered = bool(calc.get("_ordering") or calc.get("_limit"))
        grouped_inner = any(
            isinstance(c.get("aggregation"), dict)
            and c["aggregation"].get("context") not in (None, "universal")
            for c in inner.get("calculations", []))
        dedupe = agg.get("dedupe") or []
        bag_only = bool((spec or {}).get("sqlBagTemplate") or (distinct and extra_sql))
        if ordered or grouped_inner or dedupe or bag_only:
            here = {n["id"] for n in inner.get("nodes", [])}
            keys = [{"id": "k%d" % i, "name": "__k%d" % i,
                     "source": {"kind": "node", "node": nid}}
                    for i, nid in enumerate(dedupe) if nid in here]
            sub["projections"] = keys + [{"id": "p", "name": "v", "source": arg}] \
                + extra_projections
            if keys or (ordered and distinct):
                sub["distinct"] = True
            if ordered:
                sub["_ordering"] = calc.get("_ordering") or []
                sub["_limit"] = calc.get("_limit")
            sql, params = self.em.emit(sub, self.anchors)
            if ordered and ' AS "v"' not in sql:
                raise SqlError("an ordered or limited element gathers one column, but this "
                               "instance is identified by several; gather one of its roles")
            over = "*" if (grouped_inner and fn == "COUNT" and ' AS "v"' not in sql) else '"v"'
            self.calc_sql[calc["id"]] = bag_select(
                over, Frag(sql, params), distinct and over != "*" and not ordered)
            node = calc.get("_result")
            if node:
                self.anchors[node] = _ScalarAnchor(self, calc["id"])
            return
        sub["projections"] = [{"id": "p", "name": "v", "source": arg}]
        # The function's id travels with its name: the name is what most aggregates render
        # as, and the id is what finds the dialect's template for the few that do not.
        sub["_aggregate"] = (fn, distinct, calc["function"], calc["arguments"][1:])
        flat = self.em.emit_decorrelated(sub, self.anchors)
        if flat is not None:
            dsql, dparams, corr = flat
            alias = self.em.alias("agg")
            cond = " AND ".join('%s."k%d" = %s' % (alias, i, outer_ref)
                                for i, (_, outer_ref) in enumerate(corr))
            self.joins.append(("LEFT JOIN", Frag("(%s) AS %s" % (dsql, alias), dparams), cond))
            text = '%s."v"' % alias
            if fn == "COUNT":
                text = "COALESCE(%s, 0)" % text      # a scalar COUNT of nothing is 0
            elif fn == "JSON_GROUP_ARRAY":
                text = "COALESCE(%s, json_array())" % text     # ...and of nothing is empty
            self.calc_sql[calc["id"]] = Frag(text)
            node = calc.get("_result")
            if node:
                self.anchors[node] = _ScalarAnchor(self, calc["id"])
            return
        sql, params = self.em.emit(sub, self.anchors)
        # The parameters belong where the subquery's text lands, not where it was built:
        # calculations are built before the conditions that name them, and the fragment
        # carries them to wherever it is spliced.
        self.calc_sql[calc["id"]] = Frag("(%s)" % sql, params)
        node = calc.get("_result")
        if node:
            self.anchors[node] = _ScalarAnchor(self, calc["id"])

    @staticmethod
    def _is_document(arg, block) -> bool:
        """Is this value a JSON object the query built? `THE LIST OF` treats it as one."""
        if not isinstance(arg, dict) or arg.get("kind") != "calculation":
            return False
        return any(c.get("function") == "fn.jsonObject" for c in block.get("calculations", [])
                   if c["id"] == arg["calculation"])

    def call(self, spec, fid, arguments):
        """Render a function call and bind each argument's parameters once per use.

        A SQL template may name an argument more than once. SQLite has no STDDEV, so it is
        spelled from SUM and COUNT; `days_between` normalises a lenient date through a CASE
        that tests the same text several times; `rtrim(x, chars)` and `greatest(a, b, c)` are
        the dialect's two-argument forms. Rendering an argument sinks its parameters once, so
        emitting it six times left `the current statement uses 12 bindings and there are 2
        supplied` -- loudly, but wrong, and in five separate functions.

        Fixed here rather than at each call site, which is what the first two attempts did.
        Each argument is a fragment, and `Frag.placeholders` lays its parameters down once
        per placeholder, in the order the placeholders appear -- which is the order `.format`
        puts them in the SQL.
        """
        rendered = [self.value(a) for a in arguments]
        if fid in NUMERIC_ARGS:
            # Arithmetic over what the model says is text -- a date kept as text, a figure
            # read out of a document -- means "as a number" (TEXT_TYPES above).
            rendered = [self.as_number(r) if self.is_text(a) else r
                        for a, r in zip(arguments, rendered)]
        template = (spec or {}).get("sqlTemplate")
        order = ([int(m) for m in re.findall(r"\{(\d+)\}", template)] if template
                 else list(range(len(rendered))))
        # More arguments than the template places is not a call the dialect can make.
        # `greatest(a, b, c)` against SQLite's two-argument MAX used to render MAX(a, b) and
        # bind three -- a loud failure; once the binding was made to follow the placeholders
        # it would have rendered MAX(a, b) and bound two, which is the same wrong answer with
        # the noise removed. Refusing is the only honest option: nest two calls instead.
        if order and len(rendered) > max(order) + 1:
            raise SqlError(
                "%s takes %d argument(s) in this dialect and was given %d; nest the calls "
                "if you need more" % (self.function_name(fid, spec), max(order) + 1,
                                      len(rendered)))
        return self.render_call(spec, fid, rendered)

    @staticmethod
    def function_name(fid, spec):
        return (spec or {}).get("name") or str(fid).split(".")[-1]

    def render_call(self, spec, fid, args) -> Frag:
        """Infix for a two-argument operator, prefix for a one-argument one, else a call.
        `operatorSymbol` and the parameter list come from the model (model.md §3)."""
        args = [Frag.of(a) for a in args]
        # A trailing parameter the model gives a default for is supplied when the call leaves
        # it out: `round(x)` is `round(x, 0)`, and a template that has to spell both
        # arguments -- PostgreSQL's ROUND, which needs the numeric cast -- can then take one.
        for param in ((spec or {}).get("parameters") or [])[len(args):]:
            if "default" not in param:
                break
            args.append(Frag("?", [param["default"]]))
        template = (spec or {}).get("sqlTemplate")
        if template:
            # model.md §3: the dialect's spelling, when it is not the function's name.
            try:
                return Frag.placeholders(template, args)
            except (IndexError, KeyError):
                raise SqlError("function %s expects %d argument(s) for its SQL template %r"
                               % (fid, template.count("{"), template))
        symbol = (spec or {}).get("operatorSymbol")
        if symbol and len(args) == 2:
            return Frag.fmt("(%s " + symbol + " %s)", args[0], args[1])
        if symbol and len(args) == 1:
            return "(" + symbol + args[0] + ")"
        if symbol and len(args) > 2:
            # An associative operator folds. Without this, `concat(a, '-', b)` fell through to
            # a CONCAT() call, which SQLite before 3.44 does not have -- so a query that was
            # fine with two arguments failed with three, and the model's own `||` was ignored.
            return "(" + Frag.join(" %s " % symbol, args) + ")"
        name = (spec or {}).get("name") or fid.split(".")[-1]
        return name.upper() + "(" + Frag.join(", ", args) + ")"

    def use_calc(self, cid: str) -> Frag:
        """Splice a calculation into the SQL, binding its parameters at that point.

        A nested block may name a calculation of an enclosing one -- `... AS hrs WHERE c
        AND ALSO THE SUM OF hrs GROUPED BY n`, where the condition puts the aggregate under
        an EXISTS while `hrs` stays outside. The block is emitted with the enclosing anchors
        in scope, so the enclosing calculations are in scope with them; looking only in this
        context raised a bare KeyError (Spider 2.0, Pagila). The parameters bind here, where
        the text lands, not where the calculation was built."""
        for ctx in [self] + self.em._contexts[::-1]:
            if cid in ctx.calc_sql:
                frag = ctx.calc_sql[cid]
                if self._deferring and cid not in self.window_calcs:
                    # A `WITHIN` condition may compare against an ordinary computed value --
                    # `THE COUNT OF r GROUPED BY ... AS c ... THE MAXIMUM c WITHIN st AS mx
                    # WHERE c = mx`. That value is computed inside, so the wrapping query has
                    # to read it under an alias like any other inner column.
                    #
                    # Its parameters belong to the SELECT list, because that is where the
                    # text lands -- `extra` splices it into the inner SELECT while the
                    # wrapping clause carries only the alias, which binds nothing. Sending
                    # them to the current sink instead put them in the where or order slot,
                    # so every placeholder from the inner query onward took the wrong value:
                    # a filter executed as `postfreq > 0.3`, a limit as `__w0 <= 1`, and rows
                    # came back that violated the query's own conditions. No error. Three
                    # writers hit it on three databases. Only on first sight of the
                    # expression: a repeat reuses the alias and splices nothing.
                    #
                    # The fragment is held, alias in hand, and laid down with the select
                    # list where its text goes: binding on sight put its parameters ahead
                    # of the projections' own, so `(salary * 0.1)` and `2 * RANK() - 2`
                    # swapped values and the query computed `salary * 2` and `2 * RANK() -
                    # 0.1`. Silent, and a fourth writer found it.
                    return Frag(self._defer.setdefault(frag, '"__c%d"' % len(self._defer)))
                return frag
        raise SqlError("this query names a computed value that is not in scope where it is "
                       "used; bind it with AS in the same part of the query that reads it")

    # -- rendering ---------------------------------------------------------

    def duplicates_possible(self, block) -> bool:
        """Can two rows of this block be equal? If not, DISTINCT is a sort for nothing.

        The model answers this where a generic planner cannot. Rows of a block are instances
        of the thing it ranges over, joined outwards; a join multiplies only where a role is
        not functional, and an `exit` never does -- a fact has one player per role. So when
        every `enter` is functional there is at most one row per instance of the root, and
        when the root's own identity is projected, two rows differ wherever their instances do.

        Conservative on purpose: one root, an entity type carrying identifying columns (a
        value type at the root identifies nothing -- two employees may share a salary), and no
        grouped calculation, which changes what a row is. Derivation rules are the case this
        is for. `lower_rules` marks every rule body distinct because a fact population is a
        set, and across the benchmark's eleven semantic models 88 of the 94 derived concepts
        cannot produce a duplicate in the first place.
        """
        for st in block.get("steps", []):
            if st["kind"] == "enter" and not self.em.is_functional(st["role"]):
                return True
        if any(isinstance(c.get("aggregation"), dict) for c in block.get("calculations", [])):
            return True
        reached = {st["to"] for st in block.get("steps", [])}
        roots = [n for n in block.get("nodes", []) if n["id"] not in reached]
        if len(roots) != 1:
            return True
        entry = self.em.concept_map.get(roots[0]["concept"])
        if not entry or not entry.get("identifyingColumns"):
            return True
        return not any(p.get("source", {}).get("kind") == "node"
                       and p["source"]["node"] == roots[0]["id"]
                       for p in block.get("projections", []))

    def render(self, block) -> Tuple[str, list]:
        """Assemble the statement from the clauses `build` filled, in clause order. Every
        piece is a fragment, so the parameters come out in text order without anyone
        having to remember which clause a value was rendered for."""
        agg = block.get("_aggregate")
        select_items: List[Frag] = []
        if agg:
            fn, distinct = agg[0], agg[1]
            fid = agg[2] if len(agg) > 2 else None
            extra_values = agg[3] if len(agg) > 3 else []
            source = block["projections"][0]["source"]
            if fn == "JSON_GROUP_ARRAY":
                # an instance identified by several columns nests as all of them
                refs = self.refs_of(source)
                src = refs[0] if len(refs) == 1 else "json_array(" + Frag.join(", ", refs) + ")"
            else:
                src = self.count_source(source) if fn == "COUNT" else self.value(source)
                if fid in NUMERIC_AGGREGATES and self.is_text(source):
                    src = self.as_number(src)
            if src == "*" and distinct:
                raise SqlError("a distinct count needs a single column, but this "
                               "instance is identified by several; count one of its "
                               "roles instead")
            spec = self.em.functions.get(fid) if fid else None
            extra = [self.value(x) for x in extra_values]
            select_items.append(
                self.em.aggregate_sql(fid, spec, src, distinct, extra) if fid
                else "%s(%s" % (fn, "DISTINCT " if distinct else "") + src + ")")
        elif block.get("_probe"):
            select_items.append(Frag("1"))
        else:
            for p in block.get("projections", []):
                src = p["source"]
                anchor = self.anchors.get(src["node"]) if src["kind"] == "node" else None
                if anchor is not None and len(anchor.columns) > 1:
                    # An instance identified by several columns is shown as all of
                    # them: Laboratory as (ID, Date). One name per column, so a
                    # derived type's CTE and a LIST both get a well-formed row.
                    for ref, col in zip(anchor.refs(), anchor.columns):
                        select_items.append(Frag("%s AS %s" % (
                            ref, _quote_ident("%s_%s" % (p["name"], _ref_name(col))))))
                    continue
                select_items.append(self.value(src) + " AS " + _quote_ident(p["name"]))
        if not select_items:
            select_items = [Frag("1")]
        if self.corr and agg:
            select_items = [Frag("%s AS \"k%d\"" % (ref, i)) for i, (ref, _) in enumerate(self.corr)] \
                + [select_items[0] + " AS \"v\""]
            self.groups.extend(ref for ref, _ in self.corr)

        froms, joins = list(self.froms), list(self.joins)
        if not froms and joins:
            # Nothing to anchor the FROM: promote the first join, moving its condition to
            # WHERE. Happens in a correlated sub-block, where every node it touches is
            # anchored in the enclosing query -- so even an outer join loses nothing here,
            # because the row it would have kept is the enclosing one, which exists anyway.
            kind, table, cond = joins.pop(0)
            froms.append(table)
            self.where.insert(0, cond)
        # Sort keys were resolved to values during lowering (lower.resolve_ordering), which
        # is the only place that can tell a mistyped key from a real one. Ordering by a value
        # the query does not list is legal -- see [P57], which sorts on the path head.
        ordering = block.get("_ordering") or []
        limit = block.get("_limit")
        wrapped_order = None
        if self.window_where and ordering and not agg:
            # The sort keys have to be resolved *before* the wrap, and against the wrapper's
            # own columns. A projected key is in scope by its name; anything else -- sorting
            # on a column the query does not list, which [P57] allows -- has to ride out of
            # the inner select under an alias, which is what `_deferring` arranges. Rendered
            # after the wrap instead, the ORDER BY named an inner alias that is no longer in
            # scope: "no such column: employ1.salary". Four writers hit it.
            projected = {p["name"] for p in block.get("projections", [])}
            # A `WITHIN` value is selected under its alias like the filtered one, and the
            # ORDER BY has to name the alias: rendered as the expression, it named the
            # inner query's tables from outside them -- "no such column: depart2.dept_code"
            # -- whether or not the value was projected. The condition path above swaps
            # the aliases in while it renders; so does this.
            saved = {cid: self.calc_sql[cid] for cid in self.window_calcs
                     if cid in self.calc_sql}
            for cid, alias in self.window_calcs.items():
                self.calc_sql[cid] = Frag(alias)
            self._deferring = True
            try:
                wrapped_order = [
                    (Frag(_quote_ident(v["name"])) if v.get("name") in projected else ref)
                    + " %s%s" % (direction.upper(), _nulls(direction))
                    for v, direction in ordering for ref in self.refs_of(v)]
            finally:
                self._deferring = False
                self.calc_sql.update(saved)
        if self.window_where:
            # The `WITHIN` values this query filters on are selected alongside the answer and
            # the filter applied outside, which is the only order SQL allows: WHERE runs before
            # a window function exists. Same wrap as `THE FIRST n PER` below.
            for cid, alias in self.window_calcs.items():
                frag = self.calc_sql.get(cid)
                if frag is not None and frag.text:
                    select_items.append(frag + " AS " + alias)
            for ref, alias in self._defer.items():
                select_items.append(ref + " AS " + alias)
        ranked = limit is not None and not agg and (limit.get("per") is not None
                                                     or limit.get("ties"))
        window = None
        if ranked:
            # Two limits need a window rather than LIMIT, and they need the same one:
            # ROW_NUMBER numbers rows within each partition, RANK lets equal keys share a
            # number, which is the whole difference between "one of the fastest" and "the
            # fastest". The window goes in the SELECT list beside the answer.
            per = self.value(limit["per"]) if limit.get("per") is not None else None
            terms = [self.value(v) + " %s%s" % (direction.upper(), _nulls(direction))
                     for v, direction in ordering]
            over = Frag.join(" ", [x for x in (
                ("PARTITION BY " + per) if per else None,
                ("ORDER BY " + Frag.join(", ", terms)) if terms else None) if x is not None])
            window = ("%s() OVER (" % ("RANK" if limit.get("ties") else "ROW_NUMBER")
                      + over + ') AS "__rn"')
            select_items.append(window)

        # Correlation with an enclosing block needs no clause of its own: the sub-block was
        # built with the outer anchors in scope, so it already references their aliases.
        distinct = (" DISTINCT" if block.get("distinct") and not agg
                    and self.duplicates_possible(block) else "")
        sql = "SELECT%s " % distinct + Frag.join(", ", select_items)
        if froms or joins:
            # CROSS JOIN, not a comma: `A, B JOIN C ON C.x = A.y` is legal in SQLite, which
            # flattens the list, and an error in PostgreSQL, where the JOIN binds tighter than
            # the comma and A is not in scope for its ON. Joined explicitly, the roots come
            # first and every ON that follows can see all of them.
            sql = sql + " FROM " + Frag.join(" CROSS JOIN ", [Frag.of(f) for f in froms])
            for kind, table, cond in joins:
                sql = sql + " %s " % kind + table + " ON " + cond
        if self.where:
            sql = sql + " WHERE " + Frag.join(" AND ", [Frag.of(w) for w in self.where])
        if self.groups:
            terms = []
            for g in self.groups:
                if g not in terms:
                    terms.append(Frag.of(g))
            # What the keys fix is constant within a group, and SQL's rule is that a
            # selected column is grouped or aggregated: SQLite reads it off an arbitrary
            # row, PostgreSQL and DuckDB refuse the statement. Grouping by it as well
            # changes no group and satisfies the rule; lower.note_group_fixed says which
            # nodes, and their columns are named here whether or not they are selected.
            for nid in block.get("_fixed", []):
                anchor = self.anchors.get(nid)
                for ref in (anchor.refs() if anchor is not None else []):
                    if Frag.of(ref) not in terms:
                        terms.append(Frag.of(ref))
            sql = sql + " GROUP BY " + Frag.join(", ", terms)
        if self.having:
            sql = sql + " HAVING " + Frag.join(" AND ", [Frag.of(h) for h in self.having])
        if self.window_where:
            # The wrapping query's WHERE is a clause of its own, after the whole inner
            # query -- after its GROUP BY and HAVING, whose parameters a computed key binds.
            names = ", ".join(_quote_ident(p["name"]) for p in block.get("projections", []))
            sql = ("SELECT %s FROM (" % (names or "*") + sql + ") WHERE "
                   + Frag.join(" AND ", [Frag.of(w) for w in self.window_where]))
        if ranked:
            # conquer-2026.md §8's `THE FIRST n PER k` numbers rows within each partition;
            # `WITH TIES` ranks them so that equal keys share a number and all of them
            # survive the cut. The query becomes a derived table carrying the number, and the
            # outer query keeps what is within the limit.
            names = ", ".join(_quote_ident(p["name"]) for p in block.get("projections", []))
            sql = ("SELECT %s FROM (" % names + sql
                   + Frag(') WHERE "__rn" <= ?', [limit["count"] + (limit.get("offset") or 0)]))
            if limit.get("offset"):
                sql = sql + Frag(' AND "__rn" > ?', [limit["offset"]])
            if limit.get("ties"):
                # The rank IS the ordering, and it survives into the outer query where the
                # sort key may not have been projected. Rows sharing a rank are tied, so the
                # order among them is arbitrary because they are equal.
                sql = sql + ' ORDER BY "__rn"'
        else:
            if wrapped_order is not None:
                sql = sql + " ORDER BY " + Frag.join(", ", wrapped_order)
            elif ordering and not agg:
                sql = sql + " ORDER BY " + Frag.join(", ", [
                    ref + " %s%s" % (direction.upper(), _nulls(direction))
                    for v, direction in ordering for ref in self.refs_of(v)])
            # The limit is not part of the algebra (model.md §4.1): it trims an already-ordered
            # result, so it is emitted last and applies to the outermost block only.
            if limit is not None:
                sql = sql + Frag(" LIMIT ?", [limit["count"]])
                if limit.get("offset"):
                    sql = sql + Frag(" OFFSET ?", [limit["offset"]])
        return sql.text, sql.params


class UnionFind:
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _fold(parts, combine):
    """Left-fold a flat operand chain, matching the parser's left associativity."""
    out = parts[0]
    for part in parts[1:]:
        out = combine(out, part)
    return out


def _variant(block, **overrides):
    """A shallow copy of a block carrying emitter-only directives.

    These keys never reach a stored model -- they say how to render this one block -- but
    they do ride inside the IR dict, which is why they are underscore-prefixed.
    """
    out = dict(block)
    out.update(overrides)
    return out


# Fields of a mapping column this emitter knows how to honour. Anything else is refused by
# `col_ref` rather than ignored -- see the note there.
_COLUMN_FIELDS = {"id", "table", "name", "dataType", "nullable", "path", "isRowId"}
# A key that is a plain identifier goes into the path bare; anything else is bracket-quoted,
# which every dialect's JSONPath accepts. Real documents have keys like `packetLoss%`,
# `ISO_27001?` and `tx/hr`, so an allowlist of tidy names refuses legitimate schema.
# Stands in for the table alias while a reference is assembled, so the dialect's own braces
# can be escaped without touching the slot. Not a character any SQL identifier may hold.
_ALIAS = "\x00alias\x00"
_JSON_BARE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# One step of a JSONPath: a bracket-quoted key, or a bare identifier.
_JSON_STEP = re.compile(r'\.(?:"((?:[^"]|"")*)"|([A-Za-z_][A-Za-z0-9_]*))')
# What cannot be carried at all: these would end the SQL string literal or the quoted path.
_JSON_UNSAFE = re.compile(r"""['"\\]""")
# Which cast a path read needs. Text needs none; the numeric kinds do, because two of the
# three dialects hand back text. The cast itself is `fn.castNumber` / `fn.castInteger` in the
# model, not a literal here: `DOUBLE` is a syntax error on PostgreSQL, where the type is
# spelled DOUBLE PRECISION, and a type name is as dialect-specific as a function name.
_JSON_CAST = {"real": "fn.castNumber", "double": "fn.castNumber",
              "double precision": "fn.castNumber", "float": "fn.castNumber",
              "numeric": "fn.castNumber", "decimal": "fn.castNumber",
              "integer": "fn.castInteger", "int": "fn.castInteger",
              "bigint": "fn.castInteger", "smallint": "fn.castInteger"}


def _ref_name(ref: str) -> str:
    """A readable column name from a reference template.

    `Anchor.columns` holds templates now, not names (finding 87), and a CTE's column names are
    built from them: `Laboratory as (ID, Date)`. Without this the template itself became the
    name -- `Laboratory_{0}."ID"` -- which the recorded corpus caught and the test suite did
    not. A path read is named by its last step, which is what a reader would call it, and a
    step may be bracket-quoted and hold anything: `$."tx/hr"` is named `tx/hr`.
    """
    dollar = ref.rfind("$.")
    if dollar >= 0:
        steps = _JSON_STEP.findall(ref[dollar + 1:])
        if steps:
            quoted, bare = steps[-1]
            return quoted.replace('""', '"') if quoted else bare
    quoted = re.findall(r'"((?:[^"]|"")*)"', ref)
    return quoted[-1].replace('""', '"') if quoted else ref


def _nulls(direction: str) -> str:
    """Where an absent value sorts, said explicitly rather than left to the dialect.

    ConQuer's semantics are total: reading a role asserts the fact holds, so a null reaches
    an ordering key only through `OPTIONALLY`. When one does, a bare ORDER BY means whatever
    the backend says -- SQLite puts nulls first ascending, PostgreSQL puts them last -- and
    the same query returns different rows on different databases, silently. Pinned to
    SQLite's order, which is what every recorded answer was written against and what
    `reference._sortkey` computes, so nothing moves and the two backends now agree.
    """
    return " NULLS FIRST" if direction.lower() != "desc" else " NULLS LAST"


def _quote_ident(name: str) -> str:
    return '"%s"' % name.replace('"', '""')


def _coerce(v):
    dt = (v.get("dataType") or {}).get("name", "")
    lex = v["lexical"]
    if dt in ("int", "integer", "bigint", "smallint"):
        try:
            return int(lex)
        except ValueError:
            return lex
    if dt in ("decimal", "numeric", "real", "float", "double"):
        # A literal written as an integer binds as one. Everything used to bind as float,
        # harmless in a comparison and wrong in a projection: `if(g = 'F', 1, 0)` came back
        # as 1.0 and 0.0.
        try:
            return int(lex) if re.fullmatch(r"-?\d+", lex.strip()) else float(lex)
        except ValueError:
            return lex
    return lex


def emit(model: dict, block: dict) -> Tuple[str, list]:
    return Emitter(model).emit(block)
