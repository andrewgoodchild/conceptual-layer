# conceptual-layer

**A conceptual layer is your database's schema, grounded in its data and described in
sentences, ready for an agent to read.**

Point this at a SQLite or PostgreSQL database and it drafts one: what each thing is and what
identifies it, how things relate and which way a relationship is many, the values a column
actually holds, what is inside the JSON columns, where the rows contradict the documentation
— and, once someone writes them down, what the business's own terms mean. An agent gets it
over MCP, narrowed to the question it is answering. A person can read every sentence, and
correct it.

## When the DDL is not enough

A schema records how data is *stored*. It does not say which of three id-shaped columns is
"the customer", whether an order has one customer or many, what is inside an undocumented
JSON column, that a status is spelled three ways, or what *net worth* means here. Those are
the gaps an agent writing queries falls into, and filling them is where the measured value
is (below).

## How it is kept

The description is an [Object-Role Modeling](docs/01-conceptual-models.md) model: the domain
as *facts* — `Employee has EmployeeSalary`, `each Employee has at most one Department`,
`Client has NetWorth IFF …` — each of which reads as a sentence. ORM is a language modellers
author, as diagrams and as sentences; here the first draft is reverse-engineered from the
catalogue and the rows, and every claim that is a guess is reported as one, for a person to
confirm or correct. The model is what keeps the sentences consistent and checkable — a
definition can be compiled and run against the data before anyone relies on it — and it also
drives ConQuer, an optional query language compiled to SQL, for a query you want checked and
read back in English.

## Relationship to semantic layers

Malloy, MetricFlow, LookML and Cube are the same idea one level down — definitions written
once, above the tables, so every query uses the same *revenue* and the same join path. A
conceptual model can generate one: a derived fact type *is* a metric, with its grain stated.
Where it differs:

- **Drafted from the data as well as the schema.** Some semantic-layer tools generate a
  starting model from the tables; this one also reads the rows — keys and references where
  none are declared, value domains, identifiers, the schema inside JSON columns, where the
  rows contradict the documentation — and says which of its claims are guesses, for a
  modeller to refine.
- **Facts first, measures from them.** What identifies a customer, that an assignment has one
  employee and one project, which values are optional, all stated as constraints.
- **Sentences**, checkable by the people who know the business, and the same sentences a
  query writer is shown.
- **The fan trap, from the model.** Like Malloy and LookML, the compiler sums a fanned-out
  value once per thing that determines it — worked out from the model's uniqueness
  constraints rather than declared per measure — refuses a grouped count the fan-out makes
  ambiguous, and reads any query back in English. [`bench/malloy-probe`](bench/malloy-probe)
  puts the two side by side.
- **Measured**, with control arms and blind writers — including the results that went
  against it.

## The pieces

| | | |
|---|---|---|
| **The model** | ORM facts, constraints, definitions and a relational mapping in one JSON file, verbalised into controlled English; exports to NORMA's `.orm`. | [1](docs/01-conceptual-models.md), [2](docs/02-modelling-in-orm.md), [`model/`](model/) |
| **Reverse engineering** | The model from a SQLite or PostgreSQL database (PostgreSQL through SQLAlchemy): catalogue for structure, rows for the rest — keys and foreign keys (94% and 81% recall on BIRD with theirs stripped), domains, identifiers, JSON schema, profiling cautions — with a report of what it guessed. | [4](docs/04-reverse-engineering.md), [`reverse/`](reverse/) |
| **The description** | `--schema`, narrowed to a question, in the model's sentences or with table, column, JSON field and foreign key beside each entry. | [5](docs/05-the-toolchain.md) |
| **Querying, two ways** | *SQL*, with the description beside you. Or *ConQuer* (Proper, 1994): a path through the model's sentences, compiled to SQL for SQLite or PostgreSQL (and DuckDB's dialect, untested against DuckDB), read back, and summing each value once however the path fans out. | [3](docs/03-writing-conquer.md), [6](docs/06-inside-the-compiler.md) |
| **The MCP server** | The description and both runners for any agent, read-only: `describe_schema`, `run_sql`, `run_query`, `explain_query`, `build_model`, a brief. | [`mcp/`](mcp/README.md) |
| **CLI, diagram, examples** | Every piece is a command needing only the standard library for SQLite; the model draws as an ORM diagram; Chinook and Northwind run end to end against reference SQL. | [`render/`](render/), [`examples/`](examples/) |
| **The measurements** | Harnesses, every writer's answers, 165 findings. | [7](docs/07-what-we-measured.md), [`bench/`](bench/) |

## What it is worth, measured

Blind LLM writers, each given one database and its questions, scored by whether the rows their
query returns match the benchmark's answer. On 100 questions, three points either way is
noise.

**The conceptual model helped only where it said something the DDL does not.** In place of
the DDL it did as well as the DDL and no better; beside it, the same schema restated as
sentences added a few points at most, inside the noise. What helped was content the DDL does
not carry:

- **definitions** the business has written down — **+8** on BIRD, in either language, and just
  as much when a SQL writer read the same definitions as the model's FORML sentences as when a
  ConQuer writer could query them directly;
