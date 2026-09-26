#!/usr/bin/env python3
"""Laws a query language obeys whatever the schema, checked over generated paths.

The cases in `test_operators.py` assert what someone thought to assert. These assert
relations that must hold *between* queries the compiler itself produces, over paths walked
at random through whatever model it is given, with literals drawn from the data:

    monotone      COUNT(T [P]) <= COUNT(T)
    complement    COUNT(T [P]) + COUNT(T BUT NOT P) = COUNT(T)
    conjunction   COUNT(T [P] [Q]) <= COUNT(T [P]) and <= COUNT(T [Q])
    commutative   COUNT(T [P] [Q]) = COUNT(T [Q] [P])
    inclusion     COUNT(T [P OR OTHERWISE Q]) = COUNT(T[P]) + COUNT(T[Q]) - COUNT(T [P] [Q])
    distinct      DISTINCT COUNT OF P <= COUNT OF P
    grain         the grouped counts of a path sum to the count of that path
    domain        COUNT(T [has V: v]) summed over V's values = COUNT(T [has V])
    subtype       COUNT(Sub) <= COUNT(Super)
    extremes      THE MINIMUM of a path = the first value of that path ordered ascending
    listed        COUNT of a path = how many rows listing it returns; likewise SUM
    listdistinct  DISTINCT COUNT of a path = how many rows LIST ... FROM DISTINCT returns
    denotation    T <path>: 'v' = T <path> x WHERE x = 'v'
    ordering      ordering a list permutes it and drops nothing
    limit         THE FIRST n of an ascending list = the n smallest values
    setop         (T [P] listed) UNITED WITH (T BUT NOT P listed) = the whole, listed

Neither side of any of these is a reference answer: both are the compiler's own output, and
a violation says the two disagree, so one of them is wrong. That is the shape of nearly
every silent wrong answer the blind pilot found -- a conjunct dropped from a filter, a
grouped aggregate over a cross product, a join to the wrong column, a subtype that did not
narrow. Each of those is an arithmetic contradiction here, found in seconds, rather than a
plausible number in an answer file that only a careful reader would doubt.

A generated query the compiler *refuses* is not a failure: the generator knows the shape of
the schema, not the whole language, and a refusal is the compiler doing its job. Refusals
are counted and shown with -v so a generator that has stopped producing anything useful is
visible. Any other exception is a failure, because a law's operands must compile or be
refused, never crash.

    test_metamorphic.py --model M --db D [--cases N] [--seed S] [--only LAW] [-v]
"""

import argparse
import collections
import json
import os
import random
import signal
import sqlite3
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
# run-tests.sh builds the fixture in the repository root, not beside the tests
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))

import ccm                          # noqa: E402
import conquer as driver            # noqa: E402
import parser as parser_mod         # noqa: E402
import sql as sql_mod               # noqa: E402
import reference as ref_mod         # noqa: E402

REFUSALS = (parser_mod.ParseError, parser_mod.Ambiguous, sql_mod.SqlError)
# How long one generated query may run before it is abandoned and counted as refused rather
# than failed. Thirty seconds suits an indexed schema; several of Spider 2.0's local databases
# declare no index at all, where a filter that becomes an EXISTS scans the whole table once
# per row, and there `--timeout 3` is the difference between a sweep and an afternoon. A query
# too slow to finish is a performance artefact, never a soundness signal.
TIMEOUT = 30


class Refused(Exception):
    """The compiler declined a generated query. Not a finding."""


def _cell(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, str):
        try:
            arr = json.loads(v)
            if isinstance(arr, list):
                return json.dumps(sorted(arr, key=lambda x: (x is None, str(x))))
        except ValueError:
            pass
    return v


def _canon(rows):
    """Rows as a sorted multiset, cells normalised the way `test_reference.py` does."""
    return sorted((tuple(_cell(c) for c in r) for r in rows),
                  key=lambda r: tuple((c is None, str(c)) for c in r))


