# ConQuer-92 in one page

A **conceptual query language**. You never name a table, a column or a join. You name the
*types* in the model and walk the *fact types* between them by their reading. The compiler
works out the joins from the model.

Every example here runs against the model built from `reverse/tests/company.sql`, and the
counts under them are what it actually returns. `conquer/tests/test_primer.py` checks them, so
an example that stops being true is a failing test rather than a misleading prompt.

## The shape of a query

    LIST <names> FROM <path>  [ORDERED WITH <name> ASCENDING|DESCENDING]  [THE FIRST n [AFTER m]]
                                                                          (THE TOP n is the same thing)

A **path** starts at a type and steps along verb readings. `Employee has EmployeeName n`
starts at Employee, steps through the fact type read "Employee has EmployeeName", and calls
what it reaches `n`. A lower-case word after a type is a variable name you may then LIST,
compare or sort by.

The `--schema` listing gives you every type and every reading. Use it literally: if the
listing says `EmployeeHasSalary   Employee has EmployeeSalary`, then `Employee has
EmployeeSalary s` is the step. If a reading is `Atom is connected to Atom`, the step is
`is connected to`.

## The twenty things you need

**1 — project one value.**
```conquer
LIST n FROM Employee has EmployeeName n
-- 6 rows
```

**2 — `AND ALSO` branches from the SAME head.** Both branches are about one Employee; the
second omits the head, so `has ...` continues from Employee, not from `n`.
```conquer
LIST n, d FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d
-- 6 rows
```

**3 — `[ ... ]` filters the head so far and does not move the path.** `Type: value` is a
denotation: the thing whose identifier is that value.
```conquer
LIST n FROM Employee [has EmployeeGender: 'F'] has EmployeeName n
-- 4 rows
```

**4 — `WHERE` compares named values.** `= <> < <= > >=`, and `AND` / `OR` / `NOT`.
```conquer
LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > 100000
-- 4 rows
```

**5 — `BUT NOT` excludes heads for which the branch holds**; `OR OTHERWISE` is the union.
`BUT NOT has X` is also how you say "has no X at all": there is no NULL and no IS NULL.
```conquer
LIST n FROM Employee has EmployeeName n BUT NOT has Department: 'ENG'
-- 3 rows
```

**6 — a whole-query aggregate.** Also `THE SUM OF`, `THE AVERAGE`, `THE MINIMUM`,
`THE MAXIMUM`, `THE DISTINCT COUNT OF`, `THE DISTINCT SUM OF`. Counting a type counts its
instances. `THE MEDIAN` may also be written `THE MEDIAN OF`.
```conquer
THE COUNT OF Employee [has EmployeeGender: 'F']
-- 1 row: 4
```

**7 — `x IN <path>` says WHICH value is aggregated** when the path does not end on it.
```conquer
THE AVERAGE h IN Assignment has AssignmentHours h
-- 1 row
```
To aggregate something computed, bind it with `AS` inside a parenthesised path:
```conquer
THE AVERAGE v IN (Department has DepartmentBudget b AND ALSO (b / 2) AS v)
-- 1 row
```

**8 — a grouped aggregate.** Name the thing counted (`e`), `GROUPED BY` a projected name, and
name the result with `AS` so you can LIST it, sort by it, or compare it.
```conquer
LIST d, c FROM Employee e has Department has DepartmentCode d AND ALSO THE COUNT OF e GROUPED BY d AS c
-- 3 rows
```

**9 — ordering and a row limit.** The sort key must be a name the query binds.
```conquer
LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 3
-- 3 rows
```

**9a — several sort keys.** `ORDERED WITH` takes a list, applied left to right.
```conquer
LIST n, d, s FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d
   AND ALSO has EmployeeSalary s ORDERED WITH d ASCENDING, s DESCENDING
-- 6 rows
```

