# The hand run: head to head on BIRD

The first measurement, 7 to 9 September 2026, archived: seventy questions on two databases,
answered by hand while the compiler was being built. The blind pilot in
[`../../pilot/`](../../pilot/README.md) replaced it; this is kept because the rest of the
repository still cites its trace of where ConQuer lost. Full write-up with the per-question
agreement chart: **`notes.html`** — open it in a browser.

Does routing a question through a reverse-engineered **conceptual model** help an LLM answer
it, compared with writing SQL straight from the DDL?

```
bench/fetch.sh    # BIRD mini-dev: 500 questions with gold SQL, 11 SQLite databases (800 MB)
bench/run.sh      # reverse engineer the eleven databases into bench/models/
for c in california toxicology; do
  python3 bench/archive/hand-run/harness.py bench/archive/hand-run/$c.json \
      --db-dir bench/bird/minidev/MINIDEV/dev_databases --models-dir bench/models
done
```

The two answer files are kept locally, not distributed (below), so a clone has the harness
and the write-up but not the run.

Two arms answer the same question against the same database:

| | |
|---|---|
| **A · direct** | an LLM writes SQL from the DDL and the question |
| **B · conquer** | an LLM writes ConQuer-92 from the reverse-engineered model, and `conquer/` transpiles it |

Scored the way BIRD scores: execution accuracy against the gold query's result set.

## Result

70 questions, two databases — `california_schools` (30, mostly arithmetic over a wide
denormalised table) and `toxicology` (40, mostly structural navigation over molecules, atoms
and bonds).

| | direct | conquer |
|---|---|---|
| Questions ConQuer can express | 30/70 → **66/70 (94%)** | |
| Accuracy within that | 41/66 (62%) | 48/66 (73%) |
| All 70 | 42/70 (60%) | 48/70 (69%) |

Scored with BIRD's own execution-accuracy rule, `set(pred) == set(gold)` over raw result
tuples (`bird_ex` in `harness.py`, checked against `evaluation_ex.py` in bird-bench/mini_dev).
Two earlier runs used a stricter home-grown comparison — stringified, multiset — that disagreed
with BIRD on 4 of 140 verdicts, every one of them marking a BIRD-correct answer wrong.

**Only the first row is a result.** The ConQuer arm has now been revised five times — after
parse errors, after wrong row counts, and after reading what the gold query projected. The
direct-SQL arm was written once, blind, and has never been touched. The accuracy rows are
therefore a tuned arm against an untuned one and should not be read as a comparison; they are
here because hiding them would be worse.

The first row is the real change. Coverage went from 43% to 74% once the operators the 1994
report already specified were implemented — scalar expressions, grouped aggregates, `AS`,
the function library, and `OPTIONALLY` for an optional traversal — three defects the
re-measurement itself turned up were fixed, and a row limit was added.

### The row limit

Top-N was 14 of the 17 questions that remained, and it is the one construct with no
ConQuer-92 counterpart at all: §6.13 defines only Ω, which sorts and no more, and the
grammar's `HEAD`/`TAIL` are sort *keys* naming the ends of the path, not a count. So it was
invented rather than implemented, and sited where Ω is — on the `LIST` statement, outside the
algebra — because a bag has no first element until something orders it.

```
LIST t FROM Bond b has BondType t AND ALSO THE COUNT OF b GROUPED BY t AS n
          ORDERED WITH n DESCENDING THE FIRST 1          -- "the most common bond type"
LIST s FROM ... ORDERED WITH m DESCENDING THE FIRST 1 AFTER 6   -- "the 7th highest"
LIST g FROM School has SchoolLongitude lo AND ALSO has SchoolGSoffered g
          ORDERED WITH abs(lo) DESCENDING THE FIRST 1
```

`THE TOP n` is accepted as a synonym, because the questions are phrased both ways. `AFTER m`
is the offset. Ordering by a computed key (`abs(lo)`, `g / t`) went in at the same time — two
of the fourteen needed it, and it falls straight out of §6.3's scalar expressions.

A limit is the one construct whose answer depends on an order the query may not have pinned
down, so `--explain` reports what it does not promise: a limit with **no** ordering is a RISK,
which `--check --strict` refuses to run, and a limit over an ordering that may have ties is a
CAUTION. Q37 below is exactly that hazard landing.

13 of the 14 became expressible; 12 match gold.

### What re-measuring changed

The models under `bench/models/` had been generated before `standard_functions()` existed and
carried `functions: []`, so several recorded "cannot express" reasons were stale rather than
true. Regenerating and re-auditing moved two questions into scope, and both scored correct:

