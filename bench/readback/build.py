#!/usr/bin/env python3
"""Does the English read-back help a checker catch a wrong query (PLAN.md)?

    build.py pool      every distinct ConQuer answer the pilot's base-model arms wrote,
                       rescored now on BIRD by strict EX: data/pool.json
    build.py sample    per question that has both a right and a wrong answer, up to WRONG
                       wrong ones and RIGHT right ones, seeded: data/key.json
    build.py work      one directory per (arm, database): the items, the schema listing,
                       the primer, and for `readback` each query's reading in English

`data/` holds BIRD's questions and the labels, and is not distributed. A directory whose
checks.json is not empty is left alone: its inputs are the record of what its checker saw.
"""
import collections, json, os, random, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "bench/pilot"))
import score as pilot             # noqa: E402

DATA = os.path.join(HERE, "data")
WORK = os.path.join(HERE, "work")
QUESTIONS = os.path.join(ROOT, "bench/pilot/questions.json")
MATERIAL = os.path.join(ROOT, "bench/pilot/material")
ARMS = ("plain", "readback")
WRONG, RIGHT, SEED = 3, 2, 20261108


def base_arm(arm):
    """The ConQuer arms that queried the base model: not the semantic layer, not the three
    reference variants, whose read-back would need their own model."""
    return arm.startswith("conquer") and arm not in pilot.SEMANTIC and arm not in pilot.VARIANT


def model(db, cache={}):
    if db not in cache:
        m = json.load(open(os.path.join(ROOT, "bench/models/%s.ccm.json" % db)))
        cache[db] = (m, pilot.parser_mod.Lexicon(m), pilot.sql_mod.Emitter(m))
    return cache[db]


def pool():
    qs = {q["question_id"]: q for q in json.load(open(QUESTIONS))}
    seen, out, conns, gold = set(), [], {}, {}
    for r in json.load(open(os.path.join(ROOT, "bench/pilot/results.json"))):
        if not base_arm(r["arm"]) or not r.get("answer"):
            continue
        key = (r["question_id"], r["answer"])
        if key in seen:
            continue
        seen.add(key)
        q, db = qs[r["question_id"]], r["db_id"]
        c = conns.get(db)
        if c is None:
            c = conns[db] = sqlite3.connect(
                "file:%s?mode=ro" % os.path.join(pilot.DBS, db, db + ".sqlite"), uri=True)
            c.text_factory = lambda b: b.decode("utf-8", "replace")
        m, lexicon, emitter = model(db)
        row = {"question_id": q["question_id"], "db_id": db, "answer": r["answer"]}
        try:
            _, st, p = pilot.driver.transpile(m, r["answer"], lexicon, emitter)
            got = pilot.rows(c, st, p)
        except (pilot.parser_mod.ParseError, pilot.parser_mod.Ambiguous, pilot.sql_mod.SqlError,
                sqlite3.Error) as e:
            row["outcome"], row["error"] = "failed_loudly", str(e)
            out.append(row)
            continue
        if q["question_id"] not in gold:
            try:
                gold[q["question_id"]] = pilot.rows(c, q["SQL"])
            except sqlite3.Error as e:                 # a gold past the deadline
                gold[q["question_id"]] = None
                print("gold failed: %s: %s" % (q["question_id"], e))
        want = gold[q["question_id"]]
        if want is None:
            row["outcome"] = "gold_error"
            out.append(row)
            continue
        row["outcome"] = "ok" if pilot.bird_ex(got, want) else "wrong_quietly"
        row["relaxed"] = pilot.relaxed_ex(got, want, distinct=True)
        out.append(row)
    os.makedirs(DATA, exist_ok=True)
    json.dump(out, open(os.path.join(DATA, "pool.json"), "w"), indent=1)
    print(collections.Counter(r["outcome"] for r in out))


