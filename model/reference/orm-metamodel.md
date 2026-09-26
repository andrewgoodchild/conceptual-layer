# The ORM metamodel (guide to `orm-metamodel/`)

Retrieved 6 September 2026 from the NORMA repository, <https://github.com/ormsolutions/NORMA>
(branch `main`). These are the files a ConQuer-92 compiler needs in order to read and write
conceptual schemas in the format the rest of the ORM world already uses.

| File | Repo path | Size | What it is |
|---|---|---|---|
| `ORM2Core.xsd` | `ORMModel/ObjectModel/ORM2Core.xsd` | 233 KB | **The metamodel.** XML Schema for the `.orm` file format. 316 named complex types. |
| `ORM2Root.xsd` | `ORMModel/Load/ORM2Root.xsd` | 2.4 KB | Document wrapper: an `ORM2` element holding one `ORMModel` plus any number of diagram and extension parts. |
| `ORMCoreMetaModel.orm` | `Documentation/ORMCoreMetaModel.orm` | 577 KB | ORM modelled in ORM. 52 entity types, 21 value types, 86 fact types, 222 readings. The conceptual statement of the same thing. |
| `OrmMetaModel.orm` | `Documentation/OrmMetaModel.orm` | 983 KB | The larger tool-implementation model: 108 entity types, 145 fact types, including the validation-error classes. |

**Licence.** All four carry the zlib/libpng notice, copyright Neumont University and ORM
Solutions LLC. Use for any purpose including commercial, modification and redistribution
permitted; you must not misrepresent the origin, must mark altered versions, and must not
remove the notice. This is compatible with anything we are likely to do here.

**Namespaces.** `http://schemas.neumont.edu/ORM/2006-04/ORMCore` for the model,
`.../ORMRoot` for the document wrapper, `.../ORMDiagram` for shape geometry. Diagram
information is a separate namespace, so a generator can emit pure semantics and leave layout
to the tool.

## Shape of `ORMModel`

```
ORMModel
├── Definitions, Notes          informal text
├── Objects        ─ EntityType | ObjectifiedType | ValueType
├── Facts          ─ Fact | SubtypeFact | ImpliedFact
├── Constraints    ─ Uniqueness | Mandatory | Frequency | Ring
│                    | Subset | Equality | Exclusion | ValueComparison
├── GeneralRules, Functions, DataTypes
├── CustomReferenceModes, ReferenceModeKinds, RecognizedPhrases
└── ModelNotes, ModelErrors, Extensions
```

`EntityType` carries a `_ReferenceMode` attribute and a `PreferredIdentifier`. `ValueType`
carries a `ConceptualDataType`, an optional `ValueRestriction` and a default value.
`FactType` carries `_Name`, `IsExternal`, `UnaryPattern`, its `FactRoles`, its
`ReadingOrders`, its `InternalConstraints` and an optional `DerivationRule`.

## Why this matters for ConQuer

The four ORM functions the ConQuer-92 semantics actually depend on (§2 of the report) map
straight onto this schema:

| ConQuer-92 (Proper §2) | ORMCore |
|---|---|
| `Roles(f)` | `FactType/FactRoles` |
| `Rel(r)` | the `FactType` containing the `Role` |
| `Player(r)` | `Role/@RolePlayer` reference to an `ObjectType` |
| `Idf(x)` | `EntityType/PreferredIdentifier` → a `UniquenessConstraint` |
| `~` (type relatedness) | `SubtypeFact` closure |
| `RootsOf(x)` | `SubtypeFact` closure to supertypes with no supertype |
| `TNm`, `PNm`, `RNm` (§7.1) | `ObjectType/@Name`, `ReadingOrder/Reading` text |
| `MFix` (mix-fix predicates, §7.1) | `ReadingOrder` with role sequence, `{0} … {1}` slots |

Readings in `ORMCoreMetaModel.orm` look like `{0} is a subtype of {1}`, `{0} objectifies {1}`,
`{0} has {1}`. That positional-slot form is exactly Proper's mix-fix verbalisation
`MFix(f, [α₁ … α_{k}], [p₁ … p_l])` with `k + 1 = l`, so §8.4's verbalisation rules [V14]–[V16]
can consume ORM readings unchanged.

## The part worth reading closely: role paths

ORMCore contains a full role-path algebra used for derivation rules and for join constraints:
`LeadRolePath`, `RolePath`, `RoleSubPath`, `PathedRole`, `RolePathRoot`, `PathConstant`,
`CalculatedPathValue`, `JoinPathProjection`, `RoleProjection`, `QueryDerivationPath`,
`FactTypeDerivationPath`, `SubtypeDerivationPath`, plus errors such as
`PathOuterJoinRequiresOptionalRoleError` and `PathSameFactTypeRoleFollowsJoinError`.

This is the closest thing in the modern ORM world to ConQuer-92 path expressions, and it is the
`QueryBase`/`Subquery` machinery noted in `docs/08-history.md` as present in NORMA but never
given an editor or an execution engine. Two consequences:

- A ConQuer-92 path expression can very likely be *serialised* as an ORM role path, which would
  let queries round-trip through `.orm` files alongside the schema.
- Conversely, NORMA's derivation rules could be *compiled* by the same back end, which is what
  §6.11 of the report anticipates when it defines derivation rules over path expressions.

Both hold, with five gaps; `model/model.md` §0 records them and how the Common Core Model
resolves each. Neither vendored `.orm` file contains a single role-path instance, so the XSD is
normative but there is no corpus.

## Related specifications

- **Franconi & Halpin, *ORM Abstract Syntax and Semantics: normative specifications*.**
  ORM.net Proposed Recommendation, Public BETA 3, 17 March 2020. 9 pages.
  <https://www.orm.net/pdf/ORMsyntax-semantics.pdf>, sources at
  <https://gitlab.com/orm-syntax-and-semantics/orm-syntax-and-semantics-docs>.
  Defines a signature ⟨𝓣, 𝒱, 𝓟, 𝓡, 𝓓, b, 𝓕, a⟩ and gives the semantics by translation to
  first-order logic. Use it for meaning; it says explicitly that it "does not define an
  interchange format for ORM", which is what `ORM2Core.xsd` is for.
- **Halpin, T. (2002). "Metaschemas for ER, ORM and UML Data Models: A Comparison."**
  *Journal of Database Management* 13(2), 20–30. The metamodel in paper form, with ER and UML
  alongside.
