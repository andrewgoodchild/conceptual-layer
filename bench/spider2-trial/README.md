# A trial of the ConQuer toolchain on Spider 2.0's local slice

Spider 2.0-Lite has 135 tasks over 30 SQLite databases that run with no cloud account. This
is not a benchmark run -- there is no blind arm and no agent writing answers -- it is a
**trial**: reverse engineer the databases, point the property suite at the result, and write
a handful of the visible-gold tasks by hand to see what the language can and cannot say.

The point is that the schemas are unseen. Everything the compiler had been tested against was
either the eleven-table company fixture or BIRD's eleven databases, and both had been used to
find the bugs that shaped the compiler. A new corpus is the only way to find out what the old
one was hiding.

## Before the trial: what the gold queries need

`conquer/conquer-2026.md` weighted its changes by BIRD, whose gold queries average 31 tokens.
Spider 2.0 is the benchmark the field moved to, and its locally runnable SQLite slice was worth
a look because the questions it asks are the ones a data team actually asks. 135 tasks over 30
databases, gold SQL visible for 24 of them, expected result sets for all 135.

Two things it is not. It is not a scale test for the offline slice: those databases average
100 columns to BIRD's 73, and 14 tables to BIRD's 7. The 812-column warehouse schemas that
make Spider 2.0 famous are the BigQuery and Snowflake two thirds, which need cloud accounts.
And it is not, on this evidence, a single-query benchmark at all.

| In the 24 visible SQLite golds | |
|---|---|
| median gold length, all 135 tasks | 143 tokens, against BIRD's mean of 31 |
| use a CTE | 88%, median 3 per query, up to 7 |
| use a window function | 33%; `RANK`, `ROW_NUMBER`, `NTILE`, `LAG` in 29% |
| use `CASE WHEN` | 42% |
| use `UNION`, `EXCEPT` or `INTERSECT` | 29% |
| use string concatenation | 21% |

The typical query is an analytics pipeline: `local003` scores customers on recency, frequency
and monetary value in three named CTEs, each applying `NTILE(5)` over a grouped aggregate,
then joins the three. Nothing in ConQuer-92 names an intermediate result *inside a query*.
§6.11's derivation rules name one in the **model**, which is the right answer when the
quantity is a business term and the wrong one when it is a step in this afternoon's analysis;
§6.9's macros are substitution, not relations.

How much composition is *irreducible* is a smaller number than that 88%, because counting CTEs
counts how the annotator chose to write the query. Counting instead the ones where a CTE
actually reads an earlier CTE: of the 20 visible golds using them, **13 chain and 7 are
parallel**, every CTE reading only base tables and the results combined at the end. Those seven
are several aggregates at one grain, which §6.5's confluence already gathers. Of the 13, about
half need a single further stage, which `conquer/conquer-2026.md` §7's
aggregate-over-a-grouping partly covers. Roughly a third of the whole are genuine multi-stage
pipelines, the worst being seven CTEs with five of them chained.

So the gap is real but narrower than it first looks, and it is not the §6.3 function library
the way the first ten items of `conquer/conquer-2026.md` were. The first move is §6.5 restored
rather than anything new: LISA-D's confluence returned **nested** relations, and the report
changed it to an outer join for one stated reason, that "SQL-92 is not able to deal with nested
relations". SQLite has had `json_group_array` since 2016. Restoring the nesting is Malloy's
`nest:`, in the language's own vocabulary, and it is the same class of move as §6.2 and
recursion: lifting a restriction the report itself attributes to a target that has moved. It
does not bring top-N per group with it, since a confluence side path carries no Ω of its own,
and it does not reach the deep pipelines, which is worth conceding rather than papering over.

That is a fair thing to have learned and it bounds the claim this project can make. ConQuer
ties SQL on BIRD's shape of question, which is one question answered by one traversal. On
Spider 2.0's shape it would mostly not compile. Closing that means query-level named
intermediates -- LISA-D's own `WITH`, in effect -- and that is a language change, not a
function.

Caveat worth keeping: 24 visible golds is a thin sample of 135, and the constructs were
counted by pattern, not parsed. The direction is not in doubt; the percentages are indicative.

*(Written before the trial. `DEFINE`, `conquer/conquer-2026.md` §11, is the query-level named
intermediate this section asks for; "The tasks" below is what it bought.)*

