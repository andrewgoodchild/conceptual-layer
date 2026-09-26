#!/usr/bin/env python3
"""One deliberately broken model per check in model/validate.py.

`conquer/tests/test_lowered_valid.py` asserts that good blocks pass the validator. That is
only half a test: a check that silently stopped firing -- an `if` inverted, an id renamed out
from under it -- would keep every one of those cases green. These cases assert the other
half, that each check actually rejects what it is there to reject.

Each case starts from `model/examples/presidents.ccm.json`, breaks exactly one thing, and
names the check code that must appear. The control case asserts the unbroken model is clean,
so a mutation that fails for an unrelated reason cannot pass by accident.

    test_validate.py [-v] [--only SUBSTRING]
"""

import argparse
import copy
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from model import validate as validate_mod          # noqa: E402

BASE = os.path.join(HERE, "..", "examples", "presidents.ccm.json")


def concept(m, cid):
    return next(c for c in m["concepts"] if c["id"] == cid)


def body(m):
    return m["queries"][0]["body"]


def step(m, sid):
    return next(s for s in body(m)["steps"] if s["id"] == sid)


def node(m, nid):
    return next(n for n in body(m)["nodes"] if n["id"] == nid)


# -- the mutations ----------------------------------------------------------------------
# Each takes the parsed model and breaks one thing in place.

def dup_id(m):
    m["concepts"].append(copy.deepcopy(concept(m, "et.Hobby")))


def bad_supertype(m):
    concept(m, "et.Hobby")["supertypes"] = ["et.NoSuchType"]


def bad_identifier_role(m):
    concept(m, "et.President")["identifier"] = ["r.nope.role"]


def bad_role_player(m):
    concept(m, "ft.PresidentHasHobby")["roles"][0]["player"] = "et.Ghost"


def player_is_objectified(m):
    # A role's player must be an entity or value type, never the fact type it belongs to.
    concept(m, "ft.PresidentHasHobby")["roles"][0]["player"] = "ft.PresidentHasName"


def bad_reading_role(m):
    ft = concept(m, "ft.PresidentHasHobby")
    ft["readings"][0]["roleSequence"] = ["r.ph.president", "r.nope"]


def bad_node_concept(m):
    node(m, "n.h")["concept"] = "et.Imaginary"


def bad_step_role(m):
    step(m, "s.1")["role"] = "r.does.not.exist"


def step_endpoint_invisible(m):
    step(m, "s.1")["from"] = "n.elsewhere"


def enter_from_wrong_player(m):
    # n.h is a Hobby; r.ph.president is played by President, and the two are not type-related.
    step(m, "s.1")["from"] = "n.h"


def exit_to_wrong_player(m):
    step(m, "s.2")["role"] = "r.ph.president"


def outer_join_onto_mandatory(m):
    role = concept(m, "ft.PresidentHasHobby")["roles"][0]
    role["isMandatory"] = True
    step(m, "s.1")["join"] = "outer"


def exit_without_enter(m):
    body(m)["steps"] = [s for s in body(m)["steps"] if s["id"] != "s.1"]
    body(m)["unifications"] = [{"id": "u.keep", "nodes": ["n.p", "n.f"]}]


def role_entered_and_exited(m):
    step(m, "s.2")["role"] = "r.ph.president"
    step(m, "s.2")["to"] = "n.p"


def unify_unrelated_types(m):
    body(m)["unifications"] = [{"id": "u.bad", "nodes": ["n.p", "n.h"]}]


def unify_invisible_node(m):
    body(m)["unifications"] = [{"id": "u.bad", "nodes": ["n.p", "n.nowhere"]}]


def unrooted_node(m):
    body(m)["nodes"].append({"id": "n.orphan", "concept": "et.Hobby"})


def unknown_function(m):
    body(m)["calculations"] = [{"id": "calc.x", "function": "fn.nope",
                                "arguments": [{"kind": "node", "node": "n.p"}]}]
    body(m)["projections"].append({"id": "pj.x", "name": "x",
                                   "source": {"kind": "calculation", "calculation": "calc.x"}})


