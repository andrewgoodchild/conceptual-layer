"""A reference interpreter for the ConQuer-92 core: Proper's P, evaluated rather than compiled.

    P : PathExpr x (Attrs x TP) x P(Attrs) -> RA

Section 6 of the report (arXiv:2105.11926) defines the meaning of a path expression as a
translation to relational algebra over multisets, in which every expression denotes a
relation with a head column `hd`, a tail column `tl`, and one further column per bound
name. `lower.py` and `sql.py` are supposed to implement that translation. Nothing has ever
checked that they do -- the recorded corpus detects *change*, not *wrongness*, and accepted
the self-join collapse (finding 101) as its baseline for weeks.

This is the check. It takes the same parsed AST the compiler takes, builds the relation P
says it denotes directly from the data, and hands back rows. `tests/test_reference.py` runs
the compiler's SQL and this side by side; where they differ, one of them is wrong.

**Scope: the 1992 core, plus the 2026 constructs that have a stated semantics** -- and both
departures in conquer-2026 section 14, computed here independently of the compiler: 14a from
where `DISTINCT` is written, 14b from the model's uniqueness constraints. Nothing in this file
reads the compiler's lowered block, so a disagreement between the two is never explained away
by the compiler's own account of what it did. --
`GROUPED BY` (binding-sql92 section 4), `WITHIN`, `THE RANK OF`, `THE PREVIOUS`,
`OPTIONALLY`, `THE FIRST n PER`, and a value read from inside a document (rule 12). Where
this project departs from P on purpose -- `DISTINCT` on the projection, conquer-2026 section
14a -- `semantics="2026"` evaluates the stated 2026 rule and `semantics="1992"` evaluates P
as published. Everything else raises `Unsupported`, so the harness counts coverage honestly. It is written for clarity over speed and reads whole tables into
memory; that is fine for the fixtures and the BIRD corpus, and would not be for LiveSQLBench.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import math
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

import parser as cq


class Unsupported(Exception):
    """A construct the reference does not define yet. Not a bug: a scope boundary."""


Row = Dict[str, object]


class Reference:
    def __init__(self, model: dict, conn: sqlite3.Connection, lexicon=None,
                 semantics: str = "2026"):
        self.model = model
        self.conn = conn
        self.semantics = semantics
        self._pending: List[dict] = []     # grouped aggregates, collapsed once per query
        # Set by `query` when an ordered cut fell on rows that tie on the sort key. Which of
        # them survives is not defined by P or by SQL (finding 83), so a disagreement there is
        # not a disagreement about meaning.
        self.tied_cut = False
        self.lex = lexicon or cq.Lexicon(model)
        mp = model["mapping"]
        self.tables = {t["id"]: t["name"] for t in mp["tables"]}
        self.columns = {c["id"]: c for c in mp["columns"]}
        self.role_map = {e["role"]: e for e in mp["roleMap"]}
        self.concept_map = {e["concept"]: e for e in mp["conceptMap"]}
        self._pop: Dict[Tuple[str, str, str], List[Tuple[object, object]]] = {}
        self._corr: Dict[int, tuple] = {}              # correlated bags, evaluated once
        self._instances: Dict[str, List[object]] = {}
        self._derived: Dict[str, List[tuple]] = {}
        # Section 14b needs one fact from the model: a role a uniqueness constraint spans on its
        # own. Each instance playing that role plays it in at most one fact, so the fact's
        # other role is *determined* by it -- one budget per department -- and a value bound
        # through such a step carries the determining instance as its provenance.
        self.unique_roles = set()
        for c in model.get("constraints", []):
            if c.get("kind") == "uniqueness":
                for seq in c.get("roleSequences", []):
                    if len(seq) == 1:
                        self.unique_roles.add(seq[0])
        self.rules = {r["target"]["ref"]: r for r in model.get("derivationRules", [])
                      if isinstance(r.get("target"), dict)}

    # -- the population, read once per fact type -------------------------------------------

    def _col_expr(self, cid: str) -> str:
        return '"%s"' % self.columns[cid]["name"].replace('"', '""')

    def _extract(self, cid: str, raw):
        """Rule 12: a mapping column with a `path` reads a scalar out of the document the base
        column holds, cast to the type the mapping declares. Absent, null, or non-scalar is
        None -- the role is unfilled -- which is what the emitted json_extract returns too."""
        c = self.columns[cid]
        path = c.get("path")
        if not path or raw is None:
            return raw
        doc = raw
        if isinstance(doc, (bytes, bytearray)):
            doc = doc.decode("utf-8", "replace")
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except ValueError:
                return None
        for step in path:
            if not isinstance(doc, dict) or step not in doc:
                return None
            doc = doc[step]
        if isinstance(doc, (dict, list)):
            return None
        kind = (c.get("dataType") or {}).get("name", "").casefold()
        try:
            if kind in ("real", "double", "double precision", "float", "numeric", "decimal"):
                return float(doc)
            if kind in ("integer", "int", "bigint", "smallint"):
                return int(float(doc))
        except (TypeError, ValueError):
            return None
        return doc

    def _read(self, table_id: str, col_groups: List[List[str]], require_all=True, only=None,
              equals=None):
        """Rows of a table as tuples of (possibly composite) values, one per column group.

        Two ways a table too large to read whole is read for part of itself, which is how a
        walk through a 400k-row table stays a walk and not a load. `equals`: the last column
        group is a single plain column and must equal this value -- a restriction's constant
        (`[has LegalityFormat: 'commander']`), pushed down as one WHERE. `only`: the values
        the first column group may take -- the keys a step holds in hand -- read in chunks
        of an IN list. A single-column read (an identifier, for the head of a path) is
        allowed whole up to a larger cap: 400k ids is a second. Pair reads keep the cap."""
        exprs = [self._col_expr(c) for g in col_groups for c in g]
        where = " AND ".join("%s IS NOT NULL" % e for e in exprs) if require_all else "1=1"
        sql = 'SELECT %s FROM "%s" WHERE %s' % (", ".join(exprs), self.tables[table_id], where)
        n = self.conn.execute('SELECT COUNT(*) FROM "%s"' % self.tables[table_id]).fetchone()[0]
        # A proof of concept that reads whole tables into Python dicts. 200k rows across a
        # few passes is seconds; the card_games tables at 230k-430k rows turned one corpus
        # arm into a 2.3-hour run. A check that takes hours is a check nobody runs.
        # Pair reads are cached per fact type and steps push their keys down, so a whole
        # read of a 400k-row table is a second, once; the 120k cap dates from before either.
        # Only trans, at a million rows, is still read for its keys alone.
        cap = 1500000 if len(col_groups) == 1 and len(col_groups[0]) == 1 else 500000
        flat = [c for g in col_groups for c in g]
        params: list = []
        pushed = None
        if n > cap:
            last = col_groups[-1]
            if equals is not None and len(last) == 1 and not self.columns[last[0]].get("path") \
                    and not isinstance(equals, tuple):
                sql += " AND %s = ?" % exprs[-1]
                params.append(equals)
            elif only is not None and len(col_groups[0]) == 1:
                pushed = [v for v in only if v is not None and not isinstance(v, tuple)]
                if len(pushed) > 120000:
                    raise Unsupported("a %d-row table is more than this proof of concept reads" % n)
            else:
                raise Unsupported("a %d-row table is more than this proof of concept reads" % n)
        out = []
        if pushed is not None:
            raws = []
            for i in range(0, len(pushed), 500):
                chunk = pushed[i:i + 500]
                raws.extend(self.conn.execute(
                    "%s AND %s IN (%s)" % (sql, exprs[0], ", ".join("?" * len(chunk))), chunk))
        else:
            raws = self.conn.execute(sql, params)
        for raw in raws:
            raw = [self._extract(cid, v) for cid, v in zip(flat, raw)]
            if require_all and any(v is None for v in raw):
                continue                     # a path that reaches nothing is an unfilled role
            i, vals = 0, []
            for g in col_groups:
                n = len(g)
                vals.append(raw[i] if n == 1 else tuple(raw[i:i + n]))
                i += n
            out.append(tuple(vals))
        return out

    def derived(self, concept: str) -> List[tuple]:
        """Item 27 / section 6.11: the rows a DEFINE denotes are its query, evaluated."""
        if concept not in self._derived:
            rule = self.rules[concept]
            if not isinstance(rule.get("source"), str):
                raise Unsupported("a derivation rule that is not ConQuer text")
            ast = cq.Parser(self.lex, rule["source"]).parse_query()
            saved, self._pending = self._pending, []
            saved_corr, self._corr = self._corr, {}          # a query of its own: its own memo
            try:
                if (rule.get("target") or {}).get("kind") == "subtype":
                    rows, _ = self.eval_any(ast.body, None)
                    rows = self.collapse(rows)
                    self._derived[concept] = [(r["hd"],) for r in rows]
                else:
                    self._derived[concept] = self.query(ast)
            finally:
                self._pending = saved
                self._corr = saved_corr
        return self._derived[concept]

    def population(self, fact: str, r_from: str, r_to: str,
                   only=None, equals=None) -> List[Tuple[object, object]]:
        """The fact type as pairs (from-role value, to-role value), both filled. With `only`,
        the from-values a step holds, a table too large to read whole is read for those."""
        key = (fact, r_from, r_to)
        if key not in self._pop and fact in self.rules:
            roles = [r["id"] for r in self.lex.concepts[fact]["roles"]]
            i, j = roles.index(r_from), roles.index(r_to)
            self._pop[key] = [(t[i], t[j]) for t in self.derived(fact)
                              if t[i] is not None and t[j] is not None]
        if key not in self._pop:
            a, b = self.role_map.get(r_from), self.role_map.get(r_to)
            if a is None or b is None:
                raise Unsupported("role %s or %s has no relational mapping" % (r_from, r_to))
            if a["table"] != b["table"]:
                raise Unsupported("a fact type whose roles are mapped to different tables")
            # A foreign key that references a column other than the identifier (finding 34:
            # legalities.uuid -> cards.uuid, while a Card is identified by cards.id): the
            # column holds the referenced value, and the instance it names is found by
            # translating through the referenced table.
            xa, xb = self._translation(a), self._translation(b)
            if xa is not None and only is not None:
                inverse = {v: k for k, v in xa.items()}
                only = {inverse[v] for v in only if v in inverse}
            try:
                raw = self._read(a["table"], [a["columns"], b["columns"]])
            except Unsupported:
                if only is None and equals is None:
                    raise
                if xb is not None:
                    equals = None                    # the constant names an instance, not the column
                raw = self._read(a["table"], [a["columns"], b["columns"]], only=only, equals=equals)
                return self._via(raw, xa, xb)
            self._pop[key] = self._via(raw, xa, xb)
        return self._pop[key]

    def _translation(self, entry) -> Optional[Dict[object, object]]:
        """referenced value -> identifier of the instance it names, for a role mapped to a
        column that references a non-identifier column; None when the column is the
        identifier itself (the ordinary case)."""
        refs = entry.get("references")
        if not refs:
            return None
        table = self.columns[refs[0]]["table"]
        target = next((e for e in self.concept_map.values() if e["table"] == table), None)
        if target is None or target["identifyingColumns"] == list(refs):
            return None
        return dict(self._read(table, [list(refs), target["identifyingColumns"]]))

    @staticmethod
    def _via(pairs, xa, xb):
        if xa is None and xb is None:
            return pairs
        out = []
        for a, b in pairs:
            if xa is not None:
                a = xa.get(a)
            if xb is not None:
                b = xb.get(b)
            if a is not None and b is not None:
                out.append((a, b))
        return out

    def instances(self, concept: str) -> List[object]:
        """Every instance of an entity type, by identifier."""
        if concept not in self._instances and concept in self.rules:
            self._instances[concept] = [t[0] for t in self.derived(concept) if t[0] is not None]
        if concept not in self._instances:
            entry = self.concept_map.get(concept)
            if entry is None:
                raise Unsupported("%s is not mapped to a table" % concept)
            self._instances[concept] = [r[0] for r in
                                        self._read(entry["table"], [entry["identifyingColumns"]])]
        return self._instances[concept]

    # -- resolution: the same rule as lower.resolve_verb, ordinary case only -----------------

    def resolve(self, verb: str, head: str, target) -> Tuple[str, str, str]:
        cands = self.lex.verbs.get(verb.casefold(), [])
        # a fact instance in hand plays roles as the entity that objectifies it
        if self.lex.concepts.get(head, {}).get("kind") == "fact" and head in self.lex.twin:
            head = self.lex.twin[head]
        viable = [c for c in cands if self.lex.compatible(self.lex.roles[c[1]]["player"], head)]
        if isinstance(target, cq.TypeSpec):
            narrowed = [c for c in viable
                        if self.lex.compatible(self.lex.roles[c[2]]["player"], target.concept)]
            if narrowed:
                viable = narrowed
        if len(viable) != 1:
            raise Unsupported("verb %r from %s resolves to %d fact types"
                              % (verb, head, len(viable)))
        fact, r_from, r_to = viable[0]
        if len(self.lex.concepts[fact].get("roles", [])) != 2 and fact not in self.rules:
            raise Unsupported("n-ary fact type")
        return fact, r_from, r_to

    # -- the semantics --------------------------------------------------------------------

    def head_of(self, spec: cq.TypeSpec) -> Tuple[List[Row], str]:
        """A typed head denotes {hd = x, tl = x} for each instance x (rule P1)."""
        if spec.denotation is not None:
            v = self.constant(spec.denotation)
            rows = [{"hd": v, "tl": v}]
        else:
            rows = [{"hd": x, "tl": x} for x in self.instances(spec.concept)]
        if spec.var:
            for r in rows:
                r[spec.var] = r["tl"]
        return rows, spec.concept

    def eval_seq(self, seq: cq.Seq, start: Optional[Tuple[List[Row], str]]):
        parts = list(seq.parts)
        if isinstance(parts[0], cq.TypeSpec) and start is not None and parts[0].denotation is None \
                and self.lex.compatible(parts[0].concept, start[1]):
            # the head is named again where a start is already in hand: unify, do not re-range
            rows, concept = [dict(r) for r in start[0]], start[1]
            if parts[0].var:
                for r in rows:
                    r[parts[0].var] = r["tl"]
        elif isinstance(parts[0], cq.TypeSpec):
            rows, concept = self.head_of(parts[0])
        elif isinstance(parts[0], cq.ImplicitHead):
            if start is None:
                raise Unsupported("an implicit head with nothing to inherit")
            rows, concept = [dict(r) for r in start[0]], start[1]
        elif isinstance(parts[0], (cq.Binary, cq.SubExpr)):
            # A front expression as the head -- `(Card BUT NOT [has CardPower] OR OTHERWISE
            # Card [has CardPower: '*']) has CardId id`: its rows, continued from.
            rows, concept = self.eval_any(parts[0], start)
        else:
            raise Unsupported("head of kind %s" % type(parts[0]).__name__)
        for part in parts[1:]:
            if isinstance(part, cq.Step):
                rows, concept = self.step(rows, concept, part)
            elif isinstance(part, cq.Filter):
                rows = self.restrict(rows, concept, part)
            else:
                raise Unsupported("path part of kind %s" % type(part).__name__)
        return rows, concept

    def step(self, rows: List[Row], concept: str, part: cq.Step):
        """Concatenation (rule P-concat): join on tl = the fact's from-role."""
        head_fact = self.lex.fact_behind(concept)
        if head_fact is not None:
            # The position is a fact instance (an objectified fact type, or a fact type
            # named as a head). A role of its own is left by naming it -- B.2's role
            # reference `Connected has ConnectedAtom`, or the type that plays it -- and the
            # instance in hand is the identity tuple, so the exit is a read of that row.
            own = self.lex.concepts[head_fact].get("roles", [])
            if isinstance(part.target, cq.RoleSpec):
                named = [r for r in own if r["id"] in part.target.roles]
            elif isinstance(part.target, cq.TypeSpec) and part.target.denotation is None:
                named = [r for r in own if self.lex.compatible(r["player"], part.target.concept)]
                if len(named) > 1:
                    typed = self.lex.concepts[part.target.concept]["name"].casefold()
                    exact = [r for r in named if (r.get("name") or "").casefold() == typed]
                    named = exact or named
            else:
                named = []
            if len(named) == 1:
                return self.exit_role(rows, head_fact, named[0], part)
            if len(named) > 1:
                raise Unsupported("several roles of %s could be left by" % head_fact)
        if isinstance(part.target, cq.RoleSpec):
            # Appendix B.2 <role reference>: the name says which role to enter by, which is
            # the only way into a ring fact type (`Atom has ConnectedAtom`). The verb part
            # before it is nominal. The position reached is the fact instance itself, as
            # the compiler has it, so `has Bond` can leave it by another role.
            enter = [rid for rid in part.target.roles
                     if self.lex.compatible(self.lex.roles[rid]["player"], concept)]
            if len(enter) != 1:
                raise Unsupported("a role reference %d roles could enter by" % len(enter))
            return self.enter_role(rows, enter[0], part)
        if isinstance(part.target, cq.TypeSpec) and part.target.denotation is None \
                and not self._identity_related(part.target.concept, concept):
            # The target names a fact type itself -- `Superhero has HeroAttribute`, an
            # objectified fact type, not a role player: the path stops at the fact
            # instance (lower.resolve_move's "enter"), entered by the role the head plays.
            named_fact = self.lex.fact_behind(part.target.concept)
            if named_fact is not None:
                enter = [r["id"] for r in self.lex.concepts[named_fact].get("roles", [])
                         if self.lex.compatible(r["player"], concept)]
                if len(enter) == 1:
                    rows, reached = self.enter_role(rows, enter[0], part)
                    if part.target.var:
                        for r in rows:
                            r[part.target.var] = r["tl"]
                    return rows, reached
        if not isinstance(part.target, (cq.TypeSpec, type(None))):
            raise Unsupported("a step target of kind %s" % type(part.target).__name__)
        else:
            # A verb that names a fact type is a step, whatever the types either side of
            # it: `Atom19 is connected to Atom` walks the ring from a derived subtype and
            # fans out (377 rows, not the 219 heads relabelled). Only a verb no fact type
            # answers, between identity-related types, is item 16's narrowing.
            try:
                fact, r_from, r_to = self.resolve(part.verb, concept, part.target)
            except Unsupported:
                if isinstance(part.target, cq.TypeSpec) and part.target.denotation is None \
                        and self._identity_related(part.target.concept, concept):
                    return self.narrow(rows, concept, part)
                raise
        want, bang = None, None
        if isinstance(part.target, cq.TypeSpec) and part.target.denotation is not None:
            d = part.target.denotation
            if isinstance(d, tuple) and len(d) == 2 and d[0] == "!":
                bang = d                              # per row: what the enclosing row bound
            else:
                want = self.constant(d)
        by_from: Dict[object, List[object]] = {}
        in_hand = {r["tl"] for r in rows if r["tl"] is not None}
        for a, b in self.population(fact, r_from, r_to, only=in_hand, equals=want):
            by_from.setdefault(a, []).append(b)
        out = []
        var = part.target.var if isinstance(part.target, cq.TypeSpec) else None
        determined = r_from in self.unique_roles     # one to-value per from-instance
        for r in rows:
            matched = False
            if bang is not None:
                want = self.constant(bang, r)
            for nxt in by_from.get(r["tl"], ()) if r["tl"] is not None else ():
                if want is not None and not _eq(nxt, want):
                    continue
                r2 = dict(r)
                r2["tl"] = nxt
                # 14b: what determines this value, if anything does. The from-instance when
                # the from-role is unique; otherwise nothing, and the value is its own row's.
                r2["_det:tl"] = r["tl"] if determined else None
                if var:
                    r2[var] = nxt
                    r2["_det:" + var] = r2["_det:tl"]
                out.append(r2)
                matched = True
            if not matched and part.optional:
                # 2026 item 2 / section 6.5: OPTIONALLY is the outer read. The row survives
                # with the role unbound, exactly as a LEFT JOIN leaves it.
                r2 = dict(r)
                r2["tl"] = None
                if var:
                    r2[var] = None
                out.append(r2)
        player = self.lex.roles[r_to]["player"]
        if isinstance(part.target, cq.TypeSpec) and part.target.denotation is None \
                and part.target.concept != player and player in self.lex.supertypes(part.target.concept):
            # Item 16, the other half: the step reached the supertype and the query named a
            # subtype of it -- `Patient is of SevereThrombosis` reaches Examination and keeps
            # the severe ones. A node of the subtype, unified on identity with what was reached.
            keep = {_key(x) for x in self.instances(part.target.concept)}
            kept = []
            for r in out:
                if r["tl"] is not None and _key(r["tl"]) in keep:
                    kept.append(r)
                elif part.optional and r["tl"] is None:
                    kept.append(r)
            return kept, part.target.concept
        return out, player

    def _fact_row(self, fact: str, rid: str, reverse: bool = False):
        """(identity, role value) pairs of a fact type's own table -- or (role value,
        identity) with `reverse` -- from the mapping of the objectified fact's identity."""
        key = ("row", fact, rid, reverse)
        if key not in self._pop:
            cm = self.concept_map.get(fact) or self.concept_map.get(self.lex.twin.get(fact, ""))
            rm = self.role_map.get(rid)
            if cm is None or rm is None or rm["table"] != cm["table"]:
                raise Unsupported("a fact type whose identity and role are not one row")
            groups = [rm["columns"], cm["identifyingColumns"]] if reverse \
                else [cm["identifyingColumns"], rm["columns"]]
            self._pop[key] = self._read(cm["table"], groups)
        return self._pop[key]

    def exit_role(self, rows: List[Row], fact: str, role: dict, part: cq.Step):
        """Leave a fact instance by one of its roles: the value that fills it."""
        by_id: Dict[object, object] = {}
        for ident, value in self._fact_row(fact, role["id"]):
            by_id[ident] = value
        var = part.target.var if isinstance(part.target, cq.TypeSpec) else None
        out = []
        for r in rows:
            nxt = by_id.get(r["tl"]) if r["tl"] is not None else None
            if nxt is None:
                if part.optional:
                    r2 = dict(r, tl=None)
                    if var:
                        r2[var] = None
                    out.append(r2)
                continue
            r2 = dict(r, tl=nxt)
            r2["_det:tl"] = r["tl"]                  # one value per fact instance
            if var:
                r2[var] = nxt
                r2["_det:" + var] = r["tl"]
            out.append(r2)
        return out, role["player"]

    def enter_role(self, rows: List[Row], rid: str, part: cq.Step):
        """Enter a fact type by a named role: the position reached is the fact instance."""
        fact = self.lex.role_owner[rid]
        by_value: Dict[object, List[object]] = {}
        for value, ident in self._fact_row(fact, rid, reverse=True):
            by_value.setdefault(value, []).append(ident)
        out = []
        for r in rows:
            for ident in by_value.get(r["tl"], ()) if r["tl"] is not None else ():
                r2 = dict(r, tl=ident)
                r2["_det:tl"] = r["tl"] if rid in self.unique_roles else None
                out.append(r2)
        return out, fact

    def _head_spec(self, node) -> cq.TypeSpec:
        """The TypeSpec a path starts from, or a bare one for its head concept."""
        while isinstance(node, (cq.Seq, cq.Binary, cq.Where, cq.Named, cq.Distinct, cq.SubExpr)):
            if isinstance(node, cq.Seq):
                node = node.parts[0] if node.parts else None
            elif isinstance(node, cq.Binary):
                node = node.left
            elif isinstance(node, cq.SubExpr):
                node = node.parts[0] if len(node.parts) == 1 else None
            else:
                node = node.path
        if isinstance(node, cq.TypeSpec):
            return node
        raise Unsupported("a union whose left side starts from no type")

    def _identity_related(self, a: str, b: str) -> bool:
        """Do a and b share an identity -- one a subtype of the other -- rather than being
        joined by a fact type? A subtype named at a node narrows it (2026 item 16)."""
        if a == b:
            return False
        ups = getattr(self.lex, "supertypes", None)
        if ups is None:
            return False
        return a in ups(b) or b in ups(a)

    def narrow(self, rows: List[Row], concept: str, part: cq.Step):
        """Item 16: keep the rows whose tail is an instance of the named type. Widening to a
        supertype keeps everything and only relabels; narrowing to a subtype filters on the
        subtype's own population, which for a derived subtype is its rule evaluated."""
        target = part.target.concept
        ups = self.lex.supertypes
        if target in ups(concept):                      # widening: every instance qualifies
            keep = None
        else:
            keep = {_key(x) for x in self.instances(target)}
        out = []
        for r in rows:
            if r["tl"] is None:
                continue
            if keep is None or _key(r["tl"]) in keep:
                r2 = dict(r)
                if part.target.var:
                    r2[part.target.var] = r["tl"]
                out.append(r2)
            elif part.optional:
                r2 = dict(r)
                r2["tl"] = None
                if part.target.var:
                    r2[part.target.var] = None
                out.append(r2)
        return out, target

    def restrict(self, rows: List[Row], concept: str, part: cq.Filter) -> List[Row]:
        """A bracket restricts the position so far. One that binds a name joins (finding 80);
        one that binds nothing is a semijoin."""
        inner = part.expr
        parts = inner.parts if isinstance(inner, cq.SubExpr) else [inner]
        if len(parts) != 1:
            raise Unsupported("a bracket with several parts")
        fronts = {}
        for r in rows:
            fronts.setdefault(r["tl"], {"hd": r["tl"], "tl": r["tl"]})
        sub, _ = self.eval_any(parts[0], (list(fronts.values()), concept))
        bound = [k for k in (sub[0].keys() if sub else ())
                 if k not in ("hd", "tl") and not k.startswith("_det:")]
        if bound:
            by_hd: Dict[object, List[Row]] = {}
            for s in sub:
                by_hd.setdefault(s["hd"], []).append(s)
            out = []
            for r in rows:
                for s in by_hd.get(r["tl"], ()):
                    r2 = dict(r)
                    r2.update({k: s[k] for k in bound})
                    out.append(r2)
            return out
        keep = {s["hd"] for s in sub}
        return [r for r in rows if r["tl"] in keep]

    def eval_any(self, node, start):
        if isinstance(node, cq.Seq):
            return self.eval_seq(node, start)
        if isinstance(node, cq.TypeSpec):
            return self.head_of(node)
        if isinstance(node, cq.Binary):
            return self.binary(node, start)
        if isinstance(node, cq.Where):
            rows, concept = self.eval_any(node.path, start)
            return [r for r in rows if self.truth(node.condition, r)], concept
        if isinstance(node, cq.Named):
            if isinstance(node.path, (cq.Arith, cq.Constant, cq.VarRef, cq.Call)):
                if start is None:
                    raise Unsupported("a computed value with nothing to compute it over")
                rows = [dict(r) for r in start[0]]
                for r in rows:
                    r[node.name] = self.scalar(node.path, r)
                return rows, start[1]
            rows, concept = self.eval_any(node.path, start)
            for r in rows:
                r[node.name] = r["tl"]
            return rows, concept
        if isinstance(node, cq.Distinct):
            rows, concept = self.eval_any(node.path, start)
            seen, out = set(), []
            for r in rows:
                k = tuple(sorted((k, _key(v)) for k, v in r.items()))
                if k not in seen:
                    seen.add(k)
                    out.append(r)
            return out, concept
        if isinstance(node, cq.Compare):
            # A comparison written into a path -- `has EmployeeSalary > 50000` -- restricts
            # the path's tail (section 6.4's value restriction, spelled with an operator).
            # The right side is a scalar, so it may name something bound earlier.
            rows, concept = self.eval_any(node.left, start)
            kept = []
            for r in rows:
                other = self.scalar(node.right, r)
                if r["tl"] is not None and other is not None and _cmp(node.op, r["tl"], other):
                    kept.append(r)
            return kept, concept
        if isinstance(node, cq.SubExpr):
            if len(node.parts) != 1:
                raise Unsupported("a parenthesised expression with several parts")
            return self.eval_any(node.parts[0], start)
        raise Unsupported("node of kind %s" % type(node).__name__)

    def binary(self, node: cq.Binary, start):
        """Fr operators (section 6.4): AND ALSO intersects fronts, BUT NOT subtracts them.
        Both operands begin at the same head, so the right is evaluated from the left's."""
        left, concept = self.eval_any(node.left, start)
        head_concept = start[1] if start is not None else self._head_concept(node.left)
        if isinstance(node.right, cq.Named) and isinstance(node.right.path, cq.Aggregate) \
                and node.right.path.group_by:
            return self.in_block(left, node.right.path, node.right.name, head_concept), concept
        if isinstance(node.right, cq.Named) and isinstance(node.right.path, cq.Aggregate):
            # An ungrouped aggregate beside the rows: over the block's own rows when it
            # aggregates a name the block bound (one figure, on every row), otherwise a bag
            # of its own evaluated under each row, which is what a `!x` inside it reads.
            agg = node.right.path
            if agg.windowed or agg.ordering or agg.limit:
                raise Unsupported("WITHIN / an ordered bag beside the rows")
            if isinstance(agg.path, cq.VarRef) or agg.over:
                pairs = [pr for r in left for pr in self._agg_pairs(agg, r, head_concept)]
                figure = self._reduce(agg.func, self._distinct(agg), pairs)
                return [dict(r, **{node.right.name: figure}) for r in left], concept
            return [dict(r, **{node.right.name: self.scalar(agg, r)}) for r in left], concept
        if isinstance(node.right, cq.Named) and \
                isinstance(node.right.path, (cq.Arith, cq.Constant, cq.VarRef, cq.Call)):
            # A computed element is evaluated over the left's rows, bindings and all.
            fronts = [dict(r, tl=r["hd"]) for r in left]
        elif node.op == "or":
            # A union's right side ranges over what the *left started from*, not over what
            # the left admitted -- from the left's survivors, `[has SM: 'negative'] OR
            # OTHERWISE [has SM: '0']` could only re-admit the negatives (finding 116).
            if start is not None:
                fronts = [dict(r, tl=r["hd"]) for r in start[0]]
            else:
                # the left's own head, variable and all: `Employee v1 [...] OR OTHERWISE
                # has ...` binds v1 on both sides, and a bag may count it
                fronts, _ = self.head_of(self._head_spec(node.left))
        else:
            heads = {}
            for r in left:
                heads.setdefault(r["hd"], {"hd": r["hd"], "tl": r["hd"]})
            fronts = list(heads.values())
        # the right operand's implicit head is the head the left started from
        right, _ = self.eval_any(node.right, (fronts, head_concept))
        if node.op == "and":
            bound = [k for k in (right[0].keys() if right else ())
                     if k not in ("hd", "tl") and not k.startswith("_det:")]
            if isinstance(node.right, cq.SubExpr) and not bound:
                # Section 6.7: a bracketed operand is a *restriction* of the head. It keeps the
                # left rows whose head it admits and multiplies nothing -- the compiler emits
                # EXISTS for it. A bracket that binds a name joins instead (finding 80), and
                # falls through to the merge below.
                keep = {_key(r["hd"]) for r in right}
                return [l for l in left if _key(l["hd"]) in keep], concept
            by_hd: Dict[object, List[Row]] = {}
            for r in right:
                by_hd.setdefault(r["hd"], []).append(r)
            out = []
            for l in left:
                for r in by_hd.get(l["hd"], ()):
                    merged = dict(l)
                    merged.update({k: v for k, v in r.items()
                                   if k not in ("hd", "tl") and (not k.startswith("_det:")
                                                                 or k not in merged)})
                    out.append(merged)
            return out, concept
        if node.op == "butnot":
            gone = {r["hd"] for r in right}
            return [l for l in left if l["hd"] not in gone], concept
        if node.op == "or":
            # Fr-or is the union of the two relations: every row either side admits, once.
            # In a bracket only the heads matter and the compiler's EXISTS ... OR EXISTS
            # is this set; at the top level each row keeps the bindings its own side made.
            # A front expression's rows stand at the head: an alternative written as a bare
            # path (`OR OTHERWISE has EmployeeSalary v1 WHERE ...`) had moved the position
            # to the salary, and the step after the union found nothing there.
            seen, out = set(), []
            for r in left + right:
                r = dict(r, tl=r["hd"])
                k = tuple(sorted((k, _key(v)) for k, v in r.items()))
                if k not in seen:
                    seen.add(k)
                    out.append(r)
            return out, concept
        raise Unsupported("Fr operator %r" % node.op)

    # -- aggregates inside a block (binding-sql92 section 4; 2026 items 28, 29) --------------

    def _group_keys(self, agg: cq.Aggregate, row: Row) -> tuple:
        keys = []
        for k in agg.group_by:
            if isinstance(k, str):
                if k not in row:
                    raise Unsupported("GROUPED BY %r, which is not bound here" % k)
                keys.append(_key(row[k]))
            else:
                keys.append(_key(self.scalar(k, row)))
        return tuple(keys)

    def _agg_pairs(self, agg: cq.Aggregate, row: Row, head_concept: str) -> List[tuple]:
        """The (determinant, value) pairs one row of the block contributes to an aggregate.

        A bound name contributes that row's value. A path (item 17) continues from the row's
        head -- `THE SUM OF s IN Employee has EmployeeSalary s` sums *those* employees' salaries
        -- and may contribute several values, or none.
        """
        if isinstance(agg.path, cq.VarRef):
            return [(row.get("_det:" + agg.path.name), row.get(agg.path.name))]
        if isinstance(agg.path, cq.TypeSpec) and agg.path.var is None and not agg.over:
            # `THE COUNT OF Employee GROUPED BY d`: counting the type counts instances reached
            return [(None, row.get("hd"))]
        cache = self.__dict__.setdefault("_path_cache", {})
        k = id(agg)
        if k not in cache:
            fronts = [{"hd": h, "tl": h} for h in self.instances(head_concept)]
            rows_all, _ = self.eval_any(agg.path, (fronts, head_concept))
            by_hd: Dict[object, List[Row]] = {}
            for r in rows_all:
                by_hd.setdefault(_key(r["hd"]), []).append(r)
            cache[k] = by_hd
        sub = cache[k].get(_key(row["hd"]), [])
        if agg.over:
            return [(r.get("_det:" + agg.over), r.get(agg.over)) for r in sub]
        return [(r.get("_det:tl"), r["tl"]) for r in sub]

    def in_block(self, rows: List[Row], agg: cq.Aggregate, name: str,
                 head_concept: str) -> List[Row]:
        """An aggregate over the rows of the block it sits in.

        `GROUPED BY` collapses the block to one row per group, which cannot happen until every
        aggregate sharing the keys has been seen -- two of them over one key group once, not
        twice (finding 97) -- so a grouped aggregate is *pending* until `query` collapses.
        `WITHIN` reports the group's figure beside every row and changes nothing else. The
        row-relative pair order the window: RANK by the value, descending; PREVIOUS by its key.
        """
        if not agg.windowed:
            self._pending.append({"name": name, "agg": agg, "head": head_concept})
            return rows
        groups: Dict[tuple, List[int]] = {}
        for i, r in enumerate(rows):
            groups.setdefault(self._group_keys(agg, r), []).append(i)
        out = [dict(r) for r in rows]
        for members in groups.values():
            if agg.func == "rank":
                vals = [_sortkey(self._agg_pairs(agg, rows[i], head_concept)[0][1]) for i in members]
                for i, v in zip(members, vals):
                    out[i][name] = 1 + sum(1 for w in vals if w > v)      # SQL RANK: gaps on ties
            elif agg.func == "lag":
                if agg.order_key is None:
                    raise Unsupported("THE PREVIOUS without a BY key")
                ordered = sorted(members, key=lambda i: _sortkey(self.scalar(agg.order_key, rows[i])))
                prev = None
                for i in ordered:
                    out[i][name] = prev
                    prev = self._agg_pairs(agg, rows[i], head_concept)[0][1]
            else:
                figure = self._reduce(agg.func, self._distinct(agg),
                                      [pr for i in members
                                       for pr in self._agg_pairs(agg, rows[i], head_concept)])
                for i in members:
                    out[i][name] = figure
        return out

    def collapse(self, rows: List[Row]) -> List[Row]:
        """Apply the pending GROUPED BY aggregates: one row per group, the keys and every
        aggregate bound, and any other binding kept only where the group pins it to one
        value (finding 82's pinned case, which the compiler computes as MIN)."""
        pending, self._pending = self._pending, []
        if not pending:
            return rows
        keys0 = pending[0]["agg"].group_by
        if any(p["agg"].group_by != keys0 for p in pending):
            raise Unsupported("grouped aggregates over different keys in one block")
        groups: Dict[tuple, List[Row]] = {}
        for r in rows:
            groups.setdefault(self._group_keys(pending[0]["agg"], r), []).append(r)
        out = []
        for members in groups.values():
            g: Row = {}
            for k in members[0]:
                vals = {_key(m.get(k)) for m in members}
                if len(vals) == 1:
                    g[k] = members[0].get(k)
            for p in pending:
                g[p["name"]] = self._reduce(p["agg"].func, self._distinct(p["agg"]),
                                            [pr for m in members
                                             for pr in self._agg_pairs(p["agg"], m, p["head"])])
            out.append(g)
        return out

    def _reduce(self, func: str, distinct: bool, pairs):
        """Reduce (determinant, value) pairs. Section 14b: a value aggregate counts each
        determined value once -- the pairs are deduplicated on their determinant before the
        bag is summed. COUNT is exempt, and MIN and MAX are unchanged by repetition anyway."""
        if self.semantics == "2026" and func in ("sum", "avg"):
            seen, kept = set(), []
            for det, v in pairs:
                if det is None:
                    kept.append(v)
                    continue
                k = _key(det)
                if k not in seen:
                    seen.add(k)
                    kept.append(v)
            vals = kept
        else:
            vals = [v for _, v in pairs]
        vals = [v for v in vals if v is not None]
        if distinct:
            vals = list({_key(v): v for v in vals}.values())
        if func == "count":
            return len(vals)
        if func == "list":
            return json.dumps(vals)
        if not vals:
            return None
        # MIN and MAX are order functions and take text as happily as numbers -- the least
        # gender is 'F' -- where SUM and AVERAGE are arithmetic and need numbers.
        if func == "min":
            return min(vals, key=_sortkey)
        if func == "max":
            return max(vals, key=_sortkey)
        nums = [_num(v) for v in vals]
        if func == "sum":
            return sum(nums)
        if func == "avg":
            return sum(nums) / len(nums)
        raise Unsupported("group function %r" % func)

    def _head_concept(self, node) -> str:
        while True:
            if isinstance(node, cq.TypeSpec):
                return node.concept
            if isinstance(node, cq.Seq):
                node = node.parts[0]
            elif isinstance(node, (cq.Where, cq.Named, cq.Distinct)):
                node = node.path
            elif isinstance(node, cq.Binary):
                node = node.left
            elif isinstance(node, cq.SubExpr):
                node = node.parts[0]
            else:
                raise Unsupported("cannot find the head of %s" % type(node).__name__)

    # -- scalars and conditions -------------------------------------------------------------

    def constant(self, c, row: Optional[Row] = None):
        if isinstance(c, cq.Constant):
            return float(c.lexical) if c.numeric else c.lexical
        if isinstance(c, tuple) and len(c) == 2 and c[0] == "!":
            # B.2's `!x`: the value x is bound to in the enclosing block. A bag's head rows
            # carry the enclosing row's bindings as `!x` (see aggregate); a bracket's rows
            # are the enclosing rows themselves and carry x.
            if row is None:
                raise Unsupported("!%s with no enclosing row" % c[1])
            key = "!" + c[1]
            if key in row:
                return row[key]
            if c[1] in row:
                return row[c[1]]
            raise Unsupported("!%s is not bound in the enclosing block" % c[1])
        if isinstance(c, (list, tuple)):
            return tuple(self.constant(x, row) for x in c)
        raise Unsupported("a denotation of kind %s" % type(c).__name__)

    def scalar(self, node, row: Row):
        if isinstance(node, cq.Constant):
            return self.constant(node)
        if isinstance(node, cq.Aggregate):
            return self.aggregate(node, row)     # a whole-query scalar, item 10; or correlated
        if isinstance(node, cq.SubExpr) and len(node.parts) == 1:
            return self.scalar(node.parts[0], row)
        if isinstance(node, cq.VarRef):
            if node.name not in row:
                raise Unsupported("%r is not bound here" % node.name)
            return row[node.name]
        if isinstance(node, cq.Arith):
            a, b = self.scalar(node.left, row), self.scalar(node.right, row)
            if a is None or b is None:
                return None
            a, b = float(a), float(b)
            # The parser names the operation, not the symbol; and division is real
            # (conquer-2026 item 1), which float division already is. Dispatch by branch,
            # not by a dict of expressions: that evaluated every operation for every node,
            # and 185000 ** 1000 overflowed on a query that only divided.
            try:
                if node.op == "add":
                    return a + b
                if node.op == "subtract":
                    return a - b
                if node.op == "multiply":
                    return a * b
                if node.op == "divide":
                    return a / b if b else None
                if node.op == "power":
                    return a ** b
            except (OverflowError, ZeroDivisionError, ValueError):
                return None
            raise Unsupported("arithmetic %r" % node.op)
        if isinstance(node, cq.Call):
            return self.call(node, row)
        if isinstance(node, cq.Conditional):
            return (self.scalar(node.then, row) if self.truth(node.condition, row)
                    else (self.scalar(node.otherwise, row) if node.otherwise is not None
                          else None))
        raise Unsupported("scalar of kind %s" % type(node).__name__)

    # -- the function library, as SQLite computes it ----------------------------------------

    def call(self, node: cq.Call, row: Row):
        """A scalar function, with SQLite's answers: 1-based substr and instr, round half away
        from zero, integer division truncating toward zero, and NULL in gives NULL out."""
        name = node.name.casefold()
        args = [self.scalar(a, row) for a in node.args]
        if name == "if":
            return args[1] if self.truth(node.args[0], row) else (args[2] if len(args) > 2 else None)
        if any(a is None for a in args):
            return None
        try:
            if name == "round":
                x, d = float(args[0]), int(args[1]) if len(args) > 1 else 0
                q = 10.0 ** d
                return math.floor(abs(x) * q + 0.5) / q * (1 if x >= 0 else -1)
            if name == "abs":
                return abs(float(args[0]))
            if name == "length":
                return len(str(args[0]))
            if name == "upper":
                return str(args[0]).upper()
            if name == "lower":
                return str(args[0]).lower()
            if name == "substr":
                s, start = str(args[0]), int(args[1])
                count = int(args[2]) if len(args) > 2 else None
                i = start - 1 if start > 0 else len(s) + start
                return s[i:] if count is None else s[i:i + count]
            if name == "instr":
                return str(args[0]).find(str(args[1])) + 1
            if name == "concat":
                return "".join(str(a) for a in args)
            if name == "replace":
                return str(args[0]).replace(str(args[1]), str(args[2]))
            if name == "sqrt":
                return math.sqrt(float(args[0]))
            if name in ("power", "pow"):
                return float(args[0]) ** float(args[1])
            if name == "ln":
                return math.log(float(args[0]))
            if name == "exp":
                return math.exp(float(args[0]))
            if name == "div":
                a, b = float(args[0]), float(args[1])
                return float(int(a / b)) if b else None
            if name in ("year", "month", "day"):
                d = _iso(str(args[0]))
                if d is None:
                    return None
                return float({"year": d[0], "month": d[1], "day": d[2]}[name])
            if name == "days_between":
                a, b = _iso(str(args[0])), _iso(str(args[1]))
                if a is None or b is None:
                    return None
                return float((datetime.date(*a) - datetime.date(*b)).days)
            if name == "today":
                return datetime.date.today().isoformat()
        except (ValueError, OverflowError, ZeroDivisionError):
            return None
        raise Unsupported("function %r" % node.name)

    def truth(self, cond, row: Row) -> bool:
        if isinstance(cond, cq.Call):
            # a boolean function stands alone as a condition (2026 item 5)
            name = cond.name.casefold()
            args = [self.scalar(a, row) for a in cond.args]
            if any(a is None for a in args):
                return False
            a, b = str(args[0]), str(args[1]) if len(args) > 1 else ""
            # Case-folded, because ConQuer's string predicates ignore case on every backend
            # (finding 130). These compared case-sensitively while the SQL they are checked
            # against went through SQLite's LIKE, which does not -- so the compiler and its
            # own oracle disagreed, and no corpus query happened to differ in case.
            if name == "starts_with":
                return a.casefold().startswith(b.casefold())
            if name == "ends_with":
                return a.casefold().endswith(b.casefold())
            if name == "contains":
                return b.casefold() in a.casefold()
            if name == "like":
                return _like(a, b)
            raise Unsupported("boolean function %r" % cond.name)
        if isinstance(cond, cq.Compare):
            a, b = self.scalar(cond.left, row), self.scalar(cond.right, row)
            if a is None or b is None:
                return False                       # SQL's three-valued logic: unknown is not true
            return _cmp(cond.op, a, b)
        if isinstance(cond, cq.Logical):
            vals = [self.truth(o, row) for o in cond.operands]
            return all(vals) if cond.op == "and" else any(vals) if cond.op == "or" \
                else _unsupported("logical %r" % cond.op)
        if isinstance(cond, cq.Not):
            return not self.truth(cond.operand, row)
        raise Unsupported("condition of kind %s" % type(cond).__name__)

    # -- a whole query ----------------------------------------------------------------------

    def query(self, q: cq.Query) -> List[tuple]:
        # The memo of bags evaluated under a row is keyed by the AST node's identity, which
        # is only stable within one query: a later query's node can land on a freed address.
        # Cleared before *any* branch -- a whole-query scalar goes through the memo too, and
        # clearing it after that branch left one entry behind for the next query to inherit.
        self._corr = {}
        if isinstance(q.body, (cq.Aggregate, cq.Arith)):
            if q.ordering or q.limit:
                raise Unsupported("an ordered or cut scalar")
            return [(self.scalar(q.body, {}),)]
        if q.body is None:
            # `LIST <scalar>, <scalar>`: each a whole-query figure, on one row (item 10)
            if not q.projections or any(expr is None for _, expr in q.projections):
                raise Unsupported("a projection with no path and nothing computed")
            return [tuple(self.scalar(expr, {}) for _, expr in q.projections)]
        self._pending = []
        self.tied_cut = False
        rows, _ = self.eval_any(q.body, None)
        rows = self.collapse(rows)
        # Order (B.2's order specification), then cut (2026 item 8). Sorting a multiset does
        # not change it; a cut after a sort is the first n of that order. Ties are left in
        # the order the population came in, which is the same "no defined answer" the corpus
        # notes for ORDER BY ... LIMIT 1 (finding 83).
        def sort_value(item, r):
            if item.expr is not None:
                return _sortkey(self.scalar(item.expr, r))        # `ORDERED WITH abs(lon)`
            return _sortkey(r.get(item.key))
        for item in reversed(q.ordering):
            if item.end is not None or (item.key is None and item.expr is None):
                raise Unsupported("a computed or unnamed sort key")
            if item.expr is None and any(item.key not in r for r in rows):
                raise Unsupported("sort key %r is not bound on every row" % item.key)
            rows.sort(key=lambda r, it=item: sort_value(it, r), reverse=(item.direction == "desc"))
        if q.limit is not None:
            lo, hi = q.limit.offset, q.limit.offset + q.limit.count
            if q.ordering and self.semantics == "2026" and _has_distinct(q.body) and q.projections:
                # `LIST id FROM DISTINCT ... ORDERED WITH p ... THE FIRST 4` orders a
                # projection that drops p: which p stands for an id is undefined, SQL keeps
                # an arbitrary one, and the cut has no defined answer (finding 83's kind).
                shown = {name for name, _ in q.projections}
                if any(it.expr is not None or it.key not in shown for it in q.ordering):
                    self.tied_cut = True
            if q.ordering and q.limit.per is None:
                def sk(r):
                    return tuple(sort_value(i, r) for i in q.ordering)
                if 0 < hi < len(rows) and sk(rows[hi - 1]) == sk(rows[hi]):
                    self.tied_cut = True
                if 0 < lo < len(rows) and sk(rows[lo - 1]) == sk(rows[lo]):
                    self.tied_cut = True
            if q.limit.per is None:
                rows = rows[lo:hi]
            else:
                # 2026 item 8: the first n within each partition, in the query's order.
                seen: Dict[object, int] = {}
                kept = []
                for r in rows:
                    k = _key(r.get(q.limit.per))
                    n = seen.get(k, 0)
                    seen[k] = n + 1
                    if lo <= n < hi:
                        kept.append(r)
                rows = kept
        if not q.projections:
            out = [(r["tl"],) for r in rows]
        else:
            out = [tuple(self.scalar(expr, r) if expr is not None else r.get(name)
                         for name, expr in q.projections) for r in rows]
        if self.semantics == "2026" and _has_distinct(q.body):
            # conquer-2026 section 14a: DISTINCT anywhere in the body means distinct
            # projected rows. Under P it would already have applied where it was written.
            seen_rows, dedup = set(), []
            for t in out:
                k = tuple(_key(v) for v in t)
                if k not in seen_rows:
                    seen_rows.add(k)
                    dedup.append(t)
            out = dedup
        return out

    def aggregate(self, agg: cq.Aggregate, row: Optional[Row] = None):
        if agg.group_by or agg.windowed or agg.ordering or agg.limit:
            raise Unsupported("GROUPED BY / WITHIN / an ordered bag")
        if row is not None and _has_bang(agg.path):
            return self._correlated(agg, row)
        if row is not None:
            # A bag that reads nothing of the enclosing row is the same figure on every row:
            # `WHERE r = (THE MAXIMUM User has UserReputation)` under 90k posts is one
            # evaluation, not 90k.
            key = ("plain", id(agg))
            if key not in self._corr:
                self._corr[key] = self.aggregate(agg)
            return self._corr[key]
        rows, _ = self.eval_any(agg.path, None)
        pairs = [(r.get("_det:" + agg.over), r.get(agg.over)) if agg.over
                 else (r.get("_det:tl"), r["tl"]) for r in rows]
        return self._reduce(agg.func, self._distinct(agg), pairs)

    def _correlated(self, agg: cq.Aggregate, row: Row):
        """A bag that reads `!x` under an enclosing row. Evaluating it once per row is the
        whole bag times the rows -- 40k users by 90k posts -- and burned every budget it
        was given. So it is evaluated once, with each `!x` turned into a binding named !x,
        its rows grouped by those bindings, and each enclosing row looks its group up: the
        decorrelation a SQL planner does, and the same relation."""
        key = id(agg)
        if key not in self._corr:
            names: List[Tuple[str, str]] = []
            rows, _ = self.eval_any(_debang(agg.path, names), None)
            groups: Dict[tuple, list] = {}
            for r in rows:
                if any(r.get(rk) is None for _, rk in names):
                    continue                          # a restriction on nothing admits nothing
                k = tuple(_key(r.get(rk)) for _, rk in names)
                pair = (r.get("_det:" + agg.over), r.get(agg.over)) if agg.over \
                    else (r.get("_det:tl"), r["tl"])
                groups.setdefault(k, []).append(pair)
            self._corr[key] = (names, groups)
        names, groups = self._corr[key]
        for x, _ in names:
            if x not in row:
                raise Unsupported("!%s is not bound in the enclosing block" % x)
        k = tuple(_key(row[x]) for x, _ in names)
        return self._reduce(agg.func, self._distinct(agg), groups.get(k, []))

    def _distinct(self, agg: cq.Aggregate) -> bool:
        """Is this aggregate over distinct values? Its own DISTINCT, or -- under 2026's
        section 14a, DISTINCT anywhere in a body meaning distinct projected rows -- a
        DISTINCT written inside the bag it ranges over: `THE COUNT OF v1 IN (DISTINCT Atom v1
        ...)` is the normal form of `THE COUNT OF DISTINCT Atom [...]`, and read without
        this it counted the bag's rows (2,982) where the query it came from counts atoms (97)."""
        if agg.distinct:
            return True
        return self.semantics == "2026" and agg.path is not None and _has_distinct(agg.path)


