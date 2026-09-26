#!/usr/bin/env python3
"""A blind head-to-head on LiveSQLBench: SQL against ConQuer, with no gold to score against.

The gold is withheld by the benchmark, so this cannot measure correctness. What it can measure
is **agreement**: two writers, the same questions, the same database, differing only in the
language they write. Where they agree the answer is probably right; where they differ one of
them is wrong and the difference is worth reading; where one cannot answer at all, that is a
coverage gap with a name.

Two arms, each given what its language needs and nothing else:

    sql       the PostgreSQL DDL with three sample rows per table, as the corpus ships it
    conquer   the model's schema listing narrowed to the question, and the one-page primer

Both get the question and the hierarchical knowledge base entries for that database -- 55% of
these questions name a term defined only there, so withholding it would measure the wrong
thing. Neither gets gold, because there is none to withhold.

    pilot.py [--dbs N] [--per-db N] [--seed N]
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "data")
WORK = os.path.join(HERE, "work", "pilot")
MODELS = os.path.join(HERE, "work", "models")
DBS = os.path.join(HERE, "work", "db")

# LiveSQLBench publishes the same benchmark at three tiers. Large-v1 is PostgreSQL and its
# databases are dumps we load into SQLite for analysis; base-lite-sqlite ships real `.sqlite`
# files with the solution SQL rewritten for them, so it is the tier that can actually be
# scored here (finding 142). Everything below differs only in where the pieces live.
TIERS = {
    "large": {"tasks": "livesqlbench_large_v1_data.jsonl",
              "schema": os.path.join(DATA, "%s", "%s_schema.txt"),
              "kb": os.path.join(DATA, "%s", "%s_kb.jsonl"),
              "db": os.path.join(HERE, "work", "db", "%s.sqlite"),
              "models": os.path.join(HERE, "work", "models"),
              "work": os.path.join(HERE, "work", "pilot"),
              "question": "normal_query"},
    # The same tier run where it is graded: the dataset's own dumps loaded into a PostgreSQL
    # server (README, "Getting it"), reached through the container's psql for the SQL arm
    # and `conquer.py --dsn` for the other. The recorded `large` arms ran on the SQLite
    # copies, and 28 of the SQL arm's 48 answers used a function PostgreSQL does not have.
    "large-pg": {"tasks": "livesqlbench_large_v1_data.jsonl",
                 "schema": os.path.join(DATA, "%s", "%s_schema.txt"),
                 "kb": os.path.join(DATA, "%s", "%s_kb.jsonl"),
                 "db": None,
                 "dsn": os.environ.get("LIVESQL_PG", "postgresql://root:root@localhost:5433")
                 + "/%s_template",
                 "psql": "%s_template",
                 "models": os.path.join(HERE, "work", "models"),
                 "work": os.path.join(HERE, "work", "pilot-pg"),
                 "question": "normal_query"},
    "sqlite": {"tasks": "livesqlbench_data_sqlite.jsonl",
               "schema": os.path.join(DATA, "sqlite_tier", "%s_schema.txt"),
               "kb": os.path.join(DATA, "sqlite_tier", "%s_kb.jsonl"),
               "db": os.path.join(DATA, "sqlite_tier", "%s_template.sqlite"),
               "models": os.path.join(HERE, "work", "models-sqlite-tier"),
               "work": os.path.join(HERE, "work", "pilot-sqlite"),
               "question": "query"},
}
TIER = TIERS["large"]
CQ = os.path.join(ROOT, "conquer", "conquer.py")

TRY_SQL = """#!/bin/sh
# Run a candidate SQL statement and show what it returns. Says nothing about correctness.
exec sqlite3 -header -readonly "file:%s?mode=ro" "$1"
"""

TRY_CQ = """#!/bin/sh
# Run a candidate ConQuer query: the interpretation, then the rows. Says nothing about
# correctness. Add --sql-only to see the SQL it compiles to.
exec python3 "%s" "%s" --db "%s" --check --limit 20 "$@"
"""

TRY_SQL_PG = """#!/bin/sh
# Run a candidate SQL statement on the PostgreSQL server and show what it returns, the first
# sixty lines of it. Says nothing about correctness. The session is read-only and a
# statement is cut off after two minutes.
docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=120000' \\
    livesql-pg psql -X -P pager=off -U root -d "%s" -v ON_ERROR_STOP=1 -c "$1" 2>&1 | head -n 60