class Schema:
    """The model as a graph of forward readings, plus the data behind each role."""

    def __init__(self, model, conn):
        self.model, self.conn = model, conn
        self.concepts = {c["id"]: c for c in model["concepts"]}
        self.role_map = {m["role"]: m for m in model["mapping"]["roleMap"]}
        self.columns = {c["id"]: c for c in model["mapping"]["columns"]}
        self.tables = {t["id"]: t for t in model["mapping"]["tables"]}
        self.player = {}
        for c in model["concepts"]:
            for r in c.get("roles", []):
                self.player[r["id"]] = r["player"]
        # concept -> [(verb, target concept, the target's role)] for readings in role order.
        # Only forward readings: the inverse needs a verb the model does not always carry.
        self.steps = collections.defaultdict(list)
        self.source_role = {}            # a step's target role -> the role it was entered on
        for c in model["concepts"]:
            if c.get("kind") != "fact" or len(c.get("roles", [])) != 2:
                continue
            for rd in c.get("readings", []):
                text = rd.get("text", "")
                if "{0}" not in text or "{1}" not in text:
                    continue
                if text.index("{0}") > text.index("{1}"):
                    continue                      # an inverse reading: no forward verb here
                verb = ccm.unbind(text[text.index("{0}") + 3:text.index("{1}")])
                if not verb:
                    continue
                seq = rd.get("roleSequence") or [r["id"] for r in c["roles"]]
                if len(seq) != 2:
                    continue
                self.steps[self.player[seq[0]]].append((verb, self.player[seq[1]], seq[1]))
                self.source_role[seq[1]] = seq[0]
        self.entities = sorted(cid for cid, c in self.concepts.items()
                               if c.get("kind") == "entity" and self.steps.get(cid))
        self._values = {}

    def name(self, cid):
        return self.concepts[cid]["name"]

    def is_value(self, cid):
        return self.concepts[cid].get("kind") == "value"

    def values_of(self, role_id, limit=200):
        """Distinct values the data holds for a role, read straight from its column so the
        literals a filter is built from do not come from the compiler under test."""
        if role_id in self._values:
            return self._values[role_id]
        out = []
        entry = self.role_map.get(role_id)
        if entry and len(entry.get("columns", [])) == 1:
            col = self.columns[entry["columns"][0]]
            table = self.tables[entry["table"]]["name"]
            try:
                rows = self.conn.execute(
                    'SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL LIMIT %d'
                    % (col["name"], table, col["name"], limit)).fetchall()
                out = [r[0] for r in rows]
            except sqlite3.Error:
                out = []
        self._values[role_id] = out
        return out

    def literal(self, cid, role_id, rng):
        """A ConQuer literal for one of the values the data actually holds, or None."""
        vals = [v for v in self.values_of(role_id)
                if not isinstance(v, bytes) and "'" not in str(v) and str(v).strip() != ""]
        if not vals:
            return None
        v = rng.choice(vals)
        kind = (self.concepts[cid].get("dataType") or {}).get("name", "")
        numeric = any(k in kind.lower() for k in ("int", "real", "num", "dec", "float"))
        if numeric:
            try:
                float(v)
                return str(v)
            except (TypeError, ValueError):
                pass
        return "'%s'" % str(v)

    def walk(self, head, rng, depth):
        """A chain of forward steps from `head`: [(verb, target concept, role)]."""
        chain, here = [], head
        for _ in range(depth):
            options = self.steps.get(here) or []
            if not options:
                break
            verb, to, role = rng.choice(options)
            chain.append((verb, to, role))
            here = to
            if self.is_value(to):
                break
        return chain

    def chain_text(self, chain):
        return " ".join("%s %s" % (verb, self.name(to)) for verb, to, _ in chain)


