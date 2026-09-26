# Binding: CCM ↔ NORMA `.orm` (`ORM2Core.xsd`)

How a Common Core Model is read from and written to a NORMA `.orm` file. Schema vendored at
`model/reference/orm-metamodel/ORM2Core.xsd`; the gaps this binding has to bridge are
`model.md` §0.

**Read this first.** Neither vendored `.orm` file contains a single `LeadRolePath`,
`PathedRole` or `CalculatedValue` element — their three `DerivationRule`s are informal
`DerivationExpression` bodies reading *"See Subtype Textual Constraints"* — and NORMA has no
query editor or execution engine. So the *schema* half of this binding is exercised by
thousands of real files, and the *query* half is exercised by none. Treat the XSD as normative
and the absence of a corpus as a risk: validate every export against the schema mechanically,
and open it in NORMA before trusting it.

---

## 1. Schema part — lossless both ways

| CCM | ORMCore |
|---|---|
| `ValueType` | `ORMModel/Objects/ValueType` + `ConceptualDataType`, `ValueRestriction` |
| `EntityType` | `ORMModel/Objects/EntityType`, `@_ReferenceMode` |
| `EntityType.identifier` | `PreferredIdentifier` → a `UniquenessConstraint`'s role sequence |
| `EntityType.supertypes` | `SubtypeFact` elements (one per supertype) |
| `FactType` (`isObjectified: false`) | `ORMModel/Facts/Fact` |
| `FactType` (`isObjectified: true`) | `ORMModel/Objects/ObjectifiedType` + its `Fact` |
| `Role` | `FactRoles/Role`, `@Name`, `RolePlayer` |
| `Role.isMandatory` | a simple `MandatoryConstraint` on that role |
| `Reading` | `ReadingOrders/ReadingOrder/Readings/Reading/Data` + `RoleSequence` |
| `Concept.aliases` | `RecognizedPhrases` |
| `Constraint` (all kinds) | the matching `ORMModel/Constraints/*` element |
| `Function` | `ORMModel/Functions/Function` + `Parameters/Parameter` |

Two notes:

- **`isObjectified` is not free-floating.** On import it is set true iff an `ObjectifiedType`
  wraps the fact type. On export, setting it true means emitting an `ObjectifiedType`, which
  changes the conceptual model — so the exporter must never set it on its own to make a path
  legal. See §3.
- **Diagram geometry** (`ORMDiagram` namespace) is not modelled. Preserve the parts opaquely if
  round-tripping matters; never interpret them.

---

## 2. Query part — the shape change

CCM blocks are flat; ORMCore role paths are rooted trees. Import and export are therefore not
symmetric transcriptions but a normalise/denormalise pair.

### 2.1 Import (`.orm` → CCM)

| ORMCore | CCM |
|---|---|
| `LeadRolePath` | one `Block` |
| `RootObjectType ref=x` | a `Node` typed `x` |
| `PathedRole @Purpose="PostInnerJoin"` (also the deprecated `"StartRole"`) | a `Node` typed `Rel(role)` + a `Step{kind:"enter", join:"inner"}` |
| `PathedRole @Purpose="PostOuterJoin"` | the same with `join:"outer"` |
| `PathedRole @Purpose="SameFactType"` | a `Node` typed `Player(role)` + a `Step{kind:"exit"}` from the fact node the preceding entry created |
| `@IsNegated` on a root or pathed role | `Block.negated` on the enclosing sub-block, or a `not` condition |
| `SubPaths/SubPath` | `Block.subBlocks` |
| `@SplitCombinationOperator` | `Block.combinator` |
| `@SplitIsNegated` | `Block.negated` |
| `ObjectUnifier` | `Unification` |
| `CorrelatedWith` (deprecated) | `Unification` of the two nodes |
| `ValueRestriction` on a root or pathed role | `Node.restriction` |
| `CalculatedValue` | `Calculation` |
| `AggregationContext` / `@UniversalAggregationContext` | `Calculation.aggregation.context` / `"universal"` |
| `Input/@DistinctValues` | `Calculation.aggregation.distinct` |
| `Conditions/CalculatedCondition` | a `call` condition per entry, conjoined |
| `Subquery` + `SubqueryParameterInputsFor` | `Query` + `Invocation` |
| `DerivationProjection` → `RoleProjection` → `DerivationSource` | `Projection` with `target` |
| several `RolePath` under one `PathComponents` | a `SetExpr{op:"union"}` over the blocks |
| `@SetProjection` | `Block.distinct` |
| `@DerivationCompleteness`, `@DerivationStorage` | `DerivationRule.completeness`, `.storage` |
| `FactTypeDerivationPath` / `SubtypeDerivationPath` | `DerivationRule.target.kind` = `factType` / `subtype` |
| `ConstraintRoleSequenceJoinPath` + `JoinPathProjection` | a `Block` attached to the constraint |

