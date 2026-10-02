#!/usr/bin/env python3
"""Bird's Step 9: mine the data for constraints the catalogue does not declare.

§3.3.9 of *Data Reverse Engineering: from a Relational Database System to a 3-Dimensional
Conceptual Schema* (L. J. Bird, UQ, 1997). Her extraction methodology reads seven sources --
catalogue, check clauses, assertions, table triggers, user-interface code, program code, and
the data itself. `derive.py` reads the first two. This module adds the seventh, which is the
only one of the remaining five that a database connection can supply on its own.

Three of her algorithms are implemented, chosen because each answers a question the catalogue
left open in a measured way:

    3.9-a  nullable roles          a column declared nullable that is never null
    3.9-b  uniqueness constraints  a column combination with no duplicates
    3.9-g  subset constraints      one column's values contained in another's -- which, when
                                   the target is a key, is a candidate foreign key

A fourth is ours rather than Bird's, and is the same kind of claim: a column holding a handful
of distinct values over a large population is a candidate *value constraint* -- ORM's fourth
constraint kind, and the one a query author needs most, since a model that does not say a
status is one of 'A', 'B', 'C' or 'D' leaves them guessing at the spelling. It obeys the same
rule as the rest: proposed with its population attached, never sound.

The third is the one that matters. Bird's own case study declares no foreign keys at all
(Appendix G.3), and `derive.py` reading only the catalogue turns its 16 tables into 16
unrelated entity types. An inclusion dependency is the evidence that recovers them.

**Nothing here is ever sound.** Bird is explicit, and the sentence is worth keeping next to
the code:

    "if the population is not significant, trends or constraints may be detected which hold by
    coincidence rather than by necessity. The decision as to which of the constraints
    identified in this step necessarily hold in the information system is ultimately the job
    of a domain expert."

So every finding carries the population it was drawn from, and findings below `MIN_ROWS` are
reported as weak rather than suppressed -- suppressing them would hide the evidence along with
the doubt. Data can refute a constraint outright; it can only ever make one plausible.
"""

from __future__ import annotations

import bisect
import itertools
import re
import sqlite3

import catalog as catalog_mod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# Below this, Bird's "coincidence rather than necessity". Her Table 3.1 says *significant*
# populations throughout, and never fixes a number -- this one is ours, and arbitrary. It is
# here so the threshold is visible and arguable rather than implied.
MIN_ROWS = 50

# An inclusion dependency over very few distinct values is nearly free: every column whose
# only value is 1 is "contained in" every key that contains 1.
MIN_DISTINCT = 3

# A value domain: few enough values to enumerate, over a population large enough that seeing
# no others means something, and values short enough to be codes rather than prose. The ratio
# is what separates a domain from a column that is nearly unique -- 25 values over 30 rows is
# not an enumeration, it is a sample.
DOMAIN_MAX_VALUES = 25
DOMAIN_MIN_RATIO = 4
DOMAIN_MAX_LENGTH = 120


@dataclass
class Finding:
    """One constraint the data supports, with the evidence it rests on."""
    kind: str            # never-null | unique | inclusion | inclusion-1to1 | violated |
                         # satisfied | value-domain | junk | column-type | quality |
                         # exclusion | comparison | computed | ring | equality |
                         # dependency | aggregate
    table: str
    columns: List[str]
    rows: int                       # the population it was drawn from
    distinct: Optional[int] = None
    target_table: Optional[str] = None
    target_columns: Optional[List[str]] = None
    score: float = 0.0              # how much the signals of _rank agree, 0..6
    name_score: float = 0.0         # how far the column's NAME points at this target, 0..1
    signals: List[str] = field(default_factory=list)
    preferred: bool = False         # the best-scoring target for this column
    values: Optional[List[str]] = None   # value-domain: the values the population holds;
                                        # column-type: the one type they are stored as
    # A value read from inside a document rather than from the column itself: the JSON
    # keys down to it (rule 12). `columns[0]` is then the document column. A miner that
    # reads by expression rather than by name -- the domain miner -- runs over both.
    path: Optional[List[str]] = None

    @property
    def corroborated(self) -> bool:
        """The strongest single signal: the column's name points where its values do.

        Measured alone at 100% precision across four databases, and the one signal Zhang et
        al. found their value-distribution feature does *not* subsume."""
        return any(s in ("name_pk_table", "name_pk_col") for s in self.signals)

    @property
    def significant(self) -> bool:
        if self.rows < MIN_ROWS:
            return False
        if self.kind.startswith("inclusion") and (self.distinct or 0) < MIN_DISTINCT:
            return False
        if self.kind == "value-domain" and self.rows < (self.distinct or 0) * DOMAIN_MIN_RATIO:
            return False
        return True

    @property
    def evidence(self) -> str:
        n = "%d row%s" % (self.rows, "" if self.rows == 1 else "s")
        if self.distinct is not None:
            n += ", %d distinct value%s" % (self.distinct, "" if self.distinct == 1 else "s")
        return n if self.significant else n + " -- too few to be evidence"


@dataclass
class Analysis:
    row_counts: Dict[str, int] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def of_kind(self, kind: str) -> List[Finding]:
        return [f for f in self.findings if f.kind == kind]


def summarise(names: Sequence[str], limit: int = 6) -> str:
    """Name a column list without printing all of it."""
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return "%s, ... %s (%d columns)" % (", ".join(names[:limit - 1]), names[-1], len(names))


def _q(names: Sequence[str]) -> str:
    return ", ".join('"%s"' % n.replace('"', '""') for n in names)


def _t(name: str) -> str:
    return '"%s"' % name.replace('"', '""')


def _containment(conn, table, cols, ref_table, ref_cols):
    """(matched, total): the child's non-null key tuples, and how many are in the parent."""
    on = " AND ".join('p."%s" = c."%s"' % (r.replace('"', '""'), k.replace('"', '""'))
                      for k, r in zip(cols, ref_cols))
    notnull = " AND ".join('c."%s" IS NOT NULL' % k.replace('"', '""') for k in cols)
    sql = ("SELECT count(*), sum(CASE WHEN EXISTS (SELECT 1 FROM %s p WHERE %s) THEN 1 "
           "ELSE 0 END) FROM (SELECT DISTINCT %s FROM %s) c WHERE %s"
           % (_t(ref_table), on, ", ".join('"%s"' % k.replace('"', '""') for k in cols),
              _t(table), notnull))
    total, matched = conn.execute(sql).fetchone()
    return matched or 0, total or 0


def verify_foreign_keys(conn: sqlite3.Connection, catalog) -> List[tuple]:
    """Hold every declared foreign key against the rows, before anything is derived from it.

    A declaration is a claim, and the catalogues here make false ones: an integer zone
    number declared to reference a text region name, which no row satisfies (finding 172).
    A reference the data contradicts entirely -- not one of its values is in the parent --
    is dropped. A composite key `catalog.repair_crossed_keys` rebuilt is paired by position,
    which is a guess; here every order of its columns is tried and the one the rows bear out
    is kept. Returns (table, columns, parent, verdict, matched, total) for the report.
    """
    from itertools import permutations
    out = []
    for table in catalog.tables:
        keep = []
        for fk in table.foreign_keys:
            if catalog.table(fk.ref_table) is None:
                keep.append(fk)
                continue
            try:
                matched, total = _containment(conn, table.name, fk.columns,
                                              fk.ref_table, fk.ref_columns)
            except sqlite3.Error:
                keep.append(fk)
                continue
            if total and not matched:
                out.append((table.name, list(fk.columns), fk.ref_table, "dropped", 0, total))
                continue
            if len(fk.columns) > 1 and len(fk.columns) <= 4 and total and matched < total:
                best = (matched, list(fk.ref_columns))
                for order in permutations(fk.ref_columns):
                    try:
                        m, _ = _containment(conn, table.name, fk.columns, fk.ref_table, order)
                    except sqlite3.Error:
                        continue
                    if m > best[0]:
                        best = (m, list(order))
                if best[1] != list(fk.ref_columns):
                    out.append((table.name, list(fk.columns), fk.ref_table,
                                "re-paired as (%s)" % ", ".join(best[1]), best[0], total))
                    fk.ref_columns = best[1]
                    matched = best[0]
            keep.append(fk)
        table.foreign_keys = keep
    return out


def shared_key_links(conn: sqlite3.Connection, catalog) -> List[tuple]:
    """Rule 9d: the link two tables share through a pair of references neither declares.

    `pointcloud`, `registration` and `spatial` each carry `(arcref, crewref)` -- a project
    and a crew member -- and so does `scans`; the pair is unique in all four, and every
    point cloud's pair is a scan's. That is one scan per point cloud, the join every writer
    in finding 172 found by counting, and the model had only the two references to Project
    and Personnel. Here: for every two tables whose foreign keys to the same two parents use
    a pair unique in both, where one table's pairs lie inside the other's, the one is declared
    to reference the other through the pair, and the pair made a unique key of the target.
    Returns (child, columns, parent, parent columns, matched, total) for the report.
    """
    def pairs_of(t):
        single = [fk for fk in t.foreign_keys if len(fk.columns) == 1]
        out = {}
        for i, a in enumerate(single):
            for b in single[i + 1:]:
                key = tuple(sorted([(_fold_name(a.ref_table), _fold_name(a.ref_columns[0])),
                                    (_fold_name(b.ref_table), _fold_name(b.ref_columns[0]))]))
                cols = [a.columns[0], b.columns[0]] if key[0][0] == _fold_name(a.ref_table) \
                    else [b.columns[0], a.columns[0]]
                if key[0] == key[1]:
                    continue
                out[key] = cols
        return out

    def unique(t, cols):
        try:
            total, distinct = conn.execute(
                "SELECT count(*), count(DISTINCT %s) FROM %s WHERE %s"
                % (" || '\x1f' || ".join('"%s"' % c.replace('"', '""') for c in cols),
                   _t(t.name), " AND ".join('"%s" IS NOT NULL' % c.replace('"', '""')
                                           for c in cols))).fetchone()
        except sqlite3.Error:
            return False, 0
        return bool(total) and total == distinct, total

    by_pair = {}
    for t in catalog.tables:
        for key, cols in pairs_of(t).items():
            by_pair.setdefault(key, []).append((t, cols))
    found = []
    for key, members in by_pair.items():
        if len(members) < 2:
            continue
        uniq = []
        for t, cols in members:
            ok, n = unique(t, cols)
            if ok:
                uniq.append((t, cols, n))
        for i, (a, acols, an) in enumerate(uniq):
            for b, bcols, bn in uniq[i + 1:]:
                # the bigger population is the one referred to
                (child, ccols, cn), (parent, pcols, pn) = sorted(
                    [(a, acols, an), (b, bcols, bn)], key=lambda x: x[2])
                if any(fk.ref_table.casefold() == parent.name.casefold()
                       for fk in child.foreign_keys):
                    continue
                try:
                    matched, total = _containment(conn, child.name, ccols, parent.name, pcols)
                except sqlite3.Error:
                    continue
                if not total or matched != total:
                    continue
                if not any({c.casefold() for c in u} == {c.casefold() for c in pcols}
                           for u in [parent.primary_key] + list(parent.uniques)):
                    parent.uniques.append(list(pcols))
                from catalog import ForeignKey
                child.foreign_keys.append(ForeignKey(columns=list(ccols), ref_table=parent.name,
                                                     ref_columns=list(pcols)))
                found.append((child.name, list(ccols), parent.name, list(pcols), matched, total))
    return found


def _fold_name(name):
    return name.casefold()


def analyse(conn: sqlite3.Connection, catalog, tables=None,
            include_declared: bool = False, ignore_names: bool = False,
            also_unique: Optional[List["Finding"]] = None) -> Analysis:
    """Run the three algorithms over a live connection. Read-only throughout.

    `include_declared` keeps columns that already carry a declared foreign key in the
    inclusion search, which is useless in production and essential for evaluation: a database
    that declares its foreign keys is the only place this analysis can be *scored*, by asking
    how many of them it rediscovers and how much else it claims besides.

    `ignore_names` scores on the shape of the data alone. Worth reaching for when a schema
    names its references for the concept and its keys for the identifier, as Bird's case study
    does -- there string comparison is not weak evidence, it is no evidence, and including it
    only adds noise.
    """
    out = analyse_keys(conn, catalog, tables)
    live = [t for t in (tables or catalog.tables) if not t.is_view]
    _junk_dimensions(conn, live, out)
    _inclusions(conn, live, out, include_declared,
                *(( SHAPE_ONLY, SHAPE_ONLY_THRESHOLD) if ignore_names else (None, None)),
                also_unique=also_unique)
    _violations(conn, live, out)
    _dirt(conn, live, out)
    _alternate_keys(conn, live, out)
    _value_domains(conn, live, out)      # after inclusions: a candidate key is not a domain
    _undeclared_types(conn, live, out)
    _exclusions(conn, live, out)
    _comparisons(conn, live, out)
    _computed(conn, live, out)
    _rings(conn, live, out)
    _equalities(conn, live, out)
    _dependencies(conn, live, out)
    _aggregates(conn, live, out)
    return out


def analyse_keys(conn: sqlite3.Connection, catalog, tables=None) -> Analysis:
    """Row counts, mandatory roles and candidate identifiers, and nothing else.

    Split out because order matters and it is not the order the algorithms were written in.
    A foreign key points *at a key*, so the inclusion search has nothing to aim at until the
    keys exist -- and on a schema that declares none, they do not exist until rule 9b has run.
    Jiang & Naumann call detecting the two together holistic and make it the point of HoPF;
    here it is enough to run this part, apply what it finds, and only then go looking for
    references.
    """
    out = Analysis()
    live = [t for t in (tables or catalog.tables) if not t.is_view]
    for t in live:
        try:
            out.row_counts[t.name] = conn.execute(
                "SELECT COUNT(*) FROM %s" % _t(t.name)).fetchone()[0]
        except sqlite3.Error as e:
            out.skipped.append("%s: %s" % (t.name, e))
    _never_null(conn, live, out)
    _unique(conn, live, out)
    return out


# -- undeclared column types ------------------------------------------------------------

def _undeclared_types(conn, tables, out: Analysis) -> None:
    """What a column with no declared type actually holds.

    SQLite lets a column be created with no type at all, and several of Spider 2.0's local
    databases do it -- `drives.drive_id` in f1 is one. `conceptual_type` had nothing to read
    and fell back to text, so the model said text, `--schema` printed the domain as `'1'`,
    and `Drive has DriveId: '1'` compared a string with an integer in a column with no
    affinity to convert either: zero rows, no error, no warning. Exactly the silent wrong
    answer this compiler exists to make impossible.

    A declared type is never second-guessed here, however badly it fits: the catalogue is a
    statement about the universe of discourse and the population is only today's data. This
    speaks only where the catalogue is silent, which is Bird's Step 9 working as intended.
    """
    for t in tables:
        if not out.row_counts.get(t.name):
            continue
        for col in t.columns:
            if getattr(col, "declared", True):
                continue
            try:
                rows = conn.execute(
                    "SELECT typeof(%s), COUNT(*) FROM %s WHERE %s IS NOT NULL "
                    "GROUP BY 1 ORDER BY 2 DESC"
                    % (_q([col.name]), _t(t.name), _q([col.name]))).fetchall()
            except sqlite3.Error:
                continue
            if not rows:
                continue
            kinds = {k: n for k, n in rows}
            seen = sum(kinds.values())
            # one type, or integers among reals: a column holding both is a number either way
            if set(kinds) <= {"integer", "real"}:
                name = "real" if kinds.get("real") else "integer"
            elif len(kinds) == 1:
                name = {"text": "text", "blob": "blob"}.get(rows[0][0], rows[0][0])
            else:
                continue                      # mixed storage: text is the honest description
            out.findings.append(Finding("column-type", t.name, [col.name],
                                        out.row_counts[t.name], distinct=seen,
                                        values=[name]))


# -- data quality: what the values say about themselves ----------------------------------

# A text value that begins with a number and carries something else: `'104 days'`,
# `'57 years, mature donor'`. The number is the datum and the rest is a unit or a comment.
#
# A date is not that. `'2024-08-09 04:49'` also starts with digits and a non-digit, and
# admitting it made this fire on 162 columns of one database -- the wallpaper finding 128
# warns about. A date is a value of its own type, correctly stored as text by a catalogue
# with no date type; the thing worth reporting is a *quantity* wearing a unit.
_NUMERIC_TEXT = re.compile(r"^\s*-?\d+(\.\d+)?(\s+[A-Za-z\u00b0]|\s*%)")
# ...and the same quantity with its unit in front: `'US$12270'`, `'£50'`. The prefix has to
# carry a symbol. Allowing any short alphabetic prefix instead caught every prefixed
# identifier in the corpus -- `SN10024`, `PR1003`, `OP1005` -- and took this signal from
# 1.6% of columns to 6.3%, which is the wallpaper finding 128 warns about. A currency sign
# is a unit; a letter pair is a namespace. Any punctuation is too broad in turn: a hyphen
# separates a namespace from its number as often as it signs one, and admitting it caught
# `CR-001` and `SW-001`. The symbol has to be one that means something about the quantity.
_UNIT_FIRST = re.compile(r"^\s*[A-Za-z]{0,2}[$\u00a3\u20ac\u00a5\u00b1%~]\s?-?\d+(\.\d+)?\s*$")
_DATELIKE = re.compile(r"^\s*\d{1,4}[-/:.]\d{1,2}[-/:.]\d{1,4}")
# What a coded identifier looks like: a short alphabetic prefix and a number, one width.
_CODED = re.compile(r"^[A-Za-z]{1,4}[-_]?\d+$")
# Values that mean "no value" without being NULL. Lower-cased before the test.
_SENTINELS = {"", "-", "--", "n/a", "na", "none", "null", "nil", "unknown", "unspecified",
              "not applicable", "not available", "tbd", "?", "."}

#  The subset safe to *remove* from a value constraint, as opposed to merely report.
#
#  The rest of `_SENTINELS` is punctuation and two-letter tokens, and in real data those are
#  far more often values than nulls. Every one of these is a genuine domain member somewhere
#  in the benchmark: `na` is sodium in toxicology's periodic table of eighteen elements, `-`
#  is a single bond beside `=` and `#`, `-` is a negative result beside `+` in thrombosis's
#  coagulation tests, and `-` is "not carcinogenic" beside `+` on a molecule. Stripping them
#  would delete real values from three of eleven databases and quietly change what every
#  query over those columns counts.
#
#  What is left is unambiguous: an empty or blank string, and words of three or more letters
#  that say absence in English and nothing else.
_STRIPPABLE = {"n/a", "none", "null", "nil", "unknown", "unspecified",
               "not applicable", "not available", "tbd"}


