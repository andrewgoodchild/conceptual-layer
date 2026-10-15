#!/usr/bin/env python3
"""Check SQL an agent wrote by hand against the conceptual model, before trusting its rows.

The compiler handles the fan trap for a ConQuer query: it knows from the uniqueness constraints
which side of a join is many, and sums a value once per thing that determines it. But the
measured configuration is the description with plain SQL beside it (docs/07), and a writer of
plain SQL gets none of that. docs/07 has the case that shows the gap: a projection fan trap,
3,738 rows where the question had 623, compiled cleanly because it was SQL. This reads the
same constraints and tells the writer what its joins do to its aggregates.

What it says, per SELECT:

  * **fan trap** -- SUM, AVG or COUNT over a table some other table in the join has several
    rows for, so each value is counted once per match. The model says which side is many:
    a join is one-to-one or many-to-one exactly where the far side's columns cover a
    uniqueness constraint the model maps onto that table.
  * **repeated rows** -- no aggregate, and a joined table the projected ones do not
    determine, so each projected row comes back once per match (the 3,738 rows).
  * **join key** -- an equality between two tables that is not a reference the model knows,
    where it knows another one between the same tables; or a join on part of a composite
    reference.
  * **cross product** -- tables in one FROM with nothing joining them.
  * **SUM(DISTINCT)** -- the usual repair for a fan trap, and wrong too: it drops values that
    are equal, not rows that are repeated.
  * **additivity** -- a SUM over a value the model says must not be summed (`additivity` on
    a value type, model/model.md §2.1).

Every finding says what to write instead. Nothing here is a refusal: the SQL is the writer's,
the model can be wrong, and the measurements say writers rarely produce these shapes -- so
the rows are still shown, with the findings above them.

Static, from the model alone: no query is run. A table the model does not map is opaque and
nothing is claimed about it. Needs `sqlglot` (pip install sqlglot), and only here.

    sqlcheck.py MODEL.ccm.json "SELECT ..."          findings; exit 1 for any but a note
    sqlcheck.py MODEL.ccm.json -f query.sql --dialect postgres
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.qualify import qualify
    from sqlglot.optimizer.scope import traverse_scope
except ImportError:                                             # pragma: no cover
    sqlglot = None

DIALECTS = {"sqlite": "sqlite", "postgres": "postgres", "postgresql": "postgres"}
SUMMING = ("Sum", "Avg", "Count")


class Finding:
    """One thing the joins do. `note` marks the kinds measured to carry no signal on their
    own (bench/pilot/sqlcheck_eval.py): repeated rows are a wrong answer only where the
    question counts rows, and BIRD's scorer compares sets."""

    def __init__(self, kind: str, message: str, fix: str, note: bool = False):
        self.kind, self.message, self.fix, self.note = kind, message, fix, note

    def __repr__(self):
        return "Finding(%r, %r)" % (self.kind, self.message)

    def render(self) -> str:
        return "%s%s: %s\n  instead: %s" % ("note, " if self.note else "", self.kind,
                                            self.message, self.fix)


def available() -> bool:
    return sqlglot is not None


# --------------------------------------------------------------------------- the model

