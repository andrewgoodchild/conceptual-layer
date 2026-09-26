#!/usr/bin/env python3
"""Validate a Common Core Model file.

Two passes, matching model.md section 7.2:

  1. JSON Schema (ccm.schema.json) -- shape.
  2. Semantic checks -- reference resolution, step typing, unification compatibility,
     rootedness, and the rest of the taxonomy the CCM adopts from ORMCore's path errors.

    usage: validate.py [FILE ...]        (default: examples/*.ccm.json)
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.ccm import Index                                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class Findings:
    """Errors fail the file; warnings are reported but do not."""

    def __init__(self):
        self.items = []

    def add(self, check, where, message, severity="error"):
        self.items.append((severity, check, where, message))

    def warn(self, check, where, message):
        self.add(check, where, message, "warning")

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "error"]

    def __bool__(self):
        return bool(self.errors)


# --------------------------------------------------------------------------- indexing

def index_model(m):
    """The shared model index plus the two id maps only the validator needs."""
    ix = Index(m)
    return {
        "concepts": ix.concepts,
        "roles": ix.roles,
        "role_owner": ix.role_owner,         # role id -> owning fact type id == ConQuer Rel(r)
        "queries": {q["id"]: q for q in m.get("queries", [])},
        "functions": {f["id"]: f for f in m.get("functions", [])},
        "index": ix,
    }


def nested_blocks(cond):
    """The blocks a condition nests. The one place that knows which kinds nest anything."""
    kind = cond.get("kind")
    if kind == "exists":
        yield cond["block"]
    elif kind == "setCompare":
        yield cond["left"]["block"]
        yield cond["right"]["block"]
    elif kind == "not":
        yield from nested_blocks(cond["operand"])
    elif kind == "logical":
        for operand in cond.get("operands", []):
            yield from nested_blocks(operand)


def walk_blocks(expr, ancestry=()):
    """Yield (block, enclosing blocks outermost-first) over a QueryExpr, depth first."""
    if expr is None:
        return
    if expr.get("nodeType") == "setExpr":
        for operand in expr.get("operands", []):
            yield from walk_blocks(operand, ancestry)
        return
    yield expr, list(ancestry)
    inner = tuple(ancestry) + (expr,)
    for sub in expr.get("subBlocks", []):
        yield from walk_blocks(sub, inner)
    for cond in expr.get("conditions", []):
        for sub in nested_blocks(cond):
            yield from walk_blocks(sub, inner)


def visible_nodes(block, ancestry):
    """Nodes addressable from `block`: its own plus every enclosing block's."""
    out = {}
    for b in ancestry + [block]:
        for n in b.get("nodes", []):
            out[n["id"]] = n
    return out


# --------------------------------------------------------------------------- checks

def check_ids_unique(m, f):
    seen = set()
    path = []

    def visit(o):
        if isinstance(o, dict):
            if "id" in o and isinstance(o["id"], str):
                if o["id"] in seen:
                    f.add("id-unique", "$" + "".join(path), "duplicate id %r" % o["id"])
                seen.add(o["id"])
            for k, v in o.items():
                path.append("." + k)
                visit(v)
                path.pop()
        elif isinstance(o, list):
            for i, v in enumerate(o):
                path.append("[%d]" % i)
                visit(v)
                path.pop()

    visit(m)


def check_schema_refs(m, ix, f):
    for c in m.get("concepts", []):
        for sup in c.get("supertypes", []):
            if sup not in ix["concepts"]:
                f.add("ref", c["id"], "supertype %r does not exist" % sup)
        for rid in c.get("identifier", []):
            if rid not in ix["roles"]:
                f.add("ref", c["id"], "identifier role %r does not exist" % rid)
        for r in c.get("roles", []):
            player = ix["concepts"].get(r["player"])
            if player is None:
                f.add("ref", r["id"], "player %r does not exist" % r["player"])
            elif player["kind"] == "fact" and not player.get("isObjectified"):
                f.add("player-objectified", r["id"],
                      "player %r is an un-objectified fact type (model.md 2.1)" % r["player"])
        for rd in c.get("readings", []):
            for rid in rd["roleSequence"]:
                if rid not in ix["roles"]:
                    f.add("ref", rd["id"], "reading role %r does not exist" % rid)


