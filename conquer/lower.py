"""Lower a parsed ConQuer-92 path expression to a Common Core Model query block.

This is the pass model/model.md section 0 describes: the AST keeps ConQuer's algebra, where
the report's typing rules apply and where verbalisation would run; the CCM block is flat,
fully explicit, and one step from SQL.

What this pass does, in the language of that table:
  G2  flattens concatenation into nodes + steps + unifications
  A1  materialises HdCoerce/TlCoerce -- comparing an entity to a literal walks its
      reference scheme as real enter/exit steps
  A2  expands denotations Type: 'value' through Idf(x), including composite identifiers
  A3  drops hd/tl: they live here, as the (head, tail) pair each lowering returns, and
      become Projections
"""

from __future__ import annotations

import contextlib
from typing import Dict, List, Optional, Tuple

import parser as cq
from parser import Ambiguous, Judgement, ParseError


def named_vars(ast, out=None):
    """Variables an expression names explicitly, as in `Track t` or `Genre g`.

    Not `!x` denotations: those bind only when the name is free and otherwise refer to an
    enclosing binding, so hiding them would break correlation, which is the whole point of
    writing `!x`.
    """
    out = set() if out is None else out
    if isinstance(ast, cq.TypeSpec):
        if ast.var:
            out.add(ast.var)
        if ast.denotation is not None and not isinstance(ast.denotation, tuple):
            named_vars(ast.denotation, out)
    elif isinstance(ast, cq.Seq):
        for p in ast.parts:
            if isinstance(p, cq.Filter):
                named_vars(p.expr, out)
            elif isinstance(p, cq.Step):
                if p.target is not None:
                    named_vars(p.target, out)
            else:
                named_vars(p, out)
    elif isinstance(ast, cq.SubExpr):
        for p in ast.parts:
            named_vars(p, out)
    elif isinstance(ast, (cq.Binary, cq.Compare, cq.SetCompare)):
        named_vars(ast.left, out)
        named_vars(ast.right, out)
    elif isinstance(ast, cq.Where):
        named_vars(ast.path, out)
    elif isinstance(ast, cq.Named):
        out.add(ast.name)
        named_vars(ast.path, out)
    elif isinstance(ast, cq.SubQuery):
        named_vars(ast.query.body, out)
        for name, _ in ast.query.projections:
            out.add(name)
    elif isinstance(ast, (cq.Distinct, cq.Front, cq.Aggregate)):
        named_vars(ast.path, out)
    elif isinstance(ast, cq.Arith):
        named_vars(ast.left, out)
        named_vars(ast.right, out)
    elif isinstance(ast, cq.Call):
        for a in ast.args:
            named_vars(a, out)
    return out


def binds_nothing(ast) -> bool:
    """Does this operand name anything the rest of the query could refer to?

    A variable (`Genre g`), an abstract denotation (`Genre: !g`), or a nested aggregate all
    make an operand referable, so it has to share the block. An operand that names nothing
    can only filter, which is exactly Fr.
    """
    if isinstance(ast, cq.TypeSpec):
        if ast.var:
            return False
        d = ast.denotation
        if isinstance(d, tuple):          # a composite or !x denotation names something
            return False
        return d is None or binds_nothing(d)
    if isinstance(ast, cq.Seq):
        for p in ast.parts:
            if isinstance(p, cq.Filter):
                if not binds_nothing(p.expr):
                    return False
            elif isinstance(p, cq.Step):
                if p.target is not None and not binds_nothing(p.target):
                    return False
            elif not binds_nothing(p):
                return False
        return True
    if isinstance(ast, cq.SubExpr):
        return all(binds_nothing(p) for p in ast.parts)
    if isinstance(ast, (cq.Constant, cq.ImplicitHead, cq.VarRef, cq.RoleSpec)):
        return True
    if isinstance(ast, cq.Binary) and ast.op in ("and", "or", "butnot"):
        # An Fr chain names nothing when none of its operands does, and then the whole chain
        # is one filter. Falling through to False sent `[A OR OTHERWISE B]` down the branch
        # that lowers an operand into the *enclosing* block, where its alternatives became
        # siblings of whatever came before and the OR bound across it: `Employee [has
        # Department: 'ENG'] [has EmployeeGender: 'M' OR OTHERWISE has EmployeeGender: 'F']`
        # returned every employee who was either male and in ENG or female anywhere.
        return binds_nothing(ast.left) and binds_nothing(ast.right)
    return False                    # conditions, comparisons, aggregates: keep them in-block


def as_value(x) -> dict:
    """Node id or Value -> Value. model.md §4.6: a Value is a node, a constant, a calculation
    or a parameter. Only the first is a node, so the others must not be given fake ones."""
    return x if isinstance(x, dict) else {"kind": "node", "node": x}


def remap_nodes(thing, idmap):
    """Deep-copy `thing`, rewriting every node reference through `idmap`."""
    if isinstance(thing, dict):
        out = {}
        for k, v in thing.items():
            if k == "node" and isinstance(v, str):
                out[k] = idmap.get(v, v)
            elif k in ("from", "to") and isinstance(v, str):
                out[k] = idmap.get(v, v)
            elif k == "nodes" and isinstance(v, list) and all(isinstance(i, str) for i in v):
                out[k] = [idmap.get(i, i) for i in v]
            elif k == "context" and isinstance(v, list):
                out[k] = [idmap.get(i, i) if isinstance(i, str) else remap_nodes(i, idmap)
                          for i in v]
            else:
                out[k] = remap_nodes(v, idmap)
        return out
    if isinstance(thing, list):
        return [remap_nodes(v, idmap) for v in thing]
    return thing


def as_node(x, what="this position") -> str:
    if isinstance(x, dict):
        raise ParseError("%s needs something the path reaches, but was given a computed "
                         "value; a calculation has no roles to walk" % what)
    return x


