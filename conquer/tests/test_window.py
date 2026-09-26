#!/usr/bin/env python3
"""Row-relative functions and the dialect seam: conquer-2026 sections 12 and 30-34.

A group function reduces a bag to one value, and `WITHIN` changes only where the answer is
reported. Neither can say what a row is *against the other rows of its partition* -- its rank,
the row before it, the middle of the bag. Three blind benchmark writers needed one of those on
three different schemas and none could say it; one reported `THE AVERAGE` where a median was
asked for, which is a different number in the same shape with nothing to mark it (finding 99).

Every case states its truth as hand-written SQL over the same fixture, so a case fails when the
compiler's *answer* changes rather than when its text does. The dialect cases check the emitted
SQL instead, because SQLite cannot run PostgreSQL's spelling and that is the point of them.

    test_window.py [-v] [--only SUBSTRING]
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "reverse"))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402
import catalog as catalog_mod     # noqa: E402
import derive as derive_mod       # noqa: E402

DB = os.path.join(WORK, "company.sqlite")
MODEL = os.path.join(WORK, "company.ccm.json")

DEPT = ("Employee has Department has DepartmentCode d AND ALSO has EmployeeSalary s "
        "AND ALSO has EmployeeName n")
JOIN = ("FROM employee e JOIN department dp ON dp.dept_code = e.dept_code "
        "WHERE e.salary IS NOT NULL")


def rows(sql, note=""):
    return ("rows", sql, note)


def refuses(fragment):
    return ("refuses", fragment, "")


def emits(fragment, dialect):
    """The emitted SQL must contain this. For spellings no fixture engine can run."""
    return ("emits", fragment, dialect)


CASES = [
    # -- a filter on a window value, beside an ORDER BY --------------------------------------
    # Filtering on a WITHIN value wraps the query, because WHERE runs before a window function
    # exists. The sort keys were resolved *after* that wrap and against the inner aliases, so
    # the ORDER BY named a column the wrapper cannot see: "no such column: employ1.salary".
    # Four writers on one LiveSQLBench run hit it, on four different databases. The keys are
    # now resolved before the wrap -- a projected one by its name, anything else riding out
    # under an alias, which is what sorting on a column the query does not list needs.
    ("a filter on a WITHIN value sorts by a key the query does not list",
     "LIST n, v FROM Employee has EmployeeName n AND ALSO has EmployeeGender g "
     "AND ALSO has EmployeeSalary s AND ALSO THE AVERAGE s WITHIN g AS v "
     "WHERE s > v ORDERED WITH s DESCENDING",
     rows("SELECT e.emp_name, x.v FROM (SELECT emp_name, salary, gender, "
          "AVG(salary) OVER (PARTITION BY gender) AS v FROM employee "
          "WHERE gender IS NOT NULL AND salary IS NOT NULL) x JOIN employee e "
          "ON e.emp_name = x.emp_name WHERE x.salary > x.v ORDER BY x.salary DESC")),

    # The deferred expression's text goes into the INNER select and its parameters were
    # sunk into whatever clause was being rendered -- the order or where slot -- so every
    # placeholder from the inner query onward took the wrong value. A filter executed as
    # `postfreq > 0.3`, a limit as `__w0 <= 1`, and rows came back violating the query's own
    # conditions, with no error. Three writers on three databases, and the ORDER BY half was
    # mine: before it the same shape said "no such column", which at least failed loudly.
    ("a filter on a WITHIN value sorts by a computed key, parameters and all",
     "LIST n, v FROM Employee has EmployeeName n AND ALSO has EmployeeGender g "
     "AND ALSO has EmployeeSalary s AND ALSO (s * 2) AS x "
     "AND ALSO THE AVERAGE x WITHIN g AS v WHERE x > v ORDERED WITH x DESCENDING",
     rows("SELECT emp_name, v FROM (SELECT emp_name, salary * 2 AS x, "
          "AVG(salary * 2) OVER (PARTITION BY gender) AS v FROM employee "
          "WHERE gender IS NOT NULL AND salary IS NOT NULL) WHERE x > v "
          "ORDER BY x DESC")),

    ("and by one it does",
     "LIST n, v FROM Employee has EmployeeName n AND ALSO has EmployeeGender g "
     "AND ALSO has EmployeeSalary s AND ALSO THE AVERAGE s WITHIN g AS v "
     "WHERE s > v ORDERED WITH n ASCENDING",
     rows("SELECT emp_name, v FROM (SELECT emp_name, salary, gender, "
          "AVG(salary) OVER (PARTITION BY gender) AS v FROM employee "
          "WHERE gender IS NOT NULL AND salary IS NOT NULL) WHERE salary > v "
          "ORDER BY emp_name ASC")),

    # -- rank --------------------------------------------------------------------------------
    ("rank is 1 for the largest in its partition",
     "LIST n, r FROM %s AND ALSO THE RANK OF s WITHIN d AS r" % DEPT,
     rows("SELECT e.emp_name, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC) "
          + JOIN)),

    ("and restarts in each partition",
     "LIST d, r FROM %s AND ALSO THE RANK OF s WITHIN d AS r" % DEPT,
     rows("SELECT dp.dept_code, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC) "
          + JOIN)),

    # A rank over a partition of one is 1, not null: the row is the whole bag.
    ("a partition of one ranks 1",
     "LIST d, r FROM %s AND ALSO THE RANK OF s WITHIN n AS r" % DEPT,
     rows("SELECT dp.dept_code, RANK() OVER (PARTITION BY e.emp_name ORDER BY e.salary DESC) "
          + JOIN)),

    ("rank partitioned by a computed key",
     "LIST n, r FROM %s AND ALSO if(s > 100000, 'high', 'low') AS band "
     "AND ALSO THE RANK OF s WITHIN band AS r" % DEPT,
     rows("SELECT e.emp_name, RANK() OVER (PARTITION BY CASE WHEN e.salary > 100000 "
          "THEN 'high' ELSE 'low' END ORDER BY e.salary DESC) " + JOIN)),

    # -- previous ----------------------------------------------------------------------------
    ("the previous row is null at the start of each partition",
     "LIST n, p FROM %s AND ALSO THE PREVIOUS s BY n WITHIN d AS p" % DEPT,
     rows("SELECT e.emp_name, LAG(e.salary) OVER "
          "(PARTITION BY e.dept_code ORDER BY e.emp_name ASC) " + JOIN)),

    ("previous along a different key than the value",
     "LIST n, p FROM %s AND ALSO THE PREVIOUS n BY s WITHIN d AS p" % DEPT,
     rows("SELECT e.emp_name, LAG(e.emp_name) OVER "
          "(PARTITION BY e.dept_code ORDER BY e.salary ASC) " + JOIN)),

    # -- both beside ordinary aggregates -----------------------------------------------------
    ("a rank sits beside a windowed aggregate over the same partition",
     "LIST n, r, t FROM %s AND ALSO THE RANK OF s WITHIN d AS r "
     "AND ALSO THE SUM OF s WITHIN d AS t" % DEPT,
     rows("SELECT e.emp_name, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC), "
          "SUM(e.salary) OVER (PARTITION BY e.dept_code) " + JOIN)),

    ("and beside a previous over the same partition",
     "LIST n, r, p FROM %s AND ALSO THE RANK OF s WITHIN d AS r "
     "AND ALSO THE PREVIOUS s BY n WITHIN d AS p" % DEPT,
     rows("SELECT e.emp_name, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC), "
          "LAG(e.salary) OVER (PARTITION BY e.dept_code ORDER BY e.emp_name ASC) " + JOIN)),

    ("a rank can be filtered on",
     "LIST n FROM %s AND ALSO THE RANK OF s WITHIN d AS r WHERE r = 1" % DEPT,
     rows("SELECT emp_name FROM (SELECT e.emp_name AS emp_name, RANK() OVER "
          "(PARTITION BY e.dept_code ORDER BY e.salary DESC) AS r " + JOIN + ") WHERE r = 1")),

    # The wrapping WHERE is a clause of its own, and its text lands after the inner GROUP BY.
    # Its parameters were folded into the inner WHERE's list, which is the same order only
    # while nothing after the inner WHERE binds anything -- and a computed group key does.
    # `GROUPED BY substr(name, 1, 1)` executed as `SUBSTR(name, 2, 1)` with the filter as
    # `r <= 1`: plausible rows, no error. Found on LiveSQLBench's cross_db by a writer who
    # disbelieved a single row where four months had been three a moment before. The values
    # here are chosen so that every misbinding changes the answer.
    ("a rank over a computed group key can be filtered on, parameters and all",
     "LIST k, a, r FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
     "AND ALSO substr(n, 1, 1) AS k AND ALSO THE AVERAGE s GROUPED BY k AS a "
     "AND ALSO 1 AS one AND ALSO THE RANK OF a WITHIN one AS r WHERE r <= 2",
     rows("SELECT k, a, r FROM (SELECT substr(emp_name, 1, 1) AS k, AVG(salary) AS a, "
          "RANK() OVER (ORDER BY AVG(salary) DESC) AS r FROM employee "
          "WHERE salary IS NOT NULL GROUP BY substr(emp_name, 1, 1)) WHERE r <= 2")),

    # A `WITHIN` value sorted on under the wrap. The condition path swapped each window for
    # its alias while rendering; the ordering path rendered the expression, which named the
    # inner query's tables from outside: "no such column: depart2.dept_code", projected or
    # not. A credit writer worked round it by sorting on `(a * 1.0) AS ord`.
    ("a filter on one WITHIN value sorts by another that is projected",
     "LIST n, a FROM %s AND ALSO THE AVERAGE s WITHIN d AS a "
     "AND ALSO THE RANK OF s WITHIN d AS rk WHERE rk = 1 ORDERED WITH a DESCENDING" % DEPT,
     rows("SELECT emp_name, a FROM (SELECT e.emp_name, AVG(e.salary) OVER (PARTITION BY "
          "e.dept_code) AS a, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC) "
          "AS rk " + JOIN + ") WHERE rk = 1 ORDER BY a DESC")),

    ("and by one that is not",
     "LIST n FROM %s AND ALSO THE AVERAGE s WITHIN d AS a "
     "AND ALSO THE RANK OF s WITHIN d AS rk WHERE rk = 1 ORDERED WITH a DESCENDING" % DEPT,
     rows("SELECT emp_name FROM (SELECT e.emp_name, AVG(e.salary) OVER (PARTITION BY "
          "e.dept_code) AS a, RANK() OVER (PARTITION BY e.dept_code ORDER BY e.salary DESC) "
          "AS rk " + JOIN + ") WHERE rk = 1 ORDER BY a DESC")),

    # Two deferred expressions that differ only in a parameter. The alias table was keyed
    # on the text, so `(nn + ?) / ?` bound [1, 2] and bound [2, 2] shared "__c0" and the
    # filter read `rk = c OR rk = c`: a median spelled as "rank n/2 or n/2 + 1" returned
    # half its rows, silently. An alien writer caught it in their own row count.
    ("two filters on a WITHIN value that differ only by a constant are two filters",
     "LIST n FROM Employee e has EmployeeSalary s AND ALSO has EmployeeName n "
     "AND ALSO 1 AS g AND ALSO THE RANK OF s WITHIN g AS rk "
     "AND ALSO THE COUNT OF e WITHIN g AS nn WHERE rk = div(nn + 1, 2) OR rk = div(nn + 2, 2)",
     rows("SELECT emp_name FROM (SELECT emp_name, RANK() OVER (ORDER BY salary DESC) AS rk, "
          "COUNT(*) OVER () AS nn FROM employee WHERE salary IS NOT NULL) "
          "WHERE rk = (nn + 1) / 2 OR rk = (nn + 2) / 2")),

    # A constant group key. Bound, `GROUP BY ?` is a constant; spelled into the text as
    # every scorer does, `GROUP BY 1` is the ordinal of the first output column -- an
    # aggregate, which SQL refuses. A query that ran under ./try failed at the scorer.
    ("a constant group key is never an ordinal",
     "LIST c, t FROM Employee e has EmployeeSalary s AND ALSO 1 AS g "
     "AND ALSO THE COUNT OF e GROUPED BY g AS c AND ALSO THE SUM OF s GROUPED BY g AS t",
     rows("SELECT COUNT(*), SUM(salary) FROM employee WHERE salary IS NOT NULL")),

    # A template-spelled aggregate under WITHIN is each of its inner aggregates windowed
    # (`distribute_over`), and with `WITHIN 1` the window carries a constant: six insertions,
    # so six parameters, in text order between the aggregate's own. The one-list-per-clause
    # binding sank the constant once; a fragment lays it down per insertion.
    ("a windowed standard deviation on SQLite binds its constant partition once per call",
     "LIST n, sd FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
     "AND ALSO THE STANDARD DEVIATION OF s WITHIN 1 AS sd",
     rows("SELECT emp_name, SQRT((SUM(CAST(salary AS REAL) * salary) OVER () "
          "- SUM(CAST(salary AS REAL)) OVER () * SUM(salary) OVER () / COUNT(salary) OVER ()) "
          "/ (COUNT(salary) OVER () - 1)) FROM employee WHERE salary IS NOT NULL")),

    # -- the refusals ------------------------------------------------------------------------
    # A window over rows that GROUPED BY has collapsed. SQL runs the window after the
    # collapse, over one arbitrary row per group, so the rank was always 1 and `WHERE rk =
    # 1` kept every group: a credit writer built a median this way and got the mean back,
    # with no error. Refused -- but a window over the *grouped* figure is the shape the
    # cross_db writer used correctly, and the case above this section keeps it.
    ("a row-level window beside a GROUPED BY aggregate is refused",
     "LIST d, m FROM %s AND ALSO THE RANK OF s WITHIN d AS rk "
     "AND ALSO THE AVERAGE s GROUPED BY d AS m WHERE rk = 1" % DEPT,
     refuses("GROUPED BY in the same query has collapsed them")),

    ("even unfiltered, since the window would be computed over one row per group",
     "LIST d, m, a FROM %s AND ALSO THE AVERAGE s WITHIN d AS a AND ALSO "
     "THE COUNT OF n GROUPED BY d AS m" % DEPT,
     refuses("GROUPED BY in the same query has collapsed them")),

    # The partition of a window beside GROUPED BY. A partition by a row-level value the
    # group does not fix partitions one arbitrary row per group, silently; one by something
    # a key *determines* -- the department, when the key is its code -- is one partition
    # and correct, and the model's uniqueness constraints are what tell the two apart.
    ("a window beside GROUPED BY may not partition by a value the group does not fix",
     "LIST d, c, r FROM Employee e has Department has DepartmentCode d AND ALSO has "
     "EmployeeName n AND ALSO THE COUNT OF e GROUPED BY d AS c "
     "AND ALSO THE RANK OF c WITHIN n AS r",
     refuses("GROUPED BY in the same query does not fix")),

    ("but may partition by what the key identifies",
     "LIST d, c, r FROM Employee e has Department dep has DepartmentCode d "
     "AND ALSO THE COUNT OF e GROUPED BY d AS c AND ALSO THE RANK OF c WITHIN dep AS r",
     rows("SELECT dept_code, COUNT(*), 1 FROM employee GROUP BY dept_code")),

    # A window over a window: `LAG(LAG(x) OVER (..)) OVER (..)` is a "misuse of window
    # function" at the database, after the query looked fine. Nested THE PREVIOUS was a
    # crypto writer's route to two rows back; refused at compile time, naming the DEFINE
    # that does it.
    ("a previous of a previous is refused, naming the DEFINE that works",
     "LIST n, pp FROM %s AND ALSO THE PREVIOUS s BY n WITHIN d AS p "
     "AND ALSO THE PREVIOUS p BY n WITHIN d AS pp" % DEPT,
     refuses("a window cannot read another")),

    ("a rank of a rank is refused the same way",
     "LIST n, rr FROM %s AND ALSO THE RANK OF s WITHIN d AS r "
     "AND ALSO THE RANK OF r WITHIN d AS rr" % DEPT,
     refuses("a window cannot read another")),

    ("and the DEFINE the refusal names does reach two rows back",
     "DEFINE Prev ::= LIST n, p FROM %s AND ALSO THE PREVIOUS s BY n WITHIN d AS p\n"
     "LIST n, pp FROM Employee has EmployeeName n AND ALSO has Department has "
     "DepartmentCode d AND ALSO n has Prev PrevP p AND ALSO THE PREVIOUS p BY n WITHIN d "
     "AS pp" % DEPT,
     rows("SELECT emp_name, LAG(p) OVER (PARTITION BY dept_code ORDER BY emp_name) FROM "
          "(SELECT e.emp_name, e.dept_code, LAG(e.salary) OVER (PARTITION BY e.dept_code "
          "ORDER BY e.emp_name) AS p " + JOIN + ")")),

    ("a rank GROUPED BY is refused",
     "LIST d, r FROM %s AND ALSO THE RANK OF s GROUPED BY d AS r" % DEPT,
     refuses("needs WITHIN and not GROUPED BY")),

    ("a previous GROUPED BY is refused",
     "LIST d, p FROM %s AND ALSO THE PREVIOUS s BY n GROUPED BY d AS p" % DEPT,
     refuses("needs WITHIN and not GROUPED BY")),

    ("a previous with no BY key is refused",
     "LIST d, p FROM %s AND ALSO THE PREVIOUS s WITHIN d AS p" % DEPT,
     refuses("needs the order it is previous in")),

    ("a rank with no partition is refused",
     "LIST n, r FROM %s AND ALSO THE RANK OF s AS r" % DEPT,
     refuses("needs WITHIN")),

    # -- the median on SQLite (finding 158) ---------------------------------------------------
    # No ordered-set aggregate, but a bag is a derived table and the middle of a numbered
    # one is a closed form: the dialect carries it as `sqlBagTemplate`. Six salaries, so
    # the median is the mean of the third and fourth; grouped, the aggregate is re-lowered
    # into a correlated bag (the finding 117 route) because in place beside GROUP BY there
    # is no derived table to number.
    ("a median over a bag is the middle of the numbered bag",
     "THE MEDIAN s IN Employee has EmployeeSalary s",
     rows("SELECT (101500 + 164000) / 2.0")),

    ("and a grouped median is regrouped into a bag of its own",
     "LIST d, m FROM %s AND ALSO THE MEDIAN s GROUPED BY d AS m" % DEPT,
     rows("SELECT 'ENG', 172000.0 UNION ALL SELECT 'HR', 88000.0 "
          "UNION ALL SELECT 'SALES', 99750.0")),

    ("a filtered median is the middle of what passed: five values, the third",
     "LIST m FROM THE MEDIAN s IN Employee has EmployeeSalary s WHERE s > 90000 AS m",
     rows("SELECT 164000.0")),

    ("a windowed median has no bag to be spelled over, and says so",
     "LIST n, m FROM %s AND ALSO THE MEDIAN s WITHIN d AS m" % DEPT,
     refuses("only over a bag")),

    # -- percent rank, and the direction of a rank (finding 158) ------------------------------
    # (rank - 1) / (rows - 1), ordered the way THE RANK OF is: descending, so 0 is the
    # largest. `ASCENDING` turns either round. `WITHIN 1` is one partition, the whole
    # query -- the normal form always printed it that way and the parser refused to read
    # it back, so writers bound `1 AS one`.
    ("percent rank is the rank as a fraction of the partition, descending by default",
     "LIST n, p FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
     "AND ALSO THE PERCENT RANK OF s WITHIN 1 AS p",
     rows("SELECT emp_name, PERCENT_RANK() OVER (ORDER BY salary DESC) FROM employee "
          "WHERE salary IS NOT NULL")),

    ("and ascending when asked",
     "LIST n, p FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
     "AND ALSO THE PERCENT RANK OF s ASCENDING WITHIN 1 AS p",
     rows("SELECT emp_name, PERCENT_RANK() OVER (ORDER BY salary ASC) FROM employee "
          "WHERE salary IS NOT NULL")),

    ("a rank can be ascending too, and WITHIN 1 needs no bound constant",
     "LIST n, r FROM %s AND ALSO THE RANK OF s ASCENDING WITHIN 1 AS r" % DEPT,
     rows("SELECT e.emp_name, RANK() OVER (ORDER BY e.salary ASC) " + JOIN)),

    # -- roots and powers (finding 100) -------------------------------------------------------
    ("a root is a function",
     "LIST r FROM Department has DepartmentBudget b AND ALSO round(sqrt(b), 3) AS r",
     rows("SELECT ROUND(sqrt(budget), 3) FROM department")),

    ("and so is a power",
     "LIST r FROM Department has DepartmentBudget b AND ALSO round(power(b, 0.5), 3) AS r",
     rows("SELECT ROUND(pow(budget, 0.5), 3) FROM department")),

    ("ln and exp round-trip",
     "LIST r FROM Department has DepartmentBudget b AND ALSO round(exp(ln(b)), 0) AS r",
     rows("SELECT ROUND(exp(ln(budget)), 0) FROM department")),

    # -- a deferred expression binds where its text lands, not where it was built ------------
    # Filtering on a window value wraps the query, and a computed value the filter names has
    # to ride out of the inner select under an alias. Its parameters were bound the moment the
    # condition resolved -- which is before the select list renders, while its text is spliced
    # in *after* the projections. So the constants swapped slots: `(salary * 0.1)` and
    # `2 * RANK() - 2` were emitted in that order and bound [2, 2, 0.1], and the query computed
    # `salary * 2` and `2 * RANK() - 0.1`. It runs, it returns rows, and both numbers are
    # wrong. A blind LiveSQLBench writer found it and handed over the shape.
    ("a deferred filter expression does not steal the projection's parameters",
     "LIST nm, x FROM Employee has EmployeeName nm AND ALSO has EmployeeSalary s "
     "AND ALSO has EmployeeGender g AND ALSO (s * 0.1) AS x "
     "AND ALSO THE RANK OF s WITHIN g AS r AND ALSO THE COUNT OF s WITHIN g AS c "
     "WHERE 2 * r - 2 <= c",
     rows("SELECT nm, x FROM (SELECT emp_name AS nm, salary * 0.1 AS x, "
          "RANK() OVER (PARTITION BY gender ORDER BY salary DESC) AS r, "
          "COUNT(salary) OVER (PARTITION BY gender) AS c FROM employee "
          "WHERE salary IS NOT NULL AND gender IS NOT NULL) WHERE 2 * r - 2 <= c")),

    # -- an associative operator folds (finding 98) -------------------------------------------
    ("concat folds over three arguments",
     "LIST c FROM Employee has EmployeeName n AND ALSO has EmployeeGender g "
     "AND ALSO concat(n, '-', g) AS c",
     rows("SELECT emp_name || '-' || gender FROM employee WHERE gender IS NOT NULL")),

    ("and over four",
     "LIST c FROM Employee has EmployeeName n AND ALSO has EmployeeGender g "
     "AND ALSO concat(n, '-', g, '!') AS c",
     rows("SELECT emp_name || '-' || gender || '!' FROM employee WHERE gender IS NOT NULL")),
]

# The dialects. These check emitted SQL, because SQLite cannot run PostgreSQL's median and
# PostgreSQL is not here to run it -- the point is that the model carries the spelling.
DIALECT_CASES = [
    ("duckdb", "THE MEDIAN s IN Employee has EmployeeSalary s", "median("),
    ("postgresql", "THE MEDIAN s IN Employee has EmployeeSalary s",
     "percentile_cont(0.5) WITHIN GROUP"),
    ("postgresql", "LIST r FROM Department has DepartmentBudget b AND ALSO (b / 2) AS r",
     "DOUBLE PRECISION"),
    ("postgresql", "LIST r FROM Department has DepartmentBudget b AND ALSO round(b, 2) AS r",
     "numeric"),
    ("duckdb", "LIST n, r FROM %s AND ALSO THE RANK OF s WITHIN d AS r" % DEPT,
     "RANK() OVER (PARTITION BY"),
]


# Finding 101: `Anchor.columns` holds reference templates, and a CTE's column names are
# built from them -- `Laboratory as (ID, Date)`. The template itself became the name for
# several commits, which `corpus.py` caught and the suite did not. These pin the recovery.
REF_NAMES = [
    ('{0}."ID"', "ID"),
    ('{0}."emp name"', "emp name"),
    ("json_extract({0}.\"meta\", '$.location.city')", "city"),
    ("CAST(json_extract({0}.\"g\", '$.lat') AS DOUBLE)", "lat"),
    ("json_extract({0}.\"m\", '$.\"tx/hr\"')", "tx/hr"),
]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (os.path.exists(MODEL) and os.path.exists(DB)):
        print("fixture missing: run ./run-tests.sh first")
        return 2

    model = json.load(open(MODEL))
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    lex, em = parser_mod.Lexicon(model), sql_mod.Emitter(model)
    passed = failed = 0

    for name, query, expect in CASES:
        if args.only and args.only.lower() not in name.lower():
            continue
        kind, want, _ = expect
        try:
            _, sql, params = driver.transpile(model, query, lex, em)
        except Exception as e:                                          # noqa: BLE001
            if kind == "refuses" and want in str(e):
                passed += 1
                print("ok    %-58s %s" % (name, str(e)[:44] if args.verbose else ""))
            else:
                failed += 1
                print("FAIL  %s\n        %s\n        %s: %s"
                      % (name, query, type(e).__name__, str(e)[:120]))
            continue
        if kind == "refuses":
            failed += 1
            print("FAIL  %s\n        expected a refusal naming %r, got SQL" % (name, want))
            continue
        # Every scorer this project reports through spells the parameters into the text
        # (the sqlite3 binary, LiveSQLBench's harness): run the cases that way too, or a
        # bound `GROUP BY ?` passes here and an inlined `GROUP BY 1` fails there.
        inlined = sql
        for v in params:
            inlined = inlined.replace("?", repr(v) if isinstance(v, str) else str(v), 1)
        try:
            got = sorted(conn.execute(inlined).fetchall(), key=str)
            truth = sorted(conn.execute(want).fetchall(), key=str)
        except sqlite3.Error as e:
            failed += 1
            print("FAIL  %-58s SQL error: %s" % (name, str(e)[:70]))
            if args.verbose:
                print("      %s" % sql[:260])
            continue
        if got == truth:
            passed += 1
            print("ok    %-58s %d row(s)%s" % (name, len(got),
                                               "  " + str(got[:1]) if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        got  %s\n        want %s"
                  % (name, str(got[:4])[:130], str(truth[:4])[:130]))

    for ref, want in REF_NAMES:
        name = "a reference template names its column %r" % want
        if args.only and args.only.lower() not in name.lower():
            continue
        got = sql_mod._ref_name(ref)
        passed, failed = ((passed + 1, failed) if got == want else (passed, failed + 1))
        print(("ok    %-58s" % name) if got == want
              else "FAIL  %s\n        got %r from %r" % (name, got, ref))

    # The dialect cases build a model per dialect from the same fixture database.
    cat = catalog_mod.from_sqlite(DB)
    built = {}
    for dialect, query, fragment in DIALECT_CASES:
        name = "%s: %s" % (dialect, fragment[:40])
        if args.only and args.only.lower() not in name.lower():
            continue
        if dialect not in built:
            m, _ = derive_mod.derive(cat, dialect=dialect)
            built[dialect] = (m, parser_mod.Lexicon(m), sql_mod.Emitter(m))
        m, dl, de = built[dialect]
        try:
            _, sql, _ = driver.transpile(m, query, dl, de)
        except Exception as e:                                          # noqa: BLE001
            failed += 1
            print("FAIL  %-58s %s: %s" % (name, type(e).__name__, str(e)[:80]))
            continue
        if fragment in sql:
            passed += 1
            print("ok    %-58s %s" % (name, "" if not args.verbose else sql[:60]))
        else:
            failed += 1
            print("FAIL  %s\n        %r not in %s" % (name, fragment, sql[:200]))

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
