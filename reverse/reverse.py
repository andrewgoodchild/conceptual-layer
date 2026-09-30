#!/usr/bin/env python3
"""Reverse engineer an ORM model from a relational database.

    reverse.py DB.sqlite -o out/                 SQLite file
    reverse.py --json catalog.json -o out/       fixture
    reverse.py --dsn "postgresql://..." -o out/  live server (needs a DB-API driver)

Writes three things into the output directory:

    <name>.ccm.json   the draft Common Core Model, including the relational mapping
    <name>.orm        the same schema as a NORMA file, to view and validate (one way: no importer)
    <name>.report.md  the worklist -- what was guessed, what was skipped, what is blocked

The model is a DRAFT. See the rule table in reverse/README.md.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog as catalog_mod          # noqa: E402
import derive as derive_mod           # noqa: E402
# after derive, which is what puts the repository root on the path
from model import names as names_mod    # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import forml                           # noqa: E402
import ormxml                          # noqa: E402

CONFIDENCE_ORDER = {"blocker-adjacent": 0, "guess": 1, "heuristic": 2, "sound": 3}


def render_report(report, source, model=None) -> str:
    s = report.summary
    lines = [
        "# Reverse engineering report",
        "",
        "Source: `%s`" % source,
        "",
        "> \"In practice, any draft ORM schema obtained by reverse engineering usually needs",
        "> many refinements.\"",
        ">",
        "> — Halpin, Evans, Hallock & MacLean, *Database Modeling with Microsoft Visio for",
        "> Enterprise Architects* (2003), ch. 8",
        "",
        "## What was derived",
        "",
        "| | |",
        "|---|---|",
        "| Tables read | %d |" % s["tables"],
        "| Entity types | %d |" % s["entityTypes"],
        "| Value types | %d |" % s["valueTypes"],
        "| Fact types | %d |" % s["factTypes"],
        "| Constraints | %d |" % s["constraints"],
        "",
    ]

    # The rest of this report asks a human to confirm constraints. Naming them "27
    # constraints" asks the impossible: nobody can confirm a uniqueness constraint from the
    # word "uniqueness". FORML 2 (Halpin & Curland 2006) is how ORM states them in a sentence
    # a domain expert can agree or disagree with, and it is what NORMA shows.
    if model is not None:
        try:
            sentences = forml.verbalize_model(model)
        except Exception:                                  # noqa: BLE001
            sentences = []
        if sentences:
            shown = sentences[:60]
            lines += ["## What the model says", "",
                      "Every constraint above, in FORML 2 — the controlled English NORMA "
                      "verbalizes into. Read these as claims about the business, and reject "
                      "the ones that are not true of it.", ""]
            lines += ["- %s" % x for x in shown]
            if len(sentences) > len(shown):
                lines.append("- *(%d more; the full set is in the model.)*"
                             % (len(sentences) - len(shown)))
            lines.append("")

    if report.blockers:
        lines += ["## Blockers", "",
                  "These stopped part of the derivation. Fix them and re-run.", ""]
        for b in report.blockers:
            lines += ["### `%s` — %s" % (b["subject"], b["rule"]),
                      "", b["message"], "", "**Do:** %s" % b["action"], ""]
    else:
        lines += ["## Blockers", "", "None.", ""]

    if report.refinements:
        lines += [
            "## Refinements", "",
            "Ordered least trustworthy first. Confidence is the column from the rule table in",
            "`reverse/README.md`: **sound** rules are",
            "recoverable from the catalog alone, **heuristic** rules are a reading of a shape",
            "that has other explanations, **guess** rules are name-based and prove nothing.",
            "",
        ]
        ordered = sorted(report.refinements,
                         key=lambda r: (CONFIDENCE_ORDER.get(r["confidence"], 9), r["rule"]))
        current = None
        for r in ordered:
            if r["confidence"] != current:
                current = r["confidence"]
                lines += ["### %s" % current.replace("-", " ").title(), ""]
            lines += ["- **`%s`** *(%s)* — %s" % (r["subject"], r["rule"], r["message"]),
                      "  **Do:** %s" % r["action"], ""]

    lines += [
        "## Next",
        "",
        "1. Open the `.orm` file in NORMA (or FactEngine Boston) and work through the list above.",
        "2. Renaming predicates first: every reading here is `{0} has {1}`, generated from",
        "   column names, and nothing in the database records what the fact actually says.",
        "3. Keep the `.ccm.json`. It carries the relational mapping, which the `.orm` file",
        "   cannot hold (`model/model.md` §6) and which the compiler needs to reach the data.",
        "",
    ]
    return "\n".join(lines)


# -- the passes ---------------------------------------------------------------------------
#
# Each population pass says which flag asks for it, what it reads, and what has to have run
# before it. `run_passes` walks them in this order and checks the `after` edges, so a rule
# that must see the catalogue before the analysis (1d), or the domains before the document
# domains (6b'), or the key rewrite before the partitions (7b), says so once, here, and not
# by its position in a three-hundred-line function. The order of the list is the order the
# report has always been written in; the edges are the reasons for it.
#
# What this buys beyond legibility is the build record: the flags a model was built with go
# into its `_comment`, because the SQLite tier's eighteen models were built by hand and the
# command existed nowhere, and it had to be recovered by rebuilding until the bytes matched
# (finding 156, `bench/livesql/README.md`).

class Build:
    """Everything a pass may read or write, in the order the passes fill it."""

    def __init__(self, args, cat, source):
        self.args, self.cat, self.source = args, cat, source
        self.conn = None                 # the data, opened only if a pass reads it
        self.analysis = None
        self.keys, self.refs, self.mandatory, self.referenced = [], [], [], []
        self.json_shapes, self.absorb = {}, {}
        self.model, self.report = None, None
        self.verified, self.shared = [], []
        self.ran = set()

    def data(self):
        if self.conn is None:
            import sqlite3
            self.conn = sqlite3.connect(self.args.sqlite)
            self.conn.text_factory = lambda b: b.decode("utf-8", "replace")
        return self.conn


def _pop():
    import population as population_mod          # noqa: E402  (after sys.path is set)
    return population_mod


def _verify_keys(b):
    # Before anything reads the catalogue's references: a declared foreign key no row
    # satisfies is not a reference (finding 172), and a rebuilt composite key is paired the
    # way the rows bear out.
    b.verified = _pop().verify_foreign_keys(b.data(), b.cat)
    b.shared = _pop().shared_key_links(b.data(), b.cat)


def _referenced_keys(b):
    # First, and on the catalogue: everything after this -- the analysis, the partitions,
    # the derivation -- should see the key the schema actually uses.
    b.referenced = _pop().prefer_referenced_keys(b.data(), b.cat)


def _analyse(b):
    pop = _pop()
    if b.args.infer_keys:
        # Rule 9c rides with --infer-keys rather than --infer-fks, and the division is
        # what each reads rather than what each finds: 9b and 9c both read the *data* to
        # recover a schema nobody declared, while rule 9 is a name heuristic that needs
        # no data at all. It matters because 9c changes the model rather than adding to
        # it -- `tags.WikiPostId` stops being a value and becomes a reference to Post,
        # which is truer and breaks every query written for the old shape. That is a
        # migration, not a free upgrade, and it should be asked for.
        b.analysis, b.keys, b.refs = pop.recover(b.data(), b.cat,
                                                 ignore_names=b.args.ignore_names)
    else:
        b.analysis = pop.analyse(b.data(), b.cat, ignore_names=b.args.ignore_names)


def _mandatory(b):
    b.mandatory = _pop().apply_mandatory(b.analysis, b.cat)


def _json(b):
    import jsonshape
    b.json_shapes = jsonshape.read(b.data(), b.cat)


def _partitions(b):
    b.absorb = {child: parent for child, parent, _, _, covers
                in _pop().partitions(b.data(), b.cat) if covers}


def _derive(b):
    a = b.args
    glossary = None
    if a.glossary:
        glossary = names_mod.read_glossary(a.glossary)
    elif a.expand_names:
        glossary = {}
    b.model, b.report = derive_mod.derive(b.cat, infer_undeclared_fks=a.infer_fks,
                                          json_shapes=b.json_shapes, dialect=a.dialect,
                                          absorb=b.absorb, merge_domains=a.merge_domains,
                                          glossary=glossary)
    report, pop = b.report, _pop()
    for said in b.cat.repairs:
        report.refine("rule 0", "catalogue", said.split(":", 1)[0], said.split(": ", 1)[1] +
                      ". The catalogue listed every pairing of the columns as its own "
                      "reference, which taken as written makes each column reference "
                      "something it does not.",
                      "Confirm the pairing; declare the key as one composite reference.")
    for table, cols, parent, verdict, matched, total in b.verified:
        what = ("declared, and none of its %d values is in %s's key: dropped from the draft"
                % (total, parent) if verdict == "dropped" else
                "rebuilt from a cross-product declaration and %s, the order %d of %d rows "
                "match" % (verdict, matched, total))
        report.refine("rule 0", "population", "%s.%s -> %s" % (table, ", ".join(cols), parent),
                      "The reference %s is %s." % (", ".join(cols), what),
                      "Check the declaration against the data it describes.")
    for child, ccols, parent, pcols, matched, total in b.shared:
        report.refine("rule 9d", "population", "%s (%s) -> %s" % (child, ", ".join(ccols), parent),
                      "Both carry the pair (%s), it is unique in both, and all %d of %s's "
                      "pairs are %s's: one %s per %s row, a link nothing declares. Added, "
                      "with the pair as a unique key of %s."
                      % (", ".join(ccols), total, child, parent, parent, child, parent),
                      "Confirm it. Two tables can share a pair of references by design "
                      "without one belonging to the other.")
    for table, cols, target, score, signals in b.refs:
        report.refine("rule 9c", "population", "%s.%s -> %s" % (table, ", ".join(cols), target),
                      "No foreign key is declared, but every value is present in %s's key "
                      "and the shape of the match says reference rather than coincidence: %s. "
                      "Applied because --infer-keys asked for it. Rule 9 reads a column's "
                      "*name*; this reads its values, which is the half Rostin et al. (2009) "
                      "and Zhang et al. (VLDB 2010) showed carries most of the signal."
                      % (target, ", ".join(pop.SIGNAL_PROSE.get(x, x) for x in signals)),
                      "Confirm it. Containment is not reference, and a wrong join answers a "
                      "different question without saying so.")
    for table, col, evidence in b.mandatory:
        report.refine("rule 9a", "population", "%s.%s" % (table, col),
                      "Declared nullable and never null in %s, so the role is mandatory in "
                      "this draft. Applied because --infer-mandatory asked for it; Bird's "
                      "Step 9 (3.9-a) mines it and nothing used to apply it." % evidence,
                      "Confirm it. A single later insert with this column empty refutes it, "
                      "and a mandatory role that is wrong rejects data the business accepts.")
    for table, key, col, referrers, evidence in b.referenced:
        report.refine("rule 1d", "population", "%s (%s, not %s)" % (table, col, key),
                      "The declared key %s is referenced by nothing, and %s -- %s -- is what "
                      "every foreign key into this table names (%s). The rest of the schema "
                      "knows an instance by %s, so this draft identifies it that way and "
                      "keeps %s as a second identifier. Applied because "
                      "--prefer-referenced-keys asked for it."
                      % (key, col, evidence, ", ".join(referrers), col, key),
                      "Confirm which one the business means by the thing's id. A surrogate "
                      "beside a business key looks exactly like this -- and so does a "
                      "business key beside a synchronisation id, where the declared key was "
                      "right all along.")
    for table, cols, evidence in b.keys:
        report.refine("rule 9b", "population", "%s (%s)" % (table, ", ".join(cols)),
                      "No primary key is declared, and %s has no duplicate values (%s) and "
                      "is named like an identifier, so it is the one this draft uses. "
                      "Applied because --infer-keys asked for it: without a key rule 1 reads "
                      "no shape at all and the table derives to nothing."
                      % (", ".join(cols), evidence),
                      "Confirm and declare the key. Uniqueness in the current population is "
                      "not uniqueness, and a wrong identifier is a wrong identity in every "
                      "query that walks this table.")


def _domains(b):
    # types first: a domain mined from an integer column has integer values, and applying
    # it as text is what made `DriveId: '1'` match nothing
    _pop().apply_column_types(b.analysis, b.model, b.report)
    _pop().apply_domains(b.analysis, b.model, b.report)


def _document_domains(b):
    # ...and the paths rule 12 opened, which no column-wise miner sees
    _pop().apply_document_domains(b.data(), b.model, b.report)


def _constraints(b):
    _pop().apply_constraints(b.analysis, b.model, b.report)


def _enforced(b):
    _pop().apply_enforced(b.analysis, b.model, b.report)


def _identifiers(b):
    _pop().apply_alternate_keys(b.analysis, b.model, b.report)


def _profile(b):
    _pop().report_quality(b.analysis, b.report)
    _pop().apply_quality(b.analysis, b.model, b.report)
    # the same cautions for the values inside documents, and where two things are linked
    # several ways, whether the ways agree (finding 166)
    _pop().apply_document_quality(b.data(), b.model, b.report)
    _pop().apply_routes(b.data(), b.cat.tables, b.model, b.report)
    _pop().apply_structure(b.data(), b.cat.tables, b.model, b.report)


def _report_analysis(b):
    _pop().report_into(b.analysis, b.report)


# (name, the flag(s) that select it -- None for always, a tuple for all-of --, what must
#  have run before it, whether it reads the data, the pass)
PASSES = [
    ("verify-keys", "profile", (), True, _verify_keys),
    ("referenced-keys", "prefer_referenced_keys", (), True, _referenced_keys),
    ("analyse", "*", ("referenced-keys",), True, _analyse),
    ("mandatory", "infer_mandatory", ("analyse",), False, _mandatory),
    ("json", "infer_json", ("referenced-keys",), True, _json),
    ("partitions", "infer_partitions", ("referenced-keys",), True, _partitions),
    ("derive", None, ("analyse", "mandatory", "json", "partitions"), False, _derive),
    ("domains", "infer_domains", ("derive", "analyse"), False, _domains),
    ("document-domains", ("infer_domains", "infer_json"), ("domains", "json"), True,
     _document_domains),
    ("constraints", "infer_constraints", ("derive", "analyse"), False, _constraints),
    ("enforced", "infer_enforced", ("derive", "analyse"), False, _enforced),
    ("identifiers", ("infer_keys", "|", "infer_identifiers"), ("derive", "analyse"), False,
     _identifiers),
    ("profile", "profile", ("derive", "analyse"), False, _profile),
    ("report", "analyse_data", ("derive", "analyse"), False, _report_analysis),
]

# The wording each data flag refuses a catalogue fixture with. Four of the data passes had
# no check at all and reached sqlite3.connect(None) -- a TypeError, with --json.
NEEDS_DATA = {
    "prefer_referenced_keys": "a referenced column is only a key if the rows say so",
    "infer_keys": "it reads the data, not just the catalog",
    "infer_domains": "it reads the data, not just the catalog",
    "analyse_data": "it reads the data, not just the catalog",
}


def selected(args, flag) -> bool:
    if flag is None:
        return True
    if isinstance(flag, tuple):
        if "|" in flag:
            return any(getattr(args, f) for f in flag if f != "|")
        return all(getattr(args, f) for f in flag)
    if flag == "*":
        # The analysis runs for whoever needs it: a pass that reads the data, or one that
        # reads the analysis and says so with an `after` edge.
        return any(selected(args, f) for n, f, after, reads, _ in PASSES
                   if f not in (None, "*") and (reads or "analyse" in after))
    return bool(getattr(args, flag))


def _flags_of(flag):
    return [f for f in (flag if isinstance(flag, tuple) else (flag,)) if f not in (None, "*", "|")]


def run_passes(b, parser):
    """Run the selected passes in list order, checking each one's `after` edges."""
    a = b.args
    if not a.sqlite:
        for n, flag, after, reads, _ in PASSES:
            if not (reads or "analyse" in after):
                continue
            for f in _flags_of(flag):
                if getattr(a, f):
                    why = NEEDS_DATA.get(f, "it reads the data")
                    parser.error("--%s needs a SQLite file; %s" % (f.replace("_", "-"), why))
    for name, flag, after, _, run in PASSES:
        if not selected(a, flag):
            continue
        for dep in after:
            dep_flag = next(f for n, f, _, _, _ in PASSES if n == dep)
            if selected(a, dep_flag) and dep not in b.ran:
                raise RuntimeError("pass %r needs %r to have run first" % (name, dep))
        run(b)
        b.ran.add(name)
    if b.conn is not None:
        b.conn.commit()
    b.model["_comment"].append("Built by reverse/reverse.py with: " + build_flags(a))


