#!/usr/bin/env python3
"""Build one scratch directory per (arm, database) for the pilot.

Each directory holds only what that arm is allowed to see: the questions without their gold
SQL, the material the arm is defined by, and a `try` command that runs a candidate answer and
shows what it returns. Nothing in a scratch directory reveals whether an answer is right --
`try` shows rows, exactly what a developer sees, and the same for every arm.
"""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DBS = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")
MAT = os.path.join(HERE, "material")

ARMS = {
    "direct":        ["ddl"],                       # SQL from the physical schema
    "conquer":       ["schema", "primer"],          # ConQuer from the conceptual model
    # 25 Sep: the same two languages with nothing in the directory but the questions and an
    # MCP client -- the description, the runner and the brief itself fetched from mcp/server.py
    # over the protocol. The test of the server as the product surface.
    "conquer_mcp":   {"materials": [], "mcp": "conquer"},
    "direct_mcp":    {"materials": [], "mcp": "sql"},
    "modelled":      ["ddl", "forml"],              # SQL from the DDL PLUS the report's FORML excerpt
    # the second round: the FULL FORML verbalisation (the report's excerpt cut european_football_2
    # to a quarter), once for each language
    "conquer_forml": ["schema", "primer", "forml_full"],
    "modelled_full": ["ddl", "forml_full"],
    # the third round, dbt's comparison done fairly: the evidence field withheld from the
    # prompt. SQL from DDL alone is dbt's baseline; ConQuer bare separates the loss of the
    # evidence from the gain of the layer; ConQuer with the semantic layer has the same
    # definitions encoded in the model as derived fact types, subtypes and macros.
    "direct_noev":   {"materials": ["ddl"], "evidence": False},
    "conquer_noev":  {"materials": ["schema", "primer"], "evidence": False},
    "conquer_sem":   {"materials": ["schema_sem", "primer", "forml_sem"], "evidence": False,
                      "model": "semantic"},
    # the comparison the semantic-layer round left out (12 Sep): dbt's own claim is for SQL
    # generation, so give a SQL writer the same definitions as English, evidence withheld.
    # If this scores what conquer_sem scores, the definitions did the work, not the language.
    "modelled_sem":  {"materials": ["ddl", "forml_sem"], "evidence": False},
    # the ablations (12 Sep): each adds one thing to the `conquer` arm, or to the no-evidence
    # arm where the thing addresses what withholding the evidence took away
    "conquer_run2":  ["schema", "primer"],           # a second independent writer: candidates
    "conquer_run3":  ["schema", "primer"],           # a third
    "conquer_opus":  ["schema", "primer"],           # the same arm, a stronger writer
    "direct_opus":   ["ddl"],                        # and the baseline with the same writer
    "conquer_noev_lookup": {"materials": ["schema", "primer"], "evidence": False,
                            "lookup": True},         # a value-grounding tool, no evidence
    # finding 57: the same arm as `conquer`, with every attempt logged rather than only the
    # last, so the refusals can be counted and replayed under --permissive
    "conquer_logged": {"materials": ["schema", "primer"], "log": True},
    "conquer_verified": {"materials": ["schema", "primer"], "draft": "conquer"},
                                                     # a verifier over the conquer arm's answers
    # 14 Sep: the candidate-and-selection ablation again, done the way CHASE-SQL means it.
    # The earlier round sampled ONE prompt three times, which is the configuration that paper
    # says fails; these three differ in *strategy*, which is what the claim rests on. If three
    # diverse writers do not disagree more than three identical ones did (79 of 100 agreed,
    # 17 of those unanimously wrong), no selector can help and the claim dies cheaply.
    "conquer_dc":    {"materials": ["schema", "primer"], "strategy": "strategy-dc.md"},
    "conquer_plan":  {"materials": ["schema", "primer"], "strategy": "strategy-plan.md"},
    "conquer_shots": {"materials": ["schema", "primer"], "strategy": "strategy-shots.md"},
    "conquer_chase": {"materials": ["schema", "primer"],
                      "candidates": ["conquer_dc", "conquer_plan", "conquer_shots"]},
    "conquer_select": {"materials": ["schema", "primer"],
                       "candidates": ["conquer", "conquer_run2", "conquer_run3"]},
    # 15 Sep: the English description of the model is the one input that helped a SQL writer
    # (`modelled` 73-74 against `direct` 70), and it is also the input that does not scale --
    # the flat verbalisation of a Spider 2.0 schema is 18 KB of elementary facts in which
    # "Driver has DriverUrl" reads as loudly as "Result is of Race". `forml_abstract` is the
    # same model said at Bird's second level of abstraction (model/abstract.py): the things the
    # database is about, what each carries, and how they relate -- about a third the size.
    # Against `modelled` it asks whether a shorter, shaped description beats a complete flat
    # one; against `modelled_full` it holds the writer fixed and changes only the shaping.
    "modelled_abstract": ["ddl", "forml_abstract"],
    # the control the abstract arms need. Both were launched with prompts written on 15 Sep;
    # the prompt the original `modelled_full` agents were given cannot be recovered verbatim,
    # so a loss could be the material or could be the wording. This is `modelled_full` again,
    # same material, under the NEW prompt: whatever it scores is what the new prompt is worth
    # on flat English, and the abstract arm's gap against IT is what the shaping is worth.
    "modelled_full_v2": ["ddl", "forml_full"],
    # and the control for THAT: `direct` again under the same new prompt. Without it,
    # "the English is worth nothing here" and "this prompt is worth three points less"
    # cannot be told apart, and the first would overturn finding 43.
    "direct_v2": ["ddl"],
    # Finding 72: the abstraction loses no tables, so what the flat English has that the
    # summary lacks is what it is *made of* -- 82% of its sentences are "each X has at most
    # one Y". These two arms test that from both sides, under the same prompt as direct_v2
    # (68), modelled_full_v2 (70) and modelled_abstract (68).
    # 15 Sep, finding 74: with the ceiling near 86 and the best arm at 77, the only untried
    # combination of two measured winners is the divide-and-conquer method (+6, Sonnet) under
    # a stronger writer (+5, Opus with the plain prompt). `conquer_dc_v2` is the control the
    # comparison needs: the primer was rewritten this morning, so without it the Opus arm
    # would differ from `conquer_dc` (77) in two things at once.
    "conquer_dc_v2":   {"materials": ["schema", "primer"], "strategy": "strategy-dc.md"},
    # finding 75: dc_v2 scored 62 where dc scored 77, and the two differ in the primer AND in
    # the compiler (both changed on 15 Sep). This is dc again with the FROZEN primer -- the
    # exact text conquer_dc was given -- under today's compiler, which separates the two.
    "conquer_dc_old":  {"materials": ["schema", "primer_frozen"], "strategy": "strategy-dc.md"},
    "conquer_dc_opus": {"materials": ["schema", "primer"], "strategy": "strategy-dc.md"},
    "modelled_nouniq": ["ddl", "forml_nouniq"],              # flat, cardinality removed
    "modelled_abstract_card": ["ddl", "forml_abstract_card"],  # summary, cardinality added
    "conquer_abstract": ["schema", "primer", "forml_abstract"],

    # Does model QUALITY cost an author anything? The same questions and the same materials
    # against three models that differ only in which foreign keys they were built from:
    # every one the catalogue declares, what rule 9c infers from the data, and what a blind
    # judge kept of a generous proposal (finding 118). `bench/ablation/models.py` builds
    # them. The recorded-answer measure in `bench/ablation/downstream.py` asks whether an
    # answer already written still runs; this asks whether it can be written at all.
    "conquer_refs_declared": {"materials": ["schema_refs_declared", "primer"],
                              "model": "refs-declared"},
    "conquer_refs_rules":    {"materials": ["schema_refs_rules", "primer"],
                              "model": "refs-rules"},
    "conquer_refs_judged":   {"materials": ["schema_refs_judged", "primer"],
                              "model": "refs-judged"},
    # 19 Sep, finding 132's successor: projecting the wrong NUMBER of columns is fatal by
    # construction -- the tuples cannot match -- and it costs 108 of the ~953 recorded misses,
    # three of them in the best arm (q215, q1179, q1427, each one column where gold has two or
    # three). It is also the only failure class checkable from the question text alone, with
    # no gold, no database and no model. This is `conquer_dc_opus` (78) again with one
    # paragraph added to the brief telling the writer to count. Same strategy, same writer,
    # same materials, same compiler: the brief is the only variable.
    "conquer_dc_arity": {"materials": ["schema", "primer"], "strategy": "strategy-dc-arity.md"},
                                                     # a selector over three writers' candidates
}

