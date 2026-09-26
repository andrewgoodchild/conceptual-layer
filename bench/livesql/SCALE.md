# Does the description earn its keep at scale? A pre-registered round

Written 26 September 2026, before any writer ran. The results go in `bench/findings.md` and
are compared against this page, not against a revised version of it.

## The question

Every result so far had schemas small enough for a writer to take in whole. On LiveSQLBench's
PostgreSQL tier a database is about 54 tables and 980 columns, and its DDL with sample rows is
120–215 kB — 30,000 to 55,000 tokens. There, a writer cannot read the schema; it has to find
the part a question needs. That is where a conceptual layer has a structural reason to help:
its narrowed description carries what identifies each thing, the values each column holds and
what profiling found, where a narrowed DDL carries names, types and three sample rows.

The only earlier run on this tier added the description *beside* the full DDL (findings 163,
165: 19 and 23 of 48 against 21). It never tested the description *instead of* the DDL, and
never against a narrowed DDL, which is the comparison that separates the layer from mere
narrowing.

## Design

**Sample.** The ten databases of the tier the earlier rounds did not use:
`cross_border`, `cybermarket_pattern`, `disaster_relief`, `fake_account`, `mental_healths`,
`organ_transplant`, `polar_equipment`, `residential_data`, `reverse_logistics`, `virtual_idol`
(each `_large`). Ten `Query` tasks from each, drawn by `pilot.py`'s own procedure with its
default seed (balanced on the benchmark's `high_level` flag): **100 questions**, 48 of which
use a term defined only in the knowledge base. `work/pilot-scale/sample.json` lists them.

**Arms.** Every arm writes PostgreSQL SQL, so the language is not a variable. Every arm gets
the questions, the database's knowledge base (`knowledge.md`) and `./try`, which runs a
statement read-only on the server and shows rows, never correctness. They differ only in how
they see the schema:

| arm | sees the schema as |
|---|---|
| `sql` | the full DDL with three sample rows per table, `schema.sql` — the baseline |
| `sqlddlk` | `./schema "question" ["extra words"]`: the DDL narrowed to the question by a standard lexical retriever over table and column names, declared foreign keys and the sample rows (`ddl_link.py`); no `schema.sql` |
| `sqldesc` | `./schema "question" ["extra words"]`: the conceptual description in relational terms, from the *profiled* model (`build.py --profiled`), narrowed by `conquer/link.py`; no `schema.sql` |

Both narrowers take the same arguments and, called with none, print everything. The DDL
retriever is lexical — words of the question against words of names and sample rows, with
`link.py`'s tokeniser — not an embedding retriever; a stronger DDL baseline could exist, and
a win here would need testing against one before it was claimed generally. The DDL
retriever keeps about as many tables as the description's narrowing does (calibrated on the
sample's own question text before the run, and recorded below), so the two arms see similar
amounts and differ in *what* they see and how it was chosen.

**Writers.** One blind writer per (arm, database), 30 in all: Claude Opus 5.5
(`claude-opus-5-5`) agents, each given `BRIEF.md` and its working directory. Recorded in
`work/pilot-scale/ledger.json` with tokens, tool uses and time. The three arms of a database
run in the same batch, so no arm gets a later model or a quieter server.

**Scoring.** `score_pg.py` against the tier's gold, unchanged. Also recorded: whether each
narrower, given only the question text, keeps every table the gold statement touches.

## Prediction

- **Primary.** `sqldesc` scores at least **5 of 100** above `sqlddlk`. That is the claim that
  a conceptual layer does something at scale that narrowing the DDL does not.
- **Kill.** If `sqldesc` − `sqlddlk` is **3 or less**, inside the noise measured on BIRD (three
  identical runs scored 71, 69 and 68), the claim is not supported: at this scale the value is
  narrowing, and a DDL can be narrowed too. Between 3 and 5 is recorded as inconclusive.
- **Honest prior.** The writers are agents that can search a file, so the `sql` arm narrows
  the full DDL for itself. I expect `sql` to do as well as either narrowed arm, and the
  primary difference to be inside the noise; I put about 60% on the kill outcome. A larger
  difference, if one appears, is most likely to come from the value domains and identifiers
  profiling adds, which is what writers said they lacked in finding 163.

## Calibration and retriever recall

Measured before any writer ran, with `calibrate_scale.py`, on the 100 questions' own text:

| | description (`link.py`) | DDL, 8 tables | DDL, 22 tables |
|---|---|---|---|
| median characters shown | 81,000 | 29,000 | 79,600 |
| median tables named | 29 of ~54 | 10 | 25 |
| questions with every gold table kept | **72** | 28 | **51** |

`link.py`'s narrowing keeps about half the schema — it narrows far less on these models than
on BIRD's, because a profiled model's concepts are densely connected. Matching on tables
would have given the DDL arm a third of the text, so the retriever is set to **22 tables**,
which matches the description on characters. At equal size the description keeps every gold
table on 72 questions and the DDL on 51: the model's linking already retrieves better before
anyone writes a query. Whether that reaches the answers is what the run measures. The table
counts for the description include tables it only mentions, so characters are the fair
measure.

## Result

Recorded after the run; the plan above is unchanged. **The prediction failed.** The
narrowed description scored 26 of 100, the narrowed DDL 29 and the full DDL 28: description
against narrowed DDL, 1 question won and 4 lost, p = 0.38, inside the kill threshold. It also
cost the most: 1.05M tokens and 63 minutes of writer time, against 0.90M and 45 for the
narrowed DDL and 0.87M and 36 for the full DDL. The prior was right.

What happened, why, and the process defects to read it with (shared draft files between
writers in the first three batches; one description writer who never saw the description)
are in `bench/findings.md`, finding 166. `score_scale.py` reproduces the scores; each writer's
own account is in `work/pilot-scale/reports/`.
