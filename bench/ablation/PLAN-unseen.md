# The frozen judge on schemas it is unlikely to know, with names and without

Written after the candidates were exported and the rule-based baselines scored, and before any
judge ran. Finding 182 got 91% / 95% on AdventureWorks and 85% / 95% on MusicBrainz, and could
not rule out that the judges simply knew two famous schemas. This asks that directly.

**The schemas.** Both from Zenodo, pinned by checksum in `fetch-corpora.sh`, real data, keys
declared. Neither is in any benchmark this repository uses.

- **ACAI**, records of contemporary-art events in South Korea, first public 2026-08-22: 22 tables,
  25 references, all holding in the rows.
- **DBBE**, the Database of Byzantine Book Epigrams archive, first public 2026-04-06, from a
  dataset of 2023: 125 tables, 23 empty, 137 references, of which 2 are broken by orphan rows and
  cannot be found. Obscure, but public before any cutoff we can name; the judges' cutoff is not
  known here.

Each goes in twice, as published and through `corpora.py destroy`, the destroyed copies being
`blind1` and `blind2` so that the file name says nothing. Primary keys stay in place, as in
finding 182.

**Fixed before running.** `JUDGE.md` is used unchanged, its two paths apart. The candidates are
exported as in finding 182 (`refs.py llm-export --own-key --min-rows 1 --min-distinct 1
--threshold 0 --floor 0`). Sonnet judges, one per file, each given only the brief and that file,
in a directory of its own, and told to write no script, the failure of finding 182's first run.
A failed judge file is rerun; a disappointing result is not. Nothing is tuned on these.

| | References | Candidates, holding | Shipped gate | Rules at 2.6 | Plain name rule |
|---|---|---|---|---|---|
| ACAI | 25 | 24, holding 24 | 96% / 100% | 92% / 100% | 96% / 100% |
| DBBE | 137 | 136, holding 96 | 55% / 96% | 53% / 96% | 68% / 83% |
| `blind1` | 25 | 24, holding 24 | 92% / 100% | 92% / 100% | |
| `blind2` | 137 | 136, holding 85 | 53% / 94% | 53% / 94% | |

**ACAI cannot discriminate.** Every candidate is true and its keys carry their kind (`KW_00428`),
so a judge can only lose ground, and that is all it measures. It is the one schema here nobody
can have seen, and it is too easy; DBBE, with 40 false candidates and bare integers for keys, is
the test.

Recall and precision are bounded by the candidates and differ by schema, so the predictions are
in the two shares that compare across schemas: of the true candidates, how many are kept, and of
the false ones, how many are rejected. Finding 182's judges kept 100% and rejected 95% on
AdventureWorks, kept 100% and rejected 92% on MusicBrainz.

| Prediction | true kept | false rejected |
|---|---|---|
| ACAI | at least 95% | no false candidates |
| DBBE | at least 95% | at least 80% |
| `blind1` | at least 80% | no false candidates |
| `blind2` | at least 70% | at least 50% |

**How it will be read.**

- DBBE at 95% kept and 90% rejected or better: finding 182 was not mainly memory, on the evidence
  of a schema the judges are far less likely to know.
- DBBE below its prediction: finding 182 is overstated by how far.
- The gap between DBBE and `blind2` is what the judge gets from names.
- For a named schema the judge is worth its cost only if DBBE reaches at least 66% recall at 90%
  precision, beating the plain name rule's precision by 7 points with no real loss of recall.
  Otherwise the name rule is the cheaper answer.

**What it would not show.** Scored against declared references only. ACAI's 25 references are one
schema and one designer, and one reference is 4 points. DBBE is one schema, however many tables,
and its columns almost all name their targets (96%), so it does not stand in for MusicBrainz's
`entity0`. Destroying names removes the names, not the values, and a judge may still read shapes.

## What actually happened

Added after scoring; everything above is as committed. All four predictions held: true kept and
false rejected were 24 of 24 on ACAI, 96 of 96 and 35 of 40 on DBBE, 24 of 24 on `blind1`, 84 of 85
and 30 of 51 on `blind2`. DBBE reached 70% / 95%, past the bar for a named schema, and fell one
candidate short of the 90% rejected set for "not mainly memory", with all five wrongly kept reading
as references nobody declared. No file was rerun. Finding 183.
