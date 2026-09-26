#!/usr/bin/env python3
"""Reverse engineering scenarios: messy schemas, and the same model rendered several ways.

Each fixture in scenarios/ targets shapes that occur in real databases and not in textbooks.
The expectations below say what should come out AND what should be reported, because for the
heuristic rules the report is the deliverable -- a rule that silently guesses wrong is worse
than one that says it guessed.

    test_scenarios.py [-v]
"""

import contextlib
import glob
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import catalog as catalog_mod    # noqa: E402
import derive as derive_mod      # noqa: E402

# entities:   entity type names that must exist
# facts:      name -> the object types playing its roles, in order
# subtypes:   subtype -> supertype
# objectified: fact type names that must be objectified
# blockers:   how many tables could not be modelled at all
# reports:    (rule, substring that must appear in the subject or message)
# silent:     (rule, substring) that must NOT be reported -- guards against false positives
EXPECT = {
    "08-bird-drec-case-study": {
        "why": "Bird's own case study (1997 thesis, Appendix F): the DREC conference system. "
               "Kept because it is the only end-to-end ground truth for this problem, produced "
               "by the person who defined the method -- and because it is the sharpest "
               "statement of what reading one input source costs. Her Appendix G.3 says "
               "verbatim that the system declares no foreign keys, so she recovers every "
               "relationship from user interfaces, queries and data. We read the catalogue, "
               "so we recover none: sixteen tables become sixteen unrelated entity types. "
               "What this test pins is that the failure is LOUD -- the report says the model "
               "is a list of tables, not a conceptual schema -- rather than silent.",
        "entities": ["Country", "Person", "Paper", "Room", "Motel", "Rating", "Committee"],
        "facts": {},                                    # not one entity-to-entity relationship
        "blockers": 0,                                  # every table has a key; none has an FK
        "reports": [("rule 4", "the whole schema")],
        "silent": [("rule 9", ""),                      # name-matching finds nothing either:
                                                        # `Rating.paper` faces `Paper.number`
                   ("rule 7", ""), ("rule 4d", ""), ("rule 1b", "")],
    },
    "09-warehouse-wide-and-junk": {
        "why": "star schema: a keyless fact table with four foreign keys and measures, a junk "
               "dimension, a 40-column repeating group, and a degenerate dimension. None of "
               "these shapes had ever been tried, and the fact table is exactly the case "
               "rule 1b was added for -- an association the catalogue gives no key.",
        "entities": ["DateDim", "ProductDim", "OrderJunkDim", "CustomerDim", "SalesFact"],
        # The fact table is the association: four roles, one per dimension, and it objectifies
        # because the measures hang off it. That is the right ORM reading of a star.
        "facts": {"SalesFact": ["DateDim", "CustomerDim", "OrderJunkDim", "ProductDim"]},
        "objectified": ["SalesFact"],
        "blockers": 0,
        "reports": [("rule 1b", "sales_fact"),          # keyless association, identity assumed
                    ("rule 4", "sales_fact"),           # objectified by the measures
                    ("rule 2b", "customer_dim")],       # the repeating group is named
        # A junk dimension is invisible to the catalogue -- it is an ordinary table with a
        # surrogate key. Only population.py can see it, so nothing here should claim to.
        "silent": [("rule 11", ""), ("rule 7", "")],
    },
    "01-legacy-erp": {
        "why": "MyISAM era: no foreign keys anywhere, mixed naming, reserved word, no-PK table",
        "entities": ["Customer", "Order", "Ordlin", "Item"],
        "facts": {},
        "blockers": 1,                                  # SHIPMENT_LOG has no primary key
        "reports": [("rule 4", "the whole schema"),     # one report, not one per table
                    ("rule 1", "ORDLIN")],
        "silent": [("rule 7", ""), ("rule 3b", "")],
    },
    "02-crm-polymorphic": {
        "why": "polymorphic reference, EAV, association given a surrogate key, repeating group",
        "entities": ["Contact", "Company", "Note", "ContactCompany", "AttributeValue"],
        "facts": {"ContactCompanyHasContact": ["ContactCompany", "Contact"],
                  "ContactCompanyHasCompany": ["ContactCompany", "Company"]},
        "blockers": 0,
        "reports": [("rule 4b", "contact_company"),     # the association rule 4 cannot see
                    ("rule 3b", "note"),                # polymorphic owner_type / owner_id
                    ("rule 2b", "phone"),               # repeating group
                    ("rule 4c", "attribute_value")],    # EAV key is part FK, part name
    },
    "03-subtypes-three-ways": {
        "why": "one Party/Person/Organisation model rendered three ways",
        "entities": ["AParty", "APerson", "AOrganisation", "BParty", "CPerson", "COrganisation"],
        "subtypes": {"APerson": "AParty", "AOrganisation": "AParty"},
        "blockers": 0,
        # A is recovered as subtyping, B only as a discriminator to investigate,
        # C leaves no trace at all -- which is the finding, not a failure.
        "reports": [("rule 7", "a_person"), ("rule 7", "a_organisation"),
                    ("rule 8", "b_party.party_kind")],
        "silent": [("rule 7", "c_person"), ("rule 8", "c_person")],
    },
    "04-keys-two-ways": {
        "why": "same order model keyed naturally and by surrogate; only identification differs",
        "entities": ["NCustomer", "NOrder", "NOrderLine", "SCustomer", "SOrder", "SOrderLine"],
        "facts": {"NOrderLineHasNOrder": ["NOrderLine", "NOrder"],
                  "SOrderLineHasOrder": ["SOrderLine", "SOrder"]},
        "identifiers": {"NOrder": 2, "NOrderLine": 2, "SOrder": 1, "SOrderLine": 1},
        "blockers": 0,
        "reports": [("rule 4c", "n_order")],
        "silent": [("rule 4c", "s_order_line")],        # a surrogate key is not a mixed key
    },
    "05-airline": {
        "why": "two FKs to one table, composite FK, ternary, self-reference, 1:1 that is not a subtype",
        "entities": ["Airport", "Region", "Flight", "Crew", "CrewRole", "AircraftType"],
        "facts": {"FlightHasOrigin": ["Flight", "Airport"],
                  "FlightHasDestination": ["Flight", "Airport"],
                  "RegionHasParent": ["Region", "Region"],
                  "FlightCrew": ["Flight", "Crew", "CrewRole"]},
        "identifiers": {"Flight": 2},
        "blockers": 0,
        # flight_extra is vertical partitioning, but it is indistinguishable from subtyping in
        # the catalog. The rule fires and says so; that is the correct behaviour.
        "reports": [("rule 7", "flight_extra")],
    },
    "06-bom": {
        "why": "recursive many-to-many, and a relationship versioned by a date in its key",
        "entities": ["Part", "Supplier", "PartPrice", "Bom"],
        "facts": {"Bom": ["Part", "Part"]},
        "objectified": ["Bom"],
        "identifiers": {"PartPrice": 3},
        "blockers": 0,
        "reports": [("rule 4c", "part_price")],
    },
    "07-multivalued-three-ways": {
        "why": "one multi-valued fact modelled as a table, as numbered columns, and as a string",
        "entities": ["APerson", "APersonPhone", "BPerson", "CPerson"],
        "blockers": 0,
        "reports": [("rule 4c", "a_person_phone"),      # normalised: recoverable
                    ("rule 2b", "b_person")],           # numbered columns: detectable
        "silent": [("rule 2b", "c_person")],            # a delimited string: undetectable
    },
}


