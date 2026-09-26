# `reverse/` — relational catalog → draft ORM model

Reads an existing database and derives a **draft** conceptual schema from it, so the
ConQuer-92 compiler has something to compile against without anyone facing a blank page in
NORMA.

```
reverse.py DB.sqlite -o out/                 SQLite, stdlib only
reverse.py --json catalog.json -o out/       a fixture, for tests
reverse.py --dsn "postgresql://..." -o out/  a live server's information_schema
```

Three files come out:

| File | What it is |
|---|---|
| `<name>.ccm.json` | The draft Common Core Model — **including the relational mapping** |
| `<name>.orm` | The same schema as a NORMA file, for viewing and validating (there is no importer back) |
| `<name>.report.md` | The worklist: what was guessed, what was skipped, what is blocked |

Exit status is 1 when there are blockers, so it drops into a build script.

## Why it emits CCM and not `.orm` directly

`relational-to-orm-reverse-engineering.md` §7 originally sketched catalog → `.orm` → human →
compiler. Going through the CCM instead is strictly better for one reason: **reverse
engineering is the only step that knows the relational mapping.** It has just read
`information_schema`; it knows that `Employee` is `EMPLOYEE.EMP_NR` and that
`EmployeeHasSalary` is absorbed into `EMPLOYEE.SALARY`. ORMCore cannot carry any of that
(`model/model.md` §6, A5) — so emitting `.orm` alone would throw the mapping away and force
the compiler to re-derive it by guessing Rmap in reverse.

The `.orm` file is still produced, because refinement happens in NORMA. It is the branch of
the pipeline a human edits; the `.ccm.json` is the branch the compiler reads.

```
information_schema ─► derive ─┬─► draft .orm ─► NORMA / Boston ─► refined .orm
                              │                                        │
                              └─► .ccm.json (schema + mapping) ◄───────┘
                                        │                        re-import
                                        ▼
                                 ConQuer compiler ─► SQL ─► rows
```

## The rules

The derivation inverts Halpin's Rmap; `relational-to-orm-reverse-engineering.md` is the
literature it came from. The confidence column is the whole point: only the **sound** rules are
recoverable from the catalogue alone.

