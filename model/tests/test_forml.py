#!/usr/bin/env python3
"""FORML 2 verbalization, checked against Halpin's own sentences.

Every expected string below is quoted from Halpin & Curland, *ORM 2 Constraint Verbalization*,
Technical Report ORM2-02 (Neumont University, June 2006), or from *Automated Verbalization for
ORM 2*. They are his examples, not ones invented to match the implementation -- which is the
point: a verbalizer that agrees with itself proves nothing, and the whole value of FORML is
that a domain expert reading our output and a domain expert reading NORMA's output are reading
the same language.

Section numbers in the case names are his.

    test_forml.py [-v] [--only SUBSTRING]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from ccm import Index               # noqa: E402
import forml                        # noqa: E402


def model(*facts, personal=(), entities=()):
    """A minimal CCM carrying just the fact types a case needs."""
    concepts, seen = [], set()
    for name, reading, players in facts:
        for p in players:
            if p not in seen:
                seen.add(p)
                concepts.append({"id": "et." + p, "name": p,
                                 "kind": "entity" if p in entities or True else "value",
                                 **({"isPersonal": True} if p in personal else {})})
        roles = [{"id": "r.%s.%d" % (name, i), "player": "et." + p, "ordinal": i}
                 for i, p in enumerate(players)]
        concepts.append({"id": "ft." + name, "name": name, "kind": "fact", "roles": roles,
                         "readings": [{"id": "rd." + name, "text": reading,
                                       "roleSequence": [r["id"] for r in roles]}]})
    return {"ccmVersion": "1.0", "id": "t", "name": "t", "concepts": concepts,
            "constraints": []}


def fact(m, name):
    return next(c for c in m["concepts"] if c["id"] == "ft." + name)


def V(m):
    return forml.Verbalizer(Index(m))


# -- the cases -----------------------------------------------------------------------------
# Each returns (name, produced, expected).

def cases():
    # §1.2 hyphen binding. The hyphenated word binds to the object type, so the quantifier
    # goes in front of the adjective and the hyphen disappears.
    m = model(("PersonHasGivenName", "{0} has first- {1}", ("Person", "GivenName")),
              ("PersonHasIQ", "{0} has very- high {1}", ("Person", "IQ")),
              ("PersonDrives", "{0} drives a semi-trailer for {1}", ("Person", "Company")))
    v = V(m)
    yield ("§1.2 hyphen binding: adjective joins the object type",
           v.uniqueness(fact(m, "PersonHasGivenName"), ["r.PersonHasGivenName.0"]),
           "Each Person has at most one first GivenName.")
    yield ("§1.2 hyphen binding: two bound words",
           v.uniqueness(fact(m, "PersonHasIQ"), ["r.PersonHasIQ.0"]),
           "Each Person has at most one very high IQ.")
    yield ("§1.2 a hyphen inside a word is just a hyphen",
           v.uniqueness(fact(m, "PersonDrives"), ["r.PersonDrives.0"]),
           "Each Person drives a semi-trailer for at most one Company.")

    # §2.1.2 internal uniqueness on a binary, reading starting from the constrained role.
    m = model(("PersonBornInCountry", "{0} was born in {1}", ("Person", "Country")))
    v = V(m)
    f = fact(m, "PersonBornInCountry")
    yield ("§2.1.2 simple uniqueness, positive",
           v.uniqueness(f, ["r.PersonBornInCountry.0"]),
           "Each Person was born in at most one Country.")
    yield ("§2.1.2 simple uniqueness, negative",
           v.uniqueness(f, ["r.PersonBornInCountry.0"], form=forml.NEGATIVE),
           "It is impossible that the same Person was born in more than one Country.")
    yield ("§1.6 default form: what the ABSENCE of the constraint allows",
           v.uniqueness(f, ["r.PersonBornInCountry.0"], form=forml.DEFAULT),
           "It is possible that the same Person was born in more than one Country.")

    # §1.7 modality. A deontic constraint is an obligation, not a necessity.
    m = model(("PersonHasSSN", "{0} has {1}", ("Person", "SocialSecurityNumber")))
    v = V(m)
    yield ("§1.7 deontic uniqueness reads as an obligation",
           v.uniqueness(fact(m, "PersonHasSSN"), ["r.PersonHasSSN.0"],
                        modality=forml.DEONTIC),
           "It is obligatory that each Person has at most one SocialSecurityNumber.")
    yield ("§1.7 the negative of a deontic constraint is forbidden, not impossible",
           v.uniqueness(fact(m, "PersonHasSSN"), ["r.PersonHasSSN.0"],
                        form=forml.NEGATIVE, modality=forml.DEONTIC),
           "It is forbidden that the same Person has more than one SocialSecurityNumber.")

    # §2.1.3 a ring fact type: both roles played by the same object type.
    m = model(("PersonHasFather", "{0} has {1} as father", ("Person", "Person")))
    v = V(m)
    yield ("§2.1.3 uniqueness on a ring fact type",
           v.uniqueness(fact(m, "PersonHasFather"), ["r.PersonHasFather.0"]),
           "Each Person has at most one Person as father.")

    # §1.2 on a ring, the shape reverse engineering emits for a self-reference (rule 10): the
    # hyphen-bound adjective names the far role, and the inverse reading starts at the other
    # end, so §1.3 picks it for a constraint on that role. In Halpin's style, not his words.
    m = model(("EmployeeHasManager", "{0} has manager- {1}", ("Employee", "Employee")))
    fact(m, "EmployeeHasManager")["readings"].append(
        {"id": "rd.EmployeeHasManager.2", "text": "{0} is manager of {1}",
         "roleSequence": ["r.EmployeeHasManager.1", "r.EmployeeHasManager.0"]})
    v = V(m)
    yield ("§1.2 a ring reading's adjective binds to the far Employee",
           v.uniqueness(fact(m, "EmployeeHasManager"), ["r.EmployeeHasManager.0"]),
           "Each Employee has at most one manager Employee.")
    yield ("§1.3 a constraint on the far role takes the reading that starts there",
           v.uniqueness(fact(m, "EmployeeHasManager"), ["r.EmployeeHasManager.1"]),
           "Each Employee is manager of at most one Employee.")

    # §2.1.1 a unary. The constraint says the fact does not repeat, which reads differently.
    m = model(("PersonSmokes", "{0} smokes", ("Person",)))
    v = V(m)
    yield ("§2.1.1 uniqueness on a unary names the population",
           v.uniqueness(fact(m, "PersonSmokes"), ["r.PersonSmokes.0"]),
           "Each Person occurs at most once in the population of Person smokes.")

    # §2.1 spanning uniqueness over a whole binary: the combination does not repeat.
    m = model(("PersonPlayedSport", "{0} played {1}", ("Person", "Sport")))
    v = V(m)
    f = fact(m, "PersonPlayedSport")
    yield ("§2.1 spanning uniqueness reads as a combination",
           v.uniqueness(f, ["r.PersonPlayedSport.0", "r.PersonPlayedSport.1"]),
           "Each Person, Sport combination occurs at most once in the population of "
           "Person played Sport.")

    # §3.1.2 simple mandatory on a binary.
    m = model(("PersonBornInCountry", "{0} was born in {1}", ("Person", "Country")))
    v = V(m)
    f = fact(m, "PersonBornInCountry")
    yield ("§3.1.2 simple mandatory, positive",
           v.mandatory(f, "r.PersonBornInCountry.0"),
           "Each Person was born in some Country.")
    yield ("§3.1.2 negative mandatory uses 'any' and 'no'",
           v.mandatory(f, "r.PersonBornInCountry.0", form=forml.NEGATIVE),
           "It is impossible that any Person was born in no Country.")

    # §3.1 "Mandatory role does not start a predicate reading". The pattern changes shape
    # rather than moving the quantifiers -- swapping them would give "Some Person was born in
    # each Country", which is a different claim and a false one.
    yield ("§3.1 mandatory role that does not start the reading",
           v.mandatory(f, "r.PersonBornInCountry.1"),
           "For each Country, some Person was born in that Country.")
    yield ("§3.1 its negative form",
           v.mandatory(f, "r.PersonBornInCountry.1", form=forml.NEGATIVE),
           "For each Country, it is impossible that no Person was born in that Country.")

    # §2.1.4 uniqueness on a role that does not start the reading -- and §2.1.5, the same
    # shape on a ring. Halpin: "there is no need to distinguish the instances of A by
    # subscripting" here, because "that A" is unambiguous once "For each A" has bound it.
    m = model(("CountryBirthplace", "{0} is the birthplace of {1}", ("Country", "Person")),
              ("PersonFather", "{0} is the father of {1}", ("Person", "Person")))
    v = V(m)
    yield ("§2.1.4 uniqueness on a role that does not start the reading",
           v.uniqueness(fact(m, "CountryBirthplace"), ["r.CountryBirthplace.1"]),
           "For each Person, at most one Country is the birthplace of that Person.")
    yield ("§2.1.4 its negative form",
           v.uniqueness(fact(m, "CountryBirthplace"), ["r.CountryBirthplace.1"],
                        form=forml.NEGATIVE),
           "For each Person, it is impossible that more than one Country is the birthplace "
           "of that Person.")
    yield ("§2.1.5 the same shape on a ring fact type",
           v.uniqueness(fact(m, "PersonFather"), ["r.PersonFather.1"]),
           "For each Person, at most one Person is the father of that Person.")
    yield ("§3.1 mandatory on the second role of a ring reads the same way",
           v.mandatory(fact(m, "PersonFather"), "r.PersonFather.1"),
           "For each Person, some Person is the father of that Person.")

    # §3.1.1 a unary mandatory.
    m = model(("SquareIsRectangular", "{0} is rectangular in shape", ("Square",)),
              ("DoctorIsLicensed", "{0} is licensed", ("Doctor",)))
    v = V(m)
    yield ("§3.1.1 unary mandatory",
           v.mandatory(fact(m, "SquareIsRectangular"), "r.SquareIsRectangular.0"),
           "Each Square is rectangular in shape.")
    yield ("§3.1.1 deontic unary mandatory",
           v.mandatory(fact(m, "DoctorIsLicensed"), "r.DoctorIsLicensed.0",
                       modality=forml.DEONTIC),
           "It is obligatory that each Doctor is licensed.")

    # §3.3 mandatory and simple uniqueness together abbreviate to "exactly one".
    m = model(("PersonBornInCountry", "{0} was born in {1}", ("Person", "Country")))
    v = V(m)
    yield ("§3.3 mandatory + unique reads as 'exactly one'",
           v.exactly_one(fact(m, "PersonBornInCountry"), "r.PersonBornInCountry.0"),
           "Each Person was born in exactly one Country.")

    # §1.5 personal object types take "who"; everything else takes "that".
    m = model(("PersonSmokes", "{0} smokes", ("Person",)), personal=("Person",))
    v = V(m)
    yield ("§1.5 a personal object type takes 'who'",
           v.pronoun("r.PersonSmokes.0"), "who")
    m = model(("CarSmokes", "{0} smokes", ("Car",)))
    yield ("§1.5 an impersonal object type takes 'that'",
           V(m).pronoun("r.CarSmokes.0"), "that")

    # Frequency and value constraints.
    m = model(("PanelHasMember", "{0} has {1}", ("Panel", "Member")))
    v = V(m)
    yield ("frequency constraint with a range",
           v.frequency(fact(m, "PanelHasMember"), ["r.PanelHasMember.0"], 2, 5),
           "Each Panel has at least 2 and at most 5 Member.")
    yield ("frequency with equal bounds reads as 'exactly'",
           v.frequency(fact(m, "PanelHasMember"), ["r.PanelHasMember.0"], 3, 3),
           "Each Panel has exactly 3 Member.")
    yield ("a value constraint lists the permitted values",
           v.value_restriction("Gender", {"values": ["F", "M"]}),
           "Each Gender takes a value in {'F', 'M'}.")
    yield ("a subtype fact reads as an 'is a'",
           v.subtype("Manager", "Employee"),
           "Each Manager is an Employee.")

    # §1.3 when a reading starts from the other role, the one from the constrained role wins.
    m = {"ccmVersion": "1.0", "id": "t", "name": "t", "constraints": [],
         "concepts": [
             {"id": "et.Person", "name": "Person", "kind": "entity"},
             {"id": "et.Country", "name": "Country", "kind": "entity"},
             {"id": "ft.Born", "name": "Born", "kind": "fact",
              "roles": [{"id": "r.b.0", "player": "et.Person", "ordinal": 0},
                        {"id": "r.b.1", "player": "et.Country", "ordinal": 1}],
              "readings": [
                  {"id": "rd.inv", "text": "{0} is birthplace of {1}",
                   "roleSequence": ["r.b.1", "r.b.0"]},
                  {"id": "rd.fwd", "text": "{0} was born in {1}",
                   "roleSequence": ["r.b.0", "r.b.1"]}]}]}
    yield ("§1.3 the reading starting at the constrained role is chosen",
           V(m).uniqueness(fact(m, "Born"), ["r.b.0"]),
           "Each Person was born in at most one Country.")


    # The dispatcher, not the verbalizer. `verbalize_model` reads a constraint's fields by
    # name, and read `min`/`max`/`ringType` while `ccm.schema.json` defines
    # `minFrequency`/`maxFrequency`/`ringKind` and forbids any other property -- so every
    # schema-valid ring and frequency constraint verbalized to the empty string and was
    # dropped without a word. The sentences above were right the whole time; nothing could
    # reach them. Nothing in the repository produces either kind yet, which is why the
    # cases above (which call the verbalizer directly) never caught it.
    m = model(("EmployeeHasManager", "{0} has manager {1}", ("Employee", "Employee")))
    said = forml.verbalize_model(dict(m, constraints=[
        {"id": "rc.1", "kind": "ring", "ringKind": "irreflexive",
         "roleSequences": [["r.EmployeeHasManager.0", "r.EmployeeHasManager.1"]]},
        {"id": "fc.1", "kind": "frequency", "minFrequency": 2, "maxFrequency": 5,
         "roleSequences": [["r.EmployeeHasManager.0"]]},
    ]))
    yield ("a ring constraint reaches the verbalizer through verbalize_model",
           next((s for s in said if "impossible" in s), "(nothing)"),
           "It is impossible that some Employee has manager itself.")
    yield ("and a frequency constraint does too",
           next((s for s in said if "at least" in s), "(nothing)"),
           "Each Employee has manager at least 2 and at most 5 Employee.")


    # §4 set constraints and value comparison, and ORM 2 §1.7's modality. These kinds have
    # been in the CCM since it was written with nothing producing them (finding 119);
    # `population.apply_constraints` now does, and marks them deontic because a population
    # says what today's rows do rather than what the schema forbids.
    m = model(("ExaminationHasKCT", "{0} has {1}", ("Examination", "KCT")),
              ("ExaminationHasRVVT", "{0} has {1}", ("Examination", "RVVT")))
    said = forml.verbalize_model(dict(m, constraints=[
        {"id": "e1", "kind": "equality", "modality": "deontic",
         "roleSequences": [["r.ExaminationHasKCT.1", "r.ExaminationHasRVVT.1"]]},
    ]))
    yield ("a deontic equality constraint reads as an obligation",
           next((s for s in said if "only if" in s), "(nothing)"),
           "It is obligatory that for each Examination, that Examination has KCT if and "
           "only if that Examination has RVVT.")

    said = forml.verbalize_model(dict(m, constraints=[
        {"id": "x1", "kind": "exclusion",
         "roleSequences": [["r.ExaminationHasKCT.1", "r.ExaminationHasRVVT.1"]]},
    ]))
    yield ("an alethic exclusion constraint states the law flatly",
           next((s for s in said if "at most one" in s), "(nothing)"),
           "For each Examination, at most one of these holds: that Examination has KCT; "
           "that Examination has RVVT.")

    said = forml.verbalize_model(dict(m, constraints=[
        {"id": "v1", "kind": "valueComparison", "comparisonOperator": "<=",
         "roleSequences": [["r.ExaminationHasKCT.1", "r.ExaminationHasRVVT.1"]]},
    ]))
    yield ("a value comparison names both values and the operator",
           next((s for s in said if " is at most " in s), "(nothing)"),
           "For each Examination, its KCT is at most its RVVT.")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    passed = failed = 0
    for name, got, want in cases():
        if args.only and args.only.lower() not in name.lower():
            continue
        if got == want:
            passed += 1
            if args.verbose:
                print("ok    %-52s %s" % (name, got))
        else:
            failed += 1
            print("FAIL  %s\n        want: %s\n        got : %s" % (name, want, got))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
