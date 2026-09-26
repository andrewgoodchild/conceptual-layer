#!/usr/bin/env python3
"""The conceptual layer as an MCP server: the tools a blind writer had, over the protocol.

Every measurement in `bench/` was made with an agent that had two commands beside the
question -- `./schema`, which describes the database in the model's terms, and `./try`,
which runs a candidate and shows rows -- and a page of instructions. This server is those
tools for any MCP client. An agent that writes SQL gets the description in relational terms
(what identifies each thing and which columns hold it, what is inside the JSON columns, the
value domains and cautions from profiling the rows, every relationship with the columns
that carry it) and a read-only runner. One that writes ConQuer gets the listing, the
primer, the compiler's English reading of its query and its refusals. The description is
where the measured value is -- findings 156 and 157: saying what identifies a thing and what
is inside the documents -- and the language is optional; docs/07 has the numbers.

    python3 mcp/server.py --config mcp/databases.json     # stdio, for a client's config file
    python3 mcp/server.py --sqlite path/to.sqlite         # one database, model built on demand

Needs the `mcp` package, the one dependency outside the standard library in this repository
and needed only here; `psycopg` for a PostgreSQL database. Every connection is read-only.
"""
import argparse
import functools
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import conquer as driver              # noqa: E402
import parser as parser_mod           # noqa: E402
import sql as sql_mod                 # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP   # noqa: E402
except ImportError:
    # Without the package, `mcp` resolves to this directory and the error names the wrong thing.
    sys.exit("the MCP server needs the `mcp` package: pip install mcp (Python 3.10 or later)")

mcp = FastMCP("conceptual-layer")

# name -> {"sqlite": path} or {"dsn": url}, plus "model": path (built on demand for SQLite)
DATABASES = {}
MODEL_DIR = os.path.join(HERE, "models")
# The flags the LiveSQLBench tier's models were built with (bench/livesql/README.md), plus
# the two that were measured afterwards: what identifies a thing, and the schema inside
# the JSON columns. Every pass reads the data, which is why a model wants the database.
BUILD_FLAGS = ["--infer-domains", "--infer-enforced", "--infer-partitions", "--merge-domains",
               "--profile", "--expand-names", "--infer-identifiers", "--infer-json"]


# --------------------------------------------------------------------------- databases

def _entry(name):
    if name not in DATABASES:
        raise ValueError("no database called %r; list_databases says which there are" % name)
    return DATABASES[name]


def _model_path(name):
    e = _entry(name)
    if e.get("model"):
        return e["model"]
    return os.path.join(MODEL_DIR, "%s.ccm.json" % name)


@functools.lru_cache(maxsize=32)
def _loaded(path, mtime):
    """The model, its lexicon and its emitter, built once per file version."""
    model = json.load(open(path))
    lexicon = parser_mod.Lexicon(model)
    emitter = sql_mod.Emitter(model) if model.get("mapping") else None
    return model, lexicon, emitter


def _model(name):
    path = _model_path(name)
    if not os.path.exists(path):
        raise ValueError("%s has no model yet: call build_model(%r) first" % (name, name))
    return _loaded(path, os.path.getmtime(path))


def _connect(name):
    e = _entry(name)
    if e.get("sqlite"):
        return sqlite3.connect("file:%s?mode=ro" % e["sqlite"], uri=True)
    if e.get("dsn"):
        return driver._Server(e["dsn"])
    raise ValueError("%s names neither a sqlite file nor a dsn" % name)


def _rows(conn, statement, params, limit):
    try:
        cur = conn.execute(statement, params)
    except driver.DB_ERRORS as e:
        return "SQL error: %s\n  %s" % (e, statement)
    return driver.render_rows(cur, limit)


# --------------------------------------------------------------------------- tools