class Lowering:
    def __init__(self, lexicon: cq.Lexicon, prefix: str = "", permissive: bool = False):
        self.lex = lexicon
        # The experimental instrument for "do refusals help?". With `permissive` the checks
        # that are a *judgement* -- the fan trap, an impossible unification, a node joined to
        # nothing -- record what they would have said and let the query through, so the SQL
        # the author would have got can be run and compared with the right answer. Parse
        # failures are not in this set: there is no SQL behind them to compare.
        self.permissive = permissive
        self.suppressed: List[str] = []
        self.n = 0
        self.prefix = prefix                     # keeps a rule body's ids apart from the rest
        self.vars: Dict[str, str] = {}
        self.by_concept: Dict[str, List[str]] = {}
        self.agg_names: Dict[str, str] = {}
        self.node_concept: Dict[str, str] = {}   # global: a sub-block may name a parent's node

    def fresh(self, prefix: str) -> str:
        self.n += 1
        return "%s%s%d" % (self.prefix, prefix, self.n)

    # -- block construction ------------------------------------------------

    def new_block(self) -> dict:
        return {"nodeType": "block", "id": self.fresh("b"), "nodes": [], "steps": [],
                "unifications": [], "conditions": [], "calculations": [],
                "subBlocks": [], "projections": []}

    def node(self, block, concept, name=None) -> str:
        nid = self.fresh("n")
        entry = {"id": nid, "concept": concept}
        if name:
            entry["name"] = name
        block["nodes"].append(entry)
        self.node_concept[nid] = concept
        self.by_concept.setdefault(concept, []).append(nid)
        return nid

    def enter(self, block, from_node, role, join="inner") -> str:
        fact = self.lex.role_owner[role]
        to = self.node(block, fact)
        block["steps"].append({"id": self.fresh("s"), "kind": "enter", "role": role,
                               "from": from_node, "to": to, "join": join})
        return to

    def exit(self, block, fact_node, role) -> str:
        to = self.node(block, self.lex.roles[role]["player"])
        block["steps"].append({"id": self.fresh("s"), "kind": "exit", "role": role,
                               "from": fact_node, "to": to, "join": "inner"})
        return to

    def unify(self, block, a, b):
        a = as_node(a, "a unification")
        b = as_node(b, "a unification")
        if a == b:
            return
        if not self.check_unifiable(a, b):
            return
        for u in block["unifications"]:
            if a in u["nodes"] or b in u["nodes"]:
                u["nodes"] = sorted(set(u["nodes"]) | {a, b})
                return
        block["unifications"].append({"id": self.fresh("u"), "nodes": [a, b]})

    def refuse(self, message: str):
        """Refuse, or -- under `permissive` -- note it and carry on."""
        if self.permissive:
            self.suppressed.append(message)
            return
        raise Judgement(message)

    def check_unifiable(self, a, b):
        """Two nodes said to be one instance must be able to be one: `Card ... AND ALSO Set
        ...` continued from Card, so Set was unified with it and the SQL equated cards.id
        with sets.id -- a join on nothing, silently empty (pilot, card_games). Two values
        of different types may be equated (`has SetCode: !csc` is how a correlation by
        value is written); an instance and a value, or two unrelated instances, may not."""
        ca, cb = self.node_concept.get(a), self.node_concept.get(b)
        if ca is None or cb is None or ca == cb:
            return True
        da, db = self.lex.concepts.get(ca, {}), self.lex.concepts.get(cb, {})
        na, nb = da.get("name", ca), db.get("name", cb)
        if (da.get("kind") == "value") != (db.get("kind") == "value"):
            self.refuse("%s and %s cannot be the same thing: one is a value, the other an "
                        "instance. To pick a %s by a value, filter on the fact that "
                        "carries it: `%s [has <ValueType>: !x]`"
                        % (na, nb, na if da.get("kind") != "value" else nb,
                           na if da.get("kind") != "value" else nb))
            return False
        if da.get("kind") != "value" and not self.lex.compatible(ca, cb):
            self.refuse("%s and %s cannot be the same thing: no %s is a %s. AND ALSO "
                        "continues from the head, so `... AND ALSO %s ...` says the "
                        "head is a %s; to reach a %s walk to it from the head, or "
                        "correlate through a value it shares: `WHERE SOME %s [has "
                        "<ValueType>: !x]`" % (na, nb, na, nb, nb, nb, nb, nb))
            return False
        return True

    # -- verb resolution (the schema-driven, ambiguous part) ---------------

    def resolve_move(self, verb, head_concept, target):
        """Which step does this verb part mean, given where the path already is?

        Three shapes, because an ORM fact type is also a Concept (model/model.md G1):
          ("enter_exit", from, to)  the ordinary traversal  p then q-reversed
          ("enter", from, None)     the path stops at the fact instance itself --
                                    `Employee has Assignment`, where Assignment is the
                                    objectified fact type, not a role player
          ("exit", None, to)        the path is already at a fact instance and reads another
                                    of its roles -- `... Assignment has Project`
        """
        head_fact = self.lex.fact_behind(head_concept)
        if head_fact is not None and head_concept != head_fact:
            head_concept = head_fact
        if head_fact is not None:
            roles = list(self.lex.concepts[head_fact]["roles"])
            viable = roles if self.verb_names(verb, head_fact) else []
            if isinstance(target, cq.RoleSpec):
                # B.2: the role reference says which exit. The verb part before it is
                # nominal, as it is when a role reference enters a fact type below -- so a
                # ring that reads `is connected to` is still left by `has ConnectedAtom`.
                named = [r for r in roles if r["id"] in target.roles]
                if named:
                    viable = named
            elif target is not None and isinstance(target, cq.TypeSpec):
                # If none of this fact type's own roles reaches the named target, the verb
                # is not an exit at all -- it starts a new fact type hanging off the
                # objectified one. Fall through rather than picking a wrong role.
                viable = [r for r in viable
                          if self.lex.compatible(r["player"], target.concept)]
                if len(viable) > 1:
                    # A ring: several roles of this fact type are played by the named type.
                    # A role whose own name is what was typed is the one meant.
                    typed = self.lex.concepts[target.concept]["name"].casefold()
                    exact = [r for r in viable if (r.get("name") or "").casefold() == typed]
                    if exact:
                        viable = exact
            if len(viable) == 1:
                return ("exit", None, viable[0]["id"])
            if len(viable) > 1:
                raise Ambiguous(
                    "%r from %s could reach %s -- name the type it reaches"
                    % (verb, self.lex.concepts[head_concept]["name"],
                       ", ".join(self.lex.concepts[r["player"]]["name"] for r in viable)))

        if isinstance(target, cq.RoleSpec):
            # Appendix B.2 <role reference>: the name says which role to enter by, which is
            # the only way to walk into a ring fact type.
            enter = [self.lex.roles[rid] for rid in target.roles
                     if self.lex.compatible(self.lex.roles[rid]["player"], head_concept)]
            if len(enter) == 1:
                return ("enter", enter[0]["id"], None)
            if len(enter) > 1:
                raise Ambiguous("%r names %d roles reachable from %s"
                                % (target.text, len(enter),
                                   self.lex.concepts[head_concept]["name"]))
            raise ParseError("%r is not a role %s can play"
                             % (target.text, self.lex.concepts[head_concept]["name"]))

        if target is not None and isinstance(target, cq.TypeSpec):
            target_fact = self.lex.fact_behind(target.concept)
            if target_fact is not None:
                entries = [r for r in self.lex.concepts[target_fact]["roles"]
                           if self.lex.compatible(r["player"], head_concept)]
                if len(entries) == 1:
                    return ("enter", entries[0]["id"], None)
                if len(entries) > 1:
                    raise Ambiguous(
                        "%s plays %d roles in %s; say which"
                        % (self.lex.concepts[head_concept]["name"], len(entries),
                           self.lex.concepts[target_fact]["name"]))

        _, from_role, to_role = self.resolve_verb(verb, head_concept, target)
        return ("enter_exit", from_role, to_role)

    def verb_names(self, verb, fact) -> bool:
        """Does this verb part name `fact` at all?

        Which role it exits by is deliberately not asked: section 6.1's role-exit p-reversed
        is defined for every role of the fact type, and a reading says how to verbalise the
        fact, not which exits exist. The target type narrows it; if nothing narrows it,
        resolve_move raises rather than guessing.
        """
        return any(f == fact for f, _, _ in self.lex.verbs.get(verb.casefold(), []))

    def resolve_verb(self, verb: str, head_concept: str, target) -> Tuple[str, str, str]:
        candidates = self.lex.verbs.get(verb.casefold(), [])
        viable = [c for c in candidates
                  if self.lex.compatible(self.lex.roles[c[1]]["player"], head_concept)]
        reaches_target = True
        if target is not None and isinstance(target, cq.TypeSpec):
            narrowed = [c for c in viable
                        if self.lex.compatible(self.lex.roles[c[2]]["player"], target.concept)]
            reaches_target = bool(narrowed)
            if narrowed:
                viable = narrowed
        # A fact type of the head's own type beats one reached by widening to a supertype and
        # narrowing back to a sibling. Both are legitimate paths -- two subtypes of one
        # supertype are one instance, which is why `Frpm has SatscoreRtype` works -- but when
        # the head's own type carries the verb, that is what was meant.
        #
        # Without this, a schema that splits one key across several 1:1 tables is unusable:
        # LiveSQLBench's `organ_transplant_large` makes CompatibilityMetric,
        # AdministrativeAndReview, Logistic and four more all subtypes of TransplantMatching,
        # each with its own donor reference, and `CompatibilityMetric has Demographic` was
        # ambiguous between all seven. Every one of those readings is a bare `{0} has {1}`,
        # so nothing else could separate them (finding 138).
        # ...but only among candidates that still reach where the query is going. When
        # nothing reaches the target, the head's own fact types do not either, and
        # preferring them replaces a message that names the sibling form with a type error
        # about whatever the head happens to carry.
        own = [c for c in viable if self.lex.roles[c[1]]["player"] == head_concept]
        if own and reaches_target:
            viable = own
        if len(viable) == 1 and not reaches_target and isinstance(target, cq.TypeSpec):
            # The query named where it is going and nothing this verb reads reaches it. With
            # more than one candidate still falls through to the ambiguity message below,
            # which already names the ring verb or the sibling type and is the better one;
            # with exactly one it fell through to `return viable[0]` and the step went
            # somewhere else *silently*. A DEFINE of three columns reads `has <Name>-` to the first
            # value only, so `has <Name> <SecondValueType>` took the first value and returned
            # a plausible wrong number -- six writers hit that on one benchmark run.
            wanted = self.lex.concepts[target.concept]["name"]
            ways = sorted({v for v, cands in self.lex.verbs.items() for c in cands
                           if self.lex.compatible(self.lex.roles[c[1]]["player"], head_concept)
                           and self.lex.compatible(self.lex.roles[c[2]]["player"],
                                                   target.concept)})
            raise ParseError(
                "%r from %s does not reach %s -- it reaches %s%s"
                % (verb, self.lex.concepts[head_concept]["name"], wanted,
                   ", ".join(sorted({self.lex.concepts[self.lex.roles[c[2]]["player"]]["name"]
                                     for c in viable})),
                   "" if not ways else ". %s reaches %s by %s"
                   % (self.lex.concepts[head_concept]["name"], wanted,
                      ", ".join(repr(w) for w in ways))))
        if not viable:
            name = self.lex.concepts[head_concept]["name"]
            raise ParseError(
                "no fact type reads %r starting from %s%s"
                % (verb, name,
                   "" if target is None or not isinstance(target, cq.TypeSpec)
                   else " and reaching %s" % self.lex.concepts[target.concept]["name"]))
        if len(viable) > 1:
            names = [self.lex.concepts[c[0]]["name"] for c in viable]
            hint = " -- name the type it reaches"
            if target is not None and isinstance(target, cq.TypeSpec):
                wanted = self.lex.concepts[target.concept]["name"]
                reaches = any(self.lex.compatible(self.lex.roles[c[2]]["player"], target.concept)
                              for c in viable)
                if not reaches:
                    # none of these fact types reaches the target: say which verb parts do,
                    # which is the answer when a ring reads `has manager-` and the query
                    # said `has Employee`
                    ways = sorted({v for v, cands in self.lex.verbs.items() for c in cands
                                   if c not in viable
                                   and self.lex.compatible(self.lex.roles[c[1]]["player"],
                                                           head_concept)
                                   and self.lex.compatible(self.lex.roles[c[2]]["player"],
                                                           target.concept)})
                    sibling = self.shared_supertype(head_concept, target.concept)
                    # Sibling first, and deliberately ahead of `ways`: a ring verb can look
                    # like it reaches the target when the target is a subtype of the ring's
                    # player, but it reaches a *different* instance. A sibling is the same
                    # instance, so where both fire the sibling is the answer.
                    if sibling is None and ways:
                        hint = (" and none of them reaches %s; %s reaches %s by %s"
                                % (wanted, self.lex.concepts[head_concept]["name"], wanted,
                                   ", ".join(repr(w) for w in ways)))
                    elif sibling is not None:
                        # Two subtypes of one supertype share its identifier, so there is no
                        # fact type between them and no verb that walks from one to the
                        # other: `Frpm has Satscore` cannot work and neither can the inverse
                        # verb, which is what this used to advise (finding 135). What does
                        # work is naming the other one's *value* directly -- both rows are
                        # the same instance, so reading across is a step, not a hop.
                        example = self.a_value_of(target.concept)
                        hint = (" and none of them reaches %s; %s and %s are both %s, so "
                                "they share an identifier and no fact type runs between "
                                "them. Name what you want from %s directly: `%s has %s`"
                                % (wanted, self.lex.concepts[head_concept]["name"], wanted,
                                   self.lex.concepts[sibling]["name"],
                                   wanted, self.lex.concepts[head_concept]["name"],
                                   example or "<a %s value type>" % wanted))
                    else:
                        hint = (" and none of them reaches %s; the fact type may read the "
                                "other way round, so try the inverse verb (\"is of\")"
                                % wanted)
            raise Ambiguous(
                "%r from %s is ambiguous between %s%s"
                % (verb, self.lex.concepts[head_concept]["name"],
                   ", ".join(names[:8]) + (", ..." if len(names) > 8 else ""), hint))
        return viable[0]

    def shared_supertype(self, a: str, b: str):
        """The nearest type both are, when neither is the other. Two subtypes of one
        supertype are one instance seen twice, which is why no fact type joins them."""
        def up(c, seen=None):
            seen = seen if seen is not None else []
            for s in self.lex.concepts.get(c, {}).get("supertypes", []):
                if s not in seen:
                    seen.append(s)
                    up(s, seen)
            return seen
        if a == b:
            return None
        ups = up(a)
        return next((s for s in up(b) if s in ups), None)

    def a_value_of(self, concept: str):
        """One value type the concept carries, to show in a message rather than describe."""
        for r in self.lex.roles_by_player.get(concept, []):
            owner = self.lex.role_owner.get(r)
            for other in self.lex.concepts.get(owner, {}).get("roles", []):
                c = self.lex.concepts.get(other["player"], {})
                if other["id"] != r and c.get("kind") == "value":
                    return c["name"]
        return None

    # -- denotations (A2) --------------------------------------------------

    def apply_denotation(self, block, node, concept, denotation):
        """Type: 'value'. Walk Idf(x) and compare the identifying values to the literals."""
        concept_def = self.lex.concepts[concept]

        # Type: !x binds x to the abstract instance (section 6.8), whatever the type's kind.
        # This has to come before the value-type branch or !x is read as a literal.
        if isinstance(denotation, tuple) and denotation and denotation[0] == "!":
            name = denotation[1]
            if name in self.vars:
                self.unify(block, self.vars[name], node)
            else:
                self.vars[name] = node
            return

        if concept_def["kind"] == "value":
            block["conditions"].append(self.compare_condition(
                "=", {"kind": "node", "node": node}, self.constant_value(denotation, concept)))
            return

        identifier = concept_def.get("identifier") or []
        if not identifier:
            raise ParseError("%s has no preferred identifier, so %s: ... cannot be expanded"
                             % (concept_def["name"], concept_def["name"]))

        items = list(denotation) if isinstance(denotation, tuple) else [denotation]
        if len(items) != len(identifier):
            raise ParseError("%s is identified by %d role(s); %d denotation(s) given"
                             % (concept_def["name"], len(identifier), len(items)))

        for role_id, item in zip(identifier, items):
            fact = self.lex.role_owner[role_id]
            others = [r for r in self.lex.concepts[fact]["roles"] if r["id"] != role_id]
            if not others:
                raise ParseError("identifying fact type %s has no other role"
                                 % self.lex.concepts[fact]["name"])
            fact_node = self.enter(block, node, role_id)
            value_node = self.exit(block, fact_node, others[0]["id"])
            target_concept = others[0]["player"]
            if isinstance(item, cq.Constant):
                self.check_denotation_type(concept_def, target_concept, item)
                block["conditions"].append(self.compare_condition(
                    "=", {"kind": "node", "node": value_node},
                    self.constant_value(item, target_concept)))
            else:
                h, _ = self.lower(block, item)
                self.unify(block, value_node, h)

    NUMERIC_TYPES = ("int", "real", "num", "dec", "float", "double", "serial")

    def check_denotation_type(self, concept_def, target_concept, item):
        """`Superhero: 'Copycat'` expands through Idf(Superhero), which is a numeric id: the
        literal can never match, and the query silently returns nothing. Say so, and say
        what was probably meant -- a filter on the value type that carries names."""
        dt = (self.lex.concepts.get(target_concept, {}).get("dataType") or {}).get("name", "")
        if item.numeric or not any(k in dt.lower() for k in self.NUMERIC_TYPES):
            return
        try:
            float(item.lexical)
            return
        except ValueError:
            pass
        name = concept_def["name"]
        target = self.lex.concepts[target_concept]["name"]
        by_name = next((c["name"] for c in self.lex.concepts.values()
                        if c["kind"] == "value" and c["name"].casefold()
                        in (name.casefold() + "name", name.casefold() + "_name")), None)
        hint = ("%s [has %s: %r]" % (name, by_name, item.lexical)) if by_name else \
            ("%s [has <the value type that carries it>: %r]" % (name, item.lexical))
        raise ParseError("%s: %r compares the literal to %s, which is numeric: a %s is "
                         "identified by its %s, and %r is not one. To pick one by another "
                         "value, filter on that value: %s"
                         % (name, item.lexical, target, name, target, item.lexical, hint))

    def constant_value(self, item, concept) -> dict:
        lexical = item.lexical if isinstance(item, cq.Constant) else str(item)
        dt = self.lex.concepts.get(concept, {}).get("dataType")
        if dt is None:
            # No concept to take a type from -- an aggregate's result, say. Falling back to
            # text bound `COUNT(..) > 1` as the string '1', and SQLite orders every integer
            # below every string, so the comparison was always false.
            numeric = isinstance(item, cq.Constant) and item.numeric
            dt = {"name": ("decimal" if "." in lexical else "integer") if numeric else "text"}
        return {"kind": "constant", "dataType": dt, "lexical": lexical}

    @staticmethod
    def compare_condition(op, left, right) -> dict:
        return {"kind": "compare", "op": op, "left": left, "right": right}

    # -- the recursion -----------------------------------------------------

    def lower(self, block, ast, head: Optional[str] = None) -> Tuple[str, str]:
        """Return (head node, tail node) for `ast`, adding to `block`."""

        if isinstance(ast, cq.RoleSpec):
            # A bare role reference in a value position means the role's player.
            player = self.lex.roles[ast.roles[0]]["player"]
            node = head if (head is not None and self._reusable(block, head, player)) \
                else self.node(block, player)
            return node, node

        if isinstance(ast, cq.VarRef):
            if ast.name not in self.vars:
                raise ParseError("%r is not bound anywhere in this query" % ast.name)
            node = self.vars[ast.name]
            return node, node

        if isinstance(ast, cq.ImplicitHead):
            if head is None:
                raise ParseError("a path starting with a verb needs something to continue "
                                 "from; put a type before it")
            return head, head

        if isinstance(ast, cq.TypeSpec):
            if ast.var and ast.var in self.vars:
                node = self.vars[ast.var]
                if head is not None:
                    self.unify(block, head, node)
                if not self._restates(node, ast.concept):
                    # `Employee e ... AND ALSO Manager e`: the same instance, said to be
                    # a Manager. A node of the subtype, unified with e, narrows it.
                    narrowed = self.node(block, ast.concept)
                    self.unify(block, node, narrowed)
            elif head is not None and self._reusable(block, head, ast.concept):
                # "... has EmployeeName" names the type the path just reached; that is a
                # restatement of the node, not a second one to join to it.
                node = head
                if ast.var:
                    self.vars[ast.var] = node
            else:
                node = self.node(block, ast.concept, ast.var)
                if ast.var:
                    self.vars[ast.var] = node
                if head is not None:
                    self.unify(block, head, node)
            if ast.denotation is not None:
                self.apply_denotation(block, node, ast.concept, ast.denotation)
            return node, node

        if isinstance(ast, cq.Call) and self.is_boolean(ast):
            # A boolean function in path position -- `has AtomId i AND ALSO like(i, 'TR%')`
            # -- is a condition on the block. Lowering it as a scalar would compute it and
            # then never read it, which silently drops the test (found by the pilot).
            block["conditions"].append(self.lower_condition(block, ast, head))
            return head, head

        if isinstance(ast, (cq.Arith, cq.Call)):
            node = self.scalar(block, ast)
            return node, node

        if isinstance(ast, cq.Conditional):
            v = self.scalar_value(block, ast)
            return v, v

        if isinstance(ast, cq.SubQuery):
            # `(LIST x FROM ... ORDERED WITH c DESCENDING THE FIRST 1)` as a bag. The whole
            # query lowers into this block -- ordering and limit included -- and its single
            # column is what the bag holds. Two columns would be a relation, not a bag.
            self.lower_query(ast.query, block)
            pj = block.get("projections", [])
            if len(pj) != 1:
                raise ParseError("a (LIST ...) used as a bag must list exactly one thing; "
                                 "this one lists %d" % len(pj))
            src = pj[0]["source"]
            v = src["node"] if src.get("kind") == "node" else src
            return v, v

        if isinstance(ast, cq.Constant):
            v = {"kind": "constant",
                 "dataType": {"name": "numeric" if ast.numeric else "text"},
                 "lexical": ast.lexical}
            return v, v

        if isinstance(ast, cq.Seq):
            h, t = self.lower(block, ast.parts[0], head)
            for part in ast.parts[1:]:
                if isinstance(part, cq.Filter):      # [ ... ] constrains the head, not the tail
                    anchored = self._starts_from_bound(part.expr)
                    if binds_nothing(part.expr):
                        sub = self.new_block()
                        h2, _ = self.lower(sub, part.expr, None if anchored else t)
                        if not anchored:
                            self.unify(sub, t, h2)
                        block["subBlocks"].append(sub)
                    else:
                        self.lower(block, part.expr, None if anchored else t)
                    continue
                verb, target, optional = part.verb, part.target, part.optional
                concept = self.concept_of(as_node(t, "a verb step"))
                kind, from_role, to_role = self.resolve_move(verb, concept, target)
                join = "outer" if optional else "inner"
                if kind == "enter_exit":
                    t = self.exit(block, self.enter(block, t, from_role, join), to_role)
                elif kind == "enter":
                    t = self.enter(block, t, from_role, join)
                    if isinstance(target, cq.RoleSpec):
                        target = None            # the role name only said which way to go
                    elif target is not None and isinstance(target, cq.TypeSpec) \
                            and target.denotation is None and target.var is None:
                        target = None            # the target only named where to stop
                else:
                    t = self.exit(block, t, to_role)
                if target is not None:
                    if isinstance(target, cq.Constant):
                        block["conditions"].append(self.compare_condition(
                            "=", {"kind": "node", "node": t},
                            self.constant_value(target, self.concept_of(t))))
                    else:
                        th, _ = self.lower(block, target, t)
                        self.unify(block, t, th)
            return h, t

        if isinstance(ast, cq.SubExpr):
            base = head if head is not None else None
            first_h = None
            for part in ast.parts:
                h, _ = self.lower(block, part, base)
                if first_h is None:
                    first_h = h
                    base = h
                else:
                    self.unify(block, first_h, h)
            return first_h, first_h

        if isinstance(ast, cq.Named):
            h, t = self.lower(block, ast.path, head)
            self.vars[ast.name] = t
            return h, t

        if isinstance(ast, cq.Front):
            # Fr sets tl = hd: the path becomes a filter on its own head.
            h, _ = self.lower(block, ast.path, head)
            return h, h

        if isinstance(ast, cq.Distinct):
            h, t = self.lower(block, ast.path, head)
            block["distinct"] = True
            return h, t

        if isinstance(ast, cq.Where):
            h, t = self.lower(block, ast.path, head)
            cond = self.lower_condition(block, ast.condition, h)
            block["conditions"].append(cond)
            return h, t

        if isinstance(ast, cq.Binary):
            return self.lower_binary(block, ast, head)

        if isinstance(ast, cq.Compare):
            h, t = self.lower(block, ast.left, head)
            if isinstance(ast.right, cq.Constant):
                right = self.constant_value(
                    ast.right, self.concept_of(t) if not isinstance(t, dict) else None)
            else:
                rh, _ = self.lower(block, ast.right)
                right = as_value(rh)
            block["conditions"].append(self.compare_condition(ast.op, as_value(t), right))
            return h, t

        if isinstance(ast, cq.SetCompare):
            return self.lower_set_compare(block, ast, head)

        if isinstance(ast, cq.Aggregate):
            return self.lower_aggregate(block, ast, head)

        raise ParseError("cannot lower %s" % type(ast).__name__)

    @staticmethod
    def _first_of(path):
        """The element a path begins with."""
        first = path
        while True:
            if isinstance(first, cq.Seq):
                first = first.parts[0]
            elif isinstance(first, (cq.Where, cq.Distinct, cq.Front, cq.Named)):
                first = first.path
            elif isinstance(first, cq.Binary):
                first = first.left
            else:
                return first

    def _restates_head(self, block, head, path) -> bool:
        """Does `path` begin by naming the head's own type (or a supertype of it)?"""
        first = self._first_of(path)
        return head is not None and isinstance(first, cq.TypeSpec) \
            and (first.var is None or first.var not in self.vars) \
            and self._reusable(block, head, first.concept)

    def _starts_from_bound(self, path) -> bool:
        """Does `path` begin at a variable bound earlier? `Employee e has manager Employee b
        AND ALSO b has EmployeeName m` continues from b, not from the head. Unifying b with
        the head -- Fr applied blindly -- made it a self-join on emp_nr = manager_nr, and
        the rows quietly vanished (pilot, formula_1)."""
        first = self._first_of(path)
        if isinstance(first, cq.VarRef):
            return first.name in self.vars
        return isinstance(first, cq.TypeSpec) and bool(first.var) and first.var in self.vars

    def _reusable(self, block, head, concept) -> bool:
        """May a TypeSpec restate the head rather than adding a node of its own?

        Only within one block. Across a boundary -- a bag or an existential sub-block, which
        inherit the enclosing head so an implicit head has something to continue from -- the
        node has to be new, or the subquery selects from an alias it never declares. The
        unification the caller adds is what correlates the two.
        """
        if not any(n["id"] == head for n in block["nodes"]):
            return False
        return self._restates(head, concept)

    def _restates(self, node, concept) -> bool:
        """Does naming `concept` at `node` say nothing new? A restatement, or a
        generalisation of what is there, names the same instance. A subtype (or a sibling
        under the same root) narrows it: that is a node of its own, unified with the head
        on identity, so the subtype's own population applies -- `Patient [is of
        AbnormalLaboratory]` used to reuse the Laboratory node and silently drop the
        derived subtype's rule."""
        try:
            here = self.concept_of(node)
        except ParseError:
            return True
        return concept == here or concept in self.lex.supertypes(here)

    def concept_of(self, node_id) -> str:
        try:
            return self.node_concept[node_id]
        except KeyError:
            raise ParseError("unknown node %s" % node_id)

    FR_OPS = ("and", "or", "butnot")

    @classmethod
    def fr_chain(cls, ast):
        """Flatten a left-leaning FrSetOper tree into (leftmost operand, [(op, operand)]).

        `A AND ALSO B OR OTHERWISE C` parses left-associatively, and section 7.3 reads it as
        one chain of filters over a single head: A supplies the head, B and C constrain it.
        Keeping the tree shape would make A's filter part of the head, which is what turned
        OR OTHERWISE into a no-op.
        """
        rest = []
        while isinstance(ast, cq.Binary) and ast.op in cls.FR_OPS:
            rest.append((ast.op, ast.right))
            ast = ast.left
        rest.reverse()
        return ast, rest

    def lower_setexpr(self, query) -> dict:
        """Section 6.2's ∪, ∩ and − over whole paths, as model.md's SetExpr.

        Each operand is a query of its own: a `(LIST ...)` keeps its projections, a bare path
        lists its head and tail. The operands must list the same number of things, which the
        CCM requires outright rather than coercing (G3). Ordering and the limit apply to the
        whole, and an ordering key is the name of a listed thing, since a compound result has
        no path to bind a variable in."""
        if query.projections:
            raise ParseError(
                "LIST ... FROM over a set operation does not say which side it lists; put a "
                "LIST inside each operand: (LIST a FROM ...) UNITED WITH (LIST a FROM ...)")
        expr = self.setexpr(query.body)
        names = self.projection_names(expr)
        ordering = []
        for item in query.ordering:
            if item.end or item.expr is not None or item.key not in names:
                raise ParseError(
                    "a set operation is ordered by the name of something it lists (%s); %r "
                    "is not one of them" % (", ".join(names), item.end or item.key))
            ordering.append((item.key, item.direction))
        expr["_ordering"] = ordering
        if query.limit is not None:
            if query.limit.per is not None:
                raise ParseError("PER cannot apply to a set operation, which has no path to "
                                 "partition")
            if query.limit.ties:
                raise ParseError("WITH TIES applies to the rows a LIST returns, and a set operation "
                                 "is not that. Take the ties in the outer LIST instead.")
            expr["_limit"] = {"count": query.limit.count, "offset": query.limit.offset}
        return expr

    def setexpr(self, ast) -> dict:
        operands = []
        for side in (ast.left, ast.right):
            if isinstance(side, cq.Binary) and side.op in SET_OPS:
                operands.append(self.setexpr(side))
            else:
                block = self.new_block()
                q = side.query if isinstance(side, cq.SubQuery) else cq.Query(body=side)
                with self.rebinding(side):
                    self.lower_query(q, block)
                operands.append(block)
        arities = [len(self.projection_names(o)) for o in operands]
        if len(set(arities)) != 1:
            raise ParseError(
                "%s needs both sides to list the same number of things; the left lists %d "
                "and the right %d" % (SET_WORDS[ast.op], arities[0], arities[1]))
        return {"nodeType": "setExpr", "op": ast.op, "all": False, "operands": operands}

    @classmethod
    def projection_names(cls, expr) -> list:
        if expr.get("nodeType") == "setExpr":
            return cls.projection_names(expr["operands"][0])
        return [p["name"] for p in expr.get("projections", [])]

    def lower_binary(self, block, ast, head):
        if ast.op in SET_OPS:
            raise ParseError(
                "%s combines two whole paths, so it can only stand as the whole query or as "
                "an operand of another set operation, not inside a path" % SET_WORDS[ast.op])
        if ast.op not in self.FR_OPS:
            raise ParseError("unknown operator %r" % ast.op)

        base, rest = self.fr_chain(ast)
        # Once any operand is OR-ed, none of them may be merged into the block: a merged
        # operand is a hard filter that no later alternative could widen.
        disjunctive = any(op == "or" for op, _ in rest)
        # The operands of a disjunctive fold are tagged with the fold and their position:
        # the normal form writes them together, in order, as a parenthesised front
        # expression before the head's steps (finding 117). Which sub-blocks are operands
        # is not something list order can tell -- a filter lowered later may land earlier.
        fold = self.fresh("fold") if disjunctive else None
        if disjunctive and head is not None and binds_nothing(base):
            # ... and the leftmost operand is an operand too. `[A OR OTHERWISE B]` merged A
            # into the block and OR-ed B against nothing, so it meant A AND B -- silently,
            # and with the opposite answer (finding 41). Only when the base is a pure
            # restriction: where it establishes the head or binds a name, it is the path the
            # alternatives restrict, not one of them.
            h = head
            sub = self.new_block()
            sub["_frOp"] = "and"           # the first term of the fold; its operator is unread
            sub["_frFold"], sub["_frPos"] = fold, 0
            h2, _ = self.lower(sub, base, h)
            self.unify(sub, h, h2)
            block["subBlocks"].append(sub)
        else:
            before = len(block["subBlocks"])
            h, _ = self.lower(block, base, head)   # the leftmost operand supplies the head
            if fold is not None:
                # the base's own filters (`Set [has SetCode: 'C14'] OR OTHERWISE ...`) are
                # the fold's first alternative, and the normal form writes them inside the
                # parentheses; outside, they would narrow the whole union
                for s in block["subBlocks"][before:]:
                    if "_frFold" not in s:
                        s["_frFold"], s["_frPos"] = fold, 0

        for op, operand in rest:
            # An operand that starts at a bound variable is anchored there, not at the head.
            anchored = self._starts_from_bound(operand)
            if op == "and" and not disjunctive and not binds_nothing(operand):
                # The operand names something the rest of the query may refer to, so it has
                # to share the block rather than hide in a sub-block.
                h2, _ = self.lower(block, operand, None if anchored else h)
                if not isinstance(h2, dict) and not anchored:
                    self.unify(block, h, h2)
                # A computed value -- an aggregate, say -- has no head to unify with. It
                # simply joins the block's calculations and is reached by name.
                continue
            # Fr proper: the operand can only constrain the head. Merging it would join, and
            # a one-to-many leg would multiply the result -- Fr never does.
            sub = self.new_block()
            if op == "butnot":
                sub["negated"] = True
            # The operator rides on the sub-block, not a list parallel to subBlocks: filter
            # sub-expressions add blocks of their own, so positions do not line up.
            sub["_frOp"] = "or" if op == "or" else "and"
            if fold is not None:
                sub["_frFold"], sub["_frPos"] = fold, 1 + rest.index((op, operand))
            h2, _ = self.lower(sub, operand, None if anchored else h)
            if not anchored:
                self.unify(sub, h, h2)
            block["subBlocks"].append(sub)
        return h, h                                # Fr: the tail is the head

    @contextlib.contextmanager
    def rebinding(self, ast):
        """Lower `ast` as if its own variable names were fresh.

        A bag block re-expresses a path that may already have been lowered into the enclosing
        block, so its `Track t` must become a new node in the bag, not a reference to the one
        outside -- otherwise the subquery selects a column from an alias it does not declare.
        Names bound further out are left alone, so `!x` correlation still works.
        """
        names = named_vars(ast)
        saved = {n: self.vars[n] for n in names if n in self.vars}
        for n in names:
            self.vars.pop(n, None)
        try:
            yield
        finally:
            for n in names:
                self.vars.pop(n, None)
            self.vars.update(saved)

    def lower_set_compare(self, block, ast, head):
        # P (subset) Q keeps the head/tail pairs of P whose tails all appear as heads of Q,
        # so P is both the result and the left bag. When the comparison is the whole query
        # there is no enclosing head yet, so establish one from P first.
        if head is None:
            head, _ = self.lower(block, ast.left, None)
        h = head
        left_block = self.new_block()
        with self.rebinding(ast.left):
            lh, lt = self.lower(left_block, ast.left, h)
        self.unify(left_block, lh, h)
        right_block = self.new_block()
        with self.rebinding(ast.right):
            _, rt = self.lower(right_block, ast.right)
        block["conditions"].append(self.set_compare_condition(ast, left_block, lt,
                                                              right_block, rt))
        return h, h

    @staticmethod
    def set_compare_condition(ast, left_block, lt, right_block, rt) -> dict:
        cond = {"kind": "setCompare", "op": ast.op,
                "left": {"block": left_block, "node": lt},
                "right": {"block": right_block, "node": rt}}
        return {"kind": "not", "operand": cond} if getattr(ast, "negated", False) else cond

    def lower_aggregate(self, block, ast, head=None):
        """Section 6.6's group functions.

        Without GROUPED BY the aggregate is a scalar over its own path, so it lowers into a
        block of its own and the emitter renders it as a subquery. With GROUPED BY the path
        is grouped *within the enclosing query*, so it has to share that block -- there is no
        other way for the grouping attributes and the aggregate to appear side by side.
        """
        if ast.group_by:
            # The path is grouped within the enclosing query, and section 6.4's Fr says an
            # AND ALSO operand continues from the head: `Employee [...] has Department d AND
            # ALSO THE SUM OF s IN Employee has EmployeeSalary s GROUPED BY d` sums the
            # salaries of *those* employees. Lowered with no head, the restated Employee was
            # a second range and the sum was a cross product (pilot, twice). A path that
            # starts elsewhere -- `THE COUNT OF Atom [has Molecule m]` beside Molecule m --
            # is its own range, correlated by what it names.
            _, it = self.lower(block, ast.path, head if self._restates_head(block, head,
                                                                              ast.path) else None)
            if ast.over:
                if ast.over not in self.vars:
                    raise ParseError("%r IN names an attribute the path does not bind"
                                     % ast.over)
                it = self.vars[ast.over]
            context = []
            for name in ast.group_by:
                if not isinstance(name, str):
                    v, _ = self.lower(block, name)         # GROUPED BY year(d): a value
                    context.append(v)
                    continue
                if name not in self.vars:
                    raise ParseError("GROUPED BY %r, but %r is not bound by this query"
                                     % (name, name))
                context.append(self.vars[name])
            # A grouped aggregate collapses its group to one row, and this branch has no
            # derived table to order or trim on the way. The ungrouped branch below does --
            # `THE LIST OF s ... ORDERED WITH s DESCENDING THE FIRST 2` gathers the two
            # largest -- and both clauses used to be accepted here and dropped on the floor,
            # which made the primer's "it carries its own ORDERED WITH ... THE FIRST n" true
            # of the gather and false of the grouped gather it was written under. Refused
            # rather than honoured because top-n-per-group already has a spelling.
            if ast.ordering or ast.limit is not None:
                raise ParseError(
                    "%s cannot carry its own %s when it is GROUPED BY: the group collapses to "
                    "one row and there is nothing left to order or cut. Either drop GROUPED BY "
                    "-- `THE %s OF x IN <path> ORDERED WITH k DESCENDING THE FIRST n` gathers "
                    "the top n over the whole query -- or ask for the rows themselves with "
                    "`ORDERED WITH k DESCENDING THE FIRST n PER g`, which is top-n within each "
                    "group." % (ast.func.upper(), "ordering" if ast.ordering else "row limit",
                                ast.func.upper()))
            # A key is a node the path reaches or a computed value bound with AS (or
            # written in place); either groups the block.
            calc = {"id": self.fresh("calc"), "function": "fn." + self.agg_function(ast),
                    "arguments": [as_value(it)] + self.agg_extra(block, ast),
                    "aggregation": {"context": [c if isinstance(c, dict) else as_node(c)
                                                for c in context],
                                    "distinct": ast.distinct,
                                    # `WITHIN` partitions without collapsing: the same keys,
                                    # reported beside every row. The emitter turns this into
                                    # OVER (PARTITION BY ...) rather than GROUP BY.
                                    "window": bool(getattr(ast, "windowed", False))}}
            # Row-relative functions carry the order their window runs in. RANK orders by the
            # value being ranked, descending, so rank 1 is the largest; LAG orders by the key
            # the query gave it. Neither means anything without an order, which is why the
            # parser refuses them outside WITHIN.
            if ast.func in ("rank", "percent_rank"):
                calc["aggregation"]["order"] = [(as_value(it), getattr(ast, "direction", None)
                                                 or "desc")]
                calc["arguments"] = []
            elif ast.func == "lag":
                key = getattr(ast, "order_key", None)
                if key is None:
                    raise ParseError("THE PREVIOUS needs a BY key")
                ordered, _ = self.lower(block, key)
                calc["aggregation"]["order"] = [(as_value(ordered), "asc")]
            block["calculations"].append(calc)
            v = {"kind": "calculation", "calculation": calc["id"]}
            self.agg_names[calc["id"]] = ast.func
            return v, v

        inner = self.new_block()
        # The aggregate's path is a query of its own: a name it binds is its own, so two
        # aggregates side by side may both say `[has EmployeeSalary s]` without the second
        # reaching into the first's block. Names bound further out stay visible, which is
        # what `!d` correlation relies on.
        ordering, extra = [], []
        with self.rebinding(ast.path):
            _, it = self.lower(inner, ast.path)
            if isinstance(ast.over, str):
                if ast.over not in self.vars:
                    raise ParseError("%r IN names an attribute the path does not bind"
                                     % ast.over)
                it = self.vars[ast.over]
            elif ast.over is not None:
                # `THE LIST OF (s * 2) IN <path>`: an expression over what the path bound,
                # computed in the bag and aggregated there.
                it = self.scalar(inner, ast.over)
            # while the aggregate's own names are still bound: a sort key inside THE LIST OF
            # names what the aggregated path bound, not what the query around it did
            if ast.ordering:
                ordering = resolve_ordering(self, ast.ordering, inner, it, it)
            # ...and so does the key of an OBJECT: a value of the bag's own rows
            extra = self.agg_extra(inner, ast)
        # The sort keys and the second operand are grounded with the argument: a bag over
        # a value the enclosing block bound is a copy of that block, and every reference
        # into it has to point at the copy. The ordering did not, so `THE LIST OF s ORDERED
        # WITH s` at the top level ranged over the copy and sorted by the original -- "no
        # such column: employ1.salary" from inside a derived table that had no employ1.
        it, ordering, extra = self.ground_aggregate(inner, block, it, ordering, extra)
        calc = {"id": self.fresh("calc"), "function": "fn." + self.agg_function(ast),
                "arguments": [as_value(it)] + extra,
                "aggregation": {"context": "universal", "distinct": ast.distinct},
                "_block": inner}
        if ordering:
            calc["_ordering"] = ordering
        if ast.limit is not None:
            if ast.limit.ties:
                raise ParseError("WITH TIES applies to the rows a LIST returns, and an aggregate's own ordering "
                                 "is not that. Take the ties in the outer LIST instead.")
            calc["_limit"] = {"count": ast.limit.count, "offset": ast.limit.offset}
        block["calculations"].append(calc)
        v = {"kind": "calculation", "calculation": calc["id"]}
        self.agg_names[calc["id"]] = ast.func
        return v, v

    @staticmethod
    def agg_function(ast) -> str:
        """`THE LIST OF x SEPARATED BY s` is a join, not a list: the same bag, rendered as
        text. Everything else keeps the name the keyword table gave it."""
        if ast.func == "list" and getattr(ast, "extra", None) is not None:
            return "join"
        return ast.func

    def agg_extra(self, block, ast) -> list:
        """The aggregate's second operand, lowered beside the bag it applies to: the key of
        an OBJECT, the separator of a joined LIST. Empty for every other aggregate."""
        extra = getattr(ast, "extra", None)
        if extra is None:
            return []
        value, _ = self.lower(block, extra)
        return [as_value(value)]

    def lower_confluence(self, block, conf, head):
        """§6.5. Attach each side path at its junction with an outer join; return the gathered
        nodes as (label, node) so they can be projected by default.

        The join is outer because that is what the report's ⟕ says, and it is the whole
        point: `Person working for Group` requires the fact; `Firstname of` gathers a value
        that may not be there. On a junction role that is mandatory the fact is always
        present and an inner join is the same relation, so the validator's objection to
        outer-joining a mandatory role is met by not doing so.
        """
        out = []
        for i, el in enumerate(conf.elements):
            if el.via is not None:
                if el.via not in self.vars:
                    raise ParseError("VIA %r, but %r is not bound by the base path"
                                     % (el.via, el.via))
                junction = self.vars[el.via]
            else:
                junction = head
            jc = self.concept_of(as_node(junction, "a confluence junction"))
            # Attached into a side block of its own, because whether it belongs there is not
            # known until it has been walked: a gathered value that is one per junction is
            # spliced back into the query, and one that is many stays where it is and is
            # returned nested.
            side = self.new_block()
            node = self._attach(side, el.path, junction, jc)
            label = el.name or self.lex.concepts.get(self.concept_of(node), {}).get(
                "name", "gathered%d" % (i + 1))
            if self.fans_out(side):
                value = self.nest(block, side, node, label, el)
            else:
                for key in ("nodes", "steps", "unifications", "conditions",
                            "calculations", "subBlocks"):
                    block[key].extend(side[key])
                value = node
                if el.name:
                    self.vars[el.name] = node
            out.append((label, value))
        return out

    def fans_out(self, side) -> bool:
        """Does this side path reach many instances for one junction?

        §6.5's confluence is the one place ConQuer-92 knowingly departed from LISA-D: there
        it gathered a *nested relation*, and the report says why it does not here -- "since
        SQL-92 is not able to deal with nested relations, we have changed the definition
        slightly as opposed to the one used in [HPW93]" (§6.5). The change cost more than it
        looks: an outer join to a side path that fans out does not gather three phone numbers
        onto a person, it turns the person into three rows, and every other gathered value
        and every aggregate beside it is repeated with them.

        SQLite can deal with nested relations, so a side path that fans out is gathered as
        one, and only the ones that cannot multiply are still flattened. Silence in the model
        keeps the flattened reading: without uniqueness constraints nothing is known to be
        one-per-junction, and nesting everything would be as wrong as nesting nothing.
        """
        return getattr(self.lex, "uniqueness_known", False) and any(
            st["kind"] == "enter" and not self.lex.is_functional(st["role"])
            for st in side["steps"])

    def nest(self, block, side, node, label, el):
        """Gather a side path as a nested relation: a list-valued calculation over its own
        block, correlated at the junction. The emitter renders it the way it renders any
        other aggregate over a block -- which is the point: nesting needed no new machinery,
        only a group function whose result is a bag."""
        calc = {"id": self.fresh("calc"), "function": "fn.list",
                "arguments": [as_value(node)],
                "aggregation": {"context": "universal", "distinct": False},
                "_block": side}
        if el.name:
            self.vars[el.name] = node      # so the element's own sort key may name it
        if el.ordering:
            calc["_ordering"] = resolve_ordering(self, el.ordering, side, node, node)
        if el.limit is not None:
            if el.limit.ties:
                raise ParseError("WITH TIES applies to the rows a LIST returns, and a gathered list "
                                 "is not that. Take the ties in the outer LIST instead.")
            calc["_limit"] = {"count": el.limit.count, "offset": el.limit.offset}
        block["calculations"].append(calc)
        # Names the side path bound belong to the side path: its nodes are not in this block,
        # so a later mention of one would select a column from an alias nothing declares.
        inside = {n["id"] for n in side["nodes"]}
        for name, bound in list(self.vars.items()):
            if not isinstance(bound, dict) and bound in inside:
                del self.vars[name]
        value = {"kind": "calculation", "calculation": calc["id"]}
        self.agg_names[calc["id"]] = label
        if el.name:
            self.vars[el.name] = value
        return value

    def _attach(self, block, path, junction, jc):
        """Walk one side path from the junction, every step an outer join."""
        def outer_for(from_role):
            role = self.lex.roles.get(from_role, {})
            return "inner" if role.get("isMandatory") else "outer"

        # verb-led: `has Firstname`, `OPTIONALLY has Surname` -- read from the junction's side
        if isinstance(path, (cq.Step, cq.Seq)) and not (
                isinstance(path, cq.Seq) and isinstance(path.parts[0], cq.TypeSpec)):
            steps = path.parts if isinstance(path, cq.Seq) else [path]
            t, concept = junction, jc
            for st in steps:
                kind, from_role, to_role = self.resolve_move(st.verb, concept, st.target)
                # the same three shapes the main path lowering knows (resolve_move's doc):
                # through a fact, into an objectified fact, or out of one already reached
                if kind == "enter_exit":
                    t = self.exit(block, self.enter(block, t, from_role,
                                                    outer_for(from_role)), to_role)
                elif kind == "enter":
                    t = self.enter(block, t, from_role, outer_for(from_role))
                else:
                    t = self.exit(block, t, to_role)
                concept = self.concept_of(t)
                target = st.target
                if isinstance(target, cq.RoleSpec) or (
                        isinstance(target, cq.TypeSpec) and target.denotation is None
                        and target.var is None):
                    target = None
                if target is not None:
                    th, _ = self.lower(block, target, t)
                    self.unify(block, t, th)
            return t

        # a bare type, or `Type verb` with the verb dangling: resolve from the gathered value's
        # side, then enter the same fact type from the junction's role -- the report's
        # alpha-renaming of hd to a_i and tl to x_i, done without reversing the path.
        head_spec = path.parts[0] if isinstance(path, cq.Seq) else path
        if not isinstance(head_spec, cq.TypeSpec):
            raise ParseError("cannot attach %s as a confluence element" % type(path).__name__)
        verbs = [p for p in (path.parts[1:] if isinstance(path, cq.Seq) else [])]
        if verbs:
            kind, from_role, to_role = self.resolve_move(verbs[0].verb, head_spec.concept, None)
            if kind != "enter_exit":
                raise ParseError("%r from %s does not reach the junction as a value"
                                 % (verbs[0].verb, self.lex.concepts[head_spec.concept]["name"]))
            # from_role is the gathered value's role; to_role faces the junction
            if not self.lex.compatible(self.lex.player(to_role), jc):
                raise ParseError("%s %s leads to %s, not to the junction %s"
                                 % (self.lex.concepts[head_spec.concept]["name"],
                                    verbs[0].verb,
                                    self.lex.concepts[self.lex.player(to_role)]["name"],
                                    self.lex.concepts[jc]["name"]))
            gathered_role, junction_role = from_role, to_role
        else:
            facts = self.lex.facts_between(jc, head_spec.concept)
            if not facts:
                raise ParseError("no fact type connects %s to %s, so %s cannot be gathered "
                                 "here; say how -- `has %s`, or `%s of`"
                                 % (self.lex.concepts[jc]["name"],
                                    self.lex.concepts[head_spec.concept]["name"],
                                    self.lex.concepts[head_spec.concept]["name"],
                                    self.lex.concepts[head_spec.concept]["name"],
                                    self.lex.concepts[head_spec.concept]["name"]))
            if len(facts) > 1:
                raise Ambiguous("%d fact types connect %s to %s: %s. Say which with a verb"
                                % (len(facts), self.lex.concepts[jc]["name"],
                                   self.lex.concepts[head_spec.concept]["name"],
                                   ", ".join(self.lex.concepts[f]["name"] for f in facts)))
            junction_role, gathered_role = facts[0]
        node = self.exit(block, self.enter(block, junction, junction_role,
                                            outer_for(junction_role)), gathered_role)
        if head_spec.var:
            self.vars[head_spec.var] = node
        if head_spec.denotation is not None:
            self.apply_denotation(block, node, head_spec.concept, head_spec.denotation)
        return node

    def mirror_block(self, outer, inner) -> dict:
        """Copy `outer`'s nodes, steps, unifications, conditions and sub-blocks into `inner`
        under fresh ids; returns the id map. A condition naming a calculation is skipped:
        the calculation lives in the enclosing block, and copying it could pull in another
        aggregate and recurse."""
        idmap = {}
        for n in outer["nodes"]:
            copy = dict(n)
            copy["id"] = idmap[n["id"]] = self.fresh("n")
            inner["nodes"].append(copy)
            self.node_concept[copy["id"]] = copy["concept"]
        for st in outer["steps"]:
            copy = dict(st)
            copy["id"] = self.fresh("s")
            copy["from"], copy["to"] = idmap.get(st["from"], st["from"]), idmap.get(st["to"], st["to"])
            inner["steps"].append(copy)
        for u in outer["unifications"]:
            inner["unifications"].append({"id": self.fresh("u"),
                                          "nodes": [idmap.get(n, n) for n in u["nodes"]]})
        for cond in outer["conditions"]:
            if not self._names_calculation(cond):
                inner["conditions"].append(remap_nodes(cond, idmap))
        for sub in outer["subBlocks"]:
            inner["subBlocks"].append(remap_nodes(sub, idmap))
        return idmap

    def regroup_grouped(self, block, calc) -> bool:
        """Re-lower a grouped aggregate as one over a bag of its own, correlated on its keys
        (finding 117). The block is mirrored into the inner block, each key's node is
        unified with the outer one -- so the emitter groups the bag by the outer keys --
        and the argument now names the copy. `_group` keeps the keys for the outer GROUP BY
        and the normal form; `_outer_arguments` what was written. False when a key names no
        node the bag could be correlated on.

        A *computed* key correlates on the value of the expression and not on the nodes
        inside it. Unifying those nodes says "the same salary" where the key says "the same
        side of 150000", which is a different and much finer grouping: the bag then held one
        row where the group has many, and the aggregate came back silently wrong. Found by a
        writer who checked `GROUPED BY if(abs(ps - pc) < 0.1 AND pc > 0.7, 1, 0)` against
        the same query with the key wrapped in a cast, which took the other path.
        """
        context = calc["aggregation"]["context"]
        keys = context if isinstance(context, list) else []
        key_nodes, key_exprs = [], []
        for key in keys:
            if isinstance(key, str):
                key_nodes.append(key)
                continue
            if not self._nodes_named(key):
                return False              # nothing in the bag to correlate the key against
            key_exprs.append(key)
        inner = self.new_block()
        idmap = self.mirror_block(block, inner)
        for nid in dict.fromkeys(key_nodes):
            if nid in idmap:
                inner["unifications"].append({"id": self.fresh("u"), "nodes": [nid, idmap[nid]]})
        calc["_outer_arguments"] = calc["arguments"]
        calc["arguments"] = [remap_nodes(a, idmap) for a in calc["arguments"]]
        # `mirror_block` copies nodes, steps and conditions but not calculations, and
        # `remap_nodes` rewrites node ids rather than following a reference. So an argument
        # that *names* an AS-bound expression kept pointing at the enclosing block's copy of
        # it, and the bag aggregated the outer row: `MIN((SELECT AVG(outer_alias.x * ?) FROM
        # inner_alias ...))`, which SQLite rejects as a misuse of aggregate. Copy each
        # calculation the arguments reach into the bag, with its own nodes remapped, and
        # point the argument at the copy. The fourth defect of the shape findings 145, 146
        # and 149 found: an aggregate over a bound expression taking the wrong path.
        moved, by_id, repoint = self._mirror_calculations(calc, block, inner, idmap)
        self.mirror_computed_conditions(block, inner, idmap, moved, by_id, repoint)
        # The computed keys, once the copies exist: the bag keeps the rows whose key equals
        # the outer row's. `repoint` follows a calculation the expression names to its copy,
        # the way an argument is followed.
        for key in key_exprs:
            inner["conditions"].append({"kind": "compare", "op": "=", "left": key,
                                        "right": repoint(remap_nodes(key, idmap))})
        calc["_group"] = keys                     # [] for an ungrouped one: no MIN, no GROUP BY
        calc["aggregation"]["context"] = "universal"
        calc["_block"] = inner
        return True

    def _mirror_calculations(self, calc, outer, inner, idmap):
        """Copy into `inner` every calculation the arguments name, transitively."""
        by_id = {c["id"]: c for c in outer.get("calculations", [])}
        moved: dict = {}

        def copy(cid):
            if cid in moved:
                return moved[cid]
            source = by_id.get(cid)
            if source is None:
                return cid                    # not this block's: leave it alone
            fresh = dict(source)
            # The id is reserved before recursing, which is what guards a cycle; the *append*
            # waits until the arguments have been repointed, so anything this calculation
            # reads lands in the list ahead of it. The emitter renders a block's calculations
            # in order, so a dependent copied in first met "a computed value that is not in
            # scope" -- the enclosing block gets this right by construction and the bag did
            # not. `(pr * (ct - 25))` grouped is the shape that exposes it: the inner
            # subtraction is a calculation of its own.
            fresh["id"] = moved[cid] = self.fresh("c")
            fresh["arguments"] = [repoint(remap_nodes(a, idmap))
                                  for a in source.get("arguments", [])]
            inner.setdefault("calculations", []).append(fresh)
            return fresh["id"]

        def repoint(thing):
            if isinstance(thing, dict):
                if thing.get("kind") == "calculation":
                    return dict(thing, calculation=copy(thing["calculation"]))
                return {k: repoint(v) for k, v in thing.items()}
            if isinstance(thing, list):
                return [repoint(v) for v in thing]
            return thing

        calc["arguments"] = [repoint(a) for a in calc["arguments"]]
        return moved, by_id, repoint

    def mirror_computed_conditions(self, outer, inner, idmap, moved, by_id, repoint):
        """Carry into the bag the conditions `mirror_block` had to skip.

        It skips any condition naming a calculation, because the calculation lived in the
        enclosing block and copying the condition would have pointed at something outside.
        That was right while the calculations stayed outside -- and wrong the moment
        `_mirror_calculations` began copying them in. The bag then filtered on nothing:
        `WHERE h > 0.9` with `THE AVERAGE h GROUPED BY tm` averaged *every* reading, and
        returned a figure below the threshold its own filter enforces. A writer caught it by
        noticing that is impossible; before the copies existed the same shape refused to
        compile, so this was a loud failure turned silent.

        An aggregate is still left outside. Copying a condition that names one would pull a
        second aggregate into the bag and recurse, which is what the original skip was also
        guarding.
        """
        def aggregates(thing):
            found = []

            def walk(x):
                if isinstance(x, dict):
                    if x.get("kind") == "calculation":
                        c = by_id.get(x["calculation"])
                        if c is not None and c.get("aggregation"):
                            found.append(True)
                    for v in x.values():
                        walk(v)
                elif isinstance(x, list):
                    for v in x:
                        walk(v)
            walk(thing)
            return bool(found)

        for cond in outer.get("conditions", []):
            if not self._names_calculation(cond) or aggregates(cond):
                continue
            inner["conditions"].append(repoint(remap_nodes(cond, idmap)))

    def ground_aggregate(self, inner, outer, it, ordering=(), extra=()):
        """Give an ungrouped aggregate a bag of its own to range over.

        `THE AVERAGE (k - a)` aggregates an expression over variables the *enclosing* block
        bound, so lowering it walks no path and the inner block ends up with no nodes. The
        emitter then produced `(SELECT AVG(outer_alias.x - outer_alias.y))` -- a subquery with
        no FROM, aggregating the enclosing row. SQLite rejects that outright ("misuse of
        aggregate"), so it failed loudly rather than silently, but it failed.

        Without GROUPED BY the aggregate is uncorrelated: it ranges over the bag the enclosing
        block derives. So mirror that derivation into the inner block under fresh ids and
        point the argument at the copies. Conditions come too -- "the average difference for
        locally funded schools" has to keep the funding-type filter or it averages the wrong
        population.

        Nothing to do when the path walked somewhere of its own, which is the common case.
        """
        own = {n["id"] for n in inner["nodes"]}
        also = [v for v, _ in ordering] + list(extra)
        wanted = {nid for nid in (self._nodes_named(inner["calculations"])
                                  | self._nodes_named(it) | self._nodes_named(also))
                  if nid not in own}
        if not wanted:
            return it, ordering, extra

        idmap = self.mirror_block(outer, inner)
        inner["calculations"] = [remap_nodes(c, idmap) for c in inner["calculations"]]
        it = idmap.get(it, it) if isinstance(it, str) else remap_nodes(it, idmap)
        ordering = [(remap_nodes(v, idmap), d) for v, d in ordering]
        extra = [remap_nodes(x, idmap) for x in extra]
        return it, ordering, extra

    @staticmethod
    def _nodes_named(thing):
        """Every node id `thing` mentions, at any depth."""
        found = set()

        def walk(x, top=True):
            if isinstance(x, dict):
                if x.get("kind") == "node":
                    found.add(x["node"])
                elif x.get("kind") == "calculation":
                    return                  # a calculation ref names no node
                for v in x.values():
                    walk(v, False)
            elif isinstance(x, list):
                for v in x:
                    walk(v, False)
            elif isinstance(x, str) and top:
                found.add(x)                # a bare node id
        walk(thing)
        return found

    @staticmethod
    def _names_calculation(thing):
        found = []

        def walk(x):
            if isinstance(x, dict):
                if x.get("kind") == "calculation":
                    found.append(True)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(thing)
        return bool(found)

    def scalar(self, block, ast) -> dict:
        """Section 6.3's f(P1..Pn). The result is a Value of kind `calculation`, not a node:
        a calculation is not an instance of anything, so it has no place in `nodes`."""
        calc = {"id": self.fresh("calc"), "function": self.function_id(ast),
                "arguments": [self.scalar_value(block, a) for a in self.scalar_args(ast)]}
        block["calculations"].append(calc)
        return {"kind": "calculation", "calculation": calc["id"]}

    @staticmethod
    def scalar_args(ast):
        return [ast.left, ast.right] if isinstance(ast, cq.Arith) else ast.args

    def is_boolean(self, call) -> bool:
        """Is this call to a function the model marks `isBoolean` (model.md §3)?"""
        fid = self.function_id(call)
        spec = next((f for f in self.lex.model.get("functions", []) if f["id"] == fid), None)
        return bool(spec and spec.get("isBoolean"))

    def function_id(self, ast) -> str:
        """The `fn.` id a call resolves to, matching the model's spelling.

        The call is casefolded because ConQuer is not case-sensitive about names, and the
        model's ids are not: `fn.castNumber`, `fn.castInteger` and `fn.jsonPath` are camel.
        Folding one side only meant `castNumber(x)` looked for `fn.castnumber` and was told
        the model has no such function -- while the model was carrying it, in every model
        the reverse engineer has ever built. The two casts were unreachable, which is what
        text like `'104 days'` needs to become a number.
        """
        name = ast.op if isinstance(ast, cq.Arith) else ast.name.casefold()
        declared = self.lex.model.get("functions")
        if not declared:
            return "fn." + name
        exact = "fn." + name
        for f in declared:
            if f["id"] == exact or f["id"].casefold() == exact.casefold():
                return f["id"]
        raise ParseError("no function %r in this model; model.md §3 keeps the function "
                         "table as model data, so add it there" % name)

    def scalar_value(self, block, ast) -> dict:
        if isinstance(ast, cq.Constant):
            return {"kind": "constant",
                    "dataType": {"name": "numeric" if ast.numeric else "text"},
                    "lexical": ast.lexical}
        if isinstance(ast, (cq.Arith, cq.Call)):
            return self.scalar(block, ast)
        if isinstance(ast, cq.Conditional):
            return {"kind": "conditional",
                    "condition": self.lower_condition(block, ast.condition, None),
                    "then": self.scalar_value(block, ast.then),
                    "else": self.scalar_value(block, ast.otherwise)}
        _, t = self.lower(block, ast)
        return as_value(t)

    def lower_condition(self, block, cond, head):
        if isinstance(cond, cq.Logical):
            return {"kind": "logical", "op": cond.op,
                    "operands": [self.lower_condition(block, o, head) for o in cond.operands]}
        if isinstance(cond, cq.Not):
            return {"kind": "not", "operand": self.lower_condition(block, cond.operand, head)}
        if isinstance(cond, cq.Call):
            # A boolean function used as a condition -- model.md §4.6's `call` condition,
            # `isBoolean` on the function. `starts_with(n, 'A')`, `like(x, p)`. The
            # arguments are scalar values; the function's SQL template does the rest.
            fid = self.function_id(cond)
            spec = next((f for f in self.lex.model.get("functions", []) if f["id"] == fid), None)
            if spec is not None and not spec.get("isBoolean"):
                raise ParseError("%s is not a boolean function, so it cannot stand as a "
                                 "condition on its own; compare its value to something"
                                 % cond.name)
            return {"kind": "call", "function": fid,
                    "arguments": [self.scalar_value(block, a) for a in cond.args]}
        if isinstance(cond, cq.Some):
            # C[Some(P)] = P is non-empty (section 6.4). Nothing ties P's head to the
            # enclosing path: correlation happens only through variables P names, such as
            # a Type: !x denotation. Unifying the heads here silently ANDs in a join that
            # the query never asked for.
            sub = self.new_block()
            self.lower(sub, cond.path)
            return {"kind": "exists", "block": sub}
        if isinstance(cond, cq.Compare):
            left = self.value_of(block, cond.left, head)
            right = self.value_of(block, cond.right, head, like=left)
            return self.compare_condition(cond.op, left, right)
        if isinstance(cond, cq.SetCompare):
            # lower_set_compare appends to block["conditions"]; here the caller wants the
            # condition itself, so take back the one it just added.
            self.lower_set_compare(block, cond, head)
            return block["conditions"].pop()
        if isinstance(cond, (cq.Seq, cq.TypeSpec, cq.Binary, cq.Distinct,
                             cq.SubExpr, cq.VarRef, cq.ImplicitHead)):
            # A bare path used as a condition asserts the path is non-empty -- the same
            # reading as SOME, but correlated to the head the WHERE hangs off. The parser
            # accepts this form (parse_condition_atom falls through to parse_fr_level), so
            # refusing to lower it made `WHERE Employee has Department: 'ENG'` a hard error.
            sub = self.new_block()
            h2, _ = self.lower(sub, cond, head)
            if head is not None:
                self.unify(sub, head, h2)
            return {"kind": "exists", "block": sub}
        raise ParseError("cannot lower condition %s" % type(cond).__name__)

    def value_of(self, block, ast, head, like=None):
        if isinstance(ast, cq.Constant):
            concept = None
            if like and like.get("kind") == "node":
                concept = self.concept_of(like["node"])
            return self.constant_value(ast, concept)
        if isinstance(ast, cq.VarRef):
            return as_value(self.vars[ast.name])
        if isinstance(ast, cq.TypeSpec) and ast.var and ast.var in self.vars:
            return as_value(self.vars[ast.var])
        _, t = self.lower(block, ast, head)
        return as_value(t)


