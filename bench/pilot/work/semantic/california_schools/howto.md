# Writing the semantic layer

You are given a conceptual model of a database (the schema listing and its FORML
sentences) and a list of **definitions** that the business uses when it asks questions of
this data. Your job is to encode each definition *in the model*, so that anyone querying
later can use the business's term instead of re-deriving it. Three constructs, all in
ConQuer-92 (the query language whose readings appear in the schema listing):

## 1. A derived subtype — a noun phrase that picks out some of a type

    "exclusively virtual refers to Virtual = 'F'"

    {"id": "et.ExclusivelyVirtualSchool", "name": "ExclusivelyVirtualSchool", "kind": "entity",
     "supertypes": ["et.School"], "derivation": "dr.exvirtual"}
    {"id": "dr.exvirtual", "target": {"kind": "subtype", "ref": "et.School"...

The rule's `source` is a **path whose heads are the population**:

    {"id": "dr.exvirtual", "target": {"kind": "subtype", "ref": "et.ExclusivelyVirtualSchool"},
     "source": "School [has SchoolVirtual: 'F']"}

A subtype inherits every reading of its supertype: `ExclusivelyVirtualSchool has SchoolName n`.

## 2. A derived fact type — a named quantity or relationship computed from others

    "excellence rate = NumGE1500 / NumTstTakr"

    {"id": "vt.ExcellenceRate", "name": "ExcellenceRate", "kind": "value",
     "dataType": {"name": "numeric"}}
    {"id": "ft.SatscoreHasExcellenceRate", "name": "SatscoreHasExcellenceRate", "kind": "fact",
     "roles": [{"id": "r.SatscoreHasExcellenceRate.satscore", "player": "et.Satscore",
                "name": "Satscore", "ordinal": 0},
               {"id": "r.SatscoreHasExcellenceRate.rate", "player": "vt.ExcellenceRate",
                "name": "Rate", "ordinal": 1}],
     "readings": [{"id": "rd.SatscoreHasExcellenceRate", "text": "{0} has {1}",
                   "roleSequence": ["r.SatscoreHasExcellenceRate.satscore",
                                    "r.SatscoreHasExcellenceRate.rate"]}],
     "derivation": "dr.excellence"}
    {"id": "dr.excellence", "target": {"kind": "factType", "ref": "ft.SatscoreHasExcellenceRate"},
     "source": "LIST s, r FROM Satscore s has SatscoreNumGE1500 g AND ALSO has SatscoreNumTstTakr t AND ALSO (g * 1.0 / t) AS r"}

The rule's `source` is `LIST a1, a2 FROM <path>`, **one listed thing per role, in role
order**. A grouped count is a derived fact type too:

    "LIST u, c FROM User u is owner of Post p AND ALSO THE COUNT OF p GROUPED BY u AS c"

Use `{0} has {1}` as the reading unless the same two types already have such a reading, in
which case give it an adjective: `{0} has excellence- {1}` (then queries say `has excellence
ExcellenceRate`). A fact type with three roles needs a word between every pair of slots --
`{0} has full name {1} and surname {2}` -- because a query walks it verb part by verb part;
`{0} has full name {1} {2}` cannot be walked. Prefer two binary fact types.

## 3. A macro — a formula or predicate with parameters, or a whole-query number

    "percentage = DIVIDE(COUNT(x WHERE cond), COUNT(x)) * 100"

    {"id": "mc.pct", "name": "PercentFemale", "parameters": [], "kind": "scalar",
     "source": "THE COUNT OF Superhero [has Gender has GenderGender: 'Female'] * 100 / THE COUNT OF Superhero"}
    {"id": "mc.older", "name": "OlderThan", "parameters": ["dob", "years"], "kind": "condition",
     "source": "year(today()) - year(dob) > years"}

Kinds: `scalar` (a number), `condition` (true or false), `path` (a set of things).
A macro may use another macro, never itself.

## The language you have for a rule body

The examples above use `THE COUNT OF` and `THE SUM OF`; the language has more, and a
definition that needs one of these is expressible, so do not report it as not.

- Aggregates: `THE COUNT OF P`, `THE DISTINCT COUNT OF P`, `THE SUM OF P`, and
  `THE MINIMUM P`, `THE MAXIMUM P`, `THE AVERAGE P` (no `OF`), where P is a path
  ending in the value: `THE MAXIMUM Budget has BudgetSpent`, `THE AVERAGE Driver has
  DriverAge`. To aggregate a value bound earlier write `THE MAXIMUM v IN <path binding v>`.
  A grouped value is `THE COUNT OF x GROUPED BY g AS c`; an aggregate of a grouped
  aggregate is `THE MINIMUM c IN (Atom a has AtomElement e AND ALSO THE COUNT OF a
  GROUPED BY e AS c)`.
- Functions (in a filter, a comparison or a value): `like(x, 'TR%_19')`,
  `starts_with(x, 'TR')`, `contains(x, 'a')`, `ends_with(x, '_19')`, `substr(x, 1, 4)`,
  `year(d)`, `month(d)`, `day(d)`, `today()`, `days_between(a, b)`, `abs(x)`,
  `if(c, a, b)`, `div(a, b)` (integer division; `/` is real division).
- A test on a bound value goes in a WHERE inside the bracket:
  `Atom [has AtomId i WHERE like(i, 'TR%_19')]`, `Driver [has DriverDob d WHERE
  year(d) >= 1980 AND year(d) <= 1985]`.
- Absence of a fact ("no description recorded", "IS NULL") is `BUT NOT has X`:
  `Patient BUT NOT has PatientDescription` is the population with no description.
- A ratio: `THE COUNT OF X * 100 / THE COUNT OF Y`. Two counts side by side:
  `LIST THE COUNT OF X, THE COUNT OF Y`.

## What to encode, and what not to

- Encode a **term**: a noun phrase or adjective the business uses for a subset, a named
  quantity, a formula, a code's meaning ("SM = 'negative' means normal"). Ask: would this
  be in a glossary?
- Do **not** encode an **instance**: a particular person, date or id ("Lewis Hamilton
  refers to forename 'Lewis' and surname 'Hamilton'", "TR009 is the molecule id"). Those
  are what a question supplies, not what a business defines.
- Do not combine several conditions that only make sense together for one question. One
  definition, one concept.
- Do not put ORDERED WITH or THE FIRST in a rule; a definition is a set.
- Ids: prefix with `et.`, `vt.`, `ft.`, `r.<Fact>.<role>`, `rd.`, `dr.`, `mc.`; names in
  PascalCase, unique in the model. Check the schema listing so you do not reuse a name.

## Proving it

    python3 check.py DB semantic.json

merges your fragment into the model, validates it, lowers every rule, and runs
`THE COUNT OF X` for each derived type and a dummy invocation of each macro. Fix anything
it reports. It writes `DB.semantic.ccm.json` next to your fragment when everything passes.
