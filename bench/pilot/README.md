# The blind pilot

One hundred BIRD mini-dev questions, stratified by difficulty and database, answered by
fresh agents that had never seen this repository, in the arms below, with identical attempt
budgets and feedback loops. The gold SQL was absent from every working directory. Each arm's
`try` command runs a candidate and shows rows, never correctness.

| Arm | Sees | Writes |
|---|---|---|
| `direct` | the DDL | SQL |
| `conquer` | the model's schema listing and a one-page primer | ConQuer |
| `modelled` | the DDL and the report's FORML excerpt | SQL |
| `conquer_forml` | as `conquer`, plus the full FORML verbalisation | ConQuer |
| `modelled_full` | the DDL and the full FORML verbalisation | SQL |
| `direct_noev` | the DDL, **no evidence** | SQL |
| `conquer_noev` | the schema listing and the primer, **no evidence** | ConQuer |
| `conquer_sem` | as `conquer_noev`, against a model in which separate modeller agents encoded the evidence as derived fact types, subtypes and macros (`semantic/`); the FORML states each as `... IFF ...` | ConQuer |
| `modelled_sem` | the control for `conquer_sem`: the DDL plus the same definitions as English, evidence withheld | SQL |
| `conquer_run2`, `conquer_run3` | `conquer` again, two more independent writers | ConQuer |
| `conquer_vote` | no agent: `vote.py` keeps, per question, the candidate of the three writers whose result set the most of them share | ConQuer |
| `conquer_select` | a selector agent given the three writers' candidates, choosing one | ConQuer |
| `conquer_verified` | a verifier agent given the `conquer` arm's answers as drafts, accepting or revising each | ConQuer |
| `conquer_opus`, `direct_opus` | `conquer` and `direct` with Opus as the writer | ConQuer, SQL |
| `conquer_logged` | `conquer` again, with `try` recording **every** query tried and not only the one kept (finding 57-58). `refusals.py` replays each refused attempt under `--permissive` and runs the SQL it would have produced, which is how "do the refusals help?" gets an answer instead of an argument | ConQuer |
| `conquer_dc`, `conquer_plan`, `conquer_shots` | three writers differing in **strategy** rather than in sampling: divide-and-conquer, plan-before-writing, self-made exemplars. Finding 68: 77, 76, 75 against the base arm's 71 in one session, and the diversity the claim rests on does not appear — they agree *more* than three same-prompt writers did. **Finding 76**: re-running the first of these gave 64 and 62 with the primer, compiler and scorer each exonerated, so the *size* is not established — compare arms within a session, never across | ConQuer |
| `conquer_chase_vote` | the execution-consistency vote over those three: 76, a point below simply taking the best of them | ConQuer |
| `modelled_abstract`, `conquer_abstract` | the model's English said at Bird's second level of abstraction (`model/abstract.py`) rather than flat — a third the length. Finding 69: 68 and 65 | SQL, ConQuer |
| `modelled_full_v2`, `direct_v2` | the controls that make those two mean anything: the flat arm and the baseline re-run under the *same* prompt, since the recorded arms' prompt could not be reproduced. 70 and 68 — so the prompt was worth two points and the shaping nothing | SQL |
| `conquer_noev_lookup` | `conquer_noev` plus `./lookup "<text>"`, which finds where a literal lives in the data (`lookup.py`) | ConQuer |