One design detail worth stealing regardless: Spider 2.0 accepts **several** result sets per
question, 91 of the 135 having more than one and some as many as twelve. BIRD scores against
a single gold, which is why so many of its residual failures are arguments about the
question rather than the answer.

## Getting the data

The Spider 2.0 clone (`bench/spider2/`, gitignored) carries DDL and sample JSON but **not the
databases**: those are a separate 435 MB download named in `spider2-lite/README.md`, unzipped
into `spider2-lite/resource/databases/spider2-localdb/`. `build.py` makes `work/<arm>/<db>/`
from the clone -- the tasks' questions, the DDL, the knowledge documents a task names, and a
`try` script -- and none of that is tracked, being Spider's; only the `answers.json` written
here is. Then:

    python3 reverse/reverse.py <db>.sqlite -o bench/spider2-models -n <name> \
            --infer-keys --infer-fks --infer-domains
    python3 bench/spider2-trial/survey.py            what the thirty models came out as
    python3 conquer/tests/test_metamorphic.py --model bench/spider2-models/<name>.ccm.json \
            --db <db>.sqlite
    python3 bench/spider2-trial/try.py --all         re-score every recorded attempt
    python3 bench/spider2-trial/try.py local039 --query "LIST ..."

`--infer-keys` is not optional here: **223 of these 412 tables declare neither a primary key
nor a foreign key**, and rule 1 reads no shape at all without one.

`calibrate.py` asks the benchmark what it scores itself — see *Can this be scored at all?*
below, and run it before believing any number from this slice.

`try.py` compiles one ConQuer query, runs it, and scores it against **every** result set the
task accepts -- 91 of the 135 local tasks accept more than one, which is a better design than
BIRD's single gold and is why the harness reports which one matched. `attempts.json` records
the queries written so far and `--all` re-scores them, so a change to the compiler or to the
reverse engineering can be checked against real questions in seconds. `survey.py` reports
what each model derived to, how many tables stayed blocked, and how many pairs of types no
verb can tell apart.

## What the thirty databases derive to

The first pass got models out of fourteen of the thirty. The blocker was not subtle:

| | before | after |
|---|---|---|
| databases that derived **nothing at all** | 16 of 30 | **0** |
| entity types across all thirty | — | 375 |
| tables still blocked | 223 | **32** |
| pairs of types no verb can tell apart | — | **0** |

**223 of the 412 tables declare neither a primary key nor a foreign key**, and rule 1 reads
no shape at all without one. Bird's Step 9 had mined the candidate identifiers all along and
the report had always listed them; nothing applied one. `--infer-keys` (rule 9b) does, before
the derivation rather than after, because a foreign key points *at a key* and there is
nothing to aim at until they exist. Two smaller things came with it: two fact types between
the same pair of types that read identically are now separated by an adjective (f1's `races`
and `races_ext` both read `Race has Season` and a query could reach neither), and a view whose
definition no longer resolves is skipped and reported instead of taking its whole schema down
— one such view in `oracle_sql` was costing all 38 tables.

**How good are those guesses?** The benchmark answers it: eleven of these schemas declare
everything, so stripping the declarations out of the catalogue and asking again is a labelled
test. `reverse/tests/test_inference.py` reports precision and recall the way the literature
does, and Jiang & Naumann's HoPF (JIIS 54:439–461, 2020) is the bar at 88% of primary keys
and 91% of foreign keys.

| over 124 tables | first pass | now |
|---|---|---|
| primary keys | 75% recall, 96% precision | **91% recall, 100% precision** |
| foreign keys | 55% recall, 92% precision | **75% recall, 97% precision** |

Which eleven schemas these were was not recorded, and it matters: re-measured later on a
defined eleven (`oracle_sql`, `Pagila`, `sqlite-sakila`, `school_scheduling`, `chinook`,
`music`, `BowlingLeague`, `EU_soccer`, `EntertainmentAgency`, `complex_oracle`, `IPL` — 156
tables) the same code scores 83% / 98% for keys and 53% / 96% for references, and on BIRD
mini-dev 94% / 97% and 53% / 100%. The algorithm did not change; the corpus did. Quote the
corpus with the number.

