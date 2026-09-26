# ConQuer 2026

ConQuer-92 is a 1994 language whose every design cut was made to fit SQL-92 (§1 of the
report: *"LISA-D has been restricted … to ensure that the language can be implemented on top
of SQL-92"*). Thirty years on, the target has moved and the constraint has expired. This
document is the list of what was changed so the language can compete on a modern text-to-SQL
workload on its merits rather than on its vintage — each item weighted by how often BIRD's 500
gold queries need it, and each with the reason the original spec lacks it.

The measurement behind the weights: every construct in the 500 mini-dev gold queries, and the
per-question trace of the 70 we scored (`bench/archive/hand-run/README.md`, "Where the
six-question gap actually comes from"). Of the six questions direct SQL won and ConQuer lost, four were semantics rather
than authoring: integer division, total-role `NULL` handling, nested aggregation, nested
limits. Those set the order below.

Nothing here touches the algebra of §6. Every change is either a *semantic default* the report
inherited from SQL-92, a *scalar function* (§6.3 says the function library is open), or a
*presentation-level* construct sited beside Ω the way the row limit was.

## 1. Division is real

**Weight: 108 of 500 gold queries divide (22%); 92 of those `CAST` to `REAL` first; 75 divide
one aggregate by another; 59 compute a percentage.** Two of the 70 scored questions were lost
to this (Q37, Q282).

`model/binding-sql92.md` emits `/` as SQL-92's `/`, so `COUNT(x) / COUNT(y)` over integers truncates
to `0`. That is SQL-92's rule, not a conceptual one: a ratio of two counts is a ratio. Every
modern language that took the decision deliberately — Python 3, Malloy, Kotlin — made `/` real
and gave integer division its own spelling.

**Change.** `/` emits real division: `CAST(a AS REAL) / b`. A new function `div(a, b)` is
integer division for the rare case that wants it. `fn.divide` and `fn.div` both live in the
standard function library, so the CCM carries the distinction and the emitter has no special
case.

## 2. A role read to be *shown* is optional; a role read to be *tested* is required

**Weight: 38 of 500 test `IS NULL`/`IS NOT NULL` (8%); 9 of those are in the projection.**
One of the 70 was lost to it (Q23: 1,236 rows vs 1,239, three schools with no street).

`model/binding-sql92.md` §6.1a: reading a role asserts the fact instance has that role filled, so
`Employee has EmployeeSalary s` adds `salary IS NOT NULL`. That is ORM's *total* semantics and
it is right for a *condition* — `WHERE s > 100000` cannot be true of a missing salary, and 23
of the 38 `IS NOT NULL`s in BIRD are exactly this filter, which ConQuer supplies for free. It is
wrong for a *projection*: `LIST n, st FROM School has SchoolName n AND ALSO has SchoolStreet st`
asks to *see* the street, not to require one, and SQL's answer has a `NULL` in it.

`OPTIONALLY has` already expresses the outer join; the problem is that the default points the
wrong way for the more common case. Bird's Table 3.1 makes the same distinction between what a
role's population asserts and what a query does with it.

**Change.** The default is decided by *use*. A role whose value is only projected is read with
an outer join and may come back `NULL`; a role whose value appears in any condition, comparison,
aggregate argument or grouping is read with §6.1a's assertion. `OPTIONALLY` remains for forcing
the outer join on a tested role; a new `REQUIRED` forces the inner join on a projected one.
`--explain` states which reading each role got, since this is a place two people could
reasonably expect different things.

## 3. `has no X`: the missing-fact test

**Weight: 12 of 500 test `IS NULL` in `WHERE`.**

"Schools with no closing date" is a fact about absence. `BUT NOT has SchoolClosedDate` says
it today, through §7.3's `Fr`-ed set difference — if it works, this is documentation; if it
compiles to a `NOT EXISTS` over an absorbed fact type and misses the `IS NULL` case, it is a
fix in the emitter, not the language.

## 4. A scalar conditional

**Weight: 10 of 500 use `CASE WHEN`/`IIF` as a value (2%). The other 79 are conditional
counts, which `THE COUNT OF X [has …]` already expresses.**

§7.5's `IF c THEN d ELSE d` chooses between *bags* and is refused (see `conquer/README.md`).
This is the scalar cousin: `IF c THEN a ELSE b` in expression position, §6.3's `f(P1..Pn)` with
a boolean first argument. Emits `CASE WHEN c THEN a ELSE b END`.

**Change.** `if(c, a, b)` in the function library, and the words `IF … THEN … ELSE …` accepted
where a scalar expression is — inside `LIST`, inside a comparison, inside an aggregate's
argument. Distinct from the bag form by position: after `LIST` or an operator it is scalar;
at the head of a descriptor it is §7.5, and stays refused.

## 5. Pattern matching

**Weight: 21 of 500 use `LIKE` (4%).**

`substr` has been standing in for it (`substr(dn,1,9) = 'Riverside'`). A conceptual language
should say *"District Name starts with 'Riverside'"*.

**Change.** Three boolean functions: `like(x, pattern)` emitting SQL `LIKE`, and the readable
`starts_with(x, s)`, `contains(x, s)`, `ends_with(x, s)` built on it. `instr(x, s)` for the
27 string-function uses that need a position.

## 6. Dates: the two that are missing

**Weight: 83 of 500 use a date function (17%); 73 are `strftime('%Y', …)`, which `year()`
covers. The rest: `julianday` differences (3), `date('now')` (2), `strftime('%m')` (3, covered).**

**Change.** `today()` and `days_between(a, b)`. Age-at-a-date is the pattern behind every
`julianday` use, and it is a subtraction of the two.

## 7. Nested aggregation

**Weight: 19 of 500 select from a derived table (4%); the common shape is an aggregate of a
per-group aggregate.** One of the 70 (Q197: the average per-molecule count of oxygen atoms).

§6.6's group functions aggregate a path. There is no way to aggregate the *result of a
grouping*, because ConQuer-92 has no construct for using one query's result as another's
source — §6.9's macros come closest and are refused.

**Change.** Allow a grouped aggregate bound with `AS` to be aggregated: `THE AVERAGE c FROM
Molecule m AND ALSO THE COUNT OF Atom [has Molecule m] GROUPED BY m AS c`. The CCM already
holds a `Block` whose projection is a grouped calculation; the emitter wraps it as a derived
table and aggregates over it. This is the one item that touches lowering rather than the
function library.

## 8. A limit that applies somewhere other than the whole result

**Weight: 6 of 500 put `LIMIT` in a subquery; 5 use a window function (2% together).** Two of
the 70 (Q244, Q41).

`Query.limit` is outermost-only by design (`model/model.md` §4.1). Per-group and nested limits are
the same missing idea from two directions. Lowest weight on this list; noted so the roadmap
is complete, and left until 1–7 are in.

## 9. `--explain` should see what the compiler cannot refuse

Q12 was lost because `THE MAXIMUM Frpm …` is the maximum of an entity type — a maximum of its
identifier, a string. The compiler did exactly what it was told. A CAUTION here costs nothing
and would have caught it before the query ran: *an aggregate over an entity type aggregates its
identifier, which is rarely what is meant.*

## 10. Several whole-query scalars side by side

**Weight: not counted in the 500-query sweep, which only measured constructs. Two of the
hundred questions in the blind pilot (`bench/pilot/`) needed it and had no way to say it.**

"What is the average of the up votes and the average user age for users creating more than
10 posts?" wants two numbers in one row. "The difference between A and B, and between B and
C" wants three. Each is a whole-query aggregate; ConQuer-92 has `LIST … FROM <path>` for
several values *of the same thing* and a bare aggregate for one value of nothing, and nothing
for several values of nothing. Item 7 did not cover it: that aggregates *over* a grouping,
this sits aggregates *beside* each other.

**Change.** `LIST e1, e2, …` with no `FROM`, where every item is closed — an aggregate, a
constant, or arithmetic, a call or a conditional over those. Each item lowers as a whole query
of its own and the result is one row. A list with a name to bind still needs a path to bind it,
and says so.

## 11. A derivation rule scoped to one query

**Weight: the one thing the Spider 2.0 trial found the language actually short of.**

Three of the four visible-gold tasks written by hand went in on the first or second attempt,
one of them a five-predicate filter across four joins. The fourth, `local309`, asks for the
top driver *and* the top constructor of each year on one row, and there is nothing to say:
`THE FIRST n PER x` gives either one, `THE LIST OF` gives both as nested bags, and nothing
joins two whole grouped results. Roughly a third of the local slice wants a pipeline of that
shape; `local210` wants two monthly counts compared.

§6.11 already names an intermediate and the emitter already renders one as a common table
expression. §6.9's macros are substitution, which composes text and not queries. What is
missing is only the ability to declare a rule without editing the model.

**Change.** `DEFINE <Name> ::= <query>`, any number of them, before the query that uses them.
`::=` is §6.11's own derivation operator with its left-hand side scoped to one query. The
concept is shaped by what the definition lists: one thing makes a derived subtype of it, two
or more a derived fact type whose verb is the name, and a computed column gets a value type
of its own. A definition may be written in terms of an earlier one. Everything after that is
the existing rule machinery, so a definition is emitted as a CTE, verbalised by FORML as
`… IFF …`, and printed back by `--normalise` with the query it belongs to.

The join key has to be a type the model has, which is the conceptual model asserting itself:
an intermediate hangs off the schema rather than floating free.

**The keys a rule implies.** A derived fact type has whatever uniqueness constraints its rule
implies, whether the DEFINE is scoped to a query or the rule is the model's own. A rule whose
block is one row per something -- a grouping, `THE FIRST 1 PER d`, or a path none of whose
steps multiplies its head -- keys the fact type by that something, and the constraint is
added to the model when the lexicon is built (`lower.declare_derived_keys`, finding 115). So
`Frpm has EnrollmentDifference`, derived by `LIST f, d FROM Frpm f ... k - a AS d`, is
functional whether or not the model wrote that down, and a step into it is not a fan-out.
Only a fact type with no constraint at all is touched.

## 12. What a row is against the other rows of its partition

**Weight: three blind writers needed it, on three schemas, and none could say it.**

A group function reduces a bag to one value. Every aggregate this language had did that, and
`WITHIN` (item 28) changed only where the answer is *reported* -- beside each row rather than
instead of them -- not what is being computed. None of that can express what a row is relative
to its neighbours: its rank, the value in the row before it, the middle value of the bag.

The cost was measured rather than argued. A writer asked for a median, could not say one, and
reported `THE AVERAGE` instead: **0.4485 where the median is 0.4097**. Not a missing column --
a different number, in the same shape, with nothing marking it. Another lost the first year of
a year-over-year comparison because a self-join on `y2 = y - 1` drops the earliest row where a
`LAG` would keep it with a null. A third wanted a rank column and had the rows in rank order
with no way to number them.

**Change.** Three functions, each carrying the order its window runs in:

    THE RANK OF x WITHIN g          ->  RANK() OVER (PARTITION BY g ORDER BY x DESC)
    THE PERCENT RANK OF x WITHIN g  ->  PERCENT_RANK() OVER (PARTITION BY g ORDER BY x DESC)
    THE PREVIOUS x BY t WITHIN g    ->  LAG(x)  OVER (PARTITION BY g ORDER BY t ASC)

`ASCENDING` after the ranked value turns either rank the other way up (`THE RANK OF x
ASCENDING WITHIN g`), and `WITHIN 1` -- a constant, so one partition -- is the whole query,
which is what a global rank is within. The percent rank is (rank - 1) / (rows - 1): where a
row stands as a fraction of its partition, which is what a knowledge base means by
"percentile ranking", and what three blind writers built from a rank and a count by hand
before it existed (finding 158).

`THE FIRST n PER` borrows the query's `ORDERED WITH`, and that is right for a top-n: a cut and
a sort want the same order. A rank and a lag do not. You rank *by* the value and lag *along* a
key, and both are usually different from how the answer is sorted -- so RANK's argument becomes
its `ORDER BY`, with rank 1 the largest, which is what the word means outside SQL.

Both are window-only and say so. `GROUPED BY` returns one row per group and leaves nothing to
be relative to; a previous row without an order is not a previous row. Refusing those is the
same discipline as §22's aggregate locality: a query that is well formed and meaningless gets
a reason, not an answer.

`THE STANDARD DEVIATION` and `THE VARIANCE` (item 35, sample rather than population, spelled `THE STDDEV` and `THE VARIANCE OF` as well) sit on exactly the same terms as the median: DuckDB and PostgreSQL have them, SQLite has neither, and a model built for SQLite leaves them out so naming one is refused rather than emitted. A benchmark writer needing a standard deviation built one from three other aggregates -- `sqrt((avg(a*a) - avg(a)^2) * n/(n-1))` -- which is correct and is the sort of thing a query language exists to make unnecessary (finding 148).

That was the position until finding 158. SQLite spells the dispersion now, and the median too: an ordered-set aggregate has no closed form over a *column*, but it has one over a *bag* -- the mean of the middle one or two rows of the numbered derived table -- and a bag is what the compiler already builds for an aggregate over a path of its own. The model carries it as `sqlBagTemplate` beside `sqlTemplate` (model/model.md §3). In place beside `GROUP BY` there is no derived table to number, so a grouped median is re-lowered into a correlated bag of its own, the route §14b built for a value a group repeats; a windowed median has no such route and is refused with the reason.

**Two aggregates that take a second operand.** `THE LIST OF x SEPARATED BY ', '` joins the bag as one string (`group_concat`, `string_agg`); `THE OBJECT OF v BY k` gathers `{k: v, ...}`, one document keyed by a value (`json_group_object`, `jsonb_object_agg`). Both take the grouped form and the `IN` form, and in the `IN` form the second operand is written before the path that binds it, as a projection is: `THE OBJECT OF s BY n IN Employee has EmployeeName n AND ALSO has EmployeeSalary s`. Three blind writers asked for the first; the second is the one gathering shape `THE LIST OF` could not spell, and LiveSQLBench alien_5's gold is it.

`THE MEDIAN` (item 30) belongs here too, and is the one function whose *existence* is a
dialect question rather than its spelling.

## 13. Reading inside a document

**Weight: a quarter of an industrial corpus was invisible.**

253 of LiveSQLBench's 971 tables carry a `jsonb` column, and a model that stops at the column
boundary cannot say anything about what is in it. The obvious move -- a JSON type in the query
language, with a path operator -- is the wrong one twice over. ORM is attribute-free by
construction, and a document column is an attribute bundle; and a path operator is
dialect-specific, so a query carrying one stops being portable.

**Change.** None to the language. A `jsonb` column is a catalogue that stopped short: the
database says "one column of type json" where it means "nine values of known type", and
recovering schema a catalogue failed to declare is what rules 9, 9b and 9c already do. Rule 12
does it one level further in, and the *mapping* carries the path -- next to everything else
dialect-specific -- so a query says `Circuit has CircuitLocationCity` and never learns that a
document was involved.

Three shapes come out of a document column and only one is a record:

| | |
|---|---|
| **record** | keys stable row to row, naming roles -> one fact type per scalar leaf, mapped to a path |
| **map** | keys vary and are themselves data (`{'clay': 15, 'quartz': 60}`) -> in ORM a fact type whose key *plays* a role; detected, reported, and **not** derived, because reading it needs an unnest rather than a path |
| **bag** | free-form -> refused; there is no conceptual content to recover |

Asking "what is the elementary fact here?" is what separates them, and it is the whole argument
for doing this conceptually: a record's keys name roles, a map's keys play one, and a JSON
scalar type flattens that distinction away.

Two things this cost. A path is not a column: it cannot be indexed, so filtering or joining on
one is a scan, and rule 12 does not derive *references* from inside documents. And the declared
type is evidence rather than truth -- `LABOR_COST` is declared `REAL` and holds `"$150.00"`,
which casts to **0.0** in SQLite and raises in PostgreSQL -- so where a population is available
it wins over the declaration.

## 14. Two stated departures from P

**Weight: a reference interpreter found both in its first hour, and nothing else could have.**

`conquer/reference.py` evaluates Proper's P -- the report's §6, the
denotational translation of a path expression to relational algebra -- directly from the data.
Run over ~100 recorded BIRD queries it agreed with the compiler on every one it could reach
*except* two shapes, and neither is a bug. Both are places where this compiler deliberately
does not do what the 1992 semantics says, and until the interpreter existed neither had been
noticed as a departure, because nothing else evaluates P. Unstated is the worst state for a
semantic change to be in. They are stated here.

**14a. `DISTINCT` applies to the projection, not where it is written.** P's `Ds` is a
path-expression operator: `DISTINCT P` removes duplicate tuples from the relation P denotes,
at that point in the path. At a head it removes nothing -- `DISTINCT Race` is already a set of
races -- so `LIST la, lo FROM DISTINCT Race [has RaceName: 'Australian Grand Prix'] has Circuit
has CircuitLat la AND ALSO has Circuit has CircuitLng lo` denotes three identical rows under P,
one per year the race was run. This compiler returns one. `lower.py` lifts any `DISTINCT` in
the path to a flag on the whole block, which is `SELECT DISTINCT` over the projection.

Seven of the ~100 queries have this shape and every one wants the compiler's answer: a writer
who says `DISTINCT` at the head of a query means distinct *results*. The 1992 placement is a
consequence of its relational-algebra framing, where the projection is a separate operator
applied last and `Ds` has to sit somewhere inside. Here it sits on the result. **A query with
`DISTINCT` anywhere in its body returns distinct projected rows.** The normal form prints it at
the head, which is where writers put it.

The same rule holds inside a bag. An aggregate over a path projects the one value it
aggregates, so `DISTINCT` written anywhere in that path is the aggregate's `DISTINCT`: `THE
COUNT OF DISTINCT Employee [has Department is of Employee has EmployeeSalary s WHERE s > 50000]`
counts employees (6), not the rows the bracket's join produces (14), and its normal form `THE
COUNT OF v1 IN (DISTINCT Employee v1 ...)` reads the same. Under P the bracket's bound `s`
makes the rows distinct already and the count is 14 (finding 114).

**14b. An aggregate over a value the path repeats counts each value once.** Item 22, restated
as semantics rather than as a refusal. `THE SUM OF b IN Department has DepartmentBudget b AND
ALSO is of Employee has EmployeeName n` denotes, under P, the sum over a bag with one budget
*per employee* -- 9,300,000 on the fixture, because P sums the relation as it stands and the
relation has six rows. This compiler returns 3,600,000: the sum over the three budgets, each
once.

The rule (finding 79): **when the argument of a group function is determined -- by the
model's uniqueness constraints -- by a node the path reaches, the bag is the distinct values of
that node, not the rows of the block.** The fan trap is the case where P's answer is the one
nobody means, and the uniqueness constraints are what let the compiler know which value is
being repeated. Where the determinant is *not* in the path, the aggregate is refused (item 22)
rather than computed either way; where the group keys pin it (finding 82) it is computed under
`GROUPED BY` too. `COUNT` is exempt: counting a fanned head is ambiguous, and `DISTINCT` is how
the writer says which count they mean.

The rule has no direction. The fan may come *before* the value as well as after it: in `THE SUM
OF Employee has Project has ProjectPriority` three employees are assigned to one project, so its
priority is on three rows, and the sum is 9 -- each project's priority once -- not P's 17. The
determinant is what the uniqueness constraints say fixes the value (Project, here), not what
the path happened to pass through on the way; a value nothing fixes (a fact type with no
uniqueness constraint) is P's bag, one instance per row. The reference interpreter found the
fan-in case on a query the metamorphic suite generated (finding 111).

"That node" is the *nearest* owner: the object whose uniqueness constraint fixes the value,
and no further up. Employee fixes its department's budget too -- one department each -- but
"each budget once" means once per department, so `THE SUM OF Employee has Department has
DepartmentBudget`, two many-to-one steps and no fan-out anywhere, is 3,600,000: the same
relation as the example above, walked from the other end, and the same sum (finding 115).

Under `GROUPED BY` the same rule holds, and a key is read strictly: it pins what it identifies
and what that leads to functionally, nothing above it on the path. When the keys pin the
value's determinant every row of a group carries one instance and the group takes it; when
they do not, the aggregate is re-lowered over a bag of its own, correlated on the keys, where
the deduplication above is ordinary -- `THE SUM OF p GROUPED BY d` over a many-to-many adds a
priority shared by two employees of one department once (finding 117, closing 112). `COUNT`
keeps its exemption under `GROUPED BY` too.

Both are recorded as `KNOWN` in `tests/test_reference.py` and `bench/pilot/reference_check.py`,
which report them as departures and fail only on a disagreement that is *not* one of these.

## What Spider 2.0 says about the ceiling

The weights above come from BIRD, whose gold queries average 31 tokens and are one question
answered by one traversal. Spider 2.0's local slice asks for analytics pipelines instead: 88%
of its visible gold queries use a CTE, and about a third are genuine multi-stage pipelines,
one named intermediate read by the next. Nothing in ConQuer-92 names an intermediate *inside a
query*, which is what item 27 (`DEFINE`, §11) answers; the deepest pipelines it still does not
reach. The measurement, and the trial that followed it on eight of the thirty databases, are
in [`bench/spider2-trial/README.md`](../bench/spider2-trial/README.md).

## What ConQuer-92 restricted away from LISA-D

From the three LISA-D papers the report cites and never quotes at
length. §1 of the report is explicit about the relation: ConQuer-92 is *"a restriction, and a
slight extension at the same time, of the existing language LISA-D ([HPW93], [HPW97],
[HPW94])"*. The extensions are what the rest of this file is about. The restrictions are these,
and they are not gaps in the report — they are choices it made, worth knowing before anyone
proposes one of them here as new.

**Updates, with a semantics worth copying.** [HPW93] §4.7 defines `ADD P` and `DELETE P` where
P is *any* information descriptor. The meaning is not a row operation: `ADD P` is the **minimal
extension** of the population that makes P non-empty, `DELETE P` the **maximal reduction** that
makes it empty. So `ADD Address: 'New York', 'Fifth Avenue', 17` invents whatever abstract
instances and label values it must, `ADD President having-as Hobby` *"assigns an arbitrary
hobby to an arbitrary president"* and may create both, and `DELETE President having-as Hobby`
empties a fact type. A `START-TRANSACTION` / `END-TRANSACTION` pair brackets a sequence, with
the constraints as *"invariant relations (i.e. pre- and post-conditions)"* — a population
between two updates is allowed to violate them. [HPW94] §1 gives the reason the update half
belongs to the language at all: the ISO **100% Principle**, that a conceptual schema prescribes
all permitted states *and transitions*.

Nothing here implements any of that, and `docs/03-writing-conquer.md`'s "no update sublanguage"
is accurate for ConQuer-92 and not for its parent.

**Complex object types, and the two operators that walk them.** LISA-D is defined over PSM,
ter Hofstede's Predicator Set Model, whose information structure ([HPW93] §2.1) carries **power
types** (sets), **sequence types** and **schema types** as first-class object types, alongside
two *separate* partial orders — `Spec` for specialisation and `Gen` for generalisation, with a
function yielding an object type's *Pater Familias*. [HPW94] names the traversals: `CONTAINING`
goes from a power type to its elements, and `COMPRISING` *"embodies the transition from a schema
type instance to instances from its decomposition"*. Query-side, [HPW93] has `GROUP` into sets
by a criterion and `UNITE` to coerce back out.

The CCM has one subtype relation and no set-, sequence- or schema-typed concepts. §6.5's
nesting (`THE LIST OF`, finding 45) is the query-result half of this and not the schema half.
Generalisation as distinct from specialisation is the shape `reverse/` keeps meeting in the
party/discriminator pattern (rule 8) and cannot currently name.

**Constraints written in the language.** [HPW94] §5:

```
CONSTRAINT
 p6: FOR EACH x IN Aircraft:
  NUMBER-OF(Political-entity having-as Air-force CONTAINING
                Squadron COMPRISING Air-Craft x) ≤ 1
```

The report's own §1 claims both uses — the backbone of InfoAssistant's queries, *and*
"InfoModeler for the specification of derivation rules and constraints". **Both are now
implemented**, though the constraint takes the shape a query language can carry rather than
LISA-D's: a constraint carries `violation`, ConQuer whose result must be empty, so the rows it
returns are the counter-examples and one text answers both "does this hold" and "where does it
fail". `conquer.py --constraints` runs them. That is Rel's shape rather than LISA-D's (`ic X()`
against `ic X(x)`, arXiv:2504.10323 §3.5), and it needs no new syntax at all.

What is still missing from LISA-D's form is the universal quantifier that makes the constraint
read as a claim — `FOR EACH x IN Aircraft: NUMBER-OF(…) ≤ 1` says what must be true, where a
violation query says what must not.

**Universal quantification as a construct.** `FOR EACH x IN P HOLDS C` ([HPW93] §4.6). ConQuer
reaches the same answers through division and the set comparators (`WHICH ARE ALL IN`), which
is why the report could drop it; it is a different thing to write.

**For comparison, LISA-D's surface form**, from [HPW94] §4:

```
Political-entity having-as Air-force CONTAINING Squadron known-as Squadron-name '316'
```

Same shape as a ConQuer path, a different lexicon. The published record around it is in
`docs/08-history.md` §1.

## Not on the list, and why

- **`BETWEEN`** (29): two comparisons in a `WHERE` say the same thing. Sugar, later.
- **`COALESCE`** (0), **`LEFT JOIN`** (1), **set operations** (2): the benchmark does not use
  them.
- **Self-joins** (32): ring fact types and §B.2 role references cover the ones that are
  relationships. The remainder are the ring-`OR` case of Q234.

## Status

The numbers are work items in the order they were raised, not the section numbers above:
§11 is item 27, §12 items 28 and 29, §13 item 33 and §14 item 36.

| | |
|---|---|
| 1 real division | **done** — BIRD Q282 recovered; Q37 now a tie of genuine zeros, which `--explain` warns about |
| 2 projected roles optional by default | **replaced by §6.5 confluence, built.** Both Proper (⟕ in confluence) and Halpin (`maybe`) chose an explicit construct over an inferred default; so does this. Q23's street is `has SchoolStreet AS st EACH School …`. `OPTIONALLY` stays as the per-role form. See `docs/08-history.md` §3 |
| 3 `has no X` | **verified**: `BUT NOT has X` already emits `NOT EXISTS (… IS NOT NULL)`. Documentation |
| 4 scalar `if` | **done** — `IF c THEN a ELSE b` and `if(c, a, b)`; a `conditional` Value kind in the CCM. Also fixed: every numeric literal bound as a float, visible once a literal was projected |
| 5 patterns | **done** — `like`, `starts_with`, `contains`, `ends_with`, `instr`; boolean calls stand as conditions |
| 6 dates | **done** — `today()`, `days_between()`; and `year()`/`month()`/`day()` **now actually run**: they emitted `YEAR()`, which SQLite lacks |
| 7 nested aggregation | **done** — `THE AVERAGE c IN (… GROUPED BY d AS c)`; the inner grouping is emitted as a derived table. BIRD Q197's shape |
| 8 limits elsewhere | **done** — `PER x` (a window function) and `(LIST … THE FIRST n)` as a bag with its own limit. Q41's and Q244's shapes. The bag is wrapped as a derived table because in a compound SELECT the LIMIT would otherwise bind to the EXCEPT |
| 9 `--explain` caution on aggregates over entity types | **done** — *"This takes the maximum of Frpm -- an entity type -- which means the maximum of its identifier"*. And `--normalise` now prints the query back in the report's §8 normal form, so what the compiler understood can be read in ConQuer as well as in English |
| 10 whole-query scalars side by side | **done** — `LIST THE COUNT OF A, THE COUNT OF B`, no FROM. Found by the blind pilot, not the sweep |
| 11 §6.2 set operations | **done** — `UNITED WITH`, `INTERSECTED WITH`, `MINUS` over whole queries, as the CCM's `SetExpr`. Not a 2026 item so much as an unbuilt 1994 one |
| 12 §6.11 derivation rules, and the recursion the report parked | **done** — derived fact types and subtypes as rules in the model, walked like readings, emitted as CTEs, `WITH RECURSIVE` when self-referential, verbalised `… IFF …`. The semantic layer proper: a metric is a derived fact type |
| 13 §6.9 macros | **done** — abbreviations by substitution at parse time, as the report defines them; never recursive |
| 14 a computed grouping key | **done** — `GROUPED BY year(d)`, or `year(d) AS y ... GROUPED BY y`. MetricFlow's time dimension. From the semantic-layer round: a modeller could not say "per year" |
| 15 the operand of a group function is a descriptor | **done** — `THE COUNT OF Patient BUT NOT has PatientDescription` counts the difference, as B.2 reads. Arithmetic after it stays outside |
| 16 a subtype named at a node narrows it | **done** — `Patient [is of AbnormalLaboratory]`, `Department [is of Manager]`: a node of its own, joined on identity. Was silently the supertype |
| 17 a grouped aggregate's path continues from the head | **done** — `... AND ALSO THE SUM OF s IN Employee has EmployeeSalary s GROUPED BY d` sums *those* employees; it was a cross product. Fr, §6.4 |
| 18 a bound variable anchors an operand | **done** — `... AND ALSO b has Y` continues from b, not the head; it was a self-join on unrelated identifiers |
| 19 type-incompatible unification refused | **done** — `Card ... AND ALSO Set ...` and `Set: !value` are refused with the correlation form, not emitted as a join on nothing |
| 20 decorrelation | **done** — an aggregate correlated by equality is a grouped derived table joined on the key, not a per-row subquery; finding 15's timeouts gone |
| 21 the leftmost operand of a disjunction | **done** — `[A OR OTHERWISE B]` was A AND B; every operand that only restricts is an alternative. Found by the metamorphic laws, which are now part of the suite |
| 22 aggregate locality | **done** — an aggregate over a value the block repeats is refused, from ORM's uniqueness constraints, and the message names `[...]` as the fix. Malloy's name for it; the fan trap's. No line of the compiler had read the `constraints` array before. Finding 44 |
| 23 §6.5 gathers a nested relation again | **done** — a side path the model allows to be many per junction comes back as a list, not as more rows, which is [HPW93]'s definition; the report flattened it only because SQL-92 could not. `THE LIST OF` is the group function it lowers to, and it carries its own `ORDERED WITH … THE FIRST n`: top-n-per-group with no window function. Finding 45 |
| 24 a schema may not shadow the language | **done** — an n-ary reading contributed `and` as a verb part and ate the `AND` of every `AND ALSO`. A verb part that is a keyword phrase is no longer registered, and each further role of an n-ary gets a verb part of its own. Found by the Spider 2.0 trial; finding 46 |
| 25 an undeclared column type is read from the data | **done** — rule 6c. SQLite allows a column with no type; calling it text made every filter on it compare a string with a number and match nothing. Finding 47 |
| 26 a bracket keeps its disjunction | **done** — `[A] [B OR OTHERWISE C]` meant `(A AND B) OR C`. Finding 48, the half of finding 41 that fix did not reach |
| 27 a query-level named intermediate | **done** — `DEFINE <Name> ::= <query>` before the query: §6.11's derivation operator scoped to one query, so two grouped results can sit on one row. No new machinery below the parser; a definition is a rule, and a rule was already a CTE. Answers Spider 2.0's `local210` exactly |
| 28 `WITHIN`: the partition without the collapse | **done** — `THE SUM OF s WITHIN d` is `GROUPED BY d`'s partition reported *beside* every row rather than instead of them: `OVER (PARTITION BY …)`. A window function in one keyword, and the reason a grouped figure and its rows can sit on one line. Finding 77 |
| 29 row-relative functions | **done** — `THE RANK OF x WITHIN g` and `THE PREVIOUS x BY t WITHIN g`. What a row is *against the other rows of its partition*, which no aggregate can say. Both window-only: `GROUPED BY` returns one row per group and leaves nothing to be relative to, and a previous row without an order is not a previous row. Finding 104 |
| 30 `THE MEDIAN`, where the dialect has one | **done** — the middle value, not the mean. DuckDB has `median`, PostgreSQL `percentile_cont(0.5) WITHIN GROUP`, and SQLite had neither a median nor a percentile, so a model built for SQLite left `fn.median` out and asking for one was refused by name. The first function whose *existence* is a dialect question rather than its spelling. Finding 103. Since finding 158 SQLite spells it too, over the bag (`sqlBagTemplate`), and a grouped median is regrouped into a bag of its own |
| 31 roots and powers | **done** — `sqrt`, `power`, `ln`, `exp`. Their absence was not small: a benchmark writer needing an escape velocity implemented Newton-Raphson inline, six iterations, and a longer version overflowed SQLite's parser because every `AS` binding is inlined textually. Finding 100 |
| 32 a dialect is the function table, not the statement | **done** — `DIALECTS` in `reverse/derive.py`, selected with `--dialect`; twelve entries for PostgreSQL, fewer for DuckDB. Finding 83 measured the *statement* as portable (302 of 344 answers identical between SQLite and DuckDB); the differences live in the function library, where `DOUBLE` is `DOUBLE PRECISION`, `round(double, int)` does not exist, and `INSTR` is `POSITION(… IN …)` with its arguments reversed. Finding 92 |
| 33 a value inside a document is an ordinary fact type | **done** — rule 12. A `jsonb` column is a catalogue that stopped short; where its keys are stable it becomes one fact type per leaf, mapped to a *path* in the relational mapping rather than to a column. The query language gained nothing: `Circuit has CircuitLocationCity` never mentions JSON. Where the keys are data rather than roles (`{'clay': 15, 'quartz': 60}`) it is a fact type whose key plays a role, is detected, and is deliberately not derived — reading it needs an unnest, not a path. Findings 87–94 |
| 34 an undeclared function is refused, not spelled | **done** — an aggregate the model's function table does not carry was emitted as a bare SQL call on the strength of its own name, so a SQLite model with no `median` still produced `MEDIAN(...)` and failed at the database rather than at compile time. The rule scalar functions always had, applied where it never was. And aggregates now read `sqlTemplate` at all: half the dialect seam in model/model.md §3 was dead, because no aggregate had ever needed a spelling other than its name. Finding 103 |
| 35 a round trip through an entity is a join | **done** — `Employee has Department is of Employee` stands on `employee.dept_code` and re-enters the same fact type by a role that is *also* `employee.dept_code`. Same table, same columns, so it read as absorbed and returned the row already in hand: six rows where the colleague pairs are fourteen, silently. Absorption now requires the value in hand to *identify* the instance being entered. Three blind benchmark writers hit it on three schemas; the suite never did and `corpus.py` did. Finding 101 |
| 36 P, evaluated | **done** — `conquer/reference.py`, a reference interpreter over the 1992 core, and two harnesses that run it beside the compiler. 0 unknown differences on ~100 recorded queries; two stated departures, §14. Finding 106 |
| 37 a projection fan-out is a caution | **done** — finding 58: the one real fan trap in 143 authoring attempts multiplied a *projection* six-fold and compiled in silence, because item 22 guards aggregates. `--explain` now cautions when two or more `AND ALSO` branches from one head each reach many per head, names what each reaches, and says the fix: continue the second branch from the first, or gather one with `THE LIST OF`. A single fanning branch is often the point and stays silent |
| 38 percent rank, a rank's direction, `WITHIN 1` | **done** — `THE PERCENT RANK OF x WITHIN g` is (rank - 1) / (rows - 1); `ASCENDING` after the value turns either rank the other way up; `WITHIN 1` is one partition, the whole query, which the normal form always printed and the parser refused to read back. Three LiveSQLBench writers built the percent rank from a rank and a count by hand. Finding 158 |
| 39 an aggregate with a second operand | **done** — `THE LIST OF x SEPARATED BY ', '` (`group_concat`, `string_agg`) and `THE OBJECT OF v BY k` (`json_group_object`, `jsonb_object_agg`), grouped or over a path of their own, where the second operand is written before the path that binds it. The model's function table already admitted a second parameter; the grammar could not say it. Finding 158 |
| 40 the seven frictions writers reported after finding 158 | **done** — `OPTIONALLY e has X` beside `e OPTIONALLY has X`; an expression as the aggregated value in the `IN` form (`THE SUM OF round(s, 0) IN ...`); an ordered `THE LIST OF` of an outer-bound value grounds its sort key with its argument; a listed expression is named the way it was written; a value domain per document path (rule 6b, `apply_document_domains`); the primer says a DEFINE's value type is named for the *variable*; and a window beside `GROUPED BY` may partition only by what a key determines, read off the uniqueness constraints. Finding 159 |

The mechanism under 1, 5 and 6 is `sqlTemplate` on a function (model/model.md §3): a per-dialect
spelling, so the emitter knows nothing about division or dates.
