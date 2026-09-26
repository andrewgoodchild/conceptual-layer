# `render/` — drawing the ORM schema

Turns a Common Core Model into an ORM 2 diagram you can open in a browser.

```
orm_render.py MODEL.ccm.json -o diagram.html
orm_render.py MODEL.ccm.json -o diagram.html --compact    # open with value types hidden
orm_render.py MODEL.ccm.json -o body.html   --fragment    # body only, to publish as an Artifact
```

One self-contained file: no network, no build step, no library. Layout is precomputed, so the
page draws immediately and the same model always produces the same picture.

## The notation

ORM 2, as Halpin sets it out. Unfamiliar to most people, so the page draws a legend using the
real marks rather than describing them in words.

| Mark | Means |
|---|---|
| Soft rectangle, solid outline | entity type; the reference mode sits under the name in parentheses |
| Soft rectangle, dashed outline | value type |
| A row of small boxes | a fact type, one box per role |
| Bar over a span of role boxes | uniqueness constraint over those roles |
| Doubled bar | preferred identifier |
| Solid dot where a connector meets a shape | mandatory role |
| Arrow with a solid head | is a subtype of |
| Frame around the role boxes | objectified fact type |

## Two views

A reverse-engineered schema is mostly attributes — Chinook derives 53 value types against 10
entity types — so the full diagram is dominated by them. **Full notation** draws everything.
**Entities only** drops every fact type with a value-type role, leaving the entity-to-entity
structure: for Chinook that is 63 nodes down to 10, and the shape of the business becomes
readable in one look.

Both layouts are computed up front, so the toggle is instant.

## Interaction

Drag to pan, scroll to zoom, drag a shape to reposition it, click a shape to inspect it.
Selecting an object type dims everything it does not touch, which is the only way to read a
dense diagram.

The inspector shows what an ORM tool would — roles, readings, mandatory marks, reference mode,
data type, value restrictions, subtyping — and one thing they cannot: **the table and columns
each concept and role maps to**. That comes from the CCM's relational mapping
(`model/model.md` §6), which has no ORMCore counterpart, so this is the only place in the
toolchain where the conceptual and relational pictures sit side by side.

## Layout

`layout.py`: Fruchterman-Reingold with a fixed seed, a bounded frame, and a box-separation
pass afterwards. Two adjustments for this kind of model:

- Value types repel each other at roughly half strength, so an entity's attributes cluster
  around it instead of forming a ring at the diagram's edge with every connector crossing the
  middle.
- N-ary fact types get a hub node, so their role boxes have somewhere to sit; binary role
  boxes go at the midpoint of the line between the two players, rotated to it.

The frame matters. Without it, repulsion wins on small graphs and six nodes spread across
6600×8400 units.

It is a readable draft, not a hand-drawn ORM diagram. Nothing routes connectors around
shapes, so long edges cross. Drag the shapes that bother you.

## Files

| | |
|---|---|
| `layout.py` | Where the shapes go. No drawing. |
| `template.html` | The page: styles, SVG drawing, interaction. Written to publish as an Artifact, so it has no doctype or head — `--fragment` emits it as-is and the default wraps it for opening off disk. |
| `orm_render.py` | Resolves the model into what the page needs and fills the template. |