**9b — `WITH TIES`** returns everything that ranks within n, where `THE FIRST n` returns n
rows and leaves the choice among equals to the database. Ask for it when the question wants
*which* rather than *one*: "the race where he was fastest" is one question whether he was
fastest once or thirty times.
```conquer
LIST g, c FROM Employee e has EmployeeGender g AND ALSO THE COUNT OF e GROUPED BY g AS c
   ORDERED WITH c DESCENDING THE FIRST 2 WITH TIES
-- 3 rows
```
Two genders have one employee each, so `THE FIRST 2` returns two rows and `WITH TIES`
returns three. It needs a sort key, and will not combine with `AFTER`. Note that a second
sort key *breaks* a tie rather than keeping it — order by exactly what the question ranks on.

**9b2 — an operator after a `WHERE` binds to the comparison, not to the aggregate.**
`THE COUNT OF X [...] WHERE year(d) = 2019 / 12` reads as `year(d) = (2019 / 12)`, which
matches nothing, because `/` binds tighter than `=` exactly as it does in SQL. To divide the
*count*, parenthesise it: `(THE COUNT OF X [...] WHERE year(d) = 2019) / 12`. It compiles and
runs either way, so nothing will tell you which one you wrote.

**9b3 — dispersion**: `THE STANDARD DEVIATION` and `THE VARIANCE`, sample not population,
on the same terms as `THE MEDIAN` below — present only where the target dialect has them.

**9c — `THE MEDIAN`** is the middle value, not the mean: of an even count, the mean of the
two middle values. On SQLite it is spelled over the bag, so it takes `GROUPED BY` or the
`IN` form but not `WITHIN`.
```conquer
LIST d, m FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s
   AND ALSO THE MEDIAN s GROUPED BY d AS m
-- 3 rows
```

**9d — row-relative**: `THE RANK OF x WITHIN g` is x's rank in its partition, 1 for the
largest; `THE PERCENT RANK OF x WITHIN g` is the same rank as a fraction of the partition,
0 for the largest and 1 for the smallest; `THE PREVIOUS x BY t WITHIN g` is x from the row
before, in t's order. All need `WITHIN`, never `GROUPED BY` — a group returns one row and
leaves nothing to be relative to. `WITHIN 1` is one partition: the whole query. Add
`ASCENDING` after the value to rank the other way up (`THE RANK OF x ASCENDING WITHIN 1`).
```conquer
LIST n, r FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d
   AND ALSO has EmployeeSalary s AND ALSO THE RANK OF s WITHIN d AS r
-- 6 rows
```
```conquer
LIST n, p FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s
   AND ALSO THE PERCENT RANK OF s ASCENDING WITHIN 1 AS p
-- 6 rows
```

**9e — `THE LIST OF x GROUPED BY g`** gathers rather than reduces: the values come back as
one JSON array per group instead of multiplying the rows. The `IN` form takes an expression
too: `THE LIST OF (s * 2) IN Employee has EmployeeSalary s ORDERED WITH s DESCENDING`. `THE DISTINCT LIST OF` drops
repeats. `THE LIST OF x SEPARATED BY ', '` joins them as one string instead of an array;
`THE OBJECT OF v BY k` gathers `{k: v, ...}`, one JSON object keyed by k.
```conquer
LIST d, s, o FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n
   AND ALSO has EmployeeSalary sal AND ALSO THE LIST OF n SEPARATED BY ', ' GROUPED BY d AS s
   AND ALSO THE OBJECT OF sal BY n GROUPED BY d AS o
-- 3 rows
```
```conquer
LIST d, l FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeGender g
   AND ALSO THE DISTINCT LIST OF g GROUPED BY d AS l
-- 3 rows
```
An *ungrouped* gather carries its own `ORDERED WITH ... THE FIRST n` and returns the top n
over the whole query, as one array:
```conquer
LIST l FROM THE LIST OF s IN Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 2 AS l
-- 1 row
```
Top-n *within each group* is not this. A group collapses to one row, so there is nothing
left inside it to order or cut, and the combination is refused. Ask for the rows instead,
with `THE FIRST n PER g`:
```conquer
LIST d, s FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s
   ORDERED WITH s DESCENDING THE FIRST 1 PER d
-- 3 rows
```