def _is_absent(value, peers=()) -> bool:
    """Whether a value stands for NULL clearly enough to drop from a value constraint.

    `peers` are the other values the column holds. "Not available" beside "Available" is an
    answer -- no parking, no cable -- not an absence marker, and dropping it from a domain
    presented as complete was false (finding 172). A negated word whose positive form is
    among its peers is kept.
    """
    if not isinstance(value, str):
        return False
    v = " ".join(value.strip().casefold().split())
    if not (v == "" or (len(v) >= 3 and v in _STRIPPABLE)):
        return False
    if v.startswith("not "):
        positive = v[4:]
        if any(" ".join(str(p).strip().casefold().split()) == positive for p in peers):
            return False
    return True


def _dirt(conn, tables, out: Analysis) -> None:
    """Profile the values for the four ways a column lies about what it holds.

    Every other miner here proposes a *constraint* the catalogue omitted. This one proposes
    nothing: it reports what a modeller would want to know before trusting anything else,
    and the reason it exists is that one of these silently disables another miner.

        case variants    154 distinct values of `blood_compat` in LiveSQLBench's
                         organ_transplant are two values in scrambled case. The domain
                         miner's ceiling is 25 distinct, so it records no domain at all --
                         and a value domain is the one thing that tells a query author how
                         a code is spelled (findings 119, 132). A two-value enumeration,
                         invisible, with nothing reported.
        numeric text     `'104 days'`, `'57 years, mature donor'`. Correctly typed as text,
                         so nothing is wrong; but every query that wants the number has to
                         dig it out, which is work the schema could have named once.
        padding          values that differ from each other only by surrounding space are
                         the same value to a reader and different to `=`.
        sentinel nulls   `'N/A'`, `'unknown'`, `''` standing in for NULL. A mandatory role
                         inferred over these is mandatory in name only, and rule 9a mines
                         exactly that.

    Reported, never applied. What to do about dirt is the modeller's call and usually the
    source system's problem; the reverse engineer's job is to say it is there.
    """
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if not n:
            continue
        for col in t.columns:
            try:
                vals = [r[0] for r in conn.execute(
                    "SELECT %s FROM %s WHERE %s IS NOT NULL" % (_q([col.name]), _t(t.name),
                                                                _q([col.name]))).fetchall()]
            except sqlite3.Error:
                continue
            _dirt_values(t.name, col.name, n, vals, out)


def _dirt_values(table: str, column: str, n: int, vals, out: Analysis,
                 path: Optional[List[str]] = None) -> None:
    """The quality signals for one readable -- a column, or a path inside a document
    (`path`) -- over its non-null values. One function for both, so a value inside a JSON
    column is profiled exactly as a column is: finding 166's writers met `'0.30%'`,
    `'49.30 m/s'` and scrambled case inside documents, where nothing had looked."""
    def found(signals, distinct, values):
        out.findings.append(Finding("quality", table, [column], n, distinct=distinct,
                                    signals=signals, values=values, path=path))
    text = [v for v in vals if isinstance(v, str)]
    if not text:
        if len(set(vals)) == 1 and len(vals) >= MIN_ROWS:
            found(["constant"], 1, [str(vals[0])[:60]])
        return
    distinct = len(set(text))
    folded = len({v.casefold() for v in text})
    # Only worth saying when folding actually collapses the column into something
    # small enough to be an enumeration -- otherwise it is free text with mixed case.
    if folded < distinct and folded <= DOMAIN_MAX_VALUES:
        found(["case-variants"], distinct, sorted({v.casefold() for v in text})[:DOMAIN_MAX_VALUES])
    numeric = sum(1 for v in text
                  if (_NUMERIC_TEXT.match(v) or _UNIT_FIRST.match(v)) and not _DATELIKE.match(v))
    if numeric and numeric >= 0.9 * len(text):
        found(["numeric-text"], distinct, sorted(set(text))[:3])
    padded = {v for v in text if v != v.strip()}
    if padded:
        found(["padding"], len(padded), sorted(padded)[:3])
    # A column with one value across a real population is a fact type that says
    # nothing: every instance of the entity has it, and it distinguishes none of
    # them. ORM's answer is a value constraint of one value, or no fact type at all.
    # Value-based, so the SQLite copies measure it honestly. Counted over the non-null
    # values, not the rows: `constructor_results.st_mark` is null on 1,952 rows and 'D'
    # on one, and "every row holds 'D'" sent a SCALE4 writer the wrong way.
    if len(set(vals)) == 1 and len(vals) >= MIN_ROWS:
        found(["constant"], 1, [str(vals[0])[:60]])
    folded = lambda v: " ".join(v.strip().casefold().split())
    # a negated answer beside its positive form ("Not available", "Available") is a value
    sentinel = {v for v in text if folded(v) in _SENTINELS
                and not (folded(v).startswith("not ") and not _is_absent(v, text))}
    if sentinel:
        found(["sentinel-null"], sum(1 for v in text if v in sentinel), sorted(sentinel)[:4])
    formats = _date_formats(text)
    if formats:
        found(["date-formats"], len(formats), formats)
    pairs = _variant_pairs(text)
    if pairs:
        found(["variants"], len(pairs), [x for pair in pairs[:2] for x in pair])
    _more_signals(text, n, vals, found, column, path)


_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]\d{2}:\d{2}")
_VALUE_UNIT = re.compile(r"^\s*[-+]?\d[\d,]*(?:\.\d+)?\s*([A-Za-z/°%][A-Za-z/°%0-9]*)\s*$")
#  Units a name or a value may spell, to one spelling each, for telling when they disagree.
_UNIT_SPELLING = {"kmh": "km/h", "kph": "km/h", "km/h": "km/h", "mph": "mph", "ms": "m/s",
                  "mps": "m/s", "m/s": "m/s", "kg": "kg", "lb": "lb", "lbs": "lb",
                  "g": "g", "grams": "g", "km": "km", "mi": "mi", "miles": "mi",
                  "celsius": "°C", "°c": "°C", "fahrenheit": "°F", "°f": "°F"}


def _more_signals(text, n, vals, found, column, path):
    """The signals finding 172's reviews asked for: a column mostly empty, rows clustered
    several to a date, identifiers that differ only by case, and a unit in the values that
    contradicts the unit in the name."""
    nulls = n - len(vals)
    if n >= MIN_ROWS and nulls >= 0.2 * n:
        found(["sparse"], nulls, [nulls, n])
    if len(text) >= MIN_ROWS:
        stamps = [m.group(1) for m in map(_TS.match, text) if m]
        if len(stamps) >= 0.9 * len(text):
            dates = len(set(stamps))
            if len(set(stamps)) < 0.8 * len(stamps) and len(set(text)) > dates:
                found(["per-date"], dates, [len(stamps), dates])
        distinct = len(set(text))
        if distinct >= 0.95 * len(text):
            by_fold = {}
            for v in set(text):
                by_fold.setdefault(v.casefold(), []).append(v)
            clashes = [sorted(vs) for vs in by_fold.values() if len(vs) > 1]
            if clashes:
                found(["case-duplicates"], len(clashes), clashes[0][:2])
    name = (path[-1] if path else column).casefold()
    said = [w for w in re.split(r"[^a-z]+", name) if w in _UNIT_SPELLING]
    units = {m.group(1).casefold() for m in map(_VALUE_UNIT.match, text) if m}
    if said and len(units) == 1:
        vu = _UNIT_SPELLING.get(next(iter(units)))
        nu = _UNIT_SPELLING[said[-1]]
        if vu and vu != nu:
            found(["unit-conflict"], 1, [nu, vu])


# Dates as text, by shape. Finding 166: `returns.logtime` held "2024-08-13", "2024/04/16",
# "Jan 17, 2025", "April 12th, 2024" and a bare "2024" in one column, and every writer that
# sorted it as text sorted it wrong. Only a column that is mostly dates in two or more shapes
# is worth the caution; one shape sorts fine, or at least consistently.
_DATE_SHAPES = [
    ("YYYY-MM-DD", re.compile(r"^\s*\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}.*)?\s*$")),
    ("YYYY/MM/DD", re.compile(r"^\s*\d{4}/\d{1,2}/\d{1,2}\s*$")),
    ("DD/MM/YYYY or MM/DD/YYYY", re.compile(r"^\s*\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\s*$")),
    ("Month DD, YYYY", re.compile(r"^\s*[A-Za-z]{3,9}\.? \d{1,2}(st|nd|rd|th)?,? \d{4}\s*$")),
    ("DD Month YYYY", re.compile(r"^\s*\d{1,2}(st|nd|rd|th)? [A-Za-z]{3,9}\.?,? \d{4}\s*$")),
    ("YYYY alone", re.compile(r"^\s*(19|20)\d{2}\s*$")),
]


def _date_formats(text) -> List[str]:
    """An example of each date shape the values use, when most of them are dates and more
    than one shape appears at least twice; otherwise nothing."""
    seen: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    dated = 0
    for v in text:
        for name, rx in _DATE_SHAPES:
            if rx.match(v):
                dated += 1
                counts[name] = counts.get(name, 0) + 1
                seen.setdefault(name, v.strip())
                break
    shapes = [k for k, c in counts.items() if c >= 2]
    if len(shapes) < 2 or dated < 0.8 * len(text):
        return []
    return ["%s (e.g. %r)" % (k, seen[k]) for k in sorted(shapes, key=lambda k: -counts[k])]


_WORDS = re.compile(r"[a-z0-9]+")


def _variant_pairs(text) -> List[tuple]:
    """Values in a small domain that look like two spellings of one value: a bare number and
    the same number with a label (`'2'` and `'Status 2'`), or one word and a longer word it
    begins (`'own'` and `'owned'`, `'avail'` and `'available'`). Finding 166's writers each
    guessed differently at these, and the guesses decided answers. Deliberately narrow:
    `'Low'` and `'Very Low'` are two values, and nothing here pairs them."""
    values = sorted({v.strip() for v in text if v.strip()})
    if not 2 <= len(values) <= DOMAIN_MAX_VALUES:
        return []
    out = []
    for i, a in enumerate(values):
        wa = _WORDS.findall(a.casefold())
        for b in values[i + 1:]:
            wb = _WORDS.findall(b.casefold())
            if not wa or not wb or wa == wb:
                continue
            short, longer = (wa, wb) if len(" ".join(wa)) <= len(" ".join(wb)) else (wb, wa)
            pair = (a, b)
            if (len(short) == 1 and short[0].isdigit() and short[0] in longer
                    and len(longer) == 2):
                out.append(pair)
            elif (len(short) == 1 == len(longer) and len(short[0]) >= 3
                  and longer[0].startswith(short[0]) and not short[0].isdigit()):
                out.append(pair)
    return out


# -- value domains ----------------------------------------------------------------------
#
# A domain is mined from a *readable*: a catalogue column, or a path inside a document that
# rule 12 opened. The two differ only in the expression that reads them -- `"col"` against
# `json_extract("col", '$.a.b')` -- and every guard below is the same for both. Until
# finding 159 the second kind had a miner of its own, a near copy of this one that skipped
# the sentinel stripping and the ratio guard by accident, because a path is not a column of
# the catalogue and nothing column-wise ever saw it.

_JSON_BARE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _json_path_literal(steps: Sequence[str]) -> Optional[str]:
    """The JSONPath the emitter spells for these keys, or None where none can be spelled --
    `conquer/sql.py` bracket-quotes a step that is not a bare identifier and refuses a
    quote or a backslash, and the domain has to be read exactly as a query will read it."""
    steps = [str(k) for k in steps]
    if any(not k or "'" in k or '"' in k or "\\" in k for k in steps):
        return None
    return "$" + "".join(("." + k) if _JSON_BARE.match(k) else '."%s"' % k for k in steps)


def _distinct_values(conn, table: str, expr: str):
    """`(rows holding a value, distinct values, the values)` for a readable, or None when
    the population does not enumerate: fewer than two values, more than the ceiling, or
    values too long to be codes. One query to count, one to list, and the second only
    when the first says listing is worth it."""
    try:
        held, distinct = conn.execute("SELECT COUNT(%s), COUNT(DISTINCT %s) FROM %s"
                                      % (expr, expr, _t(table))).fetchone()
        if not 2 <= distinct <= DOMAIN_MAX_VALUES:
            return None
        rows = conn.execute("SELECT DISTINCT %s FROM %s WHERE %s IS NOT NULL ORDER BY 1"
                            % (expr, _t(table), expr)).fetchall()
    except sqlite3.Error:
        return None
    values = [r[0] for r in rows if r[0] is not None]
    if not values or any(len(str(v)) > DOMAIN_MAX_LENGTH for v in values):
        return None
    return held, distinct, values


def _value_domains(conn, tables, out: Analysis) -> None:
    """A column whose population holds a handful of distinct values: ORM's value constraint,
    proposed from the data.

    Identifiers and references are excluded by construction. A key's values are not a domain,
    they are the things being identified; a foreign key's are the target's keys, so the
    constraint that matters there is the inclusion dependency, not an enumeration. Anything
    the earlier algorithms have already claimed as either is skipped, declared or proposed.
    """
    referencing = {(t.name, c) for t in tables for fk in t.foreign_keys for c in fk.columns}
    referencing |= {(f.table, f.columns[0]) for f in out.of_kind("inclusion")
                    if f.preferred and len(f.columns) == 1}
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if not n:
            continue
        for col in t.columns:
            if t.is_key(col.name) or (t.name, col.name) in referencing:
                continue
            found = _distinct_values(conn, t.name, _q([col.name]))
            if found is None:
                continue
            _, distinct, values = found
            out.findings.append(Finding("value-domain", t.name, [col.name], n,
                                        distinct=distinct, values=[str(v) for v in values]))


def _document_domains(conn, model: dict, out: Analysis) -> None:
    """The same miner over the paths rule 12 opened, which are in the model's mapping and
    not in the catalogue. The population is the rows holding a value at the path: a key
    absent from most documents is judged on the documents that have it."""
    columns = {c["id"]: c for c in model["mapping"]["columns"]}
    tables = {t["id"]: t["name"] for t in model["mapping"]["tables"]}
    seen = set()
    for rm in model["mapping"]["roleMap"]:
        if len(rm["columns"]) != 1:
            continue
        col = columns.get(rm["columns"][0])
        if not col or not col.get("path") or col["id"] in seen:
            continue
        seen.add(col["id"])
        path = _json_path_literal(col["path"])
        if path is None:
            continue
        table = tables[col["table"]]
        found = _distinct_values(conn, table, "json_extract(%s, '%s')" % (_q([col["name"]]), path))
        if found is None:
            continue
        held, distinct, values = found
        out.findings.append(Finding("value-domain", table, [col["name"]], held,
                                    distinct=distinct, values=values, path=list(col["path"])))


# -- two more of ORM's constraint kinds, read off the population -----------------------
#
# The CCM carries seven constraint kinds and the derivation produced one of them. Uniqueness
# and mandatory come off the catalogue; the rest are invisible to it and visible in the data.
# Both of these are *reported*, never applied: Bird's rule holds, that a population can refute
# a constraint outright but can only ever make one plausible.

# Fewer than this and "never both filled" is arithmetic rather than evidence.
MIN_EXCLUSION_ROWS = 20


def _exclusions(conn, tables, out: Analysis) -> None:
    """Two nullable columns that are never both filled: ORM's exclusion constraint.

    This is the evidence rule 8 does not have. `flag_discriminators` reads the shape of
    subtypes flattened into one table off a column *named* `type` or `kind` beside some
    nullable columns, which is a guess about spelling; two columns that are never populated
    together is a fact about the data, and it is what makes the subtypes real. A party table
    whose `given_name` and `trading_as` never co-occur is two subtypes whatever the columns
    are called.
    """
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if n < MIN_EXCLUSION_ROWS:
            continue
        cols = [c for c in t.columns
                if c.nullable and not t.is_key(c.name) and t.fk_for(c.name) is None]
        if not 2 <= len(cols) <= 12:            # a wide sparse table is not a subtype pattern
            continue
        filled = {}
        for c in cols:
            try:
                filled[c.name] = conn.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL"
                    % (_t(t.name), _q([c.name]))).fetchone()[0]
            except sqlite3.Error:
                filled[c.name] = 0
        live = [c for c in cols if 0 < filled[c.name] < n]      # never filled says nothing
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                try:
                    both = conn.execute(
                        "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL AND %s IS NOT NULL"
                        % (_t(t.name), _q([a.name]), _q([b.name]))).fetchone()[0]
                except sqlite3.Error:
                    continue
                if both:
                    continue
                out.findings.append(Finding("exclusion", t.name, [a.name, b.name], n,
                                            distinct=filled[a.name] + filled[b.name]))


def _comparisons(conn, tables, out: Analysis) -> None:
    """One column never greater than another: ORM's value-comparison constraint.

    `start_date <= end_date` is the canonical one, and a schema states it nowhere. Only pairs
    the catalogue gives the same type are compared, and only where both are populated often
    enough for the absence of a counter-example to mean something.
    """
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if n < MIN_ROWS:
            continue
        cols = [c for c in t.columns if not t.is_key(c.name) and t.fk_for(c.name) is None
                and _comparable(c)]
        by_type = {}
        for c in cols:
            by_type.setdefault(_comparable(c), []).append(c)
        for family, group in by_type.items():
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    # Every numeric column is "never greater than" some other numeric column
                    # somewhere, and almost none of those is a constraint: on one BIRD schema
                    # the unfiltered search proposed 49, led by `Charter School (Y/N) <=
                    # District Code`. Two dates are worth asking about on their own -- a
                    # schema with two dates in a row usually means an interval. Two numbers
                    # are worth asking about only when their names say they are a pair.
                    if family != "temporal" and not _a_pair(a.name, b.name):
                        continue
                    pair = "%s IS NOT NULL AND %s IS NOT NULL" % (_q([a.name]), _q([b.name]))
                    try:
                        both, over = conn.execute(
                            "SELECT COUNT(*), SUM(CASE WHEN %s > %s THEN 1 ELSE 0 END) "
                            "FROM %s WHERE %s"
                            % (_q([a.name]), _q([b.name]), _t(t.name), pair)).fetchone()
                    except sqlite3.Error:
                        continue
                    if not both or both < MIN_ROWS:
                        continue
                    if not over:
                        out.findings.append(Finding("comparison", t.name, [a.name, b.name],
                                                    both, distinct=both))
                    elif over == both:
                        out.findings.append(Finding("comparison", t.name, [b.name, a.name],
                                                    both, distinct=both))


# The words a schema uses to mark the two ends of a range. A pair of numbers is only worth
# comparing when its names claim to be a pair.
_ENDS = [("min", "max"), ("low", "high"), ("start", "end"), ("first", "last"),
         ("from", "to"), ("lower", "upper"), ("begin", "finish"), ("open", "close")]


def _a_pair(a: str, b: str) -> bool:
    """Do these two column names name the ends of one range? `min_score`/`max_score`, and the
    same stem either side."""
    la, lb = a.casefold(), b.casefold()
    for lo, hi in _ENDS:
        for x, y in ((la, lb), (lb, la)):
            if lo in x and hi in y and x.replace(lo, "", 1) == y.replace(hi, "", 1):
                return True
    return False


