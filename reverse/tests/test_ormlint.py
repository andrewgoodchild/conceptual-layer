#!/usr/bin/env python3
"""ormlint.py on fixtures whose defects are known.

Every check is pinned twice: once on a model that has the defect, once on a model that does
not. The negatives matter more than the positives here. A linter that fires on sound models
gets switched off, and the first draft of `mandatory-role-empty` did exactly that -- it
reported 92 findings across the benchmark models, every one of them a mandatory *value*
role over a nullable column, which is vacuous rather than wrong.

    test_ormlint.py [-v] [--only SUBSTRING]
"""

import argparse
import copy
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import ormlint                                                        # noqa: E402

SCHEMA = """
CREATE TABLE person   (pname TEXT PRIMARY KEY, nickname TEXT);
CREATE TABLE employee (pname TEXT PRIMARY KEY, payroll TEXT, dept TEXT,
                       orgref TEXT);
CREATE TABLE dept     (dname TEXT PRIMARY KEY);
INSERT INTO person   VALUES ('ann', NULL), ('bob', 'bo'), ('cal', NULL);
INSERT INTO employee VALUES ('ann','p1','eng','eng'), ('bob','p2','eng','eng'),
                            ('cal','p3','eng','eng');
INSERT INTO dept     VALUES ('eng');
"""

