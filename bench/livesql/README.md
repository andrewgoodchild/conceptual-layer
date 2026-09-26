# LiveSQLBench Large-v1: a scouting run

17 September 2026. Pulled the public release, built all 18 models, and measured the three
things that need no gold. The accuracy numbers further down came later, once the SQLite
tier's gold was available; the scouting run itself had none.

## Why this benchmark

`bench/spider2-trial/README.md` records why the Spider 2.0 round stalled: 9 of the 24 local
tasks that ship gold SQL cannot reproduce their own recorded answer, so a wrong answer and a
broken question are indistinguishable. LiveSQLBench is the same regime -- industrial schemas,
not BIRD's seven tables -- from a team that withholds gold rather than publishing it stale.

|  | BIRD | Spider 2.0-lite | LiveSQLBench Large-v1 |
|---|---|---|---|
| tables per database | 7 | 4-40 | **54** |
| columns per database | 54 | 90-900 | **983** |
| declared primary keys | most | **none** (no field for one) | **971 of 971** |
| declared foreign keys | most | none | **1,228** |
| gold SQL | public | public, 38% unscoreable | by email; both tiers' gold now in `data/` |
| engine | SQLite | SQLite / BigQuery / Snowflake | PostgreSQL, Docker, local |

## Getting it

    ./fetch.sh          # 6.7 MB: questions, schemas, column meanings, knowledge bases
    python3 build.py    # 18 catalogues -> 18 CCM models, ~13 s, PostgreSQL dialect
    python3 survey.py   # what is in the corpus
    python3 coverage.py # what the compiler could attempt
    python3 keys.py     # strip the foreign keys and try to recover them

The gold SQL and test cases are **not** in the public release. Email `bird.bench25@gmail.com`,
subject `[livesqlbench-large-v1 GT&Test Cases]`; the reply is automated, and both tiers' gold
now sit in `data/` (`livesqlbench_large_v1_gt.jsonl`, `livesqlbench_base_lite_sqlite_gt.jsonl`).
The large tier's databases are 2.6 GB of PostgreSQL dumps under `data/dumps/`; the gold is
PostgreSQL SQL, so scoring it needs a server. `docker run … postgres:17` with the dumps mounted
at `/docker-entrypoint-initdb.d/postgre_table_dumps` and the dataset's own
`init-databases_postgresql_large.sh` loads all 18 as `<name>_template`; `score_pg.py` then
scores an arm the way `score_sqlite.py` does, through `psycopg`. `pilot.py --tier large-pg`
builds the arms against that server rather than the SQLite copies: the SQL arm's `try` is
the container's `psql`, the ConQuer arm's is `conquer.py --dsn`, both read-only with a
two-minute limit. The recorded `pilot/` arms ran on the copies, and finding 161 says what
that cost: 28 of the SQL arm's 48 answers use a function PostgreSQL does not have.

## What the run found

**1. The pipeline handles the scale without complaint.** 18 PostgreSQL schemas through a
reverse engineer that had only ever seen SQLite, via a catalogue fixture rather than a
connection: 971 tables, 17,606 fact types, 13 seconds, **0 blockers** and 413 refinements.
The refinements are the interesting half -- rule 3b caught polymorphic
`(event_type, event_id)` pairs in several databases and correctly refused to model them as
one fact type.

**2. This is finally the regime where the abstraction ladder could matter.** The flat
verbalisation is **80 KB per database** against BIRD's 5 KB and Spider 2.0's 6-17 KB.
Level 2 keeps 11% of the fact types, level 3 6%, level 4 3%. Finding 69 measured level 2 as
worth nothing over the bare DDL, and the standing objection was that BIRD is too small for a
summary to matter. That objection no longer has anywhere to stand: 80 KB is past the point
where anyone reads the whole thing.

**3. Name-based foreign key inference collapses here, and the reason is precise.**

    truth 1,122   reachable 55   found 44   right 37   ->  recall 3%, precision 84%

