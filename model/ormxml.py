"""Export a Common Core Model to a NORMA .orm file.

Implements the schema half of model/binding-ormcore.md section 1. The query half is not
needed yet: the reverse engineer, which is what exports, derives no queries, and section 3
of that document lists what would not survive if it did.

Ids become GUID-shaped so NORMA is happy with them; the mapping from CCM id to GUID is
deterministic, so re-running the exporter on the same model produces the same file.
"""

from __future__ import annotations

import hashlib
import os
import sys
import xml.etree.ElementTree as ET
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.ccm import Index                                            # noqa: E402

ORM = "http://schemas.neumont.edu/ORM/2006-04/ORMCore"
ROOT = "http://schemas.neumont.edu/ORM/2006-04/ORMRoot"

ET.register_namespace("orm", ORM)
ET.register_namespace("ormRoot", ROOT)


def guid(key: str) -> str:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return "_%s-%s-%s-%s-%s" % (h[0:8].upper(), h[8:12].upper(), h[12:16].upper(),
                                h[16:20].upper(), h[20:32].upper())


def _e(parent, tag, **attrs):
    return ET.SubElement(parent, "{%s}%s" % (ORM, tag),
                         {k: str(v) for k, v in attrs.items() if v is not None})


_DATATYPES = {
    "varchar": "VariableLengthTextDataType", "nvarchar": "VariableLengthTextDataType",
    "character": "FixedLengthTextDataType", "char": "FixedLengthTextDataType",
    "nchar": "FixedLengthTextDataType", "text": "LargeLengthTextDataType",
    "int": "SignedIntegerNumericDataType", "integer": "SignedIntegerNumericDataType",
    "bigint": "SignedLargeIntegerNumericDataType",
    "smallint": "SignedSmallIntegerNumericDataType",
    "numeric": "DecimalNumericDataType", "decimal": "DecimalNumericDataType",
    "real": "FloatingPointNumericDataType", "float": "FloatingPointNumericDataType",
    "double": "DoublePrecisionFloatingPointNumericDataType",
    "date": "DateTemporalDataType", "time": "TimeTemporalDataType",
    "timestamp": "DateAndTimeTemporalDataType", "datetime": "DateAndTimeTemporalDataType",
    "boolean": "TrueOrFalseLogicalDataType", "bool": "TrueOrFalseLogicalDataType",
    "blob": "VariableLengthRawDataDataType", "bytea": "VariableLengthRawDataDataType",
}


