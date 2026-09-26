"""ConQuer-92 surface parser.

The grammar is appendix B of the report (arXiv:2105.11926;
conquer/conquer-2026-grammar.ebnf is the grammar as implemented), and the
keyword table there is reproduced below verbatim. The parser is schema-driven, as
appendix B requires: a mix-fix predicate verbalisation is only a verb part plus an
information descriptor, and which fact type a verb part names can only be decided by looking
at the schema and at what the path has reached so far.

Report section 7 calls this out as an ambiguous grammar. This parser resolves ambiguity by
filtering candidate fact types against the current head's type, then against the type named
next, and raises Ambiguous when more than one candidate survives -- it never guesses silently.

Supported subset (see conquer/README.md for the full list of what is not here):
    LIST <items> FROM <descriptor>          bare <descriptor> also parses
    Type, Type var, Type: denotation        type specification with instance reference
    <path> <verb part> <path>               mix-fix predicate verbalisation
    AND ALSO / OR OTHERWISE / BUT NOT       FrSetOper
    UNITED WITH / INTERSECTED WITH / MINUS  SetOper
    WHICH ARE ALL IN / THAT INCLUDES ALL / MATCHING ALL / EXCLUDING
    = <> < <= > >= and their word forms     ValueComp
    WHERE <condition>, AND / OR / NOT / SOME
    THE COUNT OF / SUM OF / MINIMUM / MAXIMUM / AVERAGE, and DISTINCT COUNT/SUM
    [ ... ] sub-expression, ( ... ) grouping
    DISTINCT, ORDERED [WITH] ...
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.ccm import Index                                            # noqa: E402


class ParseError(Exception):
    pass


class MacroError(ParseError):
    """A macro invocation that cannot be expanded: recursive, or the wrong arity. Raised
    through the projection-list retry, which swallows ordinary parse errors."""


class Ambiguous(ParseError):
    pass


class Judgement(ParseError):
    """A refusal that is a claim about *meaning* rather than a failure to parse: a fan trap,
    a value equated with an instance, a node joined to nothing.

    Its own class because `--permissive` exists to suppress exactly these, and the test that
    holds the compiler to that was matching five hand-copied message fragments -- so the next
    judgement added would have been unmeasured and nothing would have said so. Raised only by
    `Lowering.refuse`."""


# --------------------------------------------------------------------------- AST

@dataclass
class TypeSpec:
    concept: str
    var: Optional[str] = None
    denotation: Optional[object] = None


@dataclass
class Predicate:
    """One mix-fix step: a verb part resolved to a fact type, plus what follows it."""
    fact: str
    from_role: str
    to_role: str
    verb: str
    target: Optional[object] = None


@dataclass
class RoleSpec:
    """Appendix B.2 <role reference>: naming a role rather than the type that plays it."""
    roles: List[str]
    text: str


@dataclass
class VarRef:
    name: str


@dataclass
class ImplicitHead:
    """The head an operand inherits. `A AND ALSO has B` -- the right operand continues from
    the same head, which is what makes AND ALSO an intersection of fronts (Fr) rather than a
    concatenation."""


@dataclass
class Step:
    """One mix-fix step: a verb part, what follows it, and whether the fact is optional.

    `optional` comes from the OPTIONALLY prefix, which B.2 provides a slot for. It makes the
    traversal an outer join, so the query keeps rows where the fact is absent instead of
    silently dropping them.
    """
    verb: str
    target: object = None
    optional: bool = False


@dataclass
class Filter:
    """A `[ ... ]` sub-expression sitting between path segments (section 6.7)."""
    expr: object


@dataclass
class Seq:
    parts: List[object]


@dataclass
class Binary:
    op: str
    left: object
    right: object


@dataclass
class Compare:
    op: str
    left: object
    right: object


@dataclass
class SetCompare:
    op: str
    left: object
    right: object
    negated: bool = False        # `DOES NOT EQUAL`: the CCM has no notMatch, so wrap in `not`


@dataclass
class Where:
    path: object
    condition: object


@dataclass
class Logical:
    op: str
    operands: List[object]


@dataclass
class Not:
    operand: object


@dataclass
class Some:
    path: object


@dataclass
class Aggregate:
    func: str
    path: object
    distinct: bool = False
    group_by: List[str] = field(default_factory=list)
    # `WITHIN d` is `GROUPED BY d` without the collapse: the same partition, reported beside
    # every row rather than instead of them. conquer-2026 §11.
    windowed: bool = False
    over: Optional[str] = None      # B.2's `<variable> IN`: which attribute is aggregated
    # Only `THE LIST OF` can carry these: it is the one group function whose result is a bag,
    # and a bag is the only result an order or a cut means anything to. Parsed straight after
    # the path, so an ORDERED WITH written after the whole body still orders the whole body.
    ordering: List["OrderItem"] = field(default_factory=list)
    limit: Optional["Limit"] = None
    # `THE PREVIOUS x BY t WITHIN g` -- the key the window is ordered by. Only the row-relative
    # functions carry one: a SUM does not care what order its bag was in, and a LAG is nothing
    # without it. conquer-2026 section 11.
    order_key: object = None
    # A second operand that is not the bag: `THE OBJECT OF v BY k` keys each value, `THE LIST
    # OF x SEPARATED BY ', '` joins the values as text. The bag is still the one thing
    # aggregated; this is a scalar rendered beside it (conquer-2026 section 13).
    extra: object = None
    # `THE RANK OF x ASCENDING`: which way the window is ordered. None is the function's
    # default -- descending, so rank 1 is the largest and percent rank 0 is the largest.
    direction: Optional[str] = None


@dataclass
class Arith:
    """Appendix B.3 <scalar expression>: `a * 100 / b`, `f(x)`."""
    op: str
    left: object
    right: object


@dataclass
class Call:
    name: str
    args: List[object]


@dataclass
class Constant:
    lexical: str
    numeric: bool = False


@dataclass
class SubExpr:
    parts: List[object]


@dataclass
class Named:
    """B.2 <confluence element>: `<information descriptor> AS <variable name>` -- the only
    way to give a computed descriptor, such as a grouped aggregate, a name to project."""
    path: object
    name: str


@dataclass
class Distinct:
    path: object


@dataclass
class Front:
    """Section 6.2's Fr: keep the head, discard the tail. Keyword ONLY."""
    path: object


@dataclass
class OrderItem:
    """One item of B.2's <order list>. `end` is set for the grammar's HEAD and TAIL
    terminals, which name the two distinguished ends of the path result -- section 6.13's
    hd and tl attributes -- rather than a variable bound in the query."""
    key: Optional[str]
    direction: str
    end: Optional[str] = None
    expr: object = None          # a scalar expression, when the key is computed


@dataclass
class Limit:
    """How much of the ordered result to keep.

    ConQuer-92 has no such construct. §6.13 defines only Ω, which sorts and no more, and is
    explicit that ordering "is not a part of the path-expressions themselves"; the grammar's
    HEAD and TAIL are sort *keys* naming the ends of the path, not a row count. So this is an
    extension, and it is sited where Ω is -- outside the algebra, on the LIST statement --
    rather than as a path operator, because a bag has no first element until something orders
    it."""
    count: int
    offset: int = 0
    per: Optional[str] = None     # PER x: the first n within each x, conquer-2026.md §8
    ties: bool = False            # WITH TIES: everything that ranks within n, not n rows


@dataclass
class ConfluenceElement:
    """One side path of a confluence: what to gather, what to call it, where to attach it.

    `ordering` and `limit` are an extension, and are only meaningful on a side path that
    fans out: B.2's <confluence element> has nowhere to put them because a flattened
    confluence gathers at most one value per junction, and one value has no order. Once the
    gathered relation is nested again (lower.fans_out) it is a bag per junction, and the
    first n of it in some order is exactly the question ("their three most recent orders")
    that a flat result cannot ask.
    """
    path: object                 # a TypeSpec, or a Seq/Step -- verb-led, or ending in a verb
    name: Optional[str] = None   # AS
    via: Optional[str] = None    # VIA: a variable bound in the base path; default its head
    ordering: List["OrderItem"] = field(default_factory=list)
    limit: Optional["Limit"] = None
    # `THE PREVIOUS x BY t WITHIN g` -- the key the window is ordered by. Only the row-relative
    # functions carry one: a SUM does not care what order its bag was in, and a LAG is nothing
    # without it. conquer-2026 section 11.
    order_key: object = None