Precision is the one that matters: a missing key costs a table, a wrong key is a wrong
identity in every query that walks it. The jump in references came from applying what was
already being measured — containment, coverage and Zhang et al.'s (VLDB 2010) randomness test
had been scored and *reported* since they were written, and nothing ever put them on the
catalogue. That is rule 9c, and it rides with `--infer-keys` rather than `--infer-fks`
because it changes the model rather than adding to it.

`survey.py` prints that table. The 32 still blocked were counted rather than guessed at, and
**most of them have no key to find**:

| | tables | |
|---|---|---|
| the rows are literally duplicated | 14 | no key exists at any arity — `modern_data.trees` has 690,626 rows and 683,788 distinct |
| too small for the data to be evidence | 10 | under Bird's threshold; 4 to 30 rows |
| two or more equally good candidates | 6 | `product_category_name_translation` has two unique columns and no way to choose |
| empty | 2 | nothing to read |

Only the third group is arguably a miss, and guessing between candidate identifiers is how a
schema acquires a wrong identity. Ten of the thirty-two are in `log` and nine in
`modern_data`, both collections of unkeyed event extracts.

## What the property suite found on unseen schemas

First pass: five models, about 2,300 generated assertions. Since the reverse engineering was
fixed: **all thirty models, 5,168 assertions, 0 failures** (`--cases 15 --timeout 3`). Six
defects across the passes, every one of them a *silent wrong answer* rather than a crash, and
none of them reachable from the fixture or from BIRD:

| | what happened | why the old corpus hid it |
|---|---|---|
| a schema shadowing a keyword | reverse engineering reads an n-ary table as `{0} has {1} and {2}`, contributing **`and`** as a verb part, so `... has RaceName v AND ALSO ...` consumed the `AND` as a step and refused at `ALSO` -- on every f1 query | neither the fixture nor any BIRD database has an n-ary fact type |
| an undeclared column type | SQLite lets a column be created with no type; `conceptual_type` fell back to text, so `--schema` printed the domain as `'1'` and `Drive has DriveId: '1'` compared a string with an integer in a column with no affinity to convert either. Zero rows, no error | every BIRD column declares a type |
| a bracket leaking its disjunction | `Employee [has Department: 'ENG'] [has Gender: 'M' OR OTHERWISE has Gender: 'F']` returned every employee, because `binds_nothing` did not know about `Binary`, so the alternatives were lowered into the *enclosing* block and the OR bound across the earlier bracket | finding 41 fixed this shape at the head of a chain; nobody had written two brackets in a row, one of them disjunctive |
| a calculation out of scope | a grouped aggregate whose argument is a value bound with `AS` outside, reached from inside a condition block, raised `KeyError` out of the emitter | the shape needs a `WHERE` with a disjunction between the `AS` and the aggregate |

The first three are fixed; the fourth is now a refusal that names the problem. The suite also
had two oracle bugs of its own, both about trusting a type it should have measured: a column
*declared* `NUMERIC` may hold dates (SQLite gives DATE numeric affinity), so the law comparing
`THE SUM OF` against adding the listed values was comparing SQL's coercion with Python's; and
a column may hold a number *and* a string, which SQLite sorts by storage class and Python
cannot sort at all, so the law checking `THE FIRST n` of an ascending order crashed on
AdventureWorks rather than failing. Both ask the data now.

Running the laws over all thirty takes a while and `--cases 12` is the practical setting:
several of these databases declare no indexes at all, so a generated query whose filter
becomes an `EXISTS` scans a hundred thousand rows per row. That is the database's shape, not
the compiler's — but it is worth knowing before waiting on a sweep.

## Can this be scored at all?

Before scoring anything against a benchmark, ask what the benchmark scores itself.
`calibrate.py` runs each **shipped gold query** against the **shipped database** and grades
it with the **shipped evaluator**, honouring each task's own `condition_cols` and
`ignore_order`:

> of 24 local tasks that ship their gold SQL, it reproduces the shipped answer for **14** and
> fails for **9** (1 could not be run)

