# Contributing

This is a research repository. It exists to answer a question — does a conceptual model and
a conceptual query language help an LLM write SQL? — and the answer it reached is in the
README. Contributions are welcome, and what they need to satisfy is unusual enough to be
worth stating.

## Run the suite, and the corpus

```sh
./run-tests.sh                    # ~2,200 assertions, no network, under a minute
python3 bench/pilot/corpus.py     # needs bench/fetch.sh + bench/run.sh first
```

`run-tests.sh` builds a fixture database, reverse engineers it, validates the model — against
the CCM JSON Schema too if `jsonschema` is installed — and, if `model/reference/fetch.sh` has
been run, the generated `.orm` against the ORM 2 schema, then runs every test. It must be green.

`corpus.py` recompiles **every query the pilot ever wrote** — 2,175 of them, over eleven
schemas — and diffs the emitted SQL character for character against a recorded baseline. Any
change to the compiler that alters a query's meaning has to alter its SQL, so this is the
sensitive net. If it reports changes:

- run it again with `--rows`, which executes the old and the new SQL and says whether the
  answer actually moved;
- if the change is intended and no answer moved, `--update` records the new baseline **in the
  same commit**, with the commit message saying why.

`build.py` rebuilds each arm's `try` script every run and leaves an already-answered arm's
*inputs* alone, so a recorded answer always matches the prompt that produced it. `--fresh`
deletes the arms it is asked to build, answers included; those answers are evidence, and there
is no second copy.

## Claims need measurements, and measurements need controls

The most instructive mistake in this repository's history is finding 43: a claim that the
conceptual model recovers half of what withholding BIRD's evidence costs was written up
before the control arm ran, and the control overturned the attribution. The rule that came
out of it holds for any change here:

- **Run the control before writing the claim down**, particularly when the result flatters
  the thing being built.
- **Never read a difference under 3 points as signal** on a hundred questions. The arms are
  paired, so the statistic is McNemar's on the discordant pairs, not a raw difference.
- **When an answer disagrees with a recorded result, run the recorded query too** before
  believing either. Nine of Spider 2.0's twenty-three gradable local tasks fail their own gold.

## A refusal is a feature, and so is its cost

The compiler refuses queries that are well formed and meaningless. Every such refusal must be
suppressible by `--permissive`, and `conquer/tests/test_errors.py` asserts it — a refusal that
cannot be suppressed is one whose cost can never be measured.

New refusals need a case in `test_errors.py` (the class and a phrase of the message, because
"cannot lower Seq" satisfies the class and helps nobody) and, where they change what compiles,
a corpus run.

## Style

Read a few files before writing. Comments here explain *why*, usually by naming the defect
that motivated the code or the section of the report it implements; they are not narration.
Error messages name what to do instead. Both are load-bearing: the findings file is the
project's memory, and a message that does not say how to fix the query is a message that
costs someone an attempt.