@dataclass
class Confluence:
    """Section 6.5: `Q1 [AS a1] [VIA x1], ... EACH P`.

    P is the query; each Qi gathers one more column onto it, joined at xi with a LEFT OUTER
    JOIN (the report's ⟕). This is where ConQuer-92 puts the distinction between a fact you
    *require* -- a traversal in P, which is a natural join over the fact population -- and a
    value you merely want *shown* if it exists. The report's own example: `LIST Budget VIA g,
    Firstname of, Surname given to EACH Person working for Group g part of Department: 'CS'`.
    """
    elements: List["ConfluenceElement"]
    base: object


@dataclass
class Conditional:
    """A scalar `IF c THEN a ELSE b` (conquer-2026.md §4): §6.3's f(P1..Pn) with a boolean
    first argument, distinct from §7.5's bag-valued IF by position -- this one lives where a
    scalar expression does. Emits CASE WHEN."""
    condition: object
    then: object
    otherwise: object


@dataclass
class SubQuery:
    """A whole `(LIST ... ORDERED ... THE FIRST n)` standing where a bag does -- as the operand
    of a set comparator. conquer-2026.md §8: a limit that applies somewhere other than the
    outermost result. The sub-query carries its own ordering and limit into the bag block."""
    query: "Query"


@dataclass
class Query:
    body: object
    projections: List[Tuple[str, object]] = field(default_factory=list)
    ordering: List["OrderItem"] = field(default_factory=list)
    limit: Optional["Limit"] = None
    # `THE PREVIOUS x BY t WITHIN g` -- the key the window is ordered by. Only the row-relative
    # functions carry one: a SUM does not care what order its bag was in, and a LAG is nothing
    # without it. conquer-2026 section 11.
    order_key: object = None


# --------------------------------------------------------------------------- keywords

FR_SET = {"AND ALSO": "and", "OR OTHERWISE": "or", "BUT NOT": "butnot"}
SET_OP = {"UNITED WITH": "union", "INTERSECTED WITH": "intersect", "MINUS": "except"}
# Section 6.2's underlined comparators: filter the heads of P by how P's tails sit against
# Q's heads. Each keeps its keyword so section 8 verbalisation can read it back.
SET_CMP = {"WHICH ARE ALL IN": "subset", "THAT INCLUDES ALL": "superset",
           "MATCHING ALL": "match",
           # Section 6.4/7.5's SetComp: a comparison of two whole head sets. Same machinery,
           # uncorrelated bags. `EXCLUDES` and `IS DISJOINT FROM` are the PLAIN circled-times;
           # `MISSING`/`EXCLUDING` are the underlined one, a path operator (see UNLOWERED).
           "IS A PROPER SUBSET OF": "properSubset", "IS A SUBSET OF": "subset",
           "IS A PROPER SUPERSET OF": "properSuperset", "IS A SUPERSET OF": "superset",
           "EQUALS": "match", "IS DISJOINT FROM": "disjoint", "EXCLUDES": "disjoint",
           "DOES NOT EQUAL": "match"}

# The grammar spells `DOES NOT EQUAL` as its own set comparator, but the CCM's SetOp has no
# negated match (model.md section 6.4), so it lowers as `not (P match Q)`.
SET_CMP_NEGATED = {"DOES NOT EQUAL"}

# In the grammar, parse, and refuse with the reason rather than silently meaning something
# else. Each maps to a construct the CCM can hold but the lowering does not build yet.
UNLOWERED = {
    "MISSING": "the complement-of-concatenation path operator of section 6.2",
    "EXCLUDING": "the complement-of-concatenation path operator of section 6.2",
    "THE REVERSE OF": "path reversal (section 6.1)",
    "WITH": "the cartesian product of two paths (section 6.2)",
    "THE PATH FROM": "the path shuffle / projection operator (section 6.2)",
    # B.2 <selection>, rules [P36]-[P38]: a descriptor chosen by a condition. Both the
    # `IF c THEN d ELSE d` form and the `d IF c; d IF c OTHERWISE d` alternatives sequence
    # branch on which *bag* is returned, so neither is a SQL CASE expression.
    "IF": "section 7.5's conditional descriptor, IF <condition> THEN ... [ELSE ...]",
    "OTHERWISE": "the alternatives sequence of section 7.5, ... IF ...; ... OTHERWISE ...",
}

# B.2 <confluence>. Unlike the entries above, `EACH` cannot simply be listed there: the
# report's own examples also use "each" as an article ("LIST n FROM each Employee ..."), and
# NOISE already lets it through in that position. Only the operator position -- after a
# complete descriptor -- is refused, by `_refuse_confluence`.
CONFLUENCE_REASON = ("section 6.5's confluence operation, `Q1 AS a1 VIA x1, ... EACH P`, "
                     "which gathers side paths onto a base path")
VALUE_CMP = {"IS EQUAL TO": "=", "IS NOT EQUAL TO": "<>", "IS LESS THAN OR EQUAL TO": "<=",
             "IS LESS THAN": "<", "IS GREATER THAN OR EQUAL TO": ">=",
             "IS GREATER THAN": ">", "=": "=", "<>": "<>", "!=": "<>",
             "<=": "<=", ">=": ">=", "<": "<", ">": ">"}
# `THE LIST OF` is the one group function whose result is a bag rather than a scalar: it
# gathers what the path reaches into a nested relation instead of reducing it. §6.6 does not
# have it because SQL-92 could not return one -- the same sentence in §6.5 that made
# confluence flat -- and it is what makes "each department and its staff" one row per
# department. It is also the normal form a nested confluence element reads back as.
AGGREGATES = {"THE COUNT OF": ("count", False), "THE DISTINCT COUNT OF": ("count", True),
              "THE SUM OF": ("sum", False), "THE DISTINCT SUM OF": ("sum", True),
              "THE MINIMUM": ("min", False), "THE MAXIMUM": ("max", False),
              "THE AVERAGE": ("avg", False),
              # The middle value, not the mean. A benchmark writer asked for one, could not
              # say it, and reported THE AVERAGE instead -- 0.4485 where the median is 0.4097
              # (finding 99). Whether the model *has* `fn.median` is the dialect's business:
              # DuckDB and PostgreSQL do, and a model built for SQLite leaves it out, so
              # naming it there fails in lowering rather than emitting SQL no engine will run.
              "THE MEDIAN OF": ("median", False), "THE MEDIAN": ("median", False),
              # Dispersion, on the same terms as the median: the dialect decides whether the
              # model carries it. A writer needing a standard deviation built one out of
              # three other aggregates -- `sqrt((avg(a*a) - avg(a)^2) * n/(n-1))` -- which is
              # correct, and is the sort of thing a query language exists to not make people
              # do (finding 148).
              "THE STANDARD DEVIATION OF": ("stddev", False),
              "THE STANDARD DEVIATION": ("stddev", False),
              "THE STDDEV OF": ("stddev", False), "THE STDDEV": ("stddev", False),
              "THE VARIANCE OF": ("variance", False), "THE VARIANCE": ("variance", False),
              # Row-relative: what a row is against the other rows of its partition, which no
              # aggregate can say. Both are window-only -- `GROUPED BY` returns one row per
              # group and there is nothing left to be relative to.
              "THE RANK OF": ("rank", False), "THE PREVIOUS": ("lag", False),
              # Where a row stands as a fraction of its partition: (rank - 1) / (rows - 1),
              # the PERCENT_RANK every knowledge base here means by "percentile ranking".
              "THE PERCENT RANK OF": ("percent_rank", False),
              "THE LIST OF": ("list", False), "THE DISTINCT LIST OF": ("list", True),
              # A document keyed by a value: `THE OBJECT OF v BY k` is {k: v, ...}. The one
              # gathering shape THE LIST OF could not spell (LiveSQLBench alien_5).
              "THE OBJECT OF": ("object", False)}
LOGIC = {"AND": "and", "OR": "or", "EXCLUSIVE OR": "xor", "IMPLIES": "implies",
         "IFF": "iff", "&": "and", "|": "or", "||": "xor", "=>": "implies", "<=>": "iff"}

