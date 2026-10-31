#!/usr/bin/env python3
"""Draw this round's hundred questions from the October 2026 mini-dev, and record the pins.

The draw is proportional to each database's share of the 500 (largest remainder), then
uniform within a database, from a fixed seed. `questions.json` is BIRD's text, gold included,
so it stays under the git-ignored bench/bird/; `pins.json` is this project's: the ids drawn
and the checksums of everything a writer's answer depends on.
"""
import collections, hashlib, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BIRD = os.path.join(ROOT, "bench/bird")
SOURCE = os.path.join(BIRD, "mini_dev_1024/mini_dev_sqlite.jsonl")
OUT = os.path.join(BIRD, "mini_dev_1024/questions.json")
DBS = os.path.join(BIRD, "minidev/MINIDEV/dev_databases")
SEED, SIZE = 20261031, 100
KEEP = ("question_id", "db_id", "question", "evidence", "SQL", "difficulty")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def draw(rows):
    by_db = collections.defaultdict(list)
    for r in rows:
        by_db[r["db_id"]].append(r["question_id"])
    shares = {db: len(ids) * SIZE / len(rows) for db, ids in by_db.items()}
    counts = {db: int(s) for db, s in shares.items()}
    spare = SIZE - sum(counts.values())
    for db in sorted(shares, key=lambda d: (counts[d] - shares[d], d))[:spare]:
        counts[db] += 1
    rng = random.Random(SEED)
    return {db: sorted(rng.sample(sorted(by_db[db]), counts[db])) for db in sorted(by_db)}


def main():
    rows = [json.loads(line) for line in open(SOURCE)]
    drawn = draw(rows)
    ids = {i for chosen in drawn.values() for i in chosen}
    chosen = [r for r in rows if r["question_id"] in ids]
    with open(OUT, "w") as fh:
        json.dump([{k: r[k] for k in KEEP} for r in chosen], fh, indent=1)
    pins = {"seed": SEED, "drawn": drawn, "source_sha256": sha(SOURCE),
            "databases_sha256": {db: sha(os.path.join(DBS, db, db + ".sqlite")) for db in drawn},
            "models_sha256": {db: sha(os.path.join(ROOT, "bench/models/%s.ccm.json" % db))
                              for db in drawn}}
    with open(os.path.join(HERE, "pins.json"), "w") as fh:
        json.dump(pins, fh, indent=1)
    print("%d questions, %d with no evidence, %s" % (
        len(chosen), sum(1 for r in chosen if not r["evidence"]),
        dict(collections.Counter(r["difficulty"] for r in chosen))))
    print({db: len(c) for db, c in drawn.items()})


if __name__ == "__main__":
    main()
