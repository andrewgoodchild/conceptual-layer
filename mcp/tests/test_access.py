#!/usr/bin/env python3
"""What a restricted caller sees, and what its connection refuses, against the company fixture.

Standard library only, so it runs whether or not the `mcp` package is installed: the
restriction is the part of the server that must not regress silently. Each case is a pair --
what must be gone, and what must still be there -- because a restriction that hides
everything passes every "is it hidden" test.

The PostgreSQL half (a login's privileges, row-level security) is exercised against a stand-in
connection that answers the three catalogue queries `access.from_entry` asks; there is no
server in this suite.

    test_access.py [-v]
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(ROOT, ".work")
sys.path.insert(0, os.path.join(ROOT, "mcp"))
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import access                                                           # noqa: E402
import conquer as driver                                                # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed += ok
    failed += not ok
    print("%-5s %s%s" % ("ok" if ok else "FAIL", name,
                         ("\n        " + detail) if detail and not ok else ""))


def names(model):
    return {c["name"] for c in model["concepts"]}


class FakePostgres:
    """Answers what the login is (superuser, BYPASSRLS, roles it can climb to),
    has_table_privilege, has_column_privilege and relrowsecurity from dicts."""

    def __init__(self, tables, columns, rls, login=(False, False, None)):
        self.tables, self.columns, self.rls, self.login = tables, columns, rls, login

    def execute(self, sql, params):
        if "rolsuper" in sql:
            return type("Cursor", (), {"fetchone": lambda self_: self.login})()
        bare = params[0].split(".")[-1].strip('"')
        if "has_table_privilege" in sql:
            got = self.tables.get(bare, False)
        elif "has_column_privilege" in sql:
            got = (bare, params[1]) in self.columns
        else:
            got = bare in self.rls
        return type("Cursor", (), {"fetchone": lambda self_: (got,)})()


def main(argv):
    db, path = os.path.join(WORK, "company.sqlite"), os.path.join(WORK, "company.ccm.json")
    if not (os.path.exists(db) and os.path.exists(path)):
        print("skip  no .work/company fixture: run run-tests.sh first")
        return 0
    model = json.load(open(path))

    same = access.Access().restrict(model)
    check("no restriction leaves the model alone", same is model)

    # -- a hidden table
    acc = access.Access(hide=["assignment"])
    m = acc.restrict(model)
    check("a hidden table's types are gone", not {"Assignment", "AssignmentHours"} & names(m),
          str(sorted(names(m))))
    check("and the rest are not", {"Employee", "Project", "Department", "EmployeeSalary"} <= names(m))
    check("no constraint refers to a dropped role",
          not any("Assignment" in json.dumps(k) for k in m["constraints"]))
    check("the mapping no longer has the table",
          all(t["name"] != "assignment" for t in m["mapping"]["tables"]))
    text = driver.describe(m, relational=True)
    check("the description never names it", "assignment" not in text.lower(), text[:300])
    big = dict(m, concepts=m["concepts"] + [
        {"id": "et.Extra%d" % i, "name": "Extra%d" % i, "kind": "entity"} for i in range(20)])
    narrowed = driver.describe(big, "which employees work on which projects")
    check("a narrowed view's 'not shown' list does not name it",
          "Assignment" not in narrowed and "Not shown" in narrowed, narrowed[:400])

    # -- a hidden column
    m = access.Access(hide=["employee.salary"]).restrict(model)
    check("a hidden column's fact type and value type are gone",
          not {"EmployeeHasSalary", "EmployeeSalary"} & names(m))
    check("and the entity and its other facts stay", {"Employee", "EmployeeName"} <= names(m))

    # -- an allow list
    m = access.Access(tables=["employee", "department"]).restrict(model)
    kept = {c["name"] for c in m["concepts"] if c["kind"] == "entity"}
    check("an allow list keeps only its tables' entity types",
          kept == {"Employee", "Department"}, str(kept))
    check("a reference into a hidden table goes with it",
          "ManagerHasCarSpace" not in names(m) and "EmployeeHasManager" in names(m))

    # -- free text that names a hidden table
    noisy = json.loads(json.dumps(model))
    for c in noisy["concepts"]:
        if c["name"] == "EmployeeName":
            c["dataQuality"] = [{"caution": "names repeat; join assignment to tell them apart"},
                                {"caution": "trailing spaces in 4 values"}]
    m = access.Access(hide=["assignment"]).restrict(noisy)
    dq = next(c for c in m["concepts"] if c["name"] == "EmployeeName").get("dataQuality", [])
    check("a caution naming a hidden table is dropped, the others kept",
          len(dq) == 1 and "trailing" in json.dumps(dq), json.dumps(dq))

    # -- enforcement: the connection refuses
    conn = access.Access(hide=["assignment", "employee.salary"]).guard(
        sqlite3.connect("file:%s?mode=ro" % db, uri=True))

    def refused(sql):
        try:
            conn.execute(sql).fetchall()
            return False
        except sqlite3.DatabaseError:
            return True

    check("SQLite: reading a hidden table is refused", refused("SELECT * FROM assignment"))
    check("SQLite: reading a hidden column is refused", refused("SELECT salary FROM employee"))
    check("SQLite: SELECT * over a hidden column is refused", refused("SELECT * FROM employee"))
    check("SQLite: a view over a hidden table is refused", refused("SELECT * FROM busy_employee"))
    check("SQLite: the catalogue is refused", refused("SELECT name FROM sqlite_master"))
    check("SQLite: pragmas are refused", refused("SELECT * FROM pragma_table_info('assignment')"))
    check("SQLite: everything else still reads",
          conn.execute("SELECT emp_name FROM employee ORDER BY emp_nr").fetchone() == ("Ada Lovelace",))
    conn = access.Access(tables=["department"]).guard(
        sqlite3.connect("file:%s?mode=ro" % db, uri=True))
    check("SQLite: an allow list refuses what it does not list", refused("SELECT * FROM project"))

    # -- PostgreSQL: the login's own privileges, read from the database
    pg_entry = {"dsn": "postgresql://analyst@db/x"}
    grants = dict(tables={"employee": True, "department": True, "project": False},
                  columns={("project", "proj_code"), ("project", "proj_name")},
                  rls={"employee"})
    acc = access.from_entry(pg_entry, model, FakePostgres(**grants))
    m = acc.restrict(model)
    ents = {c["name"] for c in m["concepts"] if c["kind"] == "entity"}
    check("a login sees the tables it may SELECT, and a table it has some columns of",
          ents == {"Employee", "Department", "Project"}, str(ents))
    check("and not the columns of that table it may not",
          "ProjectPriority" not in names(m) and "ProjectName" in names(m))
    gender = next(c for c in m["concepts"] if c["name"] == "EmployeeGender")
    dept = next(c for c in m["concepts"] if c["name"] == "DepartmentCode")
    check("under row-level security a profiled value domain is dropped",
          "restriction" not in gender, json.dumps(gender)[:200])
    check("and kept on a table without it",
          "restriction" not in dept or dept["restriction"].get("values") is not None)

    class Broken:
        def execute(self, *a):
            raise RuntimeError("permission denied for function has_table_privilege")
    def refuses(name, entry, conn, phrase):
        try:
            access.from_entry(entry, model, conn)
            check(name, False, "no AccessError")
        except access.AccessError as e:
            check(name, phrase in str(e), str(e))

    refuses("privileges that cannot be read refuse rather than show everything",
            pg_entry, Broken(), "could not read")
    refuses("a superuser login is refused: its grants say nothing",
            pg_entry, FakePostgres(**grants, login=(True, False, None)), "superuser")
    refuses("so is a login with BYPASSRLS",
            pg_entry, FakePostgres(**grants, login=(False, True, None)), "BYPASSRLS")
    refuses("so is one that can SET ROLE to a role it does not inherit",
            pg_entry, FakePostgres(**grants, login=(False, False, "admin")), "SET ROLE to admin")
    acc = access.from_entry(dict(pg_entry, trusted=True), model,
                            FakePostgres(**grants, login=(True, False, None)))
    check("unless the entry is marked trusted", "Project" in names(acc.restrict(model)))
    refuses("`role` is refused: a role set after connecting is undone by the caller's SQL",
            dict(pg_entry, role="analyst"), FakePostgres(**grants), "role")
    refuses("`tables` and `hide` are refused on PostgreSQL: nothing there enforces them",
            dict(pg_entry, hide=["audit_log"]), FakePostgres(**grants), "SQLite only")

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