def _comparable(column) -> Optional[str]:
    """The family a column can be ordered within, or None. Comparing a price with a date is
    arithmetic that happens to run, not a constraint worth proposing."""
    kind = (column.data_type or "").casefold()
    if any(k in kind for k in ("date", "time")):
        return "temporal"
    if any(k in kind for k in ("int", "real", "double", "float", "numeric", "decimal")):
        return "numeric"
    return None


# How many candidate formulas may be asked of one table. The search is quadratic in the
# comparable columns and most tables have none that fit, so this bounds the worst case rather
# than the common one.
MAX_FORMULA_QUERIES = 120


def _computed(conn, tables, out: Analysis) -> None:
    """A column whose value is a formula over other columns of the same row.

    `total = quantity * price`, `full_name = given || ' ' || family`. ORM's answer to a stored
    computation is a *derivation rule*: the fact is derived, not asserted, and a model that
    says so tells a query author where the number comes from and stops two columns drifting
    apart. Nothing in the catalogue records it.

    This is the rule that attacks what the benchmark measured. Definitions written down are
    worth eight points to a query writer (bench/pilot/README.md, the semantic-layer round); a
    derived column is a definition the database already contains and the schema forgets to
    mention.
    """
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if n < MIN_ROWS:
            continue
        nums = [c for c in t.columns
                if not t.is_key(c.name) and t.fk_for(c.name) is None
                and _comparable(c) == "numeric"]
        texts = [c for c in t.columns
                 if not t.is_key(c.name) and t.fk_for(c.name) is None
                 and any(k in (c.data_type or "").casefold()
                         for k in ("char", "text", "clob", "string"))]
        asked = 0
        for target in nums:
            others = [c for c in nums if c.name != target.name]
            for i, a in enumerate(others):
                for b in others[i + 1:]:
                    for op in ("*", "+", "-"):
                        if asked >= MAX_FORMULA_QUERIES:
                            break
                        asked += 1
                        if _holds(conn, t, target.name,
                                  "%s %s %s" % (_q([a.name]), op, _q([b.name])), True):
                            out.findings.append(Finding(
                                "computed", t.name, [target.name, a.name, b.name], n,
                                values=["%s %s %s" % (a.name, op, b.name)]))
        for target in texts:
            others = [c for c in texts if c.name != target.name]
            for i, a in enumerate(others):
                for b in others:
                    if a.name == b.name or asked >= MAX_FORMULA_QUERIES:
                        continue
                    for sep in ("' '", "''"):
                        asked += 1
                        expr = "%s || %s || %s" % (_q([a.name]), sep, _q([b.name]))
                        if _holds(conn, t, target.name, expr, False):
                            out.findings.append(Finding(
                                "computed", t.name, [target.name, a.name, b.name], n,
                                values=["%s || %s || %s" % (a.name, sep, b.name)]))
                            break


# Checked on this many rows first. A formula that is going to fail fails almost at once, and
# the full scan is only worth paying for a candidate that survives: card_games' `foreign_data`
# is 229,186 rows and the unsampled search took 108 seconds on one database.
FORMULA_SAMPLE = 500


def _holds(conn, table, target: str, expr: str, numeric: bool) -> bool:
    """Is `target` equal to `expr` in every row where both are present?

    `numeric` picks the comparison, and it has to be told rather than discovered: SQLite
    coerces text to 0 in arithmetic, so `ABS('G1' - ('F1' || ' ' || 'G1 F1'))` is 0 and every
    concatenation of anything looked like an identity. Sixty-seven of them on one schema.
    """
    test = ("ABS(%s - (%s)) > 1e-9" if numeric else "%s <> (%s)") % (_q([target]), expr)
    where = "%s IS NOT NULL AND (%s) IS NOT NULL" % (_q([target]), expr)
    def ask(src):
        try:
            return conn.execute("SELECT COUNT(*), SUM(CASE WHEN %s THEN 1 ELSE 0 END) FROM %s "
                                "WHERE %s" % (test, src, where)).fetchone()
        except sqlite3.Error:
            return None
    got = ask("(SELECT * FROM %s LIMIT %d)" % (_t(table.name), FORMULA_SAMPLE))
    if not got or not got[0] or got[1]:
        return False
    rows, bad = ask(_t(table.name)) or (0, 1)
    return bool(rows) and rows >= MIN_ROWS and not bad


def _rings(conn, tables, out: Analysis) -> None:
    """What a self-reference cannot do: point at itself, or go round.

    ORM calls these ring constraints, and a `manager_nr` that references its own table has one
    or it does not -- a reporting line is irreflexive and acyclic, a marriage is symmetric.
    The catalogue says only that the column is a foreign key.
    """
    for t in tables:
        for fk in t.foreign_keys:
            if fk.ref_table.casefold() != t.name.casefold() or len(fk.columns) != 1:
                continue
            col, key = fk.columns[0], (fk.ref_columns or t.primary_key or [None])[0]
            if not key:
                continue
            n = out.row_counts.get(t.name, 0)
            if n < MIN_ROWS:
                continue
            try:
                loops = conn.execute("SELECT COUNT(*) FROM %s WHERE %s = %s"
                                     % (_t(t.name), _q([col]), _q([key]))).fetchone()[0]
            except sqlite3.Error:
                continue
            if loops:
                continue
            kinds = ["irreflexive"]
            try:
                # the transitive closure of the reference, asked whether anything reaches
                # itself. UNION rather than UNION ALL, so a cycle terminates the recursion
                # instead of running forever.
                cyclic = conn.execute(
                    "WITH RECURSIVE r(a, b) AS ("
                    " SELECT %(k)s, %(c)s FROM %(t)s WHERE %(c)s IS NOT NULL"
                    " UNION SELECT r.a, t.%(c)s FROM r JOIN %(t)s AS t ON t.%(k)s = r.b"
                    " WHERE t.%(c)s IS NOT NULL) SELECT COUNT(*) FROM r WHERE a = b"
                    % {"k": _q([key]), "c": _q([col]), "t": _t(t.name)}).fetchone()[0]
            except sqlite3.Error:
                cyclic = 1
            if not cyclic:
                kinds.append("acyclic")
            out.findings.append(Finding("ring", t.name, [col], n, values=kinds))


def _equalities(conn, tables, out: Analysis) -> None:
    """Two nullable columns always absent together and present together: ORM's **equality**
    constraint, and the mirror of `_exclusions`.

    `reviewed_by` without `reviewed_at` is a half-recorded fact. Stating it makes the two one
    fact type with a composite role rather than two independent optional ones, which is the
    difference between "may be unreviewed" and "may be half reviewed".
    """
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if n < MIN_EXCLUSION_ROWS:
            continue
        cols = [c for c in t.columns
                if c.nullable and not t.is_key(c.name) and t.fk_for(c.name) is None]
        if not 2 <= len(cols) <= 12:
            continue
        filled = {}
        for c in cols:
            try:
                filled[c.name] = conn.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL"
                    % (_t(t.name), _q([c.name]))).fetchone()[0]
            except sqlite3.Error:
                filled[c.name] = 0
        live = [c for c in cols if 0 < filled[c.name] < n]   # always or never filled says nothing
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if filled[a.name] != filled[b.name]:
                    continue                                  # cheap: a count settles most
                try:
                    apart = conn.execute(
                        "SELECT COUNT(*) FROM %s WHERE (%s IS NULL) <> (%s IS NULL)"
                        % (_t(t.name), _q([a.name]), _q([b.name]))).fetchone()[0]
                except sqlite3.Error:
                    continue
                if not apart:
                    out.findings.append(Finding("equality", t.name, [a.name, b.name], n,
                                                distinct=filled[a.name]))


# A functional dependency search is quadratic in the columns and most pairs are refuted by the
# first group that has two values, so the budget is about the width of the table rather than
# the size of it.
MAX_FD_QUERIES = 200
# A dependency has to rest on repetition: this many distinct values of the determinant, each
# seen this many times on average. Below either, "a determines b" is arithmetic about how few
# rows there are rather than a claim about the business.
MIN_FD_GROUPS = 5
MIN_FD_REPEATS = 3


def _dependencies(conn, tables, out: Analysis) -> None:
    """A column determined by a **non-key** column: a fact about that column's concept rather
    than about this table's.

    `zip -> city` in an address table says City is a fact about Zip, and rule 2 will otherwise
    hang both off Address as independent properties -- which is how a denormalised table turns
    into a conceptual schema that says the wrong thing. Bird's Step 9 mines uniqueness this
    way; this is the same search one step weaker, and it is the one that finds entity types
    nobody declared.

    Only single-column determinants, only where the determinant repeats (a unique column
    determines everything and says nothing), and only where the dependent is not part of the
    key.
    """
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if n < MIN_ROWS:
            continue
        cols = [c for c in t.columns if not t.is_key(c.name) and t.fk_for(c.name) is None]
        if not 2 <= len(cols) <= 20:
            continue
        card = _cardinalities(conn, t, cols)
        asked = 0
        for a in cols:
            ca = card.get(a.name, 0)
            if ca >= n or ca < 2:
                continue                    # unique determines everything; constant nothing
            for b in cols:
                if a.name == b.name or asked >= MAX_FD_QUERIES:
                    continue
                cb = card.get(b.name, 0)
                if cb < 2 or cb > ca:
                    continue                # |b| > |a| refutes a -> b without a query
                asked += 1
                try:
                    # groups, groups with two values, and the rows behind them -- all on the
                    # subset where both columns are present, which is the only population the
                    # claim is about.
                    groups, broken, rows = conn.execute(
                        "SELECT COUNT(*), SUM(CASE WHEN d > 1 THEN 1 ELSE 0 END), SUM(k) "
                        "FROM (SELECT COUNT(DISTINCT %s) AS d, COUNT(*) AS k FROM %s "
                        "WHERE %s IS NOT NULL AND %s IS NOT NULL GROUP BY %s)"
                        % (_q([b.name]), _t(t.name), _q([a.name]), _q([b.name]),
                           _q([a.name]))).fetchone()
                except sqlite3.Error:
                    continue
                # A determinant that barely repeats determines everything and says nothing:
                # `note -> reviewed_by` holds whenever notes are near-unique. The cardinality
                # guard above counts distinct values over the whole column, which is the wrong
                # population when either column is mostly null.
                if broken or not rows or rows < MIN_ROWS:
                    continue
                # Two more guards, both about how much repetition the claim rests on. A
                # determinant with a handful of groups is nearly vacuous, and one whose groups
                # average a row or two apiece is a near-unique column determining everything:
                # `budget.remaining -> category` held on 52 rows for no reason but that
                # remaining is a decimal.
                if groups < MIN_FD_GROUPS or rows < groups * MIN_FD_REPEATS:
                    continue
                out.findings.append(Finding("dependency", t.name, [a.name, b.name], rows,
                                            distinct=groups))


# One query per (parent column, child column) pair on each foreign key, so a wide pair of
# tables is the expensive case rather than a deep one.
MAX_AGGREGATE_QUERIES = 80


def _aggregates(conn, tables, out: Analysis) -> None:
    """A parent column that is an aggregate of a child table: `order.total = SUM(line.amount)`,
    `customer.orders = COUNT(*)`.

    A stored aggregate is a derivation rule with the derivation thrown away, and it is the
    column most likely in any schema to be quietly stale. Rule 9f finds a formula inside one
    row; this finds one across a foreign key, which is the commoner shape and the one that
    carries a definition -- the artefact the benchmark measured as worth eight points.
    """
    by_name = {t.name.casefold(): t for t in tables}
    for child in tables:
        for fk in child.foreign_keys:
            parent = by_name.get(fk.ref_table.casefold())
            if parent is None or len(fk.columns) != 1 or parent.name == child.name:
                continue
            key = (fk.ref_columns or parent.primary_key or [None])[0]
            if not key or out.row_counts.get(parent.name, 0) < MIN_ROWS:
                continue
            nums = [c for c in parent.columns
                    if not parent.is_key(c.name) and parent.fk_for(c.name) is None
                    and _comparable(c) == "numeric"]
            kids = [c for c in child.columns
                    if not child.is_key(c.name) and child.fk_for(c.name) is None
                    and _comparable(c) == "numeric"]
            asked = 0
            for p in nums:
                for expr, label in ([("COUNT(*)", "COUNT(*)")]
                                    + [("SUM(c.%s)" % _q([k.name]), "SUM(%s)" % k.name)
                                       for k in kids]):
                    if asked >= MAX_AGGREGATE_QUERIES:
                        break
                    asked += 1
                    if _matches_aggregate(conn, parent, child, key, fk.columns[0], p.name, expr):
                        out.findings.append(Finding(
                            "aggregate", parent.name, [p.name], out.row_counts[parent.name],
                            target_table=child.name, target_columns=[fk.columns[0]],
                            values=["%s over %s" % (label, child.name)]))


def _matches_aggregate(conn, parent, child, key, ref, col, expr) -> bool:
    """Does `parent.col` equal `expr` over the child rows that point at it, for every parent
    row that has any? Parents with no children are left out: a stored 0 and a NULL both read
    as "none" and neither refutes the definition."""
    sql = ("SELECT COUNT(*), SUM(CASE WHEN ABS(p.%(col)s - a.v) > 1e-9 THEN 1 ELSE 0 END) "
           "FROM %(parent)s AS p JOIN (SELECT c.%(ref)s AS k, %(expr)s AS v FROM %(child)s "
           "AS c WHERE c.%(ref)s IS NOT NULL GROUP BY c.%(ref)s) AS a ON a.k = p.%(key)s "
           "WHERE p.%(col)s IS NOT NULL"
           % {"col": _q([col]), "parent": _t(parent.name), "child": _t(child.name),
              "ref": _q([ref]), "key": _q([key]), "expr": expr})
    try:
        rows, bad = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return False
    return bool(rows) and rows >= MIN_ROWS and not bad


# -- warehouse shapes -------------------------------------------------------------------

# A junk dimension's columns are flags and codes: a handful of values each, and a handful of
# columns. The upper bound on columns is what separates it from a wide dimension -- 199
# low-cardinality attributes is a denormalised customer table, not a bundle of leftovers, and
# `rows <= product` is vacuously true once the product has 199 factors.
JUNK_MAX_DISTINCT = 12
JUNK_MIN_COLUMNS = 3
JUNK_MAX_COLUMNS = 12
JUNK_MAX_ROWS = 1000


def _junk_dimensions(conn, tables, out: Analysis) -> None:
    """A table that is a bundle of unrelated flags behind a surrogate key.

    Kimball's junk dimension: the low-cardinality leftovers of a fact row -- is_gift, channel,
    payment_type -- collected into one table so the fact has one key instead of five. It is a
    storage device, and reverse engineering turns it into an entity type, which asserts that
    the business has a concept called OrderJunkDim. It does not. The flags are attributes of
    the *fact*, and the surrogate key identifies a combination rather than a thing.

    The catalogue cannot see this: the shape is an ordinary table with a surrogate primary key.
    The data can, because every non-key column has a handful of distinct values and the row
    count is near their product -- it enumerates combinations rather than describing entities.
    """
    for t in tables:
        if len(t.primary_key) != 1 or t.foreign_keys:
            continue
        rows = out.row_counts.get(t.name, 0)
        others = [c for c in t.columns if not t.is_key(c.name)]
        if rows < 2 or not (JUNK_MIN_COLUMNS <= len(others) <= JUNK_MAX_COLUMNS):
            continue
        if rows > JUNK_MAX_ROWS:
            continue
        product, cards = 1, []
        for c in others:
            d = _distinct(conn, t, c.name)
            if d == 0 or d > JUNK_MAX_DISTINCT:
                product = 0
                break
            cards.append(d)
            product *= d
        if not product or not cards:
            continue
        # Every column is low-cardinality, and there are no more rows than combinations of
        # them. A real dimension describes entities and outgrows its own attribute space.
        if rows <= product:
            out.findings.append(Finding("junk", t.name, [c.name for c in others],
                                        rows, max(cards)))


# -- the refutation direction -----------------------------------------------------------

def _violations(conn, tables, out: Analysis) -> None:
    """Declared foreign keys the data does not satisfy.

    The one direction in which data is conclusive. Everything else here proposes a constraint
    the catalogue omitted, and can only ever be plausible; this *refutes* one the catalogue
    asserts, and a counter-example is proof. Bird makes the point herself:

        "identifying constraints which hold in the Universe of Discourse but are contradicted
        by the existing data is of great value when the quality of the existing system is
        being assessed."

    It is not rare. Across a 90-database Spider sample, 33 of 118 declared single-column
    foreign keys -- 28% -- are violated by the data they constrain, which is also the ceiling
    on what any data-based method can rediscover.
    """
    for t in tables:
        for fk in t.foreign_keys:
            if len(fk.columns) != 1:
                continue
            try:
                orphans = conn.execute(
                    'SELECT COUNT(*) FROM (SELECT DISTINCT %s FROM %s WHERE %s IS NOT NULL '
                    'EXCEPT SELECT %s FROM %s)'
                    % (_q(fk.columns), _t(t.name), _q(fk.columns),
                       _q(fk.ref_columns), _t(fk.ref_table))).fetchone()[0]
            except sqlite3.Error:
                continue
            # `distinct` carries the orphan count for a violation, which is what makes its
            # evidence line read. A clean answer has none, and "0 distinct values" would be
            # a lie about a different quantity, so it is left unset.
            out.findings.append(Finding(
                "violated" if orphans else "satisfied", t.name, list(fk.columns),
                out.row_counts.get(t.name, 0), orphans or None,
                target_table=fk.ref_table, target_columns=list(fk.ref_columns)))


