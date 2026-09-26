# Reverse engineering a conceptual model from existing tables

The literature behind `reverse/`. The question it answers: can a ConQuer-92 compiler take an
existing SQL database and derive the ORM schema it needs, instead of being handed one? The rules
as built are the table in [`README.md`](README.md#the-rules); this note is where they came
from.

The short answer is that this is an orthodox ORM procedure, not a workaround. Halpin's own
tooling shipped it, his own specification lists it as part of the method, and the definitive
treatment came out of the same department that produced ConQuer-92. What the literature is
equally clear about is that the output is a **draft** requiring human refinement, and it is
worth being precise about which parts are sound and which are guesses.

§3 is a working summary of Bird's 1997 thesis, read in full. The thesis is not in the
repository; it is held in UQ eSpace, which has no stable direct link, so find it from the
eSpace record.

## 1. It is part of the method

The ORM normative specification lists reverse engineering among ORM's procedures:

> "ORM includes graphical and textual languages for modeling and querying information at the
> conceptual level, as well as procedures for designing conceptual models, transforming between
> different conceptual representations, forward engineering ORM schemas to implementation
> schemas (e.g. relational database schemas, ontologies, object-oriented schemas, XML schemas)
> and **reverse engineering implementation schemas to ORM schemas**."
>
> — Franconi & Halpin, *ORM Abstract Syntax and Semantics*, BETA 3, 17 March 2020, Introduction

## 2. The shipped implementation: Visio for Enterprise Architects

**Halpin, T., Evans, K., Hallock, P. & MacLean, B. (2003).
*Database Modeling with Microsoft Visio for Enterprise Architects.* Morgan Kaufmann.
Chapter 8, "Reverse Engineering and Importing to ORM".**

VEA's ORM source model provided "forward and reverse engineering to/from physical database
schemas" (Halpin, *Microsoft's new database modeling tool: Part 2*, Journal of Conceptual
Modeling, August 2001, `orm.net/pdf/JCM2001Aug.pdf`). The chapter states the mapping rules:

| Relational construct | ORM result |
|---|---|
| Simple primary key | "displays as the reference mode of the entity type" |
| Composite key, all key fact types shown | "appears as a primary, external uniqueness constraint" |
| Foreign key | fact type whose relationship name has "FK *n*" appended |
| Column that is neither simple PK nor FK | "its underlying fact type is displayed as a relationship from the table entity type to a value type" |
| View | fact type marked `**`, which the chapter concedes "is not strictly correct, since views are typically not materialized" |

And the honest caveat, which is the sentence to quote at anyone who calls the approach
sacrilege, because it is Halpin conceding the point himself:

> "In practice, any draft ORM schema obtained by reverse engineering usually needs many
> refinements."

The refinements the chapter names: rename predicates, consolidate redundant value types,
replace injective (one-to-one) relationships with subtyping, and add missing constraints.
The chapter also notes an asymmetry: the tool "cannot further reverse engineer a logical
database model created in this way to an ORM schema."

## 3. The definitive academic treatment, from UQ

**Bird, L. J. (née Campbell) (1997). *Data Reverse Engineering: from a Relational Database
System to a 3-Dimensional Conceptual Schema.* PhD thesis, School of Information Technology,
The University of Queensland. Submitted 28 February 1997. 291 pp.**

Held in UQ eSpace. Read directly for the notes below; section and
algorithm numbers are hers.

Her acknowledgements name four supervisors, and the list is the reason this thesis matters
more to this project than any other source: **Maria Orlowska**, **Peter Creasy**, **Erik
Proper** — the author of the ConQuer-92 report this whole repository is built on — and
**Terry Halpin**, her first supervisor, whose Rmap the derivation rules invert. The query
language and the reverse engineering came out of the same room, within a year of each other.

