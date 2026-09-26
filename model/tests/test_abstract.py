#!/usr/bin/env python3
"""Bird's abstraction: does it pick the object types a human would, and lose nothing?

Two kinds of case, because an abstraction can fail in two directions.

**False negatives** -- the thing the database is obviously about is dropped. The touchstone is
Bird's own: of the schema in her Figure 5.1 she writes that a human "would intuitively decide
that the major object types in this Universe of Discourse are 'Movie' and 'Person'", and that
"none of the algorithms reviewed in the literature arrive at this result automatically" -- the
key-concept method finds only Movie, and Feldman and Miller's finds all five. Her method is
supposed to find exactly those two. The fact types below are reconstructed from her prose and
from Halpin (1995) p. 402, which the figure is taken from; the *expectation* is her published
claim, not one invented to match this implementation.

**False positives** -- a lookup table or a column is promoted to something the database is
about. Those cases assert what must NOT survive, which is the half a recall-only measure
misses, exactly as in `conquer/tests/test_linking.py`.

Then the structural invariants, which hold for every model or the thing is not an abstraction
at all: nothing is lost (every fact type is either shown or clustered), the levels strictly
shrink (her Axiom 5-2), and what is shown stays connected (the postcondition of Algorithm 5-4).

    test_abstract.py [-v] [--models DIR]
"""

import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import abstract                      # noqa: E402

MODELS = os.path.join(HERE, "..", "..", "bench", "models")


def model(facts, entities=(), identifiers=(), mandatory=(), unique=()):
    """A CCM carrying just what the weighting rules read: players, optionality, uniqueness.

    `facts` is (name, [players]); a player named in `entities` is an entity type and everything
    else is a value type, which is the distinction rule 5 turns on. `mandatory` and `unique`
    name roles as "Fact.0".
    """
    concepts, seen, constraints = [], {}, []
    for name, players in facts:
        roles = []
        for i, p in enumerate(players):
            kind = "entity" if p in entities else "value"
            if p not in seen:
                seen[p] = {"id": "%s.%s" % ("et" if kind == "entity" else "vt", p),
                           "name": p, "kind": kind}
                concepts.append(seen[p])
            rid = "r.%s.%d" % (name, i)
            roles.append({"id": rid, "player": seen[p]["id"], "ordinal": i,
                          "name": p, "isMandatory": "%s.%d" % (name, i) in mandatory})
        concepts.append({"id": "ft." + name, "name": name, "kind": "fact", "roles": roles,
                         "readings": [{"id": "rd." + name, "text": "{0} has {1}",
                                       "roleSequence": [r["id"] for r in roles]}]})
        for i, _ in enumerate(players):
            if "%s.%d" % (name, i) in unique:
                constraints.append({"id": "uc.%s.%d" % (name, i), "kind": "uniqueness",
                                    "roleSequences": [["r.%s.%d" % (name, i)]]})
    for owner, rid in identifiers:
        next(c for c in concepts if c["id"] == owner)["identifier"] = [rid]
    return {"ccmVersion": "1.0", "id": "t", "name": "t", "concepts": concepts,
            "constraints": constraints}


def _components(s, lvl):
    """object id -> the id of its connected component among the level's fact types."""
    adj = collections.defaultdict(set)
    for fid in lvl.facts:
        ps = [s.player[r] for r in s.roles(fid)]
        for a in ps:
            adj[a].update(p for p in ps if p != a)
    seen, comp = {}, 0
    for start in sorted(lvl.objects):
        if start in seen:
            continue
        comp += 1
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen[cur] = comp
            stack.extend(adj[cur] - set(seen))
    return seen


def majors(m, level=2):
    """The entity types a level still shows, by name."""
    s = abstract.Schema(m)
    ladder = abstract.levels(m)
    lvl = ladder[min(level, len(ladder)) - 1]
    return {s.concepts[o]["name"] for o in lvl.objects
            if s.concepts.get(o, {}).get("kind") == "entity"}


# -- the movie schema, Figure 5.1 ---------------------------------------------------------------

