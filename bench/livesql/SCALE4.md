# What Shkapenyuk et al. used and we did not: a fourth pre-registered round

Written 27 September 2026, before any describer, linker or writer ran. The results go in
`bench/findings.md`, finding 169, and are compared against this page.

## Why

Shkapenyuk, Srivastava, Johnson and Ghane (AT&T; arXiv:2505.19988) reached the top of BIRD
without hints on automatically extracted metadata. On BIRD mini-dev with GPT-4o they report
49.8% with no column metadata, 59.6 with BIRD's own column descriptions, 61.2 with
descriptions an LLM wrote from a column profile, and 63.2 with both; and 61.2, 63.2 and 69.0
for the full schema, their linking and perfect linking. Set beside the three earlier rounds
here (`SCALE.md`, `SCALE2.md`, `SCALE3.md`), four things they used were never tried:

1. **The benchmark's own column meanings.** LiveSQLBench ships `column_meaning_base.json`,
   a description of every column and JSON field; no writer here was ever given it.
2. **Descriptions an LLM writes from a column profile** -- meaning and format, abbreviations
   expanded -- where the profiling here produced mechanical sentences only.
3. **A value index over every text column**, so a literal can be traced to where it is
   stored.
4. **Linking by writing SQL**: draft the query, and take the tables and columns the drafts
   use, rather than scoring words.

## What was built

- `profile.py`: per column and JSON field, rows, nulls, distinct values, minimum and maximum,
  lengths and the most common values (their profile); up to 10,000 distinct text values per
  column, indexed by value (their literal index, exact); and the column meanings, flattened,
  with the type and the example they restate removed (the DDL beside them has both).
- `DESCRIBE.md`: one describer agent per database, which sees only the profile -- no
  meanings, no knowledge base, no questions, no database -- writes a one-sentence
  description of every column and field.
- `LINK.md`: one linker agent per database, which sees the questions, the knowledge base and
  the annotated schema with both kinds of description, but cannot query the database, writes
  two drafts of each question and lists the tables, columns and literals they use.
- `conquer/annotate.py --describe`, `--values`, `--links`: descriptions as comments beside
  each column (labelled by source when there are two), and their words counted when tables
  are chosen; the values a question or a draft names, and where they are stored, with those
  tables shown; the tables a draft used, shown first.

**Budget.** 20,000 characters for every arm, set before the run. Descriptions take room: on
the development questions (organ_transplant, exchange_traded_funds, labor_certification;
30 questions, none a test database) the plain view kept every gold table on 14 with a median
of 14 tables, and with the meanings on 12 with 7; the annotated view on 16 with 9, and with
the meanings on 15 with 5. The writers can widen any view.

## Design

**Sample.** The sixty questions of `SCALE3.md`, on the same six databases
(`work/pilot-scale4/sample.json` is a copy), so each arm here can also be read beside that
round's. The writers are new and blind. The additions above were designed from the paper and
the development databases, but after SCALE3's scores were known; that is recorded here rather
than hidden.

**Arms.** All SQL writers with the knowledge base and `./try`, brief as in SCALE3, differing
only in `./schema`:

| arm | `./schema` prints | adds |
|---|---|---|
| `ddlp4` | the plain DDL, chosen lexically -- the control | -- |
| `ddlm` | as `ddlp4`, with the benchmark's column meanings beside each column | 1 |
| `annm` | the annotated DDL, chosen by the model, with the meanings and the profile descriptions | 1, 2 |
| `annl` | as `annm`, with the value index and the draft-query links | 1-4 |

24 writers, one per (arm, database), Claude Opus 5.5, all launched together after every
describer and linker has finished.

## Prediction

- **Primary 1.** `ddlm` scores at least **3 of 60** above `ddlp4`: the benchmark's own
  metadata helps. **Kill:** 0 or less.
- **Primary 2.** `annm` scores at least 3 above `ddlm`: profile descriptions and the model
  add to it. **Kill:** 0 or less.
- **Primary 3.** `annl` scores at least 3 above `annm`: literal and draft-query linking add
  to that. **Kill:** 0 or less.
- **Also recorded:** tokens and time per arm; the describers' and linkers' cost, paid once per
  database or per question set; and, beside SCALE3, each database's scores.
- **What 60 questions can say.** A difference under about five is inside the noise; every
  cell compromised by tooling is reported, with and without.
- **Honest prior.** Primary 1 about 45%: it is the paper's largest single effect, and the
  meaning of `overseerloadvalue` cannot be found by querying, but agents found much of what
  descriptions say in every earlier round. Primaries 2 and 3 about 25% each: the earlier
  rounds' misses were how questions are meant to be read, which none of this addresses.

## Changes after the plan, before any writer ran

- `annotate.py` listed at most 24 fields of a JSON column even in the full view, and said
  "and N more fields" with no way to see them; the solar linker was stopped by it
  (`electrical_performance.elec_perf_snapshot`). The full view (`./schema` with no words)
  now lists every field. The linkers for robot, museum and solar ran before the fix.
- The subagent limit (20 at once) held the four `robot_fault_prediction` writers back until
  slots freed; they ran together, a few minutes after the rest.

## Result

Recorded after the run. **All three predictions failed.**

| | of 60 | without `sports_events` (50) | writer tokens |
|---|---|---|---|
| `ddlp4`, plain DDL | 28 | 24 | 0.46M |
| `ddlm`, + the benchmark's column meanings | 28 | 24 | 0.47M |
| `annm`, annotated + meanings + profile descriptions | 26 | 22 | 0.50M |
| `annl`, + value index + draft-query links | 26 | 26 | 0.52M |

- **Primary 1**, `ddlm` − `ddlp4`: 0 (2 won, 2 lost). Killed.
- **Primary 2**, `annm` − `ddlm`: −2 (0 won, 2 lost). Killed.
- **Primary 3**, `annl` − `annm`: 0 of 60 (4 won, 4 lost). Killed. The `annl` writer on
  `sports_events` was blocked by the permission system and submitted nothing; without that
  database `annl` scores 26 against 22 for `annm` (4 won, 0 lost, p = 0.12) and 24 for the
  plain DDL (2 won, 0 lost) -- the one direction in four rounds that favours the layer, and
  inside the noise.

The describers cost 1.28M tokens and the linkers 0.50M, once per database and per question
set. The plain-DDL control reproduces: on the five databases where neither round's control
writer was blocked (all but `planets_data`), SCALE3's scored 22 of 50 and this round's 21.

**Compromised cells:** `annl` on `sports_events` (blocked, no answers); `ddlm` on
`archeology_scan` (one exploratory query blocked). Details in `bench/findings.md`, finding
169.