def define(model: dict, name: str, source: str, lexicon) -> dict:
    """`DEFINE <Name> ::= <query>`: a §6.11 derivation rule scoped to one query.

    conquer-2026.md §11. The trial on Spider 2.0 found that expressibility was not what the
    language was short of -- a five-predicate filter over four joins went in on the second
    attempt -- but *composition*: `local309` wants the top driver and the top constructor of
    each year side by side on a row, and nothing joined two whole grouped results. §6.11
    already names an intermediate and the emitter already renders one as a common table
    expression; what was missing was a way to declare one without editing the model.

    So this adds no new machinery. It reads what the query lists, gives the result a concept
    of the right shape, and hands it to `lower_rules` like any other rule:

        one thing listed     a derived *subtype* of that thing -- `DEFINE BigSpender ::=
                             LIST c FROM Customer c ...`, then `BigSpender has ...`
        two or more          a derived *fact type* read `<Name>` -- `DEFINE TopEarner ::=
                             LIST d, e FROM ...`, then `Department has TopEarner has ...`

    A listed thing that is computed rather than reached gets a value type of its own, because
    the point of an intermediate is often the computed column.
    """
    if name.casefold() in lexicon.by_name:
        raise ParseError("DEFINE %s: the model already has something called that" % name)
    try:
        ast = cq.Parser(lexicon, source).parse_query()
        probe = lower(model, ast, lexicon, prefix="def.%s.p." % name)
    except ParseError as e:
        raise ParseError("in the definition of %s: %s" % (name, e))
    blocks = probe["operands"] if probe.get("nodeType") == "setExpr" else [probe]
    listed = blocks[0].get("projections", [])
    if not listed:
        raise ParseError("DEFINE %s lists nothing, so there is no result to name" % name)

    concept_of = {n["id"]: n["concept"] for b in blocks for n in b.get("nodes", [])}
    players, new_value_types = [], []
    for p in listed:
        src = p["source"]
        cid = concept_of.get(src["node"]) if src.get("kind") == "node" else None
        if cid is None:
            # a computed column: nothing in the model is its type, so give it one
            cid = "vt.%s.%s" % (name, p["name"])
            # No dataType: we do not know one. It was declared `text`, and `constant_value`
            # takes a literal's SQL type from the value type it is compared with, so
            # `... has Taxed TaxedT v WHERE v > 200000` bound 200000 as the string '200000'
            # and SQLite, which orders every number below every string, returned nothing --
            # a silent wrong answer, found by a benchmark writer reading its own row counts
            # (finding 123). Absent, the same function falls back to the literal's own kind,
            # which is the fix already made for an aggregate's result.
            new_value_types.append({"id": cid, "name": "%s%s" % (name, p["name"].capitalize()),
                                    "kind": "value"})
        players.append((p["name"], cid))

    rid = "rule." + name
    if len(players) == 1:
        target = players[0][1]
        # a computed column's type was minted a few lines up, so it is in neither the model
        # nor the index yet; everything else is in the index the caller already holds
        kind = ("value" if any(v["id"] == target for v in new_value_types)
                else lexicon.concepts.get(target, {}).get("kind", "entity"))
        if kind == "fact":
            raise ParseError("DEFINE %s lists one thing and it is a relationship, which has "
                             "no instances to be a subtype of; list what it relates" % name)
        concept = {"id": "%s.%s" % ("et" if kind == "entity" else "vt", name), "name": name,
                   "kind": kind, "supertypes": [target], "derivation": rid}
        rule_kind = "subtype"
    else:
        roles = [{"id": "r.%s.%s" % (name, label), "player": cid, "isMandatory": False}
                 for label, cid in players]
        ids = [r["id"] for r in roles]
        # the defined name is the verb, as rule 10 spells a bound adjective; every role past
        # the second gets a verb part of its own, as an n-ary reading does
        text = "{0} has %s- {1}" % name + "".join(
            " and has %s- {%d}" % (players[i][0], i) for i in range(2, len(players)))
        readings = [{"text": text, "roleSequence": list(ids)}]
        # ... and that is not enough on its own. `reading_slots` yields a verb part only
        # between *adjacent* slots, so the reading above reaches role 2 only by walking
        # through role 1 with the verb "and has b" -- which nobody writes, and which left
        # `has <Name> <SecondValueType>` resolving silently to the FIRST value instead.
        # Six writers on the LiveSQLBench run hit that, and it returned a plausible wrong
        # number rather than refusing. So every value role also gets a reading of its own
        # that puts it next to the head, verbed with its own label.
        for i in range(1, len(players)):
            rest = [k for k in range(1, len(players)) if k != i]
            seq = [ids[0], ids[i]] + [ids[k] for k in rest]
            body = "{0} has %s- {1}" % players[i][0] + "".join(
                " and has %s- {%d}" % (players[k][0], 2 + n) for n, k in enumerate(rest))
            if body != text:
                readings.append({"text": body, "roleSequence": seq})
        concept = {"id": "ft." + name, "name": name, "kind": "fact", "roles": roles,
                   "readings": readings, "derivation": rid}
        rule_kind = "factType"

    model["concepts"].extend(new_value_types)
    model["concepts"].append(concept)
    model.setdefault("derivationRules", []).append(
        {"id": rid, "target": {"kind": rule_kind, "ref": concept["id"]}, "source": source})
    if rule_kind == "factType" and model.get("constraints"):
        # What the definition is keyed by, so the rest of the compiler knows the traversal
        # into it cannot multiply. A fact population is a set, so the whole tuple is always
        # unique; and where the definition narrows to one row per something -- a grouping, or
        # `THE FIRST 1 PER d` -- that something is a key too, which is what makes
        # `Hub has FebFinished` functional rather than something the fan-out check has to be
        # suspicious of.
        roles = [r["id"] for r in concept["roles"]]
        keys = [roles]
        for by in block_key(blocks[0], lexicon) if len(blocks) == 1 else []:
            reached = [r for r, p in zip(roles, listed)
                       if p["source"].get("kind") == "node" and p["source"]["node"] in by]
            if len(reached) == len(by) and reached != roles and reached not in keys:
                keys.insert(0, reached)
        for i, seq in enumerate(keys):
            model["constraints"].append(
                {"id": "uc.%s.%d" % (name, i), "kind": "uniqueness", "roleSequences": [seq]})
    return model