| | |
|---|---|
| `questions.json` | the sample, with gold SQL (never copied into a working directory). A verbatim subset of BIRD, so not distributed: `sample.py` rebuilds it from the download |
| `material/` | per-database DDL, schema listing, FORML; the strategy prompts. The per-database files are listings of BIRD's schemas, so they are not distributed either: `material.py` regenerates them from `bench/models/`, and `../ablation/models.py` the three `schema-refs-*` variants. The primer now comes from `conquer/primer.md`, so an arm reads what `conquer.py --primer` prints; each arm's `work/` copy records the text that run was given |
| `build.py` | makes one scratch directory per (arm, database) under `work/` |
| `work/<arm>/<db>/answers.json` | what each agent wrote; `answers-before-*.json` the earlier runs |
| `score.py` | BIRD's execution accuracy, plus loud vs quiet failure, per arm |
| `results.json` | every arm, scored by `score.py` with the compiler as it now stands |
| `results-history/` | the scores as they stood at each stage: `before-fkfix` as first run; `before-gaps` after the foreign-key join fix, two databases re-run; `three-arms` after the four coverage gaps; `five-arms` with the two FORML arms; `eight-arms` before the ablation round; `sixteen-arms` after it; `before-referent` the full re-score before the referent check (finding 126) |
| `semantic/` | the modellers' how-to and checker, plus `build.sh`, which merges every fragment into `bench/models/<db>.semantic.ccm.json` — run it after `bench/run.sh`, because the merge is against the base model that builds. `work/semantic/<db>/` holds each modeller's fragment, their merged model, and the copy of `check.py` they actually ran; the evidence list each modeller was given, `definitions.json`, is BIRD's text and is regenerated by `semantic/definitions.py` rather than distributed (the copies differ from `semantic/check.py` only in how they locate the repository root; that one is canonical) |
| `lookup.py`, `vote.py`, `ablation.py` | the ablation round's tooling: the value-lookup tool, the execution-consistency vote, and the table of each arm against its base with the per-question flips and the oracle |
| `refusals.py` | the refusal experiment: 143 attempts, 7 refused, **0 of them a judgement about meaning**. What fires is parse-level, and the one real fan trap in the run compiled cleanly because the check guards aggregates and that one multiplied a projection |
| `corpus.py`, `corpus-baseline.json` | every ConQuer query the pilot wrote, recompiled against a recorded baseline: the SQL diffed character for character, and with `--rows` the old and the new run side by side to say whether the answer moved. Eleven hundred queries over eleven schemas, in under a second. Run it after any compiler change, and `--update` when the change is intended |

Every finding the pilot, and every experiment after it, exposed is in [`../findings.md`](../findings.md).

## What it found

As of the ablation round, 12 September 2026, with the scores as recorded then; `results.json`
re-scores every arm with today's compiler, which moves several by a point (the no-evidence
ConQuer arm 54 to 55, the definitions arm 62 to 63). The arms after it, and what each measured,
are in [`../findings.md`](../findings.md) and [chapter 7](../../docs/07-what-we-measured.md).

The [hand run](../archive/hand-run/README.md) before it was authored by hand, with the schema
in view, while building the compiler. This is the other experiment: a hundred mini-dev
questions, three arms, answered by fresh Sonnet agents that had never seen this repository or
the language, with the gold SQL kept out of reach. Same model, same attempt budget, same
feedback loop for every arm.

| Arm | Correct of 100 | Could not express |
|---|---|---|
| direct SQL from DDL | 70 | 0 |
| ConQuer from the model, as first run | 57 | 24 |
| ConQuer, after the fixes the run forced | **70** | 1 |
| ConQuer, plus the model verbalised in full FORML | 66 | 3 |
| SQL from DDL plus the report's FORML excerpt | 74 | 0 |
| SQL from DDL **plus the model in full FORML** | 73 | 0 |
| SQL from DDL, **evidence withheld** | 56 | 0 |
| ConQuer from the model, evidence withheld | 54 | 3 |
| ConQuer, evidence withheld, **the evidence encoded in the model as definitions** | 62 | 1 |
| SQL from DDL, evidence withheld, **the same definitions as English** | 64 | 0 |
| ConQuer, plus a verifier pass | 73 | 0 |
| **ConQuer, written by Opus** | **76** | 0 |
| SQL from DDL, written by Opus | 74 | 0 |

On the 99 questions ConQuer can now express it ties direct SQL exactly, 70 each, with the
same four-and-four split of disagreements; a model taught the language from one page wrote
it as accurately as it wrote SQL, in 1.95 attempts against 1.25. The arm that beat the
baseline is the third one: the conceptual model handed to a SQL writer as English gained
four points on its own, at the edge of the noise band, with no compiler in the loop.