def check(name, spec, verbose=False):
    path = os.path.join(HERE, "scenarios", name + ".sqlite")
    source = os.path.join(HERE, "scenarios", name + ".sql")
    if not os.path.exists(source):
        # 08 is transcribed from Bird's thesis and kept locally (see NOTICE), so a
        # clone has no fixture to build. Say so: a scenario that silently does not run reads
        # as one that passed.
        print("skip  %-26s transcribed from Bird's 1997 thesis, not distributed (NOTICE)" % name)
        return True
    # Rebuild whenever the fixture is older than its DDL. Existence alone left an edited
    # .sql file untested: the stale database kept answering.
    if not os.path.exists(path) or os.path.getmtime(source) > os.path.getmtime(path):
        if os.path.exists(path):
            os.remove(path)
        with contextlib.closing(sqlite3.connect(path)) as conn:
            with open(source) as fh:
                conn.executescript(fh.read())
    model, report = derive_mod.derive(catalog_mod.from_sqlite(path))

    by_id = {c["id"]: c for c in model["concepts"]}
    # An objectified fact type and the entity type objectifying it share a name, so index by
    # (name, kind) rather than name alone.
    named = {}
    for c in model["concepts"]:
        named.setdefault((c["name"], c["kind"]), c)

    def find(name, kind):
        return named.get((name, kind))

    fails = []

    for want in spec.get("entities", []):
        c = find(want, "entity")
        if not c:
            fails.append("expected entity type %r" % want)

    for fname, players in (spec.get("facts") or {}).items():
        f = find(fname, "fact")
        if not f:
            fails.append("expected fact type %r" % fname)
            continue
        got = [by_id[r["player"]]["name"] for r in f["roles"]]
        if got != players:
            fails.append("%s plays %s, expected %s" % (fname, got, players))

    for sub, sup in (spec.get("subtypes") or {}).items():
        c = find(sub, "entity")
        got = [by_id[s]["name"] for s in (c or {}).get("supertypes", [])]
        if sup not in got:
            fails.append("%s should be a subtype of %s, got %s" % (sub, sup, got or "none"))

    for oname in spec.get("objectified", []):
        f = find(oname, "fact")
        if not f or not f.get("isObjectified"):
            fails.append("%s should be objectified" % oname)

    for ename, n in (spec.get("identifiers") or {}).items():
        c = find(ename, "entity")
        got = len((c or {}).get("identifier", []))
        if got != n:
            fails.append("%s identifier has %d role(s), expected %d" % (ename, got, n))

    if "blockers" in spec and len(report.blockers) != spec["blockers"]:
        fails.append("%d blockers, expected %d (%s)"
                     % (len(report.blockers), spec["blockers"],
                        "; ".join(b["subject"] for b in report.blockers) or "none"))

    def mentioned(rule, needle):
        return any(r["rule"] == rule and needle.lower() in
                   (r["subject"] + " " + r["message"]).lower()
                   for r in report.refinements)

    for rule, needle in spec.get("reports", []):
        if not mentioned(rule, needle):
            fails.append("expected %s to report %r" % (rule, needle))
    for rule, needle in spec.get("silent", []):
        if mentioned(rule, needle):
            fails.append("%s should NOT have reported %r" % (rule, needle))

    counts = {}
    for c in model["concepts"]:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    summary = "%d entity, %d value, %d fact" % (counts.get("entity", 0), counts.get("value", 0),
                                                counts.get("fact", 0))
    if fails:
        print("FAIL  %s\n        %s" % (name, spec["why"]))
        for f in fails:
            print("        - %s" % f)
    else:
        print("ok    %-26s %-52s %s" % (name, spec["why"][:52], summary))
        if verbose:
            for r in report.refinements:
                print("          [%s/%s] %s" % (r["rule"], r["confidence"], r["subject"]))
    return not fails


def main(argv):
    verbose = "-v" in argv
    only = [a for a in argv[1:] if not a.startswith("-")]
    names = only or sorted(EXPECT)
    ok = sum(check(n, EXPECT[n], verbose) for n in names)
    print("\n%d passed, %d failed, %d total" % (ok, len(names) - ok, len(names)))
    return 0 if ok == len(names) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
