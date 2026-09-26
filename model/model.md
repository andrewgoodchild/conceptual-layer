# The Common Core Model (CCM)

Normative for the ConQuer-92 → SQL compiler.

The CCM is one model covering three things the compiler needs and no single existing format
carries together:

1. **the conceptual schema** — an ORM schema, in the subset ConQuer-92 §2 actually uses;
2. **the query/derivation language** — a normalised role-path form, resolving the five
   ConQuer/ORMCore gaps set out in §0;
3. **the relational mapping** — concept-to-table and role-to-column, which ORMCore does not
   carry at all.

`ccm.schema.json` is the machine-readable form of everything below. Where the two disagree,
this document wins and the schema is a bug.

---

## 0. Resolutions

The gaps and abbreviations the comparison left open, and how the CCM settles each. This table
is the reason the folder exists; the rest of the document is detail.

| # | Issue | Resolution |
|---|---|---|
| **G1** | ORMCore has no fact-instance path node; ConQuer's `Rel(p)` is a legitimate path endpoint and §6.10 types attributes by fact types | **A `FactType` is a `Concept`.** Path nodes are typed by concepts, and a fact type is one. ConQuer's entry/exit become the two step kinds `enter`/`exit`, with the fact instance as a real node between them (§4.2). ORMCore's collapsed `PostInnerJoin`+`SameFactType` is then a *serialisation* of that pair, not the model |
| **G2** | ORMCore has no operator composing two role paths | **The CCM is normalised by construction.** A `Block` is a flat set of nodes, steps, unifications and conditions. `P ∘ Q`, `P × Q` and `P R Q` are AST operators; lowering merges the node/step sets and emits a `Unification`. There is no composition operator in the CCM |
| **G3** | ORMCore has no mid-path `∪`/`∩`/`−` between differently-rooted paths | **A query body is a set-operation tree over blocks** (§4.1). `union`/`intersect`/`except` are first class, matching SQL-92 exactly. The `Fr`-ed forms `∪ᶠ`/`∩ᶠ`/`−ᶠ` — the ones the report says will be used most — stay *inside* a block as sub-block combinators (`or`/`and`/`xor`) |
| **G4** | ORMCore has no relational division; ConQuer's `⊆ ⊇ ≡` are not encodable without losing the verbalisation | **`setCompare` is a first-class condition** (§4.6). It lowers directly to SQL, not via negation. The negated-sub-block encoding survives only as a lossy `.orm` export fallback |
| **G5** | ORMCore has no mid-path `Ds`; ConQuer's `Ds` may appear anywhere | **Distinct is a property in exactly three places:** `Block.distinct`, `Calculation.aggregation.distinct`, and (vacuously) inside an existential sub-block. The report's other `Ds` occurrences are artefacts of its multiset relational-algebra translation, internal to the definitions of `∩`, `∪`, `−` and `[Q₁,…,Qₙ]`, not constructs an author writes |
| **A1** | `HdCoerce` / `TlCoerce` (§6.2) splice in reference-scheme steps implicitly | **The CCM is fully explicit.** No coercion exists in the model; the lowering pass materialises every reference-scheme walk as real `enter`/`exit` steps. Invariant §7.1 |
| **A2** | Denotations `x:(d₁,…,dₗ)`, `x:d`, `x:!a` (§6.8) are abbreviations over `Idf(x)` | **Expanded at lowering.** `x:!a` is the CCM default — every node is the abstract instance — so `x:d` is the form that gains steps, not the other way round |
| **A3** | `hd` / `tl` are privileged columns in every ConQuer expression | **Dropped.** Every output is a `Projection`. `hd`/`tl` live in the front-end AST, where the report's ℙ, 𝕋 and 𝕃 need them, and are consumed by lowering |
| **A4** | The report uses `⊗` for two different operators | **Disambiguated** (§4.6). Underlined `⊗` (§6.2) is a path operator, the complement of concatenation; plain `⊗` (§6.4) is a condition, disjointness. The CCM gives the second a `setCompare` op named `disjoint` and expresses the first as `except` over two blocks (§4.1) |
| **A5** | ORMCore carries no relational mapping, and `.orm` keeps it (if at all) in an `##other` extension part | **The CCM owns it** (§6). Required to query: a model without one is refused |
| **A6** | Ordering `Ω(P, a:o;…)` (§6.13) is outside ConQuer's path language | **Kept outside the query body**, on `Query.ordering`. It is a presentation concern in both languages |
| **A7** | ORMCore's `DynamicState` annotates path nodes for state-change rules | **Not modelled.** An import carrying any state other than `Current` is rejected with a diagnostic, never silently ignored |