def check_block(block, ancestry, ix, f):
    where = block["id"]
    concepts, roles, owner = ix["concepts"], ix["roles"], ix["role_owner"]
    related = ix["index"].compatible
    nodes = visible_nodes(block, ancestry)
    own = {n["id"] for n in block.get("nodes", [])}

    for n in block.get("nodes", []):
        if n["concept"] not in concepts:
            f.add("ref", n["id"], "concept %r does not exist" % n["concept"])

    entered_facts = {}                       # fact node id -> the role it was entered by
    reached = set()

    for s in block.get("steps", []):
        rid = s["role"]
        if rid not in roles:
            f.add("ref", s["id"], "role %r does not exist" % rid)
            continue
        player, rel = roles[rid]["player"], owner[rid]
        src, dst = nodes.get(s["from"]), nodes.get(s["to"])
        if src is None or dst is None:
            f.add("ref", s["id"], "step endpoint not visible from this block")
            continue

        if s["kind"] == "enter":
            # from must play the role; to must be the fact instance
            if not ix["index"].compatible(src["concept"], player):
                f.add("step-player", s["id"],
                      "enter %r: from is %r, not related to Player = %r"
                      % (rid, src["concept"], player))
            if dst["concept"] != rel:
                f.add("step-player", s["id"],
                      "enter %r: to is %r, expected Rel = %r" % (rid, dst["concept"], rel))
            if s.get("join") == "outer" and roles[rid].get("isMandatory"):
                f.add("outer-join-mandatory", s["id"],
                      "outer join onto mandatory role %r can never be null" % rid)
            entered_facts.setdefault(s["to"], set()).add(rid)
        else:                                 # exit
            if src["concept"] != rel:
                f.add("step-player", s["id"],
                      "exit %r: from is %r, expected Rel = %r" % (rid, src["concept"], rel))
            if not ix["index"].compatible(dst["concept"], player):
                f.add("step-player", s["id"],
                      "exit %r: to is %r, not related to Player = %r"
                      % (rid, dst["concept"], player))
            if s["from"] not in entered_facts:
                f.add("exit-follows-enter", s["id"],
                      "exit %r leaves node %r, which no enter in this block reached" % (rid, s["from"]))
            elif rid in entered_facts[s["from"]]:
                f.add("role-reuse", s["id"],
                      "role %r is both entered and exited on fact node %r without a rejoin"
                      % (rid, s["from"]))
        reached.update((s["from"], s["to"]))

    unified = set()
    for u in block.get("unifications", []):
        kinds = []
        for nid in u["nodes"]:
            n = nodes.get(nid)
            if n is None:
                f.add("ref", u["id"], "unified node %r is not visible from this block" % nid)
            else:
                kinds.append((nid, n["concept"]))
        unified.update(u["nodes"])
        for i in range(len(kinds)):
            for j in range(i + 1, len(kinds)):
                if not ix["index"].compatible(kinds[i][1], kinds[j][1]):
                    f.add("unification-compatible", u["id"],
                          "%s (%s) and %s (%s) are not type-related -- ConQuer x ~ y"
                          % (kinds[i][0], kinds[i][1], kinds[j][0], kinds[j][1]))

    bound = reached | unified
    for inv in block.get("invocations", []):
        if inv["query"] not in ix["queries"]:
            f.add("ref", inv["id"], "query %r does not exist" % inv["query"])
        else:
            declared = {p["id"] for p in ix["queries"][inv["query"]].get("parameters", [])}
            supplied = {a["parameter"] for a in inv.get("arguments", [])}
            if declared - supplied:
                f.add("parameter-binding", inv["id"],
                      "unbound parameters: %s" % ", ".join(sorted(declared - supplied)))
        bound.update(r["node"] for r in inv.get("results", []))

    for nid in own - bound:
        f.add("rooted", where, "node %r is not reached by any step, unification or invocation" % nid)

    consumed = set()

    def note(value):
        if not isinstance(value, dict):
            return
        if value.get("kind") == "calculation":
            consumed.add(value["calculation"])
        elif value.get("kind") == "conditional":
            scan_condition(value["condition"])
            note(value["then"])
            note(value["else"])

    for calc in block.get("calculations", []):
        if calc["function"] not in ix["functions"]:
            f.add("ref", calc["id"], "function %r does not exist" % calc["function"])
        else:
            fn = ix["functions"][calc["function"]]
            if fn.get("isAggregate") and "aggregation" not in calc:
                f.add("aggregation-context", calc["id"],
                      "aggregate function %r has no aggregation context" % fn["name"])
            params = fn.get("parameters", [])
            if params and len(calc.get("arguments", [])) != len(params):
                f.add("parameter-binding", calc["id"],
                      "expected %d arguments, got %d" % (params and len(params), len(calc.get("arguments", []))))
        for a in calc.get("arguments", []):
            note(a)

    def scan_condition(cond):
        if not isinstance(cond, dict):
            return
        for key in ("left", "right"):
            v = cond.get(key)
            if isinstance(v, dict) and "kind" in v:
                note(v)
        for a in cond.get("arguments", []):
            note(a)
        if cond.get("kind") == "not":
            scan_condition(cond["operand"])
        for operand in cond.get("operands", []):
            scan_condition(operand)

    for cond in block.get("conditions", []):
        scan_condition(cond)
    for v, _ in block.get("_ordering", []):
        note(v)                              # ordering by a computed value uses it
    for pj in block.get("projections", []):
        note(pj["source"])
        if "target" in pj and pj["target"] not in ix["roles"]:
            f.add("ref", pj["id"], "projection target role %r does not exist" % pj["target"])

    for calc in block.get("calculations", []):
        if calc["id"] not in consumed:
            f.add("calculation-consumed", calc["id"],
                  "calculated value is never used in a condition, calculation or projection")


