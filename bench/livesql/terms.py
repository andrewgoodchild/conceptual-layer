#!/usr/bin/env python3
"""The knowledge base's terms, derived once in this database and checked against its rows.

Finding 166's writers missed most where a definition's formula names quantities no column is
called; finding 167's fix, matching definitions to columns by shared words, pointed the wrong
way every time. An ORM model's answer to a business term is a *derivation*: the term said in
the schema's own facts, authored once and checked, rather than guessed at by every reader.
This is that, in the form a SQL writer reads.

A definer -- one blind agent per database, which never sees a question -- reads the knowledge
base, the schema and the rows, and writes each term's derivation (`DEFINE.md`). This script
then *runs* every derivation and records what came back, so a term that does not run, or
returns nothing, says so beside it instead of passing for knowledge.

    terms.py prepare DB [--dir work/pilot-scale3/define]      the definer's working directory
    terms.py check DB                                         run the derivations; write
                                                              terms/DB.checked.json
"""
import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")
WORK = os.path.join(HERE, "work", "pilot-scale3")
MODELS = os.path.join(HERE, "work", "models-profiled2")


def kb(db):
    return [json.loads(l) for l in open(os.path.join(DATA, db, "%s_kb.jsonl" % db))]


def kb_markdown(db):
    """The knowledge base with each entry's id, which the definer's answer is keyed on."""
    out = ["# Domain knowledge", ""]
    for k in kb(db):
        out.append("## [%s] %s" % (k["id"], k.get("knowledge", "?")))
        for f in ("description", "definition"):
            if k.get(f):
                out.append("%s: %s" % (f.capitalize(), k[f]))
        ch = k.get("children_knowledge")
        if ch not in (None, -1, [], [-1]):
            out.append("Depends on: %s" % ch)
        out.append("")
    return "\n".join(out)


def prepare(db, root):
    import pilot
    pilot.TIER = dict(pilot.TIERS["large-pg"])
    d = os.path.join(root, db)
    if os.path.exists(os.path.join(d, "terms.json")):
        print("%s already has terms.json; move it aside first" % d)
        return 2
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    schema = os.path.join(DATA, db, "%s_schema.txt" % db)
    open(os.path.join(d, "knowledge.md"), "w").write(kb_markdown(db))
    open(os.path.join(d, "try"), "w").write(pilot.try_sql(db))
    open(os.path.join(d, "schema"), "w").write(
        pilot.SCHEMA_ANN % (pilot.ANNOTATE, os.path.join(MODELS, "%s.ccm.json" % db), schema))
    for f in ("try", "schema"):
        os.chmod(os.path.join(d, f), 0o755)
    print("prepared %s" % d)
    return 0


def check(db, root):
    import score_pg
    terms = json.load(open(os.path.join(root, db, "terms.json")))
    conn = score_pg.connect(score_pg.DSN, db)
    names = {k["id"]: k.get("knowledge") for k in kb(db)}
    out = []
    for t in terms:
        rec = dict(t)
        rec["knowledge"] = names.get(t.get("id"), t.get("knowledge"))
        # a definer's own LIMIT would make the recorded range a sample's
        sql = re.sub(r"\s+LIMIT\s+\d+\s*$", "", (t.get("check") or "").strip().rstrip(";"),
                     flags=re.I)
        if t.get("kind") == "none" or not sql:
            rec["checked"] = "not derived"
            out.append(rec)
            continue
        got = score_pg.rows(conn, "SELECT * FROM (%s) q LIMIT 100000" % sql)
        if isinstance(got, str):
            rec["checked"] = "failed: " + got
        elif not got:
            rec["checked"] = "ran, returned no rows"
        else:
            last = [r[-1] for r in got]
            nulls = sum(v is None for v in last)
            nums = [v for v in last if isinstance(v, float)]
            said = "ran, %s row%s" % (format(len(got), ","), "" if len(got) == 1 else "s")
            if nulls:
                said += ", %d%% of them null" % round(100 * nulls / len(got))
            if nums:
                said += ", from %s to %s" % (min(nums), max(nums))
            elif len({v for v in last if v is not None}) <= 6:
                said += ", values %s" % ", ".join(sorted({repr(v) for v in last
                                                          if v is not None})[:6])
            rec["checked"] = said
        out.append(rec)
    conn.close()
    os.makedirs(os.path.join(WORK, "terms"), exist_ok=True)
    path = os.path.join(WORK, "terms", "%s.checked.json" % db)
    json.dump(out, open(path, "w"), indent=1)
    bad = sum(not r["checked"].startswith("ran") for r in out)
    print("%s: %d terms, %d ran and returned rows, %d did not" % (db, len(out),
                                                                len(out) - bad, bad))
    return 0


def knowledge_with_terms(db, kb_md, checked_path):
    """The knowledge base as the writers read it, each definition followed by how it is
    derived in this database and what running that returned."""
    if not os.path.exists(checked_path):
        raise SystemExit("no %s: run terms.py check %s first" % (checked_path, db))
    by_name = {t["knowledge"]: t for t in json.load(open(checked_path))}
    out, pending = [], None

    def flush():
        t = by_name.get(pending)
        if not t or t.get("kind") == "none" or not t.get("expression"):
            return
        while out and not out[-1].strip():
            out.pop()
        out.extend(["", "**In this database** (%s; derived once from the schema and checked "
                        "by running it: %s):" % (t["kind"], t["checked"]), "",
                    "    %s" % " ".join(t["expression"].split())])
        if t.get("from"):
            out.append("    -- over: %s" % " ".join(t["from"].split()))
        if t.get("note"):
            out.extend(["", "*Note:* %s" % " ".join(t["note"].split())])
        out.append("")
    for line in kb_md.splitlines():
        if line.startswith("#"):
            flush()
            pending = line[3:].strip() if line.startswith("## ") else None
        out.append(line)
    flush()
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "check"])
    p.add_argument("db")
    p.add_argument("--dir", default=os.path.join(WORK, "define"))
    args = p.parse_args(argv)
    return (prepare if args.action == "prepare" else check)(args.db, args.dir)


if __name__ == "__main__":
    sys.exit(main())
