#!/usr/bin/env python3
"""The MCP server's tools, called as the functions they are, against the company fixture.

Skips, saying so, when the `mcp` package is not installed: it is the one dependency the
repository does not carry, and the suite must pass without it. When it is installed, the
second half speaks the protocol: a client over stdio lists the tools and calls one.

    test_server.py [-v]
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(ROOT, ".work")

try:
    import mcp                                                          # noqa: F401
except ImportError:
    print("skip  mcp package not installed: the server is untested here (pip install mcp)")
    sys.exit(0)

sys.path.insert(0, os.path.join(ROOT, "mcp"))
import server                                                           # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed += ok
    failed += not ok
    print("%-5s %s%s" % ("ok" if ok else "FAIL", name, ("\n        " + detail) if detail and not ok else ""))


def main(argv):
    verbose = "-v" in argv
    db, model = os.path.join(WORK, "company.sqlite"), os.path.join(WORK, "company.ccm.json")
    if not (os.path.exists(db) and os.path.exists(model)):
        print("skip  no .work/company fixture: run run-tests.sh first")
        return 0
    server.DATABASES["company"] = {"sqlite": db, "model": model}

    listing = server.list_databases()
    check("list_databases names the fixture", "company" in listing and "sqlite" in listing, listing)

    text = server.describe_schema("company")
    check("describe_schema lists the types", "Entity types" in text and "Employee" in text)
    check("describe_schema has the identification section", "Identification" in text)
    narrowed = server.describe_schema("company", question="how many employees per department")
    check("a small schema is described whole even with a question", narrowed == text,
          "%d vs %d" % (len(narrowed), len(text)))
    # narrowing itself, on the CLI path the server uses for a large schema: what it leaves
    # out is named, not counted
    big = dict(model_json := __import__("json").load(open(model)))
    big["concepts"] = list(big["concepts"]) + [
        {"id": "et.Extra%d" % i, "name": "Extra%d" % i, "kind": "entity"} for i in range(20)]
    listing = server.driver.describe(big, "how many employees per department")
    check("a narrowed listing names what it left out", "Not shown" in listing and "Extra0" in listing,
          listing[:300])
    rel = server.describe_schema("company", relational=True)
    check("relational puts the columns beside the types", '[table "' in rel and "." in rel)

    out = server.run_query("company", "LIST n FROM Employee has EmployeeName n", limit=3)
    check("run_query returns the reading, the SQL and rows",
          "SQL:" in out and "SELECT" in out and "rows" in out, out[:300])
    out = server.run_query("company", "THE SUM OF Department has DepartmentBudget AND ALSO is of Employee")
    check("a refusal comes back as text, not an exception", "refused" in out or "risk" in out.lower() or "SQL:" in out)
    out = server.run_query("company", "LIST FROM nothing here")
    check("a parse error comes back as text", "parse error" in out, out[:200])

    out = server.explain_query("company", "THE COUNT OF Employee has Department has DepartmentName: 'Engineering'")
    check("explain_query reads the query back", "Engineering" in out or "count" in out.lower(), out[:200])

    out = server.run_sql("company", "SELECT COUNT(*) AS n FROM employee", limit=5)
    check("run_sql runs plain SQL", "n" in out and "row" in out, out[:200])
    out = server.run_sql("company", "CREATE TABLE zz (a INT)")
    check("the connection is read-only", "SQL error" in out and "readonly" in out.lower() or "read-only" in out.lower(), out[:200])

    brief = server.writing_brief("conquer")
    check("the ConQuer brief carries the primer", "run_query" in brief and "ConQuer" in brief and len(brief) > 5000)
    brief = server.writing_brief("sql")
    check("the SQL brief points at run_sql and the relational listing", "run_sql" in brief and "relational" in brief)

    # over the protocol: a client on stdio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def over_stdio():
        params = StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(ROOT, "mcp", "server.py"), "--sqlite", db, "--model", model])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                prompts = {p.name for p in (await session.list_prompts()).prompts}
                result = await session.call_tool("describe_schema", {"database": "company"})
                text = "".join(getattr(c, "text", "") for c in result.content)
                return tools, prompts, text

    try:
        tools, prompts, text = asyncio.run(over_stdio())
        check("stdio: the six tools are listed",
              {"list_databases", "build_model", "describe_schema", "explain_query", "run_query", "run_sql"} <= tools, str(tools))
        check("stdio: the brief is a prompt", "writing_brief" in prompts, str(prompts))
        check("stdio: describe_schema answers", "Employee" in text, text[:200])
    except Exception as e:                                             # noqa: BLE001
        check("stdio round trip", False, "%s: %s" % (type(e).__name__, e))

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
