# Findings

Every defect and result the experiments in `bench/` turned up, numbered in the order they were
found. The first ones came from the BIRD pilot (`pilot/`); later ones from every experiment
since. Recorded as the arms ran, and fixed only after scoring, so each run stays comparable.

1. **`--schema` prints the FORML binding hyphen.** The listing shows
   `Superhero has skin- Colour`, but the query form is `has skin Colour`; writing the hyphen
   is a parse error. Introduced by the rule-10 reading work earlier today. Affects every
   database with a ring or disambiguated reading (superhero, codebase_community,
   european_football_2, and any ring). Cost the ConQuer arm attempts.

2. **A denotation on an entity silently resolves against its reference scheme.**
   `Superpower: 'Death Touch'` compares against `SuperpowerId`, returns zero rows, and
   nothing warns. The author has to know to write
   `has Superpower has SuperpowerPowerName: 'Death Touch'`. Two arms hit this independently
   (superhero, student_club). This is a *quiet wrong answer* in a language whose selling
   point is that it does not produce them. `--explain` should flag a denotation whose
   reference scheme is a surrogate id.

3. **Compiler crash: `KeyError: 'calc13'`.** A `WHERE` sitting mid-path, before an
   `AND ALSO` carrying a grouped aggregate, raises a bare KeyError instead of a message.
   Reported on california_schools Q79. A crash is not a refusal; it needs a real error.

4. **A grouped aggregate that restates its path silently cross-joins.** Writing the
   aggregate branch as a fresh filtered path rather than reusing a bound variable produces
   two uncorrelated aliases, so every group gets the same total. It compiles, runs, and is
   wrong. Reported on student_club Q1404. The lowering has a `check_rooted` for the
   uncorrelated case; this shape slips past it.

5. **`THE AVERAGE x IN <path>` rejects an arithmetic expression as its target.** So
   "the average of (a - b)" cannot be written directly and has to be decomposed by
   linearity. Reported on california_schools Q28. `THE AVERAGE v IN (... AND ALSO (a - b)
   AS v)` is the form that works and the primer does not teach it.

6. **`THE COUNT OF <path> BUT NOT <path>` does not parse.** The Fr operators are available
   inside `LIST ... FROM` but not after an aggregate word, so "count the X that are not Y"
   has to be written as a difference of two counts. Reported on thrombosis_prediction Q1256.
   §6.2's Fr is an operator on paths and an aggregate takes a path, so this looks like a
   grammar oversight rather than a design decision.

7. **The `Examination` table is not in the model at all**, because it has no primary key and
   only one foreign key, so no derivation rule identifies it. It cost the ConQuer arm five of
   the ten thrombosis_prediction questions, recorded honestly as unanswerable. The modelled
   arm noticed the same hole from the other side: its FORML file verbalises Patient and
   Laboratory and says nothing about Examination. Population analysis can find the key
   `(ID, Examination Date)` from the data but by design only reports it.

8. **A table with no declared foreign keys loses its relationships entirely.**
   `debit_card_specializing.transactions_1k` declares none, so `Transactions1kCustomerID`
   became a plain value type rather than a role facing Customer, and three of that
   database's six questions could not be expressed at all. This is the prerequisite the
   reference note already names ("row 4 fails silently on databases without declared foreign
   keys"), now measured: it costs half the questions on an affected database. `--infer-fks`
   and the population analysis both exist and neither was used in the pilot, which used the
   default pipeline. Re-running that database with inference is the obvious next experiment.

9. **Independent scalar aggregates cannot be projected side by side.** "Give me A - B, B - C
   and C - A" needs three whole-query aggregates in one result row, and ConQuer has no
   multi-column projection without a shared FROM path. Reported on
   debit_card_specializing Q1481. Not on the conquer-2026 list; it should be.

10. **A foreign key that targets a unique column, not the primary key, is joined wrongly —
    silently.** `Player_Attributes.player_api_id REFERENCES Player(player_api_id)` compiles
    to `Player.id = Player_Attributes.player_api_id`. The catalogue records `ref_columns`
    correctly; the mapping ignores it and uses the target's identity instead. Rows come back,
    they are just the wrong rows: a player whose `id` happens to collide with somebody's
    `player_api_id` gets that stranger's attributes.

    **32 of the 105 declared foreign keys in the BIRD dev set do this** — every
    `Match`/`Player_Attributes`/`Team_Attributes` link in european_football_2, and the
    `uuid` links in card_games. It cost the ConQuer arm six of ten questions on
    european_football_2, where the agent diagnosed it correctly from `--sql-only` rather
    than trusting the rows.

    This is the worst defect the pilot found, because it is exactly the failure the project
    exists to prevent: a wrong join that nobody sees. It is a mapping bug, not a language
    one, and the direct-SQL arms were unaffected because they read the DDL themselves.

11. **Role names are not discoverable.** `--schema` lists types and readings, never role
    names, so Appendix B.2's `<role reference>` -- the only way to say which role of a ring
    fact type you mean -- cannot be found from the material a query author is given. The
    toxicology agent needed it to reach both atoms of a bond, tried about a dozen invented
    spellings, and gave up, recording the question as unanswerable. `ConnectedAtom` and
    `ConnectedAtomid2` would have worked and were never on screen. This is the cheapest fix
    on the list and it converts an "unanswerable" straight into an answer.

12. **`is of` cannot be disambiguated.** When two fact types connect the same pair of types
    (`PlayerAttribute` to `Player`, by api id and by fifa api id), the forward reading is now
    distinct after the rule-10 work, but the *inverse* is not: `is of` fails with "no fact
    type reads 'is of'" and there is no spelling that says which. Reported on the
    european_football_2 re-run. The inverse verb is synthesised in `Lexicon._inverse_of` and
    inherits nothing from the disambiguation; it should.

13. **`DISTINCT` plus an ordering on a value that is not projected gives wrong rows
    silently.** SQL's `SELECT DISTINCT` cannot order by a column outside the select list, and
    the emitter does not notice. Reported on the european_football_2 re-run.


# Status, after the fixes the pilot forced

| # | Defect | |
|---|---|---|
| 1 | schema listing prints the binding hyphen | **fixed** — `Index.verbalise` unbinds |
| 2 | denotation on an entity resolves against a surrogate id, silently | open |
| 3 | crash `KeyError: 'calc13'` with WHERE mid-path before a grouped aggregate | open |
| 4 | restated aggregate path cross-joins silently | open |
| 5 | `THE AVERAGE x IN <path>` rejects an expression target | open (the `AS` form works; primer should teach it) |
| 6 | `THE COUNT OF <path> BUT NOT …` does not parse | open |
| 7 | table with no primary key and one foreign key never modelled | **fixed** — rule 1c, identified by the whole row |
| 8 | table with no declared foreign keys loses its relationships | **fixed on request** — `--infer-fks` now applies rule 9 |
| 9 | independent scalar aggregates cannot be projected side by side | **fixed** — `LIST e1, e2` with no FROM, conquer-2026 §10 |
| 10 | foreign key to a unique column joined to the primary key | **fixed**, both directions, with tests |
| 11 | role names not discoverable | **fixed** — `--schema` lists them on any fact type where a type plays two roles |
| 12 | `is of` cannot be disambiguated | **fixed** — `has X` inverts to `is X of` |
| 13 | DISTINCT plus an ordering on an unprojected value | open |

# Found by the re-runs

14. **Rule 1c, first cut, dropped rows silently.** Identifying a keyless table by its whole
    row made every column part of the identifier, so entering `Examination` from `Patient`
    asserted every column non-null and returned 2 rows where the join has 70. The thrombosis
    re-run agent caught it by cross-checking against SQLite directly. **Fixed**: the row is
    identified by its rowid, registered in the mapping as a column (`isRowId`), and
    `conquer/tests/test_mapping.py` holds a NULL row to prove it.

15. **A correlated aggregate (`!x`) is emitted as an unindexed per-row subquery.** Three
    codebase_community answers that are probably right take longer than two minutes on
    40,000 users x 92,000 posts and are scored as loud failures. The compiler does not reorder
    a cheap equality ahead of the correlated scan and does not use a join for what is a
    GROUP BY. Open; the first real performance finding.


# Found by the FORML round

16. **Giving the ConQuer author the model in English does not help.** 66 against 70, agreeing
    on 89 of 100 questions; the whole difference is one agent typing numbers in place of three
    slow queries. The schema listing is already the model in the author's own vocabulary. For
    a SQL writer the full text is worth the same as the excerpt: 73 against 74, against 70 for
    DDL alone. Small, real, and not sensitive to how much of the model is shown.

17. **Rule 9 misses a key that points at a unique column.** `cards.setCode` references
    `sets.code`, which is unique but not the primary key (`id`), and the column name carries
    the table's name as a prefix. The name rule looks only at single primary keys, so
    `Card` still has no path to `Set` and two card_games questions stay unexpressible in
    every ConQuer arm. The extension is obvious -- a column named `<table><unique column>`
    of matching type -- and the same guess-and-report discipline applies.

18. **Stale material.** The schema listings for the databases not re-run in the gap round
    still print the binding hyphen (`has api- Player`); the european_football_2 FORML-arm
    agent lost an attempt to it. My omission in rebuilding `material/`, not the tool, which
    was fixed under finding 1.

19. **An agent may answer with the answer.** Three codebase_community entries in the FORML
    arm were literal values, not queries, after the queries timed out. The scorer refused
    them as parse errors, which is the right outcome; a run that scored on agent-reported
    results would have been fooled.

# After the LISA-D round (§6.2, §6.9, §6.11)

- **Q604, unexpressible in every arm, is now one derived fact type away.** `UserHasPostCount
  ::= LIST u, c FROM User u is owner of Post p AND ALSO THE COUNT OF p GROUPED BY u AS c`,
  then `LIST THE AVERAGE v IN User [has PostCount c] has UserUpVotes v WHERE c > 10, THE
  AVERAGE a IN User [has PostCount c] has UserAge a WHERE c > 10` matches the gold exactly.
  That is the query-as-source shape, done the ORM way: name the derived fact.
- **Finding 9's construct exposed a scoping bug**: two aggregates side by side that both
  bound `s` shared the binding, and the second reached into the first's block ("node has no
  anchor"). An aggregate's path now scopes its own names, as a subquery's does. Fixed with
  two operator cases.
- **Q1481, the other one, is two macros away.** `SegSum(seg) ::= THE SUM OF v IN (Yearmonth
  [...] has Customer [...] [has CustomerSegment s2] AND ALSO (IF s2 = seg THEN x ELSE 0) AS v)
  WHERE ...` and `N() ::= THE COUNT OF ...`, then `LIST (SegSum('SME') - SegSum('LAM')) / N(),
  ...` for the three differences in one row, matching the gold exactly -- including its
  quirk that an empty conditional sum is 0, which the scalar IF reproduces where a filtered
  SUM would give NULL. Sections 6.9, 6.3's IF and the side-by-side LIST, together.

# The no-evidence round (the semantic-layer experiment)

Three arms with the evidence withheld from the prompt: SQL from the DDL, ConQuer from the
listing, and ConQuer with the evidence encoded in the model by separate modeller agents as
derived fact types, subtypes and macros (`semantic/howto.md`). Result: 56, 54 and 62 of
100, against 70 and 70 with the evidence in the prompt; 11 gained and 3 lost between the
two ConQuer arms, 8 of the 11 by name of a definition. The write-up is in `pilot/README.md`.
The modellers and the query-writers between them found the defects below, nine of them in
the compiler.

20. **A boolean function as an `AND ALSO` conjunct was dropped.** `Atom [has AtomId i AND
    ALSO like(i, 'TR%_19')]` lowered `like()` as a calculation nothing read, and the count
    came back unfiltered -- a silent wrong answer. A boolean call in path position is now a
    condition on the block. **Fixed**, two operator cases.

21. **A derived subtype of a type identified by two columns could not be emitted.**
    Laboratory is (Patient, Date); every rule rooted at it failed with "expected a single
    column, got 2", and the thrombosis modeller fell back to path macros for ten terms. The
    virtual table behind a derived subtype now carries one column per identifying column of
    its supertype, and a composite instance is listed and ordered as all of them. **Fixed**,
    five cases in `test_derived.py`; the modeller re-encoded the ten as subtypes.

22. **Naming a subtype after a step did not narrow to it.** `Patient [is of
    AbnormalCRPLaboratory]` reused the Laboratory node the step reached, so every Laboratory
    counted -- and the same for a plain subtype, `Department [is of Manager]`. A subtype
    named at a node of its supertype is now a node of its own, joined on identity; the
    normaliser writes it back as the step's type. **Fixed**, three operator cases.

23. **`--schema` never said which types were subtypes.** Frpm and Satscore are Schools with
    the same CDSCode, which is the only path between them; the listing showed three
    unconnected entity types and the no-evidence agent gave up three of six questions. The
    listing now has a `Subtypes` section and says how to walk one both ways. **Fixed**; that
    batch re-run.

24. **A text literal against a numeric identifier matched nothing, silently.** `Superhero:
    'Copycat'` expands through Idf(Superhero), an integer; four agents lost attempts finding
    that out from empty rows. Refused now, with the filter that was meant: `Superhero [has
    SuperheroName: 'Copycat']`. **Fixed.**

25. **A lone node was refused as "joined to nothing".** `LIST e FROM Employee e` is one
    range, multiplied by nothing; the cartesian check (finding 6's fix) had no exception for
    it. **Fixed.**

26. **The operand of a group function stopped before `BUT NOT` and `AND ALSO`.** `THE COUNT
    OF Patient BUT NOT has PatientDescription` was parsed as (the count) BUT NOT (...) and
    refused as "a computed value"; three agents worked around it by subtracting counts. B.2
    says the operand is an information descriptor, Fr operators included; it is now, with
    arithmetic after it still belonging to the enclosing expression. **Fixed.**

27. **GROUPED BY took only a node the path reaches.** `GROUPED BY substr(d, 1, 4)` was
    refused, so the debit_card modeller could not say "per year" and encoded a total instead
    of an annual figure. A grouping key may now be a computed value, bound with AS or written
    in place -- MetricFlow's time dimension, in section 6.3's terms. **Fixed**, two cases plus
    the normaliser's round trip.

28. **The modellers' how-to showed two aggregates and no functions.** Seven of the eleven
    modellers reported MIN, MAX, AVG, LIKE and IS-NULL definitions as inexpressible, and were
    right about the document and wrong about the language: every one compiled once the
    syntax was shown. The how-to now lists the aggregates, the functions, `WHERE` inside a
    bracket and `BUT NOT has X`, and every modeller re-encoded. Finding 11's lesson again:
    what the author cannot see does not exist.

29. **Not reproduced.** The thrombosis agent reported `(A OR B) AND C` from two brackets'
    WHEREs emitted as `A OR (B AND C)`; the shape I could construct parenthesises correctly.
    Noted, not closed. Also open: no string concatenation function, so "full name" comes back
    as two columns where the gold concatenates; and the correlated aggregate of finding 15,
    which cost the codebase_community agent two queries it had to verify on an indexed copy.

30. **A grouped aggregate's `IN` path restating the head was a second range.** Primer
    example 19, `Employee [...] has Department d AND ALSO THE SUM OF s IN Employee has
    EmployeeSalary s GROUPED BY d`, lowered the restated `Employee` with no head, so the sum
    ran over a cross product: each department's figure was (its employees) × (every
    salary). Silently wrong; the student_club agent caught it from the numbers and the
    european_football_2 agent from a query that hung. Section 6.4's Fr says the operand
    continues from the head, and now it does when its path begins by naming the head's
    type; a path that starts elsewhere (`THE COUNT OF Atom [has Molecule m]`) is still its
    own range, correlated by what it names. **Fixed**, two operator cases; the "joined to
    nothing" refusal now fires only for a type that is not the head's.

31. **An `AND ALSO` operand starting at a bound variable was unified with the head.** `Driver
    ... is of Result r has ResultPoints p AND ALSO r has Race ...` joined results to results
    on resultId = driverId and returned nothing; the formula_1 agent read the SQL and worked
    round it. Fr applied blindly. An operand (or bracket) that begins at a bound variable is
    now anchored there; the normaliser writes an `and` so anchored as that node's filter and
    an `or`/`but not` as the operator from the variable's name. **Fixed**, two operator
    cases plus the round trip.

32. **A three-role reading with adjacent slots cannot be walked.** The formula_1 modeller
    wrote `{0} has full name {1} {2}`; a query walks verb part by verb part and there is no
    verb part between the slots, so `has full name DriverForename f DriverSurname s` does
    not parse. With a word between them (`... {1} and surname {2}`) it does. The how-to now
    says so and prefers binary fact types; the agent used the two underlying readings, which
    is what the definition was anyway.

33. **`THE COUNT OF DISTINCT <path>` counts the path's tail.** The thrombosis agent expected
    `THE COUNT OF DISTINCT Patient is of AbnormalCRPLaboratory` to count patients and got
    laboratory records: an unbracketed path's tail is the laboratory, and the count is of
    the tail, as section 6.6 has it and as `--explain`'s grain caution says. Not a defect;
    the bracket form `THE DISTINCT COUNT OF Patient [is of AbnormalCRPLaboratory]` is the
    one that means it. The primer's rule 4 could say this in one line.

34. **A derived subtype's virtual table could not meet a foreign key that references a
    non-identifier column.** card_games' `legalities.uuid` references `cards.uuid`, not
    `cards.id`; the CTE behind `UnknownPowerCard` carried only `id`, so `UnknownPowerCard is
    of Legality` joined uuid to id and returned nothing, and `Legality has UnknownPowerCard`
    equated the same pair. The agent read the SQL and wrote the filter inline. A derived
    subtype now ranges over its supertype's row, narrowed by a semijoin to its CTE, so every
    absorbed fact and foreign key of the supertype applies; and unifying a referencing
    anchor with a row of the referenced table compares the referenced columns. **Fixed**,
    two cases in `test_derived.py`; both directions now agree on card_games.

35. **A type-incompatible unification was emitted, not refused.** `Card ... AND ALSO Set
    [has SetCode: !csc]` continued from Card, so Set was unified with it and the SQL
    equated cards.id with sets.id, silently empty; `Set: !csc` equated an identifier with a
    value. Both are now refused with the correlation that was meant (`WHERE SOME Set [has
    SetCode: !csc]`). **Fixed**, three operator cases. The underlying gap is finding 17:
    Card and Set are unlinked in the model, which rule 9 does not yet see.

# The ablation round (12 Sep)

Eight arms, each adding one thing to the `conquer` arm (71 with the final compiler) or to
`conquer_noev` (54): two more writers (68, 68), an execution-consistency vote (71), a
selector agent (70), a verifier (73), Opus as the writer (76; SQL with Opus 74), and a
value-lookup tool without the evidence (57). The write-up is in `pilot/README.md`; the table
with the per-question flips is `python3 ablation.py`. Findings 19 (an agent answering with
the answer) and 15 (correlated-aggregate timeouts) recurred; 15 is now fixed (36).

36. **Finding 15, fixed: a correlated aggregate is decorrelated.** `THE COUNT OF Post [has
    owner User: !u]` was a scalar subquery re-run per user, (users × posts) work on a column
    with no index: Q604 and Q672 timed out at two minutes in three arms. When the inner
    block is tied to the enclosing row by equalities alone, the emitter now renders it as a
    grouped derived table over the correlation columns, `LEFT JOIN`ed on them, with
    `COALESCE(v, 0)` for a count; any other mention of the enclosing row falls back to the
    subquery. Q604's shape runs in 0.3 seconds and gives the same rows. Three operator
    cases, and the correlated-average case now compares rows rather than text.

37. **An aggregate over a grouped block whose argument is a group key counted one group's
    rows.** `THE COUNT OF d IN (Employee e has Department d AND ALSO THE COUNT OF e GROUPED
    BY d AS c WHERE c > 2)` was rendered `SELECT COUNT(d) ... GROUP BY d HAVING ...`, a
    per-group count of which the scalar subquery returns the first: 3 where the answer is
    1. The codebase_community verifier found it, four phrasings deep, and kept the slow
    correlated draft rather than a fast wrong one. Any aggregate over a grouped block is now
    a derived table, whatever its argument. **Fixed**, one operator case.

38. **Small things the run-3 writers reported, fixed:** `--explain` printed "ordered by None"
    for a computed sort key (`abs(s)`); and the normal form of a projected correlated
    aggregate inlined it in the LIST, where it does not parse -- it is now bound with AS in
    the body, which is how the author wrote it.

39. **A WHERE on a value bound inside a BUT NOT reached the emitter.** `Card BUT NOT has
    CardPower p WHERE p <> '*'` binds p inside the negated operand and tests it outside, where
    the SQL cannot see it; the emitter died with "node has no anchor", and two card_games
    writers (run 2 and Opus) reported it as "no way to say IS NULL". It is refused now, with
    the form that was meant: `BUT NOT (has CardPower p WHERE p <> '*')`, which the normal
    form also writes with the parentheses. **Fixed**, two operator cases.

40. **A bound objectified fact instance continued from after AND ALSO lost its continuation
    in the normal form and the explain text.** `has Assignment a has Project ... AND ALSO a
    has AssignmentHours h` compiled right (finding 31's anchoring), but `--normalise` wrote
    `has Project has ProjectName n` with no hours at all, and `--explain` stopped at "and
    also a has". The superhero selector distrusted a right candidate for it. The normal form
    now stops at the fact instance and hangs its own continuations on it as filters --
    `has Assignment [has AssignmentHours h] has Project ...` -- and the verbaliser carries a
    variable's type through a path that continues from it. **Fixed**, one operator case.

42. **The model never said which values a code takes, and nobody could see them.** Agents
    across every round probed with `LIST v FROM DISTINCT Type has ValueType v` to find out
    whether female was `F` or `Female`, whether the country was `CZE`, whether a date carried
    a time part, and which of two similarly named columns held `State Special Schools`. The
    CCM has carried ORM's value constraint all along and `derive.py` sets it from a declared
    CHECK, but BIRD's schemas declare none, so all eleven models carried zero. Measured: 206
    columns across the eleven have an enumerable domain, and 35 of the 100 questions have an
    evidence hint naming a value one would have listed. **Built**: rule 6b proposes a value
    domain from the population with the same evidence and significance discipline as the rest
    of Bird's Step 9, `--infer-domains` applies it, and `--schema` prints it. 150 domains
    across the eleven models, and the corpus regression confirms not one of the 1086 pilot
    queries changed its SQL, because a concept's restriction is documentation the emitter
    never reads. Finding 11's lesson for the third time: what the author cannot see does not
    exist.

41. **`[A OR OTHERWISE B]` meant A AND B.** The leftmost operand of an Fr chain was merged
    into the block before the rule that a disjunction may merge nothing was applied, so the
    first alternative became a hard filter and the second was AND-ed against it. The comment
    beside the rule says exactly why that is wrong; it guarded the operands after the first
    and not the first. Silent, and with the opposite answer. **Fixed**: an operand that only
    restricts is an alternative wherever it sits in the chain, and where it establishes the
    head or binds a name it is still the path the alternatives restrict. Two operator cases.

    Found by `conquer/tests/test_metamorphic.py`, not by anyone thinking to write the case:
    inclusion and exclusion over generated filters said the union of two filters held fewer
    rows than either side. It had survived the whole pilot because no agent happened to put a
    disjunction inside a bracket, and the hand-written case for `OR OTHERWISE` puts it after
    a base path, which is the shape that works.

43. **The semantic-layer result was reported without its control, and the control changes
    it.** The round claimed that definitions in the model recover half of what withholding
    the evidence costs, and read that as a result about ConQuer. The missing arm is the one
    dbt's claim is actually about: the same definitions as English, in front of a SQL writer.
    It scores 64 against its own no-evidence baseline of 56 -- +8, the same as ConQuer's +8,
    two points higher in absolute terms and inside the noise band. Four questions are gained
    by both arms and by nothing else. The definitions do the work; the compiler does not.
    The write-up in `pilot/README.md` now says so. Two lessons: run the control before writing
    the claim down, and a result that flatters the thing being built deserves the control
    first, not last.

44. **The fan trap was never checked, and the model had always known how.** An aggregate in a
    block that also joins a one-to-many leg is computed over the multiplied rows: one
    department's budget summed once per employee. `--explain` cautioned about grain in
    general terms and nothing refused anything, and no agent in the pilot ever read the
    caution. Meanwhile all eleven reverse-engineered models carry ORM uniqueness constraints
    -- 865 of 1584 roles are functional to enter -- and **no line of the compiler read the
    `constraints` array at all**. Malloy's name for getting this right is aggregate
    locality; MetricFlow prevents the same thing by refusing to join into a `foreign` entity.
    **Built**: `Index.is_functional` and `Index.uniqueness` in `model/ccm.py`, and
    `check_aggregate_locality` in `lower.py`, which refuses a sum, average, count or list
    whose value the block repeats, and names `[...]` -- the semijoin ConQuer already had --
    as the fix.

    Two things the first version got wrong, both worth recording. Reading only *single-role*
    uniqueness refuses correct queries: crossing a many-to-many fans out, but a constraint
    spanning both roles of the associative fact type means one row per pair, so the count is
    right. The test has to be "is this fact instance pinned by values the group already
    fixes", run to a fixed point. The false positive was found by the metamorphic laws
    within a minute of the check going in, which is the second time that file has caught
    something no case would have. And the measured payoff is smaller than the pitch: across
    the 616 distinct pilot queries, 337 blocks hold an aggregate, 30 of those also enter a
    fan-out role, and **none of them trips the check** -- the corpus is unchanged, character
    for character. The fan trap is real, cheap to refuse, and rare in this corpus, because
    `[...]` and the sub-block promotion of an operand that binds nothing already cover most
    shapes an author writes.

45. **§6.5 was flattened for SQL-92's sake and nothing had revisited it.** The report says
    so outright: "since SQL-92 is not able to deal with nested relations, we have changed
    the definition slightly as opposed to the one used in [HPW93]". LISA-D's confluence
    returned a nested relation; the flattened version is an outer join, which does not gather
    an employee's two assignments onto the employee -- it turns the employee into two rows,
    and repeats every other gathered value and every aggregate beside them. So the operator
    whose whole job is "show it if it's there" was quietly multiplying the thing it gathered
    onto. **Built**: a side path the model allows to be many per junction is gathered as a
    nested relation again (`json_group_array`, one row per junction, the empty bag where
    absent); one that is at most one per junction is flattened exactly as before. The same
    functionality test as finding 44, pointed at the other place rows get multiplied.

    It needed no new machinery in the emitter, which is the useful part: a nest is an
    aggregate over a block, and aggregates over blocks already decorrelate into a grouped
    derived table. What it needed was a group function whose result is a bag. `THE LIST OF`
    is that, it is what a nested element reads back as under `--normalise`, and because a bag
    is the only result an order or a cut means anything to, it carries its own `ORDERED WITH
    ... THE FIRST n` -- which is top-n-per-group without a window function, and the shape
    Spider 2.0 asks for over and over.

The next four came from the Spider 2.0 trial (`spider2-trial/`), which reverse engineered
eight of that benchmark's local SQLite databases and pointed the metamorphic laws at five of
them. Every one is a silent wrong answer, and not one was reachable from the company fixture
or from BIRD -- which is the argument for a second corpus, not for more tests on the first.

46. **A schema could shadow the language's keywords.** Reverse engineering reads an n-ary
    associative table as `{0} has {1} and {2}`, which contributes **`and`** as the verb part
    between slots 1 and 2. The parser tries a verb before a keyword, so `... has RaceName v
    AND ALSO ...` consumed the `AND` as a step and refused at `ALSO`. Every f1 query with an
    `AND ALSO` in it, and f1 has five such tables. **Fixed** in two places, because fixing
    only the first would have been a regression: a verb part that is exactly a keyword phrase
    is no longer registered (`Lexicon._add_verb`), and the generated reading now gives each
    further role a verb part of its own carrying the role's label -- `{0} has {1} and has
    constructor- {2}` -- which also removes a pre-existing ambiguity on any table with four
    keys, where every role past the second had the same verb part as the one before it.

47. **A column with no declared type was called text, and every filter on it matched nothing.**
    SQLite lets a column be created with no type at all and several of Spider 2.0's databases
    do. `conceptual_type` had nothing to read and fell back to text; `--infer-domains` then
    mined the values and stored them as strings; `--schema` printed `DriveId '1'`; and
    `Drive has DriveId: '1'` compared a string with an integer in a column with no affinity
    to convert either. Zero rows, no error, no warning. **Fixed**: rule 6c reads the type off
    the population where -- and only where -- the catalogue declares none (`Column.declared`
    now distinguishes "declared TEXT" from "declared nothing"), and a domain mined from a
    numeric column is stored as numbers. 15 columns in f1 alone; none in any BIRD model,
    which is why it had never shown.

48. **A bracket leaked its disjunction across the bracket before it.** `Employee [has
    Department: 'ENG'] [has EmployeeGender: 'M' OR OTHERWISE has EmployeeGender: 'F']`
    returned every employee: `((ENG AND M) OR F)`. `binds_nothing` had no case for `Binary`,
    so it fell through to False, and a bracket that binds nothing but contains an Fr chain
    took the branch that lowers an operand into the *enclosing* block -- where its
    alternatives became siblings of the earlier bracket's sub-block and the fold ran across
    both. Finding 41 is the same defect one level out; this is the half it did not reach.
    **Fixed**: an Fr chain binds nothing when none of its operands does. 12 of the 1086
    corpus queries changed their SQL and none changed its answer. `--normalise` needed a
    change with it: the leftmost operand of a fold supplies the base and its operator is
    unread, so a block that is nothing *but* a fold was printing `[AND ALSO A OR OTHERWISE
    B]`, which does not parse.

49. **A calculation named from a block that cannot see it crashed the emitter.** `... AND ALSO
    days_between(r, d) * 24 AS hrs WHERE <disjunction> AND ALSO THE SUM OF hrs GROUPED BY n
    AS h` (Pagila, local039 as first written) put the aggregate under an EXISTS while `hrs`
    stayed outside, and `use_calc` raised a bare `KeyError: 'calc43'`. **Fixed** to the extent
    that matters: `use_calc` now looks through the enclosing blocks, which are in scope for a
    nested block exactly as their anchors are, and says so plainly when the value really is
    out of scope. Writing the `WHERE` after the aggregate instead compiles and answers the
    question. No fixture query reproduces the shape, so this one is pinned by the trial rather
    than by the suite.

50. **Nothing composed two grouped results, and §6.11 had been able to all along.** The
    Spider 2.0 trial's residue (`spider2-trial/`): `local210` wants February's and March's
    finished-order counts per hub compared, `local309` wants the top driver and the top
    constructor of each year on one row. Both are "a CTE joined to a CTE", and ConQuer had
    `THE FIRST n PER x` for either half, `THE LIST OF` for both as nested bags, and nothing
    for the join. Meanwhile §6.11's derivation rules name an intermediate *in the model* and
    the emitter has always rendered one as a common table expression -- including one whose
    body is grouped and limited, which nothing had ever tried. **Built**: `DEFINE <Name> ::=
    <query>` before the query, using §6.11's own `::=` with its left-hand side scoped to one
    query. The concept is shaped by what the definition lists (one thing a subtype, two or
    more a fact type read `has <Name>`, a computed column a value type of its own) and
    everything after that is the existing rule machinery. `local210` now matches gold exactly.

    The lesson is the one this file keeps recording from the other direction. Three defects
    earlier this week were things the compiler did that it should not; this is a thing it
    could do and nobody had asked it to. Before inventing a construct, check what the report
    already has: the whole change below the parser is a function that builds a concept.

    Two limits worth stating. The join key has to be a type the model has -- an intermediate
    hangs off the schema rather than floating free, so a key that is a computed value has
    nothing to hang on. And `local309` is still not expressible on that model, because
    `Race has Season` is ambiguous between `races` and the denormalised `races_ext`: rule 10
    reads an adjective off the foreign key to tell two *binary* fact types apart and
    `races_ext` is ternary, so it keeps the generic reading. The compiler refuses loudly and
    names both fact types, which is right, but the question cannot be asked. That is the next
    reverse-engineering job, not a language one.

51. **Spider 2.0's `local309` cannot be scored against its own artifacts.** The trial's last
    open question was whether the ConQuer answer for "the top driver and the top constructor
    of each year" was right, since it agreed with the recorded result on 73 of 75 years.
    Running the benchmark's **own gold SQL against the benchmark's own database** settles it:
    the shipped query reproduces none of the three result sets shipped for the task. Against
    `local309_a.csv` it differs on 8 of 75 rows; `_b` and `_c` have 74 rows where it produces
    75. The rows it differs on are 1958, 1964, 1965, 1970, 1972, 1973, 1974 and 1988 -- the
    seasons where the championship and the raw points total disagree, and the CSV holds the
    championship winner (Vanwall in 1958, Surtees in 1964) while the SQL sums points. The
    recorded answer was written by someone who knew the sport; the query was not.

    The ConQuer answer matches the shipped SQL on all 75 rows. So the compiler was right and
    the trial's own scoring was wrong, which is only visible because the benchmark ships the
    query as well as the answer -- BIRD ships one gold and there is nothing to cross-check.
    This is one measured instance of what Jin et al. (CIDR'26) put at 66% for Spider2.0-Snow,
    and the lesson for this bench is procedural: **when an answer disagrees with a recorded
    result, run the recorded query too before believing either.**

    `local029` fails the same test differently: its two accepted result sets disagree with
    *each other*. Both say customer `1b6c7548…` is third; `_a` records the average payment as
    137.0014 and `_b` as 119.8763. A task that accepts two mutually inconsistent answers
    cannot tell a right one from a wrong one, and it is not in `attempts.json` for that
    reason.


52. **Half the tables in a benchmark's databases declared no key, and rule 1 read nothing from
    any of them.** The Spider 2.0 survey: **223 of 412 tables declare neither a primary key
    nor a foreign key**, and sixteen of the thirty databases derived to zero concepts --
    northwind, Baseball, education_business, city_legislation and eleven more produced no
    model at all, so no question could be asked of them. Bird's Step 9 had been mining the
    candidate identifiers since it was written (`_unique`) and the report had been listing
    them; nothing ever applied one. **Built**: rule 9b, `--infer-keys`, which runs *before*
    the derivation because rule 9's name-based foreign keys need a target key to point at.
    Every database now derives something: 345 entity types across the thirty, and the blocked
    table count falls from 223 to 62.

    The discriminating signal was not the one I reached for first. "Is this column unique"
    is what the population answers, and it answers it wrongly as often as not: the fixture's
    `played.album_id` happens not to repeat, and taking it would assert the table is
    one-to-one with album. The question that separates a key from a reference is **"does this
    name point at another table"** -- `album_id` does, `collisions.case_id` does not -- which
    is rule 9's own signal read backwards. A column named for its own table
    (`categories.categoryid`) is the strongest form and the only one allowed past Bird's
    significance threshold, because there the *name* makes the claim and an eight-row lookup
    table only has to not refute it.

    Two smaller things fell out of the same survey. Rule 10 now separates two fact types that
    read alike using what the *table* name says beyond its two players, where the foreign key
    columns say the same thing -- f1's `races` and `races_ext` both read `Race has Season` and
    a query could reach neither, which is what made `local309` unaskable. And a view whose
    definition no longer resolves is skipped and reported rather than raising out of the
    catalogue reader: one such view in `oracle_sql` was costing all 38 of its tables.

    The residue is honest and stated: a table with no key whose data supports no *named*
    identifier stays blocked. Rule 9b will not invent an identity, and 62 tables is what that
    costs.

53. **The key and reference rules had never been scored, and scoring them was the whole
    improvement.** Rules 9b and 9c are guesses, and the only evidence they worked was that
    more tables derived. More tables is not better tables. The measurement that settles it
    was sitting in the benchmark all along: **a database that declares its keys is a labelled
    set.** Strip the declarations out of the catalogue, run the inference against the data
    alone, compare. `reverse/tests/test_inference.py` does that, and the literature reports
    the same way -- Jiang & Naumann's HoPF (JIIS 54:439-461, 2020) retrieves 88% of primary
    keys and 91% of foreign keys.

    Baseline on eleven Spider 2.0 schemas, 124 tables: **primary keys 75% recall / 96%
    precision, foreign keys 55% / 92%.** Every defect after that was found by reading the
    harness's output rather than by thinking:

    - `_unique` tested single columns and *one guessed* composite, so a composite key was
      found only by luck. Replaced with the level-wise minimal-UCC search the literature
      uses, bounded by a sound prune -- a combination whose column cardinalities multiply to
      less than the row count cannot be unique, so it is skipped without asking the database.
    - a column named exactly `id` scored **nothing**, because the suffix test required
      something before the suffix. Six tables in WWE, and `id` is the commonest key name there
      is.
    - `film_category.film_id` was read as "named after its own table" and taken as the key.
      An association is named after the things it associates, so "does this name point at
      *another* table" has to be asked first. Two false positives, both fixed by reordering
      two `if`s.
    - the association fallback was unreachable for the table it was written for: it hung off
      a loop over unique *findings*, and a table whose every column repeats has none.
    - a subtype's key is a reference -- `Faculty(StaffID, ...)` -- and rejecting it for that
      reason lost the key, and then lost the three references that would have pointed at it.
    - the scored inclusion findings, which have carried containment, coverage and Zhang et
      al.'s randomness test since they were written, **were reported and never applied**.
      Applying them is rule 9c, and it is worth 20 points of reference recall on its own.

    After: **primary keys 91% / 100%, foreign keys 75% / 97%.** Above HoPF on keys, below it
    on reference recall, above it on both precisions.

    Two things worth keeping from the exercise. **Precision against *declared* references
    understates precision**, because a schema's declared set is usually incomplete: six
    further proposals point at columns the schema declares nothing for, and
    `match_games.winningteamid -> teams` is an omission in BowlingLeague rather than a
    mistake here. They are counted apart. And **rule 9c changes the model rather than adding
    to it**: `tags.WikiPostId` stops being a value and becomes a reference to Post, which is
    truer and breaks every query written for the old shape -- 110 of the 1086 pilot queries
    changed and 17 stopped compiling. So it rides with `--infer-keys`, which is asked for,
    rather than with `--infer-fks`, which the BIRD pipeline passes. A migration is not a free
    upgrade.


54. **Asking what still blocks a table answered it, and found one more inconsistency of my
    own.** After rule 9b, 39 of Spider 2.0's 451 tables still derived to nothing. Counting
    them rather than guessing: **14 hold literally duplicate rows**, so no key exists at any
    arity and no search would ever find one -- `modern_data.trees` has 690,626 rows and
    683,788 distinct. Ten are under Bird's significance threshold (4 to 30 rows). Two are
    empty. The rest had a candidate the scoring rejected, and reading *why* found the defect:

    `_key_score`'s leading-columns test read the column's **declared** nullability while the
    candidate filter four lines above read the **observed** one. A schema that declares no key
    usually declares no NOT NULL either, so on exactly the schemas the rule exists for it
    could never fire. `education_business.StaffHours`, `Baseball.postseason` and
    `complex_oracle.currency` all have their key columns nullable on paper and never null in
    fact. That was an inconsistency, not a policy. Also added: an identifier may be spelled as
    a *prefix* -- `city_legislation.legislators.id_bioguide` -- which the suffix test could
    not see.

    39 blocked -> 32, 368 entity types -> 375, and the labelled measurement did not move:
    still 91% key recall at 100% precision. That last part is the point of having it -- a
    recall change that costs no precision is the only kind worth taking, and without the
    harness there would have been no way to know which kind this was.

55. **Before scoring against a benchmark, score the benchmark against itself.** The question
    was whether to re-run BIRD or Spider 2.0. Answering it needed one measurement neither
    benchmark publishes: run each **shipped gold query** against the **shipped database** and
    grade it with the **shipped evaluator**. `bench/spider2-trial/calibrate.py` does that, and
    of the 24 local tasks that ship their SQL, **it reproduces the shipped answer for 14 and
    fails for 9**. Nine of twenty-three gradable tasks cannot tell a right answer from a
    wrong one. The other 111 ship an answer and no query, so nothing can check them.

    Two of the nine are tasks the ConQuer attempts *pass*: `local131` and `local210` score 1
    under the benchmark's own evaluator while the benchmark's own gold scores 0.

    Getting this right needed a correction of my own first. `try.py` had been scoring with a
    multiset-of-rows comparison I wrote, and Spider 2.0's `compare_pandas_table` is
    **column-wise**: every gold column must appear somewhere in the prediction, matched within
    1e-2, extra predicted columns ignored, row order required unless the task's `ignore_order`
    says otherwise. Mine was stricter in one direction and looser in the other and agreed with
    theirs by luck. My first calibration run used my rule and reported 43%; theirs reports 39%
    on the same data, and the difference is exactly the point -- **scoring by a rule of one's
    own is scoring a different benchmark**. `try.py` now lifts theirs out of `evaluate.py`,
    which needs doing by hand because that module imports BigQuery and Snowflake clients at
    module level and the offline slice needs neither.

56. **Two benchmark questions answered by arithmetic rather than by running anything.**

    *Is the full BIRD run worth it?* The pilot's arms are **paired** -- same hundred
    questions, so the statistic is McNemar's on the discordant pairs, not an independent
    confidence interval. Computed from `results.json`:

    | | | discordant | p |
    |---|---|---|---|
    | direct 70 v conquer 71 | | 5 v 6 | **1.00** |
    | direct_opus 74 v conquer_opus 76 | | 1 v 3 | 0.62 |
    | direct 70 v **modelled 74** | | 1 v 5 | 0.22 |

    Only 11 of 100 questions discriminate direct from conquer at all. At that discordance
    rate, resolving a one-point true difference needs of the order of **1,500 questions** --
    three times the whole of mini-dev. So running the remaining 400 would not settle
    ConQuer v SQL and nothing should be spent on it for that reason. It *would* settle the
    one comparison with a real effect: `modelled` (+4, 1 v 5 discordant) reaches significance
    at five times the sample. That is the arm worth the money, and it is a question about the
    conceptual model rather than about the language.

    *What will LiveSQLBench cost?* Probed the public dataset directly rather than the paper.
    270 records over 18 databases, and the blockers are structural:

    - **90 of the 270 are Management (CRUD)** tasks. ConQuer-92 is a query language with no
      update sublanguage -- LISA-D had one, §6 of the report does not -- so a third of the
      benchmark is not merely hard but inexpressible. The comparable number is 180.
    - **`sol_sql`, `external_knowledge` and `test_cases` are empty in all 270.** The gold is
      withheld and released by email. Nothing can be scored offline until that is granted,
      and `external_knowledge` being withheld matters on its own: BIRD's evidence was worth
      14 points, and these tasks are built to need theirs.
    - Of the 180 Query tasks, **31% ask for a rank or a top-N per group** (which `THE FIRST n
      PER x` covers) and **20% mention recursion or a hierarchy** (which §6.11's recursive
      derivation rules cover, and which `DEFINE` now makes query-local). Those are the two
      things this compiler acquired most recently, which is either encouraging or a warning
      about reading a benchmark one hopes to do well on.
    - Median and percentile appear in 6. ConQuer's group functions are count, sum, min, max,
      avg and list; there is no median, and no ordering inside an aggregate to build one.

    So the probe's answer is: buildable today (the template databases are public), scoreable
    only after an email, and a third of it out of scope by construction.

57. **Whether refusals help an LLM is measurable, and the pilot half-measured it by
    accident.** The claim has been architectural all along: the compiler refuses queries that
    are well formed and meaningless, and that is supposed to turn a silent wrong answer into
    a correction. It splits into two claims that need different evidence.

    **(a) Does a refusal catch a query that would have been wrong?** Measurable with no agents
    at all, and now instrumented: `--permissive` records each judgement instead of raising and
    emits the SQL anyway, so the counterfactual can be run. On the fixture's fan trap it
    returns `ENG 7200000` where the answer is 2,400,000 -- the budget times the headcount.
    `test_errors.py` now asserts that every judgement refusal is suppressible, because a
    refusal that cannot be suppressed is one whose cost can never be measured.

    **(b) Does the author recover?** Needs a writer. But `results.json` already carries
    `attempts`, and splitting each arm on it is suggestive:

    | arm | first attempt | after iterating |
    |---|---|---|
    | direct | 61/76 (80%) | 9/24 (**38%**) |
    | conquer | 50/65 (77%) | 21/35 (**60%**) |
    | direct_opus | 53/62 (85%) | 21/38 (55%) |
    | conquer_opus | 48/57 (84%) | 28/43 (65%) |

    ConQuer is slightly *worse* on the first attempt and much better at recovering, and the
    two cancel to the 70 v 71 tie. That is the signature the refusal hypothesis predicts --
    harder to write, tells you when you are wrong -- and it holds at both writer strengths.
    It is **not significant**: Fisher on the recovery rates gives **p = 0.115**, and
    `attempts` conflates a refusal with a syntax error and with "I ran it and disliked the
    rows", so even a significant result would not isolate refusals.

    **The experiment that would settle it** needs one arm, not two. Re-run `conquer` with the
    `try` script logging *every* attempt rather than the last; then for each logged attempt
    the compiler refused, recompile it with `--permissive`, run it, and compare with the gold.
    Every refusal is then a data point for (a) -- no power problem, unlike an end-to-end
    ablation -- and the recovery split on the same run gives (b). Cost: one arm, 100
    questions, a tenth of the original pilot. The instrument is built; the run is not.

58. **Ran the refusal experiment. The refusals that are the argument for the language never
    fired once.** The `conquer_logged` arm: the same hundred questions, the same prompt and
    primer, a fresh writer per database, and a `try` script that records every query tried
    rather than only the one kept. Then `refusals.py` replays each refused attempt under
    `--permissive` and runs the SQL it would have produced.

    | | |
    |---|---|
    | attempts logged | **143** |
    | compiled | 136 |
    | refused | **7** |
    | of those, a *judgement* -- the fan trap, an impossible unification, a node joined to nothing | **0** |

    All seven were parse-level: unconsumed input (4), an ambiguous verb, a name not in the
    schema, a malformed aggregate. Not one was a claim about *meaning*. The arm scored 73,
    against `conquer`'s 71 and `direct`'s 70, so the writers were not unusually good or bad.

    The instrument is not broken, which I checked before believing the null: a planted fan
    trap is classified, replayed and judged `would have been WRONG` end to end. And this is
    now the **third** independent measurement agreeing -- the locality check fires on 0 of the
    1086 corpus queries, on 0 generated by the metamorphic laws, and now on 0 of 143 real
    authoring attempts.

    **The observation that matters more than the count.** The superhero writer's third
    attempt was a genuine fan trap: `Superhero has SuperheroName n AND ALSO has HeroAttribute
    has HeroAttributeAttributeValue v AND ALSO has Attribute has AttributeName: 'Speed'`. It
    **compiled cleanly** and returned 3,738 rows where the right shape returns 623 -- a
    six-fold multiplication of every name and value. The author caught it by reading the row
    count and rewrote it. The compiler said nothing, because `check_aggregate_locality`
    guards *aggregates* and this multiplies a *projection*. The one fan trap that actually
    occurred in a hundred questions is the case the check does not cover.

    So the honest conclusion is the opposite of the architectural claim: **what helps the
    author is the loop -- run it, look at the rows -- and not the refusals.** The refusals
    that fire are the ones a SQL parser would also give. The judgements that were supposed to
    be the difference are, on this corpus, unreachable.

    Two pieces of work follow, and neither should be done without deciding it is worth it.
    The locality check should cover a projection and not only an aggregate, which is the
    defect this run found. And if it did, the experiment would have to be re-run to find out
    whether that changes the answer -- one fan trap in 143 attempts is not a rate that would
    move a score.

59. **The key-inference numbers were corpus-specific, and nobody wrote down the corpus.**
    Finding 44 recorded 91% / 100% for keys and 75% / 97% for references over "eleven Spider
    2.0 schemas, 124 tables". Re-running the same harness while preparing this repository for
    publication, on the code as it stands and on the code as it stood at that commit, gives
    the same answer as each other and a different answer from the record:

    | corpus | primary keys | foreign keys |
    |---|---|---|
    | BIRD mini-dev, 11 databases, 75 tables | 94% R, 97% P | 53% R, 100% P |
    | Spider 2.0, 11 key-declaring schemas, 156 tables | 83% R, 98% P | 53% R, 96% P |

    Both commits agree to the point, so nothing regressed: the earlier run was over a
    different, easier eleven, and which eleven was never recorded. The inference leans on
    naming convention, so a corpus of conventionally-named schemas scores twenty points higher
    than one with `oracle_sql` in it.

    The lesson is the same one finding 43 taught about controls, in a different costume: **a
    measurement without its corpus is not a measurement.** Every quotation of these numbers in
    the repository now names the corpus and the command, and `test_inference.py` prints the
    per-database table so the spread is visible rather than averaged away.

60. **Provable `DISTINCT` removal: correct, sound, and worth 2%.** The model knows something
    a planner cannot: a block's rows are instances of the thing it ranges over, a join
    multiplies only where a role is not functional, and an `exit` never does. So when every
    `enter` is functional and the root's own identity is projected, no two rows can be equal
    and `SELECT DISTINCT` is a sort for nothing. `lower_rules` marks every derivation-rule
    body distinct because a fact population is a set, and **88 of the 94 derived concepts in
    the eleven semantic models cannot produce a duplicate in the first place.**

    Measured before building, which mattered twice. The first measurement said the rule fires
    on **zero** of 685 corpus queries -- and the diagnosis was right: of 90 DISTINCT blocks,
    53 are user-written `DISTINCT` over a value reached from a fanning-out root, where it is
    doing exactly the work it was asked to do. The measurement had a hole, though: it walked
    query blocks and never rule bodies, which is where every removable one lives.

    | | |
    |---|---|
    | corpus queries whose SQL changed | 43 of 1186 |
    | of those, rows identical | 42 |
    | rows "moved" | 1 -- an `AVG` differing in the 14th decimal place |
    | 88 CTE bodies, with DISTINCT | 0.946s |
    | the same, without | 0.925s |

    So it is **2.2% on the thing it directly affects**, and nothing measurable end to end on
    BIRD-sized tables. Kept for the SQL being honest rather than for the speed, and this entry
    exists so nobody cites it as an optimisation win.

    Two things worth carrying away. The one "moved" answer was floating-point summation order:
    removing DISTINCT changed the plan, which changed the order rows reached `AVG`. **`corpus.py
    --rows` compares rows by exact equality, so any plan-affecting change shows phantom moves
    on float aggregates.** And the first measurement's hole is the general lesson: a predicate
    measured over the wrong population reports zero just as confidently as a predicate that is
    wrong.

61. **Asked where the missed references went, and recall moved 53% to 81%.** Foreign-key
    recall was the weakest number this project reports and "53%" says nothing about what to do
    next. `test_inference.py --why` classifies every declared reference the inference does not
    recover, and the classification turned out to be the whole answer:

    | 104 declared foreign keys, 49 missed | |
    |---|---|
    | contained, but the search never offered that target | **29** |
    | containment does not hold: the declared reference is violated by its own data | 9 |
    | too few rows for the population to be evidence | 6 |
    | preferred and significant, and still not applied | 3 |
    | lost to a better-scoring target; target kept no key | 1 + 1 |

    The 29 have one cause. A reference points at *a* key, not at the one rule 9b chose to be
    primary, and `_unique` skips a table that already has one -- so once `apply_keys` keyed
    `cards` on `id`, every reference to `cards.uuid` became invisible, because no target was
    ever offered. The first pass's unique findings are now carried into the inclusion search
    as targets.

    **Foreign keys: recall 53% -> 81%, precision 100% either way** (55 of 104, then 84). Keys
    unchanged at 94% / 97%. No benchmark model changes: rebuilding one is byte-identical.

    What is left is mostly ceiling. **Nine of the twenty are references the data refutes** --
    the schema declares them and the values are not there -- which no data-based method can
    recover, and which `_violations` has been reporting all along at a rate of 28% in a Spider
    sample. Six are below the significance threshold, which is a dial. Three are
    `hero_attribute.hero_id -> superhero`: preferred, significant, and not *corroborated*,
    because `hero_id` is not the name of `superhero`. Corroboration is the signal measured at
    100% precision on its own, so loosening it to substrings is exactly the trade this project
    refuses to make blind.

    On Spider 2.0's eleven key-declaring schemas the same change takes references from 53% to
    **69% at 97% precision** -- `EU_soccer` alone goes 6% to 90% -- and leaves keys at 83% /
    98%. Two corpora, the same direction, no precision paid.

    The lesson is the one finding 44 taught about measurement, applied to a number rather than
    a claim: a rate with no decomposition is not actionable. Twenty minutes of classifying
    moved more than a week of scoring would have.

62. **Five more rules mined from the population, each with a decoy in the fixture.** The CCM
    carries seven constraint kinds and the derivation produced one; Step 9 mined seven finding
    kinds and proposed none of them as a constraint. After findings 61 and this one the
    reverse engineer reads twelve, and every rule added here has a *negative* case in
    `test_population.py` beside its positive one -- a shape that must not fire.

    | rule | what it reads | the decoy that must not fire |
    |---|---|---|
    | 9h | a column determined by a non-key column: an entity type nobody declared | a near-unique column, which determines everything and says nothing |
    | 9k | a parent column that equals an aggregate over a child table | a parent column that is not an aggregate of anything |
    | 9z | two columns always present together: an equality constraint | a column filled independently of them |
    | 5b | a unique combination rule 9b did not choose: an alternate key | the one it did choose |
    | 6d | one value domain held by two columns: one value type read twice | a domain only one column holds |

    The decoys are not decoration. Three of them are shapes that **did** fire before being
    guarded: `budget.remaining -> category` held on 52 real rows for no reason but that
    remaining is a decimal, `person.given = family || ' ' || full_name` held because SQLite
    coerces text to 0 in arithmetic, and `Charter School (Y/N) <= District Code` was one of 49
    value comparisons proposed on california_schools before the pairing rule. A miner that has
    never been shown a near miss has not been tested.

    On real schemas the yield is small and the hit rate is high, which is the trade this
    project wants: `zip_code (state -> short_state)` in student_club is the textbook hidden
    fact type -- "California" determines "CA", and rule 2 would otherwise hang both off the zip
    code as independent properties. `satscores (AvgScrRead, AvgScrMath)` is a real equality: a
    school either has SAT data or it does not.

    9k proposed nothing on three BIRD schemas. That is the honest result for a rule aimed at
    the one artefact the benchmark measured as worth eight points -- stored aggregates are
    common in warehouses and rare in these eleven databases -- and it is reported here rather
    than left unmentioned.

63. **The weekend's work did not move Spider 2.0, and made one recorded attempt stop
    compiling.** Asked directly: with the improved key and reference inference (finding 61),
    the six Spider 2.0 local tasks the trial covers still score **5 of 6**, and the sixth is
    `local309`, which `calibrate.py` already classified as unscoreable -- its shipped CSV holds
    championship winners and its shipped SQL sums points.

    What did change is the model, and it broke the query. Rebuilt with the better inference,
    f1 no longer has a value type called `ConstructorName`: rule 9c reads `constructors.name`
    as a *reference* to another table, so the name is now an entity, `ConstructorsExt`, reached
    by a qualified verb. The recorded attempt failed with *"'has' from Constructor is ambiguous
    between ConstructorHasId, ConstructorHasNationality, ConstructorHasUrl and none of them
    reaches ConstructorsExt"*. The compiler's own message named the four ways to reach it and
    the repair was one phrase -- `has name ConstructorsExt has ConstructorsExtName` -- after
    which the query returns the same 75 rows as before.

    That is the third time this has happened, and it is the same lesson each time: **a better
    model is a migration, not a free upgrade.** Rule 9c broke 110 of 1086 pilot queries when it
    landed (17 fatally); the same rule broke this one; and the reason is always that the model
    got *truer* -- a value became a reference, and every query written for the old shape was
    written against a schema that was wrong.

    Two things follow for anyone shipping this. The inference flags have to be part of the
    model's identity, because a query is written against a model derived with particular flags
    and is not portable to another. And the error messages carry the repair: this one named
    every reading that reaches the type, which is what made the fix a single edit rather than a
    re-derivation.

64. **Schema linking over the model: 94% of gold tables kept, 27% of the model.** The one
    lever every system at the front of the leaderboards pulls, and the first thing in this
    project aimed at it. `conquer/link.py` scores a model's concepts against a question by
    token overlap, matches quoted literals against the value domains rule 6b puts on the value
    types, connects the seeds through the fact types that lie between them, and keeps whatever
    identifies what survives. Nothing learned, nothing fetched.

    Measured against the tables BIRD's gold SQL touches, over all 500 mini-dev questions:

    | setting | every gold table kept | of the model kept |
    |---|---|---|
    | 20 seeds, no hop | 67% | 8% |
    | 40 seeds, no hop | **94%** | **27%** |
    | 20 seeds, one hop | 98% | 69% |

    **More seeds beats more hops**, which is the part worth carrying away: a hop takes
    everything adjacent, a seed is a word the question used. At the same 92% recall, twenty
    seeds and no hop keep 24% of the model where three seeds and one hop keep 31%.

    Two process notes, both of which cost more than the tuning did.

    *The tokeniser did not split camelCase.* `IncomeAmount` became one token and matched no
    question ever asked, so student_club returned **no seeds at all** for two thirds of its
    questions. Fixing it moved recall 87% -> 97% on the tuning subset. The stemmer had the
    same class of bug: `employees` stemmed to `employe` while `Employee` stemmed to itself.
    Neither was findable by tuning, and both were found by printing the seeds for one failing
    question.

    *The tuning subset lied.* The first 120 questions cover three of the eleven databases, and
    said the knee was at twenty seeds. Over all 500 it is at forty: 67% against 94% for the
    same setting. This is finding 59's lesson again -- a measurement without its corpus is not
    a measurement -- now with the corpus being a *prefix* rather than a different benchmark.

65. **Naming moved into one place; it was the right change and bought no recall.** The reverse
    engineer has understood camelCase, snake_case, plurals and abbreviations since rule 10 --
    `words`, `singular`, `is_abbrev` -- and the schema linker written a day later grew its own
    splitter and its own stemmer, the second of which was wrong in a way the first is not. Both
    now import `model/names.py`, and a concept records what rule 10 decided in a new `terms`
    field: the column it was named from, that name's words, and the expansion of any
    abbreviation in it. `EmployeeName` carries `emp`, `emp_name`, `employee`, `name`.

    Two defects fell out of the move, both in the day-old code rather than the year-old code.
    The private stemmer took `employees` to `employe` while `Employee` stayed `Employee`.
    And `singular` is written for *table names*, where `has` never appears: on question text it
    takes `has` to `ha`, which escaped a stop list that was being applied before
    singularisation rather than on both sides, and then matched every fact type whose reading
    says "has".

    | over 500 BIRD questions, at 27% of the model kept | every gold table kept |
    |---|---|
    | the private splitter and stemmer | 94% |
    | `model/names.py`, models without terms | **95%** |
    | `model/names.py`, models with terms | 94% |

    So the shared singulariser is worth a point and **`terms` is worth nothing here**. At 40
    seeds it reads as +1 (95% to 96%) and that is bought with five points of compression: the
    same curve, further along it. The mechanism does work -- `test_linking.py` shows `emp`
    finding `Employee` and `emp_name` finding `EmployeeName`, neither of which matched before
    -- but BIRD's columns are mostly already spelled the way its questions are, so there is
    little for an expansion to recover. A schema of `emp_nr` and `dept_cd` is where it would
    pay, and this corpus is not one.

    Kept anyway, for the reason the duplication was worth removing: there is now one place
    where a schema's spelling conventions are understood, and the reverse engineer no longer
    computes an abbreviation expansion and throws it away. The 1,186-query corpus is unchanged
    by the rebuilt models.

66. **Table recall was the wrong measure for schema linking, and the right one says 75%.**
    Finding 64 reported that the linker keeps every table BIRD's gold SQL touches for 96% of
    questions while keeping under a third of the model. That is the metric the literature
    reports and it is a proxy. The 1,186 ConQuer queries the pilot wrote are a better one, and
    they are already here with the questions that produced them: prune the model by the
    question, then compile the query somebody actually wrote against it.

    | | still compiles |
    |---|---|
    | pruned, no attributes (32% of the model kept) | **75%** |
    | plus the anchors' own value facts (79% kept) | 87% |
    | plus every kept entity's value facts (80% kept) | 88% |

    **A quarter of real queries stop compiling** at the setting table recall was happy with,
    and the losses are all one shape: the query names a value type the question never did --
    `DistrictA3` for "east Bohemia", `CustomerSegment` for "SME", `SetIsForeignOnly`. A
    question names what it is *about* and almost never names the column it filters *by*. Table
    recall cannot see this, because the table is there and the column is missing.

    Putting the attributes back costs nearly all the compression: on these models the concepts
    *are* mostly value types hanging off seven or eight entities, so keeping any entity's
    attributes keeps most of the model. 32% -> 79%.

    That is the answer to whether schema linking is worth an arm on BIRD: **no.** At a safe
    setting it drops a fifth of the concepts and a third of the tables, and run-to-run noise is
    three points. The regime the leaderboards are talking about is Spider 2.0 -- 812 columns
    per database against BIRD's 54, f1 alone carrying 216 fact types -- where the whole schema
    does not fit in the prompt and pruning is not optional. That is where to measure next, and
    it can be measured the same two ways without an agent.

67. **Schema linking on Spider 2.0: the compression is real, the recall is worse, and the
    sample is 24.** Finding 66 said BIRD is the wrong regime to test the leaderboards'
    schema-linking claim -- seven tables a database, and the whole schema fits in the prompt
    anyway. Spider 2.0's local slice is the right one: 14 tables and 100 columns a database,
    and `f1` derives to 216 fact types. `linking.py --corpus spider2` scores the 24 local tasks
    that ship their gold SQL.

    | corpus | setting | every gold table kept | concepts kept | tables kept |
    |---|---|---|---|---|
    | BIRD, 500 questions | 40 seeds, no attributes | 96% | 32% | 71% |
    | BIRD | 40 seeds, anchors' attributes | 96% | 79% | 71% |
    | Spider 2.0, 24 tasks | 40 seeds, no attributes | 62% | 25% | 47% |
    | Spider 2.0 | **80 seeds, no attributes** | **79%** | **38%** | 58% |
    | Spider 2.0 | 120 seeds, anchors' attributes | 79% | 73% | 60% |

    Two things are true at once. The **compression is real where the claim says it should be**:
    a Spider model prunes to 38% of its concepts where a BIRD model has to keep 79% to stay
    usable, because a BIRD model is mostly value types hanging off seven entities and a Spider
    model is many entities. And the **recall is worse** -- 79% against 96% -- which is what
    "harder" means here: more tables to choose between, and questions that name none of them.

    Sufficiency, the measure that mattered on BIRD, says nothing yet: all six recorded ConQuer
    attempts still compile against the aggressively pruned model, including at `none`. Six is
    not a number. It is worth recording only because it is the opposite of BIRD's 75%, and the
    reason is visible -- BIRD's queries filter on value types the question never names, and
    these six do not.

    **Twenty-four tasks is the honest limit of this.** One task is four points; the difference
    between 62% and 79% is four tasks. What the measurement supports is a direction, not a
    number: the bigger the schema, the more there is to prune and the harder it is to prune it.
    Nothing here justifies an agent arm on either corpus yet.

68. **Diverse candidates: the prompts are worth five points, the diversity is worth nothing.**
    Finding 40 measured candidates-and-selection at zero and did it with *one prompt sampled
    three times*, which is the configuration CHASE-SQL says fails. So three more writers, on
    the same hundred questions, differing in **strategy**: divide and conquer (split the
    question, verify each part with `try`, compose last), plan-first (say what is measured,
    which types, which filters bracket and which join, what one row is — then write it), and
    self-made exemplars (build worked queries in *this* schema first, then adapt the closest).

    | trio | scores | all three right | none right | oracle | vote |
    |---|---|---|---|---|---|
    | one prompt, three times | 71, 68, 68 | 62 | 26 | 74 | 71 |
    | three strategies | **77, 76, 75** | 72 | 20 | **80** | 76 |

    **Every diverse arm beats every same-prompt arm**, and the weakest of them beats the base
    by four. `conquer_dc` at 77 edges `conquer_opus` at 76 -- a *prompt* matching a stronger
    model. Three independent runs all landing 4 to 6 above the base is better evidence than
    one arm at 77 would be, given three-point noise.

    It is not bought with attempts. `conquer_plan` averages **1.72** against the base arm's
    1.71 and scores 76; `conquer_shots` 1.69 and scores 75. Only `conquer_dc` spends more
    (2.73) and it buys one point over plan, which is inside noise. **Method, not iteration.**

    **And the mechanism the claim rests on is absent.** Diverse strategies were supposed to
    make complementary mistakes. They agree on **86 of 100** where the same-prompt trio agreed
    on 79 -- *more* redundant, not less. The selector's headroom is best-arm 77 against oracle
    80, which is **+3: exactly what it was before** (71 against 74). The execution-consistency
    vote scores 76, a point below simply taking the best arm.

    So the leaderboard result half transfers. Its ingredient -- write the plan first, decompose,
    build examples -- is the largest lever this project has measured short of changing the
    model. Its stated mechanism -- diversity creating complementarity for a selector to exploit
    -- does not appear at all: better strategies raised the floor rather than spreading the
    candidates, and there is no more for a selector to find than there was. `conquer_chase`,
    the selector arm, was scaffolded and is not worth running.

    Caveats. One run per arm. The three strategy prompts were written for this run and the
    recorded arms' prompt could not be recovered verbatim, so some of the gap may be prompt
    quality beyond strategy -- which would not change the conclusion that *how you ask* beats
    *how many times you ask*. And one database, card_games, stalled all three arms on slow
    queries and needed the same intervention each time.

69. **The English description of a model, said at a higher level: three times shorter, and the
    accuracy is not yet measured.**
    Finding 43's result is that the *definitions* are the asset -- the English description of
    the model is worth +3 to +4 to a SQL writer (`modelled` 73-74 against `direct` 70) and +8
    when it carries the evidence definitions. It is also the input that does not scale. The
    flat verbalisation is one sentence per elementary fact, all the same size: 55 KB across the
    eleven BIRD models, 18 KB for Spider 2.0's `Baseball` alone, and in it "Driver has
    DriverUrl" reads exactly as loudly as "Result is of Race".

    Bird's thesis chapter 5 is the algorithm for this, and it is *automatic* -- which is the
    thing she says the ER clustering literature could not do. Twelve rules weigh each fact type
    ROLE from the constraints around it (mandatory 10, unary 10, non-leaf 9, smallest maximum
    frequency 8 down to 2, non-value 7, anchor point 6, set constraints 5 to 1, first keyed
    role 1); the heaviest role anchors its fact type to a player; the object types carrying the
    most anchored weight are major; the next level is the fact types between major types, with
    everything dropped **clustered** under the type it was anchored to. Implemented in
    `model/abstract.py`, tested in `model/tests/test_abstract.py`.

    | | flat | level 2 |
    |---|---|---|
    | 11 BIRD models | 55 KB | **18 KB** |
    | `Baseball` (341 fact types) | 18 KB | **4.3 KB** |
    | `f1` (216) | 16 KB | 5.4 KB |
    | `EU_soccer` (199) | 11 KB | 4.3 KB |

    Two findings fell out of implementing it, neither of them about size:

    - **Rule 1 has to exclude implied mandatory roles or the whole thing inverts.** A value
      type's mandatory role is true by construction ("each CircuitId is of some Circuit"), so
      both roles of every value fact tie at 10, both anchor, and every column is as major as
      the entity it describes. `model/forml.py` already suppressed the same sentences for the
      same reason; the abstraction needed the same judgement to work at all.
    - **A schema with no declared foreign keys abstracts to nothing**, because there are no
      fact types *between* its major types to promote. `california_schools` goes 87 → 1. That
      is finding 8 in a new place, and it makes the ladder a diagnosis as well as a summary.

    **Measured, 15 Sep.** Four arms, two of them controls, because the first reading was wrong.

    | | DDL only | + flat English | + level-2 English |
    |---|---|---|---|
    | the original prompt | 70 | **73** | — |
    | the 15 Sep prompt | 68 | **70** | **68** |

    The first three arms said `modelled_abstract` 68 against `modelled` 74 and `modelled_full`
    73 -- six lost and none won, the most lopsided paired split in the project -- and the
    write-up would have been "shaping the English costs five points". It does not. The original
    arms' prompt could not be recovered verbatim, so the flat arm was **run again under the new
    prompt**: 70. Most of that gap was the prompt, not the material. Then the baseline again for
    the same reason: 68. The prompt is worth about two points wherever it is applied
    (70→68 on DDL, 73→70 on flat English), which is finding 68's lesson arriving on the SQL side.

    Against its proper control the abstraction is **-2 (4 lost, 2 won)**, inside the noise band.
    Against the DDL alone it is **exactly level: 68 and 68, four lost and four won**. That is
    the result worth keeping:

    - **The flat English is worth +2 to +3, and it reproduced.** 70→73 under one prompt,
      68→70 under another, both with the same asymmetric paired split (2/5 and 3/5). Finding 43
      survives a second prompt, which is more than most of this project's positive results have
      been asked to do.
    - **The abstraction gives a SQL writer nothing over the DDL.** It compresses three-fold and
      compresses away precisely what was helping.
    - For ConQuer it changes nothing either way: `conquer_abstract` 65 against `conquer_forml`
      66 (9 lost, 8 won), reproducing the existing finding that the English does nothing there.

    A mechanism worth testing, stated as the hypothesis it is: the flat verbalisation says
    "each X has at most one Y" for every fact type, so a SQL writer reads the cardinality of
    every join off it. The summary keeps optionality (`?`) and drops functionality. If that is
    the active ingredient, a summary carrying it should recover the two points -- and a flat
    verbalisation stripped of uniqueness sentences should lose them. Neither is run.

    The six questions lost in the first, uncontrolled comparison showed no mechanism at all:
    an INNER JOIN fanning out duplicate atoms, `AVG` against `SUM/COUNT` over a nullable
    column, an extra projected column. Ordinary SQL judgement, which is what a two-point
    difference looks like from close up, and what made the control necessary.

70. **Three crashes and a wrong refusal, all found by writers rather than by tests.**
    The 15 Sep round put 22 fresh writers against the compiler and they turned up four defects
    in a morning, none of which the 1,500-assertion suite had. Each is now a case in
    `test_operators.py`, reproduced on the company fixture first.

    - **A bare value type could not be aggregated.** `THE AVERAGE EmployeeSalary` raised
      `node n3 has no anchor` — a crash carrying an internal node id. A value type has no
      table of its own, but its population is by definition the values in its fact type, so
      the range is over the table that carries the role. **Fixed**; where two fact types carry
      the same value type the message now names them and says to walk a path instead.
    - **Projecting out of an alternative crashed the same way.** `LIST n, g FROM ... AND ALSO
      has X g OR OTHERWISE has Y` asks for a `g` on rows that arrived by the other branch.
      `OR OTHERWISE` folds its operands into sub-blocks and the projection escaped its scope.
      **Fixed** as a refusal that says so; a card_games writer had rewritten around it by
      De Morgan without ever learning what was wrong.
    - **A `WHERE` mid-path rooted the next branch at the wrong place.** The condition parser
      took the `AND` of `AND ALSO` as a boolean operator, so `... has DepartmentCode d WHERE
      d <> 'HR' AND ALSO THE COUNT OF e GROUPED BY d` continued from `d` instead of from the
      head and produced a confident, **wrong** refusal: "Employee and DepartmentCode cannot be
      the same thing". The query is correct ConQuer. A california_schools writer got past it
      only by moving the WHERE to the end. **Fixed**: a condition's atom is a comparison, and
      both orders now return the same rows. This is finding 3's shape a second time — that fix
      turned a crash into a message, and the message was false.
    - **The primer asserted a limitation that no longer existed.** It said two independent
      aggregates cannot sit side by side; `test_operators.py` has had a passing case for the
      opposite since the conquer-2026 work. Written from finding 9's status rather than from
      the tests. **Corrected**, and the working form is now a checked example.

    Nothing in the recorded corpus moved: 1,186 queries recompile byte-identical.

71. **The harness let one arm break another, and the benchmark corpus was modified.**
    `card_games` failed for every query in the `modelled_abstract` batch with
    `unable to open database file`. Cause: `conquer.py` opened the database with a plain
    `sqlite3.connect()`, which opens for **writing**; SQLite moved the file into WAL mode and
    left `-wal` and `-shm` beside it, and `sqlite3 -readonly` — what the SQL arms' `try` uses
    — cannot then open it at all, because read-only mode cannot create the `-shm` that WAL
    needs. Two arms sharing one corpus had never run concurrently before, so this had never
    fired. That writer spent a large part of its budget diagnosing a fault in the apparatus.

    **Fixed**: the compiler opens `file:...?mode=ro`. A query compiler has no business writing
    to the database it reads. `conquer/tests/test_readonly.py` now checks the invariant in
    the three ways it broke — no sidecars appear, the file is byte-for-byte untouched, and
    `sqlite3 -readonly` can still open it afterwards. The corpus was restored to `delete`
    journal mode.

    A second, smaller thing: three abandoned slow queries were still running as orphaned
    processes after their agents had finished and moved on, holding a lock on that database.
    An abandoned query needs a timeout, not just an agent that stops waiting for it.

72. **The abstraction is lossless for querying; what it drops is the cardinality sentences.**
    Finding 69 left an open question and an obvious objection. The question: *why* did the
    level-2 summary score nothing over the bare DDL? The objection: BIRD's schemas are 7 tables
    and its flat verbalisation is 5 KB, so perhaps there was nothing for a summary to help with,
    and the answer would differ on a large schema.

    The large-schema accuracy arm **was not run**, and the reason is worth recording. Spider
    2.0's local slice has 135 questions, of which the twelve largest databases (87 to 341 fact
    types) carry 60. Of those 60, **ten ship gold SQL and seven of those reproduce their own
    recorded answer**; the other fifty are graded against a CSV nothing can check, on a
    benchmark where 38% of the checkable answers are wrong (`calibrate.py`; Jin et al. put
    Spider2.0-Snow at 66%). Published baselines on this slice run 10-20%. Three arms over 60
    such questions would land within a question or two of each other, and the number would be
    noise wearing a result's clothes. `bench/spider2-trial/build.py` and `score.py` are written
    and the work directories exist; what is missing is a benchmark worth scoring against.

    What *is* sound on those schemas is coverage, because a gold query that cannot reproduce
    its recorded answer still names the right tables: the annotation problem does not reach
    this measurement. `abstraction_recall.py` walks the ladder and asks, per question, whether
    every table the gold touches is still present.

    | | level 1 | **level 2** | level 3 | level 4 |
    |---|---|---|---|---|
    | BIRD, 500 questions | 100% | **100%** | 83% | 61% |
    | Spider 2.0, 24 questions | 87% | **87%** | 45% | 25% |
    | fact types shown (BIRD) | 792 | **167** | 61 | 39 |
    | fact types shown (Spider) | 1624 | **436** | 148 | 120 |

    **Level 2 loses nothing.** Not on BIRD, where it keeps every gold table on all 500
    questions at a 4.7x compression, and not on the large schemas, where it scores exactly what
    the *whole model* scores -- the three Spider misses are tables the reverse engineer never
    derived, not tables the abstraction dropped. The ladder only becomes lossy at level 3.

    So the failure in finding 69 is not about missing content, and the size objection does not
    survive either: a summary that keeps every needed table on a 341-fact-type schema is not
    failing for want of room. It is about what the flat form *says*. Counted over the eleven
    BIRD models, the flat verbalisation is 1,059 sentences of which **82% are uniqueness --
    "each X has at most one Y"** -- and 17% mandatory. The summary carries optionality (the
    `?` marks) and drops functionality entirely.

    That makes the hypothesis concrete and cheap to test: a SQL writer reads join cardinality
    off those 867 sentences, and nothing else in the prompt says whether a join is one-to-many.
    Two arms would settle it -- a summary that marks the functional side, and a flat
    verbalisation with the uniqueness sentences removed. Neither is run; the second is the
    better one, because it can only lose points.

73. **The cardinality hypothesis is wrong, and so is the size one.**
    Finding 72 put its money on a mechanism: the flat verbalisation is 82% "each X has at most
    one Y", a SQL writer reads join cardinality off those sentences, and the summary drops them.
    Two arms were named as the test and the prediction was written down first -- strip the
    uniqueness sentences from the flat text and it should fall from 70 to 68; add cardinality to
    the summary and it should rise from 68 to 70.

    | arm | the English it saw | size | of 100 |
    |---|---|---|---|
    | `direct_v2` | none | — | 68 |
    | `modelled_abstract` | the level-2 summary | 17.5 KB | 68 |
    | `modelled_full_v2` | flat, complete | 54.2 KB | 70 |
    | `modelled_abstract_card` | the summary **plus** cardinality | 21.2 KB | 70 |
    | **`modelled_nouniq`** | flat **minus** cardinality | **7.8 KB** | **72** |

    **Half the prediction failed and it is the half that mattered.** Removing 82% of the flat
    text's sentences did not remove the benefit: 72 against 70, one question lost and three won,
    the opposite direction from the one predicted. Cardinality is not the active ingredient.
    Adding it to the summary did move that arm the predicted way (68 → 70, 2 lost 4 won), but a
    mechanism that helps when added and also helps when removed is not a mechanism.

    The size explanation dies in the same table. The **best** arm is the **smallest** English --
    7.8 KB, a seventh of the complete text -- and the worst-performing English arm is the one in
    the middle. Against the baseline, `modelled_nouniq` is 2 lost and 6 won, the cleanest
    paired split any English arm has produced.

    What is left standing, across five arms under one prompt: **every English description is
    worth about +2 to +4 over the DDL alone, and what it says makes little difference.**
    The spread is 68 to 72 across materials differing seven-fold in size and substantially in
    content, against a noise band of ±3. That is a duller claim than "cardinality is the
    ingredient", and it is the one the numbers support. What the two surviving high arms share
    is the *per-fact-type sentence*, in the model's own names -- `modelled_nouniq` keeps "each
    X has some Y" and nothing else, and it scores highest.

    Caveats, and they matter at this resolution: one run per arm, a four-point spread against
    three-point noise, and no single pairwise difference here is individually significant. The
    refutation is the solid part -- it rests on a *predicted direction* coming out backwards,
    which does not need significance to be informative.

74. **The remaining headroom on BIRD mini-dev is mostly annotation, not capability.**
    Eighteen of the hundred questions have never been answered correctly by any of the 24
    writer arms. That number has been quoted all along as "mostly the gold's reading of an
    ambiguous question", which was an assumption, not a measurement. Measured:

    **14 of the 18 have a clear cross-arm consensus that the gold rejects** -- a majority of
    the eleven independent SQL arms, written from different materials under different prompts,
    producing the *same* answer, which the gold marks wrong. On four of them the agreement is
    11 of 11. Independent writers converging is weak evidence on its own; converging against
    the gold, on questions no system has ever passed, is not.

    Four inspected by hand:

    - **toxicology q234** ("how many bonds involve atom 12 of molecule TR009"). The gold joins
      `T2.atom_id = T1.molecule_id` -- an atom id compared with a molecule id -- and returns
      **1041**. The question's own evidence says `atom_id = 'TR009_12' OR atom_id2 =
      'TR009_12'`. Eleven of eleven arms return **3**. The gold is broken.
    - **thrombosis q1256** ("how many patients..."). The gold counts `COUNT(T1.ID)` over the
      join to Laboratory, so a patient with several abnormal CRP records counts several times:
      **208**. Ten of eleven arms return **25**, the number of patients. A fan-out bug in the
      annotation.
    - **card_games q352** (percentage of cards in Chinese Simplified). Gold 8.7734, arms
      8.7728 -- the same calculation over a slightly different denominator, both defensible.
      Unwinnable without guessing which join the annotator used.
    - **toxicology q215** ("how many atoms with iodine and with sulfur"). The gold returns two
      columns (3, 77); every arm returns one number. The question does not say which shape it
      wants.

    So the ceiling is not 100 and it is not really 82 either. Of the 18 unsolved, about 14 are
    not winnable by being better at SQL. **The best single arm is 77, the oracle over every arm
    is 82, and the practical maximum is somewhere near 86.** From 77 that leaves roughly four
    points of genuine authoring headroom plus whatever selection could recover, and selection
    has measured +3 available and 0 realised, twice.

    This is the number that should govern what gets tried next, and it retires most of the
    list. It also means the published leaderboard figure of 82 for this subset is at or above
    the honest ceiling -- a system scoring 82 here is not 18 points from perfect, it is at the
    annotation's limit.

75. **The method and the stronger model do not add — and the primer rewrite cost fifteen points.**
    Finding 74 put the ceiling near 86 and named one untried combination of two measured
    winners: the divide-and-conquer method (+6 on Sonnet) under a stronger writer (+5 for Opus
    with the plain prompt). Two arms, because the primer was rewritten the same morning and
    without a control the Opus arm would differ from `conquer_dc` in two things at once.

    | arm | writer | primer | method | of 100 |
    |---|---|---|---|---|
    | `conquer` | Sonnet | old | — | 71 |
    | `conquer_opus` | Opus | old | — | 76 |
    | `conquer_dc` | Sonnet | old | divide and conquer | **77** |
    | `conquer_dc_v2` | Sonnet | **new** | divide and conquer | **62** |
    | `conquer_dc_opus` | Opus | **new** | divide and conquer | **77** |

    **They do not add.** `conquer_dc_opus` 77 against `conquer_opus` 76 is 3 lost and 3 won —
    nothing. Against `conquer_dc` (77) it is 3 and 3. The method is worth +6 to Sonnet and
    **zero** to Opus: it buys what the stronger writer already has, and the two levers overlap
    completely rather than stacking. The ceiling stands, and the last cheap shot at it missed.

    **And the control found something worse.** `conquer_dc_v2` is `conquer_dc` again, same
    method, same schema listing, same model, differing only in the primer rewritten that
    morning — and it scored **62 against 77, losing 17 questions and winning 2**. McNemar on
    17–2 is p ≈ 0.0005. That is five times the noise band and by a wide margin the largest
    effect this project has measured. It is a regression, and it was shipped that morning as an
    improvement on the grounds that its examples were now under test.

    The style did not change: DISTINCT in 18% of answers before and 17% after, mean answer
    length 175 against 177, attempts 2.73 against 2.82. Whatever the new text does, it is not
    making writers more verbose or more defensive — it is making them **wrong**, quietly: 37
    `wrong_quietly` against the old primer's ~23 at the same attempt cost.

    Two confounds, honestly:

    - **The compiler also changed that morning** (finding 70's three fixes). `corpus.py` shows
      all 1,186 recorded queries recompiling byte-identical, so the fixes did not move any
      existing answer, but they were new capability and this is a new run.
    - **One run per arm**, and the ±3 noise band was measured on the *base* arm, never on this
      one. 15 points is far outside it, but the dc arm's own variance is unmeasured.

    The confirmation is one arm: `conquer_dc` again with the **old** primer under today's
    compiler. If it returns to 77 the primer did it; if it lands near 62 the compiler did.
    Until that runs, the shipped primer must be treated as a regression — and the general
    lesson is the one this project keeps relearning: **a change that improves a text by
    inspection is not an improvement until it is measured.**

    **Retracted the same day by finding 76 — the primer was not the cause.** The accusation
    above is left standing as written because the reasoning that produced it is the point: a
    15-point gap, a plausible culprit changed that morning, and a confound named but weighted
    too lightly. The control exonerated the primer and indicted something worse.


76. **The arm does not reproduce: 77, 64, 62. Cross-session numbers are not comparable.**
    Finding 75 blamed the primer rewrite for a 15-point drop. The confirming arm ran
    `conquer_dc` again with the **frozen primer** — the byte-identical text the original arm
    read, md5-checked — under today's compiler.

    | arm | primer | compiler | writer | of 100 |
    |---|---|---|---|---|
    | `conquer_dc` (14 Sep) | frozen | 14 Sep | Sonnet | **77** |
    | `conquer_dc_old` (15 Sep) | **frozen** | 15 Sep | Sonnet | **64** |
    | `conquer_dc_v2` (15 Sep) | new | 15 Sep | Sonnet | **62** |
    | `conquer_dc_opus` (15 Sep) | new | 15 Sep | **Opus** | **77** |

    **The primer is exonerated.** `conquer_dc_old` 64 against `conquer_dc_v2` 62 is 8 lost and
    6 won — a wash. The drop happens with the old text too.

    **The compiler is exonerated.** All ten questions `conquer_dc` won and both of today's arms
    lost recompile against today's compiler without error, and `corpus.py` already showed the
    SQL byte-identical.

    **The scorer is exonerated.** `conquer_dc` re-scored today gives **exactly 77 with zero
    outcome changes**.

    So the same arm, re-run twice, produced 64 and 62 against a recorded 77. What is left is
    the launching prompt — mine, rewritten for this session, against the original which cannot
    be recovered — and plain run-to-run variance, and **this round cannot separate them**. The
    honest range for that arm is 62 to 77.

    Three things follow, and they cost more than the primer would have:

    - **Finding 68's +6 does not reproduce.** "Divide and conquer is worth six points, the
      largest lever measured" rests on a single run of an arm that scores anywhere in a
      15-point band. The strategy arms may still beat the base — they were run in the same
      session under one prompt, which is the comparison that holds — but the *size* is not
      established and 77 is not a number to quote.
    - **The ±3 noise band does not apply to agentic arms.** It was measured on three runs of
      the base `conquer` arm at 1.7 attempts per question. This arm averages 2.7 attempts and
      does far more exploring; its spread is five times as wide. Every claim of "outside the
      noise band" made about a strategy arm needs that caveat.
    - **Within a session, arms are comparable; across sessions they are not.** Today's arms
      agree with each other: Sonnet 62-64, Opus 77, identical everything else — **a 13-point
      model effect with the method held constant**, where the cross-session comparison had
      recorded +5. Neither number is wrong; they are answers to different questions asked on
      different days.

    The repair is to the claims, not the code. Nothing is reverted: the primer stays (it is
    under test and fixes four real defects), the compiler fixes stay (they are regression-tested
    and moved no recorded query). What changes is that every cross-session figure in this file
    is now a within-session comparison plus a date.

77. **`WITHIN`: the partition without the collapse. A window function, in one keyword.**
    A third of Spider 2.0's local gold queries use a window function and ConQuer had none
    (finding on the spider2 profile: 8 of 24, and 7 of those 8 need only a partitioned rank or
    aggregate — one needs `LAG`). The gap turned out to be one distinction, not a feature.

    ConQuer already partitions. `GROUPED BY` does it and then *collapses*:

        THE COUNT OF e GROUPED BY d AS c     one row per d
        THE COUNT OF e WITHIN   d AS c       every row, carrying its group's figure

    That is exactly `OVER (PARTITION BY ...)` against `GROUP BY`, and it is the distinction a
    conceptual language should be able to make in English rather than in join syntax: *per
    group, instead of* against *per group, alongside*.

    The emitter already produced window SQL — `THE FIRST n PER` compiles to
    `ROW_NUMBER() OVER (PARTITION BY ...)` wrapped in a derived table — so the partitioning,
    the window ORDER BY and the wrap all existed. What was added:

    - `WITHIN` in the parser, reusing the `GROUPED BY` parse path, refusing an empty partition;
    - `aggregation.window` on the calculation in the lowering;
    - `OVER (PARTITION BY ...)` instead of `GROUP BY` in the emitter;
    - **the wrap, generalised.** SQL evaluates windows after `WHERE`, so a query that *filters*
      on a `WITHIN` value has to be wrapped — and the wrapping query cannot see inner columns,
      only what the subquery returns. Every value a deferred condition names is now exported
      under an alias, whether it is a column or another computed value. That last part is what
      makes `WHERE c = mx` work when `c` is itself a grouped aggregate.

    **Measured on Spider 2.0.** `local199` — "the year and month with the highest rental orders
    for each store" — is a grouped count with a window over it, and it now scores **1 under
    Spider 2.0's own evaluator**. The trial goes from 5 of 6 to **6 of 7**.

    Two honest notes on the rest. `local309` still fails and always will: `calibrate.py` shows
    its gold cannot reproduce its own recorded answer. And `local019`, whose gold uses
    `ROW_NUMBER`, is not blocked by the language at all — `WWE`'s model has `MatchWinnerId` as
    a plain value type with no reading to `Wrestler`, so the join the question needs does not
    exist. That is the no-declared-foreign-key family again, and it is the reverse engineer's
    problem, not the query language's.

    `LAG`/`LEAD` are deliberately not implemented. They are about row *adjacency* in an
    ordering, which has no reading in a fact-type model; adding them would import a relational
    idea wholesale to buy one question (`local197`).

    1,186 recorded queries recompile byte-identical; the suite is 1,513 assertions.

78. **The fan trap was guarded in the grouped case and open in the ungrouped one — and the
    obvious fix costs three right answers per wrong one.**
    `check_aggregate_locality` refuses a grouped aggregate over rows the query multiplies, with
    a message that names the offending role. It did not refuse the *ungrouped* form, because a
    whole-query aggregate lowers into a block of its own: the fan-out is inside that block and
    the `SUM` is on a calculation outside it, so nothing ever tested one against the other.

        THE SUM OF b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n

    returned **9,300,000** against a true 3,600,000 — each department's budget counted once per
    employee (2.4M×3 + 0.3M×1 + 0.9M×2). Silent, on the fixture the whole test suite runs on.
    The immediate cause was an early `if not fanout: return` on the outer block, which has no
    steps at all, so the descent into the aggregate's block never happened.

    **Then the interesting part.** Carrying the outer aggregate into the inner block's check
    fixes it — and also fires on 26 recorded pilot answers. Scored:

    | the refused aggregate | was correct | was wrong |
    |---|---|---|
    | `THE COUNT OF` | **20** | 5 |
    | `THE SUM OF` | 0 | 1 |

    Refusing a fanned COUNT rejects three right answers for every wrong one, and it refuses
    `THE COUNT OF DISTINCT Account [...]` where the author had already guarded it. That is the
    trade this project has measured before from the other side (finding: the refusals never
    fire on real authoring) and it is a bad one.

    The split is principled, not merely convenient. `THE COUNT OF Account [is of Loan …]` has a
    reading — *accounts with any such loan* — and authors mean it; the data usually obliges.
    Summing a value that fans out has no reading at all: it is arithmetically wrong the moment
    the fan-out has degree above one. **So counting a fanned head is the author's business;
    summing a fanned value is a defect.** The check now applies to value aggregates in that
    position and leaves COUNT alone. 1,186 recorded queries: **0 changed.**

    **How the neighbours handle the same class**, since it decides what to do next:

    - **Rel (RelationalAI)** cannot have it. Null-free *set* semantics over 6NF/Graph Normal
      Form: a fact is one tuple in its own relation, so there is no row to repeat. The price is
      many joins, which is why the paper's performance answer is worst-case optimal joins and
      factorised representations.
    - **Malloy** computes it correctly anyway — symmetric aggregates, keyed on the source's
      primary key, which is why it needs `join_one`/`join_many` to be right.
    - **MetricFlow** aggregates each measure at its own grain and joins afterwards, rather than
      joining and then aggregating.
    - **ConQuer** refuses, and offers `[...]` — the semijoin that matches without multiplying.

    Ours was the only one of the four that declined rather than computed. **Superseded the same
    day by finding 79: it computes now.** The refusal was inertia — the existing code refused, so
    the fix extended a refusal — and the question "why can't we find a solve?" was the right one.


79. **Compute it, don't refuse it — where the question has one answer.**
    Finding 78 caught the fanned-out `SUM` and refused it. That was the wrong instinct, and
    extending a refusal because the existing code refused is not a reason.

    Malloy uses *symmetric aggregates* — encode the primary key into the high bits of a number,
    `SUM(DISTINCT ...)`, subtract the key's contribution — because Looker had to emit one flat
    statement. It works, with precision limits. **We own the whole statement**, and we already
    wrap queries in derived tables twice (`THE FIRST n PER`, and `WITHIN` in finding 77). So the
    fix is exact and needs no arithmetic trick:

        SELECT SUM("v") FROM (SELECT DISTINCT <determinants>, <value> AS "v" FROM <block>)

    And the neat part: **the check that detects the fan-out already computes what the fix
    needs.** `keyed` in `check_aggregate_locality` is "what one row of the answer holds fixed" —
    exactly the determinants to deduplicate on. The refusal became three lines that attach
    `aggregation.dedupe`, and the emitter projects those keys beside the value, takes DISTINCT,
    and aggregates outside.

        THE SUM OF b IN Department has DepartmentBudget b AND ALSO is of Employee has EmployeeName n
        9,300,000  ->  3,600,000, the truth

    **Then the same treatment was tried on `COUNT`, and measured, and rejected.** 24 recorded
    answers would have changed SQL; re-scored against gold:

    | | |
    |---|---|
    | was right, stays right | 18 |
    | was right, becomes **wrong** | 2 |
    | was wrong, becomes right | 1 |
    | was wrong, stays wrong | 3 |

    **Net −1.** The two losses are `card_games` q416, where the evidence's formula wants the
    *joined rows* — the fan-out is the author's intent. So counting a fanned head is genuinely
    ambiguous in a way that summing a fanned value is not, and neither refusing it (20 right
    rejected for 5 wrong, finding 78) nor deduplicating it (net −1) is an improvement. `DISTINCT`
    is how an author says which they mean. The final rule:

    - **grouped aggregate over a fan-out** — refused, as before, with the role named
    - **ungrouped value aggregate over a fan-out** — **computed correctly**, deduplicated
    - **ungrouped `COUNT` over a fan-out** — left to the author, as before

    1,186 recorded queries: 0 changed. Suite 1,531 assertions.


80. **The refusal's own advice did not work when followed literally.**
    Building `conquer/tests/test_fanout.py` — thirteen cases over every shape of the trap —
    turned up one failure, and it was in the message rather than the compiler. The fan-trap
    refusal ends:

    > Put the multiplying path in brackets -- `[Department has Employee]` matches without
    > joining, so it cannot multiply

    True only while the bracket **binds nothing**. `[is of Employee]` works; `[is of Employee
    has EmployeeName n]` binds a name, compiles to a join rather than a semijoin, and
    multiplies exactly as the bare path did — so it is refused again, by the message that told
    the author to write it.

    This is not a new discovery so much as one this project kept paying for and never fixed.
    The benchmark writers found it independently and repeatedly: *"a bracket filter that binds
    a variable turns it from an EXISTS check into a real JOIN, which fans out and inflates
    counts"* (thrombosis, 7 against 6); *"needed `THE DISTINCT COUNT OF` since a plain count
    over-fans"* (codebase_community, 19 against 14). Each of them worked it out alone, an
    attempt at a time, because the message that should have said it did not.

    The message now names both forms and the difference between them. The test suite covers
    both, and every case that asserts a corrected number also asserts what the naive join would
    have given — so a case fails if the fixture ever stops containing the trap, rather than
    passing vacuously.

81. **What Malloy actually does with the fan trap, run rather than assumed — and the three
    gaps it exposes.**
    The project's 16 September plan (since retired) bet that this project's inferred uniqueness constraints
    could supply the `join_one`/`join_many` that makes Malloy's fan-out handling correct. That
    was an assertion. `bench/malloy-probe/` checks it: Malloy 0.0.433 over DuckDB, the same
    fixture and the same three traps as `conquer/tests/test_fanout.py`.

    **Malloy has two mechanisms, not one.** Neither is the Looker symmetric-aggregate
    arithmetic I had described:

    1. **Join elimination.** If the aggregate names nothing from the joined source, the join is
       simply dropped — `SELECT COUNT(1) FROM employee as base`. No fan-out because no join.
    2. **A synthesised row key.** When the join is needed, every row of the many side gets
       `GEN_RANDOM_UUID() AS "__distinct_key"`; counts become `COUNT(DISTINCT __distinct_key)`
       and sums become `SUM` over `UNNEST(list(distinct {key: <pk>, val: <value>}))`.

    The second is **the same idea as finding 79's fix** — deduplicate (determinant, value)
    pairs — written in DuckDB's struct and list functions rather than a derived table. On
    method the two are equivalent and ours is the more portable SQL. The difference is coverage.

    **Gap 1 — the grouped fan-out, and it is ours.** Malloy returns ENG 2,400,000 / SALES
    900,000 / HR 300,000 beside heads 3/2/1. This compiler refuses that shape, and a measure
    beside its dimensions is the common BI question. Confirmed, not argued.

    **Gap 2 — a CCM path step is not a Malloy join, and this would have bitten the generator.**
    The emitted SQL is `LEFT JOIN employee AS emps_0`: Malloy's joins are **outer**. A ConQuer
    path step is **inner** — reading a role asserts the fact exists. So the same question gives
    **808,500 through Malloy and 720,500 through the compiler**, not because either is wrong
    about fan-out but because they disagree about who is in scope. A generator must emit a
    filter for mandatory steps, or the two artifacts silently answer differently on the very
    fixture the plan proposes to validate them on.

    **Gap 3 — the COUNT question is answered, and Malloy's answer is better than either of
    ours.** It deduplicates counts, but resolves *which grain* by **where the measure is
    declared**: `emp_count is count()` on `employee` counts employees; `asg.count()` counts
    assignment rows. The author picks the grain when authoring the model, not when writing the
    query. That is why Malloy never faces the dilemma finding 79 measured — refusing a fanned
    COUNT costs 20 right answers per 5 wrong, deduplicating it scores net −1 — and it is a
    design worth stealing whatever else is decided: **resolve the ambiguity once, in the model,
    rather than every time, in the query.**

82. **Closing the gap the probe found: the grouped fan-out, where the keys pin the value.**
    Finding 81 measured Malloy computing the grouped fan-out that this compiler refused — ENG
    2,400,000, SALES 900,000, HR 300,000 beside heads 3/2/1 — and called it the real gap,
    because a measure beside its dimensions is the common BI question.

    Most of it closes without any deduplication machinery at all. **If the group keys already
    pin what determines the value, every row of the group carries the same value and the group
    holds exactly one instance** — so summing it n times is n × the value when what is wanted
    is the value itself. `MIN` of a constant is that constant, exactly. `Department has
    DepartmentBudget b … is of Employee … THE SUM OF b GROUPED BY c` is that shape, and it is
    the common one: a parent's measure reported beside the parent.

    The test is not a heuristic. `check_aggregate_locality` already settles what a set of nodes
    pins, run to a fixed point through the uniqueness constraints; the rewrite fires only when
    the group keys settle the argument's whole determinant chain. Where they do not — salary is
    determined by Employee, and a Department has many — the group really does hold several
    distinct values, each repeated, and there is no single instance to take. That is refused
    still, and it is the case that needs **per-aggregate** deduplication, which flat SQL cannot
    express without Looker's key-in-the-high-bits arithmetic. Malloy pays for it with
    `GEN_RANDOM_UUID()` and DuckDB's `list(distinct …)`; we decline it and say why.

    A second thing fell out. The binding-bracket trap of finding 80 — `[is of Employee has
    EmployeeName n]` joins rather than semijoins, so it multiplies — **stops mattering whenever
    the keys pin the value**: the answer is right either way. The refusal now fires only where
    the binding actually changes the number.

    Where the three gaps stand after this:

    | gap | verdict |
    |---|---|
    | grouped fan-out | **closed for the common case**, refused where per-aggregate dedup would be needed |
    | joins outer vs inner | **not a ConQuer defect** — ORM semantics. It is a requirement on the CCM → Malloy generator, recorded in the plan |
    | COUNT grain | **not changed** — finding 79 measured that at net −1. Malloy's design (grain fixed once, in the model) is the better one and is worth stealing elsewhere, but not by silently redefining `THE COUNT OF` |

    Two tests in `test_errors.py` asserted the refusal that is now a computation; they were
    retargeted to the unpinned shape rather than deleted, so the refusal stays covered.
    1,186 recorded queries: 0 changed. Suite 1,546 assertions.

83. **DuckDB alone may be enough, and our SQL already runs there — which removes the last
    argument for Malloy.**
    The Malloy case had narrowed to dialect breadth (finding 82 and the plan's §2). So: does
    DuckDB reach far enough, and what would it cost us to target only it?

    **Its reach.** `ATTACH` for SQLite, PostgreSQL, MySQL and DuckDB files; readers for Iceberg,
    Delta, DuckLake, Parquet, CSV and JSON; `httpfs`/S3/Azure/AWS. What it does *not* give is
    push-down **into** Snowflake or BigQuery as compute — for those it is a data mover, not a
    federator, and that is the honest limit of "just support DuckDB".

    **The cost.** 344 recorded ConQuer answers, compiled and run against SQLite directly and
    against DuckDB with the same file attached:

    | | |
    |---|---|
    | identical | **302** |
    | differ only where the query has no defined answer — ties under `ORDER BY … LIMIT 1` | 9 |
    | need one model-level date-function spelling | 10 |
    | **refused by DuckDB because SQLite was being permissive** | **18** |

    Nothing needed a new dialect. The emitter's SQL-92 output runs on DuckDB unmodified.

    **One real defect, one word.** `fn.divide` carried `CAST({0} AS REAL)`. SQLite gives `REAL`
    64-bit affinity; **DuckDB follows Postgres, where `REAL` is float32** — so every percentage
    came out right to seven digits and wrong after (66.66666412353516 against
    66.66666666666667). `CAST(… AS DOUBLE)` is full precision on both. Fixed in
    `reverse/derive.py` and patched into 53 built models; 171 recorded queries change their SQL
    text and **none change their answer**, which is what SQLite's affinity rules predict.

    **And the 18 refusals are the interesting ones.** Fifteen relied on SQLite silently coercing
    text to a number (`avg(VARCHAR)`), three on a bare column beside `GROUP BY`. DuckDB is the
    stricter and more correct engine in every one, and some of those queries are recorded in the
    pilot as **correct answers**. Moving to DuckDB would surface them rather than hide them.

    So the dialect-breadth argument does not survive: we already emit SQL that runs on DuckDB,
    DuckDB attaches the source kinds a messy estate actually has, and the one portability defect
    found in 344 queries was a single word carried in the model — which is exactly where the
    plan says the dialect seam belongs.

84. **Name-based foreign key inference recovers 3% on realistically named schemas, and the
    premise is what fails — not the rule.**

    LiveSQLBench Large-v1 is the first corpus this project has found that is both *large* and
    *honest about its keys*: 18 PostgreSQL databases, 971 tables, **971 declared primary keys
    and 1,228 declared foreign keys**. Spider 2.0 could never support this measurement — its
    format has no field for a key, so all 7,860 of its tables declare none and strip-and-infer
    had nothing to be scored against. BIRD's 81%/100% was over eleven small databases.

    Strip every declared foreign key and run rule 9:

    | | |
    |---|---|
    | declared references | 1,122 |
    | **reachable by rule 9 at all** | **55 (5%)** |
    | found | 44 |
    | correct | **37 — recall 3%, precision 84%** |

    Twelve of the eighteen databases score a flat zero.

    **The diagnosis is exact and it exonerates the rule.** Rule 9 matches a column named
    exactly like the target's single-column primary key. **95% of these references are not
    spelled that way**: `personnel_skills.VerifiedBySupervisorRef` → `personnel.crewregistry`,
    `qualitycontrol.arcref` → `projects.arcregistry`, `solar.technicians.Reports_To_Tech` →
    `TechNum`. Of the 55 it could reach it took 37. BIRD's 81% was measured where columns are
    named after what they point at; enterprises do not do that, and this corpus was built to
    look like an enterprise (56% snake_case, 20% camelCase, 12% UPPER_CASE, 12% Mixed_Case,
    inside one database).

    **What this costs the consolidated plan.** §3 rests on "the reverse engineer supplies the
    `join_one`/`join_many` that makes Malloy correct," motivated by warehouses where nothing is
    declared. Where keys *are* declared that still holds. Where they are not — the motivating
    case — name matching will not rescue it, and a wrong `join_one` is a silently inflated
    aggregate. Rule 9c scores containment, coverage and distribution instead of names and is
    the rule that should survive this; it could not run, because the public release ships three
    sample rows per table. **Testing 9c against these 1,122 references is now the highest-value
    unrun experiment in the repository**, and it needs the PostgreSQL dumps.

85. **The benchmark now ships the semantic layer we measured the gain from.**

    LiveSQLBench carries a 1,090-entry hierarchical knowledge base — 462 domain, 430
    calculation, 198 value-illustration entries, **560 of them depending on other entries** —
    plus a per-column gloss for all 17,694 columns. **55% of its Query tasks name a term
    defined only there** ("Conservation Priority Index", "Veteran's Podium", "Secure Income
    Efficiency Score"), and cannot be answered from the schema at all.

    Findings 43, 69 and 73 established that this project's semantic layer was worth +8 on BIRD
    and that the +8 belonged to the **definitions**, not to ConQuer — the control showed the
    language at 0. That contribution is now every competitor's baseline, supplied by the
    benchmark. Whatever case is made here has to be made somewhere else: acquisition, source
    selection, refusals, or the ladder.

    And the ladder is finally in its regime. The flat verbalisation is **80 KB per database**
    against BIRD's 5 KB, and level 2 keeps 11% of 17,606 fact types (level 3 6%, level 4 3%).
    Finding 69's zero was measured where the whole model fits in a prompt. It no longer does.

86. **Scope: 148 of 480 tasks are CRUD, and jsonb is in a quarter of the tables.**

    The compiler emits SELECT, so the honest denominator on LiveSQLBench is **332 Query
    tasks**, not 480 — and that is before correctness. Within those, the wording probe flags
    ~2% as needing something absent (median/percentile, recursion, explicit JSON). The real
    exposure is structural: **253 of 971 tables carry a `jsonb` column** and all 18 databases
    have some. Any number reported from this corpus must state the denominator it used.

87. **The emitter ignored a mapping field it did not understand, and answered anyway.**

    Before rule 12 could be built, the question was whether ConQuer needed a JSON type at all.
    Testing it rather than asserting it: a fixture with the real `location_metadata` shape, a
    model hand-patched into what rule 12 would produce, one query. Everything upstream of
    emission worked untouched -- parsing, lowering, linking, the join plan, the projection,
    the mandatory-role guard. The answer came back as

        {"location": {"city": "Sakhir", ...}, "coordinates": {"latitude": 26.0325}}

    The whole document, where the city was asked for. `path` was ignored **in silence**, and
    the SQL read `circui1."location_metadata"`. Not an error -- a plausible wrong answer, which
    is the failure class this project exists to prevent.

    Every column reference in the emitted statement goes through one function, which is why
    the fix was contained: `col_names` became `col_refs` and returns a *template* with `{0}`
    where the alias goes, so `{0}."city"` and `json_extract({0}."meta", '$.location.city')`
    are the same kind of thing to the six sites that render one. And `col_ref` now **refuses a
    mapping column carrying any field it does not know**, which is the guard that should have
    existed all along: the allowlist is six fields, and a survey of 22,366 mapping columns
    across 72 models found exactly those six in use.

88. **Two defects the large corpus found that the fixture could not.**

    `conquer/tests/test_json.py` passed on a three-row fixture. Compiling a query against all
    1,892 fact types rule 12 derived from 18 industrial schemas found two more, and both were
    invisible at small scale.

    **Tidy identifiers are not what documents contain.** The path guard was an allowlist,
    `^[A-Za-z_][A-Za-z0-9_ -]*$`, and real keys are `packetLoss%`, `ISO_27001?`, `hipaa??`,
    `grossAmt$` and `tx/hr`. It refused 17 legitimate columns. Bracket-quoting each step that
    is not a bare identifier -- `$."grip%"` -- carries all of them, and every dialect's
    JSONPath accepts it. The guard now refuses only a quote or a backslash, which are what
    would actually break out of the literal.

    **Column order decided whether a name collision was caught.** `funds.strategytype` and the
    document key `fundclass -> Strategy_Type` both want the value type `FundStrategyType`,
    differing by one letter's case. Rule 12 runs before rule 2 inside the column loop, so it
    could only see collisions with columns that came *earlier*; `exchange_traded_funds` had 13
    of them and a query naming either fact type picked one arbitrarily. Rule 12 now
    anticipates the names rule 2 will make from the rest of the table and qualifies its own
    with the document column -- `CircuitLocationMetadataGrade` beside `CircuitGrade` -- so both
    stay addressable, and reports that it did.

    Both are regression cases in `test_json.py` now, with the awkward keys and the colliding
    column in the fixture. 17 cases, and the suite is 1,563.

89. **Rule 12 on LiveSQLBench: 1,683 fact types recovered, 97% of their paths resolve.**

    | | |
    |---|---|
    | fact types, 18 databases | 17,606 -> **19,289** |
    | jsonb columns expanded | 209 records; 3 bags refused |
    | models valid against `ccm.schema.json` | 18 of 18 |
    | derived fact types that compile, emitting a path read | **1,892 of 1,892** |
    | derived paths that reach a value in a real document | **1,584 of 1,625 (97%)** |

    The query language did not change, which was the claim worth testing. A query says
    `Circuit has CircuitLocationCity`; the path lives in the mapping and `fn.jsonPath` carries
    the dialect's spelling, the same seam that carries `divide`. The cast is not decoration:
    SQLite's `json_extract` preserves storage class but DuckDB and PostgreSQL hand back text,
    so `latitude > 9` would compare `'26.0325'` to `'9'` and drop two rows of three. The test
    that separates those is in the suite rather than a number where both agree.

    **What this did not test.** The classifier never ran. LiveSQLBench ships `fields_meaning`
    for 212 of 310 jsonb columns, so the shape came from metadata somebody wrote down rather
    than from a population, and `jsonshape.classify` -- the part that has to tell a record from
    a map from a bag -- is exercised only by the fixture. The 41 unresolved paths are dominated
    by plainly optional keys (`address.province`, `phone.extension`, `revocation_reason`), and
    three sample rows cannot tell "absent because optional" from "wrongly declared".

    **The map case is detected and deliberately not derived.** `{'clay': 15, 'quartz': 60}`
    then `{'calcite': 80, 'sandstone': 20}` is not a record: the keys are data. In ORM it is
    `Survey has Percentage for Mineral`, a fact type whose key plays a role, and deriving one
    fact type per key would invent an unbounded sparse schema out of one sample. Reading it
    needs an unnest rather than a path, which the mapping cannot express. Asking "what is the
    elementary fact here?" is what separates the two, and it is the argument for doing this
    conceptually rather than by adding a JSON scalar to the query language -- a scalar type
    flattens that distinction away.

90. **Rule 12 derived fact types that no query could ever read.**

    Hunting edge cases after the LiveSQLBench build passed: a document key that cannot be
    written as a JSONPath still became a fact type. An empty key gives `$.""`, which SQLite
    answers with `OperationalError: JSON path error`; a key carrying a double quote ends the
    literal and the emitter refuses it. Either way the model **asserted a fact that no query
    could read** — the failure arrives at execution, or at emission, long after the model
    said the value was there.

    Almost everything else is spellable, because a step can be bracket-quoted: `$."tx/hr"`,
    `$."a.b"`, `$."a[0]"`, `$."net worth"` and `$."123"` all resolve, and the probe confirmed
    each. Only a quote, a backslash and the empty key do not. Rule 12 now drops exactly those,
    keeps every other key in the same document, and reports what it dropped and why. The
    emitter's guard stays as the second line.

91. **Twin documents on one table: the first silently took the bare name.**

    `matches.home` and `matches.away` both carry `{"score": …, "team": …}`. Rule 12 produced

        MatchScore   MatchTeam      (from home)
        MatchAwayScore  MatchAwayTeam   (from away)

    Whichever column the loop reached first claimed the unqualified name, so the model read
    `MatchScore` beside `MatchAwayScore` and **nothing said which was the home one**. Not a
    wrong answer — a model that cannot be read correctly, which on a 54-table schema is the
    same problem one step earlier.

    This is finding 88's collision again, in the third of three directions. Rule 12 avoided
    names already made, then learned to anticipate the ones rule 2 would make, and was still
    blind to the ones *another document on the same table* would make. It now qualifies a
    label two documents share in **both**, giving `MatchHomeScore` and `MatchAwayScore`.

    The lesson is about the shape of the defect rather than the defect: a rule that names
    things by position in a loop will keep producing asymmetric names until it is made to
    compute the whole set first. Three fixes, three directions, one cause.

    Suite 1,563 → 1,567. The classifier edges — top-level arrays, empty objects, nesting past
    the depth limit, 60-key documents, values whose type varies by row, list values, all-null
    documents — were probed and all behaved; those are the cases that did *not* need fixing.

92. **A PostgreSQL dialect is 12 function templates — and it was broken before it ever ran.**

    Finding 83 measured the *statement* as portable: 302 of 344 recorded answers identical
    between SQLite and DuckDB, no new dialect needed. What it did not measure is the function
    library, and that is where the differences actually live. Writing one out:

    | | |
    |---|---|
    | `divide`, `div` | Postgres has no `DOUBLE`; the type is `DOUBLE PRECISION` |
    | `round` | Postgres has `round(numeric, int)` and **no** `round(double, int)` |
    | `instr` | no `INSTR`; `POSITION({1} IN {0})`, arguments the other way round |
    | `list` | `json_group_array` / `json_agg` / `list` |
    | `jsonPath` | `json_extract` / `json_extract_string` / `jsonb_path_query_first … #>> '{}'` |
    | `year`, `month`, `day`, `today`, `days_between` | `strftime` / `EXTRACT` / `CURRENT_DATE` |

    Twelve entries as a patch over the SQLite base (`DIALECTS` in `reverse/derive.py`,
    `--dialect`). Two of these are the kind that answers rather than fails — `CAST(… AS DOUBLE)`
    is a *syntax error* on Postgres, which is the good case, but `round` silently not existing
    for the type in hand is not.

    The cast on a path read moved into the model with them, as `fn.castNumber` /
    `fn.castInteger`. It had been a literal type name in the emitter, which is exactly the
    mistake finding 83 caught one layer down: a type name is as dialect-specific as a function
    name.

    **And the dialect could not have worked at all.** PostgreSQL's path read ends `#>> '{}'`.
    A column reference is a template with `{0}` for the table alias, so that `{}` sat beside
    it in one `str.format` call — automatic field numbering mixed with manual, which Python
    refuses outright. Every PostgreSQL query would have raised `ValueError` on the first
    column. References are now assembled against a sentinel and every brace the dialect's own
    SQL contains is escaped before the alias slot goes back.

    It was found by writing out a worked example to show someone, not by the test suite, and
    not by the 1,892-query LiveSQLBench probe — both of which only ever ran SQLite.

93. **Reading the documents beats the declared field schema — and the declaration fails
    silently.**

    The dumps are `pg_dump --inserts` output, so they load into SQLite without PostgreSQL
    running (`bench/livesql/load.py`): 1,987,698 of 1,996,845 rows over 962 of 971 tables.
    That put a real population under `jsonshape.classify` for the first time — until now it
    had only ever seen a three-row fixture, because LiveSQLBench ships `fields_meaning` and
    rule 12 was fed that instead.

    Both are now available over the same 310 jsonb columns, so they can be compared.

    | | |
    |---|---|
    | paths the metadata declares | 1,920 |
    | paths the data actually carries | **2,101** |
    | **found in the data, never declared** | **232** |
    | **declared, but no document carries them** | **51** |
    | types agreeing (or harmlessly differing) | 1,731 |
    | **type disagreements that change an answer** | **138** |

    **The dangerous ones are numbers that are not numbers.**
    `work_orders.costing.LABOR_COST` is declared `REAL`; the values are `"$150.00"`,
    `"€1,069.50"`, `"£82.00"` — three currencies and a thousands separator.
    `CAST('$150.00' AS REAL)` is **0.0** in SQLite and an error in PostgreSQL, so a model built
    on the declaration reports every labour cost as zero and says nothing about it.
    `spare_parts.weight_kg` is the same shape: `"0.05 kg"`, `"2.6 lbs"` — units embedded, and
    mixed units at that. The classifier reading the data calls both `text`, which is right.

    **And it found the map on its own.** `geological_surveys.mineral_composition` — 29 distinct
    keys, none stable, every value an integer — is the `{'clay': 15, 'quartz': 60}` case that
    motivated the three-way split in the first place, and the classifier reached that verdict
    from 98,640 real rows rather than from the sample I had read by eye. Four maps across the
    corpus, and **zero bags**: every jsonb column here has structure.

    The conclusion is the one rule 12 was designed around but could not until now demonstrate:
    a declared schema is evidence, not truth, and where they disagree the population wins.

    **Two traps in the dumps, both silent.** `pg_dump` writes each constraint into the file of
    *both* tables it touches, so every `PRIMARY KEY` arrives twice, SQLite rejects the table,
    the fallback creates it without constraints, and **971 declared keys quietly become none** —
    the exact answer key the rule 9c experiment exists to be scored against. And each directory
    holds a `<db>_full.sql` repeating the schema, carrying data for some databases and not
    others; reading it alongside the per-table files loaded every row twice, which looks like
    nothing at all while no key is enforced. `museum_artifact` reported 423,976 rows for a
    211,988-row database.

94. **Every query shape works over a path, because a path is a column everywhere it matters.**

    A path is not a column: it cannot be indexed, SQL will not let it be named by its output
    alias in a `GROUP BY`, it has to be qualified with the right alias inside a correlated
    subquery, and it has to appear whole in a `PARTITION BY`. `test_json.py` proved the simple
    cases on three rows; `bench/livesql/query_probe.py` asks the harder ones of a real
    database — `solar_panel_large`, 28,864 rows, where `inverters.geolocation` holds
    `{"latitude": 34.0522, "LONGITUDE": -118.2437}` and `Inverter` joins to `Plant` and
    `InverterModel`. Fourteen shapes, each checked against hand-written SQL over the same
    data rather than against its own output. **All fourteen agree.**

    | | |
    |---|---|
    | join, path on one side and a column on the other | ok |
    | join across two hops, path at the far end | ok |
    | `GROUP BY` a path | the expression is repeated in the `GROUP BY`, as SQL requires |
    | aggregate a path grouped by a column, and the reverse | ok |
    | correlated bracket filtering on a path | the path is qualified with the outer alias |
    | `WITHIN` partitioned by a path, and aggregating one | `OVER (PARTITION BY …)` |
    | scalar aggregate over a path | ok |
    | two paths in one document, compared | ok |

    The reason this costs nothing is structural rather than lucky: **every column reference in
    the emitted statement goes through `col_refs`** (finding 87), so a reference is a template
    and nothing downstream knows whether it resolves to a name or a `json_extract`.

    **And the trap is the language's, not the document's.** A bracket that *binds a name* joins
    rather than semijoining, and so multiplies the head — 64 rows where the semijoin gives 41.
    That is documented behaviour (`lower.py`'s fan-out message, finding 80), and it behaves
    identically whether the bound value is a column or a path. Both are in the probe, so a
    change to either is caught.

    What a path does **not** get is an index. Filtering or joining on one is a scan, which is
    fine for a leaf value and bad if a path is ever used as a reference — rule 12 does not
    derive references from inside documents, and should not start.

95. **Rule 9c has never run on this corpus. Its analysis has, and the gate throws it away.**

    The dumps put 1,987,698 rows under rule 9c for the first time. Strip all 1,112 declared
    foreign keys from 18 databases and ask the data to find them back:

    | | found | right | recall | precision |
    |---|---|---|---|---|
    | rule 9, names only (finding 84) | 44 | 37 | **3%** | 84% |
    | **what `apply_references` applies today** | **0** | **0** | **0%** | — |
    | the shape-only model at its own threshold | 1,033 | 639 | **57%** | **62%** |

    **The zero is the finding.** `apply_references` requires `Finding.corroborated`, which is
    `any(s in ("name_pk_table", "name_pk_col") …)` — name evidence, documented as "the
    strongest single signal… measured alone at 100% precision across four databases". That
    calibration is real and it is exactly inverted here, where 95% of references are not named
    after what they point at.

    Worse, the contradiction is internal. `population.py` already carries `SHAPE_ONLY` —
    weights with every name signal removed — and its comment names the reason: *"Bird's own
    case study… her schema names references for the concept and keys for the identifier, so
    `Rating.paper` faces `Paper.number` and no amount of string comparison helps."* It has its
    own fitted threshold, 2.6. **So a mode that exists precisely for schemas where names are no
    evidence feeds an application step that requires name evidence.** Both cannot be right, and
    on this corpus the mode is right.

    **A threshold does not rescue it.** `preferred` already encodes the threshold, so sweeping
    below 2.6 changes nothing; above it the curve is shallow and then falls off a cliff:

        score >= 2.6 (calibrated)   57% recall @ 62% precision
        score >= 3.5               52% @ 68%
        score >= 4.0               43% @ 75%
        score >= 4.5                0% -- 4.5 is SHAPE_ONLY's maximum (1.0+1.0+2.0+0.5)

    The best point available is **43% at 75%**, and a quarter wrong is a wrong join in every
    query that walks it. **So rule 9c should report on schemas like this, not apply** — which
    is what it already does for everything the name gate rejects. The defect is that the gate
    makes the shape-only mode inert rather than cautious: it reports nothing either, because
    `apply_references` is where findings become refinements.

    **This corrects §3 of the consolidated plan.** "The reverse engineer supplies the
    `join_one`/`join_many` that makes Malloy correct" was motivated by warehouses declaring
    nothing. Measured: where keys are declared it holds; where they are not, the best available
    inference is 57% at 62%, and a wrong `join_one` is a silently inflated aggregate. That step
    needs a human confirming each reference, and the plan should say so.

    One thing held loosely: a candidate the catalogue does not declare is not automatically
    wrong — real schemas carry undeclared references, and 1,112 is what someone wrote down, not
    what is true. That would move precision up, not recall, and 43%/75% is reported as measured
    rather than adjusted.

96. **A PostgreSQL enum silently deleted nine tables, and a benchmark writer caught it.**

    The blind SQL writer on `labor_certification_applications` reported that the two tables all
    eight of its questions depend on — `cases` and `case_attorney` — were absent from the
    database while present in the schema it had been given, and diagnosed the cause without
    being told: they are the only two tables declaring PostgreSQL enum columns.

    It was right. `visacls public.enum_visa_class` is a **syntax error in SQLite because of the
    dot**, so the whole `CREATE TABLE` was rejected, the fallback could not save it, and the
    table vanished — along with every row of it, since the inserts then had nowhere to go.
    Stripping the `public.` prefix fixes it: 49 tables where there were 47, all 125,534 rows.
    The same bug had quietly taken 4 more tables in `disaster_relief` and 2 in
    `reverse_logistics`.

    **This is the second time a blind writer has found a defect the tests did not.** The
    measurement that mattered — `load.py` reporting "9 tables skipped" — was printed, read by
    me, and dismissed as acceptable loss. It was not: it was two thirds of one database's
    questions. A count of things that failed is not a finding until someone asks *which*.

    One table genuinely cannot be carried. `cross_border.Control_Library` declares both
    `control_code` and `"CONTROL_CODE"`; PostgreSQL keeps them apart because an unquoted
    identifier folds to lower case and a quoted one does not, and SQLite's identifiers are
    case-insensitive. That is a difference between the engines, and renaming one column would
    change what a query is allowed to name, so it stays out and is reported.

97. **Two grouped aggregates over one computed key could never run.**

    A blind ConQuer writer on `exchange_traded_funds` reported a bind-parameter mismatch, and
    when I could not reproduce it from the description, isolated the mechanism exactly:

        supplied = used + p x (k - 1)

    where `p` is the parameter count of the group key and `k` the number of `GROUPED BY`
    aggregates sharing it. The `GROUP BY` list is deduplicated at emission -- the key is
    rendered twice, once in the SELECT and once in the GROUP BY, however many aggregates share
    it -- but its parameters were bound **once per aggregate**. So the statement had 2
    placeholders and 3 bindings, and failed outright before touching the database.

    A second writer, on a different database, hit the same bug on two of its eight questions
    and worked around it by inventing a literal-free group key (`instr(f, f)`). The first
    writer's minimal case is the cleanest statement of it: the same query with
    `abs(pe) - abs(pe)` as the key runs, because `p = 0` makes the miscount vanish.

    **Any query with two grouped aggregates over a parameterised key was affected** -- which
    is an ordinary shape (a count and an average per band). It never appeared in 1,567 tests
    because every grouped-aggregate case in them groups by a *column*, and a column carries no
    parameters.

98. **An associative operator stopped being one at three arguments.**

    `concat(a, b)` compiles to `a || b` through the model's `operatorSymbol`. `concat(a, '-',
    b)` fell through to `CONCAT(...)` -- a function SQLite did not have before 3.44 -- so a
    query that worked with two arguments failed with three, and the model's own spelling was
    ignored. `render_call` now folds an operator over any number of arguments.

    Both writers hit this one too, and one of them needed **four nested two-argument calls** to
    get round it while rebuilding a date comparison that `days_between` could not do (this
    corpus stores dates as `YYYY/MM/DD`, which `julianday` returns NULL for).

    Suite 1,567 -> 1,573. Both are regression cases in `test_fanout.py`, which is where
    "well-formed query, confidently wrong answer" already lives.

99. **SQL against ConQuer on LiveSQLBench: 40 questions, both arms answered every one, and
    most disagreements belong to the benchmark rather than to either language.**

    No gold exists, so nothing here is accuracy. Two blind writers answered the same questions
    against the same database, differing only in the language: SQL got the DDL with three
    sample rows, ConQuer got `./schema --for <question>` and the primer, and **both got the
    domain knowledge base**, since 55% of these questions name a term defined only there.

    | | |
    |---|---|
    | questions compared | 40 (five databases; the sixth still running) |
    | **answered by both arms** | **40 of 40** — no refusal, no blank, on either side |
    | identical result sets | 22 |
    | differing | 18 |

    Sorting the 18 by *why*:

    | | |
    |---|---|
    | the question or schema is genuinely ambiguous, and both writers said so | **11** |
    | ConQuer could not express something | **4** |
    | cosmetic — the numbers agree exactly | **2** |
    | **ConQuer followed the question and SQL did not** | **1** |

    **The eleven are the benchmark's.** `solar_panel_15` differs by exactly 100x because
    nothing says whether a rate stored as a percentage enters the formula as 1.2 or 0.012 --
    both arms flagged it, independently, with both numbers. `solar_panel_8` is 1541 against
    1103: mean-of-ratios against ratio-of-sums, and the question says only "the mean repair
    cost". `labor_certification_16` asks for the "top 3 most successful jurisdictions" in a
    database where every jurisdiction scores 100%, so the answer is whatever the tie-break is.
    `sports_events_6` needs a race-results table the schema does not contain.

    **The four are real gaps, and three are the same gap.** Rank-as-a-column, median, and a
    previous-row comparison all need a row to be positioned against other rows. ConQuer has
    `WITHIN` for a partitioned aggregate and `THE FIRST n PER` for a top-n, and neither gives
    a rank, a percentile, or a `LAG` -- so the median question came back as an *average*
    (0.4485 where the median is 0.4097) and the year-over-year question lost its first year.
    `coverage.py` predicted median and got rank wrong. The fourth was **my documentation**: the
    primer's function list omitted `concat`, so a writer reported string concatenation as
    impossible when `concat(a, b)` had always worked.

    **The one is the interesting one.** `museum_artifact_5` says "Include all artifacts" --
    there are 995. The SQL arm inner-joined through a 3-row table, returned 3 rows, and wrote
    in its note that it had done so. The ConQuer arm wrote `OPTIONALLY` and returned 931. Not
    because the SQL writer was worse -- it saw the issue and recorded it -- but because the
    outer join is a structural commitment across a five-table chain in SQL and a word you drop
    in front of a step in ConQuer. **The cheap thing to write was the right thing**, which is
    the only mechanism by which a language can change an answer rather than merely express it.

    And two of the "differences" are a label: `Specialists` against `Specialist`, and a group's
    id against its name. Counting those as agreement, the arms agree on substance on **24 of
    40**.

100. **The final arm: no square root, so a writer implemented Newton-Raphson inline.**

    `planets_data` needed an escape velocity. The function library has no `sqrt`, `power`, `ln`
    or `exp`, so the ConQuer writer computed the root with **six inline Newton-Raphson
    iterations from a constant guess** and verified the result against the closed form. It
    then hit the wall: every `AS` binding is inlined textually by the compiler, so an iterative
    numeric computation grows exponentially in query text, and a four-iteration version of the
    same trick **overflowed SQLite's parser**.

    Both are now fixed in the cheap direction: `sqrt`, `power`, `ln` and `exp` join the
    standard library. SQLite has had them since 3.35 with the math extension, which is on by
    default, and PostgreSQL and DuckDB spell `power` as `pow` too. The textual inlining of `AS`
    remains, and is worth knowing about -- it is why a long expression chain is a compiler
    problem rather than a database one.

    **This arm gives the third independent confirmation of the self-join collapse**, on a third
    database: "`Planet has Star is of Planet` collapses back to the same planet", so a pair of
    planets in one system can only be formed as two sibling branches from `Star`. Three writers,
    three schemas, one bug, none of them able to see the others.

    Two smaller gaps it names: scientific-notation literals (`1.898E27`) do not parse, and
    there is no way to *format* a result in scientific notation.

    **The complete round: 48 questions, 27 identical, 21 differing, and every question answered
    by both arms.** `planets_data` -- chosen because it holds the three map-shaped documents
    rule 12 deliberately refuses to model -- came in at 5 agreeing and 3 differing, and none of
    the three was the maps.

    Suite 1,573 -> 1,575.

101. **The self-join collapse: three writers, three schemas, and two recorded answers were
     relying on it.**

     `Employee has Department is of Employee` stands on `employee.dept_code` and re-enters the
     same fact type by its *department* role, which is also `employee.dept_code`. Same table,
     same columns -- so the emitter read it as **absorbed** and handed back the row already in
     hand. Every round trip through an entity silently paired each row with itself: **six rows
     where the colleague pairs are fourteen**, from a well-formed query, with the join
     eliminated entirely.

     Three blind benchmark writers hit it independently on three different schemas -- "`Planet
     has Star is of Planet` collapses back to the same planet", "the compiler unifies
     `DriverStanding has Driver is of DriverStanding`", "`AnnualReturn has Fund is of
     AnnualReturn`". None could see the others.

     **The fix is one clause.** Absorption is valid only when the value in hand *identifies*
     the instance being entered: `join_cols == identity`. Standing on the fact type's
     identifying columns means standing on its row; standing on any other column of it -- a
     foreign key, a value -- means the instances that share that value, which is a join.

     **A second bug hid behind the first.** With the collapse gone, the same shape emitted
     `annual2."tickersym" = annual1."portfolioref"` -- a join on a column of the *wrong table*,
     because the referenced-column substitution replaced the target's identifier with a column
     of `funds` while entering `annual_returns`. The inverse guard has always checked the
     table; this side never did.

     **Two recorded BIRD answers change, and both were relying on the bug.**
     `superhero/796` asks for one hero's attribute values and writes `a is of HeroAttribute`,
     which means every HeroAttribute that attribute is of -- across all 750 heroes. It returned
     6 rows; it now returns 112, and 112 is what the query says. The compiler is now right and
     those two queries are now wrong, which is the correct direction for both to move.

     **The suite did not catch any of this; `corpus.py` caught all of it.** 1,982 recorded
     queries recompiled, 2 changed. It also caught a defect of mine from finding 87 that had
     been live for several commits: `Anchor.columns` holds reference *templates* now, and a
     CTE's column names are built from them, so `Laboratory as (ID, Date)` had become
     `Laboratory_{0}."ID"`. 1,575 tests never touched it.

     Suite 1,575 -> 1,579.

102. **The relevance filter cannot see a word nobody wrote, and said nothing about it.**

     A ConQuer writer reported that `./schema --for` "never mentioned `OperationalMetric`, the
     only place MTTR and MTBF live; I had to dump the whole listing and grep it." Reproduced
     exactly. The question reads *"calculate its system unavailability"* and **never says MTTR
     or MTBF** -- only the definition in `knowledge.md` does. Append the definition's terms and
     `OperationalMetric` appears immediately.

     So the filter is not broken; its input was. `link.py` scores the words the question uses,
     and a question names **what it is about**, not what it is computed from. On BIRD that
     rarely bit, because a BIRD question and its evidence field use the same vocabulary as the
     schema. Here the vocabulary is split across two documents by design.

     Two changes, neither of which pretends to solve the unsolvable part:

     - `--for` now says how many entity types it hid and that more words widen the view. A
       silent omission becomes a question the reader can answer. The writer had the terms in
       `knowledge.md` all along; nothing told it they would help.
     - the harness's `./schema` takes extra terms (`--for "$*"` rather than `"$1"`), so a
       writer can pass the quantities a formula is built from.

     **And a harness lesson, learned the expensive way.** Rebuilding the working directories to
     ship that change ran `shutil.rmtree` over `work/pilot` and destroyed all twelve arms'
     `answers.json` -- an hour of agent work each. They were recoverable only because
     `compare.py --json` had already recorded every answer verbatim. `pilot.py` now refuses to
     rebuild when recorded answers are present, and grew `--refresh-tools` to rewrite the
     scripts in place. This is the same rule the BIRD harness already carries about
     `build.py --fresh`, which I knew and did not apply here.

103. **`THE MEDIAN`, and the discovery that an undeclared aggregate was emitted anyway.**

     Finding 99's most costly gap was the median: a writer asked for one, could not say it,
     and reported `THE AVERAGE` instead -- **0.4485 where the median is 0.4097**. Not a missing
     column; a different number, in the same shape, with nothing to mark it.

     `THE MEDIAN` now exists, and it exists **per dialect**, which is the honest form:

     | | |
     |---|---|
     | DuckDB | `median(x)` |
     | PostgreSQL | `percentile_cont(0.5) WITHIN GROUP (ORDER BY x)` |
     | SQLite | **absent** -- no median, no percentile, and the LIMIT/OFFSET trick that computes one is not a scalar aggregate and cannot be a template |

     So a model built for SQLite leaves `fn.median` out of its function table, and asking for
     one is refused with a message naming which dialects have it. (Python's bundled SQLite is
     3.35.5 and has no `median`; the 3.51 CLI on this machine does, which is exactly the kind
     of difference that makes "SQLite has it" the wrong question.)

     **Two defects surfaced on the way, both of them the same mistake in different places.**

     - *An aggregate the model did not declare was emitted on the strength of its own name.* A
       SQLite model with no `fn.median` still produced `MEDIAN(...)`, and the database said
       "no such function" after the query had looked fine. `aggregate_name` now refuses
       anything the function table does not carry -- which is the rule for scalar functions
       already, applied where it had never been applied.
     - *Aggregates ignored `sqlTemplate` entirely.* Only `render_call` read it, so PostgreSQL's
       median came out as `MEDIAN(x)` even with the right template sitting in the model. The
       dialect seam existed and one side of it was not wired in. `aggregate_sql` reads it now.

     The second is the more interesting: the seam has been in `model/model.md` since the
     beginning and half of it was dead. Nothing found it because no aggregate had ever needed
     a spelling other than its name.

     Suite 1,579; corpus 1,982 unchanged.

104. **`THE RANK OF` and `THE PREVIOUS`: the row-relative gap, closed.**

     Finding 99 found ConQuer short on four things, and three were one thing: **a row
     positioned against the other rows of its partition**. Rank-as-a-column, a median, and a
     previous-row comparison. `WITHIN` gave a partitioned *aggregate* and `THE FIRST n PER` a
     top-n; neither gives a rank, a percentile or a `LAG`, so a writer asking for a median
     reported the average (finding 103) and one asking for year-over-year lost its first year.

         THE RANK OF x WITHIN g        ->  RANK() OVER (PARTITION BY g ORDER BY x DESC)
         THE PREVIOUS x BY t WITHIN g  ->  LAG(x)  OVER (PARTITION BY g ORDER BY t ASC)

     Three decisions worth recording:

     - **Each carries its own order.** `THE FIRST n PER` borrows the query's `ORDERED WITH`,
       which works because a top-n and a sort want the same order. A rank and a lag do not:
       you rank *by* the value and lag *along* a key, and both are usually different from how
       the answer is sorted. So RANK's argument becomes its ORDER BY -- rank 1 is the largest,
       which is what "rank" means outside SQL -- and `THE PREVIOUS` takes an explicit `BY`.
     - **Both are window-only, and say so.** `THE RANK OF s GROUPED BY d` is refused: a group
       returns one row and there is nothing left for it to be relative to. `THE PREVIOUS`
       without a `BY` is refused for the same reason in the other direction -- without an order
       there is no previous row.
     - **RANK takes no argument in SQL**, so lowering moves what looks like its argument into
       the window's order and leaves `arguments` empty. That was the one place the emitter
       assumed every aggregate has an argument.

     Suite 1,579 -> 1,588; corpus 1,982 unchanged.

     **What is left of finding 99's four.** The `concat` gap was documentation and is fixed;
     median, rank and lag now exist. Nothing from that round is outstanding -- though `median`
     exists only where the dialect has one, which is the honest state rather than a closed gap.

105. **Spec completeness, made a test rather than an audit.**

     Three documents describe this language and none is generated from the code:
     `conquer/reference/conquer-92-grammar.ebnf` (ConQuer-92 as Proper published it, appendices A and
     B), `conquer/conquer-2026.md` (what this project added, and why), and `conquer/primer.md`
     (the one page a query writer gets). A language grows by someone adding a keyword to a
     table in `parser.py`, and nothing had ever noticed when the documents did not follow.

     Audited: **73 multi-word phrases the parser accepts, 61 of them in the 1992 grammar.** The
     twelve that are not are this project's additions, and the spec or primer named all but
     three:

     | | |
     |---|---|
     | `THE TOP n` | a synonym for `THE FIRST n`, working and unmentioned anywhere |
     | `THE DISTINCT LIST OF` | the bag-valued group function, distinct |
     | `THE MEDIAN OF` | an alias added three commits ago and documented only as `THE MEDIAN` |

     `conquer-2026.md` was two weeks stale and did not carry **`WITHIN`**, which has been in the
     compiler since finding 77. Items 28-35 and sections 12 and 13 bring it current.

     `conquer/tests/test_spec.py` now enforces it both ways: every phrase the parser recognises
     must appear in one of the three documents, and every library function that is not an
     operator or an internal must be named in the primer -- **and every function the primer
     names must exist**, because a primer promising something absent is worse than one omitting
     something present. That second direction is finding 99's `concat` in reverse: a writer
     reported string concatenation impossible because the primer's list omitted it, and it had
     always worked.

     116 checks. Adding a keyword and documenting it are now one task, because leaving the
     second undone fails the suite.

     Suite 1,615 -> 1,732.

     **What the grammar is, and is not.** The EBNF is ConQuer-92 and is *correct as history*;
     it is not a grammar of what this compiler accepts, and should not be edited to become one.
     The 2026 additions are a separate layer with their own document, which is the honest
     arrangement: someone reading Proper's paper can still check the compiler against it.

106. **A reference interpreter for the 1992 core, as a proof of concept: it found two
     departures from P in its first hour, and none of them was a bug.**

     `conquer/reference.py` evaluates Proper's P directly from the data -- typed heads,
     verb-part steps, denotations, brackets, `AND ALSO` / `BUT NOT`, `WHERE`, projection,
     ordering and cuts, computed `AS` elements, and the whole-query group functions with
     arithmetic over them. `tests/test_reference.py` and `bench/pilot/reference_check.py`
     run the compiler's SQL and the reference side by side and compare multisets.

     | | covered | unknown differences | known departures |
     |---|---|---|---|
     | fixture, 79 queries | 36 | **0** | 2 |
     | BIRD `conquer` arm, 99 recorded | **57** | **0** | 3 |
     | BIRD `conquer_opus` arm, 100 recorded | 44 (before the last extension) | **0** | 4 |

     **Zero unknown differences on ~100 real queries is the headline, and it cuts both
     ways.** The compiler is right on the 1992 core. Every bug the blind writers found this
     week -- the self-join collapse aside, which the reference confirms fixed at 14 rows --
     was in a 2026 extension: `WITHIN`, `GROUPED BY` over a computed key, a path into a
     document, `concat`. A reference over the 1992 core cannot reach those, because there is
     no P for them yet. That is the case for writing one, not against it.

     **Two departures from P, both undocumented, both now named as `KNOWN` so that only a
     new disagreement fails:**

     - **`DISTINCT` is lifted to the whole projection.** `lower.py:612` sets
       `block["distinct"] = True` wherever `DISTINCT` appears in the path. P's `Ds` applies
       where it is written, and at the head of `DISTINCT Race [...] has CircuitLat la` it
       removes nothing -- the races *are* distinct -- so P returns three identical rows where
       the compiler returns one. Seven corpus queries across two arms, every one this shape.
       The compiler's reading is what the questions want; it is not what the 1992 semantics
       says, and nothing had written down the difference.
     - **Aggregate locality** (finding 79) sums each fanned value once; P sums the bag as it
       stands.

     Both belong in `conquer-2026.md` as stated changes to P. The interpreter is what forced
     the question -- neither had been noticed as a departure because nothing else evaluates P.

     **What it does not cover, concretely:** references to a non-identifier column (10 of the
     `conquer` arm's 99), a grouped aggregate inside a block (7), function calls (6), tables
     over 120k rows (3), computed sort keys (2), role references (2), objectified fact types
     (2). Each is bounded.

     **And a cost, measured.** Letting it read 230k-430k-row tables turned one corpus arm from
     19 seconds into 8,419. It reads whole tables into Python dicts, by design; the guard now
     stops at 120k rows. A check that takes hours is a check nobody runs.

107. **P for the 2026 constructs, evaluated: the reference now covers the extensions, and the
     compiler agrees with it on every recorded query it can reach.**

     The proof of concept (finding 106) covered the 1992 core and found the compiler right on
     it. Every bug the blind writers found this week was in a 2026 extension the reference could
     not reach, because no P existed for it. This round writes that P -- as an evaluator, which
     is the form in which a semantics can be checked rather than believed:

     | construct | P as implemented |
     |---|---|
     | `GROUPED BY` (binding-sql92 §4) | pending until the block is complete, then one row per group; two aggregates over one key group once (finding 97) |
     | `WITHIN` | the group's figure bound on every row; nothing collapses |
     | `THE RANK OF x WITHIN g` | SQL `RANK` -- gaps on ties -- by x descending within the partition |
     | `THE PREVIOUS x BY t WITHIN g` | the prior row's x in t's order, null at the start of each partition |
     | `OPTIONALLY` | the outer read: the row survives with the role unbound |
     | `THE FIRST n [AFTER m] PER k` | the first n within each partition of k, in the query's order |
     | item 16, a subtype named at a node | narrows on identity -- *instead of* a step when the type is already in hand, *after* one when the step reaches its supertype (`Patient is of SevereThrombosis` reaches Examination, then keeps the severe ones) |
     | item 17, `THE SUM OF s IN <path> GROUPED BY d` | the aggregate's explicit head is unified with the block's, not ranged over afresh |
     | item 27, `DEFINE` | a derived subtype's population is the *heads* of its rule; a derived fact type's is its rule's projection, role i as column i |
     | rule 12, a path into a document | read in Python from the base column, cast to the mapping's type; a path that reaches nothing is an unfilled role |
     | `DISTINCT` (§14a) | on the projection under `semantics="2026"`; where it is written under `"1992"` |

     | | covered | unknown differences | known departures |
     |---|---|---|---|
     | fixture, 79 queries | **51** (was 36) | **0** | 4 |
     | BIRD `conquer`, 99 recorded | **54** (was 43) | **0** | 1 |
     | BIRD `conquer_sem`, 99 recorded -- the `DEFINE`-heavy arm | **56** (was 26) | **0** | 1 |

     **What running it found, in order.** A bracketed operand of `AND ALSO` -- `AND ALSO [is
     of Employee]` -- was joining where §6.7 says it restricts; the fixture harness had it down
     as a *known* departure by label, and the mechanical detector (below) exposed that the
     compiler had applied no locality rule there at all. Three times the budget. `THE DISTINCT
     LIST OF g` fell through `_reduce` to `float('F')`. `MIN` and `MAX` were arithmetic where
     they are order functions. An aggregate's explicit `IN Employee …` head was a fresh range
     over all employees -- 3 x the grand total. And `Patient is of SevereThrombosis` resolved
     `is of` to an arbitrary inverse reading because the reference had no narrowing at all,
     which is the one that took two passes: the subtype is of Examination, not of Patient.

     **Two things about the harness worth more than any of those.**

     - *The known departures are now detected from the compiler's own block, not from the
       query text.* `dedupe` and `constant_in_group` on a lowered calculation are the compiler
       saying "I applied §14b here"; `tied_cut` is the reference saying "the ordered cut fell on
       rows that tie, and no engine promises which survives" (toxicology/212: `ca`, `k`, `pb`
       all at count 1). A label list is a list of things someone noticed once. A flag on the
       artefact is the artefact saying so.
     - *The `sem` arm's 50 "compiler refused" were the harness's fault.* Those answers were
       written against the semantic model -- derived subtypes, macros -- and the harness loaded
       the plain one. `corpus.py` selects the model per arm; the harness now does the same, and
       50 became 1.

     **Out of scope, with counts, `conquer` arm:** function calls in scalars (7), tables over
     120k rows (~13, the card_games family), references to a non-identifier column (4), role
     references (2), objectified types (2), a computed sort key (2), and two queries the 30-second
     budget cut off. Each is bounded; none is a semantics question.

     Suite 1,787. `conquer/conquer-2026.md` §14 states the two departures; item 36 records the
     evaluator.

108. **Section 14b, computed independently: the reference now derives aggregate locality from
     the model's uniqueness constraints, and every label-based "known departure" is gone.**

     The harness had classified a disagreement as *known* when the compiler's lowered block
     carried a `dedupe` or `constant_in_group` flag -- the compiler's own account of having
     applied section 14b. That is a masking mechanism: if the same query also differed for an
     unrelated reason, the flag would explain the whole difference away. A label list was worse
     (things someone noticed once), and one of its entries had already hidden a real bug for a
     day (finding 107's bracket that joined where it should restrict).

     The fix is not a better label. It is for the reference to **compute 14b itself**, from the
     model and nothing else: a fact type whose from-role a uniqueness constraint spans on its
     own has at most one to-value per from-instance, so a value bound through that step is
     *determined* by the instance it came from. Every stepped row now carries that provenance,
     and a `SUM` or `AVERAGE` deduplicates on it before reducing. `COUNT` is exempt, as 14b says;
     `MIN` and `MAX` are unchanged by repetition. Nothing in `reference.py` reads the compiler's
     block, so a disagreement between the two can no longer be explained by the compiler's own
     description of what it did.

     | | covered | unknown differences | known, of any kind |
     |---|---|---|---|
     | fixture, 79 queries | **55** (was 51) | **0** | **0** (was 4) |
     | BIRD `conquer`, 99 recorded | 54 | **0** | 1 -- a tie at an ordered cut, flagged by the reference |
     | BIRD `conquer_sem`, 99 recorded | 56 | **0** | 1 -- the same |

     The four fixture cases that had been "known locality" are now simply *agree*: the
     reference reached 3,600,000 and 2,400,000 from the uniqueness constraints, with no
     knowledge that the compiler had. That is the test asked for -- not that the flag is set
     where it should be, but that the two implementations arrive at the same number by
     different routes, and fail loudly when they do not.

     **What it caught on the way in.** The provenance keys were ordinary row keys, so a bracket
     whose inner path carried them looked like it *bound a name* and joined where section 6.7
     says it restricts: `financial/92` counted one per client, 2,009, where the districts number
     69. Three corpus queries flipped from agree to differ the moment the label was removed --
     which is the mechanism working: a masked difference became a visible one, and it was mine.
     Provenance is bookkeeping and is excluded from what counts as a binding.

     What remains classified rather than computed is one thing, and it is the reference's own
     flag rather than the compiler's: an ordered cut that falls on rows tying on the sort key
     (`toxicology/212`: `ca`, `k`, `pb` all at count 1). No engine and no semantics promises
     which survives, so that is not a disagreement about meaning.

     Suite 1,787.

109. **The projection fan-out caution: the case finding 58 said the checker did not cover.**

     Finding 58's conclusion was that the refusals which are the architectural argument for
     the language never fired on meaning in 143 real authoring attempts -- and that the *one*
     genuine fan trap that occurred compiled cleanly and returned 3,738 rows where the right
     shape returns 623, because `check_aggregate_locality` guards aggregates and this
     multiplied a projection. The author caught it by reading the row count. The benchmark
     review (finding 99's writers, and the BIRD record) put this first among the things
     actually holding the language back: not a missing feature, but the check we claimed to
     have not covering the case that happens.

     `--explain` now cautions when **two or more `AND ALSO` branches from one head each reach
     many per head**, using the same predicate `fans_out` uses -- `uniqueness_known` and the
     entered role not functional -- and resolving each branch's first step through the
     lowering's own resolver, so the caution cannot disagree with what compiles. It names each
     branch by what it *reaches*, since two that both begin `has Assignment` are told apart by
     `AssignmentHours` and `ProjectName`, which is also what gets multiplied; and it says the
     fix, which is the idiom the primer now teaches: continue the second branch from the first
     (`has Assignment a AND ALSO a has ...`), or gather one side with `THE LIST OF`.

     Three things it deliberately does not do. A single fanning branch stays silent -- the
     employees of each department is usually the point, not a trap. Under an aggregate it
     stays silent, because the aggregate's own caution already speaks. And it is a caution,
     not a refusal: listing pairs is sometimes exactly what was asked, and finding 58's own
     evidence is that what helps the author is being told, then looking at the rows.

     Six cases in `test_verbalise.py`: the finding-58 shape cautions and names both branches;
     one branch, two functional branches, the bound-continuation fix, and the aggregate form
     all stay silent. Spec item 37; primer trap list.

     Suite 1,791 -> 1,798.

110. **The normal form, checked against P: two ways the normaliser lied.**

     Section 8's claim is that two queries with the same normal form mean the same thing.
     The cheapest half of that claim is that a query and its own normal form do, and until
     now the only check was a round trip: normalise, re-parse, compare the lowered blocks.
     `test_reference.py` now evaluates the normal form with the reference interpreter and
     compares the rows; `reference_check.py --normal-form` does the same over the corpus.

     The first run found two defects the round trip could not see, because both were in
     text the round trip never re-parsed. `THE RANK OF` crashed the renderer (`IndexError`:
     the lowering moves a rank's argument into the window order, and the renderer read
     `arguments[0]`). `THE PREVIOUS` came out as `THE LAG OF`, from a fallback that spells
     any function it does not know as `THE <NAME> OF` -- text nothing parses. Both fixed:
     the renderer knows the two row-relative shapes (`THE RANK OF x WITHIN g`, `THE PREVIOUS
     x BY t WITHIN g`). Fixture: 63 of 63 agreeing queries mean the same as their normal form.

111. **The generated differential, and the fan-in case of 14b it found in half a second.**

     `test_metamorphic.py --reference` puts every generated query the laws suite runs to the
     reference interpreter as well. The laws are compiler-against-compiler and cannot see a
     defect both sides share; this can. On the fixture: 621 laws, 473 generated queries
     agree, and one did not: `THE SUM OF Employee has Project has ProjectPriority`, compiler
     17, reference 9.

     Section 14b as written -- the argument is determined by a node the path reaches, so the
     bag is that node's distinct values -- gives 9. The compiler's locality check keyed the
     value by its whole ancestry (`chain` walks to the head), which put Employee in the set,
     so the fan-out step landed "inside" what was keyed and nothing looked repeated. The
     spec's own example is the fan *after* the value; this is the fan *before* it, and the
     rule has no direction. Fix: the argument's keyed set is its determinant chain by the
     uniqueness constraints -- Project, and no further; Assignment is not in it, because the
     path entered Assignment on a non-unique role. The emitted SQL is the existing DISTINCT
     (determinant, value) subquery, so a value fixed by Project is added once per project.

     Two guards the corpus insisted on. A value nothing fixes (no uniqueness constraint on
     the fact type; the derived `EnrollmentDifference` in the california_schools semantic
     model is one) falls back to the row chain -- P's bag -- because deduplicating on the
     value alone is DISTINCT SUM, and the first cut did exactly that to `conquer_sem/
     california_schools/28` (49 rows became 9). With the fallback: 1,982 recorded queries,
     1 SQL rewrite, 0 answers moved. And the same ancestry mistake for *group keys* was
     tried strictly -- a key pins what it identifies and what that leads to, nothing above
     it -- and rejected: it refuses the fixture's spanning-uniqueness case and the by-name
     sum the reference computes, and the corpus has no query it would change either way.
     That is finding 112.

     Three fixture cases (`test_fanout.py`), the `listed` law rewritten to know 14b (when a
     step before the last fans and the last is functional, SUM must equal the listed
     (determinant, value) pairs added once), spec section 14b extended with the direction.

     The same run over two BIRD databases, whose models came from the reverse engineer
     rather than by hand: financial, 512 generated queries agree and 0 differ (73 outside
     the reference's scope); toxicology, 357 agree, 0 differ (70 outside). Random walks over
     ring fact types and composite identifiers, and the compiler and the interpreter written
     from the algebra do not disagree once.

112. **Tracked gap: 14b under GROUPED BY.**

     `LIST d, t FROM Employee has Department has DepartmentCode d AND ALSO has Project has
     ProjectPriority p AND ALSO THE SUM OF p GROUPED BY d AS t`: compiler ENG 11, SALES 6;
     reference ENG 9, SALES 3; likewise the average (2.2 against 3.0). The compiler reads
     the key `d` as pinning the whole chain it was reached by, Employee included, so
     Assignment's spanning uniqueness constraint looks satisfied and the sum runs over every
     row of the group. Section 14b says a priority shared by two employees of one department
     is added once.

     Refusing it instead is measured to be no better (finding 111), and computing it right
     needs the emitter to deduplicate under GROUP BY: `SUM(v)` over `DISTINCT (keys,
     determinant, v)` rows, either as a derived table (exact; conflicts with a COUNT in the
     same block that wants the rows) or as a correlated scalar per group. Until then the two
     queries sit in `test_reference.py`'s `GAPS` table: reported, not failed, and a gap that
     starts agreeing fails so the table cannot go stale. Spec section 14b names it.

113. **Refusal soundness has no data; the reference's function library bought eight queries.**

     The check as planned: a judgement refusal sits on an emission, so compile the refused
     query under `--permissive` and compare its rows with the reference under the 1992
     semantics. The mechanism is in `test_reference.py`. What it found is that there is
     nothing to feed it: the only arm that logged attempts (`conquer_logged`, 143) refused 7,
     all at the parser (finding 58), and the fixture's 5 refusals are the window functions
     without WITHIN or BY. Zero judgement refusals anywhere. Recorded here so nobody builds
     it twice; the harness reports "0 permissive emissions match P, 5 not checkable".

     The scalar function library in the reference (`round`, `substr`, `instr`, `concat`,
     `replace`, `sqrt`, `power`, `ln`, `exp`, the date parts, `if`, and the boolean
     `starts_with`/`ends_with`/`contains`/`like` conditions, all with SQLite's semantics --
     `round` half away from zero, 1-based `substr`) took the fixture from 55 to 63 agreeing
     queries with 0 unknown differences. One bug of its own on the way: the arithmetic
     dispatch was a dict of expressions, so `a ** b` was evaluated for a plain division and
     overflowed. Suite 1,798 -> 1,801.

114. **The corpus under the reference: two silent compiler defects and two of the reference's own.**

     `reference_check.py --normal-form` over the two BIRD arms, after finding 111's changes,
     left three disagreements. Ground truth from SQL run by hand settled each.

     *`thrombosis_prediction/1192`* -- `... AND ALSO is of BilirubinWithinNormalRangeLaboratory
     has LaboratoryDate d WHERE year(d) = 1991 AND month(d) = 10`. The compiler's statement had
     no trace of the subtype: a plain join to Laboratory, "any lab that month", three extra
     patients whose October lab has a NULL bilirubin. The lowering was right (a subtype node
     unified with the Laboratory node the step reached). The emitter aliased every step's
     anchor under the unification's *root* as well as the node, and when the union-find had
     settled on the subtype node -- reached by no step -- it inherited the row before the
     narrowing pass ran, which then saw nothing to do. Anchors are now borrowed from an
     anchored peer through one `borrow()`, which semijoins the CTE when the borrower is a
     derived subtype of that row; the root is aliased nowhere. Two cases in `test_derived.py`.

     *`toxicology/215`, normal form* -- `THE COUNT OF DISTINCT Atom [...]` normalises to `THE
     COUNT OF v1 IN (DISTINCT Atom v1 ...)`. The compiler read both as 97; the reference read
     the normal form as 2,982, the bag's rows. Section 14a in a nested position: DISTINCT
     inside the bag an aggregate ranges over is the aggregate's DISTINCT. Fixed in the
     reference -- and then the same rule turned out to be missing from the *compiler* where
     the bracket becomes a join rather than EXISTS: `THE COUNT OF DISTINCT Employee [has
     Department is of Employee has EmployeeSalary s WHERE s > 50000]` counted 14 rows for 6
     employees, because the bag's DISTINCT sat on the block and the flat aggregate never
     looked there. 215 only looked right because EXISTS deduplicates. Fixed in the emitter:
     eleven corpus statements gain COUNT(DISTINCT ...), none of their answers move.

     *`toxicology/239`* -- `THE COUNT OF Atom19 is connected to Atom`, a derived subtype through
     the ring. Compiler 377, SQL 377, reference 219: the reference's `step` took item 16's
     narrowing branch whenever head and target were identity-related, before looking at the
     verb, so `is connected to` became a widening that relabelled the 219 heads. Now the verb
     is resolved first and narrowing is what remains when no fact type answers.

     Corpus after all four: 1,982 queries, 13 statements changed, 1 answer moved -- 1192, to
     the six patients SQL gives. Fixture 66 agree, 0 differ; three new queries there (a DEFINE
     through the ring, twice; the DISTINCT bracket). One scope gap noted on the way: a
     comparison written into a path (`has EmployeeSalary > 50000`) is outside the reference.

115. **What determines a value: the nearest owner, and the keys a derivation rule implies.**

     Two loose ends from finding 111, both about the same word.

     *The keys a rule implies.* The california_schools semantic model derives `Frpm has
     EnrollmentDifference` from `LIST f, d FROM Frpm f has FrpmEnrollmentK12 k AND ALSO ...
     k - a AS d` and declares no uniqueness constraint on it, so the lexicon rated the step
     into it a fan-out and the value had no determinant. Two gaps. `block_key` knew a
     grouping and `THE FIRST 1 PER d` as the constructs that narrow a block to one row per
     something, and not the plainest: a block none of whose own steps multiplies its rows is
     one row per head. And `define()` inferred keys for a query-scoped DEFINE while the
     model's own rules got none. Now `lower.declare_derived_keys` does for the model's rules
     what `define` does for a DEFINE, appending the constraints to the model (so the
     reference reads them too) and declaring them to the index; the lexicon runs it on
     construction for a model that has rules. Only fact types with no constraint at all are
     touched. Corpus: 1 statement changed, 0 answers moved -- the rating was wrong and
     nothing recorded had leaned on it.

     *The nearest owner.* With the derived fact type functional, `THE SUM OF Employee has
     Department has DepartmentBudget` -- two many-to-one steps, no fan-out step anywhere --
     was the next thing the fixture and the reference disagreed on: 9,300,000 against
     3,600,000. That relation is the one finding 79's canonical case walks from the other
     end, and the compiler gave the two spellings different sums. Two causes. The locality
     check only ran when some step fanned out, and here none does: the repetition is the
     head's, which nothing on the path determines. And `determinants` walked every
     functional step upward, so Employee -- which does fix its department's budget, one
     department each -- was "keyed" and the head looked determined. Section 14b's "that
     node" is the node whose uniqueness constraint owns the value: Department for a budget,
     Project for a priority, and no further. The compiler now keys the argument by that
     owner alone and treats a head outside the keyed set as an offender for an aggregate
     over its own bag. Three fixture cases; laws 473 agree, 0 differ; corpus 0 answers moved
     -- in 1,982 recorded queries the shape does not occur, which says something about how
     writers actually phrase sums and nothing about whether the compiler was right.

     Under GROUPED BY the keys still pin by ancestry (finding 112); the head-as-offender rule
     is not applied there, where the emitter cannot yet deduplicate.

116. **The reference's reach: from 61 to 87 corpus queries in scope, and what it found on the way.**

     Finding 109's reference interpreter covered 61 of the `conquer` arm's queries and 68 of
     `conquer_sem`'s. The rest fell outside its scope for reasons the harness tallied, and
     this finding is the work of taking the tallies down one at a time. After it: `conquer`
     87 agree, 0 differ, 10 outside; `conquer_sem` 82 agree, 0 differ,
     14 outside; fixture 78 agree, 0 differ; the generated differential 565 queries,
     0 differ (from 473). Every query brought into scope agreed with the compiler except the
     ones below, each of which was a defect.

     *Large tables* (16 and 12 queries). Whole-table reads keep the 120k-row cap; a step now
     reads a table too large to load for the keys it holds (an IN list in chunks), a
     restriction with a constant pushes the constant down as one WHERE, and a single-column
     identifier read -- the head of a path -- is allowed whole up to 1.5M rows. Legality at
     427k rows is walked in two seconds.

     *Non-identifier references* (4 and 4): legalities.uuid -> cards.uuid while a Card is
     identified by cards.id (finding 34). The pairs go through a map read from the
     referenced table, and pushed-down keys go through it the other way.

     *Role references and objectified fact types* (4 and 4): `Connected has ConnectedAtom`
     leaves a fact instance by a named role; `Atom has ConnectedAtom has Bond` enters one
     by role and lands on the instance, as the compiler has it; a verb from an objectified
     head resolves through its entity twin.

     *B.2's `!x`* -- a correlated bag reading what the enclosing row bound -- and ungrouped
     aggregates beside the rows. Naively this is the bag re-evaluated per row: 40k users by
     90k posts burned every budget it was given, and the first corpus run with it sat for
     eighty minutes at full CPU. So it is decorrelated the way a planner does it: the bag is
     evaluated once with each `!x` turned into a binding, grouped by those bindings, and
     each enclosing row looks its group up; a bag reading nothing of the row is memoised.
     card_games/346 went from over ten minutes to nine seconds. Two things the memo taught:
     a `!x` inside a *nested* aggregate is that aggregate's correlation and must be left
     alone, and a memo keyed by a node's identity lives exactly one query -- one entry left
     behind by a whole-query scalar was inherited by the next query's node at the same
     address, and `THE SUM OF Employee has Project has ProjectPriority` answered 3,600,000
     once in twenty runs. Cleared before any branch now, and saved around a derived rule's
     own query.

     *Smaller*: `OR OTHERWISE` as the union of fronts; a comparison written into a path;
     computed sort keys; whole-query scalars side by side; SQLite's reading of text as a
     number ('18:56.516' is 18.0 to SUM, and text sorts above numbers), which was a crash.

     Two of the new constructs were wrong on first contact and the corpus said so. The
     union evaluated its right side from the left's *survivors*, so `[has SM: 'negative']
     OR OTHERWISE [has SM: '0']` could only re-admit the negatives -- thrombosis/1267, 5
     against SQL's 6. And the normal form spells the second alternative as a bare step, so
     the union's fronts must carry the left head's variable or the bag counting it sees
     only one side. Both fixed; both in the fixture.

     Still outside: heads over the largest tables with no constant to push (8 and 8), a
     set-operation head, one superhero verb the compiler resolves by a rule the reference
     does not have, two ties at an ordered cut (finding 83). `reference_check.py` gained
     `--progress` (a line per query, so a stall is visible) and `--db`, and the compiler's
     own SQL now runs under the same budget.

117. **14b under GROUPED BY, closed: the aggregate gets a bag of its own.**

     Finding 112 left `THE SUM OF p GROUPED BY d` over a many-to-many computing P's answer
     (ENG 11) where section 14b says 9, because a grouped aggregate renders as `SUM(col)` in
     the SELECT list and nothing in that position can deduplicate. The strict reading of the
     keys refused the query instead, which was measured to be no better. What was missing
     was a place to deduplicate, and the compiler already had one: an aggregate over a bag
     of its own is emitted as a subquery, and section 14b's `DISTINCT (determinant, value)`
     already lives there.

     So the locality check now reads the keys strictly -- a key pins what it identifies and
     what that leads to, nothing above it -- and decides one of three things for a grouped
     value aggregate. The keys pin the value's determinant: every row of a group carries one
     instance, MIN takes it (as before). Nothing repeats within a group, by the fan-out steps
     and the head alike: the plain SUM stands. Otherwise `lower.regroup_grouped` re-lowers
     the aggregate over a mirror of the block, unifies each key's node with the outer one --
     so the bag is correlated on the keys and the emitter groups it by them -- and the
     deduplication that finding 111 built applies inside; the enclosing GROUP BY takes the
     one figure per group with MIN, exactly, and the keys still group the block. The normal
     form prints what was written. COUNT keeps finding 78's exemption; WITHIN and the
     row-relative functions are windows, not bags, and keep the reading they had.

     The fixture case that asserted the refusal now asserts the answer -- each employee's
     salary once per department, which the compiler, the reference and SQL by hand agree on
     -- and the two GAPS queries of finding 112 are ordinary fixture cases (ENG 9, SALES 3;
     the averages 3.0). Corpus: 1,982 queries, 2 statements changed, 0 answers moved -- the
     shape is as rare in recorded answers as it is important when it occurs. Laws 565/0.

     Also in this batch, from the reference's remaining scope: a step may enter an objectified
     fact type named as its target (`Superhero has HeroAttribute`, `Employee has Assignment`
     -- eight more fixture queries in scope at a stroke), pair reads of tables up to 500k rows
     (cached, so a second once), a front expression as a head, and a classification for an
     ordered cut under DISTINCT by a key the list drops (`LIST id FROM DISTINCT ... ORDERED
     WITH p ... THE FIRST 4`, european_football_2/1135): which p stands for an id is
     undefined, SQLite keeps an arbitrary one, the reference cut before deduplicating, and
     neither is an answer -- it is finding 83's kind, and `--explain` now says so.

     And one more normaliser defect, found because the normal-form check now reaches the
     union shape: `(Card BUT NOT [has CardPower] OR OTHERWISE Card [has CardPower: '*']) has
     CardId id AND ALSO has CardArtist artist` was printed with the union *after* the steps,
     which reads as `((Card has CardId id ...) BUT NOT ...) OR OTHERWISE ...` -- and the
     compiler refused its own normal form, "artist is bound inside one alternative". The
     lowering now tags each operand of a disjunctive fold with the fold and its position
     (the merged base's own filters as position 0), and the normal form writes them together
     as a parenthesised front expression before the head's steps, each alternative bracketed
     -- written bare, `(Employee has Department: 'ENG' OR OTHERWISE ...)` moves the position
     to the department. The reference had the matching defect: an alternative written as a
     bare path left its rows standing at the path's end, and the step after the union found
     nothing there; a front expression's rows stand at the head. Corpus under the reference:
     `conquer` 95 agree, 0 differ, 2 outside, 2 ties at a cut, normal forms 95 of 95; `conquer_sem` 93 agree, 0 differ, 2 outside, 2 ties, normal forms 93 of 93.

118. **Ablations of reference inference: what each step of the published pipeline is worth.**

     The pipeline in "Scalable Join Inference for Large Context Graphs" (arXiv 2603.04176)
     is the one this reverse engineer already has two thirds of: statistics propose keys
     and inclusion dependencies, a score thresholds them, an LLM judges what is left. The
     harness in `bench/ablation/` switches the steps and the floors on one at a time,
     strips every declared reference before an arm runs, and compares with them after:
     1,112 references over the 18 LiveSQLBench schemas, 104 over BIRD's 11. And BIRD has a
     second, sharper measure: the 99 recorded answers of the `conquer` pilot arm, recompiled
     against a model built from an arm's references alone.

     *What was hiding in the floors.* On organ_transplant the shipped rules found 23 of 70
     references at 100% precision, and the diagnostic said why the other 47 were missed:
     30 were *found* and filed apart -- the referencing column is the table's own key
     (`inclusion-1to1`), because these schemas split an entity across tables that share its
     registry id -- and 17 sat under the significance floors (3 distinct values, 50 rows)
     or the proposal threshold (2.6), which the rules' Spider fitting had set for data of
     another shape. Counting the 1:1 shape: 34. Floors off: 66 found, 62 right. Threshold
     off too: 70 found, 65 right -- 93% recall at 93% precision. The five left are ties: a
     column contained in two tables' keys that are the *same* key domain, where data alone
     cannot say which table is meant and the declared schema chose one.

     *BIRD, sweep* (104 references): rules 77 right of 87 found (74% recall, 89%
     precision); with the 1:1 shape and the floors off, 85 of 97 (82%, 88%); threshold off
     too, 88 of 235 -- 85% recall at 37% precision. On BIRD's small integer surrogates, a
     shorter sequence nests in a longer one for no reason but that it is shorter, and the
     threshold is what had been holding that back.

     *BIRD, downstream* (99 recorded answers, 3 of which the declared model itself no longer
     runs): rules 71 same rows, 25 no longer compile; 1:1 and floors off 79 and 17;
     threshold off 57 and 39. (Corrected in finding 122. `model_with` rebuilt every reference
     onto the target's primary key, discarding the declared reference columns, so
     european_football_2's 28 references to `Player.player_api_id` were wired to `Player.id`.
     The baseline was built the same way, so the comparison was internally consistent and the
     conclusion below is unchanged; the first figures published here were 70, 26, 78 and 18.) No answer ever returns *different* rows -- an inferred model
     either agrees with the declared one or refuses -- and the loss under the relaxed gate is
     not noise but shape: a false reference between two lookup tables' ids (`alignment.id ->
     attribute`, `gender.id -> alignment`) makes them 1:1 subtypes of each other, the
     concepts merge, and `Superhero has SuperheroName` becomes ambiguous between five fact
     types. Superhero and european_football_2 lose nine answers of ten. Precision is not a
     nicety for a model the language reads; a false reference is a false type.

     *LiveSQL, all arms* (1,122 references, 18 schemas). The shipped rules: 669 right of
     1,063 found, 60% recall at 63% precision. The 1:1 shape: 695 of 1,337 (62%, 52%).
     Floors off: 822 of 1,662 (73%, 49%). Threshold off: 840 of 2,206 (75%, 38%). So
     organ_transplant's clean picture does not generalise: across the eighteen, every floor
     removed buys recall at a steeper price in precision, and the relaxed band is the
     judge's to sort. Approximate inclusion is a loss at every setting -- 1% tolerance
     takes the rules to 665 of 1,113 (59%, 60%), 5% to 647 of 1,175 (58%, 55%) -- because
     these references are clean and slack only admits coincidences. And the surprise:
     name evidence, which finding 84 measured at 3% recall *as a rule of its own*, is worth
     a great deal *as a gate on the data's candidates*: gated as `apply_references` gates
     it, 557 of 602 (50% recall at 93% precision); as a feature at threshold 2.0, 752 of
     927 (67%, 81%) -- better than the data alone at any threshold. On BIRD the same arm
     runs the other way (80 of 120, 77% at 67%; downstream 69 same rows and 27 not
     compiled, slightly worse than the rules), so it is not a free win either.

     *The judge.* The relaxed candidates -- every best-scoring containment, no floors, no
     threshold -- were handed to blind judges: one candidate file each, carrying names,
     row and distinct counts, the score and its signals, and five sample values a side, with
     the brief in `JUDGE.md`. No database, no model, no repository, no web. On BIRD they
     kept 93 of 235 candidates and 88 of those are declared references: **85% recall at 95%
     precision**, against the best statistical gate's 82% at 88% and the shipped rules' 74%
     at 89%. Downstream, the model built from the judged set runs **81** of the 99 recorded
     answers to the same rows with 15 no longer compiling -- the best of every arm (rules
     70/26, floors off 78/18, threshold off 57/39, names 69/27). Precision is what the
     downstream measure rewards, and the judge is the only step that buys recall without
     paying for it in precision.

     The verdicts read as diagnosis rather than taste, and three judges independently
     reported the same defect: a true reference proposed at the *wrong target*, which a
     judge can only refuse. `museum_artifact` has seven 1,000-row tables sharing a 1..1000
     key domain and the assignment offered one table for all of them; `organ_transplant`'s
     five rejections are a small table's `patient_ref` aimed at an extension table rather
     than the master, because the pass keeps the smallest containing key;
     `residential_data`'s judge counted 27 by hand and noted that no candidate offered the
     right parent for any of them.

     **So the misses were counted.** Of the 282 LiveSQL references the fully relaxed arm
     does not find, **216 -- 77% -- are columns it did propose, at a different target**;
     only 66 were never proposed at all. (BIRD: 6 of 16.) `compliance_detail.compliance_code`
     is declared at `compliance` and proposed at `vendor_contract_detail`; `consentrecord
     .dsr_ref` is declared at `datasubjectrequest` and proposed at a stakeholder table. The
     containment search is not the bottleneck and neither is the threshold: **the
     one-target-per-column assignment is**, and it is decided by a score that ranks a
     coincidence above the parent whose name the column repeats. Motl & Kordík gain as much
     from resolving the assignment globally as from any single feature and `_inclusions`
     already gestures at it with `preferred`; keeping the best *few* targets per column and
     letting a name-aware tie-break or the judge choose between them is the experiment this
     finding points at. It is not a change made on this evidence.

     *LiveSQL, judged.* 931 candidates kept of 2,206, and 840 of them are declared
     references: **75% recall at 90% precision**, against the shipped rules' 60% at 63% and
     the name gate's 50% at 93%. The number to look at twice is 840. The fully relaxed
     statistical arm found **the same 840** true references -- among 2,206 candidates, at
     38% precision. The judge discarded 1,275 of those candidates and lost *not one* true
     reference. Precision rose by 52 points at zero cost in recall, which is not a trade
     along the curve the thresholds sweep; it is a signal the score does not have.

     Per database the judged arm runs from 100% recall at 100% precision (archeology, 77 of
     77) to 23% at 84% (cross_border, where the schema's references are largely between
     columns that share a value domain and the assignment problem below dominates). Eight of
     the eighteen are at 100% precision.

     What the judge sees that the score does not is the *name*, read as a human reads it:
     not "does this column's name contain the target table's name" -- rule 9's test, which
     finding 84 measured at 3% recall here -- but whether `hospital_ref` beside a table of
     hospitals, `V#####` values beside a vendor registry, or `Shelf_Life_Days` against a
     1..10000 surrogate reads as a reference someone meant. The false positives it names are
     always one of four families: measurements and counts nesting in a short surrogate
     sequence, enum codes whose lookup table is not in the schema, two unrelated
     autoincrement sequences one of which is shorter, and the reverse direction of a
     reference that is also in the file.

     **What this says for the reverse engineer.** Three things, in the order they are worth
     doing. (1) The assignment, not the search or the threshold: 77% of the misses are
     columns already proposed at the wrong target. Keeping the best few targets per column
     instead of one would put the right answer in front of whatever chooses. (2) The judge
     earns its place -- but as a *filter on a generous proposal*, not as a way to find
     references, and the generous proposal is what rule 9c's floors and threshold currently
     prevent. (3) The floors (50 rows, 3 distinct values) and the threshold (2.6 / 4.25)
     were fitted on Spider and cost recall on both of these corpora; they are the right
     default for a silent rule and the wrong one for feeding a reviewer.

     Nothing here is fed back into the rules yet; the harness records what each arm finds
     (`bench/ablation/work/`), the judge's brief is `JUDGE.md`, and the README says how to
     run it again. `reverse/population.py` gains one knob, `TOLERANCE`, defaulting to the
     exact test the rules have always used.

119. **How much of ORM we actually use, measured: the flagship is dormant and the semantic
     arm ran blindfolded.**

     Two surveys, prompted by the question of whether the conceptual model earns its keep.

     *What the model carries.* The CCM admits eight constraint kinds: uniqueness, mandatory,
     frequency, ring, subset, equality, exclusion, valueComparison. Across the 118 `.ccm.json`
     models in the repository there are **29,508 uniqueness constraints and zero of the other
     seven**. We admit eight kinds and populate one. Meanwhile `reverse/population.py` has
     seven miners -- `_exclusions`, `_equalities`, `_rings`, `_comparisons`, `_dependencies`,
     `_computed`, `_aggregates` -- that find those very constructs in real data, and every one
     of them terminates as prose in a report rather than a constraint in the model.
     `model/abstract.py` implements Bird's abstraction rules 7-11 against subset, equality and
     exclusion constraints, and says in its own docstring that they never fire. The gap that
     matters is not ORM against our metamodel; it is our metamodel against what we populate.

     *What the compiler actually uses.* Measured over the 1,982 recorded corpus queries:

         readings / verbalisation      every query (the only interface writers had)
         objectified fact types        122 queries
         reference-scheme expansion    100 queries
         derived subtypes / fact types  45 (all in the semantic arm's 99)
         subtype narrowing              11 (10 of them derived)
         section 14b deduplication       6
         constant_in_group               0
         the fan-out refusal             0
         confluence EACH                 0, so the mandatory constraint has never
                                         once chosen a join in measured use

     The uniqueness machinery is the project's flagship and the argument for the whole
     approach. It fires on 6 of 1,982 queries and has never moved a recorded answer; findings
     79, 111, 112 and 117 each fixed real arithmetic on a fixture and each reported zero
     answers moved. The fan-out refusal has now measured zero three independent ways (findings
     44, 58, 113), and both attempts to widen it measured as harmful (78: 20 right answers
     rejected for 5 wrong; 79: net -1). The mandatory constraint's only consumer is
     `lower.outer_for`, reached only from `EACH`, which appears in no recorded query at all.
     The one conceptual feature with a measured score movement is derivation rules, +8, and
     finding 43's control showed the credit belongs to writing the definitions down rather
     than to the model or the compiler.

     *And a defect in the apparatus that measured it.* Every base model carries value domains,
     1 to 42 per database, 150 in all. **Every semantic model carries zero, and not one of the
     11 `schema-sem.txt` materials has a "Value domains" block.** The semantic models were
     merged from a base built before `bench/run.sh` gained `--infer-domains` and were never
     rebuilt; replaying the merge against today's base restores 18, 42 and 23 restrictions to
     thrombosis_prediction, card_games and california_schools. So `conquer_sem`, the best arm
     we have and the source of the +8, ran without the one thing that tells an author how a
     filter must be spelled, and without the +2.0 `link.py` scores when a question's literal
     matches a known domain. Finding 42 measured value domains at zero effect over 1,086
     queries and concluded the emitter never reads them; that is true, but it was measuring
     the arm where they were present and the emitter is not where they would help. They have
     never been tested where they would: in the semantic arm, in the listing the author reads.
     The models are outputs and rebuilding them in place would re-attribute recorded answers
     to materials nobody saw, so this wants a new arm beside `conquer_sem`, not a rebuild.

     *Fixed here.* `model/forml.py` read a constraint's `ringType`, `min` and `max` while
     `ccm.schema.json` defines `ringKind`, `minFrequency` and `maxFrequency` and forbids any
     other property, so every schema-valid ring and frequency constraint verbalised to the
     empty string and was dropped without a word. Three of the eight kinds could not have been
     verbalised even if something produced them. The verbalisers themselves were right; only
     the dispatcher was wrong. Two regression cases in `test_forml.py` now go through
     `verbalize_model` rather than calling the verbaliser directly, which is why the existing
     cases never caught it.

     Also fixed: `population._inclusions` built its target list from the primary key and the
     unique constraints without deduplicating, so a table declaring both offered the same
     target twice and every containment against it was tested and recorded twice. Callers
     deduplicate, so no published number moves; it doubled the EXCEPT queries, which are the
     expensive part of the pass.

120. **The assignment fix: pick the right target, do not keep more of them. And the seven
     miners finally reach the model.**

     *Where the right target actually sits.* Finding 118 left the question open: 77% of the
     references the search misses are columns it did propose, at another target, but is the
     right one second in the ranking or eleventh? `refs.py rank` records every containment per
     column and `assign.py` answers it offline. Over the 18 LiveSQLBench schemas the declared
     target is rank 1 for 74% of references, rank 2 for 6%, rank 3 for 4%, and somewhere in
     the list for 96% in all. Only 26 references are absent from their column's candidates and
     66 have no candidate for the column at all. **The search is not the problem.**

     *And the shortlist is not the fix.* Keeping the best three targets per column instead of
     one takes recall from 74% to 84% and precision from 35% to 17%. Ordering the candidates
     by **name evidence** instead, still keeping one, takes recall to **86% at 41% precision**
     -- better than a shortlist of three on recall and two and a half times better on
     precision. Picking better beats keeping more, on both axes at once.

     So the assignment now orders by the name the column carries, with the score breaking its
     ties: the highest of the column's similarity to the target table, to its stem, and to the
     target key's name. Measured end to end, on both corpora and both axes at once:

         LiveSQLBench, 1,122 references        before          after
           the shipped rules                   60% / 63%       67% / 81%
           floors off                          73% / 49%       82% / 67%
           fully relaxed                       75% / 38%       86% / 44%
         BIRD, 104 references
           the shipped rules                   74% / 89%       76% / 94%
           floors off                          82% / 88%       84% / 93%

     The relaxed arm now recovers 962 of LiveSQL's references where the blind judge recovered
     840 (finding 118), because the tie-break settles the assignment the judge could only
     refuse: shown a candidate at the wrong target, a judge says no and the reference is lost
     either way. BIRD's floors-off arm at 84%/93% is within a point of that judge's 85%/95%
     with no model in the loop. Corpus: 1,982 recorded queries, 0 changed.

     The lesson is the one the judge taught, arrived at twice. Finding 84 measured a *name
     rule* at 3% recall on these schemas and concluded names were worthless here; the data
     path has ignored them ever since. But that measured names as a way of *finding*
     references. As a way of *choosing between* containments the data has already proven, the
     same evidence is worth 134 references. Names are decisive for choosing and useless for
     finding, and the judge's whole contribution was reading them the way a person does.

     *The seven miners.* `population.apply_constraints`, behind `--infer-constraints`,
     promotes the exclusion, equality, value-comparison and ring findings from prose into
     `model["constraints"]` -- slots the CCM has admitted since it was written with nothing
     ever producing one (finding 119). On BIRD it states two constraints no schema states:
     `Examination.KCT` and `RVVT` always recorded together, and `District.A12` with `A15`.
     Both are real: two halves of one measurement, and unemployment for two years missing for
     the same districts.

     Every promoted constraint is **deontic** (ORM 2 section 1.7), and that is the point
     rather than a formality. A declared constraint is a law the data cannot break and a
     compiler may reason from; one recovered from a population says only what today's rows do.
     The flag is what lets a consumer report one without optimising on it. `modality` is now a
     field on the CCM constraint, defaulting to alethic.

     And the loop is closed at the reading end, which it was not: `forml.py` had verbalisers
     for uniqueness, mandatory, frequency and ring only, so exclusion, equality and value
     comparison would have reached the model and been unreadable. `set_comparison` and
     `value_comparison` are section 4's forms, and the dispatcher now passes modality, so a
     promoted constraint reads "It is obligatory that for each Examination, that Examination
     has KCT if and only if that Examination has RVVT." Three cases in `test_forml.py`.

121. **Path-scoped value constraints: the premise does not hold, and the measurement says so
     before the building starts.**

     The case for conditional value constraints was that value semantics are what BIRD's
     evidence strings mostly carry, that a value domain is the machine-readable form of one,
     and that finding 119 had just shown the semantic arm running with none. Three
     measurements, none of which needed new code.

     *How much of the benchmark could care.* Eighteen of the 100 questions name a quoted
     literal that some value domain in their database holds. That is the whole population a
     value constraint could help, conditional or not.

     *Whether having them helped.* Accuracy on those 18 against the other 82: `direct`, which
     sees no domains at all, 67% against 71%. `conquer`, which sees them, 61% against 73%.
     `conquer_sem`, which finding 119 showed sees none, 56% against 63%. The arm *with* the
     domains does worse on the domain questions than the arm without. At n=18 none of these
     gaps is more than a question or two, which is the point: the effect is not there to find.

     *Whether the failure they prevent ever happens.* A misspelled filter value has a
     signature: the query runs and returns nothing where the gold returns rows. Across all
     3,000 scored rows that signature occurs **three times, and not once on the eighteen
     questions that name a domain value** -- including in `conquer_noev`, the arm given no
     evidence hint, which is where a writer would have to guess the spelling unaided. BIRD
     quotes its literals and the quoted string is the stored value.

     So value domains solve a problem this benchmark does not contain, and a *conditional*
     value constraint would be conditional machinery for a problem whose unconditional form
     has zero measured incidence. Finding 42 measured domains at zero effect on emitted SQL
     and concluded the emitter never reads them; the honest completion is that they have no
     measured effect on authoring either. This is not an argument that ORM's value
     constraints are worthless -- on a schema of undocumented status codes, with a question
     that does not quote them, they would be the whole game. It is an argument that we cannot
     demonstrate it here, and should stop citing the +8 semantic-layer result as evidence for
     them: finding 119 shows that arm never had them.

     Finding 119's defect stands and is still worth fixing, because a benchmark apparatus
     that silently drops an input is a measurement bug whatever the input turns out to be
     worth. It no longer justifies an arm of its own.

122. **The control arm earned its keep on its first run.**

     The authoring experiment builds three models per database differing only in which
     references they were built from, and the first writer to finish -- the *declared* arm,
     the control -- reported that six of its ten answers were "correctly shaped but crippled
     by a broken link": `PlayerAttribute has api Player` was joining `Player.id` to
     `player_api_id`, so 119 of 11,060 players matched.

     It was right, and the fault was mine rather than the model's. `downstream.model_with`
     rebuilt each reference as `(column -> the target's primary key)`, discarding the
     reference columns the catalogue declares. european_football_2 declares 28 references to
     `Player.player_api_id` while Player is keyed on `id`; card_games declares 4 to
     `cards.uuid` and `sets.code`. Finding 34 is the same shape, met from the other side.
     Fixed: the declared reference columns are used wherever the catalogue declares that
     triple, and the target's key only as a fallback for an inferred one.

     Two things worth keeping from it. The downstream measure survived, because the baseline
     was built by the same broken function as the arms, so the comparison was consistent even
     while the models were wrong; the totals moved by one answer (finding 118, corrected).
     And the control arm did what a control is for. Six agents were stopped, two answer files
     discarded and the run restarted, which is cheaper than believing the result.

     *And the same bug's other half, found by another writer.* An inferred reference is a
     (table, column, target) triple with no target *column*, because that is all the ablation
     records. Where the target has two single-column keys, that is a choice: `sets` has `id`
     and `code`, and `cards.setCode` means `code`. Taking the primary key wired it to `id`,
     the join matched nothing, and the card_games writer bridged around it through
     `SetTranslation` and said so. Now chosen by the same name evidence that settles the
     assignment itself (finding 120): the key whose name the source column most nearly
     carries, primary key as the fallback. It affects exactly one reference in one of the
     three databases -- european_football_2 and codebase_community have no ambiguous target
     at all -- so six of the nine writers stand and two were re-run.

     The pattern in both halves is worth naming. Neither defect was in the compiler, the
     inference, or the model. Both were in the harness that builds an experiment's inputs,
     both made an arm look worse than it is, and both were found by an agent reading its own
     row counts rather than by any test in the suite.

123. **A DEFINE's computed column was typed `text`, and a number compared against it
     silently returned nothing.**

     The second defect the authoring experiment found, and the second found by a writer
     reading its own row counts rather than by any test. `DEFINE Taxed ::= LIST e, t FROM
     Employee e has EmployeeSalary s AND ALSO (s * 2) AS t`, then `... has Taxed TaxedT v
     WHERE v > 200000`: four rows are right, zero came back.

     `lower.define` mints a value type for a computed column, because nothing in the model is
     its type, and declared it `{"dataType": {"name": "text"}}`. That is not a neutral
     default. `lower.constant_value` takes a literal's SQL type from the value type it is
     compared with, so 200000 was bound as the string `'200000'`, and SQLite orders every
     number below every string -- the comparison is not an error, it is simply always false.

     The fix is to declare no type at all. `constant_value` already falls back to the
     literal's own kind when the concept has none, and its comment records this same bug
     being fixed once before for an aggregate's result: "Falling back to text bound
     `COUNT(..) > 1` as the string '1'". The same mistake, made twice, in the two places the
     compiler invents a value it cannot type. Two cases in `test_derived.py`, one numeric and
     one textual, so the fallback is pinned in both directions.

     Worth noting what found it. The corpus differential cannot: every recorded answer
     compiles to the same SQL as before, because no recorded query uses a DEFINE this way.
     The reference interpreter cannot: it agrees with the compiler, both reading the same
     fabricated type. Only running a query and looking at the rows finds this class, which is
     what an author does and what finding 58 said about the one real fan trap that escaped.

124. **Walking a reference does not check that the referenced instance exists.** (Closed by
     finding 126.)

     A third thing an authoring writer found by reading its own row counts, and the one I am
     recording rather than fixing.

         LIST f FROM Legality has LegalityFormat f AND ALSO has Card c
                AND ALSO c OPTIONALLY has CardPower p

     returns 427,907 rows. The inner join returns 427,835. The 72 extra are legalities whose
     `uuid` matches no card. Adding any required use of `c` -- `c has CardId i` -- makes the
     compiler join `cards` and the count becomes correct, which is how the writer found it
     and what it worked around.

     The `OPTIONALLY` is a red herring and sits correctly on its own step. The cause is that
     `Legality has Card c` reaches Card by *reading the reference column*, and `Context.step`
     says of an exit that it is "a column read in the row already in hand: never a join". So
     node `c` is anchored on `legalities.uuid` and nothing ever joins `cards`. The emitter
     does assert the fact exists -- it adds `uuid IS NOT NULL` -- but existence of the
     *referenced instance* is never checked. Only a later step that needs a column of the
     target forces the join that incidentally checks it.

     Under ORM the fact type's population is the set of (Legality, Card) pairs, and a uuid
     naming no card is not a pair, so the inner join is the right reading and this is a silent
     wrong answer. It is invisible whenever referential integrity holds, which is why no test
     has ever caught it: SQLite does not enforce declared foreign keys, and both benchmark
     corpora are full of violations nobody declared broken.

     **Closed in finding 126.**

     Why it was left open at first. The fix is to join the target table on any reference
     traversal, or to add an EXISTS, and that is a join per traversal on every query that
     walks a reference without reading the far side -- which is a large share of them. The
     cost is real and the benefit only appears on dirty data. It also interacts with finding
     34's non-identifier references and with the absorption logic that finding 101 fixed. It
     wants measuring with `corpus.py --rows` before it is chosen, not a patch at the end of a
     long session.

125. **Model quality costs an author, and it costs them quietly.**

     The question the project never measured: a semantic layer is worth +8 (finding 43) and
     the language itself is worth roughly nothing against SQL (the head-to-head), but what is
     *model quality* worth? Three arms, the same 31 questions over three databases, the same
     primer and the same writer, against three models differing in one thing only -- which
     foreign keys they were built from. Declared, what rule 9c infers, and what a blind judge
     kept of a generous proposal (finding 118).

         arm                 answered   correct   wrong rows   failed loudly
         declared               31        25           6             0
         rules                  31        21           8             2
         judged                 31        20          11             0

     Thirteen to sixteen points, and the ordering is the one the reference measurements
     predict: declared above both inferred models, and the two inferred models within one
     answer of each other. Per database it tracks the references each model has --
     card_games 7 against 5 and 5, codebase_community 9 against 7 and 7,
     european_football_2 9 against 9 and 8.

     The two arms that differ on paper barely differ in practice. The judge recovers more
     references than the rules do and scores one answer lower, which at n=31 is nothing. What
     separates both of them from the declared model is not how many references they have but
     *which*: card_games loses the same two questions under either, because neither inferred
     model carries the Card-to-Legality reference that both writers reported working around.

     **Not one query failed to compile, in either arm.** The entire cost of a worse model is
     paid in wrong rows. That is the project's own thesis arriving from an unexpected
     direction: a missing relationship does not stop an author, it makes them write something
     else that runs. The writers said so themselves without being asked -- one reported that
     `postLinks.PostId` was unreachable and it had correlated through a different column
     instead; another that there was no Card-to-Legality reference and it had written a
     correlated subquery on the uuid. Both produced a query. Both produced the wrong rows.

     What this does and does not license. It says reference inference is worth roughly a
     point of execution accuracy per three references recovered, on this sample, which makes
     the assignment fix of finding 120 -- worth 134 references on LiveSQLBench and 12 points
     of recall -- the most valuable thing measured in this stretch. It does not say either
     inferred model is bad: four or five questions at n=31 is a wide interval, and these are
     the best inferred models we have. And it does not rank the judge against the rules;
     those two are a single answer apart and this sample cannot separate them.

     The honest reading is that the gap between inferred and declared is real, material, and
     paid in silence, and that closing it is where the effort belongs. Note also what the
     inferred arms cost in *time*: a card_games writer spent 3 to 10 minutes per query on uuid
     correlations because its model had no index-backed reference to correlate through. A
     missing relationship is not only a wrong answer, it is a slow one.

126. **Finding 124 closed: the referent check, chosen by measuring three options rather than
     arguing them.**

     The defect: reading a role that reaches an entity gives an instance identified by the
     values in hand, and nothing checks that instance is in its own table. It is invisible
     wherever referential integrity holds -- and it does not hold. **11% of BIRD's declared
     single-column foreign keys have dangling values**, 1% of LiveSQLBench's; formula_1's
     three worst carry 342, 239 and 198 rows.

     Three options, all implemented behind one switch and measured over the 1,982 recorded
     queries rather than reasoned about:

         option                     SQL changed   answers moved   timed out   suites
         EXISTS semijoin               1192            1             13        pass
         inner join, first cut         1192            6              1        FAIL
         inner join, reusing joins      386            1              1        pass

     `EXISTS` was the one I expected to win: a true semijoin, and on a single microbenchmark
     the fastest of the three. Over the corpus it is the expensive one -- a correlated
     subquery per traversal, on columns that are usually unindexed, timing out thirteen
     queries that ran before. The join is cheaper and just as safe, because it joins on the
     target's *identifying* columns, which are unique, so it filters without multiplying.

     Its first cut failed `test_operators` by emitting a join the query already had. Giving
     it the same `join_keys` shape the enter branch uses collapses the two -- a later step
     that joins the target on its identity *is* the existence check -- and that alone cut the
     statements touched from 1,192 to 386. The one remaining timeout is not the check's:
     `codebase_community/584` aborts at 120 seconds with the check off as well.

     And the one answer that moves is a correction. `card_games/416` asks what percentage of
     cards without power are in French; it returned 12.976095 and now returns
     **12.975290**, which is exactly what the gold query returns, because the gold
     inner-joins `cards.uuid` to `foreign_data.uuid` -- the very check this adds. A silent
     wrong answer, in the recorded corpus, fixed by the fix.

     `CONQUER_REFERENT` keeps all three so the comparison can be re-run; the default is the
     join. A fourth option -- check only the references the data shows to be violated, which
     `population.py` could already detect -- stays unbuilt, because the measured cost of
     checking them all is one pre-existing timeout and 386 statements that answer the same.
     It would trade correctness-by-construction for an optimisation nothing asked for.

127. **The feature gaps the writers reported were not gaps. One was, and it is why they
     thought so.**

     Nine authoring writers (finding 125) reported two shapes as inexpressible. Both are
     expressible, and testing them is how the real defect surfaced.

     *"No `IS NULL`, and `BUT NOT` cannot sit inside `OR OTHERWISE`."* SQL's `power IS NULL OR
     power = '*'` is `BUT NOT [has X] OR OTHERWISE [has X: '*']`, which parses and answers
     correctly; so does `BUT NOT [has X p WHERE NOT p = '*']`, which one writer found for
     itself. Only the *bracketed* form, `[BUT NOT ... OR OTHERWISE ...]`, is refused. Three
     working idioms, none of them in the primer.

     *"The top group plus its members needs a correlated subquery to project, which it
     cannot."* It needs a `DEFINE` and a comparison against the maximum, and then it is three
     rows matching SQL exactly.

     *And the real defect underneath.* The natural way to write that definition keys it on a
     **value type** -- list the department *code* and the count -- and heading a path with a
     value type refused outright: "cannot anchor node: its concept has no table in the
     mapping". A value type has no table, and `anchor_value` cannot help either, because the
     type is carried by its own fact type *and* by the derived one, which it reports as two
     populations and declines to choose between. But the step says which is meant: the value
     is the role it is about to enter by. `Context.value_head` now ranges over that role's
     own table and stands on its column. `THE MAXIMUM DepartmentCode has Busy BusyN` answers;
     so does the whole shape it was blocking. Two cases in `test_derived.py`, corpus
     unchanged at 2,075 queries.

     Both writers wrote the value-keyed version first, because it is the obvious one, and
     both concluded the language could not express the question. That is the shape of every
     gap found today: not missing expressiveness, but a refusal that does not lead to the
     form that works. The two idioms are now in the primer, where the suite executes them.

     Suite 1,821 -> 1,825.

128. **Re-scoring the whole benchmark, and the caution it turned up: a path that folds back
     on itself.**

     The first full re-score in a while, 30 arms and 3,000 recorded answers recompiled
     through the current compiler. Six questions changed and the net is +3.

         conquer_dc_opus  card_games/416          wrong -> ok    the referent check (126)
         conquer_sem      thrombosis/1192         wrong -> ok    the anchoring fix (114)
         conquer_noev     codebase/604            timeout -> ok  the referent join prunes
         conquer_run2     card_games/344          timeout -> ok  likewise
         conquer_noev     codebase/672            timeout -> wrong
         conquer_abstract superhero/796           ok -> wrong

     The last is not a regression, and finding out why was the useful part. Every compiler
     state produces the same 3,738 rows for it, including the pre-session one: the recorded
     "6 rows, correct" came from a compiler older than any of today's work. **The score file
     was stale and had been hiding a broken question.** The corpus differential could not
     catch it either, because a baseline re-recorded after each change makes that change
     invisible to the next comparison, and today's baseline was re-recorded five times. The
     lesson is that the differential guards against *drift* and the scorer against *rot*, and
     only the scorer was overdue.

     *What 796 exposes.* `Superhero [...] has Attribute a AND ALSO a is of HeroAttribute has
     HeroAttributeAttributeValue v` enters HeroAttribute twice -- once from the hero, once
     from the attribute -- and nothing says the two rows are the same. So this hero's
     attributes are paired with every hero's rows for those attributes: 3,738 where 6 are
     right. `--explain` said nothing at all. The finding-109 caution looks for two fanning
     branches from one head; this is one branch folding back on itself, which no check saw.

     Measured before building it, which is the point: the signature occurs in **2 of the
     2,075 recorded answers and both are wrong**, against a 70% base rate. A caution firing
     at 0.1% is worth reading, where the mandatory RISK at 79% is wallpaper (finding 119). So
     it is a caution and not a refusal -- finding 78 measured that refusing more costs 20
     right answers for every 5 wrong -- and it names the fix: reach the fact type once and
     continue from it. Two cases in `test_verbalise.py`. Suite 1,825 -> 1,827.

129. **Where an absent value sorts was the backend's decision, not ours.**

     Diagnosing q37 turned this up. Its gold answers "the school with the lowest excellence
     rate" with a school whose rate is **NULL** -- `NumGE1500` is null and `NumTstTakr` is 0 --
     because SQLite sorts nulls first ascending and the gold's `LIMIT 1` takes whatever comes
     first. Our answer, the lowest *defined* rate, is the defensible one; the gold is a
     benchmark defect, and q37 joins q234, q349 and q1404 in that category. But it exposed
     something of ours.

     We emitted a bare `ORDER BY`. Null position is not standardised: SQLite sorts nulls
     first ascending, PostgreSQL sorts them last. So the same ConQuer query returned
     different rows on different backends, silently, and this compiler has had a PostgreSQL
     dialect since the LiveSQLBench work. ConQuer's semantics are total -- reading a role
     asserts the fact holds -- so a null reaches an ordering key only through `OPTIONALLY`,
     which is why nothing caught it: rare, and invisible on the one backend we test.

     Now said explicitly, `ASC NULLS FIRST` and `DESC NULLS LAST`, pinned to the order every
     recorded answer was written against and that `reference._sortkey` already computes.
     440 of the 2,075 recorded statements change and **0 answers move**: identical where it
     was defined, pinned where it was not, and the two backends now agree. Two cases in
     `test_operators.py`.

     *And three semantics changes measured and rejected.* The pattern is worth stating
     because it recurs. Asked whether ConQuer could choose better for the writer, I tested
     the two obvious defaults over every recorded answer:

         proposed default                      fixes   breaks
         THE COUNT OF means distinct             0        1
         a cut keeps every row tied at the cut   0       16
         check the referent exists (126)         1        0

     Only the correctness fix wins. The others lose, and the reason is structural: gold is
     written in SQL, so it encodes SQL's defaults, and any default we move away from SQL's
     moves away from gold. A different default can only win where the *question's* intent
     differs from SQL's -- and the question's intent is what the gold author wrote in SQL.
     Changing defaults is not a lever on this benchmark, whatever it might be worth to a
     human writer.

130. **Case was the backend's decision too, and the reference disagreed with the compiler
     about it.**

     Finding 129 asked where nulls sort; the same question applied to string matching found
     something worse. `LIKE` ignores ASCII case in SQLite and respects it in PostgreSQL and
     DuckDB, so `like(name, 'ada%')` found Ada Lovelace on one backend and nothing on
     another. And `starts_with`, `contains` and `ends_with` were built on `LIKE` in SQL while
     the reference interpreter implemented them with Python's `startswith`, `in` and
     `endswith` -- case-sensitive. **The compiler and its own oracle gave different answers**,
     and the reference check never caught it because no corpus query differed in case.

     Measured first: of the 42 distinct recorded answers using one of the four predicates,
     **0 change** under case-sensitive matching. The corpus is compatible with either
     convention, so the choice is free and should be made on merit rather than on cost.

     Pinned to **case-insensitive on every backend**, which is what SQLite and
     `reference._like` already did, spelled `ILIKE` on PostgreSQL and DuckDB. `=` remains the
     exact test, so nothing is lost: a writer who wants case to matter has an operator for it.
     The reference's three predicates now casefold, and compiler and oracle agree on all four.
     0 of 2,075 recorded statements change on SQLite. Four cases in `test_operators.py`.

     *An implementation note worth keeping.* The first attempt made the three predicates
     case-**sensitive** with `substr`/`length`/`=`, which is the other defensible choice. It
     failed on binding counts: those templates use `{1}` twice, and the emitter binds one
     parameter per argument, so the placeholders outran the bindings -- the same shape as
     finding 97. A template may not repeat a placeholder that carries a parameter until
     `render_call` renders each occurrence separately. That constraint is undocumented and
     cost an hour; it is written here so the next template does not rediscover it.

     *The audit that prompted this.* Everything else the dialects disagree about is already
     handled: `DIALECTS` patches `castNumber`, `divide`, `div`, `round`, `instr`, the date
     parts, `median`, `list` and the JSON path per backend, and the lenient date normaliser's
     SQLite-only `GLOB` never reaches PostgreSQL because that dialect overrides the date
     templates outright. Null position and case were the two that had escaped, and both were
     invisible for the same reason: we test on SQLite, and SQLite is the one that differs.


131. **Join elimination: a quarter of every join this compiler emits was doing nothing, and
     the conceptual model is what licenses dropping them.**

     Finding 81 measured Malloy eliminating a join this compiler emitted, and filed it under
     Malloy's column. This closes it, and the interesting part is *why* ORM can close it when
     SQL cannot.

     A path step across a reference emits a join that does two separable jobs. It **fetches**
     the far row, and it **filters** the near row out when no far row is there. Both are
     sometimes dead weight:

         fetching   `Employee has Department has DepartmentCode` joins `department` to read
                    `dept_code` -- which IS the column the employee row points with. The
                    value was already in hand before the join.
         filtering  `AND ALSO has Department` joins `department` to prove a department is
                    there. Where every employee's code is a real department, it proves what
                    was already true (this is finding 126's referent check, all of it).

     Surveyed over the 2,075 recorded corpus statements before building anything: of 1,984
     inner joins, **298 use their alias nowhere but in their own ON condition** and **209 use
     it only to read a column the ON already equates**. A quarter of them, in 19% of queries.

     *The half SQL cannot assume.* Dropping the filtering job is only sound if the reference
     holds over every row, and a declared foreign key does not say that -- SQLite does not
     enforce one, and 28% of the declared single-column keys in a 90-database Spider sample
     are contradicted by their own rows. So the mapping gets a new roleMap property,
     `enforced`, and the reverse engineer sets it by running the query that settles it.
     `_violations` has been running exactly that query since it was written and throwing away
     every answer that came back clean; now the clean answer is kept as a `satisfied` finding
     and `--infer-enforced` writes it onto the roles.

     Across the eleven BIRD databases, **93 of 105 declared single-column foreign keys are
     upheld and 12 are not** -- 11%, which is the same number finding 124 measured from the
     other direction, arrived at independently.

     *The half the conceptual model contributes.* Dropping the fetching job needs two more
     things, and both are questions about the model rather than the data. The columns entered
     by must be the fact type's identifier, so at most one far row matches and dropping the
     join drops no multiplication. And **every role of the fact type must map within those
     same columns**, so nothing reachable through the node lives anywhere but on the near
     side: `Department has DepartmentCode` passes, `Department has DepartmentName` does not,
     and the compiler can tell them apart by reading the roleMap. A relational optimiser
     cannot ask that question, because it has no fact types to ask it of.

     *What it does.* Over the corpus, with `enforced` applied to copies of the eleven models:

         statements that change                        1,597 of 2,075
         inner joins                                   2,060 -> 1,517  (-543, 26%)
         compile/refuse flips                          0
         answers that moved                            **0**, over 1,580 recorded answers
                                                       re-run both ways; 17 statement pairs
                                                       exceeded the 25s cap on one side or
                                                       the other and 0 of those was a new
                                                       SQL error

     On the company fixture the same change takes 19 statements from 14 inner joins and 2
     existence probes to 5 and 0. And the **reference interpreter agrees**: 94 of 94
     checkable queries, 0 DIFFER, against the enforced model -- which means something,
     because `reference.py` never reads the mapping and computes the answer with no notion of
     a join at all.

     *The gate is the whole thing, so the test proves the gate.* `test_elision.py` builds a
     copy of the fixture database with one employee pointed at a department that is not
     there, and asserts both halves: the reverse engineer refuses to mark that reference, and
     marking it anyway moves the answer from 6 rows to 7. Without that case every other case
     in the file would still pass with the `enforced` check deleted. Suite 1,839 -> 1,853.

     *And what it is worth, which is less than the join count suggests.* It moves no
     benchmark answer, and was never going to: an eliminated join returns the same rows by
     construction. The hoped-for payoff was time, because findings 126 and 128 record four
     questions whose only defect was a timeout. Timed over a 154-pair sample, both statements
     run back to back: **34.2s before, 32.0s after -- 93%**, and **not one pair had the old
     statement hit the cap where the new one did not**. So a quarter of the joins are worth
     7% of the time, because the joins that go are the cheap ones: a functional join to an
     indexed key is close to free, which is exactly why it was safe to drop. The queries that
     actually time out are rarer than one in six and the sample missed them.

     That is a real result and not a disappointment. 543 joins that cannot change an answer
     no longer appear in the SQL a reader has to check, and the mechanism -- the model saying
     which joins are redundant, where a planner cannot know -- is the part worth keeping. But
     anyone reaching for this to fix a timeout should measure that timeout first.

132. **Would a better CLI help? The one arm that logged its own invocations says no, and
     says what would.**

     Asked directly, and answerable without new agents: the `conquer_logged` arm wrapped its
     `try` script in a logger, so every invocation the writer made over 100 questions and 11
     databases is on disk in `attempts.jsonl`. 148 of them.

         questions                                                 100
         try-invocations                                           148   1.48 per question
         recorded answers the writer had run through the CLI    100 of 100
         invocations that were not the answer finally recorded      48
           of those, refused by the compiler                          7
           of those, compiled and ran and were discarded anyway      41

     So the CLI is used for everything -- not one answer was recorded without running it --
     and the compiler's refusals are on the path **7 times in 148**. The writer's loop is
     write it, run it, *look at the rows*, decide. Four times in five, what makes them
     discard a query is the rows it printed, not the message it did not print.

     *And iterating does not rescue an answer.* Attributing each invocation to the question
     it preceded:

         tries        n      ok    wrong rows    failed loudly    accuracy
         1           73      57        16              0            78%
         2           16      11         5              0            69%
         3 or more   11       5         6              0            45%

     Causation runs both ways here -- a hard question draws more tries and is also likelier
     to be wrong -- so the ordering is not the finding. **The zero column is.** Nothing failed
     loudly at any try count. The writer stops when the query runs, and running is not being
     right: 16 of the 27 misses were wrong on the first and only attempt, with the CLI
     reporting nothing amiss because nothing was amiss as far as it can tell.

     The whole benchmark says the same thing at scale. Of 984 non-ok answers across 30 arms,
     **13 are loud failures -- 1.3%**. Every other miss is a query that compiled, ran, and
     returned the wrong rows.

     *So what would help.* Not the command surface, and not better refusal messages either:
     both are on the path to about 5% of invocations and to none of this arm's misses. The
     only CLI change with leverage is one that makes a **running** query look wrong -- and
     the project already knows the shape, because finding 128 built one. A caution that fires
     on 0.1% of queries and is right when it fires gets read; the mandatory-role RISK that
     fires on 79% is wallpaper (finding 119). The two candidates that have never been tried
     where they would matter are the value domains, which finding 119 found missing from
     every semantic material and which tell a writer how a filter must be spelled, and a
     row-count sanity line, which is the thing the writer is already staring at.

133. **The arity brief: the cheapest lever on the list, measured, and it loses.**

     Finding 132 said the only CLI change with leverage is one that makes a *running* query
     look wrong. The arity check looked like the best candidate on the whole failure
     breakdown: projecting the wrong number of columns is fatal by construction -- the tuples
     cannot match -- it accounts for **108 of the ~953 recorded misses**, three of them in the
     best arm, and it is the one failure class checkable from the question text alone, with no
     gold, no database and no model.

     So: `conquer_dc_opus` again, same strategy, same writer, same materials, same compiler,
     with one paragraph added to the brief telling the writer to count the things the question
     asks for and check the `LIST` has that many.

         arm                  ok     wrong      arity matches gold
         conquer_dc_opus      78       22              97
         conquer_dc_arity     75       25              97

     **Zero questions fixed, three broken.** And the arity itself did not move: 97 either way.
     The brief fixed one arity (toxicology q215) and broke another (financial q128).

     *Why fixing the arity did not fix the answer.* q215 asks for iodine and sulfur counts.

         control       (97,)        one column, wrong
         arity brief   (3, 94)      two columns; iodine exactly right, sulfur 94
         gold          (3, 77)

     The brief did precisely what it was told to do and the answer is still wrong, because the
     sulfur count has a different defect. **Arity mismatch is a marker of having misread the
     question, not the cause of the wrong answer.** A writer who miscounts the columns has
     usually also misread what goes in them, which is why the 108 misses are real and fixing
     their shape recovers none of them.

     *And deliberating about it costs something.* On q128 the control returned
     `('Brno - mesto', 75)` and was right. The brief's writer returned `('Brno - mesto',)` and
     said why in its own report: "128 lists the districts only, since 'the number of female
     account holders' reads as the sort key rather than a second column." Told to think about
     how many things the question asks for, it thought, and thought its way out of a correct
     answer.

     *What the -3 does and does not establish.* The other two breakages (card_games q416,
     formula_1 q881) are unrelated to arity, and finding 76 is explicit that arms must be
     compared within a session -- re-running one arm there gave 64 and 62 where it had scored
     77. These two arms were run days apart, so **the -3 total is not evidence of anything**;
     run-to-run variance covers it. What survives is the per-question attribution, which does
     not depend on the total: the brief fixed no answer, fixed one arity without fixing its
     answer, and reasoned one writer out of a right answer.

     That the experiment was designed without its own same-session control is the defect in
     it, and it is finding 76's lesson arriving for the second time.

     *What this closes.* The arity lever, which finding 132 ranked first and estimated at +3.
     It is measured at 0. The 108-miss figure was real and the inference from it was wrong:
     a count that is wrong because the reading was wrong cannot be fixed by counting.

134. **A clause that was parsed and thrown away, and the precedence trap beside it.**

     The primer said `THE LIST OF x GROUPED BY g` "carries its own `ORDERED WITH ... THE
     FIRST n`, which is top-n-per-group". Half of that is true, and the half that is not was
     the half the sentence sat under.

         THE LIST OF s IN <path> ORDERED WITH s DESCENDING THE FIRST 2     [185000,172000]
         THE LIST OF s ORDERED WITH s DESCENDING THE FIRST 1 GROUPED BY d  every value, unordered

     The parser built both clauses -- `Aggregate(func='list', ordering=[...], limit=Limit(1))`
     -- and `lower_aggregate` has two branches: the ungrouped one reads `ast.ordering` and
     `ast.limit`, the grouped one never looks at either. So they were parsed, dropped on the
     floor, and the answer came back gathering everything. No test covered it, which is how a
     documented feature can do nothing for as long as this one did.

     **Refused rather than honoured.** Honouring it means ranking within each partition before
     the group collapses, which is the `THE FIRST n PER k` machinery, and that machinery lives
     at block level where this calculation is not. Top-n-per-group already has a spelling, so
     the refusal names it and the primer now shows all three forms. Four cases in
     `test_operators.py` -- the form that works, the two shapes that are refused, and the
     spelling the refusal points at. 0 recorded answers change.

     *And the trap beside it.* A blind writer lost a question to `THE COUNT OF X [...] WHERE
     year(d) = 2010 / 12`, which reads as `year(d) = (2010/12)` and matches nothing. That is
     SQL's precedence exactly, and parentheses give the other reading, so the language is
     right and the primer was silent. Now it is not, with both spellings executed as examples.
     Primer 36 -> 38 executable blocks.

135. **The writers' bug reports, verified: two real, one worse than reported, one not true.**

     Eleven blind writers filed reports this session. Checking them rather than believing
     them, because a report from inside a scratch directory is evidence about the *experience*
     and not necessarily about the compiler.

     **Confirmed, and worse than reported.** `Legality [...] has Card has CardId i AND ALSO
     has Card has CardArtist a` emits **three** joins to `cards` on the same key, not the two
     the writer counted: the referent check, the one reading `id`, and the one reading
     `artist`. The cause is exact. Alias reuse is gated on `join_cols == identity`, and here
     the join is on `cards.uuid` while `cards` is keyed by `id` -- a reference to a *unique
     column that is not the primary key*, which 32 of BIRD's 105 declared foreign keys are.
     The join is still functional, so reuse would be safe; the mapping simply does not record
     that the target is unique, so the emitter cannot tell. Fixed in finding 136.

     **Confirmed, and structural rather than a defect.** Path direction decides the plan:
     `Card [is of Legality [...]]` emits a correlated EXISTS over unindexed `legalities.uuid`,
     and `Legality [...] has Card` emits a plain join. Same question, same answer, wildly
     different cost, and nothing tells the author which way to write it.

     **Confirmed.** The sibling-subtype hop. `Frpm has Satscore` is refused with a list of
     eight readings and the advice to "try the inverse verb", and the inverse verb is not the
     answer -- naming the sibling's value type is (`Satscore has FrpmSchoolName`). The message
     points somewhere that does not work for this case.

     **Not true.** A writer reported integer value domains printed as quoted strings. They are
     not: `HeroAttributeAttributeValue` is `integer` and its domain prints `5, 10, 15, ...`
     unquoted. Either the writer misread or the model predates `apply_column_types`.

     *And unary fact types, the item that was never started.* Now measured end to end. The
     metamodel admits them (`minItems: 1`), FORML verbalises them (§2.1.1), and
     `model/abstract.py` has a rule for them. Across 56 models and **4,003 fact types there is
     not one** -- every one is binary except five ternary. Building one by hand and querying
     it shows why the gap is bigger than the reverse engineer:

         schema listing    advertises it: `PersonIsRetired   Person is retired`
         verb parts        "has, is of" -- the lexicon never registered the unary verb
         parser            `Person is retired` -> "'is' is neither a type nor a variable"
         mapping           no way to say WHICH rows it holds for: roleMap carries columns,
                           never a condition, so a unary could only ever mean "every Person"

     So the listing advertises a reading the language cannot parse against a mapping that
     could not have meant anything if it could. Four things are needed, not one, and the
     mapping is the deep one: a unary fact type's Rmap is a *predicate on a column*, and the
     CCM's relational mapping has no place to put one.

136. **The four outstanding defects, fixed or measured; and a fifth found by the test written
     for the first.**

     *Three joins where one does (finding 135), fixed.* Alias reuse was gated on
     `join_cols == identity`: a join standing on the target's identifier is functional, so a
     second copy adds nothing and dropping it cannot change the multiset. A foreign key aimed
     at some *other* unique column failed that gate and got one join per value read -- three
     joins to `cards` on `cards.uuid` where `cards` is keyed by `id`.

     The mapping does not record that a referenced column is unique. The model does, one level
     up: a single-role uniqueness constraint over the role those columns map says each value
     fills the role at most once, which for an absorbed fact type is one row -- and
     `Index.is_functional` is that question already asked and cached. `Emitter.unique_columns`
     asks it of the far columns, and the gate widens to exactly the joins that cannot fan out.

         inner joins over the recorded corpus    2,060 -> 1,684  (-376, 18%)
         statements changed                      213
         answers that moved                      0

     Independent of finding 131: these models carry no `enforced`, so the two eliminations
     compose. One query drops six joins.

     *The sibling-subtype message (finding 135), fixed.* `Frpm has Satscore` was refused with
     "the fact type may read the other way round, so try the inverse verb", and the inverse
     verb is not the answer -- two subtypes of one supertype are one instance seen twice, so
     no fact type runs between them in either direction. The message now says that and names
     the form that works, checked against the model rather than described:
     `Frpm has SatscoreRtype`. Placed *ahead* of the ring hint, because a ring verb can look
     like it reaches the target when the target is a subtype of the ring's player -- it
     reaches a different instance, and where both fire the sibling is the answer.

     *The unary surface (finding 135), made honest.* The schema listing advertised
     `PersonIsRetired   Person is retired` among "the verb parts a path may use", while the
     lexicon registered no verb for it and the parser answered "'is' is neither a type in this
     schema". Unary readings are now marked in the listing as a property rather than a step,
     and a writer who tries one anyway is told what they hit. Full unary support remains
     unbuilt and is still four things, not one (finding 135).

     *Path direction (finding 135): measured, and a caution fails the bar.* The candidate
     signature was a correlated EXISTS correlating on a column that is not the target's
     identifier, which is where a scan happens. It occurs in **211 of 2,075 recorded
     statements -- 10.2%**, and the columns it names (`player_api_id`, `uuid`) are unique and
     so usually indexed. A caution firing on one query in ten is the mandatory RISK at 79%
     again (finding 119). Not built. The principled fix is a semi-join where the correlation
     is on unique columns -- the same `unique_columns` predicate the first fix adds, and
     finding 126 already measured joins as strictly faster than correlated EXISTS -- which is
     a plan change over 911 statements and needs its own measurement.

     *And the fifth, which the test for the first exposed.* The §8 normal form drops a bound
     variable that nothing projects, and the variable was load-bearing:

         LIST a, b FROM Department has DepartmentCode a AND ALSO is of Employee has
           EmployeeName b AND ALSO is of Employee has EmployeeGender g          14 rows
         ... AND ALSO is of Employee has EmployeeGender                          6 rows

     Naming `g` makes the second `is of Employee` a second range; dropping it lets the two
     collapse. The normal form is supposed to mean what the query means, and here it does
     not. Found only because the round-trip check runs over every case in
     `test_operators.py` and this shape had never been a case. Not fixed; recorded.

137. **Two casts the model has always carried and no query could ever call.**

     Found by trying to do real work rather than by reading code. LiveSQLBench's
     `organ_transplant_large` stores a wait time as the text `'104 days'` and a medical
     urgency as `'Status 1A'`, and its knowledge base defines a score over both as though
     they were numbers. Turning the first into a number needs `castNumber`, which every model
     the reverse engineer has ever built declares -- and which answers:

         no function 'castnumber' in this model; model.md §3 keeps the function table as
         model data, so add it there

     `function_id` casefolds the call and looks up `fn.` + that, and the model declares
     `fn.castNumber`. Folding one side only makes every camel-cased function unreachable:
     `castNumber`, `castInteger`, and `fn.jsonPath`, which survives only because the mapping
     calls it internally rather than by name. `abs` and `starts_with` work because they were
     already lowercase, which is why 2,075 recorded queries never noticed.

     The message is the worst part of it. It tells the author the model lacks a function the
     model is holding, and directs them to add it to a table where it already appears.

     Resolution now matches the model's own spelling, case-insensitively on both sides. Four
     cases in `test_operators.py`, including one that still refuses a function the model
     really lacks. Suite 1,888 -> 1,895; 0 recorded statements change, because nothing could
     call these.

138. **The HKB as derivation rules: the composition works, and the obstacles are elsewhere.**

     Finding 135's question was whether LiveSQLBench's hierarchical knowledge base -- 1,090
     entries over 18 databases, 560 of them depending on other entries -- can be encoded as
     derived fact types rather than re-resolved per question. Hand-encoded one chain on
     `organ_transplant_large`, which carries 9 of the corpus's 37 multi-hop questions.

     `Patient Urgency Score = 0.7 × Status_medical + 0.3 × R_wait`, over two children:
     `R_wait` is a wait time in days over 365, and `Status_medical` is a tier mapping. Both
     children are named quantities the database does not store as numbers:

         wait_time     '104 days'   text with a unit
         med_urgency   'Status 1A', 'Status 1B', '2', 'Status 2'   two spellings of one tier

         WaitYears     castNumber(substr(w, 1, instr(w, ' ') - 1)) / 365.0
         UrgencyValue  if(contains(u,'1A'), 5, if(contains(u,'1B'), 4, ...))
         UrgencyScore  0.7 * v + 0.3 * y        over the two above

     Then the question asks for one step: `Clinical has UrgencyScore UrgencyScoreS s`, and
     it answers -- `Status 1A` with 2.72 years waiting scores 4.317, which is
     0.7 × 5 + 0.3 × 2.723. The composition the benchmark calls multi-hop reasoning happens
     in the compiler.

     *What actually obstructed it, in order.* Not the algebra, which never complained.

     1. **`castNumber` was uncallable** (finding 137). The blocker was a name, not a feature.
     2. **The formulas do not name their quantities.** 40% of the 430 calculation entries use
        bare symbols and 23% maths subscripts; only 20% say `\text{Scan Resolution (mm)}`.
        An earlier 87% binding rate was measured on that 20% and does not generalise -- and
        the databases carrying the most multi-hop questions use the hard styles. Of the 29
        multi-hop questions in the top eight databases, 4 are in the style that binds by
        string match.
     3. **The model's readings are ambiguous.** `CompatibilityMetric has Demographic` is
        refused between seven fact types that all read a bare `{0} has {1}` and all reach
        Demographic. The reverse engineer distinguishes a ring's two roles and does not
        distinguish these, so the donor-age chain could not be written at all and a different
        chain had to be chosen. That is the next thing to fix if this is pursued.

     So: composition is not the hard part and was already built. Naming is.

139. **A fact type of your own type beats one borrowed from a sibling.**

     Finding 138 left the donor-age chain unwritable: `CompatibilityMetric has Demographic`
     was ambiguous between seven fact types, every one reading a bare `{0} has {1}`, so
     nothing could separate them. I called it a defect in the reverse engineer's readings.
     It is not.

     `organ_transplant_large` splits one key across several 1:1 tables, and rule 3 models
     that the way ORM does: `CompatibilityMetric`, `AdministrativeAndReview`, `Logistic` and
     four more are all **subtypes of `TransplantMatching`**, sharing its identifier. Two
     subtypes of one supertype are one instance seen twice -- which is exactly what finding
     136 relies on to make `Frpm has SatscoreRtype` work -- so from a CompatibilityMetric,
     all seven siblings' donor references genuinely do apply. The ambiguity was real.

     It was also useless. CompatibilityMetric carries its own donor reference, and that is
     what `CompatibilityMetric has Demographic` means. The rule now says so: **a candidate
     whose from-role is played by the head's own concept beats one reached by widening to a
     supertype and narrowing back to a sibling.** Nothing becomes inexpressible -- the
     sibling reach is still there when the head's own type does not carry the verb.

     *The half that took a second attempt.* Applied before checking the target, the
     preference fires even when none of the head's own fact types reach where the query is
     going, and replaces a message naming the sibling form with a type error about whatever
     the head happens to carry -- `ManagerCarSpace and Contractor cannot be the same thing`.
     Finding 136's own test caught it. The preference now applies only among candidates that
     still reach the target.

     0 of 2,075 recorded statements change; 0 compiled before and refuse now; 0 refused
     before and compile now. Suite 1,895, unchanged, because the fixture has one subtype and
     no sibling pair -- the case lives in `test_errors.py` under a mutation that adds one.

     *And the chain it unblocked.* Expected Graft Survival, three levels, on the database
     with nine of the corpus's multi-hop questions:

         S_mismatch   CompatibilityMetricHlaMisCount            0
         I_ABO        starts_with(blood_compat, 'compatible')   1   ('COMPATIBLE', 'compatible')
         S_immune     0.6 x I_ABO + 0.4 x (1 - S_mismatch/6)    1.0
         Age_donor    castNumber(substr('18 years, young adult donor', ...))   18
         EGS          1 / (1 + exp(-(-0.5 + 1.5 S_immune - 0.02 Age)))         0.6548

     Three of the five quantities needed work the formula assumes away: a case-scrambled
     enumeration, a number embedded in prose, and a composite of the other two. All three are
     the semantic layer's job, and once they are written down the question is one step.

140. **The knowledge base, written down once: six derived fact types over a chain three deep.**

     `bench/livesql/kb.py` encodes `organ_transplant_large`'s knowledge base as derived fact
     types, which is the experiment findings 138 and 139 cleared the ground for. Six entries,
     two chains, baked into the model rather than prepended as definitions:

         DemographicHasDonorAgeYears          '57 years, mature donor'  -> 57
         ClinicalHasRecipientWaitYears        '104 days' -> 0.285
         ClinicalHasMedicalUrgencyValue       'Status 1A' and '2' -> one tier scale
         ClinicalHasPatientUrgencyScore       0.7 x urgency + 0.3 x waityears
         CompatibilityMetricHasImmunological  0.6 x ABO + 0.4 x (1 - mismatch/6)
         CompatibilityMetricHasExpectedGraft  1 / (1 + exp(-(-0.5 + 1.5 S - 0.02 Age)))

     Then the question is one step -- `CompatibilityMetric has ExpectedGraftSurvival e` --
     and answers 0.6548, the same number the hand-composed definitions gave. The multi-hop
     resolution the benchmark exists to test happens in the compiler.

     *Three of the six are not formulas at all.* `DonorAgeYears`, `RecipientWaitYears` and
     `MedicalUrgencyValue` exist because the quantities the knowledge base names are not
     stored as quantities: an age inside `'57 years, mature donor'`, a wait as `'104 days'`,
     an urgency arriving as both `'Status 1A'` and a bare `'2'`. The formulas assume all
     three away. Every competitor has to do this work too, per question, in SQL, and nothing
     in SQL lets them write it once.

     *And the listing now carries the words.* `description` on a concept (added this session)
     is the CCM's only addition for this, and the schema listing prints a `Defined terms`
     block above the readings:

         ExpectedGraftSurvival   Predicts the probability of a transplanted organ
                                 functioning successfully over a specific period.
         PatientUrgencyScore     A score that quantifies the urgency of a recipient's
                                 need for a transplant.

     That is the knowledge base's own sentence, reaching the author through the model.
     `terms` lets the model *match* a word; this is the first thing that lets an author
     *read* what one means, and finding 132 measured this listing as the surface that
     decides answers.

     Deliberately hand-written. Finding 138 measured why: 80% of the calculation entries name
     their quantities in symbols whose meaning sits in the prose beside the formula, so an
     automatic translator would be an LLM reading both -- a different experiment with a
     different claim. What is here is what a modeller writes once, from the document every
     competitor is handed.

     Suite 1,895; 0 of 2,075 recorded statements change.

141. **Profiling the values, because one kind of dirt silently switches a pass off.**

     LiveSQLBench's data is deliberately messy, and the question was whether that costs the
     reverse engineer anything. It costs it one thing exactly, and the loss is silent.

         blood_compat    154 distinct values as stored
                           2 distinct values case-folded

     `DOMAIN_MAX_VALUES` is 25, so `_value_domains` sees 154, concludes this is not an
     enumeration, and records **no domain at all**. Verified: of 12 domains found over four
     tables of `organ_transplant_large`, `blood_compat` is not one. A two-value enumeration,
     invisible, with nothing reported -- and a value domain is the one input that tells a
     query author how a code is spelled (findings 119, 132).

     What does *not* suffer is key and reference inference, which is the half that matters
     most: `compatibility_metrics.donor_ref_reg -> demographics.contrib_registry` has 596
     distinct values and **0 not contained**, folded or not. Reference columns are keys, and
     the keys here are clean. The dirt is in the values, and it is the values that carry
     meaning a query has to spell.

     *`reverse.py --profile`.* Four signals, each one measured on this corpus before it was
     written, and each firing rarely enough to be read:

         numeric-text    106 columns  1.6%   '1 days', '0 previous transplants, first-time...'
         sentinel-null    69 columns  1.1%   'none', 'None' standing in for NULL
         padding          45 columns  0.7%   differing from each other only by space
         case-variants    20 columns  0.3%   135 values that are four once folded

     over 6,562 columns of six databases. The company fixture, which is clean, reports **0**.

     *And the one that had to be tightened before it was usable.* `numeric-text` first
     matched any text beginning with digits and a non-digit, which is also every timestamp:
     162 columns on one database, the wallpaper finding 128 warns about. A date is a value
     of its own type, correctly stored as text by a catalogue with no date type; the thing
     worth reporting is a *quantity wearing a unit*. Requiring a space and a letter after
     the number, and excluding date shapes, took it from 162 to 59 on that database and made
     every survivor real.

     *One extension, from a curated data-quality list that mostly did not help.* The list
     (kwanUm/awesome-data-quality) catalogues tools without a taxonomy, and the tools it
     names are mostly *assertion* frameworks -- Great Expectations, Soda, dbt tests -- where
     you declare what you expect and they check it. This is a *discovery* pass: nobody has
     declared anything yet, which is the situation reverse engineering is always in. So the
     list's contents transfer badly.

     What did transfer was trying one of the techniques it implies. Format inference --
     reduce each value to its shape, look for a dominant shape with a minority that breaks
     it -- found 8 columns on `organ_transplant_large` and every one was an artefact of the
     shape function rather than the data. Not built. But it surfaced one class the shipped
     signal could not see: a quantity whose unit comes *first*, `'US$12270'`, `'± 1.0161'`.

     Adding it took three attempts, and the two failures are the finding. Any short
     alphabetic prefix caught every prefixed identifier in the corpus -- `SN10024`, `PR1003`,
     `OP1005` -- and took the signal from 1.6% of columns to **6.3%**. Any punctuation caught
     the hyphenated ones, `CR-001` and `SW-001`, at 1.9%. Only an actual unit symbol
     (currency, `±`, `%`) is right: **1.7%**, twelve new columns, all genuine. A letter pair
     is a namespace and a hyphen is a separator; a currency sign says something about the
     quantity.

     *A fifth signal, and the integrity problem that finding it exposed.* `ydata-profiling`
     (now `fg-data-profiling`) publishes an alert taxonomy, most of which is for machine
     learning rather than modelling -- skew, zeros, infinities, correlation. Two entries map
     onto something a conceptual model should know, and testing them split cleanly.

     **Constant** is real and now shipped: 57 columns of 6,562, 0.9%. `IS_OVERSPENT = 0` over
     70 rows, `approvalDATE = '2025-07-16'` over 1,000. A fact type over a constant column
     distinguishes no instance from another; in ORM it is a value constraint of one value, or
     it is not a fact type.

     **Text that is really a date** measured at 469 of 5,688 columns, 8.2%, which reads as
     wallpaper -- and the measurement was wrong. Those SQLite copies come from `load.py`,
     which translates PostgreSQL dumps, and SQLite has no date type: *every* date in them is
     text by construction. Against the restored PostgreSQL server the same database types 33
     columns as `timestamp` and still holds `transplant_matching.match_ts` as the text
     `'2025.02.19 08:31:22'`. The signal is real; the place I measured it cannot see it.

     **So: a signal that depends on typing cannot be measured on the shim, and one that
     depends on values can.** `case-variants` is the control -- `blood_compat` gives 154
     distinct and 2 folded on the SQLite copy *and* on PostgreSQL, identically. Every signal
     shipped here is value-based and therefore honestly measured; the date one is not built,
     and would need measuring server-side against a catalogue that has a date type to be
     worth anything.

     *And a third list, for completeness.* `psebenick/data-profiling` is SQL scripts for bulk
     metadata collection -- distinct counts, null counts, min/max, frequency distributions,
     inter-table relationships -- and says of itself that it is "not meant to provide very
     deep data profiling capabilities". Every metric it names we already compute, and the
     inter-table half is inclusion-dependency search, which is finding 120's territory and
     considerably further along. Nothing taken.

     Reported, never applied -- what to do about dirt is the modeller's call and usually the
     source system's problem. But `case-variants` deserves more than a report, because it is
     the one that disables another pass rather than merely describing the data. Folding case
     in `_value_domains` would recover `blood_compat` as two values; it also changes what a
     filter must spell, and finding 130 pinned the string predicates case-insensitive while
     `=` stayed exact, so the two interact. Measure before changing.

142. **A third tier, fully executable, and the 23% that was our own SQLite.**

     LiveSQLBench also publishes `base-lite-sqlite`: 18 databases shipped as `.sqlite` files,
     270 tasks of which 180 are SELECT, with the solution SQL rewritten for SQLite. Its
     ground truth arrives by a third email, and with it the benchmark is scoreable with no
     PostgreSQL and no Docker.

         gold against the shipped databases, Python's bundled sqlite3   139 of 180
         gold against the system's SQLite 3.51                          180 of 180

     The 41 failures were `->`, `->>` and `RIGHT JOIN` -- SQLite has had the JSON operators
     since 3.38 and right joins since 3.39, and **Python 3.10 bundles 3.35.5**. Nothing was
     wrong with the benchmark or the data; a quarter of it was unreachable through the
     library this project executes everything with.

     That is worth more than the number. `conquer/conquer.py`, `corpus.py` and every test in
     the suite run SQL through `import sqlite3`, so the ceiling on what this project can
     execute is whatever Python was built against, and it is five releases behind. It has not
     bitten yet because the emitter targets `json_extract` rather than `->>` and emits no
     right joins -- but the emitter is where a dialect is chosen, and the choice has been
     constrained by an interpreter detail nobody measured.

     *Where the three tiers now stand.*

         large-v1        480 tasks, PostgreSQL     19/19 gold runs on the restored server
         base-lite       270 tasks, PostgreSQL     gold held, databases not fetched
         base-lite-sqlite 180 SELECT, SQLite       180/180 gold runs, no server needed

     *And the fourth profiling list, which named one thing.* Capital One's DataProfiler does
     entity detection -- 30+ labels, EMAIL_ADDRESS, SSN, UUID, PHONE_NUMBER -- behind a
     pre-trained model. Tested cheaply with regexes over 6,562 columns: url 47, email 11,
     uuid 1, and phone 214, where the phone pattern matches any long digit string and is
     plainly catching identifiers. So the high-precision half is 0.9% of columns and the
     rest is a false-positive machine without the model. In ORM a detected format is a value
     constraint and a better value-type name, which is real but marginal; behind a deep
     learning dependency it is not worth it. Not built, measured rather than argued.

143. **The benchmark's own harness scores the benchmark's own gold at 77%, and the missing
     23% is the Python it runs on.**

     Finding 142 measured the SQLite tier's gold at 139 of 180 through Python's bundled
     sqlite3 and 180 of 180 through the system's 3.51, and drew the obvious conclusion about
     our own execution ceiling. Running LiveSQLBench's *official* evaluator -- cloned from
     `bird-bench/mini_dev`, in `gold` mode, where the prediction IS the ground truth and the
     only honest answer is 100% -- turns that from our problem into everyone's:

         Total instances: 180      Passed: 139      Overall accuracy: 77.22%

     The 41 failures are exactly the 41 from finding 142. Every one is refused by Python
     3.10's SQLite 3.35.5 and accepted by 3.51: the JSON operators `->` and `->>` arrived in
     3.38 and right joins in 3.39. Anyone running this harness on a stock Python 3.10 has a
     **ceiling of 77%**, cannot reach it, and is given no indication why -- the failures are
     counted as "execution errors" against the model under test.

     *And two things about using someone else's harness.* Its wrapper invokes
     `"./single_instance_eval_sqlite.py"` by a relative path, so it only runs from inside its
     own directory; from anywhere else every instance fails with `can't open file` and the
     score is 0.00%, which is indistinguishable from a model that answers nothing. And the
     database path falls back to a hardcoded `/Volumes/SN770/...` belonging to whoever wrote
     it.

     *Why use it anyway.* Because the metric is not what I had built. `score_sqlite.py`
     compared sorted result sets; `ex_base` strips `DISTINCT` and `ROUND` from **both** sides,
     normalises dates to `YYYY-MM-DD`, rounds decimals to two places, compares as a *set*
     unless the task's `conditions.order` says otherwise, and runs an explicit `test_cases`
     function where the task ships one (2 of 180 do). Mine was stricter about formatting and
     looser about order. A number from it would not have been comparable to the leaderboard,
     which is the only reason to have a number at all.

     The tier is otherwise sound: 180 of 180 golds execute, 18 databases, no server. What it
     needs is a modern SQLite under the harness, which is a packaging problem rather than a
     benchmark one.

144. **Describing the data in the schema listing, and the 75-against-367 that justifies it.**

     Three questions arrived together: is there a profiler, does it feed the reverse engineer,
     and could the schema describe the data as well as the structure. The answers were yes,
     **no**, and that third one is the fix for the second.

     Finding 141 built the profiler and `reverse.py --profile` wrote its findings to the
     worklist. A worklist is read once, by a modeller. The model itself was unchanged, so
     nothing reached the person who actually writes queries -- and the whole point of the
     `case-variants` signal is that it changes what a filter has to say.

         LIST c FROM THE COUNT OF CompatibilityMetric
                       [has CompatibilityMetricBloodCompat: 'COMPATIBLE'] AS c     75

         the same question, case-folded                                           367

     That is the filter a writer reaches for, against the spelling the data mostly uses, and
     it finds one fifth of the rows. It does not fail, it does not warn, and the number is
     plausible. The silent wrong answer this project exists to prevent, arriving through the
     data rather than through the query.

     *So the model carries it.* `dataQuality` on a concept: a list of sentences about the
     values a type holds, from profiling the population rather than from the catalogue.
     `apply_quality` attaches them, `--profile` turns it on, and the schema listing prints a
     **Value cautions** block:

         AdministrativeAndReviewExpRevStatVal
             Values arrive in mixed case (135 spellings of 4 values). An exact `=` filter
             will match a fraction of the rows; use a case-insensitive test, or spell the
             value as the domain lists it.

     Only the three signals that change what a filter must say -- case variants, a number
     wearing its unit, a stand-in for NULL. `constant` and `padding` stay on the worklist:
     they are worth telling a modeller and do not change how a column is queried.

     Cautions, never constraints. Nothing enforces them and nothing reads them but the
     listing, so deleting them loses advice rather than meaning. That is deliberate --
     finding 78 measured refusing more at 20 right answers lost for 5 wrong, and a value
     domain mined from dirty data is exactly the kind of thing that should inform a writer
     rather than bind a compiler.

     This is also the first thing the CCM carries that is *about the population* rather than
     about the universe of discourse. It sits beside `description` (what a term means) and
     `restriction` (what values are permitted); this is what the values are actually like.

145. **Every AVERAGE and SUM over a bound expression was a MIN.**

     The worst defect this project has found, and a blind writer found it in twelve questions
     of a first sample run.

         LIST g, a FROM Employee has EmployeeGender g AND ALSO has EmployeeSalary s
             AND ALSO (s * 2) AS x AND ALSO THE AVERAGE x GROUPED BY g AS a

         emitted     MIN((employ1."salary" * ?))
         should be   AVG((employ1."salary" * ?))

     It compiled. It ran. It returned one plausible number per group. `THE MAXIMUM` over the
     same expression was right, and `THE AVERAGE` over a plain value-type variable was right,
     so nothing looked systematically broken -- only `AVERAGE` and `SUM` over an expression
     bound with `AS`, which is how anyone writes a ratio or a scaled measure.

     *The mechanism is a vacuous truth.* `constant_in_group` (finding 112's machinery) asks
     what determines the aggregated value; where the group keys pin all of it, every row of
     the group carries the same value and `MIN` returns it exactly. That is a real
     optimisation for a real shape -- a parent's measure reported beside the parent. But the
     question is asked through `_first_node`, which looks for a node among the aggregate's
     arguments, and a bound expression is lowered as a *calculation referring to another
     calculation*: `fn.avg(calc11)` where `calc11` is `fn.multiply(n9, 2)`. `_first_node` did
     not follow that reference, returned None, and

         all(n in pinned for n in det)     with det empty     is True

     So "I cannot see what this depends on" was read as "the keys pin everything it depends
     on". The fix is to follow the reference; `det` empty now also fails the test, because
     unknown is not constant.

     *Why no test caught it.* `test_fanout.py` has thirteen cases over every shape of the fan
     trap and not one aggregates a bound expression -- every case aggregates a value type
     directly. The corpus did not catch it either: 0 of 2,075 recorded statements change,
     because none of them writes this shape. It was reachable only by someone answering a
     real question about a ratio, which is what LiveSQLBench's questions mostly are.

     Four cases added, pinning all four aggregates over a bound expression and the
     parent-measure shape that `MIN` is genuinely for. Suite 1,895 -> 1,899.

     *And the writer deserves the credit precisely.* It reported the defect, gave a minimal
     reproducer, established that `MAXIMUM` and `COUNT` were unaffected, found that the
     `WITHIN` form was correct, and worked around it by rewriting its query as a windowed
     aggregate over a `DISTINCT` head. None of which it was asked to do.

146. **And the normal form of the same shape did not parse.**

     Finding 145's four regression cases went into `test_fanout.py`, which the reference
     check round-trips: every case is normalised, the normal form re-parsed, and the two
     answers compared. Three of the four failed immediately.

         LIST g, a FROM Employee ... AND ALSO (s * 2) AS x AND ALSO THE AVERAGE x GROUPED BY g AS a

         normalises to   ... AND ALSO THE AVERAGE v1 * 2 GROUPED BY g AS a
         which reads as  THE AVERAGE v1    then meets `* 2` with nowhere to put it

     Normalising inlines a bound expression -- that is what it is for -- and the parentheses
     the author wrote went with it. `expr()` has always returned a precedence level alongside
     the text and the aggregate renderers threw it away, calling `value()`. `atom()` keeps it
     and parenthesises anything that is not already atomic.

     Two defects, one shape, found within minutes of each other, and neither was reachable
     before because **no test had ever aggregated a bound expression**. That is the whole
     lesson: `test_fanout.py` had thirteen cases covering every shape of the fan trap and all
     thirteen aggregated a value type directly. The gap was not in the machinery, it was in
     what the machinery had been pointed at.

     Suite 1,895 -> 1,899, 0 DIFFER, 0 of 2,075 recorded statements change.

147. **The first score on LiveSQLBench: 2 of 12, and the number is not the finding.**

     A twelve-question sample over three databases of the SQLite tier, scored through
     LiveSQLBench's own evaluator at a verified 100% gold ceiling:

         Total instances 12   Passed 2   Assertion errors 9   Execution errors 1
         Overall accuracy 16.67%

     Every one of the twelve compiled. Nothing was refused and nothing was unanswerable, so
     the loss is entirely in meaning rather than in coverage -- on 54-table industrial
     schemas whose questions name terms defined only in a knowledge base.

     **It is not a measurement of the language, because the compiler changed underneath it.**
     Two of the three writers independently reported the defect of finding 145, and one said
     its "first three drafts were all wrong by this". `alien_6` shows what that cost:

         before finding 145's fix   aggregates emitted: COUNT, MIN
                                    ran, returned 915 rows, confidently wrong
         after                      aggregates emitted: COUNT, MIN, SUM, AVG
                                    and fails loudly: MIN((SELECT SUM(...))) is not SQLite

     Every `SUM` and `AVG` the writer asked for had been a `MIN`. The answers in this sample
     were written against that compiler, by writers who worked around it -- one with
     `DEFINE`, one with `WITHIN` -- so what was scored is partly a measure of how well they
     routed around a bug that no longer exists.

     *And a second defect it exposed.* `alien_6` now emits a correlated bag wrapped in `MIN`,
     which SQLite refuses as "misuse of aggregate". The shape is a conditional count --
     `if(P, 1, 0) AS f` then `THE SUM OF f GROUPED BY k` where the key is reached through a
     many-to-one -- and it does not reproduce on the fixture, which is why it is recorded
     here rather than fixed. Silent wrong answer to loud failure is the right direction and
     not the destination.

     *What the writers found that the score does not show.* No standard deviation aggregate,
     so one computed it from `sqrt((avg(a*a) - avg(a)^2) * n/(n-1))` -- and the gold for that
     question computes a variance, with no square root, under a column named for a standard
     deviation. No JSON accessor reachable from a query, so
     values inside document columns were dug out with `instr`/`substr`. `per` is a reserved
     word and `THE AVERAGE per` misparses silently. `THE RANK OF` requires `WITHIN`, so a
     global rank needs a constant partition bound with `AS`.

     The honest position: the pipeline is proven end to end, the ceiling is real, and the
     first number is 16.67% of twelve questions against a compiler that has since changed.
     Re-run it before believing it.

148. **What else is missing: 660 gold statements, counted rather than guessed.**

     A writer needed a standard deviation and built one from three other aggregates. Rather
     than add that one and stop, count what the benchmarks actually ask for. Every function
     named in the 660 LiveSQLBench gold statements across both tiers, against the 40 this
     project offers:

         coalesce        627 of 660 statements      trim         161
         nullif          179                        json_extract  64
         regexp_replace   48                        greatest      23
         log              15                        least          -

     `coalesce` is in **627 of 660** -- more than any function in the corpus, ours or
     theirs -- and we had none of these. The survey names 248 functions we lack, but the
     distribution is the finding: a long tail of dialect-specific spellings behind a short
     head of things every query needs.

     Added, all portable across the three dialects: `coalesce`, `nullif`, `trim`, `ltrim`,
     `rtrim`, `log10`, `greatest`, `least`. And the dispersion aggregates on the same terms
     as finding 103's median -- `THE STANDARD DEVIATION` and `THE VARIANCE`, sample rather
     than population, present where DuckDB and PostgreSQL have them and refused by name on
     SQLite, which has neither.

     *Deliberately not added.* `regexp_replace` and `strftime` are dialect spellings rather
     than concepts. `json_extract` is the largest remaining gap at 64 statements and is not a
     function this can simply declare: rule 12 already maps a document's leaves to fact
     types, so a query says `Circuit has CircuitLocationCity` and never mentions JSON -- but
     that only reaches leaves the reverse engineer found. Two writers this session dug values
     out of documents with `instr`/`substr` against literal key text, which works only
     because the serialisation is stable. That is a real gap and a bigger piece of work than
     a template.

     *And what this says about the audit.* Four of this session's fixes had no test until
     asked: the unary listing marker, the value cautions, the `description` field, and all
     five profiler signals. They are covered now -- the population fixture gains a `pressing`
     table carrying each of the four dirt shapes deliberately, and the assertions include the
     negative ones (a clean column reports nothing, a title is not mistaken for a quantity),
     because a profiler that flags everything is the failure mode, not the feature.

     Suite 1,895 -> 1,942.

149. **The third defect of one shape, and the writer handed over the reproducer.**

     Finding 147 left `alien_6` failing loudly with `misuse of aggregate: SUM()` and recorded
     that it did not reproduce on the fixture. The rerun's writer reduced it in one paragraph:

         two grouped aggregates, where one's `if(...)` repeats the other's expression

         ... AND ALSO (s * 2) AS a AND ALSO if(s * 2 > 200000, 1, 0) AS b
             AND ALSO THE AVERAGE a GROUPED BY d AS m AND ALSO THE SUM OF b GROUPED BY d AS n

     "It works if the two aggregates use different variables, or if there is only one of
     them." Repeating the subexpression makes the two aggregates share a node, the second is
     re-lowered into a bag of its own, and its argument still pointed at the *outer* block:
     `SUM(CASE WHEN employ1."salary" ...)` inside a subquery that declares `employ5`.

     The cause is finding 145's, one level further in. `_first_node` learned to follow a
     calculation reference; it still could not see a node nested inside a **conditional**, so
     `det` was empty again and the aggregate took the regroup path it had no business taking.
     The walk is now generic over containers.

     *And a bug I introduced fixing it.* Recursing into a dict's values reaches its own
     `"kind"` string, and a bare string one level up is read as a node id -- so the first
     attempt named `"conditional"` as the node the aggregate depends on. Only containers are
     recursed into now. Three attempts at this one function across two findings, each caught
     by running it rather than by reading it.

     Three defects of one shape in one session: AVERAGE and SUM over a bound expression
     became MIN (145), the normal form of that shape did not parse (146), and a conditional
     nested inside it broke the bag (149). All three were unreachable from 2,075 recorded
     statements and from thirteen fan-out cases that every one aggregated a value type
     directly. Two blind writers found two of them; the third came from the test written for
     the first.

     Two cases added. Suite 1,942 -> 1,944, 0 of 2,075 recorded statements change.

150. **The rerun scores the same 2 of 12, and eight of the ten misses have the right shape.**

     Finding 147's sample re-answered by three fresh writers against the fixed compiler:

         before finding 145's fix    2 passed, 9 wrong, 1 execution error
         after                       2 passed, 10 wrong, 0 execution errors

     The same two questions pass. **The compiler defect was not what cost the score** -- both
     sets of writers worked around it, and fixing it only turned `alien_6` from a failure to
     execute into a wrong answer. That is worth knowing before commissioning 180 questions.

     *And the misses are not shape.* Comparing our result sets against the gold's:

         8 of 10     identical row count AND column count
         2 of 10     differ in row count (archeology_10, credit_7)

     The writers reached the right grain and returned the right number of things. The loss is
     inside the values, which is a different problem from the one this project usually fears.

     *Two of the ten, examined, are ours to lose and arguably not wrong.*

         alien_2   first three columns identical. The fourth differs by exactly a square:
                   the gold computes a variance under a column named for a standard
                   deviation. Our writer computed a standard deviation, which is what the
                   question and the column name ask for.

         credit_2, credit_3, credit_5   every value identical except the identifier column.
                   The questions say "customer ID" and the schema has two id-shaped columns;
                   the gold chose the other. Three of twelve turn on that one choice.

     So of the ten misses, one is a benchmark defect and three are a single ambiguity about
     which identifier "ID" means. That is not a claim that we would score 6 of 12 with better
     luck -- `archeology_1` is genuinely wrong (a real formula or grain difference) -- but it does mean 16.67% understates what the writers understood,
     and that a bigger run needs the identifier question settled first.

     The honest reading of two runs: the pipeline works, the ceiling is real, the score is
     stable at 2 of 12, and the next thing to fix is not the compiler.

151. **Rerunning the reverse engineering over BIRD caught rule 6d deleting real values.**

     Rule 6d, added the day before, strips a stand-in for NULL out of a value constraint
     before it is applied: `Unknown` in 26% of a polarisation column is the absence of a
     polarisation, and a constraint admitting it makes every count over the domain wrong.
     `_dirt` had been reporting these since it was written and nothing consumed the finding.

     Rebuilding the eleven BIRD schemas showed what the rule did to real data. `_SENTINELS`
     carries punctuation and two-letter tokens alongside the English words, and in a schema
     that is not synthetic those are far more often values than nulls:

         toxicology.atom.element     `na` is SODIUM, among eighteen chemical symbols
         toxicology.bond.bond_type   `-` is a single bond, beside `=` and `#`
         toxicology.molecule.label   `-` is "not carcinogenic", beside `+`
         thrombosis Examination.KCT  `-` is a NEGATIVE result, beside `+` -- and the column
                                     already holds a real NULL, so the two are distinct
         thrombosis Patient.Admission `-` is a category, beside `+`

     Every one would have been deleted from its domain. That is not cosmetic: `sql.py`
     turns a value constraint into `WHERE col IN (...)`, so a constraint the population
     supplied is a no-op filter and one with a value removed is a real one. Three of eleven
     databases would have started dropping rows from every query that walked those columns.

     Stripping is now restricted to what is unambiguous -- an empty or blank string, and
     words of three or more letters that say absence in English. Punctuation and two-letter
     tokens are reported and kept. Across the eleven that leaves five genuine strips
     (`None` from a work rate whose other values are low, medium and high; `''` and `' '`
     from two k_symbol columns and two patient columns) and nine values kept.

     Two more defects the same rebuild exposed, both fixed at source:

     **`make_subtype` copied the supertype's identifier onto the subtype.** A subtype
     inherits its reference scheme and declares none. The copy made the subtype name a role
     whose player is the supertype, and because it was taken when the subtype was reached
     rather than when the supertype was resolved, a chain of subtypes copied one that was
     still empty -- `credit` stacks five and the last three came out unidentifiable. Eight
     lint errors on BIRD and three on LiveSQLBench, all from one line.

     **Two ormlint false positives.** Rule 1c -- a keyless table identified by row identity
     -- is a documented reading rather than a missing identifier, and it is inherited by
     subtypes like any other scheme: ten errors on thrombosis, now notes. And a derived fact
     type takes its population from its rule, so reporting every one for want of a declared
     uniqueness constraint was twenty of twenty across the semantic models.

     **What the rebuild cost: nothing.** The committed models turned out to carry no
     `enforced` markings at all -- `bench/models` predated the `--infer-enforced` work even
     though `run.sh` has specified it since -- so rebuilding changed 518 of 2,175 recorded
     queries, almost all of it the join elimination finding 131 measured. Rescored, the two
     headline arms are `conquer` 71 and `conquer_opus` 76: the same numbers, question for
     question, including the one `not_answered`.

152. **The whole SQLite tier, 180 questions: 70 correct, and twenty-three defects.**

     The 12-question sample was noise. Twice. It scored 2 of 12 against the old models,
     1 of 12 against the new ones, and the complete tier scores **70 of 180**. A number
     that moves 17% -> 8% -> 39% on the same system was never measuring the system; it
     was measuring which twelve questions were drawn. Every proportion in finding 150 and
     in the diagnosis that followed it is void -- including "eight of twelve were decided
     before any language was involved", which was built on a sample far too small to
     carry it. The individual observations behind it survive (alien_2's gold really does
     compute a population variance under the name `anomaly_stddev`; "customer ID" really
     does have two candidate columns); the arithmetic does not.

     0 refused, 0 unanswered, 0 execution errors: every one of the 180 compiled and ran.

     **What the sample size actually bought was the defect list.** Eighteen blind writers
     on eighteen schemas found twenty-three distinct issues that twelve questions had not
     touched. Two of them were silent:

       * A `DEFINE` listing more than one value mapped every read to the FIRST column.
         Six writers hit it; none was told anything was wrong. `reading_slots` yields a
         verb part only between adjacent slots, so the n-ary reading reached the second
         value only through the first, and `has <Name> <SecondType>` resolved silently
         because `resolve_verb` left its candidate list alone when nothing reached the
         named target and `return viable[0]` did the rest.
       * A `WHERE` on a computed alias was dropped from the correlated sub-aggregates a
         DEFINE-plus-grouping emits, so an average came back below the threshold that was
         supposed to bound it. Found by a writer reading the generated SQL.

     **Two clusters, each one root cause wearing several faces.**

     *Template arity* -- five functions: `jsonPath`, the SQLite standard deviation,
     `days_between` against a literal, `rtrim(x, chars)`, `greatest(a, b, c)`. Rendering
     an argument sinks its parameters once; a template naming it several times left the
     statement short of bindings. Two were patched at their call sites in the morning,
     which was the wrong altitude, and three more of the same shape surfaced by evening.
     `Emitter.call` now binds each argument once per placeholder.

     *Determinant analysis* -- five writers, five different accounts of one trigger: a
     nested sub-expression (solar), more than one bound variable (polar), two entity
     branches off a rebound variable (archeology), a reverse `is of` step plus `today()`
     (virtual), and `greatest`/`jsonPath` in the expression (insider). None of the five
     was the rule. The cause was ordering: the emitter renders a block's calculations in
     list order and `_mirror_calculations` appended a copy *before* repointing its
     arguments, so the bag's copies landed outermost-first. The enclosing block gets this
     right by construction; only the mirrored bag did not. One line, five symptoms.

     The writers were not defeated by any of it -- a 24-deep DEFINE chain standing in for
     `LEAD(n)`, a tie-safe median built from ranks and verified by counting, `NTILE(4)`
     from a rank and a count, Pearson's r spelled out of SUM subqueries, a correlated
     denotation reaching a facility the model had no path to. Several answers route
     through a DEFINE purely to dodge a compiler bug, so 70 understates what the language
     can express today.

153. **The rerun against the fixed compiler scores the same 70 of 180 -- and cost a regression.**

     Eighteen writers rewrote 37 of the 180 answers against six fixed defects. Score before
     and after: 70. Not one question flipped either way by total; 0 refused, 0 errors.

     What the fixes bought was expression, not accuracy. crypto_7 went from 24 chained
     DEFINEs to 2, 8.7 kB to 1.9 kB, byte-identical output. Several writers report no DEFINE
     remaining in any answer. archeology unwound seven, three of them genuine corrections --
     one had been averaging over a cross product, one moved from average-of-averages to row
     weighting, one dropped a DEFINE's implicit DISTINCT. cybermarket_5 had been reading two
     independent `is of Vendor` branches, a cross product that never summed. Those were
     silently wrong and are now right, and the total did not move, which says the questions
     they belong to were failing for another reason as well.

     **The cost: my ordering fix that morning had made a refused shape compile without
     making the query's filter follow it into the bag.** `WHERE h > 0.9` beside
     `THE AVERAGE h GROUPED BY tm` averaged every row and returned a mean below the
     threshold its own filter enforces. I then told all eighteen writers the DEFINE
     workaround was unnecessary; for that shape the DEFINE was the correct query. Two --
     vaccine and robot -- disbelieved their own numbers and reverted. Sixteen took my word.
     That is also finding 19, which the robot writer had reported after the first run and
     which I closed as "not reproduced" after trying four shapes that did not route through
     the bag.

     Per database, with the number of answers that writer changed:

         disaster    9/10   changed 0      cybermarket 8/10   changed 4
         gaming      7/10   changed 1      insider     5/10   changed 4
         news        5/10   changed 1      solar       5/10   changed 2
         cross_db    4/10   changed 2      crypto      4/10   changed 1
         fake        4/10   changed 1      polar       4/10   changed 2
         mental      3/10   changed 0      museum      3/10   changed 3
         robot       3/10   changed 0      archeology  2/10   changed 7
         credit      2/10   changed 2      virtual     2/10   changed 3
         alien       0/10   changed 1      vaccine     0/10   changed 0

     The two best scores belong to writers who changed nothing and to one who changed four;
     the worst belongs to one who changed seven. There is no relationship between rewriting
     and scoring -- the same conclusion 70 -> 70 gives, reached a second way.

     **alien and vaccine at 0/10 are the thing to look at next.** Neither is explained by the
     compiler. vaccine's data is stale against `today()` -- every date is Feb 2025, the clock
     says 2026 -- so three of its questions are empty under any faithful reading. alien's
     writer flagged that alien_3 omits a station column the question does not ask for but
     every other question in the set does. Two databases contributing nothing is 20% of the
     sample, and it is a question about the benchmark and the readings, not about the
     language.

154. **Why 70 of 180, measured rather than argued.**

     Every failing answer compared against its gold, row by row and column by column:

         correct                                     70  38.9%
         right shape, ONE column differs             44  24.4%
         right shape, several columns differ         29  16.1%
         row count differs (filter or grain)         22  12.2%
         output width differs                         6   3.3%
         right rows, ties ordered differently         6   3.3%
         we return no rows                            2   1.1%
         right rows, type spelling only               1   0.6%

     **Nothing here is a compiler or language failure.** 0 refused, 0 execution errors, and
     every one of the 180 compiled and ran. The dominant class -- 44 of 180, a quarter of the
     whole benchmark -- is a query of exactly the right shape, returning exactly the right
     number of rows, with one computed column carrying a different number. That is a
     disagreement about what a definition means, not about how to say it.

     Three classes are benchmark fragility rather than error:

     *Ties.* robot_1 and robot_4 return the right rows in a different order, and the rows at
     the divergence carry identical sort keys, so ours and gold take different rows at the same
     sort value. Comparing an ordered result whose sort key
     ties cannot distinguish a right answer from a wrong one.

     *Type spelling.* the gold casts an integer aggregate to text where the column is
     declared `integer` and holds integers; `preprocess_results` normalises dates and rounds
     decimals but never coerces types, so `10 != '10'`. Three answers fail on this and no
     other difference. Matching gold means matching its casts, not its values.

     *A stale clock.* vaccine's every date is Feb 2025 and `today()` is late 2026, so
     "within the past 3 months" is empty under any faithful reading and a `CDR > 1` threshold
     is unreachable when CDR caps at 0.138. Two answers return no rows and are right to.

     alien and vaccine scoring 0/10 needed no special explanation: alien is eight
     one-or-two-column disagreements plus one output-width judgement, vaccine is five
     one-column disagreements plus the two empty results and the type-spelling case. Neither
     is a cluster of anything fixable in the compiler.

     **What this says about where the remaining points are.** Not in the language: it
     expressed all 180. Not in the compiler: nine defects were fixed between the two runs and
     the score did not move. They are in reading the knowledge base the same way the gold
     author did -- which formula, which denominator, which of two id-shaped columns, whether
     a threshold applies to the rounded or the raw value. Writers flagged exactly these, in
     their own words, on nearly every database.

155. **The last two defects of the LiveSQLBench run, and a third the regression test found.**

     *Defect 24: a computed GROUP BY key correlated its bag on the wrong thing.* **SILENT.**
     When a grouped aggregate is re-lowered over a bag of its own (finding 117), the bag is
     correlated on the group keys. `regroup_grouped` did that by unifying the *nodes the key
     mentions* with their copies -- right for `GROUPED BY d`, wrong for
     `GROUPED BY if(abs(ps - pc) < 0.1 AND pc > 0.7, 1, 0)`, where it says "the same
     peercorr" when the key says "the same side of the threshold". Each bag then held one
     row where the group has many, and the enclosing `MIN` returned the smallest member
     instead of the group's figure. On the company fixture: 88000 / 164000 where the correct
     averages are 95833.33 / 173666.67 -- the minimum of each group, which is exactly what a
     bag of one gives you. A computed key now correlates on the key's *value*, a condition
     equating the outer expression with its copy.

     The insider writer found it, and only because they ran the same query twice, once with
     the key wrapped in `castInteger(...)` and once without: the wrapper binds the key to a
     name, and a name takes the other path. Their unwrapped query returned 3.21 / 4.25
     against the wrapped 14.97 / 10.26. It now returns 14.97 / 10.26 both ways.

     *Defect 2, third site: a template-spelled aggregate over a bag.* SQLite has no STDDEV,
     so the dialect spells it from SUM, SUM of squares and COUNT -- and three sites that
     wrap a bag in an aggregate built the call from the function's *name* instead of the
     dialect's spelling, emitting `STDDEV("v")`. Loud (no such function), and the third
     place this same fix has had to be applied: the two flat call sites in the morning, the
     window path that evening, these three now. All four go through `aggregate_sql`.

     And the hole beside it: a template has nowhere to put DISTINCT, since
     `SUM(DISTINCT x * x)` is not the distinct sum of squares. Where there is a bag the
     distinct is now taken in the derived table, which is the same values once each; where
     there is not, it is refused with a message rather than emitted as `STDDEV(DISTINCT x)`
     for the engine to reject.

     *And a third, which the regression test for the first one exposed.* **SILENT, and the
     worst of the three.** The round-trip check refused the normal form of the new case, and
     the reason was the parser: a `GROUPED BY` key was read as a bound name whenever the next
     token was not `(`, so an expression beginning with a name gave up its first word and let
     the rest be read as part of the query. `GROUPED BY s * 2` grouped by `s` and multiplied
     the *count* by two. No error, a plausible number, and nothing in eleven hundred agent
     queries had written a key that shape. `IF` at the head of a key failed the same way,
     loudly. A key is now a bare name only when the token after it ends the key.

     Three defects, and the third is the one worth remembering: it was found by writing a
     test for the other two, not by looking for it. The suite passes 1078 checks and the
     2,175-query corpus is unchanged; LiveSQLBench stays at 70 of 180, because none of the
     180 shipped answers was written in the shapes these three break -- the insider writer
     shipped the wrapper precisely because the unwrapped form gave them a number they did
     not believe.

156. **Nine answers with every figure right were wrong in the first column, and the listing never said which column that was.**

     The SQL arm beats the ConQuer arm on 17 of the 180. Read against gold, nine of the
     seventeen are one mistake: asked for a thing's id, the writer listed the wrong
     id-shaped value, and every other column of every row was correct.

         credit_1,2,3,5,9   the client reference, where the gold used the other id column
         cross_db_1,3,8     a flow tag -- 952 distinct over 999 rows, not even unique
         crypto_4           the declared surrogate key, where the gold used the key other
                            tables hold

     The other eight are not this and are not fixed by it: JSON spelt as strings (news_2,
     alien_7), a cast (virtual_4), the grain of an average (virtual_3, insider_7), two
     dangling references a join drops (museum_6), and two not yet read (news_9, disaster_1).

     **The cause was not the model and not the compiler. It was one surface.** The model had
     `coreregistry` as CoreRecord's preferred identifier all along. `--schema` printed it as
     `CoreRecord has CoreRecordCoreregistry`, one `has` among 115, directly beside
     `CoreRecord has CoreRecordClientRef`, and a writer asked about *customers* took the
     one named for *clients*. The primer has said "check the listing: denote by the
     identifier it shows" since it shipped on 15 September. It showed none. The reference scheme is the
     first thing an ORM diagram draws and the one thing the listing never said.

     The SQL writer had no such choice to make. credit is six 1:1 tables chained by their
     keys -- rule 7b rightly absorbs them into one entity type -- and `expenses_and_assets`
     has exactly one id-shaped column, `expemplref`. Whoever reads that table cannot pick
     wrong. Absorbing the partitions put both identifiers on one type and dropped the five
     spellings that would have said which one the schema itself uses.

     *What changed.* `--schema` gained an **Identification** section, above the domains and
     the readings, computed from the mapping that was already there:

         CoreRecord    CoreRecordCoreregistry
                         one value, stored as core_record.coreregistry,
                         bank_and_transactions.bankexpref, ... expenses_and_assets.expemplref
                         also unique: CoreRecordClientRef -- a second identifier, with its
                         own values; nothing refers to a CoreRecord by it
         Dataflow      DataflowRecordRegistry
                         other tables refer to it as dataprofile.flowsign,
                         riskmanagement.flowlink, securityprofile.flowkey

     Three things feed it. An absorbed partition's key is now vocabulary (`terms`) on the
     root's identifier, so `expemplref` matches something. `--infer-identifiers` applies the
     alternate keys finding 151 mined, without `--infer-keys` and the model-changing rules
     that ride with it -- it adds a deontic uniqueness constraint and changes nothing. And a
     column that foreign keys reference is shown with who holds it, whether or not it is the
     key. Rebuilt, the 18 models differ from the recorded ones by 3 constraints and 7
     `terms` lists; the mapping is identical and all 180 recorded answers score exactly as
     before.

     **Measured blind: 8 of 30 became 16 of 30, and the tier 71 became 79.** Three fresh
     writers, one per database, all ten questions each so a regression would show; the brief
     said nothing about identifiers. The control is the recorded arm: same questions, same
     knowledge base, the old listing.

         credit     2 -> 6    +1,2,3,5,9   -10
         cross_db   4 -> 7    +1,3,8
         crypto     2 -> 3    +4

     All nine flipped and nothing else moved but credit_10. Two writers said why unprompted:
     "the listing says nothing refers to a CoreRecord by ClientRef", and "`OrderRecordvault`,
     the OB... key other tables hold, not the surrogate". One writer per cell, so the +8 is a
     count of nine named questions changing for a stated reason, not a rate.

     **credit_10 is the benchmark contradicting itself, and it proves the diagnosis.** Six
     credit questions ask for the "customer ID". Five golds project one id column; credit_10's
     gold starts from a different table and projects the other. credit_5 and credit_10 ask
     in the same words and mean different columns. No reading of the question wins all six:
     the identifier wins five, the old choice won one. The gold author used whichever id the
     table in hand happened to carry -- which is what was suspected, shown from the side
     that costs us a point.

     *Rule 1d, and why it is opt-in.* crypto's `orders` declares `orderspivot`, a row
     number nothing references, while three tables reference `orders.recordvault`. The
     listing reports that faithfully and a writer called it "self-contradictory: it names
     OrderSpivot as the identifier, then says nothing refers to it". The contradiction is
     the model's. `--prefer-referenced-keys` resolves it: a single-column key referenced by
     nothing, beside exactly one column that is, verified never null and never repeated,
     becomes the reference scheme -- as a rewrite of the catalogue before the derivation,
     so nothing downstream knows. It fires on 2 of this tier's 175 tables and on 2 of
     BIRD's, and BIRD is why it is never assumed: `cards` is keyed by `id`, referenced by
     `uuid`, and asked about by `id`. It was **not needed for the score** -- the listing
     alone flipped crypto_4 -- and the recorded answers score the same against either model.

     *And a silent defect, found by a writer who disbelieved one row.* A filter on a
     `WITHIN` value wraps the query, and the wrapper's parameters were folded into the inner
     WHERE's list. That is text order only while nothing after the inner WHERE binds a
     parameter, and a computed group key does: `substr(d, 1, 7) AS ym ... GROUPED BY ym ...
     WHERE rk <= 3` executed as `GROUP BY SUBSTR(d, 3, 1)` with `rk <= 7` -- one plausible
     row where there are three. `sql.py` keeps one parameter list per clause precisely so
     that binding follows text order by construction; this clause had never been given its
     list's place in that order. One line. The regression test fails without it, and the
     2,175-query corpus is unchanged.

     Writers also reported, unverified: a `GROUPED BY` beside a `WITHIN` filter returning
     the unfiltered means (credit); `ORDERED WITH` on a `WITHIN` aggregate emitting an
     inner alias out of scope (credit); nested `THE PREVIOUS` compiling to `LAG(LAG())`
     and failing at run time rather than being refused (crypto). And, from all three, the
     same complaint about this listing: a document-valued type shows none of its fields, so
     every `jsonPath` was found by dumping a row. These models were built without
     `--infer-json`.

     **What this says about the 17.** The estimate was "about 8, from the identifier fix".
     It was 9, less the one gold takes back. But the mechanism was simpler than the one
     proposed: not what *preferred* should mean -- it already meant the right thing in eight
     of nine -- but that nobody was told what it was.

157. **The eight that were not identifiers, three reported defects and three more, and the listing finally opens the documents: 79 -> 82.**

     Finding 156 left eight of the seventeen SQL-arm wins unexplained, three writer-reported
     compiler defects unverified, and one complaint from all three writers: a document-valued
     type shows none of its fields. Each, in turn.

     **The eight, read against gold and against the official harness.** Three are not
     misses at all. LiveSQLBench's own `ex_base` rounds every float to two places
     (disaster_1: ours and gold differ in the fifteenth digit from associating a product
     differently), compares `49.0` equal to `49` (virtual_4), and -- this one matters --
     strips the word DISTINCT from *both* statements before running them, including the
     `SELECT DISTINCT` inside our section-14b deduplication bag (virtual_3). Under the
     harness our per-fan average silently becomes gold's per-row one, and passes. Our own
     scorer is stricter than the leaderboard on all three, and finding 154 was classified
     against ours. Two are the gold counting join rows where the definition names
     entities: news_9's "total recommendations" counts join rows where the knowledge base defines
     distinct recommendations, and virtual_3 under our own semantics -- four fans hold two
     memberships each, 14b counts each fan's points once, the gold twice. Two are the
     writer's: museum_6 has no dangling references after all -- two readings carry a NULL
     in one of the two measures, and `has` requires both, the OPTIONALLY trap the primer
     already names; insider_7 averaged at a finer grain than the question asks, and dropped
     the one trader with no transactions. That leaves news_2 and alien_7,
     which asked for a JSON array of objects, and both writers had spelled the object with
     `concat` and eleven quote marks: it gathers as a string that looks like an object.

     *`jsonObject(k, v, ...)` and `json(text)`.* Ten of the 180 golds build a document;
     writers hand-spelled eight of them. The variadic call every dialect has, rendered as
     the engine's own `json_object` so the bytes match; `THE LIST OF` re-reads an object
     gathered through a derived table, where SQLite drops the JSON subtype. And `log10`
     is now the engine's `LOG10`, not `LN(x)/LN(10)`: the ratio is off in the fifteenth
     digit, and a figure inside a JSON column is text, where no rounding reaches it. That
     alone flipped a *recorded* answer (news_8) -- the recorded arm scores 72 against the
     rebuilt models.

     **The three reported defects: two real, one made into a refusal.**

     *`GROUPED BY` beside a `WITHIN` filter returned the unfiltered means.* **SILENT.**
     `THE RANK OF s WITHIN d AS rk AND ALSO THE AVERAGE s GROUPED BY d AS m WHERE rk = 1`
     reads as "rank within each department, keep the top, average"; SQL runs the window
     after GROUP BY, over one arbitrary row per group, so every rank is 1 and the filter
     keeps everything. The credit writer built a median this way and got the mean. Now
     refused where the window reads a row-level value -- a window over the *grouped*
     figure (`THE RANK OF c WITHIN one` over a per-group count, the cross_db writer's
     shape) is correct SQL and stays.

     *`ORDERED WITH` on a `WITHIN` value under a filter wrap: "no such column".* Loud. The
     condition path swaps each window for its alias while rendering; the ordering path
     rendered the expression, naming the inner tables from outside. Same swap.

     *Nested `THE PREVIOUS` compiled to `LAG(LAG())` and failed at run time.* Now refused
     at compile time, naming the DEFINE that reaches two rows back -- the same want as
     finding 152's twenty-four-deep chain, and the message shows the two-line spelling.

     **And three more, found by this round's writers.** Every one silent or scorer-only:

       * Two deferred expressions differing only in a parameter shared one alias. The
         table was keyed on the SQL text, so `(nn + ?) / ?` bound [1, 2] and bound [2, 2]
         were "the same", and `rk = div(nn+1,2) OR rk = div(nn+2,2)` executed as `rk = c OR
         rk = c`: a median returned half its rows. Keyed on the parameters too.
       * A constant group key -- `1 AS g ... GROUPED BY g`, the writers' idiom for "over
         everything" -- rendered as `GROUP BY ?`. Bound, a constant; spelled into the text
         as both scorers do, `GROUP BY 1` is the ordinal of the first output column, an
         aggregate. Ran under `./try`, failed at the scorer. Rendered as `(SELECT ?)`, a
         constant on every dialect and never an ordinal; and the window suite now inlines
         its parameters the way the scorers do, or it could not have caught this.
       * `LIST round(x, 2) AS y FROM ...` backed the parser up and read the whole thing as
         a path, so the message named the first variable, which was fine. Two writers
         each spent a round trip on it; it now says what is wrong where it is wrong.

     One report did not reproduce: "`THE AVERAGE x GROUPED BY g` emitted `MIN(x)` when g
     came from a DEFINE". Both shapes that show `MIN` are correct by construction -- the
     regroup route wraps a bag that computes `AVG("v")` in `MIN(...)`, and the direct
     form fires only where the keys provably pin the value (finding 145's guard). Without
     the writer's query I cannot rule out a third shape; recorded, not closed.

     **The documents.** Rule 12 (`--infer-json`) had never been run on this tier, because
     it *replaced* the opaque value type with the fact types inside it, and 50 of the 180
     recorded answers read a document with `jsonPath` -- the control arm of every
     comparison. The column is now derived both ways: the fact types, and the opaque
     value with a `description` naming them, which the listing prints under *Defined
     terms*. 41 documents across 12 databases became 358 fact types; the mapping of every
     recorded answer is untouched and the recorded arm scores 72 against the new models.
     virtual_4 is the proof of what the typing buys: `has SocialcommunityNetworkFollcount
     fc` returns `3462`, where `castNumber(jsonPath(...))` returned `3462.0` and lost.

     **Measured blind, six fresh writers against the recorded arm:**

         news       5 -> 7    +2, +8      (jsonObject; log10)
         crypto     2 -> 4    +2, +4      (document fields; the identification line)
         virtual    1 -> 2    +4          (typed document fields)
         museum     3 -> 3
         alien      1 -> 1               alien_7: wrote 'True'/'False' for a boolean
         mental     4 -> 3    -10         one writer, one reading; noise

     Merged with finding 156's credit and cross_db runs and the recorded answers for the
     other ten databases, and scored against the expanded models: **82 of 180**, from 71.
     Through LiveSQLBench's own harness the same arm scores **77**, from 71. The five it
     takes back are the harness rewriting our SQL: `remove_distinct` strips the `SELECT
     DISTINCT` that every DEFINE body carries and that news_7 collapses a window with, so
     the CTE multiplies and the answer moves (mental_3, mental_7, news_7); and it checks
     order on tied sort keys (robot_1, robot_4), which finding 154 had called fragility
     and which the leaderboard counts. Both numbers are recorded; 77 is the comparable one.

     *What the round did not fix, and why.* alien_5 wants `json_group_object`, an object
     keyed by a value, and the language has no two-argument aggregate to say it. alien_7
     is the writer's `'True'`; the primer now says a boolean is `if(c, 1, 0)`. news_9 and
     virtual_3 are the gold's. A `WITHIN` partition by a value the group key determines
     is still not checked, and an ordered `THE LIST OF` bound at the top level rather than
     in `IN` form still names an outer alias -- both pre-existing, neither hit here. Three
     writers again asked for a percent rank, a median on SQLite and a string-joining
     aggregate, in that order.

158. **The four things writers kept asking for: an object keyed by a value, a joined string, a percent rank, and a median on SQLite. All four said, and the score did not move.**

     Every round of blind writers on this tier has ended the same way: three or four of them
     name the same missing forms, then report having built each one by hand. Finding 157
     listed the four still open. They share less than they seem to, and that is what made
     them tractable in one round:

     *Two aggregates that take a second operand.* The model's function table has admitted
     a second parameter since it was written (`parameters: [bag, separator]`); the grammar
     had no way to say it. `THE LIST OF x SEPARATED BY ', '` joins the bag as one string
     (`group_concat`, `string_agg`); `THE OBJECT OF v BY k` gathers `{k: v, ...}`
     (`json_group_object`, `jsonb_object_agg`). Both take the grouped form and the `IN`
     form, and in the `IN` form the second operand is written before the path that binds it
     -- `THE OBJECT OF s BY n IN Employee has EmployeeName n AND ALSO has EmployeeSalary s`
     -- as a projection is, because the key is a value of the bag's own rows. `THE PREVIOUS
     x BY t` had already shown the shape. A DISTINCT with a separator is
     `group_concat(DISTINCT x, sep)`, which SQLite refuses ("DISTINCT aggregates must have
     exactly one argument"), so it takes its distinct in the derived table instead.

     *A percent rank, and the direction of a rank.* `THE PERCENT RANK OF x WITHIN g` is
     (rank - 1) / (rows - 1), ordered as `THE RANK OF` is, descending, so 0 is the largest.
     `ASCENDING` after the value turns either rank the other way up. And `WITHIN 1` -- a
     constant, so one partition, the whole query -- now parses: the normal form had always
     printed it and the key parser accepted a word but not a number, which is why every
     writer bound `1 AS one`.

     *A median on SQLite.* An ordered-set aggregate has no closed form over a column,
     which is what finding 103 established and why SQLite declared it absent. It has one
     over a *bag*: the mean of the middle one or two rows of the numbered derived table --
     `ROW_NUMBER() OVER (ORDER BY v)` against `COUNT(*) OVER ()`, rows (n+1)/2 and
     (n+2)/2 -- and a bag is what the compiler already builds for an aggregate over a path
     of its own. The model carries it as `sqlBagTemplate` beside `sqlTemplate`, a template
     over the bag's SQL rather than the column. In place beside `GROUP BY` there is no
     derived table to number, so a grouped median is re-lowered into a correlated bag of
     its own, the route finding 117 built for a value a group repeats and finding 155
     corrected; the enclosing GROUP BY takes the one figure with MIN, as it does there. A
     windowed median has no such route and is refused with the reason.

     **Measured blind, three fresh writers on the three databases whose golds use one of
     these:**

         news      7 -> 7    used SEPARATED BY (news_4), PERCENT RANK ASCENDING (news_6)
         crypto    4 -> 4    used PERCENT RANK ASCENDING (crypto_6)
         mental    3 -> 3    used THE MEDIAN (mental_7)

     All four forms were reached for in exactly the questions they were built for, and the
     three of those questions that were right stayed right -- because the round-2 writers
     had already got news_6, crypto_6 and mental_7 by hand, from a rank and a count, or
     from an offset into a sorted DEFINE. What the forms bought was the hand-building:
     crypto_6 shed 92 characters and news_6 its arithmetic. news_4 stays wrong for a reason
     upstream of its string (the grouping puts a row in a different category). alien_5, the
     question `THE OBJECT OF` was built for, now builds its object right -- and stays wrong
     on its average, where the gold divides integers and truncates, the class finding
     d9943b5 measured at 38 formulas. The tier
     scores **82 of 180** before and after, and 2,175 recorded queries compile to the same
     SQL.

     That is the finding, and it is the same one as finding 156's: a writer who can build
     a percent rank from a rank and a count will, and score the same; the form saves them
     the derivation and the risk of getting it wrong. It costs points only where the
     hand-built version *was* wrong -- and on this sample none of the three was.

     **Two defects the round found, both older than the forms.** Every writer reported
     the first: `WITHIN 1` crashed `./try`. Not the new parse -- the *verbaliser*, which
     `--check` runs, joined the group keys as strings and had therefore crashed on every
     computed key ever written (`GROUPED BY round(s, 0)` too); it now spells them. The
     second: the normal form of a DISTINCT joined list dropped its DISTINCT, and the
     round-trip test in the operator suite caught it before any writer could.

     *Reported again, not yet addressed:* `AND ALSO OPTIONALLY e has X` does not parse
     (three writers, two rounds; `e OPTIONALLY has X` does, and neither does when the step
     is a DEFINE's); a `LIST` of an unbound expression gets the expression as its column
     header; a DEFINE's value type is named for the variable, not the concept, which the
     primer's one example leaves ambiguous; and JSON-derived value types carry no value
     domains in the listing.

159. **The seven frictions left after finding 158, each run down: five were real, one was a crash the primer had been steering writers into, one was documentation.**

     Finding 158 closed with a list of what writers were still reporting. Taken in order.

     *1. `AND ALSO OPTIONALLY e has X` did not parse* -- three writers, two rounds. B.2 puts
     OPTIONALLY before the verb and `e OPTIONALLY has X` always worked; before a bound head,
     where English puts it, the parser read OPTIONALLY as a name. `_at_verb` had always
     skipped the word before an implicit head, which is why the primer's own example
     parsed. Both orders now mean the same thing. What it does *not* change is the primer's
     rule that OPTIONALLY covers one step: `OPTIONALLY e has manager Employee has
     EmployeeName m` still drops the employees with no manager at the second step, and the
     emitter folds the pointless outer join into an inner one -- which is what my first test
     reference got wrong.

     *2. No `THE NEXT`, no window offset.* Not built. `THE PREVIOUS` reaches one row back and
     a DEFINE reaches two; a LEAD is a LAG along the reversed key, which writers have found
     for themselves. Left as it is, deliberately: the three writers who wanted it wanted an
     offset of four, and that is a different feature than a NEXT.

     *3. `THE LIST OF <expr> IN <path>`, and an ordered `THE LIST OF` of an outer-bound
     value.* Two defects. The `IN` form's B.2 detection required `<variable> IN`; an
     expression is now read with forward references, as a projection is, and kept only if
     `IN` follows, so `THE SUM OF round(s / 1000, 0) IN Employee has EmployeeSalary s` says
     what it looks like. The second was a real miscompile that had failed loudly:
     `ground_aggregate` mirrors the enclosing block into the bag and repoints the argument
     at the copy, but the sort keys resolved before the mirror kept pointing at the original
     -- "no such column: employ1.salary" from inside a derived table that had no employ1.
     The keys and the second operand are grounded with the argument now.

     *4. JSON-derived value types had no value domains.* `apply_domains` reads what
     `_domains` mined per column, and a path inside a document is not a column of the
     catalogue, so every fact type rule 12 made came out saying nothing about how its codes
     are spelled -- `AssessmentbasicAnxietyGad7Severity` listed beside a column that shows
     `'Mild', 'Moderate', 'Severe'`. `apply_document_domains` reads each path with the same
     JSONPath the emitter spells for a query, so the domain is exactly what a filter is
     compared against. 107 of the tier's 358 document fact types have one now; the mental
     writer who probed each with `./try` would have had eleven of fourteen in the listing.

     *5. A listed expression's column header was its token stream* -- `round ( s / 1000 ,
     1 )`. Named the way it was written. The one change in this round that touches recorded
     SQL: 44 of the 2,175 corpus queries changed, every one in a column alias and nothing
     else, verified by diffing the statements with the aliases blanked; the baseline is
     rewritten.

     *6. The primer's DEFINE example left the derived type's naming ambiguous.* It is the
     variable's name, capitalised, not the concept's -- `n` gives `BusyN` -- and a
     definition with several values is walked by each variable's own name as the verb, `d
     has c StatC c AND ALSO d has t StatT t`, which the mental writer discovered from an
     error message. Written down.

     *7. The partition of a window beside `GROUPED BY` was not checked.* Finding 157's
     refusal covered the window's argument and order, and left the partition alone because
     a partition by something the key *determines* -- `GROUPED BY d` and `WITHIN dep`, a
     department's code and the department -- is one partition and correct, and telling that
     apart from a partition by an arbitrary row's value needs the model. It has the model:
     a partition node passes if a group key reaches it along steps that cannot fan out
     (a fact's player is one per role; a functional role is entered once; the reverse
     directions likewise), read off the uniqueness constraints the way the locality check
     reads them, and only where they are known. `THE COUNT OF e GROUPED BY d ... THE RANK
     OF c WITHIN n` is refused; `WITHIN dep` and `WITHIN 1` are not.

     **And the one that was not on the list.** Every writer this round reported `WITHIN 1`
     crashing `./try`, the form finding 158 had just put in the primer. Not the parse: the
     verbaliser, which `--check` runs, joined the group keys as strings and had therefore
     crashed on every computed group key ever written, `GROUPED BY round(s, 0)` included.
     Nobody had reported it because nobody had written one under `--check` until the primer
     told them to. It spells them now, and the verbaliser suite pins both.

     Suite 30 of 30 with twelve new checks; the tier scores 82 and 72 as before, since none
     of the seven was a wrong answer. Nothing here was measured blind: each of these is
     effort a writer spent, not a point they lost, and the previous round's measurement was
     that the difference between those two is real.

160. **The review: five places the week's defects pointed at, simplified, with the corpus as the net.**

     Not a benchmark round. Finding 159 closed with a ranking of the code by where this
     week's silent defects had come from, and this is that ranking worked through. The
     gate for every step was the same: 30 suites, and the 2,175 recorded queries compiling
     to the same SQL text *and the same parameter list* as before -- the corpus baseline
     compares both, which is what makes a refactor of the emitter checkable at all.

     **1. `sql.py`: text and parameters travel together.** Four of the week's silent
     defects were one mechanism: parameters bound in a different order from where their
     `?` landed, because text was assembled in one clause while its values were sunk into
     another's list. The eight per-clause lists, `_sink`, `binding()` and the two "lay the
     tail down N times" hacks are gone. Every renderer returns a `Frag` -- text with its
     parameters -- composed with `+`, so a fragment spliced into another clause carries its
     values with it and the statement's parameter list is the text order by construction.
     49 sink references became none; `render` assembles the clauses once at the end. The
     five bag emission sites, each its own copy of "project the value, emit the derived
     table, aggregate outside", are one path plus the flat one.

     Two bugs the structure exposed, both pinned: the ordered bag path never applied
     DISTINCT, so `THE DISTINCT LIST OF g ... ORDERED WITH g THE FIRST 2` gathered
     `["F","F"]`; and a template-spelled aggregate under `WITHIN` inserted the window six
     times but bound its constant once -- `WITHIN 1` on a SQLite standard deviation was
     "Incorrect number of bindings". And one fix of mine the suite refused: promoting a
     LEFT JOIN to FROM in a correlated sub-block loses nothing, because the row it would
     keep is the enclosing one. Reverted, reason in the comment. Corpus: 2,175 unchanged.

     **2. `lower.py`: one answer to "what does this fix".** `check_aggregate_locality` was
     308 lines with eight closures implementing functional determination, and my
     `check_window_over_groups` had re-implemented the union-find and the reach because
     they could not be reached. `Determination` is built once per block and both checks
     read it; 308 -> 186 lines, the second check lost its private copies.

     **3. `reverse.py`: the passes declare their order.** `main` was 308 lines of hand-wired
     flags in a sequence whose order mattered and existed nowhere else -- which is how the
     tier's build command came to be recovered by trial. `PASSES` lists each pass with its
     flag and what it needs before it; `run_passes` walks the list and raises on a missing
     edge; and every model now records the command that built it in `_comment`. Four
     data-reading flags had no "needs a SQLite file" check and reached
     `sqlite3.connect(None)`; the check is derived from the same list now.

     **4. `population.py`: a column is a column or a path.** The domain miner reads either,
     so the document-domain pass is the same code as the column one -- and the unification
     found that the document paths had been skipping the ratio guard and never reporting
     the sentinels they stripped. Three tier reports gain that line; no model changes.
     `report_into` is fifteen reporters called in the old order. The never-null check and
     the profiler were left column-only, deliberately: making them path-aware means
     mapping-driven readables for the whole analysis, which is a larger change than a
     review.

     **5. `derive.py`: one table.** The function library had two mechanisms for a dialect's
     spelling -- a patch dict and per-row name lookups. It is one row per function with the
     spellings beside it, and three kinds of spelling (a template, a name, a bag template).
     Identical output for all three dialects, entry by entry.

     Items 3-5 were done by a fork of the session, in parallel, against the same gates:
     18 tier models and 11 BIRD models rebuilt identical modulo the new build record, the
     suite, the corpus. LiveSQLBench 72 recorded and 82 merged, unmoved, as they should be:
     nothing here was meant to change an answer, and the two bugs it found were in shapes
     no recorded answer had written.

161. **The large tier on the engine it is graded on: the recorded SQL arm cannot be scored there, and the ConQuer arm met four dialect defects the SQLite copies had hidden.**

     LiveSQLBench Large-v1 is PostgreSQL. Everything the pilot had run on this tier ran on
     the SQLite copies `load.py` makes for analysis, because there was no server; there is
     one now -- the dataset's own dumps loaded into `postgres:17` by its own script, 18
     databases -- and `score_pg.py` scores against it the way `score_sqlite.py` does on the
     other tier. Scoring the 48 recorded answers (6 databases x 8) on it says two things.

     **The recorded SQL arm is a SQLite arm.** Its `try` ran `sqlite3` on the copies, and
     the writers wrote for what ran: 28 of 48 answers call `json_extract`, `julianday` or
     `instr`, 37 of 48 fail to execute on PostgreSQL (`round(double precision, integer)`
     is the fourth reason), 7 pass. That is not a score, it is a dialect mismatch, and it is
     the arm's design, not the writers'. The tier has a new form, `pilot.py --tier
     large-pg`: the SQL arm's `try` is the container's `psql`, read-only with a two-minute
     limit, and the brief names the engine. Both arms are being re-run on it.

     **The ConQuer arm is dialect-neutral text, so it can be re-scored -- 8 of 48 on the
     first attempt, and every failure but one was the compiler's.** In order of count:

     - *28 syntax errors at `$`.* The tier models carried `jsonb_path_query_first({0},
       '{1}')`, the path quoted in the template and quoted again by the caller; `derive.py`
       had fixed the template weeks ago, and `bench/livesql/build.py` returns an existing
       model without rebuilding it, so no tier model ever got the fix. Rebuilt.
     - *`round(g6)` refused*: PostgreSQL's template must spell both arguments (there is no
       `ROUND(double precision, int)`, so the value is cast to numeric) and a one-argument
       call did not fit it. A function's parameter may now carry a `default` (schema,
       model.md §3); `round(x)` is `round(x, 0)` on every dialect, as it always meant.
     - *`A, B JOIN C ON C.x = A.y`* -- legal in SQLite, which flattens the list; an error in
       PostgreSQL, where the JOIN binds tighter than the comma and A is out of scope for
       its ON. The roots are joined with CROSS JOIN now, so every ON that follows sees them.
     - *A bare column under GROUP BY*: a fund's name listed beside a total grouped by its
       ticker. SQLite reads it off an arbitrary row of the group; PostgreSQL and DuckDB
       refuse the statement. `lower.note_group_fixed` records what the keys fix
       (`Determination.fixes`) and the emitter names those columns in GROUP BY as well,
       which changes no group. The one case in the sample still fails, correctly: the
       model has no uniqueness on the ticker, so nothing fixes the name -- PostgreSQL is
       refusing an ill-defined query the copies had answered.
     - *`text - text`, `text * numeric`* (7): arithmetic on a date kept as text, on
       `substr` of one, on a figure read out of a document. SQLite converts on the quiet.
       The emitter now casts what the model says is text -- a value type declared
       character or text, a call of a text function -- when it meets arithmetic, a numeric
       comparison, or SUM/AVG (`sql.py` TEXT_TYPES, TEXT_RESULT); a literal never is.

     After these: **19 of 48 strict** (40%), 1 refused (a fact-type name the rebuild made
     ambiguous), 1 the GROUP BY above, 27 wrong. The 27 are the SQLite tier's classes
     again: golds that lower-case their text (4), a label the writer worded differently
     ("Early Filing" for "Early Filing (>6 Months)"), the id-shaped column chosen where a
     name was meant (1), and numeric definitions read differently from the gold (the rest).
     None is a dialect.

     Gates: 30 suites; the corpus compiles 54 of 2,175 to different text (`CROSS JOIN`,
     `ROUND(x, ?)`, the completed GROUP BY, the casts) and every one to the same rows,
     except card_games/349, where `THE FIRST 1` over a tie between two printings of one
     card now picks the other, and formula_1/988, where three averages differ in the
     fourteenth digit because the grouped rows are summed in a different order.
     `conquer.py --dsn` runs a query on a PostgreSQL server, read-only, so a ConQuer arm
     can be pointed at one; parameters are bound client-side because the server cannot
     type `(SELECT $1)`, which is how a constant group key is spelled.

162. **The large tier, both arms written fresh for PostgreSQL: SQL 21 of 48, ConQuer 20 of 48, at one and a half times the tokens; five defects from the writers' hands, fixed.**

     Twelve blind Opus writers, one per (arm, database): the six databases and forty-eight
     questions of finding 161's sample, both arms on the server. The SQL arm had the
     PostgreSQL DDL and the container's `psql`; the ConQuer arm the tier model's listing,
     the primer and `conquer.py --dsn`; both the knowledge base and the same brief as the
     SQLite tier, the engine named to the SQL writers. `pilot.py --tier large-pg` built the
     directories; `work/pilot-pg/` keeps the answers, the sample and the cost ledger.

     **Strict scorer: SQL 21, ConQuer 20** (19 before the fixes below). Both right on 17.
     SQL alone on 4: a threshold read strictly, a "known" filter read narrowly, tie order
     under a rounded sort key, "completed" read as has-a-position. ConQuer alone on 3: the
     regression population, fifteen years kept where the SQL writer kept ten, and the
     typed mass below. Neither on 24 -- and on 14 of those the two arms return *identical
     rows*: the same reading of an ambiguous question, scored wrong against a gold that
     reads it another way (lower-cased text on four, a label's wording, a code kept as
     text, formulas). Per database the arms are within one of each other everywhere. The
     recorded ConQuer arm, written earlier against the SQLite copies and re-scored on the
     server, is 19: the language's answers did not need the engine named.

     **Cost.** The SQL arm spent 640k tokens, 250 tool calls and 41 minutes on its 48; the
     ConQuer arm 946k, 347 and 76 minutes -- 1.48x the tokens, 1.86x the time; per writer
     90-126k against 122-176k. The SQLite tier measured the *prompt* at 60% larger; this is
     the whole conversation, and the extra is the primer to read and the listing to search
     and the more tries before the rows look right, not the answer itself, which is shorter.

     **What the writers found, fixed before the final score:**

     - *A computed group key grouped by what it read.* Finding 161's GROUP BY completion
       took the nodes a computed key mentions as fixed by it; `if(contains(b, 'kep'),
       'kepler', 'v') AS g ... GROUPED BY g` grouped by `b` as well and gave nine rows for
       two. Two writers hit it within the hour of it shipping and both worked round it
       with a DEFINE. Only a key that is a node fixes anything now.
     - *`least` and `greatest` spelled as SQLite's two-argument MIN/MAX* failed on the
       server; the variadic names now, on PostgreSQL and DuckDB. `floor` and `ceil` added.
       `div` and `castInteger` truncate on PostgreSQL as they do on SQLite -- its CAST to
       BIGINT rounds, and a writer who read "integer division" got 4 for 7/2.
     - *`year()` over a date kept as text* was `EXTRACT(YEAR FROM text)`, and `days_between`
       cast `21/12/2023` under a month-first DateStyle. PostgreSQL reads the three lenient
       spellings SQLite does, through a regex over the value's text; a real date column
       passes through unharmed. The labor writer had parsed the dates with `substr`.
     - *A condition over an expression of a grouped aggregate went to WHERE* -- `WHERE
       pct > 15` with `pct` computed from a grouped count -- because the classifier read
       only direct references. `_names_any` follows calculations to what they are built
       on, for HAVING and for the window wrap alike; this was wrong on every engine.
     - *Document fields typed text.* The tier builder took field types from the first word
       of the shipped gloss, so a stellar mass whose gloss did not lead with REAL was text
       and projected as a string where the gold has a number. `build.py` now classifies each
       document column against the rows in the SQLite copies and lets the data type what
       the gloss did not: 411 real value types in planets_data where there were fewer.

     **Reported, reproduced, fixed since (25 Sep):** a DEFINE that reaches an entity through
     a foreign key onto a non-identifier column carried the referencing column in its CTE
     (the ticker) and was joined on the identifier (`productnum`) -- `character varying =
     bigint`, and on SQLite, where the types do not stop it, a plausible wrong total: in
     `test_mapping`'s colliding fixture card A was handed card B's sum. A derived table's
     body now joins the entity on the referenced column and stands on its identifier
     (`sql.Context.identity_of`); the corpus compiles unchanged and the arm still scores 20. And
     reported, not reproduced or not defects: `THE SUM OF if(...)` parses `IF` as §7.5's
     conditional descriptor (parenthesise it); a DEFINE with no aggregate "did not
     register"; `!x` correlation only inside a denotation, so no inequality-correlated
     running total and no running sum at all; `THE LIST OF x IN` will not sit beside
     another value; the narrowed `./schema` view missed MTBF and MTTR for a question that
     never says either word; `ORDERED ... ASCENDING` puts NULLS FIRST where the server's
     default is last; counting a bracketed fan-out counts rows (documented; `THE DISTINCT
     COUNT OF`); and the listing shows every flat column twice, once beside its document
     twin. Every one is in the writers' reports under `work/pilot-pg/`.

     What it says is what the SQLite tier said: with the same definitions in hand the two
     languages land within a question of each other, on a tier where the gold disagrees
     with both of them on fourteen of forty-eight, and the conceptual language costs more
     to write in, not less.

163. **The layer without the language: a SQL writer with the DDL and the description in relational terms scores 19 of 48 -- the plain SQL writer's 21, and the same wrong rows.**

     The arm the reframing depended on. Six blind writers, the same 48 PostgreSQL questions
     as findings 161-162, writing SQL with everything the SQL arm had -- the DDL, the
     knowledge base, `psql` -- plus `./schema`: the conceptual description in relational
     terms (`--schema --relational`), with the table, column, JSON field or foreign key
     beside every entry. If the description is the product, this is the arm that shows it
     working without ConQuer.

     **It did not show that.** 19 of 48, against 21 for the same writers' colleagues with
     the DDL alone and 20 for ConQuer. Sixteen questions all three arms get; on 24 none
     does. Against the plain SQL arm: one gained (planets_data_4, the typed stellar mass),
     three lost (two in sports_events, both judgement calls the description had no part in
     -- "completed" read as a status code, points taken from the knowledge base's table
     rather than the stored column). Per database the two SQL arms are identical except
     there. And on 23 of the narrative arm's 29 misses it returned exactly the rows the
     plain arm did: same reading of the question, same disagreement with the gold. Cost
     730k tokens and 58 minutes -- 1.14x the plain arm, 0.77x ConQuer.

     **What the writers said the description gave them**, all six, unprompted and alike:
     the JSON field paths spelled out (`attorney_profile->'highest_court'->>'state'`), which
     columns other tables refer to a thing by (Fund is keyed by `productnum` and referred to
     by `tickersym` from five tables), that the DDL's declared foreign keys are a
     cross-product of bogus single-column references and the description's are not, and
     which tables are subtypes sharing a key. **And what it did not give them**, all six,
     alike: the value domains and cautions the brief promised. The tier models were built
     from the catalogue fixture (`build.py`), which runs no profiling pass, so the
     description was structure, identification and documents only. Nothing said `statustag`
     is spelled three ways, that 400 of 998 `mtbfh` are null, that 445 snapshots predate
     their plant's go-live, that `revloss` is text with a dollar sign -- every one found by
     probing, every one the kind of thing that decides an answer. Two also said the
     narrowing dropped the tables the definition needed while surfacing distractors.

     **What this says about the layer.** Put beside the earlier numbers it is consistent,
     and it narrows the claim. The +8 (finding 47) was *definitions* -- hand-written, in
     either language. The +11 (finding 156) was identification and documents *to a writer
     who had no DDL*: the ConQuer listing was all they had, and the listing had not said
     which of three id-shaped columns names a customer. A SQL writer has the DDL, sees the
     key, and reads the JSON with `->>` after one probe; the structure re-stated in
     sentences is not information to them. What the layer can carry that the DDL cannot is
     what people wrote down (definitions) and what the rows say (domains, cautions,
     contradictions of the documentation) -- and this arm had the first from the knowledge
     base like every arm, and the second not at all. The experiment that is still open is
     the profiled description: the tier's models rebuilt from the data with the flags the
     SQLite tier used, and this arm run again. It is the one that would say whether the
     description as a *product* moves a SQL writer, and it costs another six writers.

     Tooling: `conquer.py --schema --relational` (`storage(model)` reads the mapping),
     `pilot.py --arms sqlnar`, the answers and ledger under `work/pilot-pg/`, and
     `mcp/server.py`, which offers the same description as `describe_schema(relational=
     True)` beside `run_sql` -- the configuration this finding measured.

164. **The MCP server, end to end on BIRD: ConQuer 76 of 100, SQL 75 -- the recorded Opus arms' numbers, verdict for verdict -- and the SQL writer had no DDL, only the description.**

     Twenty-two blind Opus writers, one per (arm, database), the 100-question sample of
     finding 47 onwards. Each directory held `questions.json` and `./mcp`, a stdio client
     to `mcp/server.py`, and nothing else: the brief (`writing_brief`), the description
     (`describe_schema`), the runner (`run_query` or `run_sql`) all came over the protocol,
     and every call started the server (~2 s). The SQL arm had **no DDL** -- the description
     in relational terms was its only account of the data. The ConQuer arm had what the
     recorded arms had, served. Cost: ConQuer 875k tokens and 56 minutes, SQL 679k and 44
     (1.29x); every writer called the latency negligible and batched calls to hide it.

     **76 and 75.** The recorded arms with the same writer model and the shell scripts
     (`conquer_opus`, `direct_opus` with the DDL) scored 76 and 74; the served arms give the
     *same verdict* on 96 and 97 of the 100 questions. Both right on 71, ConQuer alone 5,
     SQL alone 4, neither 20 -- and on 18 of those the two return identical rows. The
     protocol is not a variable: the server is the harness, and a writer who knows only
     the six tools does what a writer with the scripts did.

     **The description alone was worth the DDL.** 75 without it against 74 with it. Read
     beside finding 163, where the description *beside* the DDL was worth nothing on the
     PostgreSQL tier (19 against 21), the difference is what the description carried:
     BIRD's models were built with `--infer-domains`, and the writers said which answers
     the domains decided -- `'east Bohemia'` with its lower-case e, SM's `'0'`/`'negative'`
     ("without it I would have guessed SM = '-' and lost 1267"), `'F'`/`'N'`/`'P'`, DOC
     `'31'` as text, the four dates transactions actually hold. The tier's models had no
     domains and no cautions, and the writers there asked for exactly those. So: the
     description is worth the DDL when it carries what the rows say, and nothing beside the
     DDL when it does not. That is the layer's value, stated twice from two sides.

     **What twenty-two reports said, and what changed.** The brief served as a prompt was
     enough on its own, 22 of 22; the tool descriptions were clear, 22 of 22. What
     `describe_schema` gave: what identifies a thing and which columns other tables refer
     to it by, every relationship as a sentence, the verb parts that tell eye from hair from
     skin colour, and the domains. What it missed: domains only on low-cardinality columns
     (writers probed for `'Game'`, `'Closed'`, a nationality); no cautions, because these
     models were built without `--profile` while the tool's text promised them (the text now
     says "where the model was profiled"); no date formats, row counts, or that `connected`
     stores each bond twice. And **the narrowing**: fourteen of twenty-two said the
     question-narrowed view had hidden the one type they needed -- Tag, Driver, ForeignData,
     Client, Card, the ring reading of Connected -- behind "N more entity types exist and
     are not shown". Fixed the same day: the listing names what it left out, and the server
     describes a schema of fifteen entity types or fewer whole. One writer also found the
     identification section pointing at `uuid` where BIRD's "card id" means `cards.id`: rule
     1d's question (finding 125), now visible from the SQL side.

     `run_query`'s reading earned its place in the ConQuer reports: the grain caution caught
     the fan-out on 672 (19 users for 14), 1267 (7 for 6) and 1505, and the tie warning sent
     writers to check 349, 794 and 212. It caught nothing a writer called wrong.

     **Open, from the reports:** a `[...]` filter that binds a variable is hoisted into a
     JOIN, where the same bracket without one is a semi-join, so a COUNT silently multiplies
     (two writers; `THE DISTINCT COUNT OF` was the fix each found). A Card-headed query
     walking backwards through `is of Legality [...]` ran about eight minutes -- a
     correlated EXISTS per filter over 56,000 cards -- where the same question head-first
     ran in seconds, and nothing warns which end to start from. `Race [filter] r` is a
     parse error with a message pointing elsewhere (the variable precedes the bracket).
     A `LIST` of unnamed scalars uses the whole expression as the column header. And the
     client's documented single-quote escape is fragile from a shell heredoc; writing the
     JSON to a file worked. The answers and the ledger are under `work/conquer_mcp/`,
     `work/direct_mcp/` and `work/mcp/`; `score.py` scores both arms.

165. **The profiled description beside the DDL: 23 of 48, against 19 unprofiled and 21 for the DDL alone -- and not one of the gains traces to what the profiling added.**

     The experiment finding 163 left open. The six tier models were rebuilt with what the
     rows say (`build.py --profiled`: the same catalogue fixture and documents as `build`,
     plus `--infer-domains --infer-enforced --infer-partitions --merge-domains --profile
     --expand-names --infer-identifiers`, read from `load.py`'s SQLite copies of the same
     rows), and the sqlnar arm was run again as `sqlnarp`: six fresh blind Opus writers,
     the same 48 questions, knowledge base, DDL and brief word for word -- a brief that
     had promised domains and cautions the first time too. Only the model moved. Cost 526k
     tokens and 23 minutes, the cheapest SQL arm yet (sqlnar 730k, plain 640k).

     **23, and the gains are judgement calls.** Against sqlnar five gained, one lost;
     against the plain arm four and two. Read answer by answer, the gains are: the stored
     sprint `points` taken over the knowledge base's points table (sports_events 9 and
     12 -- one decision, scored twice, and exactly the one finding 163 recorded going the
     other way); the latest reading per artifact (museum_artifact_5); nulls filtered
     before a window and a regression (exchange_traded_funds 2 and 8). No writer tied any
     of them to a domain or a caution, and the lost one (exchange_traded_funds_14) is a
     different reading of the Information Ratio. 23 misses are shared by all three SQL
     arms. On 48 questions a swing of four between two sets of writers is inside what
     finding 47's noise says a swing of three on a hundred is: this does not show the
     profiled description moving a SQL writer, and it does not show it failing to.

     **What the writers used, and what they still did not get.** All six named the domains
     as the thing the DDL lacked -- `warrstate`, `busbar_corrosion`, the three spellings of
     `statustag` (now a caution, where in 163 it was found by probing), `masssource`'s
     `'Msin(i)/sin(i)'`, risk and budget levels -- beside the JSON paths and the
     referring columns 163's writers already had. And they named what profiling did not
     say, which is the list of what would have decided answers: `performance.topweight`
     is null in every row (the one caution ETF needed); three date text formats in one
     labor table and empty strings in `decisionday`; a third of solar's snapshots before
     their plant's go-live; two routes from a plant to its panel model that disagree for 61
     plants; mostly-null `acc_pt`. The profiler reports low-cardinality domains, case
     variants and 'None'-for-absent; it has no caution for an all-null column, a mixed date
     format, or a date-order contradiction -- the next thing to build if the description is
     to carry what the rows say.

     **Defects the reports found.** `--expand-names` read `compcount` as
     `StarComplianceCount`, hiding the planet count a "multi-planetary" question needs.
     Keys with 10 and 3 distinct values (museum `ArtifactRatings.HIST_sign`,
     `SensitivityData.ENVsense`) are presented as ordinary identifiers, as is a
     `RevenueStreamSource` alternate key in sports. Some identification lines are filed
     under the wrong entity type. Narrowing still hands a writer 40-100 KB. And
     `load.py` had turned a column named `timestamp` into one named `TEXT` (the type
     rewrite matched inside a quoted identifier); fixed, and solar's copy reloaded.

     **What it says.** With finding 164 the picture is: the description carrying domains
     is worth the DDL to a writer who has nothing else (75 v 74), and beside the DDL it is
     somewhere between nothing and a few questions (23 v 21, 19 v 21), no measurement here
     able to say which. The answers and ledger are under `work/pilot-pg/sqlnarp/`.

166. **At scale, the description does not beat a narrowed DDL: 26 of 100 against 29, and 28
     for the full DDL. The pre-registered prediction failed.**

     `livesql/SCALE.md` fixed the question, the arms, the prediction and a kill criterion
     before any writer ran, and the page records its calibration from before the run. Ten
     PostgreSQL-tier databases the earlier rounds had not used, ten questions each; thirty blind writers, Claude Opus 5.5, one
     per (arm, database), every arm writing SQL with the knowledge base and `./try`. They
     differed only in how they saw a schema of ~54 tables and ~980 columns: the full DDL
     (`sql`), the DDL narrowed by a lexical retriever (`sqlddlk`, `ddl_link.py`), or the
     profiled conceptual description narrowed by `link.py` (`sqldesc`), the two narrowers
     calibrated to show about the same amount of text.

     | | of 100 | tokens | writer time |
     |---|---|---|---|
     | `sql`, the full DDL | 28 | 0.87M | 36 min |
     | `sqlddlk`, the DDL narrowed | 29 | 0.90M | 45 min |
     | `sqldesc`, the description narrowed | **26** | 1.05M | 63 min |

     Description against narrowed DDL: 1 question won, 4 lost, p = 0.38. The kill criterion
     was a difference of 3 or less; it is -3. Without `mental_healths` (shared drafts) and
     `virtual_idol` (below) it is 20 against 24 of 80, the same order. The prior written
     down beforehand put 60% on this outcome and expected the full-DDL arm to hold its own,
     which it did.

     **The retrieval won and the answers did not.** Measured before the run, at equal size
     the description kept every table the gold uses on 72 questions and the DDL retriever
     on 51. None of it reached the answers, for three reasons the writers stated:

     - *The writers do not need the narrowing.* Every arm can query the catalogue through
       `./try`, and writers in all three used `information_schema`, sample rows and
       GROUP BY profiling to find what they needed. The full-DDL writers searched the file.
       A narrower is a convenience to an agent with a database connection, not a gate.
     - *The description is too big to read.* On these densely connected models `link.py`
       keeps about half the schema: 80 KB narrowed, 300-360 KB whole, twice the DDL. Five
       description writers reported output too large to print; one (`virtual_idol`) was
       blocked from paging it and never used the description at all.
     - *Where the answers turned, the description had nothing to say.* The misses are the
       benchmark's semantics, the same in every arm: which of several bridge tables links
       an operation to a disaster, whether a bare `'2'` is `'Status 2'`, a stored score that
       contradicts its own definition, a knowledge-base formula whose columns do not exist,
       one timestamp shared by every row. Profiling reports what the rows hold; none of these
       is in the rows.

     What the description writers said it *did* give them was real and specific: the exact
     spellings of values (`Level3` for a Tier-3 escalation, `'Moderate'`), unit cautions
     (`'$65.20 '`, `'0.12 Threats/hour'`), JSON paths, and which columns join. The plain-DDL
     writers found the same things from three sample rows and a few probing queries, a little
     faster. What it missed: unit suffixes it did not flag (`'0.30%'`, `'49.30 m/s'` under a
     key named `speed_kmh`), mixed date formats, value domains inside JSON columns (the
     profiled models infer none there), and in one database two columns it silently left out
     (`administrative_and_review.tx_cen_code`, `rec_cen_code`).

     **Process defects, stated so the numbers are read with them.** Writers in batches one
     to three saved drafts in one shared scratch folder; one overwrote another's, and two
     `mental_healths` arms submitted byte-identical 1,000-character answers. Seventeen answer
     pairs are identical across arms of a database. Copying pulls arms together, so it cannot
     have hidden an advantage, but it does mean the three arms are less independent than
     designed; later batches were told to keep drafts in their own directory. The narrowed
     arms were told not to read the narrower's sources; a few read a saved copy of its full
     output outside their directory before being blocked.

     **What it says.** The conceptual layer's one structural argument at scale -- better
     retrieval of the schema a question needs -- holds as retrieval and does not survive
     contact with an agent that can query the database. With findings 163-165: the
     description helps where it says what the rows alone do not, and at this scale, for
     these writers, it said little of that. Answers, reports and ledger are under
     `livesql/work/pilot-scale/`; `livesql/score_scale.py` reproduces the table.

167. **A better description, retested on four held-out databases: 12 of 40, against 14 for the
     old one and 13 for the narrowed DDL. The pre-registered prediction failed again.**

     Finding 166's writers named what the description lacked, and the fixes were made as
     general rules: value domains and value cautions inside JSON columns, `'0.30%'` counted
     as a quantity with its unit, dates in several shapes, values that look like two
     spellings of one (`'2'` and `'Status 2'`), constant columns said in the listing, two
     things linked several ways and whether the ways agree, and `conquer.py --schema
     --knowledge`, which names the business terms a question uses and the columns most
     likely to hold their inputs. The new models carry two to three times the cautions
     (exchange_traded_funds 76 -> 252, most of them percentages inside JSON). The size of
     the narrowed description was deliberately not changed.

     `livesql/SCALE2.md` fixed the arms, the prediction (the new description at least 3 of
     40 above the old) and the kill (0 or less) before any writer ran. Four databases none of
     the rules was written against, ten questions each, twelve Opus 5.5 writers, every arm
     writing SQL:

     | | of 40 | tokens | writer time |
     |---|---|---|---|
     | `sqlddlk`, the DDL narrowed | 13 | 0.33M | 22 min |
     | `sqldesc`, the old description | 14 | 0.37M | 25 min |
     | `sqldesc2`, the new description | **12** | 0.36M | 18 min |

     New against old: 0 won, 2 lost, p = 0.50. Without `archeology_scan` (below) 10 against
     12 of 30; without `labor_certification` as well, 8 against 10 of 20. Every difference is
     one or two questions. The prior put 65% here.

     **What the writers said about the additions.** Used and credited: the route cautions
     (robot_fault: "the four routes between operations and actuation records agree, so the
     join path doesn't change results"; archeology: "site-equipment routes disagree, which
     pushed me to join on both"), the constant dates, the three date formats, the three
     spellings of one status, the percent units inside JSON. **Named as wrong by all four
     new-description writers: the business-term column hints** -- Median 1-Year Return
     pointed at `annual_returns.yearlyid`, Relative Positional Error at an end-effector
     column, NAICS and jurisdiction at an unrelated table, Structural Stability at unrelated
     columns. Matching a definition to columns by shared words is too weak on schemas whose
     column names are abbreviations of abbreviations; the hints cost reading and pointed
     the wrong way.

     **Why better content did not move the score.** The same three reasons as finding 166,
     unchanged by the additions. The description is still too large to read (87 KB narrowed,
     210-420 KB whole); two old-description writers were blocked from saving it and worked
     from the catalogue instead. Writers find the structure themselves through `./try` and
     `information_schema`, in every arm. And the misses are the benchmark's own semantics:
     a knowledge base that names applications absent from the data, every case certified so
     every rate is 100%, formulas over quantities no table holds (population, workforce,
     "recent price"), output shapes the question leaves open.

     **Process.** The narrowed-DDL writer on `archeology_scan` was blocked by the permission
     system from reading its schema and then from running `./try` at all, and submitted ten
     untested answers, some naming columns it never saw. The old-description writer on
     `labor_certification` was refused when it tried to save the description to search it,
     and worked from the catalogue. Both cells are compromised by tooling; the comparisons
     are reported with and without them. Seven answers are byte-identical across arms of one
     database, all on short or deterministic queries; drafts were kept per directory this
     round.

     **What it says.** Two pre-registered rounds agree. At this scale, for agents that can
     query the database, the description's content -- old or improved -- does not add to what
     a narrowed DDL and a few probing queries give, and the business-term mapping as built was
     a net negative; it has been removed from `conquer.py` (and the `sqldesc2` arm from
     `pilot.py`), so that arm cannot be rebuilt from this code. The profiling additions are correct and are kept: they are what the
     writers asked for, and they are right about the data. They do not change answers here.
     Answers, reports and ledger are under `livesql/work/pilot-scale2/`.

168. **The layer cut to its difference from the DDL, and the business terms derived and
     checked: 25 and 25 of 60 against 22 for a plain DDL of the same size -- and the whole gap
     is one database where the plain DDL's writer was blocked. Both pre-registered predictions
     failed.**

     `livesql/SCALE3.md` acted on what findings 166 and 167's writers said. **Option 1**
     (`conquer/annotate.py`): the model chooses the tables, the writer reads them as DDL, and
     beside each column go only what the DDL does not say -- values, profiling cautions, JSON
     fields, join routes -- inside 16,000 characters, a fifth of the earlier description.
     **Option 2** (`terms.py`, `DEFINE.md`): one blind definer per database, which never saw a
     question, wrote every knowledge-base term's derivation in this database; each was run and
     its result recorded beside the definition. 321 of 339 terms were derived, for 0.64M tokens
     and 52 minutes over six databases. The control was the same view, the same budget,
     chosen lexically with no comments. Six held-out databases, sixty questions, eighteen Opus
     5.5 writers.

     | | of 60 | without `planets_data` | tokens | writer time |
     |---|---|---|---|---|
     | `ddlp`, plain DDL | 22 | 22 of 50 | 0.45M | 76 min |
     | `ann`, annotated | 25 | 19 of 50 | 0.45M | 58 min |
     | `annd`, annotated and derived | 25 | 18 of 50 | 0.56M | 48 min |

     `ann` against `ddlp` is +3, the pre-registered threshold, but all six of `ann`'s wins are
     on `planets_data`, where the `ddlp` writer was blocked by the permission system and
     submitted nothing; without it, 0 won and 3 lost. `annd` against `ann` is 2 won, 2 lost.
     On the three databases no cell was compromised on, 16, 13 and 14 of 30. The prior gave
     35% and 40%; neither came in.

     **Where the arms differ at all.** Thirty questions were wrong in every arm and seventeen
     right in every arm; the arms disagree on thirteen, seven of them the blocked cell. That is
     the shape of findings 166 and 167 again: what decides these questions is not in the schema
     material any arm was given.

     **What the writers said.** All six `annd` writers credited the derivations, four in the
     words "decisive" or "did most of the work": the obscure columns named (`sprint_performance`,
     `st_mark`, `acc_pt`), the non-obvious joins (museum's artifact-to-reading chain, which the
     plain-DDL writer had to infer from row alignment), the case-sensitive `'Stable'` test,
     the warnings that several answers would be empty. `ann` writers credited the annotations
     -- JSON key lists and value lists, the routes to panel models that disagree, the robot
     routes that agree -- and one said the view for `planets` had left out most of that
     table's columns. `ddlp` writers had to find all of this by querying, and did: every
     plain-DDL writer that could query named the same joins and JSON keys. The derivations
     saved time (48 minutes of writer time against 76) and settled what the writers were
     unsure of, and the answers came out the same.

     **Why it did not move the score.** The misses are the questions' own readings -- the
     grain of a result, the base of a percentage, age at the race or today, a threshold no
     definition names, a sort order the question leaves open -- and a derivation settles
     which column holds a quantity, not which of two readings the question meant. On
     `robot_fault_prediction` both layer arms took a different reading from the plain writer
     on two questions -- distinct robots rather than records, robots with no calibration
     reading kept -- and lost both.

     **Process.** Four cells were compromised by tooling. `ddlp` on `planets_data`: blocked
     ("PII Data Handling") on its second `./schema` call, no answers. `ann` on `sports_events`:
     blocked on its first `./try`, ten untested answers. `ann` on `archeology_scan`: a few row
     counts blocked. `ddlp` on `archeology_scan`: the Docker daemon stopped mid-run and nine of
     ten answers were never executed. Two writers briefly wrote empty scratch files to `/tmp`
     and deleted them. Nine answers are byte-identical across arms, all short deterministic
     queries.

     **What it says.** Three pre-registered rounds agree. At this scale, for agents that can
     query the database, neither the conceptual description, nor the annotated DDL, nor the
     business terms derived and checked in advance changes how many answers are right; the
     derivations do make the writers faster and surer. `annotate.py` and `terms.py` are kept
     as tools, measured and not recommended as an accuracy lever. Answers, reports and both
     ledgers are under `livesql/work/pilot-scale3/`; the definers' derivations are under
     `livesql/work/pilot-scale3/terms/`.

169. **What Shkapenyuk et al. used and no round here had: the benchmark's own column meanings,
     descriptions an LLM wrote from a column profile, a value index and linking by draft
     queries. 28, 26 and 26 of 60 against 28 for the plain DDL. All three pre-registered
     predictions failed.**

     Shkapenyuk, Srivastava, Johnson and Ghane (arXiv:2505.19988) report, for single-shot
     GPT-4o on BIRD mini-dev, 49.8% with no column metadata, 59.6 with BIRD's own, 61.2 with
     profile descriptions and 63.2 with both. `livesql/SCALE4.md` tested their four pieces on
     SCALE3's sixty questions, with agents that can query the database. `profile.py` built
     the column profile, a value index (up to 10,000 distinct values per column or JSON field)
     and LiveSQLBench's `column_meaning_base.json` flattened -- which no writer in any earlier
     round had been given. Six describers, seeing only the profile, wrote 5,871 column
     descriptions (1.28M tokens); six linkers, seeing the questions, knowledge base and
     annotated schema but not the database, wrote two drafts of each question and listed what
     they used (0.50M). Every arm had 20,000 characters.

     | | of 60 | without `sports_events` |
     |---|---|---|
     | `ddlp4`, plain DDL | 28 | 24 of 50 |
     | `ddlm`, + column meanings | 28 | 24 |
     | `annm`, annotated + meanings + profile descriptions | 26 | 22 |
     | `annl`, + value index + draft-query links | 26 | 26 |

     Meanings against none: 2 won, 2 lost. Profile descriptions and the model on top: 0 won,
     2 lost. Links and values on top: 4 won, 4 lost -- but the `annl` writer on
     `sports_events` was blocked and submitted nothing, and without that database `annl` is
     4 won and 0 lost against `annm` (p = 0.12) and 2 and 0 against the plain DDL: the one
     direction in four rounds that favours the layer, inside the noise. The plain-DDL control
     reproduced SCALE3's (21 and 22 of 50 on the five databases where neither was blocked).
     Across SCALE3's three arms and these four, 29 of the 60 questions were wrong every time.

     **What the writers said.** The descriptions were read and credited, more than anything
     given in earlier rounds: "the column comments were essential", "the comments are what let
     me match" the knowledge base's `actual_payload_weight` to `payloadwval`; the JSON field
     listings, value ranges ("the range notes are what showed that Q12, Q17 and Q5 have no
     matching rows") and route warnings. Plain-DDL writers found the same by querying ("you
     only see this from the sample rows"). And every arm's misses were the same readings as in
     findings 166-168: podium from `driver_standings` or from sprints, a percentage's base,
     distinct robots or records, age now or at the race, a rate stored as a percent. The
     meanings do not say which reading the question's author meant.

     **Why this does not contradict the paper.** Their writer is single-shot and never touches
     the data, so its "no metadata" baseline is blind, and metadata is its only way to learn
     what a column holds. These writers query the database; the meaning of `overseerloadvalue`
     matters, but a writer that can look at its values and at the knowledge base's formula
     recovers it. The benchmark's own column descriptions, their largest single effect, added
     nothing here.

     **Found on the way.** The annotated view listed at most 24 fields of a JSON column even in
     the full view (fixed before the writers ran, `SCALE4.md`). The constant-column caution
     counted rows with a value, not rows: `constructor_results.st_mark` is null on 1,952 rows
     and 'D' on one, and the view said every row held 'D'; `reverse/population.py` now requires
     fifty non-null values. The `sports_events` knowledge base assumes a main-race results
     table the database does not have, and the robot one carries thirteen disaster-relief
     terms; both were met by every arm.

     **Process.** `annl` on `sports_events` blocked by the permission system ("PII Data
     Handling") after one full view; `ddlm` on `archeology_scan` had one query refused. Two
     writers wrote empty scratch files to `/tmp` and deleted them. The four `robot` writers ran
     a few minutes after the others (the subagent limit). Nineteen answers are byte-identical
     across arms, short deterministic queries. Answers, reports and both ledgers are under
     `livesql/work/pilot-scale4/`; the metadata is rebuilt by `profile.py` and `scale4.py` and
     not distributed, being made from the benchmark's rows, meanings and questions.

     **What it says.** Four pre-registered rounds agree. At this scale, for agents that can
     query the database, no description of the schema -- the model's, the benchmark's, or an
     LLM's from a profile -- and no linking, value index or pre-derived term changes how many
     answers are right. What decides them is how each question is meant to be read.

170. **The misses at scale were readings, not retrieval. Of 538 wrong answers across the four
     scale rounds, 53% used every table, column and JSON field the gold used and still answered
     something else; and the misses that did leave out a gold table or column were made just
     as often by the writer who could see the whole schema.**

     `livesql/misses.py` puts every wrong answer beside the gold and classifies it: no answer
     or an error (21, 4%); the answer does not use every table the gold uses (117, 22%); it
     does, but not every gold column or JSON field (116, 22%); it uses all of them and differs
     in a filter, grain, formula, order or rounding (284, 53%). The test is lexical, so a
     column named but misused counts as used.

     Taken at face value, 44% would be retrieval -- what BM25, a Steiner tree over the model or
     Bird's abstraction could fix. The control says otherwise. In `SCALE.md` the `sql` arm had
     the full DDL in a file and saw every table. On the questions where a narrowed arm left out
     a gold table, the full-DDL writer left out a gold table too on 16 of 17 (`sqlddlk`) and 15
     of 17 (`sqldesc`), and got the question right once in 34. Where a narrowed arm left out a
     gold column, the full-DDL writer did the same on 9 of 10 and 10 of 11, and got none right.
     These are choices -- the standings table for a podium, the stored rate or the computed
     one, the panel model's route -- made the same way whether or not the other option was on
     screen. In SCALE3 and SCALE4 the view for the question's own text lacked a gold table for
     155 of 240 misses, and the misses were no fewer where it had them all; writers widened the
     view or queried the catalogue.

     So retrieval accounts for at most about one wrong answer in a hundred here, and a better
     selector of the model's parts would not move these scores. It would matter to a one-shot
     writer that cannot widen its view -- which is where the published gains from linking come
     from. `misses.py` prints counts only; the per-question classification uses the private gold
     and is not committed.
