#!/usr/bin/env python3
"""One scratch directory per (arm, database): the questions without gold or difficulty, the
arm's way in, and an empty answers.json. Nothing in one says whether an answer is right.

Run it with the interpreter that has `mcp` installed; the client scripts name that interpreter.
A directory whose answers.json is not empty is left alone: its inputs are the record of what
its writer saw. `build.py 2` builds the repeat of PLAN2.md in work2/: the two SQL arms only.
"""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DBS = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")
REPEAT = sys.argv[1:] == ["2"]
QUESTIONS = os.path.join(ROOT, "bench/bird/mini_dev_1024/questions%s.json" % ("2" if REPEAT else ""))
WORK = os.path.join(HERE, "work2" if REPEAT else "work")
ARMS = {"sql_ddl": None, "sql_mcp": "sql"}
if not REPEAT:
    ARMS["conquer_mcp"] = "conquer"

COMMON = """# What to do

`questions.json` holds questions about the SQLite database `{db}`. Answer every one. Where a
question has `evidence`, it is outside knowledge offered with the question; some have none.
Work only in this directory: read no other file on this machine, and do not look the
questions or the database up anywhere.

{how}

Run a candidate at most six times for one question, then keep your best. Write `answers.json`
in this directory as a JSON list with one entry per question:

    {{"question_id": 12, "answer": "{language} text", "attempts": 3, "note": "optional"}}

`answer` is the final {language} alone. Nothing tells you whether an answer is right.
"""

HOW_DDL = """1. `{db}.ddl.sql` describes the database. Read it.
2. Write SQLite SQL and run it with `./try "<sql>"`, which shows the rows.
3. Look at the rows and check them against what was asked -- the right columns in the order
   asked, the right row grain, plausible values -- and revise. No rows nearly always means a
   literal spelled differently from the data, or a step that reaches nothing.
4. Return exactly the columns the question asks for, in the order it asks for them."""

HOW_MCP = """`./mcp` is your only way to the database: the header of that script says how to call it.
Start with `./mcp prompt writing_brief '{{"language": "{language}"}}'`, which gives you the brief
and how to work. To avoid quoting trouble, write long JSON arguments to a file and pass them
with `"$(cat args.json)"`."""

TRY = """#!/bin/sh
# Run a candidate SQL statement and show what it returns. Says nothing about correctness.
exec sqlite3 -header -readonly "%s" "$1"
"""

MCP = """#!/bin/sh
# Your MCP client. The server holds the database "%s"; the brief to fetch is
# writing_brief with {"language": "%s"}.
#   ./mcp list
#   ./mcp prompt writing_brief '{"language": "..."}'
#   ./mcp call describe_schema '{"database": "%s", "question": "..."}'
#   ./mcp call run_query '{"database": "...", "query": "..."}'      or run_sql with "sql"
exec "%s" "%s" --server "'%s' %s --config %s" "$@"
"""


def script(path, text):
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, 0o755)


def main():
    qs = json.load(open(QUESTIONS))
    dbs = sorted({q["db_id"] for q in qs})
    os.makedirs(WORK, exist_ok=True)
    config = os.path.join(WORK, "mcp.json")
    with open(config, "w") as fh:
        json.dump({db: {"sqlite": os.path.join(DBS, db, db + ".sqlite"),
                        "model": os.path.join(ROOT, "bench/models/%s.ccm.json" % db)}
                   for db in dbs}, fh, indent=1)
    for arm, mcp in ARMS.items():
        for db in dbs:
            d = os.path.join(WORK, arm, db)
            answers = os.path.join(d, "answers.json")
            if os.path.exists(answers) and json.load(open(answers)):
                print("left alone: %s/%s" % (arm, db))
                continue
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "questions.json"), "w") as fh:
                json.dump([dict({"question_id": q["question_id"], "question": q["question"]},
                                **({"evidence": q["evidence"]} if q["evidence"] else {}))
                           for q in qs if q["db_id"] == db], fh, indent=1)
            language = "ConQuer" if mcp == "conquer" else "SQL"
            if mcp:
                how = HOW_MCP.format(language=mcp)
                script(os.path.join(d, "mcp"), MCP % (
                    db, mcp, db, sys.executable, os.path.join(ROOT, "mcp/client.py"),
                    sys.executable, os.path.join(ROOT, "mcp/server.py"), config))
            else:
                how = HOW_DDL.format(db=db)
                shutil.copy(os.path.join(ROOT, "bench/pilot/material/%s.ddl.sql" % db), d)
                script(os.path.join(d, "try"), TRY % os.path.join(DBS, db, db + ".sqlite"))
            with open(os.path.join(d, "README.md"), "w") as fh:
                fh.write(COMMON.format(db=db, how=how, language=language))
            with open(answers, "w") as fh:
                json.dump([], fh)
    print("%d arms, %d databases, %d questions" % (len(ARMS), len(dbs), len(qs)))


if __name__ == "__main__":
    main()
