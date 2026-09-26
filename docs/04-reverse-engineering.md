# 4 — Reverse engineering a database into a model

Most databases were built before anyone wanted a conceptual model of them, so the model has to
be recovered from what is there: the catalogue, and — where the catalogue is silent — the data.

```sh
python3 reverse/reverse.py company.sqlite -o out/ -n company
```

Three files come out:

| file | what it is |
|---|---|
| `company.ccm.json` | the draft model, including the relational mapping the compiler needs |
| `company.orm` | the same schema as a NORMA file, for viewing and validating |
| `company.report.md` | the worklist: what was guessed, what was skipped, what is blocked |

**The model is a draft.** The report exists because a draft that presents itself as an answer
is worse than no draft at all.

## How a table becomes a fact type

The rules invert Halpin's *Rmap* — the standard procedure for turning an ORM model into
tables — and follow L. J. Bird's 1997 thesis on relational reverse engineering. The whole
table is in [`reverse/README.md`](../reverse/README.md); the shape of it is:

| the catalogue says | the model gets | how sure |
|---|---|---|
| a table with a primary key | an entity type, identified by that key | **sound** |
| a plain column | a binary fact type to a value type; mandatory iff `NOT NULL` | **sound** |
| a foreign key | a binary fact type to the referenced entity type | **sound** |
| a key made entirely of foreign keys | an n-ary fact type, objectified if it carries other columns | **sound**, given declared keys |
| `UNIQUE` on a column | a uniqueness constraint | **sound** |
| `CHECK (c IN …)` | a value constraint | **sound** |
| a key that is a single foreign key | a subtype | *heuristic* |
| a discriminator column with nullable groups | subtypes flattened into one table | *reported only* |
| a column named like another table's key | a fact type | *guess*, `--infer-fks` |
| a 1:1 table holding *every* parent row | a vertical partition: its columns become facts about the parent, not a subtype | *population*, `--infer-partitions` |
| a JSON column whose keys are stable | one fact type per value inside it, typed as the data is, beside the document | *population*, `--infer-json` |
| a column beside the key that never repeats and reads as a code | a second identifier | *population*, `--infer-identifiers` |
| a primary key nothing references, beside one column every foreign key does | that column becomes the reference scheme; the key becomes the alternate | *population*, `--prefer-referenced-keys` — **changes** the model |
| a column declared nullable that is never null | a mandatory role | *population*, `--infer-mandatory` |
| a column, or a path inside a document, with a handful of values | a value domain, so the listing says how the code is spelled | *population*, `--infer-domains` |

Sound rules are applied silently. Heuristics are applied and reported. Guesses, and anything
read from the data, are only applied if you ask, and every one of them lands in the report
with the evidence behind it. The passes run in a declared order (`PASSES` in `reverse.py`),
and every model records the command that built it in its `_comment` — rebuild it with the
same flags and you get the same bytes.

Two of the population rules deserve a word, because they decide what a query writer is told.
**Identification**: an entity often has several id-shaped values — a registry code the other
tables reference, a client reference nothing does, a row number — and the writer asked for
"the customer ID" picks by the name. The model marks which is the preferred identifier, the
listing prints it, and where the declared key is referenced by nothing and one other column is
what every foreign key holds, `--prefer-referenced-keys` makes that column the identifier
(opt-in, because BIRD's `cards` is keyed by `id`, referenced by `uuid`, and asked about by
`id`). **Documents**: a `jsonb` column is a catalogue that stopped short. Rule 12 reads the
population, classifies the column as a record, a map or a bag, and turns a record into fact
types mapped to paths, so a query never mentions JSON. The document stays as a value type too,
described as one, for the paths the fields do not cover.

## What the data says that the catalogue does not

`--analyse-data` reads the population and proposes the constraints no DDL records. None of
these is applied; each is a claim for a human to confirm, because a population can refute a
constraint outright and can only ever make one plausible.

| | |
|---|---|
| **9f** | a column that is a formula over others — `total = qty * price` — which is a *derivation rule* the schema forgot |
| **9k** | a column that is an aggregate over a child table — `order.total = SUM(line.amount)` |
| **9h** | a column determined by a non-key column — `state → short_state`, an entity type nobody declared |
| **9x** | two column groups never filled together — an exclusion, and the evidence rule 8's name heuristic lacks |
| **9z** | two columns always filled together — an equality |
| **9y** | one column never greater than another — `CreationDate ≤ ClosedDate` |
| **9g** | a self-reference that never loops or cycles — a ring constraint |
| **5b**, **6d** | an alternate key; one value domain held by two columns |

