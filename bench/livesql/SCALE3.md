# The layer's difference, not its restatement: a third pre-registered round

Written 27 September 2026, before any definer or writer ran. The results go in
`bench/findings.md`, finding 168, and are compared against this page.

## Why

Two rounds at scale (`SCALE.md`, `SCALE2.md`; findings 166, 167) found the conceptual
description no better than a narrowed DDL: 26 v 29 of 100, then 12 v 13 of 40. The writers
said why, and two of the reasons can be acted on:

1. **It was too large to read.** The narrowed description ran to about 80 kB, and writers
   skimmed it and found the structure themselves with queries. What they did credit -- value
   cautions, routes that disagree, date formats, units inside JSON -- was buried in a
   restatement of what the DDL already says. Yet before any writer ran, the model's linking
   had kept every gold table on 72 of 100 questions, against 51 for a DDL retriever of the
   same size.
2. **The misses were mostly business terms.** A definition's formula names quantities no
   column is called, and every writer mapped them alone, differently. Finding 167's fix --
   matching definitions to columns by shared words -- pointed the wrong way every time.

## What changed

**Option 1: the annotated DDL** (`conquer/annotate.py`). The model chooses the tables; the
writer reads them as DDL, with three sample rows cut to 160 characters; and beside each
column, as an SQL comment, goes only what the DDL does not say: the values it holds, what
profiling found, the fields inside a JSON column, and whether a table's join routes agree.
The view is cut to a budget of **16,000 characters** (about 4,000 tokens) -- a fifth of the
earlier description -- and names every table it leaves out.

**Option 2: the terms derived and checked** (`terms.py`, `DEFINE.md`). One blind definer per
database -- a Claude Opus 5.5 agent that never sees a question -- reads the knowledge base,
the annotated schema and the rows, and writes each business term's derivation in this
database: the SQL expression, what it ranges over, and a note where nothing holds what the
definition names. `terms.py check` then runs every derivation and records what came back.
The writers read each derivation, and its check, under the definition in `knowledge.md`.
This is an ORM derivation rule in the form a SQL writer reads; it is authored once, per
database, not per question.

**Budget calibration.** Set on development questions only (`calibrate_scale3.py`: the earlier
rounds' questions on organ_transplant, exchange_traded_funds and labor_certification, none of
them a test database). At 16,000 characters the annotated view kept every gold table on 16 of
30 questions, the plain view on 13; at 8,000, 12 against 11; at 24,000, 15 against 14. The
annotation takes room, so the annotated view shows fewer tables (median 7 against 11).
Where the model misses a table, it is nearly always one only a knowledge-base formula names.

## Design

**Sample.** Six test databases, none of which the annotation or the definer brief was
developed against: `museum_artifact`, `planets_data`, `solar_panel`, `sports_events`,
`archeology_scan`, `robot_fault_prediction` (each `_large`). Ten `Query` tasks each, drawn by
`pilot.py`'s procedure with seed 27: **60 questions**, 40 using a term defined only in the
knowledge base. 39 of them were drawn in earlier rounds too; the writers are new and blind.
`work/pilot-scale3/sample.json` lists them.

**Arms.** All SQL writers with the knowledge base and `./try`, differing only in `./schema`
and, for `annd`, in the knowledge base:

| arm | `./schema` prints | `knowledge.md` |
|---|---|---|
| `ddlp` | the DDL cut to 16,000 characters, tables chosen by `ddl_link.py`'s lexical scoring, no comments -- the control | the definitions |
| `ann` | the DDL cut to 16,000 characters, tables chosen by the model's linking, annotated from the profiled model | the definitions |
| `annd` | as `ann` | the definitions, each followed by its derivation and check |

The control is the same view, the same budget and the same list of what was left out; it
differs from `ann` in exactly what the layer contributes: which tables, and the comments.

**Writers.** One blind Claude Opus 5.5 writer per (arm, database), 18 in all, brief as
`BRIEF.md` with the `sqlddlk` schema paragraph. Definers first (six, one per database), then
every writer, all three arms of a database in the same batch.

**Scoring.** `score_scale.py` against the tier's gold, unchanged.

## Prediction

- **Primary 1.** `ann` scores at least **3 of 60** above `ddlp`. **Kill:** 0 or less.
- **Primary 2.** `annd` scores at least **3 of 60** above `ann`. **Kill:** 0 or less.
- Between 1 and 2 is inconclusive. On BIRD three identical runs spread over three points of
  100; here a difference smaller than about five questions cannot be told from noise, so even
  a pass is a direction, not a size.
- **Also recorded:** tokens and time per arm, and each definer's cost, which is paid once per
  database rather than per question.
- **Honest prior.** Primary 1 about 35%: the size problem is fixed, but agents that can query
  the database found the structure themselves in every earlier arm. Primary 2 about 40%: the
  business terms are where most answers were lost, but the definer is the same kind of model
  as the writers, and a derivation it gets wrong will be copied rather than questioned.

## Result

Recorded after the run; the plan above is unchanged, with one wording change to the brief
made before any writer ran: every arm's `./schema` paragraph says it prints "the DDL of the
tables your words are about, with sample rows under each, and names the tables it left out",
since the `sqlddlk` paragraph described a different view. The paragraph is the same in all
three arms.

**Both predictions failed.**

| | of 60 | without `planets_data` (50) | tokens | writer time |
|---|---|---|---|---|
| `ddlp`, plain DDL, 16,000 characters | 22 | 22 | 0.45M | 76 min |
| `ann`, annotated DDL | 25 | 19 | 0.45M | 58 min |
| `annd`, annotated DDL and derivations | 25 | 18 | 0.56M | 48 min |

- **Primary 1**, `ann` − `ddlp`: +3 of 60, at the threshold -- but every one of `ann`'s six
  wins is on `planets_data`, where the `ddlp` writer was blocked by the permission system on
  its second `./schema` call and submitted nothing. Without that database `ann` scores 19
  against 22 (0 won, 3 lost). The pass is the blocked cell, not the layer.
- **Primary 2**, `annd` − `ann`: 0 of 60 (2 won, 2 lost). Killed.
- On the three databases where no cell was compromised (museum, solar, robot; 30 questions):
  16, 13 and 14.

The six definers cost 0.64M tokens and 52 minutes together, once per database: 321 of 339
knowledge-base terms derived, every derivation run by `terms.py check`.

**Compromised cells**, all by tooling: `ddlp` on `planets_data` (blocked, no answers); `ann`
on `sports_events` (blocked from `./try` on its first call, ten untested answers); `ann` on
`archeology_scan` (a few row counts blocked); `ddlp` on `archeology_scan` (the Docker daemon
stopped mid-run, nine of ten answers untested). The details are in `bench/findings.md`,
finding 168.

What the writers said, and why better material did not move the score, are in finding 168.
