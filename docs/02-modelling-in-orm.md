# 2 — Modelling in ORM

[1 — What a conceptual model is](01-conceptual-models.md) gave the vocabulary. This page is
about building a model: the procedure, the shapes you will need, the traps, and how to edit
and check a model in this repository.

## Three ways to get a model

1. **Derive a draft from a database you already have** — `reverse/reverse.py`, covered in
   [4 — Reverse engineering](04-reverse-engineering.md). This is the usual route, and the draft
   is never the answer; it is a first guess with a report attached.
2. **Draw it in NORMA** (the ORM 2 tool for Visual Studio) and export. This repository writes
   `.orm` files NORMA's schema accepts, but does not read them back — see *Round trips* below.
3. **Write the JSON by hand.** The format is small enough; `model/examples/presidents.ccm.json`
   is a complete hand-written model.

## The procedure, condensed

ORM's design procedure starts from *examples*, not from entities. The short form:

**Step 1. Verbalise the examples as elementary facts.** Take a report, a screen, a
spreadsheet — anything the business already has — and say what each cell means in one sentence
carrying one fact.

```
Employee 'Ada Lovelace' has EmployeeSalary 185000.
Employee 'Ada Lovelace' has Department 'ENG'.
Employee 'Alan Turing' has manager Employee 'Ada Lovelace'.
```

**Step 2. Draw the fact types those sentences are instances of**, with a reading for each. At
this point you have types, roles and readings, and no constraints.

**Step 3. Add uniqueness constraints**, and check each one against the population you started
with. This is the step that catches modelling errors: if you claim "each Employee has at most
one Department" and the examples already show someone in two, the claim is wrong or the
examples are.

**Step 4. Add mandatory constraints.** Ask of every role: must every instance play it?

**Step 5. Add the rest** — value constraints, subtypes, ring constraints (irreflexive,
acyclic), frequency constraints, and derivation rules for anything computed.

**Step 6. Check it by populating it.** Fill each fact type with real examples, including the
awkward ones — the employee with no manager, the contractor with no department. A constraint
that survives the awkward cases is one you can compile against.

The step that people skip is 6, and it is the only one that finds the mistakes.

## Readings are the user interface

A fact type's reading is what a query writer types. The reverse engineer names everything
`{0} has {1}` because it cannot know better, and the single highest-value edit to any derived
model is renaming those.

Take the derived company model and rename one reading:

```python
import json
m = json.load(open(".work/company.ccm.json"))
for c in m["concepts"]:
    if c["name"] == "EmployeeHasDepartment":
        c["readings"][0]["text"] = "{0} works in {1}"
json.dump(m, open("edited.ccm.json", "w"), indent=1)
```

```sh
python3 model/validate.py edited.ccm.json
python3 conquer/conquer.py edited.ccm.json --db .work/company.sqlite \
    "LIST n FROM Employee has EmployeeName n AND ALSO works in Department has DepartmentName: 'Engineering'"
```

```
n
------------
Ada Lovelace
Alan Turing
Grace Hopper
```

A fact type may have several readings, including one that runs the other way. Add the inverse
and the same fact type can be walked from the other end:

```python
{"id": "rd.EmployeeHasDepartment.inv", "text": "{0} employs {1}",
 "roleSequence": ["r.EmployeeHasDepartment.department", "r.EmployeeHasDepartment.employee"]}
```

```sh
python3 conquer/conquer.py edited.ccm.json --db .work/company.sqlite \
    "LIST d, n FROM Department has DepartmentName d AND ALSO employs Employee has EmployeeName n"
```

The `roleSequence` is what makes this safe: the reading's slots are bound to roles, so
`{0} employs {1}` with the roles reversed is the *same fact type read backwards*, not a second
relationship that could get out of step.

**Hyphen binding.** `{0} has manager- {1}` reads "has manager" and verbalises as *"each
Employee has at most one manager Employee"*. The hyphen binds the qualifying word to the
following type, which is how ORM disambiguates two fact types that would otherwise both read
"has".

## The shapes you will need

**Subtype.** A concept with `supertypes`. Every fact about the supertype applies to the
subtype; the subtype adds its own.

