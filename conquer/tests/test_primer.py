#!/usr/bin/env python3
"""Every example in the primer, compiled and run.

The primer is a prompt: `conquer.py --primer` prints it, and an agent writes queries from it.
That makes a wrong example worse than a missing one -- it is a confident instruction to write
something that does not work, and the reader has no way to tell. Finding 30 was exactly this:
the primer's own example 19 described a shape that lowered to a cross product.

So every fenced ```conquer block runs against the company fixture, and the `-- N rows` line
under it is an assertion. An example that stops being true fails here instead of misleading a
writer.

    test_primer.py [--model M] [--db D] [-v]
"""

import argparse
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402

PRIMER = os.path.join(HERE, "..", "primer.md")
BLOCK = re.compile(r"```conquer\n(.*?)```", re.S)
EXPECT = re.compile(r"^--\s*(\d+) rows?(?:\s*:\s*(.+?))?\s*$")


def examples(text):
    """(query, expected rows or None, expected first cell or None) per fenced block."""
    for body in BLOCK.findall(text):
        lines, rows, value = [], None, None
        for line in body.rstrip().split("\n"):
            m = EXPECT.match(line.strip())
            if m:
                rows, value = int(m.group(1)), m.group(2)
            elif line.strip():
                lines.append(line.strip())
        yield " ".join(lines), rows, value


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (os.path.exists(args.model) and os.path.exists(args.db)):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2

    model = json.load(open(args.model))
    lex, emit = parser_mod.Lexicon(model), sql_mod.Emitter(model)
    conn = sqlite3.connect(args.db)
    passed = failed = 0
    for query, want_rows, want_value in examples(open(PRIMER).read()):
        note = ""
        try:
            _, text, params = driver.transpile(model, query, lex, emit)
            got = conn.execute(text, params).fetchall()
            ok = True
            if want_rows is not None and len(got) != want_rows:
                ok, note = False, "says %d rows, returns %d" % (want_rows, len(got))
            elif want_value is not None and str(got[0][0]) != want_value:
                ok, note = False, "says %s, returns %s" % (want_value, got[0][0])
            else:
                note = "%d rows" % len(got)
        except Exception as e:                                        # noqa: BLE001
            ok, note = False, "%s: %s" % (type(e).__name__, str(e).split("\n")[0][:90])
        if ok:
            passed += 1
            print("ok    %-92s %s" % (query[:92], note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s" % (query[:92], note))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