"""

TRY_CQ_PG = """#!/bin/sh
# Run a candidate ConQuer query on the PostgreSQL server: the interpretation, then the rows.
# Says nothing about correctness. Add --sql-only to see the SQL it compiles to.
exec python3 "%s" "%s" --dsn "%s" --check --limit 20 "$@"
"""


def try_sql(db):
    if TIER.get("dsn"):
        return TRY_SQL_PG % (TIER["psql"] % db)
    return TRY_SQL % (TIER["db"] % db)


def try_cq(db, model):
    if TIER.get("dsn"):
        return TRY_CQ_PG % (CQ, model, TIER["dsn"] % db)
    return TRY_CQ % (CQ, model, TIER["db"] % db)


def have(db):
    """Is this database here to run against? A server is trusted to hold what it loaded."""
    return True if TIER.get("dsn") else os.path.exists(TIER["db"] % db)

SCHEMA_SQL = """#!/bin/sh
# The conceptual description of this database, in relational terms, narrowed to a question:
#   ./schema "how many plants ..."
#   ./schema "how many plants ..." "MTTR MTBF repair"     <- extra terms widen the view
# What identifies each thing and which columns hold that identity, what is inside the JSON
# columns, the value domains and cautions from profiling the rows, and every relationship
# as a sentence with the columns that carry it. With no arguments it prints everything.
exec python3 "%s" "%s" --schema --relational --for "$*"
"""

SCHEMA_CQ = """#!/bin/sh
# What the schema lets you say, narrowed to a question:
#   ./schema "how many plants ..."
#   ./schema "how many plants ..." "MTTR MTBF repair"     <- extra terms widen the view
#
# The narrowing is scored on the words you pass, and a question names what it is about rather
# than what it is computed from -- "system unavailability" never says MTTR. When a definition
# in knowledge.md names quantities, pass those as a second argument.
exec python3 "%s" "%s" --schema --for "$*"
"""


SCHEMA_DDL = """#!/bin/sh
# The DDL narrowed to a question -- the tables whose names, columns or sample rows match its
# words, and the declared foreign keys between them:
#   ./schema "how many plants ..."
#   ./schema "how many plants ..." "MTTR MTBF repair"     <- extra terms widen the view
# With no arguments it prints every table.
exec python3 "%s" "%s" --for "$*"
"""
DDL_LINK = os.path.join(HERE, "ddl_link.py")

# SCALE3.md: the DDL itself, cut to a budget. `ann` has the model choose the tables and
# annotate them; `ddlp` is the same view chosen lexically with no annotation.
SCHEMA_ANN = """#!/bin/sh
# The DDL of the tables your words are about, with three sample rows each:
#   ./schema "how many plants ..."
#   ./schema "how many plants ..." "MTTR MTBF repair"     <- extra terms widen the view
# Comments beside a column say what profiling the rows found: the values it holds, how they
# are spelled, what is inside a JSON column. With no arguments it prints every table.
exec python3 "%s" "%s" "%s" --for "$*"
"""
SCHEMA_PLAIN = """#!/bin/sh
# The DDL of the tables your words are about, with three sample rows each:
#   ./schema "how many plants ..."
#   ./schema "how many plants ..." "MTTR MTBF repair"     <- extra terms widen the view
# With no arguments it prints every table.
exec python3 "%s" --plain "%s" --for "$*"
"""
ANNOTATE = os.path.join(ROOT, "conquer", "annotate.py")

# SCALE4.md: the same view with what Shkapenyuk et al. used. `ddlm` adds the benchmark's
# column meanings to `ddlp`; `annm` is the annotated view with the meanings and descriptions
# an LLM wrote from a column profile; `annl` adds the value index and the tables and columns
# a draft of each question used.
SCALE4 = os.path.join(HERE, "work", "pilot-scale4")
SCALE4_BUDGET = 20000
SCHEMA_S4 = """#!/bin/sh
# The DDL of the tables your words are about, with three sample rows each:
#   ./schema "how many plants ..."
#   ./schema "how many plants ..." "MTTR MTBF repair"     <- extra terms widen the view
# With no arguments it prints every table.
exec python3 %s --for "$*"
"""


def scale4_script(arm, db, model, schema_txt):
    part = lambda sub: os.path.join(SCALE4, sub, "%s.json" % db)
    args = ['"%s"' % ANNOTATE]
    args += ["--plain"] if arm in ("ddlp4", "ddlm") else ['"%s"' % model]
    args += ['"%s"' % schema_txt, "--budget", str(SCALE4_BUDGET)]
    if arm == "ddlm":
        args += ["--describe", '"%s"' % part("meanings")]
    if arm in ("annm", "annl"):
        args += ["--describe", '"documented=%s"' % part("meanings"),
                 "--describe", '"profiled=%s"' % part("descriptions")]
    if arm == "annl":
        args += ["--values", '"%s"' % part("values"), "--links", '"%s"' % part("links")]
    return SCHEMA_S4 % " ".join(args)
TERMS = os.path.join(HERE, "work", "pilot-scale3", "terms")


def knowledge(db):
    """The database's hierarchical knowledge base, as markdown."""
    path = TIER["kb"] % ((db, db) if TIER["kb"].count("%s") == 2 else db)
    out = ["# Domain knowledge", "",
           "Terms used by the questions, defined here and nowhere else.", ""]
    for line in open(path):
        k = json.loads(line)
        out.append("## %s" % k.get("knowledge", "?"))
        if k.get("description"):
            out.append(k["description"])
        if k.get("definition"):
            out.append("")
            out.append("**Definition.** %s" % k["definition"])
        ch = k.get("children_knowledge")
        if ch not in (None, -1, [], [-1]):
            out.append("")
            out.append("*Depends on knowledge id(s): %s*" % ch)
        out.append("")
    notes = data_notes(db)
    if notes:
        out += ["", "# What the data actually says", "",
                "The knowledge base above is a claim about the data. These are the places "
                "the rows disagree with it, measured rather than assumed "
                "(`bench/livesql/fieldcheck.py`).", ""] + notes + [""]
    return "\n".join(out)