```json
{"id": "et.Manager", "name": "Manager", "kind": "entity", "supertypes": ["et.Employee"]}
```

**Objectified fact type.** A relationship that has properties of its own. In the company model
`Employee has Project` is objectified as `Assignment`, which then `has AssignmentHours`. Both
the fact type and the entity type exist, and paths may walk through either.

**Multi-valued fact.** Leave the uniqueness bar off. `Employee has Skill` with no uniqueness
on the `Employee` role says an employee may have many skills — no extra table needed in the
model, whatever the database does underneath.

**Derived concept.** A concept whose population is computed by a rule rather than stored. Add
the concept and the rule:

```json
{"id": "et.HighEarner", "name": "HighEarner", "kind": "entity",
 "supertypes": ["et.Employee"], "derivation": "dr.highearner"}
```
```json
{"id": "dr.highearner", "target": {"kind": "subtype", "ref": "et.HighEarner"},
 "source": "Employee [has EmployeeSalary s WHERE s > 150000]"}
```

From then on `HighEarner` is a type like any other:

```sh
python3 conquer/conquer.py edited.ccm.json --db .work/company.sqlite \
    "LIST n FROM HighEarner has EmployeeName n"
```

and it compiles to a common table expression:

```sql
WITH "HighEarner"("id") AS (
  SELECT DISTINCT employ3."emp_nr" FROM "employee" AS employ3
  WHERE employ3."salary" IS NOT NULL AND employ3."salary" > 150000) ...
```

**This is where a business definition belongs.** "High earner", "active customer", "churned" —
each one written once, verbalised back as *"An Employee is a HighEarner IFF …"*, and available
to every query. It is also the one thing this project measured as unambiguously worth having:
see [7 — What we measured](07-what-we-measured.md).

A rule may reference its own target, which gives you transitive closure — `reports up to` — and
compiles to `WITH RECURSIVE`.

## Four traps

**The fan trap.** Two one-to-many paths leaving the same type, joined in one query, multiply
each other's rows. Sum a salary across a join to assignments and you will get the salary once
per assignment. ORM can *see* this — the uniqueness constraints say which paths fan out — and
`conquer/` uses that to sum each value once, and to refuse a grouped count whose meaning the
fan-out makes ambiguous ([3 — Writing ConQuer](03-writing-conquer.md#the-fan-trap-and-the-one-refusal-you-may-meet)).

**Treating a code as an entity, or an entity as a code.** `DepartmentCode` is a value; the
`Department` it refers to is an entity. Collapse the two and you lose the ability to say that a
department has other properties.

**Compound facts.** `Employee has (Department, StartDate)` as one ternary fact type says the
department and the start date cannot be known separately. Sometimes true, usually not. Split it
unless the population actually demands it.

**Optional vs mandatory, conflated.** A nullable column means "may have none" *or* "not known
yet" *or* "does not apply to this subtype". The third case usually wants a subtype, not a
nullable role.

## Checking a model

```sh
python3 model/validate.py MODEL.ccm.json     # structural invariants + JSON Schema
python3 render/orm_render.py MODEL.ccm.json -o model.html   # the ORM 2 diagram, in a browser
python3 model/ormcheck.py MODEL.orm          # typed references in the exported .orm
python3 conquer/conquer.py MODEL.ccm.json --schema          # what the model lets you say
```

`--schema` is the one to run before writing a query. It lists every type, every reading, every
verb part and every value domain the model knows:

```
Predicate readings (the verb parts a path may use):
  EmployeeHasDepartment        Employee has Department
  EmployeeHasManager           Employee has manager Employee
  ...
Verb parts in this schema: has, has manager, is manager of, is of
```

## Round trips

`model/ormxml.py` **exports** a model to a NORMA `.orm` file, and `run-tests.sh` validates
the result against NORMA's own `ORM2Core.xsd`. There is **no importer**: a model refined inside
NORMA cannot currently be read back into a CCM file, and no NORMA has ever opened one of these
files. Refinement today means editing the CCM JSON, which is why the format is documented and
validated. Treat the `.orm` output as a viewer and a validation target, not as a round trip.

---

Next: [3 — Writing ConQuer](03-writing-conquer.md).
