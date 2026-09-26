# `conquer/` — the ConQuer-92 → SQL transpiler

Compiles ConQuer-92 query text to SQL-92 against a Common Core Model, and runs it.

```
conquer.py MODEL.ccm.json --db company.sqlite "Employee has EmployeeName"
conquer.py MODEL.ccm.json --db company.sqlite --repl
conquer.py MODEL.ccm.json --sql-only "Employee has EmployeeSalary > 100000"
conquer.py MODEL.ccm.json --schema           # what this schema lets you say
conquer.py MODEL.ccm.json --db X -f queries.cq --show-sql
```

The model must carry a relational mapping: `.orm` cannot hold one (`model/model.md` §6), so the
`.ccm.json` is the file the compiler needs. `reverse/reverse.py` produces one. There is no
importer back from `.orm`, so refinement means editing the CCM JSON.

## The pipeline

```
ConQuer-92 text
   │  parser.py   schema-driven, appendix B of the report; conquer-2026-grammar.ebnf
   ▼
path-expression AST            ConQuer's algebra. Surface operators intact, so §8
   │                           verbalisation could run here. hd/tl live here.
   │  lower.py   model/model.md §0: G2 flatten, A1 coerce, A2 denotations, A3 drop hd/tl
   ▼
Common Core Model block        flat, fully explicit, exportable
   │                           normalise.py runs back up from here: §8's PVerb, the
   │                           block as normalised ConQuer (--normalise)
   │  sql.py     model/binding-sql92.md
   ▼
SQL-92  ─────────────────────► rows
```

The two-level split is the decision recorded in `model/model.md`: the AST is where the report's
semantics are stated, the CCM block is where SQL is one step away.

## What it supports