@mcp.tool()
def list_databases() -> str:
    """The databases this server can describe and query, and whether each has a model yet.
    A model is what the description is read from; build_model makes one from the database."""
    if not DATABASES:
        return "no databases configured (start the server with --config or --sqlite)"
    lines = []
    for name, e in sorted(DATABASES.items()):
        where = e.get("sqlite") or e.get("dsn", "?")
        path = _model_path(name)
        if os.path.exists(path):
            comment = json.load(open(path)).get("_comment") or []
            built = next((c for c in comment if "Built by" in c), "model present")
            state = built
        else:
            state = "no model yet -- build_model(%r)" % name
        lines.append("%-24s %-14s %s\n%26s%s" % (name, "postgresql" if e.get("dsn") else "sqlite",
                                                 where, "", state))
    return "\n".join(lines)


@mcp.tool()
def build_model(database: str, flags: str = "") -> str:
    """Reverse engineer a conceptual model from the database: keys, references, value
    domains, identifiers and the schema inside JSON columns, from the catalogue and the data.
    Takes a minute on a large database. `flags` overrides the default reverse.py flags. A
    PostgreSQL database needs a model built beforehand (reverse.py --dsn) and named in the
    config; this builds from SQLite files."""
    e = _entry(database)
    if not e.get("sqlite"):
        return ("%s is reached by a DSN; build its model with `python3 reverse/reverse.py "
                "--dsn URL -o DIR -n %s` and put the path under \"model\" in the config"
                % (database, database))
    os.makedirs(MODEL_DIR, exist_ok=True)
    cmd = [sys.executable, os.path.join(ROOT, "reverse", "reverse.py"), e["sqlite"],
           "-o", MODEL_DIR, "-n", database] + (flags.split() if flags else BUILD_FLAGS)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return "build failed:\n" + (r.stderr or r.stdout)[-2000:]
    e["model"] = os.path.join(MODEL_DIR, "%s.ccm.json" % database)
    report = os.path.join(MODEL_DIR, "%s.report.md" % database)
    tail = open(report).read()[:1500] if os.path.exists(report) else ""
    return "built %s\n\n%s" % (e["model"], tail)


# A schema this small is read whole: narrowing it saves nothing and every writer who was
# given a narrowed view of a BIRD database reported it had hidden the table they needed.
NARROW_ABOVE = 15


@mcp.tool()
def describe_schema(database: str, question: str = "", terms: str = "",
                    relational: bool = False) -> str:
    """Describe the database in the words of its conceptual model: the things and the values,
    what identifies each thing (asked for a thing's id, this is the value that answers it),
    what is inside the JSON columns, the value domains a filter must spell exactly, the
    cautions from profiling the rows where the model was profiled, and every relationship
    as a sentence. With a `question`, only the part the question is about -- on a large
    schema; a small one is always described whole -- and any type left out is named, so
    add `terms` (the quantities a definition is computed from, not just the name of the
    thing) to widen the view. `relational=True` puts the table, column, JSON field or
    foreign key beside each entry, for a reader who will write SQL rather than ConQuer."""
    model, _, _ = _model(database)
    about = " ".join(x for x in (question, terms) if x).strip() or None
    if sum(1 for c in model.get("concepts", []) if c["kind"] == "entity") <= NARROW_ABOVE:
        about = None
    return driver.describe(model, about, relational=relational)


@mcp.tool()
def explain_query(database: str, query: str) -> str:
    """Read a ConQuer query back in English, with what it assumes and what it risks -- a fan
    trap, a window over collapsed rows, a value it cannot find -- without running it."""
    model, lexicon, _ = _model(database)
    try:
        report, _ = driver.interpret(model, query, lexicon)
    except parser_mod.ParseError as e:
        return "parse error: %s" % e
    return report or "(the query does not parse; see the risks above)"