#  Person is identified by pname; Employee is a table whose key is its foreign key -- the
#  shape rule 7 reads as subtyping. Here it holds all three persons, so it is not one.
MODEL = {
    "id": "m.fixture", "ccmVersion": "1.0", "name": "fixture",
    "concepts": [
        {"id": "et.Person", "name": "Person", "kind": "entity",
         "identifier": ["r.PersonHasPname.person"]},
        {"id": "vt.PersonPname", "name": "PersonPname", "kind": "value"},
        {"id": "vt.PersonNickname", "name": "PersonNickname", "kind": "value"},
        {"id": "vt.EmployeePayroll", "name": "EmployeePayroll", "kind": "value"},
        {"id": "et.Dept", "name": "Dept", "kind": "entity",
         "identifier": ["r.DeptHasDname.dept"]},
        {"id": "vt.DeptDname", "name": "DeptDname", "kind": "value"},
        {"id": "et.Employee", "name": "Employee", "kind": "entity",
         "identifier": ["r.PersonHasPname.person"], "supertypes": ["et.Person"]},
        {"id": "ft.PersonHasPname", "name": "PersonHasPname", "kind": "fact",
         "roles": [{"id": "r.PersonHasPname.person", "player": "et.Person",
                    "isMandatory": True, "name": "Person", "ordinal": 0},
                   {"id": "r.PersonHasPname.pname", "player": "vt.PersonPname",
                    "isMandatory": True, "name": "Pname", "ordinal": 1}],
         "readings": [{"id": "rd.PersonHasPname", "text": "{0} has {1}",
                       "roleSequence": ["r.PersonHasPname.person",
                                        "r.PersonHasPname.pname"]}]},
        {"id": "ft.PersonHasNickname", "name": "PersonHasNickname", "kind": "fact",
         "roles": [{"id": "r.PersonHasNickname.person", "player": "et.Person",
                    "isMandatory": False, "name": "Person", "ordinal": 0},
                   {"id": "r.PersonHasNickname.nickname", "player": "vt.PersonNickname",
                    "isMandatory": True, "name": "Nickname", "ordinal": 1}],
         "readings": [{"id": "rd.PersonHasNickname", "text": "{0} has {1}",
                       "roleSequence": ["r.PersonHasNickname.person",
                                        "r.PersonHasNickname.nickname"]}]},
        {"id": "ft.EmployeeHasPayroll", "name": "EmployeeHasPayroll", "kind": "fact",
         "roles": [{"id": "r.EmployeeHasPayroll.employee", "player": "et.Employee",
                    "isMandatory": True, "name": "Employee", "ordinal": 0},
                   {"id": "r.EmployeeHasPayroll.payroll", "player": "vt.EmployeePayroll",
                    "isMandatory": True, "name": "Payroll", "ordinal": 1}],
         "readings": [{"id": "rd.EmployeeHasPayroll", "text": "{0} has {1}",
                       "roleSequence": ["r.EmployeeHasPayroll.employee",
                                        "r.EmployeeHasPayroll.payroll"]}]},
        {"id": "ft.DeptHasDname", "name": "DeptHasDname", "kind": "fact",
         "roles": [{"id": "r.DeptHasDname.dept", "player": "et.Dept",
                    "isMandatory": True, "name": "Dept", "ordinal": 0},
                   {"id": "r.DeptHasDname.dname", "player": "vt.DeptDname",
                    "isMandatory": True, "name": "Dname", "ordinal": 1}],
         "readings": [{"id": "rd.DeptHasDname", "text": "{0} has {1}",
                       "roleSequence": ["r.DeptHasDname.dept", "r.DeptHasDname.dname"]}]},
        {"id": "ft.EmployeeHasDept", "name": "EmployeeHasDept", "kind": "fact",
         "roles": [{"id": "r.EmployeeHasDept.employee", "player": "et.Employee",
                    "isMandatory": True, "name": "Employee", "ordinal": 0},
                   {"id": "r.EmployeeHasDept.dept", "player": "et.Dept",
                    "isMandatory": True, "name": "Dept", "ordinal": 1}],
         "readings": [{"id": "rd.EmployeeHasDept", "text": "{0} has {1}",
                       "roleSequence": ["r.EmployeeHasDept.employee",
                                        "r.EmployeeHasDept.dept"]}]},
    ],
    "constraints": [
        {"id": "uc.PersonHasPname", "kind": "uniqueness",
         "roleSequences": [["r.PersonHasPname.person"]], "isPreferredIdentifier": True},
        {"id": "uc.PersonHasNickname", "kind": "uniqueness",
         "roleSequences": [["r.PersonHasNickname.person"]]},
        {"id": "uc.EmployeeHasPayroll", "kind": "uniqueness",
         "roleSequences": [["r.EmployeeHasPayroll.employee"]]},
        {"id": "uc.DeptHasDname", "kind": "uniqueness",
         "roleSequences": [["r.DeptHasDname.dept"]], "isPreferredIdentifier": True},
        {"id": "uc.EmployeeHasDept", "kind": "uniqueness",
         "roleSequences": [["r.EmployeeHasDept.employee"]]},
    ],
    "mapping": {
        "tables": [{"id": "t.person", "name": "person"},
                   {"id": "t.employee", "name": "employee"},
                   {"id": "t.dept", "name": "dept"}],
        "columns": [
            {"id": "c.person.pname", "table": "t.person", "name": "pname",
             "dataType": {"name": "text"}, "nullable": False},
            {"id": "c.person.nickname", "table": "t.person", "name": "nickname",
             "dataType": {"name": "text"}, "nullable": True},
            {"id": "c.employee.pname", "table": "t.employee", "name": "pname",
             "dataType": {"name": "text"}, "nullable": False},
            {"id": "c.employee.payroll", "table": "t.employee", "name": "payroll",
             "dataType": {"name": "text"}, "nullable": True},
            {"id": "c.employee.dept", "table": "t.employee", "name": "dept",
             "dataType": {"name": "text"}, "nullable": True},
            {"id": "c.employee.orgref", "table": "t.employee", "name": "orgref",
             "dataType": {"name": "text"}, "nullable": True},
            {"id": "c.dept.dname", "table": "t.dept", "name": "dname",
             "dataType": {"name": "text"}, "nullable": False},
        ],
        "conceptMap": [
            {"concept": "et.Person", "table": "t.person",
             "identifyingColumns": ["c.person.pname"]},
            {"concept": "et.Employee", "table": "t.employee",
             "identifyingColumns": ["c.employee.pname"]},
            {"concept": "et.Dept", "table": "t.dept",
             "identifyingColumns": ["c.dept.dname"]},
            {"concept": "ft.PersonHasPname", "table": "t.person",
             "identifyingColumns": ["c.person.pname"]},
            {"concept": "ft.PersonHasNickname", "table": "t.person",
             "identifyingColumns": ["c.person.pname"]},
            {"concept": "ft.EmployeeHasPayroll", "table": "t.employee",
             "identifyingColumns": ["c.employee.pname"]},
            {"concept": "ft.EmployeeHasDept", "table": "t.employee",
             "identifyingColumns": ["c.employee.pname"]},
            {"concept": "ft.DeptHasDname", "table": "t.dept",
             "identifyingColumns": ["c.dept.dname"]},
        ],
        "roleMap": [
            {"role": "r.PersonHasPname.person", "table": "t.person",
             "columns": ["c.person.pname"]},
            {"role": "r.PersonHasPname.pname", "table": "t.person",
             "columns": ["c.person.pname"]},
            {"role": "r.PersonHasNickname.person", "table": "t.person",
             "columns": ["c.person.pname"]},
            {"role": "r.PersonHasNickname.nickname", "table": "t.person",
             "columns": ["c.person.nickname"]},
            {"role": "r.EmployeeHasPayroll.employee", "table": "t.employee",
             "columns": ["c.employee.pname"]},
            {"role": "r.EmployeeHasPayroll.payroll", "table": "t.employee",
             "columns": ["c.employee.payroll"]},
            {"role": "r.EmployeeHasDept.employee", "table": "t.employee",
             "columns": ["c.employee.pname"]},
            {"role": "r.EmployeeHasDept.dept", "table": "t.employee",
             "columns": ["c.employee.dept"]},
            {"role": "r.DeptHasDname.dept", "table": "t.dept",
             "columns": ["c.dept.dname"]},
            {"role": "r.DeptHasDname.dname", "table": "t.dept",
             "columns": ["c.dept.dname"]},
        ],
    },
}


