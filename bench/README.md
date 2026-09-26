# `bench/` — the measurements

Does routing a question through a reverse-engineered conceptual model help an LLM write the
query? Every experiment that asked is here. What they found, as one argument, is
[chapter 7 of the docs](../docs/07-what-we-measured.md); every defect and result they turned
up, numbered, is [`findings.md`](findings.md).

## The experiments

| Folder | Benchmark | What it measured |
|---|---|---|
| [`pilot/`](pilot/README.md) | BIRD mini-dev, 100 questions | The main experiment: blind agents in many arms — SQL or ConQuer, with or without the model's English, the evidence, definitions, a stronger writer, a working method — each scored by execution accuracy |
| [`livesql/`](livesql/README.md) | LiveSQLBench, SQLite and PostgreSQL tiers | The same comparison on a benchmark with knowledge bases, JSON columns and a second dialect, plus the reverse engineer against 1,122 declared references |
| [`spider2-trial/`](spider2-trial/README.md) | Spider 2.0, the 30 local databases | Not a benchmark run: what the gold queries need, what the reverse engineer makes of unseen schemas, and a handful of tasks written by hand |
| [`ablation/`](ablation/README.md) | LiveSQLBench and BIRD | A published foreign-key recovery pipeline, one step at a time, and what each step's references do to a query writer downstream |
| [`malloy-probe/`](malloy-probe/README.md) | the company fixture | How Malloy handles the fan traps the compiler was refusing at the time, which the compiler now computes |
| [`archive/hand-run/`](archive/hand-run/README.md) | BIRD mini-dev, 70 questions | The first measurement, answered by hand while the compiler was being built. Superseded by `pilot/`, kept for its trace of where ConQuer lost |

## Getting the data

No benchmark's questions, databases or gold SQL are in the repository (`NOTICE` says why).

```sh
bench/fetch.sh            # BIRD mini-dev into bench/bird/ (800 MB)
bench/run.sh              # reverse engineer its eleven databases into bench/models/
bench/livesql/fetch.sh    # LiveSQLBench's public release into bench/livesql/data/
```

Spider 2.0 is cloned by hand; [`spider2-trial/README.md`](spider2-trial/README.md) says how.

## Shared between experiments

The folders are not independent, and these are the crossings worth knowing before moving
anything:

- `pilot/corpus.py` and `corpus-baseline.json` are the compiler's regression net for the whole
  repository — every ConQuer query any pilot arm wrote, recompiled and diffed against a
  recorded baseline. `CONTRIBUTING.md` asks for it after every compiler change.
- `ablation/models.py` writes the `schema-refs-*` listings into `pilot/material/`, and
  `pilot/build.py` and `pilot/score.py` read them back; `ablation/downstream.py` reads the
  pilot's answers, and `ablation/refs.py` LiveSQLBench's models.
- `pilot/linking.py` reads Spider 2.0's models from `bench/spider2-models/`.
- `run.sh` rebuilds the semantic-layer models from `pilot/semantic/`.