The 13-point gap in the first run was coverage, not authoring, and almost all of it was defects
the pilot exposed rather than limits of the language: a foreign key to a unique column joined
to the primary key (32 of the 105 keys in the dev set; silently wrong rows), a table with no
primary key never modelled, a table with no declared keys losing its relationships, role names
never shown to the author, and no way to put two whole-query values in one row. Each is fixed,
tested and listed in [`../findings.md`](../findings.md), and the four affected databases were
re-run with identical prompts to measure it. What is left is one question needing a nested
aggregate inside arithmetic, and three answers that are probably right but take longer than two
minutes, which is the pilot's first performance finding.

**The English model helps a SQL writer and not a ConQuer writer.** The second round gave
both languages the full FORML verbalisation (the first SQL-plus-model arm had only the
report's excerpt, a quarter of the text on the biggest database). For SQL the gain is
robust to the amount of text and small: 73 and 74 against 70, with two flips each way
between the two versions -- four points, at the edge of the ±3 noise band. For ConQuer it did nothing:
66 against 70, and every point of the difference is one agent on codebase_community that
gave up on three slow queries and typed the numbers in, which the scorer correctly refused.
Question by question the two ConQuer arms agree on 89 of 100. The reason is not mysterious:
the schema listing already *is* the model, in the form a ConQuer author uses, so the
sentences add nothing a SQL writer does not already lack. What the agents said they used
the sentences for -- which values may be absent, which way a relationship is many -- is
exactly what `--explain` tells them per query anyway.

**Withholding the evidence: the semantic-layer round.** Every BIRD question comes with a
line of "evidence" -- what a code means, which column a term is, occasionally a formula,
often a particular value -- and every arm above had it. dbt's claim for a semantic layer is
that definitions held in the model do that job instead. Three more arms, with the hint
withheld from the prompt: SQL from the DDL, ConQuer from the listing, and ConQuer against a
model into which separate modeller agents had encoded the evidence as derived fact types,
subtypes and macros (`semantic/howto.md`). The modellers saw the evidence text and
not the questions; the query writers saw neither.

Withholding the hint costs both languages about the same, 14 points for SQL and 16 for
ConQuer. Encoding it into the model gets half of that back: 62, eight above bare ConQuer,
and eight short of the arm that had the hint in the prompt. Question by question it is 11
gained and 3 lost against bare ConQuer.

**The gain belongs to the definitions, not to the language.** The arm this round first left
out is the one dbt's own claim is about: a SQL writer, evidence withheld, given the same
definitions rendered as English sentences. It scores 64, which is +8 on its own no-evidence
baseline of 56 — the same +8 ConQuer gets, from the same material, two points higher in
absolute terms and so inside the noise band. Four questions are gained by both arms and
nobody else. Whatever a semantic layer is worth here, the compiler is not what delivers it;
writing the definitions down is. That is the same lesson the FORML arms taught about the
plain model, now measured for the definitions too, and it is worth stating plainly because
the first write-up of this round attributed the gain to ConQuer without having run the
control. Eight of the eleven
gains name a definition (`ProlificPostCreator`, `PercentFemaleMarvel`, `Age`,
`MostSeriousThrombosis`, `Atom19`), and one of them is Q604, which no arm with the hint
could express and which the LISA-D round said was one derived fact type away; blind, it
was. Half of the semantic arm's answers use a definition and half do not, and the accuracy
is the same in each half, 31 of 50: the definitions are used where they fit and do no harm
where they do not. The three losses are definitions that encode a different reading from
the gold's -- a normal range, a sort order -- and a wrong definition is wrong everywhere it
is used, which is the cost of a semantic layer as surely as reuse is its benefit. One more
answer, a macro whose body joined two unrelated types, was quietly wrong at modelling time
and is loudly refused now (finding 35): a definition that compiles and runs is not yet a
definition that is right, and the modellers had nothing to check against.

Why only half. The modellers were told to encode terms and not instances, and BIRD's
evidence is largely instances -- a date's format, a person's name, "TR009 is the molecule
id" -- which is what a question supplies and a model should not hold. The eight points
still missing are mostly that. The other half of the story is finding 28: seven of the
eleven modellers reported minimum, maximum, average, pattern and absence definitions as
inexpressible, and were right about the how-to and wrong about the language; once the
syntax was shown every one of them compiled. What the author cannot see does not exist.

The round also found nine compiler defects (findings 20 to 35), three of them silent
wrong answers -- a boolean test dropped, a grouped aggregate over a cross product, a bound
variable joined to the head -- each fixed with tests. All four ConQuer arms were re-scored
with the fixed compiler; the earlier arms did not move.

**The ablations: what closes the gap and what does not.** Eight more arms, each adding one
thing to the ConQuer arm (or to the no-evidence arm where the thing addresses what withholding
the evidence took away), scored with the same compiler as everything else after the round's
fixes had landed (the base arm moved from 70 to 71 when finding 36 let Q604 run).

| Adds | Arm | Base | Gained | Lost |
|---|---|---|---|---|
| a second independent writer, same prompt | 68 | 71 | 2 | 5 |
| a third | 68 | 71 | 2 | 5 |
| execution-consistency vote over the three | 71 | 71 | 1 | 1 |
| a selector agent over the three's candidates | 70 | 71 | 2 | 3 |
| a verifier pass over the base arm's answers | **73** | 71 | 2 | 0 |
| a stronger writer (Opus for Sonnet), ConQuer | **76** | 71 | 7 | 2 |
| a stronger writer, SQL from the DDL | 74 | 70 | 8 | 4 |
| a value-lookup tool, evidence withheld | 57 | 54 | 5 | 2 |

- **Run-to-run variance is three points.** Three writers with the same prompt scored 71, 68
  and 68. Anything under that is noise, which retires several of the earlier round's
  two-point readings, in both directions.
- **Candidates and selection bought nothing at this scale.** The three writers return the
  same rows on 79 of 100 questions, and on 17 of those 79 they are unanimously wrong: the
  same misreading of the question, or the gold's own quirk. The oracle over the three is 74,
  three above the base; the vote reached 71 and the selector agent 70. Where the writers
  disagree (21 questions) the selector picked right about as often as the first writer did.
  Selection helps when candidates are diverse; three Sonnets with one prompt are not.
- **A verifier is the one cheap gain:** plus two, minus none. It caught a role read as
  required that dropped a row (`OPTIONALLY`) and a column projected that was not asked for.
  Both are the compiler's own warnings, read by someone with time to read them.
- **The writer is the largest lever.** Opus for Sonnet is worth five points for ConQuer and
  four for SQL; ConQuer with Opus, 76, is the highest arm in the pilot, two above SQL with
  Opus, which is inside the noise. The gains are on the same questions in both languages
  (898, 1094, 1135), which says they are the model reading the question better, not the
  language.
- **The lookup tool gets back a fifth of the evidence gap.** 57 against 54 without the hint,
  14 short of with it. It resolved codes and names ("Czech Republic" to `CZE`); what it
  cannot resolve is a threshold the hint supplies ("normal range", "abnormal CRP").
- **The ceiling.** The oracle over all sixteen arms is 81: nineteen questions no arm has got
  right, most of them the gold's reading of an ambiguous question. The remaining gap is mostly
  not authoring.

Two process notes. One lookup batch had to be re-run because its agent wrote the results
into the answer field instead of the queries (finding 19 again; the scorer caught it), and
one run-2 batch had to be told to stop waiting on a slow query and write what it had. The
round also found five more compiler defects (findings 36 to 40), one of them the timeouts of
finding 15, fixed by decorrelating equality-correlated aggregates.

Two caveats. Every arm tested its answers before submitting, so the loud-versus-quiet
distinction collapsed and needs a no-feedback arm to measure. And keeping agents out of the
rest of the repository, where the hand-written example queries live, rested on instruction
rather than a wall; the gold SQL, which is what matters, was under my control absolutely.
