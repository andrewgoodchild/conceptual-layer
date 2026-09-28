# 3 — Writing ConQuer

ConQuer is a query language you write in the model's own sentences. It was specified in 1994
by H. A. Proper (*ConQuer-92 — the revised report on the conceptual query language LISA-D*,
Asymetrix Report 94-5, now [arXiv:2105.11926](https://arxiv.org/abs/2105.11926)); the report
defines the language and promises an SQL mapping it never delivers. This repository is that
mapping.

Everything below runs. Build the fixture first:

```sh
./run-tests.sh          # writes .work/company.sqlite and .work/company.ccm.json
alias cq='python3 conquer/conquer.py .work/company.ccm.json --db .work/company.sqlite'
```

And before writing anything, ask the model what it lets you say:

```sh
cq --schema
```

## A query is a path

The smallest query is a sentence from the model:

```sh
cq "Employee has EmployeeName"
```
```
Employee  EmployeeName
--------  ---------------
1         Ada Lovelace
2         Alan Turing
...
```

That is a **path**: it starts at a type, walks a fact type, and ends at another type. The
result is the pairs the path reaches — its *head* and its *tail*.

Paths keep going. Each step is read as English, and the verb alone is enough once the type is
established:

```sh
cq "Employee has Department has DepartmentName"
```

## Naming what you want back

`LIST … FROM …` picks which parts of the path come back, by binding names to positions:

```sh
cq "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s > 100000"
```
```
n              s
-------------  ------
Ada Lovelace   185000
Alan Turing    172000
Grace Hopper   164000
Kay Antonelli  101500
```

`n` and `s` are **variables**, bound where they appear in the path. A comparison can sit
directly on a step (`s > 100000`) or in a `WHERE` clause at the end — the two are the same
thing, and `--normalise` will show you:

```sh
cq --normalise "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s > 100000"
```
```
LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > 100000
```

## Branching: `AND ALSO`, `OR OTHERWISE`, `BUT NOT`

A path is a line. To say more than one thing about the same instance, branch:

```sh
cq "LIST n FROM Employee has EmployeeName n AND ALSO has manager Employee has EmployeeName: 'Ada Lovelace'"
cq "LIST n FROM Employee has EmployeeName n BUT NOT has Assignment"
```

`Type: value` is a **denotation** — `Employee: 3`, `Department: 'ENG'` — naming one instance by
its identifier rather than walking to it.

The three connectives come from the report's §7.3: `AND ALSO` keeps instances satisfying both
branches, `OR OTHERWISE` either, `BUT NOT` the first without the second.

## Brackets: the difference between filtering and joining

This is the distinction that matters most, and the one with no clean equivalent in SQL syntax.

```
Employee has Project                    a join: one row per (employee, project)
Employee [has Project] has EmployeeName a filter: employees that have some project,
                                        one row each
```

```sh
cq "LIST n, p FROM Employee has EmployeeName n AND ALSO has Project has ProjectName p"   # 7 rows
cq "Employee [has Project] has EmployeeName"                                             # 5 rows
```

A bracketed sub-expression tests that the path exists — it becomes an `EXISTS` — and cannot
multiply rows. An unbracketed one joins, and multiplies. Choosing wrongly is the most common
way to get a plausible wrong answer out of any query language; here it is one character.

## Aggregates

`THE COUNT OF`, `THE SUM OF`, `THE AVERAGE`, `THE MINIMUM`, `THE MAXIMUM`, each with a
`DISTINCT` variant, and `THE MEDIAN`, `THE STANDARD DEVIATION` and `THE VARIANCE` (sample, not
population; on SQLite the median is spelled over the bag, so it takes `GROUPED BY` or the `IN`
form but not `WITHIN`):

```sh
cq "THE COUNT OF Employee"
cq "THE DISTINCT SUM OF Employee has EmployeeSalary"
```

An aggregate applies to the **value the path ends at**. When a branch makes the head the
subject again, the aggregate applies to the head — which is rarely what you meant, and
`--explain` says so:

```sh
cq --explain "THE SUM OF Employee has Project AND ALSO has EmployeeSalary"
```
```
?  This takes the sum of Employee -- an entity type -- which means the sum of its
   identifier. If you meant a value the Employee has, name it: `... has EmployeeSomething v`
   and take the sum of v.
```

**Grouped aggregates** use `GROUPED BY`, and `AS` names the result so it can be listed beside
its group key:

```sh
cq "LIST d, c FROM Employee e has Department has DepartmentName d AND ALSO THE COUNT OF e GROUPED BY d AS c"
cq "LIST d, t FROM Employee [has EmployeeSalary s] has Department has DepartmentName d AND ALSO THE SUM OF s GROUPED BY d AS t"
```

`GROUPED BY` **collapses**: one row per group. When you want the group's figure *beside* each
row rather than instead of them — to compare a row with its own group — say `WITHIN`:

```sh
cq "LIST n, d, c FROM Employee e has EmployeeName n AND ALSO has Department has DepartmentCode d AND ALSO THE COUNT OF e WITHIN d AS c"
cq "LIST n FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d AND ALSO has EmployeeSalary s AND ALSO THE AVERAGE s WITHIN d AS a WHERE s > a"
```

The second reads "everyone paid above their own department's average", and it is the same
question the correlated `!d` form in example 14 asks — `WITHIN` is the one that scales, because
it computes every group's figure once instead of once per row. In SQL this is
`OVER (PARTITION BY …)`; the compiler wraps the query itself when you filter on the result,
since SQL evaluates windows after `WHERE`.

**Row-relative functions** live in the same partition: `THE RANK OF s WITHIN d` (1 for the
largest; add `ASCENDING` after the value to turn it round), `THE PERCENT RANK OF s WITHIN d`
(the rank as a fraction of the partition, 0 for the largest), and `THE PREVIOUS s BY t WITHIN
d` (the value on the row before, in `t`'s order). `WITHIN 1` is one partition — the whole
query — which is what a global rank is within. A window beside a `GROUPED BY` aggregate in
the same query is refused unless it reads a grouped value: SQL would compute it over one
arbitrary row per group and say nothing.
```
d            t
-----------  ------
Engineering  521000
People       88000
Sales        199500
```

### The fan trap, and the one refusal you may meet

Add a branch that fans out — each employee has several assignments — and a SQL join would add
each salary once per assignment. The compiler knows from the model's uniqueness constraints
which steps multiply, and sums each salary once per employee:

```sh
cq "LIST d, t FROM Department has DepartmentName d AND ALSO is of Employee has EmployeeSalary s
    AND ALSO is of Employee has Assignment has AssignmentHours h AND ALSO THE SUM OF s GROUPED BY d AS t"
```
```
d            t
-----------  ------
Engineering  521000
Sales        199500
```

The same figures as above, less People, which has no assignments for the branch to reach.
`AVERAGE` is handled the same way, and `MINIMUM` and `MAXIMUM` need nothing: repetition cannot
change them.

`COUNT` is different, because counting over a fan-out has two honest readings — the rows, or
the things — and the compiler will not pick one for you. The same query with `THE COUNT OF s`
stops:

```
THE COUNT OF here is computed over rows this query multiplies: one Department has many
Employee, and nothing in the model says otherwise, so the value is counted once per Employee
rather than once per Department. Put the multiplying path in brackets and bind nothing inside
them -- `[Department has Employee]` matches without joining, so it cannot multiply, but
`[Department has Employee x]` binds a name and joins, which multiplies again -- or aggregate
over Employee itself.
```

Bracket the branch, binding nothing inside it, and it counts each salary once:

```sh
cq "LIST d, t FROM Department has DepartmentName d AND ALSO is of Employee has EmployeeSalary s
    AND ALSO [is of Employee has Assignment has AssignmentHours] AND ALSO THE COUNT OF s GROUPED BY d AS t"
```

How often writers produce these shapes at all is a measured question, and the answer is
sobering: [7 — What we measured](07-what-we-measured.md).

## Ordering and limits

```sh
cq "LIST n, h FROM Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h
    ORDERED WITH h DESCENDING THE FIRST 3"
```

`THE FIRST n PER x` cuts within each group — "the top 3 in each department" — and compiles to
`ROW_NUMBER() OVER (PARTITION BY …)`. Ordering is the report's §6.13; the limit is not in the
report at all, and is one of the additions recorded in
[`conquer/conquer-2026.md`](../conquer/conquer-2026.md).

## Set comparison and division

Whole result sets can be compared. `WHICH ARE ALL IN` is relational division, emitted directly
rather than as a double-negation:

```sh
cq "LIST n FROM Employee has EmployeeName n AND ALSO has Project
    WHICH ARE ALL IN (Employee: 3 has Project)"
```
```
n
---------------
Alan Turing
Grace Hopper
Betty Holberton
```

Betty Holberton has no projects at all, and so is vacuously included — which is what "all of
hers are among his" means, and worth knowing before you ship the query.

The family also has `IS A SUBSET OF`, `IS A SUPERSET OF`, `EQUALS`, `IS DISJOINT FROM`,
`EXCLUDES`, and `UNITED WITH` / `INTERSECTED WITH` / `MINUS` over whole queries.

## Gathering side values: `EACH`

A path is one line through the model; `EACH` gathers extra values onto it without turning them
into more rows:

```sh
cq "LIST n, s FROM has EmployeeSalary AS s EACH Employee has EmployeeName n"
```

When the model says the gathered value is **at most one** per instance, it is flattened onto
the row — an outer join. When the model says it can be **many**, it comes back *nested*:

```sh
cq "LIST n, h FROM has Assignment has AssignmentHours AS h EACH Employee has EmployeeName n"
```
```
n                h
---------------  --------
Ada Lovelace     [120,40]
Alan Turing      [80]
Grace Hopper     [60,100]
Betty Holberton  []
```

Six employees, six rows, however many assignments each has — and the employee with none
gathers the empty bag rather than a null. The report flattened this case to an outer join
"because SQL-92 is not able to deal with nested relations"; SQLite can, so this restores what
LISA-D's confluence originally meant.

## Gathering into strings and documents

`THE LIST OF x GROUPED BY g` gathers a JSON array per group. Two more shapes gather
differently — a string, and an object keyed by a value:

```sh
cq "LIST d, s FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n
    AND ALSO THE LIST OF n SEPARATED BY ', ' GROUPED BY d AS s"
cq "LIST d, o FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n
    AND ALSO has EmployeeSalary s AND ALSO THE OBJECT OF s BY n GROUPED BY d AS o"
```
```
d      s                                       o
-----  --------------------------------------  ------------------------------------------------------------
ENG    Ada Lovelace, Alan Turing, Grace Hopper  {"Ada Lovelace":185000,"Alan Turing":172000,"Grace Hopper":164000}
```

A document is built with `jsonObject('k1', v1, 'k2', v2, …)`, nesting as a value, and a list
of those gathers objects, not strings. Text that already is a document is re-read as one with
`json(t)`. The `IN` form takes an expression as the value: `THE LIST OF (s * 2) IN Employee has
EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 2`.

## Documents inside columns

A JSON column the reverse engineer has opened (`--infer-json`) is several fact types, typed as
the data is: `has SocialcommunityNetworkFollcount fc` reads a field the way `has EmployeeSalary
s` reads a column, and `--schema` lists the fields' value domains beside everything else. The
column itself stays reachable — the listing marks it *"A JSON document"* and names its fact
types — for a path they do not cover: `jsonPath(doc, '$.a.b')`.

## `DEFINE`: naming an intermediate result

ConQuer-92 can name a derived concept in the *model* (§6.11) but has no way to name one inside
a query. That gap shows up the moment two grouped results have to sit on one row:

```sh
cq "DEFINE TopEarner ::= LIST d, e FROM Employee e [has EmployeeSalary s] has Department d
        ORDERED WITH s DESCENDING THE FIRST 1 PER d
    DEFINE FirstHired ::= LIST d, e FROM Employee e [has EmployeeHired h] has Department d
        ORDERED WITH h ASCENDING THE FIRST 1 PER d
    LIST c, a, b FROM Department has DepartmentName c
        AND ALSO has TopEarner has EmployeeName a
        AND ALSO has FirstHired has EmployeeName b"
```
```
c            a                b
-----------  ---------------  ---------------
Engineering  Ada Lovelace     Grace Hopper
People       Betty Holberton  Betty Holberton
Sales        Kay Antonelli    Jean Bartik
```

One thing listed defines a **subtype** you can walk from; two or more define a **fact type**
read `has <Name>`. Each becomes a common table expression. A definition may build on an
earlier one. A listed column that is *computed* rather than reached gets a value type named
`<Name><Variable>` — the variable you listed, capitalised, not the concept: `DEFINE Headcount
::= LIST d, c …` gives you `has Headcount HeadcountC x`. A definition that lists several values
is walked by each variable's own name as the verb: `DEFINE Stat ::= LIST d, c, t …` is
reached by `d has c StatC c AND ALSO d has t StatT t`.

## Read it back before you run it

```sh
cq --explain "THE AVERAGE Employee has EmployeeSalary"
```
```
  the average each Employee has EmployeeSalary

  Resolved
    Employee has            -> the fact type EmployeeHasSalary, reaching EmployeeSalary

  This query requires
    !  Employee must actually have an EmployeeSalary -- rows where it is absent are dropped.
```

`--explain` says which fact type each verb resolved to, what the query assumes, and what is
worth checking (an unordered limit, a possibly-tied ordering, an aggregate over an identifier).
`--normalise` prints the query in the report's §8 normal form, which is also how you find out
what the compiler thinks you wrote. `--sql-only` prints the SQL without running it.

And before writing anything, `--schema`: its *Identification* section says what value names
an instance of each type and which columns hold it. Asked for "the customer's ID", list that
value — a type often has several id-shaped values, and only one is what every other table
calls the instance. This was the single largest lever measured on real schemas
([7](07-what-we-measured.md#on-livesqlbenchs-sqlite-tier-where-the-schemas-are-worse)).

## What is not there

No update sublanguage (the report has none). No `NTILE`, no `LEAD`, no window offset
(`THE PREVIOUS` reaches one row back; a `DEFINE` reaches two). The full list of what was added beyond the 1994 report — real division, a scalar
conditional, date functions, `THE FIRST n`, `DEFINE` — is in
[`conquer/conquer-2026.md`](../conquer/conquer-2026.md), and the full supported-syntax table is in
[`conquer/README.md`](../conquer/README.md).

---

Next: [4 — Reverse engineering](04-reverse-engineering.md).
