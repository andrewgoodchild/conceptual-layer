# A conceptual layer did not help LLM agents write or check SQL

*A negative result, from eight pre-registered rounds and the pilot before them.
November 2026.*

**Summary.** This repository builds a conceptual layer for a relational database: an
Object-Role Modeling model reverse-engineered from the catalogue and the rows, served to an
agent as English sentences, with ConQuer, a query language over the model that compiles to SQL
and reads each query back in English. The bet was that an LLM agent writing queries does better
with this layer than with the DDL. On BIRD and LiveSQLBench, against agents that can run their
queries, it did not. In eight rounds whose plans, predictions and decision rules were committed
before any agent ran, the layer never beat the DDL by the pre-registered rule. That held:

- at 1,000 columns;
- with the benchmark's own column descriptions added;
- with every name, key and hint destroyed;
- when the read-back was given to someone checking a query rather than writing it.

What did help was ordinary: the definitions people write down (+8 points, to any writer in any
language), saying what identifies each thing on schemas that hide it, and one good reasoning
strategy. The measurements also found that a large share of what counts as error on these
benchmarks is the benchmarks'.

## What was tested

Three forms of the claim, in the order they were given up:

1. **The language.** An agent writing ConQuer is more often right than one writing SQL, because
   the compiler works out the joins and refuses queries that are well-formed and meaningless,
   such as a fan trap.
2. **The description.** An agent writing SQL is more often right with the model's description
   of the database than with its DDL, especially where the schema is large, badly named or
   undocumented.
3. **The read-back.** A person or agent checking a query catches more wrong ones when it is
   read back to them in English.

## Method

Every measurement used the same protocol.

- **Writers:** a fresh Claude agent per (arm, database) that had never seen the repository. The
  pilot and the October rounds used Sonnet; the LiveSQLBench rounds and some pilot arms used
  Opus.
- **Inputs:** the questions and the arm's material. The gold was never present.
- **Execution:** a runner that shows rows and never correctness, with the same attempt budget in
  every arm.
- **Arms** differ in one thing each.
- **Scoring:** the benchmark's strict execution accuracy. Paired arms get an exact McNemar test
  on the questions they split, and a bootstrap that resamples whole databases (or whole
  questions) for the interval.

For the eight rounds in the table below, a plan was committed to git before any writer ran. It
named the arms, a prediction with a range for each, and the rule for calling a difference:
usually at least 4 points with the interval excluding zero. Each plan's result was appended
under a heading that says it was added after scoring, with nothing above it changed. Each plan
is linked.

## Results

### The pre-registered rounds

| Round | Writers | What the layer gave | Layer | DDL | Verdict |
|---|---|---|---|---|---|
| [SCALE](bench/livesql/SCALE.md), LiveSQLBench PostgreSQL, 100 q | Opus | profiled description, narrowed to the question | 26 | 29 narrowed, 28 full | prediction failed (p=0.38) |
| [SCALE2](bench/livesql/SCALE2.md), 40 q, held-out databases | Opus | the same, with the gaps writers named filled in | 12 | 13 | failed again (p=0.50) |
| [SCALE3](bench/livesql/SCALE3.md), 60 q | Opus | DDL chosen by the model and annotated; then every business term derived and checked | 25, 25 | 22 | both failed; the gap is one blocked writer |
| [SCALE4](bench/livesql/SCALE4.md), 60 q | Opus | the benchmark's own column meanings; LLM-written column descriptions; a value index and draft-query linking | 28, 26, 26 | 28 | all three failed |
| [minidev2026](bench/minidev2026/PLAN.md), BIRD Oct 2026, 100 q | Sonnet | SQL from the description, no DDL | 79 | 88 | no difference shown (interval -19.7 to 0.0); ConQuer from the description 88 |
| [minidev2026 repeat](bench/minidev2026/PLAN2.md)\*, 100 more q | Sonnet | the same | 90 | 88 | no difference shown; both rounds pooled -7 of 200, -18.8 to +3.2 |
| [nameless](bench/nameless/PLAN.md), BIRD, no FKs, no evidence | Sonnet | description with names kept / names destroyed | 84 / 78 | 78 / 75 | no difference shown, as predicted; the DDL without names lost 3 points, not the 40 predicted |
| [readback](bench/readback/PLAN.md), 144 earlier ConQuer answers | Sonnet checkers | the English read-back beside each query | 79% of wrong caught | 84% | no difference shown; point estimate against the read-back |

\* The repeat's checksum was recorded before any writer ran but the plan was not committed until
after, so its pre-registration is weaker than the others'.

### Before pre-registration: the pilot

One hundred BIRD mini-dev questions (2025 annotations), 34 arms. These are not pre-registered
and are read against the pilot's own measured noise of about three points.

