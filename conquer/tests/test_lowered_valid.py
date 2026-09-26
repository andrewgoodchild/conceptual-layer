#!/usr/bin/env python3
"""Every lowered block must satisfy model/model.md, checked by the project's own validator.

This is the regression guard for a defect the altitude review found: non-node values -- an
aggregate's result, a constant -- were smuggled back as nodes typed by synthetic concepts
that exist in no model, so the compiler emitted IR it would itself reject. model.md §4.6 says
a Value is a node, a constant, a calculation or a parameter; only the first is a node.

    test_lowered_valid.py [--model M]
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

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
from model import validate         # noqa: E402

QUERIES = [
 "Employee has EmployeeName",
 "LIST d, n FROM Employee has Department has DepartmentCode d AND ALSO has EmployeeName n AND ALSO has EmployeeSalary s ORDERED WITH s DESCENDING THE FIRST 1 PER d",
 "LIST dn FROM Department d [has DepartmentName dn] WHICH ARE ALL IN (LIST x FROM Employee e has Department x AND ALSO THE COUNT OF e GROUPED BY x AS c ORDERED WITH c DESCENDING THE FIRST 1)",
 "LIST n, IF s > 170000 THEN 'high' ELSE 'low' FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
 "THE AVERAGE c IN (Department d AND ALSO THE COUNT OF Employee [has Department d] GROUPED BY d AS c)",
 "LIST n, h FROM has Assignment has AssignmentHours AS h EACH Employee has EmployeeName n",
 "LIST n FROM Employee has EmployeeName n AND ALSO has Department: 'ENG'",
 "THE COUNT OF Employee",
 "THE AVERAGE Employee has EmployeeSalary",
 "THE COUNT OF Employee / 12",
 "LIST n, s / 12 FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
 "LIST s * 100 / 200000 FROM Employee has EmployeeSalary s",
 "LIST d, c FROM Employee e has Department has DepartmentCode d "
 "AND ALSO THE COUNT OF e GROUPED BY d AS c",
 "LIST n FROM Employee has EmployeeName n AND ALSO OPTIONALLY has EmployeeSalary s",
 "LIST n FROM Employee has EmployeeName n BUT NOT has Department: 'ENG'",
 "LIST n FROM Employee has EmployeeName n AND ALSO has Assignment has Project "
 "WHICH ARE ALL IN Employee: 4 has Assignment has Project",
 "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s "
 "WHERE s > THE AVERAGE Employee has EmployeeSalary",
 "LIST c, n FROM Manager [has ManagerCarSpace c] has EmployeeName n",
 "LIST n, h FROM Employee [has EmployeeName n] has Assignment has AssignmentHours h",
]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    args = p.parse_args(argv)
    if not os.path.exists(args.model):
        print("fixture missing: run ./run-tests.sh first")
        return 2

    model = json.load(open(args.model))
    lexicon = parser_mod.Lexicon(model)
    passed = 0
    for q in QUERIES:
        try:
            block, _, _ = driver.transpile(model, q, lexicon)
        except Exception as e:
            print("FAIL  %s\n        did not compile: %s" % (q[:70], e))
            continue
        probe = dict(model)
        probe["queries"] = [{"id": "q", "name": "probe", "body": block}]
        ix = validate.index_model(probe)
        findings = validate.Findings()
        validate.check_query(probe["queries"][0], ix, findings)
        errors = [f for f in findings.items if f[0] == "error"]
        if errors:
            print("FAIL  %s" % q[:70])
            for _, check, where, message in errors[:4]:
                print("        [%s] %s: %s" % (check, where, message[:66]))
        else:
            passed += 1
            print("ok    %s" % q[:70])
    print("\n%d passed, %d failed, %d total" % (passed, len(QUERIES) - passed, len(QUERIES)))
    return 0 if passed == len(QUERIES) else 1


if __name__ == "__main__":
    sys.exit(main())
