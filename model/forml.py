#!/usr/bin/env python3
"""FORML 2: say what a constraint means, in English.

Halpin & Curland, *ORM 2 Constraint Verbalization*, Technical Report ORM2-02 (Neumont
University, June 2006) — <https://www.orm.net/pdf/ORM2_TechReport2.pdf> — and *Automated
Verbalization for ORM 2*. FORML 2 is the controlled natural language NORMA generates, and the
patterns below are its, quoted from the report's own templates.

This matters here for one reason. `reverse/` derives models full of constraints it wants a
human to confirm, and its report has been naming them — "27 constraints", "read as subtyping"
— without ever saying what any of them *asserts*. A domain expert cannot confirm a uniqueness
constraint from the word "uniqueness"; they can confirm "Each Employee was born in at most one
Country". Verbalization is how ORM has always closed that loop, and it is the half of the tool
that was missing.

The conventions, from §1 of the report:

    §1.2  hyphen binding      `Person has first- GivenName` verbalizes as "each Person has at
                              most one first GivenName" -- the hyphenated word binds to the
                              object type and the hyphen is elided
    §1.4  object variables    an object type used twice is subscripted (Person1, Person2)
    §1.5  pronouns            "who" for an object type declared personal, "that" otherwise
    §1.6  positive/negative   positive says what must hold; negative says how it is violated
    §1.7  modality            alethic "It is necessary that" / "impossible";
                              deontic "It is obligatory that" / "forbidden"
    §1.8  style               relational uses predicate readings (default); attribute uses
                              role names
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

ALETHIC, DEONTIC = "alethic", "deontic"
POSITIVE, NEGATIVE, DEFAULT = "positive", "negative", "default"

_SLOT = re.compile(r"\{(\d+)\}")

# §1.7. The negative form of an alethic constraint says it is *impossible*; of a deontic one,
# that it is *forbidden*. The default form -- what the absence of a constraint implies -- uses
# "possible" and "permitted".
MODAL = {
    (ALETHIC, POSITIVE): "It is necessary that ",
    (DEONTIC, POSITIVE): "It is obligatory that ",
    (ALETHIC, NEGATIVE): "It is impossible that ",
    (DEONTIC, NEGATIVE): "It is forbidden that ",
    (ALETHIC, DEFAULT): "It is possible that ",
    (DEONTIC, DEFAULT): "It is permitted that ",
}


def bind_hyphens(text: str) -> str:
    """§1.2. `has first- {1}` -> `has first {1}`, with `first` now bound to the placeholder.

    The hyphen tells the verbalizer that the word before it is an adjective belonging to the
    object type rather than to the predicate, so a quantifier inserted at the placeholder goes
    *before* the adjective: "at most one first GivenName", not "first at most one GivenName".
    """
    return re.sub(r"(\w)-(\s*)(?=\{)", r"\1\2", text)


def _adjectives(text: str, slot: int):
    """The hyphen-bound words belonging to slot `slot`, and the text with them removed.

    §1.2 has three cases. A hyphen directly before the placeholder binds the word before it
    (`has first- {1}`). A hyphen followed by a space binds that word *and* everything between
    it and the placeholder (`has very- high {1}`). A hyphen followed by a non-space is just
    part of the predicate and binds nothing (`drives a semi-trailer for {1}`) -- which is why
    the lookahead after the hyphen insists on a space or the placeholder itself.
    """
    m = re.search(r"(\w+)-(?=\s|\{)\s*((?:\w+\s+)*?)(?=\{%d\})" % slot, text)
    if not m:
        return text, ""
    words = " ".join(w for w in (m.group(1) + " " + (m.group(2) or "")).split())
    return text[:m.start()] + text[m.end():], words


class Verbalizer:
    """Renders CCM constraints as FORML 2 sentences.

    Takes the shared `model.ccm.Index` so it can resolve a role to its player and its owning
    fact type without rebuilding either.
    """

    def __init__(self, index, style: str = "relational"):
        self.ix = index
        self.style = style

    # -- pieces ------------------------------------------------------------

    def player_name(self, role_id: str) -> str:
        c = self.ix.concepts.get(self.ix.player(role_id) or "", {})
        return c.get("name", "?")

    def is_personal(self, role_id: str) -> bool:
        """§1.5. Personal object types take "who"; everything else takes "that"."""
        c = self.ix.concepts.get(self.ix.player(role_id) or "", {})
        return bool(c.get("isPersonal"))

    def pronoun(self, role_id: str) -> str:
        return "who" if self.is_personal(role_id) else "that"

    def reading_from(self, fact: dict, role_id: str) -> Optional[dict]:
        """§1.3. Prefer a reading that starts at the constrained role."""
        readings = fact.get("readings") or []
        for rd in readings:
            seq = rd.get("roleSequence", [])
            if seq and seq[0] == role_id:
                return rd
        return readings[0] if readings else None

    def _render(self, fact: dict, rd: dict, quantifiers: Dict[int, str]) -> str:
        """Fill a reading's slots, putting each slot's quantifier before its bound adjectives."""
        text = rd.get("text", "")
        seq = rd.get("roleSequence", [])
        for i in range(len(seq)):
            text, adj = _adjectives(text, i)
            q = quantifiers.get(i, "")
            name = self.player_name(seq[i])
            filled = " ".join(x for x in (q, adj, name) if x)
            text = text.replace("{%d}" % i, filled)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _sentence(head: str, body: str) -> str:
        """Join an optional modality prefix to a clause, capitalising whichever comes first."""
        if head:
            body = body[0].lower() + body[1:] if body else body
        else:
            body = body[0].upper() + body[1:] if body else body
        return (head + body).rstrip(".") + "."

    # -- constraints -------------------------------------------------------

    def uniqueness(self, fact: dict, roles: List[str], form=POSITIVE,
                   modality=ALETHIC, preferred=False) -> str:
        """§2.1. Internal uniqueness.

        A constraint over one role of an n-ary says the rest is functionally determined:
        "Each A R at most one B". A constraint spanning every role says only that the fact
        does not repeat, which reads quite differently: "Each A, B combination occurs at most
        once in the population of A R B".
        """
        all_roles = [r["id"] for r in fact.get("roles", [])]
        rd = self.reading_from(fact, roles[0]) if roles else None
        if rd is None:
            return ""
        seq = rd.get("roleSequence", [])

        if len(roles) == len(all_roles) and len(all_roles) > 1:
            combo = ", ".join(self.player_name(r) for r in seq)
            population = self._render(fact, rd, {})
            if form == NEGATIVE:
                return (MODAL[(modality, NEGATIVE)] + "the same %s combination occurs more "
                        "than once in the population of %s." % (combo, population))
            return ("Each %s combination occurs at most once in the population of %s."
                    % (combo, population))

        constrained = [i for i, r in enumerate(seq) if r in roles]
        free = [i for i in range(len(seq)) if i not in constrained]
        if not constrained:
            return ""

        if len(seq) == 1:                       # unary: §2.1.1
            a = self.player_name(seq[0])
            population = self._render(fact, rd, {})
            if form == NEGATIVE:
                return (MODAL[(modality, NEGATIVE)] + "the same %s occurs more than once in "
                        "the population of %s." % (a, population))
            return "Each %s occurs at most once in the population of %s." % (a, population)

        if constrained[0] != 0 and len(seq) == 2:
            # §2.1.4, "UC on a single role that does not start a predicate reading":
            # `For each A, at most one B S that A`. The same shape whether or not A is B --
            # "For each Person, at most one Person is the father of that Person" (§2.1.5).
            a = self.player_name(seq[constrained[0]])
            b = free[0]
            if form == NEGATIVE:
                head = MODAL[(modality, NEGATIVE)]
                return "For each %s, %s%s." % (
                    a, head[0].lower() + head[1:],
                    self._render(fact, rd, {b: "more than one", constrained[0]: "that"})
                    .rstrip("."))
            return "For each %s, %s." % (
                a, self._render(fact, rd, {b: "at most one", constrained[0]: "that"})
                .rstrip("."))

        if form == NEGATIVE:
            q = {constrained[0]: "the same"}
            for i in free:
                q[i] = "more than one"
            return MODAL[(modality, NEGATIVE)] + self._render(fact, rd, q) + "."
        if form == DEFAULT:
            q = {constrained[0]: "the same"}
            for i in free:
                q[i] = "more than one"
            return MODAL[(modality, DEFAULT)] + self._render(fact, rd, q) + "."

        q = {constrained[0]: "each"}
        for i in free:
            q[i] = "at most one"
        return self._sentence(MODAL[(modality, POSITIVE)] if modality == DEONTIC else "",
                              self._render(fact, rd, q))

    def mandatory(self, fact: dict, role_id: str, form=POSITIVE, modality=ALETHIC) -> str:
        """§3.1. Simple mandatory: every instance of the player takes part.

        "Each A R some B", and negatively "It is impossible that any A R no B" -- the report
        uses "any" there rather than "some" to remove an ambiguity (§3.1.2).
        """
        rd = self.reading_from(fact, role_id)
        if rd is None:
            return ""
        seq = rd.get("roleSequence", [])
        if role_id not in seq:
            return ""
        i = seq.index(role_id)
        others = [j for j in range(len(seq)) if j != i]

        if len(seq) == 1:
            return self._sentence(MODAL[(modality, POSITIVE)] if modality == DEONTIC else "",
                                  self._render(fact, rd, {i: "each"}))

        if i != 0:
            # §3.1, "Mandatory role does not start a predicate reading". The pattern changes
            # shape rather than moving the quantifiers: `For each A, some B S that A`, where A
            # is the player of the *mandatory* role. Swapping the quantifiers instead would
            # give "Some Person has each EmployeeNr", which is a different claim and a false
            # one. The back-reference is filled into the slot itself (§1.4) -- substituting
            # the name in the rendered text hit the wrong occurrence on a ring fact type,
            # where both slots hold the same name.
            a = self.player_name(seq[i])
            b = others[0] if others else 0
            if form == NEGATIVE:
                head = MODAL[(modality, NEGATIVE)]
                return "For each %s, %s%s." % (
                    a, head[0].lower() + head[1:],
                    self._render(fact, rd, {b: "no", i: "that"}).rstrip("."))
            return "For each %s, %s." % (a, self._render(fact, rd, {b: "some", i: "that"})
                                         .rstrip("."))

        if form == NEGATIVE:
            q = {i: "any"}
            for j in others:
                q[j] = "no"
            return MODAL[(modality, NEGATIVE)] + self._render(fact, rd, q) + "."

        q = {i: "each"}
        for j in others:
            q[j] = "some"
        return self._sentence(MODAL[(modality, POSITIVE)] if modality == DEONTIC else "",
                              self._render(fact, rd, q))

    def exactly_one(self, fact: dict, role_id: str, modality=ALETHIC) -> str:
        """§3.3. A role carrying both mandatory and simple uniqueness.

        "exactly one" abbreviates "some (at least one) and at most one". No unary and no n-ary
        version: a simple uniqueness on an n-ary would violate the n-1 rule.
        """
        rd = self.reading_from(fact, role_id)
        if rd is None or len(rd.get("roleSequence", [])) != 2:
            return ""
        seq = rd["roleSequence"]
        i = seq.index(role_id) if role_id in seq else None
        if i is None:
            return ""
        return self._sentence(MODAL[(modality, POSITIVE)] if modality == DEONTIC else "",
                              self._render(fact, rd, {i: "each", 1 - i: "exactly one"}))

    def frequency(self, fact: dict, roles: List[str], minimum=None, maximum=None,
                  modality=ALETHIC) -> str:
        """§ frequency: "Each A R at least 2 and at most 5 B"."""
        rd = self.reading_from(fact, roles[0]) if roles else None
        if rd is None:
            return ""
        seq = rd.get("roleSequence", [])
        i = seq.index(roles[0]) if roles[0] in seq else 0
        if minimum and maximum and minimum == maximum:
            phrase = "exactly %d" % minimum
        elif minimum and maximum:
            phrase = "at least %d and at most %d" % (minimum, maximum)
        elif minimum:
            phrase = "at least %d" % minimum
        elif maximum:
            phrase = "at most %d" % maximum
        else:
            return ""
        q = {i: "each"}
        for j in range(len(seq)):
            if j != i:
                q[j] = phrase
        return self._sentence("", self._render(fact, rd, q))

    RING = {
        "irreflexive": "no %(a)s %(r)s itself",
        "asymmetric": "if %(a)s1 %(r)s %(a)s2 then %(a)s2 %(r)s %(a)s1",
        "antisymmetric": "if %(a)s1 %(r)s %(a)s2 and %(a)s1 is not %(a)s2 "
                         "then %(a)s2 %(r)s %(a)s1",
        "intransitive": "if %(a)s1 %(r)s %(a)s2 and %(a)s2 %(r)s %(a)s3 "
                        "then %(a)s1 %(r)s %(a)s3",
        "acyclic": "%(a)s1 %(r)s %(a)s2 and %(a)s2 ... %(r)s %(a)s1",
    }

    def ring(self, fact: dict, kind: str, modality=ALETHIC) -> str:
        """Ring constraints, which say what a fact type over one object type may not do."""
        rd = self.reading_from(fact, (fact.get("roles") or [{}])[0].get("id"))
        if rd is None:
            return ""
        seq = rd.get("roleSequence", [])
        if len(seq) != 2:
            return ""
        a = self.player_name(seq[0])
        verb = re.sub(r"\s+", " ", _SLOT.sub("", bind_hyphens(rd.get("text", "")))).strip()
        body = self.RING.get(kind)
        if body is None:
            return ""
        if kind == "irreflexive":
            return (MODAL[(modality, NEGATIVE)] + "some %s %s itself." % (a, verb)) \
                if modality else ""
        return MODAL[(modality, NEGATIVE)] + (body % {"a": a, "r": verb}) + "."

    def _role_clause(self, role_id: str) -> Optional[tuple]:
        """(the player's name, the reading read from this role) for one role of a set
        constraint -- the pieces every set-comparison sentence is assembled from."""
        fact = self.ix.concepts.get(self.ix.role_owner.get(role_id, ""))
        if fact is None:
            return None
        rd = self.reading_from(fact, role_id)
        if rd is None:
            return None
        seq = rd.get("roleSequence", [])
        if role_id not in seq:
            return None
        i = seq.index(role_id)
        # the constrained role is the one being spoken about; "that" back-references the
        # subject the sentence opened with, exactly as §3.1's mandatory pattern does
        other = next((j for j in range(len(seq)) if j != i), i)
        subject = self.player_name(seq[other]) if other != i else self.player_name(seq[i])
        return subject, self._render(fact, rd, {other: "that"})

    def set_comparison(self, kind: str, roles: List[str], modality=ALETHIC) -> str:
        """§4. Exclusion and equality over two roles of the same object type.

        "For each Patient, Patient has KCT if and only if Patient has RVVT" -- the two halves
        of one measurement, which no schema states and the population does. Exclusion is the
        mirror: at most one of the two holds.
        """
        clauses = [self._role_clause(r) for r in roles]
        if len(clauses) != 2 or any(c is None for c in clauses):
            return ""
        subject = clauses[0][0]
        if any(c[0] != subject for c in clauses):
            return ""                      # not two roles of one object type: nothing to say
        a, b = (c[1] for c in clauses)
        if kind == "equality":
            body = "%s if and only if %s" % (a, b)
        elif kind == "exclusion":
            body = "at most one of these holds: %s; %s" % (a, b)
        else:
            return ""
        head = MODAL[(modality, POSITIVE)] if modality == DEONTIC else ""
        return self._sentence(head, "for each %s, %s" % (subject, body))

    def value_comparison(self, roles: List[str], operator: str, modality=ALETHIC) -> str:
        """A value of one role never greater than a value of another: `start <= end`, which
        a schema states nowhere and a population shows plainly."""
        words = {"<": "less than", "<=": "at most", "=": "equal to",
                 "<>": "different from", ">=": "at least", ">": "greater than"}
        clauses = [self._role_clause(r) for r in roles]
        if len(clauses) != 2 or any(c is None for c in clauses) or operator not in words:
            return ""
        subject = clauses[0][0]
        if clauses[1][0] != subject:
            return ""
        names = [self.player_name(r) for r in roles]
        head = MODAL[(modality, POSITIVE)] if modality == DEONTIC else ""
        return self._sentence(head, "for each %s, its %s is %s its %s"
                              % (subject, names[0], words[operator], names[1]))

    def derivation(self, rule: dict) -> str:
        """Section 6.11's own spelling: the reading with its roles named, IFF the rule.

            A Product p has a taxed price of MoneyAmt a IFF
              MoneyAmt a = 1.5 * the MoneyAmt that is the ex tax price of a Product p

        A subtype rule reads `A Super is a Sub IFF ...`. The rule text is the ConQuer it was
        written in, which reads as English already."""
        target = self.ix.concepts.get(rule.get("target", {}).get("ref", ""))
        source = " ".join((rule.get("source") or "").split())
        if target is None or not source:
            return ""
        if rule["target"]["kind"] == "factType":
            m = re.match(r"^\s*LIST\s+(.+?)\s+FROM\s+(.*)$", source, re.S | re.I)
            attrs = [a.strip() for a in m.group(1).split(",")] if m else []
            body = m.group(2) if m else source
            rd = (target.get("readings") or [{}])[0]
            seq = rd.get("roleSequence", [])
            text = bind_hyphens(rd.get("text", ""))
            roles = {r["id"]: i for i, r in enumerate(target.get("roles", []))}
            for i, rid in enumerate(seq):
                k = roles.get(rid, i)
                name = self.player_name(rid)
                attr = attrs[k] if k < len(attrs) else ""
                text = text.replace("{%d}" % i, ("%s %s" % (name, attr)).strip())
            return "%s IFF %s." % (text.strip(), body)
        sup = (target.get("supertypes") or [""])[0]
        sup_name = self.ix.concepts.get(sup, {}).get("name", "?")
        an = lambda w: ("An " if w[:1].lower() in "aeiou" else "A ") + w
        return "%s is a %s IFF %s." % (an(sup_name), target.get("name", "?"), source)

    def value_restriction(self, value_type_name: str, restriction: dict) -> str:
        """A value constraint: "Gender takes a value in {'F', 'M'}"."""
        parts = []
        for v in restriction.get("values", []) or []:
            parts.append(repr(v))
        for r in restriction.get("ranges", []) or []:
            lo, hi = r.get("min"), r.get("max")
            if lo is not None and hi is not None:
                parts.append("%s..%s" % (lo, hi))
            elif lo is not None:
                parts.append(">= %s" % lo)
            elif hi is not None:
                parts.append("<= %s" % hi)
        if not parts:
            return ""
        return "Each %s takes a value in {%s}." % (value_type_name, ", ".join(parts))

    def subtype(self, sub_name: str, super_name: str, personal=False) -> str:
        """A subtype fact: "Each Manager is an Employee"."""
        article = "an" if super_name[:1].upper() in "AEIOU" else "a"
        return "Each %s is %s %s." % (sub_name, article, super_name)


def verbalize_model(model: dict, index=None, skip_kinds=()) -> List[str]:
    """Every constraint in a CCM model, as FORML 2 sentences, in reading order.

    This is what the reverse-engineering report should show a domain expert: not "27
    constraints" but 27 statements they can agree or disagree with.
    """
    if index is None:
        from ccm import Index
        index = Index(model)
    ix = index
    v = Verbalizer(ix)
    out: List[str] = []

    facts = {c["id"]: c for c in model.get("concepts", []) if c.get("kind") == "fact"}
    # A mandatory role is spelled on the role itself, not as a separate constraint. One
    # kind is skipped: a mandatory role played by a *value type*. A value type's population
    # is by definition the values that appear in its fact types, so "For each SchoolCDSCode,
    # some School has that SchoolCDSCode" is true by construction and says nothing. NORMA
    # suppresses these implied constraints too; the BIRD rerun showed them making up half the
    # report.
    for c in model.get("concepts", []):
        if c.get("kind") != "fact":
            continue
        for r in c.get("roles", []):
            if not r.get("isMandatory"):
                continue
            if ix.concepts.get(r.get("player"), {}).get("kind") == "value":
                continue
            out.append(v.mandatory(c, r["id"]))
    for c in model.get("concepts", []):
        for sup in c.get("supertypes", []) or []:
            sup_name = ix.concepts.get(sup, {}).get("name", "?")
            out.append(v.subtype(c.get("name", "?"), sup_name))
    for rule in model.get("derivationRules", []):
        s = v.derivation(rule)
        if s:
            out.append(s)

    for k in model.get("constraints", []):
        # model.md §2.2 spells a constraint's roles as `roleSequences`, a list of sequences,
        # because an external constraint spans several fact types. Internal ones -- all that
        # reverse engineering produces -- carry exactly one.
        sequences = k.get("roleSequences") or ([k["roles"]] if k.get("roles") else [])
        if not sequences or not sequences[0]:
            continue
        roles = sequences[0]
        owner = ix.role_owner.get(roles[0])
        fact = facts.get(owner)
        if fact is None:
            continue
        kind = k.get("kind")
        # ORM 2 section 1.7. A constraint recovered from a population is deontic -- it says
        # what today's rows do, not what the schema forbids -- and reads "it is obligatory
        # that" rather than as a flat law (finding 120).
        modality = DEONTIC if k.get("modality") == "deontic" else ALETHIC
        if kind in skip_kinds:
            # `skip_kinds={"uniqueness"}` is the ablation finding 72 asks for: 82% of these
            # sentences are "each X has at most one Y", and the question is whether that is
            # what a SQL writer is actually getting from the verbalisation.
            continue
        if kind == "uniqueness":
            s = v.uniqueness(fact, roles, preferred=k.get("isPreferredIdentifier", False))
        elif kind == "mandatory":
            s = v.mandatory(fact, roles[0])
        elif kind == "frequency":
            # The field names are the schema's (`ccm.schema.json` forbids any other), and
            # these read `min`/`max`/`ringType` until now -- names no schema-valid constraint
            # can carry, so every ring and frequency constraint verbalised to the empty
            # string and was dropped silently. Nothing in the repository produces either
            # kind yet, which is why it went unseen.
            s = v.frequency(fact, roles, k.get("minFrequency"), k.get("maxFrequency"))
        elif kind == "ring":
            s = v.ring(fact, k.get("ringKind", ""), modality=modality)
        elif kind in ("equality", "exclusion"):
            s = v.set_comparison(kind, roles, modality=modality)
        elif kind == "valueComparison":
            s = v.value_comparison(roles, k.get("comparisonOperator", ""), modality=modality)
        else:
            s = ""
        if s:
            out.append(s)
    return out
