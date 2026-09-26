# Binding: CCM → SQL-92

The lowering the whole project exists to perform. A CCM `Block` is a `SELECT` block; the
correspondence is close enough to be mostly mechanical, which is the point of normalising to
the CCM rather than compiling ConQuer's algebra directly.

Prerequisite: a `RelationalMapping` (`model.md` §6). Absent one, the compiler refuses the model;
it does not derive a default Rmap.

---

## 1. The correspondence at a glance

| CCM | SQL-92 |
|---|---|
| `Block` | one `SELECT` block |
| `Node` | a table alias, or a column of one already in scope (§2) |
| `Step{kind:"enter", join:"inner"}` | `JOIN` the role's table |
| `Step{kind:"enter", join:"outer"}` | `LEFT OUTER JOIN` |
| `Step{kind:"exit"}` | read another column of the row already joined — **no join** (§2) |
| `Unification` | an equality predicate, or alias sharing when it can be elided |
| `Node.restriction`, `restriction` condition | `WHERE` (`BETWEEN`, `IN`) |
| `conditions` | `WHERE`, conjoined |
| `subBlocks` with `combinator:"and"` | correlated `EXISTS`, conjoined |
| `subBlocks` with `combinator:"or"` / `"xor"` | `OR` / exclusive-or over `EXISTS` |
| `Block.negated` on a sub-block | `NOT EXISTS` |
| `Calculation` (non-aggregate) | a scalar expression |
| `Calculation` with `aggregation.context` | an aggregate + `GROUP BY` over the context nodes |
| `aggregation.context: "universal"` | an aggregate with no `GROUP BY` |
| `aggregation.distinct` | `COUNT(DISTINCT …)`, `SUM(DISTINCT …)` |
| `Projection` | one `SELECT` list item, `AS` its `name` |
| `Block.distinct` | `SELECT DISTINCT` |
| `Invocation` | a correlated subquery, or a `WITH` view of the invoked query |
| `SetExpr` | `UNION` / `INTERSECT` / `EXCEPT` (`… ALL` when `all`) |
| `Query.ordering` | `ORDER BY` on the outermost block only |
| confluence element (§6.5) | `LEFT JOIN` from the junction, every step; the base path stays a natural join. The report's ⟕. On a junction role that is mandatory the fact is always present, so an inner join is the same relation and is what is emitted |
| `Query.limit` with `per` | the query becomes a derived table with `ROW_NUMBER() OVER (PARTITION BY per ORDER BY …) AS "__rn"`; the outer query keeps `"__rn" <= count` (and `> offset`). The window's ORDER BY sits in the SELECT list, so its parameters bind with the select list's |
| a `(LIST …)` bag with ordering or a limit | wrapped as `SELECT "v" FROM (…)`: in a compound SELECT, ORDER BY and LIMIT belong to the compound, not the operand they follow |
| `Query.limit` | `LIMIT ?` on the outermost block, `OFFSET ?` when the offset is non-zero. Bound last, after the ORDER BY parameters, because that is where the placeholders are in the text. |
| `DerivationRule.storage` | `CREATE VIEW` vs. a materialised table (§7) |

---

## 2. Nodes and steps are not one-to-one with tables and joins

The step model is ConQuer's, and it deliberately names more than SQL does.

An `enter(r)` moves from a node typed `Player(r)` to a node typed `Rel(r)`. Under the mapping,
`Rel(r)` is a table (or, for a binary fact type absorbed into an entity table, *is* that entity
table) and the entry is a join on `roleMap[r].columns`. An `exit(q)` moves from the fact node to
a node typed `Player(q)` — that is just reading `roleMap[q].columns` of the row already in hand,
and emits **no** SQL join at all.

So the canonical two-step traversal `enter(p); exit(q)` produces exactly one join. Emitting one
per step would double them.

Three cases the emitter must handle:

- **Absorbed fact type.** A functional binary fact type mapped into the entity's own table —
  reverse-engineering rule 2 in `reverse/README.md` produces
  these in bulk. Both the entry and the exit are column reads on an alias already in scope; the
  join count is zero.
- **Its own table.** An n-ary or many-to-many fact type. The entry is one join; the exit is a
  column read.
- **Objectified fact type referenced as a node.** The fact node is projected, restricted or
  aggregated over. It needs its own alias, and its identity is `conceptMap[f].identifyingColumns`.

**Alias elision.** A `Unification` between a node reached by `exit(q)` and a node that is the
`from` of a subsequent `enter(r)` where `roleMap[q].columns` and `roleMap[r].columns` reference
the same key — the overwhelmingly common case — needs no separate alias and no predicate: the
join condition absorbs it. Elide first, then emit predicates for what is left. Without this the
generated SQL is correct and unreadable.

---

## 3. Reference schemes cost nothing here

`model.md` invariant §7.1.1 requires every reference-scheme walk to be materialised as real
steps, so a CCM block carries visibly more steps than the ConQuer text that produced it
(`HdCoerce`, `TlCoerce` and the denotation abbreviations all expand during lowering).

Under a mapping produced by reverse-engineering rules 1–2, those extra steps land on the *same
column* — an entity is identified by its primary key, and the reference-scheme fact type is
absorbed into its table. They therefore cost zero joins in the emitted SQL. The explicitness is
paid for at IR level, where it buys exportability, and refunded at emission.