**9f — two levels of aggregation** are a `DEFINE`: name the first level, then aggregate
over it. The listed thing must be an entity so the definition can be walked from it.
```conquer
DEFINE DeptTotal ::= LIST dept, t FROM Employee has Department dept AND ALSO has EmployeeSalary s
   AND ALSO THE SUM OF s GROUPED BY dept AS t
THE AVERAGE t IN Department has DeptTotal DeptTotalT t
-- 1 rows
```

**9g — `AND ALSO` starts again from the head.** `Employee has Assignment AND ALSO has Project`
is two paths from Employee, not one through Assignment, and reads a second independent range.
To continue from where a path got to, bind it and start the next operand there:
```conquer
LIST n, p FROM Employee has EmployeeName n AND ALSO has Assignment a AND ALSO a has Project has ProjectName p
-- 7 rows
```

**10 — arithmetic over aggregates.** `/` is REAL division; `div(a,b)` is integer division.
```conquer
THE COUNT OF Employee [has EmployeeGender: 'F'] * 100 / THE COUNT OF Employee
-- 1 row
```

**11 — `OPTIONALLY` is an outer join.** It goes before the verb or before a bound head --
`e OPTIONALLY has X` and `OPTIONALLY e has X` mean the same thing. Reading a role normally REQUIRES it, so a row whose
salary is NULL is dropped. Use `OPTIONALLY` whenever you project something that may be absent.
```conquer
LIST n, s FROM Employee has EmployeeName n AND ALSO OPTIONALLY has EmployeeSalary s
-- 6 rows
```

**12 — functions**: starts_with, ends_with, contains, like, instr, substr, length, upper,
lower, concat, replace, abs, round, sqrt, power, ln, exp, year, month, day, today,
days_between, if(c,a,b), div. A boolean
function stands alone as a condition. Call them by name: `concat(a, b)` joins two strings,
and there is no infix `||`. `a ^ b` is `power(a, b)`; a number may be written `1.5e6`; the
date functions read ISO text and also `2023/12/21`, `21/12/2023`, `1/12/2023` (day first).
```conquer
LIST n FROM Employee has EmployeeName n WHERE starts_with(n, 'A')
-- 2 rows
```

**13 — an aggregate inside a condition**: an uncorrelated subquery.
```conquer
LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > THE AVERAGE Employee has EmployeeSalary
-- 3 rows
```

**14 — `!d` correlates the subquery to the outer instance `d`.** This is the per-group
comparison: "earns more than the average for THEIR OWN department".
```conquer
LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s AND ALSO has Department d
   WHERE s > THE AVERAGE Employee [has Department: !d] has EmployeeSalary
-- 2 rows
```

**15 — a multi-hop path.** Assignment is an objectified fact type (a table with its own
columns); you step into it and out the other side. No join is written.
```conquer
LIST n, p FROM Employee has EmployeeName n AND ALSO has Assignment has Project has ProjectName p
-- 7 rows
```

**16 — `DISTINCT` goes before the head.**
```conquer
LIST n FROM DISTINCT Employee has EmployeeName n
-- 6 rows
```

**17 — a scalar conditional.** Also `if(s > 100000, 'high', 'low')`. There is no boolean
value: a yes/no column asked for "as a boolean" is `if(c, 1, 0)`, which is what SQL's `TRUE`
and `FALSE` are on SQLite -- not the words `'True'` and `'False'`.
```conquer
LIST IF s > 100000 THEN 'high' ELSE 'low' FROM Employee has EmployeeSalary s
-- 6 rows
```

**18 — a filter binding a variable, then a condition on it, inside an aggregate.**
```conquer
THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 100000
-- 1 row: 4
```

**19 — "the department with the highest payroll"**: group, order by the group value, take one.
```conquer
LIST d, t FROM Employee has Department has DepartmentCode d
   AND ALSO THE SUM OF s IN Employee has EmployeeSalary s GROUPED BY d AS t
   ORDERED WITH t DESCENDING THE FIRST 1
-- 1 row
```