def block_key(block, lexicon=None) -> list:
    """The node sets that determine one row of `block`, narrowest first.

    Two constructs narrow a result to one row per something, and both were being read only
    where they happened to be needed. A grouped aggregate is one row per group; `THE FIRST 1
    PER d` is one row per d -- and only at 1, since `THE FIRST 3 PER d` is three. Returns
    node-id sets, so a caller can map them onto whatever it names those nodes.

    With a lexicon that knows the uniqueness constraints, a third: a block none of whose own
    steps multiplies its rows -- every fact type entered on a unique role -- has one row per
    head. `LIST f, d FROM Frpm f has FrpmEnrollmentK12 k AND ALSO ... k - a AS d` is one row
    per Frpm, and until this was said nothing keyed the fact type it defines, so the value it
    computes had no determinant and the fan-out check could not rate the step into it.
    """
    keys = []
    limit = block.get("_limit") or {}
    per = limit.get("per")
    if isinstance(per, dict) and per.get("kind") == "node" and limit.get("count") == 1:
        keys.append({per["node"]})

    grouped = [c["aggregation"]["context"] for c in block.get("calculations", [])
               if isinstance(c.get("aggregation"), dict)
               and c["aggregation"].get("context") not in (None, "universal")]
    # Every grouped aggregate has to group by the same thing for that thing to be the key,
    # and a context entry that is not a node id is not something a projection can name.
    contexts = {tuple(sorted(map(str, ctx))) for ctx in grouped}
    if len(contexts) == 1 and all(isinstance(x, str) for ctx in grouped for x in ctx):
        keys.append(set(contexts.pop()))
    if lexicon is not None and getattr(lexicon, "uniqueness_known", False):
        steps = block.get("steps", [])
        if all(st["kind"] == "exit" or lexicon.is_functional(st["role"]) for st in steps):
            targets = {st["to"] for st in steps}
            roots = [n["id"] for n in block.get("nodes", []) if n["id"] not in targets]
            if len(roots) == 1 and {roots[0]} not in keys:
                keys.append({roots[0]})
    return keys


