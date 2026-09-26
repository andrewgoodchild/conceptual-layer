# What Malloy does with the fan trap

The project's 16 September plan (since retired) bet that this project's reverse-engineered
uniqueness constraints can supply the `join_one`/`join_many` that makes Malloy's fan-out
handling correct. That was asserted. This probe checks it, on the same fixture and the same
three traps as `conquer/tests/test_fanout.py`.

    python3 -m pip install duckdb
    cd bench/malloy-probe && npm install @malloydata/malloy @malloydata/db-duckdb
    python3 build.py
    node run.mjs . queries.json

`npm install` has to be in this directory: `run.mjs` resolves `@malloydata/*` from its own
location. Neither `node_modules/` nor the built `company.duckdb` is committed.

`company.malloy` is written by hand with the cardinality the reverse engineer *does* infer
(when the probe was run, 91% recall at 100% precision for primary keys and 81%/100% for BIRD
foreign keys; 94% and 81% now), so it stands in for what a generator would emit.

## What it found

**Malloy has two mechanisms, not one.**

1. **Join elimination.** If the aggregate names nothing from the joined source, the join is
   dropped: `SELECT COUNT(1) FROM employee as base`. No fan-out because no join.
2. **A synthesised row key.** When the join is needed, each row of the many side gets
   `GEN_RANDOM_UUID() AS "__distinct_key"` and counts become `COUNT(DISTINCT __distinct_key)`;
   sums become `SUM` over `UNNEST(list(distinct {key: <pk>, val: <value>}))`.

The second is the same idea as this compiler's fix — deduplicate (determinant, value) pairs —
expressed in DuckDB's struct and list functions rather than a derived table. Ours is plainer SQL.

## The three gaps

| | |
|---|---|
| **Grouped fan-out** | Malloy computes it (ENG 2,400,000 / SALES 900,000 / HR 300,000 beside heads 3/2/1); **this compiler refused**, when the probe was run. The common BI shape, and the real gap — since closed: where the group keys pin the value (finding 82), and where they do not, by deduplicating over a bag of its own (finding 117). |
| **Joins are outer** | The emitted SQL is `LEFT JOIN employee AS emps_0`. A ConQuer path step is *inner* — reading a role asserts it exists. So a CCM path step is **not** a Malloy join, and a generated model answers 808,500 where the compiler answers 720,500. A generator must emit a filter for mandatory steps or the two disagree. |
| **COUNT grain** | Malloy deduplicates counts, but resolves *which* grain by **where the measure is declared**: `emp_count is count()` on `employee` counts employees, `asg.count()` counts assignments. The author picks the grain when authoring the model, not when writing the query. That is why Malloy never faces the dilemma finding 79 measured — refusing a fanned COUNT costs 20 right answers per 5 wrong, deduplicating it scores net −1 — and it is the better design of the three. |
