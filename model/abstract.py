#!/usr/bin/env python3
"""Reading a large model at a higher level: Bird's automatic ORM abstraction.

An ORM model says everything in elementary facts, which is what makes it checkable and what
makes a big one unreadable. `formula_1` is 94 fact types; a Spider 2.0 schema is 216. The flat
verbalisation of one of those is thousands of words in which "Driver has DriverUrl" carries the
same weight as "Result is of Race", and a reader -- human or model -- has no way to tell which
sentences are the shape of the database and which are its filling.

This is the *database comprehension problem*, and Bird's thesis solves it in chapter 5:

    Bird, L. J. (1997). Data Reverse Engineering: from a Relational Database System to a
    3-Dimensional Conceptual Schema. PhD thesis, University of Queensland. §5.2-5.4.
    Earlier as Campbell, Halpin & Proper, "Abstractions -- making flat conceptual schemas more
    comprehensible", Data & Knowledge Engineering 20(1):39-85, 1996.

Her "third dimension" is not nesting: it is a ladder of views, each showing only what was
conceptually important in the one below, with everything dropped *clustered* under the object
type it was anchored to. The part that matters is that the selection is **automatic**, and
driven by the constraints rather than by a human's sense of importance -- which is exactly what
earlier ER clustering work (Teorey, Huffman & Zoeller) could not do without human judgement.

The procedure, with her numbering:

    WeightSchema (Algorithm 5-1)  a fixed point over twelve rules, each assigning a weight to
                                  a fact type ROLE from the constraints around it
    Anchor (Definition 5-2)       the role with the highest weight in its fact type; the fact
                                  is "anchored to" that role's player
    OTWeight (Definition 5-24)    an object type's weight is the sum of the roles anchored to it
    MajorOT (Definition 5-26)     the object types above the minimum for the level
    Kernel (Definition 5-28)      the next level is the major fact types plus their players
    AddRingFTs (Algorithm 5-2)    put back fact types entirely among the survivors
    ConnectSchema (Algorithm 5-4) restore connectivity through shortest paths
    Cluster (Axioms 5-3 to 5-8)   everything dropped hangs off the type it was anchored to

Rules 7 to 11 weigh subset, equality and exclusion constraints. No model this repository
derives carries one -- reverse engineering produces uniqueness constraints and mandatory roles
-- so they are implemented against the CCM's constraint kinds and never fire here. Said plainly
because an unfired rule is not a working rule.
"""

from __future__ import annotations

import collections
import math
from typing import Dict, List, Set

SET_KINDS = ("subset", "equality", "exclusion")