- ConQuer from the model **71**, SQL from the DDL **70** (McNemar 5 against 6, p = 1.00). Opus as
  the writer: 76 and 74.
- **Withholding BIRD's per-question evidence costs 14 points.** Writing the evidence into the
  model as definitions recovers +8 for ConQuer. The same definitions as plain English to a SQL
  writer also recover +8. The gain is the definitions', not the model's or the language's.
- **The refusals almost never fired on real authoring.** The one time a fan trap occurred, the
  check did not cover the shape it took.
- Three writers with **different strategies** (decompose, plan first, self-made examples) scored
  77, 76 and 75 against 71 for the base prompt, in one session. Re-run, the first scored 64 and
  62, so the size is not established.

## What held

- **Definitions people write down.** +8, to either language. A definition that is wrong is
  wrong everywhere it is used.
- **Saying what identifies each thing, where the schema hides it.** On LiveSQLBench's SQLite
  tier, an *Identification* section and opened JSON columns took ConQuer from 71 to 82 of 180.
  That is still short of plain SQL's 85, and the databases re-run were chosen after the fact.
- **The reverse engineering, measured as the literature measures it.** Foreign keys recovered:
  - on AdventureWorks, 77% at 91% precision;
  - with a frozen LLM judge over the candidates the rules discard: 91% at 95% on AdventureWorks,
    85% at 95% on MusicBrainz;
  - on two archives published after the judge's training data, ACAI 96% / 100% and DBBE
    70% / 95%.

  With every name destroyed, DBBE falls to 61% / 80% with the judge and 53% / 94% without it.
  Most of what the recovery finds, it finds by reading names.
- **The benchmarks' own error.** On LiveSQLBench's PostgreSQL tier, three quarters of one
  round's 132 wrong answers were the gold's or the scorer's. On BIRD's 2025 mini-dev, 14 of the
  18 questions no arm ever answered have a cross-arm consensus the gold rejects.

## Why it failed, as far as the measurements say

- **Agents that can query find what the layer would have told them.** At scale, 53% of 538
  wrong answers used every table, column and JSON field the gold used and still answered
  something else. Where a gold table was left out, the writer with the whole DDL did the same 50
  times in 55. With every name destroyed, BIRD writers worked columns out from their values and
  lost 3 points, at about twice the time.
- **What is left is reading, not retrieval.** The grain of a result, the base of a percentage,
  age at the event or today, a sort order left open. A description of the schema, however good,
  does not settle these.
- **The layer costs tokens.** The ConQuer writer's static prompt averaged 55k characters against
  34.5k for SQL. On PostgreSQL, ConQuer writers used 1.5 times the tokens and 1.9 times the time.
- **The read-back answers a question checkers did not need help with.** Without it, checkers
  caught 84% of the wrong answers. Where the two arms split, the read-back had corrected a
  checker's misreading of the syntax, and the query was still wrong for a reason it did not
  show.

## What this does not show

- **Small effects.** With 100 questions an interval is about ±10 points. The pooled October
  rounds leave a loss of up to 19 points, or a gain of up to 3, possible.
- **Other writers.** Every writer was a Claude model with a runner. A one-shot writer, or one that
  cannot query the database, was not tested, and it is the case where a description has the most
  to give.
- **Unknown databases.** BIRD and LiveSQLBench are public, and a writer may know them. Renaming
  blunts that and does not remove it. The judge was checked on two archives it is unlikely to
  know; the writers were not.
- **The author's use of the read-back.** ConQuer writers saw every attempt read back
  (`--check`), and that was never isolated. The checking round selected against the read-back:
  every wrong answer in it was one its author had seen read back and kept. Its checkers also saw
  several answers to each question side by side, which the plan did not foresee.
- **Real enterprise schemas** with no declared primary keys, and people rather than agents.

## For someone building this

- Write the definitions down and check them by running them. That was the one reliable gain.
- Profile the data and say what the rows say: identifiers, value domains, what is inside JSON.
  That helps where the schema hides it, and is nothing where the DDL already says it.
- Do not expect a conceptual query language, a description of a tidy schema, or static refusals
  to raise an agent's accuracy.
- Measure noise before reading a difference. Three points between identical runs on BIRD, nine
  between two draws of 100 questions.
- Run the control before writing the claim down. The +8 was first written up as the language's,
  before the arm that gave a SQL writer the same definitions showed the same +8.

## Reproducing it

`bench/README.md` indexes every experiment. `NOTICE` says why no benchmark question, gold or
database is in the repository, and the fetch scripts get them. Each round's directory holds its
plan, its build and compare scripts, every writer's answers and a per-writer usage ledger. All
186 findings, with what each cost and how it was found, are in
[`bench/findings.md`](bench/findings.md). The long account is
[`docs/07-what-we-measured.md`](docs/07-what-we-measured.md).