---

## 1. Conventions

- Every element has an `id`, unique within the model. References are by `id`.
- `Ref` types below are `id` strings.
- All collections are ordered where order is meaningful (`Role.ordinal`, reading role
  sequences, projection lists, identifier role sequences) and unordered otherwise.
- "Concept" is the CCM's word for anything a path node can be typed by. It deliberately spans
  what ORM splits into `ObjectType` and `FactType`.

---

## 2. Schema part

### 2.1 Concept

```
Concept = ValueType | EntityType | FactType
  id      : Id
  name    : string
  aliases : string[]        // for the surface parser; ORMCore RecognizedPhrases
  kind    : "value" | "entity" | "fact"
```

**ValueType**
```
  dataType    : DataType             // name + parameters, e.g. {name:"varchar", length:64}
  restriction : ValueRestriction?    // ranges and/or enumerated values
```

**EntityType**
```
  referenceMode : string?            // ORM _ReferenceMode, e.g. "nr", "name"
  identifier    : RoleRef[]          // the preferred identifier's role sequence; ConQuer's Idf(x)
  supertypes    : ConceptRef[]
  isIndependent : boolean
  derivation    : DerivationRuleRef?
```

**FactType**
```
  roles         : Role[]             // owned, ordered; ConQuer's Roles(f)
  readings      : Reading[]
  isObjectified : boolean            // the source model objectified this fact type
  isImplied     : boolean            // ORM ImpliedFact
  derivation    : DerivationRuleRef?
```

A `FactType` **is** a `Concept` unconditionally, and may type a path node whether or not it is
objectified. `isObjectified` gates two things only: whether a `Role.player` may reference it,
and whether a path node typed by it survives `.orm` export (`binding-ormcore.md` §3).

This is the G1 resolution, and it is faithful to the report: ConQuer's type universe 𝒯𝒫
includes the relationship types ℛℒ — §6.11 says "if `t ∈ 𝒯𝒫 − ℛℒ`", which only makes sense
if ℛℒ ⊆ 𝒯𝒫.

**`terms`** is vocabulary rather than names: the table or column a concept was derived from,
the words of that name, and the expansion of any abbreviation in it — `EmployeeName` carries
`emp`, `emp_name`, `employee`, `name`. It exists because rule 10 computed all three and kept
only the result, and because matching a *question* against a model needs every word the thing
is known by. Nothing resolves against it: `aliases` are names a query may use and can collide,
`terms` only ever widen what a matcher accepts (`conquer/link.py`).

### 2.2 Role

```
Role
  id          : Id
  name        : string?              // ConQuer's RNm(r)
  player      : ConceptRef           // ConQuer's Player(r)
  isMandatory : boolean
  ordinal     : integer              // position within the owning fact type
```

`Rel(r)` — ConQuer's other role function — is the fact type that owns `r`, implicit in the
nesting. The loader builds a role-id → fact-type index.

### 2.3 Derived schema functions

Not stored; computed from the above. Named here because the report's semantics call them.

