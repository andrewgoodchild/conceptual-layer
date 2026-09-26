#!/usr/bin/env python3
"""How good are the inferred keys? Take a schema that declares them, hide them, ask again.

Rule 9b guesses a primary key where the catalogue declares none, and rule 9 guesses a foreign
key from column names. Both are guesses, and until now the only evidence they worked was that
more tables derived. More tables is not better tables: a wrong identifier is a wrong identity
in every query that walks it, and a wrong foreign key is a join that silently answers the
wrong question.

So this measures. A database that *does* declare its keys is a labelled set: strip the
declarations out of the catalogue, run the inference against the data alone, and compare what
comes back with what was there. That gives precision and recall for both, which is what the
literature reports -- Jiang & Naumann's HoPF (JIIS 54:439-461, 2020) retrieves 88% of primary
keys and 91% of foreign keys, and is the bar to aim at.

Recall says how many tables stop being blocked. **Precision is the one that matters**, because
a missing key costs a table and a wrong key costs every answer drawn through it.

    test_inference.py [-v]                    the fixture, with thresholds asserted
    test_inference.py --db X.sqlite [...]     measured against real schemas
"""

import argparse
import copy
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import catalog as catalog_mod      # noqa: E402
import derive as derive_mod        # noqa: E402
import population as pop           # noqa: E402

# What the fixture must reach. Set from measured behaviour, and meant to be raised: they are
# a ratchet against regression, not a target.
WANT = {"pk_recall": 0.90, "pk_precision": 1.0, "fk_recall": 0.90, "fk_precision": 1.0}


def stripped(cat):
    """The same catalogue with every declared key and foreign key removed -- what reverse
    engineering sees on the half of Spider 2.0's tables that declare nothing."""
    out = copy.deepcopy(cat)
    for t in out.tables:
        t.primary_key, t.uniques, t.foreign_keys = [], [], []
    return out


def truth(cat):
    """(primary keys, foreign keys) as the catalogue declares them, case-folded."""
    pks, fks = {}, set()
    for t in cat.tables:
        if t.is_view:
            continue
        if t.primary_key:
            pks[t.name.casefold()] = tuple(c.casefold() for c in t.primary_key)
        for fk in t.foreign_keys:
            fks.add((t.name.casefold(), tuple(c.casefold() for c in fk.columns),
                     fk.ref_table.casefold()))
    return pks, fks


def infer(conn, cat):
    """What the two rules propose, given no declarations at all."""
    blind = stripped(cat)
    # pop.recover is the pipeline reverse.py --infer-keys runs, called rather than restated
    # so this measures what the tool does: keys (9b), then the references that point at them
    # (9c). The names that agree with neither (rule 9) come last, in the deriver.
    _, keys, _ = pop.recover(conn, blind)
    deriver = derive_mod.Deriver(blind, infer_undeclared_fks=True)
    deriver.infer_foreign_keys()
    pks = {t.casefold(): tuple(c.casefold() for c in cols) for t, cols, _ in keys}
    fks = set()
    for t in blind.tables:
        for fk in t.foreign_keys:
            fks.add((t.name.casefold(), tuple(c.casefold() for c in fk.columns),
                     fk.ref_table.casefold()))
    return pks, fks


