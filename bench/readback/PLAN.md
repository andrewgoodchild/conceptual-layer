# Plan: does the read-back help a checker catch a wrong query?

Committed before any checker runs. Nothing here is changed after seeing a verdict; any
departure is recorded under "What actually happened" with the result.

**The question.** Eight rounds have graded the conceptual layer on whether writers get the
right answer, and on BIRD it has not beaten the DDL: finding 185 found that even without
names, keys or evidence a writer works the schema out from the rows. Accuracy is not the only
thing the layer offers. `explain_query` reads a ConQuer query back in English, with what it
assumes and what it risks, and the case for it is that a wrong query reads wrong. A query
that returns the wrong rows without an error is the failure nobody sees (`score.py`'s
`wrong quietly`). Given the question and the query, does a checker who also has the read-back
catch more of the wrong ones, without flagging more of the right?

**Material.** No new writers. Every distinct ConQuer answer the pilot's arms wrote against the
base model (`bench/pilot/results.json`, the `conquer*` arms other than `conquer_sem` and the
three reference variants, whose read-back would need their own model), rescored now on BIRD by
strict EX with the compiler as it stands (`build.py pool`). Then, per question (`build.py
sample`, seed 20261108):

- only questions with at least one right and one wrong answer. That leaves out the questions
  no arm ever answered, most of which finding 74 traced to the gold;
- a wrong answer only if no declared forgiveness accepts it (`relaxed_ex`: row order, one part
  in a million, extra or reordered columns), because what such an answer gets wrong is the
  scorer's call, not a reader's;
- up to 3 wrong answers and 2 right ones, drawn at random.

Checked before this commit. The rescore gives 1,068 distinct answers: 637 right, 406 wrong
quietly, 8 that now fail loudly, and 17 to the one question whose gold did not finish in two
minutes, which are left out. Thirty wrong answers a forgiveness accepts are left out too. The
sample is **144 items, 76 wrong and 68 right, over 34 questions in 10 databases**, from 3
items (codebase_community) to 23 (card_games): 20 checkers. The read-back of every item is
the reading alone: `interpret` runs nothing, so it shows no rows.

**Arms.** One fresh blind Sonnet 5.5 checker per (arm, database), at most 20 at once. Both arms
of a database get the same items in the same order, the question with its evidence, the
primer, and the schema listing the ConQuer writers had. The checker can run nothing.

| Arm | Sees beside each query |
|---|---|
| `plain` | nothing |
| `readback` | `explain_query`'s text for it: the reading, its assumptions and its risks |

The README (`build.py`'s `README`) differs between them by the one paragraph that says what
the read-back is. Each checker writes `right` or `wrong` and a one-sentence reason for every
item, and says whether it read outside its directory.

**Metric.** A `wrong` verdict is a flag. The catch rate is the share of wrong answers flagged,
the false-alarm rate the share of right answers flagged, and Youden's J is the first minus the
second: a checker who flags everything, or nothing, has J = 0. An item left without a verdict
is not flagged. `compare.py` is the whole analysis.

**Primary comparison.** J of `readback` minus J of `plain`. It counts as a difference only if it
is at least 10 points either way and the 95% interval, resampling whole questions, excludes
zero. Otherwise: no difference shown. Ten points, not October's four, because J moves twice
as far as an accuracy for the same items, and fewer of them are in play.

**Secondary.** The catch rate and the false-alarm rate separately, each with an exact McNemar
test on the items the two arms split.

**Predictions.**

- `plain` catches 35% of the wrong answers, within 20 to 50, and flags 15% of the right ones,
  within 5 to 30. These answers survived their writer's own checking, and each ran and
  returned plausible rows; most of what is wrong with them is a reading of the question,
  which a checker shares.
- `readback` catches 45% and flags 15%.
- **J, `readback` minus `plain`, +8, within -5 to +20: no difference shown.** The read-back
  makes a fan trap or a missing filter visible, but it says what the query does, not what the
  question meant, and in the ablation round of 12 September a verifier given the `conquer`
  arm's drafts (`conquer_verified`) scored 73 against the drafts' 71.

**Not claimed in advance.** The test is of a second reader, not of the author. The pilot's
`try` ran `conquer.py --check`, which prints the same reading before the rows, so every wrong
answer here is one its writer saw read back and kept. That selects against the read-back: the
mistakes it makes obvious were the likeliest to be caught already. These are the answers of earlier writers on 100 questions they all
shared, so the wrong ones are the mistakes this benchmark draws, not a sample of mistakes in
general. A checker may know BIRD; that is the same in both arms. The checker reads but does
not run, which is the use the read-back is for and not the only way a person checks a query.
Keeping checkers away from the rest of this repository rests on instruction, and each reports
whether it read outside its directory.

**Cost.** About 0.8 to 1.5M tokens, some $3 to $6 on the October plan's assumption: a checker
reads a listing and a primer once and then judges fourteen items on average, without exploring.
Usage is recorded per checker in `ledger.jsonl`.

## What actually happened

Added after scoring; everything above is as committed. `plain` caught 84.2% of the wrong answers
and flagged 16.2% of the right ones, J +68.0; `readback` 78.9% and 17.6%, J +61.3. The primary
comparison is -6.7 with an interval of -19.9 to +4.4: no difference shown, as predicted, but on
the other side of zero from the prediction. The catch rate was far outside its range of 20 to
50. Every question has 3 to 5 items in one checker's file, so a checker could compare the
answers to one question with each other; the plan did not foresee it, and it is the same in
both arms. 0.93M tokens. Finding 186.