| ConQuer (§2) | Computed as |
|---|---|
| `Roles(f)` | `f.roles` |
| `Rel(r)` | the fact type owning `r` |
| `Player(r)` | `r.player` |
| `Idf(x)` | `x.identifier` for an entity type; the identifying role sequence for a fact type; identity for a value type |
| `x ∼ y` (type relatedness) | the equivalence closure of the subtype relation over `supertypes` |
| `RootsOf(x)` | the maximal elements above `x` under `supertypes` (those with none of their own) |

### 2.4 Constraint

```
Constraint
  id   : Id
  kind : "uniqueness" | "mandatory" | "frequency" | "ring"
       | "subset" | "equality" | "exclusion" | "valueComparison"
  ...kind-specific fields, each carrying one or more RoleRef[] sequences
```

`uniqueness` carries `isPreferredIdentifier` and, when external, a role sequence spanning fact
types. The compiler *consumes* `uniqueness` and `mandatory` (they decide identification, outer-join
validity and duplicate elimination); it carries the rest for round-tripping and validation only.

**Two things a constraint cannot say here, both deliberate to note rather than deliberate to
have.**

*No join path.* An external uniqueness constraint over roles in different fact types is
identified by a role sequence alone. Where those fact types can be joined more than one way,
the sequence does not say which join does the identifying — the ambiguity Halpin (1989) raised
against the ORM *diagram*, and the one thing Meersman's RIDL is said to state that the diagram
cannot (`docs/08-history.md` §1). `binding-ormcore.md` maps ORMCore's
`ConstraintRoleSequenceJoinPath` to "a `Block` attached to the constraint", and no such field
exists: an import carrying one loses it silently. It does not bite today because a
reverse-engineered external uniqueness comes from a composite primary key, where the path is
forced, but a model refined in NORMA could carry one.

The choice of *which* constraint kinds to consume has prior art with a corpus behind it:
**ORM⁻** (Smaragdakis, Csallner & Subramanian, from the models built at LogicBlox) is a
restricted subset of ORM that covers the constraints actually used in practice and stays
tractable to analyse — see `docs/08-history.md` §1.

*What a constraint says in the language.* A `DerivationRule` carries `source`, the ConQuer-92
it was written in (§5). A constraint carries **`violation`**: ConQuer whose result must be
empty, so the rows it returns are the counter-examples. One text answers both questions --
whether the constraint holds, and which rows break it -- which is how Rel's integrity
constraints are shaped (`ic X()` asks, `ic X(x)` hands back the offending x). Structural
constraints do not need one: uniqueness and mandatory are already enforced by the columns they
map to. It is for the rules that are not structural, and for the ones a reverse-engineered
draft only *proposes*. `conquer.py --constraints` runs them.

### 2.5 Reading

```
Reading
  id           : Id
  text         : string              // "{0} is subtype of {1}"
  roleSequence : RoleRef[]           // slot n binds roleSequence[n]
```

This is ConQuer's mix-fix predicate `MFix(f, [α₁…α_k], [p₁…p_l])` with `k + 1 = l`, in ORM's
positional-slot spelling. `PNm(f)`, `Pre` and `Post` (§7.1) are all derivable from `text` by
splitting on the slots; they are not stored separately.

---

## 3. Function part

```
Function
  id             : Id
  name           : string
  operatorSymbol : string?           // infix when binary, prefix when unary
  sqlTemplate    : string?           // "{0}" "{1}" placeholders; when present, how the
                                     // target dialect spells it. Wins over the symbol.
  sqlBagTemplate : string?           // an aggregate the dialect spells only over a derived
                                     // table: "{bag}" is the bag's SQL, its column is "v"
  isBoolean      : boolean           // usable as a condition
  isAggregate    : boolean           // some parameter has bagInput
  parameters     : [{ name: string, bagInput: boolean,
                      default?: number | string }]  // a trailing parameter a call may leave
                                                   // out: round(x) is round(x, 0)
```