The one real inference: **`SameFactType` reconstructs a fact node that the `.orm` never named.**
ORMCore elides it — a `PathedRole`'s value is the role player, and the fact instance between an
entry and an exit has no element. The importer materialises it. This is sound because
`PathSameFactTypeRoleFollowsJoinError` guarantees a `SameFactType` role always follows an entry
into that same fact type, so the node the importer creates is always determined.

**Reject, do not ignore:** any `RootObjectType` or `PathedRole` carrying `@DynamicState` other
than `Current`. Those are state-change rules (`DynamicRule`), outside ConQuer's scope, and
silently dropping the annotation would change the rule's meaning. (`model.md` A7.)

### 2.2 Export (CCM → `.orm`)

The inverse, with four rules the importer does not need:

1. **Collapse `enter`+`exit` pairs.** An `enter(p)` immediately followed by an `exit(q)` on the
   same fact node becomes `PathedRole(p) @Purpose="PostInnerJoin"` then
   `PathedRole(q) @Purpose="SameFactType"`, and the fact node disappears.
2. **Linearise.** A block's steps form a graph; ORMCore wants a tree. Choose a root (a node
   with no incoming step), walk the spanning tree, and emit every step not on it as a `SubPath`
   plus an `ObjectUnifier` back to the node it rejoins.
3. **Split unifications.** A CCM `Unification` over *n* nodes is one `ObjectUnifier` with *n*
   children — direct. But a unification whose nodes lie in different `SetExpr` operands has no
   ORM form; see §3.
4. **Emit an `ObjectifiedType`?** No. See §3, G1.

---

## 3. What does not survive export

Five things, each with a specific diagnostic rather than a silent drop.

**G1 — a referenced fact node on an un-objectified fact type.** A fact node that is only passed
*through* (an `enter` followed by an `exit`, nothing else touching it) collapses away by rule 1
and exports cleanly. A fact node that is *referenced* — unified, restricted, projected, or used
as an aggregation context or a calculation argument — has no ORMCore element unless the fact
type is objectified.

Diagnostic, do not auto-fix. Objectifying a fact type is a change to the conceptual schema,
which is the human's artefact; the exporter must say *"node `n` is typed by the un-objectified
fact type `f` and is referenced by ⟨…⟩; objectify `f` in NORMA, or restructure the query"*.

**G3 — `intersect` and `except`.** A `SetExpr{op:"union"}` exports as several `RolePath`
elements under one `PathComponents`, each with its own `DerivationProjection`. `intersect` and
`except` have no ORM form at any level. Where the operands share a root they can often be
rewritten into one block with `combinator` and `negated` sub-blocks first — attempt that
rewrite, and diagnose only if it fails.

**G4 — `setCompare`.** ORMCore has no relational division. The lossy fallback is the ¬∃¬
encoding: `subset(L, R)` becomes a negated sub-block asserting *L*'s node with a nested negated
sub-block asserting *R*'s. It is faithful in extension and loses the surface reading, so a
round trip returns a query that no longer verbalises as *"WHICH ARE ALL IN"*.

> **Unverified.** This encoding is inferred from `@IsNegated` semantics, not read off the
> schema, and it is the only correspondence in this document that is. Check it against NORMA's
> verbalizer before relying on it. Until then, treat `setCompare` as non-exporting and
> diagnose.

**A5 — the relational mapping.** No ORMCore counterpart. The `ORM2` document element is
`xs:any namespace="##other"` and every model element carries an open `Extensions` slot, so a
mapping *could* ride along as a private namespace part — but that is this project inventing a
format, not ORMCore. Keep the mapping in the CCM JSON. Do not invent an `.orm` extension for it
without deciding that deliberately.

**§5 `valueType` derivation rules.** ConQuer's `t ::= P` covers any `t ∈ 𝒯𝒫 − ℛℒ`; ORMCore has
only `SubtypeDerivationPath`. A derived value type does not export.

---

## 4. Validation

Two passes, in this order:

1. **XSD validation** of the emitted document against `ORM2Core.xsd` and `ORM2Root.xsd`.
   Mechanical, cheap, and non-negotiable given that no corpus exists to compare against.
2. **The model.md §7.2 checks**, which are ORMCore's own error taxonomy restated. Run them on
   the CCM before export, so failures are reported against the CCM the author can see rather
   than against generated XML.

An export that passes both has still never been opened by NORMA. Do that too, once, before the
format is trusted.
