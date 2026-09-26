#!/usr/bin/env python3
"""Every query shape, over a value that lives inside a JSON document.

A path is not a column. It cannot be indexed, SQL will not let it be named by its output alias
in a `GROUP BY`, it has to be qualified with the right alias inside a correlated subquery, and
it has to appear whole in a `PARTITION BY`. `conquer/tests/test_json.py` proves the simple
cases on a three-row fixture; this asks whether the harder shapes hold on a real database --
`solar_panel_large`, 28,864 rows, where `inverters.geolocation` carries

    {"latitude": 34.0522, "LONGITUDE": -118.2437}

and `Inverter` joins to `Plant` and to `InverterModel`.

Every case states its truth as hand-written SQL against the same database, so a case fails if
the compiler's answer differs rather than if its text changes.

    query_probe.py [--only SUBSTRING] [-v]
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for d in ("conquer", "reverse"):
    sys.path.insert(0, os.path.join(ROOT, d))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402
import catalog as catalog_mod     # noqa: E402
import derive as derive_mod       # noqa: E402
import jsonshape                  # noqa: E402

DB = os.path.join(HERE, "work", "db", "solar_panel_large.sqlite")
MODEL = os.path.join(HERE, "work", "models", "solar_panel_pop.ccm.json")

# `latitude` is a path; `COST` and `cap_mw` are ordinary columns. Mixing them is the point:
# a path has to behave like a column everywhere a column can appear.
LAT = "json_extract(i.geolocation, '$.latitude')"
LON = "json_extract(i.geolocation, '$.LONGITUDE')"

CASES = [
    ("project a path beside a column",
     "LIST s, lat FROM Inverter has InverterSerialNum s AND ALSO has InverterLatitude lat",
     "SELECT i.SerialNum, %s FROM inverters i WHERE %s IS NOT NULL" % (LAT, LAT)),

    ("filter on a path, numerically",
     "LIST s FROM Inverter has InverterSerialNum s AND ALSO has InverterLatitude lat "
     "WHERE lat > 34.05",
     "SELECT i.SerialNum FROM inverters i WHERE CAST(%s AS REAL) > 34.05" % LAT),

    # -- joins -----------------------------------------------------------------------------
    ("join: path on one side, column on the other",
     "LIST lat, c FROM Inverter has InverterLatitude lat AND ALSO "
     "has Plant has PlantCapMw c",
     "SELECT %s, p.cap_mw FROM inverters i JOIN plants p ON p.sitekey = i.SiteLocation "
     "WHERE %s IS NOT NULL AND p.cap_mw IS NOT NULL" % (LAT, LAT)),

    ("join across two hops with a path at the far end",
     "LIST m, lat FROM Inverter has InverterModel has InverterModelModelName m "
     "AND ALSO has InverterLatitude lat",
     "SELECT im.modelName, %s FROM inverters i "
     "JOIN inverter_models im ON im.InverterModelTag = i.ModelIdentifier "
     "WHERE im.modelName IS NOT NULL AND %s IS NOT NULL" % (LAT, LAT)),

    # -- grouping --------------------------------------------------------------------------
    ("GROUP BY a path value",
     "LIST lat, n FROM Inverter has InverterLatitude lat AND ALSO has InverterSerialNum s "
     "AND ALSO THE COUNT OF s GROUPED BY lat AS n",
     "SELECT %s, COUNT(i.SerialNum) FROM inverters i WHERE %s IS NOT NULL GROUP BY %s"
     % (LAT, LAT, LAT)),

    ("aggregate a path, grouped by a column",
     "LIST st, t FROM Inverter has InverterAssetStatus st AND ALSO has InverterLatitude lat "
     "AND ALSO THE AVERAGE lat GROUPED BY st AS t",
     "SELECT i.ASSET_STATUS, AVG(CAST(%s AS REAL)) FROM inverters i "
     "WHERE i.ASSET_STATUS IS NOT NULL AND %s IS NOT NULL GROUP BY i.ASSET_STATUS"
     % (LAT, LAT)),

    ("aggregate a column, grouped by a path",
     "LIST lat, t FROM Inverter has InverterLatitude lat AND ALSO has InverterCost c "
     "AND ALSO THE SUM OF c GROUPED BY lat AS t",
     "SELECT %s, SUM(i.COST) FROM inverters i WHERE %s IS NOT NULL AND i.COST IS NOT NULL "
     "GROUP BY %s" % (LAT, LAT, LAT)),

    # -- a bracket is a correlated EXISTS ---------------------------------------------------
    ("a bracket filtering on a path",
     "LIST s FROM Inverter [has InverterLatitude: 34.0522] has InverterSerialNum s",
     "SELECT i.SerialNum FROM inverters i WHERE EXISTS "
     "(SELECT 1 FROM inverters x WHERE x.SerialNum = i.SerialNum "
     "AND CAST(json_extract(x.geolocation, '$.latitude') AS REAL) = 34.0522)"),

    # A bracket that BINDS a name joins rather than semijoining, and so multiplies the head
    # -- `lower.py` says so in the fan-out message, and finding 80 is about saying it clearly.
    # That is true of a path exactly as it is of a column, which is the point of this case:
    # the trap is the language's, not the document's.
    ("a bracket that binds a name joins, path or not",
     "LIST k FROM Plant [is of Inverter has InverterLatitude lat WHERE lat > 34.05] "
     "has PlantSitekey k",
     "SELECT p.sitekey FROM plants p JOIN inverters i ON i.SiteLocation = p.sitekey "
     "WHERE CAST(%s AS REAL) > 34.05" % LAT),

    ("a bracket that binds nothing semijoins, and does not",
     "LIST k FROM Plant [is of Inverter has InverterAssetStatus: 'Active'] has PlantSitekey k",
     "SELECT p.sitekey FROM plants p WHERE EXISTS (SELECT 1 FROM inverters i "
     "WHERE i.SiteLocation = p.sitekey AND i.ASSET_STATUS = 'Active')"),

    # -- windows ---------------------------------------------------------------------------
    ("WITHIN partitioned by a path",
     "LIST st, t FROM Inverter has InverterAssetStatus st AND ALSO has InverterLatitude lat "
     "AND ALSO THE COUNT OF lat WITHIN st AS t",
     "SELECT i.ASSET_STATUS, COUNT(%s) OVER (PARTITION BY i.ASSET_STATUS) FROM inverters i "
     "WHERE i.ASSET_STATUS IS NOT NULL AND %s IS NOT NULL" % (LAT, LAT)),

    ("WITHIN aggregating a path",
     "LIST st, t FROM Inverter has InverterAssetStatus st AND ALSO has InverterLatitude lat "
     "AND ALSO THE SUM OF lat WITHIN st AS t",
     "SELECT i.ASSET_STATUS, SUM(CAST(%s AS REAL)) OVER (PARTITION BY i.ASSET_STATUS) "
     "FROM inverters i WHERE i.ASSET_STATUS IS NOT NULL AND %s IS NOT NULL" % (LAT, LAT)),

    # -- aggregates ------------------------------------------------------------------------
    ("scalar aggregate over a path",
     "THE MAXIMUM lat IN Inverter has InverterLatitude lat",
     "SELECT MAX(CAST(%s AS REAL)) FROM inverters i" % LAT),

    ("two paths in the same document, compared",
     "LIST s FROM Inverter has InverterSerialNum s AND ALSO has InverterLatitude lat "
     "AND ALSO has InverterLongitude lon WHERE lat > 34.05 AND lon < -118",
     "SELECT i.SerialNum FROM inverters i WHERE CAST(%s AS REAL) > 34.05 "
     "AND CAST(%s AS REAL) < -118" % (LAT, LON)),
]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if not os.path.exists(DB):
        print("no database: run `python3 load.py solar_panel_large` first")
        return 2
    if not os.path.exists(MODEL):
        cat = catalog_mod.from_sqlite(DB)
        c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        model, _ = derive_mod.derive(cat, json_shapes=jsonshape.read(c, cat))
        c.close()
        os.makedirs(os.path.dirname(MODEL), exist_ok=True)
        json.dump(model, open(MODEL, "w"), indent=1)
    model = json.load(open(MODEL))
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    lex, em = parser_mod.Lexicon(model), sql_mod.Emitter(model)

    passed = failed = 0
    for name, query, truth in CASES:
        if args.only and args.only.lower() not in name.lower():
            continue
        try:
            _, sql, params = driver.transpile(model, query, lex, em)
        except Exception as e:                                          # noqa: BLE001
            failed += 1
            print("FAIL  %-52s %s: %s" % (name, type(e).__name__, str(e)[:90]))
            continue
        try:
            got = sorted(conn.execute(sql, params).fetchall())
            want = sorted(conn.execute(truth).fetchall())
        except sqlite3.Error as e:
            failed += 1
            print("FAIL  %-52s SQL error: %s" % (name, str(e)[:80]))
            if args.verbose:
                print("      %s" % sql[:300])
            continue
        if got == want:
            passed += 1
            print("ok    %-52s %d row(s)%s" % (name, len(got),
                                               "  " + str(got[:1]) if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %-52s got %d rows, want %d" % (name, len(got), len(want)))
            print("      got  %s" % str(got[:3])[:150])
            print("      want %s" % str(want[:3])[:150])
            if args.verbose:
                print("      %s" % sql[:400])
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
