# Plan: the repeat of finding 176

Written before any writer ran. This file's checksum went into `ledger2.jsonl` as its first line
before the first writer started. Unlike PLAN.md it is not a commit of its own, so that line and
the session are the only evidence of the order; anything changed afterwards goes under "What
actually happened".

**The question.** Finding 176 had SQL from the description 9 below SQL from the DDL, 79 against
88, an interval touching zero, one draw and one writer per database. The practical advice now
depends on it: `mcp/README.md` says to keep the DDL. Does the loss repeat on questions neither
arm has seen?

**Sample.** 100 more questions from the same release, seed 20261101, from the 400 the first draw
left, with the first draw's count per database: `sample.py 2`. 27 have no evidence. No question
repeats, so a writer's luck on a question cannot repeat either.

**Arms.** `sql_ddl` and `sql_mcp` exactly as in PLAN.md: the same `build.py` text, the same brief,
fresh blind Sonnet 5.5 writers, one per (arm, database), 22 in all, at most 20 at once. `conquer_mcp`
does not run: it is not what is in question and it would double the cost.

**Changed since round one, and disclosed.** `run_sql` now stops a SQLite query after 120 seconds
(whether any query in round one's SQL arms ran that long was not checked). The parser change
touches ConQuer only. Models, databases, brief and description are unchanged, so the brief's possible part
in the losses is still in place: this tests the result, not a fix for it.

**Metric and rule.** As PLAN.md: strict EX on all 100, an unanswered question wrong; a difference
only if `sql_mcp` minus `sql_ddl` is at least 4 points either way and the database-clustered 95%
interval excludes zero.

**How it is read.** Round two alone is the test. If it shows a difference against the description,
the loss has repeated and the README's advice stands. If it shows none, or a gain, finding 176 is
not repeated and the advice is withdrawn. A loss of 4 or more whose interval reaches zero again
is reported as such: not repeated by the rule, and not refuted. Both rounds pooled, 200 questions,
are secondary, because round one chose this question and pooling carries that in.

**Second opinions, never the verdict.** Multiset EX, the relaxed rescore by rule, and the
thinned-data check, as in `compare.py` and `grounded.py`.

**Predictions.** Round one was probably a high draw for this gap, so it should shrink. `sql_ddl`
82, within 75 to 90. `sql_mcp` minus `sql_ddl` -4, within -10 to +2.

**Cost.** About 0.9M tokens, from round one's 0.91M for these two arms: about $3.20 at Sonnet list
prices with the same 80/20 assumption.

## What actually happened

Added after scoring; everything above is as pinned. `sql_ddl` 88, `sql_mcp` 90: +2 (7, 5),
McNemar p=0.774, database interval -4.6 to +9.3, so no difference shown, and by the reading above
finding 176 is not repeated and the advice is withdrawn. Pooled -7 of 200, -18.8 to +3.2. Both
predictions held, the difference at the edge of its range. 886k tokens, 0.9M estimated. All pinned
files matched their checksums at scoring. Two writers were held back by the limit of 20 until others
finished. Some writers kept helper scripts in temporary folders outside their directories, by their
own reports. `./try` has no deadline, and one query outlived its writer. Finding 177.

