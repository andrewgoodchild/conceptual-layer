# 1 — What a conceptual model is, and why you would want one

A database schema tells you how data is *stored*. It does not tell you what the data *means*.

```sql
CREATE TABLE employee (
    emp_nr      INTEGER PRIMARY KEY,
    emp_name    VARCHAR(64) NOT NULL,
    salary      DECIMAL(10,2),
    manager_nr  INTEGER REFERENCES employee(emp_nr)
);
```

Everything a reader needs is missing. Is `salary` annual or monthly? Is `manager_nr` the
employee's manager, or the employee this row *is* the manager of? May an employee have two
managers next year? Nothing in the DDL answers any of that, and the answers are exactly what
someone has to know before they can write a correct query.

A **conceptual model** records the answers. This project uses one particular kind, **Object
Role Modeling**, and the rest of this page is ORM from zero. If you already know ORM, skip to
[2 — Modelling in ORM](02-modelling-in-orm.md).

## Facts, not tables

ORM starts from sentences that are true about the business, each carrying exactly one fact:

```
Employee 'Ada Lovelace' has EmployeeSalary 185000.
Employee 'Ada Lovelace' has Department 'ENG'.
Employee 'Alan Turing' has manager Employee 'Ada Lovelace'.
```

These are **elementary facts** — none of them can be split into two smaller facts without
losing something. "Ada earns 185000 and works in Engineering" is not elementary; it is two
facts wearing one sentence.

That sounds like a pedantic distinction. It is the whole trick. A table row is *not*
elementary: `employee` above asserts a number, a name, a salary and a manager in one breath,
and every awkward thing about relational schemas follows from that packing — nulls for facts
that do not exist, update anomalies, and the fact that you cannot tell from the DDL whether
`salary` is optional because it is unknown or optional because some employees genuinely do not
have one.

Take the same information apart into elementary facts and each one can be constrained on its
own terms.

## The vocabulary

Five words cover most of it.

| Term | What it is | In the example |
|---|---|---|
| **Entity type** | a kind of thing that exists independently and is *referred to* by something else | `Employee`, `Department`, `Project` |
| **Value type** | a kind of thing that is its own identity — a number, a string, a date | `EmployeeName`, `EmployeeSalary`, `DepartmentCode` |
| **Fact type** | a kind of sentence: a relationship between one or more types | `Employee has EmployeeSalary` |
| **Role** | one slot in a fact type — the part one type plays in it | in `Employee has Department`, `Employee` plays the "has" role |
| **Reading** | how a fact type is said in English, with the slots numbered | `{0} has {1}`, `{0} is manager of {1}` |

An entity type needs a **reference scheme**: a way to point at one of its instances. `Employee`
is referred to by its `EmployeeNr`, `Department` by its `DepartmentCode`. That is why the model
below has a fact type `Employee has EmployeeNr` as well as the entity type itself — being
referred to by a number is a fact like any other.

The **population** of a fact type is the set of facts of that kind that are currently true.
Populations are how ORM checks a model: you draw the diagram, then you fill it with example
rows and ask the domain expert whether the sentences read true.

## Constraints are the part that matters

A fact type on its own says a sentence is *possible*. Constraints say which populations are
*legal*, and they are what a query compiler can actually use.

**Uniqueness.** A line over one role says that role's filler appears at most once:

> Each Employee has at most one EmployeeSalary.

Over two roles (a *spanning* uniqueness constraint) it says the combination appears at most
once, which is what makes a many-to-many:

> Each Employee, Project combination occurs at most once in the population of
> `Employee has Project`.

**Mandatory.** A mandatory role says every instance must play it:

> Each Employee has some EmployeeName.

Note what the pair of constraints does that a column cannot: `NOT NULL` conflates "every
employee has one" with "at most one", and a nullable column conflates "may have none" with
"may have several". ORM states the two separately, so `Employee has EmployeeSalary` can be
*optional and single-valued* while `Employee has Skill` is *optional and multi-valued* — and
the second one does not need a new table to say so, just a missing uniqueness bar.

