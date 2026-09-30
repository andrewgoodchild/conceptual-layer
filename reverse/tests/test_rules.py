#!/usr/bin/env python3
"""One test per derivation rule, on a schema written to isolate it.

`test_scenarios.py` runs whole messy schemas and asserts what comes out. This is the other
half: each rule in the table of `reverse/README.md` ("The rules") gets a minimal DDL that
exercises it and nothing else, so a failure names the rule rather than the scenario. The
naming rules (rule 10) get the same treatment, because they are pure functions and were the
source of several bugs.

    test_rules.py [-v] [--only SUBSTRING]
"""

import argparse
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import catalog as catalog_mod    # noqa: E402
import derive as derive_mod      # noqa: E402


def build(ddl, infer=False, partitions=False, merge=False, glossary=None,
          domains=False):
    """Derive a model from DDL. `partitions` additionally reads the rows the DDL inserted,
    which is what rule 7b needs -- it is the one rule the catalogue cannot decide alone."""
    path = tempfile.mktemp(suffix=".sqlite")
    conn = sqlite3.connect(path)
    conn.executescript(ddl)
    conn.commit()
    try:
        catalog = catalog_mod.from_sqlite(path)
        absorb = {}
        if partitions:
            import population as population_mod
            absorb = {child: parent for child, parent, _, _, covers
                      in population_mod.partitions(conn, catalog) if covers}
        model, report = derive_mod.derive(catalog, infer_undeclared_fks=infer, absorb=absorb,
                                          merge_domains=merge, glossary=glossary)
        if domains:
            import population as population_mod
            population_mod.apply_domains(population_mod.analyse(conn, catalog), model, report)
        return model, report
    finally:
        conn.close()
        os.unlink(path)


class Model:
    """Query helpers, so an assertion reads like the rule it is testing."""

    def __init__(self, model, report):
        self.model, self.report = model, report
        self.by_id = {c["id"]: c for c in model["concepts"]}

    def concept(self, name, kind=None):
        for c in self.model["concepts"]:
            if c["name"] == name and (kind is None or c["kind"] == kind):
                return c
        return None

    def fact(self, name):
        return self.concept(name, "fact")

    def players(self, fact_name):
        f = self.fact(fact_name)
        return [self.by_id[r["player"]]["name"] for r in f["roles"]] if f else None

    def identifier(self, entity_name):
        e = self.concept(entity_name, "entity")
        return len(e.get("identifier", [])) if e else None

    def readings(self, fact_name):
        f = self.fact(fact_name)
        return [r["text"] for r in f.get("readings", [])] if f else None

    def mandatory(self, fact_name, ordinal=0):
        f = self.fact(fact_name)
        return bool(f["roles"][ordinal].get("isMandatory")) if f else None

    def restriction(self, value_name):
        v = self.concept(value_name, "value")
        return (v or {}).get("restriction")

    def reported(self, rule, needle=""):
        return any(r["rule"] == rule and needle.lower() in
                   (r["subject"] + " " + r["message"]).lower()
                   for r in self.report.refinements)

    def identity_of(self, entity_name):
        """The column names an entity type's instances are identified by in the mapping."""
        e = self.concept(entity_name, "entity")
        cols = {c["id"]: c for c in self.model["mapping"]["columns"]}
        for m in self.model["mapping"]["conceptMap"]:
            if e and m["concept"] == e["id"]:
                return [cols[c]["name"] for c in m["identifyingColumns"]]
        return None

    def references_of(self, table, column):
        """What the role mapped to `table.column` references in the target table, if the
        foreign key points somewhere other than the target's identifier."""
        cols = {c["id"]: c for c in self.model["mapping"]["columns"]}
        tables = {t["id"]: t["name"] for t in self.model["mapping"]["tables"]}
        for m in self.model["mapping"]["roleMap"]:
            if tables[m["table"]].casefold() == table.casefold() and \
                    [cols[c]["name"].casefold() for c in m["columns"]] == [column.casefold()]:
                return [cols[c]["name"] for c in m["references"]] if m.get("references") else None
        return None

    def mapped_columns(self, role_suffix):
        for m in self.model.get("mapping", {}).get("roleMap", []):
            if m["role"].endswith(role_suffix):
                cols = {c["id"]: c for c in self.model["mapping"]["columns"]}
                return [cols[c]["name"] for c in m["columns"]]
        return None