| ConQuer-92 | Report | Example |
|---|---|---|
| Type specification | B.2 | `Employee`, `Employee e` |
| Denotation `Type: value` | §6.8 | `Department: 'ENG'`, `Employee: 4` |
| Abstract denotation `Type: !x` | §6.8 | `Department: !d` inside a correlated sub-query |
| Mix-fix predicate verbalisation | B.2, §7.1 | `Employee has EmployeeName` |
| Paths through an objectified fact type | §6.1 + G1 | `Employee has Assignment has Project` |
| `AND ALSO` / `OR OTHERWISE` / `BUT NOT` | §7.3 FrSetOper | `... AND ALSO has Department: 'ENG'` |
| Sub-expression `[ … ]` | §6.7 | `Employee [has Department: !d] has EmployeeSalary` |
| Value comparison, symbol or words | §7.5 | `has EmployeeSalary > 100000` |
| `WHERE` + `AND` / `OR` / `NOT` / `SOME` | §6.4 | `WHERE s > 150000 AND s < 180000` |
| `OPTIONALLY has X` | new; B.2 provides the prefix slot | an outer join — keeps rows where the fact is absent, instead of dropping them |
| `WHICH ARE ALL IN` / `THAT INCLUDES ALL` / `MATCHING ALL` | §6.2 | relational division, emitted directly |
| `IS A SUBSET OF` / `IS A SUPERSET OF` / `IS A PROPER SUBSET OF` / `IS A PROPER SUPERSET OF` / `EQUALS` / `IS DISJOINT FROM` / `EXCLUDES` | §6.4, §7.5 | the SetComp family, over two whole head sets |
| `ONLY` | §6.2 `Fr` | keep the head, discard the tail |
| scalar expressions `a * 100 / b`, `f(x)`, unary `-`, parentheses | §6.3, B.3 — **`/` is real division** (`conquer/conquer-2026.md` §1); `div(a, b)` is the integer kind | in a `LIST` item (B.5 makes the list a *scalar expression list*) and on either side of a comparison |
| `THE SUM OF [x IN] P GROUPED BY d, e` | §6.6, B.2 | the group functions, emitted as `GROUP BY` over the enclosing block |
| `… AS name` | B.2 `<confluence element>` | names a computed descriptor so it can be projected — the only way to put a grouped aggregate beside its group key |
| `IFF` | §7.5 | |
| `IF c THEN a ELSE b`, `if(c, a, b)` | new, `conquer-2026.md` §4 | a **scalar** conditional, `CASE WHEN`, anywhere a scalar goes — in `LIST`, in a comparison, inside an aggregate's argument. §7.5's bag-valued `IF` at the head of a query is a different thing and stays refused |
| `THE AVERAGE c IN (… GROUPED BY … AS c)` | `conquer-2026.md` §7 | an aggregate of a per-group aggregate. The inner grouping becomes a derived table; `AVG(COUNT(…))` is not SQL. The operand is parenthesised because it is a whole descriptor, not a path |
| `starts_with` / `contains` / `ends_with` / `like`, `instr` | new, `conquer-2026.md` §5 | boolean functions stand as conditions on their own: `WHERE starts_with(n, 'Riverside')` |
| `year` / `month` / `day` / `today()` / `days_between` | `conquer-2026.md` §6 | spelled per dialect through `sqlTemplate` — `year()` is `strftime('%Y', …)` on SQLite, where `YEAR()` is a runtime error |
| `THE COUNT OF` / `SUM OF` / `MINIMUM` / `MAXIMUM` / `AVERAGE`, `DISTINCT` variants | §6.6 | `THE AVERAGE Employee has EmployeeSalary`. A sum or average over a value the query *repeats* counts each value once; a grouped count over a fan-out is refused — see *Aggregate locality* below |
| `LIST … FROM …` | B.5 | `LIST n, s FROM Employee has EmployeeName n …` |
| `ORDERED` / `ORDERED WITH … DESCENDING` | §6.13, [P57]–[P59] | sorts on the head by default; `ORDERED WITH HEAD/TAIL` names the ends of the path, the direction may be written either side of the key, and the key may be a computed expression (`ORDERED WITH abs(lo) DESCENDING`) |
| `THE FIRST n … PER x` | **new**, `conquer-2026.md` §8 | the first n *within each* x — `ROW_NUMBER() OVER (PARTITION BY x …)`. BIRD Q41's "top 5 in their respective counties" |
| `(LIST … ORDERED … THE FIRST n)` as a bag | **new**, `conquer-2026.md` §8 | a whole query standing where a set comparator wants a bag, carrying its own ordering and limit. "The department with the most employees" feeding an outer question — BIRD Q244's shape. Must list exactly one thing |
| `THE FIRST n` / `THE TOP n` / `… AFTER m` | **new** — no ConQuer-92 counterpart | a row limit, with `AFTER m` as the offset. §6.13 defines only Ω, which sorts and no more; `HEAD`/`TAIL` are sort keys, not a count. Sited on the `LIST` statement beside the ordering, outside the algebra, because a bag has no first element until something orders it. `--explain` calls a limit with no ordering a **risk** and one over a possibly-tied ordering a **caution** |
| `UNITED WITH` / `INTERSECTED WITH` / `MINUS` | §6.2, the CCM's `SetExpr` | over whole queries: `(LIST a FROM …) UNITED WITH (LIST a FROM …)`, or two bare paths listing head and tail. Same arity on both sides; ordered and limited as a whole by a listed name; a chain associates left |
| macros `α(E1, …)` | **§6.9**, `macros` in the model | a named abbreviation of a scalar, a condition or a path, expanded by substitution before parsing goes on, never recursive. `--normalise` shows the expansion; `--explain` says what stood for what |
| `DEFINE <Name> ::= <query>` before the query | **new**, `conquer-2026.md` §11 | a §6.11 derivation rule scoped to one query: name a whole result and walk it as though the model declared it. One thing listed makes a **subtype**, two or more a **fact type** read `has <Name>`. Emitted as a common table expression, like any derived concept. This is what lets two grouped results sit on one row — see *Composition* below |
| derived fact types and subtypes | **§6.11**, `derivationRules` in the model | `f(p1:a1,…) ::= P` written as `LIST a1,… FROM P`; `t ::= P` as the path whose heads are the population. Walked like any reading, emitted as a common table expression, verbalised by FORML as `… IFF …`. A rule may name its own target: **recursion**, the restriction the report parked "until SQL-3", as `WITH RECURSIVE` over the `UNITED WITH` the rule writes |
| `LIST e1, e2, …` with no `FROM` | **new**, `conquer-2026.md` §10 | several whole-query values in one row — two counts, three differences. Every item must be closed (an aggregate, a constant, arithmetic over those); a name to bind still needs a path. The blind pilot found two questions with no other way to say it |
| `Q1 [AS a] [VIA x], … EACH P` | §6.5 confluence | gathers side values onto the base path. The base after `EACH` is required; each element before it is kept when absent. Elements are a bare type (`Budget VIA g`) or verb-led (`has Salary AS s`); the dangling-verb form needs an inverse reading. An element the model allows to be **many per junction** comes back as a nested list rather than splitting the row — see *Nesting* below; one that is at most one per junction is the report's ⟕, a left outer join |
| `… AS h ORDERED WITH k DESCENDING THE FIRST n EACH P` | **new** | an order and a cut *inside* a gathered element: their three most recent orders, per row. Only meaningful once the element is nested, which is why B.2's `<confluence element>` has nowhere to put it |
| `THE LIST OF [x IN] P`, `THE DISTINCT LIST OF` | **new**, §6.6's shape | the one group function whose result is a **bag**: it gathers instead of reducing. `json_group_array` on SQLite. Carries its own `ORDERED WITH … THE FIRST n`, written straight after the path. This is what a nested confluence element reads back as under `--normalise` |
| `THE LIST OF x SEPARATED BY ', '` | **new**, finding 158 | the same bag joined as one string: `group_concat` / `string_agg`. Grouped, or `IN` a path of its own; a `DISTINCT` one takes its distinct in the derived table |
| `THE OBJECT OF v BY k` | **new**, finding 158 | `{k: v, ...}`, one document keyed by a value: `json_group_object` / `jsonb_object_agg`. In the `IN` form the key is written before the path that binds it, as a projection is |
| `THE MEDIAN`, `THE STANDARD DEVIATION`, `THE VARIANCE` | `conquer-2026.md` items 30, 35 | sample forms. Every dialect spells them: SQLite's dispersion as SUM and COUNT, its median over the *bag* (`sqlBagTemplate`), so a grouped median is re-lowered into a bag of its own and a windowed one is refused |
| `THE RANK OF x [ASCENDING] WITHIN g`, `THE PERCENT RANK OF x [ASCENDING] WITHIN g`, `THE PREVIOUS x BY t WITHIN g` | `conquer-2026.md` §12 | row-relative: `RANK()`, `PERCENT_RANK()`, `LAG()` over the partition. Descending by default, so 1 and 0 are the largest. `WITHIN 1` is the whole query. Refused beside a `GROUPED BY` aggregate unless they read a grouped value, and refused over another window -- a DEFINE reaches two rows back |
| `THE SUM OF round(s, 0) IN P`, `THE LIST OF (s * 2) IN P` | **new**, finding 159 | an expression as the aggregated value in the `IN` form, read with forward references like a projection |
| `jsonObject('k', v, ...)`, `json(t)`, `jsonPath(doc, '$.a')` | `conquer-2026.md` §13 | build a document, re-read text as one, read a path. A list of objects gathers objects, not strings |
| `OPTIONALLY e has X`, `e OPTIONALLY has X` | B.2's prefix slot | the same outer join, written before the head or before the verb. Covers one step: every later step needs its own |
| `DOES NOT EQUAL` | §7.5 | lowered as `not (P EQUALS Q)`, since the CCM's `SetOp` has no negated match |
| `DISTINCT` | §6.2 | |