Open, exactly as in ORMCore — the function table is model data, not grammar. The standard
library the compiler must define: arithmetic `+ - * / unary-` ; comparison as conditions rather
than functions; aggregates `count`, `sum`, `min`, `max`, `avg`; and whatever the target
dialect adds.

`sqlTemplate` is where a function's meaning and its spelling part company. `year(x)` means the
same thing everywhere; SQLite spells it `strftime('%Y', x)`, and `YEAR(x)` is a runtime error
there. Before the template existed the emitter spelled every non-operator function as its
name in capitals, which happened to work for `ABS` and `ROUND` and silently did not for dates.
It is also how `/` means real division (`conquer/conquer-2026.md` §1) without the emitter knowing
anything about division.

ConQuer's group functions map here without remainder:
`GCount`→`count`, `GSum`→`sum`, `GMin`→`min`, `GMax`→`max`, `GAvg`→`avg`, and the `GDs…`
variants are the same functions with `aggregation.distinct = true`.

---

## 4. Query part

### 4.1 Query and QueryExpr

```
Query
  id         : Id
  name       : string
  parameters : Parameter[]           // { id, name, concept: ConceptRef }
  body       : QueryExpr
  ordering   : OrderSpec[]           // { projection: ProjectionRef | value: Value,
                                     //   direction: "asc"|"desc" }
  limit      : { count: integer, offset: integer, per: Value? }?   // CCM extension; see below.
                                     // `per` keeps the first `count` within each value of
                                     // `per` rather than of the whole result

QueryExpr = Block | SetExpr

SetExpr
  op       : "union" | "intersect" | "except"
  all      : boolean                 // false ⇒ duplicate elimination
  operands : QueryExpr[]             // ≥2; left-associative for "except"
```

`SetExpr` is the G3 resolution. Its operands must agree on projection arity and type — the
CCM requires this explicitly rather than inferring a coercion, which is where the report's
`DefMap` machinery went.

`Query.parameters` is ORMCore's `QueryParameter`: a named relation with a signature, stepped
into by an `Invocation`. ConQuer's macros (§6.9) are not that. The report calls them "basically
an abbreviation" and defines them by substitution, so the CCM keeps them as `macros[]` --
`{ id, name, parameters, kind: "scalar"|"condition"|"path", source }` -- and the parser expands
an invocation `α(E1, …, En)` into the body with each parameter replaced, before parsing goes
on. They never reach the lowered form; `--normalise` shows the expansion. §6.9's ban on
recursive macros stands: a recursive definition is a derivation rule (§5).

An `OrderSpec` names either a projection or a `Value`. [P59] binds its v_i to *variables in
the descriptor*, not to result columns, and [P57] sorts on the path's head — neither has to be
listed, and SQL is equally happy to order by something it does not select. The `Value` form
also covers ordering by a computed key, `ORDERED WITH abs(lo) DESCENDING`, which the report
does not have but which falls straight out of §6.3 scalar expressions.

`Query.limit` is a **CCM extension with no ConQuer-92 counterpart**, and it is worth being
explicit about why it is here and where it sits. §6.13 defines exactly one ordering operator,
Ω(P, a₁:o₁; …), whose arguments are attributes and directions — there is no cardinality
argument anywhere in it, and the section opens by saying ordering "is not a part of the
path-expressions themselves" because it is a presentation concern. The grammar's `HEAD` and
`TAIL` look like a top-N hook but are not: they are sort *keys* naming the two distinguished
ends of the path result. So a row limit had to be invented rather than implemented.

It is sited beside `ordering` on the `Query`, outside `QueryExpr`, for the same reason Ω sits
outside the path-expression language: a bag has no first element until something orders it, so
a limit cannot compose as a path operator. It applies to the outermost block only, and it is
not closed — `SetExpr` operands may not carry one.

The limit does not promise which rows it keeps when the ordering is not total, because SQL
does not. `conquer/verbalise.py` reports that as a finding rather than hiding it: a limit with
no ordering is a RISK, so `--check --strict` refuses to run it, and a limit over an ordering
that may have ties is a CAUTION.