class Runner:
    def __init__(self, model, conn, timeout=TIMEOUT):
        self.model, self.conn = model, conn
        self.timeout = timeout
        self.lex = parser_mod.Lexicon(model)
        self.em = sql_mod.Emitter(model)
        self.cache = {}
        self.refusals = 0
        self.refused = []            # a sample, so a degraded generator is visible with -v
        # --reference: every generated query the compiler answers is also put to the
        # reference interpreter, so the laws double as a differential test over queries
        # nobody wrote. Compiler-with-compiler laws cannot see a defect both sides share;
        # this can.
        self.ref = None
        self.ref_agree = self.ref_differ = self.ref_outside = 0
        self.ref_diffs = []

    def rows(self, text):
        if text in self.cache:
            got = self.cache[text]
            if isinstance(got, Refused):
                raise got
            return got
        try:
            _, statement, params = driver.transpile(self.model, text, self.lex, self.em)
        except REFUSALS as e:
            self.refusals += 1
            if len(self.refused) < 8:
                self.refused.append("%s   %s: %s" % (text[:70], type(e).__name__, str(e)[:70]))
            self.cache[text] = Refused("%s: %s" % (type(e).__name__, e))
            raise self.cache[text]
        end = time.time() + self.timeout
        self.conn.set_progress_handler(lambda: 1 if time.time() > end else 0, 20000)
        try:
            out = self.conn.execute(statement, params).fetchall()
        except sqlite3.Error as e:
            self.refusals += 1
            self.cache[text] = Refused("sqlite: %s" % e)
            raise self.cache[text]
        finally:
            self.conn.set_progress_handler(None, 0)
        self.cache[text] = out
        if self.ref is not None:
            self.check_reference(text, out)
        return out

    def check_reference(self, text, out):
        def bell(*_):
            raise TimeoutError()
        signal.signal(signal.SIGALRM, bell)
        signal.alarm(max(1, int(self.timeout)))
        try:
            want = self.ref.query(parser_mod.Parser(self.lex, text).parse_query())
        except (ref_mod.Unsupported, TimeoutError):
            self.ref_outside += 1
            return
        finally:
            signal.alarm(0)
        got, want = _canon(out), _canon(want)
        if got == want:
            self.ref_agree += 1
        else:
            self.ref_differ += 1
            if len(self.ref_diffs) < 12:
                self.ref_diffs.append((text, got[:3], want[:3]))

    def count(self, text):
        out = self.rows(text)
        if len(out) != 1 or len(out[0]) != 1 or out[0][0] is None:
            raise Refused("not a single number: %r" % (out[:2],))
        return out[0][0]


# -- the laws ----------------------------------------------------------------------------
# Each takes (schema, runner, rng) and returns (name, ok, detail) or None when this draw
# produced nothing to test.

def law_monotone(s, run, rng):
    t, f = draw_filter(s, rng)
    if f is None:
        return None
    whole, part = run.count("THE COUNT OF %s" % t), run.count("THE COUNT OF %s [%s]" % (t, f))
    return ("a filter never adds rows", part <= whole,
            "%s [%s]: %d of %d" % (t, f, part, whole))


def law_complement(s, run, rng):
    t, f = draw_filter(s, rng)
    if f is None:
        return None
    whole = run.count("THE COUNT OF %s" % t)
    yes = run.count("THE COUNT OF %s [%s]" % (t, f))
    no = run.count("THE COUNT OF %s BUT NOT %s" % (t, f))
    return ("a filter and its complement partition the type", yes + no == whole,
            "%s [%s]: %d + %d = %d, whole %d" % (t, f, yes, no, yes + no, whole))


def law_conjunction(s, run, rng):
    t, f, g = draw_two_filters(s, rng)
    if f is None:
        return None
    both = run.count("THE COUNT OF %s [%s] [%s]" % (t, f, g))
    a = run.count("THE COUNT OF %s [%s]" % (t, f))
    b = run.count("THE COUNT OF %s [%s]" % (t, g))
    return ("a conjunction is no larger than either side", both <= a and both <= b,
            "%s [%s] [%s]: %d, sides %d and %d" % (t, f, g, both, a, b))


def law_commutative(s, run, rng):
    t, f, g = draw_two_filters(s, rng)
    if f is None:
        return None
    one = run.count("THE COUNT OF %s [%s] [%s]" % (t, f, g))
    two = run.count("THE COUNT OF %s [%s] [%s]" % (t, g, f))
    return ("two filters commute", one == two,
            "%s: [%s] [%s] = %d, reversed %d" % (t, f, g, one, two))


