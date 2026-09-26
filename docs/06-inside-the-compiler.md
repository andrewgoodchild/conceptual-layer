# 6 — Inside the compiler

For anyone changing it. If you only want to *use* it, [3](03-writing-conquer.md) and
[5](05-the-toolchain.md) are enough.

## Four representations, three steps

```
ConQuer-92 text
   │  parser.py    schema-driven; the grammar is appendix B of the 1994 report
   ▼
path-expression AST                ConQuer's own algebra. Surface operators intact, so the
   │                               report's §8 verbalisation can run here.
   │  lower.py     flatten, coerce, resolve denotations
   ▼
Common Core Model block            flat, fully explicit, exportable, model.md §4
   │                               normalise.py runs back *up* from here (--normalise)
   │  sql.py       model/binding-sql92.md
   ▼
SQL-92  ───────────────────────►   rows
```

The two-level split is the load-bearing design decision. The AST is where the report's
semantics are stated; the CCM block is where SQL is one step away. Putting the report's
operators straight into SQL would have meant no place to state the semantics, and no place to
verbalise from.

## The parser is schema-driven, necessarily

Appendix B's grammar is ambiguous on purpose: a step is a *verb part* plus an *information
descriptor*, and which fact type a verb part names cannot be decided without knowing the model
and what the path has reached so far. So the parser filters candidate fact types by the current
head's type, then by the type named next, and raises `Ambiguous` when more than one survives.
It never guesses silently.

Two consequences worth knowing:

- **`Lexicon` is built from the model**, and `--schema` prints it. A verb part exists because a
  reading in the model spells it.
- **Names are resolved against two different questions.** `Index.by_name` answers "what is this
  word", and includes every concept. `Index.object_names` answers "can this word stand where a
  *type* goes", and excludes non-objectified fact types — nothing is an instance of a
  relationship. Asking the first where the second was meant is how `DEFINE TopEarner` once made
  the verb `has TopEarner-` unreachable: it lost to its own name.

## Lowering is where the judgements live

`lower.py` turns the AST into a CCM block, and on the way makes three claims a parser cannot:

```python
check_rooted(block, refuse)               # a node nothing reaches is a cartesian product
check_window_over_groups(block, refuse, lex)   # a window over rows GROUPED BY collapsed
regroup_bag_only(block, lo)               # a median on SQLite needs a bag to be spelled over
check_aggregate_locality(block, lex, refuse)   # an aggregate over multiplied rows
Lowering.check_unifiable(a, b)            # a value equated with an instance
```

All three go through `Lowering.refuse`, which raises `Judgement` — or, under `--permissive`,
records the message and carries on. That is the whole mechanism, and it is deliberately narrow:
a `Judgement` is suppressible by construction, so the counterfactual can always be run.

`check_aggregate_locality` is the interesting one. It asks, for each aggregate, whether any
step on its path can multiply — which is exactly what a uniqueness constraint answers — and
settles to a fixed point, honouring spanning uniqueness so a genuine many-to-many is not
flagged. The first version got that wrong and the metamorphic tests found it within a minute.
It and the window check share one `Determination` object per block — the union-find over
unified nodes, how each node was reached, and the walks that read the uniqueness constraints
(`chain`, `determinants`, `pins`, `settled`, `fixes`) — so "what does this set of nodes fix"
has one answer. When a grouped value *does* repeat within its group, the aggregate is
re-lowered into a bag of its own, correlated on the keys (`regroup_grouped`), where section
14b's each-value-once semantics apply; the same route carries a grouped median on SQLite.

## Emission

`sql.py` renders a block. Things to know before changing it:

- **Every renderer returns a `Frag`** — SQL text with the parameters its placeholders bind,
  composed with `+`. A fragment spliced into a clause other than the one it was rendered in
  carries its parameters with it, and `render` assembles the clauses once at the end, so the
  statement's parameter list is the text order by construction. Four silent wrong-answer
  defects were the previous scheme — one parameter list per clause, filled as a side effect —
  getting out of step with the text (finding 160). Do not reintroduce a sink.
- An aggregate over a bag is emitted by **one path**: project the value (and whatever rides
  along — dedupe keys, a second operand, an order and a cut), emit the block as a derived
  table, aggregate over it outside. A dialect that can spell an aggregate only over a bag
  (`sqlBagTemplate`) uses the same path.
- A `WITHIN` value filtered on wraps the query, because SQL evaluates windows after `WHERE`;
  the wrapper's `WHERE` is a clause of its own, after the inner `GROUP BY`.
- A bracketed sub-expression becomes `EXISTS`, always. That is what makes filtering and joining
  different ([3](03-writing-conquer.md#brackets-the-difference-between-filtering-and-joining)).
- A derived concept — a model derivation rule, or a query-local `DEFINE` — becomes a common
  table expression, `WITH RECURSIVE` when the rule mentions its own target.
- A confluence element the model allows to be many per junction becomes `json_group_array`,
  which is how a nested result comes back rather than as extra rows.
- Dialect-specific spellings go through `sqlTemplate` on the model's functions, because
  `YEAR()` is a runtime error on SQLite and `strftime('%Y', …)` is not.

The emitted SQL is naive. It is readable and correct, not fast.

## Adding to the language

The path, roughly, for a new construct:

1. **Find it in the report first.** Most of what looks missing is in there under another name;
   `conquer/conquer-2026-grammar.ebnf` is the grammar as implemented (the 1994 grammar it
   grew from is the report's appendix B; `CITATION.cff` cites the report) and
   `conquer/conquer-2026.md` records everything added beyond it, with the reason.
2. Parse it into the AST (`parser.py`), keeping the surface operator intact.
3. Lower it (`lower.py`) into existing CCM shapes if you possibly can — `DEFINE` added no new
   machinery at all, it reuses derivation rules.
4. Emit it (`sql.py`).
5. Cases in `conquer/tests/test_operators.py`, asserting the SQL *and* the rows.
6. Make `--normalise` round-trip it, and `--explain` say something true about it.
7. Run `bench/pilot/corpus.py`. It compiles 2,175 recorded queries and compares the SQL text
   *and the parameter list* against the baseline. If an unrelated query moved, find out why
   before updating the baseline; `--rows` runs old and new to say whether the answer moved.

If the construct *refuses* anything, raise it through `Lowering.refuse` so `--permissive` can
suppress it, and add a case to `test_errors.py` with `Judgement` as the expected class — the
permissive replay is driven off that class, so a new judgement is measured automatically.

## Where the bodies are buried

`bench/findings.md` records all 165 findings the work produced, each with what it cost
and how it was found. It is the most useful file in the repository for anyone extending this, and
several entries are about the compiler being confidently wrong rather than failing.

---

Next: [7 — What we measured](07-what-we-measured.md).
