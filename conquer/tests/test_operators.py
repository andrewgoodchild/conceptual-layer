#!/usr/bin/env python3
"""One test per operator in the ConQuer-92 lexicon.

The table below mirrors the keyword table in appendix B of the report (arXiv:2105.11926)
line for line, so spec coverage is readable at a glance: every operator the report defines appears
here, with an assertion saying either what it computes or why it does not compile.

That second kind matters as much as the first. Two operators were found wired to the wrong
meaning by reading the spec table against the code -- `EXCLUDING` was bound to disjointness,
which is a *different* circled-times -- and a refusal that names the reason is what stops
that recurring silently.

Assertions:
    same_as(SQL)   run both against the fixture and compare result multisets
    ordered_as(SQL) as same_as, but row ORDER must match too -- the only way to test ORDER BY
    rows(n)        executes and returns exactly n rows
    sql_has(s)     the generated SQL contains s
    sql_has_count(s, n) the generated SQL contains s exactly n times
    refuses(s)     raises ParseError whose message contains s
    ambiguous(s)   raises Ambiguous whose message contains s

    test_operators.py [-v] [--only SUBSTRING]
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402


def same_as(sql):   return ("same_as", sql)
def ordered_as(sql): return ("ordered_as", sql)
def rows(n):        return ("rows", n)
def sql_has(s):     return ("sql_has", s)
def sql_has_count(s, n): return ("sql_has_count", (s, n))
def refuses(s):     return ("refuses", s)
def ambiguous(s):   return ("ambiguous", s)


# The fixture is reverse/tests/company.sql: 3 departments, 6 employees (2 of them managers),
# 3 projects, 7 assignments. Small enough that every expected count is checkable by hand.
CASES = [
 # -- section 6.1: the two primitives and concatenation ------------------------
 ("CONCAT  (juxtaposition)", "Employee has Department",
  same_as("SELECT emp_nr, dept_code FROM employee")),
 ("CONCAT through a value", "LIST n FROM Employee has EmployeeName n",
  same_as("SELECT emp_name FROM employee")),
 ("REVERSE  THE REVERSE OF", "THE REVERSE OF Employee has Department",
  refuses("path reversal")),
 ("inverse reading  is of", "LIST n FROM Department is of Employee has EmployeeName n",
  same_as("SELECT emp_name FROM employee WHERE dept_code IS NOT NULL")),

 # -- section 6.2: complex operations ------------------------------------------
 ("Fr  ONLY", "ONLY Employee has EmployeeName", rows(6)),
 ("Ds  DISTINCT", "LIST d FROM DISTINCT Employee has Department has DepartmentCode d",
  same_as("SELECT DISTINCT dept_code FROM employee WHERE dept_code IS NOT NULL")),
 ("PRODUCT  WITH", "Employee WITH Department", refuses("cartesian product")),
 # Section 6.2's set operations over whole paths: each side is a query of its own (a bare
 # path lists its head and tail), the sides list the same number of things, and ordering and
 # the limit apply to the whole. Built from the CCM's SetExpr (model.md G3).
 ("UNION  UNITED WITH", "Employee has EmployeeName UNITED WITH Department has DepartmentName",
  same_as("SELECT emp_nr, emp_name FROM employee "
          "UNION SELECT dept_code, dept_name FROM department")),
 ("UNION  of two listed queries",
  "(LIST n FROM Employee has EmployeeName n) UNITED WITH "
  "(LIST n FROM Department has DepartmentName n)",
  same_as("SELECT emp_name FROM employee UNION SELECT dept_name FROM department")),
 ("INTERSECTION  INTERSECTED WITH",
  "(LIST c FROM Employee has Department has DepartmentCode c) INTERSECTED WITH "
  "(LIST c FROM Department has DepartmentCode c)",
  same_as("SELECT dept_code FROM employee WHERE dept_code IS NOT NULL "
          "INTERSECT SELECT dept_code FROM department")),
 ("DIFFERENCE  MINUS",
  "(LIST c FROM Department has DepartmentCode c) MINUS "
  "(LIST c FROM Employee has Department has DepartmentCode c)",
  same_as("SELECT dept_code FROM department "
          "EXCEPT SELECT dept_code FROM employee WHERE dept_code IS NOT NULL")),
 ("set operation  ordered and limited as a whole, by a listed name",
  "(LIST n FROM Employee has EmployeeName n) UNITED WITH "
  "(LIST n FROM Department has DepartmentName n) ORDERED WITH n DESCENDING THE FIRST 3",
  ordered_as("SELECT n FROM (SELECT emp_name AS n FROM employee "
             "UNION SELECT dept_name FROM department) ORDER BY n DESC LIMIT 3")),
 ("set operation  a chain associates to the left, as section 6.2 reads it",
  "((LIST n FROM Employee has EmployeeName n) UNITED WITH "
  "(LIST n FROM Department has DepartmentName n)) MINUS "
  "(LIST n FROM Department has DepartmentName n)",
  same_as("SELECT DISTINCT emp_name FROM employee")),
 ("set operation  an operand may carry its own ordering and limit",
  "(LIST n FROM Employee has EmployeeName n ORDERED WITH n ASCENDING THE FIRST 2) UNITED WITH "
  "(LIST n FROM Department has DepartmentName n)",
  same_as("SELECT * FROM (SELECT emp_name FROM employee ORDER BY emp_name LIMIT 2) "
          "UNION SELECT dept_name FROM department")),
 ("set operation  the sides must list the same number of things",
  "(LIST n FROM Employee has EmployeeName n) UNITED WITH "
  "(LIST n, c FROM Department has DepartmentName n AND ALSO has DepartmentCode c)",
  refuses("same number")),
 ("set operation  a LIST over the whole does not say which side it lists",
  "LIST n FROM Employee has EmployeeName n UNITED WITH Department has DepartmentName n",
  refuses("inside each operand")),
 ("set operation  inside a path it has nothing to combine",
  "LIST n FROM Employee has EmployeeName n AND ALSO (Employee UNITED WITH Department)",
  refuses("whole query")),
 ("FRONT_INTERSECTION  AND ALSO",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department: 'ENG'",
  same_as("SELECT emp_name FROM employee WHERE dept_code = 'ENG'")),
 ("FRONT_UNION  OR OTHERWISE",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department: 'ENG' "
  "OR OTHERWISE has Department: 'HR'",
  same_as("SELECT emp_name FROM employee WHERE dept_code IN ('ENG','HR')")),
 # ... and the leftmost operand of a disjunction is an operand too. Merged into the block it
 # was a hard filter, so `[A OR OTHERWISE B]` meant A AND B (finding 41, found by the
 # metamorphic laws, not by anyone thinking to write this case).
 ("FRONT_UNION  where the disjunction is the whole filter",
  "THE COUNT OF Employee [has EmployeeGender: 'F' OR OTHERWISE has Department: 'ENG']",
  same_as("SELECT COUNT(*) FROM employee WHERE gender = 'F' OR dept_code = 'ENG'")),
 ("FRONT_UNION  three alternatives fold left",
  "THE COUNT OF Employee [has EmployeeGender: 'F' OR OTHERWISE has Department: 'ENG' "
  "OR OTHERWISE has Department: 'HR']",
  same_as("SELECT COUNT(*) FROM employee WHERE gender = 'F' OR dept_code IN ('ENG','HR')")),
 ("FRONT_DIFFERENCE  BUT NOT",
  "LIST n FROM Employee has EmployeeName n BUT NOT has Department: 'ENG'",
  same_as("SELECT emp_name FROM employee WHERE dept_code <> 'ENG'")),
 ("ALL_TAILS_IN  WHICH ARE ALL IN",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "WHICH ARE ALL IN Employee: 4 has Assignment has Project",
  same_as("SELECT e.emp_name FROM employee e WHERE NOT EXISTS ("
          " SELECT a.proj_code FROM assignment a WHERE a.emp_nr = e.emp_nr"
          " EXCEPT SELECT b.proj_code FROM assignment b WHERE b.emp_nr = 4)")),
 ("INCLUDES_ALL_HEADS  THAT INCLUDES ALL",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "THAT INCLUDES ALL Employee: 2 has Assignment has Project",
  same_as("SELECT e.emp_name FROM employee e WHERE NOT EXISTS ("
          " SELECT b.proj_code FROM assignment b WHERE b.emp_nr = 2"
          " EXCEPT SELECT a.proj_code FROM assignment a WHERE a.emp_nr = e.emp_nr)")),
 ("MATCHING_ALL  MATCHING ALL",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "MATCHING ALL Employee: 5 has Assignment has Project",
  sql_has("EXCEPT")),
 ("MISSING (underlined, path op)", "Employee has Department MISSING Employee: 1 has Department",
  refuses("complement-of-concatenation")),
 ("EXCLUDING (underlined, path op)",
  "Employee has Department EXCLUDING Employee: 1 has Department",
  refuses("complement-of-concatenation")),
 ("Path  THE PATH FROM", "THE PATH FROM e TO d OF Employee e has Department d",
  refuses("path shuffle")),
 ("sub-expression  [ ... ]",
  "LIST n FROM Employee [has Department: 'ENG'] has EmployeeName n",
  same_as("SELECT emp_name FROM employee WHERE dept_code = 'ENG'")),

 # -- value comparisons (section 6.2) ------------------------------------------
 ("LT  <", "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary < 100000",
  same_as("SELECT emp_name FROM employee WHERE salary < 100000")),
 ("LE  <=", "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary <= 98000",
  same_as("SELECT emp_name FROM employee WHERE salary <= 98000")),
 ("GT  IS GREATER THAN",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary IS GREATER THAN 170000",
  same_as("SELECT emp_name FROM employee WHERE salary > 170000")),
 ("GE  >=", "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary >= 172000",
  same_as("SELECT emp_name FROM employee WHERE salary >= 172000")),
 ("EQ  IS EQUAL TO",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeGender IS EQUAL TO 'X'",
  same_as("SELECT emp_name FROM employee WHERE gender = 'X'")),
 ("NE  <>", "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeGender <> 'F'",
  same_as("SELECT emp_name FROM employee WHERE gender <> 'F'")),

 # -- section 6.4 SetComp: comparisons of two whole head sets -------------------
 ("SUBSET  IS A SUBSET OF",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "IS A SUBSET OF Employee: 4 has Assignment has Project", sql_has("NOT EXISTS")),
 ("SUPERSET  IS A SUPERSET OF",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "IS A SUPERSET OF Employee: 2 has Assignment has Project", sql_has("NOT EXISTS")),
 ("PROPER_SUBSET  IS A PROPER SUBSET OF",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "IS A PROPER SUBSET OF Employee: 1 has Assignment has Project", sql_has("EXCEPT")),
 ("PROPER_SUPERSET  IS A PROPER SUPERSET OF",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "IS A PROPER SUPERSET OF Employee: 4 has Assignment has Project", sql_has("EXCEPT")),
 ("SET_EQ  EQUALS",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "EQUALS Employee: 5 has Assignment has Project", sql_has("EXCEPT")),
 ("DISJOINT  IS DISJOINT FROM (plain circled-times)",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "IS DISJOINT FROM Employee: 2 has Assignment has Project", sql_has("INTERSECT")),
 ("DISJOINT  EXCLUDES",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "EXCLUDES Employee: 2 has Assignment has Project", sql_has("INTERSECT")),

 # -- section 6.4 conditions ----------------------------------------------------
 ("Where  WHERE",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > 150000",
  same_as("SELECT emp_name FROM employee WHERE salary > 150000")),
 ("Some  SOME",
  "LIST n FROM Employee has EmployeeName n WHERE SOME Department has DepartmentCode: 'ENG'",
  same_as("SELECT emp_name FROM employee")),
 ("AND",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s > 90000 AND s < 170000",
  same_as("SELECT emp_name FROM employee WHERE salary > 90000 AND salary < 170000")),
 ("OR",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s < 90000 OR s > 180000",
  same_as("SELECT emp_name FROM employee WHERE salary < 90000 OR salary > 180000")),
 ("NOT",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE NOT s > 100000",
  same_as("SELECT emp_name FROM employee WHERE NOT salary > 100000")),
 ("XOR  EXCLUSIVE OR",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s > 100000 EXCLUSIVE OR s < 95000",
  same_as("SELECT emp_name FROM employee WHERE (salary > 100000) <> (salary < 95000)")),
 ("IMPLIES",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s > 180000 IMPLIES s > 100000",
  same_as("SELECT emp_name FROM employee WHERE NOT (salary > 180000) OR (salary > 100000)")),
 ("IFF",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s > 100000 IFF s > 150000",
  same_as("SELECT emp_name FROM employee WHERE (salary > 100000) = (salary > 150000)")),

 # -- section 6.6 group functions ----------------------------------------------
 ("Count  THE COUNT OF", "THE COUNT OF Employee",
  same_as("SELECT COUNT(emp_nr) FROM employee")),
 ("Sum  THE SUM OF", "THE SUM OF Employee has EmployeeSalary",
  same_as("SELECT SUM(salary) FROM employee")),
 ("Min  THE MINIMUM", "THE MINIMUM Employee has EmployeeSalary",
  same_as("SELECT MIN(salary) FROM employee")),
 ("Max  THE MAXIMUM", "THE MAXIMUM Employee has EmployeeSalary",
  same_as("SELECT MAX(salary) FROM employee")),
 ("Avg  THE AVERAGE", "THE AVERAGE Employee has EmployeeSalary",
  same_as("SELECT AVG(salary) FROM employee")),
 ("GDsCount  THE DISTINCT COUNT OF", "THE DISTINCT COUNT OF Employee has Department",
  same_as("SELECT COUNT(DISTINCT dept_code) FROM employee WHERE dept_code IS NOT NULL")),
 ("GDsSum  THE DISTINCT SUM OF", "THE DISTINCT SUM OF Employee has EmployeeSalary",
  same_as("SELECT SUM(DISTINCT salary) FROM employee")),
 # -- section 6.6 grouped aggregates, and B.2's group-accounting syntax ---------
 ("GCount  THE COUNT OF ... GROUPED BY",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c",
  same_as("SELECT dept_code, COUNT(*) FROM employee GROUP BY dept_code")),
 ("GSum  THE SUM OF ... GROUPED BY",
  "LIST d, t FROM Employee [has EmployeeSalary s] has Department has DepartmentCode d "
  "AND ALSO THE SUM OF s GROUPED BY d AS t",
  same_as("SELECT dept_code, SUM(salary) FROM employee GROUP BY dept_code")),
 ("GAvg  THE AVERAGE ... GROUPED BY",
  "LIST d, a FROM Employee [has EmployeeSalary s] has Department has DepartmentCode d "
  "AND ALSO THE AVERAGE s GROUPED BY d AS a",
  same_as("SELECT dept_code, AVG(salary) FROM employee GROUP BY dept_code")),
 ("GMax  THE MAXIMUM ... GROUPED BY",
  "LIST d, m FROM Employee [has EmployeeSalary s] has Department has DepartmentCode d "
  "AND ALSO THE MAXIMUM s GROUPED BY d AS m",
  same_as("SELECT dept_code, MAX(salary) FROM employee GROUP BY dept_code")),
 ("GDsCount  THE DISTINCT COUNT OF ... GROUPED BY",
  "LIST d, c FROM Employee [has EmployeeGender g] has Department has DepartmentCode d "
  "AND ALSO THE DISTINCT COUNT OF g GROUPED BY d AS c",
  same_as("SELECT dept_code, COUNT(DISTINCT gender) FROM employee GROUP BY dept_code")),
 ("group accounting  <variable> IN <descriptor>",
  "LIST d, t FROM Employee has Department has DepartmentCode d "
  "AND ALSO THE SUM OF s IN Employee has EmployeeSalary s GROUPED BY d AS t",
  sql_has("GROUP BY")),
 ("AS binds a computed descriptor so it can be projected",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c", sql_has("AS \"c\"")),

 # -- aggregate locality (Malloy's name for it; ORM's uniqueness constraints decide it) ----
 # Joining the employees repeats each department's budget, so SUM over that join is the
 # department's budget times its headcount. The refusal is in test_errors.py; here is what
 # the language offers instead, and that the forms which cannot be wrong are left alone.
 ("locality  the bracket is the fix: a semijoin cannot multiply",
  "LIST d, t FROM Department has DepartmentCode d AND ALSO has DepartmentBudget b "
  "AND ALSO [is of Employee] AND ALSO THE SUM OF b GROUPED BY d AS t",
  same_as("SELECT dept_code, budget FROM department d WHERE budget IS NOT NULL "
          "AND EXISTS (SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code)")),
 ("locality  MAXIMUM is unchanged by repetition, so it is not refused",
  "LIST d, m FROM Department has DepartmentCode d AND ALSO has DepartmentBudget b "
  "AND ALSO is of Employee e AND ALSO THE MAXIMUM b GROUPED BY d AS m",
  same_as("SELECT dept_code, budget FROM department d WHERE budget IS NOT NULL "
          "AND EXISTS (SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code)")),
 ("locality  a DISTINCT aggregate says the repetition was meant to be dropped",
  "LIST d, c FROM Department has DepartmentCode d AND ALSO has DepartmentBudget b "
  "AND ALSO is of Employee e AND ALSO THE DISTINCT COUNT OF b GROUPED BY d AS c",
  same_as("SELECT dept_code, 1 FROM department d WHERE budget IS NOT NULL "
          "AND EXISTS (SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code)")),
 ("locality  aggregating over the fan-out itself is what it is for",
  "LIST d, c FROM Department has DepartmentCode d AND ALSO is of Employee e "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c",
  same_as("SELECT dept_code, COUNT(*) FROM employee WHERE dept_code IS NOT NULL "
          "GROUP BY dept_code")),

 # -- section 6.3 scalar expressions, and B.5's scalar-expression LIST ----------
 ("scalar  a / b in a projection",
  "LIST n, s / 12 FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  same_as("SELECT emp_name, salary / 12.0 FROM employee WHERE salary IS NOT NULL")),
 # An integer literal binds as an integer. These references once read `1000.0 * 2.0`, to match
 # a coercion that made every literal a float -- visible only when a literal is projected,
 # where `if(g = 'F', 1, 0)` came back as 1.0 and 0.0.
 ("scalar  precedence: * binds tighter than +",
  "LIST s + 1000 * 2 FROM Employee has EmployeeSalary s",
  same_as("SELECT salary + 1000 * 2 FROM employee WHERE salary IS NOT NULL")),
 ("scalar  parentheses override precedence",
  "LIST (s + 1000) * 2 FROM Employee has EmployeeSalary s",
  same_as("SELECT (salary + 1000) * 2 FROM employee WHERE salary IS NOT NULL")),
 ("scalar  unary minus",
  "LIST -s FROM Employee has EmployeeSalary s",
  same_as("SELECT -salary FROM employee WHERE salary IS NOT NULL")),
 ("scalar  arithmetic in a comparison (both sides)",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s / 12 > 10000",
  same_as("SELECT emp_name FROM employee WHERE salary / 12.0 > 10000")),
 ("scalar  a percentage, the shape BIRD's evidence notes define",
  "LIST n, s * 100 / 200000 FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  same_as("SELECT emp_name, salary * 100.0 / 200000.0 FROM employee "
          "WHERE salary IS NOT NULL")),
 ("function call from the model's function table",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE abs(s) > 100000",
  same_as("SELECT emp_name FROM employee WHERE abs(salary) > 100000")),
 ("a function the model does not declare is refused",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE bogus(s) > 1", refuses("no function")),
 ("a variable may be named `a` -- an article only precedes a type",
  "LIST n, a FROM Employee has EmployeeName n AND ALSO has EmployeeSalary a",
  same_as("SELECT emp_name, salary FROM employee WHERE salary IS NOT NULL")),
 ("and an article still reads as one before a type",
  "LIST n FROM each Employee has a EmployeeName n",
  same_as("SELECT emp_name FROM employee")),
 ("aggregate over a filtered path, WHERE binding inward",
  "THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 100000",
  same_as("SELECT COUNT(*) FROM employee WHERE salary > 100000")),
 ("aggregate in a comparison",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s > THE AVERAGE Employee has EmployeeSalary",
  same_as("SELECT emp_name FROM employee WHERE salary > (SELECT AVG(salary) FROM employee)")),
 ("correlated aggregate (report section 6.4's own example)",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "AND ALSO has Department d WHERE s > THE AVERAGE Employee [has Department: !d] "
  "has EmployeeSalary",
  same_as("SELECT e.emp_name FROM employee e WHERE e.salary > "
          "(SELECT AVG(x.salary) FROM employee x WHERE x.dept_code = e.dept_code)")),

 # -- counting an instance identified by more than one column -------------------
 ("COUNT over a composite identity is COUNT(*), not an error",
  "THE COUNT OF Assignment",
  same_as("SELECT COUNT(*) FROM assignment")),
 ("COUNT over a composite identity, filtered",
  "THE COUNT OF Assignment has Project has ProjectCode: 'APOLLO'",
  same_as("SELECT COUNT(*) FROM assignment WHERE proj_code = 'APOLLO'")),
 ("a DISTINCT count of one says so rather than emitting nonsense",
  "THE DISTINCT COUNT OF Assignment", refuses("identified by several")),
 ("SUM still needs a single column",
  "THE SUM OF Assignment", refuses("single column")),

 # -- parameters bind in text order, whatever order the clauses were built in ----
 ("a literal in SELECT binds before one in WHERE",
  "LIST n, s * 100 FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE s > 100000",
  same_as("SELECT emp_name, salary * 100 FROM employee WHERE salary > 100000")),
 ("a literal in HAVING binds after one in WHERE",
  "LIST d, c FROM Employee e [has EmployeeGender: 'F'] has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c WHERE c > 1",
  same_as("SELECT dept_code, COUNT(*) FROM employee WHERE gender = 'F' "
          "GROUP BY dept_code HAVING COUNT(*) > 1")),
 # -- three defects the BIRD re-measurement turned up -------------------------------
 # An ungrouped aggregate over an expression built from the enclosing block's variables has
 # no path of its own to walk, so its block came out empty and the emitter wrote a subquery
 # with no FROM -- aggregating the enclosing row. It now ranges over a copy of the enclosing
 # bag, conditions included, which is what "the average of" means without a GROUPED BY.
 ("an aggregate over an expression gets a bag of its own",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "AND ALSO THE AVERAGE (s * 2) AS m WHERE s * 2 > m",
  same_as("SELECT emp_name FROM employee WHERE salary * 2 > "
          "(SELECT AVG(salary * 2) FROM employee WHERE salary IS NOT NULL)")),
 ("that bag keeps the enclosing block's filters",
  "LIST n FROM Employee [has EmployeeGender: 'F'] has EmployeeName n "
  "AND ALSO has EmployeeSalary s AND ALSO THE AVERAGE (s) AS m WHERE s > m",
  same_as("SELECT emp_name FROM employee WHERE gender = 'F' AND salary > "
          "(SELECT AVG(salary) FROM employee WHERE gender = 'F' AND salary IS NOT NULL)")),

 # Two paths reaching the same fact from the same row joined its table twice, under two
 # aliases. Sound but wasteful, and a fan-out risk if the target were not reached by its own
 # identifying columns -- which is exactly the test that guards the reuse.
 ("one join, not two, for two attributes of the same entity",
  "LIST b, dn FROM Employee has Department has DepartmentBudget b "
  "AND ALSO has Department has DepartmentName dn",
  sql_has_count('JOIN "department"', 1)),
 ("and it still returns what two joins returned",
  "LIST b, dn FROM Employee has Department has DepartmentBudget b "
  "AND ALSO has Department has DepartmentName dn",
  same_as("SELECT d.budget, d.dept_name FROM employee e JOIN department d "
          "ON d.dept_code = e.dept_code WHERE d.budget IS NOT NULL")),

 # A node nothing joins to is a second independent range over its concept, which the emitter
 # renders as a cartesian product. model/validate.py always rejected it; the compiler emitted
 # SQL for it anyway, so the count came back multiplied and silent.
 ("a node joined to nothing is refused, not multiplied",
  "LIST d, c FROM Employee has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF Project GROUPED BY d AS c",
  refuses("joined to nothing")),
 # ... but restating the head's own type is Fr: the same employees, not a second range
 ("restating the head in a grouped aggregate is the correlated form",
  "LIST d, c FROM Employee has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF Employee GROUPED BY d AS c",
  same_as("SELECT dept_code, COUNT(*) FROM employee WHERE dept_code IS NOT NULL "
          "GROUP BY dept_code")),
 ("the correlated form of the same query is fine",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c",
  same_as("SELECT dept_code, COUNT(*) FROM employee GROUP BY dept_code")),
 ("a lone node is still the whole point of a bare aggregate",
  "THE COUNT OF Employee", rows(1)),

 # A plain column condition AND-ed with an aggregate one must not be dragged into HAVING:
 # SQL does not reject a bare column there, it evaluates it against an arbitrary row of the
 # group, so the query returns wrong rows with no error. Found on BIRD Q25.
 ("a conjunction splits across WHERE and HAVING",
  "LIST d, c FROM Employee e [has EmployeeGender g] has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c WHERE c > 1 AND g = 'F'",
  same_as("SELECT dept_code, COUNT(*) FROM employee WHERE gender = 'F' "
          "GROUP BY dept_code HAVING COUNT(*) > 1")),
 ("literals in SELECT, WHERE and HAVING together",
  "LIST d, c * 2 FROM Employee e [has EmployeeGender: 'F'] has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c WHERE c > 1",
  same_as("SELECT dept_code, COUNT(*) * 2 FROM employee WHERE gender = 'F' "
          "GROUP BY dept_code HAVING COUNT(*) > 1")),
 ("a correlated aggregate's literals stay with their own subquery",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "AND ALSO has Department d WHERE s > THE AVERAGE Employee [has Department: !d] "
  "has EmployeeSalary AND s < 200000",
  same_as("SELECT e.emp_name FROM employee e WHERE e.salary > "
          "(SELECT AVG(x.salary) FROM employee x WHERE x.dept_code = e.dept_code) "
          "AND e.salary < 200000")),
 ("HAVING over a grouped aggregate compiles at all",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c WHERE c > 1", sql_has("HAVING")),

 # -- section 6.8 denotations ---------------------------------------------------
 ("denotation  Type: value",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department: 'ENG'",
  same_as("SELECT emp_name FROM employee WHERE dept_code = 'ENG'")),
 ("denotation  Type: !x (correlates a sub-query to an outer instance)",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s AND ALSO "
  "has Department d WHERE s > THE AVERAGE Employee [has Department: !d] has EmployeeSalary",
  same_as("SELECT emp_name FROM employee e WHERE salary > "
          "(SELECT AVG(salary) FROM employee x WHERE x.dept_code = e.dept_code)")),
 ("denotation on a value type",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeGender: 'X'",
  same_as("SELECT emp_name FROM employee WHERE gender = 'X'")),

 # -- section B.2 role reference, and the ring it exists for --------------------
 # A ring fact type: both roles played by Employee. Reverse engineering read the column
 # `manager_nr` for a verb (rule 10): `{0} has manager- {1}`, with the inverse `{0} is
 # manager of {1}` from the other end. Naming the roles walks it too.
 ("a ring's reading: the hyphen-bound adjective is part of the verb part",
  "LIST n, m FROM Employee [has EmployeeName n] has manager Employee has EmployeeNr m",
  same_as("SELECT emp_name, manager_nr FROM employee WHERE manager_nr IS NOT NULL")),
 ("a ring's inverse reading, from the other end",
  "LIST n, s FROM Employee [has EmployeeName n] is manager of Employee has EmployeeNr s",
  same_as("SELECT m.emp_name, e.emp_nr FROM employee e "
          "JOIN employee m ON m.emp_nr = e.manager_nr")),
 ("the adjective is not a type reference: `has Manager` is the subtype, and no fact type "
  "reads that way -- the message names the verb parts that do",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Manager",
  ambiguous("Employee reaches Manager by 'has manager', 'is manager of'")),
 ("role reference  enter and exit a ring by name",
  "LIST n, m FROM Employee [has EmployeeName n] has EmployeeHasManagerEmployee "
  "has EmployeeHasManagerManager has EmployeeNr m",
  same_as("SELECT emp_name, manager_nr FROM employee WHERE manager_nr IS NOT NULL")),
 ("role reference  the other direction",
  "LIST n, s FROM Employee [has EmployeeName n] has EmployeeHasManagerManager "
  "has EmployeeHasManagerEmployee has EmployeeNr s",
  same_as("SELECT m.emp_name, e.emp_nr FROM employee e "
          "JOIN employee m ON m.emp_nr = e.manager_nr")),
 ("a ring named by its type alone: `has Employee` is no reading, and the message says "
  "which are",
  "LIST n FROM Employee [has EmployeeName n] has Employee has EmployeeNr",
  ambiguous("Employee reaches Employee by 'has manager', 'is manager of'")),

 # -- objectification and subtyping (model/model.md G1, rule 7) ------------------
 ("path through an objectified fact type",
  "LIST n, p FROM Employee [has EmployeeName n] has Assignment has Project has ProjectCode p",
  same_as("SELECT e.emp_name, a.proj_code FROM employee e "
          "JOIN assignment a ON a.emp_nr = e.emp_nr")),
 ("fact-instance node carries its own attribute",
  "LIST n, h FROM Employee [has EmployeeName n] has Assignment has AssignmentHours h",
  same_as("SELECT e.emp_name, a.hours FROM employee e JOIN assignment a ON a.emp_nr = e.emp_nr")),
 ("subtype inherits the supertype's roles",
  "LIST c, n FROM Manager [has ManagerCarSpace c] has EmployeeName n",
  same_as("SELECT m.car_space, e.emp_name FROM manager m JOIN employee e ON e.emp_nr = m.emp_nr")),

 # -- section 6.13 ordering, and fact existence (binding-sql92 section 6.1a) ----
 # Case is ConQuer's to define too. SQLite's LIKE ignores ASCII case and PostgreSQL's does
 # not, so the same query answered differently per backend; and the reference interpreter
 # implemented starts_with/ends_with/contains with Python's case-sensitive methods, so the
 # compiler and its own oracle disagreed wherever case differed. All four are insensitive
 # everywhere now, ILIKE on the dialects that need it, and `=` remains the exact test
 # (finding 130).
 ("STRING  like ignores case",
  "THE COUNT OF Employee [has EmployeeName n] WHERE like(n, 'ADA%')",
  same_as("SELECT COUNT(*) FROM employee WHERE emp_name LIKE 'ADA%'")),
 ("STRING  and so does starts_with",
  "THE COUNT OF Employee [has EmployeeName n] WHERE starts_with(n, 'ada')",
  same_as("SELECT COUNT(*) FROM employee WHERE emp_name LIKE 'ada' || '%'")),
 ("STRING  and contains",
  "THE COUNT OF Employee [has EmployeeName n] WHERE contains(n, 'LOVELACE')",
  same_as("SELECT COUNT(*) FROM employee WHERE emp_name LIKE '%' || 'LOVELACE' || '%'")),
 ("STRING  but = is still exact",
  "THE COUNT OF Employee [has EmployeeName n] WHERE n = 'ada lovelace'",
  same_as("SELECT COUNT(*) FROM employee WHERE emp_name = 'ada lovelace'")),

 # Where an absent value sorts is ConQuer's to say, not the backend's. A bare ORDER BY means
 # nulls first ascending in SQLite and nulls last ascending in PostgreSQL, so the same query
 # returned different rows on different databases -- silently, and only when `OPTIONALLY` let
 # a null into the key at all. Pinned to SQLite's order, which every recorded answer was
 # written against and which `reference._sortkey` computes (finding 129).
 ("ORDER  an ascending sort says where nulls go",
  "LIST n, s FROM Employee has EmployeeName n AND ALSO OPTIONALLY has EmployeeSalary s "
  "ORDERED WITH s ASCENDING",
  sql_has("ASC NULLS FIRST")),
 ("ORDER  and a descending one says the opposite",
  "LIST n, s FROM Employee has EmployeeName n AND ALSO OPTIONALLY has EmployeeSalary s "
  "ORDERED WITH s DESCENDING",
  sql_has("DESC NULLS LAST")),

 # Ω is the one operator whose whole effect is row order, so these use `ordered_as`:
 # `same_as` sorts both sides and would pass no matter what the ORDER BY said.
 ("ORDER  ORDERED WITH ... DESCENDING",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING",
  ordered_as("SELECT salary FROM employee WHERE salary IS NOT NULL ORDER BY salary DESC")),
 ("ORDER  direction first, the [P59] spelling",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH DESCENDING s",
  ordered_as("SELECT salary FROM employee WHERE salary IS NOT NULL ORDER BY salary DESC")),
 ("ORDER  ORDERED sorts on the head, [P57]",
  "LIST n FROM Employee has EmployeeName n ORDERED",
  ordered_as("SELECT emp_name FROM employee ORDER BY emp_nr ASC")),
 ("ORDER  HEAD names the head of the path",
  "Employee has EmployeeName ORDERED WITH HEAD DESCENDING",
  ordered_as("SELECT emp_nr, emp_name FROM employee ORDER BY emp_nr DESC")),
 # The one that catches the old bug: TAIL used to sort by the head, silently.
 ("ORDER  TAIL names the tail, not the head",
  "Employee has EmployeeName ORDERED WITH TAIL DESCENDING",
  ordered_as("SELECT emp_nr, emp_name FROM employee ORDER BY emp_name DESC")),
 ("ORDER  a bound variable need not be listed ([P59] binds v_i in I, not in the result)",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING",
  ordered_as("SELECT emp_name FROM employee WHERE salary IS NOT NULL ORDER BY salary DESC")),
 # -- WITH TIES: the cut keeps everything that ranks within n, not n rows -----------------
 # Two genders have one employee each, so the second place is shared. `THE FIRST 2` has to
 # pick one of them and the database picks; `WITH TIES` keeps both. Finding 79 measured
 # making that the default at 0 answers fixed and 16 broken, so it is spelled, not assumed.
 ("ORDER  THE FIRST n cuts a tie, keeping n rows",
  "LIST g, c FROM Employee e has EmployeeGender g AND ALSO THE COUNT OF e GROUPED BY g AS c "
  "ORDERED WITH c DESCENDING THE FIRST 2",
  rows(2)),
 ("ORDER  THE FIRST n WITH TIES keeps the whole tie",
  "LIST g, c FROM Employee e has EmployeeGender g AND ALSO THE COUNT OF e GROUPED BY g AS c "
  "ORDERED WITH c DESCENDING THE FIRST 2 WITH TIES",
  same_as("SELECT gender, COUNT(emp_nr) FROM employee WHERE gender IS NOT NULL "
          "GROUP BY gender")),
 ("ORDER  WITH TIES at the bottom of the order keeps both",
  "LIST g, c FROM Employee e has EmployeeGender g AND ALSO THE COUNT OF e GROUPED BY g AS c "
  "ORDERED WITH c ASCENDING THE FIRST 1 WITH TIES",
  same_as("SELECT gender, COUNT(emp_nr) FROM employee WHERE gender IS NOT NULL "
          "GROUP BY gender HAVING COUNT(emp_nr) = 1")),
 # RANK, not ROW_NUMBER: the difference between the two IS the feature.
 ("ORDER  WITH TIES ranks rather than numbers",
  "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "ORDERED WITH s DESCENDING THE FIRST 2 WITH TIES",
  sql_has("RANK() OVER")),
 ("ORDER  a second sort key breaks the tie, so WITH TIES keeps only n",
  "LIST g, c FROM Employee e has EmployeeGender g AND ALSO THE COUNT OF e GROUPED BY g AS c "
  "ORDERED WITH c DESCENDING, g ASCENDING THE FIRST 2 WITH TIES",
  rows(2)),
 ("ORDER  WITH TIES needs something to tie on",
  "LIST n FROM Employee has EmployeeName n THE FIRST 2 WITH TIES",
  refuses("needs something to tie on")),
 ("ORDER  WITH TIES will not combine with AFTER",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 2 AFTER 1 "
  "WITH TIES",
  refuses("has no meaning")),
 ("ORDER  WITH TIES is for the rows a LIST returns, not for a set operation",
  "(LIST n FROM Employee has EmployeeName n) UNITED WITH "
  "(LIST n FROM Department has DepartmentName n) ORDERED WITH n ASCENDING THE FIRST 2 "
  "WITH TIES",
  refuses("WITH TIES applies to the rows a LIST returns")),

 # -- a clause that used to be accepted and dropped on the floor --------------------------
 # The primer claimed `THE LIST OF` "carries its own ORDERED WITH ... THE FIRST n, which is
 # top-n-per-group". It carries them ungrouped, and the grouped branch of lower_aggregate
 # never read either one: the parser built them, nothing consumed them, and the answer came
 # back gathering everything. Three assertions, because the fix has three halves -- the form
 # that works, the form that is refused, and the spelling the refusal points at.
 ("ORDER  an ungrouped gather carries its own ordering and cut",
  "LIST l FROM THE LIST OF s IN Employee has EmployeeSalary s "
  "ORDERED WITH s DESCENDING THE FIRST 2 AS l",
  same_as("SELECT '[' || group_concat(salary) || ']' FROM "
          "(SELECT salary FROM employee WHERE salary IS NOT NULL "
          " ORDER BY salary DESC LIMIT 2)")),
 ("ORDER  a grouped gather refuses them rather than ignoring them",
  "LIST d, l FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
  "AND ALSO THE LIST OF s ORDERED WITH s DESCENDING THE FIRST 1 GROUPED BY d AS l",
  refuses("nothing left to order or cut")),
 ("ORDER  and the refusal names the spelling that works",
  "LIST d, s FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
  "ORDERED WITH s DESCENDING THE FIRST 1 PER d",
  same_as("SELECT dept_code, MAX(salary) FROM employee WHERE salary IS NOT NULL "
          "GROUP BY dept_code")),
 ("ORDER  a grouped aggregate with a bare ordering is refused too",
  "LIST d, l FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
  "AND ALSO THE LIST OF s ORDERED WITH s DESCENDING GROUPED BY d AS l",
  refuses("nothing left to order or cut")),

 # -- precedence: SQL's, and silent either way -------------------------------------------
 # A blind writer lost a question to this. `/` binds tighter than `=`, so the divisor lands
 # in the comparison; both readings compile and run, so only the number says which was meant.
 ("ORDER  an operator after WHERE binds to the comparison",
  "LIST c FROM THE COUNT OF Employee [has EmployeeHired d] WHERE year(d) = 2019 / 12 AS c",
  same_as("SELECT COUNT(*) FROM employee WHERE CAST(strftime('%Y', hired) AS INTEGER) "
          "= 2019.0 / 12")),
 ("ORDER  and parentheses divide the count instead",
  "LIST c FROM (THE COUNT OF Employee [has EmployeeHired d] WHERE year(d) = 2019) / 12 AS c",
  same_as("SELECT CAST(COUNT(*) AS REAL) / 12 FROM employee "
          "WHERE CAST(strftime('%Y', hired) AS INTEGER) = 2019")),

 # -- alias reuse across a reference to a unique column that is not the key --------------
 # Reuse was gated on the join standing on the target's *identifier*, so a foreign key aimed
 # at any other unique column -- 32 of BIRD's 105 declared keys -- emitted one join per value
 # read. The fixture's references all point at identifiers, so the gate is tested here on the
 # shape it always allowed; `test_mapping.py` carries the non-identifier case.
 ("JOIN   two values off one referenced entity share a join",
  "LIST c, b FROM Employee has Department has DepartmentCode c AND ALSO has Department "
  "has DepartmentBudget b",
  sql_has_count('JOIN "department"', 1)),
 ("JOIN   and a genuinely second range still gets its own",
  "LIST a, b, g FROM Department has DepartmentCode a AND ALSO is of Employee has EmployeeName b "
  "AND ALSO is of Employee has EmployeeGender g",
  sql_has_count('JOIN "employee"', 2)),

 # -- the library gaps a survey of the gold found ---------------------------------------
 # 660 LiveSQLBench gold statements name 294 distinct functions. `coalesce` is in 627 of
 # them -- more than any function in the corpus, ours or theirs -- and we had none of these
 # (finding 148). All six are portable across all three dialects.
 ("CALL   coalesce, in 627 of 660 gold statements and absent here until now",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO coalesce(s, 0) AS x",
  same_as("SELECT COALESCE(salary, 0) FROM employee WHERE salary IS NOT NULL")),
 ("CALL   nullif",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO nullif(s, 0) AS x",
  same_as("SELECT NULLIF(salary, 0) FROM employee WHERE salary IS NOT NULL")),
 ("CALL   trim",
  "LIST x FROM Employee has EmployeeName n AND ALSO trim(n) AS x",
  same_as("SELECT TRIM(emp_name) FROM employee")),
 # The engine's own LOG10, not LN(x)/LN(10): the ratio differs from it in the fifteenth
 # digit, and a figure inside a JSON column is compared as text, where nothing rounds
 # (LiveSQLBench news_2, finding 157).
 ("CALL   log10, which a writer had to spell as ln(x)/ln(10)",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO log10(s) AS x",
  same_as("SELECT LOG10(salary) FROM employee WHERE salary IS NOT NULL")),
 ("CALL   greatest and least take two values, not a bag",
  "LIST x, y FROM Employee has EmployeeSalary s AND ALSO greatest(s, 100000) AS x "
  "AND ALSO least(s, 100000) AS y",
  same_as("SELECT MAX(salary, 100000), MIN(salary, 100000) FROM employee "
          "WHERE salary IS NOT NULL")),

 # -- SQLite has no STDDEV, but it has the moments it is made of -----------------------
 # Declared absent until a LiveSQLBench writer needed one and spelled
 # `sqrt((avg(a*a) - avg(a)^2) * n/(n-1))` by hand. A second writer, working blind on the
 # same tier, wrote the identical thing. A language that makes two people derive the sample
 # standard deviation is worse than the SQL it is being compared against, so the dialect now
 # spells it: one pass, one expression, exact against an independent computation to nine
 # places. The median took longer: an ordered-set aggregate has no closed form over a
 # column, but it has one over a bag, and the bag paths below spell it (finding 158).
 ("CALL   the standard deviation, which SQLite has no aggregate for",
  "LIST v FROM THE STANDARD DEVIATION OF EmployeeSalary AS v",
  same_as("SELECT (SELECT SQRT((SUM(CAST(salary AS REAL) * salary) "
          "- SUM(CAST(salary AS REAL)) * SUM(salary) / COUNT(salary)) / (COUNT(salary) - 1)) "
          "FROM employee WHERE salary IS NOT NULL)")),
 ("CALL   and the variance beside it",
  "LIST v FROM THE VARIANCE OF EmployeeSalary AS v",
  same_as("SELECT (SELECT (SUM(CAST(salary AS REAL) * salary) "
          "- SUM(CAST(salary AS REAL)) * SUM(salary) / COUNT(salary)) / (COUNT(salary) - 1) "
          "FROM employee WHERE salary IS NOT NULL)")),
 # OPTIONALLY before a bound head. B.2 puts it before the verb and `e OPTIONALLY has X`
 # always parsed; three writers over two rounds wrote `OPTIONALLY e has X`, where English
 # puts it, and were told OPTIONALLY was neither a type nor a variable.
 ("PATH   OPTIONALLY before a bound head modifies the step after it",
  "LIST n, m FROM Employee e has EmployeeName n AND ALSO OPTIONALLY e has manager Employee "
  "OPTIONALLY has EmployeeName m",
  same_as("SELECT e.emp_name, m.emp_name FROM employee e LEFT JOIN employee m "
          "ON m.emp_nr = e.manager_nr")),
 # The IN form took only a bound name as the aggregated value; an expression over what the
 # path binds is read with forward references, as a projection is.
 ("AGG    an expression as the aggregated value in the IN form",
  "THE SUM OF round(s / 1000, 0) IN Employee has EmployeeSalary s",
  same_as("SELECT SUM(ROUND(salary / 1000.0, 0)) FROM employee WHERE salary IS NOT NULL")),
 ("AGG    and gathered, in the order asked for",
  "LIST l FROM THE LIST OF (s * 2) IN Employee has EmployeeSalary s "
  "ORDERED WITH s DESCENDING THE FIRST 2 AS l",
  same_as("SELECT json_group_array(v) FROM (SELECT salary * 2 AS v FROM employee "
          "WHERE salary IS NOT NULL ORDER BY salary DESC LIMIT 2)")),
 # An ordered LIST of a value the enclosing block bound ranges over a copy of that block,
 # and its sort key pointed at the original: "no such column: employ1.salary" from inside
 # a derived table that had no employ1. Grounded with the argument now.
 ("AGG    an ordered list of an outer-bound value sorts inside its own bag",
  "LIST n, l FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "AND ALSO THE LIST OF s ORDERED WITH s DESCENDING THE FIRST 2 AS l",
  same_as("SELECT emp_name, (SELECT json_group_array(v) FROM (SELECT salary AS v FROM "
          "employee WHERE salary IS NOT NULL ORDER BY salary DESC LIMIT 2)) FROM employee "
          "WHERE salary IS NOT NULL")),
 # The two aggregates that take a second operand, and the two spellings each has: grouped
 # in the enclosing query, or over a path of its own with IN (finding 158). The key of an
 # OBJECT is a value of the bag's rows, so in the IN form it is named before the path that
 # binds it, like a projection. `SEPARATED BY` keeps THE LIST OF's own ORDERED WITH.
 ("AGG    an object keyed by a value, grouped",
  "LIST d, o FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n "
  "AND ALSO has EmployeeSalary s AND ALSO THE OBJECT OF s BY n GROUPED BY d AS o",
  same_as("SELECT dept_code, json_group_object(emp_name, salary) FROM employee "
          "WHERE salary IS NOT NULL GROUP BY dept_code")),
 ("AGG    and over a path of its own",
  "THE OBJECT OF s BY n IN Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  same_as("SELECT json_group_object(emp_name, salary) FROM employee WHERE salary IS NOT NULL")),
 ("AGG    a list joined as text, grouped",
  "LIST d, l FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n "
  "AND ALSO THE LIST OF n SEPARATED BY ', ' GROUPED BY d AS l",
  same_as("SELECT dept_code, group_concat(emp_name, ', ') FROM employee GROUP BY dept_code")),
 # `GROUP_CONCAT(DISTINCT x, sep)` is refused by SQLite ("DISTINCT aggregates must have
 # exactly one argument"), so a distinct join takes its distinct in a derived table --
 # regrouped into a bag when grouped, as a median is. A news writer had to drop DISTINCT.
 ("AGG    a distinct list joined as text, grouped",
  "LIST d, l FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeGender g "
  "AND ALSO THE DISTINCT LIST OF g SEPARATED BY ', ' GROUPED BY d AS l",
  same_as("SELECT dept_code, (SELECT group_concat(v, ', ') FROM (SELECT DISTINCT gender AS v "
          "FROM employee e2 WHERE e2.dept_code = e.dept_code AND gender IS NOT NULL)) "
          "FROM employee e GROUP BY dept_code")),
 ("AGG    and over a path of its own",
  "LIST l FROM THE DISTINCT LIST OF g SEPARATED BY ', ' IN Employee has EmployeeGender g AS l",
  same_as("SELECT group_concat(v, ', ') FROM (SELECT DISTINCT gender AS v FROM employee "
          "WHERE gender IS NOT NULL)")),
 # The ordered bag path was its own copy of the bag machinery and never applied DISTINCT:
 # `THE DISTINCT LIST OF g ... THE FIRST 2` gathered ["F","F"]. One bag path now, and the
 # distinct is taken in the derived table, before the cut, which is where SQL applies it.
 ("AGG    a distinct list that is ordered and cut is distinct first",
  "LIST l FROM THE DISTINCT LIST OF g IN Employee has EmployeeGender g "
  "ORDERED WITH g ASCENDING THE FIRST 2 AS l",
  same_as("SELECT json_group_array(v) FROM (SELECT DISTINCT gender AS v FROM employee "
          "WHERE gender IS NOT NULL ORDER BY gender ASC LIMIT 2)")),
 ("AGG    and over a path of its own, in the order asked for",
  "LIST l FROM THE LIST OF n SEPARATED BY ' | ' IN Employee has EmployeeName n "
  "ORDERED WITH n DESCENDING AS l",
  same_as("SELECT group_concat(emp_name, ' | ') FROM (SELECT emp_name FROM employee "
          "ORDER BY emp_name DESC)")),
 ("CALL   and grouped, where the aggregate is rendered in the SELECT list instead",
  "LIST g, v FROM Employee has EmployeeGender g AND ALSO has EmployeeSalary s "
  "AND ALSO THE STANDARD DEVIATION OF s GROUPED BY g AS v",
  same_as("SELECT gender, SQRT((SUM(CAST(salary AS REAL) * salary) "
          "- SUM(CAST(salary AS REAL)) * SUM(salary) / COUNT(salary)) / (COUNT(salary) - 1)) "
          "FROM employee WHERE gender IS NOT NULL AND salary IS NOT NULL GROUP BY gender")),
 # The template names its argument six times, so whatever rendering the argument bound has to
 # be bound six times too. Written the obvious way this failed with "the current statement
 # uses 6 bindings and there is 1 supplied" -- loudly, but it failed.
 ("CALL   a standard deviation over a bound expression binds its parameters once per use",
  "LIST g, v FROM Employee has EmployeeGender g AND ALSO has EmployeeSalary s "
  "AND ALSO (s * 2) AS x AND ALSO THE STANDARD DEVIATION OF x GROUPED BY g AS v",
  same_as("SELECT gender, SQRT((SUM(CAST(salary * 2 AS REAL) * (salary * 2)) "
          "- SUM(CAST(salary * 2 AS REAL)) * SUM(salary * 2) / COUNT(salary * 2)) "
          "/ (COUNT(salary * 2) - 1)) FROM employee "
          "WHERE gender IS NOT NULL AND salary IS NOT NULL GROUP BY gender")),

 # A bag is a derived table, and three sites built the outer aggregate from the function's
 # *name* rather than the dialect's spelling, so a standard deviation over a bag emitted
 # `STDDEV("v")` -- which SQLite does not have. The grouped-bag site is the reachable one;
 # found on LiveSQLBench, where a writer met it through a grouped DEFINE.
 ("CALL   a standard deviation over a bag is spelled the dialect's way there too",
  "THE STANDARD DEVIATION OF c IN (Department d AND ALSO THE COUNT OF Employee "
  "[has Department d] GROUPED BY d AS c)",
  same_as("SELECT SQRT((SUM(CAST(v AS REAL) * v) - SUM(CAST(v AS REAL)) * SUM(v) / COUNT(v)) "
          "/ (COUNT(v) - 1)) FROM (SELECT COUNT(*) AS v FROM employee "
          "WHERE dept_code IS NOT NULL GROUP BY dept_code)")),
 ("CALL   ...and not a bare STDDEV, which SQLite has no function for",
  "THE STANDARD DEVIATION OF c IN (Department d AND ALSO THE COUNT OF Employee "
  "[has Department d] GROUPED BY d AS c)",
  sql_has("SQRT")),
 # DISTINCT has nowhere to go in a template -- `SUM(DISTINCT x * x)` is not the distinct sum
 # of squares -- so where there is a derived table the distinct is taken there, and where
 # there is not the combination is refused rather than emitted as STDDEV(DISTINCT x).
 ("CALL   a distinct standard deviation over a bag takes the distinct in the bag",
  "THE STANDARD DEVIATION OF c IN (DISTINCT Department d AND ALSO THE COUNT OF Employee "
  "[has Department d] GROUPED BY d AS c)",
  sql_has("SELECT DISTINCT")),
 ("CALL   and a distinct standard deviation with no bag is refused, not mis-spelled",
  "THE STANDARD DEVIATION OF DISTINCT EmployeeSalary",
  refuses("no distinct stddev")),

 # -- a template that names its argument more than once ---------------------------------
 # Rendering an argument sinks its parameters once. A template that emits it several times
 # therefore left the statement short of bindings -- loudly, but wrong, and in five separate
 # functions found on one LiveSQLBench run: jsonPath, the SQLite standard deviation,
 # days_between against a literal, rtrim's two-argument form, and greatest with three. The
 # first two were fixed at their call sites, which was the wrong altitude; `Emitter.call`
 # now binds each argument once per placeholder, in the order the template places them.
 ("CALL   days_between against a literal binds the lenient-date CASE once per use",
  "LIST n, d FROM Employee has EmployeeName n AND ALSO has EmployeeHired h "
  "AND ALSO days_between('2020-01-01', h) AS d",
  sql_has("julianday")),
 # `rtrim` is declared one-argument in every dialect here. The two-argument form a writer
 # reached for used to render RTRIM(x) and bind two -- "it emits one argument but binds
 # two". It now says so instead. The two-argument form itself is a gap, not a defect.
 ("CALL   rtrim's one-argument form is what the dialect declares",
  "LIST x FROM Employee has EmployeeName n AND ALSO rtrim(n) AS x",
  same_as("SELECT RTRIM(emp_name) FROM employee")),
 ("CALL   and the two-argument form is refused rather than mis-bound",
  "LIST x FROM Employee has EmployeeName n AND ALSO rtrim(n, 'n') AS x",
  refuses("takes 1 argument")),
 # And an argument the template has nowhere to put is refused rather than dropped. Once the
 # binding follows the placeholders, `greatest(a, b, c)` against SQLite's two-argument MAX
 # would have rendered MAX(a, b) and bound two -- the same wrong answer, quietly.
 ("CALL   more arguments than the dialect's template places is refused",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO greatest(s, 1, 2) AS x",
  refuses("takes 2 argument")),

 # -- a template-spelled aggregate in a window ------------------------------------------
 # SQLite spells the standard deviation as an expression over SUM and COUNT, and `OVER`
 # cannot hang off an expression: "SQRT() may not be used as a window function". The window
 # form is each of those aggregates windowed individually, which is valid -- so the OVER is
 # distributed rather than the construct refused.
 ("CALL   a standard deviation WITHIN a partition carries the group's figure",
  "LIST g, v FROM Employee has EmployeeGender g AND ALSO has EmployeeSalary s "
  "AND ALSO THE STANDARD DEVIATION OF s WITHIN g AS v",
  sql_has("OVER (PARTITION BY")),

 # -- a function the model declares and the query could not call ------------------------
 # Every model the reverse engineer builds carries `fn.castNumber` and `fn.castInteger`.
 # Neither could be called: the parser casefolds the name and looked up `fn.castnumber`,
 # which is not what the model declares, so it answered "no function in this model" while
 # holding it. The two casts are what turns text like '104 days' into a number, which is
 # most of what a real column needs (found building a LiveSQLBench semantic layer).
 ("CALL   a camel-cased function resolves however it is spelled",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO castNumber(s) AS x",
  same_as("SELECT CAST(salary AS DOUBLE) FROM employee WHERE salary IS NOT NULL")),
 ("CALL   and folded, because names are not case-sensitive",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO CASTNUMBER(s) AS x",
  same_as("SELECT CAST(salary AS DOUBLE) FROM employee WHERE salary IS NOT NULL")),
 ("CALL   castInteger too",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO castInteger(s) AS x",
  same_as("SELECT CAST(salary AS INTEGER) FROM employee WHERE salary IS NOT NULL")),
 ("CALL   a function the model really lacks is still refused",
  "LIST x FROM Employee has EmployeeSalary s AND ALSO arctangent(s) AS x",
  refuses("no function")),

 ("ORDER  a variable named `head` beats the HEAD terminal",
  "LIST head FROM Employee has EmployeeName head ORDERED WITH head DESCENDING",
  ordered_as("SELECT emp_name FROM employee ORDER BY emp_name DESC")),
 ("ORDER  an unknown sort key is refused, not silently swapped",
  "LIST n FROM Employee has EmployeeName n ORDERED WITH typo DESCENDING",
  refuses("neither a variable this query binds")),
 ("ORDER  a sort key with nothing to sort by",
  "LIST n FROM Employee has EmployeeName n ORDERED WITH DESCENDING",
  refuses("expected something to sort by")),

 # -- THE FIRST / THE TOP: a row limit, the one construct with no ConQuer-92 counterpart ----
 # §6.13 defines only Ω, which sorts and no more, and HEAD/TAIL are sort keys rather than a
 # count -- so this is invented, not implemented, and model.md §4.1 says so.
 ("LIMIT  THE FIRST n over an ordering",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 3",
  ordered_as("SELECT salary FROM employee WHERE salary IS NOT NULL "
             "ORDER BY salary DESC LIMIT 3")),
 ("LIMIT  THE TOP n is the same operator",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE TOP 3",
  ordered_as("SELECT salary FROM employee WHERE salary IS NOT NULL "
             "ORDER BY salary DESC LIMIT 3")),
 ("LIMIT  AFTER m skips m rows first",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 2 AFTER 1",
  ordered_as("SELECT salary FROM employee WHERE salary IS NOT NULL "
             "ORDER BY salary DESC LIMIT 2 OFFSET 1")),
 ("LIMIT  ascending picks the other end",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s ASCENDING THE FIRST 1",
  ordered_as("SELECT salary FROM employee WHERE salary IS NOT NULL "
             "ORDER BY salary ASC LIMIT 1")),
 # The argmax shape -- "the department with the most employees" -- is six of the fourteen
 # top-N questions in bench/, and the reason a limit was worth adding at all.
 ("LIMIT  argmax: the group with the largest aggregate",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c ORDERED WITH c DESCENDING THE FIRST 1",
  ordered_as("SELECT dept_code, COUNT(*) c FROM employee GROUP BY dept_code "
             "ORDER BY c DESC LIMIT 1")),
 ("LIMIT  0 keeps nothing",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 0", rows(0)),
 ("LIMIT  a limit larger than the result keeps all of it",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 999",
  ordered_as("SELECT salary FROM employee WHERE salary IS NOT NULL ORDER BY salary DESC")),
 ("LIMIT  without an ordering it still compiles (and --explain calls it a risk)",
  "LIST n FROM Employee has EmployeeName n THE FIRST 2", rows(2)),
 ("LIMIT  the count must be a number",
  "LIST s FROM Employee has EmployeeSalary s THE FIRST many",
  refuses("needs a number")),
 ("LIMIT  a fractional count is refused",
  "LIST s FROM Employee has EmployeeSalary s THE FIRST 2.5",
  refuses("needs a number")),
 ("LIMIT  AFTER needs a number too",
  "LIST s FROM Employee has EmployeeSalary s THE FIRST 2 AFTER",
  refuses("AFTER needs a number")),

 # -- ConQuer 2026: the function library brought up to the target (conquer/conquer-2026.md) --
 # Division is real. SQL-92's integer truncation was the target's rule, not a conceptual one,
 # and it cost BIRD Q282: COUNT / COUNT over integers was 0.
 ("2026  `/` is real division",
  "THE COUNT OF Employee [has EmployeeGender: 'F'] * 100 / THE COUNT OF Employee",
  same_as("SELECT CAST(COUNT(CASE WHEN gender='F' THEN 1 END) * 100 AS REAL) / COUNT(*) "
          "FROM employee")),
 ("2026  `div` is the integer kind",
  "LIST div(s, 1000) FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 1",
  ordered_as("SELECT CAST((salary / 1000) AS INTEGER) FROM employee WHERE salary IS NOT NULL "
             "ORDER BY salary DESC LIMIT 1")),
 # Dates. `year()` used to emit YEAR(), which SQLite does not have -- valid ConQuer, runtime
 # error. sqlTemplate is how a function's meaning and its dialect spelling part company.
 ("2026  year() runs on SQLite",
  "LIST year(h) FROM Employee has EmployeeHired h",
  same_as("SELECT CAST(strftime('%Y', hired) AS INTEGER) FROM employee")),
 ("2026  month() and day() too",
  "LIST month(h), day(h) FROM Employee has EmployeeHired h",
  same_as("SELECT CAST(strftime('%m', hired) AS INTEGER), CAST(strftime('%d', hired) AS INTEGER) "
          "FROM employee")),
 ("2026  today() takes no arguments; days_between() subtracts",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeHired h "
  "WHERE days_between(today(), h) > 0",
  same_as("SELECT emp_name FROM employee WHERE julianday('now') - julianday(hired) > 0")),
 # Patterns, as a question says them. A boolean function stands as a condition by itself.
 ("2026  starts_with as a condition",
  "LIST n FROM Employee has EmployeeName n WHERE starts_with(n, 'A')",
  same_as("SELECT emp_name FROM employee WHERE emp_name LIKE 'A%'")),
 ("2026  contains as a condition",
  "LIST n FROM Employee has EmployeeName n WHERE contains(n, 'lan')",
  same_as("SELECT emp_name FROM employee WHERE emp_name LIKE '%lan%'")),
 # ... and inside a path, joined with AND ALSO, where it used to lower as a calculation
 # nobody read: the count came back unfiltered. Found by a pilot modeller.
 ("2026  a boolean call as an AND ALSO conjunct is a condition",
  "THE COUNT OF Employee [has EmployeeName n AND ALSO starts_with(n, 'A')]",
  same_as("SELECT COUNT(*) FROM employee WHERE emp_name LIKE 'A%'")),
 ("2026  a boolean call as a bracket filter on its own",
  "LIST n FROM Employee has EmployeeName n [like(n, '%ing')]",
  same_as("SELECT emp_name FROM employee WHERE emp_name LIKE '%ing'")),
 ("2026  a text literal against a numeric identifier is refused, with the fix",
  "LIST n FROM Employee: 'Alan' has EmployeeName n",
  refuses("Employee [has EmployeeName: 'Alan']")),
 ("a numeric-looking text literal against a numeric identifier is fine",
  "LIST n FROM Employee: '1' has EmployeeName n",
  same_as("SELECT emp_name FROM employee WHERE emp_nr = 1")),
 # A subtype named after a step narrows to it. Reusing the head node dropped the subtype's
 # own population: `Department [is of Manager]` counted departments with any employee.
 ("a subtype named after a step narrows to that subtype",
  "THE COUNT OF Department [is of Manager]",
  same_as("SELECT COUNT(*) FROM department d WHERE EXISTS (SELECT 1 FROM employee e "
          "JOIN manager m ON m.emp_nr = e.emp_nr WHERE e.dept_code = d.dept_code)")),
 ("a supertype named after a step is a restatement, not a join",
  "LIST n FROM Manager has EmployeeName n",
  same_as("SELECT e.emp_name FROM manager m JOIN employee e ON e.emp_nr = m.emp_nr")),
 # A computed grouping key: MetricFlow's time dimension. Bound with AS, or written in place.
 ("2026  grouped by a computed key bound with AS",
  "LIST y, c FROM Employee e has EmployeeHired h AND ALSO year(h) AS y "
  "AND ALSO THE COUNT OF e GROUPED BY y AS c",
  same_as("SELECT CAST(strftime('%Y', hired) AS INTEGER), COUNT(*) FROM employee "
          "WHERE hired IS NOT NULL GROUP BY 1")),
 ("2026  grouped by a computed key written in place",
  "LIST year(h), c FROM Employee e has EmployeeHired h "
  "AND ALSO THE COUNT OF e GROUPED BY year(h) AS c",
  same_as("SELECT CAST(strftime('%Y', hired) AS INTEGER), COUNT(*) FROM employee "
          "WHERE hired IS NOT NULL GROUP BY 1")),
 # And a computed key where the aggregate is re-lowered over a bag of its own, which is the
 # path a fan-out forces. The bag is correlated on the *value of the key*: correlating on the
 # nodes the expression names says "the same salary" where the key says "the same side of
 # 150000", so each bag held one employee and the answer came back as the minimum of each
 # group -- 88000 / 164000 against the correct 95833.33 / 173666.67. Silent, and found by a
 # LiveSQLBench writer who compared the key wrapped in a cast (which takes the other path)
 # with the key written plainly.
 ("2026  a computed group key correlates its bag on the key's value",
  "LIST a FROM Department d is of Employee has EmployeeSalary s "
  "AND ALSO THE AVERAGE s GROUPED BY if(s > 150000, 1, 0) AS a",
  same_as("SELECT AVG(e.salary) FROM department d JOIN employee e ON e.dept_code = d.dept_code "
          "WHERE e.salary IS NOT NULL GROUP BY CASE WHEN e.salary > 150000 THEN 1 ELSE 0 END")),
 ("2026  ...and not on the columns inside it",
  "LIST a FROM Department d is of Employee has EmployeeSalary s "
  "AND ALSO THE AVERAGE s GROUPED BY if(s > 150000, 1, 0) AS a",
  sql_has("END = CASE WHEN")),

 # B.2: the operand of a group function is an information descriptor, Fr operators
 # included. Three pilot agents wrote this and were told the count was "a computed value".
 ("an aggregate's operand takes BUT NOT",
  "THE COUNT OF Employee BUT NOT has EmployeeSalary",
  same_as("SELECT COUNT(*) FROM employee WHERE salary IS NULL")),
 ("an aggregate's operand takes AND ALSO, and arithmetic after it stays outside",
  "THE COUNT OF Employee AND ALSO has EmployeeGender: 'F' * 100 / THE COUNT OF Employee",
  same_as("SELECT CAST(SUM(gender = 'F') AS REAL) * 100 / COUNT(*) FROM employee")),
 # Fr: a grouped aggregate's own path continues from the head when it restates the head's
 # type. Lowered as a fresh range it was a cross product -- primer example 19, silently
 # wrong on a filtered head; two pilot agents found it from the numbers.
 ("a grouped aggregate's IN path restating the head continues from it",
  "LIST d, t FROM Employee [has EmployeeGender: 'F'] has Department d AND ALSO "
  "THE SUM OF s IN Employee has EmployeeSalary s GROUPED BY d AS t",
  same_as("SELECT dept_code, SUM(salary) FROM employee WHERE gender = 'F' GROUP BY dept_code")),
 ("but a path starting elsewhere is its own range, correlated by name",
  "LIST d, c FROM Department d AND ALSO THE COUNT OF Employee [has Department d] "
  "GROUPED BY d AS c",
  same_as("SELECT d.dept_code, COUNT(*) FROM department d JOIN employee e "
          "ON e.dept_code = d.dept_code GROUP BY d.dept_code")),
 # An AND ALSO operand that starts at a bound variable continues from it. Unified with the
 # head it was a self-join on emp_nr = manager_nr; a pilot agent saw the rows vanish.
 ("an operand starting at a bound variable is anchored there, not at the head",
  "LIST n, m FROM Employee e has manager Employee b AND ALSO b has EmployeeName m "
  "AND ALSO e has EmployeeName n",
  same_as("SELECT e.emp_name, b.emp_name FROM employee e "
          "JOIN employee b ON b.emp_nr = e.manager_nr")),
 ("... and as a filter that binds nothing",
  "LIST n FROM Employee e has manager Employee b AND ALSO has EmployeeName n "
  "AND ALSO b has EmployeeGender: 'F'",
  same_as("SELECT e.emp_name FROM employee e JOIN employee b ON b.emp_nr = e.manager_nr "
          "WHERE b.gender = 'F'")),
 ("... and as BUT NOT from the variable",
  "LIST n FROM Employee e has manager Employee b AND ALSO has EmployeeName n "
  "BUT NOT b has EmployeeGender: 'F'",
  same_as("SELECT e.emp_name FROM employee e JOIN employee b ON b.emp_nr = e.manager_nr "
          "WHERE NOT EXISTS (SELECT 1 FROM employee x WHERE x.emp_nr = b.emp_nr "
          "AND x.gender = 'F')")),
 # Two nodes unified must be able to be one instance. `Card ... AND ALSO Set ...` equated
 # cards.id with sets.id and returned nothing (pilot); the refusal says how to correlate.
 ("an AND ALSO operand of an unrelated type is refused, with the correlation form",
  "LIST n FROM Employee has EmployeeName n AND ALSO Project has ProjectName: 'x'",
  refuses("no Employee is a Project")),
 ("an instance denoted by a value is refused",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode c "
  "AND ALSO has Department: !c",
  refuses("one is a value")),
 ("a correlation through a shared value is the way to say it",
  "LIST pn FROM Project has ProjectName pn AND ALSO has ProjectCode c "
  "WHERE SOME Employee [has Department has DepartmentCode: !c]",
  same_as("SELECT proj_name FROM project p WHERE EXISTS "
          "(SELECT 1 FROM employee e WHERE e.dept_code = p.proj_code)")),
 # Finding 36: an aggregate correlated to the enclosing row by equality is emitted as a
 # grouped derived table joined on the correlation, not a per-row subquery -- the same
 # rows in 0.3s where the subquery took minutes on an unindexed column.
 ("a correlated aggregate is decorrelated into a grouped join",
  "LIST n FROM Employee e has EmployeeName n WHERE THE COUNT OF Assignment [has Employee: !e] > 1",
  sql_has("LEFT JOIN (SELECT")),
 ("and gives the correlated subquery's rows, zero for an employee with none",
  "LIST n, c FROM Employee e has EmployeeName n AND ALSO "
  "THE COUNT OF Assignment [has Employee: !e] AS c",
  same_as("SELECT emp_name, (SELECT COUNT(*) FROM assignment a WHERE a.emp_nr = e.emp_nr) "
          "FROM employee e")),
 ("but not when the inner block mentions the outer row in another way",
  "LIST n FROM Employee e has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE THE COUNT OF Employee [has EmployeeSalary x WHERE x > !s] > 2",
  refuses("")),
 # Finding 37: an aggregate over a grouped block whose argument is a group key. It was
 # rendered as SELECT COUNT(key) ... GROUP BY key HAVING ..., a per-group count of which
 # the scalar subquery returned the first: 3 where the answer is 1. A verifier agent found it.
 ("an aggregate over a grouped block counts the groups",
  "THE COUNT OF d IN (Employee e has Department d AND ALSO THE COUNT OF e GROUPED BY d AS c "
  "WHERE c > 2)",
  same_as("SELECT COUNT(*) FROM (SELECT dept_code FROM employee WHERE dept_code IS NOT NULL "
          "GROUP BY dept_code HAVING COUNT(*) > 2)")),
 # An objectified fact instance bound to a variable and continued from after AND ALSO
 # (finding 40): the rows were right and the normal form dropped the continuation.
 ("a bound objectified fact instance continued from after AND ALSO",
  "LIST n, h FROM Employee e has Assignment a has Project has ProjectName n "
  "AND ALSO a has AssignmentHours h",
  same_as("SELECT p.proj_name, a.hours FROM assignment a JOIN project p "
          "ON p.proj_code = a.proj_code")),
 ("2026  ends_with and like",
  "LIST n FROM Employee has EmployeeName n WHERE ends_with(n, 'ing') OR like(n, 'G%')",
  same_as("SELECT emp_name FROM employee WHERE emp_name LIKE '%ing' OR emp_name LIKE 'G%'")),
 ("2026  instr",
  "LIST instr(n, ' ') FROM Employee has EmployeeName n",
  same_as("SELECT INSTR(emp_name, ' ') FROM employee")),
 ("2026  a non-boolean function cannot stand as a condition",
  "LIST n FROM Employee has EmployeeName n WHERE length(n)",
  refuses("not a boolean function")),

 # -- conquer-2026.md §4: a scalar conditional -----------------------------------------
 # §7.5's IF chooses between bags and stays refused; this one lives where a scalar does.
 ("2026  IF THEN ELSE in a projection",
  "LIST n, IF s > 170000 THEN 'high' ELSE 'low' FROM Employee has EmployeeName n "
  "AND ALSO has EmployeeSalary s",
  same_as("SELECT emp_name, CASE WHEN salary > 170000 THEN 'high' ELSE 'low' END "
          "FROM employee WHERE salary IS NOT NULL")),
 ("2026  if(c, a, b) is the same thing as a call",
  "LIST n, if(g = 'F', 1, 0) FROM Employee has EmployeeName n AND ALSO has EmployeeGender g",
  same_as("SELECT emp_name, CASE WHEN gender = 'F' THEN 1 ELSE 0 END FROM employee "
          "WHERE gender IS NOT NULL")),
 ("2026  a conditional inside a comparison",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE IF s > 170000 THEN 1 ELSE 0 = 1",
  same_as("SELECT emp_name FROM employee WHERE salary IS NOT NULL AND "
          "CASE WHEN salary > 170000 THEN 1 ELSE 0 END = 1")),
 ("2026  the bag-valued IF of section 7.5 is still refused at the head of a query",
  "IF Employee has EmployeeSalary > 1 THEN Employee ELSE Employee",
  refuses("conditional descriptor")),

 # -- conquer-2026.md §7: an aggregate of a per-group aggregate ---------------------------
 # AVG(COUNT(..)) is not SQL; the inner grouping becomes a derived table and the outer
 # aggregate ranges over it. B.2's `<var> IN <descriptor>` names what is aggregated, and the
 # descriptor is parenthesised because it is more than a path.
 ("2026  average of a per-group count",
  "THE AVERAGE c IN (Department d AND ALSO THE COUNT OF Employee [has Department d] "
  "GROUPED BY d AS c)",
  same_as("SELECT AVG(c) FROM (SELECT COUNT(e.emp_nr) AS c FROM department d "
          "JOIN employee e ON e.dept_code = d.dept_code GROUP BY d.dept_code)")),
 ("2026  and the SQL is a derived table, not a nested aggregate",
  "THE AVERAGE c IN (Department d AND ALSO THE COUNT OF Employee [has Department d] "
  "GROUPED BY d AS c)",
  sql_has("FROM (SELECT")),
 ("2026  max of a per-group sum",
  "THE MAXIMUM t IN (Department d AND ALSO THE SUM OF Employee [has Department d] "
  "has EmployeeSalary GROUPED BY d AS t)",
  same_as("SELECT MAX(t) FROM (SELECT SUM(e.salary) AS t FROM department d "
          "JOIN employee e ON e.dept_code = d.dept_code WHERE e.salary IS NOT NULL "
          "GROUP BY d.dept_code)")),

 # -- conquer-2026.md §8: a limit that applies somewhere other than the whole result ------
 # Two shapes, the same missing idea from two directions. A `(LIST ...)` standing as a bag
 # carries its own ordering and limit -- "the department with the most employees" feeding an
 # outer question. And `PER x` keeps the first n within each x, which is a window function.
 ("2026  a (LIST ...) with its own limit stands as a bag",
  "LIST dn FROM Department d [has DepartmentName dn] WHICH ARE ALL IN "
  "(LIST x FROM Employee e has Department x AND ALSO THE COUNT OF e GROUPED BY x AS c "
  "ORDERED WITH c DESCENDING THE FIRST 1)",
  same_as("SELECT dept_name FROM department WHERE dept_code IN "
          "(SELECT dept_code FROM employee GROUP BY dept_code ORDER BY COUNT(*) DESC LIMIT 1)")),
 # In a compound SELECT, LIMIT binds to the compound, not to the operand it follows. The bag
 # must be its own derived table or the limit would trim the EXCEPT.
 ("2026  the limited bag is wrapped so LIMIT binds to it, not to the EXCEPT",
  "LIST dn FROM Department d [has DepartmentName dn] WHICH ARE ALL IN "
  "(LIST x FROM Employee e has Department x AND ALSO THE COUNT OF e GROUPED BY x AS c "
  "ORDERED WITH c DESCENDING THE FIRST 1)",
  sql_has('SELECT "v" FROM (SELECT')),
 ("2026  a bag must list exactly one thing",
  "LIST dn FROM Department d [has DepartmentName dn] WHICH ARE ALL IN "
  "(LIST x, c FROM Employee e has Department x AND ALSO THE COUNT OF e GROUPED BY x AS c)",
  refuses("exactly one thing")),
 ("2026  THE FIRST n PER x: the top earner in each department",
  "LIST d, n, s FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n "
  "AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 1 PER d",
  same_as("SELECT dept_code, emp_name, salary FROM (SELECT dept_code, emp_name, salary, "
          "ROW_NUMBER() OVER (PARTITION BY dept_code ORDER BY salary DESC) rn FROM employee "
          "WHERE salary IS NOT NULL) WHERE rn <= 1")),
 ("2026  and it is a window function",
  "LIST d, n FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n "
  "AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 1 PER d",
  sql_has("ROW_NUMBER() OVER (PARTITION BY")),
 ("2026  PER with AFTER: the second earner in each department",
  "LIST d, n FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n "
  "AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 1 AFTER 1 PER d",
  same_as("SELECT dept_code, emp_name FROM (SELECT dept_code, emp_name, "
          "ROW_NUMBER() OVER (PARTITION BY dept_code ORDER BY salary DESC) rn FROM employee "
          "WHERE salary IS NOT NULL) WHERE rn <= 2 AND rn > 1")),
 ("2026  PER an unbound name is refused",
  "LIST n FROM Employee has EmployeeName n ORDERED WITH n THE FIRST 1 PER zz",
  refuses("neither a variable this query binds")),

 # -- inventory: specified in the grammar, refused with the reason rather than mis-read ----
 ("DOES NOT EQUAL  negates EQUALS",
  "Employee has EmployeeName DOES NOT EQUAL Employee has Department has DepartmentCode",
  same_as("SELECT emp_nr FROM employee")),
 ("EQUALS  the complement of the above",
  "Employee has EmployeeName EQUALS Employee has Department has DepartmentCode",
  rows(0)),
 # -- §6.5 confluence: the report's own answer to "show it if it's there" ---------------
 # The base path after EACH is required -- a natural join over the fact population. Each
 # element before it is gathered with a LEFT OUTER JOIN, the report's ⟕. This is where
 # ConQuer-92 puts the line between a fact you need and a value you merely want shown, and
 # it is the faithful way to keep a school that has no street.
 ("EACH  verb-led element, gathered from the junction's side",
  "LIST n, s FROM has EmployeeSalary AS s EACH Employee has EmployeeName n",
  same_as("SELECT e.emp_name, e.salary FROM employee e")),
 # A side path that can be many per junction is gathered as a NESTED relation, which is
 # what §6.5 meant in [HPW93] before ConQuer-92 flattened it -- and the report says it did
 # that only "since SQL-92 is not able to deal with nested relations". An employee with two
 # assignments is one employee with two hours, not two employees; flattening repeated the
 # name, and repeated every other gathered value and any aggregate beside it.
 ("EACH  a gathered value that can be many comes back nested, not as more rows",
  "LIST n, h FROM has Assignment has AssignmentHours AS h EACH Employee has EmployeeName n",
  same_as("SELECT e.emp_name, (SELECT json_group_array(a.hours) FROM assignment a "
          "WHERE a.emp_nr = e.emp_nr) FROM employee e")),
 ("EACH  so every employee is one row, assignments or not",
  "LIST n, h FROM has Assignment has AssignmentHours AS h EACH Employee has EmployeeName n",
  rows(6)),
 ("EACH  and an employee with no assignment gathers the empty bag, not null",
  "LIST n, h FROM has Assignment has AssignmentHours AS h EACH Employee has EmployeeName n "
  "AND ALSO has EmployeeName: 'Betty Holberton'",
  same_as("SELECT 'Betty Holberton', '[]'")),
 ("EACH  a gathered value the model makes functional is still flattened",
  "LIST n, s FROM has EmployeeSalary AS s EACH Employee has EmployeeName n",
  sql_has_count("JSON_GROUP_ARRAY", 0)),
 ("EACH  a nested element takes an order and a cut of its own",
  "LIST n, h FROM has Assignment has AssignmentHours AS h ORDERED WITH h DESCENDING "
  "THE FIRST 1 EACH Employee has EmployeeName n",
  same_as("SELECT e.emp_name, (SELECT json_group_array(v) FROM "
          "(SELECT a.hours AS v FROM assignment a WHERE a.emp_nr = e.emp_nr "
          "ORDER BY a.hours DESC LIMIT 1)) FROM employee e")),
 ("EACH  PER inside an element is refused: the element is already per junction",
  "LIST n, h FROM has Assignment has AssignmentHours AS h ORDERED WITH h DESCENDING "
  "THE FIRST 1 PER n EACH Employee has EmployeeName n",
  refuses("already one bag per junction")),
 ("EACH  a bare type attaches by the one fact type between them",
  "LIST n, b FROM DepartmentBudget AS b VIA d EACH Employee has EmployeeName n "
  "AND ALSO has Department d",
  same_as("SELECT e.emp_name, d.budget FROM employee e "
          "JOIN department d ON d.dept_code = e.dept_code")),
 # The report's `Firstname of` shape reads the fact type from the VALUE's side, which needs a
 # reading that starts there. Reverse-engineered models carry only the forward reading
 # ("{0} has {1}"), so on this fixture the form is refused -- adding the inverse reading is
 # one of the refinements Halpin's chapter 8 lists, and it would make this parse.
 ("EACH  the report's dangling-verb shape needs an inverse reading this model lacks",
  "LIST n, h FROM AssignmentHours has AS h EACH Employee has EmployeeName n",
  refuses("AssignmentHours")),
 ("EACH  VIA names where to attach",
  "LIST n, pn FROM has ProjectName AS pn VIA p EACH Employee has EmployeeName n "
  "AND ALSO has Assignment has Project p",
  same_as("SELECT e.emp_name, p.proj_name FROM employee e "
          "JOIN assignment a ON a.emp_nr = e.emp_nr JOIN project p ON p.proj_code = a.proj_code")),
 ("EACH  VIA an unbound name is refused",
  "LIST n, pn FROM has ProjectName AS pn VIA zz EACH Employee has EmployeeName n",
  refuses("not bound by the base path")),
 ("EACH  without LIST, gathered values join the default projection",
  "has EmployeeSalary AS s EACH Employee has EmployeeName",
  same_as("SELECT e.emp_nr, e.emp_name, e.salary FROM employee e")),
 ("EACH  a mandatory junction role is joined inner: the same relation, and the validator's rule",
  "LIST n, c FROM has DepartmentCode AS c VIA d EACH Employee has EmployeeName n "
  "AND ALSO has Department d",
  same_as("SELECT e.emp_name, d.dept_code FROM employee e "
          "JOIN department d ON d.dept_code = e.dept_code")),
 ("EACH  a complete descriptor as an element needs path reversal, and says so",
  "LIST n FROM Department has DepartmentBudget EACH Employee has EmployeeName n",
  refuses("THE REVERSE OF")),
 ("EACH  a bare type with no connecting fact type is refused",
  "LIST n, b FROM DepartmentBudget AS b EACH Employee has EmployeeName n",
  refuses("no fact type connects")),
 # -- conquer-2026 §11: a derivation rule scoped to one query ---------------------------
 # §6.11 already names an intermediate and the emitter already renders one as a CTE; DEFINE
 # is that without editing the model. It is what the Spider 2.0 trial found the language
 # actually short of: two grouped results that have to sit on one row.
 ("DEFINE  two grouped intermediates on one row, which nothing else could say",
  "DEFINE TopEarner ::= LIST d, e FROM Employee e [has EmployeeSalary s] has Department d "
  "ORDERED WITH s DESCENDING THE FIRST 1 PER d "
  "DEFINE FirstHired ::= LIST d, e FROM Employee e [has EmployeeHired h] has Department d "
  "ORDERED WITH h ASCENDING THE FIRST 1 PER d "
  "LIST c, a, b FROM Department has DepartmentCode c "
  "AND ALSO has TopEarner has EmployeeName a AND ALSO has FirstHired has EmployeeName b",
  same_as("SELECT d.dept_code, "
          "(SELECT e.emp_name FROM employee e WHERE e.dept_code = d.dept_code "
          " AND e.salary IS NOT NULL ORDER BY e.salary DESC LIMIT 1), "
          "(SELECT e.emp_name FROM employee e WHERE e.dept_code = d.dept_code "
          " ORDER BY e.hired ASC LIMIT 1) FROM department d")),
 ("DEFINE  each definition is a common table expression",
  "DEFINE TopEarner ::= LIST d, e FROM Employee e [has EmployeeSalary s] has Department d "
  "ORDERED WITH s DESCENDING THE FIRST 1 PER d "
  "LIST c, a FROM Department has DepartmentCode c AND ALSO has TopEarner has EmployeeName a",
  sql_has("WITH \"TopEarner\"")),
 ("DEFINE  one thing listed is a subtype, walked like any other",
  "DEFINE BigEarner ::= LIST e FROM Employee e has EmployeeSalary s WHERE s > 150000 "
  "LIST n FROM BigEarner has EmployeeName n",
  same_as("SELECT emp_name FROM employee WHERE salary > 150000")),
 ("DEFINE  a bare path defines the relation of its two ends",
  "DEFINE Named ::= Employee has EmployeeName "
  "LIST n FROM Employee has Named EmployeeName n",
  same_as("SELECT DISTINCT emp_name FROM employee WHERE emp_name IS NOT NULL")),
 ("DEFINE  a definition may be written in terms of an earlier one",
  "DEFINE BigEarner ::= LIST e FROM Employee e has EmployeeSalary s WHERE s > 150000 "
  "DEFINE BigDept ::= LIST d FROM BigEarner has Department d "
  "LIST c FROM BigDept has DepartmentCode c",
  same_as("SELECT DISTINCT dept_code FROM employee WHERE salary > 150000 "
          "AND dept_code IS NOT NULL")),

 ("IF  the conditional descriptor is refused",
  "IF Employee has EmployeeSalary > 100000 THEN Employee has EmployeeName",
  refuses("conditional descriptor")),
 ("OTHERWISE  the alternatives sequence is refused",
  "Employee has EmployeeName IF Employee has EmployeeSalary > 1 OTHERWISE Employee",
  refuses("conditional descriptor")),
 ("reading an optional role requires it (binding-sql92 section 6.1a)",
  "LIST n FROM Employee [has EmployeeName n] has EmployeeSalary",
  same_as("SELECT emp_name FROM employee WHERE salary IS NOT NULL")),

 # -- conquer-2026 §10: several whole-query scalars side by side -------------------------
 # BIRD asks "the difference between A and B, and between B and C" in one breath; the pilot's
 # ConQuer arm had no way to answer in one row.
 ("2026  a LIST of whole-query scalars needs no FROM",
  "LIST THE COUNT OF Employee, THE COUNT OF Department",
  same_as("SELECT (SELECT COUNT(*) FROM employee), (SELECT COUNT(*) FROM department)")),
 ("2026  each item may be an expression over aggregates",
  "LIST THE COUNT OF Employee [has EmployeeGender: 'F'] * 100 / THE COUNT OF Employee, "
  "THE MAXIMUM Employee has EmployeeSalary - THE MINIMUM Employee has EmployeeSalary",
  same_as("SELECT (SELECT COUNT(*) FROM employee WHERE gender = 'F') * 100.0 "
          "/ (SELECT COUNT(*) FROM employee), "
          "(SELECT MAX(salary) FROM employee) - (SELECT MIN(salary) FROM employee)")),
 ("2026  two scalars side by side may bind the same name; each is its own query",
  "LIST THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 100000, "
  "THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 50000",
  same_as("SELECT (SELECT COUNT(*) FROM employee WHERE salary > 100000), "
          "(SELECT COUNT(*) FROM employee WHERE salary > 50000)")),
 ("and so may two aggregates in one expression",
  "(THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 100000) * 100 / "
  "(THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 0)",
  same_as("SELECT (SELECT COUNT(*) FROM employee WHERE salary > 100000) * 100.0 / "
          "(SELECT COUNT(*) FROM employee WHERE salary > 0)")),
 ("2026  a list with a name to bind still needs a path to bind it",
  "LIST n, THE COUNT OF Department", refuses("neither a type")),

 # -- what the 15 Sep benchmark round exposed -------------------------------------------
 # Three crashes and a wrong refusal, all found by writers rather than by tests. Each is
 # here so the next one is a failing case and not another agent's lost afternoon.

 # A value type has no table of its own, so `THE AVERAGE EmployeeSalary` had no anchor and
 # the emitter raised `node n3 has no anchor` -- a crash with an internal node id in it.
 # A value type's population is the values appearing in its fact type, so it has an answer.
 ("a bare value type can be aggregated: its population is the fact type that carries it",
  "THE AVERAGE EmployeeSalary", same_as("SELECT AVG(salary) FROM employee")),
 ("and counting one counts the values that are there, not the rows",
  "THE COUNT OF EmployeeSalary", same_as("SELECT COUNT(salary) FROM employee")),
 ("a bare value type aggregates the same as the path to it",
  "THE AVERAGE EmployeeSalary", same_as("SELECT AVG(salary) FROM employee")),
 ("and two of them sit side by side like any other whole-query scalars",
  "LIST THE AVERAGE EmployeeSalary, THE AVERAGE DepartmentBudget",
  same_as("SELECT (SELECT AVG(salary) FROM employee), "
          "(SELECT AVG(budget) FROM department)")),

 # `OR OTHERWISE` folds its operands into sub-blocks; a name bound in one of them is not
 # bound in the other, and projecting it raised `node n10 has no anchor`. A card_games
 # writer rewrote around this by De Morgan without ever learning what was wrong.
 ("projecting a name bound inside one alternative is refused, and says why",
  "LIST n, g FROM Employee has EmployeeName n AND ALSO has EmployeeGender g "
  "OR OTHERWISE has EmployeeSalary: 1",
  refuses("bound inside one alternative")),
 ("the same query without the alternative is fine",
  "LIST n, g FROM Employee has EmployeeName n AND ALSO has EmployeeGender g",
  same_as("SELECT emp_name, gender FROM employee")),

 # The condition parser took the `AND` of `AND ALSO` as a boolean operator, so the branch
 # after a mid-path WHERE was rooted at the last thing named instead of at the head. The
 # query below is correct ConQuer; it produced a confident, wrong refusal about Employee and
 # DepartmentCode being the same thing.
 ("WHERE mid-path: the branch after it still comes off the head",
  "LIST n FROM Employee has EmployeeName n WHERE n <> 'x' AND ALSO has EmployeeGender: 'F'",
  same_as("SELECT emp_name FROM employee WHERE emp_name <> 'x' AND gender = 'F'")),
 ("and a grouped aggregate after a mid-path WHERE means what it says",
  "LIST d, c FROM Employee e has Department has DepartmentCode d WHERE d <> 'HR' "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c",
  same_as("SELECT d.dept_code, COUNT(*) FROM employee e JOIN department d "
          "ON e.dept_code = d.dept_code WHERE d.dept_code <> 'HR' GROUP BY d.dept_code")),
 # -- the fan trap in a whole-query aggregate ----------------------------------------------
 # check_aggregate_locality guarded a GROUPED aggregate and not an ungrouped one: the fan-out
 # sits in the aggregate's own block while the SUM sits on a calculation outside it, so nothing
 # tested one against the other. Each department's budget was returned once per employee --
 # 9,300,000 against a true 3,600,000, silently.
 ("a fanned-out sum is computed once per value, not once per fan-out row",
  "THE SUM OF b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n",
  same_as("SELECT SUM(d.budget) FROM department d WHERE EXISTS "
          "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code "
          "AND e.emp_name IS NOT NULL)")),
 ("and the average with it",
  "THE AVERAGE b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n",
  same_as("SELECT AVG(d.budget) FROM department d WHERE EXISTS "
          "(SELECT 1 FROM employee e WHERE e.dept_code = d.dept_code "
          "AND e.emp_name IS NOT NULL)")),
 ("the same sum without the fan-out is fine",
  "THE SUM OF b IN Department has DepartmentBudget b",
  same_as("SELECT SUM(budget) FROM department")),
 # MIN and MAX are unchanged by repetition, so they are never refused.
 ("a fan-out cannot change a maximum, so it is allowed",
  "THE MAXIMUM b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n",
  same_as("SELECT MAX(budget) FROM department")),
 # Counting a fanned head stays the author's business: over the recorded corpus, refusing it
 # rejected 20 right answers for every 5 wrong ones.
 ("counting a head reached through a fan-out is still allowed",
  "THE COUNT OF Employee [has EmployeeSalary s] WHERE s > 100000",
  same_as("SELECT COUNT(*) FROM employee WHERE salary > 100000")),

 # -- conquer-2026 §11: WITHIN, the partition without the collapse -------------------------
 # A third of Spider 2.0's local gold queries need a window function and ConQuer had none.
 # `GROUPED BY` already partitions; it just also collapses. `WITHIN` is the same partition
 # reported beside every row, which is what SQL spells OVER (PARTITION BY ...).
 ("2026  WITHIN keeps every row and carries its group's figure",
  "LIST n, d, c FROM Employee e has EmployeeName n AND ALSO has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e WITHIN d AS c",
  same_as("SELECT e.emp_name, e.dept_code, COUNT(*) OVER (PARTITION BY e.dept_code) "
          "FROM employee e")),
 ("2026  where GROUPED BY returns one row per group",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c",
  same_as("SELECT dept_code, COUNT(*) FROM employee GROUP BY dept_code")),
 ("2026  a WITHIN value can be compared: the top of each group",
  "LIST n, d FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d "
  "AND ALSO has EmployeeSalary s AND ALSO THE MAXIMUM s WITHIN d AS m WHERE s = m",
  same_as("SELECT e.emp_name, e.dept_code FROM employee e WHERE e.salary = "
          "(SELECT MAX(x.salary) FROM employee x WHERE x.dept_code = e.dept_code)")),
 ("2026  and compared the other way: above your group's average",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d "
  "AND ALSO has EmployeeSalary s AND ALSO THE AVERAGE s WITHIN d AS a WHERE s > a",
  same_as("SELECT e.emp_name FROM employee e WHERE e.salary > "
          "(SELECT AVG(x.salary) FROM employee x WHERE x.dept_code = e.dept_code)")),
 ("2026  WITHIN without a partition is refused, and says what to write instead",
  "LIST n FROM Employee has EmployeeName n AND ALSO THE COUNT OF Employee WITHIN",
  refuses("WITHIN needs the partition")),

 ("which is the same answer as writing the WHERE at the end",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c WHERE d <> 'HR'",
  same_as("SELECT d.dept_code, COUNT(*) FROM employee e JOIN department d "
          "ON e.dept_code = d.dept_code WHERE d.dept_code <> 'HR' GROUP BY d.dept_code")),
]


def run(model, conn, lexicon, emitter, query, expect, verbose=False):
    kind, arg = expect
    try:
        _, statement, params = driver.transpile(model, query, lexicon, emitter)
    except parser_mod.Ambiguous as e:
        if kind == "ambiguous" and arg.lower() in str(e).lower():
            return True, "ambiguous as expected"
        return False, "unexpected ambiguity: %s" % e
    except parser_mod.ParseError as e:
        if kind == "refuses" and arg.lower() in str(e).lower():
            return True, "refused as expected"
        return False, "parse error: %s" % e
    except sql_mod.SqlError as e:
        if kind == "refuses" and arg.lower() in str(e).lower():
            return True, "refused as expected"
        return False, "cannot compile: %s" % e

    if kind == "refuses":
        return False, "expected a refusal mentioning %r, but it compiled" % arg
    if kind == "ambiguous":
        return False, "expected an ambiguity, but it compiled"
    if kind == "sql_has":
        return (arg in statement), ("contains %r" % arg if arg in statement
                                    else "SQL lacks %r: %s" % (arg, statement))
    if kind == "sql_has_count":
        needle, want_n = arg
        got_n = statement.count(needle)
        return (got_n == want_n), ("%r appears %d time(s), expected %d: %s"
                                   % (needle, got_n, want_n, statement))
    try:
        got = conn.execute(statement, params).fetchall()
    except sqlite3.Error as e:
        return False, "SQL error: %s\n        %s" % (e, statement)
    if kind == "rows":
        return (len(got) == arg), "%d rows (expected %d)" % (len(got), arg)

    want = conn.execute(arg).fetchall()
    row = lambda r: tuple("" if v is None else str(v) for v in r)
    norm = (list if kind == "ordered_as" else sorted)
    if norm([row(r) for r in got]) == norm([row(r) for r in want]):
        return True, "%d rows, matches reference" % len(got)
    return False, ("got %d rows, reference gives %d\n        %s"
                   % (len(got), len(want), statement))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if not os.path.exists(args.model):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2

    model = json.load(open(args.model))
    conn = sqlite3.connect(args.db)
    lexicon = parser_mod.Lexicon(model)
    emitter = sql_mod.Emitter(model)

    cases = [c for c in CASES if not args.only or args.only.lower() in c[0].lower()]
    passed = 0
    for name, query, expect in cases:
        ok, detail = run(model, conn, lexicon, emitter, query, expect, args.verbose)
        passed += ok
        if ok:
            print("ok    %-46s %s" % (name, detail if args.verbose else ""))
        else:
            print("FAIL  %s\n        %s\n        %s" % (name, query, detail))
    print("\n%d passed, %d failed, %d total" % (passed, len(cases) - passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
