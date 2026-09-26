#!/usr/bin/env python3
"""Score answers against LiveSQLBench-Base-Lite-SQLite's ground truth.

The tier that needs no server: 18 databases shipped as `.sqlite` files, 180 SELECT tasks,
solution SQL rewritten for SQLite, ground truth by email. Execution accuracy as BIRD defines
it -- the answer is right when its result set equals the gold's.

**Through the system's sqlite3 binary, not Python's.** Python 3.10 bundles SQLite 3.35.5,
which predates the JSON operators (3.38) and right joins (3.39); 41 of the 180 golds use one
or the other and cannot run through it at all (finding 142). Both sides go through the same
binary so a difference is never the engine.

Execution accuracy alone says nothing about *how* a system fails, and the difference
between a wrong answer and a declined one is the whole question this project is about. So
the report also carries the selective-prediction metrics the abstention literature uses
(Chen et al., SIGMOD 2025, for text-to-SQL; Wen et al., TACL 2025, for the framing):

    coverage            the share of questions answered rather than declined
    selective accuracy  accuracy over the answered ones -- what a caller actually gets
    silent errors       wrong answers delivered with no signal. The quantity abstention
                        exists to reduce, and the one a bare accuracy figure hides.

TAR and FAR -- a true abstention avoids a wrong answer, a false one discards a right
answer -- need to know what the system *would* have said. RTS has that, because it
suppresses its own model's prediction; a compiler refusal suppresses nothing, so there is
no counterfactual inside a single arm. `--against DIR` supplies one: a reference arm whose
answer to the same question stands in for what this arm would have produced had it not
declined. Without it the two rates are reported as not computable rather than as zero.

    score_sqlite.py --arm DIR [--against DIR] [--db NAME] [-v]

`DIR` holds one `<database>/answers.json` per database, the same shape the pilot writes.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DBS = os.path.join(DATA, "sqlite_tier")
SQLITE = os.environ.get("SQLITE3", "/usr/local/opt/sqlite/bin/sqlite3")
TIMEOUT = 120


def rows(db, sql):
    """The gold's or a candidate's result set, as a sorted multiset of row tuples."""
    path = os.path.join(DBS, "%s_template.sqlite" % db)
    try:
        r = subprocess.run([SQLITE, "-readonly", "-separator", "\x1f", path, sql],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "timeout"
    if r.returncode != 0:
        return "sqlite: %s" % r.stderr.strip().split("\n")[0][:80]
    return sorted(line.split("\x1f") for line in r.stdout.splitlines())


def candidate_sql(answer, model, as_sql):
    """The SQL an answer stands for, or the reason the compiler declined it.

    Returns `(sql, None)` or `(None, reason)`. Pulled out of the scoring loop so a
    reference arm -- the counterfactual TAR and FAR are measured against -- goes through
    exactly the same path as the arm under test.
    """
    if as_sql:
        return answer, None
    import conquer as driver
    try:
        _, sql, params = driver.transpile(model, answer)
    except Exception as e:                                                # noqa: BLE001
        return None, "refused: %s" % str(e)[:60]
    for v in params:                          # the CLI takes no parameters
        sql = sql.replace("?", repr(v) if isinstance(v, str) else str(v), 1)
    return sql, None


def load_arm(arm, model_dir, as_sql, only_db=None):
    """Every answer in an arm, as `{question_id: (database, answer_text)}`."""
    out = {}
    if not arm:
        return out
    for db in sorted(os.listdir(arm)):
        if only_db and db != only_db:
            continue
        path = os.path.join(arm, db, "answers.json")
        if os.path.exists(path):
            for a in json.load(open(path)):
                out[a["question_id"]] = (db, a.get("answer"))
    return out


def gold_sql(entry):
    s = entry.get("sol_sql")
    if isinstance(s, list):
        s = s[0] if s else None
    return s


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arm", required=True, help="directory of <database>/answers.json")
    p.add_argument("--against", help="a reference arm: what this arm would have answered "
                                     "had it not abstained, so TAR and FAR are computable")
    p.add_argument("--db")
    p.add_argument("--sql", action="store_true", help="answers are SQL, not ConQuer")
    p.add_argument("--model-dir", default=os.path.join(HERE, "work", "models-sqlite-tier"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    gt = {r["instance_id"]: r for r in
          (json.loads(l) for l in open(os.path.join(DATA,
                                                    "livesqlbench_base_lite_sqlite_gt.jsonl")))}
    qs = {q["instance_id"]: q for q in
          (json.loads(l) for l in open(os.path.join(DATA, "livesqlbench_data_sqlite.jsonl")))}

    if not args.sql:
        sys.path.insert(0, os.path.join(HERE, "..", "..", "conquer"))
    # `refused` is the compiler declining -- an abstention. `failed` is a query that
    # compiled, ran, and broke at the database. Lumping them hid the distinction the
    # abstention metrics below are entirely about.
    counts = {"ok": 0, "wrong": 0, "refused": 0, "failed": 0, "not_answered": 0,
              "no_gold": 0}
    misses, abstained = [], []
    for db in sorted(os.listdir(args.arm)):
        if args.db and db != args.db:
            continue
        path = os.path.join(args.arm, db, "answers.json")
        if not os.path.exists(path):
            continue
        model = None
        if not args.sql:
            mp = os.path.join(args.model_dir, "%s.ccm.json" % db)
            if os.path.exists(mp):
                model = json.load(open(mp))
        for a in json.load(open(path)):
            q = qs.get(a["question_id"])
            entry = gt.get(a["question_id"])
            if not q or not entry or not gold_sql(entry):
                counts["no_gold"] += 1
                continue
            if not a.get("answer"):
                counts["not_answered"] += 1
                abstained.append(a["question_id"])
                continue
            sql, refusal = candidate_sql(a["answer"], model, args.sql)
            if refusal:
                counts["refused"] += 1
                abstained.append(a["question_id"])
                misses.append((db, a["question_id"], refusal))
                continue
            got, want = rows(db, sql), rows(db, gold_sql(entry))
            if isinstance(got, str) or isinstance(want, str):
                counts["failed"] += 1
                misses.append((db, a["question_id"], str(got if isinstance(got, str) else want)))
            elif got == want:
                counts["ok"] += 1
            else:
                counts["wrong"] += 1
                misses.append((db, a["question_id"], "%d rows, gold %d" % (len(got), len(want))))
    n = sum(counts.values()) - counts["no_gold"]
    print("%-12s %s" % (os.path.basename(args.arm.rstrip("/")), counts))
    if n:
        print("execution accuracy: %d of %d = %.0f%%" % (counts["ok"], n, 100.0 * counts["ok"] / n))
        report_abstention(args, counts, n, abstained, gt, qs)
    if args.verbose:
        # every miss, not the first thirty: the list is what a comparison against another
        # scorer reads, and a cap hid two thirds of it
        for m in misses:
            print("   %-16s %-28s %s" % m)
    return 0


def report_abstention(args, counts, n, abstained, gt, qs):
    """Coverage, selective accuracy, silent errors -- and TAR/FAR where measurable.

    A system that answers everything has no abstention to report and a coverage of 1, and
    that is worth printing rather than omitting: at full coverage every wrong answer is a
    silent one, which is the failure mode the whole literature exists to avoid. A high
    execution accuracy and a high silent-error count are the same number said twice.
    """
    answered = counts["ok"] + counts["wrong"] + counts["failed"]
    declined = counts["refused"] + counts["not_answered"]
    print("abstention")
    print("  coverage           %4d of %d = %5.1f%%   answered rather than declined"
          % (answered, n, 100.0 * answered / n))
    if answered:
        print("  selective accuracy %4d of %d = %5.1f%%   accuracy where it did not decline"
              % (counts["ok"], answered, 100.0 * counts["ok"] / answered))
    print("  declined           %4d              %d refused by the compiler, %d never answered"
          % (declined, counts["refused"], counts["not_answered"]))
    silent = counts["wrong"]
    print("  silent errors      %4d of %d = %5.1f%%   wrong answers carrying no signal"
          % (silent, n, 100.0 * silent / n))

    if not args.against:
        if declined:
            print("  TAR / FAR          not computable: a refusal suppresses no answer, so "
                  "there is nothing\n                     to score the abstention against. "
                  "Pass --against DIR.")
        return

    # A reference arm stands in for what this arm would have answered had it not declined.
    # The abstention was *true* if that answer is wrong (it avoided an error) and *false*
    # if it is right (it threw away a correct answer).
    ref = load_arm(args.against, args.model_dir, args.sql, args.db)
    true_a = false_a = unknown = 0
    for qid in abstained:
        db, answer = ref.get(qid, (None, None))
        if not answer:
            unknown += 1
            continue
        model = None
        if not args.sql:
            mp = os.path.join(args.model_dir, "%s.ccm.json" % db)
            if os.path.exists(mp):
                model = json.load(open(mp))
        sql, refusal = candidate_sql(answer, model, args.sql)
        if refusal:
            true_a += 1                 # the reference cannot answer it either
            continue
        got, want = rows(db, sql), rows(db, gold_sql(gt[qid]))
        if isinstance(got, str) or isinstance(want, str) or got != want:
            true_a += 1
        else:
            false_a += 1
    print("  TAR                %4d of %d = %5.1f%%   declining avoided a wrong answer"
          % (true_a, n, 100.0 * true_a / n))
    print("  FAR                %4d of %d = %5.1f%%   declining threw away a right one"
          % (false_a, n, 100.0 * false_a / n))
    if unknown:
        print("  unscored           %4d              the reference arm answers neither"
              % unknown)


if __name__ == "__main__":
    sys.exit(main())