**19a2 — dispersion.** `THE STANDARD DEVIATION OF x` and `THE VARIANCE OF x` are the
*sample* forms, and work on every dialect: where the engine has no aggregate for them (SQLite
has neither) the model spells them from `SUM` and `COUNT`. `THE MEDIAN OF x` is not always
available -- it is an ordered-set aggregate with no closed form, so a SQLite model refuses it
rather than emit SQL that does not run.

**19b — the scalar library.** `abs round floor ceil sqrt power ln exp log10` · `length lower upper
substr instr replace trim ltrim rtrim concat` · `coalesce nullif greatest least` ·
`year month day today days_between` · `castNumber castInteger` · `like starts_with
contains ends_with` (all four ignore case; `=` is the exact test) · `if(cond, a, b)` ·
`jsonPath(doc, '$.field')` reads one field out of a document-valued type, and nests
(`'$.a.b'`, `'$.items[0]'`). Reach for it before picking a document apart with `substr`
and `instr`: a writer who did not know it existed spelled one field as
`substr(p, instr(p, '"propvalue": ') + 13, 20)`. Better still, look first: where the
listing's *Defined terms* say a value type is "a JSON document", its values are already
fact types of their own (`has SocialcommunityNetworkFollcount fc`), typed as the data is,
and a query reads those -- the document is there only for a path they do not cover.

**19c — building a document.** `jsonObject('k1', v1, 'k2', v2, ...)` makes an object, any
even number of arguments, nesting as a value (`jsonObject('a', 1, 'b', jsonObject(...))`);
`THE LIST OF obj GROUPED BY g` gathers objects into an array. Do not spell an object with
`concat` and quote marks: it gathers as a *string* that looks like an object. Text that
already is a document is re-read as one with `json(t)`.
```conquer
LIST d, l FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n
   AND ALSO has EmployeeSalary s AND ALSO jsonObject('name', n, 'salary', s) AS o
   AND ALSO THE LIST OF o GROUPED BY d AS l
-- 3 rows
```
```conquer
LIST n, y FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s
   AND ALSO round(log10(coalesce(s, 1)), 2) AS y
-- 6 rows
```

**20 — name the verb phrase, not bare `has`,** when two types have several fact types between
them or one type plays two roles in one. `is of` walks a reading backwards
(`Department is of Employee`). If `has` is ambiguous the compiler says so and names every
candidate.
```conquer
LIST n FROM Employee has manager Employee has EmployeeName n
-- 3 rows
```

## Traps that produce silently wrong answers

- **Two branches that each reach many.** `Employee has Assignment has AssignmentHours h AND ALSO
  has Assignment has Project has ProjectName p` is two independent ranges from each Employee, and
  the rows are every hours value paired with every project: a cross product per employee, not one
  row per assignment. `--explain` cautions. Continue the second branch from the first --
  `has Assignment a AND ALSO a has AssignmentHours h AND ALSO a has Project ...` -- or gather one
  side with `THE LIST OF`.

These cost real answers. They compile, they run, and the number is wrong.

**Counting counts the END of the path.** The bracket form counts the head:
```conquer
THE COUNT OF Employee has Assignment
-- 1 row: 7
```
```conquer
THE COUNT OF Employee [has Assignment]
-- 1 row: 5
```

**`OPTIONALLY` covers one step, not the rest of the path.** Every later step needs its own, or
the rows you were protecting are dropped one step later:
```conquer
LIST n, m FROM Employee has EmployeeName n AND ALSO OPTIONALLY has manager Employee has EmployeeName m
-- 3 rows
```
```conquer
LIST n, m FROM Employee has EmployeeName n AND ALSO OPTIONALLY has manager Employee OPTIONALLY has EmployeeName m
-- 6 rows
```

**"Absent, or equal to this" is `BUT NOT` beside `OR OTHERWISE`.** SQL writes `power IS NULL OR
power = '*'`; here absence is the missing fact and the two alternatives sit side by side:
```conquer
THE COUNT OF Employee BUT NOT [has EmployeeSalary] OR OTHERWISE [has EmployeeSalary > 150000]
-- 1 row: 3
```
That is the employees with no salary recorded plus those over 150000.
The same thing reads as one filter if you prefer -- `BUT NOT [has EmployeeSalary s WHERE NOT
s > 150000]` -- which is worth knowing because the alternatives cannot be bracketed together:
`[BUT NOT ... OR OTHERWISE ...]` does not parse. Two writers concluded this shape was
inexpressible; it is not.

