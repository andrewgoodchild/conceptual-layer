# Brief for a writer in the scale round (SCALE.md)

You are answering questions about one PostgreSQL database by writing SQL. Everything you may
use is in your working directory, `{DIR}`:

- `questions.json` — the questions. `needs_domain_knowledge` marks the ones that use a term
  defined in `knowledge.md`; `conditions` says whether the order of the result matters.
- `knowledge.md` — the business's definitions for this database. Many questions use a term
  defined only here.
- `./try "SELECT ..."` — runs a statement read-only on the database and shows the first rows
  of what it returns. It says nothing about whether the answer is right.
{SCHEMA}

**Rules.** Keep every scratch or draft file inside `{DIR}`. *(Added during the run, after
writers in batches one to three were found sharing one scratch folder; see SCALE.md.)* Work
only from these. Do not open anything outside `{DIR}` — the repository around
it holds the answers, and reading them would void the run. Do not search the web. Use `./try`
as often as you need.

**Answer.** For each question, write the one PostgreSQL `SELECT` statement you believe answers
it: the columns the question asks for, in the order it asks, and nothing else. When you are
done, write `{DIR}/answers.json`:

    [{"question_id": "...", "answer": "SELECT ..."}, ...]

one entry per question, in the order of `questions.json`. If you cannot answer a question,
give your best statement anyway, and add `"note": "why"`.

**Report.** Finish with a few lines: which questions were hardest and why, and what the schema
material you were given told you, or failed to tell you, that mattered.

The `sqlddlk` and `sqldesc` briefs add: do not read the `./schema` or `./try` scripts' source
or the files they point to; use them only by running them. Every brief adds: do not start
other agents.

---

The `{SCHEMA}` paragraph for each arm:

- `sql`: `schema.sql` — the full DDL of the database's tables, with three sample rows under
  each. It is large (about 50 tables); search it rather than reading it end to end.
- `sqlddlk`: `./schema "your question" ["extra words"]` — prints the DDL of the tables that
  match the words you give it (names, columns, sample rows) and the declared foreign keys
  between them, with three sample rows under each. Pass more words to widen the view; with no
  arguments it prints every table.
- `sqldesc`: `./schema "your question" ["extra words"]` — prints a description of the part of
  the database the words are about, in relational terms: what identifies each thing and which
  columns hold that identity, how things relate and through which columns, what is inside the
  JSON columns, the values each column holds and cautions from profiling the rows. Pass more
  words to widen the view; with no arguments it prints the whole description.