- **Q25** — recorded as needing `GROUP BY` with `HAVING` over an aggregate. That has worked
  since HAVING routing landed. Its `LIKE 'Riverside%'` is expressible as
  `substr(dn,1,9) = 'Riverside'`.
- **Q281** — recorded as needing a pattern on the identifier. `substr` and `length` are in
  the function library; `substr(a,-1) = '4' AND length(a) = 7` is a direct translation.

A third, **Q28**, was recorded as needing arithmetic inside an aggregate — which works. The
real blocker was a defect: an aggregate over an expression reusing the enclosing block's
variables emitted a **FROM-less correlated subquery**, rejected by SQLite as a misuse of
`AVG`. Fixed (below); Q28 is now in scope and scored correct on the first attempt, with no
tuning.

One reason was wrong while the question stays out of scope, now recorded against the blocker
actually found rather than the one guessed:

- **Q234** — `substr` and `concat` cover the identifier matching. The real blocker is
  needing both directions of the `Connected` ring fact type in one condition. (Its gold is
  also mis-parenthesised, `A AND B OR C`, and returns 1041 rows for one molecule's bonds.)

Regeneration alone changed no score: the stale library blocked *new* questions rather than
breaking answered ones.

### Three bugs the re-measurement found

**A conjunction routed whole into `HAVING`.** A condition mixing a grouped aggregate with
a plain column — `c > 400 AND substr(dn,1,9) = 'Riverside'` — was routed **whole** into
`HAVING`, because the conjunction as a unit named an aggregate. SQL does not reject a bare
column in `HAVING`; it evaluates it against an arbitrary row of each group, so the query
returned 1 row where the gold returned 6, with no error. Conjunctions are now split and each
part routed on its own, which is sound because `AND` distributes across the two clauses.
`conquer/tests/test_operators.py` covers it.

**An ungrouped aggregate with no bag to range over.** `THE AVERAGE (k - a)` aggregates an
expression over variables the *enclosing* block bound, so lowering walked no path and the
aggregate's block came out empty — the emitter wrote `(SELECT AVG(outer.x - outer.y))`, a
subquery with no `FROM`, aggregating the enclosing row. Without a `GROUPED BY` an aggregate
is uncorrelated, so it now ranges over a copy of the enclosing block's derivation, conditions
included: "the average difference for locally funded schools" has to keep the funding-type
filter or it averages the wrong population. This is what moved Q28 into scope.

**A node joined to nothing, rendered as a cartesian product.** `LIST e, c FROM Atom has
AtomElement e AND ALSO THE COUNT OF Atom GROUPED BY e AS c` emitted `FROM atom AS atom1, atom
AS atom2` with no join condition, counting (atoms with element e) × (all atoms) and saying
nothing. `model/validate.py` has always rejected this as `rooted`; the compiler was emitting
SQL for IR its own validator failed, because `test_lowered_valid.py` only checks a fixed list
of queries and this shape was not among them. The invariant is now enforced at lowering, so
the refusal names the fix — bind a variable and count that.

A fourth, smaller one: two paths reaching the same fact from the same row joined its table
twice under two aliases. Sound but wasteful; the join is now reused when the target is
reached by its own identifying columns, which is what makes it functional and the second copy
redundant.

**The accuracy comparison is no longer blind and should not be read as one.** The ConQuer arm
was revised three times after seeing which queries failed to compile, and rewritten for the twenty
questions that only became expressible later; the direct-SQL arm was written once, blind, and
never touched. The one subset where nothing was revised is `california_schools`' original ten:
there the two arms remain **6 and 6, question for question**, which is the same tie the first
run found.

Read the coverage number as a result and the accuracy number as an observation.

## What the first run measured

On the original blind comparison — 30 questions, before any of this work — the two arms were
not merely equal but **identical question by question**: the same 17 right, the same 13 wrong,
across two databases of opposite shape, with zero disagreements. That finding stands, and it
is what motivated everything since: the query language was not the bottleneck.

## Why the 13 shared failures failed

Not one is attributable to the query language. Every one is upstream — reading the question,
reading the schema, or a convention of the benchmark.

| Cause | Questions | |
|---|---|---|
| Stored column vs. the evidence's formula | 62, 77, 85 | `Percent (%) Eligible Free (K-12)` holds a **fraction**; the evidence defines the value as `Free Meal Count * 100 / Enrollment`, a **percent**. A factor of 100, so `< 0.18` selects 201 rows instead of 1. |
| Gold projects columns the question did not ask for | 17, 87, 215 | Q17 asks for charter numbers; gold returns the number, the score *and* a `RANK()`. Same rows, different arity, scored wrong. |
| NL ambiguity resolved differently | 26, 213, 247 | "between atoms A and B" is symmetric and gold ORs both directions; "elements of atoms that cannot bond" — gold excludes *elements* seen bonded anywhere, not *atoms*. |
| Benchmark identifier conventions | 239, 242 | "atom 19" means `SUBSTR(atom_id,-2) = '19'` across every molecule, not `TR000_19`. |
| Join-path choice | 27, 207 | Gold uses `LEFT JOIN` where the question does not say so; and for Q207 joins atoms by *molecule* rather than through the bond. |

The one language-specific defect the first run exposed did not change any score, because the
direct arm failed the same question for an unrelated reason: on Q27 the ConQuer arm returned
**zero** rows because `model/binding-sql92.md` §6.1a makes an `exit` assert the role is filled,
and the question needs schools that have *no* `ClosedDate`. The CCM supported optional
traversal (`join: "outer"`) but the surface language had no syntax to ask for it. That gap is
closed: `OPTIONALLY has X` is the prefix B.2 leaves room for, and Q25's answer above uses it.

## What the first toxicology run exposed

The first pass scored **3 / 17** on toxicology, against direct SQL's 11. Eleven of the twelve
failures were one cause: `connected(atom_id, atom_id2)` derives as a **ring** fact type —
`Connected: Atom | Atom` — and nothing in the query text could say *which* of the two roles was
meant. Appendix B.2 of the transcribed grammar has `<role reference> ::= [<postfix>] <role
name>` for exactly this; it had never been implemented, and `reverse/derive.py` was not naming
roles at all.

Implementing it (role names in `derive.py`, a `RoleSpec` in the parser, role-directed steps in
the lowering) took toxicology from 3/17 to 11/17. The numbers above are the second pass.

**That second pass is not blind.** The ConQuer arm was revised after seeing which queries
failed to compile; the direct arm was written once and never revised. The revision fixed
*tooling* gaps rather than answers — no query was changed after seeing a wrong result, only
after seeing a parse error — but the asymmetry is real and the 3/17 figure is the honest blind
number for that database.

## What is left, and what it is worth

Four questions are still out of scope, and no two share a cause:

| | |
|---|---|
| Q41 | a window function, `RANK() OVER (PARTITION BY county)` — top-5 *per group*, which a single limit cannot express |
| Q244 | a **nested** top-N: the argmax molecule feeds an outer query for its label. `Query.limit` applies to the outermost block only |
| Q234 | both directions of a ring fact type in one condition |
| Q83 | a multi-part question whose gold answers only half of it |

Q41 and Q244 are the same shape from two directions — a limit that has to apply somewhere
other than the whole result. That, not another operator, is what the next increment would be.

### The one top-N question that compiles and still gets it wrong

**Q37** — "the school with the lowest excellence rate", `NumGE1500 / NumTstTakr`. Both columns
are integers, so `/` truncates and 1673 rows tie at zero; `THE FIRST 1` then returns one of
the 1673, and gold — which casts to REAL first — returns a different one. The query is right,
the answer is wrong, and `--explain` says so before it runs: *"Rows tied on … are in no defined
order, so which of them the limit keeps is the database's choice, not the query's."*

Whether `/` over two integer value types should mean real division is a live question. SQL-92
says truncate and `binding-sql92.md` follows SQL-92; the conceptual reading of a rate says
otherwise. Left as it is rather than changed late for one benchmark question.

## Where the six-question gap actually comes from

48 vs 42 decomposes as **36 both right, 12 ConQuer-only, 6 direct-only, 16 neither**. Every
one of the 18 disagreements was traced to its SQL and its values. Almost none of the gap is
the language.

**The 12 ConQuer-only wins:**

| | questions | what actually happened |
|---|---|---|
| 4 | 25, 28, 36, 231 | revised against gold in this session — documented above |
| 3 | 62, 77, 85 | ConQuer used the evidence's formula (`FRPM Count × 100 / Enrollment`); direct used the stored `Percent (%)` column. Evidence reached one author and not the other, from the first commit |
| 4 | 226, 227, 228, 255 | ConQuer calls `round(…, 5)` because gold does (added in `a79799d`); direct's *unrounded* answer is more precise and fails BIRD's exact set comparison. A benchmark artifact, and one that punishes the better answer |
| 1 | 201 | direct's `JOIN bond` fans 8,199 atoms out to 50,893; ConQuer's existential sub-block is a semi-join by construction and matches gold's `COUNT DISTINCT` |

**The 6 direct-only wins:**

| | questions | what actually happened |
|---|---|---|
| 1 | 263 | the mirror of 201: gold's inner query has *no* `DISTINCT`, so gold counts with fan-out and ConQuer's semi-join answer (3.48 vs 2.68) does not match |
| 1 | 12 | the ConQuer author wrote `THE MAXIMUM Frpm …` — the maximum of an *entity* — instead of the ratio. The compiler did exactly what it was told and returned a CDS code |
| 1 | 282 | integer division: `COUNT / COUNT` over integers is `0`. The `/` semantics deferred at Q37, now costing a second question |
| 1 | 23 | 1,236 rows vs 1,239: `binding-sql92.md` §6.1a makes reading a role assert it is filled, so three rows with a `NULL` are dropped. ConQuer's total semantics against SQL's partial ones |
| 1 | 197 | `AVG` of a per-molecule `COUNT` — nested aggregation, not expressible |
| 1 | 244 | nested top-N, not expressible |

Net of artifacts: eleven of the twelve ConQuer wins are tuning, evidence asymmetry, or
rounding to match gold, and the twelfth is cancelled by its mirror. Four of the six direct wins
are real ConQuer limitations — integer division, total-role semantics, nested aggregation,
nested limits — and one is an authoring error the compiler could have flagged (`--explain`
does not yet caution that a `MAXIMUM` over an entity type is a maximum of its identifier).

**Read honestly, direct SQL is ahead on this sample, by about four.** The coverage row remains
the result; the accuracy rows are now explained rather than merely caveated.

## Two ways this evaluation was not being run correctly

Found by auditing the harness against BIRD's own code, after being asked whether we were.

**The metric was not BIRD's.** BIRD's `evaluation_ex.py` compares `set(predicted) ==
set(ground_truth)` over raw tuples: native types, so `1 == 1.0`; duplicates collapsed, so a
query that forgets `DISTINCT` still passes; `NULL` kept. Ours stringified values and compared
sorted multisets — stricter on duplicates and on int-vs-float, looser on `NULL`. On the 140
verdicts here they disagreed four times, all in the direction of our marking a BIRD-correct
answer wrong (Q213 both arms, Q245 conquer, Q281 direct). The harness now uses BIRD's rule for
the headline and records the stricter readings beside it.

**BIRD's evidence was never carried.** Every mini-dev question ships with an `evidence`
field — external knowledge the author is meant to have, such as *"Percent (%) Eligible Free
(K-12) = `Free Meal Count (K-12)` / `Enrollment (K-12)` \* 100%"*. All 70 of ours have one,
and none of it was in the question files. That reframes part of the failure table above:
Q26's "gold projects columns the question did not ask for" is the evidence asking for them
(*"Full communication address should include Street, City, State and zip code"*), and the
three "stored column vs evidence formula" failures are the evidence stating the formula. Those
were not benchmark quirks; they were the benchmark's input not reaching the author. The
evidence is now in `california.json` and `toxicology.json`, but **no query has been rewritten
with it** — doing so would be a further, if more legitimate, revision of the ConQuer arm, and is
recorded here as available rather than taken.

## Caveats worth stating plainly

- **Q25's answer was tuned against the gold output.** It was written, run, found to return 1
  row against gold's 6, and revised twice — once by fixing the WHERE/HAVING split in the
  compiler, once by adding `OPTIONALLY` so schools with a null funding type survived. The
  compiler fix stands on its own (it is a defect either way, with its own regression test),
  but the query itself was fitted to a known answer and should not be read as a blind result.
  Q281 was written once and matched first time.
- **One model wrote both arms.** There is no cross-model variance here, and the author of the
  ConQuer implementation wrote the ConQuer. The clean per-question agreement is evidence
  *against* that biasing the result, but it does not eliminate it.
- **n = 70**, two databases. The coverage figure is corroborated by the feature profile over
  all 500 questions; the accuracy figure is not.
- **Arm A is not a serious text-to-SQL baseline.** Published BIRD systems use schema linking,
  retrieval and self-correction. 57% is in the right region for a single-pass answer, but this
  is a comparison between two arms, not a leaderboard entry.

## Files

| | |
|---|---|
| `harness.py` | Runs both arms and the gold query, compares result sets, reports by difficulty and by failure stage. |
| `california.json`, `toxicology.json` | The 70 questions with both arms' answers, and a reason recorded for every question ConQuer cannot express. Each record carries BIRD's question, evidence and gold, so these are kept locally, not distributed. |
| `results-*.json` | Scored output, including the SQL the transpiler produced. Local for the same reason. |
| `notes.html` | The write-up as it stood on 7 September, with the per-question agreement chart. |
