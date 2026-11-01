# A judge over everything the gates throw away, on the shared corpora

Written after the candidates were exported and before any judge ran. Finding 180 left foreign-key
recall on MusicBrainz at 44% through the shipped gate, with 85% within reach at 62% precision if
every gate is off. The judge of the ablations took the same step on BIRD to 85% at 95%, and on
LiveSQLBench to 75% at 90%. This asks whether that holds on the corpora the papers report on.

**Fixed before running.** `JUDGE.md` is used unchanged. So are the candidates: every best-scoring
containment, no floors, no threshold (`refs.py llm-export --own-key --min-rows 1 --min-distinct 1
--threshold 0 --floor 0`), 157 on AdventureWorks holding 83 of 91 references, and 645 on
MusicBrainz holding 400 of 469. Those are the ceilings. The judge has seen neither corpus and
nothing is tuned on them, so both are tests. Judges see one candidate file and nothing else.
MusicBrainz is too long for one file and goes in four, in the exported order. Judges are Sonnet;
the model of the earlier judges is not recorded. No second run: a failed judge file is rerun, a
disappointing result is not.

| Prediction | recall | precision |
|---|---|---|
| AdventureWorks | at least 75% | at least 90% |
| MusicBrainz | at least 65% | at least 85% |

Each is a pass only if both hold. Set against the shipped gate, 66% / 87% and 44% / 100%, the
judge is worth having only if recall gains at least 15 points at precision of at least 85%.

**What it would not show.** Scored against declared references only, so a true reference nobody
declared counts against it. Both corpora are famous, and a judge may know them from training, as
DBAutoDoc warns of its own runs; these names cannot rule that out. Names destroyed are out of
scope: the judge reads names.
