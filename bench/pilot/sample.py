#!/usr/bin/env python3
"""Rebuild `questions.json`, the pilot's sample, from the BIRD mini-dev download.

The sample is one hundred of BIRD mini-dev's five hundred questions, drawn once and never
changed; every results file in this directory scores exactly these. The file itself is a
verbatim subset of BIRD's own records -- question, evidence, gold SQL, difficulty -- so it is
not distributed with this repository: the questions are BIRD's. What is this project's is
the draw, and that is the list below, in the order it was made.

    bench/fetch.sh                    # gets bench/bird/mini_dev_sqlite.json
    python3 bench/pilot/sample.py     # writes bench/pilot/questions.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIRD = os.path.join(HERE, "..", "bird", "mini_dev_sqlite.json")
OUT = os.path.join(HERE, "questions.json")

# BIRD mini-dev question_ids, in the sample's order. Each results-*.json scores these hundred.
SAMPLE = [422, 346, 739, 1115, 473, 424, 1256, 930, 1189, 344, 785, 37, 1011, 604, 1134, 137,
          1135, 909, 584, 794, 1124, 1107, 892, 796, 788, 854, 537, 737, 1267, 1435, 1506, 898,
          1157, 1094, 1110, 877, 1505, 201, 824, 704, 906, 173, 765, 1162, 988, 1378, 377, 665,
          1130, 352, 1164, 46, 775, 239, 82, 243, 1481, 234, 28, 24, 215, 518, 1427, 92, 672,
          881, 189, 1380, 701, 1486, 753, 128, 1525, 977, 1179, 567, 915, 230, 1501, 539, 1192,
          416, 89, 1232, 79, 349, 1404, 1361, 1187, 1375, 1405, 462, 1464, 563, 1116, 1044, 206,
          868, 212, 1312]
KEEP = ("question_id", "db_id", "question", "evidence", "SQL", "difficulty")


def main(argv=None):
    if not os.path.exists(BIRD):
        print("no %s: run bench/fetch.sh first" % os.path.relpath(BIRD))
        return 1
    by_id = {q["question_id"]: q for q in json.load(open(BIRD))}
    missing = [i for i in SAMPLE if i not in by_id]
    if missing:
        print("BIRD mini-dev has no question %s" % missing)
        return 1
    with open(OUT, "w") as fh:
        json.dump([{k: by_id[i][k] for k in KEEP} for i in SAMPLE], fh, indent=1)
    print("wrote %s: %d questions over %d databases"
          % (os.path.relpath(OUT), len(SAMPLE), len({by_id[i]["db_id"] for i in SAMPLE})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
