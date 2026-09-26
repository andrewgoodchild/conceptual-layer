# 8 — Where ConQuer came from

The published record of the language, and how this project relates to it. Everything here is
either what a publication says, cited where it is named, or what this project measured.
[`CITATION.cff`](../CITATION.cff) lists only the works the repository itself uses.

## 1. The published record

**RIDL.** R. Meersman, *The RIDL Conceptual Language* (Control Data Belgium, Brussels, 1982),
with O. De Troyer, R. Meersman & F. Ponsaert, *RIDL user guide* (Control Data, 1983): a
conceptual language for querying, updating and constraints over NIAM schemas, binary fact types
only. No copy of either report was found; both are known through C. Debruyne's 2013 VUB thesis,
which quotes RIDL constraints directly —

    EACH A IS IDENTIFIED BY (B S A) AND (D W C U A).

— and gives a full grammar for R-RIDL, a dialect for querying RDF *"based on the original RIDL
language"*, whose top rule is `LIST setExpression | FOR setExpression LIST … AS …`. Debruyne
also records, citing Halpin (1989) and Halpin & Morgan (2008), that RIDL can state which join
path identifies an external uniqueness constraint, which an ORM diagram cannot.
`model/model.md` §2.4 records that the CCM cannot say it either.

**LISA-D.** ter Hofstede, Proper & van der Weide, in *Information Systems* 18(7), 1993
([HPW93]); *Australian Computer Science Communications* 16, 1994 ([HPW94]); and *Information
Systems* 22(6/7), 1997 ([HPW97]). A query, update and constraint language over
PSM, the Predicator Set Model. [HPW94] §3 describes a provisional tool, *Doolittle*, which draws
one schema in either ER or PSM/NIAM conventions. Its surface language, beside a ConQuer path:

    Political-entity having-as Air-force CONTAINING Squadron known-as Squadron-name '316'

`conquer/conquer-2026.md` lists what ConQuer-92 restricted away from it: updates with a
minimal-population semantics, the complex object types and the `CONTAINING` / `COMPRISING`
operators that walk them, constraints written in the language itself, and explicit universal
quantification.

