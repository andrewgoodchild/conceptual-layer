# model/reference/

Material written by someone else that the model is checked against: NORMA's ORM 2 metamodel,
fetched rather than distributed, and a guide to it. Nothing here is read by the code; the
model's own specification is `model/model.md`.

The sources the project relies on, with what each is used for, are listed under `references`
in [`CITATION.cff`](../../CITATION.cff).

| | |
|---|---|
| `orm-metamodel.md` | a guide to NORMA's `.orm` schema, its licence, and what of it the exporter uses |
| `fetch.sh` | gets the metamodel into `orm-metamodel/` |

`ORM2Core.xsd` and its companions are under the zlib/libpng licence and are not in the
repository. `run-tests.sh` validates generated `.orm` files against them when they are
present and says so when they are not. `NOTICE` records the terms.