## `AND ALSO` joins; `[ … ]` filters

The distinction is `Fr`, and it is observable. `[Q]` is `Ds(Fr(Q))` (§6.7): a filter on the
head, which **cannot multiply the result**. `AND ALSO` is `Fr(P₁) ∩ Fr(P₂)`, but an operand
that names something has to share the block so the name can be projected — and sharing the
block means joining, which can multiply.

The implementation splits on exactly that: an operand that binds no variable and no `!x`
denotation cannot be referred to from outside, so it is lowered as a correlated `EXISTS`;
one that binds something is merged into the block. Chinook has two playlists named `Music`,
so the two forms give different row counts and the suite pins both:

```
Track [is of Playlist has PlaylistName: 'Music'] has TrackName t     3,290 — filter
Track has TrackName t AND ALSO is of Playlist has PlaylistName p     6,580 — join
```

Sub-expressions sit *between* path segments, as `P ∘ [Q] ∘ R`, so `[…]` attaches to the tail
reached so far, not to the head of the whole path.

## `--explain` and `--check`: read the query back before running it

```
conquer.py MODEL.ccm.json --explain "Track [has TrackName n] has Album has Artist"
conquer.py MODEL.ccm.json --db X.sqlite --check           "..."   # report, then run
conquer.py MODEL.ccm.json --db X.sqlite --check --strict  "..."   # refuse if risky
conquer.py MODEL.ccm.json --explain --json                "..."   # for a caller to act on
```