class Keys:
    """What the model says about the tables a SQL writer joins: which column sets are unique
    in each table, and which column pairs are references.

    Unique sets come from two places: the columns that identify an entity type in its own
    table, and every uniqueness constraint whose roles all map into one table -- the union of
    their columns is unique there. That one rule covers the cases that matter: a uniqueness
    on the entity role of `Employee works in Department` maps to `employee.emp_nr`, one on
    the value role of `Department has Name` to `department.dept_name`, and the spanning one
    on an association to its composite key."""

    def __init__(self, model: dict):
        mapping = model.get("mapping") or {}
        tname = {t["id"]: t["name"].casefold() for t in mapping.get("tables", [])}
        self.columns: Dict[str, Dict[str, dict]] = {name: {} for name in tname.values()}
        col = {}
        for c in mapping.get("columns", []):
            t = tname.get(c["table"])
            if t is None or c.get("path"):
                continue              # a field inside a document is not a column to join on
            col[c["id"]] = (t, c["name"].casefold())
            self.columns[t][c["name"].casefold()] = c
        self.unique: Dict[str, List[FrozenSet[str]]] = {t: [] for t in self.columns}
        self.refs: List[Tuple[str, Tuple[str, ...], str, Tuple[str, ...]]] = []
        concepts = {c["id"]: c for c in model.get("concepts", [])}
        placed = {m["concept"]: m for m in mapping.get("conceptMap", [])}
        role_map = {rm["role"]: rm for rm in mapping.get("roleMap", [])}
        player = {r["id"]: r["player"] for c in model.get("concepts", [])
                  if c["kind"] == "fact" for r in c.get("roles", [])}

        def where(ids):
            got = [col[i] for i in ids if i in col]
            if not got or len(got) != len(ids) or len({t for t, _ in got}) != 1:
                return None
            return got[0][0], tuple(c for _, c in got)

        def unique(table, cols):
            s = frozenset(cols)
            if s not in self.unique[table]:
                self.unique[table].append(s)

        for m in mapping.get("conceptMap", []):
            at = where(m.get("identifyingColumns") or [])
            if at:
                unique(*at)
        for k in model.get("constraints", []):
            seqs = k.get("roleSequences") or []
            if k.get("kind") != "uniqueness" or len(seqs) != 1:
                continue
            ids = [c for rid in seqs[0] for c in (role_map.get(rid) or {}).get("columns", [])]
            if all(rid in role_map for rid in seqs[0]):
                at = where(ids)
                if at:
                    unique(*at)
        for rid, rm in role_map.items():
            who = concepts.get(player.get(rid), {})
            if who.get("kind") != "entity" or who["id"] not in placed:
                continue
            target = placed[who["id"]]
            near = where(rm.get("columns") or [])
            far = where(rm.get("references") or target.get("identifyingColumns") or [])
            if near and far and near != far:
                self.refs.append((near[0], near[1], far[0], far[1]))
        # a subtype in a table of its own is joined to its supertype on the identifier
        for c in model.get("concepts", []):
            for sup in c.get("supertypes") or []:
                a = where((placed.get(c["id"]) or {}).get("identifyingColumns") or [])
                b = where((placed.get(sup) or {}).get("identifyingColumns") or [])
                if a and b and a != b:
                    self.refs.append((a[0], a[1], b[0], b[1]))

        # (table, column) -> the value type stored there, for additivity; and a role -> its
        # column, for the role a semi-additive value may not be summed across
        self.value: Dict[Tuple[str, str], dict] = {}
        self.role_column: Dict[str, str] = {}
        for rid, rm in role_map.items():
            who = concepts.get(player.get(rid), {})
            at = where(rm.get("columns") or [])
            if at and len(at[1]) == 1:
                self.role_column[rid] = at[1][0]
                if who.get("kind") == "value":
                    self.value.setdefault((at[0], at[1][0]), who)

    def schema(self) -> Dict[str, Dict[str, str]]:
        """The shape sqlglot needs to say which table an unqualified column belongs to."""
        return {t: {c: "TEXT" for c in cols} for t, cols in self.columns.items()}

    def pairs(self, a: str, b: str):
        """The references between two tables, each as a set of (column of a, column of b)."""
        for t1, c1, t2, c2 in self.refs:
            if (t1, t2) == (a, b):
                yield frozenset(zip(c1, c2))
            elif (t1, t2) == (b, a):
                yield frozenset(zip(c2, c1))


# --------------------------------------------------------------------------- one SELECT

class Source:
    def __init__(self, alias: str, table: Optional[str], unique: List[FrozenSet[str]]):
        self.alias, self.table, self.unique = alias, table, unique

    @property
    def label(self) -> str:
        if self.table and self.table != self.alias:
            return "%s (%s)" % (self.alias, self.table)
        return self.table or self.alias


def _derived_unique(select) -> Optional[List[FrozenSet[str]]]:
    """What is unique in the rows a subquery produces: its GROUP BY columns, all of them
    under DISTINCT, the empty set (one row) for an aggregate with no GROUP BY. None when
    nothing can be said."""
    if not isinstance(select, exp.Select):
        return None
    names = {}
    for e in select.expressions:
        inner = e.this if isinstance(e, exp.Alias) else e
        if isinstance(inner, exp.Column):
            names[(inner.table, inner.name.casefold())] = e.alias_or_name.casefold()
    group = select.args.get("group")
    if group:
        cols = []
        for g in group.expressions:
            if not isinstance(g, exp.Column) or (g.table, g.name.casefold()) not in names:
                return []
            cols.append(names[(g.table, g.name.casefold())])
        return [frozenset(cols)]
    if select.args.get("distinct"):
        return [frozenset(e.alias_or_name.casefold() for e in select.expressions)]
    if any(select.find_all(exp.AggFunc)) and not select.args.get("group"):
        return [frozenset()]
    return []