class Schema:
    """The views of a CCM that the weighting rules ask for, by their names in the thesis."""

    def __init__(self, model: dict):
        self.model = model
        self.concepts = {c["id"]: c for c in model.get("concepts", [])}
        self.facts = {i: c for i, c in self.concepts.items() if c.get("kind") == "fact"}
        self.objects = {i: c for i, c in self.concepts.items()
                        if c.get("kind") in ("entity", "value")}
        self.player: Dict[str, str] = {}
        self.owner: Dict[str, str] = {}
        self.ordinal: Dict[str, int] = {}
        self.plays = collections.defaultdict(list)
        for fid, f in self.facts.items():
            for r in f.get("roles", []):
                self.player[r["id"]] = r.get("player")
                self.owner[r["id"]] = fid
                self.ordinal[r["id"]] = r.get("ordinal", 0)
                self.plays[r.get("player")].append(r["id"])

        # An object type's *reference* fact types are excluded from the weighting, as §5.3.4
        # says: "'Room is in Building' and 'Room has Room#' are not considered in the weighting
        # procedure as they are both reference types". They come back in IdentifiedSchema.
        self.reference: Set[str] = set()
        for c in self.objects.values():
            for rid in c.get("identifier", []) or []:
                if rid in self.owner:
                    self.reference.add(self.owner[rid])

        self.supertypes = {i: list(c.get("supertypes", []) or []) for i, c in self.objects.items()}
        self.unique_single: Set[str] = set()      # roles with a single-role uniqueness constraint
        self.set_cons: List[dict] = []
        for k in model.get("constraints", []):
            seqs = k.get("roleSequences") or ([k["roles"]] if k.get("roles") else [])
            if k.get("kind") == "uniqueness" and len(seqs) == 1 and len(seqs[0]) == 1:
                self.unique_single.add(seqs[0][0])
            elif k.get("kind") in SET_KINDS:
                self.set_cons.append(k)

    # -- the relations the rules quantify over ------------------------------------------------

    def roles(self, fid: str) -> List[str]:
        return [r["id"] for r in self.facts[fid].get("roles", [])]

    def others(self, rid: str) -> List[str]:
        return [x for x in self.roles(self.owner[rid]) if x != rid]

    def is_value(self, oid: str) -> bool:
        return self.concepts.get(oid, {}).get("kind") == "value"

    def related(self, a: str, b: str) -> bool:
        """Type related: the same object type, or one a subtype of the other."""
        if a == b:
            return True
        return b in self._ancestry(a) or a in self._ancestry(b)

    def _ancestry(self, oid: str, seen=None) -> Set[str]:
        seen = seen if seen is not None else set()
        for s in self.supertypes.get(oid, []):
            if s not in seen:
                seen.add(s)
                self._ancestry(s, seen)
        return seen

    def max_freq(self, rid: str) -> float:
        """A single-role uniqueness constraint caps the role's population at one occurrence."""
        return 1.0 if rid in self.unique_single else math.inf


def weigh(s: Schema, kernel: Set[str]) -> Dict[str, int]:
    """Algorithm 5-1. Raise weights until nothing rises: rules 3 and 6 read other weights, so
    a rise in one part of the schema can pull up another."""
    weight: Dict[str, int] = {r: 0 for f in kernel for r in s.roles(f)}
    while True:
        raised = False
        for fid in kernel:
            for rid in s.roles(fid):
                w = max(rule(s, rid, kernel, weight) for rule in RULES)
                if w > weight[rid]:
                    weight[rid], raised = w, True
        if not raised:
            return weight


# -- the twelve AutoWeight rules, §5.3.2 to §5.3.13 --------------------------------------------

def _r1_mandatory(s, rid, kernel, w):
    """Full participation by the player's population. A disjunctive mandatory shares the 10.

    The rule excludes *implied* mandatory roles (her InferMand), and a mandatory role played by
    a value type is the commonest implied one: a value type's population is by definition the
    values that appear in its fact types, so "each CircuitId is of some Circuit" is true by
    construction. `model/forml.py` suppresses the same sentences for the same reason. Without
    this the two roles of every value fact tie at 10, both become anchors, and every value type
    is as major as the entity it describes -- which is the whole thing this is trying to undo.
    """
    role = next(r for r in s.facts[s.owner[rid]]["roles"] if r["id"] == rid)
    if not role.get("isMandatory") or s.is_value(s.player[rid]):
        return 0
    return 10


def _r2_unary(s, rid, kernel, w):
    return 10 if len(s.roles(s.owner[rid])) == 1 else 0


def _r3_non_leaf(s, rid, kernel, w):
    """A leaf's player plays no role in any other fact type. If exactly one role of a fact type
    is played by a non-leaf, that role is where the fact type belongs."""
    if _leaf(s, rid, kernel):
        return 0
    return 9 if all(_leaf(s, q, kernel) for q in s.others(rid)) else 0


def _leaf(s, rid, kernel):
    here = s.owner[rid]
    return not any(s.owner[q] != here and s.owner[q] in kernel
                   for q in s.plays[s.player[rid]])


def _r4_smallest_max_frequency(s, rid, kernel, w):
    """The closer a role's maximum frequency is to one, the more firmly it holds the fact type:
    8 for a uniqueness constraint, falling to 2 as the frequency grows."""
    f = s.max_freq(rid)
    if not all(f < s.max_freq(q) for q in s.others(rid)):
        return 0
    return 2 + int(round(6 / math.sqrt(f))) if f != math.inf else 2