| # | Catalog | ORM | Confidence | Applied? |
|---|---|---|---|---|
| 1 | Table with its own primary key | `EntityType`; simple key becomes the reference mode, composite key an external uniqueness constraint | sound | yes |
| 1b | No primary key, **two or more** foreign keys, other columns | an objectified fact type: the association, with the other columns hanging off it | heuristic | yes, **reported**: identifying it by the foreign keys assumes a uniqueness the catalogue does not declare |
| 1c | No primary key, **one** foreign key, other columns | entity type hanging off the referenced one, identified by its whole row (a relation is a set of tuples). BIRD's `Examination` table; a blocker until the pilot measured what that cost | heuristic | yes, **reported**; `--analyse-data` finds the real key |
| 1d | A single-column primary key **no foreign key references**, beside exactly one other column that foreign keys do | that column is the reference scheme; the declared key becomes a `UNIQUE` column beside it, which rule 5 states as the second identifier it is | population | **on request**: `--prefer-referenced-keys`, on a SQLite file. `orders` is keyed by `orderspivot`, a row number nothing mentions, and three tables reference `orders.recordvault`: the schema's own references say what an order is known by, and a question asking for "the order ID" meant the vault code (LiveSQLBench crypto_4). Verified against the rows before it is believed -- never null, never repeated -- because SQLite checks nothing and a quarter of declared foreign keys are contradicted by their data. Applied as a rewrite of the catalogue before the derivation, so nothing downstream knows. **Changes the model**, like 7b and 9c: a bare `Order` lists vault codes. 2 of the 175 tables in LiveSQLBench's SQLite tier are this shape (crypto's `orders` and `users`), and 2 in BIRD's eleven databases (card_games' `cards` and `sets`) -- where `cards` is keyed by `id`, referenced by `uuid`, and asked about by `id`, which is why it is never assumed. european_football_2's `Player` and `Team` are *not*: two different columns are referenced, the references disagree about what names an instance, and the rule says nothing |
| 2 | Non-key, non-FK column | binary fact type to a value type; mandatory iff `NOT NULL` | sound | yes |
| 3 | Foreign key | binary fact type to the referenced entity type | sound | yes |
| 4 | Key wholly foreign keys (2+) | n-ary fact type; objectified if it carries non-key columns or anything references it | sound *if keys are declared* | yes |
| 4d | No primary key, **every** column in a foreign key | a fact type whose roles are those foreign keys, identified by the whole row | sound | yes |
| 5 | `UNIQUE` on one column | uniqueness constraint on that role | sound | yes (composite reported) |
| 5c | A column **beside a declared key** that is never null, never repeats, and reads as a code (`CU338528`: text, one width, a short alphabetic prefix and a number) | a second identifier: a deontic uniqueness constraint on the *value* role | population | **on request**: `--infer-identifiers` (and `--infer-keys`, which has applied it since finding 151). Unique is not identifying -- of 323 unique non-key columns in LiveSQLBench's SQLite tier, 274 are measurements that happen not to repeat -- so the shape test is what keeps this at 2% of columns rather than 14%. Adds to the model and changes nothing in it, which is why it no longer needs the flag that does |
| 6 | `CHECK (c IN …)`, `CHECK (c BETWEEN …)` | value restriction | sound | yes (anything else reported) |
| 6b | A column holding a handful of distinct values over a large population | value restriction on the value type, from the data rather than a CHECK | population | **on request**: `--infer-domains` applies it and reports each one. Identifiers and references are excluded, and a value type reached by more than one column is reported and left alone |
| 6b′ | A path inside a document with a handful of distinct values | value restriction on the fact type rule 12 derived for it | population | **on request**, with `--infer-domains --infer-json`. The domain miner reads a *readable* -- a catalogue column or a document path -- by expression, so the same guards, the same sentinel stripping (6f) and the same applier serve both; a path is not a column of the catalogue, which is why every fact type rule 12 made had come out with no domain and a writer probed each with `./try`. 107 of the SQLite tier's 358 document fact types have one (finding 159) |
| 6c | A column the catalogue declares with **no type at all** | the conceptual type its data has, read with `typeof()` | population | **on request**, with `--infer-domains`. SQLite allows an untyped column and Spider 2.0's databases use it; the fallback called them text, so `--schema` printed `DriveId '1'` and a filter on it compared a string with an integer in a column with no affinity to convert either — zero rows, silently. A declared type is never second-guessed, however badly it fits: this speaks only where the catalogue is silent |
| 6e | Units in column names (`airtempc`, `objtempk`, `pulsepersec`) | a unit on the value type, and value types that share one merged into one domain | heuristic | **on request**: `--merge-domains`. A column name is the only record a schema keeps of its unit -- `airtempc` and `objtempk` are both temperatures, and nothing but the last letter says which scale. `model/names.py` recovers it, the CCM now has a slot for it (ORMCore calls it a UnitBased reference mode; the CCM had not copied it across), and `--merge-domains` folds value types sharing a unit into one. The unit is what makes the merge safe: merging on data type alone puts every `real` column in one domain. Celsius and kelvin stay apart -- one quantity, two domains, and a model that merges them is wrong by 273.15. A reciprocal is caught too, so `pulsepersec` is a rate rather than a duration. |
| 7 | Key is a single FK to another PK | subtype | heuristic | yes, **reported** |
| 8 | Discriminator column + nullable groups | subtypes flattened into one table | heuristic | **reported only** |
| 9 | Column name matches exactly one other table's single PK, same type, no FK declared | fact type | guess | **on request**: `--infer-fks` applies it and reports each one; a name matching several tables, or a type mismatch, is reported and left alone |
| 9a | A column declared nullable that is never null | a mandatory role | population | **on request**: `--infer-mandatory`. Bird's 3.9-a, mined since `_never_null` was written and used internally to pick identifiers, but never applied to the model -- the report said the role *may* be mandatory and stopped. Only where the population is significant |
| 9b | A table with **no declared key at all**, whose population supports one | primary key on the catalogue, before the derivation | population | **on request**: `--infer-keys`. Rule 1 reads no shape without a key, and **223 of the 412 tables in Spider 2.0's local databases declare neither key nor foreign key** — sixteen of those thirty databases derived to nothing. The candidates are the table's *minimal unique column combinations*, found by the level-wise search below; the choice among them is by name and shape. Measured by `tests/test_inference.py`: **94% recall at 97% precision** over BIRD mini-dev's eleven stripped schemas, 83% / 98% over eleven of Spider 2.0's |
| 5b | A column combination with no duplicates that rule 9b did *not* choose as the identifier | an **alternate key**: a uniqueness constraint on the role | population | **reported** by `--analyse-data` with `--infer-keys`. Already mined in the first pass and already used as a reference target; reporting it costs nothing and is model content that was being discarded |
| 6d | The same value domain held by two columns in different tables | one value type, not two | population | **reported** by `--analyse-data`. The derivation gives every column its own value type, which says two `status` columns are different kinds of thing. `cust.status, emp.status` holding exactly `'A', 'B'` is one domain read twice |
| 6f | A word standing in for NULL (`Unknown`, `not applicable`) in a column with a small domain | not a member of the value constraint; a NOT NULL column that uses one has an optional role | population | yes, wherever a domain is applied. `Unknown` fills 19-36% of five columns in one benchmark database, and rule 6b was enrolling it in the value constraint -- so the model asserted `Polarisation in {Linear, Circular, Elliptical, Unknown}` and "how many signals are polarised" answered 1000 where the truth is 742. `_dirt` had been reporting these since it was written and nothing consumed the finding. Stripping is unconditional wherever a domain is applied: a domain that admits its own null is wrong, not merely generous. Where the column was also declared NOT NULL, the role it carries stops being mandatory. |
| 9h | A column determined by a **non-key** column | a fact about *that* column's concept: an entity type the schema never declared | population | **reported** by `--analyse-data`. `zip_code (state -> short_state)` in student_club is the textbook case -- "California" determines "CA", so short_state is a fact about state and rule 2 would otherwise hang both off the zip code. Guarded on repetition: five distinct values of the determinant, three rows each on average, or a near-unique column determines everything and says nothing |
| 9k | A parent column that equals an aggregate over a child table | a **derivation rule** across a foreign key | population | **reported** by `--analyse-data`. `order.total = SUM(line.amount)` is the column most likely in any schema to be quietly stale, and a definition in the sense the benchmark measured. Parents with no children are left out: a stored 0 and a NULL both read as "none" |
| 9z | Two nullable columns always present together and absent together | an **equality** constraint, the mirror of 9x | population | **reported** by `--analyse-data`. `satscores (AvgScrRead, AvgScrMath)` -- a school either has SAT data or does not. States the difference between "may be absent" and "may be half recorded" |
| 9f | A column that equals a formula over other columns of the same row | a **derivation rule** waiting to be written: the fact is derived, not asserted | population | **reported** by `--analyse-data`. `budget.amount = spent + remaining`, `loan.amount = duration * payments`, `full_name = given \|\| ' ' \|\| family`. This is the rule that attacks what the benchmark measured: definitions written down are worth eight points to a query writer, and a derived column is a definition the database already contains. Checked on 500 rows first, then in full, because the unsampled search took 108 seconds on one database |
| 9g | A self-reference that never points at itself, and never goes round | a **ring** constraint: irreflexive, and acyclic where the closure says so | population | **reported** by `--analyse-data`. Acyclic is the one worth having -- it is what says a reporting line terminates, and what a recursive derivation rule needs in order to |
| 9x | Two column groups in one table that are never filled together | an **exclusion** constraint, and the evidence rule 8 lacks | population | **reported** by `--analyse-data`. Rule 8 reads the shape of flattened subtypes off a column *named* `type` or `kind`; this reads it off the data. `party (abn, trading_as) / (family_name, given_name)` says there are two subtypes whatever the columns are called. Pairs are mined and groups are reported, because a group is what a modeller acts on |
| 9y | One column never greater than another of the same kind | a **value-comparison** constraint | population | **reported** by `--analyse-data`. `posts.CreationDate <= ClosedDate` is a business rule no catalogue states; five of them in codebase_community alone. Two dates are asked about on their own, two numbers only when their names claim to be the ends of one range (`min_`/`max_`, `start`/`end`) -- unfiltered, every numeric column is "never greater than" some other one, and california_schools proposed 49 led by `Charter School (Y/N) <= District Code` |
| 9c | A column whose values are all present in another table's key, where the *shape* of the match says reference | foreign key on the catalogue | population | **on request**, with `--infer-keys` on a SQLite file. Rule 9 reads a column's *name*; this reads its values — containment, coverage, type agreement and `_spread`, which is Zhang et al.'s randomness test. The scoring had been mined and reported since it was written and nothing ever applied it. **81% recall at 100% precision** on BIRD, against 54% recall for names alone. Finding 61 decomposes what it still misses: nine of the twenty are references the data itself refutes |
| 10 | Names: singularisation, prefix stripping, abbreviations, readings | every name in the model | guess | yes, **all reported**. Two fact types between the same pair of types that read the same are separated by an adjective read off the foreign key column, and where the columns say the same thing, off what the table name says beyond its two players (`races` and `races_ext` differ by "ext"). An n-ary fact type's first verb part is in that grouping too: without it, f1's `Race has Season` named two fact types and could reach neither |
| 10b | Squashed abbreviations (`observstation`) | the name written out, only where it decomposes completely into known pieces | guess | **on request**: `--expand-names`, with an optional `--glossary`. `observstation` is an observation station, which is what an observatory *is*; unexpanded it produces the value type `ObservatoryObservstation` and a reading that tells the reader an observatory is identified by an observation. A squashed token is cut only if it decomposes **completely** into known pieces, so `category` is never read as `cat` plus a remainder -- half-understanding a name is worse than leaving it alone. Domain words go in the glossary file rather than the built-in table, because `sig` is a signal in one schema and a signature in the next. |
| 12 | A JSON column whose documents are records: the same keys row to row | one fact type per leaf path, mapped to that path | population | **on request**: `--infer-json`. Maps (keys that are data) are reported, not derived; free-form bags are refused. `jsonshape.py` |

Rule 4 is the one hard prerequisite. It fails **silently** on a database with no declared
foreign keys — an association table just looks like an entity with a composite key. A schema
that declares none at all gets one report saying so.

An association's roles are **not** marked mandatory by rule 4. `assignment.emp_nr NOT NULL`
says every assignment names an employee — true of any fact by definition — not that every
employee has an assignment, which is what an ORM mandatory role asserts and what the data
usually refutes. The derivation asserted it until confluence's outer join ran into the
validator's objection; FORML had been verbalizing the false claim as "Each Employee has some
Project".

### Four shapes the rule table does not cover

Added after running the scenarios in `tests/scenarios/`. Each is common, each is a shape rules
1–10 get *silently* wrong rather than loudly wrong, and each has an innocent reading as well
as a suspicious one — so all four are reported, none applied.

| # | Shape | Why rule 4 misses it |
|---|---|---|
| 4b | Association table given a surrogate key | The key is no longer "wholly foreign keys", so it becomes an entity type. The tell is a `UNIQUE` covering exactly the foreign key columns — the natural key the surrogate replaced. |
| 4c | Primary key part foreign key, part something else | Weak entities, relationships versioned by a date, and multi-valued attributes all land here, and all three are usually fact types. The report distinguishes the three readings from what the non-key part looks like. |
| 2b | `phone1, phone2, phone3` | One multi-valued fact spread across numbered columns becomes *n* unrelated single-valued facts. |
| 3b | `owner_type` + `owner_id` | A polymorphic reference. No foreign key is declared and none is possible; in ORM it is usually a supertype. |

## What the draft is not

It is a draft. Halpin shipped this in Visio for Enterprise Architects and says so himself:

> "In practice, any draft ORM schema obtained by reverse engineering usually needs many
> refinements."

Concretely, in the fixture schema (`tests/company.sql`, 7 tables) the generator emits 6 entity
types, 19 value types, 22 fact types and 27 constraints, along with one blocker and fourteen
refinements. The refinements are not noise — every predicate reading is `{0} has {1}`, because
a relational catalog records no verbs at all. Renaming them is the first thing Halpin's chapter
8 tells you to do.

The one place the placeholder is not left standing is a **ring** fact type, both roles played
by one object type, where `Employee has Employee` says nothing and a query cannot even say
which way round it walks. There rule 10 reads the schema for a verb: a self-referencing column
`manager_nr` gives `{0} has manager- {1}`, the hyphen binding the adjective to the object type
as FORML 2 §1.2 has it, so the report says *"Each Employee has at most one manager Employee"*
and a query says `has manager Employee`, with `{0} is manager of {1}` read from the other end;
`bom(parent, child)` reads `is parent of` and `is child of`; a table called `connected` reads
`is connected to`. Each is a guess, and the report lists every one in words so it can be
checked the right way round.

## Layout

| File | |
|---|---|
| `relational-to-orm-reverse-engineering.md` | The literature the rules come from: Halpin's method, Bird's 1997 thesis, and what came after. |
| `catalog.py` | The normalised catalog, and the three backends. The rules never see a database. |
| `jsonshape.py` | Rule 12: the schema inside a JSON column — records, maps and bags. |
| `derive.py` | The rules, and the refinement report. |
| `reverse.py` | CLI. |
| `tests/company.sql` | A fixture chosen to exercise every rule, including the ones that must fail: a table with no primary key (blocker), a view, a 1:1 subtype candidate, an objectified association, and a discriminator-shaped table. |
| `tests/scenarios/*.sql` | Nine fixtures of real-world messiness: no declared foreign keys at all, reserved words, soft deletes, polymorphic references, EAV, surrogate-keyed associations, repeating groups, composite and self-referencing foreign keys, ternary associations, recursive many-to-many, and a 1:1 pair that is vertical partitioning rather than subtyping. Three of them render **the same conceptual model several ways** — subtypes three ways, keys two ways, a multi-valued fact three ways — so the derivation can be compared against itself. |
| `tests/test_rules.py` | **One case per derivation rule**, each on a minimal DDL that exercises that rule and nothing else, so a failure names the rule rather than the scenario. Covers rules 1-10, the four added shapes, both blockers, the naming functions and the relational mapping. 53 cases. |
| `tests/test_scenarios.py` | Asserts what comes out *and* what gets reported, including things that must **not** be reported. For the heuristic rules the report is the deliverable: a rule that silently guesses wrong is worse than one that says it guessed. |
| `population.py` | **Bird's Step 9**: reads the data as well as the catalogue and reports the constraints it supports — candidate foreign keys (subset constraints), candidate identifiers, candidate mandatory roles, and candidate value domains (rule 6b, ours rather than Bird's). `--analyse-data`, SQLite only. Every finding carries the population behind it, at confidence `population`, and is never applied. Measured against four databases that declare their foreign keys: **87% recall, 17% precision** alone; where the column *name* also points at the target, **100% precision at 77% recall** — two independently weak signals that are strong together. |
| `tests/test_population.py` | Step 9 on a fixture whose answers are known, including a column that is unique only by coincidence and must be reported rather than trusted. 37 cases. |
| `tests/scenarios/09-warehouse-wide-and-junk.sql` | Star-schema shapes, none of which had been tried: a keyless fact table with four foreign keys and measures (rule 1b, objectified by the measures — the right ORM reading of a star), a Kimball junk dimension, a 40-column repeating group, and a degenerate dimension. |
| `ormlint.py` | **Modelling quality, not well-formedness.** `model/validate.py` asks whether a model is structurally sound; this asks whether it is good ORM. Ten checks over identity, subtyping, constraints, readings and naming. Four of them take `--db` and *measure*, because the questions they ask are about the population rather than the schema: a subtype is a proper subset by definition, and only the data knows whether a partition is proper. Severities follow `validate.py` — `error` fails the file, `warning` and `note` report. |
| `tests/test_ormlint.py` | **Every check pinned twice: a model that has the defect and one that does not.** The negatives carry the weight. Three checks were false positives at corpus scale before the negatives caught them — a mandatory *value* role over a nullable column (vacuous: a value type's population excludes null), every FORML hyphen binding read as a mangled reading (177 of 177 correct), and an objectified fact type's identifier read as dangling (it is the objectified roles, which is what objectification means). 30 cases. |

## What the scenarios showed

Running them found four bugs and three gaps:

- **A composite identifier silently lost its foreign-key roles.** `n_order`, keyed
  `(cust_code, order_seq)`, was derived with a one-role identifier. Every weak entity, EAV
  table and versioned relationship was under-identified.
- **A composite foreign key was named after its first column.** `(cust_code, order_seq)`
  points at an Order, not at a "Cust".
- **"No declared foreign keys" was reported per table**, so a lookup table that legitimately
  has none produced the same warning as a schema that has none anywhere — burying the signal
  in the one fixture where it mattered.
- **A single-column key was described as composite** when that column happened to be a
  foreign key.
- The three gaps became rules 4b, 4c, 2b and 3b above.

Two results worth keeping in mind about the same model rendered several ways: subtyping is
recovered from a 1:1 foreign key (A), only *suspected* from a discriminator (B), and leaves
**no trace at all** when each concrete class gets its own table (C). And `flight_extra` is
vertical partitioning, not subtyping — but in the catalog the two are indistinguishable, so
rule 7 fires and says so. That is the correct behaviour, not a bug.

## How good are the guesses? Strip a schema that knows, and ask

`tests/test_inference.py` is the answer to "does any of this work". A database that *does*
declare its keys is a labelled set: remove the declarations from the catalogue, run the
inference against the data alone, and compare. That is how the literature reports this --
Jiang & Naumann's HoPF (JIIS 54:439-461, 2020) retrieves 88% of primary keys and 91% of
foreign keys -- and it is the only way to know whether a rule is finding keys or inventing
them.

**Name the corpus with the number.** The inference leans on naming convention, so the same
code scores very differently on schemas that follow one and schemas that do not. Two corpora,
both reproducible, measured with the command above:

| corpus | primary keys | foreign keys |
|---|---|---|
| BIRD mini-dev, 11 databases, 75 tables (`bench/fetch.sh` gets it) | **94% recall, 97% precision** | **81% recall, 100% precision** |
| Spider 2.0, the 11 local schemas that declare keys, 156 tables | 83% recall, 98% precision | 69% recall, 97% precision |

Before rules 9b and 9c the same harness reported 75% / 96% for keys and 55% / 92% for
references, so the gain is real; an earlier write-up quoted 91% and 75% from a different,
easier selection of eleven Spider schemas, which is exactly the trap this table exists to
avoid.

`--why` is the other half of the harness: it classifies every declared reference the
inference does not recover, which is how recall moved from 53% to 81% (finding 61). A rate
with no decomposition says nothing about what to do next.

Precision is the number that matters. A missing key costs one table; a wrong key is a wrong
identity in every query that walks it, and a wrong foreign key is a join that answers a
different question without saying so. The two remaining contradicted references are both
`Faculty_Categories.StaffID`, which the schema points at `Faculty` and the scoring points at
`Staff` -- a subtype sitting between the column and the table it is named after.

Scoring against *declared* foreign keys understates precision, because a schema's declared
set is usually incomplete: six more proposals are onto columns the schema declares nothing
for, and `match_games.winningteamid -> teams` is not a mistake there, it is an omission. Those
are counted apart rather than as errors.

## Known limits

- Composite `UNIQUE` and composite primary keys are reported rather than turned into external
  uniqueness constraints.
- `CHECK` parsing recognises `IN` and `BETWEEN`. Everything else is reported verbatim.
- Views are reported, never modelled. Chapter 8 concedes that treating a view as a fact type
  "is not strictly correct".
- The `information_schema` backend is written to the standard and tested only against the
  SQLite backend's output shape. It has not been run against a live PostgreSQL or SQL Server.
- A table with no declared key whose data supports no *named* identifier stays blocked, even
  where some column is unique. Rule 9b will not make a reference the identity of the table
  that holds it: a `played` table whose `album_id` happens not to repeat is a play log, not a
  one-to-one with album, and the population cannot tell the difference. Reported, not applied.
- **A table with duplicate rows has no key at any arity**, and 32 tables across Spider 2.0's
  thirty databases are in that position or close to it. Counted: 14 hold literally duplicated
  rows (`modern_data.trees`, 690,626 rows and 683,788 distinct), 10 are too small for their
  own data to be evidence, 2 are empty, and the rest have two or more equally good candidates
  and are refused for that. Only the last group is arguably a miss, and guessing between
  candidate identifiers is how a schema acquires a wrong identity.