def _conjuncts(e):
    if e is None:
        return []
    if isinstance(e, exp.And):
        return _conjuncts(e.left) + _conjuncts(e.right)
    if isinstance(e, exp.Paren):
        return _conjuncts(e.this)
    return [e]


def _constant(e) -> bool:
    """A literal, a bound parameter or a scalar subquery -- `date = (SELECT MAX(date) ...)`:
    a column equal to one is fixed to a single value."""
    if isinstance(e, exp.Neg):
        e = e.this
    return isinstance(e, (exp.Literal, exp.Placeholder, exp.Subquery))


def _averaged(agg) -> bool:
    """`SUM(x) / COUNT(x)`: an average written out by hand, which is what a non-additive
    value should get. BIRD's gold writes `AVG` this way more often than it writes `AVG`."""
    node = agg
    while isinstance(node.parent, (exp.Cast, exp.Paren, exp.Mul)):
        node = node.parent
    div = node.parent
    return isinstance(div, exp.Div) and div.this is node and \
        any(isinstance(a, exp.Count) for a in div.expression.find_all(exp.AggFunc))


def _own(node, root):
    """`node` belongs to this SELECT and not to a subquery inside it."""
    p = node.parent
    while p is not None and p is not root:
        if isinstance(p, (exp.Select, exp.Subquery)):
            return False
        p = p.parent
    return True


