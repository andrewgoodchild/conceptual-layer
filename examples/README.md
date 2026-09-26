# `examples/` — real databases, real queries

Two published sample databases, reverse engineered with no hand editing, then queried in
ConQuer-92 with every answer checked against reference SQL.

```
./fetch.sh          # download the databases (not committed; Northwind is 24 MB)
./run.sh            # reverse engineer, validate, render, and check every query
```

`run.sh` does the whole pipeline for each database: derive the model, validate it, validate
the generated `.orm` against `ORM2Core.xsd`, render the diagram, then run the query cases.

| | Chinook | Northwind |
|---|---|---|
| Source | [lerocha/chinook-database](https://github.com/lerocha/chinook-database) | [jpwhite3/northwind-SQLite3](https://github.com/jpwhite3/northwind-SQLite3) |
| Tables | 11 | 13 |
| Derived | 10 entity, 53 value, 63 fact types | 11 entity, 75 value, 85 fact types |
| Blockers | none | none |
| Query cases | 30 (the 14 of the exercise set, and 16 harder ones), all passing | 9, all passing (1 marked slow) |

## What the queries are checked against

For **Chinook** the first fourteen questions are not ours: they are a published exercise set,
[LucasMcL/15-sql_queries_02-chinook](https://github.com/LucasMcL/15-sql_queries_02-chinook),
and the cases keep that set's numbering. The reference SQL beside each was written here for
the columns the case asks for, so a pass means the transpiler returned the same rows as a
hand-written answer to a question posed without any knowledge of this project.

For **Northwind** the questions are the standard ones but the reference SQL was written here,
so it is an independent second implementation rather than an external authority. That file
exists mainly to exercise what Chinook does not: a table name containing a space
(`Order Details`), an objectified association carrying a payload (`OrderDetail`), and a pure
association with none (`EmployeeTerritory`).

Rows are compared as multisets, so order does not matter but duplicates do. The largest case
matches on 609,283 rows.

## What these two proved

Running against schemas nobody designed for this project found six real bugs that the hand-made
fixture never would have:

- `Order Details` broke SQL generation twice: unquoted identifiers, and an alias derived from
  the table name that inherited its space (`order 1`).
- `InvoiceLine.InvoiceId` derived a fact type called `InvoiceLineHasId`. A foreign key column
  names the table it points *at*, so stripping the owning table's prefix is wrong.
- `Invoiceline`, `Mediatype`, `Playlisttrack` — the namer lower-cased CamelCase it should have
  preserved, and could not see `CustomerTypeID` inside `CustomerDemographics`.
- Pathing into `OrderDetail` exposed that a fact node could only exit by the role its reading
  happened to name second. Section 6.1's role-exit is defined for *every* role.
- The emitter assigned root anchors after processing steps, so a path that *started* at a fact
  type could not be anchored at all.
- `Type: !x` inside a correlated aggregate was read as a literal instead of a variable binding.

## A caveat worth keeping

All but one predicate reading in these models is `{0} has {1}`, because a relational catalog
records no verbs; the exception, `Employee reports to Employee`, is read off a column named
`ReportsTo`. That is why some queries here read awkwardly — `Track is of Playlist`, the inverse
of `has`, rather than `Track is on Playlist` — and why `has` is ambiguous often enough to need
the target type named. Renaming readings is the first refinement Halpin's chapter 8 asks for,
and it is what would make these queries read like English. Here that means editing the CCM
JSON; [docs/02](../docs/02-modelling-in-orm.md) shows how.