**The top group, and its members, is a `DEFINE` plus a comparison against the maximum.** One
query cannot both group and list what is in each group, so name the grouped result and ask
the question against it:
```conquer
DEFINE Busy ::= LIST d, n FROM Employee has Department has DepartmentCode d
                AND ALSO THE COUNT OF d GROUPED BY d AS n
LIST c, nm FROM Employee has Department has DepartmentCode c AND ALSO has EmployeeName nm
     AND ALSO c has Busy BusyN n WHERE n = THE MAXIMUM DepartmentCode has Busy BusyN
-- 3 rows
```
Each row is the busiest department's code beside one of its employees.
A definition's reading is its name (`has Busy`) and its value type is the definition's name
followed by the **variable** you listed, capitalised -- `n` gives `BusyN`; it is the
variable's name, not the concept's. A definition that lists several values is walked by
each variable's own name as the verb: `DEFINE Stat ::= LIST d, c, t FROM ...` is reached by
`d has c StatC c AND ALSO d has t StatT t` (`has Stat StatC c` also reaches the first). Key
it on whatever the answer lists -- an entity or a value type will both do.

**A denotation on an entity compares against its identifier**, which is often a surrogate id.
`has Superpower: 'Death Touch'` matches nothing if Superpower is identified by a number. Check
the listing: denote by the identifier it shows, otherwise step to the named value —
`has Superpower has SuperpowerPowerName: 'Death Touch'`.

**Asked for a thing's id, list its identifier — not the value whose name sounds most like the
question.** The listing's *Identification* section says which value that is. A type often has
several id-shaped values (a registry code, a client reference, a tag); only one of them is what
every other table calls the instance, and that is the one "its ID" means unless the question
names another. The rows come back the same either way and the answer is wrong in every row.

**Every branch after `AND ALSO` continues from the head**, not from the last thing named. To
continue from the last thing, keep stepping: `has Department has DepartmentCode d`.

**A grouped aggregate that restates the whole path instead of reusing a bound name** is a
second, uncorrelated range, so every group gets the same total. Bind the head (`Employee e`)
and aggregate over `e`.

**21 — `WITHIN` is `GROUPED BY` without the collapse**: the same partition, reported beside
every row instead of instead of them. This is how you compare a row with its own group.
```conquer
LIST n, d, c FROM Employee e has EmployeeName n AND ALSO has Department has DepartmentCode d
   AND ALSO THE COUNT OF e WITHIN d AS c
-- 6 rows
```
```conquer
LIST n FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d
   AND ALSO has EmployeeSalary s AND ALSO THE AVERAGE s WITHIN d AS a WHERE s > a
-- 2 rows
```

**22 — whole-query scalars sit side by side with no FROM at all**, and each may be an
expression. This is how "the difference between A and B, and between B and C" fits in one row.
```conquer
LIST THE COUNT OF Employee, THE AVERAGE EmployeeSalary
-- 1 row
```
Naming a value type on its own aggregates every value it has: `THE AVERAGE EmployeeSalary` is
the average over the fact type that carries it. Where two fact types carry the same value type,
say which by walking a path — `THE AVERAGE v IN Employee has EmployeeSalary v`.

## What you cannot write

- **A projection out of one alternative.** `LIST n, g FROM ... AND ALSO has X g OR OTHERWISE
  has Y: 1` asks for a `g` on rows that came in by the other branch. Ask the alternatives as
  separate queries.
- **A table or a column.** If the type is not in the schema listing, the model does not have
  it, and the question may be unanswerable — say so rather than inventing a name.
- **`IS NULL`, `IN (subquery)`, `EXISTS`.** Absence is `BUT NOT`, membership is just a step,
  existence is a `[...]` filter. "Absent **or** equal to this" is the two side by side:
  `BUT NOT [has X] OR OTHERWISE [has X: 'v']`.