def sample():
    """A wrong answer that a declared forgiveness accepts (rounding, row order, an extra
    column) is left out: what it gets wrong is the scorer's to say, not a reader's."""
    by_q = collections.defaultdict(lambda: {"ok": [], "wrong": []})
    for r in json.load(open(os.path.join(DATA, "pool.json"))):
        if r["outcome"] == "ok":
            by_q[r["question_id"]]["ok"].append(r)
        elif r["outcome"] == "wrong_quietly" and r["relaxed"] is None:
            by_q[r["question_id"]]["wrong"].append(r)
    rng, items = random.Random(SEED), []
    for qid in sorted(by_q):
        got = by_q[qid]
        if not got["ok"] or not got["wrong"]:
            continue
        for label, n in (("wrong", WRONG), ("ok", RIGHT)):
            pick = sorted(got[label], key=lambda r: r["answer"])
            rng.shuffle(pick)
            items += [dict(r, label=label) for r in pick[:n]]
    for db in sorted({r["db_id"] for r in items}):
        mine = [r for r in items if r["db_id"] == db]
        rng.shuffle(mine)
        for i, r in enumerate(mine, 1):
            r["item"] = "%s-%02d" % (db[:3], i)
    items.sort(key=lambda r: r["item"])
    json.dump(items, open(os.path.join(DATA, "key.json"), "w"), indent=1)
    print("%d items: %d wrong, %d right, %d questions, %d databases" % (
        len(items), sum(r["label"] == "wrong" for r in items),
        sum(r["label"] == "ok" for r in items), len({r["question_id"] for r in items}),
        len({r["db_id"] for r in items})))


README = """# Checking queries against their questions

These are queries other people wrote against the `{db}` database in ConQuer, a conceptual
query language. `conquer-primer.md` explains the language and `{db}.schema.txt` lists every
type and reading in the database's model.

`items.json` holds {n} items. Each has a question, the evidence that came with it (a hint the
writer was given), and the query someone wrote to answer it.{readback} Some of the queries
answer their question and some return the wrong rows. How many of each is not said, and it
is not the same in every database.

For each item, decide whether the query, run against the database, would return what the
question asks for: the right rows and the right columns, nothing missing and nothing extra.
You cannot run the queries; read them. Judge what a query returns, not how it is written: a
clumsy query that returns the right answer is right.

Write `checks.json`, a list with one entry per item:

    {{"item": "...", "verdict": "right" or "wrong", "reason": "one sentence"}}

Every item gets a verdict. Work only in this directory: read no other file in the repository
or on the machine, and do not look the questions up. When you finish, say in one line
whether you read anything outside this directory.
"""
READBACK = """ Each also has `readback`: the compiler's reading of that query in
English, with what it assumes and what it risks. A program wrote it from the query; the
query's author did not. It says what the query does, not whether that is what the question
wants."""


def work():
    qs = {q["question_id"]: q for q in json.load(open(QUESTIONS))}
    items = json.load(open(os.path.join(DATA, "key.json")))
    primer = open(os.path.join(ROOT, "conquer/primer.md")).read()
    for db in sorted({r["db_id"] for r in items}):
        mine = [r for r in items if r["db_id"] == db]
        m, lexicon, _ = model(db)
        for arm in ARMS:
            d = os.path.join(WORK, arm, db)
            checks = os.path.join(d, "checks.json")
            if os.path.exists(checks) and json.load(open(checks)):
                print("left alone: %s/%s" % (arm, db))
                continue
            os.makedirs(d, exist_ok=True)
            shown = []
            for r in mine:
                q = qs[r["question_id"]]
                x = {"item": r["item"], "question": q["question"], "evidence": q["evidence"],
                     "query": r["answer"]}
                if arm == "readback":
                    x["readback"] = pilot.driver.interpret(m, r["answer"], lexicon)[0]
                shown.append(x)
            json.dump(shown, open(os.path.join(d, "items.json"), "w"), indent=1)
            with open(os.path.join(d, "conquer-primer.md"), "w") as fh:
                fh.write(primer)
            with open(os.path.join(d, db + ".schema.txt"), "w") as fh:
                fh.write(open(os.path.join(MATERIAL, db + ".schema.txt")).read())
            with open(os.path.join(d, "README.md"), "w") as fh:
                fh.write(README.format(db=db, n=len(mine),
                                       readback=READBACK if arm == "readback" else ""))
            json.dump([], open(checks, "w"))
    print("%d arms, %d items" % (len(ARMS), len(items)))


if __name__ == "__main__":
    {"pool": pool, "sample": sample, "work": work}[sys.argv[1]]()