Earlier papers, all as L. J. Campbell: *The Reverse Engineering of Relational Databases* (with
Halpin, 5th Workshop on the Next Generation of CASE Tools, Utrecht, 1994); *Reverse Engineering
using Verbalization Techniques* (ADC '95, Adelaide); *Data Structure Extraction — A
Methodological Approach* (UQ Technical Report 377, 1996); *Abstraction Techniques for Conceptual
Schemas* (with Halpin, ADC 1994); *Abstractions — Making flat conceptual schemas more
comprehensible* (with Halpin, **DKE** 20(1):39–85, 1996); *Adding a New Dimension to Flat
Conceptual Modeling* (ORM-1, Magnetic Island, 1994).

"3-dimensional" is not about nesting or objectification. It is a **layered abstraction**: major
object types form a layer that summarises the one below, so a large schema can be read at
several levels.

That was first noted here as a diagramming idea belonging to `render/`. It is not: chapter 5 is
an algorithm over the constraints, and what it produces is useful wherever a large model has to
be *said*, not only drawn. It is implemented in `model/abstract.py` -- WeightSchema (Algorithm
5-1) and its twelve weighting rules, the kernel (Definition 5-28), AddRingFTs, ConnectSchema
and the clustering axioms -- and `summarise()` renders a level as English. On the eleven BIRD
models the flat verbalisation is 55 KB and the level-2 summary is 18 KB; on Spider 2.0's
`Baseball`, 341 fact types become a 4 KB description. Rules 7 to 11 weigh set constraints and
never fire on a reverse-engineered model, which carries only uniqueness and mandatory.

### 3.1 The architecture: extraction, then conceptualization

Her method is **two phases**, and `reverse/derive.py` collapses them into one:

| | |
|---|---|
| **Chapter 3 — Extraction** | catalogue + check clauses + assertions + triggers + user-interface code + **data populations** → a logical schema in her IDL notation. Ten steps. |
| **Chapter 4 — Conceptualization** | IDL → ORM: elementary fact types, entity types, subtypes, the conceptual reading. |

Splitting them is what lets a constraint be *sourced* rather than merely asserted, which is the
next point.

### 3.2 Table 3.1 — every construct has ranked alternative sources

The organising idea of the whole extraction phase, and the thing this project does not have.
Each construct lists the places it may come from, best first, ending in a default assumption or
the domain expert. **Nothing is fatal.**

| IDL construct | Possible input sources, in order |
|---|---|
| Relationship types | relational tables |
| Fact type roles | columns |
| Primary uniqueness constraint | primary keys → other keys + default assumptions → **significant data populations** + default assumptions |
| Optional roles | optional columns → significant populations → the assumption that primary columns are mandatory and others optional |
| Functional dependencies | keys → assertions → table triggers → UI triggers → significant populations → the assumption that no transitive FDs exist |
| Existence constraints | check clauses → table triggers → UI triggers → populations → the assumption that none apply |
| Subset and exclusion constraints | check clauses → table triggers → UI triggers → populations → the assumption that none apply |

### 3.3 Step 2 processes *keys*, not *primary keys* — and this is where we diverge

Her Algorithm 3.2 translates **each key or unique index** into a uniqueness constraint, with
primary keys merely *marked* as primary:

> `FOR EACH k ∈ Key DO … Unique += v; IF k ∈ PKey THEN PKey += v`

A table with no declared primary key is therefore **not a failure**. It becomes a relationship
type whose primary uniqueness constraint is simply *not yet known*, to be supplied later by
Step 9 from the data, or by the domain expert in Step 10.

**Our rule 1 does the opposite**: it treats a missing primary key as a blocker that stops the
derivation, and the table's fact types never get built. Measured over 206 Spider databases,
this is the *only* blocker that ever fires — 103 tables across 47 databases (23%) — and the
loss is not cosmetic. `academic.cite(cited, citing)`, two foreign keys to `publication` and no
primary key, is the ordinary many-to-many association; it produced no concept and no mapping
entry at all, so "which publications cite this one" became unaskable. Bird's architecture would
have modelled it as a relationship type and left the uniqueness constraint open.

### 3.4 Step 9 — mining the data, with algorithms

§3.3.9 is the direct answer to "can we just infer it from the data". Her algorithms:

| | |
|---|---|
| 3.9-a | nullable roles — a role whose population contains a null is optional |
| 3.9-b | **uniqueness constraints**: assume every role unique, then walk row pairs; roles that agree contradict the assumption, and weaker constraints are assumed in their place. O(Σ&#124;Pop(r)&#124;²·&#124;Roles(r)&#124;²) |
| 3.9-d2 | **intra-relationship functional dependencies**: `FindInvalidFDs` collects agree-sets from row pairs and keeps only the most general invalid FDs; `FindPositiveFDs` derives the valid ones from them |
| 3.9-e | complex (compound) roles, inferred from roles that repeatedly appear together on the left of a minimal FD |
| 3.9-f, -g, -h | existence constraints; subset and exclusion constraints; value constraints |

3.9-d2 is an **agree-set** method — the Dep-Miner / FastFDs family — written in 1997, ahead of
TANE (1999), Dep-Miner (2000) and FastFDs (2001). She restricts FDs to a single table
(§2.3.5), on the grounds that inter-table FDs "are rare in practice", and handles the
optional-role case explicitly (§2.3.6, FDs over partial information) — which the classical FD
literature mostly does not.

### 3.5 Her caveat, which is the answer to "is inferred evidence trustworthy"

Quoted because it settles the epistemics better than anything written here could:

> "The analysis performed in this step is obviously dependent on whether or not the existing
> data populations are representative of the data constraints imposed. If the populations are
> large enough, it is likely that they accurately represent at least those constraints imposed
> by the existing information system. However, **if the population is not significant, trends or
> constraints may be detected which hold by coincidence rather than by necessity.** The decision
> as to which of the constraints identified in this step necessarily hold in the information
> system is ultimately the job of a domain expert (Step 10)."

Note the phrase carried through Table 3.1: *significant* data populations, not merely present
ones. Measured on the 103 blocked Spider tables, the median population is **15 rows**, and 29 of
the 47 tables where a candidate key happens to be unique have 20 rows or fewer. By her standard
that corpus cannot support key inference at all — which is a fact about Spider's toy data, not
about the technique.

She also makes the sharper observation that the *refutation* direction is the sound one:
identifying constraints that hold in the universe of discourse but are contradicted by the data
"is of great value when the quality of the existing system is being assessed."

### 3.6 She named the failure mode of this literature in 1997

> "few papers consider how the logical structures and constraints are extracted from the
> existing information system. Instead, they tend to assume that a logical description of the
> data structures has already been extracted from the system catalogue. In order to get around
> this oversight, many authors have been forced to make an assortment of unrealistic assumptions
> (such as assuming that columns which share the same name necessarily share a common domain)."

Rules 9 and 10 below are exactly that assumption, and are marked *guess* for exactly that reason.
She credits Petit et al. [PTBK96] with beginning to explore population analysis for a limited
class of FDs; her Step 9 is the general treatment.

### 3.7 What changed here as a result

Her method changed four things in the rules, and three are done. Rule 1 is no longer a blocker
where a table has foreign keys to organise it (rules 1b and 1c); rule 4 no longer needs a
declared key when every column is in a foreign key (rule 4d); and data inference sits behind
opt-in `--infer-*` flags, at a confidence level of its own, `population`, never promoted to
*sound*. The fourth, recording the *source* of every constraint as her Table 3.1 does — a
primary key, a unique index, a population of 12,400 rows, assumed absent — is only half done:
the confidence levels separate population evidence from the catalogue's, but not one catalogue
source from another.

### 3.8 Her case study, run through our derivation

Appendices F–I are a complete worked example: the "DREC Information System", a conference
organiser in MS Access. F describes it, G extracts the logical schema, H conceptualizes it, I
abstracts it. It is the only end-to-end ground truth for this problem, produced by the person
who defined the method.

G.3, verbatim: *"because the 'DREC System' does not explicitly declare foreign keys, no
progress can be made in this step."* Every relationship in her result is recovered from user
interfaces, queries and data.

Transcribed as `reverse/tests/scenarios/08-bird-drec-case-study.sql` (16 tables; the column
lists are hers, the keys reconstructed since F.2 lists columns only) and run through
`derive.py`:

| | |
|---|---|
| Entity types | 16 |
| Fact types | 56 — every one of them an attribute |
| **Entity-to-entity relationships** | **0** |
| With `--infer-fks` | **0** |

Sixteen tables become sixteen unrelated entity types. `--infer-fks` adds nothing because it
matches a column name against a single-column primary key *name*, and her schema names
references by concept while targets name their identifier: `Rating.paper` faces `Paper.number`,
`Person.country` faces `Country.country_code`, `Request.motel_name` faces `Motel.mname`. That
is ordinary good relational naming, and it defeats name-matching completely — which is exactly
the "unrealistic assumption" of §3.6, demonstrated on her own data.

The one good outcome is that the failure is loud: the report says *"Not one foreign key is
declared anywhere … the model is a list of tables, not a conceptual schema."* Kept as a
permanent scenario so the limitation stays a tested fact rather than a claim.

Items 1 and 2 are done. Over the 206 Spider databases the blocked count fell from 47 databases
to 14 and from 103 tables to 37, adding 389 roles; `academic.cite` is now a ring fact type over
`Publication` and is queryable. Items 3 and 4 are not.

Related, by the same group: **Bird, L., Goodchild, A. & Halpin, T. (2000). "Object Role
Modelling and XML-Schema."** *Proc. ER 2000*, Salt Lake City, LNCS, 309–322 — the forward
direction, ORM to XML Schema. Also **Bird, L., Goodchild, A. & Finnigan, S. (1999). "Querying
Heterogeneous Databases Using Standardized Schemas and SQL."** *ADC 1999*.

### 3.9 What the field learned after 1997

Bird's Step 9 predates the discovery literature it anticipates. Her Algorithm 3.9-d2 finds
functional dependencies from **agree sets** over row pairs — the Dep-Miner (2000) and FastFDs
(2001) family — and her 3.9-b weakens an all-unique assumption the way the lattice-traversal
algorithms would. What came after:

| | |
|---|---|
| **TANE** (Huhtala et al. 1999) | levelwise attribute-lattice traversal with stripped partitions; the classic |
| **Dep-Miner** (2000), **FastFDs** (2001) | agree-set / difference-set methods — Bird's shape, published later |
| **HyFD** (Papenbrock & Naumann, SIGMOD 2016) | hybrid sampling + lattice; current state of the art |
| Papenbrock et al., VLDB 2015 | the seven-algorithm comparison, and **BINDER** for inclusion dependencies |
| **DUCC** (VLDB 2013), **HyUCC** | unique column combinations, i.e. candidate keys |

None of that machinery is needed here: it exists because the attribute lattice explodes on wide
tables, and the tables in question are narrow. What *is* needed is the line of work aimed at
this specific problem — picking foreign keys out of inclusion dependencies, which is a ranking
problem, not a discovery one:

- **Rostin et al. (2009)**, *A Machine Learning Approach to Foreign Key Discovery* — ten
  heuristic features over INDs.
- **Zhang et al. (2010)**, *On multi-column foreign key discovery* (VLDB) — a value-distribution
  "randomness" feature that subsumes most of Rostin's **except column names**.
- **Jiang & Naumann (2020)**, *Holistic primary key and foreign key detection* — score functions
  over UCCs and INDs together, with pruning. PKs and FKs are chosen jointly, not separately.
- **Motl & Kordík** measure feature importances directly, and the ordering is the surprise:
  FK-column-name-vs-PK-table-name is the strongest signal, containment itself is the *weakest*,
  and a global assignment step lifts FK F-measure from 0.74 to 0.87 on its own.

### 3.10 Ablation on 90 Spider databases

Ground truth is every declared single-column foreign key; candidates are every inclusion
dependency `population.py` finds. **33 of 118 declared foreign keys are violated by their own
data**, so 85 are findable at all and recall below is against those.

| | kept | right | precision | recall | F1 |
|---|---|---|---|---|---|
| containment only | 408 | 81 | 20% | 95% | 0.33 |
| + column does not identify its own table | 298 | 78 | 26% | 92% | 0.41 |
| + name resembles the target table | 53 | 38 | 72% | 45% | 0.55 |
| + name resembles the target key | 79 | 56 | 71% | 66% | **0.68** |
| + differs from its own table's name | 85 | 57 | 67% | 67% | 0.67 |
| + declared types agree | 136 | 70 | 51% | 82% | 0.63 |
| **Zhang's spread alone** (no names at all) | 56 | 41 | 73% | 48% | 0.58 |
| **shape only** — spread + coverage + not-own-key, no names | 86 | 62 | 72% | 73% | **0.73** |
| all, one best target per column, thresholded | 76 | 60 | 79% | 71% | **0.75** |

Single features alone, each resolved to one target per column: **spread 0.68**, name-vs-target-key
0.67, coverage 0.66, name-vs-target-table 0.58, does-not-identify-own-table 0.53, type agreement
0.48. The ordering matches the published work — containment last — with one correction to it:
Zhang's distribution feature is the strongest single signal of any kind, name-based included.

**The shape-only row is the answer to §3.8.** Bird's schema names references for the concept and
keys for the identifier, so `Rating.paper` faces `Paper.number` and string comparison is not weak
evidence but none. Scoring on the data's shape alone — how the child's values sit inside the
parent's, how much of it they cover, whether the column identifies its own table — reaches F1
0.73 without consulting a single name, which is better than the *named* model managed before
`spread` existed. Exposed as `--ignore-names`.

Tuning the threshold on half the databases and scoring the other half: containment alone
**F1 0.31**, the ranked model **0.72**, and **0.77** once Zhang's spread is included (88%
precision, 68% recall). On the four databases of §3.8's evaluation the shipped configuration
proposes 26 foreign keys and **all 26 are correct** (100% precision, 84% recall), against 87%
recall at 17% precision for containment alone.

On Chinook with its foreign keys stripped out — Bird's situation exactly, real data and no
declarations — it proposes ten relationships and all ten are right (91% recall). With
`--ignore-names`, nine of eleven at 82% precision: worse here, because Chinook's names are
helpful, and the point of that mode is the schemas where they are not.

## 4. The classical relational reverse-engineering literature

- **Shoval, P. & Shreiber, N. (1993). "Database reverse engineering: from the relational to the
  binary relationship model."** *Data & Knowledge Engineering* 10, 293–315. The closest fit of
  the classical papers, because the binary-relationship model *is* NIAM's model. Algorithmic
  transformation of a relational schema to a binary-relationship schema.
- **Chiang, R., Barron, T. & Storey, V. (1994). "Reverse engineering of relational databases:
  extraction of an EER model from a relational database."** *Data & Knowledge Engineering* 12,
  107–142. Combines schema analysis with **data instance analysis**, which is how you recover
  what the catalog does not declare.
- **Premerlani, W. & Blaha, M. (1994). "An approach for reverse engineering of relational
  databases."** *Communications of the ACM* 37(5), 42–49. With the companion
  **Blaha & Premerlani (1995), "Observed idiosyncrasies of relational database designs,"**
  *WCRE 1995*, 116 — a catalogue of the ways real schemas violate the assumptions.

## 5. Current tools that do it

- **FactEngine "Boston"** reverse engineers a database into ORM and imports NORMA `.orm` files.
  <https://factengine.ai>
- **ActiveFacts / CQL** (Clifford Heath). The Microsoft AdventureWorks schema was reverse
  engineered into CQL: <https://github.com/infinuendo/AdventureWorks>. Endorsed on orm.net.
- **CaseTalk**, **ORM Studio** — both listed under tools at <https://www.orm.net/resources.html>.

## 6. The rules, inverted from Rmap

The derivation inverts Halpin's Rmap, targeting the ORM functions the ConQuer-92 semantics need
(§2 of the report). The rule table, with each rule's confidence and whether it is applied, is
in [`README.md`](README.md#the-rules); what follows are the three points about it that the table
does not say.

Rule 10, naming, produces one thing beyond names: readings for **ring** fact types. The
placeholder `{0} has {1}` is honest for `Employee has Department` — the verb is unknown, and
"has" is what ORM says when it does not know — but over two roles of one type it says nothing
at all, and a query has to fall back on role references to say which way it walks. So for a
ring the names are read for a verb, in this order of evidence: a labelled column (`manager_nr`
→ `{0} has manager- {1}`, with `{0} is manager of {1}` from the other end; `parent`/`child` →
`is parent of` / `is child of`; `reports_to` → the verb itself), then the table's name minus
the player's (`connected` → `is connected to`, `follows` → `follows`, `friendship` → `has
friendship with`), and if neither says anything the placeholder stays. The hyphen is FORML 2
§1.2's: the adjective belongs to the object type, so the verbaliser puts the quantifier before
it — *"at most one manager Employee"* — and the query language drops the hyphen, `has manager
Employee`. A wrong guess here inverts a hierarchy silently, which is why every one is reported
in words.

The confidence column is one axis short of Bird's Table 3.1, which records the **source** as
well: a uniqueness constraint from a primary key, from a unique index, from a population of
12,400 rows, and one *assumed absent* are four different claims. A population-derived
constraint is a statement about data that can change under it, and has a class of its own
(§3.5, §3.7); the other three the table still calls alike "sound".

Note that rules 1 and 2 collapse two pieces of ConQuer-92 machinery: because entity instances
are already their key values, the `Denote` function of §7.13 and the entity-to-value expansion
of §5.9 become no-ops. That is a simplification of the compiler, not a compromise of it.

## 7. The pipeline

This note first recommended a generator that emits a `.orm` file for a human to refine in NORMA,
and a compiler that reads the refined `.orm`. The project goes through the Common Core Model
instead, because the reverse engineer is the only step that knows the relational mapping and
`.orm` cannot carry it; [`README.md`](README.md#why-it-emits-ccm-and-not-orm-directly) says
why. The argument for the draft survives unchanged: the conceptual schema stays a human
artefact, independent of the table layout, and the generator only removes the blank-page
problem — the workflow chapter 8 of the Visio book prescribes.

Schema and metamodel files are in `model/reference/orm-metamodel/`; see
`model/reference/orm-metamodel.md`.