class Scope:
    def __init__(self, scope, keys: Keys, root: bool, dialect: str):
        self.select = scope.expression
        self.keys, self.root, self.dialect = keys, root, dialect
        self.sources: Dict[str, Source] = {}
        for alias, src in scope.sources.items():
            if isinstance(src, exp.Table):
                name = src.name.casefold()
                if name in keys.unique:
                    self.sources[alias] = Source(alias, name, keys.unique[name])
                else:
                    self.sources[alias] = Source(alias, name, [])
            else:
                got = _derived_unique(getattr(src, "expression", None))
                self.sources[alias] = Source(alias, None, got or [])
        self.eq: Dict[Tuple[str, str], Set[Tuple[str, str]]] = {}
        self.fixed: Dict[str, Set[str]] = {a: set() for a in self.sources}
        where = self.select.args.get("where")
        preds = _conjuncts(where.this if where else None)
        for j in self.select.args.get("joins") or []:
            preds += _conjuncts(j.args.get("on"))
        for p in preds:
            if not isinstance(p, exp.EQ):
                continue
            l, r = p.left, p.right
            if isinstance(l, exp.Column) and isinstance(r, exp.Column):
                if l.table in self.sources and r.table in self.sources and l.table != r.table:
                    a, b = sorted([(l.table, l.name.casefold()), (r.table, r.name.casefold())])
                    self.eq.setdefault((a[0], b[0]), set()).add((a[1], b[1]))
            elif isinstance(l, exp.Column) and l.table in self.sources and _constant(r):
                self.fixed[l.table].add(l.name.casefold())
            elif isinstance(r, exp.Column) and r.table in self.sources and _constant(l):
                self.fixed[r.table].add(r.name.casefold())

    # ------------------------------------------------------------------ the join graph

    def on(self, a: str, b: str) -> Set[Tuple[str, str]]:
        """The equalities joining a to b, as (column of a, column of b)."""
        if a < b:
            return set(self.eq.get((a, b), ()))
        return {(y, x) for x, y in self.eq.get((b, a), ())}

    def _covered(self, b: str, cols: Set[str]) -> bool:
        cols = cols | self.fixed[b]
        return any(u <= cols for u in self.sources[b].unique)

    def determines(self, a: str, b: str) -> bool:
        """Each row of a meets at most one row of b."""
        return self._covered(b, {cb for _, cb in self.on(a, b)})

    def reach(self, start: Set[str]) -> Set[str]:
        seen, todo = set(start), list(start)
        while todo:
            a = todo.pop()
            for b in self.sources:
                if b not in seen and self.determines(a, b):
                    seen.add(b)
                    todo.append(b)
        return seen

    def multipliers(self, alias: str) -> List[str]:
        """The sources a row of `alias` can meet more than once."""
        got = self.reach({alias})
        return sorted(a for a in self.sources if a not in got)

    def connected(self) -> List[Set[str]]:
        parts, left = [], set(self.sources)
        while left:
            todo, part = [left.pop()], set()
            while todo:
                a = todo.pop()
                part.add(a)
                for b in list(left):
                    if self.on(a, b):
                        left.discard(b)
                        todo.append(b)
            parts.append(part)
        return parts

    def fan(self, start: Set[str]) -> Optional[Tuple[str, str]]:
        """The join where a row of `alias` first meets several rows: (near, far), or None.
        The near side is something `alias` determines, so the step named is the one that
        multiplies -- `loan -> account` is fine and `account -> disp` is not, and saying
        "loan meets several disp rows" without the middle step sent a reader to the wrong
        join."""
        got = self.reach(start)
        steps = [(x, y) for x in sorted(got) for y in sorted(self.sources)
                 if y not in got and self.on(x, y)]
        if steps:
            return steps[0]
        rest = sorted(a for a in self.sources if a not in got)
        return (sorted(start)[0], rest[0]) if rest else None

    def why(self, near: str, far: str) -> str:
        """Why a row of `near` meets several of `far`, in a clause."""
        o = self.sources[far]
        cols = sorted(cb for _, cb in self.on(near, far))
        if not cols:
            return "nothing joins %s to the rest" % o.label
        via = "" if near == far else "%s joined to %s " % (o.label, self.sources[near].label)
        if o.table is None:
            return "%son %s, which is not unique in that subquery" % (via, ", ".join(cols))
        keys = " or ".join("(%s)" % ", ".join(sorted(u)) for u in o.unique) or "none"
        return "%son %s, which the model does not make unique in %s (its keys: %s)" % (
            via, ", ".join(cols), o.table, keys)

    def same(self, alias: str, column: str) -> Set[str]:
        """The sources holding a value equal to alias.column through the join's equalities:
        `COUNT(account.account_id)` joined on `loan.account_id` counts loans as surely as
        `COUNT(loan.account_id)` does."""
        seen, todo = {(alias, column)}, [(alias, column)]
        while todo:
            a, c = todo.pop()
            for b in self.sources:
                for x, y in self.on(a, b):
                    if x == c and (b, y) not in seen:
                        seen.add((b, y))
                        todo.append((b, y))
        return {a for a, _ in seen}

    # ------------------------------------------------------------------ the checks

    def findings(self) -> List[Finding]:
        out = []
        out += self._join_keys()
        out += self._cross()
        aggs = [a for a in self.select.find_all(exp.AggFunc) if _own(a, self.select)]
        out += self._aggregates(aggs)
        if self.root and not aggs and not self.select.args.get("group") \
                and not self.select.args.get("distinct"):
            out += self._repeats()
        return out

    def _join_keys(self) -> List[Finding]:
        out = []
        for (a, b), pairs in sorted(self.eq.items()):
            ta, tb = self.sources[a].table, self.sources[b].table
            if ta is None or tb is None or ta not in self.keys.unique or tb not in self.keys.unique:
                continue
            pairs = frozenset(pairs)
            known = list(self.keys.pairs(ta, tb))
            if ta == tb and all(x == y for x, y in pairs):
                continue                       # a self-join on the same columns
            if any(k <= pairs for k in known):
                continue
            partial = [k for k in known if pairs < k]
            said = " AND ".join("%s.%s = %s.%s" % (a, x, b, y) for x, y in sorted(pairs))
            if partial:
                whole = " AND ".join("%s.%s = %s.%s" % (a, x, b, y) for x, y in sorted(partial[0]))
                out.append(Finding(
                    "join key", "%s is part of a composite reference; the model joins %s to "
                    "%s on all of it" % (said, ta, tb),
                    "join on %s" % whole))
            elif known:
                ways = "; ".join(" AND ".join("%s.%s = %s.%s" % (a, x, b, y) for x, y in sorted(k))
                                 for k in known)
                out.append(Finding(
                    "join key", "%s is not a reference the model knows between %s and %s"
                    % (said, ta, tb),
                    "the model relates them by %s -- use that, unless equal values in these "
                    "columns are what the question means" % ways))
        return out

    def _cross(self) -> List[Finding]:
        parts = self.connected()
        if len(parts) < 2:
            return []
        single = [p for p in parts if all(self._covered(a, set()) for a in p)]
        loose = [p for p in parts if p not in single]
        if len(loose) < 2:
            return []
        names = [", ".join(sorted(self.sources[a].label for a in p)) for p in loose]
        return [Finding(
            "cross product", "nothing joins {%s}: every row of one is paired with every row "
            "of the other" % "} to {".join(names),
            "add the join condition, or use a subquery if the pairing is not wanted")]

    def _columns(self, node) -> Set[str]:
        return {c.table for c in node.find_all(exp.Column) if c.table in self.sources}

    def _summed(self, node) -> List:
        """The columns an aggregate adds up -- not the ones its conditions read.
        `SUM(IIF(c.segment = 'SME', y.consumption, 0))` sums yearmonth's rows and only asks
        customers which of them to keep: BIRD writes its percentages this way, and reading
        every column in the argument made a fan trap of each one."""
        if isinstance(node, exp.If):
            return self._summed(node.args.get("true")) + self._summed(node.args.get("false"))
        if isinstance(node, exp.Case):
            got = []
            for w in node.args.get("ifs") or []:
                got += self._summed(w.args.get("true"))
            return got + self._summed(node.args.get("default"))
        if node is None or isinstance(node, exp.Literal):
            return []
        return list(node.find_all(exp.Column))

    def _measured(self, node) -> Set[str]:
        """The sources whose values an aggregate adds up (`_summed`)."""
        return {c.table for c in self._summed(node) if c.table in self.sources}

    def _aggregates(self, aggs) -> List[Finding]:
        out = []
        for agg in aggs:
            kind = type(agg).__name__
            if kind not in SUMMING:
                continue
            arg = agg.this
            distinct = isinstance(arg, exp.Distinct)
            text = agg.sql(dialect=self.dialect)
            if distinct:
                out += self._sum_distinct(agg, kind, arg, text)
                continue
            if isinstance(arg, exp.Star) or arg is None:
                if not any(not self.multipliers(a) for a in self.sources):
                    out.append(Finding(
                        "fan trap", "%s counts combinations of %s rows, not any one thing"
                        % (text, ", ".join(sorted(s.label for s in self.sources.values()))),
                        "count the thing meant: COUNT(DISTINCT its key)"))
                continue
            counted = None
            if kind == "Count" and isinstance(arg, exp.Column) and arg.table in self.sources:
                counted = self.same(arg.table, arg.name.casefold())
            for alias in sorted(self._measured(arg)):
                many = self.multipliers(alias)
                if not many or (counted and any(not self.multipliers(a) for a in counted)):
                    out += self._additivity(agg, kind, alias, text)
                    continue
                src = self.sources[alias]
                near, other = self.fan({alias})
                if kind == "Count":
                    fix = "COUNT(DISTINCT %s's key) counts each %s once" % (src.label, src.label)
                else:
                    fix = ("compute it from %s alone, or aggregate %s in a subquery grouped "
                           "by the join columns and join that" % (src.label,
                                                                  self.sources[other].label))
                out.append(Finding(
                    "fan trap", "%s counts each %s row once per matching %s row (%s)"
                    % (text, src.label, self.sources[other].label, self.why(near, other)),
                    fix))
        return out

    def _sum_distinct(self, agg, kind, arg, text) -> List[Finding]:
        if kind == "Count":
            return []
        cols = list(arg.find_all(exp.Column))
        if len(cols) == 1 and cols[0].table in self.sources:
            src = self.sources[cols[0].table]
            if any(u and u <= {cols[0].name.casefold()} for u in src.unique):
                return []                     # a key: distinct values are distinct rows
        return [Finding(
            "SUM(DISTINCT)", "%s drops values that are equal, not rows that repeat: two "
            "different rows with the same amount count once" % text,
            "remove the repetition instead -- aggregate the repeated table in a subquery "
            "before the join -- and sum plainly")]

    def _additivity(self, agg, kind, alias, text) -> List[Finding]:
        if kind != "Sum" or _averaged(agg):
            return []
        src = self.sources[alias]
        out = []
        for c in self._summed(agg.this):
            if c.table != alias or src.table is None:
                continue
            vt = self.keys.value.get((src.table, c.name.casefold()))
            how = (vt or {}).get("additivity")
            if how == "nonAdditive":
                out.append(Finding(
                    "additivity", "%s adds %s, which the model says is not additive (%s)"
                    % (text, vt["name"], "a rate, ratio, average or the like"),
                    "average it, or sum the quantities it is computed from"))
            elif how == "semiAdditive":
                over = self.keys.role_column.get(vt.get("additiveExcept"), "")
                group = self.select.args.get("group")
                held = {g.name.casefold() for g in (group.expressions if group else [])
                        if isinstance(g, exp.Column)} | self.fixed.get(alias, set())
                if over and over not in held:
                    out.append(Finding(
                        "additivity", "%s adds %s across %s, which the model says it may not "
                        "be summed over (a level, not a flow)" % (text, vt["name"], over),
                        "fix %s to one value (the latest, usually) or group by it" % over))
        return out

    def _repeats(self) -> List[Finding]:
        shown = set()
        for e in self.select.expressions:
            if isinstance(e, exp.Star):
                return []
            shown |= self._columns(e)
        if not shown or len(self.sources) < 2:
            return []
        step = self.fan(shown)
        if step is None:
            return []
        names = ", ".join(sorted(self.sources[a].label for a in shown))
        many = self.sources[step[1]].label
        return [Finding(
            "repeated rows", "each row of %s comes back once per matching %s row (%s)"
            % (names, many, self.why(*step)),
            "if %s is only a condition, test it with EXISTS (or IN); if the repetition is not "
            "wanted, SELECT DISTINCT" % many, note=True)]


