# `model/` — the Common Core Model

This folder holds the **settled model** for the ConQuer-92 → SQL compiler. Everything here is
normative for the implementation. `reference/` is the opposite: NORMA's metamodel, fetched to
check the `.orm` export against, and never an instruction to the compiler.

| File | What it is |
|---|---|
| `model.md` | **The specification.** Schema part, naming part, query part, derivation rules, relational mapping, validation rules. Normative. |
| `ccm.schema.json` | JSON Schema for the same model. The machine-readable form the compiler loads and emits. |
| `binding-ormcore.md` | CCM ↔ NORMA `.orm` (`ORM2Core.xsd`). Import rules, export rules, and exactly what does not survive a round trip. |
| `binding-sql92.md` | CCM → SQL-92. The lowering, block by block. |
| `ccm.py` | Shared access to a model: the id indexes, and the derived schema functions §2.3 names — `Rel(r)`, `Player(r)`, `x ∼ y`, `RootsOf(x)`, plus reading verbalisation. Every other package imports this rather than rebuilding the indexes. |
| `validate.py` | Both validation passes: JSON Schema, then the semantic checks of `model.md` §7.2. `python3 validate.py [FILE …]`, defaulting to `examples/`. Needs `jsonschema` for pass 1; runs pass 2 without it. |
| `examples/presidents.ccm.json` | A worked model: the report's own presidents-and-hobbies example, encoding §6.2's *"WHICH ARE ALL IN"* query. |
| `tests/test_validate.py` | **One deliberately broken model per check in `validate.py`.** Each starts from the example, breaks exactly one thing, and names the check that must fire; the control asserts the unbroken model is clean. Asserting only that good models pass would leave a check that silently stopped firing green. 31 cases. |
| `ormxml.py` | CCM → `.orm`, per `binding-ormcore.md` §1. The reverse engineer writes one beside every model it derives. |
| `ormcheck.py` | Checks an exported `.orm` for what `ORM2Core.xsd` cannot say: typed references and cross-element invariants. See *On the `.orm` output* below. |
| `abstract.py` | Bird's automatic ORM abstraction: reads a large model at a higher level, for a human or a query writer, without changing it. |
| `forml.py` | FORML 2: every constraint said in English, after Halpin & Curland's ORM2-02 report. |
| `names.py` | How a schema spells things — camelCase, snake_case, plurals, abbreviations, units — in one place for the reverse engineer and the describer. |
| `tests/test_abstract.py`, `tests/test_forml.py`, `tests/test_names.py` | The three above. Every expected FORML string is quoted from ORM2-02; most of the naming cases assert that a name is left *unchanged*. |
| `tests/test_ormcheck.py` | **One deliberately broken `.orm` per check in `ormcheck.py`.** `examples/run.sh` proves the generator is clean today; these prove the checker would notice if it stopped being. `xmllint --schema` passes every one of them, which is the whole reason ormcheck exists. 15 cases. |

## Why a core model at all, rather than just using ORMCore

Comparing ConQuer-92 path expressions against ORMCore role paths found five things ORMCore
cannot represent, plus several ConQuer constructs that are abbreviations needing expansion,
plus one thing neither carries (the relational mapping); `model.md` §0 lists them. The Common
Core Model is the resolution of all of those in one place, so that the compiler has a single
unambiguous target and both `.orm` and SQL become *bindings* rather than the model itself.

The pipeline as built:

```
SQL catalog ─► reverse engineer ─► ┌───────────────────┐ ─► .orm export (to view in NORMA)
                  hand edits ─────►│ Common Core Model │
ConQuer-92 text ─► AST ─► lower ──►└───────────────────┘ ─► SQL-92
```

There is no `.orm` importer: refinement means editing the CCM JSON, and `binding-ormcore.md`
§1 and §2.1 say what an importer would have to do.

## On the `.orm` output

The generated `ORMModel` element **validates against the vendored `ORM2Core.xsd`**, and
`run-tests.sh` checks it on every run (via `xmllint`, skipped if absent). Getting there took
four corrections that only mechanical validation would have caught: the attribute is
`IsIndependent`, not `_IsIndependent`; `PlayedRoles` must precede `PreferredIdentifier`,
because `ObjectTypeType`'s own elements come before an extension's; an `ObjectifiedType`
requires a `NestedPredicate` reference to the fact type it objectifies; and `SubtypeFact`
spells it `PreferredIdentificationPath`.

`ormcheck.py` covers what the schema cannot. `ORM2Core.xsd` types every `id` as `xs:ID` and
every `ref` as `xs:IDREF` — but libxml2 does not resolve IDREFs in schema mode, and even where
a validator does, IDREF only proves the target *exists*, never that it is the right **kind**
of element. A `RolePlayer` pointing at a `Reading` validates cleanly against the schema; it
would not survive NORMA. `ormcheck` checks the typed references and the cross-element
invariants: role players are object types, a reading order names roles of its own fact type,
a reading's slot count matches its role sequence, an objectified type nests a fact, a
preferred identifier is a uniqueness constraint that exists.

It found a real defect on its first run: an objectified association's entity type claimed a
preferred identifier that was never created, in three of four generated models. XSD validation
had passed all of them.

Schema-valid is still not the same as accepted. **No NORMA has opened one of these files.**
That is the first of the two open items under *Status* below; `ormcheck` narrows the gap
rather than closing it.

## The rest of the project

| Folder | |
|---|---|
| `reverse/` | Relational catalog → draft CCM + `.orm` + a refinement worklist. |
| `conquer/` | ConQuer-92 → SQL, and a runner. |
| `render/` | CCM → an ORM 2 diagram in a browser. |
| `examples/` | Chinook and Northwind, end to end, checked against reference SQL. |

`run-tests.sh` at the root runs the built-in fixture; `examples/run.sh` runs the real ones.

## Status

The model is in use: the compiler in `conquer/` lowers every query to it and emits SQL from it,
the reverse engineer writes it, and `validate.py` checks every model `run-tests.sh` and
`examples/run.sh` build. Two things are still open:

1. **NORMA has not opened an exported `.orm`.** It validates against `ORM2Core.xsd` and passes
   `ormcheck.py` (*On the `.orm` output* above), but schema-valid is not accepted. No role-path
   XML is emitted at all, and neither vendored `.orm` file contains a single `LeadRolePath`,
   `PathedRole` or `CalculatedValue` element, so any this project emits would likely be the
   first instance data of its kind.
2. **The verbalisation of the lowered set comparators is unchecked against NORMA's
   verbalizer** (`binding-ormcore.md` §3). It is the one correspondence inferred rather than
   read off the schema.
