#!/usr/bin/env python3
"""Section 8 of the report: PVerb, from a path expression back to ConQuer text.

The report's Figure 1 has two arrows between ConQuer-92 and the path-expression level:
*parsing* down, *verbalisation* up. The stored, manipulated artifact is the path expression;
ConQuer text is its external form, and §8's rules [V1]-[V46] define `PVerb`, which renders a
path expression as ConQuer in a **normalised** form. §10: "a non-ambiguous subset of ConQuer-92
which is used to verbalise path-expressions in a normalised form (basically what happens
already), and a more liberal ConQuer-92 language from a user's point of view."

This is that arrow. The input is the lowered block -- our path-expression level -- and the
output is ConQuer with every step explicit, every ambiguity resolved, every abbreviation
expanded, every unnamed thing that is referred to given a name. It is what the compiler
*understood*, in the language the author wrote, which is the one form an author can compare
against what they meant. `--explain` says the same in English; this says it in ConQuer.

Where the rules map:

    §8.2  types, denotations     a node is its type name; an equality with a constant on a
                                 node nothing else refers to folds back into `Type: 'v'`;
                                 a node unified with one outside its block is `Type: !x`
    §8.3  concatenation          enter + exit through a fact type is one mix-fix step
    §8.4  mix-fix                the verb text is read from the fact type's reading, between
                                 the slots of the two roles used ([V14]), a hyphen-bound
                                 adjective included; a ring fact type whose only reading is
                                 the placeholder `has` is entered and left by role name
                                 ([V15]-[V16], B.2), since `Atom has Atom` says nothing
    §8.5  unary                  DISTINCT
    §8.6  binary (Fr)            a sub-block with `_frOp` is AND ALSO / OR OTHERWISE / BUT NOT
    §8.7  sub-expressions        a step off the line of the path is a filter `[ ... ]`
    §8.9  selection              WHERE
    §8.10 group functions        THE COUNT OF ... GROUPED BY ... ([V29]), named with AS;
                                 WITHIN for the uncollapsed form (conquer-2026 §11);
                                 an aggregate over a path names what it aggregates only when
                                 that is not the path's last node (`THE SUM OF s IN ...`)
    §8.11 gathering              an outer-joined step is OPTIONALLY -- the normalised form of
                                 both OPTIONALLY and a confluence element
    §8.13 scalar expressions     infix by operatorSymbol, else a call
    §8.14 conditions             comparisons, AND/OR/NOT, SOME, the set comparators
    [P56]-[P59]                  LIST, ORDERED WITH; and this project's THE FIRST n

What makes the output *normalised* rather than merely valid: a path is linear, so a node with
two continuations shows one on the line and the other as a filter; the `AND ALSO` of the
source survives only at the head, where it is the Fr operator it names; anything referred to
by a later clause has a name, and the name is the column's where the author gave one.

Compare `--explain`: that produces English of its own wording and is not §8. This produces
ConQuer, and the round-trip test (`tests/test_normalise.py`) is the proof it is faithful --
the normalised text is re-parsed, re-lowered and re-run, and must return the same rows.

Two things Clifford Heath's CQL verbaliser (activefacts-cql, `verbalise_query`) does that
this one does not attempt: contract successive readings into one sentence when the last
noun phrase is the next reading's first placeholder, and choose among several readings of a
fact type for the smoother join. Normalised ConQuer wants one step per fact type and the
first reading, so neither applies. Two things it does that CQL's leaves as `raise`: aggregates
and optional steps.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

SET_CMP_WORDS = {"subset": "WHICH ARE ALL IN", "superset": "THAT INCLUDES ALL",
                 "match": "EQUALS", "properSubset": "IS A PROPER SUBSET OF",
                 "properSuperset": "IS A PROPER SUPERSET OF", "disjoint": "IS DISJOINT FROM"}
AGG_WORDS = {"count": "THE COUNT OF", "sum": "THE SUM OF", "min": "THE MINIMUM",
             "max": "THE MAXIMUM", "avg": "THE AVERAGE", "median": "THE MEDIAN",
             "stddev": "THE STANDARD DEVIATION", "variance": "THE VARIANCE",
             "object": "THE OBJECT OF"}
DISTINCT_AGG_WORDS = {"count": "THE DISTINCT COUNT OF", "sum": "THE DISTINCT SUM OF",
                      "list": "THE DISTINCT LIST OF"}
FR_WORDS = {"and": "AND ALSO", "or": "OR OTHERWISE"}
LOGIC_WORDS = {"and": "AND", "or": "OR", "xor": "EXCLUSIVE OR", "implies": "IMPLIES",
               "iff": "IFF"}


def node_source(v) -> Optional[str]:
    return v["node"] if isinstance(v, dict) and v.get("kind") == "node" else None


def written_names(thing) -> set:
    """Every variable name the lowered query already carries, at any depth -- sub-blocks,
    condition blocks and the bag blocks that hang off aggregates included."""
    found = set()
    if isinstance(thing, dict):
        if isinstance(thing.get("name"), str) and "id" in thing:
            found.add(thing["name"])
        for v in thing.values():
            found |= written_names(v)
    elif isinstance(thing, list):
        for v in thing:
            found |= written_names(v)
    return found


class Normaliser:
    def __init__(self, index, block=None):
        self.ix = index
        self.names: Dict[str, str] = {}          # node id (or calc:id) -> variable name
        self.fresh_n = 0
        # Names the query already uses. A generated `v2` that collides with a written `v2`
        # somewhere else in the query is two things called one thing, and the normal form
        # stops being a fixed point: normalising it again renumbers from a different start.
        self.taken: set = set(written_names(block)) if block is not None else set()

    # -- names ---------------------------------------------------------------------------

    def cname(self, concept: str) -> str:
        return self.ix.concepts.get(concept, {}).get("name", concept.split(".")[-1])

    def name_for(self, block: dict, nid: str) -> Optional[str]:
        """The variable a node is called, if it has or has been given one."""
        if nid in self.names:
            return self.names[nid]
        for n in block.get("nodes", []):
            if n["id"] == nid and n.get("name"):
                self.names[nid] = n["name"]
                return n["name"]
        return None

    def ensure_name(self, block: dict, nid: str) -> str:
        """§8's VNm: anything referred to has to be called something."""
        name = self.name_for(block, nid)
        if name is None:
            name = self.fresh()
            self.names[nid] = name
        return name

    def fresh(self, prefix="v") -> str:
        while True:
            self.fresh_n += 1
            name = "%s%d" % (prefix, self.fresh_n)
            if name not in self.taken:
                self.taken.add(name)
                return name

    def calc_name(self, block, cid) -> str:
        """A grouped aggregate is referred to by name: the column's if it is projected,
        else a fresh one, the same each time it is mentioned."""
        key = "calc:" + cid
        if key in self.names:
            return self.names[key]
        for p in block.get("projections", []):
            if p["source"].get("kind") == "calculation" and p["source"]["calculation"] == cid:
                self.names[key] = p["name"]
                return p["name"]
        self.names[key] = self.fresh("c")
        return self.names[key]

    # -- structure -----------------------------------------------------------------------

    @classmethod
    def referenced(cls, block: dict) -> set:
        """Node ids that something other than this block's own steps mentions: they need
        names. A nested block refers to the enclosing one through its unifications and
        through the steps it takes from outside -- except a sub-block's point of attachment,
        which the enclosing text supplies by position."""
        found = set()

        def walk(x, sub=False):
            if isinstance(x, dict):
                if x.get("nodeType") == "block":
                    own = {n["id"] for n in x.get("nodes", [])}
                    skip = cls.attachment(x)[0] if sub else None
                    for st in x.get("steps", []):
                        if st["from"] not in own and st["from"] != skip:
                            found.add(st["from"])       # a step taken from outside
                    for u in x.get("unifications", []):
                        found.update(n for n in u["nodes"] if n != skip)
                    for k, v in x.items():
                        if k not in ("nodes", "steps", "unifications"):
                            walk(v, k == "subBlocks")
                    return
                if x.get("kind") == "node":
                    found.add(x["node"])
                for k, v in x.items():
                    walk(v, k == "subBlocks")
            elif isinstance(x, (list, tuple)):
                for v in x:
                    walk(v, sub)

        for k, v in block.items():
            if k not in ("nodes", "steps", "unifications"):
                walk(v, k == "subBlocks")
        for calc in block.get("calculations", []):
            ctx = (calc.get("aggregation") or {}).get("context")
            if isinstance(ctx, list):
                found.update(c for c in ctx if isinstance(c, str))
        return found

    @staticmethod
    def attachment(sub: dict) -> Tuple[Optional[str], Optional[str]]:
        """(the enclosing node a nested block continues from, and the block's own node
        unified with it when that is how it attaches)."""
        own = {n["id"] for n in sub.get("nodes", [])}
        for st in sub.get("steps", []):
            if st["from"] not in own:
                return st["from"], None
        targets = {st["to"] for st in sub.get("steps", [])}
        for u in sub.get("unifications", []):
            outer = [n for n in u["nodes"] if n not in own]
            inner = [n for n in u["nodes"] if n in own and n not in targets]
            if outer and inner:
                # the block starts at its own copy of the enclosing node; a unification with
                # a node reached by a step is a `Type: !x` denotation instead
                return outer[0], inner[0]
        return None, None

    @staticmethod
    def is_grouped(calc) -> bool:
        agg = calc.get("aggregation")
        if "_group" in calc:
            return True                    # regrouped by the fan-out check: printed as written
        return isinstance(agg, dict) and agg.get("context") not in (None, "universal") \
            and calc.get("_block") is None

    def linear(self, block: dict) -> bool:
        """One path: everything reachable from one root, no grouped aggregate, no Fr
        operand. Such a block is an <information descriptor> on its own."""
        nodes = [n["id"] for n in block.get("nodes", [])]
        targets = {st["to"] for st in block.get("steps", [])}
        roots = [n for n in nodes if n not in targets]
        outer = self.attachment(block)[0]
        if outer is not None:
            roots = [r for r in roots if r != outer]
        if len(roots) > (0 if outer else 1):
            return False
        if any(self.is_grouped(c) for c in block.get("calculations", [])):
            return False
        return not any(s.get("_frOp") or s.get("negated") for s in block.get("subBlocks", []))

    # -- readings ------------------------------------------------------------------------

    def verb_between(self, fact: dict, role_in: str, role_out: str) -> str:
        """[V14]: the reading text between the two roles' slots."""
        for verb, a, b in self.ix.reading_slots(fact):
            if a == role_in and b == role_out:
                return verb
        for verb, a, b in self.ix.reading_slots(fact):
            if a == role_out and b == role_in:
                # the reading runs the other way: the lexicon's inverse of its verb
                inverse = getattr(self.ix, "_inverse_of", lambda v: None)(verb)
                return inverse or verb
        return "has"

    def verb_into(self, fact: dict, role_in: str) -> str:
        """The verb after the slot of the role a step enters by; entering at a reading's
        later slot, the inverse of the verb before it."""
        for verb, a, _b in self.ix.reading_slots(fact):
            if a == role_in:
                return verb
        for verb, _a, b in self.ix.reading_slots(fact):
            if b == role_in:
                inverse = getattr(self.ix, "_inverse_of", lambda v: None)(verb)
                return inverse or verb
        return "has"

    def verb_before(self, fact: dict, role_out: str) -> str:
        """The verb before the slot of the role a step leaves by."""
        for verb, _a, b in self.ix.reading_slots(fact):
            if b == role_out:
                return verb
        return "has"

    def role_name(self, rid: str) -> str:
        return self.ix.roles.get(rid, {}).get("name") or rid.split(".")[-1]

    @staticmethod
    def generic(verb: str) -> bool:
        """The placeholder reading reverse engineering emits when the schema has no verb.
        On a ring it says nothing about direction."""
        return verb.casefold() in ("has", "is of")

    def nominal(self) -> Optional[str]:
        """The verb part before a role reference is nominal (B.2): `has`, if the model has it."""
        return "has" if "has" in getattr(self.ix, "verbs", {}) else None

    def by_name(self, fact: dict, rid: str) -> bool:
        """Naming the type would not say which role: its player plays another role of the
        same fact type. B.2's <role reference> is the only unambiguous way through."""
        player = self.ix.player(rid)
        return sum(1 for r in fact.get("roles", []) if r.get("player") == player) > 1

    # -- rendering -----------------------------------------------------------------------

    def render(self, block: dict, head: Optional[str] = None, from_parent: bool = False,
               terminal: Optional[str] = None) -> str:
        """A block as a ConQuer descriptor, with WHERE. `head` says which node to start at.
        A nested block continues from a node of its enclosing block, which that block has
        already rendered: with `from_parent` the descriptor starts at the verb. `terminal`
        is the node the descriptor has to end on -- the compared set, the aggregated value
        -- so every other continuation becomes a filter."""
        nodes = {n["id"]: n for n in block.get("nodes", [])}
        steps = block.get("steps", [])
        base = self.referenced({k: v for k, v in block.items() if k != "conditions"})
        ref = base | self.referenced({"conditions": block.get("conditions", [])})
        targets = {st["to"] for st in steps}
        parent = {st["to"]: st["from"] for st in steps}
        if head is None and not from_parent:
            roots = [nid for nid in nodes if nid not in targets]
            head = roots[0] if roots else (next(iter(nodes)) if nodes else None)

        # a grouped aggregate over a path of its own (`THE SUM OF s IN Employee has
        # EmployeeSalary s GROUPED BY d`): that path is a root of this block, and it is
        # rendered inside the aggregate, where it started. When the aggregated node is the
        # root itself the path *is* the argument and needs no name.
        absorbed: Dict[str, dict] = {}
        for calc in block.get("calculations", []):
            # THE RANK OF has no argument: the ranked value is the window's order
            nid = (node_source(calc["arguments"][0])
                   if self.is_grouped(calc) and calc.get("arguments") else None)
            if nid in nodes:
                root = nid
                while root in parent:
                    root = parent[root]
                if root != head and root not in absorbed:
                    absorbed[root] = calc
                    if root == nid:
                        ref.discard(nid)

        # unifications. With a node outside the block the inner node *is* that node:
        # `Type: !x` (B.2), or plainly its name when the inner node is referred to as well.
        # Two nodes of the same block unified share a name.
        # A subtype node unified with a node of its supertype, with nothing of its own, is
        # how lowering says "this instance is a Manager". It is written as the type of the
        # node it narrows -- `is of Manager` -- not as a second root `AND ALSO Manager v1`,
        # which would continue from the head and mean something else.
        narrowed: Dict[str, str] = {}
        merged: set = set()
        moved = targets | {st["from"] for st in steps}
        for u in block.get("unifications", []):
            inner = [n for n in u["nodes"] if n in nodes]
            for b in inner:
                if b in moved or b in ref or b == head or b in merged:
                    continue
                cb = nodes[b].get("concept", "")
                for a in inner:
                    if a == b or a in merged or a in narrowed:
                        continue
                    ca = nodes[a].get("concept", "")
                    if ca != cb and ca in self.ix.supertypes(cb):
                        narrowed[a] = cb
                        merged.add(b)
                        break
        nodes = {k: v for k, v in nodes.items() if k not in merged}

        marks: Dict[str, str] = {}
        for u in block.get("unifications", []):
            if from_parent and head in u["nodes"]:
                continue                        # the attachment: merged below
            inner = [n for n in u["nodes"] if n in nodes]
            outer = [n for n in u["nodes"] if n not in nodes and n not in merged]
            if outer:
                oname = self.ensure_name(block, outer[0])
                for n in inner:
                    if n in ref:
                        self.names[n] = oname
                    else:
                        marks[n] = oname
            elif len(inner) > 1:
                name = self.ensure_name(block, inner[0])
                for n in inner[1:]:
                    self.names[n] = name

        # a denotation folds into its type ([V2]); everything else stays a condition
        denotations: Dict[str, dict] = {n: {"kind": "outer", "name": m} for n, m in marks.items()}
        conditions = []
        for cond in block.get("conditions", []):
            nid = node_source(cond.get("left")) if cond.get("kind") == "compare" else None
            if nid and cond.get("op") == "=" and cond["right"].get("kind") == "constant" \
                    and nid not in denotations \
                    and not self.named_elsewhere(block, nid, base, cond):
                denotations[nid] = cond["right"]
            else:
                conditions.append(cond)
        for nid in nodes:                       # in the block's order: names are stable
            if nid in ref and nid not in denotations:
                self.ensure_name(block, nid)

        enters: Dict[str, List[dict]] = {}
        exits: Dict[str, List[dict]] = {}
        for st in steps:
            (enters if st["kind"] == "enter" else exits).setdefault(st["from"], []).append(st)
        # An Fr operator's sub-block anchored at a node other than the head -- `... OR
        # OTHERWISE b has X`, `... BUT NOT b has X` -- is written at the head, from b's name,
        # since the operator belongs to the head and the descriptor to b.
        attached: Dict[str, List[dict]] = {}
        anchored_ops: List[Tuple[dict, str]] = []
        for sub in block.get("subBlocks", []):
            at = self.attachment(sub)[0]
            if at is not None and at != head and (sub.get("_frOp") == "or" or sub.get("negated")):
                self.ensure_name(block, at)         # written from the node's name, so name it
                anchored_ops.append((sub, at))
                continue
            attached.setdefault(at or "", []).append(sub)

        line = None
        if terminal is not None:
            parent = {st["to"]: st["from"] for st in steps}
            line, x = set(), terminal
            while x is not None and x not in line:
                line.add(x)
                x = parent.get(x)

        ctx = dict(block=block, nodes=nodes, enters=enters, exits=exits, line=line, head=head,
                   denotations=denotations, attached=attached, seen=set(), narrowed=narrowed,
                   entered={st["to"] for st in steps if st["kind"] == "enter"})
        if from_parent and head is not None:
            text = self.node_text(ctx, head, with_type=False)
            for u in block.get("unifications", []):
                if head in u["nodes"]:
                    for inner in u["nodes"]:
                        if inner in nodes and inner not in ctx["seen"]:
                            more = self.node_text(ctx, inner, with_type=False)
                            text = ("%s %s" % (text, more)).strip()
        else:
            fr = []
            if head and any(s.get("_frOp") == "or" for s in attached.get(head, [])):
                # the union's alternatives: BUT NOT and OR OTHERWISE operands, and the AND
                # ALSO operands before the first OR OTHERWISE (the fold's base); an AND ALSO
                # after the union is a filter on its result and stays outside the parentheses
                # the operands of the disjunctive fold, in their written order (lower.py tags
                # them); a sub-block of any other origin is a filter and stays outside
                folds = {s["_frFold"] for s in attached[head] if s.get("_frOp") == "or" and "_frFold" in s}
                fr = sorted((s for s in attached[head] if s.get("_frFold") in folds),
                            key=lambda s: s.get("_frPos", 0))
            if fr:
                # A union at the head -- `(Card BUT NOT [has CardPower] OR OTHERWISE Card
                # [has CardPower: '*']) has CardId id` -- is a front expression the steps
                # continue from. Written after the steps it read as `((Card has CardId id
                # ...) BUT NOT ...) OR OTHERWISE ...`, binding id in one alternative only;
                # the compiler refused the normal form of card_games/346 (finding 117).
                # The alternatives leave the head's bucket first, or they print twice.
                attached[head] = [s for s in attached.get(head, []) if s not in fr]
                # the bare type (and name) of the head, then the head rendered as usual --
                # its own filters and steps -- with the alternatives spliced in between
                bare = dict(ctx, seen=set(), enters={k: v for k, v in enters.items() if k != head},
                            exits={k: v for k, v in exits.items() if k != head},
                            attached=dict(attached, **{head: []}))
                token = self.node_text(bare, head, with_type=True, is_head=True)
                full = self.node_text(ctx, head, with_type=True, is_head=True)
                rest = full[len(token):] if full.startswith(token) else full
                parts = []
                for i, s in enumerate(fr):
                    # each alternative is a restriction of the head, so it is bracketed:
                    # written bare, `(Employee has Department: 'ENG' OR OTHERWISE ...)` moves
                    # the position to the department and the steps after it read from there
                    body = self.render(s, head, from_parent=True)
                    if not body.startswith("["):
                        body = "[%s]" % body
                    word = "BUT NOT" if s.get("negated") else FR_WORDS.get(s.get("_frOp"), "AND ALSO")
                    if s.get("_frPos", 1) == 0:
                        parts.append(body)                   # the fold's base carries no word
                    else:
                        parts.append("%s %s" % (word, body))
                text = ("(%s %s) %s" % (token, " ".join(parts), rest)).strip()
            else:
                text = self.node_text(ctx, head, with_type=True, is_head=True) if head else ""
            if block.get("distinct"):
                text = "DISTINCT " + text
        for sub, at in anchored_ops:
            word = "BUT NOT" if sub.get("negated") else FR_WORDS.get(sub.get("_frOp"), "AND ALSO")
            body = self.render(sub, at, from_parent=True)
            if not text.strip() and not sub.get("negated"):
                # The leftmost operand of a fold supplies the base and its operator is unread
                # (lower.py says so where it sets it). `[A OR OTHERWISE B]` is one filter
                # block whose own first sub-block carries `and`, and writing that word here
                # produced `[AND ALSO A OR OTHERWISE B]`, which does not parse.
                text = "%s %s" % (self.ensure_name(block, at), body) if at else body
                continue
            text = "%s %s %s %s" % (text, word, self.ensure_name(block, at), body)

        # anything not reached from the head: a second root in the same block
        for nid in nodes:
            if nid not in ctx["seen"] and nid not in targets and nid not in absorbed:
                extra = self.node_text(ctx, nid, with_type=True)
                text = "%s AND ALSO %s" % (text, extra) if text else extra

        # grouped aggregates live in the block's calculations and are named with AS
        for calc in block.get("calculations", []):
            if not self.is_grouped(calc):
                continue
            root = next((r for r, c in absorbed.items() if c is calc), None)
            if root is None:
                text += " AND ALSO " + self.grouped_aggregate(block, calc)
                continue
            nid = node_source(calc["arguments"][0])
            path, x = set(), nid
            while x is not None and x not in path:
                path.add(x)
                x = parent.get(x)
            over = self.node_text(dict(ctx, line=path), root, with_type=True)
            if nid != root:
                over = "%s IN %s" % (self.ensure_name(block, nid), over)
            text += " AND ALSO " + self.grouped_aggregate(block, calc, over=over)

        for sub in attached.get("", []):
            text += " " + self.sub_text(sub, head)

        if conditions:
            text += " WHERE " + " AND ".join(self.top(block, c, cond=True) for c in conditions)
        text = text.strip()
        # The leftmost operand of an Fr fold supplies the base and its operator is unread
        # (lower.py says so where it sets it). A block that is nothing but the fold -- which
        # is what `[A OR OTHERWISE B]` lowers to -- would otherwise open with the word:
        # `[AND ALSO A OR OTHERWISE B]`, which does not parse.
        if text.startswith("AND ALSO "):
            text = text[len("AND ALSO "):]
        return text

    def named_elsewhere(self, block, nid, base, cond) -> bool:
        """A node that is projected, ordered by, unified, or in another condition cannot fold
        into a denotation: the reader has to be able to refer to it."""
        if nid in self.names or nid in base:
            return True
        if any(n["id"] == nid and n.get("name") for n in block.get("nodes", [])):
            return True
        others = [c for c in block.get("conditions", []) if c is not cond]
        return nid in self.referenced({"conditions": others})

    def node_text(self, ctx, nid, with_type: bool, is_head: bool = False) -> str:
        """A node and what continues from it: its type (unless the enclosing text has said
        it), its filters, its steps -- one on the line, the rest as filters -- and then the
        Fr operators whose left operand it is."""
        block, nodes, denotations = ctx["block"], ctx["nodes"], ctx["denotations"]
        ctx["seen"].add(nid)
        node = nodes.get(nid, {})
        parts = []
        if with_type:
            t = self.cname(ctx["narrowed"].get(nid) or node.get("concept", "?"))
            if nid in denotations:
                t += ": " + self.constant(denotations[nid])
            name = self.name_for(block, nid)
            if name:
                t += " " + name
            parts.append(t)

        subs = ctx["attached"].get(nid, [])
        # AND ALSO continues from the head, so an `and` sub-block anchored at any other node
        # -- `... AND ALSO b has X` -- is that node's filter: `b [has X]`
        at_head = nid == ctx["head"]
        for sub in subs:
            if not sub.get("_frOp") and not sub.get("negated"):
                parts.append(self.sub_text(sub, nid))
            elif not at_head and sub.get("_frOp") == "and" and not sub.get("negated"):
                parts.append("[%s]" % self.render(sub, nid, from_parent=True))

        legs: List[Tuple[str, bool]] = []          # (text, on the line)
        for st in ctx["enters"].get(nid, []):
            legs.append((self.leg(ctx, st), ctx["line"] is None or st["to"] in ctx["line"]))
        # an objectified fact type at the head of a path is left by its roles, not entered
        if nid not in ctx["entered"]:
            for ex in ctx["exits"].get(nid, []):
                fact = self.ix.concepts.get(self.ix.rel(ex["role"]) or "", {})
                by_name = self.by_name(fact, ex["role"])
                verb = (self.nominal() if by_name else None) or self.verb_before(fact, ex["role"])
                legs.append((self.leg_out(ctx, fact, ex, verb, "", by_name),
                             ctx["line"] is None or ex["to"] in ctx["line"]))

        if ctx["line"] is not None:
            parts += ["[%s]" % t for t, on in legs if not on]
            parts += [t for t, on in legs if on]
        elif is_head:
            # the head: several continuations are the Fr operator §6.2 spells AND ALSO
            if legs:
                parts.append(" AND ALSO ".join(t for t, _ in legs))
        else:
            # any other node -- AND ALSO would continue from the head, not from here -- so
            # only its last continuation stays on the line
            parts += ["[%s]" % t for t, _ in legs[:-1]] + [t for t, _ in legs[-1:]]

        for sub in subs:
            if sub.get("negated") or (sub.get("_frOp") and (at_head or sub["_frOp"] != "and")):
                parts.append(self.sub_text(sub, nid))
        return " ".join(parts)

    def leg(self, ctx, st) -> str:
        """One step: enter a fact type by a role, and leave it by another -- or stop at the
        fact instance when the fact type is objectified and nothing leaves it."""
        block, nodes = ctx["block"], ctx["nodes"]
        fact_node = st["to"]
        fact = self.ix.concepts.get(nodes.get(fact_node, {}).get("concept", ""), {})
        role_in = st["role"]
        prefix = "OPTIONALLY " if st.get("join") == "outer" else ""
        outs = ctx["exits"].get(fact_node, [])
        ctx["seen"].add(fact_node)
        if not outs:
            if self.by_name(fact, role_in):
                # B.2: entered by role name, and the verb part before a role reference is nominal
                stop, verb = self.role_name(role_in), self.nominal() or self.verb_into(fact, role_in)
            else:
                stop, verb = self.cname(nodes[fact_node]["concept"]), self.verb_into(fact, role_in)
            leg = "%s%s %s" % (prefix, verb, stop)
            name = self.name_for(block, fact_node)
            if name:
                leg += " " + name
            return leg + self.trailing(ctx, fact_node)
        extra = ctx["enters"].get(fact_node, [])
        name = self.name_for(block, fact_node)
        if extra or name:
            # An objectified fact instance that is named, or that plays roles of its own
            # (`has Assignment a ... AND ALSO a has AssignmentHours h`): stop at it, hang its
            # own continuations on it as filters, then leave it by its roles. Folding the
            # enter and the exit into one step lost both (finding 40).
            stop = self.cname(nodes[fact_node]["concept"])
            leg = "%s%s %s" % (prefix, self.verb_into(fact, role_in), stop)
            if name:
                leg += " " + name
            for st2 in extra:
                leg += " [%s]" % self.leg(ctx, st2)
            texts = [self.leg_out(ctx, fact, ex, self.verb_before(fact, ex["role"]), "",
                                  self.by_name(fact, ex["role"])) for ex in outs]
            tail = texts[0] if len(texts) == 1 else "%s [%s]" % (texts[0], "] [".join(texts[1:]))
            return leg + " " + tail
        texts = []
        for ex in outs:
            verb = self.verb_between(fact, role_in, ex["role"])
            spell = self.by_name(fact, role_in) and self.generic(verb)
            if spell:
                # a ring fact type whose reading is the placeholder: `Atom has Atom` says
                # nothing, so enter and leave it by role name, B.2's <role reference>. A ring
                # with a reading of its own (`is connected to`, `has manager`) says which way
                # it goes, and the plain step is the normal form.
                verb = "%s %s %s" % (self.verb_into(fact, role_in), self.role_name(role_in), verb)
            texts.append(self.leg_out(ctx, fact, ex, verb, prefix, spell))
        # a fact type left by two roles: the second continuation is a filter on the first
        return texts[0] if len(texts) == 1 else "%s [%s]" % (texts[0], "] [".join(texts[1:]))

    def leg_out(self, ctx, fact, ex, verb, prefix, by_name=False) -> str:
        block, nodes, denotations = ctx["block"], ctx["nodes"], ctx["denotations"]
        to = ex["to"]
        target = self.role_name(ex["role"]) if by_name \
            else self.cname(ctx["narrowed"].get(to) or nodes.get(to, {}).get("concept", "?"))
        leg = "%s%s %s" % (prefix, verb, target)
        if to in denotations:
            leg += ": " + self.constant(denotations[to])
        name = self.name_for(block, to)
        if name and not by_name:
            leg += " " + name
        ctx["seen"].add(to)
        return leg + self.trailing(ctx, to)

    def trailing(self, ctx, nid) -> str:
        rest = self.node_text(ctx, nid, with_type=False)
        return (" " + rest) if rest else ""

    def sub_text(self, sub: dict, at: Optional[str]) -> str:
        """A sub-block: `[ ... ]` for a filter, or an Fr operator."""
        at = at or self.attachment(sub)[0]
        body = self.render(sub, at, from_parent=at is not None)
        op = sub.get("_frOp")
        if sub.get("negated"):
            return "BUT NOT " + body
        if op:
            return "%s %s" % (FR_WORDS.get(op, "AND ALSO"), body)
        return "[%s]" % body

    def nested(self, block: dict, terminal: Optional[str] = None) -> str:
        """A block in a condition or an aggregate: a bag `(LIST ...)` when it projects, else
        a descriptor continuing from the enclosing node it attaches to, if any."""
        if block.get("projections"):
            return "(%s)" % self.query(block)
        outer, _inner = self.attachment(block)
        if outer is None and terminal is not None \
                and not any(n["id"] == terminal for n in block.get("nodes", [])):
            outer = terminal            # the compared set is an enclosing node itself
        if outer is not None:
            name = self.ensure_name(block, outer)
            return ("%s %s" % (name, self.render(block, outer, from_parent=True,
                                                 terminal=terminal))).strip()
        return self.render(block, terminal=terminal)

    # -- values and conditions -------------------------------------------------------------

    def constant(self, v: dict) -> str:
        if v.get("kind") == "outer":
            return "!" + v["name"]
        lex = v.get("lexical", "")
        dt = (v.get("dataType") or {}).get("name")
        numeric = dt in ("numeric", "integer", "decimal", "real", "float") if dt \
            else bool(re.fullmatch(r"-?\d+(\.\d+)?", lex or ""))
        return lex if numeric else "'%s'" % lex.replace("'", "''")

    # §8.13: an expression is bracketed only where the operators' precedence needs it.
    # The levels: 0 a form that runs to the end of the text (IF ... ELSE, an aggregate with
    # its own WHERE), 1 additive, 2 multiplicative, 3 an atom.
    PREC = {"+": 1, "-": 1, "*": 2, "/": 2}

    def value(self, block, v) -> str:
        return self.expr(block, v)[0]

    def atom(self, block, v) -> str:
        """A value where only an atom parses: an aggregate's argument.

        `THE AVERAGE v1 * 2 GROUPED BY g` reads as `THE AVERAGE v1`, then meets `* 2` with
        nowhere to put it and refuses at `GROUPED BY`. An expression bound with `AS` is
        inlined by the normal form -- that is what normalising means -- so the parentheses
        the author wrote have to be put back. Found by the round-trip check the moment a
        test aggregated a bound expression for the first time (finding 146).
        """
        text, prec = self.expr(block, v)
        return text if prec >= 3 else "(%s)" % text

    def top(self, block, x, cond=False) -> str:
        return self.condition(block, x) if cond else self.value(block, x)

    def expr(self, block, v) -> Tuple[str, int]:
        """(text, precedence level) of a value."""
        if isinstance(v, str):
            return self.ensure_name(block, v), 3
        kind = v.get("kind")
        if kind == "node":
            return self.ensure_name(block, v["node"]), 3
        if kind == "constant":
            return self.constant(v), 3
        if kind == "calculation":
            calc = next((c for c in block.get("calculations", [])
                         if c["id"] == v["calculation"]), None)
            if calc is None:
                return "?", 3
            if self.is_grouped(calc) or calc["id"] in getattr(self, "bound_calcs", {}):
                return self.calc_name(block, calc["id"]), 3
            return self.calculation(block, calc)
        if kind == "conditional":
            return "IF %s THEN %s ELSE %s" % (self.condition(block, v["condition"]),
                                              self.value(block, v["then"]),
                                              self.value(block, v["else"])), 0
        return "?", 3

    def calculation(self, block, calc) -> Tuple[str, int]:
        agg = calc.get("aggregation")
        fn = calc["function"].split(".")[-1]
        if isinstance(agg, dict):
            text = self.aggregate(block, calc)
            return text, (0 if " WHERE " in text else 3)
        spec = next((f for f in getattr(self.ix, "model", {}).get("functions", [])
                     if f["id"] == calc["function"]), {})
        symbol = spec.get("operatorSymbol")
        args = [self.expr(block, a) for a in calc.get("arguments", [])]
        if symbol and len(args) == 2:
            prec = self.PREC.get(symbol, 2)
            (lt, lp), (rt, rp) = args
            if lp < prec:
                lt = "(%s)" % lt
            if rp < prec or (rp == prec and symbol in ("-", "/")):
                rt = "(%s)" % rt
            return "%s %s %s" % (lt, symbol, rt), prec
        if symbol and len(args) == 1:
            t, p = args[0]
            return "%s%s" % (symbol, t if p == 3 else "(%s)" % t), 3
        return "%s(%s)" % (fn, ", ".join(t for t, _ in args)), 3

    def aggregate(self, block, calc) -> str:
        """A group function over a path of its own (§6.6, B.2): `THE COUNT OF <descriptor>`
        aggregates the path's last node; anything else is named -- `THE SUM OF s IN (...)`."""
        agg = calc["aggregation"]
        fn = calc["function"].split(".")[-1]
        word = (DISTINCT_AGG_WORDS if agg.get("distinct") else AGG_WORDS).get(
            fn, "THE %s OF" % fn.upper())
        inner = calc.get("_block")
        if inner is None:
            return self.calc_name(block, calc["id"])
        # Only a bag-valued group function carries these, and they are written where they
        # were parsed: straight after the path, before GROUPED BY or AS.
        trim = ""
        if calc.get("_ordering"):
            trim += " ORDERED WITH " + ", ".join(
                "%s %s" % (self.top(inner, v), "DESCENDING" if d == "desc" else "ASCENDING")
                for v, d in calc["_ordering"])
        if calc.get("_limit"):
            trim += " THE FIRST %d" % calc["_limit"]["count"]
            if calc["_limit"].get("offset"):
                trim += " AFTER %d" % calc["_limit"]["offset"]
        arg = calc["arguments"][0]
        # The two-operand aggregates write their second operand after the bag's name and
        # before IN: `THE OBJECT OF v BY k IN (...)`, `THE LIST OF n SEPARATED BY ', ' IN
        # (...)`. The key of an OBJECT is a value of the bag's rows, so it has to be spelled
        # against the inner block, and the linear form has no name to hang it on.
        tail = ""
        if fn == "object" and len(calc["arguments"]) > 1:
            tail = " BY " + self.value(inner, calc["arguments"][1])
        elif fn == "join" and len(calc["arguments"]) > 1:
            word = "THE DISTINCT LIST OF" if agg.get("distinct") else "THE LIST OF"
            tail = " SEPARATED BY " + self.value(inner, calc["arguments"][1])
        nid = node_source(arg)
        if nid is not None and self.linear(inner) and not tail:
            return "%s %s%s" % (word, self.nested(inner, terminal=nid), trim)
        if nid is not None:
            name = self.ensure_name(inner, nid)
            return "%s %s%s IN (%s)%s" % (word, name, tail, self.nested(inner), trim)
        if arg.get("kind") == "calculation":
            c = next((c for c in inner.get("calculations", []) if c["id"] == arg["calculation"]),
                     None)
            if c is not None and self.is_grouped(c):
                name = self.calc_name(inner, c["id"])
                return "%s %s%s IN (%s)%s" % (word, name, tail, self.nested(inner), trim)
        # an expression: it is computed alongside the path and named, then aggregated --
        # and still ordered and cut as it was written; the trim was dropped here and the
        # round trip of `THE LIST OF (s * 2) IN ... ORDERED WITH s DESCENDING THE FIRST 2`
        # gathered everything.
        expr = self.value(inner, arg)
        name = self.fresh()
        return "%s %s%s IN (%s AND ALSO %s AS %s)%s" % (word, name, tail, self.nested(inner),
                                                       expr, name, trim)

    def grouped_aggregate(self, block, calc, over: Optional[str] = None) -> str:
        """[V29]: THE COUNT OF x GROUPED BY n1, ..., nl AS name. `over` is the text of a
        path the aggregate walks itself -- `x IN <path>` or the path alone (B.2)."""
        agg = calc["aggregation"]
        fn = calc["function"].split(".")[-1]
        word = (DISTINCT_AGG_WORDS if agg.get("distinct") else AGG_WORDS).get(
            fn, "THE %s OF" % fn.upper())
        context = calc.get("_group") or agg.get("context", [])
        keys = ", ".join(self.ensure_name(block, c) if isinstance(c, str)
                         else self.value(block, c) for c in context)
        name = self.calc_name(block, calc["id"])
        arguments = calc.get("_outer_arguments", calc["arguments"])
        # The row-relative functions (conquer-2026 section 12) carry their order in the
        # window, not in an argument: RANK ranks by the value it orders by, PREVIOUS keeps
        # its argument and names the key it is previous in with BY. Spelled any other way
        # they do not parse -- the reference found `THE LAG OF` here, which nothing reads.
        order = agg.get("order") or []
        if fn in ("rank", "percent_rank") and order:
            # descending is the default and is not written; ascending is
            direction = " ASCENDING" if order[0][1] == "asc" else ""
            return "%s %s%s WITHIN %s AS %s" % (
                "THE RANK OF" if fn == "rank" else "THE PERCENT RANK OF",
                self.value(block, order[0][0]), direction, keys, name)
        arg = over if over is not None else self.atom(block, arguments[0])
        if fn == "lag" and order:
            return "THE PREVIOUS %s BY %s WITHIN %s AS %s" % (
                arg, self.value(block, order[0][0]), keys, name)
        # The two-operand aggregates carry their second operand in the text, after the bag.
        if fn == "object" and len(arguments) > 1:
            arg += " BY " + self.value(block, arguments[1])
        elif fn == "join" and len(arguments) > 1:
            word = "THE DISTINCT LIST OF" if agg.get("distinct") else "THE LIST OF"
            arg += " SEPARATED BY " + self.value(block, arguments[1])
        # `WITHIN` is the same partition without the collapse, and reading it back as
        # GROUPED BY changes the answer -- the round-trip test caught exactly that, comparing
        # 6 rows against 3.
        joiner = "WITHIN" if agg.get("window") else "GROUPED BY"
        if not keys:
            return "%s %s AS %s" % (word, arg, name)      # regrouped, but written ungrouped
        return "%s %s %s %s AS %s" % (word, arg, joiner, keys, name)

    # the parser's own precedence for the connectives, so a condition is bracketed only
    # where it has to be and `WHERE a AND b` is the same text however it was lowered
    LOGIC_PREC = {"and": 4, "xor": 3, "or": 2, "implies": 1, "iff": 0}

    def condition(self, block, cond, within: int = -1) -> str:
        kind = cond.get("kind")
        if kind == "compare":
            return "%s %s %s" % (self.top(block, cond["left"]), cond["op"],
                                 self.top(block, cond["right"]))
        if kind == "logical":
            op = LOGIC_WORDS.get(cond["op"], cond["op"].upper())
            prec = self.LOGIC_PREC.get(cond["op"], 0)
            text = (" %s " % op).join(self.condition(block, o, prec) for o in cond["operands"])
            return "(%s)" % text if prec <= within else text
        if kind == "not":
            return "NOT " + self.condition(block, cond["operand"], 5)
        if kind == "exists":
            return "SOME " + self.nested(cond["block"])
        if kind == "setCompare":
            left = self.nested(cond["left"]["block"], terminal=cond["left"].get("node"))
            right = self.nested(cond["right"]["block"], terminal=cond["right"].get("node"))
            return "%s %s %s" % (left, SET_CMP_WORDS.get(cond["op"], cond["op"]), right)
        if kind == "call":
            return "%s(%s)" % (cond["function"].split(".")[-1],
                               ", ".join(self.top(block, a) for a in cond["arguments"]))
        if kind == "restriction":
            n = self.ensure_name(block, cond["node"])
            r = cond["restriction"]
            parts = ["%s = %s" % (n, self.constant({"lexical": str(v)})) for v in r.get("values", [])]
            for rg in r.get("ranges", []):
                if rg.get("min") is not None:
                    parts.append("%s >= %s" % (n, rg["min"]))
                if rg.get("max") is not None:
                    parts.append("%s <= %s" % (n, rg["max"]))
            return "(" + " OR ".join(parts) + ")"
        return "..."

    # -- the statement -----------------------------------------------------------------

    def setexpr(self, expr: dict) -> str:
        """[V19]-[V21]: a set operation over whole queries, each in parentheses so it reads
        back as the operand it is; ordering by the listed name, then the limit."""
        sides = ["(%s)" % (self.setexpr(op) if op.get("nodeType") == "setExpr"
                           else self.query(op)) for op in expr["operands"]]
        text = (" %s " % SET_OP_WORDS[expr["op"]]).join(sides)
        if expr.get("_ordering"):
            text += " ORDERED WITH " + ", ".join(
                "%s %s" % (n, "DESCENDING" if d == "desc" else "ASCENDING")
                for n, d in expr["_ordering"])
        limit = expr.get("_limit")
        if limit:
            text += " THE FIRST %d" % limit["count"]
            if limit.get("offset"):
                text += " AFTER %d" % limit["offset"]
        return text

    def query(self, block: dict) -> str:
        """[P56]-[P59] plus this project's limit: LIST ... FROM ... ORDERED WITH ... THE FIRST."""
        if not block.get("nodes") and not block.get("steps"):
            # a whole-query expression: `THE COUNT OF ... / THE COUNT OF ...`. No path, so no
            # LIST ... FROM; the projection is the query.
            pj = block.get("projections", [])
            text = ", ".join(self.top(block, p["source"]) for p in pj)
            return re.sub(r"\s+", " ", ("LIST " + text) if len(pj) > 1 else text)
        # a projected node the author did not name is called what the column is called,
        # when that is a usable variable name; otherwise it gets a fresh one
        taken = {self.cname(c).casefold() for c in self.ix.concepts} | {
            n["name"] for n in block.get("nodes", []) if n.get("name")}
        for p in block.get("projections", []):
            nid = node_source(p["source"])
            name = p.get("name") or ""
            if nid and nid not in self.names \
                    and not any(n["id"] == nid and n.get("name") for n in block["nodes"]) \
                    and re.fullmatch(r"[a-z][A-Za-z0-9_]*", name) \
                    and name.casefold() not in taken and name not in self.names.values():
                self.names[nid] = name
        # A projected ungrouped aggregate over a path of its own -- `THE COUNT OF Assignment
        # [has Employee: !e]` beside a LIST with a FROM -- is bound in the body with AS and
        # projected by name, which is the form the parser reads; inline in the LIST it does
        # not parse (an aggregate is a descriptor, not a scalar factor).
        self.bound_calcs = {}
        for p in block.get("projections", []):
            src = p["source"]
            if src.get("kind") != "calculation":
                continue
            calc = next((c for c in block.get("calculations", [])
                         if c["id"] == src["calculation"]), None)
            if calc is not None and calc.get("_block") is not None and not self.is_grouped(calc):
                self.bound_calcs[calc["id"]] = self.calc_name(block, calc["id"])
        cols = [self.top(block, p["source"]) for p in block.get("projections", [])]
        body = self.render(block)
        for cid, name in self.bound_calcs.items():
            calc = next(c for c in block["calculations"] if c["id"] == cid)
            body += " AND ALSO %s AS %s" % (self.calculation(block, calc)[0], name)
        text = "LIST %s FROM %s" % (", ".join(cols), body) if cols else body
        ordering = block.get("_ordering") or []
        if ordering:
            text += " ORDERED WITH " + ", ".join(
                "%s %s" % (self.top(block, v), "DESCENDING" if d == "desc" else "ASCENDING")
                for v, d in ordering)
        limit = block.get("_limit")
        if limit:
            text += " THE FIRST %d" % limit["count"]
            if limit.get("offset"):
                text += " AFTER %d" % limit["offset"]
            if limit.get("per") is not None:
                text += " PER " + self.top(block, limit["per"])
            if limit.get("ties"):
                text += " WITH TIES"
        return re.sub(r"\s+", " ", text).strip()


SET_OP_WORDS = {"union": "UNITED WITH", "intersect": "INTERSECTED WITH", "except": "MINUS"}


def to_conquer(block: dict, index) -> str:
    """The §8 arrow: a lowered QueryExpr back as normalised ConQuer."""
    n = Normaliser(index, block)
    return n.setexpr(block) if block.get("nodeType") == "setExpr" else n.query(block)