def declare_derived_keys(model: dict, lexicon=None) -> int:
    """The uniqueness constraints the model's own derivation rules imply, appended to the
    model and declared to `lexicon`. What `define` does for a query-scoped DEFINE, for the
    rules a model was written with.

    The california_schools semantic model derives `Frpm has EnrollmentDifference` from a rule
    that lists one row per Frpm, and declares no constraint on it; so the lexicon rated the
    step into it as a fan-out, and the value had no determinant for section 14b to use. Only
    fact types with no uniqueness constraint at all are touched, so this is idempotent and a
    model that said what it meant is left alone. A rule that does not parse is skipped here
    and reported by `lower_rules`, which names it.
    """
    lexicon = lexicon or cq.Lexicon(model)
    if not getattr(lexicon, "uniqueness_known", False):
        return 0
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    declared = set(lexicon.uniqueness_of)
    added = 0
    for rule in model.get("derivationRules", []):
        target = rule.get("target") or {}
        if target.get("kind") != "factType" or not isinstance(rule.get("source"), str):
            continue
        fid = target.get("ref")
        fact = concepts.get(fid)
        if fact is None or fid in declared:
            continue
        try:
            ast = cq.Parser(lexicon, rule["source"]).parse_query()
            expr = lower(model, ast, lexicon, prefix=rule["id"] + ".key.")
        except (ParseError, Ambiguous, Judgement):
            continue
        blocks = expr["operands"] if expr.get("nodeType") == "setExpr" else [expr]
        if len(blocks) != 1:
            continue
        listed = blocks[0].get("projections", [])
        roles = [r["id"] for r in fact.get("roles", [])]
        if len(listed) != len(roles):
            continue
        for i, by in enumerate(block_key(blocks[0], lexicon)):
            reached = [r for r, p in zip(roles, listed)
                       if p["source"].get("kind") == "node" and p["source"]["node"] in by]
            if len(reached) == len(by) and reached != roles:
                model.setdefault("constraints", []).append(
                    {"id": "uc.%s.%d" % (rule["id"], i), "kind": "uniqueness",
                     "roleSequences": [reached]})
                lexicon.declare_uniqueness(reached)
                added += 1
    return added


