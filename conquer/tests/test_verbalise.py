#!/usr/bin/env python3
"""Tests for `--explain`: the sentence, and each section of the interpretation report.

The report exists to be read before a query runs, so what it *says* is the contract, not just
that it says something. Each case asserts on one section:

    says(s)       the verbalised sentence contains s
    resolved(a,b) some resolution line mentions both a and b
    expands(s)    the Expanded list mentions s
    requires(s)   the Requires list mentions s
    checks(s)     the Worth-checking list mentions s
    silent(sec)   that section is empty -- guards against warning on everything

    test_verbalise.py [-v] [--only SUBSTRING]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))

import parser as parser_mod      # noqa: E402
import verbalise as verb_mod     # noqa: E402


def says(s):            return ("sentence", s)
def resolved(a, b):     return ("resolved", (a, b))
def expands(s):         return ("expanded", s)
def requires(s):        return ("requires", s)
def checks(s):          return ("checks", s)
def not_checks(s):      return ("not_checks", s)
def silent(section):    return ("silent", section)
def lacks(s):           return ("lacks", s)         # the sentence must NOT contain s
def risks(n):           return ("risks", n)
def validates():        return ("validates", None)


CASES = [
 ("an aggregate names its grain",
  "THE COUNT OF Employee has Assignment",
  checks("Its grain is Assignment: one per row")),
 ("a set operation reads each side on its own",
  "(LIST n FROM Employee has EmployeeName n) UNITED WITH (LIST n FROM Department has DepartmentName n)",
  says("united with")),
 ("and says what the result keeps",
  "(LIST n FROM Employee has EmployeeName n) MINUS (LIST n FROM Department has DepartmentName n)",
  expands("the left's rows that are not in the right")),
 ("a row of whole-query scalars is read back item by item",
  "LIST THE COUNT OF Employee, THE COUNT OF Department",
  says("List, side by side: the number of each Employee ; the number of each Department")),
 ("a plain path reads as a sentence",
  "Employee has EmployeeName", says("each Employee has EmployeeName")),
 # A computed key -- `GROUPED BY round(s, 0)`, `WITHIN 1` -- was joined into the sentence
 # as a string and crashed `--check` on every one ever written. Two LiveSQLBench writers
 # found it on `WITHIN 1`, the whole-query partition the primer had just started to name.
 ("a computed group key is spelled in the sentence",
  "LIST c FROM Employee has EmployeeSalary s AND ALSO has EmployeeName n "
  "AND ALSO THE COUNT OF n GROUPED BY round(s / 100000, 0) AS c",
  says("grouped by round(s / 100000, 0)")),
 ("and so is a constant partition",
  "LIST n, r FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "AND ALSO THE RANK OF s WITHIN 1 AS r",
  says("partitioned by 1")),

 ("LIST names the columns first",
  "LIST n FROM Employee has EmployeeName n", says("List n for each Employee")),

 ("a variable is named in the sentence",
  "LIST n FROM Employee has EmployeeName n", says("(called n)")),

 # A sub-expression matches without joining, which is a relative clause in English. It used
 # to print the ConQuer brackets, leaving syntax in the middle of a sentence meant for a
 # reader who does not know the syntax.
 ("a sub-expression reads as a relative clause, not as brackets",
  "LIST n FROM Employee [has Department: 'ENG'] has EmployeeName n",
  says("that has Department is 'ENG',")),

 ("each verb reports the fact type it resolved to",
  "Employee has Department",
  resolved("Employee has", "EmployeeHasDepartment")),

 ("and what that fact type reaches",
  "Employee has Department", resolved("Employee has", "reaching Department")),

 ("a multi-hop path reports every step",
  "Employee has Assignment has Project",
  resolved("Assignment has", "Project")),

 ("a role reference reports which role of which fact type",
  "Employee has EmployeeHasManagerEmployee",
  resolved("Employee has", "EmployeeHasManagerEmployee role")),

 # -- Expanded: the abbreviations the lowering silently materialises -----------
 ("a denotation reports that the reference scheme was walked",
  "Employee has Department: 'ENG'", expands("reference scheme")),

 ("and names the value the comparison is really against",
  "Employee has Department: 'ENG'", expands("DepartmentCode")),

 ("an abstract denotation reports that it binds the instance, not the value",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Department d "
  "AND ALSO has EmployeeSalary s WHERE s > THE AVERAGE Employee [has Department: !d] "
  "has EmployeeSalary",
  expands("not to its identifying value")),

 # -- Requires: the reason the BIRD query silently returned nothing ------------
 ("reading an optional role is reported as a requirement",
  "Employee has EmployeeSalary", requires("must actually have")),

 ("and names the role, so the reader can judge it",
  "Employee has EmployeeSalary", requires("EmployeeSalary")),

 ("a mandatory role is not reported -- the list stays short enough to read",
  "Employee has EmployeeName", silent("requires")),

 ("a path through an optional foreign key is reported",
  "Employee has EmployeeHasManagerEmployee has EmployeeHasManagerManager",
  requires("must actually have")),

 # -- Worth checking ----------------------------------------------------------
 ("an aggregate warns about fan-out",
  "THE AVERAGE Employee has EmployeeSalary", checks("fans out")),

 ("a set comparison explains its quantifier",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "WHICH ARE ALL IN Employee: 4 has Assignment has Project",
  checks("whole set")),

 ("SOME explains that it is not correlated by position",
  "LIST n FROM Employee has EmployeeName n WHERE SOME Department has DepartmentCode: 'ENG'",
  checks("tied to the enclosing query only through variables")),

 ("a plain path warns about nothing",
  "Employee has EmployeeName", silent("checks")),

 # -- severity: what makes the report actionable rather than merely readable ---
 ("a dropped optional fact is a risk, not a note",
  "Employee has EmployeeSalary", risks(1)),

 ("a query with nothing optional carries no risk",
  "Employee has EmployeeName", risks(0)),

 ("an aggregate's fan-out warning is a caution, not a risk",
  "THE COUNT OF Employee", risks(0)),

 ("but averaging an optional value is a risk -- the absent rows are dropped",
  "THE AVERAGE Employee has EmployeeSalary", risks(1)),

 ("AND ALSO resumes at the head, so its operand resolves against the right type",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  resolved("Employee has", "EmployeeHasSalary")),

 # -- operators read back in words --------------------------------------------
 ("AND ALSO", "Employee has EmployeeName AND ALSO has Department", says("and also")),
 ("BUT NOT", "Employee has EmployeeName BUT NOT has Department", says("but not")),
 ("OR OTHERWISE",
  "Employee has Department: 'ENG' OR OTHERWISE has Department: 'HR'", says("or otherwise")),
 ("DISTINCT", "DISTINCT Employee has Department", says("the distinct")),
 ("ONLY (Fr)", "ONLY Employee has EmployeeName", says("only the start of")),
 ("a comparison reads as words",
  "Employee has EmployeeSalary > 100000", says("is greater than")),
 ("WHICH ARE ALL IN reads as a quantifier",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "WHICH ARE ALL IN Employee: 4 has Assignment has Project",
  says("which are all among")),
 ("IS DISJOINT FROM reads as a quantifier",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
  "IS DISJOINT FROM Employee: 2 has Assignment has Project",
  says("which share none of")),
 ("an aggregate reads as words", "THE COUNT OF Employee", says("the number of")),
 # Finding 58: the one real fan trap in 143 authoring attempts multiplied a *projection* and
 # nothing said so. Two independent branches from one head that each reach many per head are
 # a cross product per head, and that is almost never what a LIST meant.
 ("two fanning branches from one head are a caution",
  "LIST n, h, p FROM Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h "
  "AND ALSO has Assignment has Project has ProjectName p",
  checks("each reach many")),
 ("and the caution names what each branch reaches, since both begin the same way",
  "LIST n, h, p FROM Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h "
  "AND ALSO has Assignment has Project has ProjectName p",
  checks("AssignmentHours")),
 ("and the other",
  "LIST n, h, p FROM Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h "
  "AND ALSO has Assignment has Project has ProjectName p",
  checks("ProjectName")),
 ("one fanning branch is often the point, and is not a caution",
  "LIST n, h FROM Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h",
  not_checks("each reach many")),
 ("two functional branches do not multiply",
  "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  not_checks("each reach many")),
 ("continuing the second branch from the first is the fix, and is not a caution",
  "LIST n, h, p FROM Employee has EmployeeName n AND ALSO has Assignment a "
  "AND ALSO a has AssignmentHours h AND ALSO a has Project has ProjectName p",
  not_checks("each reach many")),
 ("under an aggregate the aggregate's own caution speaks, not this one",
  "THE COUNT OF Employee has Assignment has AssignmentHours h AND ALSO has Assignment has Project",
  not_checks("each reach many")),

 # conquer-2026.md §9: BIRD Q12 took THE MAXIMUM of an entity type and got a CDS code back.
 # Well-formed, so nothing could refuse it; --explain can at least say what it means.
 ("an aggregate over an entity type is a caution",
  "THE MAXIMUM Employee has Department",
  checks("the max of its identifier")),
 ("confluence reads as 'also showing', and says the gathered values may be empty",
  "LIST n, s FROM has EmployeeSalary AS s EACH Employee has EmployeeName n",
  says("also showing s")),
 ("confluence explains its outer join",
  "LIST n, s FROM has EmployeeSalary AS s EACH Employee has EmployeeName n",
  expands("come back empty where absent")),
 # What used to read back as "..." -- everything with an AS, every grouped aggregate, every
 # scalar. A reader checking a query before it runs cannot check an ellipsis.
 # finding 128: a path that enters one fact type twice, by different roles, is talking about
 # two different instances of it and pairs every one with every other. No existing check
 # speaks -- the finding-109 caution wants two fanning branches from one head, and this is
 # one branch folding back on itself. It fires on 2 of 2,075 recorded answers, both wrong,
 # against a 70% base rate.
 ("entering one fact type twice by different roles is cautioned",
  "LIST n, h FROM Employee has EmployeeName n AND ALSO has Assignment a "
  "AND ALSO a has Project p AND ALSO p is of Assignment has AssignmentHours h",
  checks("enters Assignment twice")),
 ("but entering it once is not",
  "LIST n, h FROM Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h",
  not_checks("twice, by different roles")),

 # finding 117: an ordered cut under DISTINCT by a key the list drops has no defined answer
 ("an ordered cut under DISTINCT by a dropped key is cautioned",
  "LIST n FROM DISTINCT Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h "
  "ORDERED WITH h DESCENDING THE FIRST 2",
  checks("which it drops")),
 ("but not when the ordering key is listed",
  "LIST n, h FROM DISTINCT Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h "
  "ORDERED WITH h DESCENDING THE FIRST 2",
  not_checks("which it drops")),
 ("nor without DISTINCT",
  "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has AssignmentHours h "
  "ORDERED WITH h DESCENDING THE FIRST 2",
  not_checks("which it drops")),

 ("a grouped aggregate bound with AS reads back in full",
  "LIST t FROM Bond b has BondType t AND ALSO THE COUNT OF b GROUPED BY t AS n "
  "ORDERED WITH n DESCENDING THE FIRST 1" if False else
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c",
  says("the number of e, grouped by d (called c)")),
 ("`x IN` says what is aggregated",
  "THE AVERAGE c IN (Department d AND ALSO THE COUNT OF Employee [has Department d] "
  "GROUPED BY d AS c)",
  says("the average c in")),
 ("arithmetic in a projection reads as written",
  "LIST n, s * 100 / 12 FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
  says("List n, s * 100 / 12")),
 ("a scalar conditional reads as if-then-else",
  "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
  "WHERE IF s > 170000 THEN 1 ELSE 0 = 1",
  says("if s > 170000 then 1 else 0")),
 ("nothing in a full query reads as an ellipsis",
  "LIST d, c FROM Employee e has Department has DepartmentCode d "
  "AND ALSO THE COUNT OF e GROUPED BY d AS c ORDERED WITH c DESCENDING THE FIRST 1",
  lacks("...")),
 ("ORDERED reads as words",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING",
  says("ordered by s descending")),

 # -- the row limit. It is the one construct whose answer depends on an order the query may
 # not have pinned down, so what --explain says about it is the whole safety story.
 ("a limit reads back as words",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 3",
  says("keeping the first 3")),
 ("an offset reads back too",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 2 AFTER 1",
  says("keeping 2 after the first 1")),
 ("a limit over an ordering warns about ties",
  "LIST s FROM Employee has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 3",
  checks("tied on s are in no defined order")),
 ("a limit with no ordering is a risk, not a caution",
  "LIST n FROM Employee has EmployeeName n THE FIRST 3", risks(1)),
 ("and it says what to do about it",
  "LIST n FROM Employee has EmployeeName n THE FIRST 3", checks("Add ORDERED WITH")),
 # EmployeeName is mandatory, so nothing else in this query raises a risk: the assertion is
 # about the limit alone.
 ("a per-group limit says which group",
  "LIST d, n FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n "
  "AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 1 PER d",
  says("keeping the first 1 for each d")),
 ("an ordered limit is not a risk",
  "LIST n FROM Employee has EmployeeName n ORDERED WITH n DESCENDING THE FIRST 3",
  risks(0)),
]


def check(interp, expect):
    kind, arg = expect
    if kind == "sentence":
        return (arg.lower() in interp.text().lower()), interp.text()
    if kind == "resolved":
        a, b = arg
        hit = any(a.lower() in t.lower() and b.lower() in m.lower()
                  for t, m in interp.resolved)
        return hit, "; ".join("%s -> %s" % r for r in interp.resolved) or "(nothing resolved)"
    if kind == "validates":
        return (True, "")            # handled by the caller, which has the model
    if kind == "risks":
        return (len(interp.risks) == arg), "%d risk(s): %s" % (
            len(interp.risks), "; ".join(f.message[:60] for f in interp.risks) or "none")
    if kind == "lacks":
        text = " ".join(interp.sentence)
        return (arg not in text), ("%r absent, as it must be" % arg if arg not in text
                                   else "sentence still contains %r: %s" % (arg, text))
    if kind == "not_checks":
        hit = any(arg.lower() in g.lower() for g in interp.checks)
        return (not hit), ("absent, as it must be" if not hit
                           else "checks mention it: " + "; ".join(interp.checks))
    if kind == "silent":
        got = {"requires": interp.requires, "checks": interp.checks,
               "expanded": interp.expanded}[arg]
        return (not got), ("empty" if not got else "; ".join(got))
    got = {"expanded": interp.expanded, "requires": interp.requires,
           "checks": interp.checks}[kind]
    hit = any(arg.lower() in g.lower() for g in got)
    return hit, "; ".join(got) or "(empty)"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if not os.path.exists(args.model):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2
    model = json.load(open(args.model))
    lexicon = parser_mod.Lexicon(model)

    cases = [c for c in CASES if not args.only or args.only.lower() in c[0].lower()]
    passed = 0
    for name, query, expect in cases:
        try:
            interp = verb_mod.explain(model, query, lexicon)
            ok, detail = check(interp, expect)
        except Exception as e:
            ok, detail = False, "%s: %s" % (type(e).__name__, e)
        passed += ok
        if ok:
            print("ok    %-56s %s" % (name, detail[:60] if args.verbose else ""))
        else:
            print("FAIL  %s\n        %s\n        got: %s" % (name, query, detail[:400]))
    print("\n%d passed, %d failed, %d total" % (passed, len(cases) - passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