This is also why the report's §7.13 `Denote` and its §5.9 entity-to-value expansion have no SQL
stage of their own: they already happened.

---

## 4. Aggregation

`aggregation.context` is the set of nodes held fixed while the bag is collected, which is
exactly `GROUP BY`. The emitted grouping columns are the identifying columns of each context
node, not the node's whole row.

- `context: "universal"` → no `GROUP BY`.
- `context: []` → also no `GROUP BY`. Distinguish these two in the CCM only if a target dialect
  ever needs to; SQL-92 does not.
- `distinct: true` → `DISTINCT` inside the aggregate call.
- A `Calculation` used in a condition rather than a projection lands in `HAVING`, not `WHERE`,
  whenever its aggregation context is the enclosing block's grouping.

ConQuer's `Where(P, C)` example — *"Person who earns a Salary x AND ALSO works for a Company c
WHERE x > THE AVERAGE Salary of a Person who works for c"* — is a correlated aggregate
sub-block, not a `HAVING`: the average is over a different extent than the outer grouping.
Decide `HAVING` vs. correlated subquery by comparing the calculation's context with the block's,
never by syntax.

---

## 5. Set comparisons

`setCompare` is first class in the CCM precisely so it can be emitted directly rather than
through the ¬∃¬ encoding. For bags `L = (block_L, node_L)` and `R = (block_R, node_R)`,
correlated to the enclosing block:

| `op` | SQL-92 |
|---|---|
| `subset` | `NOT EXISTS (SELECT nodeL FROM blockL EXCEPT SELECT nodeR FROM blockR)` |
| `superset` | the same with `L` and `R` exchanged |
| `match` | both of the above, conjoined |
| `properSubset` | `subset` and `NOT match` |
| `properSuperset` | `superset` and `NOT match` |
| `disjoint` | `NOT EXISTS (SELECT nodeL FROM blockL INTERSECT SELECT nodeR FROM blockR)` |

`EXCEPT` and `INTERSECT` are in SQL-92. On a dialect lacking them, fall back to
`NOT EXISTS (… AND NOT EXISTS (…))`, which is the same encoding `binding-ormcore.md` §3 uses for
export — correct, and harder to read.

The report's *other* circled-times — the underlined `⊗` of §6.2, the complement of concatenation
— is not a `setCompare`. It arrives as a `SetExpr{op:"except"}` over a cross block and a
concatenation block and needs nothing special here.

---

## 6. Null semantics

The one place the report offers no guidance and SQL will bite.

ConQuer-92's semantics are total: a path expression denotes a multiset, and the report's
relational algebra has no null. SQL-92 has three-valued logic, and the CCM introduces nulls in
exactly one way — `Step.join: "outer"`.

Rules:

1. An outer join is only legal onto a non-mandatory role (`model.md` §7.2, from
   `PathOuterJoinRequiresOptionalRoleError`), so nulls appear only where the schema says the
   fact may be absent.
1a. **An `exit` asserts the fact instance has that role filled.** Where the fact type has its
   own table the join already enforces this; where it is absorbed into the entity's table
   (which is what reverse engineering produces for every attribute and every functional
   foreign key) nothing does, so the emitter adds `IS NOT NULL` on the mapped columns unless
   the fact node was reached by an outer join. Without it `Employee has Employee` — a
   self-referencing `ReportsTo` — silently succeeds for an employee with no manager, because
   reading a null column is not an error in SQL. This is the report's total semantics
   restored: a path step through an optional role succeeds only where the fact exists.
2. A node downstream of an outer join may be null. Conditions over it follow SQL's three-valued
   logic, which means `NOT (x = 1)` does not select rows where `x` is null. Where the CCM says
   `not`, emit `NOT (…)` **and** decide explicitly whether nulls are wanted; the report's `¬C`
   is two-valued and means *"the condition does not hold"*, which is SQL's
   `NOT (…) OR … IS NULL`.
3. Aggregates ignore nulls in SQL; `count(*)` does not. Emit `COUNT(col)`, never `COUNT(*)`,
   unless the CCM asked to count rows.

Item 2 is a genuine semantic decision, not a detail. Record whichever way it goes here once it
is made, because the front end cannot express the difference.

---

## 7. Derivation rules

| `completeness` / `storage` | Emission |
|---|---|
| `fullyDerived` / `notStored` | `CREATE VIEW` |
| `fullyDerived` / `stored` | a materialised table plus whatever the dialect offers to refresh it |
| `partiallyDerived` / either | a view over the union of the asserted rows and the derived ones |

`partiallyDerived` means instances may be both asserted and calculated. It has no ConQuer
counterpart — it comes from ORMCore — and it is the case most likely to be got wrong, because
the asserted and derived populations must not duplicate. Emit `UNION`, never `UNION ALL`.

---

## 8. What this binding does not do

- **Optimisation.** The normalisation into a flat block is the structural optimisation; beyond
  that, emit clearly and let the database plan. Do not hand-roll join ordering.
- **Recursion.** Not in the model (`model.md` §4.1). ConQuer deferred it for SQL-92's sake;
  that constraint has expired, so `WITH RECURSIVE` is available whenever the model decides to
  admit recursion.
- **Dialect variation.** SQL-92 is the target. Dialect adaptation belongs in a layer below this
  one, driven by the `Function` table (`model.md` §3), which is model data precisely so a
  dialect can extend it.