# --------------------------------------------------------------------------- harness

TMP = tempfile.mkdtemp(prefix="ormlint-")
DB = os.path.join(TMP, "fixture.sqlite")
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def run(model, db=DB, edit=None):
    """Lint a (possibly edited) copy of the fixture, returning check name -> messages."""
    m = copy.deepcopy(model)
    if edit:
        edit(m)
    path = os.path.join(TMP, "m.ccm.json")
    json.dump(m, open(path, "w"))
    out = ormlint.lint(path, db)
    found = {}
    for _, chk, where, message in out.items:
        found.setdefault(chk, []).append("%s: %s" % (where, message))
    return found


def concept(m, cid):
    return next(c for c in m["concepts"] if c["id"] == cid)


def expect(found, check, n, note=""):
    got = len(found.get(check, []))
    assert got == n, "%s: expected %d finding(s), got %d %s%s" % (
        check, n, got, found.get(check, []), (" -- " + note) if note else "")


# --------------------------------------------------------------------------- identity

@case
def test_subtype_restating_the_supertype_identifier_is_flagged():
    """Employee's identifier names r.PersonHasPname.person, a role Person plays."""
    found = run(MODEL)
    expect(found, "identifier-not-played", 1)
    assert "played by Person" in found["identifier-not-played"][0]


@case
def test_inheriting_without_restating_is_clean():
    """The repair: drop the subtype's identifier and let it inherit."""
    found = run(MODEL, edit=lambda m: concept(m, "et.Employee").pop("identifier"))
    expect(found, "identifier-not-played", 0)
    expect(found, "identifier-missing", 0, "a subtype inherits identification")


@case
def test_an_objectified_fact_types_identifier_is_not_flagged():
    """Assignment objectifies EmployeeHasDept, so it is identified by that fact type's roles
    -- whose players are Employee and Dept, not Assignment. Correct ORM, not a dangling ref."""
    def objectify(m):
        concept(m, "ft.EmployeeHasDept").update(name="Assignment", isObjectified=True)
        m["concepts"].append({"id": "et.Assignment", "name": "Assignment", "kind": "entity",
                              "identifier": ["r.EmployeeHasDept.employee",
                                             "r.EmployeeHasDept.dept"]})
    found = run(MODEL, edit=objectify)
    assert not any("Assignment" in f for f in found.get("identifier-not-played", [])), \
        "objectified identifier reported: %s" % found.get("identifier-not-played")


