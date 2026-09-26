#!/usr/bin/env python3
"""The relational mapping, end to end: does the SQL join the columns the schema says?

These cases exist because the BIRD pilot found a join that returned the wrong rows without a
word of complaint. A foreign key that targets a unique column rather than the primary key --
`legalities.uuid REFERENCES cards(uuid)`, `Player_Attributes.player_api_id REFERENCES
Player(player_api_id)` -- was joined to the primary key anyway. 32 of the 105 declared keys
in the BIRD development set are like that. So each case here builds a small database whose
identifiers are arranged to COLLIDE, derives the model, and checks the rows both ways round:
a wrong join is not an empty result here, it is a plausible wrong one.

    test_mapping.py [-v] [--only SUBSTRING]
"""

import argparse
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "reverse"))

import catalog as catalog_mod      # noqa: E402
import conquer as driver           # noqa: E402
import derive as derive_mod        # noqa: E402
import parser as parser_mod        # noqa: E402
import sql as sql_mod              # noqa: E402

# `card.api_id` is the unique key the foreign key points at; `card.id` is the primary key.
# The values are arranged so that attr.api_id = 1 collides with card.id = 1 (card A) while
# it actually belongs to card B (api_id = 1). A join on the primary key gives A the rows.
DDL = """
CREATE TABLE card (id INTEGER PRIMARY KEY, api_id INTEGER NOT NULL UNIQUE, name TEXT);
CREATE TABLE attr (id INTEGER PRIMARY KEY, api_id INTEGER REFERENCES card(api_id),
                   potential INTEGER);
CREATE TABLE colour (id INTEGER PRIMARY KEY, colour TEXT);
CREATE TABLE hero (id INTEGER PRIMARY KEY, name TEXT,
                   eye_colour_id INTEGER REFERENCES colour(id),
                   hair_colour_id INTEGER REFERENCES colour(id));
CREATE TABLE patient (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE exam (patient_id INTEGER REFERENCES patient(id), result INTEGER);
INSERT INTO card VALUES (1, 30, 'A'), (2, 1, 'B'), (3, 2, 'C');
INSERT INTO patient VALUES (1, 'P'), (2, 'Q');
INSERT INTO exam VALUES (1, NULL), (1, 5), (2, 7);
INSERT INTO attr VALUES (1, 30, 90), (2, 30, 80), (3, 1, 70);
INSERT INTO colour VALUES (1, 'Blue'), (2, 'Brown');
INSERT INTO hero VALUES (1, 'X', 1, 2), (2, 'Y', 2, 1), (3, 'Z', 1, 1);
"""


def same_as(sql):     return ("same_as", sql)
def sql_matches(rx):  return ("sql_matches", rx)
def sql_lacks(rx):    return ("sql_lacks", rx)


