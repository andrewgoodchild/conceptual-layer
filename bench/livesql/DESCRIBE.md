# Brief for a describer in the fourth scale round (SCALE4.md)

You are describing one PostgreSQL database's columns for the people who will query it. You
have only what profiling its rows found. Everything you may use is in your working directory,
`{DIR}`:

- `profile.txt` — every column, and every field inside a JSON column, with its type and what
  profiling found: how many rows are null, how many distinct values, the minimum and maximum
  (compared as text), the range of lengths, and the most common values with their counts.

**Rules.** Keep every scratch or draft file inside `{DIR}`. Do not open anything outside
`{DIR}` — the repository around it holds answers about this database, and reading it would
void the run. Do not search the web. Do not start other agents.

**The job.** For every line of `profile.txt` that names a column or a JSON field, write a short
description — one sentence, at most 30 words — of what it most likely holds and in what
format: its meaning, read from the table's name, the column's name and its neighbours, and
the values; and the format a filter must match (a code's shape, a date's format, a unit, a
case convention, a fixed set of values, a column that is constant or mostly null). Expand
abbreviations where the context makes the expansion clear, and say "probably" where it does
not. Do not describe a column you cannot read; write what the values show instead.

Write `{DIR}/descriptions.json`, one entry per profiled column or field:

    {"table|column": "…", "table|column|field.subfield": "…", …}

The key for `mechanical_status.component_status->brakes.J1` is
`"mechanical_status|component_status|brakes.J1"`. Validate it with `python3 -m json.tool`.
Work table by table; there are several hundred entries.

**Report.** Finish with a few lines: how many entries you wrote, and which columns you could
not read.