def _r5_non_value(s, rid, kernel, w):
    """Value types are by definition less conceptually important than non-value types."""
    if s.is_value(s.player[rid]):
        return 0
    return 7 if all(s.is_value(s.player[q]) for q in s.others(rid)) else 0


def _r6_anchor_points(s, rid, kernel, w):
    """A role whose player already anchors something heavy carries this fact type too."""
    if not _heavy(s, rid, w):
        return 0
    return 6 if not any(_heavy(s, q, w) for q in s.others(rid)) else 0


def _heavy(s, rid, w):
    return any(w.get(q, 0) >= 7 for q in s.plays[s.player[rid]])


def _set_roles(s):
    out = set()
    for k in s.set_cons:
        for seq in k.get("roleSequences") or []:
            out.update(seq)
    return out


def _r7_single_role_set(s, rid, kernel, w):
    """Rules 7 to 11 weigh subset, equality and exclusion constraints. Nothing this repository
    derives carries one, so on a reverse-engineered model these return 0 every time."""
    cons = [k for k in s.set_cons if any(rid in seq for seq in k["roleSequences"])]
    if len(cons) != 1 or any(q in _set_roles(s) for q in s.others(rid)):
        return 0
    far = [r for seq in cons[0]["roleSequences"] for r in seq if r != rid]
    return 5 if any(w.get(r, 0) >= 7 for r in far) else 0


def _r8_multi_role_set(s, rid, kernel, w):
    for k in s.set_cons:
        seqs = k["roleSequences"]
        for i, seq in enumerate(seqs):
            if rid not in seq:
                continue
            pos = seq.index(rid)
            for j, other in enumerate(seqs):
                if j != i and pos < len(other) and w.get(other[pos], 0) >= 7:
                    return 4
    return 0


def _r9_set_and_anchor_points(s, rid, kernel, w):
    if not s.set_cons or not _heavy(s, rid, w):
        return 0
    if any(_heavy(s, q, w) for q in s.others(rid)):
        return 0
    return 3 if rid in _set_roles(s) else 0


def _r10_joining_roles(s, rid, kernel, w):
    joins = set()
    for k in s.set_cons:
        for seq in k["roleSequences"]:
            if len({s.owner[r] for r in seq if r in s.owner}) > 1:
                joins.update(seq)
    if rid not in joins:
        return 0
    return 2 if not any(q in joins for q in s.others(rid)) else 0


def _r11_first_role_of_set(s, rid, kernel, w):
    for k in s.set_cons:
        for seq in k["roleSequences"]:
            if rid in seq and seq.index(rid) == 0 and len(seq) > 1:
                return 1
    return 0


def _r12_first_keyed_role(s, rid, kernel, w):
    """The default: the first role covered by an internal uniqueness constraint. The order the
    modeller chose to verbalise the fact type in is itself evidence."""
    keyed = [r for r in s.roles(s.owner[rid]) if r in s.unique_single]
    if not keyed:
        keyed = s.roles(s.owner[rid])
    return 1 if s.ordinal[rid] == min(s.ordinal[r] for r in keyed) else 0


RULES = (_r1_mandatory, _r2_unary, _r3_non_leaf, _r4_smallest_max_frequency, _r5_non_value,
         _r6_anchor_points, _r7_single_role_set, _r8_multi_role_set, _r9_set_and_anchor_points,
         _r10_joining_roles, _r11_first_role_of_set, _r12_first_keyed_role)


# -- levels ------------------------------------------------------------------------------------

class Level:
    """One rung: what is shown, and what each shown object type absorbed."""

    def __init__(self, n, facts, objects, clusters, weight, anchored):
        self.n, self.facts, self.objects = n, facts, objects
        self.clusters, self.weight, self.anchored = clusters, weight, anchored

    def __repr__(self):
        return "<level %d: %d fact types, %d object types>" % (
            self.n, len(self.facts), len(self.objects))


