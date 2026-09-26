#!/usr/bin/env python3
"""Rebuild each modeller's `definitions.json` from the pilot's sample.

A modeller for the semantic-layer round was given one database and the list of definitions
its questions lean on: every piece of BIRD's `evidence` for the sampled questions on that
database, split at the semicolons, in the order first met, without duplicates. That list is
BIRD's text, so it is not distributed; this regenerates it byte for byte from
`questions.json`, which `sample.py` rebuilds from the download.

    python3 bench/pilot/sample.py                  # writes bench/pilot/questions.json
    python3 bench/pilot/semantic/definitions.py    # writes work/semantic/<db>/definitions.json
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "..", "questions.json")
WORK = os.path.join(HERE, "..", "work", "semantic")


def definitions(questions, db):
    seen = []
    for q in questions:
        if q["db_id"] != db:
            continue
        for piece in re.split(r";\s*", q.get("evidence") or ""):
            piece = piece.strip()
            if piece and piece not in seen:
                seen.append(piece)
    return seen


def main():
    if not os.path.exists(QUESTIONS):
        print("no %s: run bench/pilot/sample.py first" % os.path.relpath(QUESTIONS))
        return 2
    with open(QUESTIONS) as fh:
        questions = json.load(fh)
    for db in sorted({q["db_id"] for q in questions}):
        out = os.path.join(WORK, db, "definitions.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as fh:
            json.dump(definitions(questions, db), fh, indent=1, ensure_ascii=False)
        print("wrote %s" % os.path.relpath(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
