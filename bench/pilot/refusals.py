#!/usr/bin/env python3
"""What did the compiler's refusals buy? Replay each one under `--permissive`.

Finding 57. The claim that a conceptual query language earns its keep by *refusing* what is
well formed and meaningless has been architectural: the compiler refuses, and the author is
supposed to correct rather than ship a silent wrong answer. The recorded answers cannot test
it, because they are what survived the refusals.

So the `conquer_logged` arm keeps every query tried, and this replays them:

    for each attempt the compiler refused
        recompile it with --permissive -- the judgements become notes, the SQL is emitted
        run that SQL and compare it with the gold
            different rows   the refusal prevented a wrong answer   (the benefit)
            the same rows    the refusal cost the author a detour   (the cost)
            no SQL at all    a parse failure, not a judgement       (not in scope)

Every refusal is a data point, which is why this needs no second arm and has no power
problem. The recovery question -- did the author get there in the end -- is the final answer
for the same question, which `score.py` already grades.

    refusals.py [--arm conquer_logged] [-v]
"""

import argparse
import collections
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
DBS = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")
MODELS = os.path.join(ROOT, "bench/models")
TIMEOUT = 30

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402

REFUSALS = (parser_mod.ParseError, parser_mod.Ambiguous, sql_mod.SqlError)

# The judgements, by a phrase of their message. Everything else that refuses is a parse or a
# mapping failure -- there is no SQL behind it, so there is nothing to compare.
JUDGEMENTS = [
    ("the fan trap", "computed over rows this query multiplies"),
    ("a value equated with an instance", "cannot be the same thing"),
    ("a node joined to nothing", "joined to nothing"),
    ("a verb walked off a computed value", "was given a computed value"),
    ("a computed value out of scope", "not in scope where it is used"),
]


# Everything else that refuses. Not judgements -- there is no SQL behind them -- but worth
# separating, because "the compiler said no" is only useful feedback if it said something the
# author could act on, and these are what it actually says.
OTHERS = [
    ("a name that is not in the schema", "neither a type in this schema"),
    ("a verb the head cannot follow", "no fact type reads"),
    ("an ambiguous verb", "ambiguous between"),
    ("unconsumed input", "unconsumed input"),
    ("a role the head cannot play", "is not a role"),
    ("a listed name the query never reaches", "is not reached by this query"),
    ("a sort key the query does not have", "cannot sort by"),
    ("a construct the report defines but this does not build", "does not compile"),
    ("no fact type connects these", "no fact type connects"),
    ("a denotation against a surrogate", "has no preferred identifier"),
]


def classify(message):
    for name, needle in JUDGEMENTS:
        if needle in message:
            return name
    return None


def classify_other(message):
    for name, needle in OTHERS:
        if needle in message:
            return name
    return "other: " + message.split(".")[0][:52]