**ConQuer-92.** H. A. Proper, *ConQuer-92 — The revised report on the conceptual query
language LISA-D*, Asymetrix Report 94-5, Asymetrix Research Laboratory, University of
Queensland, 1994; 87 pages, public since 2021 as
[arXiv:2105.11926](https://arxiv.org/abs/2105.11926). Its abstract names it *"the backbone of
InfoAssistant's query facilities"*. It contains the grammar of path expressions and of the
language in BNF (appendices A and B), an ORM formalisation, multisets, a multiset relational
algebra, a denotational semantics, verbalisation rules, parsing and ambiguity handling, and
normalisation — a compiler stack:

```
        ConQuer-92           <- concrete syntax, parsing, verbalisation
   Path Expression Queries   <- abstract language
 Multiset Relational Algebra <- semantics          --> SQL-92 (implementation)
          NULLs              <- multisets, populations
```

The report says *"The implementation of ConQuer-92 in SQL-92 will be treated in a separate
report"*; this project found no such report. The language is specified in public; a compiler
to SQL was not. Its twelve references cite ter Hofstede, Proper & van der Weide for LISA-D and
Halpin for ORM. Companion Asymetrix reports, all on arXiv: Query By Navigation (2105.09562),
Spider Queries (2105.10349), Point to Point Queries (2102.01411), Computer Supported Query
Formulation (2105.09009), and Proper & Halpin's Conceptual Schema Optimisation (2105.12647).

**ConQuer-I and ConQuer-II.** Three publications:

| Title | Authors | Venue | Year |
|---|---|---|---|
| ConQuer: A Conceptual Query Language | Bloesch & Halpin | ER'96, LNCS **1157**, pp. 121–133 | 1996 |
| Conceptual Queries using ConQuer–II | Bloesch & Halpin | ER'97, LNCS **1331**, pp. 113–126 | 1997 |
| Conceptual Queries | Halpin | *Database Newsletter* 26(2) | 1998 |

The 1998 item summarises ConQuer–II for practitioners. ER'96's acknowledgements thank Erik
Proper for *"formalizing an alternative version of the language and… suggesting the name
'ConQuer'"*, which gives the published order: **LISA-D → ConQuer-92 → ConQuer-I →
ConQuer-II**.

**ActiveQuery.** The ConQuer–II tool. Bloesch's *Journal of Conceptual Modeling* column of June
1998 describes how it shipped: *"Visio's Preferred Customer Edition of InfoModeler includes
the prototype tool ActiveQuery. ActiveQuery is an Excel add-in and an ActiveX control that
can be used to build English like database queries from your InfoModeler models."* Halpin's
*Object-Role Modeling: an overview* (orm.net/pdf/ORMwhitePaper.pdf) records its end:

> "In 1997, InfoModelers Inc. released a restricted version of a powerful ORM query tool,
> named 'ActiveQuery' … With the acquisition of InfoModelers by Visio Corporation, which in
> turn was acquired by Microsoft Corporation, the ActiveQuery product is no longer
> available."

**NORMA.** The current open-source ORM tool has no query capability a user can reach.
Internally it carries a `QueryBase`/`Subquery`/`QueryParameter` role-path algebra, used only
by derivation rules: no editor, no execution, and none of 114 sample `.orm` files uses it. ORM
2 Technical Report 1 (2005) planned *"ORM queries"* in a textual language.

**Constellation Query Language.** C. Heath, OTM 2009, and *A Simple Metamodel for Fact-Based
Queries*, OTM 2013; implemented in `activefacts-cql`, which executes multi-hop conceptual
joins as natural-language paths. Its SQL generation for queries is unfinished. Its query
verbaliser is set beside the report's §8 in §5 below.

**Role paths and datalog.** Curland, Halpin & Stirewalt, *A Role Calculus for ORM* (OTM 2009
Workshops, LNCS 5872, pp. 692–701), a role calculus to underpin textual languages for ORM, is
the published prior art for the role-path level this project lowers through (`model/model.md`
§0). It was followed by *Mapping ORM to Datalog: An Overview* (OTM 2010) and a *Logical Data
Modeling* series using **LogiQL**, *"a leading edge deductive database language based on
extended datalog"*, which supplies the recursion ConQuer–II lacked. McGill, Dillon & Stirewalt,
*Scalable analysis of conceptual data models* (ISSTA 2011), builds on **ORM⁻** (Smaragdakis,
Csallner & Subramanian), a subset of ORM that *"includes the vast majority of constraints used
in practice and, moreover, allows scalable analysis"* — the principled version of this
project's decision to consume only `uniqueness` and `mandatory` (`model/model.md` §2.4).

**Rel.** Aref et al., *Rel: A Programming Language for Relational Data*,
[arXiv:2504.10323](https://arxiv.org/abs/2504.10323), 2025:

> "Rel is also heavily influenced by the fact-based modeling paradigm, particularly by
> Object-Role Modeling (ORM) (Halpin and Morgan, 2008). Unlike traditional relational query
> languages, Rel is geared towards working with facts about abstract ORM-style
> attribute-free entities rather than records representing ER-style entities with
> attributes."

It answers the objection this project's emitter runs into: *"The ORM-inspired approach to data
modeling entails splitting data into many relations and performing many joins. This can be
done without sacrificing performance by embracing factorized representations and worst-case
optimal joins."* Its integrity constraints are the model for `conquer.py --constraints`.

## 2. What ConQuer-II could express, measured

The capability set, from all three ConQuer papers. ConQuer–II **has**:
aggregation (count/sum/avg/max/min), grouping via for-clauses, HAVING,
correlated subqueries of arbitrary complexity, named subqueries (= CTEs),
negation, `maybe` (left outer join), subtyping, arbitrary arithmetic
expressions, quantifiers, and query reuse as derived predicates.

It **lacks**, per the papers themselves: **ORDER BY and top-k** (never
mentioned in any of the three), user-level **set operations** (and/or give
*internal* union/intersection only), **recursion**, and **collection
types**.

| query model | BIRD dev | BIRD train | Spider |
|---|---|---|---|
| **ConQuer–II as published** | **57.1%** | **64.8%** | **69.3%** |
| + ORDER BY / LIMIT | 74.0% | 82.6% | 92.5% |
| + CAST / CASE / string functions | 95.3% | 99.6% | 92.5% |

**ConQuer–II expresses roughly two-thirds of these benchmarks as
published**, and 74–93% with ordering and top-k — which it omitted as
presentation concerns, not expressiveness limits.

Its own stated ceiling, ER'97: *"The main extension planned … is
recursive completeness. First-order languages like ConQuer–II lack the
expressive power of recursive languages."* Never delivered. And the 1998
article is blunt about the practical bound: *"ActiveQuery was designed to
translate ConQuer queries into a sequence of SQL statements on the back
end DBMS, and hence is limited in practice by the power of the chosen SQL
back end."*

## 3. A fact that might not be there

Should a projected role keep the rows that lack it? The report and ConQuer-II both answer, and
neither answers by inference.

**Proper, ConQuer-92 (1994).** §3 declines to define NULL semantics — *"we do not explicitly
concern ourselves with a proper definition of the semantics of NULL values … In practice we
will stick as much as possible to the standards dictated by SQL-92."* But the algebra itself
draws the line, at the operator level. Concatenation (§6.1) is a natural join over fact
populations: an absent fact has no row, so a traversal *requires* the fact. And in exactly two
places the report uses a **left outer join** — the ⟕ glyph, confirmed at
400 DPI: the `Where` selection (§6.4) and **confluence** (§6.5), the operator for gathering
side information onto a base path:

> `LIST Budget VIA g, Firstname of, Surname given to EACH Person working for Group g part of Department: 'CS'`

The base path is required; the gathered values are shown if present. The distinction is
*syntactic* — `EACH` separates what the query is about from what it wants displayed — and it
is the report's own answer to the question.

**Halpin & Bloesch, ConQuer-II (1996–97).** An explicit `maybe` keyword for the left outer
join (§2 above). Per role, every time, by the author.

**Bird (1997).** §2.3.6, *Functional Dependencies over Partial Information*, citing Codd that
FD theory *"was developed without considering missing db-values"* and building on Maier's
permissible completions. Optional roles are first-class in her IDL (Table 3.1). Constraints
rather than queries, but the same recognition that partial information is the normal case.

**What this project did with it.** `model/binding-sql92.md` §6.1a renders traversal as the
natural join it is — `IS NOT NULL` on an absorbed fact — which is faithful. Confluence was
refused until September 2026; it is now built (`conquer/lower.py`, `lower_confluence`), with
the outer join the report specifies. A proposal to infer the reading from use — outer when only
projected, inner when tested — was considered and set aside: both predecessors chose explicit
over inferred, and that is a considered choice, not an oversight. `OPTIONALLY` remains as the
per-role escape hatch, which is `maybe` by another name.

One restriction, stated plainly: the report's dangling-verb element (`Firstname of`) reads a
fact type from the *value's* side and needs an inverse reading to exist. Reverse-engineered
models carry only the forward reading, so on those the element is written from the junction
(`has Firstname`). Adding inverse readings is among the refinements Halpin's chapter 8 lists.

## 4. ConQuer-3, thirty-two years late

The 1994 report's own words: ConQuer-92 is LISA-D "restricted in the sense that certain
restrictions had to be made to ensure that the language can be implemented on top of
SQL-92 … The resulting language can later be extended further when SQL-3 can be used as a
target platform, leading to ConQuer-3. Using SQL-3 as the target platform will in
particular allow us to define recursive queries." SQLite has had recursive common table
expressions since 2014. This project lifted the restrictions the report itself marked as
temporary, and built the two sections it had specified but nobody had implemented:

| | in the report | built |
|---|---|---|
| §6.2 `UNITED WITH`, `INTERSECTED WITH`, `MINUS` over whole paths | defined | as the CCM's `SetExpr`; a compound `SELECT` |
| §6.9 macros | defined, "basically an abbreviation", non-recursive | by substitution at parse time; `--normalise` shows the expansion |
| §6.11 derivation rules: derived fact types `f(p:a,…) ::= P` and subtypes `t ::= P` | defined, with the `IFF` verbalisation | as rules in the model, walked like readings, emitted as CTEs, verbalised by FORML as `… IFF …` |
| recursion in a rule | deferred to ConQuer-3 | `WITH RECURSIVE` over the rule's `UNITED WITH`; the least fixpoint |
| `LIST e1, e2` of whole-query scalars | absent | added, `conquer/conquer-2026.md` §10 |

What this amounts to is the semantic layer the metric-layer vendors sell, in ORM's own
terms: a metric is a derived fact type with a reading, a rule, and a sentence. ConQuer-II's
"derived predicates" and Halpin's later LogiQL work are the same construct with a Datalog
semantics; the 1994 report gives it a relational one and, now, a fixpoint. Nothing here was
invented. What is still not built from LISA-D proper: power types (a set as an object), the
update language, and schema-level queries.

## 5. Verbalising a query: the report's §8 and its relatives

Four systems turn a query, or its compiled form, back into words. They differ in what they
read from, what they write, and what the words are *for*. This section sets them side by side
because `conquer/normalise.py` implements the first, `conquer/verbalise.py` the last, and the
two in between are the nearest prior work.

| | reads | writes | deterministic | aggregates | optional steps | for |
|---|---|---|---|---|---|---|
| **ConQuer-92 §8, `PVerb`** (Proper 1994) | path expression | normalised ConQuer | yes, rules [V1]–[V46] | [V29] `GROUPED BY` | [V33]-ish gathering | regenerating the text from the stored artifact |
| **CQL `verbalise_query`** (Heath, ActiveFacts, ≤2018) | query graph | English from readings | yes | none in the verbaliser | `raise "REVISIT: Need to emit 'maybe' here"` | reading a conceptual query aloud |
| **GBV-SQL** (Chen et al., arXiv 2509.12612, Sep 2025) | generated SQL | prose, by an LLM | no | whatever the LLM says | whatever the LLM says | a self-check the same LLM then judges |
| **`--explain`** (this project) | ConQuer AST | English from readings + findings | yes | named (`THE COUNT OF …`) | a RISK finding | telling an author what will silently go wrong |

FORML 2 (Halpin & Curland, ORM2-02, 2006) is not in the table because it verbalises
*constraints and fact types*, not queries; `model/forml.py` does that for the reverse-engineering
report. Its hyphen binding and modal forms are about the schema, and a query verbaliser reads
the schema's readings the same way whichever of the four it is.

### §8: text is a view of the path expression

Figure 1 of the report has two arrows between ConQuer-92 and the path-expression level:
parsing down and verbalisation up. §8 defines the second as

    PVerb : PathExpr × ℘(TP) × ℘(Attr × TP) → Σ+

over a path expression already normalised by §7.12's rules, with an environment `L` (the types
to the left, so a verbalisation cannot be ambiguous) and `T` (the typing of variables). §10
names the consequence: two languages, *"a non-ambiguous subset of ConQuer-92 which is used to
verbalise path-expressions in a normalised form"* and *"a more liberal ConQuer-92 language from
a user's point of view"*. The liberal one is what people type; the normalised one is what the
system says back. Nothing the user typed is stored; the path expression is.

`normalise.py` is this arrow from the lowered block (`model/model.md`'s CCM, this project's
path-expression level). What "normalised" comes to in practice is listed in `conquer/README.md`
under `--normalise`; the rules themselves are the report's §8. Two departures from the report
are worth recording:

- The report verbalises *before* denotations are expanded; the block has them expanded, so
  `Department: 'ENG'` comes back as `has Department has DepartmentCode: 'ENG'`. That is more
  explicit than [V2] would have produced, and it is the one place the normal form is longer
  than a user would write.
- `!x` ([V6], B.2) is what a unification with a node of the enclosing block becomes. The
  report has it as a denotation the user writes; here it is also what the compiler *says* when
  a correlated sub-query was written some other way.

The check that this is §8 and not a paraphrase is the round trip in
`conquer/tests/test_normalise.py`: 127 operator-suite queries and all 66 BIRD answers compile,
normalise, recompile to the same rows, and normalise again to the same text.

### CQL: the same idea, stopped at the same two places

Clifford Heath's ActiveFacts (`activefacts-cql`, Ruby, MIT) carries fact types with ordered
reading templates (`{0} serves in {1}`) and a `verbalise_query` (verbaliser.rb, line 671 in
the last revision, 2018-11-28) that walks a query graph and either *contracts* — emits `that`
plus the next reading with its first placeholder stripped, when the last noun phrase is that
placeholder — or conjoins with `and`, with `it is not the case that` for negation, adjectives,
role names and stable subscripts. It is the same arrow as §8, from a different intermediate
form, aimed at English rather than at a normal form of its own language.

It stops at exactly two constructs. Optional steps hit `raise "REVISIT: Need to emit 'maybe'
here"` (line 709 of the same file); aggregation has no handling in the verbaliser at all.
Those are, to the construct, the two additions ConQuer-II made over ConQuer-I (Halpin &
Bloesch 1996–97: `maybe` for the left outer join, and the group functions — see
§2 and §3 above). `normalise.py` covers both: `OPTIONALLY` for a step whose join is
outer, `THE COUNT OF x GROUPED BY … AS c` for a grouped aggregate and `THE AVERAGE v IN (…)`
for one over its own path.

What `normalise.py` does not attempt that CQL does: contraction into one running sentence,
and choosing among several readings of a fact type for the smoother join. A normal form wants
one step per fact type and the first reading, so neither applies to it; `--explain`'s English
would benefit from the first, and does not yet do it.

### GBV-SQL: the arrow without a model to read from

Chen et al. (2025) have an LLM paraphrase its own generated SQL back into a natural-language
description and have the same LLM judge that description against the original question —
"grounded back-verbalisation". No template, no published prompt, no code; because the
paraphrase step is itself unreliable they add a binary selector that also looks at execution
results. The abstract reports 63.23% execution accuracy on BIRD, +5.8 absolute over their
baseline; on a reading of the paper's ablation, the back-translation
step on its own accounts for about +1.4 of that and the selector for the rest (not
independently checked here).

The point of setting it beside §8 is that it is the same instinct — *read the compiled thing
back and compare it with what was meant* — done without a conceptual model, so the reading
back has to be done by the same fallible component that did the writing, and then judged by
it again. With a model, the reading back is a function: the readings are in the schema, the
path is in the block, and the verbaliser cannot mis-describe a join because it does not
describe anything it did not find. That is the whole difference between `--explain` finding
*"Satscore must actually have a SchoolClosedDate — rows where it is absent are dropped"* on
BIRD Q41 and a paraphrase that might or might not mention it. The cost is the model, which is
what `reverse/` exists to supply.

### `--explain` is not §8

`verbalise.py` walks the ConQuer AST, not the block, and writes English of its own wording
with findings attached (RISK / CAUTION / NOTE). It is the report's *idea* of reading the query
back, applied where it pays on a text-to-SQL workload: at the misreadings — a dropped optional
fact, a verb ambiguity resolved by taking the first reading, an aggregate over an entity type.
It now prints the §8 form too, under **Normalised**, so the two stand together: English for a
reader who does not know ConQuer, normalised ConQuer for one who wrote the query and wants to
see what the compiler made of it.
