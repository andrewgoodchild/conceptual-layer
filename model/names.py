#!/usr/bin/env python3
"""How a schema spells things: camelCase, snake_case, plurals, abbreviations.

One place, because there were two. `reverse/derive.py` has understood `InvoiceLineId`,
`dept_code` and `emp` for `employee` since rule 10 was written -- that knowledge is how a
column becomes a concept name. `conquer/link.py` then grew its own splitter and its own
stemmer for schema linking, and the private stemmer was immediately wrong in a way the shared
one is not: it took `employees` to `employe` while `Employee` stayed `Employee`, so the one
word a question and a model had in common stopped matching.

Nothing here is specific to either direction. A name is split the same way whether it is being
turned into a concept or matched against a question, so both import from here.
"""

from __future__ import annotations

import re
from typing import List, Optional

_SEPARATOR = re.compile(r"[^0-9a-zA-Z]+")
_HUMP = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def words(name: str) -> List[str]:
    """Split on separators and on CamelCase humps. `InvoiceLineId` -> [Invoice, Line, Id],
    `dept_code` -> [dept, code], `CustomerTypeID` -> [Customer, Type, ID]."""
    out = []
    for chunk in _SEPARATOR.split(name or ""):
        out.extend(_HUMP.findall(chunk))
    return out


def pascal(name: str) -> str:
    out = []
    for w in words(name):
        out.append(w if (w.isupper() and len(w) <= 3) else w[:1].upper() + w[1:].lower())
    return "".join(out) or "X"


def singular(name: str) -> str:
    low = (name or "").casefold()
    for suffix, repl in (("ies", "y"), ("ches", "ch"), ("shes", "sh"),
                         ("sses", "ss"), ("xes", "x"), ("zes", "z")):
        if low.endswith(suffix):
            return name[: -len(suffix)] + repl
    if low.endswith("s") and not low.endswith("ss") and not low.endswith("us"):
        return name[:-1]
    return name


def is_abbrev(short: str, long: str) -> bool:
    """`emp` for `employee` (a prefix), `dept` for `department` (a contraction: d-e-p-t are
    in order but not contiguous, since `department` starts `depa`).

    Subsequence with a matching first letter, three characters minimum -- below that every
    column prefix in the schema matches something. Still a guess: `dot` is a subsequence of
    `department` too. Every name derived from one is reported.
    """
    s, l = (short or "").casefold(), (long or "").casefold()
    if len(s) < 3 or len(s) >= len(l) or s[0] != l[0]:
        return False
    it = iter(l)
    return all(ch in it for ch in s)


# --------------------------------------------------------------------------- units

#  A column whose name ends in a unit is the only record the schema keeps of that unit:
#  `airtempc` and `objtempk` are both temperatures, in Celsius and kelvin, and nothing but
#  the last letter says so. ORM has somewhere to put this -- ORMCore's UnitBased reference
#  mode, "a value type associated with a measurable unit" -- so it is worth recovering.
#
#  Longest suffix first, so `dbm` (power) is not read as `db` (a ratio), and `tempk` before
#  `k`. Only suffixes long enough to be unambiguous appear: a bare `c` or `s` matches half
#  the schema, so Celsius is only recognised in `tempc`.
UNIT_SUFFIXES = (
    ("tempc", "degC"), ("tempk", "K"), ("dbm", "dBm"), ("hpa", "hPa"), ("pct", "%"),
    ("mhz", "MHz"), ("ghz", "GHz"), ("khz", "kHz"), ("gyr", "Gyr"), ("sol", "M_sun"),
    ("deg", "deg"), ("rad", "rad"), ("hrs", "h"), ("sec", "s"), ("min", "min"),
    ("kg", "kg"), ("km", "km"), ("mm", "mm"), ("cm", "cm"), ("ms", "ms"),
    ("hz", "Hz"), ("db", "dB"), ("ly", "ly"), ("pc", "pc"), ("au", "AU"),
)

#  Words that end in one of those suffixes without meaning it. `address` is not attoseconds.
_NOT_A_UNIT = frozenset((
    "sec", "deg", "min", "rad", "sol", "db", "ms", "hz", "ly", "pc", "au", "km", "kg",
    "cm", "mm", "pct", "hrs", "address", "status", "process", "access", "class", "gas",
    "analysis", "diagnosis", "basis", "bias", "alias", "atlas", "index", "codec",
))