Rule 9 matches a column named exactly like the target's single-column primary key. **95% of
these references are not spelled that way** -- `personnel_skills.VerifiedBySupervisorRef`
points at `personnel.crewregistry`, `qualitycontrol.arcref` at `projects.arcregistry`. Of the
55 references the rule could reach, it recovered 37. The rule is not broken; its premise is,
and BIRD's 81% was measured where the premise holds. Twelve of the eighteen databases score a
flat zero.

That is the first measurement this project has of key inference on schemas named the way
enterprises name things, and it is only possible because LiveSQLBench declares the keys that
Spider 2.0 has no field for.

**What it does not say:** rule 9c scores candidate references on value containment, coverage
and distribution rather than on names, and it is the rule that should survive this. It could
not run -- the public release ships three sample rows per table, which is not a population.
Testing 9c is the case for standing up the actual PostgreSQL dumps, and it is the single most
valuable thing this corpus could tell us.

## Both arms on the server

With the dumps loaded (above), both arms were written fresh for PostgreSQL by twelve blind
writers — the six databases and 48 questions `pilot.py` samples, `--tier large-pg` — and
scored with `score_pg.py` (findings 161–162). The answers, the sample and the cost ledger are
under `work/pilot-pg/`.

| | of 48 | tokens | minutes |
|---|---|---|---|
| plain SQL, PostgreSQL DDL and the knowledge base | **21** | 640k | 41 |
| ConQuer, the listing and the primer | **20** | 946k | 76 |
| plain SQL, the DDL *and* the description in relational terms (`--arms sqlnar`, finding 163) | **19** | 730k | 58 |
| the same, the description from profiled models (`build.py --profiled`, `--arms sqlnarp`, finding 165) | **23** | 526k | 23 |
| the recorded ConQuer arm, written against the SQLite copies, re-scored here | 19 | | |
| the recorded SQL arm | — | | 28 of 48 use a function PostgreSQL does not have |

Both right on 17; on 14 of the 24 neither gets, the two arms return identical rows. Before
the score, the server exposed eleven dialect defects the SQLite copies had hidden — the
templates for JSON paths, `round`, `least`, integer division and dates; a comma-join scoped
differently; bare columns under GROUP BY; arithmetic on text; a HAVING classification that
read only direct references — all fixed, and the DEFINE defect found with them since
(finding 162).

## What we could attempt, and what we could not

Of 480 tasks, **148 are Management** -- CRUD. The compiler emits SELECT and nothing else, so
the honest denominator is **332**. Within those:

- **~2% signal a construct we do not have** by their wording: median/percentile (no
  ordered-set aggregate), recursion, explicit JSON access.
- **jsonb is the real exposure.** 253 of 971 tables carry a `jsonb` column and every database
  has some. The wording probe admits only 4 tasks; that is a floor, not the gap.
- **55% are `high_level`** -- they name a term whose definition lives only in the knowledge
  base ("Conservation Priority Index", "Veteran's Podium", "Secure Income Efficiency Score").

That last one deserves its own line, because it is this project's own finding turned into a
benchmark. We measured the semantic layer's whole contribution as coming from the *definitions*
and not from the language: +8 on BIRD whatever the definitions said, with the control showing
the language worth 0. LiveSQLBench ships a 1,090-entry hierarchical knowledge base, 560 of
whose entries depend on other entries, as a first-class input to every competitor. The layer
we found carries the gain is now the baseline everyone gets. Whatever case this project makes
here has to be made somewhere else.

## The dialect, which was wrong for two days

19 September. `build.py` called `derive` without a dialect, so every one of these 18
PostgreSQL models was built with SQLite's function library:

| | built as | PostgreSQL needs |
|---|---|---|
| `fn.divide` | `CAST({0} AS DOUBLE)` | `DOUBLE PRECISION` -- `DOUBLE` is a *syntax error*, not a wrong answer |
| `fn.jsonPath` | `json_extract` | `jsonb_path_query_first(...) #>> '{}'` |
| `fn.year` | `strftime` | `EXTRACT(YEAR FROM ...)` |
| `fn.median` | stripped: SQLite has no ordered-set aggregate | `percentile_cont(0.5) WITHIN GROUP` |