- **what profiling the rows found** — which column identifies a thing, what is inside a JSON
  column, the values a column holds — which took re-run ConQuer writers on LiveSQLBench from
  71 to 82 of 180 (the databases re-run were chosen after the fact, with no control).

One BIRD question asks how many women were among the patients with the most serious
thrombosis examined in 1997. The database grades thrombosis 0 to 3, and the most serious grade
is 1; the value domain in the listing shows the four grades, and nothing in the schema says
which is worst. Without the definitions, the SQL writer took the highest grade and the ConQuer
writer guessed 3: both queries ran, both returned a number, both were wrong. With them, both
read one sentence of the model's FORML —

> An Examination is a MostSeriousThrombosis IFF Examination [has ExaminationThrombosis: 1].

— and both were right: the SQL writer wrote `Thrombosis = 1`, and the ConQuer writer used
`MostSeriousThrombosis` directly.

So the most valuable thing this project gives an LLM is the model's own sentences — its FORML
and its listing — when they carry what the business has defined and what profiling the rows
found. The ORM structure is what makes those sentences checkable and consistent; on its own,
restating the schema, it was worth little.

**At scale it may not help over the DDL.** On schemas of about 980 columns, four
pre-registered rounds found nothing -- the model's description, the annotated DDL, business
terms derived and checked, even the benchmark's own column descriptions -- that beat a DDL
narrowed to the question: agents that can
query the database find the structure themselves, and what decides their answers is how each
question is meant to be read, which no description of the schema supplies
([docs/07](docs/07-what-we-measured.md#at-scale-nothing-beat-the-ddl)). That a better
description of the schema helps an LLM write SQL is a known research result, but it is a
result for one-shot systems; once the LLM iterates and explores the data itself, the benefit
diminishes.

**ConQuer, the language, gave no measurable help, and it cost more.** Given the same
information, ConQuer writers and SQL writers scored the same on every benchmark: 71 v 70 and 76
v 74 on BIRD, 82 v 85 and 20 v 21 on LiveSQLBench's two tiers. A ConQuer writer never writes a
join — the model supplies the path, and a query is about a third the length of the SQL it
compiles to — but the queries came out no shorter than the SQL writers' own on BIRD, and about
a tenth shorter on LiveSQLBench. They took more attempts to get right (1.7 against 1.25 per
question on BIRD), and used 1.3–1.5 times the tokens. The likeliest reason is that the writers
have seen a great deal of SQL and no ConQuer before its one-page primer. What ConQuer does give
is a query read back in English and the fan trap handled from the model: it is for a query you
want checked, not for accuracy.

Every arm, what each writer was given, and the caveats are in [7 — What we
measured](docs/07-what-we-measured.md); the experiments themselves, with every writer's
answers, are in [`bench/`](bench/README.md) — BIRD in [`bench/pilot/`](bench/pilot/README.md),
LiveSQLBench in [`bench/livesql/`](bench/livesql/README.md).

## Try it

```sh
./run-tests.sh
python3 reverse/reverse.py yours.sqlite -o out/ -n yours --infer-domains --profile --infer-identifiers --infer-json
python3 conquer/conquer.py out/yours.ccm.json --schema --relational
pip install mcp && python3 mcp/server.py --sqlite yours.sqlite
```

`reverse.py` exits 1 when its report lists blockers — tables it could not model — and still
writes the model; the report says what each one needs.

Python 3.9 or later, standard library only for SQLite. Optional: `mcp` for the server (Python
3.10 or later), `psycopg` and `SQLAlchemy` for PostgreSQL, `jsonschema` for the schema half of
`model/validate.py`.

## Documentation

[docs/](docs/): [conceptual models](docs/01-conceptual-models.md) · [modelling in
ORM](docs/02-modelling-in-orm.md) · [reverse engineering](docs/04-reverse-engineering.md) ·
[the toolchain](docs/05-the-toolchain.md) · [writing ConQuer](docs/03-writing-conquer.md) ·
[inside the compiler](docs/06-inside-the-compiler.md) · [what we
measured](docs/07-what-we-measured.md) · [where ConQuer came from](docs/08-history.md). Layout:
`model/` the model, `reverse/` the reverse engineer, `conquer/` the description and the
compiler, `mcp/` the server, `render/` the diagram, `examples/`, `bench/` the measurements.

## Tests, proofs and benchmarks

~2,200 assertions, property tests, a round-trip proof that `--normalise` is a fixed point, a
corpus of 2,175 recorded queries that must compile identically after every change, and 165
findings ([`bench/findings.md`](bench/findings.md)). Not a production query
engine: the SQL is meant to be readable, not fast, and the findings include wrong answers the
compiler gave silently until a test caught them. [CONTRIBUTING.md](CONTRIBUTING.md) says
what a claim has to satisfy here.

## Licence

Apache-2.0 ([LICENSE](LICENSE)). The benchmarks, the sources and the sample databases are
fetched by script or kept locally, not distributed. What of other people's work is included —
models derived from the benchmark schemas, short quotations, the 1994 report's keyword table —
is listed with its terms in [NOTICE](NOTICE).
