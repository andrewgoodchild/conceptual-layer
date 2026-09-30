#!/usr/bin/env python3
"""Which part of a model a question is about: schema linking over a conceptual model.

The one lever the text-to-SQL leaderboards agree on. On Spider 2.0 a database averages 812
columns, a question needs four of them, and everything downstream -- the prompt, the writer's
attention, the ambiguity of a verb -- is decided by what the writer was shown. This picks that
subset.

Doing it over a *conceptual model* rather than over a DDL has three advantages, and they are
the reason this is worth trying here rather than reproducing a published method:

  * **Readings are English.** `Employee has manager- Employee` carries the words a question
    uses. A DDL has `manager_nr INTEGER`.
  * **Value domains are in the model.** Rule 6b puts the values a column holds on the value
    type, so "how many are in the 'ENG' department" can link the literal to the type that
    holds it -- the value-retrieval trick, without a retrieval index.
  * **The model is a graph.** Once the seeds are chosen, keeping the answer *connected* is a
    graph closure over fact types rather than a guess about which joins a writer will need.

Nothing here is learned, fitted or fetched: it is token overlap plus a bounded walk. That is
the floor a method should beat, and `bench/pilot/linking.py` measures it against the tables
BIRD's gold SQL actually touches.

    link.py MODEL.ccm.json "the question"          the concepts, scored
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.ccm import Index                                            # noqa: E402
from model.names import singular, words                                # noqa: E402

# Words that match everything and mean nothing. Deliberately short: a stop list is a place
# where a method quietly becomes fitted to one benchmark's phrasing.
STOP = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "from", "by", "with", "and", "or",
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "do", "does", "did",
    "what", "which", "who", "whom", "whose", "when", "where", "how", "why", "many", "much",
    "list", "show", "give", "find", "name", "names", "tell", "please", "all", "each", "every",
    "that", "this", "these", "those", "it", "its", "there", "their", "them", "his", "her",
    "most", "least", "more", "less", "than", "then", "also", "any", "some", "one", "two",
    "number", "total", "count", "average", "sum", "max", "min", "top", "first", "last",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def tokens(text: str) -> Set[str]:
    """The words of a name or a question, split and singularised by `model/names.py`.

    Both halves are done there rather than here, and the reason is a defect this had in its
    first hour: a private splitter that did not take camelCase apart, so `IncomeAmount` matched
    no question ever asked, and a private stemmer that took `employees` to `employe` while
    `Employee` stayed `Employee`. The reverse engineer has understood both since rule 10.
    """
    out = set()
    for raw in _WORD.findall(text or ""):
        for w in words(raw):
            low = w.casefold()
            # before *and* after singularising. `singular` is written for table names, where
            # `has` never appears; on question text it takes `has` to `ha`, which then escaped
            # the stop list and matched every fact type whose reading says "has".
            if low in STOP or len(low) < 2:
                continue
            low = singular(low).casefold()
            if low not in STOP and len(low) > 1:
                out.add(low)
    return out


def literals(question: str) -> List[str]:
    """Quoted strings in the question, which are values rather than vocabulary."""
    return [a or b for a, b in _QUOTED.findall(question or "")]


def widen(question: str, knowledge) -> str:
    """The question, plus the definitions of the business terms it names.

    A question names what it is about, not what it is computed from: "Intensive Workload"
    never says `cycletimesecval`, so a view chosen from its words left out the tables the
    definition needs, and writers widened it by hand every time (findings 171, 172). A term
    counts as named when every word of its name, or its abbreviation in brackets, is in the
    question; its definition, and those of the terms it depends on, are added to the words
    the view is chosen from. Only the choosing changes -- nothing is added to the listing, so
    a term matched by accident costs a wider view, not a wrong statement.
    """
    if not knowledge:
        return question
    qt = tokens(question)
    low = " ".join(question.lower().split())
    by_id = {k.get("id"): k for k in knowledge}
    chosen = []
    for k in knowledge:
        name = k.get("knowledge") or ""
        abbrev = re.findall(r"\(([A-Za-z][A-Za-z0-9-]{1,9})\)", name)
        bare = re.sub(r"\([^)]*\)", " ", name)
        words_ = tokens(bare)
        named = (words_ and words_ <= qt) or " ".join(bare.lower().split()) in low \
            or any(re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(a), question) for a in abbrev)
        if named:
            chosen.append(k)
    for k in list(chosen):
        kids = k.get("children_knowledge")
        for kid in (kids if isinstance(kids, list) else [kids]):
            if kid not in (None, -1) and by_id.get(kid) and by_id[kid] not in chosen:
                chosen.append(by_id[kid])
    extra = " ".join(" ".join(str(k.get(f) or "") for f in ("description", "definition"))
                     for k in chosen)
    return question + (" " + extra if extra.strip() else "")


class Linker:
    """Scores a model's concepts against a question. Built once per model; the index and the
    token bags are the expensive part and neither depends on the question."""

    def __init__(self, model: dict, index: Optional[Index] = None):
        self.model = model
        self.ix = index or Index(model)
        self.bag: Dict[str, Set[str]] = {}
        self.domain: Dict[str, Set[str]] = {}
        for c in model.get("concepts", []):
            bag = tokens(c["name"])
            # What the reverse engineer knew and used to throw away: the column this was named
            # from, the words of it, and the expansion of any abbreviation in it. `emp_name`
            # is what a DBA types and `emp` is what rule 10 quietly expanded.
            for t in c.get("terms", []) + list(c.get("aliases", [])):
                bag |= tokens(t)
            for r in c.get("readings", []):
                bag |= tokens(re.sub(r"\{\d+\}", " ", r.get("text", "")))
            self.bag[c["id"]] = bag
            values = (c.get("restriction") or {}).get("values") or []
            self.domain[c["id"]] = {str(v).lower() for v in values}
        # entity type -> the fact types that identify it, which a query needs in order to name
        # an instance at all
        self.identifying: Dict[str, Set[str]] = {}
        for c in model.get("concepts", []):
            for r in c.get("roles", []) if c["kind"] == "fact" else []:
                player = r["player"]
                if any(rr["player"] != player for rr in c["roles"]):
                    continue
        for c in model.get("concepts", []):
            if c["kind"] != "fact":
                continue
            for r in c.get("roles", []):
                self.identifying.setdefault(r["player"], set())
        for c in model.get("concepts", []):
            if c["kind"] == "fact" and self._is_reference_scheme(c):
                for r in c["roles"]:
                    self.identifying.setdefault(r["player"], set()).add(c["id"])
        # the fact types each concept plays a role in, for the walk
        self.touching: Dict[str, Set[str]] = {}
        for c in model.get("concepts", []):
            if c["kind"] != "fact":
                continue
            for r in c.get("roles", []):
                self.touching.setdefault(r["player"], set()).add(c["id"])

    def _is_reference_scheme(self, fact: dict) -> bool:
        """A binary fact type between an entity and the value that identifies it."""
        roles = fact.get("roles", [])
        if len(roles) != 2:
            return False
        players = [self.ix.concepts.get(r["player"], {}) for r in roles]
        kinds = [p.get("kind") for p in players]
        if sorted(kinds) != ["entity", "value"]:
            return False
        entity = players[kinds.index("entity")]
        ident = entity.get("identifier") or []
        return any(r["id"] in ident for r in roles)

    def score(self, question: str) -> Dict[str, float]:
        """concept id -> how much this question looks like it is about that concept."""
        qt = tokens(question)
        lits = {v.lower() for v in literals(question)} | {w.lower() for w in _WORD.findall(question)}
        out: Dict[str, float] = {}
        for cid, bag in self.bag.items():
            if not bag:
                continue
            hit = bag & qt
            if hit:
                # the share of the concept's own words the question uses, so a one-word name
                # that matches beats a four-word name with one word in common
                out[cid] = len(hit) / len(bag) + 0.25 * len(hit)
            # A literal the question quotes, found in a value type's domain, is the strongest
            # signal there is: it says which column the filter is on, not merely which table.
            if self.domain.get(cid) and (self.domain[cid] & lits):
                out[cid] = out.get(cid, 0) + 2.0
        return out

    def neighbours(self, cid: str):
        """(fact type, other player) for every fact type this concept plays a role in.

        In a fixed order. A set here made the walk, and so which of two equally short paths
        the view kept, depend on Python's hash seed: the same question showed a different
        bridge table on different runs (finding 172)."""
        for fid in sorted(self.touching.get(cid, ())):
            for r in self.ix.concepts[fid].get("roles", []):
                if r["player"] != cid:
                    yield fid, r["player"]

    def path(self, start: str, goal: str, limit: int):
        """The fact types on a shortest walk from one concept to another, or None. Breadth
        first, so the first walk found is a shortest one, and bounded because a model is
        connected enough that an unbounded search returns the whole schema."""
        if start == goal:
            return set()
        seen, frontier = {start}, [(start, set())]
        for _ in range(limit):
            nxt = []
            for here, used in frontier:
                for fid, other in self.neighbours(here):
                    if other == goal:
                        return used | {fid}
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.append((other, used | {fid}))
            frontier = nxt
            if not frontier:
                break
        return None

    def relevant(self, question: str, seeds: int = 40, hops: int = 0,
                 connect: int = 2, attributes: str = "anchors") -> Set[str]:
        """The concept ids to show a writer.

        Seeds, the fact types on shortest paths *between* seeds, whatever identifies what is
        kept, and optionally `hops` of indiscriminate neighbourhood.

        The defaults come off two measurements, and they disagree in a way worth knowing.
        Against the tables BIRD's gold SQL touches, forty seeds and no hop keep every gold
        table for 96% of questions -- and **more seeds beats more hops**, since a hop takes
        everything adjacent where a seed is a word the question used.

        But table recall is a proxy. `linking.py --queries` asks the harder question -- do the
        1,186 ConQuer queries the pilot actually wrote still *compile* against the pruned
        model -- and without `attributes` the answer is 75%: the subset holds the right tables
        and is missing the column the filter is on. A question names what it is about and
        almost never names the column it filters by. Keeping an entity's own value facts puts
        that back, at 87%, and costs most of the compression on BIRD-shaped models, where the
        model is mostly value types hanging off a handful of entities.

        `attributes="none"` is the aggressive setting: 32% of the model kept, and a quarter of
        real queries no longer expressible. Pick it only where the schema is wide enough for
        that to be worth it.
        """
        scored = sorted(self.score(question).items(), key=lambda kv: (-kv[1], kv[0]))
        chosen = {cid for cid, _ in scored[:seeds]}
        if not chosen:
            return set()
        keep = set(chosen)

        # A value type is a fact about something; keep what it is a fact about, and treat that
        # as a seed too, since the question named the value and meant the thing.
        anchors = {c for c in chosen if self.ix.concepts.get(c, {}).get("kind") == "entity"}
        for cid in sorted(chosen):
            kind = self.ix.concepts.get(cid, {}).get("kind")
            if kind == "value":
                for fid, other in self.neighbours(cid):
                    keep.add(fid)
                    keep.add(other)
                    if self.ix.concepts.get(other, {}).get("kind") == "entity":
                        anchors.add(other)
            elif kind == "fact":
                for r in self.ix.concepts[cid].get("roles", []):
                    keep.add(r["player"])
                    if self.ix.concepts.get(r["player"], {}).get("kind") == "entity":
                        anchors.add(r["player"])

        # Connect the anchors to each other. A question about employees and projects needs
        # whatever lies between them, and nothing else about either.
        ordered = sorted(anchors)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                walk = self.path(a, b, connect)
                if not walk:
                    continue
                for fid in walk:
                    keep.add(fid)
                    keep |= {r["player"] for r in self.ix.concepts[fid].get("roles", [])}

        # Expansion is from the *anchors* rather than from everything kept. Expanding from
        # every entity in the kept set pulls the connecting path's neighbours in too, and one
        # hop becomes two: 35% of the model where the seeds' own neighbourhoods are 12%.
        frontier = set(anchors)
        for _ in range(max(0, hops)):
            nxt = set()
            for cid in sorted(frontier):
                for fid, other in self.neighbours(cid):
                    keep.add(fid)
                    keep.add(other)
                    nxt.add(other)
            frontier = nxt

        # An entity's own value facts. A question names the things it is about and almost
        # never names the column it filters on -- `q89` asks for east Bohemia and the query
        # needs `DistrictA3` -- so keeping an entity without its attributes keeps a type
        # nothing can be said about. This is the cheap part of a hop: value types only, no
        # other entity and nothing beyond it.
        widen = (() if attributes == "none" else anchors if attributes == "anchors" else
                 [c for c in keep if self.ix.concepts.get(c, {}).get("kind") == "entity"])
        for cid in widen:
            for fid, other in self.neighbours(cid):
                if self.ix.concepts.get(other, {}).get("kind") == "value":
                    keep.add(fid)
                    keep.add(other)

        # Everything that identifies what is kept, or a query cannot name an instance; and
        # subtypes travel with their supertypes, since one is walked through the other.
        for cid in sorted(keep):
            for fid in sorted(self.identifying.get(cid, ())):
                keep.add(fid)
                keep |= {r["player"] for r in self.ix.concepts[fid].get("roles", [])}
        for cid in sorted(keep):
            keep |= set(self.ix.concepts.get(cid, {}).get("supertypes") or [])
        return keep


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("model")
    p.add_argument("question", nargs="+")
    p.add_argument("--seeds", type=int, default=40)
    p.add_argument("--hops", type=int, default=1)
    args = p.parse_args(argv)
    model = json.load(open(args.model))
    linker = Linker(model)
    question = " ".join(args.question)
    scored = linker.score(question)
    keep = linker.relevant(question, args.seeds, args.hops)
    names = {c["id"]: c["name"] for c in model["concepts"]}
    print("seeds:")
    for cid, s in sorted(scored.items(), key=lambda kv: -kv[1])[:args.seeds]:
        print("  %5.2f  %s" % (s, names.get(cid, cid)))
    print("\nkept %d of %d concepts:" % (len(keep), len(model["concepts"])))
    print("  " + ", ".join(sorted(names.get(c, c) for c in keep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
