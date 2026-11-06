# Plan: the description where the names are gone

Committed before any writer runs. Nothing here is changed after seeing an answer; any departure
is recorded under "What actually happened" with the result.

**The question.** On BIRD the description served from a reverse-engineered model has not beaten
the DDL: 79 against 88 in finding 176, 90 against 88 in finding 177. BIRD is the easy case for
the DDL, with good names, declared keys and a line of evidence for most questions. An
undocumented database has none of those, and that is what the description is built from rows
to stand in for. Strip all three, and does the description pull ahead of the DDL?

**Data.** BIRD mini-dev's eleven databases as `bench/minidev2026/fetch.sh` pins them, in two
copies made by `build.py dbs` with `bench/ablation/corpora.py`:

- `named`: every declared foreign key dropped. Names, rows and primary keys kept.
- `nameless`: the same, and every table and column renamed (`t0003`, `c0012`, seeded) and each
  table's columns put in a seeded shuffled order, so a remembered BIRD schema cannot be read off
  position. SQLite's `sqlite_sequence`, which holds the old table names, is not copied.

Checked before this commit: both copies have every table and row, no foreign key, and no
original table or column name in the nameless catalogue; all 100 gold queries return the same
rows on the named copy as on BIRD's. Indexes other than the primary keys' are gone from both.

**Sample.** The 100 questions of `bench/minidev2026/PLAN.md` (seed 20261031). Earlier writers
saw them with evidence and BIRD's own databases; nobody here sees those writers' answers.

**Arms.** One fresh blind Sonnet 5.5 writer per (arm, database), 44 in all, at most 20 at once,
each launched with the prompt October's writers had. No arm gets evidence.

| Arm | Sees | Runs with |
|---|---|---|
| `ddl_named` | the named copy's DDL | `./try` |
| `mcp_named` | the description of the named copy's model, `relational=True`, no DDL | `run_sql` |
| `ddl_nameless` | the nameless copy's DDL | `./try` |
| `mcp_nameless` | the description of the nameless copy's model | `run_sql` |

The README, brief and working steps are October's text (`bench/minidev2026/build.py`), with
the evidence absent. Each model is built from its copy alone by `build.py models`:
`--infer-keys --infer-fks --infer-domains --infer-enforced`, the data passes `bench/run.sh`
uses plus rule 9c's search. No judge: with no names it has nothing to read (finding 183), and
on the named copy it would be a second variable.

**Metric.** BIRD's strict EX as `bench/pilot/score.py` computes it, on all 100, an unanswered
question wrong. An answer runs on its arm's copy and the gold on BIRD's database; the rows are
the same, so no gold is translated. `compare.py` is the whole analysis.

**Primary comparison.** `mcp_nameless` minus `ddl_nameless`. It counts as a difference only if
it is at least 4 points either way and the database-clustered 95% interval excludes zero, as in
October. Otherwise: no difference shown.

**Secondary.** `mcp_named` minus `ddl_named`; what the names are worth to each arm
(`ddl_nameless` minus `ddl_named`, `mcp_nameless` minus `mcp_named`); and the description's
margin nameless minus its margin named, which is descriptive only: 100 questions cannot test
an interaction of any likely size.

**Predictions.**

- `ddl_named` 74, within 64 to 84: no evidence costs about what it cost in 2025 (the
  no-evidence round in `bench/findings.md`, 70 to 56), on the 74 questions that had some.
- `mcp_named` minus `ddl_named` -2, within -10 to +5, as in October.
- `ddl_nameless` 35, within 20 to 50. Most questions name a concept the writer has to find by
  its values, and many columns cannot be told apart that way.
- **`mcp_nameless` minus `ddl_nameless` +3, within -5 to +10: no difference shown.** The
  description adds recovered references and value domains, but on destroyed names rule 9c
  recovered 46% of AdventureWorks's foreign keys at 59% precision (finding 180), and the DDL
  writer can query the same rows.

The case for running it is that the prediction is not obvious. If the description wins by the
rule, that is the first measured setting where it helps a writer; if not, it is evidence that
structure recovered from rows does not stand in for names.

**Not claimed in advance.** The database's name and the question text still say what the domain
is, and a writer may know BIRD; a renamed copy blunts that and does not remove it. Primary keys
are left declared, an easier setting than an enterprise database with none. Keeping writers
away from BIRD's own files in this repository rests on instruction, and each reports whether it
read outside its directory. Scores are not comparable with October's: no evidence here.

**Cost.** About 2.5 to 4M tokens, some $9 to $15 on PLAN.md's assumption, scaled from October's
52k a writer and allowing for longer exploration without names. Usage is recorded per writer in
`ledger.jsonl`.