**Nine of twenty-three gradable tasks cannot tell a right answer from a wrong one**, because
the query and the answer the benchmark ships for them disagree. `local309` is the clearest:
the CSV holds championship winners and the SQL sums points. `local029` ships two accepted
answers that contradict each other. This is the same measurement Jin et al. (CIDR'26) report
as 66% for Spider2.0-Snow, asked of the slice that runs offline, and it is the reason a raw
execution-accuracy number from these 135 tasks would not mean much: the other 111 ship an
answer and no query, so nothing can check them at all, and there is no reason to think they
are cleaner.

Two of the nine are tasks the ConQuer answers **pass** — `local131` and `local210` score 1
under the benchmark's own evaluator while the benchmark's own gold query scores 0.

## The tasks

Four of the 24 visible-gold local tasks, written by hand against the reverse-engineered
models. Three match a gold result set exactly.

Recorded in `attempts.json`; `try.py --all` re-scores them all in seconds, **through Spider
2.0's own `compare_pandas_table`** rather than a rule of our own. Theirs is column-wise, not
row-wise: every gold column must appear somewhere in the prediction, matched within 1e-2,
extra predicted columns ignored, row order required unless the task says otherwise. Scoring
by a different rule is scoring a different benchmark.

| task | db | needs | result |
|---|---|---|---|
| local038 | Pagila | five filters over four joins, top 1 by count | **match** |
| local039 | Pagila | a computed measure summed per group, top 1 | **match** |
| local131 | EntertainmentAgency | three conditional counts pivoted per row, zeros kept | **match** |
| local210 | delivery_center | two grouped counts compared: a CTE joined to a CTE | **match** |
| local163 | education_business | an average per group, then the row closest to it | **match** |
| local309 | f1 | top 1 *per year*, for a driver **and** a constructor, in one row | unscoreable |

Two of those were impossible when the trial started. `local210` needs a CTE joined to a CTE,
which is what `DEFINE` is for. `local163` needs two chained definitions on a database that
**derived to nothing at all** before rule 9b — eighteen tables, not one of them declaring a
key.

The first pass through these four settled what the gap actually is. It is **not**
expressibility -- three went in on the first or second attempt, one of them a five-predicate
filter across four joins -- it is **composition**. `local210` and `local309` both want two
whole grouped results side by side, and `THE FIRST n PER x` gives you either one while
`THE LIST OF` gives you both as nested bags.

§6.11 already names an intermediate and the emitter already renders one as a common table
expression, so the fix was to let a query declare a rule without editing the model:
**`DEFINE <Name> ::= <query>`**, `conquer/conquer-2026.md` §11. `local210` now matches gold exactly --
two monthly counts per hub, joined, compared:

```
DEFINE FebFinished ::= LIST h, orders FROM Order [has OrderStatus: 'FINISHED']
         [has OrderCreatedMonth: 2] has Store has Hub h
         AND ALSO THE COUNT OF Order GROUPED BY h AS orders
DEFINE MarFinished ::= … the same for month 3 …

LIST i, n, f, m, p FROM Hub has HubId i AND ALSO Hub has HubName n
     AND ALSO has FebFinished FebFinishedOrders f
     AND ALSO has MarFinished MarFinishedOrders m
     AND ALSO round((m - f) * 100 / f, 2) AS p
     WHERE p > 20 ORDERED WITH p DESCENDING
```

`local309` now compiles and runs — two definitions joined on Season, 75 rows, both halves on
one row — and it is the benchmark that cannot score it. **Running the shipped gold SQL
against the shipped database reproduces none of the three result sets shipped for the task**:
against `local309_a.csv` it differs on 8 of 75 rows, and `_b` and `_c` have 74 rows where it
produces 75. The eight are 1958, 1964, 1965, 1970, 1972, 1973, 1974 and 1988 — the seasons
where the championship and the raw points total disagree, and the CSV holds the championship
winner while the SQL sums points. Somebody who knew the sport wrote the answer; the query did
not. The ConQuer answer matches the shipped SQL on all 75 rows.

That is one measured instance of the annotation problem Jin et al. (CIDR'26) put at 66% for
Spider2.0-Snow, and it is only visible because this benchmark ships the query as well as the
answer. `local029` fails the same test differently: its two accepted result sets disagree with
*each other* about the third customer's average payment (137.0014 against 119.8763), so no
answer can satisfy both. Neither task is in `attempts.json`; the procedural lesson is that
**when an answer disagrees with a recorded result, run the recorded query before believing
either.**

Getting there needed the reverse engineering rather than the language. `Race has Season` was
ambiguous between `races` and the denormalised `races_ext`, so the compiler refused — loudly
and correctly, and uselessly. Rule 10 now separates them by what the table name says beyond
its two players: `has year` and `has ext`.