# Why a declared foreign key was not recovered. Ordered so that the first reason that applies
# is the one reported, because they compose: a reference whose target lost its key was never
# going to be scored on anything else.
def diagnose(path):
    """(reason -> [missed foreign keys]) for one database.

    Recall on references is the weakest number this harness reports, and "53%" says nothing
    about what to do next. These reasons do: one of them is a threshold to move, one is a
    scoring bug waiting to be found, and two are ceilings no data-based method can pass.
    """
    cat = catalog_mod.from_sqlite(path)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    try:
        want_pk, want_fk = truth(cat)
        blind = stripped(cat)
        analysis, keys, refs = pop.recover(conn, blind)
        deriver = derive_mod.Deriver(blind, infer_undeclared_fks=True)
        deriver.infer_foreign_keys()
        got = set()
        for t in blind.tables:
            for fk in t.foreign_keys:
                got.add((t.name.casefold(), tuple(c.casefold() for c in fk.columns),
                         fk.ref_table.casefold()))
        keyed = {t.name.casefold() for t in blind.tables if t.primary_key}
        rows = {t.name.casefold(): analysis.row_counts.get(t.name, 0) for t in blind.tables}
        incl = {}
        for f in analysis.of_kind("inclusion") + analysis.of_kind("inclusion-1to1"):
            k = (f.table.casefold(), tuple(c.casefold() for c in f.columns),
                 (f.target_table or "").casefold())
            incl[k] = f

        by = {t.name.casefold(): t for t in blind.tables}
        out = {}
        for miss in sorted(want_fk - got):
            table, cols, target = miss
            f = incl.get(miss)
            if len(cols) > 1:
                why = "composite: the inclusion search reads one column"
            elif target not in keyed:
                why = "the target kept no key, so there was nothing to point at"
            elif rows.get(table, 0) < pop.MIN_ROWS:
                why = "too few rows for the population to be evidence"
            elif f is None:
                why = ("containment does not hold: the declared reference is violated by the "
                       "data" if not _contained(conn, cat, miss) else
                       "contained, but the search never proposed it")
            elif not f.significant:
                why = "proposed but below the significance threshold"
            elif not f.preferred:
                why = "proposed, but another target scored higher for the same column"
            elif not f.corroborated:
                why = "preferred, but the column's name points nowhere near the target"
            elif [c.casefold() for c in (by.get(table).primary_key if by.get(table) else [])] \
                    == list(cols):
                why = "rejected: the column is this table's whole key, which reads as a subtype"
            else:
                why = "preferred, significant and corroborated, and still not applied"
            out.setdefault(why, []).append(miss)
        return out, len(want_fk)
    finally:
        conn.close()


def _contained(conn, cat, miss) -> bool:
    """Does the declared reference actually hold in the data? `_violations` reports that 28%
    of declared single-column foreign keys in a Spider sample do not."""
    table, cols, target = miss
    by = {t.name.casefold(): t for t in cat.tables}
    t, tgt = by.get(table), by.get(target)
    if not t or not tgt or len(cols) != 1:
        return False
    fk = next((f for f in t.foreign_keys
               if tuple(c.casefold() for c in f.columns) == cols), None)
    key = (fk.ref_columns if fk and fk.ref_columns else tgt.primary_key or [None])[0]
    if not key:
        return False
    try:
        return not conn.execute(
            'SELECT COUNT(*) FROM (SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL '
            'EXCEPT SELECT "%s" FROM "%s")'
            % (cols[0], t.name, cols[0], key, tgt.name)).fetchone()[0]
    except sqlite3.Error:
        return False


def measure(path):
    """(counts, notes) for one database."""
    cat = catalog_mod.from_sqlite(path)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    try:
        want_pk, want_fk = truth(cat)
        got_pk, got_fk = infer(conn, cat)
    finally:
        conn.close()
    # A table the catalogue never keyed cannot be scored either way: it has no answer.
    scored_pk = {t: k for t, k in got_pk.items() if t in want_pk}
    # as sets: the order of a composite key's columns does not change which rows it
    # identifies, and neither the catalogue nor the search has an opinion worth scoring
    right_pk = {t for t, k in scored_pk.items() if set(k) == set(want_pk[t])}
    wrong_pk = [(t, scored_pk[t], want_pk[t]) for t in scored_pk if t not in right_pk]
    missed_pk = sorted(t for t in want_pk if t not in got_pk)
    right_fk = got_fk & want_fk
    # A schema that declares no foreign key at all is not a labelled set for them: every
    # proposal is unscoreable rather than wrong, and counting them as wrong said
    # `deliveries.driver_id -> drivers` was a false positive.
    #
    # Within a schema that does declare them, a proposal is only *contradicted* when the
    # schema declares a different target for the same columns. Where it declares nothing for
    # those columns the proposal may well be a real reference the schema never wrote down --
    # `match_games.winningteamid -> teams` is not a mistake, it is an omission in
    # BowlingLeague. Counting those as wrong understates precision, so they are counted
    # apart, and precision over the contradicted ones is the number to trust.
    declared_for = {(f[0], f[1]) for f in want_fk}
    scored_fk = {f for f in got_fk if (f[0], f[1]) in declared_for} if want_fk else set()
    wrong_fk = sorted(scored_fk - want_fk)
    undeclared_fk = sorted({f for f in got_fk if f[2] in want_pk} - scored_fk - want_fk) \
        if want_fk else []
    missed_fk = sorted(want_fk - got_fk)
    return {
        "tables": len([t for t in cat.tables if not t.is_view]),
        "pk_declared": len(want_pk), "pk_found": len(scored_pk), "pk_right": len(right_pk),
        "fk_declared": len(want_fk), "fk_found": len(scored_fk), "fk_right": len(right_fk),
        "fk_undeclared": len(undeclared_fk),
    }, (wrong_pk, wrong_fk, missed_pk, missed_fk, undeclared_fk)


