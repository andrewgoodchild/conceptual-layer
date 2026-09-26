"""Shared access to a Common Core Model.

`model.md` §2.3 names the functions a consumer of a CCM needs — `Roles(f)`, `Rel(r)`,
`Player(r)`, `Idf(x)`, `x ∼ y`, `RootsOf(x)` — and says they are computed, not stored. This
module is that API. Before it existed the index was rebuilt in six modules and type
relatedness was written twice, in two versions that disagreed about objectified twins.

Import from a sibling package with:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from model.ccm import Index
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

_SLOT = re.compile(r"\{(\d+)\}")
_BOUND = re.compile(r"(\w)-(?=\s|$)")


def unbind(text: str) -> str:
    """A reading's hyphen-bound adjective (FORML 2 §1.2: `has manager- {1}`) belongs to the
    object type when the reading is verbalised and to the verb part when it is typed in a
    query, where nobody would type the hyphen. `has manager- ` -> `has manager`. A hyphen
    inside a word (`semi-trailer`) is part of the predicate and is left alone."""
    return _BOUND.sub(r"\1", text.strip())


class Index:
    """Id-addressed view of a model, plus the derived schema functions.

    Built once and passed around: `Lexicon`, `Emitter`, the validator, the exporter and the
    renderer all need the same three dicts, and a cached closure is only useful if there is
    one index to cache it on.
    """

    def __init__(self, model: dict):
        self.model = model
        self.concepts: Dict[str, dict] = {}
        self.roles: Dict[str, dict] = {}
        self.role_owner: Dict[str, str] = {}      # role id -> owning fact type id = Rel(r)
        self.by_name: Dict[str, str] = {}
        self.object_names: Dict[str, str] = {}    # names that can stand where a type goes
        self.roles_by_player: Dict[str, List[str]] = {}

        for c in model.get("concepts", []):
            self.concepts[c["id"]] = c
            names = [c["name"]] + list(c.get("aliases", []))
            for n in names:
                self.by_name.setdefault(n.casefold(), c["id"])
            # A fact type is a relationship, not an object type: nothing is an instance of
            # one, so its name cannot stand where a type goes. Objectified is the exception --
            # there the name IS an object type, which is what objectification means. Kept
            # apart from `by_name`, which answers the broader question "what is this word",
            # because both questions have callers: `match_verb` backs off a hyphen-bound
            # adjective that names an object type (rule 10's `has manager` against the Manager
            # subtype), and asking `by_name` there made `DEFINE TopEarner` unreachable -- the
            # verb `has TopEarner-` lost to its own name.
            if not (c["kind"] == "fact" and not c.get("isObjectified")):
                for n in names:
                    self.object_names.setdefault(n.casefold(), c["id"])
            for r in c.get("roles", []):
                self.roles[r["id"]] = r
                self.role_owner[r["id"]] = c["id"]
                self.roles_by_player.setdefault(r["player"], []).append(r["id"])

        # An objectified fact type and the entity type objectifying it are one concept in ORM
        # (model.md §2.1); the CCM keeps them as two elements, paired here by name so no
        # consumer has to scan for the partner.
        self.twin: Dict[str, str] = {}
        grouped: Dict[str, list] = {}
        for c in model.get("concepts", []):
            grouped.setdefault(c["name"], []).append(c)
        for group in grouped.values():
            fact = next((c for c in group
                         if c["kind"] == "fact" and c.get("isObjectified")), None)
            entity = next((c for c in group if c["kind"] == "entity"), None)
            if fact and entity:
                self.twin[fact["id"]] = entity["id"]
                self.twin[entity["id"]] = fact["id"]

        # Which traversals can multiply, from ORM's uniqueness constraints. A constraint
        # spanning a single role r says each instance of Player(r) fills r at most once, so
        # entering Rel(r) through r reaches at most one fact and cannot turn one row into
        # many; a constraint spanning two or more roles says nothing of the kind, because
        # either role alone repeats. model.md §2.3 does not name this function -- LISA-D's
        # path expressions have no rows to multiply -- but a compiler that emits joins does,
        # and every consumer that needs it was about to compute it for itself.
        self._functional: set = set()
        self.uniqueness_of: Dict[str, List[List[str]]] = {}   # fact type -> role sequences
        self.uniqueness_known = False
        for c in model.get("constraints", []):
            if c.get("kind") != "uniqueness":
                continue
            self.uniqueness_known = True
            for seq in c.get("roleSequences", []):
                if len(seq) == 1:
                    self._functional.add(seq[0])
                owner = self.role_owner.get(seq[0]) if seq else None
                if owner is not None:
                    self.uniqueness_of.setdefault(owner, []).append(list(seq))
        # A unary fact type is a set: an instance is in its population or it is not, so
        # entering one is functional whether or not the constraint was written down.
        for c in model.get("concepts", []):
            if c.get("kind") == "fact" and len(c.get("roles", [])) == 1:
                self._functional.add(c["roles"][0]["id"])

        self._closure: Dict[str, frozenset] = {}

    # -- model.md §2.3 -----------------------------------------------------

    def declare_uniqueness(self, seq) -> None:
        """A uniqueness constraint learned after construction: the key a derivation rule
        implies (lower.declare_derived_keys). The model has the constraint appended as well,
        so a consumer built later from the same model sees it too."""
        seq = list(seq)
        if not seq:
            return
        self.uniqueness_known = True
        if len(seq) == 1:
            self._functional.add(seq[0])
        owner = self.role_owner.get(seq[0])
        if owner is not None:
            self.uniqueness_of.setdefault(owner, []).append(seq)
        self._closure.clear()

    def is_functional(self, role_id: str) -> bool:
        """Does entering this role's fact type through it reach at most one fact?

        Meaningless unless `uniqueness_known`: a model that declares no uniqueness at all
        has not said that anything is many-to-one, and reading silence as "everything fans
        out" would condemn every query it can express.
        """
        return role_id in self._functional

    def uniqueness(self, fact_id: str) -> List[List[str]]:
        """Every role sequence a uniqueness constraint spans over this fact type. A spanning
        one is what says `Assignment` holds one row per (employee, project) even though
        neither role alone is unique -- which is the difference between a query that
        multiplies its rows and one that does not."""
        return self.uniqueness_of.get(fact_id, [])

    def player(self, role_id: str) -> Optional[str]:
        role = self.roles.get(role_id)
        return role["player"] if role else None

    def rel(self, role_id: str) -> Optional[str]:
        return self.role_owner.get(role_id)

    def supertypes(self, cid: str) -> frozenset:
        """`cid` and everything above it. Cached: closures are static per model."""
        cached = self._closure.get(cid)
        if cached is not None:
            return cached
        seen, stack = set(), [cid]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(self.concepts.get(x, {}).get("supertypes", []))
        # An objectified fact type and its entity twin are the same instances, so a path that
        # reaches one may continue through the other.
        result = frozenset(seen | {self.twin[x] for x in seen if x in self.twin})
        self._closure[cid] = result
        return result

    def facts_between(self, a: str, b: str):
        """Binary fact types with one role playable by `a` and the other by `b`, as
        (role facing a, role facing b) pairs. §6.5 confluence attaches a bare value type at a
        junction by the one fact type that connects them; two is an ambiguity, none an error."""
        out = []
        for c in self.concepts.values():
            if c.get("kind") != "fact" or len(c.get("roles", [])) != 2:
                continue
            r0, r1 = c["roles"]
            if self.compatible(r0["player"], a) and self.compatible(r1["player"], b):
                out.append((r0["id"], r1["id"]))
            elif self.compatible(r1["player"], a) and self.compatible(r0["player"], b):
                out.append((r1["id"], r0["id"]))
        return out

    def compatible(self, a: str, b: str) -> bool:
        """ConQuer's type relatedness `x ∼ y`: a and b share a root."""
        return a == b or bool(self.supertypes(a) & self.supertypes(b))

    def roots_of(self, cid: str) -> List[str]:
        return sorted(x for x in self.supertypes(cid)
                      if not self.concepts.get(x, {}).get("supertypes"))

    def fact_behind(self, cid: str) -> Optional[str]:
        """The fact type a concept denotes: itself if it is one, else the fact it objectifies."""
        c = self.concepts.get(cid)
        if c is None:
            return None
        if c["kind"] == "fact":
            return cid
        twin = self.twin.get(cid)
        if twin and self.concepts[twin]["kind"] == "fact":
            return twin
        # a subtype of an objectified fact type -- a derived subtype of Assignment -- is
        # entered the same way: its instances are that fact type's instances
        for s in c.get("supertypes", []):
            behind = self.fact_behind(s)
            if behind is not None:
                return behind
        return None

    # -- readings ----------------------------------------------------------

    def verbalise(self, fact: dict) -> str:
        """A reading with its slots filled by role-player names: `Employee has Department`."""
        readings = fact.get("readings") or []
        if not readings:
            return fact.get("name", "")
        rd = readings[0]
        seq = rd.get("roleSequence", [])

        def fill(m):
            i = int(m.group(1))
            if i >= len(seq):
                return m.group(0)
            player = self.concepts.get(self.player(seq[i]) or "", {})
            return player.get("name", "?")

        return unbind(_SLOT.sub(fill, rd.get("text", ""))) or fact.get("name", "")

    def reading_slots(self, fact: dict):
        """Yield (verb text, from role, to role) for each gap between two slots of a reading.

        This is ConQuer's mix-fix `MFix` read off ORM's positional-slot spelling: the text
        between `{i}` and `{j}` is the verb part that steps from role i to role j.
        """
        for rd in fact.get("readings", []):
            seq = rd.get("roleSequence", [])
            pieces = _SLOT.split(rd.get("text", ""))
            # pieces alternate: literal, index, literal, index, ..., literal
            for k in range(1, len(pieces) - 2, 2):
                verb = unbind(pieces[k + 1])
                a, b = int(pieces[k]), int(pieces[k + 2])
                if verb and a < len(seq) and b < len(seq):
                    yield verb, seq[a], seq[b]