@mcp.tool()
def run_query(database: str, query: str, limit: int = 50) -> str:
    """Compile a ConQuer query to SQL and run it, read-only. Returns the compiler's reading of
    the query (what it will count, what it assumes), the SQL, and the first rows. A refusal
    -- an aggregate over multiplied rows, a partition the group does not fix -- comes back
    as text saying why and how to write it instead. `describe_schema` says what can be
    named; the `writing_brief` prompt says how the language is written."""
    model, lexicon, emitter = _model(database)
    try:
        report, risks = driver.interpret(model, query, lexicon)
    except parser_mod.ParseError as e:
        return "parse error: %s" % e
    try:
        _, statement, params = driver.transpile(model, query, lexicon, emitter)
    except parser_mod.ParseError as e:
        return "%s\n\nparse error: %s" % (report or "", e)
    except sql_mod.SqlError as e:
        return "%s\n\nrefused: %s" % (report or "", e)
    conn = _connect(database)
    try:
        rows = _rows(conn, statement, params, limit)
    finally:
        conn.close()
    return "%s\n\nSQL: %s\n%s\n\n%s" % (report or "", statement,
                                       "-- parameters: %r" % (params,) if params else "", rows)


@mcp.tool()
def run_sql(database: str, sql: str, limit: int = 50) -> str:
    """Run a SQL statement against the database, read-only, and show the first rows. For an
    agent writing SQL with `describe_schema(relational=True)` beside it -- the layer without
    the language, which the measurements say is where the value is."""
    conn = _connect(database)
    try:
        return _rows(conn, sql, (), limit)
    finally:
        conn.close()


# --------------------------------------------------------------------------- prompts

BRIEF = """You are answering questions about a database with the tools of this server.

1. `describe_schema(database, question)` describes the database in the words of its
   conceptual model, narrowed to the question. Read every section: what identifies each
   thing (asked for a thing's id, that is the value to return, unless the question names
   another), what is inside the JSON columns, the value domains (a filter must spell one
   exactly), the cautions from profiling the rows. A question names what it is about, not
   what it is computed from: pass the quantities a definition uses as `terms` to widen it.
2. {how}
3. Look at the rows and check them against what was asked -- the right columns in the order
   asked, the right row grain, plausible values -- and revise. No rows nearly always means a
   literal spelled differently from the data, or a step that reaches nothing.
4. Return exactly the columns the question asks for, in the order it asks for them.
"""

HOW = {
    "conquer": ("`run_query(database, query)` runs a ConQuer query and shows how it was read "
                "and the first rows; `explain_query` reads it back without running. The "
                "language is below. Write the path in the model's own sentences; the compiler "
                "supplies the joins, refuses a query that would multiply what it sums, and "
                "says what it assumed."),
    "sql": ("`describe_schema(..., relational=True)` puts the table, column, JSON field or "
            "foreign key beside every entry. Write PostgreSQL or SQLite SQL, as the database "
            "is, and run it with `run_sql(database, sql)`."),
}


@mcp.prompt()
def writing_brief(language: str = "conquer") -> str:
    """How to answer questions with this server's tools: `conquer` for the conceptual query
    language (the brief and the one-page primer), `sql` for plain SQL with the description
    in relational terms."""
    how = HOW.get(language, HOW["conquer"])
    text = BRIEF.format(how=how)
    if language != "sql":
        text += "\n\n" + open(os.path.join(ROOT, "conquer", "primer.md")).read()
    return text


# --------------------------------------------------------------------------- main

def load_config(path):
    base = os.path.dirname(os.path.abspath(path))
    for name, e in json.load(open(path)).items():
        e = dict(e)
        for key in ("sqlite", "model"):
            if e.get(key) and not os.path.isabs(e[key]):
                e[key] = os.path.normpath(os.path.join(base, e[key]))
        DATABASES[name] = e


def main(argv=None):
    global MODEL_DIR
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config", help="JSON: {name: {sqlite|dsn, model?}}; see databases.example.json")
    p.add_argument("--sqlite", help="one SQLite database, named after its file")
    p.add_argument("--model", help="with --sqlite, its model (built on demand otherwise)")
    p.add_argument("--models-dir", default=MODEL_DIR, help="where build_model writes")
    p.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    args = p.parse_args(argv)
    MODEL_DIR = args.models_dir
    if args.config:
        load_config(args.config)
    if args.sqlite:
        name = os.path.splitext(os.path.basename(args.sqlite))[0]
        DATABASES[name] = {"sqlite": os.path.abspath(args.sqlite),
                           **({"model": os.path.abspath(args.model)} if args.model else {})}
    mcp.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