def lower_rules(model: dict, lexicon=None) -> list:
    """Section 6.11: derivation rules, from their ConQuer text to the CCM's QueryExpr.

    `f(p1:a1, ..., pn:an) ::= P` is written as `LIST a1, ..., an FROM P` on a rule whose target
    is the fact type f, one listed thing per role in role order; the lowered projections are
    tagged with the role each populates. `t ::= P` is written as the path P on a rule whose
    target is the subtype t, and its population is the heads of P. Either may mention its own
    target: that is the recursion section 6.9 deferred to SQL-3, which every current SQL has.
    A fact population is a set, so both are distinct.

    Idempotent: a rule that already carries a body is left alone. Returns the rules lowered.
    """
    lexicon = lexicon or cq.Lexicon(model)
    done = []
    concepts = {c["id"]: c for c in model.get("concepts", [])}
    for rule in model.get("derivationRules", []):
        if rule.get("body") is not None or not rule.get("source"):
            continue
        target = concepts.get(rule["target"]["ref"])
        if target is None:
            raise ParseError("derivation rule %s targets %r, which is not a concept"
                             % (rule["id"], rule["target"]["ref"]))
        try:
            ast = cq.Parser(lexicon, rule["source"]).parse_query()
            expr = lower(model, ast, lexicon, prefix=rule["id"] + ".")
        except ParseError as e:
            raise ParseError("in the derivation rule for %s: %s" % (target["name"], e))
        kind = rule["target"]["kind"]
        blocks = expr["operands"] if expr.get("nodeType") == "setExpr" else [expr]
        if kind == "factType":
            roles = target.get("roles", [])
            for b in blocks:
                pj = b.get("projections", [])
                if len(pj) != len(roles):
                    raise ParseError(
                        "the derivation rule for %s lists %d things but the fact type has %d "
                        "roles; list one per role, in role order" % (target["name"], len(pj),
                                                                     len(roles)))
                for p, r in zip(pj, roles):
                    p["target"] = r["id"]
                b["distinct"] = True
        elif kind == "subtype":
            for b in blocks:
                pj = b.get("projections", [])
                if not pj:
                    raise ParseError("the derivation rule for %s lists nothing" % target["name"])
                b["projections"] = pj[:1]           # the heads are the population
                b["distinct"] = True
        else:
            raise ParseError("derivation rule %s: target kind %r is not built" % (rule["id"], kind))
        rule["body"] = expr
        done.append(rule)
    return done


SET_OPS = ("union", "intersect", "except")
SET_WORDS = {"union": "UNITED WITH", "intersect": "INTERSECTED WITH", "except": "MINUS"}


def lower(model: dict, query: cq.Query, lexicon=None, prefix: str = "",
          permissive: bool = False) -> dict:
    """A Query to its QueryExpr: a Block, or -- when the body is one of section 6.2's set
    operations over whole paths -- a SetExpr over blocks (model.md G3)."""
    lo = Lowering(lexicon or cq.Lexicon(model), prefix, permissive)
    if isinstance(query.body, cq.Binary) and query.body.op in SET_OPS:
        return lo.lower_setexpr(query)
    block = lo.new_block()
    lo.lower_query(query, block)
    if lo.suppressed:
        block["_suppressed"] = list(lo.suppressed)
    return block


def _lower_query(self, query, block):
    """Lower a whole Query into `block`: body, projections, ordering, limit. Used for the top
    level and, unchanged, for a `(LIST ...)` standing as a bag (conquer-2026.md §8)."""
    lo = self
    gathered = []
    if query.body is None:
        head = tail = None                  # a row of whole-query scalars: no path at all
    elif isinstance(query.body, cq.Confluence):
        head, tail = lo.lower(block, query.body.base)
        gathered = lo.lower_confluence(block, query.body, head)
    else:
        head, tail = lo.lower(block, query.body)

    if query.projections:
        for name, spec in query.projections:
            node = None
            if query.body is None:
                node, _ = lo.lower(block, spec)     # each item is a whole query of its own
            elif isinstance(spec, cq.Conditional):
                node = lo.scalar_value(block, spec)
            elif isinstance(spec, (cq.Arith, cq.Call)):
                node = lo.scalar(block, spec)
            elif name in lo.vars:
                node = lo.vars[name]
            elif spec is not None and isinstance(spec, cq.TypeSpec):
                found = lo.by_concept.get(spec.concept, [])
                if not found:
                    raise ParseError("%r is not reached by this query, so it cannot be listed"
                                     % name)
                node = found[0]
            else:
                raise ParseError("%r is neither a variable nor a type in this query" % name)
            block["projections"].append({
                "id": lo.fresh("pj"), "name": name, "source": as_value(node)})
    else:
        seen, defaults = [], []
        for label, value in [("head", head), ("tail", tail)] + gathered:
            key = repr(value)
            if key not in seen:
                seen.append(key)
                defaults.append((label, value))
        for label, value in defaults:
            if isinstance(value, dict):
                name = lo.agg_names.get(value.get("calculation"), label)
            else:
                name = lo.lex.concepts.get(lo.concept_of(value), {}).get("name", label)
            block["projections"].append({
                "id": lo.fresh("pj"), "name": name, "source": as_value(value)})

    block["_ordering"] = resolve_ordering(lo, query.ordering, block, head, tail)
    if query.limit is not None:
        block["_limit"] = {"count": query.limit.count, "offset": query.limit.offset}
        if query.limit.ties:
            # Ties are ties *in the sort key*, so there has to be one. `THE FIRST 3 WITH
            # TIES` with nothing ordered would mean "three arbitrary rows and everything
            # arbitrarily equal to them", which is not a question anyone asks.
            if not block["_ordering"]:
                raise ParseError(
                    "WITH TIES needs something to tie on: add ORDERED WITH <key>. Without a "
                    "sort key there is no rank to be equal in, so `THE FIRST %d WITH TIES` "
                    "and `THE FIRST %d` would mean the same thing."
                    % (query.limit.count, query.limit.count))
            block["_limit"]["ties"] = True
        if query.limit.per is not None:
            # the first n WITHIN each value of `per` -- resolved the way a sort key is
            (per_value, _), = resolve_ordering(
                lo, [cq.OrderItem(key=query.limit.per, direction="asc")], block, head, tail)
            block["_limit"]["per"] = per_value
    check_rooted(block, refuse=lo.refuse)
    check_projections(block, refuse=lo.refuse)
    check_window_over_groups(block, refuse=lo.refuse, lex=lo.lex)
    regroup_bag_only(block, lo)
    check_aggregate_locality(block, lo.lex, refuse=lo.refuse, regroup=lo.regroup_grouped)
    note_group_fixed(block, lo.lex)
    return head, tail


def regroup_bag_only(block, lo):
    """A grouped aggregate the dialect can spell only over a derived table is re-lowered
    into a bag of its own, correlated on its keys -- the route finding 117 built for values
    a group repeats, taken here for a different reason. SQLite has no median; the middle of
    a numbered derived table is one (`sqlBagTemplate`), and `THE MEDIAN x GROUPED BY g` in
    place beside GROUP BY has no derived table to number. Regrouped, the bag yields one
    figure per group and the enclosing GROUP BY takes it with MIN, exactly as it does for a
    repeated value. Windowed medians have no such route and are refused with the reason.
    """
    functions = {f["id"]: f for f in lo.lex.model.get("functions", [])}
    for calc in list(block.get("calculations", [])):
        agg = calc.get("aggregation")
        spec = functions.get(calc.get("function"))
        if not isinstance(agg, dict) or calc.get("_block") is not None or not spec:
            continue
        # A DISTINCT aggregate with a second operand -- `THE DISTINCT LIST OF g SEPARATED
        # BY ', '` -- is `group_concat(DISTINCT g, ', ')`, which SQLite refuses ("DISTINCT
        # aggregates must have exactly one argument"). Over a bag the distinct is taken in
        # the derived table and the separator applied outside it, so it goes that way too.
        distinct_pair = agg.get("distinct") and len(calc.get("arguments", [])) > 1
        if not distinct_pair and (not spec.get("sqlBagTemplate") or spec.get("sqlTemplate")):
            continue
        what = ("a DISTINCT %s with a separator" if distinct_pair
                else "%s") % calc["function"].split(".")[-1]
        if agg.get("window"):
            lo.refuse("this dialect spells %s only over a bag, and a WITHIN window is not one. "
                      "Take it GROUPED BY and read it back beside the rows, or in a DEFINE."
                      % what)
        if not isinstance(agg.get("context"), list) or not lo.regroup_grouped(block, calc):
            lo.refuse("this dialect spells %s only over a bag, and this query gives it no "
                      "keys to correlate one on" % what)
    for sub in block.get("subBlocks", []):
        regroup_bag_only(sub, lo)
    for calc in block.get("calculations", []):
        if calc.get("_block") is not None:
            regroup_bag_only(calc["_block"], lo)