def _anchors(s: Schema, kernel: Set[str], weight: Dict[str, int]):
    """Definition 5-2: the highest-weighted role of a fact type, ties included."""
    out = {}
    for fid in kernel:
        rs = s.roles(fid)
        top = max((weight.get(r, 0) for r in rs), default=0)
        out[fid] = [r for r in rs if weight.get(r, 0) == top and top > 0]
    return out


def _identified(s: Schema, objects: Set[str]) -> Set[str]:
    """Every shown object type keeps the fact types that identify it (§5.4.4)."""
    out = set()
    for oid in objects:
        for rid in s.concepts.get(oid, {}).get("identifier", []) or []:
            if rid in s.owner:
                out.add(s.owner[rid])
    return out


def _connect(s: Schema, objects: Set[str], facts: Set[str]) -> Set[str]:
    """Algorithm 5-4, the shortest-path half: reconnect components through the fact types of
    the level below, so the abstraction is still a connected schema rather than islands."""
    if len(objects) < 2:
        return facts
    adj = collections.defaultdict(set)
    for fid, f in s.facts.items():
        ps = [r.get("player") for r in f.get("roles", [])]
        for a in ps:
            for b in ps:
                if a != b:
                    adj[a].add((b, fid))
    seen, order = set(), [o for o in objects]
    root = order[0]
    # components of the shown schema
    comp = {root}
    frontier = [root]
    while frontier:
        cur = frontier.pop()
        for fid in facts:
            ps = [r.get("player") for r in s.facts[fid].get("roles", [])]
            if cur in ps:
                for p in ps:
                    if p in objects and p not in comp:
                        comp.add(p)
                        frontier.append(p)
    for target in order:
        if target in comp:
            continue
        # breadth-first through the whole schema for the shortest connecting path
        prev, queue, seen = {}, collections.deque([root]), {root}
        while queue:
            cur = queue.popleft()
            if cur == target:
                break
            for nxt, fid in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    prev[nxt] = (cur, fid)
                    queue.append(nxt)
        node = target
        while node in prev:
            node, fid = prev[node]
            facts.add(fid)
            objects.update(r.get("player") for r in s.facts[fid].get("roles", []))
        comp.add(target)
    return facts


def levels(model: dict, most: int = 8) -> List[Level]:
    """The ladder, from the flat schema up to the last rung that still says something.

    Definition 5-28 makes the next kernel the major fact types plus their players. A kernel can
    therefore empty out while object types remain -- a schema whose important types have no
    fact types *between* them, which is what a database with no declared foreign keys derives
    to. That is still a rung worth showing ("this database is about three things"), and it is
    also a useful diagnosis, so the objects are carried rather than read back off the kernel.
    """
    s = Schema(model)
    facts = {f for f in s.facts if f not in s.reference}
    objects = {s.player[r] for f in facts for r in s.roles(f)}
    clusters = collections.defaultdict(set)
    out: List[Level] = []
    n = 1
    while True:
        weight = weigh(s, facts)
        anchored = _anchors(s, facts, weight)
        shown = set(facts)
        # ring fact types (Algorithm 5-2) and identification (§5.4.4) are shown but take no
        # part in choosing the next level
        shown |= {f for f in s.facts
                  if f not in s.reference and len(s.roles(f)) > 1
                  and {s.player[r] for r in s.roles(f)} <= objects}
        shown |= _identified(s, objects)
        shown = _connect(s, set(objects), shown)
        out.append(Level(n, shown, set(objects), {k: set(v) for k, v in clusters.items()},
                         weight, anchored))
        if n >= most or not facts:
            return out

        ot_weight = collections.Counter()
        for fid, rs in anchored.items():
            for r in rs:
                ot_weight[s.player[r]] += weight.get(r, 0)
        floor = min(ot_weight.get(o, 0) for o in objects)
        major = {o for o in objects if ot_weight.get(o, 0) > floor}
        major_facts = {f for f in facts
                       if {s.player[r] for r in s.roles(f)} <= major
                       and any(not s.related(s.player[a], s.player[b])
                               for a in s.roles(f) for b in s.roles(f))}
        if not major or (major_facts == facts and major == objects):
            return out

        # everything that just disappeared clusters under the type it was anchored to
        # (Axiom 5-3). A fact anchored to a type that is itself disappearing is carried to
        # whichever surviving type absorbs it, which is what the recursion does for free.
        # Axiom 5-8 adds the reference types needed to identify anything in a cluster: when
        # Legality stops being shown, "Legality has LegalityId" leaves with it rather than
        # being lost between the kernel it was never in and the level it is no longer named by.
        for fid in facts - major_facts:
            for r in anchored.get(fid) or []:
                clusters[s.player[r]].add(fid)
                for p in {s.player[q] for q in s.roles(fid)}:
                    for rid in s.concepts.get(p, {}).get("identifier", []) or []:
                        if rid in s.owner and s.owner[rid] not in _identified(s, objects - {p}):
                            clusters[s.player[r]].add(s.owner[rid])
        facts = major_facts
        objects = major | {s.player[r] for f in major_facts for r in s.roles(f)}
        n += 1