def aggregate_without_context(m):
    m["functions"] = [{"id": "fn.count", "name": "count", "isAggregate": True,
                       "parameters": [{"name": "over"}]}]
    body(m)["calculations"] = [{"id": "calc.c", "function": "fn.count",
                                "arguments": [{"kind": "node", "node": "n.h"}]}]
    body(m)["projections"].append({"id": "pj.c", "name": "c",
                                   "source": {"kind": "calculation", "calculation": "calc.c"}})


def wrong_argument_count(m):
    m["functions"] = [{"id": "fn.plus", "name": "plus",
                       "parameters": [{"name": "a"}, {"name": "b"}]}]
    body(m)["calculations"] = [{"id": "calc.p", "function": "fn.plus",
                                "arguments": [{"kind": "node", "node": "n.h"}]}]
    body(m)["projections"].append({"id": "pj.p", "name": "p",
                                   "source": {"kind": "calculation", "calculation": "calc.p"}})


def calculation_never_used(m):
    m["functions"] = [{"id": "fn.id", "name": "id", "parameters": [{"name": "a"}]}]
    body(m)["calculations"] = [{"id": "calc.dead", "function": "fn.id",
                                "arguments": [{"kind": "node", "node": "n.h"}]}]


def bad_projection_target(m):
    body(m)["projections"][0]["target"] = "r.not.a.role"


def no_projections(m):
    body(m)["projections"] = []


def setexpr_arity_mismatch(m):
    one = copy.deepcopy(body(m))
    two = copy.deepcopy(body(m))
    two["id"] = "b.other"
    two["projections"] = two["projections"][:1]
    for key, suffix in (("nodes", "b"), ("steps", "b")):
        for item in two[key]:
            item["id"] += ".b"
    m["queries"][0]["body"] = {"nodeType": "setExpr", "op": "union",
                               "operands": [one, two]}


def bad_ordering_projection(m):
    m["queries"][0]["ordering"] = [{"projection": "pj.nope", "direction": "asc"}]


def bad_invocation_query(m):
    body(m)["invocations"] = [{"id": "inv.1", "query": "q.missing", "arguments": [],
                               "results": []}]


def unbound_parameter(m):
    m["queries"].append({
        "id": "q.byName", "name": "ByName",
        "parameters": [{"id": "prm.n", "name": "n", "concept": "vt.PresidentName"}],
        "body": copy.deepcopy(body(m))})
    body(m)["invocations"] = [{"id": "inv.1", "query": "q.byName", "arguments": [],
                               "results": []}]


def schema_violation(m):
    m["concepts"][0]["kind"] = "notAKind"


def derivation_target_missing(m):
    m["derivationRules"] = [{"id": "dr.1", "target": {"kind": "factType", "ref": "ft.Nope"},
                             "body": copy.deepcopy(body(m)),
                             "completeness": "fullyDerived", "storage": "notStored"}]


def derivation_unprojected_role(m):
    rule_body = copy.deepcopy(body(m))
    rule_body["projections"][0]["target"] = "r.pn.president"   # only one of two roles
    rule_body["projections"] = rule_body["projections"][:1]
    m["derivationRules"] = [{"id": "dr.2",
                             "target": {"kind": "factType", "ref": "ft.PresidentHasName"},
                             "body": rule_body,
                             "completeness": "fullyDerived", "storage": "notStored"}]