@case
def test_entity_with_no_identifier_is_flagged():
    found = run(MODEL, edit=lambda m: concept(m, "et.Dept").update(identifier=[]))
    expect(found, "identifier-missing", 1)


@case
def test_identifier_naming_an_unknown_role_is_flagged():
    def bad(m):
        concept(m, "et.Dept").update(identifier=["r.nope"])
        concept(m, "et.Employee").pop("identifier")       # isolate: Employee has its own
    found = run(MODEL, edit=bad)
    expect(found, "identifier-not-played", 1)
    assert "not a role in this model" in found["identifier-not-played"][0]


# --------------------------------------------------------------------------- subtyping

@case
def test_a_chain_of_empty_subtype_identifiers_is_flagged():
    """credit's failure shape: three subtypes deep, every identifier empty. Exempting a
    subtype from `identifier-missing` must not exempt one whose ancestors are empty too."""
    def chain(m):
        concept(m, "et.Employee").update(identifier=[])
        m["concepts"].append({"id": "et.Contractor", "name": "Contractor", "kind": "entity",
                              "identifier": [], "supertypes": ["et.Employee"]})
    found = run(MODEL, edit=chain)
    expect(found, "subtype-identifier-differs", 2,
           "both carry [] where the chain supplies Person's identifier")
    assert "inherited from" in found["subtype-identifier-differs"][0]
    expect(found, "identifier-missing", 0, "the chain does reach an identified Person")


@case
def test_a_chain_rooted_in_nothing_is_unidentifiable():
    """No ancestor is identified, so every link in the chain is undenotable."""
    def chain(m):
        m["concepts"].append({"id": "et.Ghost", "name": "Ghost", "kind": "entity"})
        m["concepts"].append({"id": "et.Wraith", "name": "Wraith", "kind": "entity",
                              "supertypes": ["et.Ghost"]})
    found = run(MODEL, edit=chain)
    expect(found, "identifier-missing", 2)
    assert "inherits none either" in "".join(found["identifier-missing"])


@case
def test_a_subtype_of_an_identified_supertype_is_exempt():
    """Two levels down from Person, which is identified: nothing to report."""
    def chain(m):
        concept(m, "et.Employee").pop("identifier")
        m["concepts"].append({"id": "et.Contractor", "name": "Contractor", "kind": "entity",
                              "supertypes": ["et.Employee"]})
    expect(run(MODEL, edit=chain), "identifier-missing", 0)


@case
def test_subtype_without_a_defining_condition_is_flagged():
    found = run(MODEL)
    expect(found, "subtype-undefined", 1)


@case
def test_a_defined_subtype_is_clean():
    def add_rule(m):
        m["derivationRules"] = [{"id": "dr.Employee",
                                 "target": {"kind": "subtype", "ref": "et.Employee"},
                                 "source": "Person has EmployeePayroll"}]
    expect(run(MODEL, edit=add_rule), "subtype-undefined", 0)


@case
def test_subtype_holding_the_whole_supertype_is_flagged():
    """Three employees, three persons: a vertical partition, not a subtype."""
    found = run(MODEL)
    expect(found, "subtype-not-proper", 1)
    assert "vertical partition" in found["subtype-not-proper"][0]


@case
def test_a_proper_subset_is_clean():
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM employee WHERE pname = 'cal'")
    conn.commit()
    try:
        expect(run(MODEL), "subtype-not-proper", 0, "2 of 3 is a proper subset")
    finally:
        conn.execute("INSERT INTO employee VALUES ('cal', 'p3', 'eng', 'eng')")
        conn.commit()


@case
def test_an_empty_inherited_identifier_is_flagged():
    """The eager-copy failure: the supertype was not resolved when the copy was taken."""
    found = run(MODEL, edit=lambda m: concept(m, "et.Employee").update(identifier=[]))
    expect(found, "subtype-identifier-differs", 1)


# --------------------------------------------------------------------------- constraints

