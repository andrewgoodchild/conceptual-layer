# 5 — The toolchain

Every command in the repository, in the order you would meet them. Nothing here needs anything
outside the Python standard library.

## Getting a working copy going

```sh
./run-tests.sh          # the whole suite; also builds the fixture into .work/
./examples/run.sh       # Chinook + Northwind: derive, validate, render, query
./model/reference/fetch.sh  # NORMA's ORM 2 schema (not redistributed)
./bench/fetch.sh        # BIRD mini-dev: 500 questions, 11 databases, 800 MB
./bench/run.sh          # derive the benchmark models
```

`run-tests.sh` builds `.work/company.sqlite` from `reverse/tests/company.sql`, reverse
engineers it, validates the result, and then runs every test against it. That fixture is what
the examples in these pages use.

## Model → diagram, model → NORMA, model → English

```sh
python3 model/validate.py MODEL.ccm.json          # JSON Schema + the structural invariants
python3 render/orm_render.py MODEL.ccm.json -o model.html    # an ORM 2 diagram in a browser
python3 model/ormcheck.py MODEL.orm               # typed references inside an exported .orm
```

`ormcheck` exists because XML Schema validation is not enough: `ORM2Core.xsd` types every id as
`xs:ID` and every ref as `xs:IDREF`, and an IDREF only proves the target *exists*, never that
it is the right kind of element. A `RolePlayer` pointing at a `Reading` validates cleanly and
would not survive NORMA. It found a real defect on its first run.

`model/forml.py` is a library rather than a command: it turns constraints into the controlled
English NORMA verbalises into, and the reverse engineer's report is its main caller.

That English is flat — one sentence per elementary fact, every sentence the same size — which is
right for a domain expert agreeing to claims one at a time and wrong for anyone trying to see
the shape of a database. `formula_1` is 94 fact types; Spider 2.0's `Baseball` is 341, and its
flat verbalisation is 18 KB in which "Driver has DriverUrl" reads as loudly as "Result is of
Race". This is the *database comprehension problem*, and Bird's thesis gives an automatic
answer:

```sh
python3 model/abstract.py MODEL.ccm.json --ladder     # the rungs and what each drops
python3 model/abstract.py MODEL.ccm.json --level 2    # that rung, in English
```

Twelve weighting rules score each fact type *role* from the constraints around it; the heaviest
role anchors its fact type to a player; the object types carrying the most anchored weight are
*major*, and the next level is the fact types between major types. Everything dropped is
**clustered** under the type it was anchored to rather than discarded, so `DriverUrl` becomes
part of the line that describes Driver:

```
- **Driver** — identified by DriverId. Carries code?, dob?, forename, nationality?, ref, surname.
- **Race** — identified by RaceId. Carries date, name, round, time?, url?.
...
## How they relate
- Each Result is of some Race.
```

`?` marks a value that may be absent, because a summary that loses optionality produces queries
that silently drop rows. Across the eleven BIRD models this turns 55 KB of flat English into
18 KB; `Baseball`'s 341 fact types become a 4 KB description.