def rates(c):
    def div(a, b):
        return a / b if b else 1.0
    return (div(c["pk_right"], c["pk_declared"]), div(c["pk_right"], c["pk_found"]),
            div(c["fk_right"], c["fk_declared"]), div(c["fk_right"], c["fk_found"]))


FIXTURE = """
CREATE TABLE artist   (artist_id INTEGER PRIMARY KEY, name TEXT NOT NULL, country TEXT);
CREATE TABLE album    (album_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                       artist_id INTEGER NOT NULL REFERENCES artist(artist_id),
                       label TEXT, released TEXT);
CREATE TABLE track    (track_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                       album_id INTEGER NOT NULL REFERENCES album(album_id),
                       seconds INTEGER NOT NULL);
CREATE TABLE venue    (venue_id INTEGER PRIMARY KEY, venue_name TEXT NOT NULL, city TEXT);
-- an association: neither column identifies a row, both together do
CREATE TABLE gig      (artist_id INTEGER NOT NULL REFERENCES artist(artist_id),
                       venue_id INTEGER NOT NULL REFERENCES venue(venue_id),
                       PRIMARY KEY (artist_id, venue_id));
-- a natural key that names nothing else in the schema
CREATE TABLE pressing (catalogue_no TEXT PRIMARY KEY,
                       album_id INTEGER NOT NULL REFERENCES album(album_id), plant TEXT);
-- an event log: no identity of its own, and nothing should invent one
CREATE TABLE play     (album_id INTEGER NOT NULL REFERENCES album(album_id),
                       station TEXT NOT NULL, played_on TEXT NOT NULL);
"""