Report §8 is thirty pages of verbalisation rules, and `model/model.md` §8 says they belong on
the AST "where the surface operators still exist". `verbalise.py` is that pass, aimed at the
problem the BIRD run exposed: **every failure that survived was a misreading, not a
mis-compilation.** A wrong column, an ambiguous phrase resolved the other way, a join path the
question did not imply — none of those are visible in the SQL unless you already know the
schema. All of them are visible here.

It prints the query as a sentence built from the model's own predicate readings, then four
lists:

| | |
|---|---|
| **Resolved** | which fact type each verb picked, and what it reached |
| **Expanded** | abbreviations the lowering materialised — `Customer: 1` walking the reference scheme, `!x` binding the instance rather than its value |
| **This query requires** | facts the query silently insists exist, because reading an optional role drops rows where it is absent |
| **Worth checking** | a verb that could have meant several fact types, a set comparison's quantifier, an aggregate that may be counting fan-out |

Every finding carries a **severity**, which is what makes the report actionable rather than
merely readable:

| | |
|---|---|
| `!` **risk** | the query will silently return the wrong rows — a dropped optional fact, or a verb ambiguity resolved by taking the first reading |
| `?` **caution** | worth a look, usually fine — fan-out under an aggregate, a set comparison's quantifier |
| `-` **note** | an abbreviation the lowering expanded, recorded so it is not a surprise |

`--check` prints the report and then runs. `--check --strict` refuses to run while any risk
stands, exiting non-zero — so a caller writing queries can loop: write, read the
interpretation, revise, run. `--json` gives the same thing as a structure, with a
`risk_count` to branch on.

The third list is the one that earns its place. On the BIRD question that asked for schools
"opened after 1991 **or** closed before 2000", the ConQuer arm returned zero rows; `--explain`
says *"Satscore must actually have a SchoolClosedDate — rows where it is absent are dropped"*,
which is precisely the bug, stated before the query runs.

## `--normalise`: the query back in ConQuer, as the compiler understood it

```
conquer.py MODEL.ccm.json --normalise "LIST n FROM Employee has EmployeeName n AND ALSO has Department: 'ENG' ORDERED"
LIST n FROM Employee v1 has EmployeeName n AND ALSO has Department has DepartmentCode: 'ENG' ORDERED WITH v1 ASCENDING
```

Report §8 defines `PVerb`, the arrow from a path expression back to text, and §10 says what
it is for: *"a non-ambiguous subset of ConQuer-92 which is used to verbalise path-expressions
in a normalised form ... and a more liberal ConQuer-92 language from a user's point of
view"*. The stored artifact is the path expression; the text is regenerated from it.
`normalise.py` is that arrow, from the lowered block. Normalised means:

- every step is explicit — `Department: 'ENG'` is spelt through its reference scheme;
- the path is a line — a node with two continuations shows one on the line and the other as a
  filter `[ … ]`, and `AND ALSO` survives only at the head, where it is the Fr operator;
- everything referred to has a name — the column's, where the author gave one, else `v1`,
  `v2`; a sort key that was only bound gets one; `ORDERED` alone names the head it sorts on;