CASES = [
 # (name, mutation, expected check code, expected severity)
 ("control: the example model is clean",          None,                     None,      None),
 ("id-unique  a duplicated concept id",           dup_id,                   "id-unique", "error"),
 ("ref  supertype that does not exist",           bad_supertype,            "ref",     "error"),
 ("ref  preferred identifier names no role",      bad_identifier_role,      "ref",     "error"),
 ("ref  a role played by nothing",                bad_role_player,          "ref",     "error"),
 ("player-objectified  role played by a fact type", player_is_objectified,  "player-objectified", "error"),
 ("ref  a reading naming a role that does not exist", bad_reading_role,     "ref",     "error"),
 ("ref  node typed by a missing concept",         bad_node_concept,         "ref",     "error"),
 ("ref  step over a role that does not exist",    bad_step_role,            "ref",     "error"),
 ("ref  step endpoint not visible here",          step_endpoint_invisible,  "ref",     "error"),
 ("step-player  enter from the wrong player",     enter_from_wrong_player,  "step-player", "error"),
 ("step-player  exit to the wrong player",        exit_to_wrong_player,     "step-player", "error"),
 ("outer-join-mandatory  outer join can never be null", outer_join_onto_mandatory,
                                                                            "outer-join-mandatory", "error"),
 ("exit-follows-enter  exit from an unentered fact node", exit_without_enter,
                                                                            "exit-follows-enter", "error"),
 ("role-reuse  one role both entered and exited", role_entered_and_exited,  "role-reuse", "error"),
 ("unification-compatible  unifying unrelated types", unify_unrelated_types,
                                                                            "unification-compatible", "error"),
 ("ref  unifying a node from nowhere",            unify_invisible_node,     "ref",     "error"),
 ("rooted  a node no step reaches",               unrooted_node,            "rooted",  "error"),
 ("ref  calculation over a function not in the model", unknown_function,    "ref",     "error"),
 ("aggregation-context  aggregate with no context", aggregate_without_context,
                                                                            "aggregation-context", "error"),
 ("parameter-binding  wrong number of arguments", wrong_argument_count,     "parameter-binding", "error"),
 ("calculation-consumed  a value nothing uses",   calculation_never_used,   "calculation-consumed", "error"),
 ("ref  projection onto a role that does not exist", bad_projection_target, "ref",     "error"),
 ("projection-required  a body block with no projections", no_projections,  "projection-required", "error"),
 ("setexpr-arity  union operands disagree",       setexpr_arity_mismatch,   "setexpr-arity", "error"),
 ("ref  ordering names an unknown projection",    bad_ordering_projection,  "ref",     "error"),
 ("ref  invoking a query that does not exist",    bad_invocation_query,     "ref",     "error"),
 ("parameter-binding  invocation leaves a parameter unbound", unbound_parameter,
                                                                            "parameter-binding", "error"),
 ("schema  a concept kind the schema does not allow", schema_violation,     "schema",  "error"),
 ("ref  derivation rule targeting a missing fact type", derivation_target_missing,
                                                                            "ref",     "error"),
 ("derivation-projection  a target role left unprojected", derivation_unprojected_role,
                                                                            "derivation-projection", "error"),
]


def load_schema():
    try:
        import jsonschema                              # noqa: F401
        return json.load(open(os.path.join(HERE, "..", "ccm.schema.json")))
    except ImportError:
        return None


def run(case, schema, base, tmpdir):
    name, mutate, want, severity = case
    m = copy.deepcopy(base)
    if mutate is not None:
        mutate(m)
    path = os.path.join(tmpdir, "case.ccm.json")
    with open(path, "w") as fh:
        json.dump(m, fh)
    findings = validate_mod.validate(path, schema)
    got = [(sev, check) for sev, check, _, _ in findings.items]

    if want is None:
        if not findings.errors:
            return True, "clean, as it must be"
        return False, "expected a clean model, got %s" % sorted({c for _, c in got})
    if (severity, want) in got:
        return True, "reported %s" % want
    return False, ("expected a %s %r; got %s"
                   % (severity, want, sorted(set(got)) or "nothing at all"))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    schema = load_schema()
    if schema is None:
        print("note: jsonschema not installed -- the schema case will be skipped\n")
    base = json.load(open(BASE))

    cases = [c for c in CASES if not args.only or args.only.lower() in c[0].lower()]
    passed = failed = skipped = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for case in cases:
            if case[2] == "schema" and schema is None:
                skipped += 1
                continue
            ok, note = run(case, schema, base, tmpdir)
            if ok:
                passed += 1
                if args.verbose:
                    print("ok    %-52s %s" % (case[0], note))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (case[0], note))

    tail = ", %d skipped (no jsonschema)" % skipped if skipped else ""
    print("\n%d passed, %d failed, %d total%s" % (passed, failed, len(cases) - skipped, tail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