def apply_enforced(analysis: Analysis, model: dict, report) -> List[tuple]:
    """Record, on the roles that carry them, which declared references the data upholds.

    `_violations` already runs the query that settles it, and until now threw away every
    answer that came back clean. The clean answer is worth as much as the dirty one, to a
    different reader: a compiler. A path step across a reference emits a join, and the join
    does two things -- it fetches the far row, and it drops the near row when no far row is
    there. Where the reference holds over every row the second is dead weight, and where the
    step only wants a value the near side already holds (`Employee has Department has
    DepartmentCode` -- the code IS the column the employee points with) the first is too.
    That is the join elimination Malloy does by construction; what ORM adds is a reason to
    believe it, written in the model rather than assumed by the optimiser.

    Deliberately narrow: single-column keys, because that is what `_violations` tests.

    Not gated on `significant`, which every other population rule here is, and the reason is
    that this one is not inferring a constraint. Rules 9a to 9d propose something the
    catalogue never said, so a handful of rows agreeing is coincidence; here the catalogue
    has already declared the foreign key and the data is only being asked whether it agrees.
    What the compiler needs is that no row in *this* database dangles, and a clean answer
    over six rows says that as completely as a clean answer over six million. An empty
    population says nothing, so one row is the floor.

    This is still a claim about today's rows, like rule 9a's. One insert of a dangling value
    refutes it, and then the compiler quietly keeps rows the join would have dropped -- so
    it is applied on request, reported, and never assumed.
    """
    mapping = model.get("mapping") or {}
    tname = {t["id"]: t["name"].casefold() for t in mapping.get("tables", [])}
    cname = {c["id"]: c["name"].casefold() for c in mapping.get("columns", [])}
    table_of = {m["concept"]: m["table"] for m in mapping.get("conceptMap", [])}
    player = {r["id"]: r["player"]
              for c in model.get("concepts", []) for r in c.get("roles", [])}
    held = {}
    for f in analysis.of_kind("satisfied"):
        if f.rows:
            held[(f.table.casefold(), tuple(c.casefold() for c in f.columns))] = (
                f.target_table.casefold(),
                "%d row%s, none of them dangling" % (f.rows, "" if f.rows == 1 else "s"))

    applied = []
    for entry in mapping.get("roleMap", []):
        key = (tname.get(entry["table"]),
               tuple(cname.get(c) for c in entry["columns"]))
        if key not in held:
            continue
        target, evidence = held[key]
        # The role has to face the table the foreign key points at. A key column that is
        # also the entity's own identifier is mapped by two roles -- the one reaching the
        # target and the one reaching the entity itself -- and only the first is a reference.
        reached = table_of.get(player.get(entry["role"], ""))
        if reached is None or tname.get(reached) != target:
            continue
        entry["enforced"] = True
        applied.append((key[0], ", ".join(key[1]), target, evidence))

    for table, cols, target, evidence in applied:
        report.refine("enforced references", "population",
                      "%s.%s -> %s" % (table, cols, target),
                      "The foreign key is declared AND no row breaks it (%s), so a path "
                      "across it can read the referenced value from the column in hand and "
                      "skip the join that would fetch it back. Applied because "
                      "--infer-enforced asked for it. A declared key is not enough on its "
                      "own: 28%% of the declared single-column foreign keys in a 90-database "
                      "Spider sample are contradicted by their own rows." % evidence,
                      "Confirm the constraint is actually enforced, not merely unbroken so "
                      "far. One dangling value inserted later and queries silently keep "
                      "rows the join used to drop.")
    return applied


# -- 3.9-a: a column declared nullable that never is ------------------------------------

def _alternate_keys(conn, tables, out: Analysis) -> None:
    """A second identifier on a table that already has one.

    `_unique` searches only keyless tables -- once rule 9b has a key it stops looking, which
    is right for *choosing* an identifier and wrong for describing the type. ORM has no such
    limit: a uniqueness constraint on a value role says that value identifies the object, and
    an entity type may have several.

    It costs an answer. LiveSQLBench's `core_record` carries `coreregistry` (the declared
    key, which five tables reference) and `clientref` (1000 distinct over 1000 rows,
    referenced by nothing). Both are identifiers; only one was modelled as one, so the model
    stated exactly the same thing about `clientref` as about `appref`, which is not unique at
    all. Asked for "the customer ID", a writer took `clientref` -- the *client* reference --
    and the gold meant `coreregistry`. Three of twelve questions turned on that, and nothing
    in the schema listing said there were two to choose between (finding 151).

    Single columns only, never null, and never the key itself: a composite alternate key is
    rarer, riskier to propose, and not what an author is choosing between.
    """
    never_null: Dict[str, set] = {}
    for f in out.of_kind("never-null"):
        never_null.setdefault(f.table, set()).add(f.columns[0].casefold())
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if t.is_view or n < MIN_ROWS or not t.primary_key:
            continue
        key = {c.casefold() for c in t.primary_key}
        for col in t.columns:
            name = col.name.casefold()
            if name in key:
                continue
            if col.nullable and name not in never_null.get(t.name, set()):
                continue
            try:
                d = conn.execute('SELECT COUNT(DISTINCT %s) FROM %s'
                                 % (_q([col.name]), _t(t.name))).fetchone()[0]
            except sqlite3.Error:
                continue
            if d != n:
                continue
            # Unique is not identifying. Of 323 unique non-key columns across the 18
            # LiveSQLBench SQLite databases, 274 are measurements that happen not to repeat
            # -- frequencies, distances, vertex counts, loan amounts -- and proposing those
            # as identifiers is the wallpaper finding 128 warns about, at 14% of all columns.
            # What is left is what a coded identifier looks like: text, one width, a short
            # alphabetic prefix and a number. 49 columns, 2.2%, and every one of them reads
            # as an identifier (`CU338528`, `ACC7210284`, `ART54317`).
            try:
                vals = [r[0] for r in conn.execute(
                    "SELECT %s FROM %s LIMIT 300" % (_q([col.name]), _t(t.name)))]
            except sqlite3.Error:
                continue
            if not vals or not all(isinstance(v, str) for v in vals):
                continue
            if len({len(v) for v in vals}) != 1 or any(_DATELIKE.match(v) for v in vals):
                continue
            if not all(_CODED.match(v) for v in vals):
                continue
            out.findings.append(Finding("alternate-key", t.name, [col.name], n, distinct=d))


def _never_null(conn, tables, out: Analysis) -> None:
    """Bird's Algorithm 3.9-a, inverted.

    Hers classifies a role as optional when its population contains a null, which the
    catalogue already tells us. The useful direction here is the other one: a column the
    catalogue permits to be null but which never is, so the role may really be mandatory. That
    is a *candidate*, not a fact -- an insert tomorrow can refute it, which is exactly why it
    is a finding rather than a constraint.
    """
    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if not n:
            continue
        for col in t.columns:
            if not col.nullable or t.is_key(col.name):
                continue
            try:
                nulls = conn.execute("SELECT COUNT(*) FROM %s WHERE %s IS NULL"
                                     % (_t(t.name), _q([col.name]))).fetchone()[0]
            except sqlite3.Error:
                continue
            if nulls == 0:
                out.findings.append(Finding("never-null", t.name, [col.name], n))


# -- 3.9-b: unique column combinations --------------------------------------------------

def _unique(conn, tables, out: Analysis) -> None:
    """Bird's Algorithm 3.9-b: the minimal unique column combinations of a keyless table.

    Hers assumes every role unique and weakens the assumption against each pair of rows --
    O(|Pop|^2 x |Roles|^2), the shape TANE and its successors exist to improve on. The modern
    form of the same question is UCC discovery (Papenbrock & Naumann's HyUCC and DUCC), and a
    primary key is one of the UCCs a table has; Jiang & Naumann's HoPF is built on exactly
    that observation.

    This is the standard level-wise search, bounded three ways so it stays a handful of
    queries rather than a research problem:

      * only keyless tables, and within them only columns that are never null, because an
        identifier cannot be absent;
      * **the cardinality product**, which is a sound prune: a combination whose column
        cardinalities multiply to less than the row count cannot possibly be unique, so it
        is skipped without asking the database;
      * arity and query caps, because the useful keys are small and the search is not.

    Only *minimal* combinations are recorded: a superset of a unique combination is unique
    and says nothing further. That matters for what follows, because the thing that makes a
    key a key is being the smallest such set.
    """
    never_null_by_table: Dict[str, set] = {}
    for f in out.of_kind("never-null"):
        never_null_by_table.setdefault(f.table, set()).add(f.columns[0].casefold())
    for t in tables:
        if t.primary_key or t.is_view:
            continue
        n = out.row_counts.get(t.name, 0)
        if not n:
            continue
        never_null = never_null_by_table.get(t.name, set())
        usable = [c for c in t.columns
                  if not c.nullable or c.name.casefold() in never_null]
        card = _cardinalities(conn, t, usable)
        if not card:
            continue

        minimal: List[Tuple[str, ...]] = [(c,) for c in card if card[c] == n]
        rest = sorted((c for c in card if card[c] < n), key=lambda c: -card[c])
        # The cardinality prune below skips a combination without asking the database, but it
        # still has to *reach* it: a 128-column table of low-cardinality columns enumerated
        # 288,000 tuples to issue no query at all. A column that cannot reach the row count
        # even beside the largest cardinalities in the table is in no unique combination of
        # this arity, so drop it before the enumeration rather than inside it.
        ceiling = 1
        for v in sorted(card[c] for c in rest)[-(MAX_KEY_ARITY - 1):]:
            ceiling *= v
        rest = [c for c in rest if card[c] * ceiling >= n]
        asked = 0
        for k in range(2, MAX_KEY_ARITY + 1):
            if asked >= MAX_KEY_QUERIES or len(rest) < k:
                break
            for combo in itertools.combinations(rest, k):
                if asked >= MAX_KEY_QUERIES:
                    break
                if any(set(m) <= set(combo) for m in minimal):
                    continue                       # a superset of a key is not a key
                product = 1
                for c in combo:
                    product *= card[c]
                    if product >= n:
                        break
                if product < n:
                    continue                       # cannot be unique, whatever the data says
                asked += 1
                if _distinct_rows(conn, t, combo) == n:
                    minimal.append(combo)

        order = {c.name: i for i, c in enumerate(t.columns)}
        for cols in minimal[:MAX_KEYS_REPORTED]:
            # in table order, not the order the search happened to try them in: a composite
            # key reads as the schema writes it, and the search sorts by cardinality
            out.findings.append(Finding("unique", t.name,
                                        sorted(cols, key=lambda c: order.get(c, 0)), n, n))


# A key people write is short. Three columns covers every composite in the benchmark
# schemas, and the search is exponential in this number.
MAX_KEY_ARITY = 3
# How many combinations may be *asked of the database* per table. The cardinality prune
# removes most candidates for free; this bounds what is left on a hundred-column table.
MAX_KEY_QUERIES = 120
# Beyond a handful, extra unique combinations are noise in the report and add nothing to
# the choice.
MAX_KEYS_REPORTED = 8


def _cardinalities(conn, table, columns) -> Dict[str, int]:
    """COUNT(DISTINCT) for every column, in one pass rather than one pass per column."""
    cols = [c.name for c in columns]
    if not cols:
        return {}
    try:
        row = conn.execute("SELECT %s FROM %s" % (
            ", ".join("COUNT(DISTINCT %s)" % _q([str(c)]) for c in cols),
            _t(table.name))).fetchone()
    except sqlite3.Error:
        return {}
    return dict(zip(cols, row))


def _distinct_rows(conn, table, cols) -> int:
    """How many distinct combinations of `cols` the table holds. Named apart from `_distinct`,
    which counts one column's values and is what the inclusion scoring asks for."""
    try:
        return conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT %s FROM %s)"
                            % (_q(list(cols)), _t(table.name))).fetchone()[0]
    except sqlite3.Error:
        return -1


def _looks_like_a_reference(column: str) -> bool:
    """Is this column *spelled* like an identifier? `id` on its own counts -- it is the
    commonest primary key name there is, and requiring something before the suffix meant a
    column called exactly `id` scored nothing at all (WWE, six tables)."""
    from derive import KEY_SUFFIXES              # one vocabulary, defined where naming lives
    low = column.casefold()
    return (low in _BARE_KEY_NAMES
            or any(low.startswith(p) for p in _KEY_PREFIXES)
            or any(low.endswith(sfx) and len(low) > len(sfx) for sfx in KEY_SUFFIXES))


# `id_bioguide`, `id_govtrack`: the same convention written the other way round.
_KEY_PREFIXES = ("id_", "pk_")


_BARE_KEY_NAMES = {"id", "key", "pk"}


# -- 3.9-g: subset constraints, i.e. candidate foreign keys -----------------------------

def _inclusions(conn, tables, out: Analysis, include_declared: bool = False,
                weights=None, threshold=None, also_unique=None) -> None:
    """Bird's Algorithm 3.9-g, narrowed to the case that recovers relationships.

    A subset constraint says one role's population is contained in another's. When the
    containing role is a key, that is the evidence for a foreign key the catalogue never
    declared -- and an undeclared foreign key is the single thing that turns a list of tables
    into a conceptual schema.

    Only columns that are not already part of a declared foreign key are considered, and only
    against a key of matching arity in another table. The test is `EXCEPT`: every non-null
    value on the left must appear on the right.
    """
    weights = weights or WEIGHTS
    threshold = THRESHOLD if threshold is None else threshold
    vcache: Dict[Tuple[str, str], object] = {}
    targets: List[Tuple[object, List[str]]] = []
    by_name = {t.name: t for t in tables}
    for t in tables:
        for key in ([t.primary_key] if t.primary_key else []) + list(t.uniques):
            # A table that declares its primary key as a unique constraint too offers the
            # same target twice, and every containment against it was tested and recorded
            # twice -- harmless, since callers deduplicate, but it doubles the EXCEPT
            # queries, which are the expensive part of this pass.
            if key and (t.name, tuple(key)) not in {(x.name, tuple(k)) for x, k in targets}:
                targets.append((t, list(key)))
    # A reference points at *a* key, not at the one chosen to be primary. On a schema that
    # declares nothing, rule 9b picks one identifier per table and every other unique column
    # becomes invisible as a target -- which is where the largest single share of the missed
    # references went: 29 of the 49 BIRD misses were contained in a column the search never
    # offered, `rulings.uuid -> cards` among them, because `cards` had been keyed on `id`.
    seen = {(t.name, tuple(k)) for t, k in targets}
    for f in list(out.of_kind("unique")) + list(also_unique or []):
        t = by_name.get(f.table)
        if t is None or len(f.columns) != 1 or (f.table, tuple(f.columns)) in seen:
            continue
        seen.add((f.table, tuple(f.columns)))
        targets.append((t, list(f.columns)))

    for t in tables:
        n = out.row_counts.get(t.name, 0)
        if not n:
            continue
        declared = set() if include_declared else {
            c.casefold() for fk in t.foreign_keys for c in fk.columns}
        for col in t.columns:
            if col.name.casefold() in declared:
                continue
            for target, key in targets:
                if len(key) != 1 or target.name.casefold() == t.name.casefold():
                    continue
                if not out.row_counts.get(target.name):
                    continue
                found = _contained(conn, t, [col.name], target, key)
                if found is None:
                    continue
                parent = _distinct(conn, target, key[0])
                spread = _spread(conn, t.name, col.name, target.name, key[0], vcache)
                score, signals = _rank(t, col, target, key[0], found, parent, spread, weights)
                # The name evidence, kept whatever the weights: under `ignore_names` it is
                # scored at zero, because finding 84 measured a name *rule* at 3% recall on
                # schemas that do not name their references after their targets. But as a
                # tie-break among containments the data has already proven, it is worth
                # +134 references on the 18 LiveSQLBench schemas -- 74% recall to 86%, at
                # better precision, with no extra candidates (finding 120). Names are
                # decisive for choosing between targets and useless for finding them.
                name_score = max(_similar(col.name, target.name),
                                 _similar(col.name, _stem(target.name)),
                                 1.0 if _stem(target.name) in col.name.casefold() else 0.0,
                                 _similar(col.name, key[0]))
                # A column that identifies its OWN table is a weaker signal, because two
                # independent surrogate sequences nest whenever one is shorter: `Album.AlbumId`
                # is "contained in" `Invoice.InvoiceId` for no reason but that there are fewer
                # albums than invoices. It is not noise either -- a primary key that really
                # does reference another table is the 1:1 subtype shape, which is how
                # `frpm.CDSCode` relates to `schools.CDSCode`. So it is kept and separated,
                # rather than dropped with the noise or mixed in with the evidence.
                own_key = [c.casefold() for c in t.primary_key] == [col.name.casefold()]
                out.findings.append(Finding(
                    "inclusion-1to1" if own_key else "inclusion",
                    t.name, [col.name], n, found,
                    target_table=target.name, target_columns=list(key),
                    score=score, name_score=name_score, signals=signals))

    # Motl & Kordík gain as much from resolving the assignment globally as from any single
    # feature, and the reason is visible in the raw output: one column is "contained in" eight
    # different keys and references at most one of them. Keep the best-scoring target for each
    # column as the proposal; the rest stay in the analysis but are summarised, not listed.
    ranked: Dict[Tuple[str, str], List[Finding]] = {}
    for f in out.findings:
        if not f.kind.startswith("inclusion"):
            continue
        ranked.setdefault((f.table.casefold(), f.columns[0].casefold()), []).append(f)
    for group in ranked.values():
        # A column references one table, and which one is settled by the name where the name
        # says anything: the highest name evidence first, the score breaking its ties. This
        # is the assignment step Motl & Kordik gain as much from as from any single feature,
        # and finding 120 measured it: the containment search already finds the right target
        # for 96% of references, and the score alone puts it first for 74%.
        for f in sorted(group, key=lambda f: (-f.name_score, -f.score))[:TOPK]:
            f.preferred = f.score >= threshold


# Weights and threshold for _rank. Both were fitted on half of a 90-database Spider sample
# and scored on the other half, where they took inclusion-dependency F1 from 0.31 to 0.72
# (89% precision, 61% recall). They are not sacred; they are what measured best, and
# `reverse/tests/test_population.py` pins the behaviour rather than the numbers.
#
# The shape agrees with the published work. Rostin et al. (2009) rank inclusion dependencies
# by ten heuristics; Zhang et al. (2010) show a value-distribution feature subsumes most of
# them *except* column names; Motl & Kordík measure name features as the three strongest and
# containment itself as the WEAKEST, and gain as much again from a global assignment step as
# from any feature. That last point is why `preferred` exists.
WEIGHTS = {"not_own_key": 1.0, "name_pk_table": 2.0, "name_pk_col": 1.0,
           "name_not_own": 1.0, "type_agree": 0.5, "coverage": 0.5, "spread": 1.5}
THRESHOLD = 4.25

# The same model with every name signal removed. Bird's own case study is the reason it
# exists: her schema names references for the concept and keys for the identifier, so
# `Rating.paper` faces `Paper.number` and no amount of string comparison helps. Measured at
# F1 0.73 on the Spider sample -- better than the *named* model was before `spread` was added.
SHAPE_ONLY = {"not_own_key": 1.0, "coverage": 1.0, "spread": 2.0, "type_agree": 0.5}
SHAPE_ONLY_THRESHOLD = 2.6

_KEY_WORDS = ("id", "code", "no", "nr", "num", "key", "ref")


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _similar(a: str, b: str) -> float:
    a, b = a.casefold(), b.casefold()
    if not a or not b:
        return 0.0
    return 1.0 - _levenshtein(a, b) / max(len(a), len(b))


def _stem(name: str) -> str:
    n = name.casefold()
    return n[:-1] if n.endswith("s") and len(n) > 3 else n


def _sorted_values(conn, table: str, col: str, cache: dict, cap: int = 50000):
    """The column's distinct non-null values, sorted, or None if they cannot be ordered."""
    k = (table.casefold(), col.casefold())
    if k in cache:
        return cache[k]
    out = None
    try:
        rows = conn.execute("SELECT DISTINCT %s FROM %s WHERE %s IS NOT NULL"
                            % (_q([col]), _t(table), _q([col]))).fetchall()
        vs = [r[0] for r in rows]
        if vs and len(vs) <= cap:
            kinds = {type(v) for v in vs}
            if kinds <= {int, float}:
                out = sorted(float(v) for v in vs)
            elif kinds == {str}:
                out = sorted(vs)
    except sqlite3.Error:
        out = None
    cache[k] = out
    return out


