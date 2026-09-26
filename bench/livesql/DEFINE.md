# Brief for a definer in the third scale round (SCALE3.md)

You are preparing one PostgreSQL database's business terms for the people who will query it.
You will not see their questions. Everything you may use is in your working directory, `{DIR}`:

- `knowledge.md` — the business's definitions for this database, each with an id in brackets.
- `./schema ["words"]` — the database's DDL with sample rows, and comments on each column
  saying what profiling its rows found. With no arguments it prints every table; with words,
  the tables they are about.
- `./try "SELECT ..."` — runs a statement read-only on the database and shows the first rows.

**Rules.** Keep every scratch or draft file inside `{DIR}`. Do not open anything outside
`{DIR}` — the repository around it holds answers to questions about this database, and
reading them would void the run. Do not read the `./schema` or `./try` scripts' source or the
files they point to; use them only by running them. Do not search the web. Do not start other
agents.

**The job.** For every entry in `knowledge.md`, say how it is computed or tested *in this
database*: which tables, columns and JSON fields hold what the definition names, and one SQL
expression that realises it. A definition's formula names quantities in its own words
(`installation_date`, `total_personnel`); your job is to find what actually holds each one, by
reading the schema and querying the rows, and to say so when nothing does.

Run every expression with `./try` before you write it down. Check that it returns sensible
values: the right grain, plausible ranges, few nulls, units that match the definition. Where
an entry builds on another (`Depends on`), use the other's expression.

Write `{DIR}/terms.json`, one object per entry, in the order of `knowledge.md`:

    [{"id": 0,
      "kind": "measure" | "condition" | "value" | "none",
      "expression": "the SQL expression or condition, using the aliases in `from`",
      "from": "the FROM clause it is valid over, with joins and aliases",
      "check": "one SELECT that computes it over the data, for example the key and the value",
      "note": "anything a query writer must know: a quantity no column holds and what you
               used instead, units, a JSON field's spelling, a choice between two readings"},
     ...]

- `measure`: a number or quantity, per row of something (say per what in `note` if `from`
  does not make it plain).
- `condition`: a test that picks rows out — a category, a threshold, a status.
- `value`: what a stored value or code means, as a condition on it.
- `none`: nothing in this database realises it; say why in `note`, and leave the others empty.

Keep each expression to what the definition says. Do not guess at questions it might be
used in.

**Report.** Finish with a few lines: how many entries you could derive, which could not be and
why, and where the definitions and the data disagree.