None of it would have run against the server these questions are graded on, and nothing
caught it because the pilot executes against the SQLite copies `load.py` makes for analysis
-- which is the shim that file warns is "for analysis, not for answers".

Two consequences beyond the templates. `fn.median` being stripped is why `coverage.py` still
reports median/percentile as a construct we do not have: we do, on this target, and the
model was hiding it. And rebuilding surfaced one recorded pilot answer that passes a single
argument to `round`, which is declared with two -- SQLite's one-slot template accepted it and
PostgreSQL's does not. The stricter reading is the right one; the query was always
under-specified.

## Rule 12: the schema inside the jsonb columns

Added 17 September after the scouting run found 253 of 971 tables carrying a `jsonb` column
the model could not reach. A document column is a catalogue that stopped short -- the database
says "one column of type json" where it means "nine values of known type" -- so recovering it
is the same act as rules 9, 9b and 9c, one level further in. `reverse/jsonshape.py` classifies
a column three ways and only one of them is a record:

| | | |
|---|---|---|
| **record** | keys stable row to row, naming roles | one fact type per scalar leaf, mapped to a path |
| **map** | keys vary and are themselves data -- `{'clay': 15, 'quartz': 60}` | detected, **not** derived: in ORM this is `Survey has Percentage for Mineral`, and reading it needs an unnest rather than a path |
| **bag** | free-form notes, a change log | refused |

Here the classifier is not what runs. LiveSQLBench ships `fields_meaning` -- name and declared
type per key -- for 212 of its 310 jsonb columns, and that is a field schema somebody wrote
down, so `jsonshape.from_fields` takes it directly. Running the classifier against the real
PostgreSQL dumps would exercise the harder half and is the stronger test.

    fact types          17,606 -> 19,289     +1,683 recovered from inside documents
    columns expanded    209 records, 3 bags refused
    models valid        18 of 18 against ccm.schema.json
    queries compiled    1,892 of 1,892 derived fact types, every one emitting a path read
    paths resolved      1,584 of 1,625 tested against real sample documents (97%)

The query language did not change. A ConQuer query says `Circuit has CircuitLocationCity` and
never mentions JSON; the path lives in the mapping, next to everything else dialect-specific,
and `fn.jsonPath` carries the spelling (`json_extract` for SQLite and DuckDB,
`jsonb_path_query_first` for PostgreSQL). `python3 json_probe.py` compiles a query against
every derived fact type; `python3 execute_probe.py` runs the emitted extraction against the
three sample rows each dump carries.