def _spread(conn, child_table, child_col, parent_table, parent_col, cache) -> Optional[float]:
    """Zhang et al. (2010): does the child's population look like a *sample* of the parent's?

    A real foreign key scatters across the key it references -- every album has some artist,
    and the artists used are spread through the artist table. A coincidental inclusion is
    clustered: 347 album ids sit in the first eighth of 3503 track ids because both start at 1
    and one is shorter, which says nothing about albums and tracks.

    Measured as the 1-Wasserstein distance between where the child's values fall in the
    parent's sorted order and the uniform distribution they would follow if drawn at random.
    Returned as 1 (indistinguishable from a random sample) down to 0 (tightly clustered).

    This is the one signal that does not depend on naming, which is what makes it the answer
    for schemas like Bird's -- and on the Spider sample it is the strongest single feature of
    any kind, name-based ones included.
    """
    parent = _sorted_values(conn, parent_table, parent_col, cache)
    child = _sorted_values(conn, child_table, child_col, cache)
    if not parent or not child or len(parent) < 5 or len(child) < 3:
        return None
    if type(parent[0]) is not type(child[0]):
        return None
    n_p, n = len(parent), len(child)
    pos = sorted(bisect.bisect_left(parent, v) / n_p for v in child)
    w1 = sum(abs(p - (i + 0.5) / n) for i, p in enumerate(pos)) / n
    return max(0.0, 1.0 - 2.0 * w1)


def _rank(table, column, target, key, distinct, parent_distinct,
          spread=None, weights=None) -> Tuple[float, List[str]]:
    """Score one inclusion dependency as a candidate foreign key.

    Containment says the values *could* reference; these say whether they plausibly *do*.
    Each signal is 0..1 and its weight is above; the returned list names the ones that fired,
    so the report can say why rather than showing a number.
    """
    weights = weights or WEIGHTS
    col, tname, keyname = column.name, target.name, key
    feats = {
        "spread": 0.5 if spread is None else spread,
        "name_pk_table": max(_similar(col, tname), _similar(col, _stem(tname)),
                             1.0 if _stem(tname) in col.casefold() else 0.0),
        "name_pk_col": _similar(col, keyname),
        "name_not_own": 1.0 - _similar(col, table.name),
        "type_agree": 1.0 if _same_type(column, target.column(keyname)) else 0.0,
        "not_own_key": 0.0 if [c.casefold() for c in table.primary_key] == [col.casefold()]
                       else 1.0,
        "coverage": min(1.0, distinct / parent_distinct) if parent_distinct else 0.0,
    }
    score = sum(w * feats[k] for k, w in weights.items() if k in feats)
    return score, [k for k, v in feats.items()
                   if v >= 0.5 and weights.get(k)]


# Feature key -> what it means in words, for the report.
SIGNAL_PROSE = {
    "name_pk_table": "the column is named after the table it points at",
    "name_pk_col": "the column is named like the key it points at",
    "name_not_own": "the column is not named after its own table",
    "type_agree": "the declared types agree",
    "not_own_key": "the column does not identify its own table",
    "coverage": "its values cover much of the target",
    "spread": "its values sit in the target like a random sample, not a clustered run",
}


def _same_type(a, b) -> bool:
    if a is None or b is None:
        return False
    norm = lambda c: (c.data_type or "").split("(")[0].strip().upper()
    return norm(a) == norm(b)


def _distinct(conn, table, col) -> int:
    try:
        return conn.execute('SELECT COUNT(DISTINCT %s) FROM %s'
                            % (_q([col]), _t(table.name))).fetchone()[0] or 0
    except sqlite3.Error:
        return 0


# How many targets a column may be proposed at (bench/ablation/refs.py). One is what a rule
# that applies itself must do: a column references one table. But 77% of the references the
# search misses are columns it *did* propose, at a different target (finding 118), so a
# reviewer -- or a judge -- is better served by the best few. Raising it above 1 makes
# `preferred` a shortlist rather than a decision, which only a caller that chooses between
# them should do.
TOPK = 1

# Approximate inclusion (bench/ablation/refs.py): the share of a column's distinct values a
# containment may miss and still count. 0 is the exact test the rules use; a dirty reference
# -- a few dangling values in a schema that declared nothing -- needs a little slack, and how
# much is an empirical question the ablation asks.
TOLERANCE = 0.0


def _contained(conn, table, cols, target, key) -> Optional[int]:
    """Is every non-null value of `table.cols` present in `target.key`?

    Returns the number of distinct values behind the claim, or None when it does not hold.
    A column that is entirely null proves nothing and is rejected rather than counted as a
    vacuous subset. With TOLERANCE above zero, a containment missing no more than that
    share of the distinct values holds too.
    """
    where = " AND ".join("%s IS NOT NULL" % _q([c]) for c in cols)
    try:
        distinct = conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT %s FROM %s WHERE %s)"
            % (_q(cols), _t(table.name), where)).fetchone()[0]
        if not distinct:
            return None
        missing = conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT %s FROM %s WHERE %s "
            "EXCEPT SELECT %s FROM %s)"
            % (_q(cols), _t(table.name), where, _q(key), _t(target.name))).fetchone()[0]
    except sqlite3.Error:
        return None
    return distinct if missing <= TOLERANCE * distinct else None


# -- reporting --------------------------------------------------------------------------

def apply_keys(analysis: Analysis, catalog, tables=None, conn=None) -> List[tuple]:
    """Give a keyless table the identifier its data supports. Returns what was applied, as
    (table, columns, why) -- the caller reports it, because the report does not exist yet.

    Rule 1 needs a primary key or a foreign key to read any shape at all, and **223 of the
    412 tables in Spider 2.0's local databases declare neither**: sixteen of those thirty
    databases derived to nothing. Bird's Step 9 has mined the candidate identifiers all
    along (§3.3.9, `_unique` above) and the report has always listed them; it just never
    applied one. This applies one, and it must run *before* the derivation, because rule 9's
    name-based foreign keys need a target key to point at.

    Choosing between candidates is the whole difficulty, and the rule is deliberately timid:
    a column named after its own table is what a schema means by an identifier, and where
    nothing is named that way the guess is only taken when one candidate stands clear of the
    rest. A wrong key is a wrong identity for every query that walks the table, so a refusal
    here costs one table and a bad guess costs the schema.
    """
    applied = []
    live = list(tables or catalog.tables)
    # what the schema calls its tables: a column whose name points at one of *them* is a
    # reference, whatever the population says about its uniqueness
    from derive import singular, words                             # noqa: PLC0415
    elsewhere = {" ".join(w.casefold() for w in words(singular(t.name))) for t in live}
    unique_by_table: Dict[str, list] = {}
    never_null_by_table: Dict[str, set] = {}
    for g in analysis.findings:          # indexed once: both were rescanned per table
        if g.kind == "unique":
            unique_by_table.setdefault(g.table, []).append(g)
        elif g.kind == "never-null":
            never_null_by_table.setdefault(g.table, set()).add(g.columns[0])
    # over tables rather than over findings: a table whose every column repeats has no unique
    # finding at all, and that is exactly the table the association fallback below is for.
    # Iterating findings made the fallback unreachable for it (IPL's ball_by_ball, four
    # columns none of which is unique alone).
    for t in live:
        if t.primary_key or t.is_view:
            continue
        rows = analysis.row_counts.get(t.name, 0)
        if not rows:
            continue
        candidates = unique_by_table.get(t.name, [])
        never_null = never_null_by_table.get(t.name, set())
        scored = []
        for g in candidates:
            cols = [c for c in t.columns if c.name in g.columns]
            if len(cols) != len(g.columns):
                continue
            if any(c.nullable and c.name not in never_null for c in cols):
                continue                              # an identifier cannot be absent
            score = _key_score(t, g.columns, elsewhere, never_null)
            # Bird's significance rule guards a constraint inferred from the data *alone*.
            # A column named after its own table is not that: the name makes the claim and
            # the population is only asked not to refute it, which an eight-row lookup table
            # does as well as a large one. Anything weaker is not taken at all -- the choice
            # below never gets past NAMED_FOR_ITS_TABLE -- so significance is not consulted
            # a second time here.
            if score < NAMED_FOR_ITS_TABLE:
                continue
            scored.append((score, g.columns, g.evidence))
        scored.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
        best = scored[0] if scored and scored[0][0] >= NAMED_FOR_ITS_TABLE else None
        if best is not None and len(scored) > 1 and scored[1][0] == scored[0][0]:
            best = None                               # two equally good: guess neither
        if best is None:
            # Every minimal combination was rejected, and the table may still be an
            # association. `film_category(film_id, category_id)` is declared on both columns,
            # but `film_id` alone happens to be unique here -- a film has one category -- so
            # the minimal combination is a *reference*, and the key the schema means is a
            # superset of it, which no minimal-UCC search will ever propose. The shape is the
            # evidence: every column a reference, none of them null, the set unique.
            best = _association_key(conn, t, rows, never_null) if conn else None
        if best is None and len(candidates) == 1 and len(candidates[0].columns) == 1 \
                and candidates[0].significant:
            # Exactly one way to tell these rows apart, and the table is not an association.
            # Two shapes reach here and both are real keys the scoring cannot name:
            #
            #   a subtype     `Faculty(StaffID, Title, Status)` -- StaffID is a reference to
            #                 Staff *and* the identity of a Faculty, which is what a subtype
            #                 is. Rejecting it for naming another table lost the key and then
            #                 lost every reference that would have pointed at it.
            #   a natural key `ztblDays(DateField)`, `stacking.problem(name, ...)` -- nothing
            #                 in the name says identifier, and nothing needs to.
            #
            # The guard is that it be the *only* one: where a column is unique by coincidence
            # there is usually another that is too, and two candidates means guess neither.
            col = candidates[0].columns[0]
            entry = t.column(col)
            if entry is not None and (not entry.nullable or col in never_null) \
                    and (_looks_like_a_reference(col) or t.columns[0].name == col):
                best = (NAMED_FOR_ITS_TABLE, [col], candidates[0].evidence)
        if best is None:
            continue
        t.primary_key = list(best[1])
        applied.append((t.name, list(best[1]), best[2]))

    if conn is not None:
        applied += _keys_that_are_referenced(conn, analysis, live, unique_by_table)
    return applied


def _keys_that_are_referenced(conn, analysis, tables, unique_by_table) -> List[tuple]:
    """A second pass, for a table too small for its own data to be evidence but which other
    tables clearly point at.

    `school_scheduling.Faculty(StaffID, Title, Status)` has 24 rows, under Bird's significance
    threshold, so uniqueness in *its* population says nothing -- and it keeps no key. Three
    other tables then carry a `StaffID` that could only have meant Faculty, and with no
    Faculty key to aim at they were all read as references to `Staff` instead: two wrong
    joins, caused by a missing key rather than by anything about references.

    Being referenced is the evidence a small table cannot supply itself, and it is the signal
    Jiang & Naumann's HoPF exists to exploit: keys and references decide each other, so the
    search has to go round twice. Once is enough here -- the tables this rescues are leaves.
    """
    applied = []
    for t in tables:
        if t.primary_key or t.is_view:
            continue
        candidates = unique_by_table.get(t.name, [])
        if len(candidates) != 1 or len(candidates[0].columns) != 1:
            continue
        col = candidates[0].columns[0]
        entry = t.column(col)
        if entry is None or not _looks_like_a_reference(col):
            continue
        for other in tables:
            if other is t or other.is_view or other.column(col) is None:
                continue
            if not analysis.row_counts.get(other.name):
                continue
            if _contained(conn, other, [col], t, [col]) is None:
                continue
            t.primary_key = [col]
            applied.append((t.name, [col],
                            "%s and %s.%s is contained in it"
                            % (candidates[0].evidence, other.name, col)))
            break
    return applied


def _association_key(conn, table, out_rows, never_null):
    """The whole set of reference-looking columns, when that is unique and nothing is null."""
    refs = [c for c in table.columns
            if _looks_like_a_reference(c.name)
            and (not c.nullable or c.name in never_null)]
    if len(refs) < 2:
        return None
    cols = [c.name for c in refs]
    if _distinct_rows(conn, table, cols) != out_rows:
        return None
    return (NAMED_FOR_ITS_TABLE, cols,
            "%d rows, %d distinct combinations" % (out_rows, out_rows))


def _initials(table_name: str) -> str:
    """`Person` -> "p", `M_Cast` -> "mc". A schema that keys `Person` by `PID` and `Movie` by
    `MID` is naming the table, just briefly, and Db-IMDB does exactly that."""
    from derive import singular, words                             # noqa: PLC0415
    return "".join(w[0].casefold() for w in words(singular(table_name)) if w)


# `categories.categoryid`: the score a column gets for carrying its own table's name plus an
# identifier suffix, which is what a schema means when it means "this is the key".
NAMED_FOR_ITS_TABLE = 5


def _key_score(table, columns: Sequence[str], elsewhere=frozenset(),
               never_null=frozenset()) -> int:
    """How much a column set reads like the table's identifier. Naming is rule 10's signal
    and it is the only one available before the model exists.

    The discriminating question is not "is this column unique" -- the population answers that
    and answers it wrongly as often as not -- but "does this name point at *another* table".
    `played.album_id` does, so it is a reference that happens not to repeat, and making it the
    identity would assert a one-to-one with album that nobody claimed. `collisions.case_id`
    points at nothing in the schema, so it is this table's own natural key. Rule 9 reads the
    same signal in the other direction to find foreign keys.
    """
    from derive import singular, strip_key_suffix, words          # noqa: PLC0415
    own_name = " ".join(w.casefold() for w in words(singular(table.name)))
    own = set(own_name.split())
    score = 0
    if len(columns) > 1:
        # Two shapes say "this is the key" about a composite, and the evidence is the shape
        # itself rather than any one name.
        #
        #   every column a reference     an association: `gig(artist_id, venue_id)`
        #   the *leading* columns        how a composite key is written, near universally:
        #                                `Bowler_Scores(MatchID, GameNumber, BowlerID, ...)`
        #
        # The leading form must be a *proper* prefix with every column declared NOT NULL.
        # Without that, a table whose columns are together unique -- an event log, the case
        # with no identity at all -- would be handed one.
        if all(_looks_like_a_reference(c) for c in columns):
            return NAMED_FOR_ITS_TABLE
        names = [c.name for c in table.columns]
        # "Not null" as the *data* has it, not only as the catalogue declares it. A schema
        # that declares no key usually declares no NOT NULL either -- Spider 2.0's
        # `StaffHours`, `postseason` and `currency` all have their key columns nullable on
        # paper and never null in fact -- and reading the declaration here while the
        # candidate filter above reads the population was an inconsistency, not a policy.
        filled = [c for c in columns
                  if not table.column(c).nullable or c in never_null]
        if len(columns) < len(names) and list(columns) == names[:len(columns)] \
                and len(filled) == len(columns):
            return NAMED_FOR_ITS_TABLE
        return 0
    col = columns[0]
    parts = [w.casefold() for w in words(strip_key_suffix(col))]
    stem, joined = set(parts), " ".join(parts)
    if not _looks_like_a_reference(col):
        return 0                                      # not spelled like an identifier at all
    score += 2
    others = elsewhere - {own_name}
    if not stem:
        score += 2                                    # bare `id`
    elif joined in others or singular(joined) in others:
        # It names *another* table, so it is a reference -- and this has to be asked before
        # "is it named after its own table", because an association is named after the things
        # it associates: `film_category.film_id` looked like its own name and is not.
        return 0
    elif stem and stem <= own:
        score += 3                                    # `categories.categoryid`: its own name
    elif joined == _initials(table.name):
        score += 3                                    # `Person.PID`, `Movie.MID`
    else:
        score += 2                                    # a natural key: `collisions.case_id`
    if table.columns and table.columns[0].name == col:
        score += 1
    kind = (table.column(col).data_type or "").casefold()
    if "int" in kind:
        score += 1
    return score


def apply_references(analysis: Analysis, catalog, tables=None) -> List[tuple]:
    """Put the best-scoring candidate references on the catalogue as foreign keys.

    Rule 9 reads a foreign key off a column *name*: `transactions.CustomerID` matches the
    primary key of `customers` and nothing else. That is one feature of the ten Rostin et al.
    (2009) use and it is the only one the derivation had. Everything else was already being
    measured here and thrown away -- containment, coverage, type agreement, and `_spread`,
    which is Zhang et al.'s (VLDB 2010) randomness test and the strongest single signal of
    any of them.

    So this applies what the scoring already decided: the preferred candidate for a column,
    above the threshold, where the column carries no declared reference and the target is a
    key. Rule 9 still runs afterwards and skips anything already referenced, so the two
    compose rather than compete -- names alone still find references the data cannot
    distinguish, and the data finds the ones whose names do not match.
    """
    applied = []
    by_table = {t.name: t for t in (tables or catalog.tables)}
    for f in analysis.of_kind("inclusion"):
        if not (f.preferred and f.significant and f.corroborated):
            continue
        t, target = by_table.get(f.table), by_table.get(f.target_table)
        if t is None or target is None or t.fk_for(f.columns[0]) is not None:
            continue
        if [c.casefold() for c in t.primary_key] == [c.casefold() for c in f.columns]:
            continue                # a key that references another key is the 1:1 subtype
        t.foreign_keys.append(catalog_mod.ForeignKey(
            columns=list(f.columns), ref_table=target.name,
            ref_columns=list(f.target_columns or target.primary_key)))
        applied.append((f.table, list(f.columns), f.target_table, f.score, f.signals))
    return applied


def apply_mandatory(analysis: Analysis, catalog, tables=None) -> List[tuple]:
    """Make a role mandatory where the data says the column is never absent (Bird's 3.9-a).

    The finding has been mined since `_never_null` was written and `apply_keys` has been using
    it internally to choose identifiers, but nothing ever put it on the model: the report said
    "the role may be mandatory" and left it there. Rule 2 reads mandatory straight off
    `NOT NULL`, so applying it is one flag on the catalogue, before the derivation.

    Only where the population is significant. A column that is never null across eight rows is
    not evidence of anything, and a mandatory role that is wrong rejects data the business
    accepts.
    """
    applied = []
    by_table = {t.name: t for t in (tables or catalog.tables)}
    for f in analysis.of_kind("never-null"):
        if not f.significant:
            continue
        t = by_table.get(f.table)
        col = t.column(f.columns[0]) if t else None
        if col is None or not col.nullable or t.is_key(col.name):
            continue
        col.nullable = False
        applied.append((f.table, col.name, f.evidence))
    return applied