def rows_of(conn, statement, params):
    end = time.time() + TIMEOUT
    conn.set_progress_handler(lambda: 1 if time.time() > end else 0, 20000)
    try:
        return set(conn.execute(statement, params).fetchall())
    except sqlite3.Error as e:
        return "sqlite: %s" % e
    finally:
        conn.set_progress_handler(None, 0)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arm", default="conquer_logged")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    gold = {q["question_id"]: q for q in json.load(open(os.path.join(HERE, "questions.json")))}
    work = os.path.join(HERE, "work", args.arm)
    if not os.path.isdir(work):
        print("no such arm: %s" % args.arm)
        return 2

    tally = collections.Counter()
    kinds = collections.Counter()
    others = collections.Counter()
    recovered = {}
    cases = []
    for db in sorted(os.listdir(work)):
        log = os.path.join(work, db, "attempts.jsonl")
        if not os.path.exists(log):
            continue
        model = json.load(open(os.path.join(MODELS, "%s.ccm.json" % db)))
        lex, em = parser_mod.Lexicon(model), sql_mod.Emitter(model)
        conn = sqlite3.connect("file:%s?mode=ro" % os.path.join(DBS, db, db + ".sqlite"), uri=True)
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        # Attribute each attempt to a question by looking *forward* to the next attempt the
        # author kept: the log is in order and every final answer appears in it, so a run of
        # drafts belongs to the question the run ends on. Attempts after the last kept answer
        # belong to nothing and are counted apart rather than guessed at.
        answers = json.load(open(os.path.join(work, db, "answers.json")))
        final = {(a.get("answer") or "").strip(): a["question_id"] for a in answers if a.get("answer")}
        log_lines = []
        for line in open(log):
            try:
                log_lines.append(json.loads(line)["query"].strip())
            except (ValueError, KeyError):
                pass
        belongs, current = {}, None
        for i in range(len(log_lines) - 1, -1, -1):
            if log_lines[i] in final:
                current = final[log_lines[i]]
            belongs[i] = current

        seen = set()
        for i, text in enumerate(log_lines):
            if not text or (db, text) in seen:
                continue
            seen.add((db, text))
            tally["attempts"] += 1
            try:
                driver.transpile(model, text, lex, em)
                tally["compiled"] += 1
                continue
            except REFUSALS as e:
                message = str(e)
            tally["refused"] += 1
            qid_here = belongs.get(i)
            if qid_here is not None and qid_here not in recovered:
                kept = next((a.get("answer") for a in answers
                             if a["question_id"] == qid_here), None)
                recovered[qid_here] = _answer_is_right(conn, model, lex, em, kept,
                                                       gold, qid_here)
            kind = classify(message)
            if kind is None:
                others[classify_other(message)] += 1
                continue
            kinds[kind] += 1
            tally["judgement"] += 1
            # the counterfactual: what the author would have got
            try:
                _, statement, params = driver.transpile(model, text, permissive=True)
            except Exception as e:                                    # noqa: BLE001
                tally["judgement, still would not compile"] += 1
                continue
            got = rows_of(conn, statement, params)
            if isinstance(got, str):
                tally["judgement, the SQL would not run"] += 1
                continue
            qid = belongs.get(i)
            want = _gold_rows(conn, gold, qid) if qid else None
            if want is None:
                tally["judgement, no gold to compare"] += 1
                verdict = "unknown"
            elif isinstance(want, str):
                tally["judgement, gold would not run"] += 1
                verdict = "unknown"
            else:
                verdict = "would have been right" if got == want else "would have been WRONG"
                tally[verdict] += 1
            cases.append((db, qid, kind, verdict, text[:88], message.split(".")[0][:88]))
        conn.close()

    print("%-52s %s" % ("attempts logged", tally["attempts"]))
    print("%-52s %s" % ("  compiled", tally["compiled"]))
    print("%-52s %s" % ("  refused", tally["refused"]))
    print("%-52s %s" % ("    of those, a judgement the compiler made", tally["judgement"]))
    print()
    print("judgements -- what a permissive compiler would have let through:")
    for k, v in kinds.most_common():
        print("   %-50s %d" % (k, v))
    if not kinds:
        print("   none")
    print()
    print("everything else it refused (no SQL behind these, so nothing to replay):")
    for k, v in others.most_common():
        print("   %-50s %d" % (k, v))
    if not others:
        print("   none")
    print()
    print("the counterfactual, for each judgement replayed under --permissive:")
    for k in ("would have been WRONG", "would have been right",
              "judgement, still would not compile", "judgement, the SQL would not run",
              "judgement, no gold to compare", "judgement, gold would not run"):
        if tally[k]:
            print("   %-50s %d" % (k, tally[k]))
    hit = [q for q in recovered if recovered[q]]
    if recovered:
        print()
        print("did the author recover? for each question whose drafting was refused at least "
              "once,\nwhether the answer finally kept is right:")
        print("   %-50s %d of %d" % ("recovered", len(hit), len(recovered)))
    if args.verbose:
        print()
        for db, qid, kind, verdict, text, why in cases:
            print("  %-22s q%-5s %-32s %s\n      %s\n      %s"
                  % (db, qid, kind, verdict, text, why))
    return 0


def _answer_is_right(conn, model, lex, em, answer, gold, qid):
    """Did the query the author finally kept give the gold's rows? BIRD's own comparison."""
    if not answer:
        return False
    try:
        _, statement, params = driver.transpile(model, answer, lex, em)
    except Exception:                                                 # noqa: BLE001
        return False
    got = rows_of(conn, statement, params)
    want = _gold_rows(conn, gold, qid)
    return not isinstance(got, str) and not isinstance(want, str) and got == want


def _gold_rows(conn, gold, qid):
    q = gold.get(qid)
    if q is None:
        return None
    return rows_of(conn, q["SQL"], [])


if __name__ == "__main__":
    sys.exit(main())