def law_inclusion(s, run, rng):
    t, f, g = draw_two_filters(s, rng)
    if f is None:
        return None
    either = run.count("THE COUNT OF %s [%s OR OTHERWISE %s]" % (t, f, g))
    a = run.count("THE COUNT OF %s [%s]" % (t, f))
    b = run.count("THE COUNT OF %s [%s]" % (t, g))
    both = run.count("THE COUNT OF %s [%s] [%s]" % (t, f, g))
    return ("inclusion and exclusion", either == a + b - both,
            "%s: either %d, %d + %d - %d = %d" % (t, either, a, b, both, a + b - both))


def law_distinct(s, run, rng):
    t, f = draw_filter(s, rng)
    if f is None:
        return None
    head = next((c for c in s.entities if s.name(c) == t), None)
    if head and len(s.concepts[head].get("identifier") or []) > 1:
        return None          # identified by several columns: a distinct count of it has none
    plain = run.count("THE COUNT OF %s [%s]" % (t, f))
    distinct = run.count("THE DISTINCT COUNT OF %s [%s]" % (t, f))
    return ("a distinct count is no larger", distinct <= plain,
            "%s [%s]: distinct %d, plain %d" % (t, f, distinct, plain))


def law_grain(s, run, rng):
    """The grouped counts of a path sum to the count of the same path. A grouped aggregate
    whose operand ranges independently of the group makes a cross product, and the sum then
    exceeds the total: the shape of the primer's own example 19 (finding 30)."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    grouped = run.rows("LIST v, c FROM %s x %s v AND ALSO THE COUNT OF x GROUPED BY v AS c"
                       % (t, path))
    total = run.count("THE COUNT OF %s %s" % (t, path))
    summed = sum(r[1] for r in grouped if r[1] is not None)
    return ("grouped counts sum to the whole", summed == total,
            "%s %s: groups %d summing to %d, whole %d" % (t, path, len(grouped), summed, total))


def law_domain(s, run, rng):
    """Every value of a value type, counted separately, adds up to the whole walk. Catches a
    denotation that matches nothing and a filter that matches too much.

    Both sides count rows of the same walk, not heads: a bracket is a semijoin and would
    dedupe the head, while the per-value counts are per pair, so on a one-to-many step the
    two grains differ for a good reason and the law would be testing the wrong thing."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    role = chain[-1][2]
    vals = s.values_of(role, limit=30)
    if not vals or len(vals) > 25:
        return None
    t, path = s.name(head), s.chain_text(chain)
    whole = run.count("THE COUNT OF %s %s" % (t, path))
    total = 0
    for v in vals:
        lit = literal_for(s, chain[-1][1], v)
        if lit is None:
            return None
        total += run.count("THE COUNT OF %s %s: %s" % (t, path, lit))
    return ("a value type's domain partitions the walk", total == whole,
            "%s %s: %d values summing to %d, whole %d" % (t, path, len(vals), total, whole))


def _listable(s, run, t, path, cap=4000):
    """A walk small enough to list, or None. The laws below compare a whole result against an
    aggregate over it, so they have to read every row; on a warehouse table that is not a
    test, it is a scan."""
    try:
        n = run.count("THE COUNT OF %s %s" % (t, path))
    except Refused:
        return None
    return n if 0 < n <= cap else None


def _numeric(s, cid, role_id=None):
    """Is this value type a number, as the *data* has it?

    The declared type is not enough. SQLite gives a column declared DATE numeric affinity, so
    `drivers_ext.dob` arrives typed `num` and holds '1950-10-12'; SUM over it coerces the
    leading digits and returns a year total, while adding the listed values in Python returns
    nothing. The law would have been comparing two wrong answers. Where the data is to hand,
    it decides.
    """
    kind = (s.concepts[cid].get("dataType") or {}).get("name", "")
    if not any(k in kind.lower() for k in ("int", "real", "num", "dec", "float", "double")):
        return False
    if role_id is None:
        return True
    seen = [v for v in s.values_of(role_id) if v is not None]
    return bool(seen) and all(isinstance(v, (int, float)) for v in seen)