def recover(conn: sqlite3.Connection, catalog, tables=None,
            ignore_names: bool = False) -> Tuple[Analysis, List[tuple], List[tuple]]:
    """Rules 9b and 9c: recover the keys a catalogue does not declare, then the references
    that point at them. Returns `(analysis, keys, references)`.

    The order is the whole of the subtlety -- a foreign key points *at a key*, so the
    inclusion search has nothing to aim at until rule 9b has run -- and it was written out
    twice, once here and once in the harness that measures it. Two copies of an order is two
    chances to measure something the tool does not do, so both callers use this.
    """
    before = analyse_keys(conn, catalog, tables)
    keys = apply_keys(before, catalog, tables=tables, conn=conn)
    # analyse() runs the key pass again on purpose: the catalogue now declares what rule 9b
    # found, so the inclusion search can aim at it, and the keyed tables skip the unique
    # search the second time round. That skip is why the first pass's unique findings are
    # carried forward -- once a table has a key, nothing mines its *other* unique columns
    # again, and a reference points at whichever key it likes.
    analysis = analyse(conn, catalog, tables, ignore_names=ignore_names,
                       also_unique=before.of_kind("unique"))
    # The minimal unique combinations rule 9b did not choose. They are alternate keys, they
    # are already paid for, and until now they were used as reference targets and then thrown
    # away rather than reported as the uniqueness constraints they are.
    chosen = {(t, tuple(c.casefold() for c in cols)) for t, cols, _ in keys}
    for f in before.of_kind("unique"):
        if (f.table, tuple(c.casefold() for c in f.columns)) in chosen:
            continue
        analysis.findings.append(Finding("alternate-key", f.table, list(f.columns),
                                         f.rows, distinct=f.distinct))
    return analysis, keys, apply_references(analysis, catalog, tables)


def apply_column_types(analysis: Analysis, model: dict, report) -> None:
    """Give a value type reached only by undeclared columns the type its data has.

    Same discipline as `apply_domains`: a value type reached by more than one column is left
    alone unless every one of them agrees, because two columns sharing a name do not share a
    population. A value type any *declared* column reaches is left alone outright -- the
    declaration wins.
    """
    mined = {(f.table, f.columns[0]): f.values[0]
             for f in analysis.of_kind("column-type") if f.significant and f.values}
    if not mined:
        return
    player = {r["id"]: r["player"] for c in model.get("concepts", []) for r in c.get("roles", [])}
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    columns = {c["id"]: c for c in model["mapping"]["columns"]}
    tables = {t["id"]: t for t in model["mapping"]["tables"]}
    reached: Dict[str, set] = {}
    for rm in model["mapping"]["roleMap"]:
        cid = player.get(rm["role"])
        if not cid or concepts.get(cid, {}).get("kind") != "value":
            continue
        for col in rm.get("columns", []):
            c = columns.get(col)
            if c:
                reached.setdefault(cid, set()).add((tables[c["table"]]["name"], c["name"]))

    applied = []
    for cid, pairs in reached.items():
        found = {mined.get(p) for p in pairs}
        if len(found) != 1 or None in found:
            continue                     # some column declares a type, or they disagree
        name = found.pop()
        if concepts[cid].get("dataType", {}).get("name") == name:
            continue
        concepts[cid]["dataType"] = {"name": name}
        for p in pairs:
            for c in model["mapping"]["columns"]:
                if tables[c["table"]]["name"] == p[0] and c["name"] == p[1]:
                    c["dataType"] = {"name": name}
        applied.append("%s (%s)" % (concepts[cid]["name"], name))
    if applied:
        report.refine("rule 6c", "population", "%d undeclared column types read from the data"
                      % len(applied),
                      "These columns are declared with no type at all, so the conceptual type "
                      "fell back to text and every filter on them compared a string with a "
                      "number: zero rows, silently. The population says what they hold: %s."
                      % ", ".join(sorted(applied)[:12]),
                      "Check them. A column with no declared type is a defect in the source "
                      "schema, and the right repair is there, not here.")


# Finding-kind -> CCM constraint kind, for the constraints a population supports. The CCM has
# admitted all of these since it was written; nothing has ever produced one (finding 119),
# while the miners below have been finding them and reporting them as prose.
PROMOTABLE = {"exclusion": "exclusion", "equality": "equality",
              "comparison": "valueComparison", "ring": "ring"}


def apply_constraints(analysis: Analysis, model: dict, report) -> None:
    """Promote the constraints the data supports from prose into the model.

    `_exclusions`, `_equalities`, `_comparisons` and `_rings` each find an ORM constraint the
    schema states nowhere, and each ended at `report.refine` -- a sentence for a human, which
    no consumer reads. This puts them in `model["constraints"]`, where FORML verbalises them,
    `model/abstract.py`'s rules 7-11 can finally weigh them, and a reader of the model sees
    what the data actually obeys.

    Every one is marked **deontic** (ORM 2 section 1.7). That is not a formality. A declared
    constraint is a law the data cannot break and a compiler may reason from; one recovered
    from a population says only what today's rows do, and the next insert may break it.
    Marking them keeps the distinction a consumer needs in order to report them without
    optimising on them.
    """
    if not model.get("mapping"):
        return
    columns = {c["id"]: c for c in model["mapping"]["columns"]}
    tables = {t["id"]: t["name"] for t in model["mapping"]["tables"]}
    # (table name, column name) -> the role whose mapping is exactly that column
    role_of: Dict[Tuple[str, str], str] = {}
    for rm in model["mapping"]["roleMap"]:
        cols = rm.get("columns") or []
        if len(cols) != 1 or cols[0] not in columns:
            continue
        c = columns[cols[0]]
        role_of.setdefault((tables.get(c["table"], ""), c["name"]), rm["role"])
    owner = {r["id"]: c for c in model.get("concepts", []) for r in c.get("roles", [])}

    made: List[str] = []
    for f in analysis.findings:
        kind = PROMOTABLE.get(f.kind)
        if kind is None or not f.significant:
            continue
        roles = [role_of.get((f.table, col)) for col in f.columns]
        if not roles or any(r is None for r in roles):
            continue
        c = {"id": "pc.%s.%s.%s" % (kind, f.table, "-".join(f.columns)),
             "kind": kind, "modality": "deontic"}
        if kind == "ring":
            # the ring is a property of the fact type the column reaches, not of the column:
            # its role sequence is that fact type's own roles
            fact = owner.get(roles[0])
            if fact is None or len(fact.get("roles", [])) != 2 or not f.values:
                continue
            c["roleSequences"] = [[r["id"] for r in fact["roles"]]]
            c["ringKind"] = f.values[0]
        else:
            c["roleSequences"] = [roles]
            if kind == "valueComparison":
                c["comparisonOperator"] = "<="     # _comparisons records (lesser, greater)
        if any(x["id"] == c["id"] for x in model.setdefault("constraints", [])):
            continue
        model["constraints"].append(c)
        made.append("%s on %s.%s" % (kind, f.table, ", ".join(f.columns)))
    if made:
        report.refine("rule 6e", "population", "%d constraints applied" % len(made),
                      "The data supports these, and the model now states them: %s. Each is "
                      "marked deontic, because a population says what today's rows do and "
                      "not what the schema forbids -- a consumer may report one but must "
                      "not reason from it the way it reasons from a declared key."
                      % summarise(made, 8),
                      "Check each against the domain. A deontic constraint that is really "
                      "alethic should be declared in the database, where it will be "
                      "enforced; one that is neither should be deleted.")


def apply_domains(analysis: Analysis, model: dict, report) -> None:
    """Put the significant value domains on the value types they belong to.

    A value type may be reached from more than one column -- `derive.py` shares one by name --
    and two columns sharing a name do not share a population. Where that happens the domain is
    reported and not applied, because a union would assert values a column never holds and
    picking one would assert a column's values of the other.

    A domain mined inside a document (`Finding.path`) is applied the same way and reported
    on its own line, naming the path, because the value type it lands on was made by rule 12
    and nothing else in the report says where its values live.
    """
    player = {r["id"]: r["player"] for c in model.get("concepts", []) for r in c.get("roles", [])}
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    columns = {c["id"]: c for c in model["mapping"]["columns"]}
    tables = {t["id"]: t for t in model["mapping"]["tables"]}
    # value type -> the (table, column, path) triples that reach it; a column read whole
    # has no path
    reached: Dict[str, set] = {}
    for rm in model["mapping"]["roleMap"]:
        cid = player.get(rm["role"])
        if not cid or concepts.get(cid, {}).get("kind") != "value":
            continue
        for col in rm.get("columns", []):
            c = columns.get(col)
            if c:
                reached.setdefault(cid, set()).add(
                    (tables[c["table"]]["name"], c["name"],
                     tuple(c["path"]) if c.get("path") else None))

    applied, shared, stripped, loosened, inside = 0, [], [], [], []
    for f in analysis.of_kind("value-domain"):
        if not f.significant:
            continue
        here = (f.table, f.columns[0], tuple(f.path) if f.path else None)
        for cid, triples in reached.items():
            if here not in triples:
                continue
            if len(triples) > 1:
                shared.append("%s.%s (%s)" % (f.table, f.columns[0], concepts[cid]["name"]))
                continue
            if concepts[cid].get("restriction"):
                continue                      # a declared CHECK is sound; do not overwrite it
            # A domain mined from a column whose type the data supplied (rule 6c) holds
            # that column's values, not their spelling: `DriveId: '1'` against an integer
            # column with no affinity matches nothing, so the listing has to print 1.
            name = (concepts[cid].get("dataType") or {}).get("name")
            # A stand-in for NULL is not a member of the domain. `Unknown` in 26% of
            # `polarmode` is the absence of a polarisation, and enrolling it makes the model
            # assert something false: "how many signals are polarised" answers 1000 where the
            # truth is 742. `_dirt` has reported these since it was written and nothing
            # consumed the finding. Stripping is not optional -- a domain that admits its own
            # null is wrong, not merely generous -- so it happens wherever a domain is applied.
            values = [v for v in f.values if not _is_absent(v, f.values)]
            if len(values) != len(f.values):
                stripped.append("%s.%s (%s)" % (f.table, f.columns[0],
                                                ", ".join(sorted(set(f.values) - set(values)))))
                # The role is mandatory only if every instance really plays it. A column
                # declared NOT NULL that spells absence as a word does not.
                for owner in concepts.values():
                    if owner.get("kind") != "fact":
                        continue
                    if not any(r["player"] == cid for r in owner.get("roles", [])):
                        continue
                    for r in owner["roles"]:
                        if concepts[r["player"]]["kind"] == "entity" and r.get("isMandatory"):
                            r["isMandatory"] = False
                            loosened.append(owner["name"])
            if not values:
                continue                      # nothing left but sentinels: no domain at all
            if f.path is None and name in ("integer", "real"):
                # a column's values were mined as text; a path's keep the storage class
                # json_extract gave them, which is what a filter is compared against
                cast = int if name == "integer" else float
                try:
                    values = [cast(v) for v in values]
                except (TypeError, ValueError):
                    pass
            concepts[cid]["restriction"] = {"values": values}
            if f.path is not None:
                inside.append((f, concepts[cid]["name"], values))
            else:
                applied += 1
    if applied:
        report.refine("rule 6b", "population", "%d value constraints applied" % applied,
                      "Each value type reached by exactly one column, and whose column holds "
                      "few enough distinct values over a large enough population, now carries "
                      "the values seen as an ORM value constraint. The schema listing shows "
                      "them, which is the point: a domain nobody can see is a domain nobody "
                      "can use.",
                      "Check them against the domain. Every one is an observation of today's "
                      "data, not a rule, and `--infer-domains` is opt-in for that reason.")
    if stripped:
        report.refine(
            "rule 6f", "population", "%d domains had a stand-in for NULL removed" % len(stripped),
            "These columns spell absence as a word -- %s -- and the value was about to be "
            "enrolled in the value constraint as if it were a member of the domain. It is "
            "not: a signal whose polarisation is 'Unknown' has no polarisation, and a "
            "constraint admitting it makes every count over the domain wrong."
            % summarise(sorted(set(stripped)), limit=6),
            "Check that the stand-in really means absent here. Where it means a real "
            "category -- an 'Unknown' species that is a species -- put the CHECK back.")
    if loosened:
        report.refine(
            "rule 6f", "population", "%d roles made optional" % len(set(loosened)),
            "The column is declared NOT NULL but spells absence as a word, so the role it "
            "carries is not mandatory after all: %s."
            % summarise(sorted(set(loosened)), limit=6),
            "Confirm. A mandatory role that is wrong asserts the business always knows "
            "something it does not.")
    if shared:
        report.refine("rule 6b", "population", "%d domains not applied" % len(shared),
                      "These columns have a domain worth recording, but their value type is "
                      "reached by more than one column: %s. Two columns that share a value "
                      "type do not share a population, and ORM would need a role-level value "
                      "constraint to tell them apart."
                      % summarise(sorted(set(shared)), limit=8),
                      "Split the value type, or declare the CHECK on the column that needs it.")


    for f, vtname, values in inside:
        path = _json_path_literal(f.path)
        report.refine("rule 6b", "population",
                      "%s.%s %s (%s)" % (f.table, f.columns[0], path, vtname),
                      "%d distinct value(s) over %d rows inside the document: %s. Recorded "
                      "as the value domain of the fact type rule 12 derived for this path, "
                      "so the listing says how the code is spelled." % (
                          len(values), f.rows, ", ".join(repr(v) for v in values[:6])
                          + (" ..." if len(values) > 6 else "")),
                      "Seen, not permitted: a value absent from today's documents may still "
                      "be valid.")


def shared_domains(analysis: Analysis) -> Dict[tuple, List[tuple]]:
    """Value domains that more than one column holds, exactly. The same handful of values in
    two places is one value type read twice, and a model that says otherwise makes a query
    author work out which spelling belongs to which column."""
    domains: Dict[tuple, List[tuple]] = {}
    for f in analysis.of_kind("value-domain"):
        if f.significant and f.values:
            domains.setdefault(tuple(sorted(f.values)), []).append((f.table, f.columns[0]))
    return {v: w for v, w in domains.items() if len(w) > 1}


QUALITY_PROSE = {
    "case-variants": ("the same values in scrambled case", 
                      "%(distinct)d distinct values that are %(folded)d once case is folded: "
                      "%(values)s. A value domain is what tells a query author how a code is "
                      "spelled, and the domain miner's ceiling is %(ceiling)d distinct, so a "
                      "column like this records no domain at all -- the enumeration is "
                      "invisible rather than wrong.",
                      "Fold the case at the source, or accept that a filter on this column "
                      "has to be case-insensitive."),
    "numeric-text": ("a quantity stored with its unit",
                     "values like %(values)s: the number is the datum and the rest is a unit "
                     "or a comment. Typed text, correctly -- but every query that wants the "
                     "number digs it out, which the schema could name once.",
                     "Consider a derived fact type that extracts the number, so the query "
                     "language never sees the unit."),
    "padding": ("values that differ only by surrounding space",
                "%(distinct)d value(s) with leading or trailing whitespace, e.g. %(values)s. "
                "The same value to a reader and a different one to `=`.",
                "Trim at the source. Until then a filter may silently match nothing."),
    "constant": ("one value over the whole population",
                 "every one of %(rows)d rows holds %(values)s. A fact type over this "
                 "distinguishes no instance from another -- in ORM it is a value constraint "
                 "of one value, or it is not a fact type.",
                 "Check whether the column is reserved for future use, defaulted and never "
                 "set, or genuinely constant. Only the last is worth modelling."),
    "date-formats": ("dates in several shapes",
                     "%(distinct)d date shapes in one text column: %(values)s. Sorted as text "
                     "they interleave, and a range filter on the text is wrong.",
                     "Store a date. Until then every query parses each shape."),
    "sparse": ("mostly empty",
               "Null in a large share of the rows (%(values)s).",
               "Say what a missing value counts as in any measure that uses it."),
    "per-date": ("several rows per date",
                 "Rows and dates: %(values)s.",
                 "Say whether a 'daily' measure counts rows or days."),
    "case-duplicates": ("identifiers that differ only by case",
                        "For example %(values)s.",
                        "Decide whether they are one thing; fold case at the source if so."),
    "unit-conflict": ("a unit in the values that contradicts the name",
                      "The name and the values name different units: %(values)s.",
                      "Correct the name or the values."),
    "variants": ("values that look like two spellings of one",
                 "%(values)s: a bare code beside the same code with a label, or a word beside "
                 "a longer word it begins. Each reader decides alone whether they are one value.",
                 "Say which it is, at the source or in a definition."),
    "sentinel-null": ("a stand-in for NULL",
                      "%(distinct)d row(s) holding %(values)s, which read as absent rather "
                      "than as a value. A role inferred mandatory over these is mandatory in "
                      "name only, which is what rule 9a would do.",
                      "Decide whether these mean NULL. If they do, they defeat both the "
                      "mandatory inference and any filter that tests for absence."),
}


def apply_alternate_keys(analysis: Analysis, model: dict, report) -> int:
    """State a second identifier as ORM states one: uniqueness on the *value* role.

    The model already says "each CoreRecord has at most one CoreRecordClientref" -- that is
    uniqueness on the entity role, and every single-valued attribute has it. What makes a
    value an identifier is the other direction, "for each Clientref, at most one CoreRecord
    has that Clientref", and without it the model cannot tell an author that `clientref`
    identifies a record while `appref` does not (finding 151).

    Only where the data says so, and never over a declared one: a `UNIQUE` in the catalogue
    is already a constraint and this does not restate it.
    """
    mapping = model.get("mapping") or {}
    tname = {t["id"]: t["name"].casefold() for t in mapping.get("tables", [])}
    cname = {c["id"]: c["name"].casefold() for c in mapping.get("columns", [])}
    player = {r["id"]: r["player"] for c in model.get("concepts", []) for r in c.get("roles", [])}
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    # the role a column maps, where that role is played by a value type
    role_of = {}
    for rm in mapping.get("roleMap", []):
        cid = player.get(rm["role"])
        if cid and concepts.get(cid, {}).get("kind") == "value" and len(rm["columns"]) == 1:
            col = rm["columns"][0]
            role_of[(tname.get(rm["table"]), cname.get(col))] = rm["role"]
    already = {r for k in model.get("constraints", []) if k["kind"] == "uniqueness"
               for seq in k.get("roleSequences", []) for r in seq if len(seq) == 1}

    applied = []
    for f in analysis.of_kind("alternate-key"):
        if not f.significant or len(f.columns) != 1:
            continue
        role = role_of.get((f.table.casefold(), f.columns[0].casefold()))
        if role is None or role in already:
            continue
        model.setdefault("constraints", []).append(
            {"id": "uc.alt.%s" % role.split(".", 1)[-1].replace(".", "_"),
             "kind": "uniqueness", "roleSequences": [[role]],
             "modality": "deontic"})
        already.add(role)
        applied.append((f.table, f.columns[0], concepts[player[role]]["name"]))

    for table, col, vt in applied:
        report.refine("alternate identifier", "population", "%s.%s" % (table, col),
                      "Every row holds a different value and none is absent, so this "
                      "identifies its instance as surely as the declared key does. ORM "
                      "states that as a uniqueness constraint on the value role, and "
                      "without it the model says the same thing about this column as about "
                      "one that merely happens to be single-valued -- so nothing tells a "
                      "query author that %s is a second way to name the same thing." % vt,
                      "Confirm it. Uniqueness in today's rows is not uniqueness, and an "
                      "identifier that is wrong is a wrong identity in every query that "
                      "walks it. Recorded as deontic for that reason.")
    return len(applied)


