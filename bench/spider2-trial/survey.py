#!/usr/bin/env python3
"""What the reverse engineering makes of Spider 2.0's thirty local databases.

Three numbers per model, and they are the three that decide whether a question can be asked
of it at all:

    concepts        nothing derived means every query is impossible; rule 1 blocks a table
                    that declares neither a key nor a foreign key, and half of these do
    blockers        tables that derived to nothing, from the report
    unreachable     verb parts naming two fact types between the same pair of types, where
                    naming the target does not help either -- the pair cannot be walked

Run it after any change to `reverse/`, against the models in `bench/spider2-models/`.

    survey.py [-v]
"""

import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
MODELS = os.path.join(ROOT, "bench/spider2-models")

import parser as parser_mod            # noqa: E402


def unreachable(lex):
    """Two fact types between the same pair of types, read by the same verb part."""
    out = []
    for verb, entries in lex.verbs.items():
        seen = {}
        for fact, a, b in entries:
            key = (lex.player(a), lex.player(b))
            if seen.setdefault(key, fact) != fact:
                out.append((verb, lex.concepts[lex.player(a)]["name"],
                            lex.concepts[lex.player(b)]["name"]))
    return out


def main(argv=None):
    verbose = "-v" in (argv or sys.argv[1:])
    total = collections.Counter()
    print("%-30s %8s %8s %8s %12s" % ("database", "tables", "derived", "blocked", "unreachable"))
    for path in sorted(glob.glob(os.path.join(MODELS, "*.ccm.json"))):
        name = os.path.basename(path)[:-len(".ccm.json")]
        model = json.load(open(path))
        lex = parser_mod.Lexicon(model)
        report = os.path.join(MODELS, name + ".report.md")
        blocked = 0
        if os.path.exists(report):
            blocked = len(re.findall(r"^### `.*` — rule 1$", open(report).read(), re.M))
        tables = len(model.get("mapping", {}).get("tables", []))
        bad = unreachable(lex)
        entities = sum(1 for c in model["concepts"] if c["kind"] == "entity")
        print("%-30s %8d %8d %8d %12d" % (name, tables + blocked, entities, blocked, len(bad)))
        if verbose and bad:
            for verb, a, b in bad[:4]:
                print("      %-20s %s -> %s" % (verb, a, b))
        total["tables"] += tables + blocked
        total["derived"] += entities
        total["blocked"] += blocked
        total["unreachable"] += len(bad)
        total["models"] += 1
        total["empty"] += 1 if entities == 0 else 0
    print("\n%d models: %d tables, %d entity types, %d tables blocked, %d unreachable pairs, "
          "%d models empty" % (total["models"], total["tables"], total["derived"],
                               total["blocked"], total["unreachable"], total["empty"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