def law_extremes(s, run, rng):
    """The aggregate and the ordering are different code paths to the same value, and a query
    author uses them interchangeably: `THE MINIMUM x` against `ORDERED WITH x THE FIRST 1`."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    if _listable(s, run, t, path) is None:
        return None
    low = run.count("THE MINIMUM %s %s" % (t, path))
    high = run.count("THE MAXIMUM %s %s" % (t, path))
    first = run.rows("LIST v FROM %s %s v ORDERED WITH v ASCENDING THE FIRST 1" % (t, path))
    last = run.rows("LIST v FROM %s %s v ORDERED WITH v DESCENDING THE FIRST 1" % (t, path))
    ok = bool(first) and bool(last) and first[0][0] == low and last[0][0] == high
    return ("the extremes are the ends of the ordering", ok,
            "%s %s: minimum %r first %r, maximum %r last %r"
            % (t, path, low, first[0][0] if first else None, high, last[0][0] if last else None))


def law_listed(s, run, rng):
    """An aggregate over a path counts, or adds up, exactly what listing that path returns."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    n = _listable(s, run, t, path)
    if n is None:
        return None
    listed = run.rows("LIST v FROM %s %s v" % (t, path))
    if len(listed) != n:
        return ("an aggregate counts what listing returns", False,
                "%s %s: count %d, listed %d" % (t, path, n, len(listed)))
    if not _numeric(s, chain[-1][1], chain[-1][2]):
        return ("an aggregate counts what listing returns", True,
                "%s %s: %d rows" % (t, path, n))
    total = run.count("THE SUM OF %s %s" % (t, path))
    added = sum(r[0] for r in listed if isinstance(r[0], (int, float)))
    # Section 14b: a value fixed by a node the path reaches is added once per instance of
    # that node, not once per row. When a step before the last fans out and the last is
    # functional, the walk can put one value on many rows, and what SUM must equal is the
    # listed (determinant, value) pairs added with the duplicates removed. Listing the
    # determinant beside the value is the query language's own way to say that.
    fans_before = any(not run.lex.is_functional(s.source_role[role]) for _, _, role in chain[:-1])
    if fans_before and run.lex.is_functional(s.source_role[chain[-1][2]]):
        verb, to, _ = chain[-1]
        pairs = run.rows("LIST k, v FROM %s %s k %s %s v"
                         % (t, s.chain_text(chain[:-1]), verb, s.name(to)))
        once = sum(v for _, v in set(pairs) if isinstance(v, (int, float)))
        return ("an aggregate adds each determined value once (14b)",
                abs((total or 0) - once) <= max(1e-6, abs(once) * 1e-9),
                "%s %s: sum %r, listed adds to %r, once per determinant %r"
                % (t, path, total, added, once))
    return ("an aggregate counts and adds what listing returns",
            abs((total or 0) - added) <= max(1e-6, abs(added) * 1e-9),
            "%s %s: sum %r, listed adds to %r" % (t, path, total, added))


def law_listdistinct(s, run, rng):
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    if _listable(s, run, t, path) is None:
        return None
    n = run.count("THE DISTINCT COUNT OF %s %s" % (t, path))
    listed = run.rows("LIST v FROM DISTINCT %s %s v" % (t, path))
    return ("a distinct count counts what a distinct list returns", n == len(listed),
            "%s %s: distinct count %d, listed %d" % (t, path, n, len(listed)))


