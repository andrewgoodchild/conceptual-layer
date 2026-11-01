# Recovering references when the names say nothing

Written before the change below was made or tested on its test corpus. Finding 179 measured
foreign keys at 27% recall with every name destroyed and read that as what the data alone can
do. It is not. `_inclusions` sorts a column's candidates by name similarity first and score
second, under `ignore_names` too, and on a destroyed schema that similarity is between strings
like `c0012` and `t0017`. So the tie-break is choosing arbitrarily.

**Seen so far, on development corpora only** (names-destroyed AdventureWorks and the 11 BIRD
databases, `corpora.py destroy`). Over all containments, offline: the true target is ranked
first by score for 71 of AdventureWorks's 91 references, and first by the tie-break for 32. At
the shipped gate, sorting by score instead takes AdventureWorks from 26 right of 39 proposed to
57 right of 78, and all 12 databases from 72 right of 91 to 104 right of 136.

**The change.** When digits are removed from a schema's column names and at most two different
words remain, over more than five columns, the names say nothing. Then the search behaves as
`ignore_names` with `name_score` zero, so the score decides, whichever path called it.

**The test corpus: MusicBrainz, names destroyed.** No result has been seen on it. The baseline
is the search as it stands before the change, with `refs.py names` and `refs.py sweep` on
`bar-blind`, and the same again after the change.

| Prediction, on `rules@2.6` | |
|---|---|
| Recall | up at least 15 points |
| Precision | down at most 5 points |

**Does no harm.** The rule must not fire on any real schema: 61 were checked (BIRD 11, LiveSQLBench
18, Spider 2.0-lite 30, AdventureWorks, MusicBrainz) and the fewest words in any of them is
far above two. Findings on every named corpus must come out identical, so named results are
unchanged by construction, and that is checked rather than assumed on BIRD and AdventureWorks.

**What it does not claim.** Destroyed names are a clean test, not a common schema. A schema with
cryptic but varied names (`MANDT`, `BUKRS`) is not caught by this rule and keeps the tie-break.