def correlates(block, ancestry):
    """Does `block` (or anything nested in it) unify with a node from an enclosing block?"""
    outer = {n["id"] for b in ancestry for n in b.get("nodes", [])}
    if not outer:
        return True
    stack = [block]
    while stack:
        b = stack.pop()
        for u in b.get("unifications", []):
            if outer & set(u["nodes"]):
                return True
        stack.extend(b.get("subBlocks", []))
        for cond in b.get("conditions", []):
            stack.extend(nested_blocks(cond))
    return False


def check_correlation(expr, f):
    """A condition whose nested blocks never mention an enclosing node is constant.

    One side of a setCompare being constant is normal and often the point -- "all in the
    hobbies of president Clinton" is a fixed set. Both sides constant means the whole
    condition is a fixed truth value, which is a dropped correlation. Warn, do not fail.
    """
    for block, ancestry in walk_blocks(expr):
        for cond in block.get("conditions", []):
            group = list(nested_blocks(cond))
            if not group:
                continue
            inner = list(ancestry) + [block]
            if any(correlates(sub, inner) for sub in group):
                continue
            f.warn("uncorrelated", group[0]["id"],
                   "no %s block unifies with an enclosing node; the condition is constant "
                   "regardless of the enclosing block -- dropped correlation?"
                   % cond.get("kind"))


def check_query(q, ix, f):
    body = q["body"]
    tops = body["operands"] if body.get("nodeType") == "setExpr" else [body]
    arities = []
    for t in tops:
        for b, _ in walk_blocks(t):
            if b is t:
                pj = b.get("projections", [])
                if not pj:
                    f.add("projection-required", b["id"], "body block has no projections")
                arities.append(tuple(p["name"] for p in pj))
    if len(set(arities)) > 1:
        f.add("setexpr-arity", q["id"],
              "set operands disagree on projections: %s" % " vs ".join(map(str, sorted(set(arities)))))

    for b, ancestry in walk_blocks(body):
        check_block(b, ancestry, ix, f)
    check_correlation(body, f)

    known = {p["id"] for t in tops for b, _ in walk_blocks(t) for p in b.get("projections", [])}
    for o in q.get("ordering", []):
        if o["projection"] not in known:
            f.add("ref", q["id"], "ordering references unknown projection %r" % o["projection"])