def _debang(node, names: list):
    """A copy of `node` in which every `!x` denotation is a binding named `!x` (or the
    variable already there); `names` collects (x, the row key it is bound under). A nested
    aggregate is left alone: a `!x` inside it is *its* correlation, to the row this bag
    makes, and is decorrelated when that row is in hand."""
    if isinstance(node, cq.Aggregate):
        return node
    if isinstance(node, cq.TypeSpec):
        d = node.denotation
        if isinstance(d, tuple) and len(d) == 2 and d[0] == "!":
            rk = node.var or "!" + d[1]
            if (d[1], rk) not in names:
                names.append((d[1], rk))
            return dataclasses.replace(node, denotation=None, var=rk)
        return node
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {}
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if isinstance(v, list):
                nv = [_debang(x, names) if dataclasses.is_dataclass(x) else x for x in v]
                if any(a is not b for a, b in zip(nv, v)):
                    changes[f.name] = nv
            elif dataclasses.is_dataclass(v) and not isinstance(v, type):
                nv = _debang(v, names)
                if nv is not v:
                    changes[f.name] = nv
        return dataclasses.replace(node, **changes) if changes else node
    return node


def _has_bang(node) -> bool:
    """Does a `!x` denotation occur in this path, outside any nested aggregate?"""
    if isinstance(node, cq.Aggregate):
        return False
    if isinstance(node, cq.TypeSpec):
        d = node.denotation
        return isinstance(d, tuple) and len(d) == 2 and d[0] == "!"
    for attr in ("path", "left", "right", "expr", "target", "condition"):
        child = getattr(node, attr, None)
        if child is not None and not isinstance(child, (str, int, float)) and _has_bang(child):
            return True
    for attr in ("parts",):
        for child in getattr(node, attr, None) or []:
            if _has_bang(child):
                return True
    return False


