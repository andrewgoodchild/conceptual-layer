#!/usr/bin/env python3
"""Bird's Step 9 on a fixture whose answers are known.

`population.py` proposes constraints the catalogue does not declare, from the data. That is
guesswork with evidence attached, so the tests have to pin two different things: that it finds
what is there, and that it says how weak the finding is when the population cannot support it.

The fixture declares no foreign keys at all -- deliberately, because that is the situation the
module exists for and the situation of Bird's own case study (Appendix G.3).

    test_population.py [-v] [--only SUBSTRING]
"""

import argparse
import os
import tempfile
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import catalog as catalog_mod      # noqa: E402
import population as pop           # noqa: E402

SCHEMA = """
CREATE TABLE artist (artist_id INTEGER PRIMARY KEY, name TEXT NOT NULL, country TEXT);
CREATE TABLE album  (album_id INTEGER PRIMARY KEY, title TEXT NOT NULL, artist_id INTEGER,
                     label TEXT);
-- no primary key, no foreign keys: the shape that used to be a blocker
CREATE TABLE played  (album_id INTEGER, station TEXT, plays INTEGER);
-- a table so small nothing found in it can be evidence
CREATE TABLE tiny    (a INTEGER, b INTEGER);
-- Kimball's junk dimension: low-cardinality flags behind a surrogate key. A storage device,
-- which reverse engineering turns into an entity type claiming a business concept exists.
CREATE TABLE order_junk (junk_key INTEGER PRIMARY KEY, is_gift TEXT, is_rush TEXT,
                         channel TEXT, payment_type TEXT, priority TEXT);
-- no primary key, but one column is named like this table's own identifier: rule 9b
CREATE TABLE venue (venue_id INTEGER NOT NULL, venue_name TEXT NOT NULL, city TEXT);
-- an association with no key, no foreign keys and no single unique column: the identifier is
-- the two reference-looking columns together, which is the shape half of Spider 2.0 is in
CREATE TABLE album_venue (album_id INTEGER NOT NULL, venue_id INTEGER NOT NULL);
-- dirty values, the four shapes `_dirt` profiles. Nothing here is a constraint: it is what
-- a modeller needs told before trusting anything else, and one of it silently disables the
-- value-domain miner (finding 141).
CREATE TABLE pressing (pressing_id INTEGER PRIMARY KEY,
                       condition TEXT,      -- one enumeration in scrambled case
                       runtime   TEXT,      -- a quantity wearing its unit
                       notes     TEXT,      -- a stand-in for NULL
                       format    TEXT);     -- one value over the whole population
-- a declared foreign key the data does not satisfy
CREATE TABLE review (review_id INTEGER PRIMARY KEY, album_id INTEGER,
                     FOREIGN KEY (album_id) REFERENCES album(album_id));
-- two subtypes flattened into one table, with nothing in the column names to say so, plus a
-- range whose two ends are ordered and two numbers that are ordered only by accident
CREATE TABLE contract (contract_id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                       artist_id INTEGER, venue_id INTEGER,
                       runs_from DATE, runs_to DATE, seats INTEGER, margin INTEGER,
                       fee INTEGER);
-- three text columns that are not a concatenation of each other, which SQLite's coercion
-- rules used to say they were
CREATE TABLE person_name (person_id INTEGER PRIMARY KEY, given TEXT, family TEXT, nick TEXT);
-- a reporting line: never points at itself, never goes round
CREATE TABLE staff (staff_id INTEGER PRIMARY KEY, staff_name TEXT,
                    reports_to INTEGER REFERENCES staff(staff_id));
-- the same shape with a cycle in it: irreflexive, and NOT acyclic
CREATE TABLE clique (clique_id INTEGER PRIMARY KEY,
                     follows INTEGER REFERENCES clique(clique_id));
-- a stored aggregate (total) and a column that is not one (fee)
CREATE TABLE invoice (invoice_id INTEGER PRIMARY KEY, total INTEGER, fee INTEGER);
CREATE TABLE line (line_id INTEGER PRIMARY KEY,
                   invoice_id INTEGER REFERENCES invoice(invoice_id), amount INTEGER);
-- zip determines city; street is determined by nothing, and note is near-unique, which used
-- to make it "determine" everything it was compared with
CREATE TABLE address (address_id INTEGER PRIMARY KEY, zip TEXT, city TEXT, street TEXT,
                      note TEXT);
-- two columns always filled together, two that are never filled together, and one that is
-- filled independently of both
CREATE TABLE record (record_id INTEGER PRIMARY KEY, by_whom TEXT, at_when TEXT,
                     person_ref TEXT, company_ref TEXT, comment TEXT);
-- no declared key and two columns that could be one, so rule 9b picks and 5b reports the
-- other; `grade` shares its domain with `ticket.grade` and `size` does not share anything
CREATE TABLE entry (entry_no INTEGER NOT NULL, email TEXT NOT NULL, grade TEXT, size TEXT);
CREATE TABLE ticket (ticket_id INTEGER PRIMARY KEY, grade TEXT);
"""


