#!/usr/bin/env python3
"""Encode a LiveSQLBench knowledge base as derived fact types.

Every database ships a hierarchical knowledge base: business terms, each with a description
and often a formula, and 560 of the 1,090 entries depend on other entries. Every competitor
gets it as prose and LaTeX, and resolves the dependencies per question -- that is the
"multi-hop reasoning" the benchmark is built to test.

A derived fact type is the other way to do it. Each entry becomes one rule, the dependencies
compose because a rule may name a fact type another rule derives, and the question becomes a
single step. Finding 138 verified the composition end to end; this writes it down.

**Hand-written, and deliberately.** Finding 138 measured the obstacle: only 20% of the 430
calculation entries name their quantities in words, the rest use bare symbols like `Cr` or
`T_{cold}` whose meaning is in the prose beside the formula rather than in the formula. A
translator would be an LLM reading both, which is a different experiment with a different
claim. What is encoded here is what a modeller would write, once, from the same document
every competitor is handed.

The quantities also need work the formulas assume away: a wait time stored as the text
`'104 days'`, an urgency arriving as both `'Status 1A'` and a bare `'2'`, a donor age inside
`'57 years, mature donor'`. That is the semantic layer's job and it is why the entries below
are longer than the formulas they implement.

    kb.py DATABASE [-o out.ccm.json]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
sys.path.insert(0, os.path.join(ROOT, "model"))

# (value type, head entity, ConQuer source, the KB term it implements)
# `source` lists one thing per role, in role order: the head, then the derived value.
CHAINS = {
    "organ_transplant_large": [
        ("DonorAgeYears", "Demographic",
         "LIST d, y FROM Demographic d has DemographicAgeCount a AND ALSO "
         "castNumber(substr(a, 1, instr(a, ' ') - 1)) AS y",
         "Donor Age"),
        ("RecipientWaitYears", "Clinical",
         "LIST c, y FROM Clinical c has ClinicalWaitTime w AND ALSO "
         "(castNumber(substr(w, 1, instr(w, ' ') - 1)) / 365.0) AS y",
         "Recipient Wait Time Ratio"),
        ("MedicalUrgencyValue", "Clinical",
         "LIST c, v FROM Clinical c has ClinicalMedUrgency u AND ALSO "
         "if(contains(u, '1A'), 5, if(contains(u, '1B'), 4, "
         "if(contains(u, '2'), 3, if(contains(u, '3'), 2, 1)))) AS v",
         "Medical Urgency Status"),
        ("PatientUrgencyScore", "Clinical",
         "LIST c, s FROM Clinical c has MedicalUrgencyValue v AND ALSO "
         "has RecipientWaitYears y AND ALSO (0.7 * v + 0.3 * y) AS s",
         "Patient Urgency Score"),
        ("ImmunologicalCompatibilityScore", "CompatibilityMetric",
         "LIST cm, s FROM CompatibilityMetric cm has CompatibilityMetricBloodCompat b "
         "AND ALSO has CompatibilityMetricHlaMisCount mm AND ALSO "
         "(0.6 * if(starts_with(b, 'compatible'), 1, 0) + 0.4 * (1 - mm / 6.0)) AS s",
         "Immunological Compatibility Score"),
        ("ExpectedGraftSurvival", "CompatibilityMetric",
         "LIST cm, e FROM CompatibilityMetric cm has ImmunologicalCompatibilityScore s "
         "AND ALSO has Demographic has DonorAgeYears ad AND ALSO "
         "(1.0 / (1 + exp(0 - (0 - 0.5 + 1.5 * s - 0.02 * ad)))) AS e",
         "Expected Graft Survival (EGS) Score"),
    ],
}


def entity_id(model, name):
    for c in model["concepts"]:
        if c["kind"] == "entity" and c["name"] == name:
            return c["id"]
    raise SystemExit("no entity type %r in this model" % name)


def enrich(model, db, kb):
    """Add one derived fact type per chain, carrying the knowledge base's own words."""
    added = 0
    for value, head, source, term in CHAINS.get(db, []):
        hid = entity_id(model, head)
        vt, ft, dr = "vt." + value, "ft.%sHas%s" % (head, value), "dr." + value
        entry = kb.get(term, {})
        model["concepts"].append({
            "id": vt, "name": value, "kind": "value",
            "dataType": {"name": "numeric"},
            **({"description": entry["description"]} if entry.get("description") else {})})
        model["concepts"].append({
            "id": ft, "name": ft.split(".")[1], "kind": "fact",
            "roles": [{"id": "r.%s.%s" % (ft.split(".")[1], head.lower()),
                       "player": hid, "name": head, "ordinal": 0},
                      {"id": "r.%s.%s" % (ft.split(".")[1], value.lower()),
                       "player": vt, "name": value, "ordinal": 1}],
            "readings": [{"id": "rd." + ft.split(".")[1], "text": "{0} has {1}",
                          "roleSequence": ["r.%s.%s" % (ft.split(".")[1], head.lower()),
                                           "r.%s.%s" % (ft.split(".")[1], value.lower())]}],
            "derivation": dr})
        model.setdefault("derivationRules", []).append(
            {"id": dr, "target": {"kind": "factType", "ref": ft}, "source": source})
        added += 1
    return added


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("database")
    p.add_argument("-o", "--out")
    p.add_argument("--model")
    args = p.parse_args(argv)
    db = args.database
    src = args.model or os.path.join(HERE, "work", "models", "%s-sqlite.ccm.json" % db)
    model = json.load(open(src))
    kb = {r["knowledge"]: r for r in
          (json.loads(l) for l in
           open(os.path.join(HERE, "data", db, "%s_kb.jsonl" % db)))}
    n = enrich(model, db, kb)
    out = args.out or src.replace(".ccm.json", "-kb.ccm.json")
    json.dump(model, open(out, "w"), indent=1)
    print("%s: %d derived fact types from %d knowledge base entries -> %s"
          % (db, n, len(kb), os.path.basename(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