#  Single tokens that end in `ly` without being light-years: adverbs and the nouns a schema
#  actually uses. `sourcedistly` is a distance in light-years; `daily` is how often.
_LY_WORDS = ("daily", "hourly", "weekly", "monthly", "yearly", "quarterly", "annually",
             "anomaly", "supply", "family", "assembly", "early", "only", "reply", "apply",
             "fully", "successfully", "rally", "italy", "july", "poly", "nightly")


def _unit_in_token(c: str) -> Optional[str]:
    """The unit a single squashed token ends in (`freqmhz`, `pulsewidms`), or None."""
    if c in _NOT_A_UNIT or (c.endswith("ly") and any(c.endswith(w) for w in _LY_WORDS)):
        return None
    for suffix, unit in UNIT_SUFFIXES:
        if not c.endswith(suffix):
            continue
        stem = c[:-len(suffix)].strip("_")
        #  Something has to be left, and it has to be a word rather than a stray letter --
        #  `ms` alone is a column called ms, not milliseconds of something.
        if len(stem) >= 2 and stem not in _NOT_A_UNIT:
            #  `ms` is milliseconds on a duration and metres per second on a speed, and the
            #  stem is the only thing that says which. `pulsewidms` is a width; `windspeedms`
            #  is a speed. Guessing wrong here is worse than most: the two differ by 10^3
            #  and by dimension, so nothing downstream would catch it.
            if unit == "ms" and any(w in stem for w in ("speed", "velocity", "vel")):
                return "m/s"
            #  `pulsepersec` is pulses per second, a rate -- the reciprocal of the unit the
            #  suffix names, not the unit itself. Merging it into Duration because it ends
            #  in `sec` would put a frequency and a length of time in one domain.
            if stem.endswith("per") and len(stem) > 5:
                return "1/%s" % unit
            return unit
    return None


def unit_of(column: str) -> Optional[str]:
    """The measurable unit a column name ends in, or None.

    Name-based and therefore a guess, like every other rule 10 answer. It is a cheap one to
    check and an expensive one to miss: a model that cannot say `freqmhz` is megahertz
    cannot say that `freqmhz` and `centerfreqmhz` are the same domain either.

    A name split into words (`sess_dur_min`, `EquipmentCostDaily`) names its unit as a whole
    last word or not at all. Reading a suffix off the last word's letters is what made
    `weight_grams` milliseconds, `spatial_dims` a duration and `is_anomaly` light-years
    (finding 172); only a single squashed token (`freqmhz`) is read by its ending.
    """
    parts = [w.casefold() for w in words(column.strip("_"))]
    if not parts:
        return None
    if len(parts) == 1:
        return _unit_in_token(parts[0])
    last = parts[-1]
    units = dict(UNIT_SUFFIXES)
    if last not in units:
        return None
    unit = units[last]
    before = parts[-2]
    if before == "per":
        return "1/%s" % unit
    if unit == "ms" and any(w in "".join(parts[:-1]) for w in ("speed", "velocity", "vel")):
        return "m/s"
    return unit


#  What each unit measures, so a merged domain can be named for the quantity rather than for
#  one of the columns that happened to reach it. A quantity with more than one unit in play
#  keeps them apart -- Celsius and kelvin are the same quantity and not the same domain, and
#  a model that merges them is wrong by 273.15.
#  A unit suffix that carries a quantity word along with the unit. Stripping `tempc` off a
#  name to leave the unit in its own slot also strips "temperature", so the name that comes
#  back is `AirTempC` -> `Air`, which has lost the thing being measured. These put the word
#  back. Every other suffix in UNIT_SUFFIXES is a pure unit and drops cleanly.
UNIT_TOKEN_RESIDUE = {"tempc": "temperature", "tempk": "temperature"}

UNIT_QUANTITY = {
    "deg": "Angle", "rad": "Angle",
    "MHz": "Frequency", "GHz": "Frequency", "kHz": "Frequency", "Hz": "Frequency",
    "K": "Temperature", "degC": "Temperature",
    "s": "Duration", "ms": "Duration", "min": "Duration", "h": "Duration",
    "m/s": "Speed", "km": "Length", "mm": "Length", "cm": "Length",
    "ly": "Distance", "pc": "Distance", "AU": "Distance",
    "kg": "Mass", "M_sun": "Mass", "hPa": "Pressure", "%": "Percentage",
    "dB": "Level", "dBm": "Power", "Gyr": "Age",
    #  Reciprocals. A count per unit time is a rate, and is not the quantity its suffix names.
    "1/s": "Rate", "1/min": "Rate", "1/h": "Rate",
}


