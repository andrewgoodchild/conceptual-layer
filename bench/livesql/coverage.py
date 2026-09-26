#!/usr/bin/env python3
"""What share of LiveSQLBench could this compiler attempt at all?

Two hard limits are structural and need no reading: the compiler emits SELECT, so the
Management tasks are out; and it has no JSON support, so a question whose answer must reach
into a `jsonb` column is out.

The rest is a text probe over `normal_query`, and it is a *crude* one -- the gold is withheld,
so the only evidence is how the question is worded. Counts here are signals for sizing, not
measurements, and are labelled as such. The honest version of this file needs the gold, and
that is one email away.

    coverage.py [-v]
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# Wordings that signal a construct. Ordered most-specific first; a question is counted once,
# under the first that matches, so the tally partitions rather than double-counts.
SIGNALS = [
    ("recursive / hierarchy", r"\b(recursi|hierarch|ancestor|descendant|transitive|reports? (up|to)\b.*chain|org chart)"),
    ("json field",            r"\b(json|jsonb|key of the|nested (field|key|attribute))"),
    ("running / cumulative",  r"\b(cumulative|running total|running sum|moving average|rolling|year[- ]over[- ]year|month[- ]over[- ]month|progress(es|ing)? (through|over))"),
    ("rank / top-n per",      r"\b(rank|top \d|highest .* (for|per|in) each|the (most|least) .* per\b|n?th (highest|largest))"),
    ("median / percentile",   r"\b(median|percentile|quartile|interquartile|mode of)"),
    ("share of total",        r"\b(percentage of|proportion of|ratio of .* to the total|share of|as a percentage)"),
    ("grouped aggregate",     r"\b(for each|per |group(ed)? by|by region|by category|average .* (by|across))"),
    ("scalar aggregate",      r"\b(how many|count|total number|the (maximum|minimum|highest|lowest|average)\b|sum of)"),
    ("filter / project",      r"."),
]


def jsonb_tables(db):
    """Tables whose DDL declares a jsonb column -- a question touching these may be out of reach."""
    path = os.path.join(DATA, db, "%s_schema.txt" % db)
    out, cur = set(), None
    for line in open(path):
        m = re.match(r'^CREATE TABLE\s+"?(\w+)"?', line)
        if m:
            cur = m.group(1)
        elif cur and "jsonb" in line.lower():
            out.add(cur)
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    tasks = [json.loads(l) for l in open(
        os.path.join(DATA, "livesqlbench_large_v1_data.jsonl"))]
    query = [t for t in tasks if t["category"] == "Query"]

    print("480 tasks: %d Query, %d Management\n" % (len(query), len(tasks) - len(query)))
    print("The compiler emits SELECT and nothing else, so the %d Management tasks are out of\n"
          "scope before anything is measured. Everything below is over the %d Query tasks.\n"
          % (len(tasks) - len(query), len(query)))

    tally = collections.Counter()
    examples = collections.defaultdict(list)
    for t in query:
        text = t["normal_query"].lower()
        for name, pat in SIGNALS:
            if re.search(pat, text):
                tally[name] += 1
                examples[name].append(t["instance_id"])
                break

    print("%-24s %6s  %s" % ("construct signalled", "count", "does the compiler have it?"))
    print("-" * 78)
    HAVE = {
        "filter / project": "yes",
        "scalar aggregate": "yes",
        "grouped aggregate": "yes -- GROUPED BY ... AS",
        "share of total": "partly -- finding 82 closed the pinned case",
        "rank / top-n per": "yes -- THE FIRST n PER, WITHIN",
        "running / cumulative": "yes -- WITHIN (finding 77)",
        "median / percentile": "NO -- no ordered-set aggregate",
        "json field": "NO",
        "recursive / hierarchy": "NO -- no transitive closure",
    }
    for name, _ in SIGNALS:
        if tally[name]:
            print("%-24s %6d  %s" % (name, tally[name], HAVE.get(name, "?")))
    print("-" * 78)
    missing = sum(tally[n] for n in ("median / percentile", "json field",
                                     "recursive / hierarchy"))
    print("%-24s %6d  of %d Query tasks signal something we do not have (%.0f%%)"
          % ("not expressible", missing, len(query), 100.0 * missing / len(query)))

    hl = sum(1 for t in query if t.get("high_level"))
    print("\nhigh_level:      %d of %d Query tasks (%.0f%%) name a term defined only in the"
          % (hl, len(query), 100.0 * hl / len(query)))
    print("                 knowledge base -- these cannot be answered from the schema alone.")

    # The wording probe sees "json" only when the question says so. The structural exposure is
    # bigger, and it is the number to quote when sizing the gap.
    dbs = sorted({t["selected_database"] for t in query})
    with_json = {db: jsonb_tables(db) for db in dbs}
    exposed = sum(1 for t in query if with_json[t["selected_database"]])
    print("\njsonb reach:     %d of %d databases carry jsonb columns, in %d tables. %d Query tasks\n"
          "                 sit on such a database -- the 4 above is what the *wording* admits,\n"
          "                 and is a floor, not the gap."
          % (sum(1 for v in with_json.values() if v), len(dbs),
             sum(len(v) for v in with_json.values()), exposed))

    print("\nreminder: the gold is withheld, so none of the above is an accuracy measurement.")
    if args.verbose:
        for name, _ in SIGNALS:
            if tally[name]:
                print("\n%s: %s" % (name, ", ".join(examples[name][:8])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
