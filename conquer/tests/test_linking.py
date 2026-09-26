#!/usr/bin/env python3
"""Schema linking: what a question is about, and what it is not about.

Every case is a pair. A linker that keeps the whole model has perfect recall and is useless, so
each positive -- this concept must survive -- is matched by a negative, a concept that must be
dropped. The measured version of the same trade-off is `bench/pilot/linking.py`, which scores
recall against the tables BIRD's gold SQL touches and reports what share of the model was kept.

Two of the negatives are regression guards for defects this found in its own first hour: a
tokeniser that did not split camelCase, so `IncomeAmount` matched no question ever asked, and a
stemmer that took `employees` to `employe` while `Employee` stayed `employee`.

    test_linking.py [--model M] [-v]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import link as link_mod              # noqa: E402
import conquer as driver             # noqa: E402

# (name, question, must keep, must drop)
CASES = [
 ("a question about two types keeps both, and what joins them",
  "Which employees work on the Apollo project?",
  ["Employee", "Project", "Assignment"], ["Party", "PartyAbn"]),

 ("and does not keep the types it never mentions",
  "List the departments and their budgets",
  ["Department", "DepartmentBudget"], ["Project", "Party", "ProjectPriority"]),

 # The tokeniser has to split a name the way a question says it, or a model whose concepts
 # are `EmployeeSalary` and `DepartmentBudget` matches nothing at all.
 ("a camelCase name is found by the word inside it",
  "What is the highest salary?", ["EmployeeSalary"], ["ProjectName"]),

 ("a plural in the question finds the singular in the model",
  "How many employees are there?", ["Employee"], ["Party"]),

 # Rule 6b puts the values a column holds on the value type, which is what lets a literal in
 # the question say which column the filter is on rather than merely which table.
 ("a literal in the question links the value type whose domain holds it",
  "How many employees have gender 'X'?", ["EmployeeGender"], ["ProjectPriority"]),

 # The reverse engineer knew `emp_name` was `EmployeeName` and that `emp` meant `employee`.
 # Rule 10 used both and wrote neither down until `terms` existed; without them a question
 # that says what the DBA says matches nothing.
 ("a question using the column's own spelling finds the concept",
  "What is in emp_name?", ["EmployeeName"], ["ProjectName"]),

 ("and an abbreviation the reverse engineer expanded still matches",
  "How many emp records are there?", ["Employee"], ["Party"]),

 ("an entity is kept with whatever identifies it, or a query cannot name an instance",
  "Which project has the highest priority?", ["Project", "ProjectCode", "ProjectHasCode"],
  ["PartyGivenName"]),
]


def run(model, linker, case):
    name, question, want, drop = case
    keep = linker.relevant(question)
    names = {c["id"]: c["name"] for c in model["concepts"]}
    kept = {names[c] for c in keep if c in names}
    missing = [w for w in want if w not in kept]
    wrong = [d for d in drop if d in kept]
    if missing:
        return False, "dropped %s; kept %s" % (", ".join(missing), sorted(kept)[:8])
    if wrong:
        return False, "kept %s, which this question is not about" % ", ".join(wrong)
    return True, "%d of %d concepts" % (len(keep), len(model["concepts"]))


def nothing_matches(model, linker):
    """A question with no overlap should keep nothing rather than everything."""
    keep = linker.relevant("qwertyuiop zxcvbnm")
    return (not keep), "kept %d concepts" % len(keep)


def schema_still_renders(model, linker):
    """--schema --for has to produce a usable listing, not a traceback."""
    text = driver.describe(model, "Which employees work on the Apollo project?")
    # a type the narrowing drops is named once, on the line that says what was left out, so
    # a reader can widen the view without guessing -- and nowhere else
    body = [l for l in text.split("\n") if not l.strip().startswith("Not shown")]
    hidden = [l for l in text.split("\n") if l.strip().startswith("Not shown")]
    return ("Employee" in text and not any("Party" in l for l in body)
            and any("Party" in l for l in hidden) and "Predicate readings" in text,
            "%d lines" % len(text.split("\n")))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not os.path.exists(args.model):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % args.model)
        return 2

    model = json.load(open(args.model))
    linker = link_mod.Linker(model)
    checks = [(c[0], lambda c=c: run(model, linker, c)) for c in CASES]
    checks.append(("a question the model has no words for keeps nothing",
                   lambda: nothing_matches(model, linker)))
    checks.append(("--schema --for renders the pruned model",
                   lambda: schema_still_renders(model, linker)))
    passed = failed = 0
    for name, fn in checks:
        ok, note = fn()
        if ok:
            passed += 1
            print("ok    %-62s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s" % (name, note))
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