class Determination:
    """What the model says fixes what, over a block and the blocks enclosing it.

    Both checks below ask the same question of a block -- given some nodes a group or a
    window holds fixed, what else is fixed, and which steps therefore cannot multiply --
    and each used to answer it with its own copy of the union-find, the reach map and the
    walks. Built once per block: the unifications as a union-find (unified nodes are one
    instance), how each node was reached (`up`, `up_step`), this block's own fan-out steps,
    and which node fills which role of each fact node. The walks read the model's
    uniqueness constraints through `lex.is_functional` and `lex.uniqueness`, which is why
    none of this runs where the model declares none (`lex.uniqueness_known`).
    """

    def __init__(self, block, lex, ancestry=()):
        self.block, self.lex = block, lex
        self.scope = list(ancestry) + [block]
        self._parent: Dict[str, str] = {}
        for b in self.scope:
            for u in b.get("unifications", []):
                for other in u["nodes"][1:]:
                    self.union(u["nodes"][0], other)
        # How each node was reached, over the whole enclosing scope: a sub-block's path
        # starts at one of its parent's nodes, so a chain that stops at the block boundary
        # is not a chain.
        self.up: Dict[str, str] = {}
        self.up_step: Dict[str, dict] = {}
        for b in self.scope:
            for st in b.get("steps", []):
                self.up.setdefault(self.find(st["to"]), self.find(st["from"]))
                self.up_step.setdefault(self.find(st["to"]), st)
        # ...but only this block's own steps multiply this block's own rows. A fan-out
        # inside a sub-block is under an EXISTS, which matches without joining.
        self.own = block.get("steps", [])
        self.fanout = [st for st in self.own
                       if st["kind"] == "enter" and not lex.is_functional(st["role"])]
        # which nodes fill which role of each fact node this block reaches, either way round
        self.fills: Dict[Tuple[str, str], str] = {}
        for st in self.own:
            if st["kind"] == "enter":
                self.fills[(self.find(st["to"]), st["role"])] = self.find(st["from"])
            else:
                self.fills[(self.find(st["from"]), st["role"])] = self.find(st["to"])

    def find(self, x):
        parent = self._parent
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def chain(self, nid):
        """Every node on the way back from `nid` to the head, functional or not."""
        seen, x = set(), self.find(nid)
        while x is not None and x not in seen:
            seen.add(x)
            x = self.up.get(x)
        return seen

    def determinants(self, nid):
        """What the model says fixes this value: the chain back from it through steps that
        are functional -- leaving a fact node, or entering one on a unique role -- and no
        further. `chain` walks to the head regardless, and that put the fanning source in
        the set: `THE SUM OF Employee has Project has ProjectPriority` counted a priority
        once per employee (17, not 9), because Employee was "keyed" by ancestry alone. The
        reference interpreter found it on a generated query (conquer-2026 section 14b)."""
        lex, find, up_step = self.lex, self.find, self.up_step
        seen, x = set(), find(nid)
        st = up_step.get(x)
        seen.add(x)
        if st is not None and st["kind"] == "exit":
            # x plays a role of the fact node above it. That node fixes x, and the object
            # that entered it on a unique role owns the value: Department for a budget,
            # Project for a priority. Assignment, entered from Employee on a non-unique
            # role, owns nothing -- one project has many assignments -- so nothing is keyed
            # and the value stays P's bag. The owner is the *nearest* such node, on purpose:
            # Employee determines its department's budget too (one department each), but
            # "each budget once" means once per department, which is where the reference
            # interpreter and section 14b put it and where `THE SUM OF Employee has
            # Department has DepartmentBudget` = 3,600,000 comes from.
            fact = find(st["from"])
            into = up_step.get(fact)
            if into is not None and into["kind"] == "enter" and lex.is_functional(into["role"]):
                seen.add(fact)
                seen.add(find(into["from"]))
        elif st is not None and lex.is_functional(st["role"]):
            seen.add(find(st["from"]))          # a fact node entered on a unique role
        return seen

    def settled(self, keyed):
        """The fan-out steps whose fact instance the group already pins, and everything that
        follows from them. Run to a fixed point: pinning Assignment pins the Project it
        leads to, which may pin the next one."""
        lex, find = self.lex, self.find
        keyed, accepted = set(keyed), set()
        while True:
            grew = False
            for st in self.fanout:
                if st["id"] in accepted:
                    continue
                node = find(st["to"])
                if not any(all(self.fills.get((node, r)) in keyed for r in seq)
                           for seq in lex.uniqueness(lex.role_owner[st["role"]])):
                    continue
                accepted.add(st["id"])
                keyed.add(node)
                grew = True
            for st in self.own:                  # what a pinned row leads to is pinned too
                if find(st["from"]) in keyed and find(st["to"]) not in keyed \
                        and (st["kind"] == "exit" or lex.is_functional(st["role"])):
                    keyed.add(find(st["to"]))
                    grew = True
            if not grew:
                return keyed, accepted

    def pins(self, nid):
        """What a group key fixes: itself, and -- while the node plays a unique role in the
        fact above it, as an identifier does -- that fact and the object it belongs to.
        `settled` then adds what those lead to functionally. Read strictly, so a department
        code does not pin the employee the path came through (finding 117)."""
        lex, find = self.lex, self.find
        seen, x = set(), find(nid)
        while x is not None and x not in seen:
            seen.add(x)
            st = self.up_step.get(x)
            if st is None or st["kind"] != "exit" or not lex.is_functional(st["role"]):
                break
            fact = find(st["from"])
            seen.add(fact)
            x = self.up.get(fact)
        return seen

    def roots(self):
        find = self.find
        targets = {find(st["to"]) for st in self.block.get("steps", [])}
        return [find(n["id"]) for n in self.block.get("nodes", [])
                if find(n["id"]) not in targets]

    def fixes(self, nodes):
        """Every node the given ones fix, walking this block's steps both ways along the
        ones that cannot fan out: forward, a fact's player is one per role and a functional
        role is entered once; backward, a fact is reached from a player that plays a unique
        role in it, and a player from its fact always. What a window may partition by."""
        lex, find = self.lex, self.find
        reach = {find(n) for n in nodes}
        edges = []
        for st in self.own:
            a, b, functional = find(st["from"]), find(st["to"]), lex.is_functional(st["role"])
            if st["kind"] == "exit" or functional:
                edges.append((a, b))
            if st["kind"] == "enter" or functional:
                edges.append((b, a))
        grew = True
        while grew:
            grew = False
            for a, b in edges:
                if a in reach and b not in reach:
                    reach.add(b)
                    grew = True
        return reach


def note_group_fixed(block, lex, ancestry=()):
    """Record on each block which of its nodes its GROUP BY keys hold fixed, for the emitter.

    SQL's rule is that a selected column is either grouped or aggregated. SQLite does not
    enforce it -- a bare column comes off one arbitrary row of the group, which is right
    exactly when the keys fix it -- and PostgreSQL and DuckDB refuse the statement: "column
    must appear in the GROUP BY clause or be used in an aggregate function". The first
    large-tier answer that listed a fund's name beside a total grouped by its ticker failed
    that way. What the keys fix is constant within a group, so grouping by it as well
    changes no group and satisfies the rule; `Determination.fixes` says what that is, and
    `sql.render` puts its columns into GROUP BY. Runs after `regroup_grouped`, so a
    re-lowered aggregate's keys (`_group`) are read where they will be grouped. Silence in
    the model is not evidence, as ever: with no uniqueness known, nothing is recorded and
    the statement is what it was.
    """
    if not getattr(lex, "uniqueness_known", False):
        return
    keys = set()
    for calc in block.get("calculations", []):
        agg = calc.get("aggregation")
        if not isinstance(agg, dict) or agg.get("window") \
                or calc["function"].rsplit(".", 1)[-1] in WINDOW_ONLY:
            continue                                  # a partition is not a GROUP BY
        if calc.get("_group") is not None:
            context = calc["_group"]
        elif calc.get("_block") is None:
            context = agg.get("context")
        else:
            continue                                  # a bag groups itself, below
        for key in (context if isinstance(context, list) else []):
            # Only a key that IS a node fixes anything. A computed key -- `if(contains(b,
            # 'kep'), 'kepler', 'v') AS g ... GROUPED BY g` -- is a function of the nodes
            # it reads, not the other way round: two bands share one label, and grouping
            # by `b` as well split the two groups into nine. A blind writer found that
            # within the hour of it shipping (finding 162).
            if isinstance(key, str):
                keys.add(key)
            elif isinstance(key, dict) and key.get("kind") == "node":
                keys.add(key["node"])
    if keys:
        d = Determination(block, lex, ancestry)
        reach = d.fixes(keys)
        block["_fixed"] = sorted(n["id"] for n in block.get("nodes", [])
                                 if d.find(n["id"]) in reach)
    scope = tuple(ancestry) + (block,)
    for calc in block.get("calculations", []):
        if calc.get("_block") is not None:
            note_group_fixed(calc["_block"], lex, scope)
    for sub in block.get("subBlocks", []):
        note_group_fixed(sub, lex, scope)


def check_window_over_groups(block, refuse, lex=None):
    """Refuse a window over rows that GROUPED BY has already collapsed.

    `THE RANK OF s WITHIN d AS rk AND ALSO THE AVERAGE s GROUPED BY d AS m WHERE rk = 1`
    reads as "rank the salaries in each department, keep the top one, average it". SQL runs
    the window *after* GROUP BY, over one row per department carrying one arbitrary salary,
    so every rank is 1, the filter keeps every group, and the answer is the plain group
    means -- returned without a word. A LiveSQLBench writer built a median that way and
    got the mean back.

    A window over the *grouped* figure is fine and used: `THE COUNT OF e GROUPED BY d AS c
    AND ALSO THE RANK OF c WITHIN one` ranks the counts, and SQL computes RANK() OVER
    (ORDER BY COUNT(..)) over the groups exactly as written. So the rule is what the window
    reads: its argument and its order must be a group key or a grouped aggregate, or built
    from those. The partition is checked more loosely: WITHIN something the key
    *determines* is correct (`GROUPED BY d` and `WITHIN dep`, the department's code and the
    department, are one partition), so a partition node passes if a group key reaches it
    along functional steps -- which needs the model's uniqueness constraints, so it runs
    only where they are known, as the locality check does.
    """
    calcs = block.get("calculations", [])
    by_id = {c["id"]: c for c in calcs}
    grouped, windows = [], []
    for c in calcs:
        agg = c.get("aggregation")
        if not isinstance(agg, dict) or c.get("_block") is not None:
            continue
        if agg.get("window") or c["function"].rsplit(".", 1)[-1] in WINDOW_ONLY:
            windows.append(c)
        elif isinstance(agg.get("context"), list):
            grouped.append(c)

    def names_window(thing, seen=()):
        """Does this value read another window of the same block, at any depth?"""
        if isinstance(thing, dict) and thing.get("kind") == "calculation":
            cid = thing.get("calculation")
            if cid in seen or cid not in by_id:
                return False
            if by_id[cid] in windows:
                return True
            return names_window(by_id[cid].get("arguments", []), seen + (cid,))
        if isinstance(thing, dict):
            return any(names_window(v, seen) for v in thing.values()
                       if isinstance(v, (dict, list)))
        if isinstance(thing, list):
            return any(names_window(v, seen) for v in thing)
        return False

    for w in windows:
        # A window over a window. SQL computes every window of a SELECT over the same rows
        # at once, so `LAG(LAG(x) OVER (..)) OVER (..)` is a "misuse of window function" at
        # the database -- after the query looked fine. A crypto writer nested THE PREVIOUS
        # to reach two rows back and found out at run time; the twenty-four-deep DEFINE
        # chain in finding 152 is the same want. The definition is the spelling that works:
        # its window is computed in a derived table and the query's window runs over that.
        agg = w["aggregation"]
        reads = list(w.get("arguments", [])) + [v for v, _ in agg.get("order", [])] \
            + [k for k in (agg.get("context") or []) if isinstance(k, dict)]
        if any(names_window(r) for r in reads):
            func = w["function"].rsplit(".", 1)[-1]
            word = WINDOW_WORDS.get(func, "THE %s ... WITHIN" % func.upper())
            refuse("%s here reads a value another WITHIN computes, and SQL computes every "
                   "window of one query over the same rows at once -- a window cannot read "
                   "another. Name the inner one in a DEFINE and window over that: "
                   "`DEFINE Prev ::= LIST k, p FROM ... THE PREVIOUS x BY k WITHIN g AS p` "
                   "and then `... has Prev PrevP p AND ALSO THE PREVIOUS p BY k WITHIN g`."
                   % word)
    if not grouped or not windows:
        return
    fixed_nodes, fixed_calcs = set(), {c["id"] for c in grouped}
    for c in grouped:
        for key in c["aggregation"]["context"]:
            if isinstance(key, dict) and key.get("kind") == "calculation":
                fixed_calcs.add(key["calculation"])
            else:
                fixed_nodes |= {key} if isinstance(key, str) else Lowering._nodes_named(key)

    def row_level(thing, seen=()):
        """A node the group did not fix, reached by this value; None if there is none."""
        if isinstance(thing, str):
            return None if thing in fixed_nodes else thing
        if not isinstance(thing, dict):
            return None
        if thing.get("kind") == "node":
            return None if thing["node"] in fixed_nodes else thing["node"]
        if thing.get("kind") == "calculation":
            cid = thing.get("calculation")
            if cid in fixed_calcs or cid in seen or cid not in by_id:
                return None
            return row_level(by_id[cid].get("arguments", []), seen + (cid,))
        for v in thing.values():
            if isinstance(v, (dict, list)):
                hit = row_level(v, seen)
                if hit:
                    return hit
        return None

    known = getattr(lex, "uniqueness_known", False) if lex is not None else False
    det = Determination(block, lex) if known else None
    reach, find = (det.fixes(fixed_nodes), det.find) if known else (set(), None)
    for w in windows:
        agg = w["aggregation"]
        if known:
            for key in agg.get("context") or []:
                nid = key if isinstance(key, str) else None
                if isinstance(key, dict) and key.get("kind") == "node":
                    nid = key["node"]
                if nid is not None and find(nid) not in reach:
                    func = w["function"].rsplit(".", 1)[-1]
                    refuse("%s ... WITHIN partitions the rows by a value that GROUPED BY in "
                           "the same query does not fix, so the window would partition one "
                           "arbitrary row of each group. Partition by a group key, or by "
                           "something a key determines, or put the window in a DEFINE."
                           % WINDOW_WORDS.get(func, "THE %s OF" % func.upper()))
        reads = list(w.get("arguments", [])) + [v for v, _ in agg.get("order", [])]
        for thing in reads:
            if isinstance(thing, list):
                thing = {"kind": "list", "items": thing}
            if row_level(thing) is not None:
                func = w["function"].rsplit(".", 1)[-1]
                word = WINDOW_WORDS.get(func, "THE %s ... WITHIN" % func.upper())
                refuse("%s reads rows, and GROUPED BY in the same query has collapsed them "
                       "to one per group: the window would run over one arbitrary row of "
                       "each group and rank or lag nothing. Either window a grouped value "
                       "(`THE COUNT OF e GROUPED BY d AS c AND ALSO THE RANK OF c WITHIN "
                       "one`), or put the row-level window and its filter in a DEFINE and "
                       "aggregate over that (primer section 9f)." % word)


Lowering.lower_query = _lower_query


def check_projections(block, refuse):
    """A LIST may only project something every answer row actually has.

    `OR OTHERWISE` folds its operands into sub-blocks, and a name bound inside one of them is
    bound in *that* alternative only: `LIST n, g FROM Employee has EmployeeName n AND ALSO has
    EmployeeGender g OR OTHERWISE has EmployeeSalary: 1` asks for a gender on rows that got in
    by their salary and never touched the gender fact. The emitter met this as a node with no
    anchor and raised `node n10 has no anchor`, which tells the author nothing; a card_games
    writer spent several attempts rewriting around it by De Morgan before finding a form that
    compiled. Without the union the same names stay in the outer block, so an escaped
    projection is always this.
    """
    inside = {}
    for sub in block.get("subBlocks", []):
        for n in sub.get("nodes", []):
            inside.setdefault(n["id"], sub)
    own = {n["id"] for n in block.get("nodes", [])}
    for p in block.get("projections", []):
        src = p.get("source") or {}
        if src.get("kind") != "node" or src.get("node") in own:
            continue
        sub = inside.get(src["node"])
        if sub is None:
            continue                       # not an alternative branch; leave it to the emitter
        refuse(
            "`%s` is bound inside one alternative of this query, so the rows that came in "
            "through another alternative have no %s to show. Project only what every answer "
            "has, or ask the alternatives as separate queries." % (p.get("name"), p.get("name")))


def check_rooted(block, refuse, ancestry=()):
    """Every node a block declares must be reached by something in it (model.md §7.2).

    A node nothing reaches is a second, independent range over its concept, and the emitter
    renders that faithfully -- as a cartesian product. `LIST e, c FROM Atom has AtomElement e
    AND ALSO THE COUNT OF Atom GROUPED BY e AS c` counted (atoms with element e) × (all
    atoms) and said nothing, because the author wrote `Atom` where they meant a variable
    bound to the one already in hand.

    `model/validate.py` has always rejected this; the compiler was emitting SQL for IR its own
    validator failed. The rule is enforced here so the refusal arrives with the query text
    rather than at the far end of a pipeline. Aggregate blocks hang off a calculation's
    `_block`, which the validator does not walk either: a lone node is the whole point of
    `THE COUNT OF Employee`, so they are left alone here too.
    """
    visible = {n["id"] for b in ancestry for n in b.get("nodes", [])}
    own = {n["id"] for n in block.get("nodes", [])}
    bound = set(visible)
    for st in block.get("steps", []):
        bound.update((st["from"], st["to"]))
    for u in block.get("unifications", []):
        bound.update(u["nodes"])
    for inv in block.get("invocations", []):
        bound.update(r["node"] for r in inv.get("results", []))
    # a filter sub-block or a nested condition block that continues from one of this block's
    # nodes binds it: `School [has SchoolVirtual: 'F']` is the virtual schools, one range
    for sub in block.get("subBlocks", []):
        bound.update(st["from"] for st in sub.get("steps", []))
        for u in sub.get("unifications", []):
            bound.update(u["nodes"])
    for cond in block.get("conditions", []):
        for nested in nested_blocks(cond):
            bound.update(st["from"] for st in nested.get("steps", []))
            for u in nested.get("unifications", []):
                bound.update(u["nodes"])

    for n in block.get("nodes", []):
        if n["id"] not in bound and len(own) > 1:
            # one lone node is one range -- `LIST e FROM Employee e` is every Employee,
            # multiplied by nothing; it is a second unjoined node that multiplies
            concept = n["concept"].split(".")[-1]
            refuse(
                "%s is named here but joined to nothing, so it ranges over every %s "
                "independently and multiplies the answer. Bind a variable to the one you "
                "mean and use that -- `%s x ... THE COUNT OF x` rather than "
                "`... THE COUNT OF %s`" % (concept, concept, concept, concept))

    inner = list(ancestry) + [block]
    for sub in block.get("subBlocks", []):
        check_rooted(sub, refuse, inner)
    for cond in block.get("conditions", []):
        for nested in nested_blocks(cond):
            check_rooted(nested, refuse, inner)