def _has_distinct(node) -> bool:
    if isinstance(node, cq.Distinct):
        return True
    for attr in ("path", "left", "right", "expr"):
        child = getattr(node, attr, None)
        if child is not None and _has_distinct(child):
            return True
    for attr in ("parts",):
        for child in getattr(node, attr, None) or []:
            if _has_distinct(child):
                return True
    return False


_NUM_PREFIX = re.compile(r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SLASH_ISO = re.compile(r"^(\d{4})/(\d{2})/(\d{2})")
_DAY_FIRST = re.compile(r"^(\d{1,2})/(\d{2})/(\d{4})")


def _iso(text: str):
    """(year, month, day) from ISO text, or from the slashed shapes the lenient date
    functions accept -- the same three as reverse/derive.py's LENIENT, day-first."""
    for pat, order in ((_ISO, (1, 2, 3)), (_SLASH_ISO, (1, 2, 3)), (_DAY_FIRST, (3, 2, 1))):
        m = pat.match(text.strip())
        if m:
            try:
                y, mo, d = (int(m.group(i)) for i in order)
                datetime.date(y, mo, d)
                return (y, mo, d)
            except ValueError:
                return None
    return None


def _like(text: str, pattern: str) -> bool:
    """SQL LIKE: % any run, _ one character, case-insensitive as SQLite has it."""
    rx = "^" + "".join(".*" if c == "%" else "." if c == "_" else re.escape(c)
                       for c in pattern) + "$"
    return re.match(rx, text, re.I | re.S) is not None


def _unsupported(msg):
    raise Unsupported(msg)


def _sortkey(v):
    """Nulls first, then numbers, then text -- SQLite's collation order for a mixed column."""
    if v is None:
        return (0, 0)
    try:
        return (1, float(v))
    except (TypeError, ValueError):
        return (2, str(v))


def _key(v):
    return round(v, 6) if isinstance(v, float) else v


def _eq(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def _num(v) -> float:
    """SQLite's arithmetic reading of a value: a number, the numeric prefix of text
    ('18:56.516' is 18.0, as SUM and AVG take it), and 0 for text with none."""
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM_PREFIX.match(str(v))
    return float(m.group(0)) if m else 0.0


def _cmp(op, a, b) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        pass
    if isinstance(a, str) != isinstance(b, str):
        # SQLite's type order when a text value meets a number: the number is less
        a, b = (1, 0) if isinstance(a, str) else (0, 1)
    return {"=": a == b, "<>": a != b, "!=": a != b, "<": a < b, "<=": a <= b,
            ">": a > b, ">=": a >= b}[op]
