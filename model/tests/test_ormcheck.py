#!/usr/bin/env python3
"""One deliberately broken .orm per check in model/ormcheck.py.

`examples/run.sh` runs ormcheck over every generated model and expects silence. That proves
the generator is clean today; it does not prove the checker would notice if it stopped being
clean. These cases break one reference or one element at a time and assert the checker says
so.

The distinction matters more here than elsewhere: `xmllint --schema` passes all of these.
ORM2Core.xsd types ids as `xs:ID` and refs as `xs:IDREF`, and libxml2 does not resolve IDREFs
in schema mode -- and even when it does, IDREF cannot check that a reference points at the
right KIND of element. That gap is the whole reason ormcheck exists, so it needs its own
negative tests rather than borrowing confidence from the XSD.

    test_ormcheck.py [-v] [--only SUBSTRING]
"""

import argparse
import contextlib
import copy
import os
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(HERE, ".."))

import ormcheck                                     # noqa: E402

ORM = ormcheck.ORM
ET.register_namespace("orm", ORM.strip("{}"))


def find(model, name):
    return model.find(".//" + ORM + name)


def find_all(model, name):
    return model.findall(".//" + ORM + name)


def parent_of(model, child):
    for p in model.iter():
        if child in list(p):
            return p
    return None


# -- the mutations ----------------------------------------------------------------------
# Each takes the ORMModel element and breaks one thing in place.

def dangling_role_player(model):
    find(model, "RolePlayer").set("ref", "_NothingDeclaresThis")


def role_player_points_at_a_fact(model):
    # The classic case the XSD cannot catch: a well-formed IDREF to the wrong kind of element.
    fact_id = find(model, "Fact").get("id")
    find(model, "RolePlayer").set("ref", fact_id)


def reading_order_names_a_foreign_role(model):
    orders = find_all(model, "ReadingOrder")
    other_role = [r for r in orders[1].iter(ORM + "Role") if r.get("ref")][0].get("ref")
    first = [r for r in orders[0].iter(ORM + "Role") if r.get("ref")][0]
    first.set("ref", other_role)


def reading_has_too_many_slots(model):
    data = find(model, "Data")
    data.text = (data.text or "") + " {9}"


def objectified_without_nested_predicate(model):
    obj = find(model, "ObjectifiedType")
    obj.remove(obj.find(ORM + "NestedPredicate"))


def nested_predicate_points_at_an_entity(model):
    entity_id = find(model, "EntityType").get("id")
    find(model, "NestedPredicate").set("ref", entity_id)


def value_type_without_data_type(model):
    vt = [v for v in find_all(model, "ValueType")
          if v.find(ORM + "ConceptualDataType") is not None][0]
    vt.remove(vt.find(ORM + "ConceptualDataType"))


def preferred_identifier_dangling(model):
    find(model, "PreferredIdentifier").set("ref", "_NoSuchConstraint")


def preferred_identifier_points_at_a_role(model):
    role_id = [r for r in find_all(model, "Role") if r.get("id")][0].get("id")
    find(model, "PreferredIdentifier").set("ref", role_id)


def preferred_identifier_for_points_at_a_fact(model):
    fact_id = find(model, "Fact").get("id")
    find(model, "PreferredIdentifierFor").set("ref", fact_id)


def internal_constraint_points_at_a_role(model):
    role_id = [r for r in find_all(model, "Role") if r.get("id")][0].get("id")
    container = find(model, "InternalConstraints")
    list(container)[0].set("ref", role_id)


def played_role_points_at_an_entity(model):
    entity_id = find(model, "EntityType").get("id")
    container = find(model, "PlayedRoles")
    list(container)[0].set("ref", entity_id)


def constraint_role_sequence_dangling(model):
    constraints = model.find(ORM + "Constraints")
    role = [r for r in constraints.iter(ORM + "Role") if r.get("ref")][0]
    role.set("ref", "_NoSuchRole")