def export(model: dict) -> bytes:
    ix = Index(model)
    roles, role_owner = ix.roles, ix.role_owner

    # Group the internal constraints by the fact type that owns them, once. Testing every
    # constraint against every fact type inside the fact loop is quadratic in schema size,
    # and on a 100-table model it was most of the export.
    internal_by_fact: Dict[str, list] = {}
    for k in model.get("constraints", []):
        if k["kind"] not in ("uniqueness", "mandatory"):
            continue
        owners = {role_owner.get(rid) for s in k.get("roleSequences", []) for rid in s}
        if len(owners) == 1:
            owner = owners.pop()
            if owner is not None:
                internal_by_fact.setdefault(owner, []).append(k)

    doc = ET.Element("{%s}ORM2" % ROOT)
    orm_model = _e(doc, "ORMModel", id=guid(model["id"]), Name=model.get("name", "Model"))

    objects = _e(orm_model, "Objects")
    datatypes_used = {}

    for c in model["concepts"]:
        if c["kind"] == "value":
            vt = _e(objects, "ValueType", id=guid(c["id"]), Name=c["name"])
            dt = c.get("dataType", {"name": "text"})
            kind = _DATATYPES.get(dt["name"], "VariableLengthTextDataType")
            dt_id = datatypes_used.setdefault(kind, guid("dt." + kind))
            ref = _e(vt, "ConceptualDataType", id=guid(c["id"] + ".cdt"), ref=dt_id)
            if dt.get("length"):
                ref.set("Length", str(dt["length"]))
            if dt.get("scale") is not None:
                ref.set("Scale", str(dt["scale"]))
            if c.get("restriction"):
                _restriction(vt, c["id"], c["restriction"])

        elif c["kind"] == "entity":
            nested = ix.fact_behind(c["id"])
            tag = "ObjectifiedType" if nested else "EntityType"
            et = _e(objects, tag, id=guid(c["id"]), Name=c["name"],
                    IsIndependent=str(c.get("isIndependent", False)).lower(),
                    _ReferenceMode=c.get("referenceMode", ""))
            # ObjectTypeType's own elements come before the extension's, so PlayedRoles
            # precedes PreferredIdentifier and NestedPredicate.
            played = _e(et, "PlayedRoles")
            for rid in ix.roles_by_player.get(c["id"], []):
                _e(played, "Role", ref=guid(rid))
            if c.get("identifier"):
                _e(et, "PreferredIdentifier",
                   ref=guid("uc:%s" % "+".join(sorted(c["identifier"]))))
            if nested:
                _e(et, "NestedPredicate", id=guid(c["id"] + ".nested"), ref=guid(nested))

    facts = _e(orm_model, "Facts")
    for c in model["concepts"]:
        if c["kind"] != "fact":
            continue
        fact = _e(facts, "Fact", id=guid(c["id"]), _Name=c["name"])
        fact_roles = _e(fact, "FactRoles")
        for r in c["roles"]:
            role_el = _e(fact_roles, "Role", id=guid(r["id"]), Name=r.get("name", ""),
                         _IsMandatory=str(r.get("isMandatory", False)).lower())
            _e(role_el, "RolePlayer", ref=guid(r["player"]))
        orders = _e(fact, "ReadingOrders")
        for rd in c.get("readings", []):
            order = _e(orders, "ReadingOrder", id=guid(rd["id"] + ".order"))
            readings = _e(order, "Readings")
            reading = _e(readings, "Reading", id=guid(rd["id"]))
            _e(reading, "Data").text = rd["text"]
            seq = _e(order, "RoleSequence")
            for rid in rd["roleSequence"]:
                _e(seq, "Role", ref=guid(rid))
        internal = internal_by_fact.get(c["id"], [])
        if internal:
            container = _e(fact, "InternalConstraints")
            for k in internal:
                tag = "UniquenessConstraint" if k["kind"] == "uniqueness" \
                    else "MandatoryConstraint"
                _e(container, tag, ref=guid(_constraint_key(k)))

    # Subtyping is a fact type in ORM, not an attribute of the subtype.
    for c in model["concepts"]:
        for sup in c.get("supertypes", []):
            sf = _e(facts, "SubtypeFact", id=guid("st.%s.%s" % (c["id"], sup)),
                    IsPrimary="true", PreferredIdentificationPath="true")
            fr = _e(sf, "FactRoles")
            sub_role = _e(fr, "SubtypeMetaRole", id=guid("st.%s.%s.sub" % (c["id"], sup)))
            _e(sub_role, "RolePlayer", ref=guid(c["id"]))
            sup_role = _e(fr, "SupertypeMetaRole", id=guid("st.%s.%s.sup" % (c["id"], sup)))
            _e(sup_role, "RolePlayer", ref=guid(sup))

    constraints = _e(orm_model, "Constraints")
    for k in model.get("constraints", []):
        if k["kind"] != "uniqueness":
            continue
        uc = _e(constraints, "UniquenessConstraint", id=guid(_constraint_key(k)),
                Name=k["id"], IsInternal=str(_is_internal(k, role_owner)).lower())
        seq = _e(uc, "RoleSequence")
        for rid in k.get("roleSequences", [[]])[0]:
            _e(seq, "Role", ref=guid(rid))
        if k.get("isPreferredIdentifier"):
            owner = _identified_entity(k, model)
            if owner:
                _e(uc, "PreferredIdentifierFor", ref=guid(owner))

    for c in model["concepts"]:
        if c["kind"] != "fact":
            continue
        for r in c["roles"]:
            if r.get("isMandatory"):
                mc = _e(constraints, "MandatoryConstraint",
                        id=guid("mc." + r["id"]), Name="mc_" + r["id"], IsSimple="true")
                seq = _e(mc, "RoleSequence")
                _e(seq, "Role", ref=guid(r["id"]))

    dts = _e(orm_model, "DataTypes")
    for kind, dt_id in sorted(datatypes_used.items()):
        _e(dts, kind, id=dt_id)

    ET.indent(doc, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(doc, encoding="utf-8")


def _restriction(parent, cid, restriction):
    vr = _e(parent, "ValueRestriction")
    vrc = _e(vr, "ValueConstraint", id=guid(cid + ".vc"), Name="vc_" + cid.split(".")[-1])
    ranges = _e(vrc, "ValueRanges")
    for v in restriction.get("values", []):
        _e(ranges, "ValueRange", id=guid(cid + ".v." + str(v)), MinValue=v, MaxValue=v,
           MinInclusion="NotSet", MaxInclusion="NotSet")
    for r in restriction.get("ranges", []):
        _e(ranges, "ValueRange", id=guid(cid + ".r." + str(r)),
           MinValue=r.get("min", ""), MaxValue=r.get("max", ""),
           MinInclusion="NotSet", MaxInclusion="NotSet")


def _constraint_key(k):
    return "uc:%s" % "+".join(sorted(s for seq in k.get("roleSequences", []) for s in seq)) \
        if k.get("isPreferredIdentifier") else "k:" + k["id"]


def _is_internal(k, role_owner):
    owners = {role_owner.get(rid) for seq in k.get("roleSequences", []) for rid in seq}
    return len(owners) <= 1


def _identified_entity(k, model):
    for c in model["concepts"]:
        if c.get("identifier") and \
                sorted(c["identifier"]) == sorted(k.get("roleSequences", [[]])[0]):
            return c["id"]
    return None
