#!/usr/bin/env python3
"""Merge a semantic-layer fragment into a database's model and prove every definition
compiles and runs.

    check.py DB FRAGMENT.json         # validates, lowers, probes; writes DB.semantic.ccm.json

The fragment is {"concepts": [...], "derivationRules": [...], "macros": [...]}, in the
CCM's shapes. Each derived concept is probed with THE COUNT OF; each macro is expanded with
dummy arguments. Nothing here looks at any question or any gold SQL.
"""
import copy, json, os, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
while not (os.path.isdir(os.path.join(ROOT, "conquer")) and os.path.isdir(os.path.join(ROOT, "model"))):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        raise RuntimeError("could not locate repo root (a directory containing conquer/ and model/) above %s" % HERE)
    ROOT = parent
sys.path.insert(0, os.path.join(ROOT, "conquer")); sys.path.insert(0, os.path.join(ROOT, "model"))
import conquer as driver, parser as parser_mod, sql as sql_mod, lower as lower_mod   # noqa
import validate as validate_mod                                                      # noqa

DBS = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")


def main(db, fragment_path, out_dir=None):
    base = json.load(open(os.path.join(ROOT, "bench/models/%s.ccm.json" % db)))
    frag = json.load(open(fragment_path))
    m = copy.deepcopy(base)
    ids = {c["id"] for c in m["concepts"]} | {r["id"] for r in m.get("derivationRules", [])}
    problems = []
    for key in ("concepts", "derivationRules", "macros"):
        for item in frag.get(key, []):
            if item["id"] in ids:
                problems.append("duplicate id %s" % item["id"])
            ids.add(item["id"])
            m.setdefault(key, []).append(item)
    tmp = tempfile.mktemp(suffix=".ccm.json")
    json.dump(m, open(tmp, "w"))
    schema = json.load(open(os.path.join(ROOT, "model/ccm.schema.json")))
    findings = validate_mod.validate(tmp, schema)
    os.unlink(tmp)
    problems += ["validate: %s %s %s" % f[1:4] for f in findings.errors]
    if problems:
        print("\n".join("FAIL " + p for p in problems)); return 1

    lex = parser_mod.Lexicon(m)
    try:
        lower_mod.lower_rules(m, lex)
    except parser_mod.ParseError as e:
        print("FAIL rule: %s" % e); return 1
    em = sql_mod.Emitter(m)
    conn = sqlite3.connect(os.path.join(DBS, db, db + ".sqlite"))
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    deadline = [0]
    import time
    def run(q):
        _, st, p = driver.transpile(m, q, lex, em)
        deadline[0] = time.time() + 60
        conn.set_progress_handler(lambda: 1 if time.time() > deadline[0] else 0, 20000)
        try:
            return conn.execute(st, p).fetchall()
        finally:
            conn.set_progress_handler(None, 0)
    ok = True
    for c in frag.get("concepts", []):
        if not c.get("derivation"):
            continue
        q = "THE COUNT OF %s" % c["name"]
        try:
            rows = run(q); print("ok   %-40s %s -> %s" % (c["name"], q, rows[0][0]))
        except Exception as e:
            ok = False; print("FAIL %-40s %s: %s" % (c["name"], type(e).__name__, str(e)[:160]))
    for mc in frag.get("macros", []):
        n = len(mc.get("parameters", []))
        args = ", ".join(["1"] * n)
        q = {"scalar": "LIST %s(%s), 0" % (mc["name"], args),
             "condition": "LIST IF %s(%s) THEN 1 ELSE 0, 0" % (mc["name"], args),
             "path": "THE COUNT OF %s(%s)" % (mc["name"], args)}[mc["kind"]]
        try:
            rows = run(q); print("ok   %-40s %s" % ("%s/%d" % (mc["name"], n), mc["kind"]))
        except Exception as e:
            ok = False; print("FAIL %-40s %s: %s" % (mc["name"], type(e).__name__, str(e)[:160]))
    if ok:
        out = os.path.join(out_dir or os.path.dirname(fragment_path), "%s.semantic.ccm.json" % db)
        json.dump(m, open(out, "w"), indent=1)
        print("all definitions compile and run; merged model written to %s" % out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
