#!/usr/bin/env python3
"""The PostgreSQL half of test_access.py against a live server: which logins are refused, and
that the refusals are about something real.

Needs `psycopg` and an administrator's DSN in CONCEPTUAL_LAYER_TEST_DSN; it says so and passes
without them. It makes its own database and four roles, and drops them. Each login is checked
two ways, what `access.from_entry` says and what the login can actually do, because a refusal
of a login that could do no harm passes every "is it refused" test.

    CONCEPTUAL_LAYER_TEST_DSN=postgresql://postgres@localhost/postgres test_pg_access.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "mcp"))
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import access                                                           # noqa: E402
import conquer as driver                                                # noqa: E402

DB = "conceptual_layer_access_test"
ROLES = ("cl_reader", "cl_writer", "cl_creator", "cl_files")
MODEL = {"mapping": {"tables": [{"id": "t1", "name": "t"}], "columns": []}}
LIFTED = "BEGIN READ WRITE; %s; COMMIT"

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed += ok
    failed += not ok
    print("%-5s %s%s" % ("ok" if ok else "FAIL", name,
                         ("\n        " + detail) if detail and not ok else ""))


def on(dsn, **changes):
    return psycopg.conninfo.make_conninfo(dsn, **changes)


def refusal(dsn, trusted=False):
    """The AccessError's text for this login, or "" when it is served."""
    conn = driver._Server(dsn)
    entry = dict(dsn=dsn, trusted=True) if trusted else dict(dsn=dsn)
    try:
        access.from_entry(entry, MODEL, conn)
        return ""
    except access.AccessError as e:
        return str(e)
    finally:
        conn.close()


def runs(dsn, sql):
    conn = driver._Server(dsn)
    try:
        conn.execute(sql, ())
        return True
    except psycopg.Error:
        return False
    finally:
        conn.close()


def setup(admin):
    drop(admin)
    admin.execute("CREATE DATABASE %s" % DB)
    for role in ROLES:
        admin.execute("CREATE ROLE %s LOGIN" % role)
    admin.execute("GRANT pg_execute_server_program TO cl_files")


def drop(admin):
    admin.execute("DROP DATABASE IF EXISTS %s" % DB)
    for role in ROLES:
        admin.execute("DROP ROLE IF EXISTS %s" % role)


def main():
    dsn = os.environ.get("CONCEPTUAL_LAYER_TEST_DSN")
    if not dsn:
        print("CONCEPTUAL_LAYER_TEST_DSN is not set: no live PostgreSQL checks run")
        return 0
    admin = psycopg.connect(dsn, autocommit=True)
    setup(admin)
    try:
        here = on(dsn, dbname=DB)
        with psycopg.connect(here, autocommit=True) as db:
            db.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            db.execute("CREATE TABLE t (id int)")
            db.execute("CREATE TABLE u (id int)")
            db.execute("INSERT INTO t VALUES (1), (2), (3)")
            db.execute("GRANT SELECT ON t TO cl_reader, cl_writer, cl_creator, cl_files")
            db.execute("GRANT DELETE ON u TO cl_writer")
            db.execute("GRANT DELETE ON t TO cl_writer")
            db.execute("GRANT CREATE ON SCHEMA public TO cl_creator")

            def rows():
                return db.execute("SELECT count(*) FROM t").fetchone()[0]

            reader = on(here, user="cl_reader")
            writer = on(here, user="cl_writer")
            creator = on(here, user="cl_creator")
            files = on(here, user="cl_files")

            check("a login with only SELECT is served", refusal(reader) == "", refusal(reader))
            check("and the read-only session refuses it a write",
                  not runs(reader, "DELETE FROM t"))
            check("and lifting the session does not help: its grants refuse",
                  not runs(reader, LIFTED % "DELETE FROM t") and rows() == 3)

            why = refusal(writer)
            check("a login that can delete is refused, and told which table",
                  "public.t" in why and "public.u" in why, why)
            check("rightly: `BEGIN READ WRITE` lifts the read-only session",
                  not runs(writer, "DELETE FROM t WHERE id = 1") and
                  runs(writer, LIFTED % "DELETE FROM t WHERE id = 1") and rows() == 2)
            check("and a DO block that commits needs no second statement",
                  runs(writer, "DO $$ BEGIN PERFORM set_config('default_transaction_read_only', "
                               "'off', false); COMMIT; DELETE FROM t WHERE id = 2; END $$")
                  and rows() == 1)
            check("trusted serves it anyway", refusal(writer, trusted=True) == "")

            why = refusal(creator)
            check("a login that can create in a schema is refused", "schema public" in why, why)
            check("rightly", runs(creator, LIFTED % "CREATE TABLE made (i int)"))

            why = refusal(files)
            check("a login that can run programs on the server is refused",
                  "pg_execute_server_program" in why, why)
            check("rightly: COPY TO PROGRAM is not a write, the read-only session allows it",
                  runs(files, "COPY (SELECT 1) TO PROGRAM 'cat > /dev/null'"))

            # what the catalogue checks cannot see, and mcp/README.md says so
            check("a SELECT-only login can still lift the session for a large object",
                  runs(reader, LIFTED % "SELECT lo_create(0)"))
            check("and a temporary table",
                  runs(reader, LIFTED % "CREATE TEMP TABLE scratch (i int)"))
    finally:
        drop(admin)
        admin.close()
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        import psycopg
        import psycopg.conninfo
    except ImportError:
        print("psycopg is not installed: no live PostgreSQL checks run")
        sys.exit(0)
    sys.exit(main())
