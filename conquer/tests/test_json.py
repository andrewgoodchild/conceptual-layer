#!/usr/bin/env python3
"""Rule 12 end to end: a document column becomes fact types a query can reach.

A `jsonb` column is a catalogue that stopped short, and every rule in `reverse/` exists to
recover schema a catalogue failed to declare. These cases check the whole path -- population
read, shape classified, fact types derived, path carried in the mapping, SQL emitted, answer
correct -- and they check the two ways it can go quietly wrong:

    the cast       SQLite's json_extract preserves storage class but DuckDB and PostgreSQL
                   hand back text, so `latitude > 9` must not compare '26.0325' to '9'. The
                   case that distinguishes them is here, not a number where both agree.
    the guard      a mapping column carrying a field the emitter does not understand must be
                   refused. Before this existed, `path` was ignored in silence and the query
                   returned the whole document as though it were the value -- a plausible
                   wrong answer, which is the failure this project exists to prevent.

    test_json.py [-v] [--only SUBSTRING]
"""

import argparse
import json
import os
import sqlite3
import tempfile
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "reverse"))

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402
import catalog as catalog_mod     # noqa: E402
import derive as derive_mod       # noqa: E402
import jsonshape                  # noqa: E402

DB = os.path.join(WORK, "json-fixture.sqlite")

# The two awkward cases are here because LiveSQLBench has them and the first build of this
# rule got both wrong (findings 87-88): keys that are not tidy identifiers, and a document
# key named like a column the table already has.
ROWS = [
    # Three shapes in one table, which is what a real warehouse looks like.
    ("bahrain", "Bahrain International Circuit",
     {"location": {"city": "Sakhir", "country": "Bahrain"}, "coordinates": {"latitude": 26.0325},
      "grip%": 88, "turns/km": 1.4, "Grade": "FIA 1", "": 0, 'a"b': 0},
     {"sand": 70, "limestone": 30}, "resurfaced 2023", "Grade 1"),
    ("catalunya", "Circuit de Barcelona-Catalunya",
     {"location": {"city": "Montmelo", "country": "Spain"}, "coordinates": {"latitude": 41.57},
      "grip%": 91, "turns/km": 3.1, "Grade": "FIA 1", "": 0, 'a"b': 0},
     {"granite": 55, "clay": 45}, None, "Grade 1"),
    ("istanbul", "Istanbul Park",
     {"location": {"city": None, "country": "Turkey"}, "coordinates": {"latitude": 40.9517},
      "grip%": 79, "turns/km": 2.6, "Grade": "FIA 2", "": 0, 'a"b': 0},
     {"basalt": 80, "shale": 15, "mica": 5}, "turn 8 is four-apex", "Grade 2"),
]


