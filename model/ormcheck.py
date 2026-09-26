#!/usr/bin/env python3
"""Check a generated .orm beyond what its schema can.

`ORM2Core.xsd` types every `id` as `xs:ID` and every `ref` as `xs:IDREF`, so an XML validator
already proves that ids are unique and that every reference resolves. What it cannot prove is
that a reference resolves to the *right kind* of element: a `RolePlayer` pointing at a
`Reading` validates cleanly, and NORMA would reject it.

This checks the typed and cross-element invariants a schema cannot express. It is not a
substitute for opening the file in NORMA -- nothing here is -- but it covers the failures a
generator is most likely to produce.

    ormcheck.py FILE.orm [FILE.orm ...]
"""

import argparse
import sys
import xml.etree.ElementTree as ET

ORM = "{http://schemas.neumont.edu/ORM/2006-04/ORMCore}"
OBJECT_TYPES = {"EntityType", "ValueType", "ObjectifiedType"}


def tag(el):
    return el.tag.split("}")[-1]


def check(path):
    root = ET.parse(path).getroot()
    model = root.find(ORM + "ORMModel")
    if model is None:
        model = root if tag(root) == "ORMModel" else None
    if model is None:
        return ["no ORMModel element"]

    by_id = {}
    for el in model.iter():
        if el.get("id"):
            by_id.setdefault(el.get("id"), el)

    problems = []

    def kind_of(ref):
        el = by_id.get(ref)
        return tag(el) if el is not None else None

    def want(ref, kinds, what):
        k = kind_of(ref)
        if k is None:
            problems.append("%s references %s, which no element declares" % (what, ref))
        elif k not in kinds:
            problems.append("%s references a %s; expected %s"
                            % (what, k, " or ".join(sorted(kinds))))

    # a role is played by an object type, never by anything else
    for fact in model.iter():
        if tag(fact) not in ("Fact", "SubtypeFact", "ImpliedFact"):
            continue
        fact_roles = {r.get("id") for r in fact.iter()
                      if tag(r) in ("Role", "SubtypeMetaRole", "SupertypeMetaRole")
                      and r.get("id")}
        for role in fact.iter():
            if tag(role) not in ("Role", "SubtypeMetaRole", "SupertypeMetaRole"):
                continue
            player = role.find(ORM + "RolePlayer")
            if player is not None:
                want(player.get("ref"), OBJECT_TYPES,
                     "%s %s RolePlayer" % (fact.get("_Name") or tag(fact), role.get("id", "?")))

        # a reading order's role sequence names roles of its own fact type, and a reading's
        # slots match that sequence
        for order in fact.iter(ORM + "ReadingOrder"):
            seq = [r.get("ref") for r in order.iter(ORM + "Role") if r.get("ref")]
            for ref in seq:
                if ref not in fact_roles:
                    problems.append("%s ReadingOrder names role %s, which belongs to another "
                                    "fact type" % (fact.get("_Name") or "?", ref))
            for reading in order.iter(ORM + "Reading"):
                data = reading.find(ORM + "Data")
                text = (data.text or "") if data is not None else ""
                slots = {int(s) for s in _slots(text)}
                if slots and (max(slots) + 1) != len(seq):
                    problems.append("%s reading %r has %d slots for %d roles"
                                    % (fact.get("_Name") or "?", text, max(slots) + 1, len(seq)))

    for objectified in model.iter(ORM + "ObjectifiedType"):
        nested = objectified.find(ORM + "NestedPredicate")
        if nested is None:
            problems.append("ObjectifiedType %s has no NestedPredicate"
                            % objectified.get("Name"))
        else:
            want(nested.get("ref"), {"Fact"},
                 "ObjectifiedType %s NestedPredicate" % objectified.get("Name"))

    for el in model.iter(ORM + "PreferredIdentifier"):
        want(el.get("ref"), {"UniquenessConstraint"}, "PreferredIdentifier")

    for el in model.iter(ORM + "PreferredIdentifierFor"):
        want(el.get("ref"), OBJECT_TYPES, "PreferredIdentifierFor")

    for container in model.iter(ORM + "InternalConstraints"):
        for ref in container:
            want(ref.get("ref"), {"UniquenessConstraint", "MandatoryConstraint",
                                  "FrequencyConstraint", "RingConstraint"},
                 "InternalConstraints entry")

    for played in model.iter(ORM + "PlayedRoles"):
        for ref in played:
            want(ref.get("ref"), {"Role", "SubtypeMetaRole", "SupertypeMetaRole"},
                 "PlayedRoles entry")

    constraints = model.find(ORM + "Constraints")
    if constraints is not None:
        for c in constraints:
            for role in c.iter(ORM + "Role"):
                want(role.get("ref"), {"Role", "SubtypeMetaRole", "SupertypeMetaRole"},
                     "%s %s role sequence" % (tag(c), c.get("Name") or c.get("id")))

    for vt in model.iter(ORM + "ValueType"):
        if vt.find(ORM + "ConceptualDataType") is None:
            problems.append("ValueType %s has no ConceptualDataType" % vt.get("Name"))

    return problems


def _slots(text):
    out, i = [], 0
    while True:
        a = text.find("{", i)
        if a < 0:
            return out
        b = text.find("}", a)
        if b < 0:
            return out
        body = text[a + 1:b]
        if body.isdigit():
            out.append(body)
        i = b + 1


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+")
    args = p.parse_args(argv)
    failed = 0
    for path in args.files:
        problems = check(path)
        if problems:
            failed += 1
            print("FAIL  %s" % path)
            for m in problems[:12]:
                print("        %s" % m)
            if len(problems) > 12:
                print("        ... and %d more" % (len(problems) - 12))
        else:
            print("ok    %s  (typed references and cross-element consistency)" % path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
