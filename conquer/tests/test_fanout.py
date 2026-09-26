#!/usr/bin/env python3
"""The fan trap: every shape of it, and what the compiler does with each.

A block is one flat join, so a path that branches many-ways repeats everything on the other
branch. Aggregate over that and the number is wrong by a factor nobody can see — the query is
well formed, the SQL runs, and the answer is confidently false. It is the one error class a
conceptual model already holds the answer to, because uniqueness constraints say which steps
multiply.

The compiler does three different things, and the difference is not stylistic:

    SUM, AVERAGE, grouped or not          computed correctly, each value once per what
                                          determines it (findings 82, 117)
    MINIMUM, MAXIMUM                      nothing to do: repetition cannot change them
    COUNT                                 left as written ungrouped -- counting a fanned head
                                          is ambiguous, and a bracket or `DISTINCT` is how an
                                          author says which they mean; grouped, where the keys
                                          do not pin it, refused (test_errors.py)

Every case here states the truth as SQL and, where a trap exists, the wrong answer the naive
join gives. That second part is what makes these tests mean something: a case that only asserts
today's output would still pass if the deduplication were deleted and the data happened not to
fan out. A case that passes a `wrong=` fails if the fixture stops containing that trap at all.

    test_fanout.py [-v] [--only SUBSTRING]
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402


# -- expectations --------------------------------------------------------------------------

def rows_where(pred): return ("rows_where", pred, None)


def same_as(sql, wrong=None):
    """The query must return what this SQL returns. `wrong` is what the un-deduplicated join
    gives: asserted to differ, so the case proves the trap is present in the fixture."""
    return ("same_as", sql, wrong)


def refuses(fragment):
    return ("refuses", fragment, None)


CASES = [
    # -- an aggregate over a bound expression, which compiled to MIN --------------------
    # `constant_in_group` asks what determines the aggregated value and, if the group keys
    # pin all of it, emits MIN -- every row of the group carries the same value and MIN
    # returns it exactly. `_first_node` could not see through `(s * 2) AS x` to the node
    # underneath, so it answered "nothing determines this", and `all()` over an empty set is
    # true. Every AVERAGE and SUM over a bound expression became MIN: it compiled, it ran,
    # and it returned a plausible number per group. Found by a blind writer on LiveSQLBench
    # (finding 145), not by any test here -- which is why all four aggregates are pinned now.
    ("an average over a bound expression averages, and does not take the minimum",
     "LIST g, a FROM Employee has EmployeeGender g AND ALSO has EmployeeSalary s "
     "AND ALSO (s * 2) AS x AND ALSO THE AVERAGE x GROUPED BY g AS a",
     same_as("SELECT gender, AVG(salary * 2) FROM employee "
             "WHERE gender IS NOT NULL AND salary IS NOT NULL GROUP BY gender",
             wrong="SELECT gender, MIN(salary * 2) FROM employee "
                   "WHERE gender IS NOT NULL AND salary IS NOT NULL GROUP BY gender")),
    # The same shape one level further out. When the expression's columns are NOT all on the
    # head table, `regroup_grouped` re-lowers the aggregate over a bag of its own -- and
    # `mirror_block` copies nodes, steps and conditions but not calculations, while
    # `remap_nodes` rewrites node ids rather than following a reference. So an argument that
    # *names* a bound expression kept pointing at the enclosing block's copy, and the bag
    # aggregated the outer row: `MIN((SELECT AVG(outer_alias.x * ?) FROM inner_alias ...))`.
    # SQLite rejects that as a misuse of aggregate, so it failed loudly rather than quietly --
    # but it failed, on a question a blind writer had to work around with three DEFINEs.
    # The fourth defect of the shape findings 145, 146 and 149 found.
    ("a grouped average over a bound expression whose columns are not on the head table",
     "LIST d, a FROM Employee has EmployeeSalary s AND ALSO has Department "
     "has DepartmentCode d AND ALSO (s * 2) AS x AND ALSO THE AVERAGE x GROUPED BY d AS a",
     same_as("SELECT department.dept_code, AVG(salary * 2) FROM employee "
             "JOIN department ON department.dept_code = employee.dept_code "
             "WHERE salary IS NOT NULL GROUP BY department.dept_code")),

    # The bag's calculations are rendered in list order, and `_mirror_calculations` appended
    # a dependent before the dependency it had just copied -- so a *nested* expression met
    # "this query names a computed value that is not in scope". `(pr * ct)` grouped worked and
    # `(pr * (ct - 25))` grouped did not, which is why five writers on one benchmark run gave
    # five different accounts of the trigger. The enclosing block gets this right by
    # construction; only the mirrored bag did not.
    ("a grouped average over a nested expression, whose inner part is a calculation too",
     "LIST d, a FROM Employee has EmployeeSalary s AND ALSO has Department "
     "has DepartmentCode d AND ALSO (s * (s - 1000)) AS x "
     "AND ALSO THE AVERAGE x GROUPED BY d AS a",
     same_as("SELECT department.dept_code, AVG(salary * (salary - 1000)) FROM employee "
             "JOIN department ON department.dept_code = employee.dept_code "
             "WHERE salary IS NOT NULL GROUP BY department.dept_code")),

    # A filter on the computed value has to reach the bag too. `mirror_block` skips any
    # condition naming a calculation -- right while the calculations stayed outside, wrong the
    # moment `_mirror_calculations` began copying them in. The bag then filtered on nothing:
    # `WHERE x > 200000` with `THE AVERAGE x GROUPED BY d` averaged every row and returned a
    # figure BELOW the threshold its own filter enforces, which is impossible and is how a
    # writer caught it. Before the copies existed the same shape refused to compile, so this
    # was a loud failure turned silent -- the worst direction to move a defect in.
    ("a grouped average over a filtered computed value keeps the filter",
     "LIST d, a FROM Employee has EmployeeSalary s AND ALSO has Department "
     "has DepartmentCode d AND ALSO has Department has DepartmentBudget b "
     "AND ALSO (s + b) AS x WHERE x > 300000 AND ALSO THE AVERAGE x GROUPED BY d AS a",
     same_as("SELECT dp.dept_code, AVG(e.salary + dp.budget) FROM employee e "
             "JOIN department dp ON dp.dept_code = e.dept_code "
             "WHERE e.salary + dp.budget > 300000 GROUP BY dp.dept_code")),

    ("and a grouped average can never fall below its own filter",
     "LIST d, a FROM Employee has EmployeeSalary s AND ALSO has Department "
     "has DepartmentCode d AND ALSO has Department has DepartmentBudget b "
     "AND ALSO (s + b) AS x WHERE x > 300000 AND ALSO THE AVERAGE x GROUPED BY d AS a",
     rows_where(lambda r: all(row[1] > 300000 for row in r))),

    ("and a sum over one sums",
     "LIST g, a FROM Employee has EmployeeGender g AND ALSO has EmployeeSalary s "
     "AND ALSO (s * 2) AS x AND ALSO THE SUM OF x GROUPED BY g AS a",
     same_as("SELECT gender, SUM(salary * 2) FROM employee "
             "WHERE gender IS NOT NULL AND salary IS NOT NULL GROUP BY gender",
             wrong="SELECT gender, MIN(salary * 2) FROM employee "
                   "WHERE gender IS NOT NULL AND salary IS NOT NULL GROUP BY gender")),
    ("the maximum was always right, and stays right",
     "LIST g, a FROM Employee has EmployeeGender g AND ALSO has EmployeeSalary s "
     "AND ALSO (s * 2) AS x AND ALSO THE MAXIMUM x GROUPED BY g AS a",
     same_as("SELECT gender, MAX(salary * 2) FROM employee "
             "WHERE gender IS NOT NULL AND salary IS NOT NULL GROUP BY gender")),
    # The shape finding 145's fix turned from a silent MIN into broken SQL: two grouped
    # aggregates where one's `if` repeats the other's expression. Sharing the subexpression
    # makes them share a node, the second is re-lowered into a bag, and its argument still
    # pointed at the outer block -- `SUM()` over an outer column, which SQLite refuses. A
    # blind writer reduced it to this; `_first_node` could not see a node nested inside a
    # conditional (finding 149).
    ("two grouped aggregates, one whose condition repeats the other's expression",
     "LIST d, m, n FROM Employee has Department has DepartmentCode d AND ALSO "
     "has EmployeeSalary s AND ALSO (s * 2) AS a AND ALSO if(s * 2 > 200000, 1, 0) AS b "
     "AND ALSO THE AVERAGE a GROUPED BY d AS m AND ALSO THE SUM OF b GROUPED BY d AS n",
     same_as("SELECT d.dept_code, AVG(e.salary * 2), "
             "SUM(CASE WHEN e.salary * 2 > 200000 THEN 1 ELSE 0 END) "
             "FROM employee e JOIN department d ON d.dept_code = e.dept_code "
             "WHERE e.salary IS NOT NULL GROUP BY d.dept_code")),
    ("and a conditional alone is aggregated, not minimised",
     "LIST d, n FROM Employee has Department has DepartmentCode d AND ALSO "
     "has EmployeeSalary s AND ALSO if(s > 100000, 1, 0) AS b "
     "AND ALSO THE SUM OF b GROUPED BY d AS n",
     same_as("SELECT d.dept_code, SUM(CASE WHEN e.salary > 100000 THEN 1 ELSE 0 END) "
             "FROM employee e JOIN department d ON d.dept_code = e.dept_code "
             "WHERE e.salary IS NOT NULL GROUP BY d.dept_code")),

    ("a parent's measure beside the parent still takes MIN, which is the case this is for",
     "LIST c, t FROM Department has DepartmentCode c AND ALSO has DepartmentBudget b "
     "AND ALSO is of Employee AND ALSO THE SUM OF b GROUPED BY c AS t",
     same_as("SELECT d.dept_code, d.budget FROM department d "
             "WHERE EXISTS (SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code)")),

    # -- what blind benchmark writers found (findings 97-98) --------------------------------
    # Two grouped aggregates over ONE computed key. The GROUP BY list is deduplicated but the
    # key's parameters were bound once per aggregate, so every such query failed to run at all
    # with "Incorrect number of bindings supplied". Two writers hit it independently.
    ("two grouped aggregates over one computed key bind their parameters once",
     "LIST g, n, m FROM Employee has EmployeeSalary s AND ALSO if(s > 100000, 'high', 'low') "
     "AS g AND ALSO THE COUNT OF s GROUPED BY g AS n AND ALSO THE AVERAGE s GROUPED BY g AS m",
     same_as("SELECT CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END, COUNT(salary), "
             "AVG(salary) FROM employee WHERE salary IS NOT NULL "
             "GROUP BY CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END")),

    ("and a third aggregate over the same key does not break it either",
     "LIST g, n, t FROM Employee has EmployeeSalary s AND ALSO if(s > 100000, 'high', 'low') "
     "AS g AND ALSO THE COUNT OF s GROUPED BY g AS n AND ALSO THE AVERAGE s GROUPED BY g AS m "
     "AND ALSO THE SUM OF s GROUPED BY g AS t",
     same_as("SELECT CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END, COUNT(salary), "
             "SUM(salary) FROM employee WHERE salary IS NOT NULL "
             "GROUP BY CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END")),

    # An associative operator over more than two arguments folds. `concat(a, '-', b)` fell
    # through to CONCAT(), which SQLite before 3.44 does not have -- so a query that worked
    # with two arguments failed with three, and the model's own `||` was ignored.
    # -- row-relative: what a row is against the other rows of its partition (finding 104) ---
    # Three blind writers needed one of these and none could be said: a rank column, a median,
    # a previous-row comparison. RANK orders the window by the value being ranked, descending,
    # so rank 1 is the largest.
    ("THE RANK OF is a rank within the partition",
     "LIST n, r FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d "
     "AND ALSO has EmployeeSalary s AND ALSO THE RANK OF s WITHIN d AS r",
     same_as("SELECT e.emp_name, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC) "
             "FROM employee e JOIN department d ON d.dept_code = e.dept_code "
             "WHERE e.salary IS NOT NULL")),

    ("THE PREVIOUS is the prior row in the order it names",
     "LIST n, p FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
     "AND ALSO has EmployeeName n AND ALSO THE PREVIOUS s BY n WITHIN d AS p",
     same_as("SELECT e.emp_name, LAG(e.salary) OVER "
             "(PARTITION BY e.dept_code ORDER BY e.emp_name ASC) "
             "FROM employee e JOIN department d ON d.dept_code = e.dept_code "
             "WHERE e.salary IS NOT NULL")),

    # Both are window-only: GROUPED BY returns one row per group and leaves nothing to be
    # relative to. And a previous row without an order is not a previous row.
    ("a rank GROUPED BY is refused, not silently collapsed",
     "LIST d, r FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
     "AND ALSO THE RANK OF s GROUPED BY d AS r",
     refuses("needs WITHIN and not GROUPED BY")),

    ("and THE PREVIOUS without a BY key is refused",
     "LIST d, p FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
     "AND ALSO THE PREVIOUS s WITHIN d AS p",
     refuses("needs the order it is previous in")),

    # Finding 101. `Employee has Department is of Employee` stands on `employee.dept_code`
    # and re-enters the same fact type by its department role -- same table, same columns --
    # which read as absorbed and handed back the row already in hand. Each employee was paired
    # with themselves: six rows where the colleague pairs are fourteen, silently, from a
    # well-formed query. Three blind benchmark writers hit it on three different schemas.
    ("a round trip through an entity joins rather than returning the row in hand",
     "LIST a, b FROM Employee has EmployeeName a AND ALSO has Department is of Employee "
     "has EmployeeName b",
     same_as("SELECT a.emp_name, b.emp_name FROM employee a "
             "JOIN employee b ON b.dept_code = a.dept_code")),

    # The same shape one hop further out, and the one that must still absorb: reading another
    # value of the row in hand is not a join and must not become one.
    ("but reading another value of the same row still absorbs",
     "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
     same_as("SELECT emp_name, salary FROM employee WHERE salary IS NOT NULL")),

    # Finding 100: without sqrt, a writer needing an escape velocity implemented
    # Newton-Raphson inline, and a longer version of the same trick overflowed SQLite's parser
    # because every `AS` binding is inlined textually.
    ("a root is a function, not six iterations of Newton-Raphson",
     "LIST r FROM Department has DepartmentBudget b AND ALSO round(sqrt(b), 3) AS r",
     same_as("SELECT ROUND(sqrt(budget), 3) FROM department")),

    ("an associative operator folds over more than two arguments",
     "LIST c FROM Employee has EmployeeName n AND ALSO has EmployeeGender g "
     "AND ALSO concat(n, '-', g) AS c",
     same_as("SELECT emp_name || '-' || gender FROM employee WHERE gender IS NOT NULL")),

    # -- what blind benchmark writers found (findings 97-98) --------------------------------
    # Two grouped aggregates over ONE computed key. The GROUP BY list is deduplicated but the
    # key's parameters were bound once per aggregate, so every such query failed to run at all
    # with "Incorrect number of bindings supplied".
    ("two grouped aggregates over one computed key bind their parameters once",
     "LIST g, n, m FROM Employee has EmployeeSalary s AND ALSO if(s > 100000, 'high', 'low') "
     "AS g AND ALSO THE COUNT OF s GROUPED BY g AS n AND ALSO THE AVERAGE s GROUPED BY g AS m",
     same_as("SELECT CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END, COUNT(salary), "
             "AVG(salary) FROM employee WHERE salary IS NOT NULL "
             "GROUP BY CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END")),

    ("and a third aggregate does not break it either",
     "LIST g, n, t FROM Employee has EmployeeSalary s AND ALSO if(s > 100000, 'high', 'low') "
     "AS g AND ALSO THE COUNT OF s GROUPED BY g AS n AND ALSO THE AVERAGE s GROUPED BY g AS m "
     "AND ALSO THE SUM OF s GROUPED BY g AS t",
     same_as("SELECT CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END, COUNT(salary), "
             "SUM(salary) FROM employee WHERE salary IS NOT NULL "
             "GROUP BY CASE WHEN salary > 100000 THEN 'high' ELSE 'low' END")),

    # An associative operator over more than two arguments folds. `concat(a, '-', b)` fell
    # through to CONCAT(), which SQLite before 3.44 does not have -- so a query that worked
    # with two arguments failed with three, and the model's own `||` was ignored.
    # -- row-relative: what a row is against the other rows of its partition (finding 104) ---
    # Three blind writers needed one of these and none could be said: a rank column, a median,
    # a previous-row comparison. RANK orders the window by the value being ranked, descending,
    # so rank 1 is the largest.
    ("THE RANK OF is a rank within the partition",
     "LIST n, r FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d "
     "AND ALSO has EmployeeSalary s AND ALSO THE RANK OF s WITHIN d AS r",
     same_as("SELECT e.emp_name, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC) "
             "FROM employee e JOIN department d ON d.dept_code = e.dept_code "
             "WHERE e.salary IS NOT NULL")),

    ("THE PREVIOUS is the prior row in the order it names",
     "LIST n, p FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
     "AND ALSO has EmployeeName n AND ALSO THE PREVIOUS s BY n WITHIN d AS p",
     same_as("SELECT e.emp_name, LAG(e.salary) OVER "
             "(PARTITION BY e.dept_code ORDER BY e.emp_name ASC) "
             "FROM employee e JOIN department d ON d.dept_code = e.dept_code "
             "WHERE e.salary IS NOT NULL")),

    # Both are window-only: GROUPED BY returns one row per group and leaves nothing to be
    # relative to. And a previous row without an order is not a previous row.
    ("a rank GROUPED BY is refused, not silently collapsed",
     "LIST d, r FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
     "AND ALSO THE RANK OF s GROUPED BY d AS r",
     refuses("needs WITHIN and not GROUPED BY")),

    ("and THE PREVIOUS without a BY key is refused",
     "LIST d, p FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
     "AND ALSO THE PREVIOUS s WITHIN d AS p",
     refuses("needs the order it is previous in")),

    # Finding 101. `Employee has Department is of Employee` stands on `employee.dept_code`
    # and re-enters the same fact type by its department role -- same table, same columns --
    # which read as absorbed and handed back the row already in hand. Each employee was paired
    # with themselves: six rows where the colleague pairs are fourteen, silently, from a
    # well-formed query. Three blind benchmark writers hit it on three different schemas.
    ("a round trip through an entity joins rather than returning the row in hand",
     "LIST a, b FROM Employee has EmployeeName a AND ALSO has Department is of Employee "
     "has EmployeeName b",
     same_as("SELECT a.emp_name, b.emp_name FROM employee a "
             "JOIN employee b ON b.dept_code = a.dept_code")),

    # The same shape one hop further out, and the one that must still absorb: reading another
    # value of the row in hand is not a join and must not become one.
    ("but reading another value of the same row still absorbs",
     "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
     same_as("SELECT emp_name, salary FROM employee WHERE salary IS NOT NULL")),

    # One Department has many Employee. Summing the budget over that path adds each budget
    # once per employee: 2.4M x 3 + 0.3M x 1 + 0.9M x 2 = 9,300,000 against a true 3,600,000.
    ("a summed value is counted once, not once per fan-out row",
     "THE SUM OF b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n",
     same_as("SELECT SUM(d.budget) FROM department d WHERE EXISTS "
             "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code AND e.emp_name IS NOT NULL)",
             wrong="SELECT SUM(d.budget) FROM department d "
                   "JOIN employee e ON e.dept_code = d.dept_code")),

    # The same trap the other way round: the fan is *before* the value. Three employees are
    # assigned to one project, so the project's priority is on three rows; its determinant
    # (Project, by the uniqueness constraint on `Project has ProjectPriority`) is in the path,
    # and section 14b says the bag is that node's distinct values -- 9, not 17. The locality
    # check keyed the value by its whole ancestry, which included Employee, and so saw no
    # repetition. Found by the reference interpreter on a query the laws suite generated.
    ("a value reached through a fan-in is summed once per determinant",
     "THE SUM OF Employee has Project has ProjectPriority",
     same_as("SELECT SUM(priority) FROM project WHERE proj_code IN (SELECT proj_code FROM assignment)",
             wrong="SELECT SUM(p.priority) FROM assignment a JOIN project p ON p.proj_code = a.proj_code")),

    ("and averaged once per determinant",
     "THE AVERAGE Employee has Project has ProjectPriority",
     same_as("SELECT AVG(priority) FROM project WHERE proj_code IN (SELECT proj_code FROM assignment)",
             wrong="SELECT AVG(p.priority) FROM assignment a JOIN project p ON p.proj_code = a.proj_code")),

    # And with no fan-out step at all: two many-to-one steps put each department's budget
    # on a row per employee. The relation is the one the first case in this group walks from
    # the other end, and the sum is the same 3,600,000 -- the compiler said 9,300,000 for
    # this spelling and 3,600,000 for that one until the reference interpreter compared them.
    ("a value reached through many-to-one steps from a repeating head is summed once",
     "THE SUM OF Employee has Department has DepartmentBudget",
     same_as("SELECT SUM(budget) FROM department WHERE dept_code IN (SELECT dept_code FROM employee)",
             wrong="SELECT SUM(d.budget) FROM employee e JOIN department d ON d.dept_code = e.dept_code")),

    ("and averaged once",
     "THE AVERAGE Employee has Department has DepartmentBudget",
     same_as("SELECT AVG(budget) FROM department WHERE dept_code IN (SELECT dept_code FROM employee)",
             wrong="SELECT AVG(d.budget) FROM employee e JOIN department d ON d.dept_code = e.dept_code")),

    ("but a value the head itself determines is summed once per head",
     "THE SUM OF Employee has EmployeeSalary",
     same_as("SELECT SUM(salary) FROM employee")),

    # Under GROUPED BY (finding 112, closed in 117): a department code pins nothing about
    # the project, so a priority shared by two ENG employees is added once per department.
    ("a grouped sum whose keys do not pin the value adds each determined value once",
     "LIST d, t FROM Employee has Department has DepartmentCode d AND ALSO has Project has "
     "ProjectPriority p AND ALSO THE SUM OF p GROUPED BY d AS t",
     same_as("SELECT dc, SUM(priority) FROM (SELECT DISTINCT e.dept_code AS dc, p.proj_code, "
             "p.priority FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr "
             "JOIN project p ON p.proj_code = a.proj_code) GROUP BY dc",
             wrong="SELECT e.dept_code, SUM(p.priority) FROM employee e JOIN assignment a "
                   "ON a.emp_nr = e.emp_nr JOIN project p ON p.proj_code = a.proj_code "
                   "GROUP BY e.dept_code")),

    ("and averages it once",
     "LIST d, t FROM Employee has Department has DepartmentCode d AND ALSO has Project has "
     "ProjectPriority p AND ALSO THE AVERAGE p GROUPED BY d AS t",
     same_as("SELECT dc, AVG(priority) FROM (SELECT DISTINCT e.dept_code AS dc, p.proj_code, "
             "p.priority FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr "
             "JOIN project p ON p.proj_code = a.proj_code) GROUP BY dc",
             wrong="SELECT e.dept_code, AVG(p.priority) FROM employee e JOIN assignment a "
                   "ON a.emp_nr = e.emp_nr JOIN project p ON p.proj_code = a.proj_code "
                   "GROUP BY e.dept_code")),

    ("while a key that pins the head keeps the plain sum",
     "LIST n, t FROM Employee has EmployeeNr n AND ALSO has Project has ProjectPriority p "
     "AND ALSO THE SUM OF p GROUPED BY n AS t",
     same_as("SELECT e.emp_nr, SUM(p.priority) FROM employee e JOIN assignment a "
             "ON a.emp_nr = e.emp_nr JOIN project p ON p.proj_code = a.proj_code "
             "GROUP BY e.emp_nr")),

    ("and the bound form is the same query",
     "THE SUM OF p IN Employee has Project has ProjectPriority p",
     same_as("SELECT SUM(priority) FROM project WHERE proj_code IN (SELECT proj_code FROM assignment)",
             wrong="SELECT SUM(p.priority) FROM assignment a JOIN project p ON p.proj_code = a.proj_code")),

    ("and an averaged one",
     "THE AVERAGE b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n",
     same_as("SELECT AVG(d.budget) FROM department d WHERE EXISTS "
             "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code AND e.emp_name IS NOT NULL)",
             wrong="SELECT AVG(d.budget) FROM department d "
                   "JOIN employee e ON e.dept_code = d.dept_code")),

    # A second, independent trap: one Employee has many Assignment, so a salary summed over
    # the assignment path is added once per assignment. 1,069,500 against a true 720,500.
    ("the same through an objectified fact type",
     "THE SUM OF s IN Employee has EmployeeSalary s AND ALSO has Assignment has AssignmentHours h",
     same_as("SELECT SUM(e.salary) FROM employee e WHERE EXISTS "
             "(SELECT 1 FROM assignment a WHERE a.emp_nr = e.emp_nr AND a.hours IS NOT NULL)",
             wrong="SELECT SUM(e.salary) FROM employee e "
                   "JOIN assignment a ON a.emp_nr = e.emp_nr")),

    # -- what needs no fixing -------------------------------------------------------------
    ("no fan-out, no deduplication",
     "THE SUM OF b IN Department has DepartmentBudget b",
     same_as("SELECT SUM(budget) FROM department")),

    # MIN and MAX are unchanged by repetition: the largest of a bag is the largest of that bag
    # with duplicates in it. They are never deduplicated and never refused.
    ("a maximum is unchanged by repetition",
     "THE MAXIMUM b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n",
     same_as("SELECT MAX(budget) FROM department")),
    ("and so is a minimum",
     "THE MINIMUM b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n",
     same_as("SELECT MIN(budget) FROM department")),

    # -- the grouped form, where the group keys pin the value ------------------------------
    # Grouping by DepartmentCode pins the Department, which determines the budget, so every row
    # of a group carries the same one and the group holds exactly one instance. MIN of a
    # constant is that constant. Malloy reaches the same numbers by its distinct-key route
    # (bench/malloy-probe): ENG 2,400,000, SALES 900,000, HR 300,000.
    ("a grouped sum whose keys pin the value is computed, not refused",
     "LIST c, t FROM Department has DepartmentCode c AND ALSO has DepartmentBudget b "
     "AND ALSO is of Employee has EmployeeName n AND ALSO THE SUM OF b GROUPED BY c AS t",
     same_as("SELECT d.dept_code, d.budget FROM department d WHERE EXISTS "
             "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code AND e.emp_name IS NOT NULL)",
             wrong="SELECT d.dept_code, SUM(d.budget) FROM department d "
                   "JOIN employee e ON e.dept_code = d.dept_code GROUP BY d.dept_code")),
    ("and the average with it",
     "LIST c, t FROM Department has DepartmentCode c AND ALSO has DepartmentBudget b "
     "AND ALSO is of Employee has EmployeeName n AND ALSO THE AVERAGE b GROUPED BY c AS t",
     same_as("SELECT d.dept_code, d.budget FROM department d WHERE EXISTS "
             "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code AND e.emp_name IS NOT NULL)")),

    # ...but when the keys do NOT pin it -- salary is determined by Employee, and a Department
    # has many -- the group holds several distinct values, each repeated by the second
    # branch. This used to be refused, because per-aggregate deduplication is what one flat
    # statement cannot do. Now the aggregate is re-lowered over a bag of its own, correlated
    # on the keys, where the deduplication is ordinary (finding 117): each employee's salary
    # once per department.
    ("a grouped sum whose keys do not pin the value adds each employee's salary once",
     "LIST c, t FROM Department has DepartmentCode c AND ALSO is of Employee has EmployeeSalary s "
     "AND ALSO is of Employee has Assignment has AssignmentHours h "
     "AND ALSO THE SUM OF s GROUPED BY c AS t",
     same_as("SELECT d.dept_code, SUM(e.salary) FROM department d JOIN employee e "
             "ON e.dept_code = d.dept_code WHERE EXISTS (SELECT 1 FROM employee e2 JOIN assignment a "
             "ON a.emp_nr = e2.emp_nr WHERE e2.dept_code = d.dept_code) GROUP BY d.dept_code",
             wrong="SELECT d.dept_code, SUM(e.salary) FROM department d JOIN employee e "
                   "ON e.dept_code = d.dept_code JOIN employee e2 ON e2.dept_code = d.dept_code "
                   "JOIN assignment a ON a.emp_nr = e2.emp_nr GROUP BY d.dept_code")),

    ("and the refusal's own suggestion works",
     "LIST c, t FROM Department has DepartmentCode c AND ALSO has DepartmentBudget b "
     "AND ALSO [is of Employee] AND ALSO THE SUM OF b GROUPED BY c AS t",
     same_as("SELECT d.dept_code, SUM(d.budget) FROM department d WHERE EXISTS "
             "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code) GROUP BY d.dept_code",
             wrong="SELECT d.dept_code, SUM(d.budget) FROM department d "
                   "JOIN employee e ON e.dept_code = d.dept_code GROUP BY d.dept_code")),

    # A bracket that binds a name is a join, not a semijoin, so it multiplies like the bare
    # path -- but the group keys still pin the budget, so the value is taken once and the
    # answer is right either way. Where the keys do NOT pin it, the binding bracket is refused
    # and the message says so; that is `test_errors.py`.
    ("a bracket that binds a name joins, but a pinned value survives it",
     "LIST c, t FROM Department has DepartmentCode c AND ALSO has DepartmentBudget b "
     "AND ALSO [is of Employee has EmployeeName n] AND ALSO THE SUM OF b GROUPED BY c AS t",
     same_as("SELECT d.dept_code, d.budget FROM department d WHERE EXISTS "
             "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code AND e.emp_name IS NOT NULL)",
             wrong="SELECT d.dept_code, SUM(d.budget) FROM department d "
                   "JOIN employee e ON e.dept_code = d.dept_code GROUP BY d.dept_code")),

    # -- COUNT is the author's call --------------------------------------------------------
    # Counting a fanned head has two defensible readings and the compiler picks neither:
    # deduplicating it scored net -1 over the recorded corpus (finding 79), refusing it
    # rejected 20 right answers for 5 wrong (finding 78).
    ("counting a fanned head counts the rows, as written",
     "THE COUNT OF Employee has Assignment",
     same_as("SELECT COUNT(*) FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr")),
    ("and the bracket form counts the heads",
     "THE COUNT OF Employee [has Assignment]",
     same_as("SELECT COUNT(*) FROM employee e WHERE EXISTS "
             "(SELECT 1 FROM assignment a WHERE a.emp_nr = e.emp_nr)")),
    ("DISTINCT is how the author says which they mean",
     "THE DISTINCT COUNT OF s IN Employee has EmployeeSalary s AND ALSO has Assignment",
     same_as("SELECT COUNT(DISTINCT e.salary) FROM employee e "
             "JOIN assignment a ON a.emp_nr = e.emp_nr")),

    # -- a fan-out the model proves harmless ----------------------------------------------
    # Assignment carries a uniqueness constraint spanning BOTH its roles, so for one
    # (employee, project) there is one row. A count grouped by those is not multiplied, and
    # check_aggregate_locality has to see that or it would refuse every many-to-many.
    ("a many-to-many pinned by a spanning uniqueness constraint is not refused",
     "LIST p, c FROM Employee e has Assignment has Project has ProjectName p "
     "AND ALSO THE COUNT OF e GROUPED BY p AS c",
     same_as("SELECT pr.proj_name, COUNT(*) FROM assignment a "
             "JOIN project pr ON pr.proj_code = a.proj_code GROUP BY pr.proj_name")),
]


def run(model, conn, lexicon, emitter, query, expect, verbose):
    kind, sql, wrong = expect
    try:
        _, statement, params = driver.transpile(model, query, lexicon, emitter)
    except Exception as e:                                             # noqa: BLE001
        if kind == "refuses":
            return (sql in str(e)), "%s: %s" % (type(e).__name__, str(e).split("\n")[0][:70])
        return False, "%s: %s" % (type(e).__name__, str(e).split("\n")[0][:80])
    if kind == "refuses":
        return False, "expected a refusal mentioning %r, but it compiled" % sql
    if kind == "rows_where":
        # An invariant the rows must satisfy, for a property no reference query states as
        # neatly as the property itself -- "a grouped average cannot fall below its own
        # filter" is the check that caught a dropped filter in the wild.
        rows = conn.execute(statement, params).fetchall()
        if not rows:
            return False, "no rows, so the invariant proves nothing"
        return (bool(sql(rows)), "%d rows satisfy the invariant" % len(rows)) if sql(rows) \
            else (False, "invariant violated: %s" % (rows[:3],))

    got = sorted(tuple(str(v) for v in r) for r in conn.execute(statement, params).fetchall())
    want = sorted(tuple(str(v) for v in r) for r in conn.execute(sql).fetchall())
    if got != want:
        return False, "returns %s, should be %s" % (got[:3], want[:3])
    if wrong is not None:
        naive = sorted(tuple(str(v) for v in r) for r in conn.execute(wrong).fetchall())
        if naive == want:
            return False, ("the fixture no longer contains this trap: the naive join gives the "
                           "same answer, so this case proves nothing")
        return True, "%s, where the naive join gives %s" % (
            got[0] if len(got) == 1 else "%d rows" % len(got),
            naive[0] if len(naive) == 1 else "%d rows" % len(naive))
    return True, str(got[:2])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (os.path.exists(args.model) and os.path.exists(args.db)):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.db)
        return 2

    model = json.load(open(args.model))
    conn = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    lexicon, emitter = parser_mod.Lexicon(model), sql_mod.Emitter(model)
    cases = [c for c in CASES if not args.only or args.only.lower() in c[0].lower()]
    passed = failed = 0
    for name, query, expect in cases:
        ok, note = run(model, conn, lexicon, emitter, query, expect, args.verbose)
        if ok:
            passed += 1
            print("ok    %-62s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s\n        %s" % (name, query, note))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