# --------------------------------------------------------------------------- driver

def public(obj):
    """The model without its internal keys. Keys beginning with `_` (`_ordering`, `_limit`,
    `_frOp`, `_block`) are the compiler's own, documented as such in model.md, and a lowered
    derivation-rule body carries them; the schema describes the public shape."""
    if isinstance(obj, dict):
        return {k: public(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [public(v) for v in obj]
    return obj


def validate(path, schema):
    findings = Findings()
    with open(path) as fh:
        m = public(json.load(fh))

    try:
        from jsonschema import Draft202012Validator
    except ImportError:                       # optional: without it, the semantic checks only
        schema = None
    if schema is not None:
        for e in sorted(Draft202012Validator(schema).iter_errors(m), key=str):
            findings.add("schema", "$." + ".".join(str(p) for p in e.absolute_path), e.message)
        if findings:
            return findings                   # shape first; semantics need a well-formed model

    ix = index_model(m)
    check_ids_unique(m, findings)
    check_schema_refs(m, ix, findings)
    for q in m.get("queries", []):
        check_query(q, ix, findings)
    rules = {r["id"]: r for r in m.get("derivationRules", [])}
    for c in m.get("concepts", []):
        d = c.get("derivation")
        if d is None:
            continue
        rule = rules.get(d)
        if rule is None:
            findings.add("ref", c["id"], "derivation %r is not a rule in derivationRules" % d)
        elif rule["target"]["ref"] != c["id"]:
            findings.add("derivation-target", c["id"],
                         "derivation %r targets %r, not this concept" % (d, rule["target"]["ref"]))
        elif (c["kind"] == "fact") != (rule["target"]["kind"] == "factType"):
            findings.add("derivation-target", c["id"],
                         "a %s cannot be the target of a %r rule" % (c["kind"], rule["target"]["kind"]))
    for rule in m.get("derivationRules", []):
        target = rule["target"]
        if target["ref"] not in ix["concepts"]:
            findings.add("ref", rule["id"], "target %r does not exist" % target["ref"])
        if rule.get("body") is None:
            if not rule.get("source"):
                findings.add("derivation-empty", rule["id"], "neither a source nor a body")
            continue                          # a source is lowered by the compiler, not here
        check_query({"id": rule["id"], "body": rule["body"]}, ix, findings)
        if target["kind"] == "factType" and target["ref"] in ix["concepts"]:
            need = {r["id"] for r in ix["concepts"][target["ref"]].get("roles", [])}
            body = rule["body"]
            tops = body["operands"] if body.get("nodeType") == "setExpr" else [body]
            for t in tops:
                got = {p.get("target") for p in t.get("projections", [])}
                if need - got:
                    findings.add("derivation-projection", rule["id"],
                                 "unprojected target roles: %s" % ", ".join(sorted(need - got)))
    return findings


def main(argv):
    paths = argv[1:] or sorted(glob.glob(os.path.join(HERE, "examples", "*.ccm.json")))
    if not paths:
        print("no CCM files given or found"); return 2
    try:
        schema = json.load(open(os.path.join(HERE, "ccm.schema.json")))
        import jsonschema                      # noqa: F401
    except ImportError:
        print("note: jsonschema not installed -- running semantic checks only\n")
        schema = None

    failed = 0
    for path in paths:
        findings = validate(path, schema)
        name = os.path.relpath(path, HERE)
        if findings:
            failed += 1
            print("FAIL %s" % name)
        elif findings.items:
            print("ok   %s (with warnings)" % name)
        else:
            print("ok   %s" % name)
        for severity, check, where, message in findings.items:
            print("  %-7s [%s] %s: %s" % (severity, check, where, message))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
