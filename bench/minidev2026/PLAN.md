# Plan: paired arms on the October 2026 BIRD mini-dev

Committed before any writer runs. Nothing here was changed after seeing an answer; any
departure is recorded under "What actually happened" with the result.

**The question.** Finding 164 found the served description worth the DDL, 75 of 100 against
74, on the 2025-07-04 annotations. The new release renumbers and rewrites nearly all of the
questions, labels 460 of 500 "challenging", and leaves 135 with no evidence. Does the
description still match the DDL here, and does it matter more where the evidence has gone?

**Data.** `fetch.sh` pins the revision and checksum. All 500 golds ran and returned rows on the
local databases and scored by nothing else. The models are the ones in `bench/models/`, built
from the databases alone, so they carry nothing from the new questions. `pins.json` holds the
checksums of the source, databases and models, and the draw.

**Sample.** 100 questions, proportional across the 11 databases, seed 20261031: `sample.py`.
It holds 26 with no evidence. The difficulty label is not shown to writers.

**Arms.** One fresh blind Sonnet 5.5 writer per (arm, database), 33 in all, launched together.
Gold is absent from their directories; keeping them out of the repository rests on instruction.

| Arm | Sees | Runs with |
|---|---|---|
| `sql_ddl` | the DDL, the shared working steps | `./try` |
| `sql_mcp` | the description with `relational=True`, no DDL, over MCP | `run_sql` |
| `conquer_mcp` | the description and the primer, over MCP | `run_query` |

Every arm gets the evidence where a question has one, and at most six runs per question.
`sqlglot` is not installed, so `run_sql` shows rows with no checker findings: the description
is the one variable. Prompts are in `build.py`. The writers use the working tree at this commit
plus its uncommitted changes, which touch the PostgreSQL path and docstrings only, not SQLite.

**Metric.** BIRD's strict EX as `bench/pilot/score.py` computes it, on all 100 questions, an
unanswered one wrong. `compare.py` is the whole analysis.

**Primary comparison.** `sql_mcp` minus `sql_ddl`. It counts as a difference only if it is at
least 4 points either way, past finding 47's three, and the database-clustered 95% interval
excludes zero. Otherwise it is reported as no difference shown; a single round this size can
show a large shift only.

**Secondary.** `conquer_mcp` against each SQL arm, and `sql_mcp` minus `sql_ddl` split by
evidence present or absent. The split has 26 questions on one side and is descriptive only.

**Predictions.** `sql_ddl` 85, within 79 to 91. `sql_mcp` minus `sql_ddl` +2, within -3 to +5,
so no difference shown. `conquer_mcp` two below `sql_mcp`, within -6 to +2. The description's
margin is larger on the questions with no evidence than on those with it.

**Not claimed in advance.** Scores here are not comparable with any 2025 number: another test
set, and the writers are Sonnet where finding 164's were Opus. High scores also leave less room
for a difference, which is a limit of this design. No gold is audited in this round.

**Cost.** About 2.5 to 4M tokens, scaled from finding 164's 1.55M for two arms of Opus writers.
Usage is recorded per writer.

## What actually happened

Added after scoring; everything above is as committed. `sql_ddl` 88, `sql_mcp` 79, `conquer_mcp`
88. The primary comparison is -9 with a database-resampled interval of -19.7 to 0.0, so by the rule above:
no difference shown. The +2 prediction failed. The evidence split held only nominally, -2 of 26 against
-7 of 74, a loss in both. `sql_ddl` fell within its range, and `conquer_mcp` came +9 over `sql_mcp` where -6 to +2 was predicted. Usage was 1.73M tokens, under the estimate.

One departure: the session allows 20 subagents at once, so 13 writers started as others finished.
`ledger.jsonl` holds each writer's usage. Finding 176 has the reading of the losses.