**Value constraints** list what a value type may hold: `EmployeeGender` is one of `'M'`, `'F'`,
`'X'`.

**Subtypes.** `Manager` is an `Employee`; every fact about employees applies to it, and
managers additionally have a car space.

**Objectification.** Sometimes a relationship is itself a thing that has properties. "Employee
works on Project" becomes `Assignment`, which then `has AssignmentHours`. In the relational
world that is an association table with extra columns; in ORM it is a fact type wearing an
entity type's hat.

## Verbalisation: the model reads back as English

Every constraint above was quoted from output, not invented. This repository generates it:

```sh
./run-tests.sh                       # builds .work/company.sqlite and derives a model
sed -n '/## What the model says/,/^## /p' .work/company.report.md
```

```
- Each Employee has some EmployeeName.
- Each Employee has at most one EmployeeSalary.
- For each DepartmentName, at most one Department has that DepartmentName.
- Each Employee, Project combination occurs at most once in the population of Employee has Project.
- Each Manager is an Employee.
```

That controlled English is **FORML** (Formal ORM Language). It is not decoration. A domain
expert cannot confirm "27 constraints", and cannot confirm "UNIQUE(dept_name)" either, but
they can confirm *"For each DepartmentName, at most one Department has that DepartmentName"* —
and they can reject it, which is the useful direction. `model/forml.py` implements the
verbalisation patterns from Halpin & Curland's *ORM 2 Constraint Verbalization*; the reverse
engineer prints every constraint it guessed so a human can throw out the wrong ones.

This is the property that makes ORM worth the trouble compared with ER or UML class diagrams:
the model is stated in sentences, so it can be *read back* in sentences, so it can be checked
by someone who will never read a diagram.

## Where the relational database went

A conceptual model is not a replacement for tables — it is a layer above them. The mapping
between the two lives *inside* the model file, because a query written in conceptual terms has
to become SQL over real columns:

```json
"mapping": {
  "tables":     [{"id": "t.employee", "name": "employee"}],
  "columns":    [{"id": "c.employee.salary", "table": "t.employee", "name": "salary",
                  "dataType": {"name": "decimal"}, "nullable": true}],
  "conceptMap": [{"concept": "et.Employee", "table": "t.employee",
                  "identifyingColumns": ["c.employee.emp_nr"]}],
  "roleMap":    [{"role": "r.EmployeeHasSalary.salary", "table": "t.employee",
                  "columns": ["c.employee.salary"]}]
}
```

So a model in this repository carries three things at once: the vocabulary (types and fact
types), the rules (constraints), and the wiring (which column holds which role). The format is
specified in [`model/model.md`](../model/model.md); you rarely write it by hand.

## Why any of this in 2026

The honest answer, measured rather than asserted, is in [7 — What we measured](07-what-we-measured.md):
handing a language model a conceptual model instead of the DDL did **not** make it write better
queries on a standard benchmark. What did help — by 8 points — was writing down what the
columns mean, and that helped a plain SQL writer exactly as much.

So the case for a conceptual model is not "LLMs need it to write SQL". The case is narrower and
survives the measurement:

- **The definitions are the asset, and they need somewhere to live.** "Active customer means an
  order in the last 90 days" is worth 8 points to any writer, human or model. A conceptual model
  is a place to put that sentence where it is checkable and versioned rather than lost in a
  Slack thread.
- **A model can be read back and confirmed.** FORML turns a schema into claims a domain expert
  can reject. Nothing else in the stack does that.
- **Constraints are machine-usable.** Uniqueness is what tells a compiler that joining two
  one-to-many paths will multiply rows. This repository uses exactly that to refuse a class of
  wrong aggregate (see [5 — Refusals](05-the-toolchain.md#refusals-and---permissive)) — though
  the measurement showed that class is rarer in practice than the architecture assumed.

---

Next: [2 — Modelling in ORM](02-modelling-in-orm.md).