def data_notes(db):
    """Where the rows contradict the documentation, in the words a writer needs.

    A knowledge base goes stale and data acquires faults nobody notices, and both change
    answers: credit documents `networth` as assets minus liabilities and the column equals
    that on none of its thousand rows, so a writer who reads the column is wrong every
    time. Telling the writer costs a paragraph; not telling them cost ten answers.
    """
    if TIER["tasks"] != TIERS["sqlite"]["tasks"]:
        return []                        # the checks read the .sqlite files
    sys.path.insert(0, HERE)
    import fieldcheck                                                   # noqa: E402
    con = fieldcheck.connect(db)
    lines, decoys = [], set()
    try:
        for t, c, term, agree, total, _ in fieldcheck.check_decoys(db, con):
            if agree < total:
                decoys.add((t, c))
                lines.append("- **`%s.%s` does not hold %s.** The definition says it is, and "
                             "the column matches it on %d of %d rows. Compute the value; do "
                             "not read the column." % (t, c, term, agree, total))
        for t, c, term in fieldcheck.check_pins(db, con):
            if (t, c) in decoys:
                continue        # the column is named for it and does not hold it; said above
            lines.append("- **`%s.%s` is %s**, stored. The knowledge base names this column "
                         "as the quantity itself." % (t, c, term))
        for t, c, lo, hi, below, above, total, mn, mx in fieldcheck.check_ranges(db, con):
            lines.append("- **`%s.%s` leaves its documented range.** Stated %s to %s; the "
                         "data runs %s to %s, with %d rows below and %d above, of %d."
                         % (t, c, lo, hi, mn, mx, below, above, total))
        for t, c, declared, got in fieldcheck.check_miscast(db, con):
            lines.append("- **`%s.%s` is documented %s and stored as %s.**"
                         % (t, c, declared, got))
        mixed = fieldcheck.check_mixed(db, con)
        if mixed:
            lines.append(
                "- **%d columns hold integers on some rows and reals on others**, and SQLite "
                "divides those two different ways -- `x / 10` truncates on the integer rows "
                "and not on the others. They are: %s."
                % (len(mixed), ", ".join("`%s.%s`" % (t, c) for t, c, _, _ in mixed)))
    finally:
        con.close()
    return lines


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--tier", choices=sorted(TIERS), default="large",
                   help="which LiveSQLBench tier. `sqlite` is the one that can be scored "
                        "here: real .sqlite databases, solution SQL rewritten for them.")
    p.add_argument("--dbs", type=int, default=6)
    p.add_argument("--per-db", type=int, default=8)
    p.add_argument("--seed", type=int, default=18)
    p.add_argument("--refresh-tools", action="store_true",
                   help="rewrite the try/schema scripts in place, leaving answers alone")
    p.add_argument("--force", action="store_true",
                   help="rebuild even though recorded answers are present, discarding them")
    p.add_argument("--db-list", help="comma-separated databases, overriding the default pick")
    p.add_argument("--work", help="the directory the arms are built in, overriding the tier's")
    p.add_argument("--arms", default="sql,conquer",
                   help="which arms to build, comma-separated: `sql` (DDL), `conquer` (the "
                        "listing and the primer), `sqlnar` (DDL and the listing in "
                        "relational terms -- the layer without the language), `sqlnarp` "
                        "(sqlnar with the profiled models of `build.py --profiled`), "
                        "`sqlddlk` (the DDL narrowed to the question, no full DDL) and "
                        "`sqldesc` (the profiled description narrowed, no DDL) -- SCALE.md; "
                        "`ddlp`, `ann` and `annd` (the DDL cut to a budget: chosen lexically; "
                        "chosen and annotated by the model; and that with the knowledge "
                        "base's terms derived and checked) -- SCALE3.md; `ddlp4`, `ddlm`, "
                        "`annm` and `annl` (the same with column meanings, profile "
                        "descriptions, a value index and draft-query links) -- SCALE4.md. "
                        "Only the arms named are touched.")
    args = p.parse_args(argv)
    global TIER
    TIER = dict(TIERS[args.tier])
    if args.work:
        TIER["work"] = os.path.abspath(args.work)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    tasks = [json.loads(l) for l in
             open(os.path.join(DATA, TIER["tasks"]))]
    query = [t for t in tasks if t["category"] == "Query"]

    # Pick databases that stress different things rather than the first six alphabetically:
    # documents, foreign keys, maps, scale, and two ordinary ones.
    WANTED = ["solar_panel_large",            # documents with dirty types ($150.00 as REAL)
              "sports_events_large",          # 38 jsonb columns, the most of any
              "labor_certification_applications_large",   # 121 foreign keys, the most
              "planets_data_large",           # three map-shaped documents
              "exchange_traded_funds_large",  # the largest, 538,932 rows
              "museum_artifact_large"]        # ordinary, as a control
    if args.db_list:
        WANTED = [d.strip() for d in args.db_list.split(",") if d.strip()]
    dbs = [d for d in WANTED if have(d)][:args.dbs]
    if not dbs:
        # The WANTED list names large-v1's databases. Another tier has its own, and there is
        # no equivalent judgement to make about them yet, so take what the tasks name.
        dbs = sorted({t["selected_database"] for t in query
                      if have(t["selected_database"])})[:args.dbs]

    rng = random.Random(args.seed)
    chosen = {}
    for db in dbs:
        here = [t for t in query if t["selected_database"] == db]
        high = [t for t in here if t.get("high_level")]
        low = [t for t in here if not t.get("high_level")]
        rng.shuffle(high)
        rng.shuffle(low)
        half = args.per_db // 2
        pick = high[:half] + low[:args.per_db - half]
        pick += [t for t in here if t not in pick][:args.per_db - len(pick)]
        chosen[db] = pick[:args.per_db]

    # Never destroy recorded answers. Rebuilding the working directories is cheap and the
    # answers in them are not: they are what an agent spent an hour writing, and the only
    # record of what each arm actually said. Ask for them to be moved, rather than deciding
    # on the author's behalf that they do not matter.
    if args.refresh_tools:
        n = 0
        for db in sorted(os.listdir(os.path.join(TIER["work"], "conquer"))):
            model = os.path.join(TIER["models"], "%s.ccm.json" % db)
            d = os.path.join(TIER["work"], "conquer", db)
            open(os.path.join(d, "schema"), "w").write(SCHEMA_CQ % (CQ, model))
            open(os.path.join(d, "try"), "w").write(try_cq(db, model))
            os.chmod(os.path.join(d, "schema"), 0o755)
            os.chmod(os.path.join(d, "try"), 0o755)
            # The primer is tooling too, and leaving it behind is worse than leaving a stale
            # script: a writer cannot use what it is not told exists. The copies in the
            # LiveSQLBench arms had fallen twelve functions behind -- the whole of the
            # scalar library in section 19b -- and one writer hand-rolled
            # `substr(p, instr(p, '"propvalue": ') + 13, 20)` for want of knowing better.
            open(os.path.join(d, "primer.md"), "w").write(
                subprocess.run([sys.executable, CQ, "--primer"],
                               capture_output=True, text=True, check=True).stdout)
            open(os.path.join(TIER["work"], "sql", db, "try"), "w").write(try_sql(db))
            os.chmod(os.path.join(TIER["work"], "sql", db, "try"), 0o755)
            # The knowledge base is tooling too, and it grew a section: where the rows
            # contradict it. Both arms get it -- the hazards are in the data, not in the
            # language, and withholding them from one arm would measure something else.
            kb = knowledge(db)
            for arm in ("conquer", "sql"):
                d2 = os.path.join(TIER["work"], arm, db)
                if os.path.isdir(d2):
                    open(os.path.join(d2, "knowledge.md"), "w").write(kb)
            n += 1
        print("refreshed the tooling in %d database pair(s); answers untouched" % n)
        return 0

    existing = []
    for arm in arms:
        for root, _, files in os.walk(os.path.join(TIER["work"], arm)):
            existing += [os.path.join(root, f) for f in files if f.startswith("answers")]
    if existing and not args.force:
        print("%d recorded answer file(s) under %s for the arms %s.\n"
              "Move them aside, or pass --force to discard them."
              % (len(existing), TIER["work"], ", ".join(arms)))
        for f in sorted(existing)[:6]:
            print("   %s" % f)
        return 2
    for arm in arms:                     # only the arms asked for; the others keep their answers
        shutil.rmtree(os.path.join(TIER["work"], arm), ignore_errors=True)
    total = 0
    for db in dbs:
        for arm in arms:
            model = os.path.join(TIER["models"] + ("-profiled" if arm in ("sqlnarp", "sqldesc")
                                                   else "-profiled2" if arm in ("ann", "annd", "annm",
                                                                                "annl")
                                                   else ""),
                                 "%s.ccm.json" % db)
            d = os.path.join(TIER["work"], arm, db)
            os.makedirs(d)
            qs = [{"instance_id": t["instance_id"], "question": t[TIER["question"]],
                   "needs_domain_knowledge": bool(t.get("high_level")),
                   "conditions": t.get("conditions", {})} for t in chosen[db]]
            json.dump(qs, open(os.path.join(d, "questions.json"), "w"), indent=1)
            kb_md = knowledge(db)
            if arm == "annd":
                import terms as terms_mod
                kb_md = terms_mod.knowledge_with_terms(
                    db, kb_md, os.path.join(TERMS, "%s.checked.json" % db))
            open(os.path.join(d, "knowledge.md"), "w").write(kb_md)
            schema_txt = TIER["schema"] % ((db, db) if TIER["schema"].count("%s") == 2 else db)
            if arm in ("sqlddlk", "sqldesc", "ddlp", "ann", "annd",
                       "ddlp4", "ddlm", "annm", "annl"):
                # SCALE.md: the schema only through a narrower, never whole in a file
                open(os.path.join(d, "try"), "w").write(try_sql(db))
                script = (SCHEMA_DDL % (DDL_LINK, schema_txt) if arm == "sqlddlk"
                          else SCHEMA_PLAIN % (ANNOTATE, schema_txt) if arm == "ddlp"
                          else SCHEMA_ANN % (ANNOTATE, model, schema_txt) if arm in ("ann", "annd")
                          else scale4_script(arm, db, model, schema_txt)
                          if arm in ("ddlp4", "ddlm", "annm", "annl")
                          else SCHEMA_SQL % (CQ, model))
                open(os.path.join(d, "schema"), "w").write(script)
                os.chmod(os.path.join(d, "schema"), 0o755)
            elif arm in ("sql", "sqlnar", "sqlnarp"):
                shutil.copy(TIER["schema"] % ((db, db) if TIER["schema"].count("%s") == 2 else db),
                            os.path.join(d, "schema.sql"))
                open(os.path.join(d, "try"), "w").write(try_sql(db))
                if arm in ("sqlnar", "sqlnarp"):
                    # the layer without the language: the same listing the ConQuer arm
                    # reads, in relational terms, beside the DDL. `sqlnarp` reads it from
                    # the profiled model -- the same model plus what the rows say, which
                    # finding 163's models had none of
                    open(os.path.join(d, "schema"), "w").write(SCHEMA_SQL % (CQ, model))
                    os.chmod(os.path.join(d, "schema"), 0o755)
            else:
                open(os.path.join(d, "primer.md"), "w").write(
                    subprocess.run([sys.executable, CQ, "--primer"],
                                   capture_output=True, text=True).stdout)
                open(os.path.join(d, "try"), "w").write(try_cq(db, model))
                open(os.path.join(d, "schema"), "w").write(SCHEMA_CQ % (CQ, model))
                os.chmod(os.path.join(d, "schema"), 0o755)
            os.chmod(os.path.join(d, "try"), 0o755)
        total += len(chosen[db])
    print("%d questions over %d databases, %d arm(s) -> %d working directories"
          % (total, len(dbs), len(arms), len(arms) * len(dbs)))
    for db in dbs:
        n = sum(1 for t in chosen[db] if t.get("high_level"))
        print("   %-40s %d questions (%d need domain knowledge)"
              % (db, len(chosen[db]), n))
    json.dump({db: [t["instance_id"] for t in chosen[db]] for db in dbs},
              open(os.path.join(TIER["work"], "sample.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
