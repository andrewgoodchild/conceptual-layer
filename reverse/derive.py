"""Derive a draft Common Core Model from a relational catalog.

Implements the rule table in reverse/README.md ("The rules"), which inverts Halpin's Rmap;
reverse/relational-to-orm-reverse-engineering.md is where the rules came from. Rules 1-6 are
sound and applied silently. Rules 7-8 are heuristics: applied, and every instance reported.
Rules 9-10 are guesses: 10 (naming) is applied because a draft needs names and every name is
reported; 9 (undeclared foreign keys) is off unless asked for with `--infer-fks`, and reported
wherever it is applied.

The output is a DRAFT. Halpin, who shipped this in Visio for Enterprise Architects, says so
himself: "In practice, any draft ORM schema obtained by reverse engineering usually needs many
refinements." The refinement report this module returns alongside the model is that sentence
turned into a worklist.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from catalog import Catalog, ForeignKey, Table

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from model import names as _names                                      # noqa: E402

# --------------------------------------------------------------------------- naming (rule 10)

_WORD = re.compile(r"[^0-9a-zA-Z]+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


# How a schema spells things lives in model/names.py, because the query side needs the same
# answers: a name is split the same way whether it is becoming a concept or being matched
# against a question. Re-exported here, where rule 10 has always called them.
words, pascal, singular, is_abbrev = _names.words, _names.pascal, _names.singular, _names.is_abbrev
unit_of = _names.unit_of


def strip_prefix(column: str, table: str) -> str:
    """Drop the table's name from the head of a column name.

    Three forms, all rule 10 guesses: an exact prefix (`employee_name`), a shared leading
    run of CamelCase words (`InvoiceLineId` against `InvoiceLine`), and an abbreviation
    (`dept_code` against `department`)."""
    c, t = column.casefold(), singular(table).casefold()
    # With a separator the match is unambiguous at any length (`dept_code` from `dept`).
    # Without one it is only safe for a table name long enough to be a real prefix: table `p`
    # would otherwise turn every column into a fragment, `pri` -> `ri`.
    for candidate in ([t + "_"] + ([t] if len(t) >= 3 else [])):
        if c.startswith(candidate) and len(c) > len(candidate):
            return column[len(candidate):].lstrip("_")

    cw, tw = words(column), words(singular(table))
    shared = 0
    while shared < len(cw) and shared < len(tw) and shared < len(cw) - 1 \
            and cw[shared].casefold() == tw[shared].casefold():
        shared += 1
    if shared:
        return "".join(cw[shared:])

    head, _, tail = column.partition("_")
    if tail and is_abbrev(head, t):
        return tail
    return column


# The spellings a column uses when it holds an identifier, for anything asking "is this name
# an identifier's name" -- `population.py` scores candidate keys and references with it. The
# underscore forms (`_id`, `_code`) need no entry of their own: a suffix test on the bare word
# already matches them.
KEY_SUFFIXES = ("id", "no", "nr", "code", "key")


def terms_for(name: str, source: Optional[str] = None) -> List[str]:
    """The words this concept is known by, beyond the name rule 10 gave it.

    Rule 10 computes three things and used to keep one: the source name, its word split, and
    whether a word in it is an abbreviation of a word in the name. All three are what a
    question has to be matched against -- `emp_name` is what a DBA types, `emp` is what rule 10
    silently expanded to `Employee` -- so they are written down rather than discarded.

    Vocabulary, not names. `aliases` resolve in a query and can collide; these only ever widen
    what a matcher will accept.
    """
    out = {name.casefold()}
    for w in words(name):
        out.add(w.casefold())
    if source:
        out.add(source.casefold())
        source_words = [w.casefold() for w in words(source)]
        out |= set(source_words)
        # `emp` -> `employee`: the expansion rule 10 already made, kept beside the short form
        for short in source_words:
            for long in (w.casefold() for w in words(name)):
                if is_abbrev(short, long):
                    out.add(long)
    return sorted(t for t in out if len(t) > 1)


def strip_key_suffix(column: str) -> str:
    # Deliberately narrower than KEY_SUFFIXES: this one *renames*, and a bare `code` or `key`
    # is usually the value itself (`barcode`, `sortkey`), not a suffix on something else.
    # `_name` is here for the same reason in reverse -- it is a suffix worth losing in a name.
    for suffix in ("_id", "_no", "_nr", "_code", "_key", "_name", "id", "no", "nr"):
        low = column.casefold()
        if low.endswith(suffix) and len(low) > len(suffix):
            return column[: -len(suffix)].rstrip("_")
    return column


PREPOSITIONS = {"to", "of", "from", "by", "for", "with", "in", "on", "at", "into", "under",
                "over"}


def ring_label(label: Optional[str], player: str) -> Optional[str]:
    """A ring role's label, if it says something the player's name does not.

    `manager_nr` on employee says "manager". `atom_id2` on connected says "atom", numbered:
    the player again, which is what a self-join's columns are usually called in a schema
    that has nothing to say about direction. So is `a`/`b`.
    """
    base = re.sub(r"\d+$", "", label or "")
    base = pascal(strip_key_suffix(base)) if base else ""
    if len(re.sub(r"[^A-Za-z]", "", base)) < 3 or base.casefold() == player.casefold() \
            or is_abbrev(base, player):
        return None
    return label


def ring_readings(table: str, player: str, labels) -> Optional[List[Tuple[str, Tuple[int, ...]]]]:
    """Rule 10 for a ring fact type: readings guessed from what the schema does say.

    `{0} has {1}` over two roles of one type says nothing -- "Atom has Atom" -- and leaves a
    query no way to say which way round it walks except by role name. The column labels or
    the table name usually do say. `manager_nr` reads `{0} has manager- {1}`, the hyphen
    binding the adjective to the object type as FORML 2 §1.2 has it, with the inverse
    `{0} is manager of {1}` read from the other end; `bom(parent, child)` reads `is parent
    of` one way and `is child of` the other; a column `reports_to` is the verb itself; a
    table called `connected` reads `is connected to`, `follows` reads `follows`, and a noun
    such as `friendship` reads `has friendship with`.

    Returns [(text, role order)] with the reading from the first role first, or None when
    nothing in the names says anything, in which case the placeholder stays and the report
    says so. Every one of these is a guess and is reported as one.
    """
    def phrase(label):
        return " ".join(w.lower() for w in words(label))

    a, b = labels
    if a and b:
        return [("{0} is %s of {1}" % phrase(a), (0, 1)),
                ("{0} is %s of {1}" % phrase(b), (1, 0))]
    if a or b:
        # one role is labelled, the other is the plain player: read from the plain side
        text = phrase(b or a)
        near, far = (0, 1) if b else (1, 0)
        if text.split()[-1] in PREPOSITIONS:                            # reports_to
            return [("{0} %s {1}" % text, (near, far))]
        return [("{0} has %s- {1}" % text, (near, far)),
                ("{0} is %s of {1}" % text, (far, near))]
    own = {w.lower() for w in words(player)}
    rest = [w.lower() for w in words(table)
            if w.lower() not in own and singular(w.lower()) not in own
            and not is_abbrev(w, player)]
    if not rest:
        return None
    text, last = " ".join(rest), rest[-1]
    if last.endswith("ed"):                                             # connected, married
        return [("{0} is %s to {1}" % text, (0, 1))]
    if last in PREPOSITIONS or (last.endswith("s") and not last.endswith(("ss", "us", "is"))):
        return [("{0} %s {1}" % text, (0, 1))]                          # reports_to, follows
    return [("{0} has %s with {1}" % text, (0, 1))]                     # friendship


# A JSONPath step can be bracket-quoted -- `$."tx/hr"` -- so almost anything is spellable.
# These are not: a quote or a backslash would end the literal, and an empty key has nothing to
# quote. `conquer/sql.py` refuses the same set at emission; this stops one being derived.
_JSON_UNSPELLABLE = re.compile(r"""['"\\]""")


# --------------------------------------------------------------------------- functions

# model/model.md §3: the function table is model data, not grammar, so a model that means to
# be queried has to carry one. Reverse engineering emits the standard library; a modeller can
# add to it. `isAggregate` is derived from a parameter being a bag, exactly as §3 says.
#
# One table, function by dialect. Each row is written for SQLite, which is what `--db`
# speaks, and names the dialects that spell it differently; a dialect that is not named
# spells it the SQLite way. Measured on 344 recorded queries (finding 83), the SQL-92 the
# emitter produces needs no dialect at all -- these are the functions, not the shape of the
# statement. This used to be two mechanisms, a patch dictionary per dialect and per-name
# lookups in the row, and the second grew every time a function needed a name rather than
# a template on one engine; it was the first thing a review of the file asked for.
#
# A spelling is one of: a template with `{0}` `{1}` placeholders; `Name("pow")`, a call
# by another name; `Bag("...")`, a template over the derived table an aggregate ranges over
# (`{bag}` is its SQL) for the one aggregate SQLite can only spell that way; or `ABSENT`,
# which leaves the function out of the model so the parser says the name is not a
# function here, rather than the database saying "no such function" after the query
# looked fine. An empty spelling is a call by the function's own name.
ABSENT = object()
_ABSENT = ABSENT                       # the older name, kept for the tests that use it


class Name(str):
    """A spelling that is a call by this name, not a template."""


class Bag(str):
    """A spelling that is a template over the bag's SQL, not over a column."""


LENIENT = ("CASE WHEN {N} GLOB '[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]*' "
           "THEN replace(substr({N}, 1, 10), '/', '-') "
           "WHEN {N} GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]*' "
           "THEN substr({N}, 7, 4) || '-' || substr({N}, 4, 2) || '-' || substr({N}, 1, 2) "
           "WHEN {N} GLOB '[0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]*' "
           "THEN substr({N}, 6, 4) || '-' || substr({N}, 3, 2) || '-0' || substr({N}, 1, 1) "
           "ELSE {N} END")


def lenient(n: int) -> str:
    """The date text at placeholder n, normalised to ISO for SQLite's date functions. Handles
    `2023/12/21`, `21/12/2023` and `1/12/2023`; anything else passes through untouched."""
    return LENIENT.replace("{N}", "{%d}" % n)


def _fn(name, spell="", symbol=None, boolean=False, params=("a", "b"), bag=(), defaults=None,
        **dialects):
    """One row: how every dialect spells `name`, unless a keyword names one that differs.
    `defaults` gives a trailing parameter the value a call that leaves it out means."""
    return {"name": name, "symbol": symbol, "boolean": boolean, "params": params, "bag": bag,
            "defaults": defaults or {}, "spell": dict({"sqlite": spell}, **dialects)}


# ILIKE is PostgreSQL's case-insensitive LIKE, which is what ConQuer's four string predicates
# mean on every backend (finding 130). Case is ConQuer's to define, not the backend's:
# SQLite's LIKE ignores ASCII case and PostgreSQL's does not, so these answered differently
# per backend; and the reference interpreter implemented them with Python's case-sensitive
# `startswith`, so the compiler and its own oracle disagreed wherever case differed. Pinned
# to case-insensitive, which is what SQLite and `reference._like` already do; `=` remains
# the exact test.
_ILIKE = dict(duckdb="({0} ILIKE {1})", postgresql="({0} ILIKE {1})")
# PostgreSQL reads the same three lenient date spellings as SQLite (LENIENT below), through
# a regex rather than GLOB, and over the text of the value so that a real date or
# timestamp column passes through the ELSE branch unharmed. Without this `year()` on a
# date kept as text was `EXTRACT(YEAR FROM text)`, an error, and `days_between` cast
# `21/12/2023` to a date under the server's month-first DateStyle, which is a different
# error; the labor_certification writer parsed the dates with substr instead (finding 162).
_PG_LENIENT = ("CASE WHEN CAST({N} AS text) ~ '^[0-9]{{4}}/[0-9]{{2}}/[0-9]{{2}}' "
               "THEN replace(substr(CAST({N} AS text), 1, 10), '/', '-') "
               "WHEN CAST({N} AS text) ~ '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}' "
               "THEN substr(CAST({N} AS text), 7, 4) || '-' || substr(CAST({N} AS text), 4, 2) "
               "|| '-' || substr(CAST({N} AS text), 1, 2) "
               "WHEN CAST({N} AS text) ~ '^[0-9]/[0-9]{{2}}/[0-9]{{4}}' "
               "THEN substr(CAST({N} AS text), 6, 4) || '-' || substr(CAST({N} AS text), 3, 2) "
               "|| '-0' || substr(CAST({N} AS text), 1, 1) "
               "ELSE CAST({N} AS text) END")


def _pg_date(n: int) -> str:
    """The value at placeholder n as a PostgreSQL date, read leniently."""
    return "CAST(%s AS date)" % _PG_LENIENT.replace("{N}", "{%d}" % n)


_EXTRACT = {p: "CAST(EXTRACT(%s FROM {0}) AS INTEGER)" % p for p in ("YEAR", "MONTH", "DAY")}
_PG_EXTRACT = {p: "CAST(EXTRACT(%s FROM %s) AS INTEGER)" % (p, _pg_date(0))
               for p in ("YEAR", "MONTH", "DAY")}

# SQLite has no STDDEV or VARIANCE aggregate, but it has SUM and COUNT, and the sample forms
# are a closed expression in those. Spelled out rather than declared absent, because a
# writer who cannot say `THE STANDARD DEVIATION` writes the moments by hand -- both blind
# writers on the LiveSQLBench arm did, identically -- and a language that makes them do that
# is worse than the SQL they are being compared against. The sum-of-squares form, not
# Welford: it is one pass and one expression, which is what a template can be. It loses
# precision when the mean is large relative to the spread; SQLite's REAL is a double, so
# that matters only at around 15 significant figures.
_MOMENTS = ("(SUM(CAST({0} AS REAL) * {0}) - SUM(CAST({0} AS REAL)) * SUM({0}) / COUNT({0})) "
            "/ (COUNT({0}) - 1)")

FUNCTIONS = [
    # arithmetic (section 6.3 scalar expressions). Division is REAL: a ratio of two counts
    # is a ratio, and SQL-92's integer truncation was the target's rule rather than a
    # conceptual one -- conquer/conquer-2026.md §1. `div` is the integer kind, for the rare
    # case that wants it.
    _fn("add", symbol="+"), _fn("subtract", symbol="-"), _fn("multiply", symbol="*"),
    # DOUBLE, not REAL: SQLite gives both 64-bit affinity, but DuckDB follows Postgres
    # where REAL is float32 -- so `CAST(.. AS REAL)` silently computed every percentage to
    # seven digits there (66.66666412353516 against 66.66666666666667). One word, and it
    # is the only portability defect in 12 queries run against both engines. No DOUBLE in
    # Postgres either: it spells 64-bit float DOUBLE PRECISION, and `CAST(x AS DOUBLE)` is
    # a syntax error rather than a wrong answer -- the better failure, but still a failure.
    _fn("divide", "(CAST({0} AS DOUBLE) / {1})", symbol="/",
        postgresql="(CAST({0} AS DOUBLE PRECISION) / {1})"),
    # Integer division truncates, on every dialect. SQLite's CAST to INTEGER truncates;
    # PostgreSQL's CAST to BIGINT *rounds* (3.5 -> 4), so it is spelled through TRUNC.
    _fn("div", "CAST(({0} / {1}) AS INTEGER)", postgresql="CAST(TRUNC({0} / {1}) AS BIGINT)"),
    _fn("negate", symbol="-", params=("a",)),
    # Reading a value out of a JSON document (rule 12). Two arguments: the column and a
    # JSONPath. SQLite's json_extract preserves storage class, DuckDB's json_extract and
    # PostgreSQL's jsonb_path_query_first return text, so `sql.py` casts on top of this
    # to the type the mapping column declares. The path placeholder is NOT quoted: both
    # callers pass an expression. Rule 12 hands in a quoted literal it built, and a user
    # writing `jsonPath(doc, '$.x')` reaches this through `render_call`, which has already
    # rendered the argument to a bind marker. Quoting it here made that
    # `json_extract(col, '?')` -- a literal question mark with a parameter left over -- so
    # no user-written jsonPath had ever run. jsonb_path_query_first returns jsonb; `#>> '{}'`
    # is how it becomes text, with the braces doubled for str.format.
    _fn("jsonPath", "json_extract({0}, {1})",
        duckdb="json_extract_string({0}, {1})",
        postgresql="(jsonb_path_query_first({0}, {1}::jsonpath) #>> '{{}}')"),
    # A path read hands back text in DuckDB and PostgreSQL, so a numeric one has to be
    # cast or `latitude > 9` compares '26.0325' to '9'. The type name is the dialect's,
    # which is why these are functions rather than a literal in the emitter.
    _fn("castNumber", "CAST({0} AS DOUBLE)", params=("a",),
        postgresql="CAST({0} AS DOUBLE PRECISION)"),
    _fn("castInteger", "CAST({0} AS INTEGER)", params=("a",),
        postgresql="CAST(TRUNC(CAST({0} AS numeric)) AS BIGINT)"),        # truncates, as SQLite
    # Building a document, for the questions that ask for one: 5 of LiveSQLBench's 180
    # SQLite tasks want a JSON array of objects in a column, and two writers spelled the
    # objects with `concat` and eleven quote marks apiece -- and lost, because a string
    # that looks like an object is gathered as a string. `jsonObject(k1, v1, k2, v2, ...)`
    # takes any even number of arguments; `render_call` emits a plain call for a function
    # with neither symbol nor template, which is the variadic form every dialect has.
    _fn("jsonObject", Name("json_object"), params=("key", "value"),
        postgresql=Name("jsonb_build_object")),
    # ...and text that already is a document, re-read as one. SQLite keeps the JSON
    # subtype inside an expression and drops it through a derived table, which is where
    # a `THE LIST OF` bag lives: the objects come out as quoted strings. `THE LIST OF
    # jsonObject(...)` reparses on its own (sql.py); text built any other way says so.
    _fn("json", "json({0})", params=("a",), postgresql="({0})::jsonb"),
    # group functions (section 6.6)
    _fn("count", params=("bag",), bag=("bag",)),
    _fn("sum", params=("bag",), bag=("bag",)),
    _fn("min", params=("bag",), bag=("bag",)),
    _fn("max", params=("bag",), bag=("bag",)),
    _fn("avg", params=("bag",), bag=("bag",)),
    # Dispersion. A benchmark writer needing a standard deviation computed it as
    # `sqrt((avg(a*a) - avg(a)^2) * n/(n-1))` out of three more aggregates, which is the
    # same shape as finding 99's median: askable in the question, unsayable in the
    # language (finding 148). PostgreSQL and DuckDB have both; SQLite spells the moments.
    _fn("stddev", "SQRT(%s)" % _MOMENTS, params=("bag",), bag=("bag",),
        duckdb="stddev_samp({0})", postgresql="stddev_samp({0})"),
    _fn("variance", "(%s)" % _MOMENTS, params=("bag",), bag=("bag",),
        duckdb="var_samp({0})", postgresql="var_samp({0})"),
    # the one group function whose result is a bag: it gathers rather than reduces, so
    # `EACH` can hand back LISA-D's nested relation instead of multiplying the rows
    # (conquer/lower.py fans_out). SQLite spells it json_group_array.
    _fn("list", Name("json_group_array"), params=("bag",), bag=("bag",),
        duckdb="list({0})", postgresql="json_agg({0})"),
    # The two aggregates that take a second operand, which the language could not say
    # until `THE LIST OF x SEPARATED BY ', '` and `THE OBJECT OF v BY k` (finding 158):
    # a string joined with a separator, and a document keyed by a value. Three writers
    # asked for the first; alien_5's gold is the second, and the twelve golds that
    # gather anything gather one of these two or `THE LIST OF`.
    _fn("join", Name("group_concat"), params=("bag", "separator"), bag=("bag",),
        duckdb="STRING_AGG({0}, {1})", postgresql="STRING_AGG({0}, {1})"),
    _fn("object", "json_group_object({1}, {0})", params=("bag", "key"), bag=("bag",),
        postgresql="jsonb_object_agg({1}, {0})"),
    # a small library so a model can express what real questions ask. round(double
    # precision, integer) does not exist in Postgres; only round(numeric, integer).
    _fn("abs", params=("a",)),
    # `round(x)` is `round(x, 0)` everywhere. PostgreSQL has no ROUND(double precision, int),
    # so its template casts to numeric and must spell both arguments; the default is what
    # lets the one-argument call through it (the large tier's writers wrote `round(g6)`).
    _fn("round", params=("a", "digits"), defaults={"digits": 0},
        postgresql="ROUND(CAST({0} AS numeric), {1})"),
    # Roots and powers. Their absence was not a small gap: a benchmark writer needing an
    # escape velocity implemented Newton-Raphson inline, six iterations of it, and a
    # four-iteration version of the same trick overflowed SQLite's parser because every
    # `AS` binding is inlined textually. SQLite has had these since 3.35 with the math
    # extension, which is on by default; PostgreSQL and DuckDB spell `power` as `pow` too.
    _fn("sqrt", params=("a",)), _fn("power", Name("pow"), params=("a", "b")),
    _fn("ln", params=("a",)), _fn("exp", params=("a",)),
    _fn("length", params=("a",)), _fn("lower", params=("a",)), _fn("upper", params=("a",)),
    _fn("substr", params=("a", "start", "count")),
    _fn("concat", symbol="||"),
    # No INSTR in Postgres. POSITION takes its arguments the other way round.
    _fn("instr", "INSTR({0}, {1})", postgresql="POSITION({1} IN {0})"),
    _fn("replace", params=("a", "b", "c")),
    # The gaps a survey of 660 LiveSQLBench gold statements found, weighted by how many
    # of them use each one. `coalesce` is in 627 of the 660 -- more than any other
    # function in the corpus, ours or theirs -- and every one of these is portable
    # across all three dialects.
    _fn("coalesce", "COALESCE({0}, {1})"),
    _fn("nullif", "NULLIF({0}, {1})"),
    _fn("trim", "TRIM({0})", params=("a",)),
    _fn("ltrim", "LTRIM({0})", params=("a",)),
    _fn("rtrim", "RTRIM({0})", params=("a",)),
    # log10 specifically: `ln(x)/ln(10)` is what a writer had to spell instead, and a
    # knowledge base that defines an index as a log ratio is asking for it by name.
    # Spelled as the engine's own LOG10, not as a ratio of natural logs: the ratio is
    # off in the fifteenth digit (75.4479188025793 against 75.4479188025794), and a
    # figure inside a JSON column is compared as text, where no rounding reaches it.
    # SQLite has had log10 since 3.35 with the math functions sqrt and power already
    # rely on; PostgreSQL and DuckDB have always had it.
    _fn("log10", "LOG10({0})", params=("a",)),
    # greatest/least over two values. SQLite spells them MAX/MIN, which are also the
    # aggregate names, so the template is the honest place to keep them apart.
    # SQLite spells these as its two-argument MIN/MAX; PostgreSQL and DuckDB have the
    # variadic names, and a model that carried SQLite's spelling made `least` fail at run
    # time on the server -- the sports_events writer nested `if` instead (finding 162).
    _fn("greatest", "MAX({0}, {1})", postgresql=Name("greatest"), duckdb=Name("greatest")),
    _fn("least", "MIN({0}, {1})", postgresql=Name("least"), duckdb=Name("least")),
    _fn("floor", params=("a",)), _fn("ceil", params=("a",)),
    # patterns (conquer-2026.md §5). `like` is SQL's; the other three are what a question
    # actually says -- "District Name starts with 'Riverside'".
    _fn("like", "({0} LIKE {1})", boolean=True, **_ILIKE),
    _fn("starts_with", "({0} LIKE {1} || '%')", boolean=True,
        duckdb="({0} ILIKE {1} || '%')", postgresql="({0} ILIKE {1} || '%')"),
    _fn("contains", "({0} LIKE '%' || {1} || '%')", boolean=True,
        duckdb="({0} ILIKE '%' || {1} || '%')", postgresql="({0} ILIKE '%' || {1} || '%')"),
    _fn("ends_with", "({0} LIKE '%' || {1})", boolean=True,
        duckdb="({0} ILIKE '%' || {1})", postgresql="({0} ILIKE '%' || {1})"),
    # dates (conquer-2026.md §6). SQLite has no YEAR(); it has strftime. Lenient on the
    # shape of the text: see LENIENT above. A date that is already ISO passes through the
    # ELSE untouched, so nothing that worked before changes.
    _fn("year", "CAST(strftime('%%Y', %s) AS INTEGER)" % lenient(0), params=("a",),
        duckdb=_EXTRACT["YEAR"], postgresql=_PG_EXTRACT["YEAR"]),
    _fn("month", "CAST(strftime('%%m', %s) AS INTEGER)" % lenient(0), params=("a",),
        duckdb=_EXTRACT["MONTH"], postgresql=_PG_EXTRACT["MONTH"]),
    _fn("day", "CAST(strftime('%%d', %s) AS INTEGER)" % lenient(0), params=("a",),
        duckdb=_EXTRACT["DAY"], postgresql=_PG_EXTRACT["DAY"]),
    _fn("today", "date('now')", params=(), duckdb="CURRENT_DATE", postgresql="CURRENT_DATE"),
    _fn("days_between", "(julianday(%s) - julianday(%s))" % (lenient(0), lenient(1)),
        duckdb="DATE_DIFF('day', {1}, {0})",
        postgresql="(%s - %s)" % (_pg_date(0), _pg_date(1))),
    # The median. A benchmark writer asked for one, could not say it, and reported the
    # AVERAGE instead -- 0.4485 where the median is 0.4097 (finding 99). DuckDB and
    # PostgreSQL both have it. SQLite has no ordered-set aggregate, but a bag is a derived
    # table, and the middle of a numbered derived table is a closed form: spelled over the
    # *bag*, not the column, as the average of the middle one or two, which is the median
    # of an even count as well as an odd one. In place beside GROUP BY it cannot be said
    # this way, and the emitter re-lowers a grouped median into a bag of its own.
    _fn("median", Bag('(SELECT AVG("v") FROM (SELECT "v", ROW_NUMBER() OVER (ORDER BY "v") '
                      'AS "__rn", COUNT(*) OVER () AS "__n" FROM ({bag})) WHERE "__rn" IN '
                      '(("__n" + 1) / 2, ("__n" + 2) / 2))'),
        params=("bag",), bag=("bag",),
        duckdb="median({0})", postgresql="percentile_cont(0.5) WITHIN GROUP (ORDER BY {0})"),
    # Row-relative, and window-only. Every dialect here has had window functions for
    # years -- SQLite since 3.25 -- so unlike `median` these are not a dialect question.
    # `THE RANK OF x WITHIN g` orders the window by x descending, so rank 1 is the
    # largest; `THE PREVIOUS x BY t WITHIN g` orders it by t.
    _fn("rank", params=("bag",), bag=("bag",)),
    # (rank - 1) / (rows - 1): where a row stands as a fraction of its partition, which
    # is what a knowledge base means by "percentile ranking" and what three writers
    # built from a rank and a count by hand.
    _fn("percent_rank", params=("bag",), bag=("bag",)),
    _fn("lag", params=("bag",), bag=("bag",)),
]

DIALECTS = ("sqlite", "duckdb", "postgresql")


def standard_functions(dialect: str = "sqlite") -> List[dict]:
    if dialect not in DIALECTS:
        raise ValueError("unknown dialect %r; known: %s"
                         % (dialect, ", ".join(sorted(DIALECTS))))
    out = []
    for row in FUNCTIONS:
        spell = row["spell"].get(dialect, row["spell"]["sqlite"])
        if spell is ABSENT:
            continue
        # A dialect that renames the call keeps no template; one that gives a template
        # keeps the SQLite name, which is what the emitter falls back to for the bare call.
        base = row["spell"]["sqlite"]
        name = spell if isinstance(spell, Name) else (
            base if isinstance(base, Name) else row["name"])
        template = spell if (spell and not isinstance(spell, (Name, Bag))) else None
        out.append({"id": "fn." + row["name"], "name": str(name),
                    **({"operatorSymbol": row["symbol"]} if row["symbol"] else {}),
                    **({"sqlTemplate": template} if template else {}),
                    **({"sqlBagTemplate": str(spell)} if isinstance(spell, Bag) else {}),
                    "isBoolean": row["boolean"],
                    "isAggregate": bool(row["bag"]),
                    "parameters": [dict({"name": p, "bagInput": p in row["bag"]},
                                        **({"default": row["defaults"][p]}
                                           if p in row["defaults"] else {}))
                                   for p in row["params"]]})
    return out


# --------------------------------------------------------------------------- report

class Report:
    def __init__(self):
        self.blockers: List[dict] = []
        self.refinements: List[dict] = []
        self.summary: Dict[str, int] = {}

    def block(self, rule, subject, message, action):
        self.blockers.append({"rule": rule, "subject": subject,
                              "message": message, "action": action})

    def refine(self, rule, confidence, subject, message, action):
        self.refinements.append({"rule": rule, "confidence": confidence, "subject": subject,
                                 "message": message, "action": action})

    def as_dict(self):
        return {"summary": self.summary, "blockers": self.blockers,
                "refinements": self.refinements}


# --------------------------------------------------------------------------- classification

ENTITY, FACT, SUBTYPE, UNKEYED, VIEW = "entity", "fact", "subtype", "unkeyed", "view"


def _summarise(names, limit=6):
    """Name a column list without printing all of it."""
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return "%s, ... %s -- %d columns" % (", ".join(names[:limit - 1]), names[-1], len(names))


def classify(catalog: Catalog, table: Table) -> Tuple[str, Optional[dict]]:
    """Which ORM construct does this table become?

    Rule 1  own primary key                     -> EntityType
    Rule 4  key is wholly foreign keys (2+)     -> FactType, objectified if anything hangs off it
    Rule 4d no key, but every column is a FK    -> FactType; the shape identifies it, not a key
    Rule 1b no key, 2+ FKs and other columns    -> FactType objectified by the rest (heuristic)
    Rule 7  key is a single foreign key to a PK -> subtype candidate (heuristic)
            no primary key and no association shape -> blocker
    """
    if table.is_view:
        return VIEW, None
    if not table.primary_key:
        return classify_keyless(table)

    covering = []
    for fk in table.foreign_keys:
        if all(table.is_key(c) for c in fk.columns):
            covering.append(fk)
    covered = {c.casefold() for fk in covering for c in fk.columns}
    wholly = covered == {c.casefold() for c in table.primary_key}

    if wholly and len(covering) >= 2:
        order = {c.casefold(): i for i, c in enumerate(table.primary_key)}
        covering.sort(key=lambda fk: min(order.get(c.casefold(), 99) for c in fk.columns))
        return FACT, {"fks": covering}
    if wholly and len(covering) == 1:
        fk = covering[0]
        target = catalog.table(fk.ref_table)
        if target is not None and {c.casefold() for c in fk.ref_columns} == \
                {c.casefold() for c in target.primary_key}:
            return SUBTYPE, {"fk": fk, "supertype": target}
    return ENTITY, None


def classify_keyless(table: Table) -> Tuple[str, Optional[dict]]:
    """A table with no declared primary key.

    Bird's extraction methodology (§3.3.2 of the 1997 thesis) processes *keys*, with primary
    keys merely marked as primary. A table without one is still a relationship type; what is
    missing is knowledge of its uniqueness constraint, not the table's meaning. Treating the
    absence as fatal is what lost `academic.cite(cited, citing)` -- two foreign keys to
    `publication`, an ordinary many-to-many association -- from the model entirely, along with
    102 other tables across 47 of 206 Spider databases.

    Two shapes are recoverable without inventing a key:

    Rule 4d, sound: every column belongs to a foreign key. The fact type's roles *are* those
    foreign keys, and a relation is a set of tuples, so the whole row identifies the instance.
    No key needs to be assumed because none is used.

    Rule 1b, heuristic: two or more foreign keys plus other columns. The same association with
    attributes hanging off it, so it objectifies -- but identifying it by the foreign keys is
    an assumption about uniqueness the catalog does not make, and the report says so.

    Anything else -- fewer than two foreign keys -- is still a blocker. There is no shape to
    read, and inventing an identifier from column names would be the "unrealistic assumption"
    Bird names as this literature's failure mode.
    """
    # A keyed association orders its roles by position in the primary key. Without one, the
    # only equally defensible order is the table's own column order -- and *some* deterministic
    # order is required, because role order fixes the reading and the role-to-column mapping.
    # Left to the catalogue it is whatever PRAGMA happened to return.
    position = {c.name.casefold(): i for i, c in enumerate(table.columns)}
    fks = sorted(table.foreign_keys,
                 key=lambda fk: min(position.get(c.casefold(), 99) for c in fk.columns))
    if len(fks) == 1 and len(table.columns) > len(fks[0].columns):
        # Rule 1c, heuristic: one foreign key plus other columns. `examination(patient_id,
        # date, result, ...)` -- a set of facts about the referenced entity, with no key
        # declared over them. It is an entity type hanging off the referenced one, and the
        # only identifier the catalogue supports is the row itself: a relation is a set of
        # tuples, so that is sound, if unlovely. Bird's step 9 finds the real key from the
        # data. Refusing this shape cost a BIRD database a quarter of its questions.
        return ENTITY, {"keyless": True, "fk": fks[0]}
    if len(fks) < 2:
        return UNKEYED, None
    covered = {c.casefold() for fk in fks for c in fk.columns}
    every = {c.name.casefold() for c in table.columns}
    return FACT, {"fks": fks, "keyless": True, "wholly": covered == every}


# --------------------------------------------------------------------------- value restrictions

# The \b and the NOT lookahead together keep `c NOT IN (...)` from being read as a
# restriction on a column called "not" -- which also suppressed the report that would
# otherwise have said the CHECK was not understood.
_IN_RE = re.compile(r"\b(?![\"`\[]?NOT\b)([\"`\[]?(\w+)[\"`\]]?)\s+IN\s*\((.*?)\)",
                    re.IGNORECASE | re.DOTALL)
_BETWEEN_RE = re.compile(
    r"\b(?![\"`\[]?NOT\b)([\"`\[]?(\w+)[\"`\]]?)\s+BETWEEN\s+(\S+)\s+AND\s+(\S+)",
    re.IGNORECASE)
_LITERAL_RE = re.compile(r"'((?:[^']|'')*)'|([-+]?\d+(?:\.\d+)?)")


def parse_check(expression: str) -> Tuple[Dict[str, dict], bool]:
    """Rule 6. Recognise `c IN (...)` and `c BETWEEN x AND y`; report anything else."""
    found: Dict[str, dict] = {}
    matched_span = False

    for m in _IN_RE.finditer(expression):
        values = [(a.replace("''", "'") if a is not None else b)
                  for a, b in _LITERAL_RE.findall(m.group(3))]
        if values:
            found.setdefault(m.group(2).casefold(), {})["values"] = values
            matched_span = True

    for m in _BETWEEN_RE.finditer(expression):
        lo, hi = m.group(3).strip("'"), m.group(4).strip("'")
        found.setdefault(m.group(2).casefold(), {}).setdefault("ranges", []).append(
            {"min": lo, "max": hi})
        matched_span = True

    return found, matched_span


# --------------------------------------------------------------------------- data types

def conceptual_type(sql_type: str) -> dict:
    t = (sql_type or "").strip()
    base = re.split(r"[\s(]", t, maxsplit=1)[0].casefold()
    size = re.search(r"\((\d+)(?:\s*,\s*(\d+))?\)", t)
    out: dict = {"name": base or "text"}
    if size:
        if size.group(2) is not None:
            out["length"] = int(size.group(1))
            out["scale"] = int(size.group(2))
        elif base in ("char", "varchar", "nvarchar", "nchar", "character",
                      "varying", "text", "binary", "varbinary"):
            out["length"] = int(size.group(1))
    return out


# --------------------------------------------------------------------------- the derivation

class Deriver:
    def __init__(self, catalog: Catalog, infer_undeclared_fks: bool = False,
                 json_shapes: Optional[dict] = None, dialect: str = "sqlite",
                 absorb: Optional[dict] = None, merge_domains: bool = False,
                 glossary: Optional[dict] = None):
        self.catalog = catalog
        self.infer = infer_undeclared_fks
        # Rule 7b: {folded child table -> parent table name} for the rule 7 candidates the
        # population showed to be vertical partitioning. Empty means every candidate keeps
        # the subtype reading, which is rule 7 as it has always behaved.
        self.absorb = {k.casefold(): v for k, v in (absorb or {}).items()}
        self.merge = merge_domains
        # Rule 10b: written-out abbreviations. `None` leaves every name exactly as rule 10
        # spelled it; an empty dict still turns expansion on, using the built-in table alone.
        self.glossary_on = glossary is not None
        self.glossary = glossary or {}
        # Rule 12: {(table, column): (shape, fields, why)}, from the population or from a
        # declared field schema. Empty means the rule does not run at all.
        self.json_shapes = json_shapes or {}
        self.dialect = dialect
        self._path_columns: set = set()
        self.report = Report()
        self.reading_guesses: List[Tuple[str, str]] = []     # (fact type, reading as words)
        self.fk_source: Dict[str, str] = {}          # role id -> the column that named it

        self.concepts: List[dict] = []
        self.constraints: List[dict] = []
        self.constraint_ids: set = set()         # so naming a constraint stays O(1)
        self.by_id: Dict[str, dict] = {}

        self.entity_of: Dict[str, str] = {}          # folded table name -> entity concept id
        self.identity_roles: Dict[str, List[str]] = {}   # entity id -> identifying role ids
        self.identity_columns: Dict[str, List[str]] = {}  # folded table -> identifying columns
        self.mapping = {"tables": [], "columns": [], "conceptMap": [], "roleMap": []}
        self.column_id: Dict[Tuple[str, str], str] = {}
        self.table_id: Dict[str, str] = {}
        self.value_types: Dict[Tuple[str, str], str] = {}
        self._checks: Dict[str, tuple] = {}

    # -- small builders ----------------------------------------------------

    def _unique_id(self, prefix: str, name: str, taken) -> str:
        """`prefix.Name`, with 2, 3, ... appended until it is free in `taken`."""
        cid, n = "%s.%s" % (prefix, name), 2
        while cid in taken:
            cid, n = "%s.%s%d" % (prefix, name, n), n + 1
        return cid

    def _add(self, concept: dict) -> str:
        self.concepts.append(concept)
        self.by_id[concept["id"]] = concept
        return concept["id"]

    def value_type(self, name: str, sql_type: str, restriction: Optional[dict] = None,
                   source: Optional[str] = None) -> str:
        dt = conceptual_type(sql_type)
        key = (name, dt["name"] + str(dt.get("length", "")) + str(dt.get("scale", "")))
        if key in self.value_types:
            existing = self.by_id[self.value_types[key]]
            if restriction and "restriction" not in existing:
                existing["restriction"] = restriction
            return self.value_types[key]
        cid = self._unique_id("vt", name, self.by_id)
        concept = {"id": cid, "name": name, "kind": "value", "dataType": dt,
                   "terms": terms_for(name, source)}
        # The column name is the only place the unit is written down. Recovering it is what
        # lets two value types be recognised as one domain later -- and what stops `airtempc`
        # and `objtempk` being merged into one, which they are not.
        unit = unit_of(source) if source else None
        if unit:
            concept["unit"] = unit
        if restriction:
            concept["restriction"] = restriction
        self.value_types[key] = self._add(concept)
        return cid

    def fact_type(self, name: str, roles: List[dict], reading: str,
                  readings: Optional[List[Tuple[str, Tuple[int, ...]]]] = None) -> dict:
        """`reading` is the text over the roles in order; `readings`, when given, replaces it
        with several, each over the roles in the order it names -- a ring's inverse reading
        starts at the other role."""
        fid = self._unique_id("ft", name, self.by_id)
        # Slots come from names, so two roles of one fact type can want the same one --
        # `country(country)` gives CountryHasCountry two roles both called "country". Left
        # alone that emits duplicate role ids, and the identifier, the uniqueness
        # constraints and the role map all collapse onto whichever won.
        # A player appearing twice means a ring, and then a bare role name (`Atom`) is both
        # ambiguous between the two roles and shadowed by the object type of the same name.
        # Qualify those with the fact type's name so each is addressable.
        seen_players = {}
        for r in roles:
            seen_players[r["player"]] = seen_players.get(r["player"], 0) + 1
        ring_players = {p for p, n in seen_players.items() if n > 1}

        taken = set()
        for i, r in enumerate(roles):
            slot = base = r.pop("_slot")
            n2 = 2
            while slot in taken:
                slot, n2 = "%s%d" % (base, n2), n2 + 1
            taken.add(slot)
            r["id"] = "r.%s.%s" % (fid[3:], slot)
            # Name the role. Without a name a ring fact type -- two roles played by one
            # object type, as in `connected(atom_id, atom_id2)` -- cannot be navigated at
            # all: nothing in the query text can say which of the two is meant.
            r["name"] = (name + pascal(slot)) if r["player"] in ring_players \
                else pascal(slot)
            r["ordinal"] = i
        rds = readings or [(reading, tuple(range(len(roles))))]
        concept = {"id": fid, "name": name, "kind": "fact", "roles": roles,
                   "readings": [{"id": "rd.%s%s" % (fid[3:], "" if k == 0 else ".%d" % (k + 1)),
                                 "text": text,
                                 "roleSequence": [roles[i]["id"] for i in order]}
                                for k, (text, order) in enumerate(rds)]}
        self._add(concept)
        return concept

    def disambiguate_readings(self):
        """Rule 10: when two fact types between the same pair of types read the same, read
        the foreign key column into the verb.

        `superhero.eye_colour_id` and `hair_colour_id` both give `Superhero has Colour`, and
        nothing in a query can then say which is meant -- a role reference names the role the
        head enters *by*, and both are called `Superhero`. The column says `eye`, so the
        reading does: `{0} has eye- {1}`, the hyphen binding the adjective to the object type
        (FORML 2 section 1.2) so it verbalises "at most one eye Colour" and a query says
        `has eye Colour`. Same shape as a ring reading, same guess, reported the same way.
        """
        # An n-ary fact type's *first* verb part reads exactly like a binary one between the
        # same pair, so it belongs in the same grouping: f1's `races` and the denormalised
        # `races_ext` both read `Race has Season`, and a query could reach neither -- the
        # compiler refused, correctly and uselessly. Its later roles already have verb parts
        # of their own, so only slot 0 to slot 1 is at stake, and only that part is rewritten.
        groups: Dict[tuple, List[dict]] = {}
        for c in self.concepts:
            if c["kind"] != "fact" or len(c.get("roles", [])) < 2:
                continue
            text = (c.get("readings") or [{}])[0].get("text", "")
            if len(c.get("readings", [])) != 1 or not text.startswith("{0} has {1}"):
                continue                      # a ring, or already read from the names
            key = (c["roles"][0]["player"], c["roles"][1]["player"])
            groups.setdefault(key, []).append(c)

        for (_near, far), facts in sorted(groups.items()):
            if len(facts) < 2:
                continue
            player = {w.casefold() for w in words(self.by_id[far]["name"])}
            adjectives, plain = {}, 0
            for c in facts:
                col = self.fk_source.get(c["roles"][1]["id"])
                rest = [w for w in words(strip_key_suffix(col or ""))
                        if w.casefold() not in player and singular(w.casefold()) not in player]
                adj = " ".join(w.lower() for w in rest)
                if adj and adj not in adjectives.values():
                    adjectives[c["id"]] = adj
                    continue
                # The column says nothing the target's name does not (`post_id` -> Post), or
                # says what another column already said -- f1's two `year` columns. What is
                # left that tells them apart is the table each came from: `races_ext` beyond
                # `race` is "ext". One fact type may keep the plain reading and still be told
                # apart, since the others' readings are longer and match first.
                adj = self.table_adjective(c, player)
                if adj and adj not in adjectives.values():
                    adjectives[c["id"]] = adj
                else:
                    plain += 1
            if plain > 1 or len(adjectives) + plain != len(facts):
                continue                      # nothing to gain, or a partial rename
            for c in facts:
                adj = adjectives.get(c["id"])
                if adj is None:
                    continue
                text = c["readings"][0]["text"]
                c["readings"][0]["text"] = "{0} has %s- {1}%s" % (adj, text[len("{0} has {1}"):])
                self.reading_guesses.append(
                    (c["name"], "%s has %s %s" % (self.by_id[c["roles"][0]["player"]]["name"],
                                                  adj, self.by_id[far]["name"])))

    def table_adjective(self, fact: dict, far_player: set) -> str:
        """What this fact type's own table name says beyond its two players' names.

        The last thing available when the foreign key columns cannot tell two fact types
        apart, and it is what a denormalised copy is usually called: `races` and `races_ext`
        differ by "ext" and nothing else in the schema records the difference.
        """
        entry = next((m for m in self.mapping["conceptMap"] if m["concept"] == fact["id"]), None)
        if entry is None:
            return ""
        table = next((t for t in self.mapping["tables"] if t["id"] == entry["table"]), None)
        near = {w.casefold() for w in words(self.by_id[fact["roles"][0]["player"]]["name"])}
        known = near | far_player
        rest = [w for w in words(table["name"] if table else "")
                if w.casefold() not in known and singular(w.casefold()) not in known]
        return " ".join(w.lower() for w in rest)

    def guess_ring_readings(self, table_name: str, name: str, roles: List[dict],
                            labels: List[Optional[str]]):
        """Rule 10 on a binary ring: readings from the names, recorded as the guess they are."""
        if len(roles) != 2 or roles[0]["player"] != roles[1]["player"]:
            return None
        player = self.by_id[roles[0]["player"]]["name"]
        readings = ring_readings(table_name, player, [ring_label(l, player) for l in labels])
        if readings:
            self.reading_guesses.append(
                (name, readings[0][0].replace("{0}", player).replace("{1}", player)))
        return readings

    def uniqueness(self, name: str, roles: List[str], preferred: bool = False) -> str:
        cid = self._unique_id("uc", name, self.constraint_ids)
        self.constraint_ids.add(cid)
        self.constraints.append({"id": cid, "kind": "uniqueness", "roleSequences": [roles],
                                 **({"isPreferredIdentifier": True} if preferred else {})})
        return cid

    def role_label(self, fk, target_name: str) -> str:
        """What to call the role facing a foreign key's target. Rule 10, so a guess.

        A foreign key column names the table it points AT, so the owning table's prefix must
        not be stripped: InvoiceLine.InvoiceId is "Invoice", not "Id". And a composite key's
        first column names a component rather than the target, so (cust_code, order_seq)
        points at an Order, not at a "Cust".
        """
        label = pascal(strip_key_suffix(fk.columns[0])) or target_name
        if len(fk.columns) > 1 or label == target_name or is_abbrev(label, target_name):
            return target_name
        return label

    # -- mapping -----------------------------------------------------------

    def register_table(self, table: Table):
        tid = "t." + table.name
        self.table_id[table.name.casefold()] = tid
        entry = {"id": tid, "name": table.name}
        if table.schema:
            entry["schema"] = table.schema
        self.mapping["tables"].append(entry)
        for col in table.columns:
            cid = "c.%s.%s" % (table.name, col.name)
            self.column_id[(table.name.casefold(), col.name.casefold())] = cid
            self.mapping["columns"].append({
                "id": cid, "table": tid, "name": col.name,
                "dataType": conceptual_type(col.data_type), "nullable": col.nullable})

    def fk_reference(self, fk) -> Optional[Tuple[str, List[str]]]:
        """The target table and columns a foreign key points at, when they are not that
        table's identifier. 32 of the 105 foreign keys in the BIRD dev set are like this."""
        target = self.catalog.table(fk.ref_table)
        if target is None or not fk.ref_columns or any(c is None for c in fk.ref_columns):
            return None
        identity = [c.casefold() for c in self.identifying_columns(target)]
        if [c.casefold() for c in fk.ref_columns] == identity:
            return None
        return (target, list(fk.ref_columns))

    def cols(self, table: Table, names: List[str]) -> List[str]:
        return [self.column_id[(table.name.casefold(), n.casefold())] for n in names]

    def identifying_columns(self, table: Table) -> List[str]:
        """The columns that identify an instance of this table's entity type.

        Usually the primary key. A keyless association objectified under rule 1b or 4d has
        none, and is identified instead by the foreign-key columns its roles are mapped to --
        recorded here when the association was built. Every attribute that hangs off the
        objectified type has to be mapped through the same columns, or its role maps to
        nothing and the model fails its own schema.
        """
        return list(table.primary_key) or self.identity_columns.get(table.name.casefold(), [])

    def path_column(self, table: Table, col, path: List[str], sql_type: str) -> str:
        """Declare a mapping column for a value that lives at a path inside a document.

        It is a column like any other downstream -- a role maps to it, the emitter reads it --
        and the only difference is that its SQL is a `fn.jsonPath` call rather than a name.
        """
        base = self.column_id[(table.name.casefold(), col.name.casefold())]
        cid = "%s|%s" % (base, ".".join(path))
        if cid not in self._path_columns:
            self._path_columns.add(cid)
            self.mapping["columns"].append({
                "id": cid, "table": self.table_id[table.name.casefold()], "name": col.name,
                "path": list(path), "dataType": conceptual_type(sql_type), "nullable": True})
        return cid

    def map_path_role(self, role_id: str, table: Table, column_id: str):
        self.mapping["roleMap"].append({
            "role": role_id, "table": self.table_id[table.name.casefold()],
            "columns": [column_id]})

    def map_concept(self, concept_id: str, table: Table, identifying: List[str]):
        self.mapping["conceptMap"].append({
            "concept": concept_id, "table": self.table_id[table.name.casefold()],
            "identifyingColumns": self.cols(table, identifying)})

    def map_role(self, role_id: str, table: Table, columns: List[str],
                 references: Optional[Tuple[str, List[str]]] = None):
        """`references` is (target table, its columns) when this role is a foreign key whose
        target is NOT the target entity's identifier -- `legalities.uuid` referencing
        `cards.uuid` while `cards` is keyed by `id`. Without it the emitter would join the
        value to the target's identifier and match nothing, or worse, match the wrong rows."""
        entry = {"role": role_id, "table": self.table_id[table.name.casefold()],
                 "columns": self.cols(table, columns)}
        if references is not None:
            target, cols = references
            entry["references"] = self.cols(target, cols)
        self.mapping["roleMap"].append(entry)

    # -- passes ------------------------------------------------------------

    def expand_documents(self, table: Table, eid: str, ename: str, col) -> bool:
        """Rule 12, applied on request (--infer-json).

        A document column whose population reads as a *record* becomes one binary fact type
        per scalar leaf, each mapped to the path that reaches it. The query author writes
        `Circuit has City` and never learns that a JSON column was involved; the path lives
        in the mapping, where every other dialect-specific thing already lives.

        A *map* and a *bag* are reported and left alone. Returns the fact types made, so the
        caller can put their names on the opaque value type it goes on to make: the column
        stays reachable as the document it is, because 50 of the 180 recorded LiveSQLBench
        answers read one with `jsonPath`, and the listing then says what is inside it.
        """
        verdict = self.json_shapes.get((table.name, col.name))
        if verdict is None:
            return []
        shape, fields, why = verdict
        where = "%s.%s" % (table.name, col.name)
        if shape == "map":
            self.report.refine(
                "rule 12", "population", where,
                "A JSON column whose keys are data rather than roles -- %s. In ORM this is a "
                "fact type whose key plays a role (`Survey has Percentage for Mineral`), not "
                "a record: making one fact type per key would invent an unbounded, sparse "
                "schema out of one sample. Left as an opaque value." % why,
                "Model it by hand as a fact type over the key, or normalise the column out. "
                "The mapping cannot express it yet: reading it needs an unnest, not a path.")
            return []
        if shape != "record" or not fields:
            self.report.refine(
                "rule 12", "heuristic", where,
                "A JSON column with no recoverable record structure -- %s. Left as an opaque "
                "value, which is what the catalogue declared." % why,
                "Nothing to do unless the column really does have a schema, in which case "
                "the sample did not show it.")
            return []

        # A step the emitter cannot spell must not become a fact type. Deriving one makes the
        # model assert a fact no query can ever read -- it fails at execution with a JSONPath
        # error, or is refused at emission, and either way the model lied.
        spellable, unspellable = [], []
        for f in fields:
            steps = [str(k) for k in f["path"]]
            (unspellable if any(not k or _JSON_UNSPELLABLE.search(k) for k in steps)
             else spellable).append(f)
        if unspellable:
            self.report.refine(
                "rule 12", "sound", where,
                "%d key(s) cannot be written as a JSONPath -- empty, or carrying a quote or a "
                "backslash: %s. No fact type was made for them: one that cannot be read is "
                "worse than none." % (
                    len(unspellable),
                    ", ".join(repr(".".join(str(k) for k in f["path"]))
                              for f in unspellable[:6])),
                "Rename the keys in the source, or read them with a hand-written derivation "
                "rule that quotes them itself.")
        fields = spellable
        if not fields:
            return []

        ident = self.identifying_columns(table)
        # A document often repeats a column the table already has -- `funds.strategytype`
        # beside `fundclass -> Strategy_Type`. Two value types then differ only by case, and
        # a query naming either is ambiguous: the reader cannot see which fact is meant and
        # the parser picks one. Qualify the derived name with the column it came out of, so
        # both stay addressable and the name says where the value lives.
        # Names already made, *and* the ones rule 2 will make from this table's other
        # columns: rule 12 runs first within the column loop, so a collision with a column
        # that comes later is invisible unless it is anticipated. Column order decided
        # whether the clash was caught, which is no way to name a model.
        taken = {c["name"].casefold() for c in self.concepts}
        taken |= {(ename + self.label_for(c.name, table.name)).casefold()
                  for c in table.columns if c.name != col.name}
        # ...and the labels this table's *other* documents make. `matches.home` and
        # `matches.away` both carry `score`, and without this whichever is processed first
        # takes the bare name -- MScore beside MAwayScore, so nothing says which is the home
        # one. A label two documents share is qualified in both, or in neither.
        mine = {pascal("_".join(str(k) for k in f["path"])) for f in fields}
        shared = set()
        for (t, other), (oshape, ofields, _) in self.json_shapes.items():
            if t == table.name and other != col.name and oshape == "record":
                shared |= mine & {pascal("_".join(str(k) for k in f["path"]))
                                  for f in ofields}
        clash = self.label_for(col.name, table.name)
        made, collided = [], []
        for f in fields:
            label = pascal("_".join(str(k) for k in f["path"]))
            if (ename + label).casefold() in taken or label in shared:
                collided.append(ename + label)
                label = clash + label
            vt = self.value_type(ename + label, f["dataType"], source=col.name)
            ft = self.fact_type(
                "%sHas%s" % (ename, label),
                [{"_slot": ename.lower(), "player": eid, "isMandatory": False},
                 {"_slot": label.lower(), "player": vt, "isMandatory": True}],
                "{0} has {1}")
            self.uniqueness(ft["id"], [ft["roles"][0]["id"]])
            self.map_concept(ft["id"], table, ident)
            self.map_role(ft["roles"][0]["id"], table, ident)
            self.map_path_role(ft["roles"][1]["id"],
                               table, self.path_column(table, col, f["path"], f["dataType"]))
            made.append(ft["name"])
            taken.add((ename + label).casefold())
        if collided:
            self.report.refine(
                "rule 12", "heuristic", where,
                "%d value(s) in this document are named like something the table already has "
                "(%s). A query naming either would be ambiguous, so the derived ones carry "
                "the column: %s. Whether they are the same fact is not something the schema "
                "says." % (len(collided), ", ".join(collided[:6]), clash + "..."),
                "Check whether the document repeats the column or means something else. If "
                "it repeats it, drop one -- two names for one fact is worse than either.")
        self.report.refine(
            "rule 12", "population", where,
            "A JSON column read as a record -- %s. It became %d fact type(s): %s. Each is "
            "mapped to a path inside the column, so the model says what is in there and a "
            "query never mentions JSON." % (why, len(made), ", ".join(made[:6]) + (" ..." if len(made) > 6 else "")),
            "Check the readings and the types against the documents. A key that is absent "
            "from most rows reads as an optional role here, which may understate a real "
            "mandatory one, or overstate a key that is simply rare.")
        return made

    def infer_foreign_keys(self):
        """Rule 9, applied on request (--infer-fks).

        A column that is not a key, is in no declared foreign key, and is named exactly like
        the single-column primary key of exactly one *other* table of the same conceptual
        type, is read as a foreign key to it. `transactions_1k.CustomerID` -> `customers`.
        A name that matches several tables (`id`) is left alone and reported. This is a
        guess -- name coincidence is not a reference -- and the report says so for each one;
        the BIRD pilot measured the cost of not guessing at half the questions on a
        database that declares no keys at all.
        """
        pk_index: Dict[str, List[Table]] = {}
        for t in self.catalog.tables:
            if len(t.primary_key) == 1 and not t.is_view:
                pk_index.setdefault(t.primary_key[0].casefold(), []).append(t)
        for t in self.catalog.tables:
            if t.is_view:
                continue
            for col in t.columns:
                if t.fk_for(col.name) is not None or t.is_key(col.name):
                    continue
                targets = [x for x in pk_index.get(col.name.casefold(), [])
                           if x.name.casefold() != t.name.casefold()]
                if len(targets) != 1:
                    continue
                target = targets[0]
                pk = target.column(target.primary_key[0])
                if pk is None or conceptual_type(col.data_type)["name"] \
                        != conceptual_type(pk.data_type)["name"]:
                    continue
                t.foreign_keys.append(ForeignKey(columns=[col.name], ref_table=target.name,
                                                 ref_columns=[pk.name], name="inferred"))
                self.report.refine(
                    "rule 9", "guess", "%s.%s -> %s.%s" % (t.name, col.name, target.name, pk.name),
                    "No foreign key is declared, but the column is named exactly like the "
                    "primary key of %s and nothing else, with the same type. Applied because "
                    "--infer-fks asked for it: the model now has a fact type between %s and "
                    "%s." % (target.name, t.name, target.name),
                    "Confirm against the data (--analyse-data scores the same pairing on "
                    "containment, spread and coverage). A name coincidence here is a wrong "
                    "join in every query that walks it.")

    def run(self) -> Tuple[dict, Report]:
        for name in getattr(self.catalog, "unreadable", []):
            self.report.block(
                "read", name,
                "The source lists this, but describing it failed -- a view whose definition "
                "no longer resolves against the tables it names. Nothing about it could be "
                "read, so it is not in the model.",
                "Fix or drop the view in the source schema. Everything else was read.")
        if self.infer:
            self.infer_foreign_keys()
        kinds = {}
        for table in self.catalog.tables:
            kind, extra = classify(self.catalog, table)
            kinds[table.name.casefold()] = (kind, extra)
            if kind == VIEW:
                self.report.refine(
                    "book ch.8", "guess", table.name,
                    "VIEW. Halpin's own chapter concedes marking a view as a fact type "
                    "\"is not strictly correct, since views are typically not materialized\".",
                    "Decide whether this is a derived fact type with a derivation rule, or noise.")
            elif kind == UNKEYED:
                self.report.block(
                    "rule 1", table.name,
                    "No primary key and no foreign key, so there is no shape to read and "
                    "nothing to identify an entity type with.",
                    "Declare a primary key, or supply the identifying columns by hand.")
            elif kind == ENTITY and extra and extra.get("keyless"):
                self.report.refine(
                    "rule 1c", "heuristic", table.name,
                    "No primary key, one foreign key (to %s) and other columns. Read as an "
                    "entity type identified by the row itself (SQLite's rowid, in the mapping "
                    "as a column): a relation is a set of tuples, so that is sound, but it is "
                    "not what anyone means by a key and it binds the model to this dialect."
                    % extra["fk"].ref_table,
                    "Find the real key: --analyse-data reports the column combinations the "
                    "population makes unique. Then declare it.")
            elif kind == FACT and extra.get("keyless"):
                if extra.get("wholly"):
                    self.report.refine(
                        "rule 4d", "sound", table.name,
                        "No primary key, but every column belongs to a foreign key. Read as "
                        "an association whose roles are those foreign keys; a relation is a "
                        "set of tuples, so the whole row identifies the instance and no key "
                        "had to be assumed.",
                        "Confirm the reading. If the table is allowed to hold duplicate rows "
                        "it is a bag, not a fact type, and the spanning uniqueness constraint "
                        "is wrong.")
                else:
                    self.report.refine(
                        "rule 1b", "heuristic", table.name,
                        "No primary key. Read as an association over its %d foreign keys, "
                        "objectified by the remaining columns. Identifying it by those "
                        "foreign keys is an assumption: the catalog does not say the "
                        "combination is unique."
                        % len(extra["fks"]),
                        "Confirm that the foreign keys together identify a row -- Bird's 1997 "
                        "thesis §3.3.9 mines this from the data, but only where the population "
                        "is significant. Otherwise declare the real key.")


        if not any(t.foreign_keys for t in self.catalog.tables if not t.is_view) \
                and len([t for t in self.catalog.tables if not t.is_view]) > 1:
            self.report.refine(
                "rule 4", "blocker-adjacent", "the whole schema",
                "Not one foreign key is declared anywhere. Rule 4 fails silently on "
                "undeclared keys, so every association in this schema has been missed and "
                "each table has become an isolated entity type.",
                "Declare the foreign keys, or run with --infer-fks and confirm every "
                "suggestion against the data. Until then the model is a list of tables, "
                "not a conceptual schema.")

        for table in self.catalog.tables:
            if not table.is_view:
                self.register_table(table)

        # Pass 1 - entity types and their reference schemes (rules 1, 2 partly)
        for table in self.catalog.tables:
            kind, _ = kinds[table.name.casefold()]
            if kind in (ENTITY, SUBTYPE) and table.name.casefold() not in self.absorb:
                self.make_entity(table)
        self.resolve_absorbed()

        # Pass 2 - attributes, foreign keys, associations (rules 2, 3, 4, 5, 6).
        # Associations first: objectifying one creates an entity type, and a foreign key
        # onto that table can only resolve once it exists. Interleaved, a table sorting
        # before the association it references got a spurious rule 3 blocker instead.
        for table in self.catalog.tables:
            kind, extra = kinds[table.name.casefold()]
            if kind == FACT:
                self.make_association(table, extra["fks"], extra)
        for table in self.catalog.tables:
            kind, _ = kinds[table.name.casefold()]
            if kind in (ENTITY, SUBTYPE):
                self.make_attributes(table)

        # Pass 3 - subtyping (rule 7) and discriminators (rule 8)
        for table in self.catalog.tables:
            kind, extra = kinds[table.name.casefold()]
            if kind == SUBTYPE and table.name.casefold() not in self.absorb:
                self.make_subtype(table, extra)
            if kind in (ENTITY, SUBTYPE):
                self.flag_discriminators(table)
            if not table.is_view:
                self.flag_surrogate_association(table)
                self.flag_mixed_key(table, kind)
                self.flag_repeating_group(table)
                self.flag_polymorphic(table)

        if self.infer:
            self.flag_undeclared_fks()
        if self.merge:
            self.merge_domains()
        self.disambiguate_readings()
        self.flag_naming()
        self.flag_value_type_merges()

        model = {
            "ccmVersion": "0.1",
            "id": "reverse-engineered",
            "name": "Draft ORM schema (reverse engineered)",
            "_comment": [
                "DRAFT. Generated by reverse/reverse.py from a relational catalog using the",
                "rules in reverse/README.md.",
                "Halpin: \"In practice, any draft ORM schema obtained by reverse engineering",
                "usually needs many refinements.\" See the accompanying report for the worklist.",
            ],
            "concepts": self.concepts,
            "constraints": self.constraints,
            "functions": standard_functions(self.dialect),
            "mapping": self.mapping,
        }
        self.report.summary = {
            "tables": len([t for t in self.catalog.tables if not t.is_view]),
            "entityTypes": len([c for c in self.concepts if c["kind"] == "entity"]),
            "valueTypes": len([c for c in self.concepts if c["kind"] == "value"]),
            "factTypes": len([c for c in self.concepts if c["kind"] == "fact"]),
            "constraints": len(self.constraints),
            "blockers": len(self.report.blockers),
            "refinements": len(self.report.refinements),
        }
        return model, self.report

    # -- rule 1 ------------------------------------------------------------

    def make_entity(self, table: Table):
        name = pascal(singular(table.name))
        eid = self._unique_id("et", name, self.by_id)
        entity = {"id": eid, "name": name, "kind": "entity", "identifier": [],
                  "terms": terms_for(name, table.name)}
        self._add(entity)
        self.entity_of[table.name.casefold()] = eid
        if not table.primary_key:
            # Rule 1c: no key declared. The instance is identified by the row itself --
            # SQLite's rowid, registered as a column of the mapping. NOT the whole row's
            # columns: that made every attribute part of the identifier, so entering the
            # type from elsewhere asserted every column non-null and silently dropped any
            # row with a NULL in it (the BIRD pilot's thrombosis re-run caught this).
            # A rowid is never null and never repeats. It is also SQLite's, and the
            # mapping says so; another dialect binds its own row identity here.
            tid = self.table_id[table.name.casefold()]
            cid = "c.%s.rowid" % table.name
            self.column_id[(table.name.casefold(), "rowid")] = cid
            self.mapping["columns"].append({
                "id": cid, "table": tid, "name": "rowid",
                "dataType": {"name": "integer"}, "nullable": False, "isRowId": True})
            self.identity_columns[table.name.casefold()] = ["rowid"]
        self.map_concept(eid, table, self.identifying_columns(table))

        key_cols = [table.column(c) for c in table.primary_key]
        if len(key_cols) == 1 and table.fk_for(key_cols[0].name) is None:
            # Simple primary key: "displays as the reference mode of the entity type".
            col = key_cols[0]
            # The reference mode is what the entity type is identified *by*, and it is the
            # name a reader sees first -- `Observatory(.observstation)` says an observatory is
            # known by an observation. Expanded, it says `.observationStation`, which is what
            # the column holds.
            label = self.label_for(col.name, table.name) or "Id"
            # Spelled from the expansion only when there is one. Without --expand-names the
            # reference mode stays the raw column name, which is what it has always been and
            # what the diagram and the .orm export already show.
            mode = (" ".join(_names.words(label)) if self.glossary_on
                    else strip_prefix(col.name, table.name)) or "id"
            entity["referenceMode"] = mode.casefold()
            vt = self.value_type(name + label, col.data_type, source=col.name)
            ft = self.fact_type(
                "%sHas%s" % (name, label),
                [{"_slot": name.lower(), "player": eid, "isMandatory": True},
                 {"_slot": label.lower(), "player": vt, "isMandatory": True}],
                "{0} has {1}")
            entity["identifier"] = [ft["roles"][0]["id"]]
            self.identity_roles[eid] = [ft["roles"][0]["id"]]
            self.uniqueness(ft["id"] + ".pid", [ft["roles"][0]["id"]], preferred=True)
            self.uniqueness(ft["id"] + ".inv", [ft["roles"][1]["id"]])
            ident = self.identifying_columns(table)
            self.map_concept(ft["id"], table, ident)
            self.map_role(ft["roles"][0]["id"], table, ident)
            self.map_role(ft["roles"][1]["id"], table, [col.name])
        else:
            # Composite key: "appears as a primary, external uniqueness constraint".
            self.identity_roles[eid] = []
            if len(table.primary_key) > 1:
                self.report.refine(
                    "rule 1", "sound", "%s (%s)" % (table.name, eid),
                    "Composite primary key over %s, so identification is an external "
                    "uniqueness constraint spanning several fact types rather than a "
                    "reference mode." % ", ".join(table.primary_key),
                    "Confirm the external uniqueness constraint once the key fact types "
                    "exist; consider whether a simpler reference scheme is the real one.")

    # -- rules 2, 3, 5, 6 --------------------------------------------------

    def restrictions_for(self, table: Table):
        """Every CHECK on a table, parsed once. Was re-parsed per column in three passes."""
        key = table.name.casefold()
        cached = self._checks.get(key)
        if cached is None:
            merged, unparsed = {}, []
            for chk in table.checks:
                found, matched = parse_check(chk.expression)
                for col, spec in found.items():
                    merged.setdefault(col, {}).update(spec)
                if not matched:
                    unparsed.append(chk)
            cached = self._checks[key] = (merged, unparsed)
        return cached

    def make_attributes(self, table: Table, skip_columns=frozenset()):
        eid = self.entity_of[table.name.casefold()]
        entity = self.by_id[eid]
        ename = entity["name"]

        restrictions, unparsed = self.restrictions_for(table)
        for check in unparsed:
            self.report.refine(
                "rule 6", "sound", "%s CHECK" % table.name,
                "CHECK constraint not recognised: %s"
                % (check.expression[:120] + ("..." if len(check.expression) > 120 else "")),
                "Only `col IN (...)` and `col BETWEEN x AND y` become value restrictions. "
                "Add the rest by hand, as a value restriction or a textual constraint.")

        simple_pk = len(table.primary_key) == 1 and entity.get("referenceMode")
        unique_single = {c[0].casefold() for c in table.uniques if len(c) == 1}
        handled_fks = set()

        for col in table.columns:
            if simple_pk and table.is_key(col.name):
                continue                              # already the reference scheme
            if col.name.casefold() in skip_columns:
                continue                              # already a role of the objectified fact
            fk = table.fk_for(col.name)

            if fk is not None:
                if id(fk) in handled_fks:
                    continue
                handled_fks.add(id(fk))
                if all(table.is_key(c) for c in fk.columns) and \
                        table.name.casefold() in self.entity_of and \
                        len(table.primary_key) == len(fk.columns):
                    continue                          # the subtype's own key; rule 7 handles it
                identifying = (not simple_pk
                               and all(table.is_key(c) for c in fk.columns))
                self.make_fk_fact(table, eid, ename, fk, identifying)
                continue

            # Rule 12 first: a document column with a record inside it becomes several fact
            # types, one per value -- and then, below, the opaque value as well, so that a
            # query which reads the document with `jsonPath` still can, and so the listing
            # can say beside the document which fact types its values became.
            inside = self.expand_documents(table, eid, ename, col) if self.json_shapes else []

            # Rule 2: a non-key, non-FK column is a binary fact type to a value type.
            label = self.label_for(col.name, table.name)
            restriction = self.restriction_of(restrictions.get(col.name.casefold()))
            vt = self.value_type(ename + label, col.data_type, restriction,
                                 source=col.name)
            if inside:
                self.by_id[vt]["description"] = (
                    "A JSON document. Its values are fact types of their own -- %s -- and a "
                    "query reads those; the document itself is here for a path they do not "
                    "cover." % ", ".join(inside))
            ft = self.fact_type(
                "%sHas%s" % (ename, label),
                [{"_slot": ename.lower(), "player": eid,
                  "isMandatory": not col.nullable and not table.is_key(col.name)},
                 {"_slot": label.lower(), "player": vt, "isMandatory": True}],
                "{0} has {1}")
            self.uniqueness(ft["id"], [ft["roles"][0]["id"]])
            if col.name.casefold() in unique_single:          # rule 5
                self.uniqueness(ft["id"] + ".alt", [ft["roles"][1]["id"]])
            ident = self.identifying_columns(table)
            self.map_concept(ft["id"], table, ident)
            self.map_role(ft["roles"][0]["id"], table, ident)
            self.map_role(ft["roles"][1]["id"], table, [col.name])
            if table.is_key(col.name) and not simple_pk:
                self.identity_roles[eid].append(ft["roles"][0]["id"])

        if not simple_pk and self.identity_roles.get(eid):
            entity["identifier"] = list(self.identity_roles[eid])
            self.uniqueness(eid + ".pid", entity["identifier"], preferred=True)

        for cols in table.uniques:
            if len(cols) > 1:
                self.report.refine(
                    "rule 5", "sound", "%s (%s)" % (table.name, ", ".join(cols)),
                    "Composite UNIQUE constraint. It becomes an external uniqueness constraint "
                    "spanning the fact types for those columns.",
                    "Add the external uniqueness constraint in NORMA; the generator emits only "
                    "the single-column case.")

    def restriction_of(self, spec: Optional[dict]) -> Optional[dict]:
        if not spec:
            return None
        out = {}
        if spec.get("values"):
            out["values"] = spec["values"]
        if spec.get("ranges"):
            out["ranges"] = spec["ranges"]
        return out or None

    # -- rule 3 ------------------------------------------------------------

    def make_fk_fact(self, table: Table, eid: str, ename: str, fk, identifying: bool = False):
        target = self.entity_of.get(fk.ref_table.casefold())
        if target is None:
            self.report.block(
                "rule 3", "%s -> %s" % (table.name, fk.ref_table),
                "Foreign key targets %r, which did not become an entity type."
                % fk.ref_table,
                "Usually means the target has no primary key. Fix that first.")
            return
        target_name = self.by_id[target]["name"]
        # A foreign key column names the table it points AT, so the owning table's prefix
        # must not be stripped: InvoiceLine.InvoiceId is "Invoice", not "Id".
        label = pascal(strip_key_suffix(fk.columns[0])) or target_name
        if len(fk.columns) > 1 or label == target_name or is_abbrev(label, target_name):
            # A composite key's first column names a component, not the target: the pair
            # (cust_code, order_seq) points at an Order, not at a Cust.
            label = target_name
        mandatory = all(not table.column(c).nullable for c in fk.columns)
        roles = [{"_slot": ename.lower(), "player": eid, "isMandatory": mandatory},
                 {"_slot": label.lower(), "player": target, "isMandatory": False}]
        # A self-reference is a ring, and `{0} has {1}` over it says nothing. The column
        # said "manager": read it.
        readings = self.guess_ring_readings(table.name, "%sHas%s" % (ename, label), roles,
                                            [None, label])
        ft = self.fact_type("%sHas%s" % (ename, label), roles, "{0} has {1}", readings)
        self.fk_source[ft["roles"][1]["id"]] = fk.columns[0]
        self.uniqueness(ft["id"], [ft["roles"][0]["id"]])
        ident = self.identifying_columns(table)
        self.map_concept(ft["id"], table, ident)
        self.map_role(ft["roles"][0]["id"], table, ident)
        self.map_role(ft["roles"][1]["id"], table, fk.columns, self.fk_reference(fk))
        if identifying:
            # A weak entity is identified partly by its parent, so the role facing the parent
            # belongs in the preferred identifier. Without this the identifier silently loses
            # a component and the entity is under-identified.
            self.identity_roles[eid].append(ft["roles"][0]["id"])

    # -- rule 4 ------------------------------------------------------------

    def make_association(self, table: Table, fks, how=None):
        how = how or {}
        # The instance is identified by the roles it plays. With a declared key that is the
        # key; without one it is the foreign-key columns themselves, which for rule 4d is
        # every column the table has.
        key_columns = table.primary_key or [c for fk in fks for c in fk.columns]
        self.identity_columns[table.name.casefold()] = key_columns
        name = pascal(singular(table.name))
        roles, players = [], []
        for fk in fks:
            target = self.entity_of.get(fk.ref_table.casefold())
            if target is None:
                self.report.block(
                    "rule 4", table.name,
                    "Association leg targets %r, which did not become an entity type."
                    % fk.ref_table,
                    "Give %r a primary key." % fk.ref_table)
                return
            target_name = self.by_id[target]["name"]
            label = self.role_label(fk, target_name)
            # NOT the player-side mandatory constraint. `assignment.emp_nr NOT NULL` says every
            # assignment row names an employee, which is true of any fact by definition; an
            # ORM mandatory role on Employee would say every EMPLOYEE has an assignment, which
            # the catalogue cannot know and the data usually refutes. FORML verbalized the
            # false claim as "Each Employee has some Project" until §6.5 confluence needed the
            # outer join it forbade.
            roles.append({"_slot": label.lower(), "player": target, "isMandatory": False})
            players.append((label, fk))

        # Each further role gets a verb part of its own, carrying the role's label as a
        # bound adjective the way rule 10's binary readings do. `{0} has {1} and {2}` read
        # more naturally but contributed "and" as the verb part between slots 1 and 2, and
        # a schema may not shadow the language: `... has RaceName v AND ALSO ...` consumed
        # the AND as a step and refused at ALSO (Spider 2.0's f1, every query). It also left
        # every role past the second reachable only through a verb part identical to the one
        # before it, which is an ambiguity on any table with four keys.
        slots = "{1}" + "".join(
            " and has %s- {%d}" % (players[i][0].casefold(), i) for i in range(2, len(roles)))
        reading = "{0} has %s" % slots if len(roles) > 1 else "{0}"
        readings = self.guess_ring_readings(table.name, name, roles, [l for l, _ in players])
        ft = self.fact_type(name, roles, reading, readings)
        spanning = self.uniqueness(ft["id"], [r["id"] for r in ft["roles"]])
        self.map_concept(ft["id"], table, key_columns)
        for role, (_, fk) in zip(ft["roles"], players):
            self.map_role(role["id"], table, fk.columns, self.fk_reference(fk))

        covered = {c.casefold() for fk in fks for c in fk.columns}
        extra = [c for c in table.columns if c.name.casefold() not in covered]
        referenced = self.catalog.referencing(table.name)
        if extra or referenced:
            # "objectified if anything references it" -- and equally if facts hang off it
            ft["isObjectified"] = True
            # For an objectified fact type the spanning uniqueness constraint IS the
            # preferred identifier. Without marking it, the entity type claims an identifier
            # no constraint provides -- a dangling reference that XSD validation lets pass,
            # because libxml2 does not resolve IDREFs in schema mode.
            for k in self.constraints:
                if k["id"] == spanning:
                    k["isPreferredIdentifier"] = True
            eid = self._unique_id("et", name, self.by_id)
            self._add({"id": eid, "name": name, "kind": "entity", "identifier":
                       [r["id"] for r in ft["roles"]]})
            self.entity_of[table.name.casefold()] = eid
            self.map_concept(eid, table, key_columns)
            why = []
            if extra:
                why.append("it carries non-key columns (%s)"
                           % ", ".join(c.name for c in extra))
            if referenced:
                why.append("it is referenced by %s"
                           % ", ".join(t.name for t in referenced))
            self.report.refine(
                "rule 4", "sound", "%s (%s)" % (table.name, ft["id"]),
                "Objectified because %s." % " and ".join(why),
                "Check the objectified type's name -- %r is the table's name, not necessarily "
                "the concept's." % name)
            self.make_attributes(
                table, skip_columns={c.casefold() for _, fk in players for c in fk.columns})

    # -- rule 7 ------------------------------------------------------------

    #  The unit suffix tokens, for stripping one off the end of an expanded name.
    _UNIT_TOKENS = frozenset(u for u, _ in _names.UNIT_SUFFIXES)

    def label_for(self, column: str, table: str) -> str:
        """The PascalCase label a column contributes to a concept name.

        Without `--expand-names` this is rule 10 as it has always been: drop the table's name
        from the front and pascal-case what is left. With it, the abbreviations are written
        out first, so `observstation` stops being a word and becomes `ObservationStation`.

        A unit at the end is dropped, because the value type now has a slot for it. Saying it
        twice is not the reason: `FrequencyMhz` and `CentreFrequencyMhz` are one domain, and a
        name that carries the unit hides that as effectively as no unit at all did.
        """
        raw = strip_prefix(column, table)
        if not self.glossary_on:
            return pascal(raw)
        text = _names.expand(raw, self.glossary)
        parts = text.split()
        if len(parts) > 1 and parts[-1].casefold() in self._UNIT_TOKENS and unit_of(column):
            #  A suffix like `tempc` is a quantity word plus a unit. Dropping the whole token
            #  leaves `AirTempC` as `Air`, which no longer says what was measured, so the
            #  quantity word goes back and only the unit letters leave.
            residue = _names.UNIT_TOKEN_RESIDUE.get(parts[-1].casefold())
            parts = parts[:-1] + ([residue] if residue else [])
        return pascal(" ".join(parts))

    def merge_domains(self):
        """Fold value types measured in the same unit into one domain.

        Reverse engineering mints one value type per column, so a schema of 136 columns gets
        126 value types every one of which is played by exactly one role. That is not a model
        of anything: `sourceradeg` and `polarangledeg` are both an angle in degrees, and a
        model that cannot say so cannot compare them, reuse a restriction, or tell a reader
        that the two are commensurable.

        The unit is what makes the merge safe. Merging on data type alone would put every
        `real` column in one domain; merging on an identical enumeration is defensible but
        cannot be *named* -- the three columns sharing {High, Low, Medium} have no word in
        common -- so those are reported instead, and left alone.

        Celsius and kelvin do not merge. They are the same quantity and not the same domain.
        """
        groups: Dict[tuple, List[dict]] = {}
        for c in self.concepts:
            if c["kind"] == "value" and c.get("unit"):
                key = (c["dataType"]["name"], c["unit"])
                groups.setdefault(key, []).append(c)

        units = [u for _, u in groups]
        merged = []
        for (_, unit), members in sorted(groups.items()):
            if len(members) < 2:
                continue
            name = self._unique_id("vt", _names.quantity_name(unit, units), self.by_id)
            keep = members[0]
            # Every id the merge retires, the survivor's own included: it is about to be
            # renamed, so comparing against it afterwards would match nothing.
            gone = {m["id"] for m in members}
            was = [m["name"] for m in members]
            # The survivor becomes the domain: renamed for what it measures, and carrying
            # every term its members answered to so a question naming an old one still lands.
            keep["id"], keep["name"] = name, name.split(".", 1)[1]
            keep["terms"] = sorted({t for m in members for t in m.get("terms", [])})
            keep.pop("restriction", None)      # one column's values are not the domain's
            self.concepts = [c for c in self.concepts
                             if c["id"] not in gone or c is keep]
            self.by_id = {c["id"]: c for c in self.concepts}
            for c in self.concepts:
                for r in c.get("roles", []):
                    if r["player"] in gone:
                        r["player"] = name
            for k, v in list(self.value_types.items()):
                if v in gone:
                    self.value_types[k] = name
            for e in self.mapping["conceptMap"]:
                if e["concept"] in gone:
                    e["concept"] = name
            merged.append((keep["name"], unit, was))

        self.disambiguate_merged(groups)
        for name, unit, was in merged:
            self.report.refine(
                "rule 6e", "heuristic", name,
                "%s are all measured in %s, so they are one domain, not %d. Merged and named "
                "for what the unit measures. Applied because --merge-domains asked for it."
                % (_summarise(was), unit, len(was)),
                "Check that they really are commensurable. Two columns can share a unit and "
                "not a domain -- a wavelength and a height are both metres.")
        return len(merged)

    def disambiguate_merged(self, groups):
        """Give each fact type reaching a merged domain a reading that tells it apart.

        Merging is right as modelling and wrong as vocabulary if nothing else changes. Three
        columns measured in MHz become one `FrequencyInMHz`, and the three fact types that
        reached them all read `{0} has {1}` -- so `Signal has FrequencyInMHz` is ambiguous
        between the observed, the centre and the carrier frequency, and the compiler's advice,
        "name the type it reaches", is no help because they reach the same type. A writer on
        the LiveSQLBench arm hit this on two of four questions.

        The repair is the one rule 10 already uses for a ring: FORML 2 section 1.2's
        hyphen-bound adjective, which binds a qualifier to the object type. `Signal has
        centerfreq- FrequencyInMHz` names the role, and the query language drops the hyphen.
        """
        for c in self.concepts:
            if c["kind"] != "fact" or len(c.get("roles", [])) != 2:
                continue
            near, far = c["roles"]
            if far["player"] not in {m["id"] for members in groups.values()
                                     for m in members}:
                continue
            # Only where it is actually ambiguous: one fact type to a domain needs no
            # qualifier, and adding one would make every merged model read worse.
            siblings = [o for o in self.concepts
                        if o["kind"] == "fact" and len(o.get("roles", [])) == 2
                        and o["roles"][0]["player"] == near["player"]
                        and o["roles"][1]["player"] == far["player"]]
            if len(siblings) < 2:
                continue
            adjective = far.get("name") or ""
            if not adjective:
                continue
            for rd in c.get("readings", []):
                if rd["text"] == "{0} has {1}":
                    rd["text"] = "{0} has %s- {1}" % adjective.casefold()

    def resolve_absorbed(self):
        """Point each absorbed table at the entity type its columns will hang off.

        An absorbed table gets no entity type of its own: its columns become fact types on the
        parent, which is what a vertical partition means -- the same instance, more facts about
        it. Everything downstream reads `entity_of`, so aliasing it is the whole change; the
        columns still map to the partition's own table, and the compiler still emits the join.

        The walk is transitive because partitions chain. `credit` stacks five of them, and
        stopping at the immediate parent would leave four entity types where the schema has
        one. A cycle would be a foreign key ring between primary keys, which cannot happen,
        but the guard is cheap and the alternative is a hang.
        """
        for child in self.absorb:
            seen, at = {child}, child
            while at in self.absorb:
                at = self.absorb[at].casefold()
                if at in seen:
                    at = None
                    break
                seen.add(at)
            root = self.entity_of.get(at) if at else None
            if root is None:
                continue
            self.entity_of[child] = root
            self.identity_columns[child] = self.identity_columns.get(at, [])
            self.alias_identifier(root, child)
            self.report.refine(
                "rule 7b", "population", "%s -> %s" % (child, self.by_id[root]["name"]),
                "Every instance of %s is in this table, so it is not a subtype of it but a "
                "second table of columns about the same instance. Its columns become fact "
                "types on %s. Applied because --infer-partitions asked for it."
                % (self.by_id[root]["name"], self.by_id[root]["name"]),
                "Confirm it. A subtype that happens to hold every instance today looks "
                "exactly like this, and absorbing one loses the distinction the schema was "
                "drawing. Queries written against the separate type will need rewriting.")

    def alias_identifier(self, root: str, child: str):
        """An absorbed partition's key is the root's identifier under another name: say so.

        Absorbing `expenses_and_assets` into CoreRecord keeps its columns and drops its key,
        because `expemplref` holds `coreregistry`'s value and a second fact type for it would
        say nothing. But the *word* went with it. The mapping still knows the identity is
        spelled six ways; the vocabulary knew one, so a question or a definition that says
        `expemplref` matched no concept at all -- and the gold of every credit question names
        the customer by whichever partition's key was in front of its author. Vocabulary, not
        a name: `terms` only ever widen what a matcher accepts.
        """
        table = self.catalog.table(child)
        roles = self.identity_roles.get(root) or []
        if table is None or len(table.primary_key) != 1 or len(roles) != 1:
            return                      # a composite identity has no one value type to alias
        fact = next((c for c in self.concepts if c["kind"] == "fact"
                     and any(r["id"] == roles[0] for r in c["roles"])), None)
        if fact is None:
            return
        vt = self.by_id.get(next(r["player"] for r in fact["roles"] if r["id"] != roles[0]))
        if vt is None or vt["kind"] != "value":
            return
        key = table.primary_key[0]
        vt["terms"] = sorted(set(vt.get("terms", [])) | {key.casefold()}
                             | {w.casefold() for w in words(key) if len(w) > 1})

    def make_subtype(self, table: Table, extra):
        sub = self.entity_of.get(table.name.casefold())
        sup = self.entity_of.get(extra["supertype"].name.casefold())
        if not sub or not sup:
            return
        self.by_id[sub].setdefault("supertypes", []).append(sup)
        # A subtype inherits its supertype's reference scheme and declares none of its own.
        # Copying the supertype's identifier across made the subtype name a role whose player
        # is the supertype -- a dangling reference in all but name -- and, because the copy
        # was taken when the subtype was reached rather than when the supertype was resolved,
        # a chain of subtypes copied an identifier that was still empty. `credit` stacks five
        # and the last three came out unidentifiable. Not copying fixes both.
        self.by_id[sub].pop("identifier", None)
        self.report.refine(
            "rule 7", "heuristic", "%s -> %s" % (table.name, extra["supertype"].name),
            "One-to-one foreign key between two primary keys, read as subtyping: %s is a "
            "subtype of %s." % (self.by_id[sub]["name"], self.by_id[sup]["name"]),
            "Confirm. The same shape is also how a plain 1:1 association or vertical "
            "partitioning looks. If it is subtyping, add the subtype derivation rule; "
            "if not, replace the SubtypeFact with a one-to-one fact type.")

    # -- rule 8 ------------------------------------------------------------

    def flag_discriminators(self, table: Table):
        nullable = [c for c in table.columns
                    if c.nullable and not table.is_key(c.name) and table.fk_for(c.name) is None]
        if len(nullable) < 2:
            return
        for col in table.columns:
            if table.is_key(col.name) or col.nullable:
                continue
            looks_like = re.search(r"(type|kind|category|status|class|discriminator)$",
                                   col.name, re.IGNORECASE)
            restricted = bool(self.restrictions_for(table)[0]
                              .get(col.name.casefold(), {}).get("values"))
            if looks_like or restricted:
                self.report.refine(
                    "rule 8", "heuristic", "%s.%s" % (table.name, col.name),
                    "Looks like a discriminator (%s) alongside %d nullable columns (%s). "
                    "That is the shape of subtypes flattened into one table."
                    % ("enumerated by a CHECK" if restricted else "named like a type column",
                       len(nullable), ", ".join(c.name for c in nullable[:6])),
                    "If these are subtypes, split them out and give each a subtype derivation "
                    "rule over this column. Not applied automatically.")

    # -- shapes the rule table does not cover ------------------------------
    #
    # Four patterns common in real schemas that rules 1-10 get silently wrong rather than
    # loudly wrong. None is applied; each is reported, because each has an innocent reading
    # as well as the suspicious one.

    def flag_surrogate_association(self, table: Table):
        """An association table given a surrogate key stops looking like an association.

        Rule 4 keys off "the primary key is wholly foreign keys". Add an `id` column and that
        test fails, so the association becomes an entity type and the fact type is lost. The
        giveaway is a UNIQUE constraint covering exactly the foreign key columns -- the
        natural key the surrogate replaced.
        """
        if len(table.primary_key) != 1 or table.fk_for(table.primary_key[0]) is not None:
            return
        if len(table.foreign_keys) < 2:
            return
        fk_cols = {c.casefold() for fk in table.foreign_keys for c in fk.columns}
        for cols in table.uniques:
            if {c.casefold() for c in cols} == fk_cols:
                payload = [c.name for c in table.columns
                           if not table.is_key(c.name) and table.fk_for(c.name) is None]
                self.report.refine(
                    "rule 4b", "heuristic", table.name,
                    "Primary key is a surrogate, but UNIQUE (%s) covers exactly the foreign "
                    "key columns. That is an association table wearing a surrogate key, so "
                    "rule 4 did not fire and it became an entity type instead of a %s fact "
                    "type."
                    % (", ".join(cols), "n-ary" if len(table.foreign_keys) > 2 else "binary"),
                    "If it is an association, make it a fact type over %s%s. If the surrogate "
                    "is genuinely referenced elsewhere as an identity, leave it as an entity "
                    "type and objectify instead."
                    % (" and ".join(fk.ref_table for fk in table.foreign_keys),
                       ", objectified to carry %s" % ", ".join(payload) if payload else ""))
                return

    def flag_mixed_key(self, table: Table, kind: str):
        """A primary key that is part foreign key and part something else.

        Weak entities, versioned relationships and multi-valued attributes all land here, and
        all three are usually a fact type rather than an entity type. Rule 4 only fires when
        the key is *wholly* foreign keys, so none of them is caught.
        """
        if kind not in (ENTITY, SUBTYPE) or len(table.primary_key) < 2:
            return
        fk_part = [c for c in table.primary_key if table.fk_for(c) is not None]
        rest = [c for c in table.primary_key if table.fk_for(c) is None]
        if not fk_part or not rest:
            return
        rest_cols = [table.column(c) for c in rest]
        kinds = {(c.data_type or "").split("(")[0].casefold() for c in rest_cols if c}
        if kinds & {"date", "datetime", "timestamp"}:
            reading = ("a relationship versioned by %s -- conceptually a fact type with a "
                       "date role, not an entity type" % ", ".join(rest))
        elif all(re.search(r"(seq|no|num|line|idx|order)$", c, re.IGNORECASE) for c in rest):
            reading = ("a weak entity: %s only sequences the parent's children, so this is "
                       "usually a multi-valued fact type about %s"
                       % (", ".join(rest), fk_part[0]))
        else:
            reading = ("part foreign key, part %s, which is the shape of an objectified or "
                       "multi-valued fact type" % ", ".join(rest))
        self.report.refine(
            "rule 4c", "heuristic", table.name,
            "Primary key (%s) is %s." % (", ".join(table.primary_key), reading),
            "Decide whether this is really an entity type in its own right. If it is not, "
            "replace it with a fact type and let its identification come from the parent.")

    _SEQ = re.compile(r"^(.*?)[_ ]?(\d+)$")

    def flag_repeating_group(self, table: Table):
        """phone1, phone2, phone3: one multi-valued fact spread across numbered columns."""
        groups = {}
        for col in table.columns:
            m = self._SEQ.match(col.name)
            if not m or not m.group(1):
                continue
            key = (m.group(1).casefold(), (col.data_type or "").casefold())
            groups.setdefault(key, []).append(col.name)
        for (stem, _), cols in sorted(groups.items()):
            if len(cols) >= 2:
                self.report.refine(
                    # A subject names the thing; it does not enumerate it. A 200-column
                    # dimension turned this line into an unreadable wall.
                    "rule 2b", "heuristic", "%s (%s)" % (table.name, _summarise(sorted(cols))),
                    "%d columns share the stem %r and a data type, differing only by a "
                    "number. That is one multi-valued fact spread across columns, and it has "
                    "become %d unrelated single-valued fact types."
                    % (len(cols), stem, len(cols)),
                    "Replace them with one fact type %s has %s, with no uniqueness on the %s "
                    "role." % (pascal(singular(table.name)), pascal(stem),
                               pascal(singular(table.name))))

    def flag_polymorphic(self, table: Table):
        """owner_type + owner_id: a reference no foreign key can express."""
        names = {c.name.casefold(): c for c in table.columns}
        for col in table.columns:
            m = re.match(r"^(.*?)[_ ]?(type|kind|class)$", col.name, re.IGNORECASE)
            if not m or not m.group(1):
                continue
            stem = m.group(1)
            partner = next((names[k] for k in
                            (stem.casefold() + "_id", stem.casefold() + "id",
                             stem.casefold() + "_key", stem.casefold() + "_no")
                            if k in names), None)
            if partner is None or table.fk_for(partner.name) is not None:
                continue
            values = self.restrictions_for(table)[0].get(
                col.name.casefold(), {}).get("values") or []
            self.report.refine(
                "rule 3b", "heuristic",
                "%s (%s, %s)" % (table.name, col.name, partner.name),
                "%r selects a table and %r holds a key into it, with no foreign key declared "
                "and none possible. A polymorphic reference like this cannot be a single fact "
                "type.%s" % (col.name, partner.name,
                             " The discriminator admits %s." % ", ".join(values)
                             if values else ""),
                "In ORM this is usually a supertype: give the referenced types a common "
                "supertype and make one fact type to it. Nothing here can be derived "
                "automatically.")

    # -- rule 9 ------------------------------------------------------------

    def flag_undeclared_fks(self):
        pk_index = {}
        for table in self.catalog.tables:
            if len(table.primary_key) == 1 and not table.is_view:
                pk_index.setdefault(table.primary_key[0].casefold(), []).append(table)

        for table in self.catalog.tables:
            if table.is_view:
                continue
            for col in table.columns:
                if table.fk_for(col.name) is not None or table.is_key(col.name):
                    continue
                for target in pk_index.get(col.name.casefold(), []):
                    if target.name.casefold() == table.name.casefold():
                        continue
                    self.report.refine(
                        "rule 9", "guess", "%s.%s -> %s.%s"
                        % (table.name, col.name, target.name, target.primary_key[0]),
                        "Column name matches the primary key of %s, but no foreign key is "
                        "declared, and the name matches more than one table or the types "
                        "differ, so it was not applied." % target.name,
                        "Confirm against the data before adding a fact type by hand. Name "
                        "coincidence is not a reference.")

    # -- rule 10 and Halpin's named refinements ----------------------------

    def flag_naming(self):
        facts = [c for c in self.concepts if c["kind"] == "fact"]
        guessed = {name for name, _ in self.reading_guesses}
        if self.reading_guesses:
            self.report.refine(
                "rule 10", "guess", "readings read from names: " + _summarise(sorted(guessed)),
                "A reading that says nothing was replaced by one read from the column or "
                "the table name: a ring fact type (both roles played by one type, \"Atom "
                "has Atom\"), or two fact types between the same pair of types that read "
                "alike (\"Superhero has Colour\" twice). %s.%s"
                % ("; ".join("%s reads \"%s\"" % (n, t) for n, t in self.reading_guesses),
                   " The hyphen binds an adjective to the object type (FORML 2 section 1.2): "
                   "`has manager- Employee` verbalises as \"at most one manager Employee\" "
                   "and a query says `has manager Employee`."
                   if any("-" in t for _, t in self.reading_guesses) else ""),
                "Check each. A wrong guess on a ring inverts a hierarchy silently, and a "
                "wrong adjective attaches a fact to the wrong column.")
        if len(facts) > len(guessed):
            self.report.refine(
                "rule 10", "guess", "all %d fact types" % len(facts)
                if not guessed else "%d of %d fact types" % (len(facts) - len(guessed), len(facts)),
                "Every predicate reading%s is a placeholder generated from table and column "
                "names (\"{0} has {1}\"). None of them came from the database."
                % (" but those above" if guessed else ""),
                "Renaming predicates is the first refinement Halpin's chapter 8 names. Do it "
                "in NORMA before the model is used for anything.")
        entities = [c for c in self.concepts if c["kind"] == "entity"]
        if entities:
            self.report.refine(
                "rule 10", "guess", "all %d entity types" % len(entities),
                "Entity type names are singularised table names, by suffix rules that do not "
                "know English.",
                "Check them, especially irregular plurals and abbreviations.")
        self.report.refine(
            "book ch.8", "guess", "the whole model",
            "Missing constraints. The catalog declares uniqueness, nullability and referential "
            "integrity; it does not declare frequency, ring, subset, equality, exclusion or "
            "value comparison constraints, so none are present.",
            "Add them in NORMA. Halpin lists this among the refinements a draft always needs.")

    def flag_value_type_merges(self):
        by_shape: Dict[str, List[dict]] = {}
        for c in self.concepts:
            if c["kind"] != "value":
                continue
            dt = c["dataType"]
            suffix = re.sub(r"^[A-Z][a-z]+", "", c["name"]) or c["name"]
            by_shape.setdefault("%s|%s|%s" % (suffix, dt["name"], dt.get("length", "")),
                                []).append(c)
        for group in [g for _, g in sorted(by_shape.items())]:
            if len(group) > 1:
                self.report.refine(
                    "book ch.8", "heuristic", ", ".join(c["name"] for c in group),
                    "%d value types share a name suffix and data type. They may be one value "
                    "type." % len(group),
                    "\"Consolidate redundant value types\" is a refinement chapter 8 names. "
                    "Merge only where they really are the same domain -- PersonName and "
                    "CompanyName usually are not.")


def derive(catalog: Catalog, infer_undeclared_fks: bool = False, json_shapes=None,
           dialect: str = "sqlite", absorb=None, merge_domains: bool = False, glossary=None):
    return Deriver(catalog, infer_undeclared_fks, json_shapes, dialect, absorb,
                   merge_domains, glossary).run()