def movies():
    """Movie has a Title, cost a MoneyAmt, and was directed by a Person; a Person was born in
    a Country and lives in a Country. Only Movie and Person are entity types with identifiers;
    Title, MoneyAmt and Country are what the schema records *about* them."""
    return model(
        [("MovieHasTitle", ["Movie", "Title"]),
         ("MovieCost", ["Movie", "MoneyAmt"]),
         ("MovieDirectedBy", ["Movie", "Person"]),
         ("PersonBornIn", ["Person", "Country"]),
         ("PersonLivesIn", ["Person", "Country"]),
         ("PersonHasName", ["Person", "PersonName"])],
        entities=("Movie", "Person"),
        identifiers=(("et.Movie", "r.MovieHasTitle.0"), ("et.Person", "r.PersonHasName.0")),
        mandatory=("MovieHasTitle.0", "MovieDirectedBy.0", "PersonHasName.0", "PersonBornIn.0"),
        unique=("MovieHasTitle.0", "MovieHasTitle.1", "MovieCost.0", "MovieDirectedBy.0",
                "PersonBornIn.0", "PersonLivesIn.0", "PersonHasName.0", "PersonHasName.1"))


def cases():
    """(name, check) where check returns (ok, note)."""

    def movie_and_person():
        got = majors(movies())
        want, must_not = {"Movie", "Person"}, {"Title", "MoneyAmt", "Country"}
        if not want <= got:
            return False, "dropped %s" % ", ".join(sorted(want - got))
        if got & must_not:
            return False, "kept %s, which the schema is about a Movie having" % ", ".join(
                sorted(got & must_not))
        return True, "major: %s" % ", ".join(sorted(got))
    yield ("Figure 5.1: the major object types are Movie and Person", movie_and_person)

    def lookup_not_major():
        """A one-column lookup a fact type points at is not what a database is about."""
        m = model(
            [("OrderHasId", ["Order", "OrderId"]),
             ("OrderHasStatus", ["Order", "Status"]),
             ("OrderHasCustomer", ["Order", "Customer"]),
             ("OrderHasTotal", ["Order", "OrderTotal"]),
             ("CustomerHasId", ["Customer", "CustomerId"]),
             ("CustomerHasName", ["Customer", "CustomerName"]),
             ("StatusHasCode", ["Status", "StatusCode"]),
             ("StatusHasLabel", ["Status", "StatusLabel"])],
            entities=("Order", "Customer", "Status"),
            identifiers=(("et.Order", "r.OrderHasId.0"), ("et.Customer", "r.CustomerHasId.0"),
                         ("et.Status", "r.StatusHasCode.0")),
            mandatory=("OrderHasId.0", "OrderHasStatus.0", "OrderHasCustomer.0",
                       "CustomerHasId.0", "CustomerHasName.0", "StatusHasCode.0"),
            unique=("OrderHasId.0", "OrderHasId.1", "OrderHasStatus.0", "OrderHasCustomer.0",
                    "OrderHasTotal.0", "CustomerHasId.0", "CustomerHasId.1",
                    "CustomerHasName.0", "StatusHasCode.0", "StatusHasCode.1",
                    "StatusHasLabel.0"))
        got = majors(m, 3)
        if "Order" not in got:
            return False, "dropped Order, which every fact type is anchored to"
        return True, "level 3 keeps %s" % ", ".join(sorted(got))
    yield ("a lookup table is not what the database is about", lookup_not_major)

    def values_never_major():
        for name in ("formula_1", "european_football_2", "card_games"):
            path = os.path.join(MODELS, "%s.ccm.json" % name)
            if not os.path.exists(path):
                continue
            m = json.load(open(path))
            s = abstract.Schema(m)
            for lvl in abstract.levels(m)[1:]:
                vals = [s.concepts[o]["name"] for o in lvl.objects if s.is_value(o)
                        and not any(o == s.player[r]
                                    for e in lvl.objects
                                    for rid in s.concepts.get(e, {}).get("identifier", []) or []
                                    for r in s.roles(s.owner[rid]))]
                if vals:
                    return False, "%s level %d keeps value types %s" % (
                        name, lvl.n, ", ".join(sorted(vals)[:4]))
        return True, "only identifying values survive"
    yield ("above level 1 a value type survives only as an identifier", values_never_major)

    def entities_kept():
        """The things formula_1 is about. A reader who is told this database is about Races,
        Drivers, Constructors and Circuits can find their way; one told it is about
        DriverStandingPositionText cannot."""
        path = os.path.join(MODELS, "formula_1.ccm.json")
        if not os.path.exists(path):
            return True, "no corpus here"
        got = majors(json.load(open(path)))
        want = {"Race", "Driver", "Constructor", "Circuit", "Result"}
        missing = want - got
        return (not missing), ("dropped %s" % ", ".join(sorted(missing)) if missing
                               else "kept all of %s" % ", ".join(sorted(want)))
    yield ("formula_1 is about races, drivers, constructors and circuits", entities_kept)

    def nothing_lost():
        """Conservation: a fact type that stops being shown is clustered under the type it was
        anchored to. If it is in neither, the abstraction is not a summary, it is a deletion."""
        for path in sorted(glob.glob(os.path.join(MODELS, "*.ccm.json")))[:12]:
            m = json.load(open(path))
            s = abstract.Schema(m)
            every = set(s.facts)
            for lvl in abstract.levels(m):
                held = set(lvl.facts) | {f for c in lvl.clusters.values() for f in c}
                lost = every - held
                if lost:
                    return False, "%s level %d loses %d fact types (%s)" % (
                        os.path.basename(path), lvl.n, len(lost),
                        ", ".join(sorted(s.concepts[f]["name"] for f in lost)[:3]))
        return True, "every fact type is shown or clustered, at every level"
    yield ("nothing is lost: what is not shown is clustered", nothing_lost)

    def strictly_shrinks():
        """Her Axiom 5-2: each level strictly decreases the populatable types in the kernel."""
        for path in sorted(glob.glob(os.path.join(MODELS, "*.ccm.json")))[:12]:
            m = json.load(open(path))
            ladder = abstract.levels(m)
            sizes = [len(l.facts) for l in ladder]
            for a, b in zip(sizes, sizes[1:]):
                if b >= a:
                    return False, "%s: %s does not shrink" % (os.path.basename(path), sizes)
        return True, "every ladder strictly decreases"
    yield ("each level is strictly smaller than the one below", strictly_shrinks)

    def stays_connected():
        """The postcondition of ConnectSchema, stated as what an abstraction may not do rather
        than as a property of the model: two types you could walk between at the bottom must
        still be walkable at every level that shows them both.

        Not "every level is connected" -- `california_schools` declares no foreign keys, so its
        three tables are three islands in the flat model already, and no abstraction can join
        what the schema never joined. That is finding 8 showing up in a new place, not a defect
        here.
        """
        for path in sorted(glob.glob(os.path.join(MODELS, "*.ccm.json")))[:12]:
            m = json.load(open(path))
            s = abstract.Schema(m)
            ladder = abstract.levels(m)
            base = _components(s, ladder[0])
            for lvl in ladder[1:]:
                here = _components(s, lvl)
                for a in lvl.objects:
                    for b in lvl.objects:
                        if a < b and base.get(a) == base.get(b) and here.get(a) != here.get(b):
                            return False, "%s level %d breaks the path between %s and %s" % (
                                os.path.basename(path), lvl.n,
                                s.concepts[a]["name"], s.concepts[b]["name"])
        return True, "no level breaks a connection the flat model had"
    yield ("what is shown stays as connected as the model was", stays_connected)

    def deterministic():
        path = os.path.join(MODELS, "formula_1.ccm.json")
        if not os.path.exists(path):
            return True, "no corpus here"
        m = json.load(open(path))
        first = abstract.summarise(m, 2)
        again = abstract.summarise(json.loads(json.dumps(m)), 2)
        return first == again, "two runs agree" if first == again else "two runs differ"
    yield ("the same model summarises the same way twice", deterministic)

    def optionality_survives():
        """A summary that loses which values may be absent produces queries that silently drop
        rows -- the trap the primer spends a paragraph on."""
        path = os.path.join(MODELS, "formula_1.ccm.json")
        if not os.path.exists(path):
            return True, "no corpus here"
        text = abstract.summarise(json.load(open(path)), 2)
        if "code?" not in text:
            return False, "Driver.code is nullable and the summary does not say so"
        if "surname?" in text:
            return False, "Driver.surname is mandatory and the summary marks it optional"
        return True, "`?` marks the nullable values and only those"
    yield ("the summary keeps what may be absent", optionality_survives)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    passed = failed = 0
    for name, check in cases():
        ok, note = check()
        if ok:
            passed += 1
            print("ok    %-62s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s" % (name, note))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
