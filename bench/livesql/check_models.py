#!/usr/bin/env python3
"""Finding 172's defects, checked against rebuilt models: each one the reviews found, as it
was found, and whether the model still says it.

    check_models.py [--models work/models-profiled3]
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CQ = os.path.join(ROOT, "conquer", "conquer.py")


def load(models, db):
    path = os.path.join(models, "%s.ccm.json" % db)
    return json.load(open(path)) if os.path.exists(path) else None


def report(models, db):
    path = os.path.join(models, "%s.report.json" % db)
    return json.load(open(path)) if os.path.exists(path) else {"refinements": []}


def listing(models, db):
    return subprocess.run([sys.executable, CQ, os.path.join(models, "%s.ccm.json" % db),
                           "--schema", "--relational"], capture_output=True, text=True).stdout


def cautions(m):
    return {c["name"]: c.get("dataQuality", []) for c in m["concepts"]}


def refs(m):
    """(table, [columns]) -> (table, [columns]) for every reference the mapping records."""
    cols = {c["id"]: c for c in m["mapping"]["columns"]}
    tabs = {t["id"]: t["name"] for t in m["mapping"]["tables"]}
    out = []
    for rm in m["mapping"]["roleMap"]:
        if rm.get("references"):
            src = [cols[c]["name"] for c in rm["columns"]]
            dst = [cols[c]["name"] for c in rm["references"]]
            out.append((tabs[rm["table"]], src, tabs[cols[rm["references"][0]]["table"]], dst))
    return out


def checks(models):
    m = load(models, "labor_certification_applications_large")
    if m:
        text = listing(models, "labor_certification_applications_large")
        yield ("labor: the case-worksite reference is one four-column reference",
               "case_worksite.ws_addr1, case_worksite.wscity, case_worksite.wsstate, "
               "case_worksite.wszip -> worksite.w_addr1, worksite.wcity, worksite.wstate, "
               "worksite.wzip" in text, "(ws_addr1, wscity, wsstate, wszip) -> worksite")
        yield ("labor: no single worksite column is said to name a worksite",
               "wsstate -> worksite.w_addr1" not in text, "wsstate -> w_addr1 gone")
        c = cautions(m)
        yield ("labor: attorney emails that differ only by case are cautioned",
               any("only by case" in s for v in c.values() for s in v), "lawmail")
    m = load(models, "cybermarket_pattern_large")
    if m:
        text = listing(models, "cybermarket_pattern_large")
        yield ("cybermarket: the product reference is one composite reference",
               "[transaction_products.ListingAge -> products.SellerPointer" not in text
               and "transaction_products.ProdCat, transaction_products.Subcategory" in text,
               "ProdCat, Subcategory, ListingAge, SellerPointer -> products")
    m = load(models, "residential_data_large")
    if m:
        c = cautions(m)
        park = [x for x in m["concepts"] if "Parkavail" in x["name"] or "ParkAvail" in x["name"]]
        vals = [str(v).strip().lower() for x in park
                for v in (x.get("restriction") or {}).get("values", [])]
        yield ("residential: 'Not available' parking is a value, not an absence",
               "not available" in vals and not any("reads as absent" in s and "ot available" in s
                                                  for x in park for s in x.get("dataQuality", [])),
               repr(vals[:6]))
        text = listing(models, "residential_data_large")
        yield ("residential: households' location reference is one (region, zone) reference",
               "[households.loczone -> locations.regioncode" not in text
               and "households.locregion, households.loczone -> locations.regioncode, "
                   "locations.zonenum" in text, "(locregion, loczone) -> locations")
    for db, bad in (("reverse_logistics_large", ("DurationInMs", "1Kg")),
                    ("virtual_idol_large", ("DurationMinimum", "SessDurationMinimum")),
                    ("archeology_scan_large", ("Duration",)),
                    ("robot_fault_prediction_large", ("Distance",)),
                    ("mental_healths_large", ("Distance",))):
        m = load(models, db)
        if not m:
            continue
        names = {c["name"] for c in m["concepts"] if c["kind"] == "value"}
        hit = [n for n in names if any(n == b or n.endswith(b) for b in bad)]
        yield ("%s: no value type named from a unit misread (%s)" % (db.split("_")[0],
                                                                    ", ".join(bad)),
               not hit, repr(hit[:4]))
    m = load(models, "archeology_scan_large")
    if m:
        pc = [r for r in refs(m) if r[0] == "pointcloud" and r[2] == "scans"]
        yield ("archeology: a point cloud references its scan through (project, crew)",
               bool(pc), repr(pc))
    m = load(models, "mental_healths_large")
    if m:
        text = listing(models, "mental_healths_large")
        yield ("mental_healths: encounters' facility and clinician references are inferred",
               "encounters.fac_id -> facilities" in text and "encounters.clin_id -> clinicians" in text,
               "rule 9c")
    m = load(models, "museum_artifact_large")
    if m:
        c = cautions(m)
        yield ("museum: the ratings' coverage of artifacts is said",
               any("Only" in s and "are referred to by" in s for v in c.values() for s in v),
               "ArtifactRatings covers 10 of 995")
        yield ("museum: several readings per date are said",
               any("rows per date" in s for v in c.values() for s in v), "readTS")
    m = load(models, "sports_events_large")
    if m:
        c = cautions(m)
        yield ("sports: most (race, driver) groups having one lap is said",
               any("groups have a single row" in s for v in c.values() for s in v), "lap_times")
        st = [s for n, v in c.items() if "StMark" in n or "Stmark" in n for s in v]
        yield ("sports: st_mark is not called constant",
               not any("Every row holds the same value" in s for s in st), repr(st[:2]))
    m = load(models, "planets_data_large")
    if m:
        c = cautions(m)
        yield ("planets: a flag null exactly where its measurement is null is said",
               any("Null exactly where" in s for v in c.values() for s in v), "Mag_Blend")
    m = load(models, "polar_equipment_large")
    if m:
        c = cautions(m)
        yield ("polar: the speed named in km/h and held in m/s is said",
               any("The name says" in s for v in c.values() for s in v), "speed")
    m = load(models, "cross_border_large")
    if m:
        core = [c for c in m["concepts"] if c["kind"] == "value"
                and any(t in c["name"] for t in ("DataFlow", "DataProfile", "SecurityProfile",
                                                 "VendorManagement", "RiskManagement"))]
        with_values = [c for c in core if (c.get("restriction") or {}).get("values")]
        yield ("cross_border: the core tables have value lists",
               len(with_values) >= 5, "%d of %d core value types" % (len(with_values), len(core)))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--models", default=os.path.join(HERE, "work", "models-profiled3"))
    args = p.parse_args(argv)
    passed = failed = 0
    for name, ok, note in checks(args.models):
        print("%s  %-66s %s" % ("ok  " if ok else "FAIL", name, note[:90]))
        passed += ok
        failed += not ok
    print("\n%d fixed, %d still there" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