Recursion lives in derivation rules (§5), where ConQuer §6.9 said it would once SQL had a
fixpoint: a rule whose body mentions its own target is a least fixpoint, emitted as
`WITH RECURSIVE` over the rule's `SetExpr`. A query itself is not recursive; it walks the
derived fact type.

### 4.2 Block

```
Block
  id            : Id
  nodes         : Node[]
  steps         : Step[]
  invocations   : Invocation[]
  unifications  : Unification[]
  calculations  : Calculation[]
  conditions    : Condition[]
  subBlocks     : Block[]
  combinator    : "and" | "or" | "xor"     // how subBlocks combine; default "and"
  negated       : boolean                  // meaningful on a sub-block: NOT EXISTS
  projections   : Projection[]             // required on a body block, empty on a sub-block
  distinct      : boolean
```

A block is a conjunctive query. Its sub-blocks are existential branches — ConQuer's `Fr` and
its sub-expressions `[Q₁,…,Qₙ]`, and ORMCore's `SubPaths`. A sub-block correlates with its
parent through `unifications` that reference nodes in an enclosing block.

### 4.3 Node

```
Node
  id          : Id
  concept     : ConceptRef           // may be a fact type — see G1
  name        : string?              // the ConQuer attribute name, when the surface named it
  restriction : ValueRestriction?
```

`Node.name` is for diagnostics and verbalisation. It is **not** the correlation mechanism —
`Unification` is. Two nodes sharing a name are not thereby the same instance.

### 4.4 Step

```
Step
  id   : Id
  kind : "enter" | "exit"
  role : RoleRef
  from : NodeRef
  to   : NodeRef
  join : "inner" | "outer"           // "enter" only; "exit" must be "inner"
```

- **`enter`** — `from` is typed `Player(role)`, `to` is typed `Rel(role)`. This is ConQuer's
  role-entry `p`. The join happens here.
- **`exit`** — `from` is typed `Rel(role)`, `to` is typed `Player(role)`. This is ConQuer's
  role-exit `p←`. It never joins; it reads another role of a fact instance already in hand.

Traversing a fact type from role `p` to role `q` is therefore the pair `enter(p)`, `exit(q)`,
with a fact-typed node between them. That node is ordinary: it may be unified, restricted,
projected, or aggregated over.

`join: "outer"` is ConQuer's `⟕`, which the report only ever produces implicitly inside the
definitions of `∪`, `Where` and confluence. The CCM makes it explicit, following ORMCore.

### 4.5 Unification, Invocation, Calculation

```
Unification
  id    : Id
  nodes : NodeRef[]                  // ≥2; asserted to be the same instance
```

The G2/variable resolution. A ConQuer attribute is an equivalence class of occurrences; a
`Unification` is that class. Nodes may span nesting levels, which is how a sub-block correlates.

```
Invocation
  id        : Id
  query     : QueryRef
  arguments : [{ parameter: ParameterRef, value: Value }]
  results   : [{ projection: ProjectionRef, node: NodeRef }]
```

Stepping into a named query. Every parameter must be bound.

```
Calculation
  id          : Id
  function    : FunctionRef
  arguments   : Value[]
  aggregation : { context: NodeRef[] | "universal", distinct: boolean } ?
```

