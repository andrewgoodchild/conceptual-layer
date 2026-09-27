# 7 — What we measured

The project had a thesis: that routing a question through a conceptual model, in a query
language that can only say things the model supports, would help a language model write
correct queries — and that the queries it *refused* would be the difference.

It was tested. The thesis did not survive. This page is what was actually found, including the
parts that argue against the thing being built.

## The experiment

A hundred questions from [BIRD](https://bird-bench.github.io/) mini-dev, stratified across
eleven databases, each answered by a fresh agent that had never seen this repository. Every arm
got the same attempt budget and the same test-your-answer loop; the gold SQL was withheld.
Arms differ in exactly one thing each, which is what makes them comparable.

Everything below is reproducible: `bench/fetch.sh`, `bench/run.sh`, then `bench/pilot/`.

## The head-to-head is a tie

| arm | of 100 |
|---|---|
| direct SQL from the DDL | 70 |
| ConQuer from the conceptual model | **71** |
| the same two, written by a stronger model (Opus, not Sonnet) | 74 / **76** |
| SQL from the DDL **plus the model verbalised as English** | 73–74 |
| ConQuer plus the model verbalised as English | 66 |
| ConQuer plus a verifier pass | 73 |
| three writers, voted / selected | 71 / 70 |
| **three writers given three different *strategies*** | **77 / 76 / 75** — one session; the first of these re-ran at 64 and 62, see below |
| oracle over every arm | 82 |

71 against 70. The arms are paired, so the statistic is McNemar's test on the questions where
they disagree — 5 against 6, **p = 1.00**. At that rate of disagreement, detecting a true
one-point difference would need on the order of 1,500 questions.

**Run-to-run noise is three points.** Three writers with an identical prompt scored 71, 69 and
68. That single fact retires most two-point readings in the literature, including several of
this project's own earlier ones.

Only 11 of 100 questions discriminate the two languages at all. A model taught ConQuer from a
one-page primer wrote it about as accurately as it wrote SQL, in 1.71 attempts against 1.25.

## The semantic-layer gain is real, and it is not the language's

Every BIRD question ships a line of "evidence" — what a code means, which column a term is,
sometimes a formula. Withholding it costs **14 points** for a SQL writer and 16 for a ConQuer
writer. That is the size of the prize a semantic layer claims.

Encoding those definitions *into the conceptual model* — as derived fact types, subtypes and
macros, by separate modeller agents who saw the evidence but never the questions — recovers
**+8**.

Handing the same definitions to a **SQL** writer as plain English sentences also recovers
**+8**.

| arm | of 100 |
|---|---|
| SQL, evidence withheld | 56 |
| ConQuer, evidence withheld | 55 |
| ConQuer + the definitions in the model | 63 |
| **SQL + the same definitions as English** | **64** |

So the gain belongs to *writing the definitions down*, not to the conceptual model and not to
the compiler. The first write-up of this round attributed it to ConQuer — the control arm had
not been run yet, and the control overturned the claim. That is finding 43, and it is the
methodological lesson of the whole project: **run the control before writing the claim down**,
especially when the result flatters the thing you are building.

Two details worth keeping:

- Half the definition arm's answers use a definition and half do not, and accuracy is the same
  in each half. Definitions are used where they fit and do no harm where they do not.
- A *wrong* definition is wrong everywhere it is used. Three answers were lost that way. A
  definition that compiles and runs is not yet a definition that is right.

## How you ask

Every arm above changes the *inputs* — the language, the definitions, the writer. One arm
changes the **method**, and it is the only thing in this project that moved accuracy by more
than noise without changing the model.

The literature's version of this is CHASE-SQL: generate candidates with *different reasoning
strategies*, then have a selector pick between them. An earlier arm here scored that at zero —
but it sampled **one prompt three times**, which is the configuration the paper itself says
fails. So three more writers, same hundred questions, differing only in strategy:

| strategy | of 100 | attempts |
|---|---|---|
| divide and conquer — split the question, verify each part with `try`, compose last | **77** | 2.73 |
| plan first — say what is measured, which filters bracket, what one row *is*; then write | **76** | 1.72 |
| self-made exemplars — build worked queries in *this* schema, then adapt the closest | **75** | 1.69 |
| the same prompt, three times | 71, 69, 68 | 1.71, 1.68, 1.60 |

Every strategy arm beats every same-prompt arm, and the weakest beats the base by four. Two of
them spend no more attempts than the base did, so it is method and not iteration.

**A later round undercut the size of this.** Re-running the divide-and-conquer arm twice more —
once with the byte-identical frozen primer, to rule that out — gave **64 and 62 against the
recorded 77**, with the compiler, the scorer and the primer each separately exonerated. The
arm's honest range is 62 to 77, so "worth six points" is not established: what survives is that
the strategy arms beat the base *within the session they were run in*, which is the only
comparison that holds. The ±3 noise band on this page was measured on the base arm at 1.7
attempts per question; an arm that averages 2.7 and explores far more has roughly five times
that spread.

**But the mechanism the claim rests on is not there.** Diverse strategies are supposed to make
complementary mistakes for a selector to exploit. These agree *more* than the same-prompt trio
did — all three right on 72 questions against 62 — and the headroom from best arm to oracle is
**+3, and +4 before** (77→80, against 71→75). Voting over the trio scores 76,
a point *below* simply taking the best of them.

So the ingredient transfers and the mechanism does not: better strategies raised the floor
rather than spreading the candidates. If you are choosing where to spend effort, spend it on
one good method rather than on three samples and a referee.

## The refusals never fire

This was the architectural argument for the whole exercise: a conceptual query language can
refuse queries that are well-formed and meaningless — the fan trap, a value equated with an
instance, a node joined to nothing — and a SQL writer gets no such warning.

`--permissive` was built to measure it: every refusal is suppressible, so the query it blocked
can be run and scored. Then a logging arm recorded *every attempt* a writer made, not just the
one it kept.

| | |
|---|---|
| attempts logged | **143** |
| compiled | 136 |
| refused | **7** |
| of those, a judgement about meaning | **0** |

All seven refusals were parse-level: unconsumed input, an ambiguous verb, a name not in the
schema. Not one was a claim about meaning. The instrument works — a planted fan trap is
classified, replayed and judged wrong end to end — and this is the third independent
measurement agreeing: the locality check fires on 0 of the 1,186 queries the corpus then held, 0 of the
generated metamorphic queries, and 0 of 143 real authoring attempts.

**And the one real fan trap in the run compiled cleanly.** A writer produced a genuine fan
trap that returned 3,738 rows where the right shape returns 623 — and the compiler said
nothing, because the locality check guards *aggregates* and this multiplied a *projection*.
The author caught it by reading the row count.

The honest conclusion is the opposite of the thesis: **what helps the author is the loop — run
it, look at the rows — not the refusals.**

## The reverse engineering is measured like the literature measures it

Strip the declared keys out of a schema that has them, ask the inference to recover them, and
score it. Jiang & Naumann's HoPF (JIIS 54:439–461, 2020) is the bar, at 88% of primary keys
and 91% of foreign keys.

```sh
python3 reverse/tests/test_inference.py --db bench/bird/minidev/MINIDEV/dev_databases/*/*.sqlite
```

| corpus | primary keys | foreign keys |
|---|---|---|
| BIRD mini-dev, 11 schemas, 75 tables | 94% recall, 97% precision | 81% recall, 100% precision |
| Spider 2.0, 11 key-declaring schemas, 156 tables | 83% recall, 98% precision | 69% recall, 97% precision |

**Name the corpus whenever you quote these.** The same code scores 94% and 83% on primary keys
depending on which schemas it is asked about, because the inference leans on naming convention
and conventions differ. An earlier selection of Spider schemas gave 91% and 75%; it was not a
better algorithm, it was an easier eleven.

Precision is the number that matters. A missing key costs one table; a wrong key is a wrong
identity in every query that walks it, and a wrong foreign key is a join that answers a
different question without saying so.

Recall on foreign keys is the weak spot, and scoring against *declared* references understates
it: dozens more proposals land on columns the schema declares nothing for, and some of those
are omissions in the schema rather than mistakes in the inference. They are counted apart.

## Schema linking: the lever the leaderboards agree on

Every system at the front of BIRD and Spider 2.0 spends most of its effort on one thing —
picking the part of the schema a question is about before writing anything. A conceptual model
is a better thing to link against than a DDL, for three reasons that cost nothing: the readings
are English, the value domains are *in* the model (so a literal in the question says which
column the filter is on), and the model is a graph, so keeping the answer connected is a walk
rather than a guess.

`conquer/link.py` does it with token overlap and a bounded walk — nothing learned, fetched or
fitted — and `bench/pilot/linking.py` scores it against the tables BIRD's gold SQL actually
touches, over all 500 mini-dev questions:

| setting | every gold table kept | of the model kept |
|---|---|---|
| 20 seeds, no hop | 67% | 8% |
| **40 seeds, no hop** | **94%** | **27%** |
| 20 seeds, one hop | 98% | 69% |

The shape of that curve is the finding: **more seeds beats more hops.** A hop is
indiscriminate — it takes everything adjacent — where a seed is a word the question actually
used. Forty seeds and no hop keep every table the answer needs for 94% of questions while
dropping three quarters of the model.

Two cautions worth more than the numbers. Tuning on the first 120 questions said the knee was
at twenty seeds; the full 500 said forty, because the first 120 covered three of the eleven
databases. And the method's first hour produced 87% recall for a reason that had nothing to do
with method: the tokeniser did not split camelCase, so `IncomeAmount` matched no question ever
asked. Fixing that was worth ten points, and no amount of tuning would have found it.

## The benchmarks are shakier than the systems

Running Spider 2.0's own gold SQL against its own databases and grading it with its own
evaluator: **it reproduces its own recorded answer for 14 of 23 gradable local tasks.** For one
task the shipped CSV holds championship winners and the shipped SQL sums points. Another ships
two accepted answers that contradict each other.

That is the same measurement Jin et al. (CIDR'26) report as a 66% annotation-error rate for
Spider2.0-Snow — asked here of the slice that runs offline.

`bench/spider2-trial/calibrate.py` asks that question of any benchmark, and it is worth asking
before believing any score, including the ones on this page.

## A second benchmark, where the schemas are worse

BIRD's databases have seven tables. [LiveSQLBench](../bench/livesql/README.md) is the
enterprise kind: dozens of tables per database, `jsonb` columns nobody documented, and a
1,090-entry knowledge base of definitions handed to *every* competitor — so the definitions
that were worth +8 above are table stakes here. Its SQLite tier is 180 SELECT questions over
18 databases whose gold, sent on request, can be scored offline. Same method:
fresh blind writers, one per database, the gold withheld from them.

| ConQuer arm | of 180 | what changed |
|---|---|---|
| as first recorded | 71 | |
| after the listing said what identifies each type | 79 | finding 156 |
| after it opened the JSON columns, and `log10` was spelled natively | **82** | finding 157 |
| after the four query forms writers kept asking for | 82 | finding 158 — used everywhere they applied, moved nothing |
| the same 82 through the benchmark's own harness | 77 | it strips the `DISTINCT` our `DEFINE` bodies rely on, and checks order on ties |
| **plain SQL from the DDL, same knowledge base** | **85** | |

Two cautions on reading that column. The rows after the first come from fresh writers re-run
on the eight databases the SQL arm had won, swapped into the recorded arm — databases chosen
after the fact, with no re-run of the other ten to say what re-running alone is worth. And the
scores are as recorded at each step: re-scored with today's compiler, the first row is 70 and
the 82 is 81.

**The eleven points were description, not language.** Nine of the seventeen questions the SQL
arm had won were one mistake: asked for a customer's id, the writer listed the wrong one of two
id-shaped columns, with every other figure right. The model had the right identifier all along;
`--schema` had never printed a reference scheme, so it was one `has` among 115. An
*Identification* section fixed it, blind: credit 2→6, cross_db 4→7, crypto 2→3. The next three
were JSON columns the model had left opaque. Then the four forms writers had asked for in every
round — an object keyed by a value, a joined string, a percent rank, a median on SQLite — were
built, and three fresh writers reached for all four exactly where they applied and scored what
the previous round had: they had already built the same by hand. The forms bought effort, not
points.

**The gap that is left is not the language's either.** Of the 98 still wrong when this was
counted, the two arms produced *byte-identical* wrong answers on 59 (64 of 99, re-scored with
today's compiler) — two writers, two languages, no contact, converging on the same rows. That
is suggestive rather than proof, since the writers share a model and a knowledge base and can
share a misreading; the ones checked by hand were the gold's error: a variance labelled a
standard deviation, integer division that truncates on every row, join rows counted as
entities. So perhaps a third of this benchmark is unwinnable by anyone, and the addressable
pool is the questions where the arms disagree.

**And it costs tokens rather than saving them**, which is not what the upfront modelling
suggests. Per question, the SQL writer's static prompt (DDL + knowledge base) averages 34.5k
characters; the ConQuer writer's (primer + narrowed listing + knowledge base) 55k. The primer
is 5k tokens SQL never needs, and the listing is *richer* than the DDL it came from — readings,
domains, identification, cautions — which is exactly what the eleven points were. Output is the
one place the language is terser: 690 characters per answer against 755 for hand-written SQL,
and a third of the SQL it compiles to. The reverse engineering and profiling are a one-time
cost per database; they never appear in a prompt except as that larger listing.

**The tier the benchmark is graded on says the same, for the whole conversation.** Large-v1
is PostgreSQL, and nothing here had ever run on one: the recorded answers had run on SQLite
copies, and the SQL arm's were SQLite dialect. With the dataset's dumps loaded into a server,
both arms were written fresh — six databases, 48 questions, twelve blind writers — with the
engine named to the SQL writers and the ConQuer writers told nothing (finding 162). **SQL 21
of 48, ConQuer 20**, both right on 17, and on 14 of the 24 neither gets, the two arms return
*identical* rows against a gold that read the question the other way. Per database they are
within one everywhere. The cost this time is the writers' whole sessions: SQL 640k tokens
and 41 minutes, ConQuer 946k and 76 — 1.5× the tokens, 1.9× the time — spent reading the
primer, searching the listing and trying more before the rows looked right. What the server
did find was the compiler's: eleven dialect defects the copies had hidden, from a comma-join
PostgreSQL scopes differently to a `CAST` that rounds where SQLite's truncates, every one
fixed before the score above (findings 161–162), and a twelfth — a DEFINE joined on the wrong column — fixed since.

**The layer without the language had no detectable effect on a SQL writer who has the DDL.** The arm the
reframing of this repository depended on: the same SQL writers, with the DDL, the knowledge
base *and* the conceptual description in relational terms — table, column, JSON field and
foreign key beside every entry — scored **19 of 48** against 21 without it, and on 23 of
their 29 misses returned the rows the plain arm returned (finding 163). All six said what
they used: the JSON paths spelled out, and which column other tables refer to a thing by.
All six said what they missed: the value domains and cautions, which those models did not
have, because the tier's builder runs no profiling. Read with the +8 and the LiveSQLBench re-runs above, the
layer's value narrows to two things: what people wrote down, and what the rows say. The
structure said twice is not information to someone who can read a DDL.

**Profiled, the same arm scored 23.** The tier's models rebuilt with what the rows say —
domains, cautions, alternate identifiers — and six fresh writers: 23 of 48 against 19 and
21, for 526k tokens (finding 165). But the gains were judgement calls (a stored column taken
over the knowledge base's table, nulls filtered first), none tied to a domain or a caution,
and a swing of four on 48 questions is inside the noise. The writers used the domains and
listed what the profiler still does not say: a column null in every row, three date formats
in one table, snapshots dated before their plant existed. Beside the DDL, the description is
worth somewhere between nothing and a few questions; no measurement here says which.

**Through the MCP server, on BIRD, the description alone matched the DDL.** Twenty-two
writers with nothing but a client to [`mcp/server.py`](../mcp/README.md) — the brief, the
description and the runner all over the protocol, the SQL writers with no DDL — scored
**76 of 100 in ConQuer and 75 in SQL**, the same verdict as the recorded shell-script arms
on 96 and 97 questions (finding 164). The protocol is not a variable. And the SQL arm with
the description alone matched the recorded arm that had the DDL, because BIRD's models carry
the value domains and the writers named the answers those decided. Read with the paragraph
above: the layer matched the DDL when it carried what the rows say, and showed no detectable
effect beside the DDL when it did not — both within the noise band, and read with the
writers' own accounts of what they used.

## At scale, nothing beat the DDL

Every result above had schemas small enough for a writer to take in whole. On LiveSQLBench's
PostgreSQL tier a database is about 54 tables and 980 columns, 30,000 to 55,000 tokens of
DDL, and a writer has to find the part a question needs. That is where a conceptual layer has
a structural reason to help, so four pre-registered rounds tested it, each with its plan
committed before any writer ran and every arm writing SQL with the knowledge base and a
read-only runner.

| round | what the layer gave | layer | DDL arms |
|---|---|---|---|
| [SCALE.md](../bench/livesql/SCALE.md), 100 questions | the profiled description, narrowed to the question | 26 | 29 narrowed, 28 full |
| [SCALE2.md](../bench/livesql/SCALE2.md), 40 questions | the same, with the gaps the writers named filled in | 12 (old: 14) | 13 narrowed |
| [SCALE3.md](../bench/livesql/SCALE3.md), 60 questions | the DDL chosen by the model and annotated with what profiling found; then every business term derived and checked | 25, 25 | 22 plain, same size |
| [SCALE4.md](../bench/livesql/SCALE4.md), 60 questions | the benchmark's own column meanings; then descriptions an LLM wrote from a column profile; then a value index and linking by draft queries | 28, 26, 26 | 28 plain, same size |

**The first round** (finding 166). The model's linking kept every table the gold needed more
often than a DDL retriever of the same size (72 against 51 of 100) before anyone wrote a
query, and the answers did not follow. Writers that can query the database found the tables
anyway; the description, at about 80 kB narrowed, was too large to read; and the misses were
the benchmark's meaning, which profiling cannot supply. It also cost the most.

**The second** (finding 167) filled in what those writers said was missing: value lists and
cautions inside JSON, percentages stored as text, mixed date formats, near-duplicate
spellings, whether several join routes agree, and business terms mapped to columns by shared
words. Writers credited the route and date cautions; all four named the business-term hints
as wrong, and they were removed. The score did not move.

**The third** (finding 168) cut the layer to its difference from the DDL -- the model
choosing the tables, the profiling as comments beside each column, a fifth of the size -- and
added every knowledge-base term derived once, by an agent that never saw a question, and
checked by running it. Writers called the derivations "decisive" and finished in 48 minutes
of writer time against 76 for the plain DDL. The answers came out the same: the annotated
arms' three-point lead is one database where the plain-DDL writer was blocked by the
permission system and submitted nothing; without it, 19 and 18 against 22 of 50. Thirty of
the sixty questions were wrong in every arm and seventeen right in every arm.

**The fourth** (finding 169) tested what Shkapenyuk et al. used to top BIRD without hints
and no round here had: the benchmark's own description of every column, which LiveSQLBench
ships and no writer had been given; one-sentence descriptions an LLM wrote from a column
profile; an index of every text value; and tables chosen by drafting the query first.
Writers credited the descriptions more than anything before -- "the column comments were
essential" -- and the scores did not move: 28 with the meanings and 28 without, 26 with
everything. Without the one blocked cell the full set was 26 of 50 against 24 for the plain
DDL, the only direction in four rounds that favours the layer, inside the noise.

**Retrieval was not the bottleneck** (finding 170). Of 538 wrong answers across the four
rounds, 53% used every table, column and JSON field the gold used and still answered
something else. The rest did leave out a gold table or column -- but on those same questions
the writer with the whole DDL in front of it made the same kind of miss 50 times in 55 and
got the question right once: the misses are choices of which table or column holds the
answer, not failures to find one. A better selector of the model's parts -- BM25, a Steiner
tree, Bird's abstraction -- would help a one-shot writer that cannot widen its view, not these.

**And most of the misses were not the writers'** (finding 171). Question by question, with the
gold, the model and the data side by side: of 132 wrong answers in the fourth round, 71 were
against gold that contradicts its own knowledge base or has a defect, 25 were right answers
failed by the scorer on tie order or rounding, and 31 turned on terms the knowledge base leaves
undefined or questions with more than one reading. None was caused by something the
reverse-engineered model stated falsely, or by a fact it lacked.

Read together: at this scale, for agents that can query the database, the layer tells them
what they would have found, and the misses are how a question is meant to be read -- the
grain of a result, the base of a percentage, age at the event or today, a sort order left
open -- which a description of the schema, however good, does not settle. The profiling is
right about the data and is kept; `conquer/annotate.py` and `bench/livesql/terms.py` are kept
as tools, measured and not recommended as an accuracy lever. Each round had cells compromised
by tooling (writers blocked by the permission system, once the database going down); each is
reported with and without them, and none changes the reading.

**Against the published work.** That better descriptions improve text-to-SQL is established,
and the results above reproduce it where the conditions match. Sequeda, Allemang and Jacob
put an ontology and mappings -- a conceptual layer by another name -- over an enterprise
insurance schema and took GPT-4 zero-shot from 16% to 54% (GRADES-NDA 2024); here, saying
what identifies a thing and what is inside a document took ConQuer writers from 71 to 82 of
180, with no re-run control. BIRD's own evidence hints raise accuracy, and the +8 from
written-down definitions is that finding again -- in plain English as much as in the model.
Metadata from profiling tops BIRD's leaderboard (Shkapenyuk et al., 2025), and generated
table and column descriptions that restate the schema gain under a point (Gao and Luo, 2025),
as restating it gained nothing here. Shkapenyuk et al.'s own largest effect -- BIRD's column
descriptions, +9.8 points for a single-shot writer -- was tested directly in the fourth round,
with LiveSQLBench's, and added nothing. What those studies share is a writer that generates
from the prompt alone, for which the description is the only window onto the database. The
writers here were agents that could query it, and they found the keys, the JSON fields, the
spellings and the join routes for themselves. The gain from description shrinks once the
writer can explore the data; none of these three studies tests that condition, and it is the
one this repository adds.

## What this means if you are building with LLMs in 2026

- **The definitions are the asset.** +8 points, to any writer, in any language. Where they live
  matters much less than whether they exist and are right. A conceptual model is a good place —
  checkable, verbalisable, versioned — but it is not a magic one.
- **How you ask beats how many times you ask.** A reasoning strategy — decompose, plan first,
  build your own examples — beat the base arm by four to six points in the session it was run
  in, at the same attempt cost; re-run, one strategy scored 64 and 62, so the size is not
  established. Sampling one prompt three times and voting is worth 0. Selection stays worth about 3 whatever you feed it.
- **A conceptual query language is not a lever on accuracy.** A stronger writer gained 4–5
  points, at the edge of the ±3 noise band; a verifier pass gained 2, inside it. The language choice is worth nothing
  measurable, and a strong SQL writer given the same knowledge still leads.
- **A conceptual *model* is a lever exactly where the schema is bad.** What identifies a
  thing, what is inside a document, how a code is spelled: on schemas that hide those, saying
  them was worth eleven points, and it was the model that knew. On seven tidy tables there is
  nothing to say that the DDL does not; on a thousand columns, to agents that can query the
  database, nothing we said beat the DDL either.
- **It is not a token saving.** The knowledge that helps is more description, not less, and
  the writer has to be taught the language. Budget for it; cache the constant parts.
- **Refusals sound better than they measure.** Static judgements about meaning almost never
  fire on real authoring, and the one time the trap actually occurred, the check did not cover
  the shape it took. Cheap execution feedback caught what static analysis did not.
- **Score on cleaned data or your number is noise.** Half the gold in the benchmarks the field
  reports on is contestable. Ask whether the gold reproduces itself before you compare systems.
- **Run the control first.** The most instructive mistake here was writing up a real +8 as a
  win for the architecture before running the arm that showed the same +8 without it.

## Shortening the English removes what was helping

The English description of the model is the input that helps a SQL writer, and it is the one
that does not scale: flat verbalisation is one sentence per elementary fact, 55 KB across the
eleven BIRD models and 18 KB for a single Spider 2.0 schema. `model/abstract.py` implements
Bird's 1997 abstraction — twelve weighting rules, major object types, clustering — and says the
same model at a higher level in a third of the space, keeping which values may be absent.

It does not work.

| | DDL only | + flat English | + level-2 English |
|---|---|---|---|
| one prompt | 70 | **73** | — |
| another prompt | 68 | **70** | **68** |

Two things fall out of that table, and the second one needed *two* control arms to see.

**The English gained +2 to +3 under both prompts.** Two independent prompts, same direction,
same size, same asymmetric paired split — each inside the ±3 noise band on its own, so what
the repetition shows is a direction, not a size.

**The abstraction gives a SQL writer nothing over the DDL alone** — 68 against 68, four
questions lost and four won. Three times shorter, and the help is gone with the length.

Two more arms then tested *why*, against a prediction written down first. The flat text is 82%
"each X has at most one Y", so the guess was that a SQL writer reads join cardinality off it.
Strip those sentences and the arm should fall to 68.

| the English it saw | size | of 100 |
|---|---|---|
| none | — | 68 |
| the level-2 summary | 17.5 KB | 68 |
| flat, complete | 54.2 KB | 70 |
| the summary plus cardinality | 21.2 KB | 70 |
| **flat minus cardinality** | **7.8 KB** | **72** |

It went *up*. Removing 82% of the sentences cost nothing, so cardinality is not the ingredient;
and since the best arm is also the smallest, neither is length. What survives is duller and
better supported: **any English description of the model is worth about +2 to +4 over the DDL,
and what it says matters little** — five arms, one prompt, materials differing seven-fold in
size, all inside a four-point band against three-point noise.

The first cut of this experiment ran only the abstract arm and read it against the recorded
flat arms: 68 against 73 and 74, six lost and none won. "Shaping costs five points" is what
that says, and it is wrong. The recorded arms' prompt could not be reproduced verbatim, so the
flat arm was run again under the new prompt (70), and then the baseline under it too (68). The
prompt was worth two points wherever it was applied; the shaping was worth the rest of nothing.
**Two of the four arms in this experiment exist only to make the other two mean something.**

## Where the ceiling is

The oracle over every arm is **82**. Eighteen questions no arm ever got right, and most of
them are the gold's reading of an ambiguous question rather than an authoring failure.
Thirty-four arms and three strategies moved that ceiling by one question.

So the residual is mostly not about how the query was written. That, more than any single arm,
is why the thesis is not rescued by a better compiler.

---

The pilot's write-up, arm by arm, is [`bench/pilot/README.md`](../bench/pilot/README.md); the
LiveSQLBench rounds are in [`bench/livesql/README.md`](../bench/livesql/README.md), and
[`bench/README.md`](../bench/README.md) indexes every experiment. All 165 findings the work
produced, with what each cost and how it was found, are in
[`bench/findings.md`](../bench/findings.md).

---

Next: [8 — Where ConQuer came from](08-history.md).