def quantity_name(unit: str, units_in_play=()) -> str:
    """A name for the domain of values measured in `unit`.

    `Frequency` where megahertz is the only frequency unit the schema uses, `FrequencyInHz`
    where it uses two -- because then the bare quantity would name two different domains.
    """
    quantity = UNIT_QUANTITY.get(unit)
    if not quantity and unit.startswith("1/"):
        #  `cost_per_kg` is an amount per kilogram; its domain was named `1Kg` (finding 172).
        return "Per" + pascal(_SEPARATOR.sub(" ", unit[2:]))
    if not quantity:
        return pascal(_SEPARATOR.sub(" ", unit)) or "Quantity"
    kin = {u for u in units_in_play if UNIT_QUANTITY.get(u) == quantity}
    if len(kin) > 1:
        #  `1/s` has no readable pascal form, so a reciprocal disambiguates on its base unit.
        label = unit[2:] + "Inverse" if unit.startswith("1/") else unit
        return "%sIn%s" % (quantity, pascal(_SEPARATOR.sub(" ", label)))
    return quantity


# --------------------------------------------------------------------------- abbreviations

#  Schemas abbreviate, and a reverse engineer that treats a column name as an opaque token
#  carries the abbreviation into the model: `observstation` becomes a value type called
#  ObservatoryObservstation, and the reading "Observatory has Observstation" tells a reader
#  the observatory is identified by an observation. It is identified by its name.
#
#  Two rules keep this from doing damage. An entry only fires on a whole word of the split
#  name, never on a substring -- `cat` must not turn `category` into `catalogue`. And the
#  table is deliberately small and general: domain words belong in a --glossary file, because
#  `sig` is a signal in one schema and a signature in the next.
GLOSSARY = {
    "addr": "address", "amt": "amount", "attr": "attribute", "auth": "authorisation",
    "avg": "average", "bal": "balance", "cat": "category", "cfg": "configuration",
    "cnt": "count", "col": "column", "comp": "compliance", "conf": "confidence",
    "config": "configuration", "cust": "customer", "db": "database", "dept": "department",
    "desc": "description", "dest": "destination", "dist": "distance", "doc": "document",
    "dt": "date", "dur": "duration", "emp": "employee", "eq": "equipment",
    "equip": "equipment", "err": "error", "freq": "frequency", "grp": "group",
    "hist": "history", "idx": "index", "info": "information", "init": "initial",
    "inv": "invoice", "lvl": "level", "max": "maximum", "mgr": "manager", "min": "minimum",
    "msg": "message", "num": "number", "nr": "number", "obj": "object", "obs": "observation",
    "org": "organisation", "params": "parameters", "pct": "percentage", "perf": "performance",
    "pos": "position", "prio": "priority", "prob": "probability", "proc": "processing",
    "prod": "product", "qty": "quantity", "qc": "quality control", "reg": "registry",
    "req": "request", "res": "research", "rev": "review", "sec": "security",
    "seq": "sequence", "src": "source", "stat": "status", "std": "standard",
    "temp": "temperature", "ts": "timestamp", "txn": "transaction", "usr": "user",
    "val": "value", "ver": "version", "vol": "volume",
}

#  Squashed compounds: a single token that is two words with no separator. Unlike GLOSSARY
#  these are matched as a whole token and rewritten to several words, which is the case a
#  word-by-word expansion cannot reach. `observstation` is the one that started this.
COMPOUNDS = {
    "observstation": "observation station",
    "recordregistry": "record registry",
    "signalregistry": "signal registry",
    "telescregistry": "telescope registry",
}


def expand(name: str, glossary=None) -> str:
    """Rewrite a name's abbreviated words in full. Returns the name unchanged if none match.

    Word-level only. The name is split the way every other rule 10 answer splits it, each
    word is looked up whole, and anything unrecognised is left exactly as it was -- so a name
    the glossary knows nothing about survives untouched rather than being half-guessed.
    """
    table = dict(GLOSSARY)
    compounds = dict(COMPOUNDS)
    for k, v in (glossary or {}).items():
        (compounds if " " in v else table)[k.casefold()] = v
    vocab = _vocabulary(table, compounds)
    out, changed = [], False
    for w in words(name):
        key = w.casefold()
        if key in compounds:
            out.extend(compounds[key].split())
            changed = True
            continue
        if key in table:
            out.append(table[key])
            changed = True
            continue
        #  A word the tables do not know may still be several words squashed together.
        #  Only a token that decomposes completely is cut; anything else is left as it came.
        pieces = segment(key, vocab)
        if pieces:
            out.extend(table.get(p, p) for p in pieces)
            changed = True
            continue
        out.append(w)
    return " ".join(out) if changed else name