# Each case: (rule, what it should do, DDL, assertion over the derived Model)
CASES = [
 ("rule 1", "a simple primary key becomes the reference mode",
  "CREATE TABLE person (person_id INTEGER PRIMARY KEY, person_name VARCHAR(40));",
  lambda m: m.concept("Person", "entity")["referenceMode"] == "id"
            and m.identifier("Person") == 1),

 ("rule 1", "a composite key identifies through several roles",
  "CREATE TABLE seat (row_no INTEGER NOT NULL, seat_no INTEGER NOT NULL,"
  " occupied CHAR(1), PRIMARY KEY (row_no, seat_no));",
  lambda m: m.identifier("Seat") == 2 and m.reported("rule 1", "composite")),

 ("rule 2", "a non-key column becomes a binary fact type to a value type",
  "CREATE TABLE person (person_id INTEGER PRIMARY KEY, nickname VARCHAR(40));",
  lambda m: m.players("PersonHasNickname") == ["Person", "PersonNickname"]),

 ("rule 2", "NOT NULL makes the entity's role mandatory",
  "CREATE TABLE person (person_id INTEGER PRIMARY KEY, a VARCHAR(9) NOT NULL, b VARCHAR(9));",
  lambda m: m.mandatory("PersonHasA") and not m.mandatory("PersonHasB")),

 ("rule 3", "a foreign key becomes a fact type to the referenced entity type",
  "CREATE TABLE dept (dept_id INTEGER PRIMARY KEY);"
  "CREATE TABLE emp (emp_id INTEGER PRIMARY KEY, dept_id INTEGER REFERENCES dept(dept_id));",
  lambda m: m.players("EmpHasDept") == ["Emp", "Dept"]),

 ("rule 3", "a foreign key column names its target, not its own table",
  "CREATE TABLE invoice (InvoiceId INTEGER PRIMARY KEY);"
  "CREATE TABLE InvoiceLine (InvoiceLineId INTEGER PRIMARY KEY,"
  " InvoiceId INTEGER REFERENCES invoice(InvoiceId));",
  lambda m: m.fact("InvoiceLineHasInvoice") is not None),

 ("rule 3", "two foreign keys to one table stay separate fact types",
  "CREATE TABLE airport (iata CHAR(3) PRIMARY KEY);"
  "CREATE TABLE flight (id INTEGER PRIMARY KEY,"
  " origin CHAR(3) REFERENCES airport(iata), destination CHAR(3) REFERENCES airport(iata));",
  lambda m: m.players("FlightHasOrigin") == ["Flight", "Airport"]
            and m.players("FlightHasDestination") == ["Flight", "Airport"]),

 ("rule 4", "a key of wholly foreign keys becomes an n-ary fact type",
  "CREATE TABLE a (a_id INTEGER PRIMARY KEY);CREATE TABLE b (b_id INTEGER PRIMARY KEY);"
  "CREATE TABLE ab (a_id INTEGER REFERENCES a(a_id), b_id INTEGER REFERENCES b(b_id),"
  " PRIMARY KEY (a_id, b_id));",
  lambda m: m.players("Ab") == ["A", "B"] and not m.fact("Ab").get("isObjectified")),

 ("rule 4", "an association carrying a payload is objectified",
  "CREATE TABLE a (a_id INTEGER PRIMARY KEY);CREATE TABLE b (b_id INTEGER PRIMARY KEY);"
  "CREATE TABLE ab (a_id INTEGER REFERENCES a(a_id), b_id INTEGER REFERENCES b(b_id),"
  " qty INTEGER, PRIMARY KEY (a_id, b_id));",
  lambda m: m.fact("Ab").get("isObjectified") and m.concept("Ab", "entity") is not None),

 ("rule 4", "a ternary association keeps all three roles",
  "CREATE TABLE a (a_id INTEGER PRIMARY KEY);CREATE TABLE b (b_id INTEGER PRIMARY KEY);"
  "CREATE TABLE c (c_id INTEGER PRIMARY KEY);"
  "CREATE TABLE abc (a_id INTEGER REFERENCES a(a_id), b_id INTEGER REFERENCES b(b_id),"
  " c_id INTEGER REFERENCES c(c_id), PRIMARY KEY (a_id, b_id, c_id));",
  lambda m: m.players("Abc") == ["A", "B", "C"]),

 ("rule 4", "a recursive many-to-many gives one fact type with both roles on one player",
  "CREATE TABLE part (part_no VARCHAR(9) PRIMARY KEY);"
  "CREATE TABLE bom (parent VARCHAR(9) REFERENCES part(part_no),"
  " child VARCHAR(9) REFERENCES part(part_no), PRIMARY KEY (parent, child));",
  lambda m: m.players("Bom") == ["Part", "Part"]),

 ("rule 5", "a single-column UNIQUE becomes a uniqueness constraint on that role",
  "CREATE TABLE person (person_id INTEGER PRIMARY KEY, email VARCHAR(80) UNIQUE);",
  lambda m: any(k["kind"] == "uniqueness" and
                any("PersonHasEmail.email" in r for s in k.get("roleSequences", []) for r in s)
                for k in m.model["constraints"])),

 ("rule 5", "a composite UNIQUE is reported, not silently dropped",
  "CREATE TABLE s (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER, UNIQUE (a, b));",
  lambda m: m.reported("rule 5", "composite unique")),

 ("rule 6", "CHECK ... IN becomes an enumerated value restriction",
  "CREATE TABLE person (id INTEGER PRIMARY KEY,"
  " sex CHAR(1) CHECK (sex IN ('M','F','X')));",
  lambda m: m.restriction("PersonSex")["values"] == ["M", "F", "X"]),

 ("rule 6", "CHECK ... BETWEEN becomes a range restriction",
  "CREATE TABLE p (id INTEGER PRIMARY KEY, pri INTEGER CHECK (pri BETWEEN 1 AND 5));",
  lambda m: m.restriction("PPri")["ranges"] == [{"min": "1", "max": "5"}]),

 ("rule 6", "a negated CHECK is reported, not read as a restriction on a column called NOT",
  "CREATE TABLE p (id INTEGER PRIMARY KEY, s CHAR(1) CHECK (s NOT IN ('x','y')));",
  lambda m: m.restriction("PS") is None and m.reported("rule 6", "not recognised")),

 ("rule 7", "a one-to-one key-to-key foreign key is read as subtyping, and reported",
  "CREATE TABLE party (party_id INTEGER PRIMARY KEY);"
  "CREATE TABLE person (party_id INTEGER PRIMARY KEY REFERENCES party(party_id),"
  " dob DATE);",
  lambda m: m.concept("Person", "entity").get("supertypes")
            and m.reported("rule 7", "person")),

 ("rule 7b", "a 1:1 table holding every parent row is absorbed, not made a subtype",
  "CREATE TABLE party (party_id INTEGER PRIMARY KEY, nm TEXT);"
  "CREATE TABLE party_extra (party_id INTEGER PRIMARY KEY REFERENCES party(party_id),"
  " dob DATE);"
  "INSERT INTO party VALUES (1,'a'),(2,'b');"
  "INSERT INTO party_extra VALUES (1,'2020-01-01'),(2,'2021-01-01');",
  lambda m: m.concept("PartyExtra", "entity") is None
            and m.players("PartyHasDob") == ["Party", "PartyDob"]
            and m.reported("rule 7b", "party_extra"),
  {"partitions": True}),

 ("rule 7b", "a 1:1 table holding only some parent rows stays a subtype",
  "CREATE TABLE party (party_id INTEGER PRIMARY KEY, nm TEXT);"
  "CREATE TABLE person (party_id INTEGER PRIMARY KEY REFERENCES party(party_id),"
  " dob DATE);"
  "INSERT INTO party VALUES (1,'a'),(2,'b'),(3,'c');"
  "INSERT INTO person VALUES (1,'2020-01-01');",
  lambda m: m.concept("Person", "entity").get("supertypes")
            and not m.reported("rule 7b"),
  {"partitions": True}),

 ("rule 7b", "with no rows to measure, the subtype reading stands",
  "CREATE TABLE party (party_id INTEGER PRIMARY KEY, nm TEXT);"
  "CREATE TABLE person (party_id INTEGER PRIMARY KEY REFERENCES party(party_id),"
  " dob DATE);",
  lambda m: m.concept("Person", "entity").get("supertypes")
            and not m.reported("rule 7b"),
  {"partitions": True}),

 ("rule 7b", "a chain of partitions absorbs to the root, not to the link above it",
  "CREATE TABLE a (k INTEGER PRIMARY KEY, x TEXT);"
  "CREATE TABLE b (k INTEGER PRIMARY KEY REFERENCES a(k), y TEXT);"
  "CREATE TABLE c (k INTEGER PRIMARY KEY REFERENCES b(k), z TEXT);"
  "INSERT INTO a VALUES (1,'x');INSERT INTO b VALUES (1,'y');INSERT INTO c VALUES (1,'z');",
  lambda m: m.concept("B", "entity") is None and m.concept("C", "entity") is None
            and m.players("AHasZ") == ["A", "AZ"],
  {"partitions": True}),

 ("rule 7b", "without the flag a full-coverage partition is still read as subtyping",
  "CREATE TABLE party (party_id INTEGER PRIMARY KEY, nm TEXT);"
  "CREATE TABLE party_extra (party_id INTEGER PRIMARY KEY REFERENCES party(party_id),"
  " dob DATE);"
  "INSERT INTO party VALUES (1,'a');INSERT INTO party_extra VALUES (1,'2020-01-01');",
  lambda m: m.concept("PartyExtra", "entity").get("supertypes")
            and not m.reported("rule 7b")),

 ("rule 6f", "a stand-in for NULL is not enrolled in the value constraint",
  "CREATE TABLE signals (id INTEGER PRIMARY KEY, polar VARCHAR(12));"
  + "".join("INSERT INTO signals VALUES (%d,'%s');" % (i, v) for i, v in enumerate(
      ["Linear", "Circular", "Unknown"] * 40)),
  lambda m: "Unknown" not in (m.restriction("SignalPolar") or {}).get("values", [])
            and sorted((m.restriction("SignalPolar") or {}).get("values", [])) ==
                ["Circular", "Linear"]
            and m.reported("rule 6f", "stand-in for NULL"),
  {"domains": True}),

 ("rule 6f", "a domain of nothing but stand-ins is no domain at all",
  "CREATE TABLE signals (id INTEGER PRIMARY KEY, note VARCHAR(12));"
  + "".join("INSERT INTO signals VALUES (%d,'%s');" % (i, v) for i, v in enumerate(
      ["Unknown", "N/A", "TBD"] * 40)),
  lambda m: m.restriction("SignalNote") is None,
  {"domains": True}),

 ("rule 6f", "a single bond is not a missing bond",
  "CREATE TABLE bonds (id INTEGER PRIMARY KEY, bond_type VARCHAR(2));"
  + "".join("INSERT INTO bonds VALUES (%d,'%s');" % (i, v) for i, v in enumerate(
      ["-", "=", "#"] * 40)),
  lambda m: sorted((m.restriction("BondType") or {}).get("values", [])) == ["#", "-", "="],
  {"domains": True}),

 ("rule 6f", "sodium is not `not applicable`",
  "CREATE TABLE atoms (id INTEGER PRIMARY KEY, element VARCHAR(2));"
  + "".join("INSERT INTO atoms VALUES (%d,'%s');" % (i, v) for i, v in enumerate(
      ["c", "n", "o", "na", "cl"] * 30)),
  lambda m: "na" in (m.restriction("AtomElement") or {}).get("values", []),
  {"domains": True}),

 ("rule 6f", "a negative test result is not an absent one",
  "CREATE TABLE tests (id INTEGER PRIMARY KEY, kct VARCHAR(2));"
  + "".join("INSERT INTO tests VALUES (%d,'%s');" % (i, v) for i, v in enumerate(
      ["+", "-"] * 60)),
  lambda m: sorted((m.restriction("TestKct") or {}).get("values", [])) == ["+", "-"],
  {"domains": True}),

 ("rule 6e", "a unit in the column name lands on the value type",
  "CREATE TABLE r (id INTEGER PRIMARY KEY, freqmhz REAL, airtempc REAL, status VARCHAR(8));",
  lambda m: m.concept("RFreqmhz", "value")["unit"] == "MHz"
            and m.concept("RAirtempc", "value")["unit"] == "degC"
            and "unit" not in m.concept("RStatus", "value")),

 ("rule 6e", "value types in the same unit merge into one domain",
  "CREATE TABLE r (id INTEGER PRIMARY KEY, freqmhz REAL, centrefreqmhz REAL,"
  " carrierfreqmhz REAL);",
  lambda m: m.concept("Frequency", "value")
            and m.concept("RFreqmhz", "value") is None
            and m.reported("rule 6e", "measured in MHz"),
  {"merge": True}),

 ("rule 6e", "Celsius and kelvin are one quantity and two domains",
  "CREATE TABLE r (id INTEGER PRIMARY KEY, airtempc REAL, groundtempc REAL, objtempk REAL,"
  " skytempk REAL);",
  lambda m: m.concept("TemperatureInDegC", "value")
            and m.concept("TemperatureInK", "value")
            and m.concept("Temperature", "value") is None,
  {"merge": True}),

 ("rule 6e", "without the flag every column keeps its own value type",
  "CREATE TABLE r (id INTEGER PRIMARY KEY, freqmhz REAL, centrefreqmhz REAL);",
  lambda m: m.concept("RFreqmhz", "value") and m.concept("Frequency", "value") is None),

 ("rule 10b", "an abbreviated column name is written out",
  "CREATE TABLE observatories (observstation VARCHAR(60) PRIMARY KEY, weather VARCHAR(8));",
  lambda m: m.concept("ObservatoryObservationStation", "value")
            and m.concept("Observatory", "entity")["referenceMode"] == "observation station",
  {"glossary": {}}),

 ("rule 10b", "a name the glossary does not know survives untouched",
  "CREATE TABLE t (telescref VARCHAR(20) PRIMARY KEY, category VARCHAR(20));",
  lambda m: m.concept("TTelescref", "value") and m.concept("TCategory", "value"),
  {"glossary": {}}),

 ("rule 10b", "a user glossary reaches the domain words the built-in table cannot",
  "CREATE TABLE t (telescref VARCHAR(20) PRIMARY KEY, nm VARCHAR(20));",
  lambda m: m.concept("TTelescopeRef", "value"),
  {"glossary": {"telesc": "telescope"}}),

 ("rule 10b", "the unit is dropped from the name once the value type carries it",
  "CREATE TABLE r (id INTEGER PRIMARY KEY, freqmhz REAL);",
  lambda m: m.concept("RFrequency", "value")["unit"] == "MHz"
            and m.concept("RFreqmhz", "value") is None,
  {"glossary": {}}),

 ("rule 10b", "a unit suffix carrying a quantity word keeps the word",
  "CREATE TABLE r (id INTEGER PRIMARY KEY, airtempc REAL, windspeedms REAL);",
  lambda m: m.concept("RAirTemperature", "value")["unit"] == "degC"
            and m.concept("RWindSpeed", "value")["unit"] == "m/s"
            and m.concept("RAir", "value") is None,
  {"glossary": {}}),

 ("rule 10b", "a unit word leaves before the abbreviations are written out",
  "CREATE TABLE r (id INTEGER PRIMARY KEY, sess_dur_min REAL);",
  lambda m: m.concept("RSessDuration", "value") is not None
            and m.concept("RSessDuration", "value")["unit"] == "min"
            and m.concept("RSessDurationMinimum", "value") is None,
  {"glossary": {}}),

 ("rule 10b", "without the flag rule 10 spells names exactly as it always has",
  "CREATE TABLE observatories (observstation VARCHAR(60) PRIMARY KEY);",
  lambda m: m.concept("ObservatoryObservstation", "value")),

 ("rule 8", "a discriminator beside nullable groups is reported, never applied",
  "CREATE TABLE party (id INTEGER PRIMARY KEY,"
  " party_type VARCHAR(8) NOT NULL CHECK (party_type IN ('p','o')),"
  " dob DATE, abn VARCHAR(11));",
  lambda m: m.reported("rule 8", "party_type")
            and not m.concept("Party", "entity").get("supertypes")),

 ("rule 4b", "an association wearing a surrogate key is reported",
  "CREATE TABLE a (a_id INTEGER PRIMARY KEY);CREATE TABLE b (b_id INTEGER PRIMARY KEY);"
  "CREATE TABLE ab (id INTEGER PRIMARY KEY, a_id INTEGER NOT NULL REFERENCES a(a_id),"
  " b_id INTEGER NOT NULL REFERENCES b(b_id), UNIQUE (a_id, b_id));",
  lambda m: m.reported("rule 4b", "ab")),

 ("rule 4c", "a key that is part foreign key, part sequence is reported as a weak entity",
  "CREATE TABLE ord (ord_id INTEGER PRIMARY KEY);"
  "CREATE TABLE ord_line (ord_id INTEGER REFERENCES ord(ord_id), line_no INTEGER,"
  " qty INTEGER, PRIMARY KEY (ord_id, line_no));",
  lambda m: m.reported("rule 4c", "weak entity") and m.identifier("OrdLine") == 2),

 ("rule 4c", "a key versioned by a date is reported as such",
  "CREATE TABLE p (p_id INTEGER PRIMARY KEY);CREATE TABLE s (s_id INTEGER PRIMARY KEY);"
  "CREATE TABLE price (p_id INTEGER REFERENCES p(p_id), s_id INTEGER REFERENCES s(s_id),"
  " effective DATE, amount DECIMAL(9,2), PRIMARY KEY (p_id, s_id, effective));",
  lambda m: m.reported("rule 4c", "versioned")),

 ("rule 2b", "numbered columns are reported as one multi-valued fact",
  "CREATE TABLE c (id INTEGER PRIMARY KEY, phone1 VARCHAR(20), phone2 VARCHAR(20),"
  " phone3 VARCHAR(20));",
  lambda m: m.reported("rule 2b", "phone")),

 ("rule 3b", "a polymorphic reference is reported",
  "CREATE TABLE note (id INTEGER PRIMARY KEY,"
  " owner_type VARCHAR(8) NOT NULL CHECK (owner_type IN ('a','b')), owner_id INTEGER);",
  lambda m: m.reported("rule 3b", "owner_type")),

 ("blocker", "a table with no primary key blocks, naming the table",
  "CREATE TABLE log (at VARCHAR(19), note VARCHAR(80));"
  "CREATE TABLE k (id INTEGER PRIMARY KEY);",
  lambda m: any(b["subject"] == "log" for b in m.report.blockers)),

 ("blocker", "a schema with no foreign keys at all is reported once, not per table",
  "CREATE TABLE a (id INTEGER PRIMARY KEY, x INTEGER);"
  "CREATE TABLE b (id INTEGER PRIMARY KEY, y INTEGER);"
  "CREATE TABLE c (id INTEGER PRIMARY KEY, z INTEGER);",
  lambda m: sum(1 for r in m.report.refinements
                if r["rule"] == "rule 4" and "whole schema" in r["subject"]) == 1),

 ("rule 10", "CamelCase is preserved, not flattened",
  "CREATE TABLE InvoiceLine (InvoiceLineId INTEGER PRIMARY KEY, MediaType VARCHAR(9));",
  lambda m: m.concept("InvoiceLine", "entity") is not None),

 ("rule 10", "an abbreviated table prefix is stripped from its columns",
  "CREATE TABLE department (dept_code VARCHAR(8) PRIMARY KEY, dept_name VARCHAR(40));",
  lambda m: m.concept("Department", "entity")["referenceMode"] == "code"
            and m.concept("DepartmentName", "value") is not None),

 # Rule 10 computes three things -- the source name, its words, and whether one is an
 # abbreviation of another -- and used to keep only the name it built from them. `terms` keeps
 # the rest, because matching a question against the model needs every word the thing is known
 # by, and a DBA types `dept_code`.
 ("rule 10", "a concept records the source name it was derived from",
  "CREATE TABLE department (dept_code VARCHAR(8) PRIMARY KEY, dept_name VARCHAR(40));",
  lambda m: "dept_name" in m.concept("DepartmentName", "value")["terms"]
            and "dept" in m.concept("DepartmentName", "value")["terms"]),

 ("rule 10", "and does not record words from anywhere else",
  "CREATE TABLE department (dept_code VARCHAR(8) PRIMARY KEY, dept_name VARCHAR(40));",
  lambda m: "code" not in m.concept("DepartmentName", "value")["terms"]),

 ("rule 10", "a plural table name is singularised",
  "CREATE TABLE categories (id INTEGER PRIMARY KEY);",
  lambda m: m.concept("Category", "entity") is not None),

 ("rule 10", "ring roles are qualified so each is addressable",
  "CREATE TABLE part (part_no VARCHAR(9) PRIMARY KEY);"
  "CREATE TABLE bom (parent VARCHAR(9) REFERENCES part(part_no),"
  " child VARCHAR(9) REFERENCES part(part_no), PRIMARY KEY (parent, child));",
  lambda m: len({r["name"] for r in m.fact("Bom")["roles"]}) == 2
            and all(n.startswith("Bom") for n in {r["name"] for r in m.fact("Bom")["roles"]})),

 # Rule 10 on a ring: `{0} has {1}` over two roles of one type says nothing, so the verb is
 # read from what the schema does say -- and reported as the guess it is.
 ("rule 10", "a self-reference reads by its column, the adjective hyphen-bound (FORML 2 s1.2)",
  "CREATE TABLE employee (emp_nr INTEGER PRIMARY KEY,"
  " manager_nr INTEGER REFERENCES employee(emp_nr));",
  lambda m: m.readings("EmployeeHasManager") == ["{0} has manager- {1}", "{0} is manager of {1}"]),
 ("rule 10", "and its inverse reading starts at the other role",
  "CREATE TABLE employee (emp_nr INTEGER PRIMARY KEY,"
  " manager_nr INTEGER REFERENCES employee(emp_nr));",
  lambda m: m.fact("EmployeeHasManager")["readings"][1]["roleSequence"]
            == list(reversed(m.fact("EmployeeHasManager")["readings"][0]["roleSequence"]))),
 ("rule 10", "a ring whose columns name both roles reads each way by its role",
  "CREATE TABLE part (part_no VARCHAR(9) PRIMARY KEY);"
  "CREATE TABLE bom (parent VARCHAR(9) REFERENCES part(part_no),"
  " child VARCHAR(9) REFERENCES part(part_no), PRIMARY KEY (parent, child));",
  lambda m: m.readings("Bom") == ["{0} is parent of {1}", "{0} is child of {1}"]),
 ("rule 10", "a ring whose columns only number the player reads by the table's name",
  "CREATE TABLE atom (atom_id TEXT PRIMARY KEY);"
  "CREATE TABLE connected (atom_id TEXT REFERENCES atom(atom_id),"
  " atom_id2 TEXT REFERENCES atom(atom_id), PRIMARY KEY (atom_id, atom_id2));",
  lambda m: m.readings("Connected") == ["{0} is connected to {1}"]),
 ("rule 10", "a column ending in a preposition is the verb itself",
  "CREATE TABLE employee (id INTEGER PRIMARY KEY, reports_to INTEGER REFERENCES employee(id));",
  lambda m: m.readings("EmployeeHasReportsTo") == ["{0} reports to {1}"]),
 ("rule 10", "a table named for a verb reads by it; one named for a noun reads has-with",
  "CREATE TABLE person (id INTEGER PRIMARY KEY);"
  "CREATE TABLE follows (person1 INTEGER REFERENCES person(id),"
  " person2 INTEGER REFERENCES person(id), PRIMARY KEY (person1, person2));"
  "CREATE TABLE friendship (a INTEGER REFERENCES person(id), b INTEGER REFERENCES person(id),"
  " PRIMARY KEY (a, b));",
  lambda m: m.readings("Follow") == ["{0} follows {1}"]
            and m.readings("Friendship") == ["{0} has friendship with {1}"]),
 ("rule 10", "when the names say nothing the placeholder stays",
  "CREATE TABLE person (id INTEGER PRIMARY KEY);"
  "CREATE TABLE person_person (person1 INTEGER REFERENCES person(id),"
  " person2 INTEGER REFERENCES person(id), PRIMARY KEY (person1, person2));",
  lambda m: m.readings("PersonPerson") == ["{0} has {1}"]),
 ("rule 10", "a guessed ring reading is reported as a guess, in words",
  "CREATE TABLE employee (emp_nr INTEGER PRIMARY KEY,"
  " manager_nr INTEGER REFERENCES employee(emp_nr));",
  lambda m: m.reported("rule 10", "Employee has manager- Employee")
            and m.reported("rule 10", "predicate reading")),

 ("rule 10", "every generated name is reported as a guess",
  "CREATE TABLE person (id INTEGER PRIMARY KEY, nickname VARCHAR(9));",
  lambda m: m.reported("rule 10", "predicate reading")
            and m.reported("rule 10", "entity type names")),

 # Rule 1c: no primary key, one foreign key, other columns. The shape of BIRD's
 # thrombosis_prediction.Examination, which used to be a blocker and cost a quarter of that
 # database's questions.
 ("rule 1c", "a keyless table with one foreign key is an entity type identified by its row",
  "CREATE TABLE patient (id INTEGER PRIMARY KEY, name TEXT);"
  "CREATE TABLE examination (id INTEGER REFERENCES patient(id), exam_date TEXT,"
  " thrombosis INTEGER);",
  lambda m: m.concept("Examination", "entity") is not None
            and m.identity_of("Examination") == ["rowid"]
            and any(m.players(c["name"]) == ["Examination", "Patient"]
                    for c in m.model["concepts"] if c["kind"] == "fact")),
 ("rule 1c", "the row, not its columns: no attribute is part of the identifier",
  "CREATE TABLE patient (id INTEGER PRIMARY KEY);"
  "CREATE TABLE examination (id INTEGER REFERENCES patient(id), exam_date TEXT);",
  lambda m: m.identifier("Examination") == 0),
 ("rule 1c", "and the report says the row is the identifier and where a real key comes from",
  "CREATE TABLE patient (id INTEGER PRIMARY KEY);"
  "CREATE TABLE examination (id INTEGER REFERENCES patient(id), exam_date TEXT);",
  lambda m: m.reported("rule 1c", "rowid") and m.reported("rule 1c", "set of tuples")),
 ("rule 1", "no key and no foreign key is still a blocker",
  "CREATE TABLE log (msg TEXT, at TEXT);",
  lambda m: any(b["rule"] == "rule 1" and b["subject"] == "log" for b in m.report.blockers)),

 # Rule 9 applied on request. debit_card_specializing declares no foreign keys at all, and
 # the pilot lost half its questions there for want of them.
 ("rule 9", "an undeclared foreign key is applied when --infer-fks asks and the name is unique",
  "CREATE TABLE customers (CustomerID INTEGER PRIMARY KEY, segment TEXT);"
  "CREATE TABLE transactions (TransactionID INTEGER PRIMARY KEY, CustomerID INTEGER,"
  " amount REAL);",
  lambda m: any(m.players(c["name"]) == ["Transaction", "Customer"]
                for c in m.model["concepts"] if c["kind"] == "fact")
            and m.reported("rule 9", "Applied because --infer-fks"),
  {"infer": True}),
 ("rule 9", "and never applied by default",
  "CREATE TABLE customers (CustomerID INTEGER PRIMARY KEY, segment TEXT);"
  "CREATE TABLE transactions (TransactionID INTEGER PRIMARY KEY, CustomerID INTEGER,"
  " amount REAL);",
  lambda m: not any(m.players(c["name"]) == ["Transaction", "Customer"]
                    for c in m.model["concepts"] if c["kind"] == "fact")),
 ("rule 9", "a name that matches several tables' keys is left alone, and said so",
  "CREATE TABLE a (id INTEGER PRIMARY KEY); CREATE TABLE b (id INTEGER PRIMARY KEY);"
  "CREATE TABLE c (cid INTEGER PRIMARY KEY, id INTEGER);",
  lambda m: not any(m.players(x["name"]) in (["C", "A"], ["C", "B"])
                    for x in m.model["concepts"] if x["kind"] == "fact")
            and m.reported("rule 9", "not applied"),
  {"infer": True}),
 ("rule 9", "a name match with a different type is not a reference",
  "CREATE TABLE customers (CustomerID INTEGER PRIMARY KEY);"
  "CREATE TABLE notes (NoteID INTEGER PRIMARY KEY, CustomerID TEXT);",
  lambda m: not any(m.players(c["name"]) == ["Note", "Customer"]
                    for c in m.model["concepts"] if c["kind"] == "fact"),
  {"infer": True}),

 # A foreign key may point at a unique column rather than the primary key. The BIRD pilot
 # found 32 of 105 declared keys like this, every one joined to the wrong column -- silently.
 ("mapping", "a foreign key to a unique column records the columns it references",
  "CREATE TABLE card (id INTEGER PRIMARY KEY, uuid TEXT UNIQUE);"
  "CREATE TABLE legality (id INTEGER PRIMARY KEY, uuid TEXT REFERENCES card(uuid));",
  lambda m: m.references_of("legality", "uuid") == ["uuid"]),
 ("mapping", "a foreign key to the primary key records nothing extra",
  "CREATE TABLE dept (id INTEGER PRIMARY KEY);"
  "CREATE TABLE emp (id INTEGER PRIMARY KEY, dept_id INTEGER REFERENCES dept(id));",
  lambda m: m.references_of("emp", "dept_id") is None),

 ("mapping", "an absorbed attribute maps the entity role to the key and the value to its column",
  "CREATE TABLE person (person_id INTEGER PRIMARY KEY, nickname VARCHAR(40));",
  lambda m: m.mapped_columns("PersonHasNickname.person") == ["person_id"]
            and m.mapped_columns("PersonHasNickname.nickname") == ["nickname"]),

 ("mapping", "a composite foreign key maps all its columns to the one role",
  "CREATE TABLE f (a CHAR(2), b INTEGER, PRIMARY KEY (a, b));"
  "CREATE TABLE g (a CHAR(2), b INTEGER, note VARCHAR(9), PRIMARY KEY (a, b),"
  " FOREIGN KEY (a, b) REFERENCES f(a, b));",
  lambda m: m.concept("G", "entity") is not None),

 ("catalog", "an implicit foreign key target is ordered by the key, not by column position",
  "CREATE TABLE parent (b TEXT, a TEXT, PRIMARY KEY (a, b));"
  "CREATE TABLE child (x TEXT, y TEXT, PRIMARY KEY (x, y),"
  " FOREIGN KEY (x, y) REFERENCES parent);",
  lambda m: m.concept("Child", "entity") is not None),

 ("catalog", "a partial unique index is not read as an unconditional constraint",
  "CREATE TABLE t (id INTEGER PRIMARY KEY, code VARCHAR(9), active INTEGER);"
  "CREATE UNIQUE INDEX ix ON t(code) WHERE active = 1;",
  lambda m: not any(k["kind"] == "uniqueness" and
                    any("THasCode.code" in r for s in k.get("roleSequences", []) for r in s)
                    for k in m.model["constraints"])),

 ("view", "a view is reported and not modelled as a fact type",
  "CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER);"
  "CREATE VIEW v AS SELECT id FROM t;",
  lambda m: m.reported("book ch.8", "view") and m.concept("V", "entity") is None),
]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    cases = [c for c in CASES
             if not args.only or args.only.lower() in (c[0] + " " + c[1]).lower()]
    passed = 0
    for case in cases:
        rule, what, ddl, check = case[:4]
        opts = case[4] if len(case) > 4 else {}
        try:
            model, report = build(ddl, **opts)
            ok = bool(check(Model(model, report)))
            detail = ""
        except Exception as e:                       # a rule that raises is a failure
            ok, detail = False, "%s: %s" % (type(e).__name__, e)
        passed += ok
        print("%s  %-9s %s%s" % ("ok  " if ok else "FAIL", rule, what,
                                 "\n        " + detail if detail else ""))
    print("\n%d passed, %d failed, %d total" % (passed, len(cases) - passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