LOOKUP = """#!/bin/sh
# Where does a literal live? Searches every column for a value equal to, containing, or
# resembling the text, and names the value type that holds it. Says nothing about meaning.
export DB MODEL ROOT
exec python3 "$LOOKUP" "$@"
"""

MCP_CLIENT = """#!/bin/sh
# Your MCP client. The server holds the database "%s"; the brief to fetch is
# writing_brief with {"language": "%s"}.
#   ./mcp list
#   ./mcp prompt writing_brief '{"language": "..."}'
#   ./mcp call describe_schema '{"database": "%s", "question": "..."}'
#   ./mcp call run_query '{"database": "...", "query": "..."}'      or run_sql with "sql"
exec python3 "%s" --server "python3 %s --config %s" "$@"
"""

TRY_SQL = """#!/bin/sh
# Run a candidate SQL statement and show what it returns. Says nothing about correctness.
exec sqlite3 -header -readonly "$DB" "$1"
"""

TRY_CQ = """#!/bin/sh
# Run a candidate ConQuer query: the interpretation, then the rows. Says nothing about
# correctness. Add --sql-only to see the SQL it compiles to.
exec python3 "$CQ" "$MODEL" --db "$DB" --check --limit 20 "$@"
"""

# The same thing, keeping every query tried. Finding 57: the recorded answers are what
# survived the compiler's refusals, so they say nothing about how often it refused or what
# the refusal was worth. The log is the missing evidence -- one line of JSON per attempt,
# written before the compiler is asked, so an attempt that is refused is recorded exactly
# like one that is not. Nothing in it reveals whether an answer is right.
TRY_CQ_LOGGED = """#!/bin/sh
# Run a candidate ConQuer query: the interpretation, then the rows. Says nothing about
# correctness. Add --sql-only to see the SQL it compiles to.
python3 - "$LOG" "$@" <<'PYEOF'
import json, sys, time
with open(sys.argv[1], "a") as fh:
    print(json.dumps({"at": time.time(),
                      "query": " ".join(a for a in sys.argv[2:] if not a.startswith("-"))}),
          file=fh)
PYEOF
exec python3 "$CQ" "$MODEL" --db "$DB" --check --limit 20 "$@"
"""


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--arm", action="append", help="build only this arm (repeatable); leaves the rest alone")
    p.add_argument("--fresh", action="store_true",
                   help="wipe the arms being built first -- every arm, unless --arm names "
                        "some. Destroys their answer files, which are evidence.")
    args = p.parse_args(argv)
    qs = json.load(open(os.path.join(HERE, "questions.json")))
    work = os.path.join(HERE, "work")
    arms = {a: ARMS[a] for a in (args.arm or ARMS)}
    if args.fresh:
        # Only the arms asked for: --fresh used to wipe work/ whole, so `--fresh --arm direct`
        # destroyed 198 answer files while --arm's help promised it left the rest alone.
        for arm in arms:
            shutil.rmtree(os.path.join(work, arm), ignore_errors=True)
    made, left = [], []
    for arm, spec in arms.items():
        spec = spec if isinstance(spec, dict) else {"materials": spec}
        wants = spec["materials"]
        for db in sorted({q["db_id"] for q in qs}):
            mine = [q for q in qs if q["db_id"] == db]
            d = os.path.join(work, arm, db)
            os.makedirs(d, exist_ok=True)
            # `try` is rebuilt every time: it is a script, and the only way to get a fresh one
            # used to be --fresh, which destroys answers. Everything else here is an *input*,
            # and an arm that has already answered must keep the inputs it answered against --
            # rewriting `questions.json`, the materials, or a `draft.json` built from another
            # arm's answers would leave the recorded answers attributed to a prompt nobody saw.
            answers = os.path.join(d, "answers.json")
            answered = os.path.exists(answers) and bool(json.load(open(answers)))
            if answered:
                left.append((arm, db))
            else:
                # questions, stripped of the gold SQL and of the difficulty label
                json.dump([dict({"question_id": q["question_id"], "question": q["question"]},
                                **({"evidence": q["evidence"]} if spec.get("evidence", True)
                                   else {}))
                           for q in mine],
                          open(os.path.join(d, "questions.json"), "w"), indent=1)
                if spec.get("strategy"):
                    shutil.copy(os.path.join(MAT, spec["strategy"]),
                                os.path.join(d, "how-to-work.md"))
                for w in wants:
                    if w == "primer_frozen":
                        shutil.copy(os.path.join(MAT, "conquer-primer-frozen.md"),
                                    os.path.join(d, "conquer-primer.md"))
                        continue
                    if w in ("forml_abstract_card", "forml_nouniq"):
                        sys.path.insert(0, os.path.join(ROOT, "model"))
                        mpath = os.path.join(ROOT, "bench/models/%s.ccm.json" % db)
                        mm = json.load(open(mpath))
                        if w == "forml_abstract_card":
                            import abstract as abstract_mod
                            name = "%s.forml-abstract-card.md" % db
                            text = abstract_mod.summarise(mm, 2, cardinality=True)
                        else:
                            import forml as forml_mod
                            name = "%s.forml-nouniq.md" % db
                            text = ("# What the model says\n\nEvery constraint in the "
                                    "conceptual model of this database, as FORML 2 "
                                    "sentences.\n\n" + "\n".join(
                                        "- " + x for x in forml_mod.verbalize_model(
                                            mm, skip_kinds={"uniqueness"})))
                        with open(os.path.join(d, name), "w") as fh:
                            fh.write(text + "\n")
                        continue
                    if w == "forml_abstract":
                        # derived, not stored: the summary is a function of the model, and a
                        # stored copy would be one more thing to forget to regenerate
                        sys.path.insert(0, os.path.join(ROOT, "model"))
                        import abstract as abstract_mod
                        name = "%s.forml-abstract.md" % db
                        mpath = os.path.join(ROOT, "bench/models/%s.ccm.json" % db)
                        with open(os.path.join(d, name), "w") as fh:
                            fh.write(abstract_mod.summarise(json.load(open(mpath)), 2) + "\n")
                        continue
                    if w == "primer":
                        # the primer ships with the compiler now (`conquer.py --primer`), so
                        # an arm reads what a user reads. Each arm keeps its own copy in
                        # work/, which is the record of the text that run was actually given.
                        shutil.copy(os.path.join(ROOT, "conquer/primer.md"),
                                    os.path.join(d, "conquer-primer.md"))
                        continue
                    src = {"ddl": "%s.ddl.sql" % db, "schema": "%s.schema.txt" % db,
                           "forml": "%s.forml.md" % db, "forml_full": "%s.forml-full.md" % db,
                           "schema_sem": "%s.schema-sem.txt" % db,
                           "forml_sem": "%s.forml-sem.md" % db,
                           "schema_refs_declared": "%s.schema-refs-declared.txt" % db,
                           "schema_refs_rules": "%s.schema-refs-rules.txt" % db,
                           "schema_refs_judged": "%s.schema-refs-judged.txt" % db}[w]
                    shutil.copy(os.path.join(MAT, src), os.path.join(d, src))
            dbfile = os.path.join(DBS, db, db + ".sqlite")
            if spec.get("mcp"):
                # no `try`: the client is the only way in, and the server holds the model
                open(os.path.join(d, "mcp"), "w").write(MCP_CLIENT % (
                    db, spec["mcp"], db, os.path.join(ROOT, "mcp", "client.py"),
                    os.path.join(ROOT, "mcp", "server.py"),
                    os.path.join(HERE, "work", "mcp", "bird.json")))
                os.chmod(os.path.join(d, "mcp"), 0o755)
                for stale in ("try", "lookup"):
                    if os.path.exists(os.path.join(d, stale)):
                        os.remove(os.path.join(d, stale))
                if not os.path.exists(os.path.join(d, "answers.json")):
                    json.dump([], open(os.path.join(d, "answers.json"), "w"))
                made.append((arm, db, len(mine)))
                continue
            script = TRY_CQ if arm.startswith("conquer") else TRY_SQL
            if spec.get("log"):
                script = TRY_CQ_LOGGED
            env = 'DB="%s"\n' % dbfile
            if arm.startswith("conquer"):
                # `model` names the variant: "semantic", or any suffix models.py writes
                # (refs-declared, refs-rules, refs-judged). Absent, the base model.
                variant = spec.get("model")
                model = "bench/models/%s.%sccm.json" % (
                    db, (variant + ".") if variant else "")
                env += 'CQ="%s"\nMODEL="%s"\n' % (os.path.join(ROOT, "conquer/conquer.py"),
                                                   os.path.join(ROOT, model))
                if spec.get("log"):
                    env += 'LOG="%s"\n' % os.path.join(d, "attempts.jsonl")
            body = script.split("\n", 1)
            open(os.path.join(d, "try"), "w").write(body[0] + "\n" + env + body[1])
            os.chmod(os.path.join(d, "try"), 0o755)
            if spec.get("lookup"):
                lenv = env + 'ROOT="%s"\nLOOKUP="%s"\n' % (ROOT, os.path.join(HERE, "lookup.py"))
                lb = LOOKUP.split("\n", 1)
                open(os.path.join(d, "lookup"), "w").write(lb[0] + "\n" + lenv + lb[1])
                os.chmod(os.path.join(d, "lookup"), 0o755)
            if spec.get("draft") and not answered:
                shutil.copy(os.path.join(work, spec["draft"], db, "answers.json"),
                            os.path.join(d, "draft.json"))
            if spec.get("candidates") and not answered:
                cands = {}
                for i, a in enumerate(spec["candidates"], 1):
                    for x in json.load(open(os.path.join(work, a, db, "answers.json"))):
                        cands.setdefault(x["question_id"], []).append(
                            {"candidate": i, "answer": x.get("answer"), "note": x.get("note")})
                json.dump([{"question_id": q["question_id"], "candidates": cands.get(q["question_id"], [])}
                           for q in mine], open(os.path.join(d, "candidates.json"), "w"), indent=1)
            if not os.path.exists(os.path.join(d, "answers.json")):
                json.dump([], open(os.path.join(d, "answers.json"), "w"))
            made.append((arm, db, len(mine)))
    for arm in arms:
        n = sum(c for a, _, c in made if a == arm)
        kept = sum(1 for a, _ in left if a == arm)
        print("%-10s %2d batches, %3d questions%s"
              % (arm, sum(1 for a, _, _ in made if a == arm), n,
                 ", %d already answered (inputs left as they were)" % kept if kept else ""))


if __name__ == "__main__":
    main()