# -- saying it in English ----------------------------------------------------------------------

def _short(s: Schema, oid: str, owner_name: str) -> str:
    """`DriverForename` under Driver reads as `forename`: rule 10 built the name by joining the
    table's name to the column's, and here the table's name is already the line you are on."""
    name = s.concepts.get(oid, {}).get("name", "?")
    if name.lower().startswith(owner_name.lower()) and len(name) > len(owner_name):
        name = name[len(owner_name):]
    return name[:1].lower() + name[1:]


def summarise(model: dict, level: int = 2, cardinality: bool = False) -> str:
    """One level of the ladder, as English.

    The flat verbalisation says every elementary fact in one list, which is the right thing for
    a domain expert checking claims one at a time and the wrong thing for anyone trying to see
    the shape of a database. This says the shape: what the database is about, what each of those
    things carries, and how they relate -- with the detail absorbed into the type it belongs to
    rather than dropped.
    """
    import forml as forml_mod
    from ccm import Index

    s = Schema(model)
    ladder = levels(model)
    lvl = ladder[min(level, len(ladder)) - 1]
    ix = Index(model)
    v = forml_mod.Verbalizer(ix)

    entities = sorted((o for o in lvl.objects if s.concepts.get(o, {}).get("kind") == "entity"),
                      key=lambda o: s.concepts[o]["name"])
    lines = ["# What %s is about" % (model.get("name") or "this database"),
             "",
             "Level %d of %d: the whole model has %d fact types, this view has %d."
             % (lvl.n, len(ladder), len(s.facts), len(lvl.facts)),
             ""]
    if len(ladder) > 1 and lvl.n > 1:
        lines.append("Each thing below is named, then what it carries. Detail that is not shown "
                     "has been absorbed into the thing it describes, not discarded. A `?` marks "
                     "a value that may be absent -- reading one of those in a query needs "
                     "`OPTIONALLY`, or the row is dropped.")
        lines.append("")

    for oid in entities:
        name = s.concepts[oid]["name"]
        ident = [s.concepts[s.player[r]]["name"]
                 for rid in s.concepts[oid].get("identifier", []) or []
                 for r in s.roles(s.owner[rid]) if s.player[r] != oid]
        carried, refs = [], []
        for fid in sorted(lvl.clusters.get(oid, ())) + [f for f in sorted(lvl.facts)
                                                        if f not in lvl.clusters.get(oid, ())]:
            if fid in s.reference or fid not in s.facts:
                continue
            roles = s.roles(fid)
            if oid not in [s.player[r] for r in roles]:
                continue
            if fid not in lvl.clusters.get(oid, ()):
                continue
            far = [s.player[r] for r in roles if s.player[r] != oid] or [oid]
            if all(s.is_value(f) for f in far):
                # `?` marks a value that may be absent. The flat verbalisation carries this as
                # the *absence* of an "Each X has some Y" sentence, which a summary cannot do by
                # omission, and it is the difference between a query that needs OPTIONALLY and
                # one that silently drops rows.
                mark = "" if _mandatory(s, [r for r in roles if s.player[r] == oid][0]) else "?"
                carried.extend(_short(s, f, name) + mark for f in far)
            else:
                refs.append(", ".join(s.concepts[f]["name"] for f in far))
        say = "**%s**" % name
        if ident:
            say += " — identified by %s" % ", ".join(ident)
        if carried:
            say += ". Carries %s" % ", ".join(carried)
        if refs:
            say += ". Through absorbed detail, reaches %s" % "; ".join(refs)
        lines.append("- " + say + ".")

    # Which roles a single-role uniqueness constraint covers: "each Result has at most one
    # Race" is the sentence a SQL writer reads join cardinality off, and 82% of the flat
    # verbalisation is sentences of that shape. The summary drops them by default, which is
    # the difference finding 72 put its money on.
    unique = {}
    for k in model.get("constraints", []):
        seqs = k.get("roleSequences") or ([k["roles"]] if k.get("roles") else [])
        if k.get("kind") == "uniqueness" and len(seqs) == 1:
            owner = ix.role_owner.get(seqs[0][0])
            if owner:
                unique.setdefault(owner, []).append((seqs[0], k.get("isPreferredIdentifier")))

    between = []
    for fid in sorted(lvl.facts):
        if fid in s.reference:
            continue
        players = [s.player[r] for r in s.roles(fid)]
        if any(s.is_value(p) for p in players) or len(players) < 2:
            continue
        for r in s.roles(fid):
            if r in (lvl.anchored.get(fid) or []):
                said = (v.mandatory(s.facts[fid], r) if _mandatory(s, r)
                        else _plain(s, v, fid, r))
                if cardinality:
                    for seq, preferred in unique.get(fid, []):
                        said += " " + v.uniqueness(s.facts[fid], seq, preferred=bool(preferred))
                between.append(said)
                break
    if between:
        lines += ["", "## How they relate", ""] + ["- " + b for b in sorted(set(between))]
    return "\n".join(lines)


