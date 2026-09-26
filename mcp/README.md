# The conceptual layer as an MCP server

Every number in [`bench/`](../bench/README.md) was produced by an agent that had, beside the
question, two commands — `./schema`, describing the database in its model's terms, and
`./try`, running a candidate and showing rows — and a page of instructions. This server is
those tools over the [Model Context Protocol](https://modelcontextprotocol.io), for any client
that speaks it: Claude Code, Claude Desktop, an agent framework.

```sh
pip install mcp                                   # the one dependency; psycopg for PostgreSQL
python3 mcp/server.py --sqlite examples/db/chinook.sqlite       # one database
python3 mcp/server.py --config mcp/databases.json               # several; see the example
```

For Claude Code: `claude mcp add conceptual-layer -- python3 /path/to/mcp/server.py --config
/path/to/mcp/databases.json`. For Claude Desktop, the same command and arguments under
`mcpServers` in its configuration file. `databases.example.json` is the shape of the config:
a name, a `sqlite` path or a `dsn`, and optionally the `model` — for a SQLite database the
model is built on demand.

## What it offers

| | |
|---|---|
| `list_databases` | what is configured, and whether each has a model |
| `build_model` | reverse engineer the model from a SQLite database: keys, references, value domains, identifiers, the schema inside JSON columns ([4](../docs/04-reverse-engineering.md)) |
| `describe_schema` | the description, narrowed to a question: what identifies each thing, what is inside the documents, the value domains, the cautions from profiling, every relationship as a sentence; `relational=True` puts the table, column, JSON field or foreign key beside each entry |
| `explain_query` | a ConQuer query read back in English, with its risks, without running it |
| `run_query` | a ConQuer query compiled and run, read-only: the reading, the SQL, the rows — or the refusal and how to write it instead |
| `run_sql` | plain SQL, read-only, for an agent that writes SQL with the description beside it |
| prompt `writing_brief` | how to work with the tools: `conquer` (with the one-page primer) or `sql` |

Every connection is read-only, with a statement timeout on PostgreSQL.

## What to expect from it

Read [7 — What we measured](../docs/07-what-we-measured.md) before choosing between the two
query tools. The description is where the measured value is: written-down definitions were
worth about +8 points to a writer in either language, and on LiveSQLBench, saying what
identifies a thing and what is inside the JSON columns took re-run ConQuer writers from 71 to 82
of 180 (no re-run control; docs/07 has the caveats). The language was not:
ConQuer and SQL land within a question of each other on every benchmark tried, and ConQuer
costs about half again the tokens over a session, because there is a primer to read and a
listing to search. What `run_query` adds is the reading back and the fan trap handled from
the model — a value summed once, an ambiguous count refused — and the honest finding is that writers rarely produce the shapes
they guard. So: `describe_schema(relational=True)` and `run_sql` is the configuration the
numbers recommend; `run_query` is there for a query you want checked and read back.

The build flags are the ones the benchmark models were built with, and a model wants the
data: every pass past the catalogue reads the rows. A PostgreSQL database needs its model
built beforehand (`reverse/reverse.py --dsn`) and named in the config.

## Tested end to end

Twenty-two blind writers answered BIRD's 100-question sample with nothing but `client.py`
and this server -- the brief, the description and the runner all over the protocol, the SQL
writers with no DDL at all (finding 164). ConQuer scored **76 of 100** and SQL **75**,
the same verdict as the recorded shell-script arms on 96 and 97 questions; the SQL arm with
the description alone matched the recorded arm that had the DDL. Every writer said the brief
and the tool descriptions were enough. What they asked for and did not get -- profiling
cautions, domains for every column -- is what a model built with `build_model`'s default
flags has and BIRD's did not; and the one defect fourteen of them named, a narrowed
description hiding the table they needed, is fixed.

`tests/test_server.py` calls each tool against the company fixture and then speaks the
protocol to the server over stdio; `run-tests.sh` runs it and says so when `mcp` is absent.
`client.py` is the command-line client the writers used.