# Longest first, so "AND ALSO" wins over "AND" and "IS LESS THAN OR EQUAL TO" over "IS LESS THAN".
# The same set, unordered, is what a schema-derived verb part may not be (Lexicon._add_verb).
PHRASES = sorted(
    set(FR_SET) | set(SET_OP) | set(SET_CMP) | set(VALUE_CMP) | set(AGGREGATES) | set(LOGIC)
    | set(UNLOWERED)
    | {"LIST", "FROM", "WHERE", "NOT", "SOME", "DISTINCT", "ONLY", "ORDERED WITH", "ORDERED",
       "ASCENDING", "DESCENDING", "GROUPED BY", "WITHIN", "EACH", "AS", "VIA", "OPTIONALLY",
       "SEPARATED BY",
       "THE FIRST", "THE TOP", "AFTER", "THEN", "ELSE", "PER", "WITH TIES", "DEFINE",
       "THE", "A", "AN", "AND"},
    key=lambda p: (-len(p.split()), -len(p)))
KEYWORD_PHRASES = frozenset(PHRASES)

NOISE = {"A", "AN", "EACH"}          # articles the report's examples use freely

# An article cannot meaningfully follow a type specification, so it must not block a
# variable of the same name: `has EmployeeSalary a` names a variable, not an article.
NAMEABLE_BLOCKERS = [p for p in PHRASES if p.upper() not in NOISE]

_PHRASE_ORDER = {}                   # keyword tuple -> longest-first order, built once


# --------------------------------------------------------------------------- tokens

@dataclass
class Token:
    kind: str          # word | string | number | punct | phrase
    text: str
    pos: int


_TOKEN_RE = re.compile(r"""
    (?P<string>'(?:[^']|'')*'|"(?:[^"]|"")*")
  | (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<punct><=>|<=|>=|<>|!=|\|\||=>|[()\[\],:!<>=&|+\-*/.^])
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<space>\s+)
""", re.VERBOSE)


def _tidy(tokens) -> str:
    """Tokens back into text a reader would write: `round(s / 1000, 1)`, not
    `round ( s / 1000 , 1 )`. A listed expression is named by its text, and the spaced
    form was every writer's column header."""
    out, prev = "", ""
    for tok in tokens:
        # `(` sticks to a function name -- lowercase, as every library function is spelled
        # -- and not to a keyword: `round(`, `starts_with(`, but `WHERE (` and `IN (`.
        call = tok == "(" and prev[:1].isalpha() and prev.islower()
        if out and tok not in (",", ")") and not out.endswith("(") and not call:
            out += " "
        out += tok
        prev = tok
    return out


def tokenize(text: str) -> List[Token]:
    out, i = [], 0
    while i < len(text):
        m = _TOKEN_RE.match(text, i)
        if not m:
            raise ParseError("unexpected character %r at %d" % (text[i], i))
        i = m.end()
        if m.lastgroup == "space":
            continue
        if m.lastgroup == "string":
            body = m.group()[1:-1].replace("''", "'").replace('""', '"')
            out.append(Token("string", body, m.start()))
        elif m.lastgroup == "number":
            out.append(Token("number", m.group(), m.start()))
        elif m.lastgroup == "punct":
            out.append(Token("punct", m.group(), m.start()))
        else:
            out.append(Token("word", m.group(), m.start()))
    return out


# --------------------------------------------------------------------------- lexicon

class Lexicon(Index):
    """What the parser needs on top of the shared model index: the verb vocabulary.

    A verb part comes from a reading -- "{0} has {1}" contributes "has" stepping from
    roleSequence[0] to roleSequence[1]. Readings are ORM's spelling of ConQuer's mix-fix
    MFix, so this is the report's own construction; Index.reading_slots does the splitting.
    """

    def __init__(self, model: dict):
        super().__init__(model)

        # verb part -> [(fact id, from role, to role)]. A reading's hyphen-bound adjective
        # (`has manager- {1}`) is part of the verb part here: `has manager`.
        self.verbs: dict = {}
        self.shadowed: set = set()        # verb parts a keyword outranks; see _add_verb
        for c in model["concepts"]:
            if c["kind"] != "fact":
                continue
            for verb, a, b in self.reading_slots(c):
                self._add_verb(verb.casefold(), (c["id"], a, b))
                inverse = self._inverse_of(verb)
                if inverse:
                    self._add_verb(inverse, (c["id"], b, a))
        self.verb_phrases = sorted(self.verbs, key=lambda v: (-len(v.split()), -len(v)))
        # Unary readings, recorded but never registered as verb parts. A unary fact type is a
        # set -- there is no second role to walk to -- so no path can use it, and the model's
        # own listing now says so. Kept here only so that a writer who tries anyway is told
        # what they hit instead of "'is' is neither a type in this schema" (finding 135).
        self.unary: dict = {}
        for c in model["concepts"]:
            if c["kind"] == "fact" and len(c.get("roles", [])) == 1:
                for r in c.get("readings", []):
                    text = re.sub(r"\{\d+\}", "", r.get("text", "")).strip()
                    if text:
                        self.unary.setdefault(text.casefold(), c["name"])

        # Section 6.9's Macros function: name -> (parameters, kind, body text)
        self.macros: dict = {m["name"].casefold(): m for m in model.get("macros", [])}

        # Appendix B.2's <role reference>: a role may be named directly. On a ring fact type
        # -- both roles played by one object type -- whose only reading is the placeholder
        # `{0} has {1}`, it is the one way to say which role is meant; a ring with a reading
        # of its own (`is connected to`, `has manager-`) says so by the verb.
        self.role_names: dict = {}
        for rid, r in self.roles.items():
            if r.get("name"):
                self.role_names.setdefault(r["name"].casefold(), []).append(rid)

        # Derived fact types carry the keys their rules imply. A rule that lists one row
        # per head is functional whether or not the model wrote the constraint down, and
        # the fan-out check and section 14b both need to know. Costs nothing for a model
        # without rules; for one with them, a parse of each rule once per lexicon.
        if model.get("derivationRules") and model.get("constraints"):
            import lower                                   # lazily: lower imports this module
            lower.declare_derived_keys(model, self)

    def _add_verb(self, verb: str, entry: tuple):
        # A schema may not shadow the language. Reverse engineering reads an n-ary table as
        # `{0} has {1} and {2}`, which contributes "and" as the verb part between slots 1 and
        # 2 -- and then `... has RaceName v AND ALSO ...` consumed the AND as a step and
        # refused at ALSO, on every f1 query, because a verb was tried before a keyword.
        # Appendix B.2's role reference is how such a role is walked: `Drive Constructor`.
        if verb.upper() in KEYWORD_PHRASES:
            self.shadowed.add(verb)
            return
        entries = self.verbs.setdefault(verb, [])
        if entry not in entries:            # an explicit inverse reading and a derived one
            entries.append(entry)

    @staticmethod
    def _inverse_of(verb: str) -> Optional[str]:
        # A stopgap: reverse engineering emits one reading per fact type, never the inverse
        # reading order ORM normally carries, so a path can only be walked one way. Emitting
        # both orders in reverse/derive.py would remove this.
        #
        # A reading whose verb carries a bound adjective (rule 10: `has eye`, `has fifa api`)
        # needs the adjective in its inverse too, or two fact types between the same pair of
        # types become indistinguishable again going backwards -- which is how
        # `Player is of PlayerAttribute` came to have no reading at all.
        v = " ".join(verb.split()).casefold()
        if v in ("has", "have"):
            return "is of"
        for lead in ("has ", "have "):
            if v.startswith(lead):
                return "is %s of" % v[len(lead):]
        return None


# --------------------------------------------------------------------------- parser