def build(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # 60 artists, over the significance threshold; every album points at a real artist
    conn.executemany("INSERT INTO artist VALUES (?,?,?)",
                     [(i, "artist %d" % i, "AU" if i % 3 else None) for i in range(1, 61)])
    conn.executemany("INSERT INTO album VALUES (?,?,?,?)",
                     [(i, "album %d" % i, 1 + (i * 7) % 60, "label %d" % (i % 5))
                      for i in range(1, 121)])
    conn.executemany("INSERT INTO played VALUES (?,?,?)",
                     [(1 + (i * 11) % 120, "station %d" % (i % 9), i) for i in range(1, 91)])
    conn.executemany("INSERT INTO tiny VALUES (?,?)", [(1, 1), (2, 2), (3, 3)])
    # 60 rows so the population is significant; `condition` is two values in many spellings,
    # `runtime` a number with a unit, `notes` a sentinel, `format` constant.
    spellings = ["MINT", "Mint", "mInT", "mint", "MiNt", "miNT"]
    conn.executemany("INSERT INTO pressing VALUES (?,?,?,?,?)",
                     [(i, spellings[i % len(spellings)] if i % 2 else "USED",
                       "%d minutes" % (30 + i), "N/A" if i % 7 == 0 else "seen",
                       "vinyl") for i in range(1, 61)])
    # One row per distinct combination, which is what makes it a junk dimension rather than
    # a table that merely has repetitive columns: 2 x 2 x 3 x 2 x 3 = 72 rows.
    import itertools
    combos = list(itertools.product("YN", "YN", ("web", "store", "phone"),
                                    ("card", "cash"), ("high", "normal", "low")))
    conn.executemany("INSERT INTO order_junk VALUES (?,?,?,?,?,?)",
                     [(i,) + c for i, c in enumerate(combos, 1)])
    conn.executemany("INSERT INTO venue VALUES (?,?,?)",
                     [(i, "venue %d" % i, "city %d" % (i % 4)) for i in range(1, 61)])
    # each album played at three venues: neither column alone identifies a row, both do
    conn.executemany("INSERT INTO album_venue VALUES (?,?)",
                     [(1 + (i // 3), 1 + (i % 60)) for i in range(180)])
    # 40 reviews, ten of them pointing at albums that do not exist
    conn.executemany("INSERT INTO review VALUES (?,?)",
                     [(i, i if i <= 30 else 500 + i) for i in range(1, 41)])
    # a recording contract names an artist, a residency names a venue, and never both; the
    # dates are a real range; seats is always below fee, which is a coincidence of units
    conn.executemany("INSERT INTO contract VALUES (?,?,?,?,?,?,?,?,?)",
                     [(i, "recording" if i % 2 else "residency",
                       i if i % 2 else None, None if i % 2 else i,
                       "2024-01-%02d" % (i % 28 + 1), "2024-06-%02d" % (i % 28 + 1),
                       100 + i, 7 * i, 100 + i + 7 * i) for i in range(1, 81)])
    conn.executemany("INSERT INTO person_name VALUES (?,?,?,?)",
                     [(i, "G%d" % i, "F%d" % i, "N%d" % i) for i in range(1, 81)])
    conn.executemany("INSERT INTO staff VALUES (?,?,?)",
                     [(i, "s%d" % i, None if i <= 3 else i // 3) for i in range(1, 81)])
    # 1 -> 2 -> 3 -> 1 is a cycle; nothing points at itself
    conn.executemany("INSERT INTO clique VALUES (?,?)",
                     [(i, (i % 3) + 1 if i <= 3 else i - 1) for i in range(1, 81)])
    conn.executemany("INSERT INTO invoice VALUES (?,?,?)",
                     [(i, 3 * (10 + i), 7 + i % 5) for i in range(1, 81)])
    conn.executemany("INSERT INTO line VALUES (?,?,?)",
                     [(i * 10 + j, i, 10 + i) for i in range(1, 81) for j in range(3)])
    conn.executemany("INSERT INTO address VALUES (?,?,?,?,?)",
                     [(i, "Z%d" % (i % 8), "C%d" % (i % 8), "S%d" % i, "note %d" % i)
                      for i in range(1, 81)])
    conn.executemany("INSERT INTO entry VALUES (?,?,?,?)",
                     [(i, "e%d@x" % i, "ABC"[i % 3], "XY"[i % 2]) for i in range(1, 81)])
    conn.executemany("INSERT INTO ticket VALUES (?,?)",
                     [(i, "ABC"[i % 3]) for i in range(1, 81)])
    conn.executemany("INSERT INTO record VALUES (?,?,?,?,?,?)",
                     [(i, "u%d" % i if i % 3 == 0 else None,
                       "t%d" % i if i % 3 == 0 else None,
                       "p%d" % i if i % 2 else None, None if i % 2 else "c%d" % i,
                       "note" if i % 5 else None) for i in range(1, 81)])
    conn.commit()
    return conn


def find(analysis, kind, table, column, target=None):
    for f in analysis.of_kind(kind):
        if f.table.casefold() == table.casefold() \
                and [c.casefold() for c in f.columns] == [column.casefold()] \
                and (target is None or f.target_table.casefold() == target.casefold()):
            return f
    return None


def constraint_cases(a):
    """The two constraint kinds mined from the population rather than the catalogue."""
    ex = [f for f in a.of_kind("exclusion") if f.table == "contract"]
    pair = {frozenset(f.columns) for f in ex}
    yield ("two columns never filled together are an exclusion constraint",
           frozenset(("artist_id", "venue_id")) in pair,
           "contract (artist_id, venue_id): %d pair(s) found" % len(ex))

    cmps = {(f.columns[0], f.columns[1]) for f in a.of_kind("comparison")}
    yield ("a range's two ends are a value-comparison constraint",
           ("runs_from", "runs_to") in cmps, "contract runs_from <= runs_to")

    # Every number is below some other number somewhere. On one BIRD schema the unfiltered
    # search proposed 49 of these, led by `Charter School (Y/N) <= District Code`.
    yield ("two numbers ordered by coincidence are not proposed",
           ("seats", "fee") not in cmps and ("fee", "seats") not in cmps,
           "seats/fee: %s" % ("not proposed" if ("seats", "fee") not in cmps else "PROPOSED"))

    comp = {(f.table, f.columns[0], f.values[0]) for f in a.of_kind("computed")}
    yield ("a stored computation is found, and is a derivation rule waiting to happen",
           ("contract", "fee", "seats + margin") in comp,
           "contract.fee = seats + margin; %d formula(s) found" % len(comp))

    # SQLite coerces text to 0 in arithmetic, so `ABS('a' - ('b' || 'c'))` is 0 and every
    # concatenation of anything looks like an identity. That found 67 formulas on one schema.
    yield ("text is compared as text, not coerced to zero",
           not [c for c in comp if c[0] == "person_name"],
           "person_name proposes %d" % len([c for c in comp if c[0] == "person_name"]))

    rings = {(f.table, f.columns[0]): f.values for f in a.of_kind("ring")}
    yield ("a self-reference that never loops or cycles is a ring constraint",
           rings.get(("staff", "reports_to")) == ["irreflexive", "acyclic"],
           "staff.reports_to: %s" % (rings.get(("staff", "reports_to")) or "nothing"))

    yield ("a self-reference with a cycle in it is not called acyclic",
           rings.get(("clique", "follows")) == ["irreflexive"],
           "clique.follows: %s" % (rings.get(("clique", "follows")) or "nothing"))

    # -- rule 9k, an aggregate across a foreign key ------------------------------------
    agg = {(f.table, f.columns[0], f.values[0]) for f in a.of_kind("aggregate")}
    yield ("a stored aggregate of a child table is found",
           ("invoice", "total", "SUM(amount) over line") in agg,
           "invoice.total = SUM(line.amount)")

    yield ("a column that is not an aggregate of anything is not proposed",
           not [x for x in agg if x[1] == "fee"], "invoice.fee: %d proposal(s)"
           % len([x for x in agg if x[1] == "fee"]))

    # -- rule 9h, a column determined by a non-key column ------------------------------
    fds = {(f.table, f.columns[0], f.columns[1]) for f in a.of_kind("dependency")}
    yield ("a column determined by a non-key column is a hidden fact type",
           ("address", "zip", "city") in fds, "address: zip -> city")

    yield ("a column determined by nothing is not proposed",
           not [x for x in fds if x[0] == "address" and x[2] == "street"],
           "address.street: %d determinant(s)"
           % len([x for x in fds if x[0] == "address" and x[2] == "street"]))

    # A near-unique determinant determines everything and says nothing. `budget.remaining ->
    # category` held on 52 real rows for no reason but that remaining is a decimal.
    yield ("a near-unique column does not get to determine everything",
           not [x for x in fds if x[0] == "address" and x[1] == "note"],
           "address.note determines %d thing(s)"
           % len([x for x in fds if x[0] == "address" and x[1] == "note"]))

    # -- rule 9z, always present together ----------------------------------------------
    eqs = {(f.table, frozenset(f.columns)) for f in a.of_kind("equality")}
    yield ("two columns always filled together are an equality constraint",
           ("record", frozenset(("by_whom", "at_when"))) in eqs, "record (by_whom, at_when)")

    yield ("a column filled independently of them is not in an equality",
           not [x for x in eqs if "comment" in x[1]],
           "record.comment: %d equality(s)" % len([x for x in eqs if "comment" in x[1]]))

    # -- and the two constraint kinds do not confuse each other -------------------------
    exc = {(f.table, frozenset(f.columns)) for f in a.of_kind("exclusion")}
    yield ("columns that exclude each other are not also called equal",
           ("record", frozenset(("person_ref", "company_ref"))) in exc
           and ("record", frozenset(("person_ref", "company_ref"))) not in eqs,
           "record (person_ref, company_ref): exclusion only")

    yield ("columns that are equal are not also called exclusive",
           ("record", frozenset(("by_whom", "at_when"))) not in exc,
           "record (by_whom, at_when): equality only")

    yield ("a table below the threshold proposes neither",
           not [f for f in a.of_kind("exclusion") + a.of_kind("comparison") if f.table == "tiny"],
           "tiny is three rows")


def cases(a):
    """(name, ok, note) for each assertion."""
    yield ("a real reference is proposed from the data alone",
           find(a, "inclusion", "album", "artist_id", "artist") is not None,
           "album.artist_id -> artist.artist_id")

    f = find(a, "inclusion", "album", "artist_id", "artist")
    yield ("and the column name corroborates it", bool(f and f.corroborated),
           "name agrees with containment -- the pairing that measured 100% precision")
    yield ("the evidence names the population", bool(f and "120 rows" in f.evidence),
           f.evidence if f else "")
    yield ("a well-populated finding is significant", bool(f and f.significant), "")

    # `played` has no declared key. Its `plays` column happens to hold 90 distinct values, so
    # the data says it identifies a row -- and it does not: it is a play count that is unique
    # only because this fixture numbered them 1..90. That is Bird's "holds by coincidence
    # rather than by necessity" in miniature, and the correct behaviour is to report it (a
    # human can see what `plays` means; the algorithm cannot) rather than to hide or trust it.
    yield ("an accidentally-unique column is still proposed as a candidate identifier",
           find(a, "unique", "played", "plays") is not None,
           "played.plays is unique by coincidence -- reported for a human to reject")
    yield ("a column with real duplicates is not proposed",
           find(a, "unique", "played", "station") is None,
           "9 stations over 90 rows")
    yield ("a table that declares a key is not second-guessed",
           not [f for f in a.of_kind("unique") if f.table.casefold() in ("album", "artist")],
           "album and artist have primary keys; their data is not asked")

    yield ("a column that is never null is proposed as mandatory",
           find(a, "never-null", "album", "title") is None,   # title is already NOT NULL
           "already mandatory in the catalogue, so not re-reported")
    yield ("a nullable column that is never null IS proposed",
           find(a, "never-null", "album", "label") is not None,
           "album.label is nullable and never null")
    yield ("a nullable column that IS null is not proposed",
           find(a, "never-null", "artist", "country") is None,
           "artist.country contains nulls")

    small = [f for f in a.findings if f.table == "tiny"]
    yield ("findings from a tiny population are reported, not hidden",
           all(not f.significant for f in small),
           "%d finding(s) on `tiny`, none significant" % len(small))
    yield ("and they say so in their evidence",
           all("too few to be evidence" in f.evidence for f in small), "")

    yield ("a column that identifies its own table is separated, not mixed in",
           all(f.table.casefold() != "album" or f.columns[0].casefold() != "album_id"
               for f in a.of_kind("inclusion")),
           "album.album_id findings go to the weaker inclusion-1to1 bucket")

    # Zhang et al.'s randomness feature. album.artist_id draws 60 artists out of 60, scattered
    # across the whole table; a clustered inclusion would score near zero. It is the one signal
    # that survives a schema whose names carry no information.
    yield ("a real reference scores high on spread",
           bool(f and "spread" in f.signals),
           "values sit in the target like a sample, not a run")
    yield ("the proposal is preferred, and it is the only one for that column",
           bool(f and f.preferred)
           and len([x for x in a.of_kind("inclusion")
                    if x.table == "album" and x.columns[0] == "artist_id" and x.preferred]) == 1,
           "one target per column, globally resolved")

    # Kimball shapes. The catalogue cannot see either of these: a junk dimension is an
    # ordinary table with a surrogate key, and a violated foreign key is a *declared* one.
    j = [x for x in a.of_kind("junk") if x.table.casefold() == "order_junk"]
    yield ("a junk dimension is recognised from its data",
           bool(j), "every non-key column is a flag, one row per combination")
    yield ("the junk finding is significant when the population supports it",
           bool(j) and j[0].significant, "72 rows, one per combination")
    yield ("and a real entity table is not mistaken for one",
           not [x for x in a.of_kind("junk") if x.table.casefold() in ("album", "artist")],
           "album and artist have high-cardinality columns")

    vi = [x for x in a.of_kind("violated") if x.table.casefold() == "review"]
    yield ("a declared foreign key the data contradicts is reported",
           bool(vi) and vi[0].distinct == 10,
           "10 of 40 reviews point at albums that do not exist")
    yield ("that finding is proof, not evidence, so it does not need a big population",
           bool(vi), "a counter-example settles it however few rows there are")

    # -- value domains: ORM's value constraint, proposed from the population -------------
    d = find(a, "value-domain", "album", "label")
    yield ("a column with a handful of values over a big population is a domain",
           d is not None and d.values == ["label 0", "label 1", "label 2", "label 3", "label 4"],
           "album.label holds 5 labels across 120 rows")
    yield ("and it is significant enough to act on", bool(d and d.significant), "")
    yield ("a station list is a domain too",
           bool(find(a, "value-domain", "played", "station")),
           "9 stations over 90 rows")
    yield ("a nearly-unique column is not a domain",
           find(a, "value-domain", "played", "plays") is None,
           "90 distinct values over 90 rows is a sample, not an enumeration")
    yield ("a declared foreign key is not a domain",
           find(a, "value-domain", "review", "album_id") is None,
           "its values are the target's keys; the constraint that matters is the inclusion")
    yield ("a proposed foreign key is not a domain either",
           find(a, "value-domain", "played", "album_id") is None,
           "rule 9d has already claimed it")
    yield ("a primary key is not a domain",
           find(a, "value-domain", "artist", "artist_id") is None, "")
    yield ("a column with one value and nulls is not a domain",
           find(a, "value-domain", "artist", "country") is None,
           "artist.country is 'AU' or absent: one value is not a choice")
    small = [f for f in a.of_kind("value-domain") if f.table == "tiny"]
    yield ("a domain from a tiny population is reported, not hidden",
           all(not f.significant for f in small),
           "%d on `tiny`, none significant" % len(small))
    junky = find(a, "value-domain", "order_junk", "channel")
    yield ("a junk dimension's flags are domains",
           junky is not None and junky.values == ["phone", "store", "web"], "")

    yield ("nothing is ever reported as sound",
           all(getattr(f, "kind", "") != "sound" for f in a.findings), "by construction")


def key_cases(analysis, cat):
    """Rule 9b applied, not merely reported: `apply_keys` mutates the catalogue before the
    derivation, because rule 1 reads no shape at all from a table with no key."""
    before = {t.name: list(t.primary_key) for t in cat.tables}
    applied = dict((t, cols) for t, cols, _ in pop.apply_keys(analysis, cat))

    yield ("a column named like its own table's identifier becomes the key",
           applied.get("venue") == ["venue_id"], str(applied.get("venue")))
    yield ("an association with no single unique column is keyed by both references",
           applied.get("album_venue") == ["album_id", "venue_id"],
           str(applied.get("album_venue")))
    yield ("a column unique only by coincidence, and not named like an identifier, is not",
           "played" not in applied,
           "played.plays is unique here and means nothing; rule 9b leaves it to the report")
    yield ("a table too small for its data to be evidence is left alone",
           "tiny" not in applied, "")
    yield ("a table that declares a key is not second-guessed",
           all(t.primary_key == before[t.name] for t in cat.tables
               if before[t.name] and t.name not in applied), "")
    yield ("the catalogue now carries the keys, which is what rule 1 reads",
           next(t for t in cat.tables if t.name == "venue").primary_key == ["venue_id"], "")


def partition_cases(path):
    """`partitions` separates rule 7's two readings, which only the population can.

    Built on its own database rather than the shared fixture: the distinction is entirely a
    matter of how many rows each side holds, so the fixture has to say so precisely.
    """
    db = tempfile.mktemp(suffix=".sqlite")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE party (id INTEGER PRIMARY KEY, nm TEXT);
        -- every party is here: the same instance's other columns
        CREATE TABLE party_audit (id INTEGER PRIMARY KEY REFERENCES party(id), seen DATE);
        -- only some parties are here, and the rest are in party_org: real subtyping
        CREATE TABLE party_person (id INTEGER PRIMARY KEY REFERENCES party(id), dob DATE);
        CREATE TABLE party_org (id INTEGER PRIMARY KEY REFERENCES party(id), abn TEXT);
        -- not a candidate at all: its key is its own, not a foreign key
        CREATE TABLE note (note_id INTEGER PRIMARY KEY, party_id INTEGER REFERENCES party(id));
        INSERT INTO party VALUES (1,'a'),(2,'b'),(3,'c'),(4,'d');
        INSERT INTO party_audit  VALUES (1,'2024-01-01'),(2,'2024-01-02'),
                                        (3,'2024-01-03'),(4,'2024-01-04');
        INSERT INTO party_person VALUES (1,'1990-01-01'),(2,'1991-01-01');
        INSERT INTO party_org    VALUES (3,'123'),(4,'456');
    """)
    conn.commit()
    try:
        found = {c: (p_, cn, pn, ok)
                 for c, p_, cn, pn, ok in pop.partitions(conn, catalog_mod.from_sqlite(db))}

        yield ("a 1:1 table holding every parent row is a vertical partition",
               found.get("party_audit", (None,))[-1] is True,
               "party_audit: %s" % (found.get("party_audit"),))

        yield ("a 1:1 table holding half the parent rows is not",
               found.get("party_person", (None,))[-1] is False,
               "party_person: %s" % (found.get("party_person"),))

        yield ("sibling subtypes that partition the parent between them are both kept",
               found.get("party_person", (None,))[-1] is False
               and found.get("party_org", (None,))[-1] is False,
               "person 2/4 and org 2/4 of party")

        yield ("a table with its own key is not a candidate",
               "note" not in found,
               "note has its own primary key")

        # An empty database is not evidence of subtyping, but it is not evidence against it
        # either, and absorbing on no evidence would silently flatten a real hierarchy.
        empty = tempfile.mktemp(suffix=".sqlite")
        econn = sqlite3.connect(empty)
        econn.executescript("""
            CREATE TABLE party (id INTEGER PRIMARY KEY);
            CREATE TABLE person (id INTEGER PRIMARY KEY REFERENCES party(id), dob DATE);
        """)
        econn.commit()
        try:
            rows = pop.partitions(econn, catalog_mod.from_sqlite(empty))
            yield ("with no rows at all nothing is called a partition",
                   rows and all(not r[-1] for r in rows),
                   "%d candidate(s), none absorbed" % len(rows))
        finally:
            econn.close()
            os.remove(empty)
    finally:
        conn.close()
        os.remove(db)


def reporting_cases(a, path):
    """Two rules that are about what the *report* says rather than what the data holds."""
    shared = pop.shared_domains(a)
    where = {tuple(sorted(w)) for w in shared.values()}
    yield ("one domain held by two columns is reported once, not as two value types",
           (("entry", "grade"), ("ticket", "grade")) in where,
           "entry.grade and ticket.grade: %d shared domain(s)" % len(shared))

    yield ("a domain only one column holds is not reported as shared",
           not [w for w in shared.values() if ("entry", "size") in w],
           "entry.size is not shared")

    # rule 5b needs the whole recovery, because an alternate key is only "alternate" once
    # rule 9b has chosen the other one. A fresh catalogue: recover() applies what it finds.
    cat = catalog_mod.from_sqlite(path)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    try:
        analysis, keys, _ = pop.recover(conn, cat)
    finally:
        conn.close()
    chosen = {t: cols for t, cols, _ in keys}
    alt = {(f.table, tuple(f.columns)) for f in analysis.of_kind("alternate-key")}
    # -- the data-quality profile: what the values say about themselves ------------------
    # Each of these is a way the data misleads a reader rather than a constraint it supports,
    # and each fires rarely enough on a real corpus to be read (finding 141). The signals are
    # asserted here and NOT on the clean tables, because a profiler that flags everything is
    # the wallpaper finding 128 warns about -- `numeric-text` first matched every timestamp.
    q = {(f.table, f.columns[0], f.signals[0]) for f in a.of_kind("quality")}
    yield ("one enumeration in many spellings is reported",
           ("pressing", "condition", "case-variants") in q,
           "pressing.condition: %s" % sorted(x[2] for x in q if x[1] == "condition"))
    yield ("...and it collapses to the values it really has",
           sorted(next(f.values for f in a.of_kind("quality")
                       if f.columns[0] == "condition" and f.signals[0] == "case-variants"))
           == ["mint", "used"], "folded values")
    yield ("a quantity stored with its unit is reported",
           ("pressing", "runtime", "numeric-text") in q, "pressing.runtime")
    yield ("a stand-in for NULL is reported",
           ("pressing", "notes", "sentinel-null") in q, "pressing.notes")
    yield ("one value over the whole population is reported",
           ("pressing", "format", "constant") in q, "pressing.format")
    yield ("a clean column is reported as nothing",
           not [x for x in q if x[0] == "artist" and x[1] == "name"],
           "artist.name: %d signal(s)" % len([x for x in q if x[1] == "name"]))
    yield ("and a title is not mistaken for a quantity",
           ("album", "title", "numeric-text") not in q, "album.title")


    yield ("the unique column rule 9b did not choose is reported as an alternate key",
           ("entry", ("email",)) in alt or ("entry", ("entry_no",)) in alt,
           "entry: chose %s, reported %s" % (chosen.get("entry"),
                                             [c for t, c in alt if t == "entry"]))

    yield ("and the one it did choose is not reported as an alternate key",
           not [c for t, c in alt if t == "entry" and list(c) == chosen.get("entry")],
           "entry key %s is not also an alternate" % (chosen.get("entry"),))


def profile_cases():
    """Finding 166's additions to the profile, each pinned both ways: what the writers met and
    had to find by hand, and the near miss that must stay quiet."""
    yield ("a percentage stored as text is a quantity with its unit",
           bool(pop._NUMERIC_TEXT.match("0.30%")), "'0.30%'")
    yield ("...and a code like '1A' is not",
           not pop._NUMERIC_TEXT.match("1A"), "'1A'")
    mixed = ["2024-08-13", "2024-08-14", "2024/04/16", "2024/04/17", "Jan 17, 2025",
             "April 12th, 2024", "2024", "2025"]
    shapes = pop._date_formats(mixed)
    yield ("dates in several shapes are reported, one example each",
           len(shapes) >= 3 and any("YYYY alone" in s for s in shapes), "; ".join(shapes))
    yield ("...and one shape throughout is not",
           pop._date_formats(["2024-08-13", "2024-09-01", "2025-01-02"]) == [], "ISO only")
    pairs = pop._variant_pairs(["Status 1A", "Status 2", "2", "Status 3", "3"])
    yield ("a bare code beside the same code with a label is a pair of spellings",
           ("2", "Status 2") in pairs or ("Status 2", "2") in pairs, repr(pairs))
    yield ("a word beside a longer word it begins is a pair",
           bool(pop._variant_pairs(["own", "owned", "rented"])), "own / owned")
    yield ("...and 'Low' beside 'Very Low' is two values, not two spellings",
           pop._variant_pairs(["Low", "Very Low", "High"]) == [], "Low / Very Low")

    import sqlite3 as _sq
    conn = _sq.connect(":memory:")
    conn.executescript("""
        CREATE TABLE op (op_id TEXT PRIMARY KEY);
        CREATE TABLE disaster (d_id TEXT PRIMARY KEY);
        CREATE TABLE coord (c_id TEXT PRIMARY KEY, op_ref TEXT REFERENCES op(op_id),
                            d_ref TEXT REFERENCES disaster(d_id));
        CREATE TABLE fin (f_id TEXT PRIMARY KEY, op_ref TEXT REFERENCES op(op_id),
                          d_ref TEXT REFERENCES disaster(d_id));
        CREATE TABLE trip (t_id TEXT PRIMARY KEY, from_op TEXT REFERENCES op(op_id),
                           to_op TEXT REFERENCES op(op_id));
        INSERT INTO op VALUES ('o1'), ('o2');
        INSERT INTO disaster VALUES ('d1'), ('d2');
        INSERT INTO coord VALUES ('c1', 'o1', 'd1'), ('c2', 'o2', 'd2');
        INSERT INTO fin VALUES ('f1', 'o1', 'd1'), ('f2', 'o2', 'd1');
        INSERT INTO trip VALUES ('t1', 'o1', 'o2');""")
    tables = catalog_mod.from_sqlite_connection(conn).tables if hasattr(
        catalog_mod, "from_sqlite_connection") else None
    if tables is None:
        import tempfile
        path = tempfile.mktemp(suffix=".sqlite")
        disk = _sq.connect(path)
        conn.backup(disk)
        disk.close()
        tables = catalog_mod.from_sqlite(path).tables
    found = pop.routes(conn, tables)
    r = next((x for x in found if {x["a"], x["b"]} == {"disaster", "op"}), None)
    yield ("two tables each holding an operation and a disaster are two routes between them",
           r is not None and len(r["via"]) == 2, repr(found))
    # compared from the first table in name order, `disaster`: d1 is the one both routes
    # cover, and they disagree about it -- coord says o1, fin says o1 and o2
    yield ("...and where they overlap they are checked against each other",
           r is not None and r["overlap"] == 1 and r["disagree"] == 1,
           "overlap %s, disagree %s" % (r and r["overlap"], r and r["disagree"]))
    yield ("two keys from one table to the same table are roles, not routes",
           not [x for x in found if "trip" in [v[0] for v in x["via"]]], "trip.from_op / to_op")


def review_cases():
    """Finding 172's fixes, each pinned: what the model said wrongly or left out, and the
    near miss that must stay as it was."""
    import sqlite3 as _sq
    import tempfile
    from catalog import Catalog, ForeignKey, Table, Column, repair_crossed_keys

    # a composite key a dump listed as a cross product
    parent = Table("worksite", columns=[Column(n, "TEXT", True, i) for i, n in enumerate(("a", "c", "s"))],
                   primary_key=["a", "c", "s"])
    child = Table("cw", columns=[Column(n, "TEXT", True, i) for i, n in enumerate(("k", "wa", "wc", "ws"))],
                  primary_key=["k"],
                  foreign_keys=[ForeignKey([x], "worksite", [y])
                                for x in ("wa", "wc", "ws") for y in ("a", "c", "s")])
    cat = repair_crossed_keys(Catalog(tables=[parent, child]))
    fks = [(f.columns, f.ref_columns) for f in cat.table("cw").foreign_keys]
    yield ("nine single-column references onto a three-column key are one reference",
           fks == [(["wa", "wc", "ws"], ["a", "c", "s"])] and len(cat.repairs) == 1, repr(fks))
    two = Table("t2", columns=[Column("x", "TEXT", True, 0), Column("y", "TEXT", True, 1)],
                foreign_keys=[ForeignKey(["x"], "worksite", ["a"]),
                              ForeignKey(["y"], "worksite", ["c"])])
    cat = repair_crossed_keys(Catalog(tables=[parent, two]))
    yield ("...and two references that are not a full cross product are left alone",
           len(cat.table("t2").foreign_keys) == 2 and not cat.repairs, "x->a, y->c")

    # an answer is not an absence marker
    yield ("'Not available' beside 'Available' is an answer, kept",
           not pop._is_absent("Not available", ["Available", "Not available"]), "parking")
    yield ("...'Not available' with no positive form beside it still reads as absent",
           pop._is_absent("Not available", ["Yes", "No"]), "Yes / No")

    path = tempfile.mktemp(suffix=".sqlite")
    conn = _sq.connect(path)
    conn.executescript("""
        CREATE TABLE region (name TEXT PRIMARY KEY);
        CREATE TABLE house (h INTEGER PRIMARY KEY, zone INTEGER REFERENCES region(name));
        CREATE TABLE scans (sid TEXT PRIMARY KEY, proj TEXT REFERENCES project(p),
                            crew TEXT REFERENCES crew(c));
        CREATE TABLE cloud (cid TEXT PRIMARY KEY, proj TEXT REFERENCES project(p),
                            crew TEXT REFERENCES crew(c), pts INTEGER);
        CREATE TABLE project (p TEXT PRIMARY KEY);
        CREATE TABLE crew (c TEXT PRIMARY KEY);
        INSERT INTO region VALUES ('North'), ('South');
        INSERT INTO house VALUES (1, 3), (2, 7);
        INSERT INTO project VALUES ('P1'), ('P2');
        INSERT INTO crew VALUES ('C1'), ('C2');
        INSERT INTO scans VALUES ('s1', 'P1', 'C1'), ('s2', 'P1', 'C2'), ('s3', 'P2', 'C1');
        INSERT INTO cloud VALUES ('k1', 'P1', 'C1', 10), ('k2', 'P2', 'C1', 20);""")
    conn.commit()
    cat = catalog_mod.from_sqlite(path)
    verdicts = pop.verify_foreign_keys(conn, cat)
    yield ("a declared reference no row satisfies is dropped",
           any(v[0] == "house" and v[3] == "dropped" for v in verdicts)
           and not cat.table("house").foreign_keys, repr(verdicts))
    links = pop.shared_key_links(conn, cat)
    yield ("a pair unique in two tables, one inside the other, is a link",
           any(l[0] == "cloud" and l[2] == "scans" for l in links), repr(links))
    conn.close()
    os.remove(path)

    # the new value signals
    class Out:
        def __init__(self):
            self.findings = []
    out = Out()
    vals = ["x%d" % i for i in range(60)]
    pop._dirt_values("t", "c", 200, vals, out)
    yield ("a column null in most rows is said to be sparse",
           any(f.signals == ["sparse"] for f in out.findings), "140 of 200 null")
    out = Out()
    stamps = ["2024-03-%02d 1%d:00:00" % (1 + i % 5, i % 10) for i in range(60)]
    pop._dirt_values("t", "readts", 60, stamps, out)
    yield ("several rows to a date are said to be",
           any(f.signals == ["per-date"] for f in out.findings), "60 rows on 5 dates")
    out = Out()
    ids = ["user%d@x.com" % i for i in range(60)] + ["User1@x.com"]
    pop._dirt_values("t", "lawmail", 61, ids, out)
    yield ("identifiers that differ only by case are reported",
           any(f.signals == ["case-duplicates"] for f in out.findings), "user1 / User1")
    out = Out()
    pop._dirt_values("t", "speed_kmh", 60, ["%d.3 m/s" % i for i in range(60)], out)
    yield ("a unit in the values that contradicts the name is reported",
           any(f.signals == ["unit-conflict"] for f in out.findings), "km/h named, m/s held")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    path = os.path.join(HERE, ".population.sqlite")
    if os.path.exists(path):
        os.remove(path)
    conn = build(path)
    try:
        cat = catalog_mod.from_sqlite(path)
        a = pop.analyse(conn, cat)
        passed = failed = 0
        for name, ok, note in (list(cases(a)) + list(key_cases(a, cat))
                               + list(constraint_cases(a)) + list(reporting_cases(a, path))
                               + list(partition_cases(path)) + list(profile_cases())
                               + list(review_cases())):
            if args.only and args.only.lower() not in name.lower():
                continue
            if ok:
                passed += 1
                if args.verbose:
                    print("ok    %-56s %s" % (name, note))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, note))
        print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
        return 1 if failed else 0
    finally:
        conn.close()
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    sys.exit(main())
