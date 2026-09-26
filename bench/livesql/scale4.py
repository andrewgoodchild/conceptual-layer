#!/usr/bin/env python3
"""SCALE4.md's preparation: the describers' and linkers' working directories, and collecting
what they wrote into the files `annotate.py` reads.

    scale4.py describe DB     work/pilot-scale4/describe/DB/  (profile.txt only)
    scale4.py link DB         work/pilot-scale4/link/DB/      (questions, knowledge, ./schema)
    scale4.py collect DB      descriptions/DB.json and links/DB.json from what they wrote
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pilot                                                              # noqa: E402

W = pilot.SCALE4
SCALE3 = os.path.join(HERE, "work", "pilot-scale3")


def fresh(d):
    for f in ("descriptions.json", "links.json"):
        if os.path.exists(os.path.join(d, f)):
            raise SystemExit("%s already has %s; move it aside first" % (d, f))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)


def describe(db):
    d = os.path.join(W, "describe", db)
    fresh(d)
    shutil.copy(os.path.join(W, "profile", "%s.txt" % db), os.path.join(d, "profile.txt"))
    print("prepared %s" % d)


def link(db):
    pilot.TIER = dict(pilot.TIERS["large-pg"])
    d = os.path.join(W, "link", db)
    fresh(d)
    qs = json.load(open(os.path.join(SCALE3, "ddlp", db, "questions.json")))
    json.dump([{"instance_id": q["instance_id"], "question": q["question"]} for q in qs],
              open(os.path.join(d, "questions.json"), "w"), indent=1)
    open(os.path.join(d, "knowledge.md"), "w").write(pilot.knowledge(db))
    model = os.path.join(pilot.TIER["models"] + "-profiled2", "%s.ccm.json" % db)
    schema = pilot.TIER["schema"] % (db, db)
    open(os.path.join(d, "schema"), "w").write(pilot.scale4_script("annm", db, model, schema))
    os.chmod(os.path.join(d, "schema"), 0o755)
    print("prepared %s" % d)


def collect(db):
    for sub, f in (("describe", "descriptions"), ("link", "links")):
        src = os.path.join(W, sub, db, "%s.json" % f)
        if not os.path.exists(src):
            print("%s: no %s yet" % (db, src))
            continue
        data = json.load(open(src))
        os.makedirs(os.path.join(W, f), exist_ok=True)
        json.dump(data, open(os.path.join(W, f, "%s.json" % db), "w"), indent=1)
        print("%s: %d %s" % (db, len(data), f))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["describe", "link", "collect"])
    p.add_argument("dbs", nargs="+")
    args = p.parse_args(argv)
    for db in args.dbs:
        {"describe": describe, "link": link, "collect": collect}[args.action](db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
