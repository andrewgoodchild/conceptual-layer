#!/usr/bin/env python3
"""The annotated DDL (`annotate.py`): the model's notes land beside the right columns, the
model chooses the tables, and the budget is kept.

A small hand-written model over a two-table DDL in LiveSQLBench's shape, so nothing here
depends on a benchmark being present.

    test_annotate.py [-v]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import annotate                                                          # noqa: E402

DDL = """CREATE TABLE plants (
plant_ref text NOT NULL,
state text NULL,
specs jsonb NULL,
    PRIMARY KEY (plant_ref)
);

First 3 rows:
plant_ref    state    specs
-----------  -------  ------------------------------------------------------------
P1           active   {'capacity_mw': 12.5, 'panel': 'mono', 'notes': '%s'}
...


CREATE TABLE repairs (
repair_ref text NOT NULL,
plant_ref text NULL,
hours real NULL,
    PRIMARY KEY (repair_ref),
    FOREIGN KEY (plant_ref) REFERENCES plants(plant_ref)
);

First 3 rows:
repair_ref    plant_ref    hours
------------  -----------  -------
R1            P1           3.5
...
""" % ("x" * 400)


def value(cid, name, **kw):
    return dict(id=cid, name=name, kind="value", dataType={"name": "text"}, **kw)


MODEL = {
    "concepts": [
        {"id": "et.Plant", "name": "Plant", "kind": "entity",
         "dataQuality": ["Reaches Repair by 2 routes: repairs directly (10 pairs), "
                         "audits (8 pairs); they agree wherever they overlap (8 Plant)."]},
        {"id": "et.Repair", "name": "Repair", "kind": "entity"},
        value("vt.PlantState", "PlantState",
              restriction={"values": ["active", "retired"]},
              dataQuality=["Values arrive in mixed case (5 spellings of 2 values)."]),
        value("vt.Capacity", "PlantSpecsCapacityMw", dataQuality=["Stored with its unit."]),
        value("vt.Hours", "RepairHours"),
        {"id": "ft.PlantHasState", "name": "PlantHasState", "kind": "fact",
         "roles": [{"id": "r.s.p", "player": "et.Plant"}, {"id": "r.s.v", "player": "vt.PlantState"}]},
        {"id": "ft.PlantHasCap", "name": "PlantHasCap", "kind": "fact",
         "roles": [{"id": "r.c.p", "player": "et.Plant"}, {"id": "r.c.v", "player": "vt.Capacity"}]},
        {"id": "ft.RepairHours", "name": "RepairHasHours", "kind": "fact",
         "roles": [{"id": "r.h.r", "player": "et.Repair"}, {"id": "r.h.v", "player": "vt.Hours"}]},
    ],
    "mapping": {
        "tables": [{"id": "t.p", "name": "plants"}, {"id": "t.r", "name": "repairs"}],
        "columns": [
            {"id": "c.p.ref", "table": "t.p", "name": "plant_ref"},
            {"id": "c.p.state", "table": "t.p", "name": "state"},
            {"id": "c.p.cap", "table": "t.p", "name": "specs", "path": ["capacity_mw"],
             "dataType": {"name": "real"}},
            {"id": "c.r.ref", "table": "t.r", "name": "repair_ref"},
            {"id": "c.r.hours", "table": "t.r", "name": "hours"},
        ],
        "conceptMap": [{"concept": "et.Plant", "table": "t.p", "identifyingColumns": ["c.p.ref"]},
                       {"concept": "et.Repair", "table": "t.r", "identifyingColumns": ["c.r.ref"]}],
        "roleMap": [
            {"role": "r.s.p", "table": "t.p", "columns": ["c.p.ref"]},
            {"role": "r.s.v", "table": "t.p", "columns": ["c.p.state"]},
            {"role": "r.c.p", "table": "t.p", "columns": ["c.p.ref"]},
            {"role": "r.c.v", "table": "t.p", "columns": ["c.p.cap"]},
            {"role": "r.h.r", "table": "t.r", "columns": ["c.r.ref"]},
            {"role": "r.h.v", "table": "t.r", "columns": ["c.r.hours"]},
        ],
    },
}


def cases():
    ann = annotate.Annotator(DDL, MODEL)
    whole = ann.view("")
    state = next(l for l in whole.splitlines() if l.startswith("state "))
    yield ("a column's values and cautions go beside it",
           "'active', 'retired'" in state and "mixed case" in state)
    yield ("a JSON field is listed under its column, with its note",
           "specs->>'capacity_mw' real  Stored with its unit." in whole)
    yield ("a route caution is said in table terms, above the table",
           "-- rows here reach repairs by 2 join routes (repairs directly, audits); "
           "they agree" in whole)
    yield ("a column the model has nothing to say about is left alone",
           "\nhours real NULL,\n" in whole)
    yield ("a long sample row is cut", "x" * 300 not in whole and "..." in whole)
    narrow = ann.view("how many hours did repairs take", budget=400)
    yield ("the model chooses the table the question is about, and names the one left out",
           "CREATE TABLE repairs" in narrow and "CREATE TABLE plants" not in narrow
           and "Not shown: plants." in narrow)
    plain = annotate.Annotator(DDL).view("")
    yield ("the plain view is the same DDL with no comments",
           "CREATE TABLE plants" in plain and "--" not in plain.split("First 3 rows")[0])


def main():
    verbose = "-v" in sys.argv
    failed = 0
    for name, ok in cases():
        failed += not ok
        if verbose or not ok:
            print("%s  %s" % ("ok  " if ok else "FAIL", name))
    print("%d failed" % failed if failed else "annotate: all passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