def law_denotation(s, run, rng):
    """`has V: 'x'` and `has V x WHERE x = 'x'` are the same restriction said two ways. The
    first expands through the type's reference scheme, which is where a literal compared
    against a numeric identifier used to match nothing at all."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    lit = s.literal(chain[-1][1], chain[-1][2], rng)
    if lit is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    try:
        a = run.count("THE COUNT OF %s %s: %s" % (t, path, lit))
        b = run.count("THE COUNT OF %s %s x WHERE x = %s" % (t, path, lit))
    except Refused:
        return None
    return ("a denotation is a comparison", a == b,
            "%s %s: denoted %d, compared %d" % (t, path, a, b))


def law_ordering(s, run, rng):
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    if _listable(s, run, t, path, cap=2000) is None:
        return None
    plain = run.rows("LIST v FROM %s %s v" % (t, path))
    order = run.rows("LIST v FROM %s %s v ORDERED WITH v ASCENDING" % (t, path))
    return ("ordering permutes a list and drops nothing",
            sorted(map(repr, plain)) == sorted(map(repr, order)),
            "%s %s: %d rows, %d ordered" % (t, path, len(plain), len(order)))


def law_limit(s, run, rng):
    """The first n of an ascending order are the n smallest values. True with ties, where
    which *rows* come back is the database's choice but the multiset of values is not."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    n = _listable(s, run, t, path, cap=2000)
    if n is None or n < 3:
        return None
    k = rng.randint(1, min(n - 1, 5))
    whole = run.rows("LIST v FROM %s %s v" % (t, path))
    firsts = run.rows("LIST v FROM %s %s v ORDERED WITH v ASCENDING THE FIRST %d" % (t, path, k))
    want = sorted((r[0] for r in whole), key=_sqlite_order)[:k]
    return ("the first n of an ordering are the n smallest",
            sorted(map(repr, (r[0] for r in firsts))) == sorted(map(repr, want)),
            "%s %s: first %d of %d rows" % (t, path, k, n))


def _sqlite_order(v):
    """Sort the way the database does, so the oracle is the database's own rule rather than
    Python's. SQLite orders by storage class first -- NULL, then numbers, then text, then
    blobs -- and only then by value. A column holding both a number and a string is legal
    there and is not sortable in Python at all: AdventureWorks has one, and the law that
    checks `THE FIRST n` of an ascending order crashed on it rather than failing."""
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (1, int(v))
    if isinstance(v, (int, float)):
        return (1, v)
    if isinstance(v, str):
        return (2, v)
    return (3, v)


