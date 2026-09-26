# Brief for a linker in the fourth scale round (SCALE4.md)

You are preparing, for each question about one PostgreSQL database, the list of tables and
columns its answer is likely to need. You will not run anything against the database.
Everything you may use is in your working directory, `{DIR}`:

- `questions.json` — the questions.
- `knowledge.md` — the business's definitions for this database.
- `./schema ["words"]` — the database's DDL with comments on each column: what the column
  holds, and what profiling its rows found. With no arguments it prints every table; with
  words, the tables they are about.

**Rules.** Keep every scratch or draft file inside `{DIR}`. Do not open anything outside
`{DIR}` — the repository around it holds the answers, and reading them would void the run. Do
not read the `./schema` script's source or the files it points to; use it only by running it.
Do not search the web. Do not start other agents.

**The job.** For each question, write a draft PostgreSQL query that answers it, and a second
draft that takes the other plausible reading where there is one (of a term, a join, a grain).
Then list every table and every column either draft uses, and every literal value either
filters on. Drafts are for finding the schema the answer needs: prefer including a column you
are unsure of to leaving it out.

Write `{DIR}/links.json`, keyed by the question's text exactly as `questions.json` gives it:

    {"<question text>": {"instance_id": "...",
                         "tables": ["...", ...],
                         "columns": ["table.column", "table.column->field", ...],
                         "literals": ["...", ...],
                         "drafts": ["SELECT ...", "SELECT ..."]},
     ...}

Validate it with `python3 -m json.tool`.

**Report.** Finish with a few lines: which questions you were least sure of the schema for,
and why.
