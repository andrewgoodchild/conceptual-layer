# Does a better description help? A pre-registered retest

Written 26 September 2026, after `SCALE.md`'s round and before any writer in this one ran. The
results go in `bench/findings.md`, finding 167, and are compared against this page.

## What changed

Finding 166's writers named what the description lacked. Two kinds of fix were made, both as
general rules rather than for any one database:

**The profile** (`reverse/population.py`, `bench/livesql/build.py`):

- value domains inside JSON columns, which no profiled model had carried;
- the value cautions for paths inside JSON columns as well as for columns;
- a percentage stored as text (`'0.30%'`) counted as a quantity with its unit;
- dates stored as text in several shapes;
- values that look like two spellings of one (`'2'` and `'Status 2'`, `'own'` and `'owned'`);
- a column with one value on every row, now said in the listing;
- two things linked by several routes, and whether the routes agree in the data.

**The knowledge base** (`conquer.py --schema --knowledge`): the business terms a question uses,
with the columns most likely to hold what each is computed from, matched on shared words.

Not changed: how much the narrowed description shows. It is still about half the schema on
these models, which finding 166's writers found too large to read. This round measures the
content, with that size problem left in place.

## Design

**Sample.** Four databases none of the new rules was written against:
`archeology_scan` and `robot_fault_prediction` (never used by any round), and
`exchange_traded_funds` and `labor_certification_applications` (the first two alphabetically
of the six the earlier PostgreSQL rounds used). Ten `Query` tasks each by `pilot.py`'s own
procedure: **40 questions**, 30 of them using a term defined only in the knowledge base.

**Arms**, all SQL writers with the knowledge base and `./try`, differing only in `./schema`:

| arm | `./schema` prints |
|---|---|
| `sqlddlk` | the DDL narrowed to the question (`ddl_link.py`, 22 tables) |
| `sqldesc` | the description from the old profiled models (`work/models-profiled/`) |
| `sqldesc2` | the description from the new profiled models (`work/models-profiled2/`), with the business terms |

The old models for the two never-used databases were built from the code as it stood before
the changes, in a separate checkout, so `sqldesc` is the old description throughout.

**Writers.** One blind Claude Opus 5.5 writer per (arm, database), 12 in all, all launched
together, each told to keep drafts inside its own directory. Brief as `BRIEF.md`.

## Prediction

- **Primary.** `sqldesc2` scores at least **3 of 40** above `sqldesc`: the new content helps.
- **Kill.** `sqldesc2` − `sqldesc` of **0 or less**.
- **Secondary**, recorded but not predicted: `sqldesc2` against `sqlddlk`.
- **What 40 questions can say.** Little. On BIRD three identical runs spread over three
  points of 100; here a real difference smaller than about four questions cannot be told from
  noise, so a result between 1 and 2 is inconclusive and even a pass is a direction, not a size.
- **Honest prior.** About 35% on the primary. The additions address what writers said, but
  finding 166's misses were mostly the benchmark's own semantics, and the description is still
  too large to read.

## Result

Recorded after the run; the plan above is unchanged. **The prediction failed.** The new
description scored 12 of 40, the old 14 and the narrowed DDL 13: new against old, 0 questions
won and 2 lost, inside the kill criterion. Two cells were compromised by the permission system
(`archeology_scan`'s narrowed-DDL writer could not run queries; `labor_certification`'s
old-description writer could not use its description); without them the order is the same.
All four new-description writers named the business-term column hints as wrong, and they have
since been removed from `conquer.py`, so `sqldesc2` can no longer be rebuilt from this code. The details,
and what the writers credited, are in `bench/findings.md`, finding 167.