def apply_document_domains(conn: sqlite3.Connection, model: dict, report) -> int:
    """Rule 6b for the fact types rule 12 derived: a value domain per document path.

    The paths are in the model's mapping and not in the catalogue, so `analyse` never sees
    them: every value type rule 12 made came out with no domain -- `TreatmentbasicEngagement`
    listed beside `TreatmentbasicStatus` and saying nothing about how its codes are spelled,
    and a mental-health writer probed each one with `./try`. Mined by the same miner as a
    column's domain, over the same JSONPath the emitter spells for a query, and applied by
    the same applier; only the population is different, and it is where the values live.
    """
    out = Analysis()
    _document_domains(conn, model, out)
    apply_domains(out, model, report)
    return len(out.findings)


def _document_dirt(conn, model: dict, out: Analysis) -> None:
    """`_dirt` over the paths rule 12 opened, read exactly as a query reads them."""
    columns = {c["id"]: c for c in model["mapping"]["columns"]}
    tables = {t["id"]: t["name"] for t in model["mapping"]["tables"]}
    seen = set()
    for rm in model["mapping"]["roleMap"]:
        if len(rm["columns"]) != 1:
            continue
        col = columns.get(rm["columns"][0])
        if not col or not col.get("path") or col["id"] in seen:
            continue
        seen.add(col["id"])
        path = _json_path_literal(col["path"])
        if path is None:
            continue
        table = tables[col["table"]]
        expr = "json_extract(%s, '%s')" % (_q([col["name"]]), path)
        try:
            vals = [r[0] for r in conn.execute("SELECT %s FROM %s WHERE %s IS NOT NULL"
                                               % (expr, _t(table), expr)).fetchall()]
        except sqlite3.Error:
            continue
        if vals:
            try:
                rows = conn.execute("SELECT count(*) FROM %s" % _t(table)).fetchone()[0]
            except sqlite3.Error:
                rows = len(vals)
            _dirt_values(table, col["name"], rows, vals, out, path=list(col["path"]))


def apply_document_quality(conn: sqlite3.Connection, model: dict, report) -> int:
    """The value cautions for the paths inside documents, which the column-wise profile
    never reads. Where finding 166's writers met most of what they had to find by hand."""
    out = Analysis()
    _document_dirt(conn, model, out)
    return apply_quality(out, model, report)


# -- several routes between two things ------------------------------------------------------
#
# Finding 166's writers spent more effort here than anywhere: `operations` names no disaster,
# and four tables each hold an operation and a disaster; engagement reaches a fan through
# interactions or through memberships; equipment reaches a station three ways. Which route a
# question means is the writer's call, but whether the routes *agree* is a fact about the
# data, and the model is the thing that knows the routes exist.

def _route_pairs(conn, table: str, a_col: str, b_col: str) -> Optional[Dict[str, set]]:
    try:
        rows = conn.execute("SELECT DISTINCT %s, %s FROM %s WHERE %s IS NOT NULL AND %s IS NOT NULL"
                            % (_q([a_col]), _q([b_col]), _t(table), _q([a_col]),
                               _q([b_col]))).fetchall()
    except sqlite3.Error:
        return None
    out: Dict[str, set] = {}
    for a, b in rows:
        out.setdefault(str(a), set()).add(str(b))
    return out


def routes(conn, tables) -> List[dict]:
    """For each pair of tables linked by two or more routes -- a table holding foreign keys to
    both, or one referencing the other directly -- each route's pairs and whether the routes
    agree where they overlap."""
    by_name = {t.name: t for t in tables if not t.is_view}
    links: Dict[tuple, list] = {}
    for t in by_name.values():
        single = [fk for fk in t.foreign_keys if len(fk.columns) == 1 and fk.ref_table in by_name]
        # Two keys from one table to the same table are two roles -- an origin and a
        # destination -- not two routes to one thing. Only a table that refers to a target
        # once can be a route to it.
        targets = [fk.ref_table for fk in single]
        single = [fk for fk in single if targets.count(fk.ref_table) == 1]
        for fk in single:                       # a direct reference is a route of its own
            if fk.ref_table != t.name and len(t.primary_key) == 1:
                if t.name < fk.ref_table:           # keyed as the bridges are, in name order
                    links.setdefault((t.name, fk.ref_table), []).append(
                        (t.name, t.primary_key[0], fk.columns[0]))
                else:
                    links.setdefault((fk.ref_table, t.name), []).append(
                        (t.name, fk.columns[0], t.primary_key[0]))
        for i, fa in enumerate(single):
            for fb in single[i + 1:]:
                a, b = fa.ref_table, fb.ref_table
                if a == b or t.name in (a, b):
                    continue
                if a > b:
                    fa, fb, a, b = fb, fa, b, a
                links.setdefault((a, b), []).append((t.name, fa.columns[0], fb.columns[0]))
    out = []
    for (a, b), via in sorted(links.items()):
        seen_tables = set()
        via = [v for v in via if not (v[0] in seen_tables or seen_tables.add(v[0]))]
        if len(via) < 2:
            continue
        mapped = [(table, _route_pairs(conn, table, ca, cb)) for table, ca, cb in via]
        mapped = [(table, m) for table, m in mapped if m]
        if len(mapped) < 2:
            continue
        both = set()
        for i, (_, m1) in enumerate(mapped):
            for _, m2 in mapped[i + 1:]:
                both |= set(m1) & set(m2)
        disagree = sum(1 for k in both
                       if len({frozenset(m[k]) for _, m in mapped if k in m}) > 1)
        out.append({"a": a, "b": b, "overlap": len(both), "disagree": disagree,
                    "via": [(table, sum(len(v) for v in m.values())) for table, m in mapped]})
    return out


def apply_routes(conn, tables, model: dict, report) -> int:
    """Say, on both entity types, that they are linked several ways and whether the ways
    agree. A caution, like the value cautions: it changes which join a query should choose."""
    entity = {}
    tnames = {t["id"]: t["name"] for t in model["mapping"]["tables"]}
    concepts = {c["id"]: c for c in model["concepts"]}
    for cm in model["mapping"]["conceptMap"]:
        c = concepts.get(cm["concept"])
        if c and c["kind"] == "entity":
            entity.setdefault(tnames.get(cm["table"]), c)
    applied = 0
    for r in routes(conn, tables):
        ca, cb = entity.get(r["a"]), entity.get(r["b"])
        if not ca or not cb:
            continue
        listed = ["%s (%d pairs)" % (table if table not in (r["a"], r["b"])
                                     else "%s directly" % table, n)
                  for table, n in sorted(r["via"], key=lambda v: -v[1])]
        ways = ", ".join(listed[:4]) + (", and %d more" % (len(listed) - 4)
                                         if len(listed) > 4 else "")
        if not r["overlap"]:
            verdict = "they never cover the same %s, so the choice decides which rows appear" % ca["name"]
        elif not r["disagree"]:
            verdict = "they agree wherever they overlap (%d %s)" % (r["overlap"], ca["name"])
        else:
            verdict = ("they disagree for %d of the %d %s they share, so the route chosen changes "
                       "the answer" % (r["disagree"], r["overlap"], ca["name"]))
        for c, other in ((ca, cb), (cb, ca)):
            said = "Reaches %s by %d routes: %s; %s." % (other["name"], len(r["via"]), ways, verdict)
            marks = c.setdefault("dataQuality", [])
            if said not in marks:
                marks.append(said)
                applied += 1
    if applied:
        report.refine("data quality", "population", "%d route caution(s)" % applied,
                      "Two things the schema links more than one way, with whether the ways "
                      "agree in the data.",
                      "Say in a definition which route a business question means.")
    return applied


def apply_structure(conn, tables, model: dict, report) -> int:
    """Three things about the rows' shape that finding 171's writers had to count for
    themselves, each put where the listing shows it:

    * coverage -- a table whose rows refer to only a small share of what it references:
      10 of 995 artifacts have a rating. Said on the referenced entity.
    * one row per group -- a composite key whose last column almost never varies within the
      rest: 94% of (race, driver) pairs have one lap. Said on the table's entity.
    * joint nulls -- a flag null exactly where another value is null: a blend flag missing on
      the 109 stars with no magnitude means no magnitude, not "not blended". Said on the flag.
    """
    concepts = {c["id"]: c for c in model["concepts"]}
    tnames = {t["id"]: t["name"] for t in model["mapping"]["tables"]}
    entity = {}
    for cm in model["mapping"]["conceptMap"]:
        c = concepts.get(cm["concept"])
        if c and c["kind"] == "entity":
            entity.setdefault(tnames.get(cm["table"]).casefold(), c)
    by_name = {t.name.casefold(): t for t in tables}
    applied = 0

    def say(concept, text):
        nonlocal applied
        marks = concept.setdefault("dataQuality", [])
        if text not in marks:
            marks.append(text)
            applied += 1

    rows = {}
    for t in tables:
        try:
            rows[t.name.casefold()] = conn.execute("SELECT count(*) FROM %s" % _t(t.name)).fetchone()[0]
        except sqlite3.Error:
            rows[t.name.casefold()] = 0

    for t in tables:
        for fk in t.foreign_keys:
            parent = by_name.get(fk.ref_table.casefold())
            n = rows.get(fk.ref_table.casefold(), 0)
            if parent is None or n < MIN_ROWS or fk.ref_table.casefold() == t.name.casefold():
                continue
            try:
                covered = conn.execute(
                    "SELECT count(*) FROM (SELECT DISTINCT %s FROM %s WHERE %s)"
                    % (_q(fk.columns), _t(t.name),
                       " AND ".join("%s IS NOT NULL" % _q([c]) for c in fk.columns))).fetchone()[0]
            except sqlite3.Error:
                continue
            ent = entity.get(fk.ref_table.casefold())
            if ent and covered < 0.5 * n:
                say(ent, "Only %d of %d are referred to by %s (%s): a join to it keeps %d%% "
                         "of them unless it is an outer join."
                    % (covered, n, t.name, ", ".join(fk.columns), round(100 * covered / n)))
        key = t.primary_key
        ent = entity.get(t.name.casefold())
        in_fk = {c.casefold() for fk in t.foreign_keys for c in fk.columns}
        # a counter at the end of a key of references -- (race, driver, lap) -- not the last
        # column of a composite reference, which varies with the rest by construction
        if ent and len(key) >= 3 and rows.get(t.name.casefold(), 0) >= MIN_ROWS \
                and key[-1].casefold() not in in_fk \
                and all(c.casefold() in in_fk for c in key[:-1]):
            head = key[:-1]
            try:
                groups, single = conn.execute(
                    "SELECT count(*), sum(CASE WHEN k = 1 THEN 1 ELSE 0 END) FROM "
                    "(SELECT count(*) k FROM %s GROUP BY %s)" % (_t(t.name), _q(head))).fetchone()
            except sqlite3.Error:
                groups, single = 0, 0
            if groups and single >= 0.8 * groups:
                say(ent, "%d of %d (%s) groups have a single row here, so a spread or a "
                         "consistency measure within a group is empty or zero for most."
                    % (single, groups, ", ".join(head)))

    # joint nulls, over columns and the paths inside documents
    columns = {c["id"]: c for c in model["mapping"]["columns"]}
    player = {r["id"]: r["player"] for c in model["concepts"] for r in c.get("roles", [])}
    readable = {}
    for rm in model["mapping"]["roleMap"]:
        cid = player.get(rm["role"])
        if not cid or concepts.get(cid, {}).get("kind") != "value" or len(rm["columns"]) != 1:
            continue
        col = columns.get(rm["columns"][0])
        if not col:
            continue
        table = tnames[col["table"]]
        if col.get("path"):
            lit = _json_path_literal(col["path"])
            if lit is None:
                continue
            expr = "json_extract(%s, '%s')" % (_q([col["name"]]), lit)
            label = "%s->%s" % (col["name"], ".".join(col["path"]))
        else:
            expr, label = _q([col["name"]]), col["name"]
        readable.setdefault(table, {})[expr] = (label, cid)
    for table, exprs in readable.items():
        n = rows.get(table.casefold(), 0)
        if n < MIN_ROWS or len(exprs) > 200:
            continue
        stats = {}
        for expr in exprs:
            try:
                nulls, distinct = conn.execute("SELECT sum(CASE WHEN %s IS NULL THEN 1 ELSE 0 END), "
                                               "count(DISTINCT %s) FROM %s"
                                               % (expr, expr, _t(table))).fetchone()
            except sqlite3.Error:
                continue
            if nulls:
                stats[expr] = (nulls, distinct)
        for flag, (nulls, distinct) in stats.items():
            if distinct > 3:
                continue
            for other, (onulls, odistinct) in stats.items():
                if other == flag or onulls != nulls or odistinct <= 3:
                    continue
                try:
                    both = conn.execute("SELECT count(*) FROM %s WHERE %s IS NULL AND %s IS NULL"
                                        % (_t(table), flag, other)).fetchone()[0]
                except sqlite3.Error:
                    continue
                if both == nulls:
                    label, cid = exprs[flag]
                    say(concepts[cid], "Null exactly where %s is null (%d rows): a missing value "
                                       "here means %s was not recorded, not a value of its own."
                        % (exprs[other][0], nulls, exprs[other][0]))
                    break
    if applied:
        report.refine("data quality", "population", "%d structure caution(s)" % applied,
                      "Coverage of referenced tables, groups of one row, and flags null "
                      "exactly where another value is.",
                      "Say in a definition how a measure treats the rows these leave out.")
    return applied


def report_quality(analysis: Analysis, report) -> None:
    """Put the data-quality profile on the derivation report.

    Reported, never applied: what to do about dirt is the modeller's call and usually the
    source system's problem. The reverse engineer's job is to say it is there, because one
    of these silently disables another pass -- a case-scrambled enumeration is not recorded
    as a value domain, and nothing else says so.
    """
    for f in analysis.of_kind("quality"):
        sig = f.signals[0]
        title, why, action = QUALITY_PROSE[sig]
        report.refine("data quality", "population", "%s.%s -- %s" % (f.table, f.columns[0], title),
                      why % {"distinct": f.distinct or 0, "rows": f.rows,
                             "folded": len(f.values or []),
                             "ceiling": DOMAIN_MAX_VALUES,
                             "values": ", ".join(repr(v) for v in (f.values or [])[:4])},
                      action)


# What to tell a query author about a column the profile flagged. Only the signals that
# change what a *filter* has to say: a constant column or a padded one is worth a worklist
# entry, but neither makes a well-written filter match the wrong rows.
QUALITY_MARKER = {
    "case-variants": "Values arrive in mixed case (%(distinct)d spellings of %(folded)d "
                     "values: %(listed)s). An exact `=` filter will match a fraction of the "
                     "rows; use a case-insensitive test.",
    "numeric-text": "The number is stored with its unit, as %(values)s. Comparisons are "
                    "string comparisons unless the number is extracted first.",
    "sentinel-null": "Some rows hold %(values)s, which reads as absent rather than as a "
                     "value. A test for absence will not find them.",
    "date-formats": "Dates are stored as text in %(distinct)d shapes: %(formats)s. Sorting or "
                    "comparing the text orders them wrongly; parse each shape to a date first.",
    "variants": "Some values look like two spellings of one: %(pairs)s. Decide whether they "
                "mean the same before filtering on either.",
    "constant": "Every row holds the same value, %(value)r: it cannot order, rank or tell rows "
                "apart.",
    "sparse": "Null in %(v0)s of %(v1)s rows. An average, a filter or a ranking over it covers "
              "only the rows that have it; say what a missing value counts as.",
    "per-date": "Several rows per date: %(v0)s rows fall on %(v1)s dates. A count of rows is "
                "not a count of days.",
    "case-duplicates": "%(distinct)d values differ from another only by case, as %(pairs)s. "
                       "A count of distinct values counts each twice unless it folds case.",
    "unit-conflict": "The name says %(v0)s; the values are written in %(v1)s. Convert before "
                     "comparing with anything in %(v0)s.",
}


def apply_quality(analysis: Analysis, model: dict, report) -> int:
    """Put the profile's cautions on the value types a query author names.

    `report_quality` writes the same findings to the worklist, which a modeller reads once.
    This puts them where a *query author* reads them -- the schema listing -- because that
    is the surface measured as deciding answers (finding 132), and because each of these
    makes an ordinary filter match the wrong rows without failing:
    `blood_compat = 'compatible'` finds one spelling of 154.

    Only the signals that change what a filter must say. A constant column and a padded one
    are worth telling the modeller and do not change how the column is queried.
    """
    player = {r["id"]: r["player"] for c in model.get("concepts", []) for r in c.get("roles", [])}
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    columns = {c["id"]: c for c in model["mapping"]["columns"]}
    tables = {t["id"]: t for t in model["mapping"]["tables"]}
    reached: Dict[str, set] = {}
    for rm in model["mapping"]["roleMap"]:
        cid = player.get(rm["role"])
        if not cid or concepts.get(cid, {}).get("kind") != "value":
            continue
        for col in rm.get("columns", []):
            c = columns.get(col)
            if c:
                reached.setdefault(cid, set()).add((tables[c["table"]]["name"], c["name"],
                                                    tuple(c.get("path") or ())))

    applied = 0
    for f in analysis.of_kind("quality"):
        text = QUALITY_MARKER.get(f.signals[0])
        if not text:
            continue
        here = (f.table, f.columns[0], tuple(f.path or ()))
        for cid, pairs in reached.items():
            if here not in pairs or len(pairs) > 1:
                continue
            said = text % {"distinct": f.distinct or 0, "folded": len(f.values or []),
                           "values": ", ".join(repr(v) for v in (f.values or [])[:2]),
                           "formats": "; ".join(str(v) for v in (f.values or [])),
                           "pairs": " and ".join(repr(v) for v in (f.values or [])[:2]),
                           "value": (f.values or ["?"])[0],
                           "listed": ", ".join(repr(v) for v in (f.values or [])[:12])
                           + (", ..." if len(f.values or []) > 12 else ""),
                           "v0": (list(f.values or []) + ["?", "?"])[0],
                           "v1": (list(f.values or []) + ["?", "?"])[1]}
            marks = concepts[cid].setdefault("dataQuality", [])
            if said not in marks:
                marks.append(said)
                applied += 1
    if applied:
        report.refine("data quality", "population", "%d caution(s) on value types" % applied,
                      "The profile found values that make an ordinary filter match the wrong "
                      "rows without failing, and the schema listing now says so where the "
                      "query author reads it.",
                      "These are cautions, not constraints. Nothing enforces them and "
                      "nothing depends on them; deleting them loses advice, not meaning.")
    return applied