Two of those matter more than the rest. **9f and 9k produce definitions**, which is the one
artefact [7 — What we measured](07-what-we-measured.md) found worth eight points. And each
proposal can be written back as a `violation` query on the constraint, so "confirm this" becomes
something `conquer.py --constraints` keeps asking as the data grows.

Names come last, and are the weakest part: every reading starts life as `{0} has {1}`, because
nothing in a database records what a relationship *says*. Fixing that is the first refinement,
and [2 — Modelling in ORM](02-modelling-in-orm.md#readings-are-the-user-interface) shows how.

## When the catalogue declares nothing

Plenty of real databases declare no keys at all. **223 of the 412 tables in Spider 2.0's local
databases declare neither a primary key nor a foreign key** — and rule 1 cannot read any shape
from a table without a key, so sixteen of those thirty databases derived to *nothing*.

Two rules recover what the catalogue does not say, by reading the data:

- **Rule 9b — the identifier.** Find the table's *minimal unique column combinations* by a
  level-wise search, then choose among them by name and shape: a column named after its own
  table is what a schema means by an identifier; a column named after *another* table is a
  reference, not an identity.
- **Rule 9c — the references.** A column whose values are all present in another table's key
  is a candidate foreign key. Containment alone is weak evidence, so it is scored: coverage,
  type agreement, the name, and the value-distribution test from Zhang et al. (VLDB 2010).

Both are behind `--infer-keys`, because they *change* the model rather than adding to it —
`tags.WikiPostId` stops being a value and becomes a reference — and that is a migration, not a
free upgrade.

Watch it on a two-table database that declares nothing:

```sh
sqlite3 nokeys.sqlite <<'SQL'
CREATE TABLE artist (artist_id INTEGER, name TEXT);
CREATE TABLE album  (album_id INTEGER, title TEXT, artist_id INTEGER);
SQL
python3 reverse/reverse.py nokeys.sqlite -o out/ -n nokeys
#   nokeys: 2 tables -> 0 entity types, 0 value types, 0 fact types, 0 constraints

python3 reverse/reverse.py nokeys.sqlite -o out/ -n nokeys --infer-keys --infer-fks
#   nokeys: 2 tables -> 2 entity types, 5 value types, 5 fact types, 7 constraints
```

and the report says what it did and what it wants from you:

```
- **`album (album_id)`** *(rule 9b)* — No primary key is declared, and album_id has no
  duplicate values (4 rows, 4 distinct values -- too few to be evidence) and is named like
  an identifier, so it is the one this draft uses.
  **Do:** Confirm and declare the key. Uniqueness in the current population is not
  uniqueness, and a wrong identifier is a wrong identity in every query that walks this table.
```

Note the phrase *"too few to be evidence"*. Bird's rule is that a population can refute a
constraint outright but can only ever make one plausible, so every finding carries the
population it was drawn from, and a small one says so.

## Is the guessing any good?

This is measurable, and the measurement is the point of
[`reverse/tests/test_inference.py`](../reverse/tests/test_inference.py). A database that
*does* declare its keys is a labelled set: strip the declarations out of the catalogue, run
the inference against the data alone, and compare with what was removed.

```sh
python3 reverse/tests/test_inference.py                      # the built-in fixture
python3 reverse/tests/test_inference.py --db one.sqlite two.sqlite   # a real corpus
```

The numbers this repository quotes are in
[7 — What we measured](07-what-we-measured.md#the-reverse-engineering-is-measured-like-the-literature-measures-it),
with the corpus each one was measured on — which matters more than it sounds, because the same
inference scores very differently on schemas that name things conventionally and schemas that
do not.

## What blocks a table

The report's *Blockers* section lists what stopped part of the derivation. The common ones:

- **No key and none inferable.** An event log with no identity at all is not a modelling
  failure; it genuinely has no entity type.
- **A view the catalogue cannot read.** One broken view no longer takes the schema down with
  it; it is reported and skipped.
- **A schema that declares no foreign keys at all.** Association tables then look like
  entities with composite keys, and nothing says otherwise. One report entry covers it.

---

Next: [5 — The toolchain](05-the-toolchain.md).