- a node unified with the enclosing block is `Type: !x` (B.2); a ring fact type steps by its
  own reading where it has one (`has manager Employee`) and is entered and left by role name
  where its reading is only the placeholder; a reading walked backwards uses its inverse;
- a grouped aggregate is declared once with `AS` and referred to by name ([V29]); an aggregate
  over a path aggregates its last node, and anything else is named — `THE AVERAGE v IN (…)`;
- an outer join is `OPTIONALLY`, whether it was written that way or as a confluence element;
  a *nested* confluence element is `THE LIST OF …`, which is what it lowers to;
- brackets only where precedence needs them.

The proof it is faithful is a round trip, `tests/test_normalise.py`: every query in the
operator suite and every BIRD answer in `bench/` is compiled, normalised, and the normalised
text compiled again — same rows, and normalising *that* gives the same text back. So what
`--normalise` prints is not a paraphrase: it is a query the compiler reads identically, with
nothing left implicit. `--explain` prints it too, under **Normalised**, beside the English:
same information, two languages — one for a reader who does not know ConQuer, one for a
reader who wrote the query and wants to compare. [`docs/08-history.md`](../docs/08-history.md) §5
sets this beside the other query verbalisers.

## Aggregate locality

A block is one flat join, so its rows are one per combination of everything the query
reaches. An aggregate over that is right only when the block has one row per (what is
aggregated, what it is grouped by). Branch off the way to the aggregated value with a path
that fans out and it is not:

```
LIST d, t FROM Department has DepartmentCode d AND ALSO has DepartmentBudget b
             AND ALSO is of Employee e AND ALSO THE SUM OF b GROUPED BY d AS t
```

Each department has one budget and three employees, so the budget is on the row three times
and `SUM` adds it three times. The query is well formed, the SQL runs, and the number is
wrong by a factor nothing in the answer shows. Malloy calls getting this right *aggregate
locality*; it is the classic fan trap, and it is the one class of silent wrong answer a
conceptual model already holds the answer to — a uniqueness constraint on a role says
whether entering through it can multiply.

So the compiler does not add it three times. A `SUM` or `AVERAGE` over a value the query
repeats is computed once per thing that determines the value: where the group keys pin it,
as here, the group's one value is taken; where they do not, the aggregate is re-lowered over
a bag of its own, correlated on the keys, and deduplicated there (finding 117). `MINIMUM` and
`MAXIMUM` need nothing.

`COUNT` is the exception. Counting over a fan-out has two readings — the rows or the things —
and deduplicating it scored worse over the recorded corpus than leaving it (findings 78, 79).
Ungrouped, it counts the rows as written; grouped, where the keys do not pin what is counted,
it is refused, and the message names the bracket that says which:

> THE COUNT OF here is computed over rows this query multiplies: one Department has many
> Employee … Put the multiplying path in brackets and bind nothing inside them —
> `[Department has Employee]` matches without joining, so it cannot multiply — or aggregate
> over Employee itself.

§6.4's `[…]` is `Ds(Fr(Q))`, a semijoin. ConQuer already had the operator that cannot
multiply; what it lacked was anything that noticed when you had not used it.

Read with care, because reading only the *single-role* constraints refuses correct queries.
`Employee x has Project has ProjectName v … THE COUNT OF x GROUPED BY v` crosses a
many-to-many, so entering `Assignment` does fan out — but `Assignment` carries a uniqueness
constraint spanning **both** its roles, so there is one row per (employee, project) and the
count is right. A fan-out is harmless when some uniqueness constraint of the fact type it
reaches is satisfied by values the group already fixes, and that test runs to a fixed point,
because a fact type pinned that way pins what it leads to. `MINIMUM` and `MAXIMUM` are never
refused: repetition cannot change them. Nor is a `DISTINCT` aggregate, which says the
repetition was meant to be dropped. A model that declares no uniqueness constraints at all
has not said anything is many-to-one, and the check does not run.

## Composition: `DEFINE`, a derivation rule for one query

The Spider 2.0 trial (`bench/spider2-trial/`) found that expressibility was not what the
language was short of — a five-predicate filter across four joins went in on the second
attempt — but **composition**. Ask for the top driver *and* the top constructor of each
year, on one row, and there is nothing to say: `THE FIRST n PER x` gives you either one,
`THE LIST OF` gives you both as nested bags, and nothing joins two whole grouped results.

