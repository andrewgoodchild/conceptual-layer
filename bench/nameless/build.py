#!/usr/bin/env python3
"""The October 2026 mini-dev's first 100 questions on undocumented copies of their databases
(PLAN.md): no foreign key declared, no evidence, and in one copy no name either.

    build.py dbs       data/named/<db>.sqlite, foreign keys dropped; data/nameless/<db>.sqlite,
                       every table and column renamed too and each table's columns
                       shuffled (bench/ablation/corpora.py)
    build.py models    data/models/<copy>/, reverse engineered from each copy alone
    build.py work      one scratch directory per (arm, database), as bench/minidev2026/build.py

`data/` holds BIRD's rows and is not distributed; it may be a symlink to a larger disk. Run
`work` with the interpreter that has `mcp` installed, or name it in MCP_PYTHON: a venv's
interpreter can report its base's path, which has no `mcp`. The client scripts name it. A directory
whose answers.json is not empty is left alone: its inputs are the record of what its writer saw.
"""
import importlib.util, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "bench/ablation"))
sys.path.insert(0, os.path.join(ROOT, "bench/pilot"))
import corpora                                       # noqa: E402
import material                                      # noqa: E402

# October's build.py, by path: bench/pilot has a build.py of its own.
_spec = importlib.util.spec_from_file_location(
    "october", os.path.join(ROOT, "bench/minidev2026/build.py"))
october = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(october)

BIRD = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")
QUESTIONS = os.path.join(ROOT, "bench/bird/mini_dev_1024/questions.json")
DATA = os.path.join(HERE, "data")
WORK = os.path.join(HERE, "work")
COPIES = ("named", "nameless")
# The arm's way in, and which copy it sees. The text each writer reads is October's.
ARMS = {"ddl_named": (None, "named"), "mcp_named": ("sql", "named"),
        "ddl_nameless": (None, "nameless"), "mcp_nameless": ("sql", "nameless")}
# The shipped data passes, as bench/run.sh builds BIRD's models, and rule 9c's search, which
# is what an undocumented database needs. No judge: on the nameless copy it has nothing to
# read (finding 183), and on the named one it would be a second variable.
PYTHON = os.environ.get("MCP_PYTHON", sys.executable)
FLAGS = ["--infer-keys", "--infer-fks", "--infer-domains", "--infer-enforced"]


def databases():
    return sorted({q["db_id"] for q in json.load(open(QUESTIONS))})


def copy_path(copy, db):
    return os.path.join(DATA, copy, db + ".sqlite")


def model_path(copy, db):
    return os.path.join(DATA, "models", copy, db + ".ccm.json")


def dbs():
    for copy in COPIES:
        os.makedirs(os.path.join(DATA, copy), exist_ok=True)
    for db in databases():
        source = os.path.join(BIRD, db, db + ".sqlite")
        corpora.strip(source, copy_path("named", db))
        renamed = copy_path("nameless", db) + ".renamed"
        corpora.destroy(source, renamed)
        corpora.strip(renamed, copy_path("nameless", db), seed=20261107)
        os.remove(renamed)
        print("ok   %s" % db)


def models():
    for copy in COPIES:
        out = os.path.join(DATA, "models", copy)
        os.makedirs(out, exist_ok=True)
        for db in databases():
            subprocess.run([sys.executable, os.path.join(ROOT, "reverse/reverse.py"),
                            copy_path(copy, db), "-o", out, "-n", db] + FLAGS, check=True,
                           stdout=subprocess.DEVNULL)
            print("ok   %s/%s" % (copy, db))


def work():
    qs = json.load(open(QUESTIONS))
    os.makedirs(WORK, exist_ok=True)
    configs = {}
    for copy in COPIES:
        configs[copy] = os.path.join(WORK, "mcp-%s.json" % copy)
        with open(configs[copy], "w") as fh:
            json.dump({db: {"sqlite": copy_path(copy, db), "model": model_path(copy, db)}
                       for db in databases()}, fh, indent=1)
    for arm, (mcp, copy) in ARMS.items():
        for db in databases():
            d = os.path.join(WORK, arm, db)
            answers = os.path.join(d, "answers.json")
            if os.path.exists(answers) and json.load(open(answers)):
                print("left alone: %s/%s" % (arm, db))
                continue
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "questions.json"), "w") as fh:
                json.dump([{"question_id": q["question_id"], "question": q["question"]}
                           for q in qs if q["db_id"] == db], fh, indent=1)
            if mcp:
                how = october.HOW_MCP.format(language=mcp)
                october.script(os.path.join(d, "mcp"), october.MCP % (
                    db, mcp, db, PYTHON, os.path.join(ROOT, "mcp/client.py"),
                    PYTHON, os.path.join(ROOT, "mcp/server.py"), configs[copy]))
            else:
                how = october.HOW_DDL.format(db=db)
                with open(os.path.join(d, db + ".ddl.sql"), "w") as fh:
                    fh.write(material.ddl_text(copy_path(copy, db)))
                october.script(os.path.join(d, "try"), october.TRY % copy_path(copy, db))
            with open(os.path.join(d, "README.md"), "w") as fh:
                fh.write(october.COMMON.format(db=db, how=how, language="SQL"))
            with open(answers, "w") as fh:
                json.dump([], fh)
    print("%d arms, %d databases, %d questions" % (len(ARMS), len(databases()), len(qs)))


if __name__ == "__main__":
    {"dbs": dbs, "models": models, "work": work}[sys.argv[1]]()