class Parser:
    def __init__(self, lexicon: Lexicon, text: str):
        self.lex = lexicon
        self.expanded_macros: List[Tuple[str, str]] = []   # (invocation, expansion) for --explain
        self._expanding: List[str] = []
        self.text = text
        self.toks = tokenize(text)
        self.i = 0
        self.declared = set()          # variables bound earlier in this query text
        self.forward_refs = False      # inside LIST, a name may be bound later in the path

    # -- token helpers -----------------------------------------------------

    def eof(self) -> bool:
        return self.i >= len(self.toks)

    def peek(self, k=0) -> Optional[Token]:
        return self.toks[self.i + k] if self.i + k < len(self.toks) else None

    def match_phrase(self, phrases) -> Optional[str]:
        """Longest phrase match at the cursor, over multi-word keyword phrases."""
        for phrase in phrases:
            words = phrase.split()
            if all(self.peek(n) is not None
                   and self.peek(n).text.casefold() == w.casefold()
                   and self.peek(n).kind in ("word", "punct")
                   for n, w in enumerate(words)):
                self.i += len(words)
                return phrase
        return None

    def _try_macro(self) -> Optional[dict]:
        """Section 6.9: `α(E1, ..., En)` where α is a macro is the macro's body with each
        parameter replaced by its argument. The report calls the mechanism "basically an
        abbreviation", and that is how it is built: at the token level, before parsing goes
        on, with the body and each argument parenthesised so precedence survives. The caller
        parses again from the same place and never sees the name. Returns whether it did."""
        t, nxt = self.peek(), self.peek(1)
        if t is None or t.kind != "word" or nxt is None or nxt.kind != "punct" \
                or nxt.text != "(" or t.text.casefold() not in self.lex.macros \
                or t.text.casefold() in self.lex.by_name:
            return None
        macro = self.lex.macros[t.text.casefold()]
        if macro["name"].casefold() in self._expanding:
            raise MacroError("macro %s is recursive; section 6.9 allows no recursive macros. "
                             "A recursive definition is a derivation rule (section 6.11)"
                             % macro["name"])
        start, pos = self.i, t.pos
        self.i += 2
        args: List[List[Token]] = []
        if not (self.peek() and self.peek().kind == "punct" and self.peek().text == ")"):
            while True:
                a0 = self.i
                self.parse_scalar()               # a path is a scalar that computes nothing
                args.append(self.toks[a0:self.i])
                if self.peek() and self.peek().kind == "punct" and self.peek().text == ",":
                    self.i += 1
                    continue
                break
        self.expect_punct(")")
        params = macro.get("parameters", [])
        if len(args) != len(params):
            raise MacroError("macro %s takes %d argument%s, not %d"
                             % (macro["name"], len(params), "" if len(params) == 1 else "s",
                                len(args)))
        bound = dict(zip(params, args))
        body = [Token("punct", "(", pos)]
        for tok in tokenize(macro["source"]):
            if tok.kind == "word" and tok.text in bound:
                body += [Token("punct", "(", pos)] + \
                        [Token(x.kind, x.text, pos) for x in bound[tok.text]] + \
                        [Token("punct", ")", pos)]
            else:
                body.append(Token(tok.kind, tok.text, pos))
        body.append(Token("punct", ")", pos))
        self.expanded_macros.append((
            " ".join(x.text for x in self.toks[start:self.i]),
            " ".join(x.text for x in body[1:-1])))
        self.toks[start:self.i] = body
        self.i = start
        # a macro may use another macro, never itself, at any depth
        self._expanding.append(macro["name"].casefold())
        return macro

    def match_verb(self) -> Optional[str]:
        """The longest verb part at the cursor, with one exception. A reading's hyphen-bound
        adjective makes `has manager` a verb part; when that adjective is also a type or role
        name and no descriptor follows it, the word was the target -- `Employee has Manager`,
        the subtype -- and the shorter verb part is meant."""
        phrases = self.lex.verb_phrases
        while True:
            save = self.i
            verb = self.match_phrase(phrases)
            if verb is None:
                return None
            tail = verb.split()[1:]
            if tail and any(w in self.lex.object_names or w in self.lex.role_names
                            for w in tail) \
                    and not self._starts_descriptor():
                self.i = save
                shorter = [p for p in phrases if p != verb]
                if self.match_phrase(shorter) is None:
                    self.i = save
                    return self.match_phrase(phrases)      # nothing shorter fits
                self.i = save
                phrases = shorter
                continue
            return verb

    @staticmethod
    def _longest_first(phrases):
        # Cached: at_phrase(*PHRASES) runs on every atom, and PHRASES is already in this
        # order, so re-sorting fifty keywords per token was pure overhead.
        key = phrases if isinstance(phrases, tuple) else tuple(phrases)
        try:
            return _PHRASE_ORDER[key]
        except KeyError:
            ordered = sorted(key, key=lambda p: (-len(p.split()), -len(p)))
            _PHRASE_ORDER[key] = ordered
            return ordered

    def try_phrase(self, *phrases) -> Optional[str]:
        save = self.i
        got = self.match_phrase(self._longest_first(phrases))
        if got is None:
            self.i = save
        return got

    def _try_confluence(self):
        """B.2 <confluence>: elements, then EACH, then the base. None if that is not what
        follows; the cursor is restored so an ordinary descriptor can be parsed instead."""
        if not self._each_ahead(operator_only=True):
            return None
        save = self.i
        elements = []
        while True:
            elem = self._parse_confluence_element()
            if elem is None:
                self.i = save
                return None
            elements.append(elem)
            t = self.peek()
            if t is not None and t.kind == "punct" and t.text == ",":
                self.i += 1
                continue
            break
        tok = self.peek()
        if tok is None or tok.text != "EACH" or not self.try_phrase("EACH"):
            self.i = save
            return None
        base = self.parse_descriptor()
        return Confluence(elements, base)

    def _parse_confluence_element(self):
        """`Budget VIA g`, `Firstname of`, `has Firstname AS f` -- a side path, in one of the
        three shapes that can be attached at a junction without reversing a path:

          a bare type            Budget          the one fact type between junction and Budget
          type then a verb       Firstname of    the fact type read from Firstname's side
          verb-led               has Firstname   the fact type read from the junction's side

        A complete descriptor with a head and a tail of its own would need §6.1's path
        reversal to attach, which is not built; it is refused with that reason.
        """
        self.skip_noise()
        save = self.i
        parts = []
        if self._at_verb():
            while self._at_verb():
                optional = self.try_phrase("OPTIONALLY") is not None
                verb = self.match_verb()
                target = self.parse_atom() if self._starts_descriptor() else None
                parts.append(Step(verb, target, optional))
            path = Seq(parts) if len(parts) > 1 else parts[0]
        else:
            t = self.peek()
            if t is None or t.kind != "word":
                self.i = save
                return None
            try:
                head = self.parse_atom()
            except ParseError:
                self.i = save
                return None
            parts = [head]
            while self._at_verb():
                verb = self.match_verb()
                target = self.parse_atom() if self._starts_descriptor() else None
                parts.append(Step(verb, target, False))
                if target is not None:
                    raise ParseError(
                        "a confluence element with a head and a tail of its own (%r ... %r) "
                        "would need THE REVERSE OF to attach at the junction, which is not "
                        "built. Write it from the junction's side -- `has X` -- or as a "
                        "dangling verb -- `X of`" % (getattr(head, "concept", "?"), verb))
            path = Seq(parts) if len(parts) > 1 else parts[0]
        name = via = None
        if self.try_phrase("AS"):
            t = self.peek()
            if t is None or t.kind != "word":
                raise ParseError("AS must be followed by a variable name")
            self.i += 1
            name = t.text
            self.declared.add(name)
        if self.try_phrase("VIA"):
            t = self.peek()
            if t is None or t.kind != "word":
                raise ParseError("VIA must be followed by a variable name")
            self.i += 1
            via = t.text
        # after AS and VIA, so a key may name what the element itself bound
        ordering = self.parse_ordering()
        limit = self.parse_limit()
        if limit is not None and limit.per is not None:
            raise ParseError("PER inside a confluence element: the element is already one "
                             "bag per junction, so THE FIRST %d is per junction already"
                             % limit.count)
        return ConfluenceElement(path, name, via, ordering, limit)

    def _each_ahead(self, operator_only=False) -> bool:
        """Is there an `EACH` in the unconsumed remainder?

        The word is both an article the report's examples use freely (`each Person has a
        Name`) and §6.5's confluence operator (`Firstname of, Surname given to EACH Person`).
        Locally the two are indistinguishable -- a dangling verb precedes the operator, and a
        verb precedes the article. The report resolves it typographically: formal items are
        set in a distinct style (§1.1 of Halpin's verbalization report says the same). Here
        that style is upper case, so `EACH` is the operator and `each` is the article.
        """
        save = self.i
        try:
            while not self.eof():
                if self.at_phrase("EACH"):
                    tok = self.peek()
                    if not operator_only or (tok is not None and tok.text == tok.text.upper()):
                        return True
                self.i += 1
            return False
        finally:
            self.i = save

    def _refuse_confluence(self):
        raise ParseError("'EACH' is %s, which this transpiler parses but does not compile"
                         % CONFLUENCE_REASON)

    def at_phrase(self, *phrases) -> bool:
        save = self.i
        got = self.match_phrase(self._longest_first(phrases))
        self.i = save
        return got is not None

    def at_phrase_at(self, ahead: int, *phrases) -> bool:
        """`at_phrase`, looking `ahead` tokens past the current one."""
        save = self.i
        self.i += ahead
        try:
            return self.at_phrase(*phrases)
        finally:
            self.i = save

    def expect_punct(self, ch):
        t = self.peek()
        if t is None or t.kind != "punct" or t.text != ch:
            raise ParseError("expected %r near %r" % (ch, self._context()))
        self.i += 1

    def _context(self) -> str:
        t = self.peek()
        return self.text[t.pos:t.pos + 40] if t else "<end of input>"

    def skip_noise(self):
        # Not inside a projection list: there an article is never meant, and skipping one
        # swallows any variable named `a`, `an` or `each`.
        if self.forward_refs:
            return
        # An article only counts as noise when it actually precedes a type -- "a Person".
        # Skipping it unconditionally swallowed any variable named `a`, `an` or `each`,
        # which is a name people reach for constantly.
        while not self.eof() and self.peek().kind == "word" \
                and self.peek().text.upper() in NOISE:
            nxt = self.peek(1)
            if nxt is None or nxt.kind != "word" or (
                    nxt.text.casefold() not in self.lex.by_name
                    and nxt.text.casefold() not in self.lex.role_names
                    and nxt.text.upper() not in NOISE):
                return
            self.i += 1

    # -- entry point -------------------------------------------------------

    def parse_query(self) -> Query:
        q = self._parse_query_parts()
        if not self.eof():
            raise ParseError("unconsumed input near %r" % self._context())
        return q

    def parse_definition(self) -> Optional[str]:
        """`DEFINE <Name> ::=`, consumed; the name, or None if that is not what is here.

        conquer-2026.md §11. §6.11's derivation operator is `::=`, and this is that operator
        with its left-hand side scoped to one query: what follows names a result the query
        may then walk as though the model declared it. Only the header is parsed here,
        because the body has to be parsed against a lexicon that already knows the
        definitions before it.
        """
        if not self.try_phrase("DEFINE"):
            return None
        t = self.peek()
        if t is None or t.kind != "word":
            raise ParseError("DEFINE must be followed by a name for what is being defined")
        name = t.text
        self.i += 1
        for ch in (":", ":", "="):
            tok = self.peek()
            if tok is None or tok.kind != "punct" or tok.text != ch:
                raise ParseError("DEFINE %s must be followed by ::= and then a query that "
                                 "lists what it holds" % name)
            self.i += 1
        return name

    def parse_subquery(self) -> SubQuery:
        """`( LIST ... )` -- the opening parenthesis already consumed."""
        q = self._parse_query_parts()
        self.expect_punct(")")
        return SubQuery(q)

    @staticmethod
    def _closed(expr) -> bool:
        """A scalar with nothing left to bind: an aggregate, a constant, or arithmetic, a call
        or a conditional over those. A list of such things needs no path to be listed FROM."""
        if isinstance(expr, (Aggregate, Constant)):
            return True
        if isinstance(expr, Arith):
            return Parser._closed(expr.left) and Parser._closed(expr.right)
        if isinstance(expr, Call):
            return all(Parser._closed(a) for a in expr.args)
        if isinstance(expr, Conditional):
            return Parser._closed(expr.then) and Parser._closed(expr.otherwise)
        return False

    def _parse_query_parts(self) -> Query:
        projections = []
        if self.try_phrase("LIST"):
            save = self.i
            items = self._try_projection_list()
            if items is not None and self.at_phrase("AS"):
                # `LIST round(x, 2) AS y FROM ...`: SQL's habit, and the projection list has
                # no place for a name -- names are bound in the path, where the value is
                # computed. Backing up and reading the whole thing as a path said "'n' is
                # neither a type nor a variable", which two writers each spent a round trip
                # on. Say what is wrong where it is wrong.
                raise ParseError(
                    "LIST cannot name a column with AS. Bind the expression in the path and "
                    "list the name: `LIST n, k FROM ... AND ALSO round(s / 1000, 1) AS k` "
                    "(near %r)" % self._context())
            if items is not None and self.try_phrase("FROM"):
                projections = items
            elif items is not None and len(items) > 1 \
                    and all(e is not None and self._closed(e) for _, e in items) \
                    and (self.eof() or (self.peek().kind == "punct" and self.peek().text == ")")):
                # Several whole-query scalars side by side (conquer-2026.md §10): `LIST THE
                # COUNT OF A, THE COUNT OF B`. There is no path to list them FROM; each item is
                # a whole query of its own and the result is one row.
                return Query(body=None, projections=items)
            else:
                self.i = save
        # §7.5's IF chooses between BAGS and is refused (UNLOWERED). The scalar IF of
        # conquer-2026.md §4 is only ever reached inside a scalar expression -- after LIST,
        # an operator, or a call -- so an IF at the head of the body is the refused one.
        if self.at_phrase("IF"):
            raise ParseError("'IF' is %s, which this transpiler parses but does not compile"
                             % UNLOWERED["IF"])
        body = self._try_confluence()
        if body is None:
            body = self.parse_descriptor()
        ordering = self.parse_ordering()
        limit = self.parse_limit()
        return Query(body=body, projections=projections, ordering=ordering, limit=limit)

    def _try_projection_list(self):
        """B.5: LIST <scalar expression list> FROM ... -- so a column may be computed.

        Parsed before the path that binds the names, so a bare name here is a forward
        reference; lowering resolves it once the path has run.
        """
        items = []
        self.forward_refs = True
        try:
            while True:
                start = self.i
                if self.peek() is None:
                    return None
                try:
                    expr = self.parse_scalar()
                except MacroError:
                    raise
                except ParseError:
                    return None
                label = _tidy(t.text for t in self.toks[start:self.i])
                items.append((label, None if isinstance(expr, VarRef) else expr))
                if self.peek() and self.peek().kind == "punct" and self.peek().text == ",":
                    self.i += 1
                    continue
                return items
        finally:
            self.forward_refs = False

    def _direction(self, default="asc"):
        """ASCENDING is the default, so the token is consumed only to move past it.
        With `default=None` the caller can tell "no direction was written" apart from
        "ascending was written", which is what lets an item put its direction first."""
        if self.try_phrase("DESCENDING"):
            return "desc"
        if self.try_phrase("ASCENDING"):
            return "asc"
        return default

    def parse_ordering(self):
        """B.2's <order specification>. Two spellings of an order item are accepted: the
        grammar writes `<name> ASCENDING`, while rule [P59] prints the direction first,
        `ASCENDING <name>`. The report uses both, so both parse.

        Bare `ORDERED ASCENDING` sorts on the head ([P57]/[P58]).
        """
        out = []
        if self.try_phrase("ORDERED WITH"):
            while True:
                leading = self._direction(default=None)
                t = self.peek()
                if t is None or t.kind != "word":
                    if leading is None and not out:
                        raise ParseError("ORDERED WITH needs at least one thing to sort by")
                    raise ParseError("ORDERED WITH expected something to sort by near %r"
                                     % self._context())
                # HEAD and TAIL are terminals in the grammar, but a query is free to bind a
                # variable of either name; a bound variable is the more specific reading and
                # wins. `forward_refs` is not in play here -- ordering is parsed last, so
                # every variable the query binds is already known.
                name = t.text
                end = name.lower() if name.upper() in ("HEAD", "TAIL") else None
                if end and name in self.declared:
                    end = None
                expr = None
                if end or self._simple_order_key():
                    self.i += 1
                else:
                    # Anything else is a scalar expression, so a result can be ordered by
                    # something it does not list -- `abs(lo)`, `g / t`.
                    expr = self.parse_scalar()
                    name = None
                direction = leading or self._direction()
                out.append(OrderItem(key=name if not end else None, direction=direction,
                                     end=end, expr=expr))
                if self.peek() and self.peek().kind == "punct" and self.peek().text == ",":
                    self.i += 1
                    continue
                break
        elif self.try_phrase("ORDERED"):
            out.append(OrderItem(key=None, direction=self._direction(), end="head"))
        return out

    def parse_limit(self):
        """`THE FIRST <n>` / `THE TOP <n>`, optionally `AFTER <m>` to skip m first.

        Both spellings mean the same thing: the questions this answers are phrased both ways
        ("the top 5 schools", "the 7th highest"), and a conceptual query language that reads
        back as English should accept the phrasing people use.
        """
        word = self.try_phrase("THE FIRST", "THE TOP")
        if word is None:
            return None
        count = self._whole_number("%s needs a number" % word)
        offset = 0
        if self.try_phrase("AFTER"):
            offset = self._whole_number("AFTER needs a number")
        per = None
        if self.try_phrase("PER"):
            t = self.peek()
            if t is None or t.kind != "word":
                raise ParseError("PER needs a variable to group by, near %r" % self._context())
            self.i += 1
            per = t.text
        # `WITH TIES` asks for everything that ranks within n rather than for n rows. "The
        # race where Hamilton was fastest" is one question whether he was fastest once or
        # thirty-seven times, and `THE FIRST 1` answers a different one -- it picks a row,
        # and which row is the backend's business. This is opt-in for the reason finding 79
        # gives: making it the default cost 16 recorded answers, because the gold is written
        # in SQL and SQL's LIMIT does not keep ties.
        ties = self.try_phrase("WITH TIES") is not None
        if ties and offset:
            raise ParseError("THE FIRST %d AFTER %d WITH TIES has no meaning: skipping rows "
                             "and keeping ties disagree about what the %dth row is. Drop "
                             "AFTER, or drop WITH TIES." % (count, offset, offset + 1))
        return Limit(count=count, offset=offset, per=per, ties=ties)

    def _simple_order_key(self):
        """Is the item just a name? Then keep it as a key rather than parsing an expression.

        `resolve_ordering` resolves a key against the variables the query binds *and* the
        names of its results, so `ORDERED WITH "s * 100"` sorts by a listed computed column,
        and an unknown key is refused with the sortable names listed. Handing a bare word to
        `parse_scalar` instead would refuse it earlier with a message that says only that the
        word is not a type.
        """
        nxt = self.peek(1)
        if nxt is None:
            return True
        if nxt.kind == "punct":
            return nxt.text == ","
        save, self.i = self.i, self.i + 1
        try:
            return self.at_phrase("ASCENDING", "DESCENDING", "THE FIRST", "THE TOP")
        finally:
            self.i = save

    def _whole_number(self, complaint):
        t = self.peek()
        if t is None or t.kind != "number" or float(t.text) != int(float(t.text)) \
                or int(float(t.text)) < 0:
            raise ParseError("%s, but found %r" % (complaint, self._context()))
        self.i += 1
        return int(float(t.text))

    # -- descriptors -------------------------------------------------------

    def parse_descriptor(self):
        node = self.parse_set_level()
        if self.try_phrase("WHERE"):
            # `A WHERE c AND ALSO B` is `(A WHERE c) AND ALSO B`: WHERE is a condition on the
            # path so far, and the branch after it still comes off the head. Before this, the
            # condition parser swallowed the `AND` of `AND ALSO` as a boolean operator, so the
            # branch was rooted at the last thing named instead of at the head -- which
            # surfaced as a confident and wrong refusal ("Employee and DepartmentCode cannot
            # be the same thing") on a query that is fine, and a california_schools writer
            # only got past it by moving the WHERE to the end.
            node = Where(node, self.parse_condition())
            while True:
                op = self.try_phrase(*FR_SET)
                if op is None:
                    break
                node = Binary(FR_SET[op], node, self.parse_comparison())
            while True:
                op = self.try_phrase(*SET_OP)
                if op is None:
                    break
                node = Binary(SET_OP[op], node, self.parse_fr_level())
        return node

    def parse_set_level(self):
        left = self.parse_fr_level()
        while True:
            op = self.try_phrase(*SET_OP)
            if op is None:
                return left
            left = Binary(SET_OP[op], left, self.parse_fr_level())

    def parse_fr_level(self):
        left = self.parse_comparison()
        while True:
            op = self.try_phrase(*FR_SET)
            if op is None:
                return left
            left = Binary(FR_SET[op], left, self.parse_comparison())

    def parse_comparison(self):
        # parse_scalar falls through to parse_path when no arithmetic operator follows, so
        # this stays a path comparison unless the text actually computes something.
        left = self.parse_scalar()
        if self.try_phrase("AS"):
            t = self.peek()
            if t is None or t.kind != "word":
                raise ParseError("AS must be followed by a variable name")
            self.i += 1
            self.declared.add(t.text)
            left = Named(left, t.text)
        infix = self.try_phrase(*UNLOWERED)
        if infix is not None:
            raise ParseError("%r is %s, which this transpiler parses but does not compile"
                             % (infix, UNLOWERED[infix]))
        op = self.try_phrase(*SET_CMP)
        if op is not None:
            return SetCompare(SET_CMP[op], left, self.parse_path(),
                              negated=op in SET_CMP_NEGATED)
        op = self.try_phrase(*VALUE_CMP)
        if op is not None:
            return Compare(VALUE_CMP[op], left, self.parse_scalar())
        return left

    def parse_path(self):
        """A linear path: a head, then mix-fix verb parts each pulling in a descriptor."""
        self.skip_noise()

        if self.try_phrase("DISTINCT"):
            return Distinct(self.parse_path())
        if self.try_phrase("ONLY"):
            return Front(self.parse_path())
        unlowered = self.try_phrase(*UNLOWERED)
        if unlowered is not None:
            raise ParseError("%r is %s, which this transpiler parses but does not compile"
                             % (unlowered, UNLOWERED[unlowered]))
        agg = self.try_phrase(*AGGREGATES)
        if agg is not None:
            func, distinct = AGGREGATES[agg]
            # B.2: <group function> [ <variable> 'IN' ] <information descriptor>. The
            # variable names the attribute aggregated -- the `a` of GSum(P, X, a).
            over, extra_first = None, None
            t, nxt = self.peek(), self.peek(1)
            if t is not None and t.kind == "word" and nxt is not None \
                    and nxt.kind == "word" and nxt.text.upper() == "IN" \
                    and t.text.casefold() not in self.lex.by_name:
                over = t.text
                self.i += 2
            elif t is not None and ((t.kind == "punct" and t.text == "(")
                                    or (t.kind == "word" and nxt is not None
                                        and nxt.kind == "punct" and nxt.text == "("
                                        and t.text.casefold() not in self.lex.by_name)):
                # `THE LIST OF (s * 2) IN <path>`, `THE SUM OF round(s, 0) IN <path>`: the
                # aggregated value is an expression over what the path binds. Read with
                # forward references, as a projection is, and kept only if IN follows --
                # `(Employee has ...)` is a parenthesised path, not an expression.
                save = self.i
                self.forward_refs = True
                try:
                    candidate = self.parse_scalar()
                except ParseError:
                    candidate = None
                finally:
                    self.forward_refs = False
                if candidate is not None and not isinstance(candidate, (VarRef, TypeSpec)) \
                        and self.try_phrase("IN"):
                    over = candidate
                else:
                    self.i = save
            elif t is not None and t.kind == "word" and nxt is not None \
                    and t.text.casefold() not in self.lex.by_name \
                    and ((func == "object" and nxt.kind == "word" and nxt.text.upper() == "BY")
                         or (func == "list" and self.at_phrase_at(1, "SEPARATED BY"))):
                # `THE OBJECT OF v BY k IN <path>`, `THE LIST OF n SEPARATED BY ', ' IN
                # <path>`: the variable, then the second operand, then IN. The key names
                # what the path binds, and the path comes after it -- a forward reference,
                # like a name in a projection list. Only when IN does follow: `THE OBJECT
                # OF s BY n GROUPED BY d` is the grouped form, read the ordinary way.
                save = self.i
                self.i += 1
                self.try_phrase("BY", "SEPARATED BY")
                self.forward_refs = True
                try:
                    candidate = self.parse_scalar()
                except ParseError:
                    candidate = None
                finally:
                    self.forward_refs = False
                if candidate is not None and self.try_phrase("IN"):
                    over, extra_first = t.text, candidate
                else:
                    self.i = save
            inner = self.parse_path()
            # B.2: the operand is an information descriptor, so section 6.4's Fr operators
            # belong to it -- `THE COUNT OF Patient BUT NOT has PatientDescription` counts
            # the difference. Arithmetic after it belongs to the enclosing expression, which
            # is why this is not parse_fr_level (that would take `* 100` into the operand).
            while True:
                fr = self.try_phrase(*FR_SET)
                if fr is None:
                    break
                inner = Binary(FR_SET[fr], inner, self.parse_path())
            # `THE COUNT OF X WHERE C` filters X: the condition belongs inside the aggregate,
            # where the variables X binds are in scope. Parsed here because WHERE otherwise
            # attaches at descriptor level, outside.
            if self.try_phrase("WHERE"):
                inner = Where(inner, self.parse_condition())
            ordering, limit = [], None
            if func == "list":
                ordering = self.parse_ordering()
                limit = self.parse_limit()
                if limit is not None and limit.per is not None:
                    raise ParseError("PER inside THE LIST OF: the gathered bag is already "
                                     "one per row of the query around it")
            # `THE PREVIOUS x BY t` -- the order the window runs in. Required there and
            # accepted nowhere else: ranking is by the value being ranked, and every other
            # aggregate is order-blind.
            order_key, extra, direction = None, extra_first, None
            if extra is not None:
                pass                                  # written before IN, already read
            elif func == "lag":
                if not self.try_phrase("BY"):
                    raise ParseError(
                        "THE PREVIOUS needs the order it is previous in -- "
                        "`THE PREVIOUS v BY y WITHIN f`. Without a key there is no previous row")
                order_key = self.parse_scalar()
            elif func == "object":
                if not self.try_phrase("BY"):
                    raise ParseError(
                        "THE OBJECT OF needs the key each value is filed under -- "
                        "`THE OBJECT OF v BY k GROUPED BY g` is {k: v, ...}")
                extra = self.parse_scalar()
            elif func == "list" and self.try_phrase("SEPARATED BY"):
                # `THE LIST OF n SEPARATED BY ', '`: the same bag, joined as text rather
                # than gathered as an array. Lowering renames the function.
                extra = self.parse_scalar()
            elif func in ("rank", "percent_rank"):
                direction = self.try_phrase("ASCENDING", "DESCENDING")
                direction = direction.lower()[:-6] if direction else None    # asc / desc
            group, windowed = [], False
            if self.at_phrase("WITHIN"):
                windowed = True
            if self.try_phrase("GROUPED BY", "WITHIN"):
                while True:
                    t, nxt = self.peek(), self.peek(1)
                    if t is None:
                        break
                    # A key is a bound name only when the next token ends it. Anything else
                    # after a word means the key is an expression that begins with one, and
                    # taking the word alone leaves the rest of it to be read as part of the
                    # query: `GROUPED BY s * 2` grouped by `s` and multiplied the *count* by
                    # two, silently. `IF` starts an expression whatever follows it.
                    if (t.kind == "word" and t.text.upper() != "IF"
                            and not (nxt is not None and nxt.kind == "punct"
                                     and nxt.text not in (",", ")"))):
                        group.append(t.text)          # a bound name: GROUPED BY d
                        self.i += 1
                    elif t.kind == "word" or (t.kind == "punct" and t.text == "(") \
                            or t.kind == "number":
                        # A computed key -- GROUPED BY year(d) -- groups by the value of
                        # the expression. MetricFlow's time dimension, in section 6.3's terms.
                        # A number is a constant key: `WITHIN 1` is one partition, the
                        # whole query, which is what a global rank is within. The normal
                        # form printed it that way and the parser refused to read it back,
                        # so writers bound `1 AS one` and wrote `WITHIN one`.
                        group.append(self.parse_scalar())
                    else:
                        break
                    if self.peek() and self.peek().kind == "punct" and self.peek().text == ",":
                        self.i += 1
                        continue
                    break
            if windowed and not group:
                raise ParseError("WITHIN needs the partition it is within -- "
                                 "`THE COUNT OF e WITHIN d`. For a whole-query total, "
                                 "leave it off entirely")
            if func in ("rank", "percent_rank", "lag") and not windowed:
                word = {"rank": "THE RANK OF", "percent_rank": "THE PERCENT RANK OF",
                        "lag": "THE PREVIOUS"}[func]
                raise ParseError(
                    "%s is what a row is against the other rows of its partition, so it needs "
                    "WITHIN and not GROUPED BY -- `%s v WITHIN g`, or `WITHIN 1` for the "
                    "whole query. GROUPED BY returns one row per group, and there is nothing "
                    "left for it to be relative to"
                    % (word, word if func != "lag" else "THE PREVIOUS ... BY t"))
            return Aggregate(func, inner, distinct, group, windowed, over, ordering, limit,
                             order_key, extra, direction)

        # `OPTIONALLY e has X`: the prefix before a bound head, modifying the step after it.
        # B.2 puts OPTIONALLY in front of the verb, and `e OPTIONALLY has X` has always
        # parsed; three blind writers over two rounds put it in front of the head instead,
        # which is where English puts it, and got "'OPTIONALLY' is neither a type nor a
        # variable". Both orders now mean the same thing.
        lead_optional = False
        if self.at_phrase("OPTIONALLY") and not self._at_verb():
            self.try_phrase("OPTIONALLY")
            lead_optional = True
        parts = [ImplicitHead() if self._at_verb() and not self._starts_descriptor()
                 else self.parse_atom()]
        while True:
            save = self.i
            self.skip_noise()
            # A sub-expression mid-path is a filter on the head reached so far. Section 6.7:
            # "the line of P o R is not disturbed by the sub-expression".
            if self.peek() and self.peek().kind == "punct" and self.peek().text == "[":
                parts.append(Filter(self.parse_atom()))
                continue
            optional = (self.try_phrase("OPTIONALLY") is not None) or lead_optional
            lead_optional = False
            verb = self.match_verb()
            if verb is None:
                self.i = save
                break
            target = None
            if self._starts_descriptor():
                target = self.parse_atom()
            parts.append(Step(verb, target, optional))
        return Seq(parts) if len(parts) > 1 else parts[0]

    def _starts_descriptor(self) -> bool:
        save = self.i
        self.skip_noise()
        t = self.peek()
        ok = t is not None and (
            t.kind in ("string", "number")
            or (t.kind == "word" and (t.text.casefold() in self.lex.by_name
                                      or t.text.casefold() in self.lex.role_names))
            or (t.kind == "punct" and t.text in "(["))
        self.i = save
        return ok

    ARITH = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/", "power": "^"}

    def parse_scalar(self):
        """<scalar expression> ::= ... | <scalar> <bin operator> <scalar> | '(' <scalar> ')'"""
        left = self.parse_scalar_term()
        while True:
            t = self.peek()
            if t is None or t.kind != "punct" or t.text not in ("+", "-"):
                return left
            self.i += 1
            left = Arith("add" if t.text == "+" else "subtract", left,
                         self.parse_scalar_term())

    def parse_scalar_term(self):
        left = self.parse_scalar_power()
        while True:
            t = self.peek()
            if t is None or t.kind != "punct" or t.text not in ("*", "/"):
                return left
            self.i += 1
            left = Arith("multiply" if t.text == "*" else "divide", left,
                         self.parse_scalar_power())

    def parse_scalar_power(self):
        """`a ^ b`, binding tighter than `*`. A benchmark writer with (RH-50)^2 to compute
        wrote (rh-50)*(rh-50) because there was no exponent operator; `power(a, b)` existed
        and `^` did not. Left-associative, like the rest of this grammar."""
        left = self.parse_scalar_factor()
        while True:
            t = self.peek()
            if t is None or t.kind != "punct" or t.text != "^":
                return left
            self.i += 1
            left = Arith("power", left, self.parse_scalar_factor())

    def parse_scalar_factor(self):
        macro = self._try_macro()
        if macro is not None:
            try:
                # a path macro's expansion is a descriptor, and the steps that follow it
                # belong to the path parser, not to a scalar factor
                return self.parse_path() if macro["kind"] == "path" \
                    else self.parse_scalar_factor()
            finally:
                self._expanding.pop()
        t = self.peek()
        # `IF c THEN a ELSE b` in scalar position. §7.5's IF at the head of a descriptor
        # chooses between bags and stays refused (UNLOWERED); reached here, after LIST or an
        # operator or inside a call, it is the scalar conditional of conquer-2026.md §4.
        nxt = self.peek(1)
        if self.at_phrase("IF") and not (nxt is not None and nxt.kind == "punct"
                                         and nxt.text == "("):
            # (`if(` with a parenthesis is the call form, handled below)
            self.try_phrase("IF")
            cond = self.parse_condition()
            if not self.try_phrase("THEN"):
                raise ParseError("IF ... needs THEN, near %r" % self._context())
            then = self.parse_scalar()
            if not self.try_phrase("ELSE"):
                raise ParseError("IF ... THEN ... needs ELSE, near %r" % self._context())
            return Conditional(cond, then, self.parse_scalar())
        if t is not None and t.kind == "punct" and t.text == "-":
            self.i += 1
            return Call("negate", [self.parse_scalar_factor()])
        if t is not None and t.kind == "punct" and t.text == "(":
            save = self.i
            self.i += 1
            try:
                inner = self.parse_scalar()
                self.expect_punct(")")
                return inner
            except ParseError:
                self.i = save
        # `name(args)` is a function call; anything else falls back to a path.
        if t is not None and t.kind == "word":
            nxt = self.peek(1)
            if nxt is not None and nxt.kind == "punct" and nxt.text == "(" \
                    and t.text.casefold() not in self.lex.by_name:
                name = t.text
                self.i += 2
                if name.casefold() == "if":
                    # if(c, a, b): the first argument is a condition, not a value
                    cond = self.parse_condition()
                    self.expect_punct(",")
                    then = self.parse_scalar()
                    self.expect_punct(",")
                    otherwise = self.parse_scalar()
                    self.expect_punct(")")
                    return Conditional(cond, then, otherwise)
                # `today()` -- a call may take no arguments (conquer-2026.md §6)
                nxt = self.peek()
                if nxt is not None and nxt.kind == "punct" and nxt.text == ")":
                    self.i += 1
                    return Call(name, [])
                args = [self.parse_scalar()]
                while self.peek() and self.peek().kind == "punct" and self.peek().text == ",":
                    self.i += 1
                    args.append(self.parse_scalar())
                self.expect_punct(")")
                return Call(name, args)
        return self.parse_path()

    def parse_atom(self):
        self.skip_noise()
        if self._try_macro() is not None:
            try:
                return self.parse_atom()
            finally:
                self._expanding.pop()
        t = self.peek()
        if t is None:
            raise ParseError("unexpected end of input")

        if t.kind == "string":
            self.i += 1
            return Constant(t.text)
        if t.kind == "number":
            self.i += 1
            return Constant(t.text, numeric=True)
        if t.kind == "punct" and t.text == "(":
            self.i += 1
            if self.at_phrase("LIST"):
                return self.parse_subquery()
            inner = self.parse_descriptor()
            self.expect_punct(")")
            return inner
        if t.kind == "punct" and t.text == "[":
            self.i += 1
            parts = [self.parse_descriptor()]
            while self.peek() and self.peek().kind == "punct" and self.peek().text == ",":
                self.i += 1
                parts.append(self.parse_descriptor())
            self.expect_punct("]")
            return SubExpr(parts)

        if t.kind == "word":
            cid = self.lex.by_name.get(t.text.casefold())
            if cid is None:
                if t.text in self.declared or self.forward_refs:
                    self.i += 1
                    return VarRef(t.text)
                roles = self.lex.role_names.get(t.text.casefold())
                if roles:
                    self.i += 1
                    return RoleSpec(roles, t.text)
                ahead = " ".join(x.text for x in self.toks[self.i:self.i + 4]).casefold()
                unary = next((n for v, n in self.lex.unary.items() if ahead.startswith(v)),
                             None)
                if unary is not None:
                    raise ParseError(
                        "%r reads the unary fact type %s, which is a property rather than a "
                        "step: it has one role, so there is nothing on the other side to walk "
                        "to and no path can use it. Filter on the value it was derived from "
                        "instead." % (self._context(), unary))
                raise ParseError("%r is neither a type in this schema nor a variable bound "
                                 "earlier in this query (near %r)"
                                 % (t.text, self._context()))
            self.i += 1
            spec = TypeSpec(cid)
            nxt = self.peek()
            if nxt is not None and nxt.kind == "punct" and nxt.text == ":":
                self.i += 1
                spec.denotation = self.parse_denotation()
            elif nxt is not None and nxt.kind == "word" \
                    and nxt.text.casefold() not in self.lex.by_name \
                    and not self.at_phrase(*NAMEABLE_BLOCKERS) \
                    and not self._at_verb():
                spec.var = nxt.text
                self.declared.add(nxt.text)
                self.i += 1
            return spec

        raise ParseError("cannot parse %r" % self._context())

    def _at_verb(self) -> bool:
        """Is a verb part next, allowing for a prefix such as OPTIONALLY (B.2's prefix slot)?"""
        save = self.i
        self.match_phrase(["OPTIONALLY"])
        got = self.match_phrase(self.lex.verb_phrases)
        self.i = save
        return got is not None

    def parse_denotation(self):
        t = self.peek()
        if t is not None and t.kind == "punct" and t.text == "!":
            self.i += 1
            name = self.peek()
            if name is None or name.kind != "word":
                raise ParseError("expected a variable name after '!'")
            self.i += 1
            return ("!", name.text)
        if t is not None and t.kind == "punct" and t.text == "(":
            self.i += 1
            items = [self.parse_denotation()]
            while self.peek() and self.peek().kind == "punct" and self.peek().text == ",":
                self.i += 1
                items.append(self.parse_denotation())
            self.expect_punct(")")
            return tuple(items)
        return self.parse_atom()

    # -- conditions --------------------------------------------------------

    # Tighter binds first. A flat left-associative chain read `a OR b AND c` as
    # `(a OR b) AND c`, which is not what either the report or anyone typing it means.
    # NOT binds tightest (handled in parse_condition_atom), then AND, XOR, OR, IMPLIES,
    # with IFF loosest -- the usual ordering for the connectives of section 7.5.
    LOGIC_PRECEDENCE = {"and": 4, "xor": 3, "or": 2, "implies": 1, "iff": 0}

    def parse_condition(self, min_precedence=0):
        left = self.parse_condition_atom()
        while True:
            save = self.i
            # `AND ALSO` and `OR OTHERWISE` begin with a boolean keyword but are path
            # operators, not conditions. LOGIC's longest-first rule cannot separate them
            # because the phrases are not in LOGIC at all, so look before taking one.
            if self.at_phrase(*FR_SET):
                return left
            op = self.try_phrase(*LOGIC)
            if op is None:
                return left
            key = LOGIC[op]
            precedence = self.LOGIC_PRECEDENCE.get(key)
            if precedence is None:
                raise ParseError("%r has no defined precedence; the keyword table and the "
                                 "precedence table disagree" % op)
            if precedence < min_precedence:
                self.i = save                      # binds looser than the caller's level
                return left
            right = self.parse_condition(precedence + 1)
            if isinstance(left, Logical) and left.op == key:
                left.operands.append(right)
            else:
                left = Logical(key, [left, right])

    def parse_condition_atom(self):
        if self.try_phrase("NOT"):
            return Not(self.parse_condition_atom())
        if self.try_phrase("SOME"):
            return Some(self.parse_descriptor())
        if self.peek() and self.peek().kind == "punct" and self.peek().text == "(":
            save = self.i
            self.i += 1
            inner = self.parse_condition()
            self.expect_punct(")")
            # `(s + 1) * 2 > 1`: the bracket was a scalar's, not a condition's. An operator
            # after it says so; start again and let parse_scalar own the bracket.
            nxt = self.peek()
            if nxt is not None and ((nxt.kind == "punct" and nxt.text in "+-*/")
                                    or self.at_phrase(*VALUE_CMP) or self.at_phrase(*SET_CMP)):
                self.i = save
                return self.parse_fr_level()
            return inner
        # A condition's atom is a comparison, never an Fr expression: the `AND ALSO` after
        # `WHERE d <> 'HR'` is a path operator belonging to the descriptor outside, and taking
        # it here rooted the branch at the last thing named instead of at the head.
        return self.parse_comparison()


def parse(model: dict, text: str) -> Query:
    return Parser(Lexicon(model), text).parse_query()