def _mandatory(s: Schema, rid: str) -> bool:
    role = next(r for r in s.facts[s.owner[rid]]["roles"] if r["id"] == rid)
    return bool(role.get("isMandatory")) and not s.is_value(s.player[rid])


def _plain(s: Schema, v, fid: str, rid: str) -> str:
    """A fact type nobody is obliged to play still has to be stated, so say it as a possibility
    rather than borrowing the mandatory sentence, which would assert more than the model does."""
    reading = (s.facts[fid].get("readings") or [{}])[0].get("text", "{0} has {1}")
    names = [s.concepts[s.player[r]]["name"] for r in s.roles(fid)]
    for i, n in enumerate(names):
        reading = reading.replace("{%d}" % i, n)
    return "%s." % reading


def main(argv=None):
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("model", help="a .ccm.json model")
    p.add_argument("--level", type=int, default=2, help="which rung to say in English")
    p.add_argument("--cardinality", action="store_true",
                   help="add the uniqueness sentence to each relationship -- the one thing the "
                        "flat verbalisation is mostly made of, and the summary otherwise drops")
    p.add_argument("--ladder", action="store_true", help="show the rungs and stop")
    p.add_argument("--weights", action="store_true", help="the anchor chosen for each fact type")
    args = p.parse_args(argv)

    model = json.load(open(args.model))
    s = Schema(model)
    if args.ladder or args.weights:
        ladder = levels(model)
        for lvl in ladder:
            print("level %d: %3d fact types, %3d object types, %d clustered"
                  % (lvl.n, len(lvl.facts), len(lvl.objects), sum(len(c) for c in lvl.clusters.values())))
        if args.weights:
            lvl = ladder[0]
            print()
            for fid in sorted(lvl.anchored):
                anch = lvl.anchored[fid]
                print("%-38s -> %s" % (s.concepts[fid]["name"],
                                       ", ".join(s.concepts[s.player[r]]["name"] for r in anch)))
        return 0
    print(summarise(model, args.level, cardinality=args.cardinality))
    return 0


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
