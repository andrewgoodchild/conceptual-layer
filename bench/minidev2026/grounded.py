#!/usr/bin/env python3
"""Was a right answer right for a reason, or because of what this data happens to hold?

"Beyond Correctness" (2610.02739) counts a success as grounded when the answer is right and the
question's ambiguities were actually resolved. BIRD has no ambiguity annotations and these
writers could ask nobody, so that metric cannot be computed here. This is a stand-in for the
part of it that can, and it is labelled as one: an answer EX called right must go on matching
the gold on thinned copies of the database, half the rows gone from each table and whatever
pointed at them by a declared foreign key. An answer that matched by coincidence tends to come
apart; one the gold agrees with for a reason does not. It reads only the results.json that
compare.py wrote, and adds `held` to each right answer there. A second opinion, never the score.

    grounded.py [SCRATCH_DIR] [2]        2 for the repeat of PLAN2.md
"""
import collections, json, os, shutil, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "bench/pilot"))
import score as pilot             # noqa: E402

REPEAT = sys.argv[2:] == ["2"]
QUESTIONS = os.path.join(ROOT, "bench/bird/mini_dev_1024/questions%s.json" % ("2" if REPEAT else ""))
SEEDS = (1, 2, 3)


def thin(source, path, seed):
    """A copy of `source` at `path` with about half of each table gone, consistently: a row
    whose declared parent was deleted goes too, so a join the data guarantees still holds."""
    shutil.copy(source, path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=OFF")
    c.execute("PRAGMA synchronous=OFF")
    c.create_function("keep", 1, lambda r: hash((seed, r)) % 2 == 0, deterministic=True)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                      "AND name NOT LIKE 'sqlite_%'")]
    keys = {t: c.execute('PRAGMA foreign_key_list("%s")' % t).fetchall() for t in tables}
    for t in tables:
        c.execute('DELETE FROM "%s" WHERE NOT keep(rowid)' % t)
    while True:
        gone = 0
        for t, fks in keys.items():
            for _, _, parent, col, to, *_ in fks:
                if to is None:
                    continue
                gone += c.execute(
                    'DELETE FROM "%s" WHERE "%s" IS NOT NULL AND "%s" NOT IN '
                    '(SELECT "%s" FROM "%s")' % (t, col, col, to, parent)).rowcount
        if not gone:
            break
    c.commit()
    c.close()


def statement(row, models, conn):
    if not row["arm"].startswith("conquer"):
        return row["answer"], ()
    db = row["db_id"]
    if db not in models:
        m = json.load(open(os.path.join(ROOT, "bench/models/%s.ccm.json" % db)))
        models[db] = (m, pilot.parser_mod.Lexicon(m), pilot.sql_mod.Emitter(m))
    m, lexicon, emitter = models[db]
    _, st, p = pilot.driver.transpile(m, row["answer"], lexicon, emitter)
    return st, p


def main():
    scratch = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "work", "thinned")
    os.makedirs(scratch, exist_ok=True)
    results = os.path.join(HERE, "results2.json" if REPEAT else "results.json")
    rows = json.load(open(results))
    gold = {q["question_id"]: q["SQL"] for q in json.load(open(QUESTIONS))}
    by_db, models = collections.defaultdict(list), {}
    for r in rows:
        if r["outcome"] == "ok":
            r["held"] = True
            by_db[r["db_id"]].append(r)
    for db in sorted(by_db):
        source = os.path.join(pilot.DBS, db, db + ".sqlite")
        for seed in SEEDS:
            path = os.path.join(scratch, "%s.%d.sqlite" % (db, seed))
            thin(source, path, seed)
            c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            c.text_factory = lambda b: b.decode("utf-8", "replace")
            wanted = {}
            for r in by_db[db]:
                q = r["question_id"]
                try:
                    wanted.setdefault(q, pilot.rows(c, gold[q]))
                    st, p = statement(r, models, c)
                    if not pilot.bird_ex(pilot.rows(c, st, p), wanted[q]):
                        r["held"] = False
                except sqlite3.Error:
                    r["held"] = False
            c.close()
            os.remove(path)
        print(db, flush=True)
    with open(results, "w") as fh:
        json.dump(rows, fh, indent=1)
    arms = sorted({r["arm"] for r in rows})
    for arm in arms:
        right = [r for r in rows if r["arm"] == arm and r["outcome"] == "ok"]
        print("%-11s right %3d  held on thinned data %3d" % (
            arm, len(right), sum(1 for r in right if r["held"])))


if __name__ == "__main__":
    main()