# --------------------------------------------------------------------------- driver

def check(model: dict, sql: str, dialect: str = "sqlite", keys: Optional[Keys] = None
          ) -> List[Finding]:
    """The findings for one statement. A statement the parser cannot read gets none: the
    database will say what is wrong with it, and this has nothing to add."""
    if sqlglot is None:
        raise RuntimeError("the SQL checker needs sqlglot: pip install sqlglot")
    keys = keys or Keys(model)
    dialect = DIALECTS.get(dialect, dialect)
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
        tree = qualify(tree, schema=keys.schema(), dialect=dialect,
                       validate_qualify_columns=False, quote_identifiers=False,
                       identify=False)
        scopes = list(traverse_scope(tree))
    except Exception:                                               # noqa: BLE001
        return []
    out, seen = [], set()
    top = scopes[-1].expression if scopes else None
    for scope in scopes:
        if not isinstance(scope.expression, exp.Select):
            continue
        s = Scope(scope, keys, scope.expression is top or _in_union(scope.expression, top),
                  dialect)
        for f in s.findings():
            if (f.kind, f.message) not in seen:
                seen.add((f.kind, f.message))
                out.append(f)
    return out


def _in_union(select, top) -> bool:
    """A branch of a top-level UNION is a root too: its rows are the answer's rows."""
    p = select.parent
    while isinstance(p, (exp.Union, exp.Intersect, exp.Except, exp.Subquery)):
        if p is top:
            return True
        p = p.parent
    return False


def render(findings: List[Finding]) -> str:
    return "\n".join(f.render() for f in findings)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("model")
    p.add_argument("sql", nargs="?")
    p.add_argument("-f", "--file")
    p.add_argument("--dialect", default="sqlite", choices=sorted(DIALECTS))
    args = p.parse_args(argv)
    if sqlglot is None:
        sys.exit("the SQL checker needs sqlglot: pip install sqlglot")
    sql = open(args.file).read() if args.file else args.sql
    if not sql:
        p.error("give the SQL, or -f FILE")
    found = check(json.load(open(args.model)), sql, args.dialect)
    print(render(found) if found else "nothing to say")
    return 1 if any(not f.note for f in found) else 0


if __name__ == "__main__":
    sys.exit(main())