# min and max are unchanged by repetition -- the largest of a bag is the largest of that bag
# with duplicates in it -- so a path that fans out cannot make them wrong. Every other group
# function counts each duplicate.
FANOUT_SAFE = {"min", "max"}
# The row-relative functions: a window and nothing else, whatever the aggregation says.
WINDOW_ONLY = ("rank", "percent_rank", "lag")
WINDOW_WORDS = {"rank": "THE RANK OF", "percent_rank": "THE PERCENT RANK OF",
                "lag": "THE PREVIOUS"}


def check_aggregate_locality(block, lex, refuse, ancestry=(), ranging=(), regroup=None):
    """Refuse an aggregate over a value the block repeats. Malloy calls this aggregate
    locality; ORM calls the information it needs a uniqueness constraint.

    A block is one flat join, so its rows are one per combination of everything it reaches.
    A grouped aggregate is correct exactly when the block has one row per (what is
    aggregated, what it is grouped by) -- then every value is added once. When a path
    branches off that and fans out -- `Department d has Budget b AND ALSO d is of Employee
    e` -- the budget is on the row once per employee and SUM adds it that many times. The
    query is well formed, the SQL runs, and the number is wrong by a factor nobody can see.
    This is the fan trap, and it is the one class of error a conceptual model already holds
    the answer to.

    Reading the constraints as ORM means them matters, and reading only the single-role ones
    is not enough. `Employee x has Project has ProjectName v ... THE COUNT OF x GROUPED BY v`
    walks a many-to-many, so entering Assignment fans out -- but Assignment carries a
    uniqueness constraint spanning *both* its roles, so for one (employee, project) there is
    one row, and the count is right. A fan-out is harmless when some uniqueness constraint of
    the fact type it reaches is satisfied by values the group already fixes; the test below
    is that, run to a fixed point, because a fact type pinned that way pins what it leads to.

    The refusal is not a dead end, because ConQuer already has the operator that fixes it.
    §6.4's `[...]` is Ds(Fr(Q)), a semijoin: it requires the fact without joining to it, so
    it cannot multiply. `... AND ALSO [d is of Employee]` sums each budget once.

    Silence in the model is not evidence: a model that declares no uniqueness constraint at
    all has not said that anything is many-to-one, so the check does not run.
    """
    if not getattr(lex, "uniqueness_known", False):
        return

    d = Determination(block, lex, ancestry)
    scope, find, fanout = d.scope, d.find, d.fanout
    chain, determinants, settled, pins, roots_of = (
        d.chain, d.determinants, d.settled, d.pins, d.roots)

    def test(calc, value_only=False):
        """Is this aggregate computed over rows *this* block multiplies?

        `value_only` guards the case where an enclosing block's aggregate ranges over this
        one. Measured over the 1,186 recorded pilot queries, refusing a COUNT in that position
        rejects 20 answers that were right for every 5 that were wrong -- authors write
        `THE COUNT OF Account [is of Loan ...]` meaning "accounts with any such loan", and the
        data usually obliges. Summing a *value* that fans out has no such reading: it is
        arithmetically wrong whenever the fan-out has degree above one, and there it was 1 for
        1. So the rule is counting a fanned head is the author's business; summing a fanned
        value is a defect.
        """
        agg = calc["aggregation"]
        if not isinstance(agg, dict):
            return
        if value_only and calc["function"].rsplit(".", 1)[-1] == "count":
            # Counting a fanned head is genuinely ambiguous and we cannot resolve it for the
            # author. Refusing it rejected 20 right answers for 5 wrong (finding 78);
            # deduplicating it scored net -1 over the recorded corpus, because `card_games`
            # q416's evidence wants the joined rows and the fan-out is the intent. `DISTINCT`
            # is how the author says which they mean. A summed *value* has no such ambiguity.
            return

        func = calc["function"].rsplit(".", 1)[-1]
        if func in FANOUT_SAFE or agg.get("distinct"):
            return
        # what one row of the answer holds fixed: the value aggregated, and the group keys
        keyed = set()
        context = agg.get("context")
        for thing in calc.get("arguments", []):
            for nid in ({thing} if isinstance(thing, str) else Lowering._nodes_named(thing)):
                det = determinants(nid)
                # Nothing the model knows fixes this value (a fact type with no uniqueness
                # constraint, a derived one the lexicon cannot rate): then it is P's bag, one
                # instance per row, and the row is what keys it. Deduplicating on the value
                # alone would be DISTINCT SUM, which nobody asked for.
                keyed |= det if len(det) > 1 else chain(nid)
        # The keys keep the whole chain they were reached by. That over-states what a group
        # fixes -- a department code does not pin the employee the path came through -- and
        # the reference interpreter shows the consequence on `THE SUM OF p GROUPED BY d`
        # over a many-to-many (tests/test_reference.py GAPS, finding 112). Reading the keys
        # strictly refuses that query instead, which is no better until the emitter can
        # deduplicate under GROUP BY; until then this is the recorded behaviour.
        for thing in (context if isinstance(context, list) else []):
            for nid in ({thing} if isinstance(thing, str) else Lowering._nodes_named(thing)):
                keyed |= chain(nid)
        if not keyed:
            return                                    # nothing walked: no rows to repeat
        keyed, accepted = settled(keyed)
        offender = next((st for st in fanout if st["id"] not in accepted
                         and find(st["to"]) not in keyed), None)
        if offender is None and value_only:
            # No step fans out, but the head itself may: `THE SUM OF Employee has Department
            # has DepartmentBudget` walks many-to-one twice and puts each budget on a row
            # per employee -- the same relation as the fan-out case below, entered from the
            # other end, and section 14b has no direction. The head repeats the value
            # whenever what determines the value does not determine the head.
            roots = [find(n["id"]) for n in block.get("nodes", [])
                     if find(n["id"]) not in {find(st["to"]) for st in block.get("steps", [])}]
            if any(r not in keyed for r in roots):
                agg["dedupe"] = sorted(keyed)
            return
        context = agg.get("context")
        # WITHIN reports the group's figure beside every row and the row-relative functions
        # order a window; neither is a bag to re-lower. They keep the reading below.
        windowed = agg.get("window") or func in WINDOW_ONLY
        keys = context if isinstance(context, list) else []
        if (keys or context == "universal") and func not in ("count",) and not value_only \
                and not windowed and calc.get("_block") is None:
            # A grouped value aggregate, read with the keys taken strictly (finding 117):
            # what a key pins is what it identifies and what that leads to, nothing above it.
            # An ungrouped aggregate beside the rows is the same with no keys at all.
            first = _first_node(calc.get("arguments", []), block.get("calculations"))
            det = determinants(first)
            det = det if len(det) > 1 else chain(first)
            pinned = set()
            for key in keys:
                for nid in ({key} if isinstance(key, str) else Lowering._nodes_named(key)):
                    pinned |= pins(nid)
            pinned, _ = settled(pinned)
            # `det` empty means the value depends on nothing this can see -- which is what
            # happens to an expression bound with `AS`, because `_first_node` finds no node
            # in its arguments. `all()` over an empty set is true, so the test below used to
            # pass vacuously and conclude that a value it could not analyse was constant
            # within every group. `THE AVERAGE x GROUPED BY g` over `(s * 2) AS x` compiled
            # to `MIN((salary * 2))`: it ran, returned a plausible number per group, and was
            # the average of nothing. Found by a blind writer on LiveSQLBench, not by a test.
            #
            # Unknown is not constant. An aggregate over a literal would also land here and
            # is the only thing this costs, which is a case nobody writes.
            if det and all(n in pinned for n in det):
                # The keys alone pin what determines the value: every row of a group carries
                # the same one and MIN returns it exactly. `Department has DepartmentBudget b
                # ... is of Employee ... THE SUM OF b GROUPED BY c` is this shape, and it is
                # the common one: a parent's measure reported beside the parent.
                agg["constant_in_group"] = True
                return
            strict, accepted_s = settled(det | pinned)
            repeats = next((st for st in fanout if st["id"] not in accepted_s
                            and find(st["to"]) not in strict), None)
            if repeats is None and all(r in strict for r in roots_of()):
                return                                # nothing repeats within a group
            # The value repeats within a group and the keys do not pin it: aggregate it in
            # a bag of its own, correlated on the keys, where section 14b's deduplication
            # applies -- `THE SUM OF p GROUPED BY d` over a many-to-many adds a priority
            # shared by two employees of one department once (finding 112, closed in 117).
            if regroup is not None and regroup(block, calc):
                check_aggregate_locality(calc["_block"], lex, refuse, tuple(scope),
                                         ranging=(calc,), regroup=regroup)
                return
            if repeats is None and offender is None:
                return
            refuse(_fanout_message(lex, func, (offender or repeats)["role"]))
        if offender is None:
            return
        if value_only:
            # We know the fan-out, and we know what the value is determined by -- `keyed` is
            # exactly that. So compute it rather than decline: the aggregate ranges over the
            # DISTINCT (determinants, value) rows, which counts each value once. Malloy has to
            # do this with symmetric-aggregate arithmetic because Looker emitted one flat
            # statement; we own the whole statement and can simply deduplicate, which is exact
            # and has no precision limit.
            agg["dedupe"] = sorted(keyed)
            return
        refuse(_fanout_message(lex, func, offender["role"]))

    for calc in block.get("calculations", []):
        agg = calc.get("aggregation")
        if not isinstance(agg, dict):
            continue                                  # a scalar calculation repeats no bag
        if calc.get("_block") is not None:
            # An ungrouped aggregate ranges over a bag of its own. The block is checked as a
            # block -- and the aggregate is carried *into* that check, because the fan-out is
            # in there while the SUM is out here, so nothing tested one against the other and
            # `THE SUM OF b IN Department has DepartmentBudget b AND ALSO is of Employee has
            # EmployeeName n` returned each budget once per employee, silently.
            check_aggregate_locality(calc["_block"], lex, refuse, tuple(scope), ranging=(calc,),
                                     regroup=regroup)
            continue
        if fanout or calc.get("aggregation", {}).get("context") not in (None,):
            test(calc)                                # grouped or universal: the head may repeat

    for calc in ranging:                              # an enclosing block's aggregate over this one
        test(calc, value_only=True)                   # even with no fan-out: the head may repeat

    for sub in block.get("subBlocks", []):
        check_aggregate_locality(sub, lex, refuse, tuple(scope), regroup=regroup)
    for cond in block.get("conditions", []):
        for nested in nested_blocks(cond):
            check_aggregate_locality(nested, lex, refuse, tuple(scope))


def _first_node(arguments, calculations=None):
    """The node an aggregate's argument names, if it names one.

    An argument may name another calculation rather than a node -- `(s * 2) AS x` makes the
    multiply a calculation of its own and the aggregate's argument is a reference to it. Not
    following that reference made this return None for every aggregate over a bound
    expression, and None meant "depends on nothing", which the caller read as "constant
    within the group" and compiled to MIN (finding 145).
    """
    by_id = {c["id"]: c for c in (calculations or [])}
    seen = set()

    def look(things):
        for thing in things:
            if isinstance(thing, dict) and thing.get("kind") == "calculation":
                cid = thing.get("calculation")
                if cid in by_id and cid not in seen:
                    seen.add(cid)
                    found = look(by_id[cid].get("arguments", []))
                    if found:
                        return found
                continue
            for nid in ({thing} if isinstance(thing, str) else Lowering._nodes_named(thing)):
                return nid
            # A conditional, a comparison, anything else built out of values: the nodes are
            # nested inside it rather than named at the top. `if(s * 2 > 200000, 1, 0)` is
            # the shape -- a blind writer hit it when one grouped aggregate's `if` repeated
            # another's expression, which makes the two share a node, and the aggregate was
            # re-lowered into a bag whose argument still pointed at the outer block:
            # `SUM()` over an outer column, which SQLite refuses (finding 149).
            # Only the containers: a dict's *values* include its own "kind" string, and a
            # bare string is read as a node id one level up, so recursing into them names
            # `"conditional"` as a node.
            if isinstance(thing, dict):
                found = look([v for v in thing.values() if isinstance(v, (dict, list))])
                if found:
                    return found
            elif isinstance(thing, list):
                found = look([v for v in thing if isinstance(v, (dict, list))])
                if found:
                    return found
        return None

    return look(arguments)


def _fanout_message(lex, func, role) -> str:
    fact = lex.role_owner[role]
    near = lex.concepts.get(lex.player(role), {}).get("name", "it")
    far = next((lex.concepts.get(r["player"], {}).get("name", "them")
                for r in lex.concepts[fact].get("roles", []) if r["id"] != role),
               lex.concepts[fact].get("name", "them"))
    # The bracket only stops the multiplication while it binds no name: a bracket that binds
    # one is a join, not a semijoin, and multiplies exactly as the bare path did. Saying
    # "put it in brackets" without that caveat is advice that fails when followed -- the
    # benchmark writers kept finding it out for themselves, one wasted attempt at a time.
    return ("THE %s OF here is computed over rows this query multiplies: one %s has many %s, "
            "and nothing in the model says otherwise, so the value is counted once per %s "
            "rather than once per %s. Put the multiplying path in brackets and bind nothing "
            "inside them -- `[%s has %s]` matches without joining, so it cannot multiply, but "
            "`[%s has %s x]` binds a name and joins, which multiplies again -- or aggregate "
            "over %s itself."
            % (func.upper(), near, far, far, near, near, far, near, far, far))


def nested_blocks(cond):
    """The blocks a condition nests -- the same set model/validate.py walks."""
    kind = cond.get("kind")
    if kind == "exists":
        yield cond["block"]
    elif kind == "setCompare":
        for side in ("left", "right"):
            if isinstance(cond.get(side), dict) and "block" in cond[side]:
                yield cond[side]["block"]
    elif kind == "not":
        yield from nested_blocks(cond["operand"])
    else:
        for operand in cond.get("operands", []):
            yield from nested_blocks(operand)


def resolve_ordering(lo, items, block, head, tail):
    """Resolve each sort key of section 6.13's Ω to the value it names.

    [P59] binds the v_i to *variables in the descriptor*, and [P57]/[P58] sort on the path's
    hd -- neither has to be a listed column, and SQL is equally happy to order by something
    it does not select. So a key resolves against, in order: the path's two ends (HEAD and
    TAIL), the variables the query binds, and the names of the listed results, which is what
    lets `ORDERED WITH "s * 100"` sort by a computed column.

    A key matching none of those is refused. The emitter used to match written names against
    projection names and silently fall back to the first projection, so `ORDERED WITH TAIL`
    sorted by the head and a typo sorted by whatever was listed first -- both wrong rows, no
    error.
    """
    projected = {p["name"]: p["source"] for p in block.get("projections", [])}
    out = []
    for item in items:
        if item.expr is not None:
            # An ordering over a computed value. The calculation goes in the block like any
            # other; model/validate.py counts `_ordering` as consuming it, so it is not
            # reported as a value nothing uses.
            out.append((lo.scalar(block, item.expr), item.direction))
            continue
        if item.end:
            out.append((as_value(head if item.end == "head" else tail), item.direction))
        elif item.key in lo.vars:
            out.append((as_value(lo.vars[item.key]), item.direction))
        elif item.key in projected:
            out.append((projected[item.key], item.direction))
        else:
            known = sorted(set(lo.vars) | set(projected))
            raise ParseError("cannot sort by %r: it is neither a variable this query binds "
                             "nor one of its results (%s)"
                             % (item.key, ", ".join(known) or "nothing"))
    return out
