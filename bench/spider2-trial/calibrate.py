#!/usr/bin/env python3
"""How often does Spider 2.0's own gold SQL reproduce Spider 2.0's own recorded answer?

Before scoring anything against a benchmark it is worth asking what the benchmark scores
itself. This runs each shipped gold query against the shipped database and grades the result
with the shipped evaluator, using each task's own `condition_cols` and `ignore_order`. A task
whose gold query cannot reproduce its gold answer cannot tell a right answer from a wrong one,
and a score that includes it is measuring the annotation, not the system.

Only the 24 local tasks that ship their SQL can be asked; the other 111 ship an answer and no
query, so nothing can check them. Jin et al. (CIDR'26) put the annotation error rate for
Spider2.0-Snow at 66%; this is the same question asked of the slice that runs offline.

    calibrate.py [-v]
"""

import json
import os
import sqlite3
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
warnings.filterwarnings("ignore")

import importlib.util                                                    # noqa: E402
_spec = importlib.util.spec_from_file_location("spider2_try", os.path.join(HERE, "try.py"))
_try = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_try)
GOLD, LITE, DBS, DB_FILE = _try.GOLD, _try.LITE, _try.DBS, _try.DB_FILE
official_score = _try.official_score


def main(argv=None):
    verbose = "-v" in (argv or sys.argv[1:])
    if not os.path.exists(os.path.join(LITE, "spider2-lite.jsonl")):
        print("no Spider 2.0 clone at %s: bench/spider2-trial/README.md says how to get one"
              % os.path.relpath(LITE))
        return 2
    tasks = {json.loads(l)["instance_id"]: json.loads(l)
             for l in open(os.path.join(LITE, "spider2-lite.jsonl"))}
    ok = bad = skip = 0
    for f in sorted(os.listdir(os.path.join(GOLD, "sql"))):
        iid = f[:-4]
        t = tasks.get(iid)
        if t is None or not iid.startswith("local"):
            continue
        db = DB_FILE.get(t["db"], t["db"])
        path = os.path.join(DBS, db + ".sqlite")
        if not os.path.exists(path):
            skip += 1
            continue
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            conn.text_factory = lambda b: b.decode("utf-8", "replace")
            cur = conn.execute(open(os.path.join(GOLD, "sql", f)).read())
            rows, cols = cur.fetchall(), [d[0] for d in cur.description]
        except sqlite3.Error as e:
            skip += 1
            print("   %-10s the gold query will not run here: %s" % (iid, str(e)[:50]))
            continue
        score = official_score(iid, rows, cols)
        ok += 1 if score else 0
        bad += 0 if score else 1
        if not score:
            print("   %-10s scores 0 against its own recorded answer (%d rows)"
                  % (iid, len(rows)))
        elif verbose:
            print("   %-10s ok" % iid)
    print("\nof %d local tasks that ship their gold SQL, it reproduces the shipped answer "
          "for %d and fails for %d (%d could not be run)" % (ok + bad + skip, ok, bad, skip))
    return 0


if __name__ == "__main__":
    sys.exit(main())