**The document stays reachable as a document** (22 September). Rule 12 used to replace the
opaque value type with the fact types inside it, so a query written before the expansion --
`jsonPath(c, '$.autopay')` -- stopped compiling after it. 50 of the 180 recorded SQLite-tier
answers are written that way, and they are the control arm of every comparison; a rebuild
that broke them would have measured the breakage. The column is now derived both ways: the
fact types, and the opaque value with a `description` naming them, which the listing prints
under *Defined terms* so a writer is sent to the fact types rather than to `jsonPath`. The
recorded arm scored the same 71 against the expanded models when this was written (70 with
today's compiler)
(`work/models-sqlite-tier-json/`, the identification build plus `--infer-json`).

**The 41 paths that did not resolve** are dominated by keys that are plainly optional --
`address.province`, `phone.extension`, `permits -> conditions.revocation_reason`. Three rows
cannot tell "absent because optional" from "wrongly declared", which is one more reason to
want the dumps.

## The SQLite tier's models, and the flags that build them

22 September. The 18 models the 180-question run was written against
(`work/models-sqlite-tier/`) were built by hand and the command was recorded nowhere. It was
recovered by rebuilding until all 18 came out byte for byte -- and since finding 160 every
model records the command that built it in its `_comment` (`Built by reverse/reverse.py
with: ...`), so this cannot happen again:

    for f in data/sqlite_tier/*_template.sqlite; do
      python3 ../../reverse/reverse.py "$f" -o work/models-sqlite-tier \
              -n "$(basename "$f" _template.sqlite)" \
              --infer-domains --infer-enforced --infer-partitions \
              --merge-domains --profile --expand-names
    done

No `--infer-json`: the documents stay opaque and every writer reaches into them with
`jsonPath`, which three of them independently named as the listing's biggest gap. That is
what `work/models-sqlite-tier-json/` adds (see *The document stays reachable* above).

A model now records the flags it was built with, in its `_comment` (`Built by
reverse/reverse.py with: ...`), so this paragraph need never be reconstructed again.

`work/models-sqlite-tier-ident/` is the same command plus `--infer-identifiers` (finding
156). It differs by 3 uniqueness constraints and 7 `terms` lists, the mapping is identical,
and the recorded answers score the same 71 against either. The answers written against it
are in `work/pilot-sqlite-ident/`, beside the recorded arm rather than over it:

    python3 score_sqlite.py --arm work/pilot-sqlite-ident/conquer \
            --model-dir work/models-sqlite-tier-ident          # credit 6, cross_db 7, crypto 3

`work/models-sqlite-tier-json/` adds `--infer-json` on top (finding 157): 41 documents in
12 databases become 358 fact types beside the documents themselves, and the function table
spells `log10` natively. The recorded arm scored 72 against these when this was written (news_8 flips on the
`log10`; 71 with today's compiler). The six databases written against them are in `work/pilot-sqlite-json/`:

    python3 score_sqlite.py --arm work/pilot-sqlite-json/conquer \
            --model-dir work/models-sqlite-tier-json   # news 7, crypto 4, virtual 2, museum 3, alien 1, mental 3

Merging the three arms -- json where it ran, then ident, then recorded -- scores **82 of
180** here and **77** through the official harness, which strips the `DISTINCT` our
DEFINE bodies rely on and checks order on tied keys. The recorded arm is 71 on both.

`work/pilot-sqlite-lang/` is a fourth round on news, crypto and mental against the same
models rebuilt with the language additions of finding 158 (`THE OBJECT OF v BY k`, `THE
LIST OF x SEPARATED BY s`, `THE PERCENT RANK OF`, `THE MEDIAN` on SQLite, `WITHIN 1`).
The writers used every one of them where it applied and scored exactly as round 2 did.

## Files

| | |
|---|---|
| `fetch.sh` | pulls the public release into `data/` |
| `catalogue.py` | LiveSQLBench schema dump -> the fixture `reverse.py --json` reads |
| `build.py` | all 18 models, and the abstraction ladder over them |
| `survey.py` | corpus and schema shape |
| `coverage.py` | what the compiler could attempt; crude, wording-based, labelled as such |
| `keys.py` | strip-and-infer over 1,122 declared references |
| `json_probe.py` | compiles a query against every fact type rule 12 derived |
| `execute_probe.py` | runs the emitted path reads against the dumps' sample rows |
| `query_probe.py` | every query shape over a value inside a JSON document |
| `classify_probe.py` | rule 12's reading of the documents against the field schema someone wrote down |
| `refs_probe.py` | rule 9c against the 1,122 declared references: data beats names, 3% to 57% recall |
| `kb.py` | a knowledge base encoded as derived fact types |
| `fieldcheck.py` | the data checked against what the knowledge base says it is |
| `conformance.py` | an answer checked against the knowledge base's definitions, and which check discriminates (finding 154) |
| `compare.py` | where the SQL and ConQuer arms agree, with no gold to score against |
| `official_eval.py` | an arm scored with LiveSQLBench's own evaluator rather than ours |

`work/` is generated. What is tracked under it is what the writers wrote -- each arm's
answers, the sample and the cost ledger under `work/pilot*/` -- and not the working
directories `pilot.py` makes them from.
