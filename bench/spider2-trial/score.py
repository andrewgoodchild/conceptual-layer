#!/usr/bin/env python3
"""Score the large-schema arms with Spider 2.0's own grader.

Each answer is run against the shipped database and compared with the task's recorded result
sets using the benchmark's own `compare_pandas_table`, its own `condition_cols` and its own
`ignore_order` -- through `try.official_score`, so nothing here invents a grading rule.

Two numbers are printed, and the second is the honest one:

    scored          correct out of every question attempted
    on gold we trust  correct out of the questions whose gold is not known to be broken

`calibrate.py` finds that 9 of the 24 local tasks shipping gold SQL cannot reproduce their own
recorded answer. Those tasks cannot tell a right answer from a wrong one. They are excluded
from the second number and named, rather than quietly dropped.

    score.py [--arms A B] [-v]
"""

import argparse
import collections
import importlib.util
import json
import os
import sqlite3
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
warnings.filterwarnings("ignore")
_spec = importlib.util.spec_from_file_location("spider2_try", os.path.join(HERE, "try.py"))
_try = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_try)

WORK = os.path.join(HERE, "work")
# Reported by calibrate.py: the gold SQL does not reproduce the recorded answer, so the task
# cannot grade anything. local309 is the one that will not run at all.
BROKEN = {"local003", "local017", "local023", "local029", "local066",
          "local131", "local210", "local219", "local309"}
TIMEOUT = 120


def run(db, sql):
    path = _try.db_path(db) if hasattr(_try, "db_path") else None
    if path is None:
        from build import db_path
        path = db_path(db)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.set_progress_handler(_deadline(TIMEOUT), 100000)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        return rows, [d[0] for d in cur.description or []], None
    except Exception as e:                                          # noqa: BLE001
        return None, None, "%s: %s" % (type(e).__name__, str(e)[:80])
    finally:
        conn.close()


def _deadline(seconds):
    import time
    end = time.time() + seconds
    return lambda: 1 if time.time() > end else 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arms", nargs="*", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    sys.path.insert(0, HERE)

    arms = args.arms or sorted(a for a in os.listdir(WORK)
                               if os.path.isdir(os.path.join(WORK, a)))
    table, per_q = {}, collections.defaultdict(dict)
    for arm in arms:
        got = collections.Counter()
        for db in sorted(os.listdir(os.path.join(WORK, arm))):
            d = os.path.join(WORK, arm, db)
            answers = os.path.join(d, "answers.json")
            if not os.path.exists(answers):
                continue
            for a in json.load(open(answers)):
                iid, sql = a.get("instance_id"), (a.get("answer") or "").strip()
                if not iid:
                    continue
                got["asked"] += 1
                if not sql:
                    per_q[iid][arm] = "blank"
                    continue
                rows, cols, err = run(db, sql)
                if err:
                    got["failed"] += 1
                    per_q[iid][arm] = "error"
                    if args.verbose:
                        print("   %-10s %-12s %s" % (arm, iid, err))
                    continue
                score = _try.official_score(iid, rows, cols)
                per_q[iid][arm] = "ok" if score else "wrong"
                got["correct"] += bool(score)
        table[arm] = got

    trusted = [i for i in per_q if i not in BROKEN]
    print("%-10s %8s %8s %8s   %s" % ("arm", "asked", "correct", "ran", "on gold we trust"))
    print("-" * 62)
    for arm in arms:
        g = table[arm]
        good = sum(1 for i in trusted if per_q[i].get(arm) == "ok")
        print("%-10s %8d %8d %8d   %d of %d" % (
            arm, g["asked"], g["correct"], g["asked"] - g["failed"], good, len(trusted)))
    print("\n%d questions, %d excluded as ungradeable gold" % (len(per_q), len(per_q) - len(trusted)))
    if len(arms) > 1 and args.verbose:
        print("\nwhere the arms differ (trusted gold only):")
        for i in sorted(trusted):
            marks = {a: per_q[i].get(a) for a in arms}
            if len(set(marks.values())) > 1:
                print("   %-12s %s" % (i, "  ".join("%s=%s" % (a, marks[a]) for a in arms)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