def build(path):
    conn = sqlite3.connect(path)
    conn.executescript(FIXTURE)
    conn.executemany("INSERT INTO artist VALUES (?,?,?)",
                     [(i, "artist %d" % i, "AU" if i % 3 else "NZ") for i in range(1, 81)])
    conn.executemany("INSERT INTO album VALUES (?,?,?,?,?)",
                     [(i, "album %d" % i, 1 + (i * 7) % 80, "label %d" % (i % 6),
                       "19%02d-01-01" % (60 + i % 40)) for i in range(1, 161)])
    conn.executemany("INSERT INTO track VALUES (?,?,?,?)",
                     [(i, "track %d" % i, 1 + (i * 13) % 160, 120 + i % 300)
                      for i in range(1, 401)])
    conn.executemany("INSERT INTO venue VALUES (?,?,?)",
                     [(i, "venue %d" % i, "city %d" % (i % 7)) for i in range(1, 91)])
    conn.executemany("INSERT INTO gig VALUES (?,?)",
                     sorted({(1 + (i * 11) % 80, 1 + (i * 17) % 90) for i in range(300)}))
    conn.executemany("INSERT INTO pressing VALUES (?,?,?)",
                     [("CAT-%04d" % i, 1 + (i * 3) % 160, "plant %d" % (i % 4))
                      for i in range(1, 121)])
    conn.executemany("INSERT INTO play VALUES (?,?,?)",
                     [(1 + (i * 19) % 160, "station %d" % (i % 11), "2026-01-%02d" % (i % 28 + 1))
                      for i in range(1, 241)])
    conn.commit()
    conn.close()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db", nargs="*", help="measure against real databases instead")
    p.add_argument("--why", action="store_true",
                   help="with --db, classify every declared foreign key the inference did not "
                        "recover, instead of scoring")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if args.db and args.why:
        import collections
        tally, examples, declared = collections.Counter(), {}, 0
        for path in args.db:
            try:
                reasons, n = diagnose(path)
            except sqlite3.Error as e:
                print("%-26s %s" % (os.path.basename(path)[:26], e))
                continue
            declared += n
            for why, misses in reasons.items():
                tally[why] += len(misses)
                examples.setdefault(why, []).append(
                    "%s.%s -> %s" % (misses[0][0], ",".join(misses[0][1]), misses[0][2]))
        missed = sum(tally.values())
        print("%d declared foreign keys, %d not recovered:\n" % (declared, missed))
        for why, n in tally.most_common():
            print("  %4d  %-58s %s" % (n, why, examples[why][0][:40]))
        return 0

    if args.db:
        print("%-26s %7s %-18s %-18s" % ("database", "tables", "primary keys", "foreign keys"))
        totals = {k: 0 for k in ("pk_declared", "pk_found", "pk_right", "fk_declared",
                                 "fk_found", "fk_right", "fk_undeclared", "tables")}
        for path in args.db:
            try:
                counts, (wrong_pk, wrong_fk, missed_pk, missed_fk, extra_fk) = measure(path)
            except sqlite3.Error as e:
                print("%-26s %s" % (os.path.basename(path)[:26], e))
                continue
            for k in totals:
                totals[k] += counts[k]
            pr, pp, fr, fp = rates(counts)
            print("%-26s %7d  R %3.0f%% P %3.0f%%     R %3.0f%% P %3.0f%%"
                  % (os.path.basename(path)[:-7][:26], counts["tables"],
                     100 * pr, 100 * pp, 100 * fr, 100 * fp))
            if args.verbose:
                for t, got, want in wrong_pk:
                    print("      wrong key   %-22s proposed %s, declared %s" % (t, got, want))
                for f in wrong_fk[:4]:
                    print("      wrong ref   %s.%s -> %s" % (f[0], ",".join(f[1]), f[2]))
                for t in missed_pk[:6]:
                    print("      no key for  %s" % t)
                for f in missed_fk[:4]:
                    print("      missed ref  %s.%s -> %s" % (f[0], ",".join(f[1]), f[2]))
                for f in extra_fk[:4]:
                    print("      extra ref   %s.%s -> %s  (schema declares none here)"
                          % (f[0], ",".join(f[1]), f[2]))
        pr, pp, fr, fp = rates(totals)
        print("\n%d tables: primary keys recall %.0f%% precision %.0f%% (%d of %d declared); "
              "foreign keys recall %.0f%% precision %.0f%% (%d of %d), and %d more onto a "
              "column the schema declares nothing for"
              % (totals["tables"], 100 * pr, 100 * pp, totals["pk_right"],
                 totals["pk_declared"], 100 * fr, 100 * fp, totals["fk_right"],
                 totals["fk_declared"], totals["fk_undeclared"]))
        return 0

    path = os.path.join(HERE, ".inference.sqlite")
    if os.path.exists(path):
        os.remove(path)
    build(path)
    try:
        counts, (wrong_pk, wrong_fk, missed_pk, missed_fk, extra_fk) = measure(path)
        pr, pp, fr, fp = rates(counts)
        got = {"pk_recall": pr, "pk_precision": pp, "fk_recall": fr, "fk_precision": fp}
        passed = failed = 0
        for name, floor in sorted(WANT.items()):
            ok = got[name] >= floor
            passed += ok
            failed += not ok
            print("%s  %-14s %3.0f%%  (floor %.0f%%)"
                  % ("ok   " if ok else "FAIL ", name, 100 * got[name], 100 * floor))
        for t, g, w in wrong_pk:
            print("      wrong key on %s: proposed %s, declared %s" % (t, g, w))
        for f in wrong_fk:
            print("      wrong reference %s.%s -> %s" % (f[0], ",".join(f[1]), f[2]))
        print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
        return 1 if failed else 0
    finally:
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    sys.exit(main())