def read_glossary(path: str) -> dict:
    """A user's own abbreviations, one `short = long` per line; `#` starts a comment.

    Domain words live here rather than in GLOSSARY because they are not portable: `sig` is a
    signal in one schema and a signature in the next, and a built-in guess would be wrong
    half the time without saying so.
    """
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            short, _, long = line.partition("=")
            short, long = short.strip().casefold(), long.strip()
            if short and long:
                out[short] = long
    return out


#  Whole words a squashed token may be built from, beyond the abbreviations. Domain-neutral
#  and deliberately short: the point is to recognise a boundary, not to know the domain.
_COMMON = frozenset((
    "account", "action", "active", "address", "age", "air", "alert", "amount", "analysis",
    "angle", "area", "asset", "audit", "band", "bank", "base", "batch", "book", "cache",
    "call", "card", "case", "cell", "change", "check", "city", "claim", "class", "client",
    "code", "collab", "company", "contact", "content", "cost", "country", "credit", "crew",
    "data", "date", "day", "detect", "device", "disc", "discover", "drift", "due", "end",
    "entry", "event", "file", "first", "flag", "flow", "follow", "fund", "group", "hash",
    "head", "health", "hour", "house", "image", "index", "input", "item", "job", "join",
    "key", "kind", "label", "last", "layer", "length", "level", "limit", "line", "link",
    "list", "load", "local", "lock", "log", "long", "loss", "main", "mark", "mass", "match",
    "mode", "model", "month", "name", "net", "network", "node", "note", "null", "object",
    "offset", "order", "output", "owner", "page", "pass", "path", "pattern", "pay", "peer",
    "period", "phase", "phone", "place", "plan", "point", "policy", "pool", "port", "post",
    "power", "press", "price", "profile", "project", "pub", "pulse", "quality", "queue",
    "range", "rate", "ratio", "read", "reason", "record", "ref", "region", "report",
    "request", "result", "risk", "role", "room", "root", "round", "row", "rule", "run",
    "sale", "scan", "scheme", "school", "score", "seen", "sensor", "server", "service",
    "session", "set", "shift", "ship", "short", "side", "sign", "signal", "site", "size",
    "slot", "sort", "source", "space", "span", "speed", "split", "staff", "stage", "stamp",
    "start", "state", "station", "step", "stock", "storage", "store", "stream", "string",
    "sub", "sum", "system", "table", "tag", "target", "task", "team", "test", "text",
    "time", "title", "token", "total", "town", "track", "trail", "type", "unit", "update",
    "usage", "use", "user", "value", "view", "week", "weight", "width", "wind", "word",
    "work", "write", "year", "zone",
))


def _vocabulary(table, compounds):
    """Every piece a squashed token may be cut into, longest first."""
    #  The identifier spellings; derive.py keeps the same tuple as KEY_SUFFIXES.
    vocab = set(_COMMON) | set(table) | {"id", "no", "nr", "code", "key"}
    vocab |= {u for u, _ in UNIT_SUFFIXES}
    for long in table.values():
        vocab |= {w for w in long.split() if len(w) > 2}
    for long in compounds.values():
        vocab |= {w for w in long.split() if len(w) > 2}
    return sorted(vocab, key=len, reverse=True)


def segment(token: str, vocab) -> Optional[List[str]]:
    """Cut a squashed token into known pieces, or None if it does not fully decompose.

    Full decomposition is the whole safety property. A token that cuts into known pieces with
    a remainder left over is not understood, and half-understanding a name is worse than
    leaving it alone: `category` starts with `cat` and finishes with nothing recognisable, so
    it comes back None and stays `category`. Fewest pieces wins, which prefers a real word to
    a pile of fragments.
    """
    token = token.casefold()
    if len(token) < 4:
        return None
    best: dict = {}

    def cut(rest):
        if not rest:
            return []
        if rest in best:
            return best[rest]
        best[rest] = None                     # guard against re-entering the same suffix
        found = None
        for piece in vocab:
            if len(piece) < 2 or not rest.startswith(piece):
                continue
            tail = cut(rest[len(piece):])
            if tail is not None and (found is None or len(tail) + 1 < len(found)):
                found = [piece] + tail
        best[rest] = found
        return found

    pieces = cut(token)
    return pieces if pieces and len(pieces) > 1 else None