§6.11 already names an intermediate, and the emitter already renders one as a common table
expression. What was missing was a way to declare one without editing the model:

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

Two `WITH` clauses and a join, and it answers Spider 2.0's `local210` exactly. The rules are
the report's, not new machinery: what a `DEFINE` adds is a concept shaped by what the query
lists, and then `lower_rules` treats it like any rule in the model.

- **One thing listed** makes a derived **subtype** of that thing: `DEFINE BigEarner ::= LIST e
  FROM Employee e has EmployeeSalary s WHERE s > 150000`, then `BigEarner has EmployeeName n`.
- **Two or more** make a derived **fact type** whose verb is the name: `DEFINE TopEarner ::=
  LIST d, e FROM …`, then `Department has TopEarner has EmployeeName a`. A bare path with no
  `LIST` defines the relation of its two ends.
- A listed thing that is **computed** rather than reached gets a value type of its own, named
  `<Name><Column>` — `FebFinishedOrders` above. Name the listed column well and the query
  reads well.
- A definition may be written in terms of an earlier one, so a chain of stages composes.
- `--explain` reports each one as the derivation rule it is, in FORML: *"TopEarner is derived
  (§6.11): Department d has TopEarner Employee e IFF …"*. `--normalise` prints the
  definitions back with the query, because a normal form that dropped them would not be a
  query anyone could run.

The join key has to be something the model has a type for. That is not a limitation so much
as the conceptual model asserting itself: an intermediate hangs off the schema, it does not
float free, and if your key is a computed value there is nothing to hang it on.

## Nesting: §6.5 as [HPW93] meant it

§6.5's confluence is the one place ConQuer-92 says it knowingly departed from LISA-D:

> Since SQL-92 is not able to deal with nested relations, we have changed the definition
> slightly as opposed to the one used in [HPW93].

LISA-D's confluence gathered a **nested relation**. Flattened to an outer join it costs more
than it looks: gathering an employee's assignments does not put three rows of hours on one
employee, it turns the employee into three rows, and every other gathered value and every
aggregate beside them is repeated with them. SQLite can deal with nested relations, so a side
path the model allows to be many per junction is gathered as one again:

```
LIST n, h FROM has Assignment has AssignmentHours AS h EACH Employee has EmployeeName n
  →  Ada Lovelace   [120,40]
     Betty Holberton []
```

`json_group_array` per junction, and an absent side path gathers the empty bag rather than a
null. A side path that is at most one per junction is still flattened, exactly as before —
so `has EmployeeSalary AS s` is a column, not a list of one. That is the same functionality
test the locality check uses, and the two features are the same idea pointed at the two
places rows get multiplied.

A nested element takes an order and a cut of its own, which a flat one had no use for:

```
LIST n, h FROM has Assignment has AssignmentHours AS h ORDERED WITH h DESCENDING THE FIRST 1
             EACH Employee has EmployeeName n
```

That is top-n-per-group without a window function. The same thing is directly expressible as
a group function, `THE LIST OF`, which is what the confluence lowers to and what
`--normalise` prints it back as.

## What it does not

`EACH` is both the confluence operator and an article the report's examples use freely
(`each Person has a Name`). The two are locally indistinguishable — a dangling verb precedes
the operator, a verb precedes the article — and the report resolves it typographically:
formal items are set in a distinct style. Here that style is upper case: `EACH` is the
operator, `each` is the article.

Everything below is in the grammar and not compiled. Each *parses* and refuses with the
reason, rather than being silently absent or — worse — silently meaning something else:
`EXCLUDING` had been wired to disjointness, which is the *plain* circled-times of §6.4
(`IS DISJOINT FROM` / `EXCLUDES`), a different operator.

- **`THE PATH FROM … VIA … TO …`** (§6.2 `Path`), **`THE REVERSE OF`** (§6.1 reversal),
  **`WITH`** (cartesian product), and the underlined circled-times of §6.2 spelled
  **`MISSING`/`EXCLUDING`**.