`aggregation` is present exactly when the function is an aggregate. `context` is the set of
nodes held fixed while the bag is collected — ConQuer's grouping set `X`, ORMCore's
`AggregationContext`. `"universal"` is the grand total (ConQuer's `X = ∅`).

### 4.6 Condition

```
Condition =
  | { kind: "compare",     op: "<"|"<="|"="|"<>"|">="|">", left: Value, right: Value }
  | { kind: "setCompare",  op: SetOp, left: Bag, right: Bag }
  | { kind: "exists",      block: Block }
  | { kind: "not",         operand: Condition }
  | { kind: "logical",     op: "and"|"or"|"xor"|"implies", operands: Condition[] }
  | { kind: "restriction", node: NodeRef, restriction: ValueRestriction }
  | { kind: "call",        function: FunctionRef, arguments: Value[] }   // isBoolean

SetOp = "subset" | "properSubset" | "superset" | "properSuperset" | "match" | "disjoint"

Bag   = { block: Block, node: NodeRef }    // the multiset of values of `node` over `block`

Value = { kind: "node",        node: NodeRef }
      | { kind: "constant",    dataType: DataType, lexical: string }
      | { kind: "calculation", calculation: CalculationRef }
      | { kind: "parameter",   parameter: ParameterRef }
      | { kind: "conditional", condition: Condition, then: Value, else: Value }
                                            // CCM extension, conquer/conquer-2026.md §4: a scalar
                                            // CASE WHEN. Not §7.5's bag-valued IF.
```

`setCompare` is the G4 resolution and covers, in one construct:

| ConQuer | `SetOp` |
|---|---|
| `P ⊆ Q` underlined (§6.2), *"WHICH ARE ALL IN"* | `subset` |
| `P ⊇ Q` underlined (§6.2), *"THAT INCLUDES ALL"* | `superset` |
| `P ≡ Q` underlined (§6.2), *"MATCHING ALL"* | `match` |
| `P ⊗ Q` **plain** (§6.4), exclusion | `disjoint` |
| `P S Q` for `S ∈ {⊂,⊆,=,⊇,⊃}` (§6.4) | the corresponding op |

**A4, stated once.** The report uses the glyph `⊗` for two different operators. Underlined `⊗`
(§6.2) is a *path* operator: `ℙ⟦P ⊗ Q⟧ ≜ (δ_tl P ⋈ δ_hd Q) − ℙ⟦P ∘ Q⟧`, the head/tail
combinations *not* connected by concatenation, verbalised *"EXCLUDING"*. Plain `⊗` (§6.4) is a
*condition*: `P₁ ⊗ P₂ ≜ ¬Some(Fr(P) ∩ Fr(Q))`, disjointness. Only the second is a
`setCompare`. The first is a `SetExpr` with `op: "except"` over a cross block and a
concatenation block, and it keeps its own name in the AST so §8 can still verbalise it as
*"EXCLUDING"*.

(The §6.4 definition is printed with a `P₁`/`P₂` versus `P`/`Q` variable mismatch in the report
itself.)

### 4.7 Projection

```
Projection
  id     : Id
  name   : string                    // output column name
  source : Value
  target : RoleRef?                  // set when the block populates a derived fact type
```

Every output is a projection — the A3 resolution. Confluence (§6.5) needs no construct of its
own: the base path is the block, each gathered `Qᵢ` is a sub-block joined with
`join: "outer"`, and each `aᵢ` is a projection of that sub-block's leaf node. This is strictly
more general than the report's version, in which each `Qᵢ` contributes exactly one column.

---

## 5. Derivation rules

```
DerivationRule
  id           : Id
  target       : { kind: "factType" | "subtype" | "valueType", ref: ConceptRef }
  body         : QueryExpr
  completeness : "fullyDerived" | "partiallyDerived"
  storage      : "notStored" | "stored"
```

Projections live on the body's blocks and carry `target` role references. For
`kind: "factType"` every role of the target fact type must be projected exactly once, in every
alternative of a `SetExpr`.

`completeness` and `storage` come from ORMCore and have no ConQuer counterpart; they are what a
SQL back end needs to choose between a view, a materialised view and on-demand evaluation
(`binding-sql92.md` §7).

`kind: "valueType"` is a CCM extension. ConQuer's §6.11 second class of rule covers any
`t ∈ 𝒯𝒫 − ℛℒ`, which includes value types; ORMCore has only `SubtypeDerivationPath`. It does
not export.

**Authoring form.** A rule carries `source`, the ConQuer-92 it was written in, and the compiler
lowers that into `body` (`conquer/lower.py lower_rules`, idempotent, called by `transpile`).
A fact-type rule is `LIST a1, …, an FROM P`, one listed thing per role in role order — that is
`f(p1:a1, …, pn:an) ::= P` with the binding positional — and the lowered projections carry
`target`. A subtype rule is a path P; its population is the heads of P, so the body keeps only
the head projection. Both are `distinct`: a fact population is a set.

**Recursion.** A rule may mention its own target, and the population is the least fixpoint.
The emitter renders every derived concept a statement touches as a common table expression,
`WITH RECURSIVE` when one is self-referential; the rule's `SetExpr` supplies the base case
and the step, as SQL's recursive CTE requires. A rule that references itself other than
through a `UNITED WITH` fails at the database, which is the same rule SQL applies.

**Mapping.** A derived concept has no table. The emitter gives it a virtual one, `v.<id>`,
whose columns are its roles (or `id` for a subtype); `conceptMap` and `roleMap` entries for it
are synthesised, never stored.

---

## 6. Relational mapping

Optional in the model, required to query it: the compiler refuses a model without one rather
than guess a default Rmap. Present, SQL generation is a lookup instead of a re-derivation,
which is both faster and — more importantly — correct for schemas that were reverse
engineered from an existing database and must map back onto *those* tables.

```
RelationalMapping
  tables      : [{ id, name, schema? }]
  columns     : [{ id, table: TableRef, name, dataType, nullable: boolean }]
  conceptMap  : [{ concept: ConceptRef, table: TableRef, identifyingColumns: ColumnRef[] }]
  roleMap     : [{ role: RoleRef, table: TableRef, columns: ColumnRef[],
                   references?: ColumnRef[], enforced?: boolean }]
```

`roleMap` may give several columns for one role: a role played by a compositely identified
entity type maps to the whole foreign key.

A column may carry `isRowId: true`: it is the table's own row identity (SQLite's `rowid`),
registered so that a table with no declared key can still identify its instances (reverse
engineering rule 1c). It exists in no `CREATE TABLE`, and it binds the mapping to the dialect
that has it.

