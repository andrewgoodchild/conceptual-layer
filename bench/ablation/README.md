# Reference-inference ablations

What a published pipeline for recovering foreign keys does, switched on one step at a
time, and measured on schemas whose declared references are the truth. The pipeline is the
one in "Scalable Join Inference for Large Context Graphs" (arXiv 2603.04176): statistics
propose key candidates and inclusion dependencies, a score thresholds them, an LLM judges
what is left. Our reverse engineer already has the first two (rules 9, 9b, 9c; findings
84 and 91); the ablations ask what each step and each floor is worth.

## Corpora

- **LiveSQLBench Large**, 18 schemas in `bench/livesql/work/db`, 1,112 declared
  references. Enterprise-style names -- 95% of references are not spelled like the key
  they point at (finding 84) -- and entities split across tables sharing an id.
- **BIRD** minidev, 11 databases, for the downstream measure: the recorded ConQuer answers
  of the `conquer` pilot arm, recompiled against a model built from each arm's references.

Every arm strips the declared references before it runs and never reads them; they are
compared with afterwards.

## Arms (`refs.py`)

| arm | what is on |
|---|---|
| `names` | rule 9c with name evidence, gated as `apply_references` gates it (name-corroborated) |
| `rules` | rule 9c on the data alone, as shipped: preferred + significant, score >= 2.6 |
| `+1to1` | ...and a table's own key contained in another's key counts (the 1:1 split shape) |
| `+md1+mr1` | ...and the significance floors (3 distinct values, 50 rows) removed |
| `+t0` | ...and the proposal threshold removed: every best-scoring containment, swept by score |
| `approx@eps` | the containment test tolerates `eps` of the distinct values dangling |
| `llm` | the fully relaxed candidates with blind evidence, kept or dropped by a judge |

`refs.py sweep --eps E` computes every data gate from one analysis per tolerance (the floors
and thresholds are filters on the findings); `refs.py names` runs the named path;
`refs.py llm-export ...` writes `work/llm/<db>.candidates.json`, a judge following
`JUDGE.md` writes `work/llm/<db>.verdicts.json`, and `refs.py llm-score` scores what it kept.
Results land in `work/<corpus>.<arm>.json` as the found sets per database and gate, so arms
can be compared after the fact. The candidates files carry a few sample values per column, as
the judge saw them; in the one database whose samples were people's email addresses, those
are replaced by `<email address>` here.

## Downstream (`downstream.py`)

For each BIRD database: the model rebuilt from a catalogue with only an arm's references
declared, every recorded answer recompiled against it, and against the declared model each
answer either gives the same rows, different rows, or no longer compiles -- a column the arm
did not recover is a value where the answer walked a relationship.

## Blindness

The judge reads one candidate file and nothing else -- not the database, not the model, not
the repository -- and the candidate files carry no declared reference. Findings record what
each arm found; nothing here is fed back into the rules without a finding saying why.
