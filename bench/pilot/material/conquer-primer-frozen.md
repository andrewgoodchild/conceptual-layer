# ConQuer-92 in one page

A **conceptual query language**. You never name a table, a column or a join. You name the
*types* in the model and walk the *fact types* between them by their reading. The compiler
works out the joins from the model.

## The shape of a query

    LIST <names> FROM <path>  [ORDERED WITH <name> ASCENDING|DESCENDING]  [THE FIRST n [AFTER m]]

A **path** starts at a type and steps along verb readings. `Employee has EmployeeName n`
starts at Employee, steps through the fact type read "Employee has EmployeeName", and calls
what it reaches `n`. A lower-case word after a type is a variable name you may then LIST,
compare or sort by.

The `--schema` listing gives you every type and every reading. Use it literally: if the
listing says `EmployeeHasSalary   Employee has EmployeeSalary`, then `Employee has
EmployeeSalary s` is the step. If a reading is `Atom is connected to Atom`, the step is
`is connected to`.

## The twenty things you need

    1  LIST n FROM Employee has EmployeeName n
       project one value

    2  LIST n, d FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d
       AND ALSO branches from the SAME head. Both branches are about one Employee.
       The second branch omits the head: `has ...` continues from Employee, not from n.

    3  LIST n FROM Employee [has EmployeeGender: 'F'] has EmployeeName n
       [ ... ] is a filter on the head so far, and does not move the path.
       `Type: value` is a denotation: the thing whose identifier is that value.

    4  LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > 100000
       WHERE compares named values.  = <> < <= > >=  and AND / OR / NOT

    5  LIST n FROM Employee has EmployeeName n BUT NOT has Department: 'ENG'
       BUT NOT excludes heads for which the branch holds.  OR OTHERWISE is the union.

    6  THE COUNT OF Employee [has EmployeeGender: 'F']
       a whole-query aggregate. Also THE SUM OF, THE AVERAGE, THE MINIMUM, THE MAXIMUM,
       THE DISTINCT COUNT OF.  Counting a type counts its instances.

    7  THE AVERAGE h IN Assignment has AssignmentHours h
       `x IN <path>` says WHICH value is aggregated when the path does not end on it.
       To aggregate a computed value, bind it inside a parenthesised path:
       THE AVERAGE d IN (Frpm has FrpmEnrollmentK12 k AND ALSO has FrpmEnrollmentAges517 a AND ALSO (k - a) AS d)

    8  LIST d, c FROM Employee e has Department has DepartmentCode d
          AND ALSO THE COUNT OF e GROUPED BY d AS c
       a grouped aggregate. Name the thing counted (`e`), GROUP BY a projected name,
       and name the result with AS so you can LIST it, sort by it, or compare it.

    9  LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s
          ORDERED WITH s DESCENDING THE FIRST 3
       ordering and a row limit. The sort key must be a name the query binds.

   10  THE COUNT OF Employee [has EmployeeGender: 'F'] * 100 / THE COUNT OF Employee
       arithmetic over aggregates. `/` is REAL division; `div(a,b)` is integer division.

   11  LIST n, s FROM Employee has EmployeeName n AND ALSO OPTIONALLY has EmployeeSalary s
       IMPORTANT: reading a role normally REQUIRES it. A row whose salary is NULL is
       dropped. `OPTIONALLY` makes that step an outer join, so the value may come back
       empty. Use it whenever you project something that may be absent.

   12  LIST n FROM Employee has EmployeeName n WHERE starts_with(n, 'A')
       functions: starts_with, ends_with, contains, like, instr, substr, length, upper,
       lower, abs, round, year, month, day, today, days_between, if(c,a,b), div.
       A boolean function stands alone as a condition.

   13  LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s
          WHERE s > THE AVERAGE Employee has EmployeeSalary
       an aggregate inside a condition: an uncorrelated subquery.

   14  LIST n FROM ... AND ALSO has Department d
          WHERE s > THE AVERAGE Employee [has Department: !d] has EmployeeSalary
       `!d` correlates the subquery to the outer instance `d`. This is the per-group
       comparison: "earns more than the average for THEIR OWN department".

   15  LIST n, p FROM Employee has EmployeeName n AND ALSO has Assignment has Project
          has ProjectName p
       a multi-hop path. Assignment is an objectified fact type (a table with its own
       columns); you step into it and out the other side. No join is written.

   16  LIST n FROM DISTINCT Employee has EmployeeName n
       DISTINCT goes before the head.

   17  LIST IF s > 100000 THEN 'high' ELSE 'low' FROM Employee has EmployeeSalary s
       a scalar conditional. Also `if(s > 100000, 'high', 'low')`.

   18  THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 100000
       a filter binding a variable, then a condition on it, inside an aggregate.

   19  LIST d, t FROM Employee has Department has DepartmentCode d
          AND ALSO THE SUM OF s IN Employee has EmployeeSalary s GROUPED BY d AS t
          ORDERED WITH t DESCENDING THE FIRST 1
       "the department with the highest payroll": group, order by the group value, take one.

   20  LIST n FROM Employee has EmployeeName n AND ALSO has Employee2 ...
       when two types have several fact types between them, or one type plays two roles
       in one fact type, name the ROLE instead of the type. The schema listing shows role
       names. `is of` walks a reading backwards: `Department is of Employee` from Department.

## Rules that catch people out

- **Every branch after `AND ALSO` continues from the head**, not from the last thing named.
  To continue from the last thing, just keep stepping: `has Department has DepartmentCode d`.
- **Reading a role asserts it exists.** Projecting a nullable value without `OPTIONALLY`
  silently drops rows. If a question says "list X and their Y" and Y may be missing, use
  `OPTIONALLY`.
- **You cannot name a table or a column.** If the type you want is not in the schema
  listing, the model does not have it and the question may be unanswerable.
- **A denotation `Type: v`** means "the instance identified by v". For a value type,
  `has EmployeeGender: 'F'` is just equality. For an entity type it walks the reference
  scheme, so `has Department: 'ENG'` finds the Department whose code is 'ENG'.
- **A grouped aggregate must be named with `AS`** before you can LIST or sort by it.