def build():
    os.makedirs(WORK, exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE circuits (
          circuit_id TEXT NOT NULL PRIMARY KEY,
          circuit_name TEXT NOT NULL,
          location_metadata TEXT,   -- a record: stable keys naming roles
          surface_mix TEXT,         -- a map: keys are data
          notes TEXT,               -- a bag: not JSON at all
          grade TEXT                -- a column the document also carries, under another case
        );''')
    conn.executemany("INSERT INTO circuits VALUES (?,?,?,?,?,?)",
                     [(a, b, json.dumps(c), json.dumps(d), e, f) for a, b, c, d, e, f in ROWS])
    conn.commit()
    conn.close()


TWIN = os.path.join(WORK, "json-twin.sqlite")


def build_twin():
    """Two documents on one table carrying the same keys.

    Finding 91: whichever column was processed first took the bare name, so a model read
    `MatchScore` beside `MatchAwayScore` and nothing said which was the home one. A label two
    documents share has to be qualified in both, or in neither.
    """
    if os.path.exists(TWIN):
        os.remove(TWIN)
    conn = sqlite3.connect(TWIN)
    conn.executescript(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, home TEXT, away TEXT);")
    conn.executemany("INSERT INTO matches VALUES (?,?,?)", [
        ("m%d" % i,
         json.dumps({"score": i, "team": "Home %d" % i}),
         json.dumps({"score": i * 2, "team": "Away %d" % i})) for i in range(3)])
    conn.commit()
    conn.close()
    cat = catalog_mod.from_sqlite(TWIN)
    c = sqlite3.connect("file:%s?mode=ro" % TWIN, uri=True)
    model, _ = derive_mod.derive(cat, json_shapes=jsonshape.read(c, cat))
    c.close()
    return model


def model_for(infer_json=True):
    cat = catalog_mod.from_sqlite(DB)
    shapes = {}
    if infer_json:
        conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        shapes = jsonshape.read(conn, cat)
        conn.close()
    model, report = derive_mod.derive(cat, json_shapes=shapes)
    return model, report, shapes


# -- expectations ----------------------------------------------------------------------------

def rows(expected):
    return ("rows", expected)


def refuses(fragment):
    return ("refuses", fragment)


CASES = [
    ("a value inside a document is queryable as an ordinary fact type",
     "LIST n, c FROM Circuit has CircuitName n AND ALSO has CircuitLocationCity c",
     rows([("Bahrain International Circuit", "Sakhir"),
           ("Circuit de Barcelona-Catalunya", "Montmelo")])),

    # Istanbul's city is null inside the document. A role read asserts the fact holds, so the
    # row drops -- the same total semantics as any other optional column (binding-sql92 §6).
    ("a null inside the document drops the row, as a null column would",
     "LIST c FROM Circuit has CircuitLocationCity c",
     rows([("Sakhir",), ("Montmelo",)])),

    # Rule 12 reaches `fn.jsonPath` through `render_document_path`, which builds the path
    # itself. A writer reaches the same function through `render_call`, which has already
    # rendered the argument to a bind marker -- and the template quoted its placeholder, so
    # what came out was `json_extract(col, '?')`: a literal question mark with a parameter
    # left over. No user-written jsonPath had ever run. Found by a LiveSQLBench writer who
    # picked a document apart with substr and instr instead, for want of a function that was
    # in the model all along.
    # A map's keys are data, so rule 12 leaves the column whole and the document itself is
    # nameable -- which is exactly when a writer needs to reach into it by hand.
    ("a writer may call jsonPath directly, not only through a mapped path",
     "LIST n, g FROM Circuit has CircuitName n AND ALSO has CircuitSurfaceMix d "
     "AND ALSO jsonPath(d, '$.granite') AS g",
     # A key the document lacks reads as null rather than dropping the row: the fact asserted
     # is `has CircuitSurfaceMix`, and that holds for all three.
     rows([("Bahrain International Circuit", None),
           ("Circuit de Barcelona-Catalunya", 55),
           ("Istanbul Park", None)])),

    ("a second path into the same column is a second fact type",
     "LIST c, k FROM Circuit has CircuitLocationCity c AND ALSO has CircuitLocationCountry k",
     rows([("Sakhir", "Bahrain"), ("Montmelo", "Spain")])),

    # The case that separates a cast from no cast: as text, '26.0325' > '9' is false.
    ("a numeric path is compared as a number, not as text",
     "LIST n FROM Circuit has CircuitName n AND ALSO has CircuitCoordinatesLatitude lat "
     "WHERE lat > 9",
     rows([("Bahrain International Circuit",), ("Circuit de Barcelona-Catalunya",),
           ("Istanbul Park",)])),

    ("and the comparison still discriminates",
     "LIST n FROM Circuit has CircuitName n AND ALSO has CircuitCoordinatesLatitude lat "
     "WHERE lat > 30",
     rows([("Circuit de Barcelona-Catalunya",), ("Istanbul Park",)])),

    # Finding 87. Real keys are `packetLoss%`, `ISO_27001?`, `tx/hr`. An allowlist of tidy
    # identifiers refused 17 legitimate columns across LiveSQLBench; bracket-quoting carries
    # them, and every dialect's JSONPath accepts `$."grip%"`.
    ("a key that is not a tidy identifier is still readable",
     "LIST n FROM Circuit has CircuitName n AND ALSO has CircuitGrip g WHERE g > 85",
     rows([("Bahrain International Circuit",), ("Circuit de Barcelona-Catalunya",)])),

    ("and one with a slash in it",
     "THE MAXIMUM t IN Circuit has CircuitTurnsKm t",
     rows([(3.1,)])),

    # Finding 88. `circuits.grade` and the document's `Grade` differ only by case, so both
    # fact types wanted the name CircuitGrade and a query naming it picked one arbitrarily.
    # The derived one now carries the column it came out of, and both stay reachable.
    ("a document key colliding with a real column keeps both addressable",
     "LIST a, b FROM Circuit has CircuitGrade a AND ALSO has CircuitLocationMetadataGrade b",
     rows([("Grade 1", "FIA 1"), ("Grade 1", "FIA 1"), ("Grade 2", "FIA 2")])),

    ("a path value aggregates like any other",
     "THE MAXIMUM lat IN Circuit has CircuitCoordinatesLatitude lat",
     rows([(41.57,)])),

    ("and groups like any other",
     "LIST k, t FROM Circuit has CircuitLocationCountry k AND ALSO "
     "has CircuitCoordinatesLatitude lat AND ALSO THE COUNT OF lat GROUPED BY k AS t",
     rows([("Bahrain", 1), ("Spain", 1), ("Turkey", 1)])),

    # Building a document rather than reading one. Five of LiveSQLBench's 180 SQLite tasks
    # want "a JSON array of objects" in a column, and both writers who met one spelled the
    # object with `concat` and eleven quote marks -- and lost, because the gathered value
    # was a string that looked like an object. `jsonObject` is the variadic call every
    # dialect has; SQLite renders it exactly as its own json_object does, which is what
    # the gold is compared against byte for byte.
    ("a query can build an object, and a list of them gathers objects, not strings",
     "LIST k, l FROM Circuit has CircuitLocationCountry k AND ALSO has CircuitName n "
     "AND ALSO has CircuitGrip g AND ALSO jsonObject('name', n, 'grip', g) AS o "
     "AND ALSO THE LIST OF o GROUPED BY k AS l",
     rows([("Bahrain", '[{"name":"Bahrain International Circuit","grip":88}]'),
           ("Spain", '[{"name":"Circuit de Barcelona-Catalunya","grip":91}]'),
           ("Turkey", '[{"name":"Istanbul Park","grip":79}]')])),

    ("an object nests, and a conditional inside it is a value like any other",
     "LIST o FROM Circuit has CircuitName n AND ALSO has CircuitGrip g "
     "AND ALSO jsonObject('name', n, 'surface', jsonObject('grip', g, "
     "'band', if(g > 85, 'high', 'low'))) AS o",
     rows([('{"name":"Bahrain International Circuit","surface":{"grip":88,"band":"high"}}',),
           ('{"name":"Circuit de Barcelona-Catalunya","surface":{"grip":91,"band":"high"}}',),
           ('{"name":"Istanbul Park","surface":{"grip":79,"band":"low"}}',)])),

    # Text that already is a document is re-read as one with `json`, because SQLite gathers
    # it as a string otherwise: the shape both writers were in.
    ("text built by hand is gathered as a document once json() says it is one",
     "LIST k, l FROM Circuit has CircuitLocationCountry k AND ALSO has CircuitGrip g "
     "AND ALSO concat('{\"grip\": ', g, '}') AS t AND ALSO json(t) AS j "
     "AND ALSO THE LIST OF j GROUPED BY k AS l",
     rows([("Bahrain", '[{"grip":88}]'), ("Spain", '[{"grip":91}]'),
           ("Turkey", '[{"grip":79}]')])),

    ("and without it, as the string it is",
     "LIST k, l FROM Circuit has CircuitLocationCountry k AND ALSO has CircuitGrip g "
     "AND ALSO concat('{\"grip\": ', g, '}') AS t AND ALSO THE LIST OF t GROUPED BY k AS l",
     rows([("Bahrain", '["{\\"grip\\": 88}"]'), ("Spain", '["{\\"grip\\": 91}"]'),
           ("Turkey", '["{\\"grip\\": 79}"]')])),
]

TWIN_CASES = [
    ("twin documents both carry their column in the name",
     "LIST h, a FROM Match has MatchHomeScore h AND ALSO has MatchAwayScore a",
     rows([(0, 0), (1, 2), (2, 4)])),

    ("and neither claimed the bare name",
     "LIST v FROM Match has MatchScore v",
     refuses("MatchScore")),

    ("the values really are the two different documents",
     "LIST h, a FROM Match has MatchHomeTeam h AND ALSO has MatchAwayTeam a",
     rows([("Home 0", "Away 0"), ("Home 1", "Away 1"), ("Home 2", "Away 2")])),
]

# Shape classification, checked directly: the three kinds must not be confused, because
# deriving fact types from a map invents an unbounded sparse schema out of one sample.
SHAPES = [
    ("a record is recognised", "location_metadata", "record"),
    ("a map is not mistaken for a record", "surface_mix", "map"),
    # SQLite has no JSON type, so `notes` is TEXT like the other two. It gets no verdict at
    # all because its values do not even look like documents -- cheaper than classifying, and
    # the same outcome: left alone.
    ("prose is never mistaken for a document", "notes", "<absent>"),
]


def run_case(model, conn, lexicon, emitter, query, expect):
    kind, want = expect
    try:
        _, sql, params = driver.transpile(model, query, lexicon, emitter)
    except Exception as e:                                              # noqa: BLE001
        if kind == "refuses":
            return (want in str(e)), str(e)[:110]
        return False, "%s: %s" % (type(e).__name__, str(e)[:110])
    if kind == "refuses":
        return False, "expected a refusal naming %r, got SQL" % want
    got = conn.execute(sql, params).fetchall()
    if sorted(got) != sorted(want):
        return False, "got %r, want %r" % (got, want)
    return True, "%d row(s)" % len(got)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    build()
    model, report, shapes = model_for()
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    lexicon, emitter = parser_mod.Lexicon(model), sql_mod.Emitter(model)
    passed = failed = 0

    for name, col, want in SHAPES:
        if args.only and args.only.lower() not in name.lower():
            continue
        got = shapes.get(("circuits", col), ("<absent>", [], ""))[0]
        if got == want:
            passed += 1
            print("ok    %-64s %s" % (name, got if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        classified %r as %r, want %r" % (name, col, got, want))

    # Finding 90. A key the emitter cannot spell must not become a fact type: `$.""` is a
    # JSONPath error at execution, and a key carrying a quote ends the literal. Deriving one
    # makes the model assert a fact no query can read, which is worse than not having it.
    # Every *other* key in the same document must still come through.
    name = "a key that cannot be spelled is not derived at all"
    if not args.only or args.only.lower() in name.lower():
        paths = [tuple(c["path"]) for c in model["mapping"]["columns"] if c.get("path")]
        unspellable = [p for p in paths if any(not k or '"' in k for k in p)]
        alongside = ("grip%",) in paths          # the same document's other keys survive
        if not unspellable and alongside:
            passed += 1
            print("ok    %-64s %s" % (name, "%d path columns" % len(paths) if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        derived %r; other keys present: %s"
                  % (name, unspellable, alongside))

    # The map and the bag must survive as opaque values rather than vanishing.
    for name, want in (("a map stays queryable as an opaque value", "CircuitSurfaceMix"),
                       ("a bag stays queryable as an opaque value", "CircuitNotes")):
        if args.only and args.only.lower() not in name.lower():
            continue
        have = any(c["name"] == want for c in model["concepts"] if c["kind"] == "value")
        passed, failed = (passed + 1, failed) if have else (passed, failed + 1)
        print(("ok    %-64s" % name) if have else ("FAIL  %s\n        no value type %r" % (name, want)))

    # A value domain inside a document. `apply_domains` reads what `_domains` mined per
    # column, and a path is not a column, so every fact type rule 12 derived came out with
    # no domain and a writer probed each one with ./try. Its own fixture: the domain miner
    # wants a population, and the three circuits above are not one.
    name = "a document path with a handful of values gets a value domain"
    if not args.only or args.only.lower() in name.lower():
        dpath = tempfile.mktemp(suffix=".sqlite")
        dconn = sqlite3.connect(dpath)
        dconn.execute("CREATE TABLE reading (id INTEGER PRIMARY KEY, doc TEXT)")
        for i in range(60):
            dconn.execute("INSERT INTO reading VALUES (?, ?)", (i, json.dumps(
                {"quality": ["Low", "Medium", "High"][i % 3], "grip%": 80 + i,
                 "status": "" if i % 10 == 0 else "ok"})))
        dconn.commit()
        cat = catalog_mod.from_sqlite(dpath)
        shapes = jsonshape.read(dconn, cat)
        dmodel, dreport = derive_mod.derive(cat, json_shapes=shapes)
        import population as pop
        n = pop.apply_document_domains(dconn, dmodel, dreport)
        by_name = {c["name"]: c for c in dmodel["concepts"] if c["kind"] == "value"}
        quality = (by_name.get("ReadingQuality") or {}).get("restriction", {}).get("values")
        grip = (by_name.get("ReadingGrip") or {}).get("restriction")
        status = (by_name.get("ReadingStatus") or {}).get("restriction", {}).get("values")
        ok = quality == ["High", "Low", "Medium"] and grip is None and status == ["ok"]
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(("ok    %-64s %d domain(s)" % (name, n)) if ok else
              "FAIL  %s\n        quality %r, grip %r, status %r" % (name, quality, grip, status))
        dconn.close()
        os.remove(dpath)

    # Finding 91: twin documents, checked on their own fixture.
    twin = build_twin()
    tconn = sqlite3.connect("file:%s?mode=ro" % TWIN, uri=True)
    tlex, tem = parser_mod.Lexicon(twin), sql_mod.Emitter(twin)
    for name, query, expect in TWIN_CASES:
        if args.only and args.only.lower() not in name.lower():
            continue
        ok, note = run_case(twin, tconn, tlex, tem, query, expect)
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(("ok    %-64s %s" % (name, note if args.verbose else "")) if ok
              else "FAIL  %s\n        %s\n        %s" % (name, query, note))
    tconn.close()

    for name, query, expect in CASES:
        if args.only and args.only.lower() not in name.lower():
            continue
        ok, note = run_case(model, conn, lexicon, emitter, query, expect)
        if ok:
            passed += 1
            print("ok    %-64s %s" % (name, note if args.verbose else ""))
        else:
            failed += 1
            print("FAIL  %s\n        %s\n        %s" % (name, query, note))

    # The guard. A mapping column carrying a field the emitter does not understand is refused,
    # not approximated -- and rule 12's own `path` is only safe because of it.
    for name, mutate, fragment in (
            ("an unknown mapping field is refused, not ignored",
             lambda c: c.update({"encoding": "base64"}), "does not understand"),
            ("a path with no fn.jsonPath in the model is refused",
             None, "no `fn.jsonPath`")):
        if args.only and args.only.lower() not in name.lower():
            continue
        m = json.loads(json.dumps(model))
        if mutate:
            mutate(m["mapping"]["columns"][0])
        else:
            m["functions"] = [f for f in m["functions"] if f["id"] != "fn.jsonPath"]
        try:
            driver.transpile(m, "LIST c FROM Circuit has CircuitLocationCity c",
                             parser_mod.Lexicon(m), sql_mod.Emitter(m))
            failed += 1
            print("FAIL  %s\n        emitted SQL instead of refusing" % name)
        except Exception as e:                                          # noqa: BLE001
            if fragment in str(e):
                passed += 1
                print("ok    %-64s %s" % (name, str(e)[:60] if args.verbose else ""))
            else:
                failed += 1
                print("FAIL  %s\n        refused with %s" % (name, str(e)[:120]))

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