def build_flags(args) -> str:
    """The command line that reproduces this model, minus where it came from and went to."""
    out = ["--dialect " + args.dialect]
    for key, value in sorted(vars(args).items()):
        if key in ("sqlite", "json", "dsn", "out", "name", "dialect", "schema") or not value:
            continue
        out.append("--%s" % key.replace("_", "-") + ("" if value is True else " " + str(value)))
    return " ".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("sqlite", nargs="?", help="path to a SQLite database file")
    src.add_argument("--json", help="a catalog fixture in JSON")
    src.add_argument("--dsn", help="a database URL for a live server")
    p.add_argument("--schema", default="public", help="server schema for --dsn")
    p.add_argument("-o", "--out", default=".", help="output directory")
    p.add_argument("-n", "--name", help="base name for the output files")
    p.add_argument("--dialect", default="sqlite",
                   choices=sorted(derive_mod.DIALECTS),
                   help="which SQL the model's functions should spell (model/model.md "
                        "section 3). The emitted statement shape is SQL-92 either way; this "
                        "is the function library, where the differences actually live.")
    p.add_argument("--infer-json", action="store_true",
                   help="read the data and recover the schema inside JSON columns (rule 12): "
                        "a document whose keys are stable becomes one fact type per value, "
                        "mapped to a path into the column, so a query never mentions JSON. "
                        "Documents whose keys are data (a map) or unconstrained (a bag) are "
                        "reported and left opaque. SQLite only.")
    p.add_argument("--infer-fks", action="store_true",
                   help="apply undeclared foreign keys guessed from column names (rule 9): a "
                        "column named exactly like one other table's single primary key, of "
                        "the same type. Each one is reported as the guess it is")
    p.add_argument("--infer-keys", action="store_true",
                   help="read the data and recover the schema the catalogue does not "
                        "declare: the identifier a keyless table's population supports (rule "
                        "9b) and then the references that point at it (rule 9c), scored on "
                        "containment, coverage and value distribution rather than on names. "
                        "Rule 1 can read no shape at all without a key and half the tables "
                        "in some schemas declare none. Measured by stripping schemas that do "
                        "declare: over BIRD mini-dev's 11 databases, 94%% recall / 97%% "
                        "precision for keys and 81%% / 100%% for references "
                        "(reverse/tests/test_inference.py, which names its corpus because the "
                        "rates move with naming convention); each one is reported as the "
                        "guess it is. SQLite only.")
    p.add_argument("--infer-mandatory", action="store_true",
                   help="read the data and make a role mandatory where its column is declared "
                        "nullable and is never null (rule 9a, Bird's 3.9-a). Mined since the "
                        "beginning and never applied: the report said the role *may* be "
                        "mandatory and stopped there. Only where the population is "
                        "significant; each one is reported. SQLite only")
    p.add_argument("--infer-constraints", action="store_true",
                   help="state the exclusion, equality, value-comparison and ring "
                        "constraints the data supports, as deontic constraints. The CCM has "
                        "admitted these since it was written and nothing has ever produced "
                        "one; the miners have been finding them and printing prose "
                        "(finding 119). Deontic because a population says what today's rows "
                        "do, not what the schema forbids.")
    p.add_argument("--infer-partitions", action="store_true",
                   help="read the data and absorb rule 7's subtype candidates that turn out "
                        "to be vertical partitioning. A table whose whole primary key is a "
                        "foreign key to another's is a subtype or a second table of columns "
                        "about the same instance, and the catalogue cannot tell which; the "
                        "population can, because a subtype holds a *proper* subset and a "
                        "partition holds every instance. Absorbed, the partition's columns "
                        "become fact types on the parent entity type and the compiler still "
                        "emits the join. Changes the model rather than adding to it, like "
                        "rule 9c, so it is opt-in: queries naming the separate type break.")
    p.add_argument("--infer-identifiers", action="store_true",
                   help="read the data and state the second identifiers it supports: a "
                        "column beside the key that is never null, never repeats and reads "
                        "as a code (`CU338528`) gets a uniqueness constraint on its value "
                        "role, which is how ORM says a value identifies. Without it the "
                        "model says the same about `clientref` as about a column that "
                        "merely happens to be single-valued, and the schema listing cannot "
                        "tell an author there are two ids to choose between. Adds to the "
                        "model and changes nothing in it; deontic, because it is a claim "
                        "about today's rows. Also applied by --infer-keys. SQLite only.")
    p.add_argument("--prefer-referenced-keys", action="store_true",
                   help="read the data and, where a table's primary key is referenced by "
                        "nothing while every foreign key into the table names one other "
                        "column, identify the entity type by that column: it is what the "
                        "rest of the schema calls an instance, and the declared key is a "
                        "row number. Verified against the rows before it is believed. "
                        "Changes the model rather than adding to it, like rules 7b and 9c, "
                        "so it is opt-in -- a bare entity lists the other column -- and it "
                        "is not always what an author means: BIRD's `cards` is keyed by "
                        "`id`, referenced by `uuid`, and asked about by `id`. SQLite only.")
    p.add_argument("--expand-names", action="store_true",
                   help="write out the abbreviations in column names before they become "
                        "concept names. `observstation` is an observation station, which is "
                        "what an observatory is -- unexpanded it produces the value type "
                        "ObservatoryObservstation and the reading 'Observatory has "
                        "Observstation', which tells a reader an observatory is identified by "
                        "an observation. Conservative by construction: a squashed token is "
                        "cut only if it decomposes *completely* into known pieces, so "
                        "`category` is never read as `cat` plus a remainder.")
    p.add_argument("--glossary", metavar="FILE",
                   help="your own abbreviations, one `short = long` per line, `#` for a "
                        "comment. Domain words belong here rather than in the built-in "
                        "table: `sig` is a signal in one schema and a signature in the next. "
                        "Implies --expand-names.")
    p.add_argument("--merge-domains", action="store_true",
                   help="fold value types measured in the same unit into one domain. Reverse "
                        "engineering mints one value type per column, so a 136-column schema "
                        "gets 126 value types each played by a single role -- which is not a "
                        "model of anything: `sourceradeg` and `polarangledeg` are both an "
                        "angle in degrees and nothing can say so. The unit is what makes the "
                        "merge safe; merging on data type alone would put every real column "
                        "in one domain, and Celsius and kelvin stay apart because they are "
                        "the same quantity and not the same domain.")
    p.add_argument("--profile", action="store_true",
                   help="read the data and report what the values say about themselves: "
                        "enumerations wearing scrambled case, quantities stored with their "
                        "unit, values padded with space, and stand-ins for NULL. Reported "
                        "on the worklist, never applied -- but one of them silently "
                        "disables another pass, because a case-scrambled enumeration blows "
                        "past the value-domain ceiling and is recorded as no domain at all. "
                        "SQLite only.")
    p.add_argument("--infer-enforced", action="store_true",
                   help="read the data and mark, on each role that carries a declared "
                        "foreign key, whether the data upholds it -- no row points at a "
                        "row that is not there. Where it does, the compiler may read a "
                        "referenced value from the column in hand and drop the join that "
                        "would fetch it back, and drop the join that checks the referent "
                        "exists. A quarter of the joins in the recorded query corpus are "
                        "one of those two. A claim about today's rows, so it is asked for "
                        "and reported, never assumed. SQLite only.")
    p.add_argument("--infer-domains", action="store_true",
                   help="read the data and put the value domains it supports on the value "
                        "types: a column holding a handful of distinct values over a large "
                        "population becomes an ORM value constraint, which is what tells a "
                        "query author how a code is spelled. Seen, not permitted, and "
                        "reported as such. SQLite only.")
    p.add_argument("--analyse-data", "--analyze-data", action="store_true", dest="analyse_data",
                   help="read the data as well as the catalogue and report the constraints it "
                        "supports -- Bird (1997) Step 9. Candidate foreign keys, identifiers "
                        "and mandatory roles, each with the population behind it. Reported at "
                        "confidence `population`, never applied. SQLite only.")
    p.add_argument("--ignore-names", action="store_true",
                   help="with --analyse-data, score candidate references on the shape of the "
                        "data alone. For schemas that name references for the concept and "
                        "keys for the identifier, where string comparison is no evidence.")
    args = p.parse_args(argv)

    if args.sqlite:
        # sqlite3 creates a database for a path that does not exist, so a typo used to
        # produce an empty file, a model of nothing, and no complaint at all.
        if not os.path.exists(args.sqlite):
            raise SystemExit("no such database: %s" % args.sqlite)
        cat, source = catalog_mod.from_sqlite(args.sqlite), args.sqlite
        default_name = os.path.splitext(os.path.basename(args.sqlite))[0]
    elif args.json:
        cat, source = catalog_mod.from_json(args.json), args.json
        default_name = os.path.splitext(os.path.basename(args.json))[0]
    else:
        try:
            import sqlalchemy
            conn = sqlalchemy.create_engine(args.dsn).raw_connection()
        except ImportError:
            p.error("--dsn needs SQLAlchemy, or open the connection yourself and call "
                    "catalog.from_dbapi()")
        cat, source = catalog_mod.from_dbapi(conn, args.schema), args.dsn
        default_name = args.schema

    name = args.name or default_name
    ctx = Build(args, cat, source)
    run_passes(ctx, p)
    model, report = ctx.model, ctx.report
    model["id"] = name
    model["name"] = "%s (draft, reverse engineered)" % name

    os.makedirs(args.out, exist_ok=True)
    ccm_path = os.path.join(args.out, name + ".ccm.json")
    orm_path = os.path.join(args.out, name + ".orm")
    rep_path = os.path.join(args.out, name + ".report.md")

    with open(ccm_path, "w") as fh:
        json.dump(model, fh, indent=2)
        fh.write("\n")
    with open(orm_path, "wb") as fh:
        fh.write(ormxml.export(model))
    with open(rep_path, "w") as fh:
        fh.write(render_report(report, source, model))

    s = report.summary
    print("%s: %d tables -> %d entity types, %d value types, %d fact types, %d constraints"
          % (name, s["tables"], s["entityTypes"], s["valueTypes"], s["factTypes"],
             s["constraints"]))
    print("  %s" % ccm_path)
    print("  %s" % orm_path)
    print("  %s   (%d blockers, %d refinements)"
          % (rep_path, s["blockers"], s["refinements"]))
    return 1 if report.blockers else 0


if __name__ == "__main__":
    sys.exit(main())