@case
def test_fact_type_without_uniqueness_is_flagged():
    found = run(MODEL, edit=lambda m: m["constraints"].remove(
        next(k for k in m["constraints"] if k["id"] == "uc.EmployeeHasDept")))
    expect(found, "fact-type-no-uniqueness", 1)


@case
def test_uniqueness_the_data_breaks_is_flagged():
    """Claim the nickname role is unique; two persons have a null nickname."""
    def dup(m):
        m["constraints"].append({"id": "uc.nick", "kind": "uniqueness",
                                 "roleSequences": [["r.PersonHasNickname.nickname"]]})
    found = run(MODEL, edit=dup)
    expect(found, "uniqueness-violated", 1)
    assert "not unique" in found["uniqueness-violated"][0]


@case
def test_sound_uniqueness_is_clean():
    expect(run(MODEL), "uniqueness-violated", 0)


@case
def test_mandatory_entity_role_over_a_null_column_is_flagged():
    """EmployeeHasDept.employee is mandatory; null one row of the key it maps to."""
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO employee VALUES ('dee', 'p4', NULL, NULL)")
    conn.commit()
    try:
        found = run(MODEL)
        expect(found, "mandatory-role-empty", 1)
        assert "employee.dept is null in 1 row" in found["mandatory-role-empty"][0]
    finally:
        conn.execute("DELETE FROM employee WHERE pname = 'dee'")
        conn.commit()


@case
def test_mandatory_value_role_over_a_null_column_is_not_flagged():
    """The false positive that made the first draft useless.

    PersonHasNickname.nickname is mandatory and person.nickname is null for two of three
    rows. That is not a contradiction: the value type's population is the column's values,
    which never includes null, so the constraint is vacuously satisfied."""
    found = run(MODEL)
    assert sqlite3.connect(DB).execute(
        "select count(*) from person where nickname is null").fetchone()[0] == 2
    expect(found, "mandatory-role-empty", 0,
           "a mandatory value role ranges over values, not over rows")


@case
def test_fact_type_with_no_mandatory_role_is_a_note():
    def loosen(m):
        for r in concept(m, "ft.PersonHasNickname")["roles"]:
            r["isMandatory"] = False
    found = run(MODEL, edit=loosen)
    expect(found, "fact-type-no-mandatory-role", 1)


# --------------------------------------------------------------------------- readings

@case
def test_reading_that_drops_a_role_is_flagged():
    found = run(MODEL, edit=lambda m: concept(m, "ft.EmployeeHasDept")["readings"][0]
                .update(text="{0} has a department"))
    expect(found, "reading-arity", 1)


@case
def test_a_hyphen_bound_reference_column_is_flagged():
    """'{0} has deptref- {1}' binds the foreign key where the role's meaning belongs."""
    found = run(MODEL, edit=lambda m: concept(m, "ft.EmployeeHasDept")["readings"][0]
                .update(text="{0} has deptref- {1}"))
    expect(found, "reading-adjective-is-a-reference", 1)
    assert "'deptref'" in found["reading-adjective-is-a-reference"][0]


@case
def test_a_hyphen_bound_role_name_is_clean():
    """FORML 2 section 1.2: '{0} has manager- {1}' is the correct construction, not a defect.
    The first draft of this check flagged all 177 hyphens in the corpus, every one correct."""
    found = run(MODEL, edit=lambda m: concept(m, "ft.EmployeeHasDept")["readings"][0]
                .update(text="{0} has manager- {1}"))
    expect(found, "reading-adjective-is-a-reference", 0)


@case
def test_a_plain_reading_is_clean():
    found = run(MODEL)
    expect(found, "reading-adjective-is-a-reference", 0)
    expect(found, "reading-arity", 0)


@case
def test_a_hyphen_inside_a_verb_phrase_is_not_flagged():
    """`is co-located with` is a verb phrase: the hyphen binds no object type."""
    found = run(MODEL, edit=lambda m: concept(m, "ft.EmployeeHasDept")["readings"][0]
                .update(text="{0} is co-located with {1}"))
    expect(found, "reading-adjective-is-a-reference", 0)


# --------------------------------------------------------------------------- naming