def report_into(analysis: Analysis, report) -> None:
    """Turn findings into refinements on the derivation report.

    Confidence is `population` for every one of them, a class of its own alongside sound,
    heuristic and guess. Those three are claims about the *schema*, which does not change when
    somebody inserts a row. This one is a claim about the data, and it can go stale.
    """
    # One function per finding kind, called in the order the report has always listed
    # them: the report sorts refinements by confidence and rule and is stable within
    # a rule, so the order here is the order a reader sees.
    _report_inclusion(analysis, report)
    _report_inclusion_1to1(analysis, report)
    _report_value_domain(analysis, report)
    _report_unique(analysis, report)
    _report_junk(analysis, report)
    _report_violated(analysis, report)
    _report_exclusion(analysis, report)
    _report_alternate_key(analysis, report)
    _report_aggregate(analysis, report)
    _report_dependency(analysis, report)
    _report_equality(analysis, report)
    _report_ring(analysis, report)
    _report_computed(analysis, report)
    _report_comparison(analysis, report)
    _report_never_null(analysis, report)


def _report_inclusion(analysis: Analysis, report) -> None:
    proposed = [f for f in analysis.of_kind("inclusion") if f.preferred]
    rejected = [f for f in analysis.of_kind("inclusion") if not f.preferred]

    for f in sorted(proposed, key=lambda x: -x.score):
        report.refine(
            "rule 9d", "population",
            "%s.%s -> %s.%s" % (f.table, f.columns[0], f.target_table, f.target_columns[0]),
            "Every value of %s.%s appears in %s.%s (%s), and %s. Bird's Step 9 subset "
            "constraint (§3.3.9), ranked as the best target for this column."
            % (f.table, f.columns[0], f.target_table, f.target_columns[0], f.evidence,
               "; ".join(SIGNAL_PROSE[s] for s in f.signals) or "nothing else agrees"),
            "Confirm with someone who knows the domain, then declare the foreign key and "
            "re-run. Containment in the current data is evidence, not a constraint: it can "
            "hold by coincidence, and an insert tomorrow can refute it."
            + ("" if f.significant else " This population is too small to rely on."))

    if rejected:
        # One line, not one per candidate. Chinook alone yields 65 of these, and a report
        # nobody finishes reading is the same as no report.
        report.refine(
            "rule 9d", "population", "%d weaker containments" % len(rejected),
            "%d further column pairs are contained but score below the threshold, usually "
            "because the column's name points somewhere else or it is already contained in a "
            "better-matching key. Containment alone runs at about 17%% precision; ranked and "
            "resolved to one target per column it runs at 100%% on the same four databases, "
            "which is why these are counted rather than listed." % len(rejected),
            "Run `python3 reverse/population.py DB` to see them all, if the proposals above "
            "missed something you expected.")


def _report_inclusion_1to1(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("inclusion-1to1"):
        report.refine(
            "rule 9e", "population",
            "%s.%s -> %s.%s" % (f.table, f.columns[0], f.target_table, f.target_columns[0]),
            "%s.%s identifies its own table and every value also appears in %s.%s (%s). That "
            "is the shape of a one-to-one relationship or subtyping -- but it is equally the "
            "shape of two unrelated surrogate sequences, where the shorter nests inside the "
            "longer for no reason at all."
            % (f.table, f.columns[0], f.target_table, f.target_columns[0], f.evidence),
            "Weaker than the other subset findings: check this one against the domain before "
            "anything else. If it is real, rule 7 will read it once the foreign key is "
            "declared.")


def _report_value_domain(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("value-domain"):
        report.refine(
            "rule 6b", "population", "%s.%s in {%s}"
            % (f.table, f.columns[0], ", ".join(repr(v) for v in f.values[:6])
               + (", ..." if len(f.values) > 6 else "")),
            "%s.%s holds only %d distinct value%s across %s. ORM records that as a value "
            "constraint on the value type, which is what tells whoever writes a query that "
            "the code is spelled %r and not something else."
            % (f.table, f.columns[0], f.distinct, "" if f.distinct == 1 else "s", f.evidence,
               f.values[0]),
            "Seen, not permitted: a domain drawn from a population says what is there, never "
            "what is allowed. Declare a CHECK constraint if the set really is closed, and "
            "rule 6 will read it as sound instead."
            + ("" if f.significant else " This population is too small to rely on."))


def _report_unique(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("unique"):
        report.refine(
            "rule 9b", "population", "%s (%s)" % (f.table, ", ".join(f.columns)),
            "No primary key is declared, but %s has no duplicate values (%s), so it is a "
            "candidate identifier. Bird's Step 9 uniqueness constraint (§3.3.9)."
            % (", ".join(f.columns), f.evidence),
            "Confirm and declare the key. Uniqueness in the current population is not "
            "uniqueness."
            + ("" if f.significant else " This population is too small to rely on."))


def _report_junk(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("junk"):
        report.refine(
            "rule 11", "population", f.table,
            "Every non-key column here has at most %d distinct values (%s), and %d rows is no "
            "more than the number of combinations of them. That is the shape of a junk "
            "dimension: low-cardinality flags gathered behind a surrogate key so a fact table "
            "can carry one key instead of several. It has become an entity type, which claims "
            "the business has a concept by this name."
            % (f.distinct, summarise(f.columns), f.rows),
            "If it is a junk dimension, these are attributes of the fact it hangs off, not a "
            "thing in their own right: move the fact types onto the fact and delete the entity "
            "type. If the business really does name this concept, keep it and rename it.")


def _report_violated(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("violated"):
        report.refine(
            "rule 9v", "refuted",
            "%s.%s -> %s.%s" % (f.table, f.columns[0], f.target_table, f.target_columns[0]),
            "This foreign key IS declared, and the data does not satisfy it: %d value%s in "
            "%s.%s appear%s in no row of %s.%s. The only finding here that is proof rather "
            "than evidence -- a counter-example settles it."
            % (f.distinct, "" if f.distinct == 1 else "s", f.table, f.columns[0],
               "s" if f.distinct == 1 else "", f.target_table, f.target_columns[0]),
            "Either the data is wrong or the constraint is. Worth knowing before the model "
            "is trusted: the derivation believed the declaration.")


def _report_exclusion(analysis: Analysis, report) -> None:
    # Pairwise is how it is mined and groups are what a modeller acts on: four pair entries
    # for `given_name, family_name` against `trading_as, abn` say one thing, that this table
    # holds two subtypes. Columns joined by "filled together at least once" are one group;
    # columns in different groups never co-occur.
    by_table: Dict[str, List[Finding]] = {}
    for f in analysis.of_kind("exclusion"):
        by_table.setdefault(f.table, []).append(f)
    for table, fs in by_table.items():
        cols = sorted({c for f in fs for c in f.columns})
        never = {frozenset(f.columns) for f in fs}
        parent = {c: c for c in cols}
        def find(x, parent=parent):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a in cols:                      # union everything NOT excluded from each other
            for b in cols:
                if a < b and frozenset((a, b)) not in never:
                    parent[find(a)] = find(b)
        groups: Dict[str, List[str]] = {}
        for c in cols:
            groups.setdefault(find(c), []).append(c)
        shape = " / ".join("(%s)" % ", ".join(g) for g in groups.values())
        report.refine(
            "rule 9x", "population", "%s %s" % (table, shape),
            "These column groups are never filled together (%s): an ORM **exclusion** "
            "constraint, and the evidence rule 8 does not have -- it reads the same shape off "
            "a column *named* like a type. Groups that never co-occur are subtypes, whatever "
            "the columns are called." % fs[0].evidence,
            "Confirm it, then split the subtypes out and give each a derivation rule over the "
            "discriminator. Write the refutation down as a `violation` query on the "
            "constraint, and `conquer.py --constraints` will keep asking as the data grows.")


def _report_alternate_key(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("alternate-key"):
        report.refine(
            "rule 5b", "population", "%s (%s)" % (f.table, ", ".join(f.columns)),
            "No duplicate values in %s, and this is not the identifier the draft chose: an "
            "**alternate key**, which ORM states as a uniqueness constraint on the role."
            % f.evidence,
            "Confirm it and add the uniqueness constraint. It is not the identity, but it is "
            "what lets a query name an instance by this instead.")

    for values, where in shared_domains(analysis).items():
        report.refine(
            "rule 6d", "population", ", ".join("%s.%s" % w for w in where[:4]),
            "These columns hold exactly the same %d values (%s): one value type read twice. "
            "The derivation gives each column a value type of its own, which says they are "
            "different kinds of thing."
            % (len(values), ", ".join(repr(v) for v in values[:6])),
            "If it is one domain, merge the value types and let both roles play it -- then a "
            "query author cannot ask for a spelling that belongs to the other column.")


def _report_aggregate(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("aggregate"):
        report.refine(
            "rule 9k", "population", "%s.%s = %s" % (f.table, f.columns[0], f.values[0]),
            "Every %s row with children equals %s, over %s. A stored aggregate is a derivation "
            "rule with the derivation thrown away, and the column in any schema most likely to "
            "be quietly stale." % (f.table, f.values[0], f.evidence),
            "If it is a definition, make it a derived fact type whose rule aggregates %s -- "
            "then it cannot drift. Keep the column; the mapping still reads it."
            % f.target_table)


def _report_dependency(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("dependency"):
        report.refine(
            "rule 9h", "population", "%s (%s -> %s)" % (f.table, f.columns[0], f.columns[1]),
            "%s determines %s over %s, and %s is not this table's key: that makes %s a fact "
            "about %s rather than about %s, which is the shape of an entity type the schema "
            "never declared."
            % (f.columns[0], f.columns[1], f.evidence, f.columns[0], f.columns[1],
               f.columns[0], f.table),
            "Confirm it, then lift %s into its own entity type identified by %s, with %s "
            "hanging off it. Rule 2 otherwise hangs both off %s as independent properties, "
            "which says something false about the business."
            % (f.columns[0], f.columns[0], f.columns[1], f.table))


def _report_equality(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("equality"):
        report.refine(
            "rule 9z", "population", "%s (%s, %s)" % (f.table, f.columns[0], f.columns[1]),
            "Always present together and absent together in %s: an ORM **equality** "
            "constraint, the mirror of an exclusion. Two halves of one fact rather than two "
            "independent optional ones." % f.evidence,
            "Confirm it. The difference it states is between 'may be absent' and 'may be half "
            "recorded', and only the second is a bug waiting to happen.")


def _report_ring(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("ring"):
        report.refine(
            "rule 9g", "population", "%s.%s" % (f.table, f.columns[0]),
            "A self-reference that is %s in %s: an ORM **ring** constraint. The catalogue says "
            "only that the column is a foreign key."
            % (" and ".join(f.values), f.evidence),
            "Confirm it. Acyclic is the one worth having: it is what says a reporting line "
            "terminates, and it is what a recursive derivation rule needs in order to.")


def _report_computed(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("computed"):
        report.refine(
            "rule 9f", "population", "%s.%s = %s" % (f.table, f.columns[0], f.values[0]),
            "Every row's %s is exactly %s, over %s. ORM's answer to a stored computation is a "
            "**derivation rule**: the fact is derived rather than asserted, which tells a "
            "query author where the number comes from and stops the two drifting apart."
            % (f.columns[0], f.values[0], f.evidence),
            "If it is a definition rather than a coincidence, replace the fact type with a "
            "derived one whose rule is `LIST x, %s FROM ...` -- and keep the column, since the "
            "mapping still reads it." % f.values[0])


def _report_comparison(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("comparison"):
        report.refine(
            "rule 9y", "population", "%s (%s <= %s)" % (f.table, f.columns[0], f.columns[1]),
            "%s is never greater than %s, over %s: an ORM **value-comparison** constraint, "
            "which no catalogue states and every schema has."
            % (f.columns[0], f.columns[1], f.evidence),
            "Confirm it. A single later row refutes it, which is what makes it worth writing "
            "down as a `violation` query rather than trusting.")


def _report_never_null(analysis: Analysis, report) -> None:
    for f in analysis.of_kind("never-null"):
        report.refine(
            "rule 9a", "population", "%s.%s" % (f.table, f.columns[0]),
            "Declared nullable but never null in %s, so the role may be mandatory. Bird's "
            "Step 9 (§3.3.9)." % f.evidence,
            "Confirm before making the role mandatory; a single later insert refutes it."
            + ("" if f.significant else " This population is too small to rely on."))


def main(argv=None):
    import argparse
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import catalog as catalog_mod

    global MIN_ROWS
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sqlite")
    p.add_argument("--min-rows", type=int, default=MIN_ROWS)
    args = p.parse_args(argv)

    MIN_ROWS = args.min_rows
    conn = sqlite3.connect(args.sqlite)
    cat = catalog_mod.from_sqlite(args.sqlite)
    a = analyse(conn, cat)

    print("%d tables, %d rows in total"
          % (len(a.row_counts), sum(a.row_counts.values())))
    for kind, label in (("junk", "tables shaped like junk dimensions"),
                        ("violated", "DECLARED foreign keys the data contradicts (proof)"),
                        ("inclusion", "candidate foreign keys (subset constraints)"),
                        ("inclusion-1to1", "candidate 1:1 / subtype links (weaker)"),
                        ("unique", "candidate identifiers"),
                        ("never-null", "candidate mandatory roles"),
                        ("value-domain", "candidate value constraints")):
        found = a.of_kind(kind)
        if kind == "inclusion":
            found = sorted(found, key=lambda x: (not x.preferred, -x.score))
        print("\n%s: %d" % (label, len(found)))
        for f in found:
            mark = " *" if getattr(f, "preferred", False) else "  "
            if kind.startswith("inclusion") or kind == "violated":
                print("%s %-32s -> %-24s %s"
                      % (mark, "%s.%s" % (f.table, f.columns[0]),
                         "%s.%s" % (f.target_table, f.target_columns[0]), f.evidence))
            elif kind == "value-domain":
                print("%s %-32s %-22s %s"
                      % (mark, "%s.%s" % (f.table, f.columns[0]),
                         f.evidence, summarise([repr(v) for v in f.values], limit=5)))
            else:
                print("%s %-32s %s" % (mark, "%s (%s)" % (f.table, summarise(f.columns)),
                                       f.evidence))
        if kind == "inclusion" and any(x.preferred for x in found):
            print("  * = proposed: best-scoring target for that column, above the threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# --------------------------------------------------------------------------- vertical partitions

#  How many rows a partition may be short of its parent and still count as covering it. A
#  vertical partition is written by the same INSERT as its parent, so in practice it is exact;
#  the tolerance is for a handful of rows lost to a failed backfill, not for a real subtype.
COVERAGE = 0.995


def partitions(conn: sqlite3.Connection, catalog, tables=None) -> List[tuple]:
    """Which rule 7 subtype candidates are vertical partitioning rather than subtyping.

    The two are indistinguishable in the catalogue -- both are a table whose whole primary key
    is a foreign key to another table's whole primary key, one to one. Only the population
    separates them, and it separates them cleanly:

      a subtype holds a *proper* subset of its supertype, and sibling subtypes are usually
      disjoint -- a Party is a Person or an Organisation, not both;

      a vertical partition holds *every* instance, because it is the same row's other columns
      stored in a second table.

    Returns one tuple per candidate: (child, parent, child rows, parent rows, is_partition).
    Candidates with no rows to measure are returned with `is_partition` False -- an empty
    database is not evidence of subtyping, but it is not evidence against it either, and the
    subtype reading is the one rule 7 already makes.
    """
    out = []
    by_name = {t.name.casefold(): t for t in (tables or catalog.tables)}
    for table in (tables or catalog.tables):
        if table.is_view or not table.primary_key:
            continue
        covering = [fk for fk in table.foreign_keys
                    if all(table.is_key(c) for c in fk.columns)]
        if len(covering) != 1:
            continue
        fk = covering[0]
        if {c.casefold() for c in fk.columns} != {c.casefold() for c in table.primary_key}:
            continue
        parent = by_name.get(fk.ref_table.casefold())
        if parent is None or {c.casefold() for c in fk.ref_columns} != \
                {c.casefold() for c in parent.primary_key}:
            continue
        try:
            child_n = conn.execute("SELECT count(*) FROM %s" % _t(table.name)).fetchone()[0]
            parent_n = conn.execute("SELECT count(*) FROM %s" % _t(parent.name)).fetchone()[0]
        except sqlite3.Error:
            continue
        covers = bool(parent_n) and child_n >= parent_n * COVERAGE
        out.append((table.name, parent.name, child_n, parent_n, covers))
    return out


def prefer_referenced_keys(conn: sqlite3.Connection, catalog, tables=None) -> List[tuple]:
    """Identify an instance by the column the rest of the schema refers to it by.

    Rule 1 takes the primary key as the reference scheme, and nearly always that is also the
    column every foreign key points at. Where it is not, the schema is saying two different
    things: `orders` declares `orderspivot`, a row number nothing mentions, and three tables
    reference `orders.recordvault`. An order is known everywhere outside its own table by its
    vault code, a question asking for "the order ID" means the vault code, and the model
    answered with the row number (LiveSQLBench crypto_4).

    So: a single-column primary key that no foreign key references, beside exactly one other
    column that foreign keys do. A foreign key must reference a candidate key -- PostgreSQL
    refuses one that does not -- but SQLite checks nothing and a quarter of declared foreign
    keys are contradicted by their rows, so the claim is verified rather than assumed: never
    null, never repeated. Where it holds, the catalogue is rewritten before the derivation,
    which is the whole change -- the referenced column becomes the key, the declared key
    becomes a UNIQUE column beside it, and rule 5 states it as the second identifier it is.

    It changes the model rather than adding to it, like rules 7b and 9c: a bare `Order` now
    lists vault codes. And it is not always what an author means. BIRD's `cards` is keyed by
    `id` and referenced by `uuid`, and its questions asking for a card's id mean `id`. Opt-in
    for both reasons. Returns (table, declared key, referenced column, referrers, evidence).
    """
    applied = []
    every = list(tables or catalog.tables)
    targets: Dict[str, Dict[str, List[str]]] = {}
    for t in every:
        for fk in t.foreign_keys:
            if len(fk.columns) == 1 and len(fk.ref_columns or []) == 1 and fk.ref_columns[0]:
                targets.setdefault(fk.ref_table.casefold(), {}).setdefault(
                    fk.ref_columns[0].casefold(), []).append("%s.%s" % (t.name, fk.columns[0]))
    for t in every:
        if t.is_view or len(t.primary_key) != 1 or t.fk_for(t.primary_key[0]) is not None:
            continue
        referenced = targets.get(t.name.casefold(), {})
        key = t.primary_key[0]
        if key.casefold() in referenced or len(referenced) != 1:
            continue                # the key is what is referenced, or the references disagree
        col = t.column(next(iter(referenced)))
        if col is None or t.fk_for(col.name) is not None:
            continue
        try:
            n, d, nulls = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT %s), SUM(%s IS NULL) FROM %s"
                % (_q([col.name]), _q([col.name]), _t(t.name))).fetchone()
        except sqlite3.Error:
            continue
        if not n or d != n or nulls:
            continue
        t.primary_key = [col.name]
        col.nullable = False
        if not any([c.casefold() for c in u] == [key.casefold()] for u in t.uniques):
            t.uniques.append([key])
        applied.append((t.name, key, col.name, referenced[col.name.casefold()],
                        "%d distinct over %d rows, none absent" % (d, n)))
    return applied
