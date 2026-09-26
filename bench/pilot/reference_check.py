#!/usr/bin/env python3
"""The reference interpreter against the recorded corpus: does the compiler implement P?

`corpus.py` recompiles every recorded query and reports what changed since the baseline. It
cannot say whether the baseline was right -- it accepted the self-join collapse (finding 101)
for weeks. This runs each recorded query through `conquer/reference.py`, which evaluates
Proper's semantics directly from the data, and compares the two result sets. A disagreement
is a compiler bug, a reference bug, or a deliberate departure from P that the 2026 spec ought
to name. All three are worth knowing.

The reference is a proof of concept over the 1992 core, so most recorded queries fall outside
it; the count of those is part of the result, not a thing to hide.

    reference_check.py [--arm ARM] [-v]
"""

import argparse
import collections
import json
import signal
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
sys.path.insert(0, HERE)

import corpus                      # noqa: E402
import conquer as driver           # noqa: E402
import parser as parser_mod        # noqa: E402
import sql as sql_mod              # noqa: E402
import reference as ref_mod        # noqa: E402


import re


def _cell(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, int):
        return float(v)
    if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
        try:                                   # a gathered bag: order is not promised
            return tuple(sorted((str(_cell(x)) for x in json.loads(v))))
        except ValueError:
            return v
    return v


def canon(rows):
    out = [tuple(_cell(v) for v in r) for r in rows]
    return sorted(out, key=lambda t: tuple(str(x) for x in t))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--arm", default="conquer")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--normal-form", action="store_true",
                   help="also evaluate each agreeing query's --normalise text and compare")
    p.add_argument("--progress", action="store_true", help="one line per query on stderr")
    p.add_argument("--db", action="append", help="only this database (repeatable)")
    p.add_argument("--budget", type=int, default=30,
                   help="seconds the reference may spend on one query before it is counted "
                        "as too slow -- a check that takes hours is a check nobody runs")
    args = p.parse_args(argv)

    class TooSlow(Exception):
        pass

    def _alarm(signum, frame):
        raise TooSlow()
    signal.signal(signal.SIGALRM, _alarm)

    loaded = {}
    tally = collections.Counter()
    reasons = collections.Counter()
    diffs = []
    t0 = time.time()
    for arm, db, qid, text in corpus.answers([args.arm]):
        if db not in loaded:
            # The semantic-layer arm was written against the semantic model, which carries the
            # derived fact types, subtypes and macros its queries name. corpus.py selects it
            # the same way; checking those answers against the plain model refuses half of them.
            semantic = arm in getattr(corpus, "SEMANTIC", ()) or "sem" in arm
            path = os.path.join(corpus.MODELS, "%s.%sccm.json" % (db, "semantic." if semantic else ""))
            if not os.path.exists(path):
                path = os.path.join(corpus.MODELS, "%s.ccm.json" % db)
            model = json.load(open(path))
            conn = sqlite3.connect("file:%s?mode=ro"
                                   % os.path.join(corpus.DBS, db, db + ".sqlite"), uri=True)
            lex = parser_mod.Lexicon(model)
            loaded[db] = (model, conn, lex, sql_mod.Emitter(model),
                          ref_mod.Reference(model, conn, lex))
        model, conn, lex, em, ref = loaded[db]
        if args.db and db not in args.db:
            continue
        if args.progress:
            print("%s/%s" % (db, qid), file=sys.stderr, flush=True)
        try:
            signal.alarm(args.budget)
            block, sql, params = driver.transpile(model, text, lex, em)
            got = canon(conn.execute(sql, params).fetchall())
            signal.alarm(0)
        except TooSlow:
            signal.alarm(0)
            tally["too slow for the compiler's SQL (>%ds)" % args.budget] += 1
            continue
        except Exception as e:                                          # noqa: BLE001
            signal.alarm(0)
            tally["compiler refused/failed"] += 1
            continue
        try:
            signal.alarm(args.budget)
            ext, rest, lex2, _ = driver.expand_definitions(model, text, lex)
            r = ref if ext is model else ref_mod.Reference(ext, conn, lex2)
            want = canon(r.query(parser_mod.Parser(lex2 or lex, rest).parse_query()))
            signal.alarm(0)
        except TooSlow:
            signal.alarm(0)
            tally["too slow for the reference (>%ds)" % args.budget] += 1
            reasons["SLOW: %s/%s" % (db, qid)] += 1
            continue
        except ref_mod.Unsupported as e:
            signal.alarm(0)
            tally["outside the reference's scope"] += 1
            reasons[str(e).split(" resolves")[0][:60]] += 1
            continue
        except Exception as e:                                          # noqa: BLE001
            signal.alarm(0)
            tally["reference crashed"] += 1
            reasons["CRASH %s: %s" % (type(e).__name__, str(e)[:50])] += 1
            continue
        if got == want:
            tally["agree"] += 1
            if args.normal_form:
                try:
                    signal.alarm(args.budget)
                    nf = driver.normalise(model, text, lex)
                    ext2, rest2, lex3, _ = driver.expand_definitions(model, nf, lex)
                    r2 = ref if ext2 is model else ref_mod.Reference(ext2, conn, lex3)
                    nf_want = canon(r2.query(parser_mod.Parser(lex3 or lex, rest2).parse_query()))
                    signal.alarm(0)
                except (TooSlow, ref_mod.Unsupported):
                    signal.alarm(0)
                    tally["normal form: outside scope"] += 1
                except Exception as e:                                  # noqa: BLE001
                    signal.alarm(0)
                    tally["normal form: DIFFER"] += 1
                    diffs.append((db, qid, "NORMAL FORM FAILS: " + str(e)[:80], got, []))
                else:
                    if nf_want == want:
                        tally["normal form: agree"] += 1
                    else:
                        tally["normal form: DIFFER"] += 1
                        diffs.append((db, qid, "NORMAL FORM: " + nf[:100], want, nf_want))
        elif r.tied_cut:
            tally["tie at an ordered cut"] += 1
            reasons["TIE: %s/%s -- no defined answer (finding 83)" % (db, qid)] += 1
        else:
            tally["DIFFER"] += 1
            diffs.append((db, qid, text, got, want))

    n = sum(tally.values())
    print("%s arm: %d recorded queries in %.0fs\n" % (args.arm, n, time.time() - t0))
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print("   %-34s %4d" % (k, v))
    if reasons:
        print("\nwhy queries fall outside the reference's scope:")
        for k, v in reasons.most_common(12):
            print("   %3d  %s" % (v, k))
    if diffs:
        print("\nDIFFER -- the compiler and P disagree:")
        for db, qid, text, got, want in diffs:
            print("\n   %s/%s\n     %s\n     compiler  %s\n     reference %s"
                  % (db, qid, text[:120], str(got[:3])[:100], str(want[:3])[:100]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