- **The `selection` production** (B.2, [P36]–[P38]): `IF c THEN d ELSE d`, and the
  alternatives sequence `d IF c; d IF c OTHERWISE d`. Both branch on which *bag* is
  returned, so neither is a SQL `CASE` expression.
- **Descending into a subtype.** A path walks from a subtype up to its supertype's roles, not
  the other way. Where reverse engineering reads a 1:1 foreign key as subtyping (rule 7's
  vertical-partitioning trap) the two halves become unreachable from the supertype — which is
  why BIRD Q27 still cannot be written as gold writes it, even with `OPTIONALLY`.
- **A variable may not share a name with a type.** `... has TrackName track` reads `track` as
  the entity type `Track`, not as a variable. This is report §7's ambiguity showing through;
  the parser has no way to prefer one reading, so it takes the type.

## Ambiguity

Report §7 calls the ConQuer grammar ambiguous, and it is: a verb part like `has` names dozens
of fact types. The parser resolves by filtering candidates against the type the path has
reached, then against the type named next, and **raises rather than guessing** when more than
one survives:

```
$ conquer.py model.json "Employee has Project"
ambiguous: 'has' from Employee is ambiguous between EmployeeHasNr, Assignment,
EmployeeHasName, ... -- name the type it reaches
```

This is the honest behaviour, but it is not the schema-driven parser report §7 describes,
which uses the full typing relation 𝕋 and the head/tail combination function 𝕃 to prune. That
remains the project's largest open design point.

Reverse-engineered schemas make this worse than it needs to be, because every reading is
`{0} has {1}`. Renaming predicates in NORMA is what makes queries readable *and* unambiguous —
`Employee works for Department` collides with nothing.

## Worth knowing about the SQL

Two behaviours from `model/binding-sql92.md` show up immediately.

**Absorbed fact types cost nothing** (§3). `Employee has EmployeeName` walks two path steps
and emits:

```sql
SELECT employ1.emp_nr AS "Employee", employ1.emp_name AS "EmployeeName"
FROM employee AS employ1
```

No join. The model is fully explicit — the reference scheme is real path steps — but the
mapping puts them in the same table, so nothing reaches the SQL.

**Set comparisons are emitted directly** (§5), not through a `¬∃¬` encoding:

```
LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project
           WHICH ARE ALL IN Employee: 4 has Assignment has Project
```
```sql
SELECT employ1.emp_name AS "n" FROM employee AS employ1
WHERE NOT EXISTS (SELECT assign2.proj_code AS "v" FROM assignment AS assign2
                  WHERE assign2.emp_nr = employ1.emp_nr
                  EXCEPT
                  SELECT assign4.proj_code AS "v" FROM employee AS employ3
                  JOIN assignment AS assign4 ON assign4.emp_nr = employ3.emp_nr
                  WHERE employ3.emp_nr = ?)
```

That is why `setCompare` is first class in the CCM rather than sugar over negation (G4).
Note it returns employees with *no* assignments too: the empty set is a subset of anything,
which is what `⊆̲` means.

## Null semantics

Two separate questions, and they now have different answers.

**Fact existence: settled, in the report's favour.** Reading a role asserts the fact instance
has it filled. Where the fact type is absorbed into an entity's table no join enforces that,
so the emitter adds `IS NOT NULL` on the mapped columns (`model/binding-sql92.md` §6.1a). Found
by a real query: `Employee has Employee` — a self-referencing `ReportsTo` — was succeeding for
employees with no manager, because reading a null column is not an error in SQL. So
`Track has Album` now returns the 3,503 tracks that have an album, not all 3,503+ rows with
nulls among them.

**Negation: still SQL's, not the report's.** `NOT (…)` is emitted plainly, so three-valued
logic applies and `BUT NOT` does not return rows where the compared column is null. The
report's `¬C` is two-valued and means "the condition does not hold", i.e.
`NOT (…) OR … IS NULL`. Unchanged, because which is right depends on what the schema's nulls
mean, and §6.1a removes the case where it bit in practice.

## Layout