@case
def test_fact_type_named_for_the_foreign_key_is_flagged():
    """Named for the column the role maps to -- `EmployeeHasOrgref` over employee.orgref."""
    def rename(m):
        concept(m, "ft.EmployeeHasDept").update(name="EmployeeHasOrgref")
        next(r for r in m["mapping"]["roleMap"]
             if r["role"] == "r.EmployeeHasDept.dept")["columns"] = ["c.employee.orgref"]
    found = run(MODEL, edit=rename)
    expect(found, "fact-type-named-for-column", 1)
    assert "'orgref'" in found["fact-type-named-for-column"][0]


@case
def test_a_verb_phrase_name_omitting_the_far_type_is_clean():
    """`TelescopeIsAt` does not mention Observatory and is a better name than one that does.
    An earlier draft asked only whether the far type's name appeared, and reported both it
    and `SignalDetectedDuring` on a hand-built model."""
    found = run(MODEL, edit=lambda m: concept(m, "ft.EmployeeHasDept")
                .update(name="EmployeeWorksIn"))
    expect(found, "fact-type-named-for-column", 0)


@case
def test_a_model_with_no_mapping_skips_the_column_checks():
    """A hand-built model carries no relational mapping and is not wrong for it."""
    found = run(MODEL, edit=lambda m: m.pop("mapping"))
    expect(found, "fact-type-named-for-column", 0)
    expect(found, "subtype-undefined", 1, "model-only checks still run")


@case
def test_fact_type_named_for_the_type_it_reaches_is_clean():
    expect(run(MODEL), "fact-type-named-for-column", 0)


@case
def test_an_entity_carrying_weather_and_no_time_is_flagged():
    """An observatory is a place; its air temperature is a fact about a moment. Stored as
    attributes of the place, only the latest can ever be held."""
    def weather(m):
        for nm, unit in (("AirTemperature", "degC"), ("WindSpeed", "m/s"),
                         ("Pressure", "hPa")):
            m["concepts"].append({"id": "vt.%s" % nm, "name": nm, "kind": "value",
                                  "dataType": {"name": "real"}, "unit": unit})
            m["concepts"].append({
                "id": "ft.Dept%s" % nm, "name": "Dept%s" % nm, "kind": "fact",
                "roles": [{"id": "r.Dept%s.dept" % nm, "player": "et.Dept",
                           "isMandatory": False, "name": "Dept", "ordinal": 0},
                          {"id": "r.Dept%s.v" % nm, "player": "vt.%s" % nm,
                           "isMandatory": True, "name": "V", "ordinal": 1}],
                "readings": [{"id": "rd.Dept%s" % nm, "text": "{0} has {1}",
                              "roleSequence": ["r.Dept%s.dept" % nm, "r.Dept%s.v" % nm]}]})
            m["constraints"].append({"id": "uc.Dept%s" % nm, "kind": "uniqueness",
                                     "roleSequences": [["r.Dept%s.dept" % nm]]})
    found = run(MODEL, edit=weather)
    expect(found, "entity-holds-a-reading", 1)
    assert "conditions at a moment" in found["entity-holds-a-reading"][0]


