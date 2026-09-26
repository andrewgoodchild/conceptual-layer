# Documentation

Eight pages, in order. The first three assume you know SQL and nothing else.

| | |
|---|---|
| [1 — What a conceptual model is](01-conceptual-models.md) | ORM from zero: facts rather than tables, constraints, verbalisation, and why you would want one |
| [2 — Modelling in ORM](02-modelling-in-orm.md) | the design procedure, the shapes you will need, four traps, and how to edit and check a model here |
| [3 — Writing ConQuer](03-writing-conquer.md) | the query language from zero, every example runnable against the fixture |
| [4 — Reverse engineering](04-reverse-engineering.md) | a relational database into a draft model, and what to do when the catalogue declares nothing |
| [5 — The toolchain](05-the-toolchain.md) | every command, what refusals are, and the tools worth stealing |
| [6 — Inside the compiler](06-inside-the-compiler.md) | for changing it: the four representations, where judgements live, how to add a construct |
| [7 — What we measured](07-what-we-measured.md) | the research findings on two benchmarks, including the ones that argue against the thesis |
| [8 — Where ConQuer came from](08-history.md) | the published record of the language and its relatives, what each could express, and the other ways of reading a query back as English |

Reference material lives with the code it specifies: [`model/model.md`](../model/model.md) is the
model format, [`conquer/conquer-2026.md`](../conquer/conquer-2026.md) is everything added beyond the
1994 report, [`conquer/README.md`](../conquer/README.md) is the full syntax table,
[`reverse/README.md`](../reverse/README.md) is the full rule table,
and [`bench/README.md`](../bench/README.md) indexes every experiment.

## Glossary

**ORM** — Object Role Modeling. A way of describing a domain as *fact types* (kinds of
sentence) between *object types*, with constraints on which populations are legal. Attribute
free: a salary is a fact about an employee, not a column on one.

**Fact type** — a kind of sentence. `Employee has EmployeeSalary`. Binary here most of the
time, sometimes n-ary.

**Role** — one slot in a fact type; the part a type plays in it.

**Reading** — how a fact type is said, with numbered slots: `{0} has manager- {1}`. The thing a
query writer actually types.

**Entity type / value type** — a thing referred to by something else (`Employee`, referred to
by its number) versus a thing that is its own identity (`185000`, `'ENG'`).

**Objectification** — a relationship treated as a thing in its own right, so it can have
properties. `Employee works on Project` becomes `Assignment`, which has hours.

**Uniqueness / mandatory constraint** — "at most one" and "at least one", stated separately.
Between them they say what a nullable column and a `NOT NULL` cannot.

**FORML** — the controlled English ORM constraints verbalise into. *"For each DepartmentName,
at most one Department has that DepartmentName."* What lets a domain expert reject a model
they would never read as a diagram.

**NORMA** — the open-source ORM 2 tool for Visual Studio. This repository writes `.orm` files
its schema accepts.

**CCM (Common Core Model)** — the JSON this repository stores a model in: the vocabulary, the
constraints, the derivation rules, *and* the mapping down to real tables and columns.

**ConQuer / LISA-D** — the conceptual query language specified in H. A. Proper's 1994 Asymetrix
report, built on ter Hofstede, Proper and van der Weide's LISA-D. You write queries as paths
through the model's own sentences. The report specifies an SQL mapping it never delivered; this repository is that
mapping.

**Path** — a walk through the model: a type, a verb, another type, repeated. The unit ConQuer
is made of.

**Fan trap** — joining two one-to-many paths from the same type, so each multiplies the other's
rows. Sum anything afterwards in plain SQL and the answer is wrong. ORM's constraints can see
it coming, and the compiler sums each value once; how often it matters in practice is
[7](07-what-we-measured.md#the-refusals-never-fire).

**Judgement** — a refusal that is a claim about meaning rather than a failure to parse. Every
one is suppressible with `--permissive`, so its cost can be measured.

**Derivation rule** — a concept whose population is computed rather than stored. `DEFINE` is
the same thing scoped to a single query.

**BIRD / Spider 2.0 / LiveSQLBench** — text-to-SQL benchmarks. All ship gold SQL; a large
fraction of it is contestable, which
[7](07-what-we-measured.md#the-benchmarks-are-shakier-than-the-systems) measures rather than
assumes. LiveSQLBench's schemas are the enterprise kind — dozens of tables, JSON columns, a
knowledge base of definitions handed to every competitor — and it is where the layer's value
finally showed.

**Identification** — what names an instance of a type: the value the schema refers to it by.
`--schema` prints it for every type, because a writer asked for "the customer ID" otherwise
picks whichever id-shaped column sounds right, and there are usually several
([7](07-what-we-measured.md#a-second-benchmark-where-the-schemas-are-worse)).