`references` is present only when a role's columns are a foreign key pointing at columns that
are *not* the target entity type's identifier -- `legalities.uuid` referencing `cards.uuid`
while `cards` is keyed by `id`. The emitter joins on those columns instead of the identifier.
Without it the join silently matches the wrong rows, or none: 32 of the 105 declared foreign
keys in the BIRD development set point somewhere other than a primary key.

`enforced` says that every value the role's columns hold is present in the columns they
reference -- in `references` when it is given, otherwise in the target's identifier. It is a
claim about the data, not about the catalogue, and the distinction is the point: a declared
foreign key does not say it, because SQLite does not enforce one and 28% of the declared
single-column keys in a 90-database Spider sample are contradicted by their own rows. Where
it is present and true, a path step across the reference need not join at all if the far
table holds nothing the near side does not already have -- the join that would check the
referent exists filters nothing out, and a fact type whose every role maps within the
referenced columns has nothing to fetch. Absent, the compiler assumes nothing and joins.
Reverse engineering writes it on request (`--infer-enforced`), never by default.

This part is the A5 resolution and has no ORMCore counterpart at all. `ORM2Core.xsd` stops at
the conceptual schema; the `ORM2` document element is an open container of `##other` namespace
parts and every `ORMModel` element carries an open `Extensions` slot, so a `.orm` file *may*
carry a relational mapping alongside the model, but it is not ORMCore and its shape is not
specified by the schema this project vendored. The CCM therefore owns the mapping outright.

---

## 7. Invariants and validation

### 7.1 Structural invariants

