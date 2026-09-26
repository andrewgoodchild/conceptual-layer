#!/usr/bin/env python3
"""names.py: the three things a column name is read for beyond its words.

Units, quantities and abbreviations are all guesses made from spelling, and all three are
cheap to check and expensive to get wrong. A unit read off the wrong suffix puts a duration
and a frequency in one domain; an abbreviation expanded on a substring turns `category` into
a catalogue. So the negatives are as load-bearing as the positives here: most of these cases
assert that a name is left exactly as it came.

    test_names.py [-v] [--only SUBSTRING]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from model.names import (expand, quantity_name, read_glossary,       # noqa: E402
                        segment, unit_of, _vocabulary, GLOSSARY, COMPOUNDS)

VOCAB = _vocabulary(GLOSSARY, COMPOUNDS)
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def eq(got, want, why=""):
    assert got == want, "expected %r, got %r%s" % (want, got, (" -- " + why) if why else "")


# --------------------------------------------------------------------------- units

@case
def test_a_unit_suffix_is_recognised():
    for column, unit in [("freqmhz", "MHz"), ("airtempc", "degC"), ("objtempk", "K"),
                         ("sourcedistly", "ly"), ("objmasssol", "M_sun"),
                         ("obsdurhrs", "h"), ("presshpa", "hPa"), ("noisefloordbm", "dBm"),
                         ("sigstrdb", "dB"), ("bandusagepct", "%"), ("lunardistdeg", "deg")]:
        eq(unit_of(column), unit, column)


@case
def test_the_longest_suffix_wins():
    """`dbm` is power and `db` is a ratio; `tempk` is kelvin and a bare `k` is nothing."""
    eq(unit_of("noisefloordbm"), "dBm")
    eq(unit_of("sigstrdb"), "dB")


@case
def test_a_word_that_merely_ends_in_a_unit_is_not_one():
    """The check that keeps this from firing on a third of every schema."""
    for column in ("status", "address", "analysis", "process", "class", "access",
                   "diagnosis", "alias", "index", "signalclass", "bias"):
        eq(unit_of(column), None, column)


@case
def test_a_bare_unit_is_a_column_called_that():
    """`ms` on its own is a column named ms, not milliseconds of something unnamed."""
    for column in ("ms", "sec", "deg", "db", "hz"):
        eq(unit_of(column), None, column)


@case
def test_metres_per_second_is_told_from_milliseconds_by_the_stem():
    """The two differ by a factor of 1000 and by dimension, so nothing downstream catches it."""
    eq(unit_of("windspeedms"), "m/s")
    eq(unit_of("velms"), "m/s")
    eq(unit_of("pulsewidms"), "ms")
    eq(unit_of("proctimems"), "ms")


@case
def test_a_rate_is_not_the_unit_its_suffix_names():
    """`pulsepersec` is pulses per second. Reading it as seconds would put a frequency in
    the Duration domain alongside a length of time."""
    eq(unit_of("pulsepersec"), "1/s")
    eq(unit_of("bitspersec"), "1/s")
    eq(unit_of("periodsec"), "s")
    eq(unit_of("sigdursec"), "s")


# --------------------------------------------------------------------------- quantities

@case
def test_a_quantity_names_the_domain():
    eq(quantity_name("MHz", ["MHz", "deg"]), "Frequency")
    eq(quantity_name("deg", ["MHz", "deg"]), "Angle")
    eq(quantity_name("ly", ["ly"]), "Distance")


@case
def test_two_units_of_one_quantity_keep_their_names_apart():
    """Celsius and kelvin are the same quantity and not the same domain -- a model that
    merges them is wrong by 273.15."""
    units = ["K", "degC"]
    eq(quantity_name("K", units), "TemperatureInK")
    eq(quantity_name("degC", units), "TemperatureInDegC")
    assert quantity_name("K", units) != quantity_name("degC", units)


@case
def test_a_reciprocal_gets_a_readable_name():
    eq(quantity_name("1/s", ["1/s"]), "Rate")
    assert "/" not in quantity_name("1/s", ["1/s", "1/h"])


@case
def test_an_unknown_unit_still_produces_a_name():
    assert quantity_name("furlong", ["furlong"])


# --------------------------------------------------------------------------- segmentation

@case
def test_a_squashed_token_is_cut_into_known_pieces():
    eq(segment("freqmhz", VOCAB), ["freq", "mhz"])
    eq(segment("deptcode", VOCAB), ["dept", "code"])
    eq(segment("avgqty", VOCAB), ["avg", "qty"])
    eq(segment("signalregistry", VOCAB), ["signal", "registry"])


@case
def test_a_token_that_does_not_fully_decompose_is_left_alone():
    """The safety property. `category` starts with `cat` and finishes with nothing known, so
    a greedy cut would produce `catalogue` + rubbish. Full decomposition or nothing."""
    for token in ("category", "catalogue", "status", "sigstrdb", "telescref"):
        eq(segment(token, VOCAB), None, token)


@case
def test_a_single_piece_is_not_a_segmentation():
    eq(segment("signal", VOCAB), None, "one known word is not a squashed compound")


@case
def test_a_short_token_is_never_cut():
    for token in ("id", "abc", "key"):
        eq(segment(token, VOCAB), None, token)


# --------------------------------------------------------------------------- expansion

@case
def test_a_compound_is_written_out():
    """The one that started this: an observatory identified by an 'observstation' reads as
    identified by an observation. It is identified by its name -- an observation station."""
    eq(expand("observstation"), "observation station")


@case
def test_an_abbreviated_word_is_written_out():
    eq(expand("emp_name"), "employee name")
    eq(expand("dept_code"), "department code")
    eq(expand("avg_qty"), "average quantity")


@case
def test_a_squashed_token_is_segmented_then_expanded():
    eq(expand("analysisprio"), "analysis priority")
    eq(expand("obsdurhrs"), "observation duration hrs")


@case
def test_a_name_the_glossary_does_not_know_is_unchanged():
    """Half-understanding a name is worse than leaving it alone."""
    for name in ("category", "catalogue", "status", "telescref", "sigclasstype"):
        eq(expand(name), name, name)


@case
def test_an_abbreviation_never_fires_on_a_substring():
    """`cat` is in the table; `category` must survive it."""
    eq(expand("category"), "category")
    eq(expand("catalogue"), "catalogue")


@case
def test_a_user_glossary_adds_domain_words():
    """`sig` is a signal in one schema and a signature in the next, which is why it is not
    built in."""
    eq(expand("telescref", {"telesc": "telescope"}), "telescope ref")
    eq(expand("sigstr", {"sig": "signal", "str": "strength"}), "signal strength")


@case
def test_a_user_glossary_entry_of_several_words_is_a_compound():
    eq(expand("wkorder", {"wkorder": "work order"}), "work order")


@case
def test_reading_a_glossary_file():
    path = os.path.join(HERE, "_glossary.tmp")
    with open(path, "w") as fh:
        fh.write("# a comment\ntelesc = telescope\n\n  sig  =  signal \nbroken line\n")
    try:
        g = read_glossary(path)
        eq(g, {"telesc": "telescope", "sig": "signal"})
    finally:
        os.remove(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()
    cases = [c for c in CASES if not args.only or args.only in c.__name__]
    failed = 0
    for c in cases:
        try:
            c()
            if args.verbose:
                print("ok   %s" % c.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL %s\n       %s" % (c.__name__, e))
        except Exception as e:                                        # noqa: BLE001
            failed += 1
            print("ERROR %s\n       %s: %s" % (c.__name__, type(e).__name__, e))
    print("%d passed, %d failed" % (len(cases) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