CASES = [
 # -- a foreign key to a unique column, both directions -------------------------------------
 ("forward: the key in hand references the target's unique column, not its id",
  "LIST n FROM Attr has Card has CardName n",
  same_as("SELECT c.name FROM attr a JOIN card c ON c.api_id = a.api_id")),
 ("forward: the join is written on the referenced column",
  "LIST n FROM Attr has Card has CardName n",
  sql_matches(r'card\d+\."api_id" = attr\d+\."api_id"')),
 ("forward: and not on the primary key, which would hand B's rows to A",
  "LIST n FROM Attr has Card has CardName n",
  sql_lacks(r'card\d+\."id" = attr\d+\."api_id"')),
 ("inverse: entering the fact type from the target joins its unique column too",
  "LIST n, p FROM Card has CardName n AND ALSO is of Attr has AttrPotential p",
  same_as("SELECT c.name, a.potential FROM card c JOIN attr a ON a.api_id = c.api_id")),
 ("inverse: the join is written on the referenced column",
  "LIST n, p FROM Card has CardName n AND ALSO is of Attr has AttrPotential p",
  sql_matches(r'attr\d+\."api_id" = card\d+\."api_id"')),
 ("a count agrees with the hand-written join",
  "THE COUNT OF Attr has Card",
  same_as("SELECT COUNT(*) FROM attr a JOIN card c ON c.api_id = a.api_id")),
 # A DEFINE keyed by an entity reached across the reference: its column must hold the
 # card's id, which is what the query using it joins on. It held `attr.api_id`, so the
 # join handed card B's total (api_id 1) to card A (id 1) -- finding 162, where PostgreSQL
 # refused it as `character varying = bigint`.
 ("a DEFINE keyed by an entity reached by reference carries its identifier",
  "DEFINE Pot ::= LIST c, t FROM Attr a has Card c AND ALSO a has AttrPotential p "
  "AND ALSO THE SUM OF p GROUPED BY c AS t\n"
  "LIST n, t FROM Card c has CardName n AND ALSO c has Pot PotT t",
  same_as("SELECT c.name, SUM(a.potential) FROM attr a JOIN card c ON c.api_id = a.api_id "
          "GROUP BY c.id, c.name")),

 # -- a keyless table (rule 1c) is identified by its row, so a NULL in it drops nothing ---
 ("a keyless table's rows are all there",
  "THE COUNT OF Exam", same_as("SELECT COUNT(*) FROM exam")),
 ("entering it from the entity it hangs off does not demand every column be filled",
  "THE COUNT OF Patient is of Exam", same_as("SELECT COUNT(*) FROM exam")),
 ("and the join asserts nothing about columns the path never reads",
  "THE COUNT OF Patient is of Exam", sql_lacks(r'"result" IS NOT NULL')),
 ("reading a value still requires it, as it should",
  "LIST r FROM Patient: 1 is of Exam has ExamResult r",
  same_as("SELECT result FROM exam WHERE patient_id = 1 AND result IS NOT NULL")),

 # -- two foreign keys to one table read by their columns (rule 10), inverse included -------
 ("two fact types between the same types read apart: has eye",
  "THE COUNT OF Hero has eye Colour has ColourColour: 'Blue'",
  same_as("SELECT COUNT(*) FROM hero h JOIN colour c ON c.id = h.eye_colour_id "
          "WHERE c.colour = 'Blue'")),
 ("and has hair",
  "THE COUNT OF Hero has hair Colour has ColourColour: 'Blue'",
  same_as("SELECT COUNT(*) FROM hero h JOIN colour c ON c.id = h.hair_colour_id "
          "WHERE c.colour = 'Blue'")),
 ("the inverse of a reading with an adjective keeps the adjective: is eye of",
  "THE COUNT OF Colour [has ColourColour: 'Blue'] is eye of Hero",
  same_as("SELECT COUNT(*) FROM hero h JOIN colour c ON c.id = h.eye_colour_id "
          "WHERE c.colour = 'Blue'")),
 ("and is hair of reaches the other fact type",
  "THE COUNT OF Colour [has ColourColour: 'Blue'] is hair of Hero",
  same_as("SELECT COUNT(*) FROM hero h JOIN colour c ON c.id = h.hair_colour_id "
          "WHERE c.colour = 'Blue'")),
]

INVERSES = [
 ("has", "is of"), ("have", "is of"), ("has fifa api", "is fifa api of"),
 ("has eye", "is eye of"), ("is connected to", None), ("has manager", "is manager of"),
]


def build():
    path = tempfile.mktemp(suffix=".sqlite")
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    conn.commit()
    model, _report = derive_mod.derive(catalog_mod.from_sqlite(path))
    return path, conn, model


def run(model, conn, lexicon, emitter, query, expect):
    kind, arg = expect
    try:
        _, statement, params = driver.transpile(model, query, lexicon, emitter)
    except (parser_mod.ParseError, sql_mod.SqlError) as e:
        return False, "%s: %s" % (type(e).__name__, e)
    if kind == "sql_matches":
        ok = re.search(arg, statement) is not None
        return ok, statement if not ok else "matches %r" % arg
    if kind == "sql_lacks":
        ok = re.search(arg, statement) is None
        return ok, statement if not ok else "lacks %r" % arg
    got = conn.execute(statement, params).fetchall()
    want = conn.execute(arg).fetchall()
    row = lambda r: tuple("" if v is None else str(v) for v in r)
    if sorted(row(r) for r in got) == sorted(row(r) for r in want):
        return True, "%d rows, matches reference" % len(got)
    return False, "got %r, reference %r\n        %s" % (got, want, statement)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    path, conn, model = build()
    try:
        lexicon = parser_mod.Lexicon(model)
        emitter = sql_mod.Emitter(model)
        passed = total = 0
        for name, query, expect in CASES:
            if args.only and args.only.lower() not in name.lower():
                continue
            total += 1
            ok, detail = run(model, conn, lexicon, emitter, query, expect)
            passed += ok
            if ok:
                print("ok    %-70s %s" % (name[:70], detail if args.verbose else ""))
            else:
                print("FAIL  %s\n        %s\n        %s" % (name, query, detail))
        for verb, want in INVERSES:
            name = "the inverse of %r is %r" % (verb, want)
            if args.only and args.only.lower() not in name.lower():
                continue
            total += 1
            got = parser_mod.Lexicon._inverse_of(verb)
            if got == want:
                passed += 1
                print("ok    %-70s" % name)
            else:
                print("FAIL  %s\n        got %r" % (name, got))
        print("\n%d passed, %d failed, %d total" % (passed, total - passed, total))
        return 0 if passed == total else 1
    finally:
        conn.close()
        os.unlink(path)


if __name__ == "__main__":
    sys.exit(main())