It is a better thing to *read*. It is not a better prompt: given to a SQL writer it scores what
the bare DDL scores, where the flat verbalisation is worth two to three points. Use it to
understand a schema, not to feed one to a model —
[7 — What we measured](07-what-we-measured.md#shortening-the-english-removes-what-was-helping).

## Database → model

```sh
python3 reverse/reverse.py DB.sqlite -o out/ -n name
```

| flag | what it does |
|---|---|
| `--json`, `--dsn` | read a catalogue fixture, or a live server, instead of a SQLite file |
| `--analyse-data` | read the data and *report* the constraints it supports; applies nothing |
| `--infer-fks` | apply foreign keys guessed from column names (rule 9) |
| `--infer-keys` | apply keys and references recovered from the data (rules 9b, 9c) |
| `--infer-domains` | apply value constraints the data supports, and types for undeclared columns |
| `--infer-json` | recover the schema inside JSON columns (rule 12): one fact type per value of a record-shaped document, mapped to a path, beside the document itself; with `--infer-domains`, each path's value domain too |
| `--infer-identifiers` | state the second identifiers the data supports (rule 5c): adds to the model, changes nothing in it |
| `--prefer-referenced-keys` | identify a type by the column every foreign key names, where that is not the primary key (rule 1d): *changes* the model |
| `--ignore-names` | score references on the shape of the data alone |

The division is deliberate: everything that *reads the data* is opt-in, because a population
can refute a constraint outright but can only ever make one plausible. See
[4 — Reverse engineering](04-reverse-engineering.md). The passes run in a declared order
(`PASSES` in `reverse.py`), and every model records the flags it was built with in its
`_comment`, so a rebuild is reproducible from the model alone.

## Model + query → SQL → rows

```sh
python3 conquer/conquer.py MODEL.ccm.json --db DB.sqlite "Employee has EmployeeName"
```

| flag | what it does |
|---|---|
| `--primer` | the one-page language primer and the working method — with `--schema --for "…"`, the whole prompt an LLM needs to write ConQuer here. In one session the method beat the base arm; the size did not reproduce ([chapter 7](07-what-we-measured.md#how-you-ask)) |
| `--schema` | what the model lets you say: types, what identifies each one and every column that value is stored in, readings, verb parts, value domains |
| `--schema --for "…"` | only the part of the model a question is about — schema linking, measured in [7](07-what-we-measured.md#schema-linking-the-lever-the-leaderboards-agree-on) |
| `--schema --relational` | the same description with where each thing is stored beside it — table and key, column, JSON field as `col->'a'->>'b'`, foreign key as `referencing -> key` — for a reader who will write SQL rather than ConQuer (finding 163 measured it) |
| `--db` | the database to run against — refused if the model does not describe it, since a model is bound to one physical schema and a *partly* overlapping database would otherwise return wrong rows |
| `--dsn` | a PostgreSQL URL instead of `--db`; read-only, with a two-minute statement limit (needs `psycopg`) |
| `--sql-only` | print the SQL and stop |
| `--show-sql` | print the SQL *and* the rows |
| `--explain` | read the query back in English, with its assumptions and risks, without running |
| `--check` | `--explain`, then run — the check-then-run loop |
| `--strict` | with `--check`, refuse to run when the interpretation carries a risk |
| `--normalise` | the query in the report's §8 normal form: every step explicit |
| `--show-ccm` | the lowered Common Core Model block |
| `--permissive` | do not refuse what is merely meaningless (see below) |
| `--constraints` | run every constraint carrying a `violation` query and name the rows that break it |
| `-f FILE`, `--repl`, `--json`, `--limit` | batch, interactive, machine-readable, row cap |

## The same, for an agent

[`mcp/server.py`](../mcp/README.md) offers the description and the runners over the Model
Context Protocol: `describe_schema` (narrowed to a question, in the model's terms or
relational), `explain_query`, `run_query`, `run_sql`, `build_model`, and a `writing_brief`
prompt in ConQuer and SQL flavours. It is the pilot harness with a network interface — the
two commands every blind writer in [7](07-what-we-measured.md) had — and its README says
which configuration the numbers recommend.

## Refusals and `--permissive`

The compiler refuses some queries that parse perfectly well, because it can tell from the
model that they do not mean what they appear to:

| refusal | what it caught |
|---|---|
| **aggregate locality** | a grouped count over rows the query multiplies — the one form of the fan trap it does not compute through |
| **unrooted node** | a type named but joined to nothing, which ranges over everything |
| **unifiable nodes** | a value equated with an instance, or two unrelated instances |

Each is a `Judgement` — a claim about meaning, not a parse failure — and every one of them
must be suppressible:

```sh
python3 conquer/conquer.py MODEL.ccm.json --permissive "…"
#   suppressed (--permissive): THE COUNT OF here is computed over rows this query multiplies: …
```

That flag is an *instrument*, not a convenience. A refusal that cannot be suppressed is one
whose cost can never be measured: you cannot find out whether the query it blocked would have
given the right answer. `conquer/tests/test_errors.py` holds the compiler to that — it replays
every `Judgement` case under `--permissive` and asserts SQL comes out.

The measurement that flag made possible is the most uncomfortable finding in the project:
[the refusals never fire](07-what-we-measured.md#the-refusals-never-fire).

## Measuring and not regressing

```sh
python3 bench/pilot/corpus.py              # recompile 2,175 real queries, diff the SQL
python3 bench/pilot/corpus.py --rows       # …and say whether an answer actually moved
python3 reverse/tests/test_inference.py    # strip a schema of its keys and score the guesses
python3 bench/spider2-trial/calibrate.py   # ask a benchmark whether its own gold reproduces
python3 conquer/tests/test_metamorphic.py  # property tests over generated queries
```

The corpus needs the BIRD models (`bench/fetch.sh`, then `bench/run.sh`), and `calibrate.py`
needs a local Spider 2.0 clone (`bench/spider2-trial/README.md`); the other three run on a
fresh clone.

Two of these are worth borrowing whatever you are building.

**The corpus** recompiles every query the benchmark pilot ever wrote and diffs the emitted SQL
character for character against a recorded baseline. Any compiler change that alters a query's
meaning has to alter its SQL, so this is the sensitive net — and `--rows` executes old and new
to say whether an answer moved.

**The metamorphic tests** generate queries at random through whatever model they are given and
check *laws* rather than answers: a filter cannot return more rows than no filter; `MAXIMUM` is
unchanged by repetition. They found a bug — `[A OR OTHERWISE B]` compiling to `A AND B` — that
no hand-written case would have. The seed is fixed, so a failure reproduces.

---

Next: [6 — Inside the compiler](06-inside-the-compiler.md).