1. **Fully explicit.** No coercion, no denotation abbreviation, no implicit reference-scheme
   walk. Every step a query takes through a reference scheme is a real `enter`/`exit` pair.
   Lowering establishes this; nothing downstream may assume otherwise. (A1, A2)
2. **Normalised.** No composition operator exists. A block's steps and unifications are flat.
   (G2)
3. **Rooted.** Every node in a block is reachable from some node by steps, or unified with one
   that is, or bound by an invocation result, or a parameter. A block with an unreachable node
   is invalid.
4. **Distinct only where §0/G5 permits it.**
5. **Ordering is not part of the body.** (A6)

### 7.2 Validation rules

ORMCore names each failure mode individually; ConQuer states its type requirement once
(`⟨a,x⟩,⟨a,y⟩ ∈ T ⇒ x ∼ y`) and leaves it there. The CCM adopts ORM's taxonomy, since it is
the same requirement operationalised.

| CCM check | From |
|---|---|
| `enter` step's `from` node is typed `Player(role)` or a subtype; `to` is typed `Rel(role)` | `JoinedPathRoleRequiresCompatibleRolePlayerError` |
| `exit` step's `from` node is typed `Rel(role)`; `to` is typed `Player(role)` or a subtype | as above |
| every `Unification`'s nodes are pairwise type-related under `∼` | `ObjectUnifierRequiresCompatibleObjectTypesError` — **this is ConQuer's `x ∼ y`** |
| an `exit` follows an `enter` on the same fact node | `PathSameFactTypeRoleFollowsJoinError` |
| a role is not re-entered within one fact instance without a fresh `enter` | as above |
| `join: "outer"` targets a non-mandatory role | `PathOuterJoinRequiresOptionalRoleError` |
| every `Calculation` names a `Function` | `CalculatedPathValueRequiresFunctionError` |
| every aggregate `Calculation` has an `aggregation` block | `CalculatedPathValueRequiresAggregationContextError` |
| every `Calculation` is consumed by a condition, another calculation, or a projection | `CalculatedPathValueMustBeConsumedError` |
| argument count and `bagInput` shape match the function's parameters | `CalculatedPathValueParameterBindingError` |
| every `Invocation` binds every parameter of its query | `QueryParameterBindingError` |
| a derivation rule projects every role of its target fact type, once, in every alternative | `FactTypeDerivationRequiresProjectionError`, `PartialFactTypeDerivationProjectionError` |
| a projection's source type is compatible with its `target` role player | `DerivedFactTypeRoleProjectionCompatibilityError` |
| `SetExpr` operands agree on projection arity and type | CCM-specific (see §4.1) |
| a `Role.player` referencing a fact type requires `isObjectified` | CCM-specific (see §2.1) |
| every block is rooted (§7.1.3) | `PathRequiresRootObjectTypeError`, generalised |

### 7.3 What is deliberately not checked

`𝕃⟦P⟧` — the report's head/tail type-combination function, used to prune paths that are empty
in any population (`𝕃⟦P⟧(T) = ∅`) and to disambiguate verbalisations. The per-step and
per-unification compatibility checks above are a local approximation of it. Whether `𝕃` is
computed on the AST only, or recomputed over the CCM, is an open question; neither is built.

---

## 8. What is out of scope

- **Dynamic rules.** ORMCore's `DynamicRuleNodeState` annotates path nodes for state-change
  rules. Not modelled; an import carrying any state but `Current` is rejected. (A7)
- **Diagram geometry.** ORM's `ORMDiagram` namespace. Preserved opaquely on round trip if at
  all; never interpreted.
- **The surface parser.** Report §7's schema-driven ambiguous grammar produces the AST that
  lowers to the CCM. It lives in `conquer/parser.py`; the CCM is its target, not its solution.
- **Verbalisation.** Report §8's rules run over the AST, where the surface operators still
  exist. By the time a query is a CCM block, `subset` has lost the word *"WHICH ARE ALL IN"*.