CASES = [
 # (name, mutation, expected substring of the reported problem)
 ("control: a generated model is clean",            None,                            None),
 ("RolePlayer with a dangling reference",           dangling_role_player,            "which no element declares"),
 ("RolePlayer pointing at a Fact, not an object type", role_player_points_at_a_fact, "references a Fact; expected"),
 ("ReadingOrder naming another fact type's role",   reading_order_names_a_foreign_role,
                                                                                     "belongs to another fact type"),
 ("a reading with more slots than roles",           reading_has_too_many_slots,      "slots for"),
 ("ObjectifiedType with no NestedPredicate",        objectified_without_nested_predicate,
                                                                                     "has no NestedPredicate"),
 ("NestedPredicate pointing at an EntityType",      nested_predicate_points_at_an_entity,
                                                                                     "references a EntityType; expected Fact"),
 ("ValueType with no ConceptualDataType",           value_type_without_data_type,    "has no ConceptualDataType"),
 ("PreferredIdentifier with a dangling reference",  preferred_identifier_dangling,   "which no element declares"),
 ("PreferredIdentifier pointing at a Role",         preferred_identifier_points_at_a_role,
                                                                                     "expected UniquenessConstraint"),
 ("PreferredIdentifierFor pointing at a Fact",      preferred_identifier_for_points_at_a_fact,
                                                                                     "PreferredIdentifierFor references a Fact"),
 ("InternalConstraints entry pointing at a Role",   internal_constraint_points_at_a_role,
                                                                                     "InternalConstraints entry references a Role"),
 ("PlayedRoles entry pointing at an EntityType",    played_role_points_at_an_entity,
                                                                                     "PlayedRoles entry references a EntityType"),
 ("a constraint role sequence with a dangling ref", constraint_role_sequence_dangling,
                                                                                     "which no element declares"),
]


def build_model(workdir):
    """Reverse-engineer the fixture database once; every case mutates a copy of the result."""
    # Build the database here rather than reaching for reverse/tests/company.sqlite: that file
    # is generated (and gitignored), so a fresh clone does not have one, and reverse.py handed
    # a missing path quietly produces an empty model.
    db = os.path.join(workdir, "company.sqlite")
    with contextlib.closing(sqlite3.connect(db)) as conn:
        with open(os.path.join(ROOT, "reverse", "tests", "company.sql")) as fh:
            conn.executescript(fh.read())
    # Not check=True: reverse.py exits non-zero when the report has blockers, and this
    # fixture has one. What matters here is that the .orm was written -- but keep the output,
    # because if it crashed instead, that output is the only thing that says why.
    run = subprocess.run([sys.executable, os.path.join(ROOT, "reverse", "reverse.py"),
                          db, "-o", workdir, "-n", "company"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    path = os.path.join(workdir, "company.orm")
    if not os.path.exists(path):
        raise SystemExit("could not build the fixture model at %s\n%s"
                         % (path, run.stdout.decode("utf-8", "replace")))
    return path


def run(case, tree, workdir):
    name, mutate, want = case
    root = copy.deepcopy(tree.getroot())
    model = root.find(ORM + "ORMModel")
    if model is None and ormcheck.tag(root) == "ORMModel":
        model = root
    if mutate is not None:
        mutate(model)

    path = os.path.join(workdir, "case.orm")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    problems = ormcheck.check(path)

    if want is None:
        return (not problems), ("clean, as it must be" if not problems
                                else "expected no problems, got: %s" % problems[:2])
    hits = [p for p in problems if want in p]
    if hits:
        return True, hits[0][:80]
    return False, ("expected a problem mentioning %r; got %s"
                   % (want, problems[:3] or "nothing at all"))


def test_no_orm_model(workdir):
    path = os.path.join(workdir, "empty.orm")
    with open(path, "w") as fh:
        fh.write('<?xml version="1.0"?><NotAnOrmFile/>')
    problems = ormcheck.check(path)
    if problems == ["no ORMModel element"]:
        return True, "reported the missing ORMModel"
    return False, "expected 'no ORMModel element', got %s" % problems


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    cases = [c for c in CASES if not args.only or args.only.lower() in c[0].lower()]
    passed = failed = 0
    with tempfile.TemporaryDirectory() as workdir:
        tree = ET.parse(build_model(workdir))
        checks = [(c[0], lambda c=c: run(c, tree, workdir)) for c in cases]
        if not args.only or args.only.lower() in "a file that is not an orm model":
            checks.append(("a file that is not an ORM model",
                           lambda: test_no_orm_model(workdir)))
        for name, fn in checks:
            ok, note = fn()
            if ok:
                passed += 1
                if args.verbose:
                    print("ok    %-50s %s" % (name, note))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, note))

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