| File | |
|---|---|
| `parser.py` | Tokeniser, schema lexicon (verb parts come from readings), recursive-descent parser, AST. |
| `lower.py` | AST → CCM block. Denotation expansion, reference-scheme materialisation, verb resolution. |
| `sql.py` | CCM block → SQL. Anchors, join elision, set comparisons, aggregates. |
| `verbalise.py` | AST → English, plus the interpretation report behind `--explain`. |
| `normalise.py` | CCM block → normalised ConQuer: report §8's `PVerb`, behind `--normalise`. |
| `link.py` | Schema linking: which part of a model a question is about, behind `--schema --for QUESTION`. |
| `reference.py` | A reference interpreter: the report's §6 meaning of a path, evaluated directly from the data, to check the compiler against. |
| `conquer.py` | CLI and REPL. |
| `conquer-2026.md`, `conquer-2026-grammar.ebnf` | The language as implemented: what was added beyond the 1994 report and why, and its grammar. `tests/test_spec.py` fails if the parser accepts a phrase none of them names. |
| `primer.md`, `method.md` | The prompt a query writer is given: the one-page language primer and the working method. `--primer` prints both, and the MCP server serves the primer. Every example in the primer is checked by `tests/test_primer.py`. |
| `tests/queries.cq` | 19 queries covering the table above. Run with `run-tests.sh`. |
| `tests/test_operators.py` | **One case per operator in the ConQuer-92 lexicon**, mirroring the keyword table in appendix B of the report line for line, so spec coverage is readable at a glance. Each asserts either what the operator computes (against reference SQL) or the reason it refuses to compile. 208 cases. |
| `tests/test_metamorphic.py` | **Sixteen laws that hold between queries, over paths generated from the model and literals drawn from the data.** A filter never adds rows; a filter and its complement partition the type, and united they are the whole; two filters commute; inclusion and exclusion; grouped counts sum to the whole; a value type's domain partitions the walk; an aggregate counts and adds exactly what listing the same path returns; the extremes are the ends of the ordering; a denotation is a comparison; ordering permutes and drops nothing; the first n are the n smallest. Neither side of any law is a reference answer, so a violation says the compiler disagrees with itself, which is the shape of nearly every silent wrong answer the pilot found. 621 assertions on the fixture, the same 621 every run (the seed is fixed), and it runs against any model with a database. |
| `tests/test_verbalise.py` | The sentence and each section of the `--explain` report. What it *says* is the contract, so the assertions name the wording. 53 cases. |
| `tests/test_normalise.py` | The §8 normal form: cases naming the text a rule produces, then the round trip over the whole operator suite — recompile the normalised text, same rows, fixed point. |
| `tests/test_derived.py` | **§6.9 macros and §6.11 derivation rules** on the fixture: a derived value, a recursive derived relationship checked against a hand-written recursive CTE, a derived subtype; the FORML `IFF` sentences; scalar, condition and path macros, nested and refused when recursive; the `--explain` notes; the validator on source-only rules. 31 cases. |
| `tests/test_mapping.py` | **Does the SQL join the columns the schema says?** Builds a database whose identifiers collide on purpose, derives it, and checks rows both ways round. Exists because the BIRD pilot found a foreign key to a unique column joined to the primary key, returning plausible wrong rows. 20 cases. |
| `tests/test_errors.py` | **What the compiler says when the query, or the model, is wrong.** Asserts the exception class *and* a phrase from the message — a mistyped name, an unbound variable, half-finished input, a mapping that does not hold together, and every `Judgement` replayed under `--permissive`. 41 cases. |
| `tests/cases/*.cases` | Query cases paired with reference SQL, checked row for row. |
| `tests/compare.py` | Runs both sides and compares the result sets as multisets. |

## Verified against real databases

`examples/run.sh` runs 39 cases against Chinook and Northwind (one, slow, behind `--slow`),
reverse engineered with no hand editing, each ConQuer query checked against reference SQL
rather than merely executed. All pass; the largest matches on 609,283 rows. The Chinook
reference SQL comes from a published exercise set, so those results are checked against work
done with no knowledge of this project. See `examples/README.md`, including the six bugs those
schemas found.