@case
def test_the_same_readings_beside_a_time_are_clean():
    """Given a time to hang them on, the readings are facts about a moment and say so."""
    def weather_and_time(m):
        for nm, unit in (("AirTemperature", "degC"), ("WindSpeed", "m/s")):
            m["concepts"].append({"id": "vt.%s" % nm, "name": nm, "kind": "value",
                                  "dataType": {"name": "real"}, "unit": unit})
            m["concepts"].append({
                "id": "ft.Dept%s" % nm, "name": "Dept%s" % nm, "kind": "fact",
                "roles": [{"id": "r.Dept%s.dept" % nm, "player": "et.Dept",
                           "isMandatory": False, "name": "Dept", "ordinal": 0},
                          {"id": "r.Dept%s.v" % nm, "player": "vt.%s" % nm,
                           "isMandatory": True, "name": "V", "ordinal": 1}],
                "readings": [{"id": "rd.Dept%s" % nm, "text": "{0} has {1}",
                              "roleSequence": ["r.Dept%s.dept" % nm, "r.Dept%s.v" % nm]}]})
            m["constraints"].append({"id": "uc.Dept%s" % nm, "kind": "uniqueness",
                                     "roleSequences": [["r.Dept%s.dept" % nm]]})
        m["concepts"].append({"id": "vt.ReadingTime", "name": "ReadingTime", "kind": "value",
                              "dataType": {"name": "timestamp"}})
        m["concepts"].append({
            "id": "ft.DeptAt", "name": "DeptAt", "kind": "fact",
            "roles": [{"id": "r.DeptAt.dept", "player": "et.Dept", "isMandatory": False,
                       "name": "Dept", "ordinal": 0},
                      {"id": "r.DeptAt.t", "player": "vt.ReadingTime", "isMandatory": True,
                       "name": "T", "ordinal": 1}],
            "readings": [{"id": "rd.DeptAt", "text": "{0} read at {1}",
                          "roleSequence": ["r.DeptAt.dept", "r.DeptAt.t"]}]})
        m["constraints"].append({"id": "uc.DeptAt", "kind": "uniqueness",
                                 "roleSequences": [["r.DeptAt.dept"]]})
    expect(run(MODEL, edit=weather_and_time), "entity-holds-a-reading", 0)


@case
def test_one_reading_is_not_enough_to_flag():
    def one(m):
        m["concepts"].append({"id": "vt.AirTemperature", "name": "AirTemperature",
                              "kind": "value", "dataType": {"name": "real"}, "unit": "degC"})
        m["concepts"].append({
            "id": "ft.DeptTemp", "name": "DeptTemp", "kind": "fact",
            "roles": [{"id": "r.DeptTemp.dept", "player": "et.Dept", "isMandatory": False,
                       "name": "Dept", "ordinal": 0},
                      {"id": "r.DeptTemp.v", "player": "vt.AirTemperature",
                       "isMandatory": True, "name": "V", "ordinal": 1}],
            "readings": [{"id": "rd.DeptTemp", "text": "{0} has {1}",
                          "roleSequence": ["r.DeptTemp.dept", "r.DeptTemp.v"]}]})
        m["constraints"].append({"id": "uc.DeptTemp", "kind": "uniqueness",
                                 "roleSequences": [["r.DeptTemp.dept"]]})
    expect(run(MODEL, edit=one), "entity-holds-a-reading", 0)


@case
def test_a_plain_model_carries_no_readings():
    expect(run(MODEL), "entity-holds-a-reading", 0)


@case
def test_unplayed_value_type_is_flagged():
    def orphan(m):
        m["concepts"].append({"id": "vt.Loose", "name": "Loose", "kind": "value"})
    expect(run(MODEL, edit=orphan), "value-type-unplayed", 1)


@case
def test_a_model_with_no_shared_domains_is_flagged_once():
    """One finding for the model, not one per value type."""
    expect(run(MODEL), "value-type-never-shared", 1)


@case
def test_one_shared_value_type_clears_it():
    """Point the nickname role at PersonPname: now one value type is played twice."""
    def share(m):
        concept(m, "ft.PersonHasNickname")["roles"][1]["player"] = "vt.PersonPname"
    expect(run(MODEL, edit=share), "value-type-never-shared", 0)


# --------------------------------------------------------------------------- data-optional

@case
def test_data_checks_are_skipped_without_a_database():
    found = run(MODEL, db=None)
    for chk in ("subtype-not-proper", "uniqueness-violated", "mandatory-role-empty"):
        expect(found, chk, 0, "needs --db")
    expect(found, "subtype-undefined", 1, "model-only checks still run")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

    cases = [c for c in CASES if not args.only or args.only in c.__name__]
    failed = 0
    for c in cases:
        try:
            c()
            if args.verbose:
                print("ok   %s" % c.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL %s\n       %s" % (c.__name__, e))
        except Exception as e:                                        # noqa: BLE001
            failed += 1
            print("ERROR %s\n       %s: %s" % (c.__name__, type(e).__name__, e))
    print("%d passed, %d failed" % (len(cases) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
