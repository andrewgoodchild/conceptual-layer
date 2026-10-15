"""Which values may be summed: additivity on value types, guessed from their names.

A sum over a rate, a ratio, an average or an age is a number with no meaning, and a sum of a
balance or a stock level across dates counts the same money once per day it sat there. Nothing
in a catalogue says which columns are which -- a DECIMAL is a DECIMAL -- so a semantic layer
either has someone write it down (Kimball's additive, semi-additive and non-additive facts) or
says nothing. This writes down what the *name* says, as the guess it is: each one is a claim on
the review file, at confidence `guess`, and a rejected one is not made again.

Two kinds are inferred, and deliberately not the third:

  * `nonAdditive` -- the name is a rate, ratio, percentage, average, rank, rating, age or a
    coordinate. Price is left out on purpose: BIRD's `transactions_1k.Price` is what a
    transaction cost, and its questions sum it.
  * `semiAdditive` -- the name is a balance, stock, inventory or headcount, *and* the thing it
    is a fact about has exactly one date in the same table: the role a sum must not run
    across. With no date, or two, there is nothing to name and nothing is said.

`additive` is the default and is never written: marking everything else additive would say
more than a name knows.

What it buys is two warnings: `describe_schema` says not to sum these, and the SQL checker
reports a SUM that does (conquer/sqlcheck.py).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from model.names import words                                          # noqa: E402
import review as review_mod                                            # noqa: E402

NUMERIC = {"integer", "real", "numeric", "decimal", "float", "double", "bigint", "smallint"}
TEMPORAL = {"date", "datetime", "timestamp"}
NON_ADDITIVE = {"rate", "ratio", "percent", "percentage", "pct", "avg", "average", "mean",
                "median", "rank", "ranking", "rating", "age", "latitude", "longitude", "lat",
                "lng", "lon"}
LEVELS = {"balance", "stock", "inventory", "headcount"}


def _vocabulary(concept):
    out = set()
    for name in [concept["name"]] + list(concept.get("terms") or []):
        out |= {w.casefold() for w in words(name)}
    return out


def apply(model, report):
    """Mark the value types whose names say how they add up. Returns how many."""
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    role_map = {rm["role"]: rm for rm in (model.get("mapping") or {}).get("roleMap", [])}
    # value type -> [(the entity it is a fact about, its own role, the table it is in)]
    facts_of = {}
    for f in model.get("concepts", []):
        roles = f.get("roles", []) if f["kind"] == "fact" else []
        if len(roles) != 2:
            continue
        kinds = [concepts.get(r["player"], {}).get("kind") for r in roles]
        if sorted(kinds) != ["entity", "value"]:
            continue
        ent, val = (roles[0], roles[1]) if kinds[0] == "entity" else (roles[1], roles[0])
        table = (role_map.get(val["id"]) or {}).get("table")
        facts_of.setdefault(val["player"], []).append((ent["player"], val["id"], table))

    def dates_beside(entity, table):
        return [rid for vid, uses in facts_of.items()
                for e, rid, t in uses
                if e == entity and t == table and
                (concepts[vid].get("dataType") or {}).get("name") in TEMPORAL]

    made = 0
    for c in model.get("concepts", []):
        if c["kind"] != "value" or c.get("additivity") or \
                (c.get("dataType") or {}).get("name") not in NUMERIC:
            continue
        vocab = _vocabulary(c)
        if vocab & NON_ADDITIVE:
            said = sorted(vocab & NON_ADDITIVE)[0]
            if review_mod.vetoed("additivity", c["name"]):
                continue
            c["additivity"] = "nonAdditive"
            report.refine("additivity", "guess", c["name"],
                          "Named as a %s, so a sum of it means nothing: an average, or the "
                          "quantities it is computed from, is what a total needs." % said,
                          "Reject it if this is a quantity after all; the schema listing and "
                          "the SQL checker stop warning about sums of it.")
            made += 1
        elif vocab & LEVELS:
            uses = facts_of.get(c["id"], [])
            if len(uses) != 1:
                continue
            entity, _, table = uses[0]
            dates = dates_beside(entity, table)
            if len(dates) != 1 or review_mod.vetoed("additivity", c["name"]):
                continue
            date = concepts.get(next(r["player"] for f in model["concepts"] if f["kind"] == "fact"
                                     for r in f.get("roles", []) if r["id"] == dates[0]), {})
            c["additivity"], c["additiveExcept"] = "semiAdditive", dates[0]
            report.refine("additivity", "guess", c["name"],
                          "Named as a %s, which is a level at a point in time: summed over "
                          "several %s values it counts the same thing once per date. Summing "
                          "it within one date is fine."
                          % (sorted(vocab & LEVELS)[0], date.get("name", "date")),
                          "Reject it if this is a flow (an amount moved) rather than a level.")
            made += 1
    return made