def law_setop(s, run, rng):
    """Section 6.2's union against section 6.4's Fr: a filter and its complement, listed and
    united, are the whole population listed."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None
    t, path = s.name(head), s.chain_text(chain)
    if _listable(s, run, t, path, cap=2000) is None:
        return None
    f = draw_filter_on(s, rng, head)
    if f is None:
        return None
    # the negated operand goes last: `BUT NOT <descriptor>` takes a whole descriptor, so a
    # chain written after it is swallowed into the operand and means something else
    try:
        united = run.rows("(LIST v FROM %s [%s] %s v) UNITED WITH "
                          "(LIST v FROM %s %s v BUT NOT %s)" % (t, f, path, t, path, f))
    except Refused:
        return None
    whole = run.rows("LIST v FROM DISTINCT %s %s v" % (t, path))
    return ("a filter and its complement unite to the whole",
            {repr(r[0]) for r in united} == {repr(r[0]) for r in whole},
            "%s %s [%s]: united %d, whole %d" % (t, path, f, len(united), len(whole)))


def law_subtype(s, run, rng):
    subs = [c for c in s.model["concepts"] if c.get("supertypes") and c.get("kind") != "fact"]
    if not subs:
        return None
    c = rng.choice(subs)
    sup = s.concepts.get(c["supertypes"][0])
    if sup is None:
        return None
    a = run.count("THE COUNT OF %s" % c["name"])
    b = run.count("THE COUNT OF %s" % sup["name"])
    return ("a subtype is no larger than its supertype", a <= b,
            "%s %d of %s %d" % (c["name"], a, sup["name"], b))


LAWS = [law_monotone, law_complement, law_conjunction, law_commutative, law_inclusion,
        law_distinct, law_grain, law_domain, law_subtype,
        law_extremes, law_listed, law_listdistinct, law_denotation, law_ordering,
        law_limit, law_setop]


# -- drawing -----------------------------------------------------------------------------

def literal_for(s, cid, v):
    if isinstance(v, bytes) or "'" in str(v) or str(v).strip() == "":
        return None
    kind = (s.concepts[cid].get("dataType") or {}).get("name", "")
    if any(k in kind.lower() for k in ("int", "real", "num", "dec", "float")):
        try:
            float(v)
            return str(v)
        except (TypeError, ValueError):
            pass
    return "'%s'" % str(v)


def draw_value_chain(s, rng, tries=12):
    """A head entity and a chain of forward steps ending on a value type."""
    for _ in range(tries):
        if not s.entities:
            return None, None
        head = rng.choice(s.entities)
        chain = s.walk(head, rng, rng.randint(1, 3))
        if chain and s.is_value(chain[-1][1]):
            return head, chain
    return None, None


def draw_filter_on(s, rng, head, tries=8):
    """A filter body on this head, binding nothing. Drawing one for a different head and
    using it here is how a generator produces nonsense the compiler is right to refuse."""
    for _ in range(tries):
        chain = s.walk(head, rng, rng.randint(1, 3))
        if not chain or not s.is_value(chain[-1][1]):
            continue
        lit = s.literal(chain[-1][1], chain[-1][2], rng)
        if lit:
            return "%s: %s" % (s.chain_text(chain), lit)
    return None


def draw_filter(s, rng):
    """(head type name, a filter body that binds nothing)."""
    head, chain = draw_value_chain(s, rng)
    if head is None:
        return None, None
    lit = s.literal(chain[-1][1], chain[-1][2], rng)
    if lit is None:
        return None, None
    return s.name(head), "%s: %s" % (s.chain_text(chain), lit)


def draw_two_filters(s, rng, tries=10):
    """Two filters on the same head, different value types where the schema allows."""
    for _ in range(tries):
        t, f = draw_filter(s, rng)
        if f is None:
            continue
        for _ in range(tries):
            head = [c for c in s.entities if s.name(c) == t]
            if not head:
                break
            chain = s.walk(head[0], rng, rng.randint(1, 3))
            if not chain or not s.is_value(chain[-1][1]):
                continue
            lit = s.literal(chain[-1][1], chain[-1][2], rng)
            g = "%s: %s" % (s.chain_text(chain), lit) if lit else None
            if g and g != f:
                return t, f, g
    return None, None, None


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=os.path.join(WORK, "company.ccm.json"))
    p.add_argument("--db", default=os.path.join(WORK, "company.sqlite"))
    p.add_argument("--cases", type=int, default=40, help="draws per law")
    p.add_argument("--timeout", type=float, default=TIMEOUT,
                   help="seconds one generated query may run before it is abandoned")
    p.add_argument("--seed", type=int, default=20260912)
    p.add_argument("--only")
    p.add_argument("--reference", action="store_true",
                   help="also evaluate every generated query with the reference interpreter")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    model = json.load(open(args.model))
    conn = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    s = Schema(model, conn)
    run = Runner(model, conn, args.timeout)
    if args.reference:
        run.ref = ref_mod.Reference(model, conn, run.lex)

    passed = failed = drawn = 0
    for law in LAWS:
        label = law.__name__[4:]
        if args.only and args.only.lower() not in label.lower():
            continue
        # crc32, not hash(): PYTHONHASHSEED is random per process, so hash(label) made
        # every run draw a different set of queries -- a printed seed reproduced nothing.
        rng = random.Random(args.seed + zlib.crc32(label.encode()) % 10000)
        for _ in range(args.cases):
            try:
                got = law(s, run, rng)
            except Refused:
                continue
            if got is None:
                continue
            name, ok, detail = got
            drawn += 1
            if ok:
                passed += 1
                if args.verbose:
                    print("ok    %-46s %s" % (name, detail))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, detail))

    print("\n%d passed, %d failed, %d total (%d generated queries the compiler refused)"
          % (passed, failed, drawn, run.refusals))
    if args.reference:
        print("reference: %d generated queries agree, %d DIFFER, %d outside its scope"
              % (run.ref_agree, run.ref_differ, run.ref_outside))
        for text, got, want in run.ref_diffs:
            print("DIFF  %s\n        compiler  %s\n        reference %s"
                  % (text[:120], str(got)[:110], str(want)[:110]))
        failed += run.ref_differ
    if args.verbose and run.refused:
        print("refused, a sample:")
        for r in run.refused:
            print("  " + r)
    if drawn == 0:
        print("nothing was drawn: the generator found no usable path in this model")
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
