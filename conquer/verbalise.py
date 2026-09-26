"""Read a parsed ConQuer-92 query back as English, and report how it was interpreted.

This is NOT an implementation of the report's section 8. Its forty-six rules [V1]-[V46]
define PVerb, a function from a stored path expression back to *ConQuer text* in normalised
form -- [V29] renders GCount as `THE COUNT OF ... GROUPED BY ...` -- the upward arrow of the
report's Figure 1. Nothing here produces ConQuer; it produces English, and its wording ("the
number of", "and also", "(called n)") is its own. An earlier version of this docstring said
"this is that pass". It was not.

What it does share with section 8 is one mechanism, [V14]: a mix-fix predicate is read from
the schema's own readings, and only when that reading is unique in its path-expression
context. That uniqueness test is the compiler's own Ambiguous check, and `step()` gets it by
delegating to `Lowering.resolve_move` rather than by re-deriving it -- so the explanation
cannot resolve a verb differently from the SQL.

It exists in the service of a practical problem the BIRD run exposed: **every failure that
survived was a misreading, not a mis-compilation** -- the wrong column, an ambiguous phrase
resolved the other way, a join path the question did not imply. None of those show up in the
SQL unless you already know the schema. All of them show up here.

Two outputs, from one walk of the AST:

  verbalise(...)   the query as a sentence, built from the schema's own predicate readings
  report(...)      what each name resolved to, what got expanded, and what to check --
                   including facts the query silently requires to exist

The second is the useful one. It is written to be read by whoever wrote the query, human or
otherwise, *before* the SQL runs.
"""

from __future__ import annotations

from typing import List

import lower as lowering
import parser as cq


RISK, CAUTION, NOTE = "risk", "caution", "note"


class Finding:
    """One thing the compiler understood that the author might not have intended.

    `severity` is what makes the report actionable rather than merely readable:
      risk     the query will silently return the wrong rows -- a dropped optional fact,
               an ambiguity resolved by taking the first reading
      caution  worth a look, usually fine -- fan-out under an aggregate, a quantifier
      note     an abbreviation the lowering expanded, recorded so it is not a surprise
    """

    __slots__ = ("severity", "section", "message")

    def __init__(self, severity, section, message):
        self.severity, self.section, self.message = severity, section, message

    def as_dict(self):
        return {"severity": self.severity, "section": self.section, "message": self.message}


class Interpretation:
    """What the compiler understood, in the order a reader wants it."""

    def __init__(self, query=""):
        self.query = query
        self.sentence = []
        self.resolved = []                   # (what was typed, what it resolved to)
        self.findings = []
        self.normalised = None               # section 8's form of the same query, if it lowers

    def note(self, severity, section, message):
        self.findings.append(Finding(severity, section, message))

    def _section(self, name):
        seen, out = set(), []
        for f in self.findings:
            if f.section == name and f.message not in seen:
                seen.add(f.message)
                out.append(f.message)
        return out

    # kept as lists so callers and tests can read a section directly
    expanded = property(lambda self: self._section("expanded"))
    requires = property(lambda self: self._section("requires"))
    checks = property(lambda self: self._section("checks"))

    @property
    def risks(self):
        return [f for f in self.findings if f.severity == RISK]

    def text(self):
        out = " ".join(w for w in self.sentence if w)
        for a, b in ((" ,", ","), ("[ ", "["), (" ]", "]"), ("  ", " ")):
            out = out.replace(a, b)
        return out.strip()

    def as_dict(self):
        return {"query": self.query, "reads_as": self.text(), "normalised": self.normalised,
                "resolved": [{"typed": t, "means": m} for t, m in self.resolved],
                "findings": [f.as_dict() for f in self.findings],
                "risk_count": len(self.risks)}


class Verbaliser:
    def __init__(self, lexicon: cq.Lexicon):
        self.var_concepts = {}
        self.lex = lexicon
        self.resolver = lowering.Lowering(lexicon)
        self.out = Interpretation()

    # -- naming ------------------------------------------------------------

    def cname(self, cid) -> str:
        return self.lex.concepts.get(cid, {}).get("name", cid)

    def reading_for(self, fact_id, from_role, to_role) -> str:
        """The verb part that steps from one role to the other, as the model words it."""
        fact = self.lex.concepts[fact_id]
        for verb, a, b in self.lex.reading_slots(fact):
            if a == from_role and b == to_role:
                return verb
            if a == to_role and b == from_role:
                inv = self.lex.__class__._inverse_of(verb)
                if inv:
                    return inv
        return "is related to"

    # -- the walk ----------------------------------------------------------

    def query(self, q: cq.Query) -> Interpretation:
        if q.body is None:
            # a row of whole-query scalars, each read back on its own
            self.out.sentence.append("List, side by side:")
            for i, (_, spec) in enumerate(q.projections):
                if i:
                    self.out.sentence.append(";")
                self.path(spec, None)
            return self.out
        if q.projections:
            self.out.sentence.append("List")
            self.out.sentence.append(", ".join(n for n, _ in q.projections))
            self.out.sentence.append("for each")
        if isinstance(q.body, cq.Confluence):
            self.path(q.body.base, None)
            shown = []
            for el in q.body.elements:
                what = el.name or self._element_name(el.path)
                trim = []
                for item in el.ordering:
                    trim.append("ordered by %s %s"
                                % (item.key or "it",
                                   "descending" if item.direction == "desc" else "ascending"))
                if el.limit is not None:
                    trim.append("the first %d of them" % el.limit.count)
                shown.append("%s%s%s" % (what, " at %s" % el.via if el.via else "",
                                         " (%s)" % ", ".join(trim) if trim else ""))
            self.out.sentence.append(", also showing " + ", ".join(shown))
            self.out.note(NOTE, "expanded",
                "Confluence (§6.5): the base path is required, what follows EACH; the "
                "gathered values (%s) come back empty where absent, and rows are never "
                "dropped for lacking one. A gathered value the model allows to be many per "
                "row -- an employee's assignments, not their salary -- comes back as a "
                "nested list rather than splitting the row into one per value. That is "
                "LISA-D's definition of confluence; the report flattened it only because "
                "SQL-92 could not return a nested relation." % ", ".join(shown))
        else:
            self.path(q.body, None)
        for item in q.ordering:
            # HEAD and TAIL name the ends of the path rather than a variable, and reading
            # them back as "the first/last thing named" is what lets a user catch the
            # difference between the two before running the query.
            key = {"head": "the first thing named", "tail": "the last thing named"}.get(
                item.end, item.key)
            if key is None and item.expr is not None:      # a computed key: abs(s), k - a
                key = self.scalar_words(item.expr)
            self.out.sentence.append(
                ", ordered by %s %s"
                % (key, "descending" if item.direction == "desc" else "ascending"))
        if q.limit is not None:
            self.limit(q)
        return self.out

    def limit(self, q):
        """Read a limit back, and say what it does not promise.

        A limit is the one construct whose answer depends on an order the query may not have
        pinned down. `THE FIRST 3` over an ordering with ties returns three of the tied rows,
        chosen by the database; over no ordering at all it returns any three. Neither is an
        error and neither is reported by SQL, so it is reported here, before the query runs.
        """
        lim = q.limit
        within = " for each %s" % lim.per if lim.per else ""
        ties = " and everything tied with them" if lim.ties else ""
        if lim.offset:
            self.out.sentence.append(", keeping %d after the first %d%s"
                                     % (lim.count, lim.offset, within))
        else:
            self.out.sentence.append(", keeping the first %d%s%s"
                                     % (lim.count, within, ties))

        if not q.ordering:
            self.out.note(RISK, "checks",
                          "Nothing orders this result, so `THE FIRST %d` keeps whichever %d "
                          "rows the database happens to produce. Add ORDERED WITH to say "
                          "which ones you mean." % (lim.count, lim.count))
        elif not lim.ties:
            # Named the problem and stopped, which is how a caution becomes wallpaper: a
            # blind writer reported it firing "on nearly every top-N query, so it did not
            # help me distinguish the genuine ties". It cannot distinguish them -- that
            # needs the data -- but it can state the two readings and name the spelling of
            # the other one, which turns a shrug into a one-word decision.
            keys = ", ".join(k.key or (k.end or "") for k in q.ordering)
            self.out.note(CAUTION, "checks",
                          "Rows tied on %s are in no defined order, so which of them the "
                          "limit keeps is the database's choice, not the query's. If the "
                          "question means all of the rows that rank within %d rather than "
                          "%d row%s, write THE FIRST %d WITH TIES."
                          % (keys, lim.count, lim.count, "" if lim.count == 1 else "s",
                             lim.count))
            # `LIST id FROM DISTINCT ... ORDERED WITH p ... THE FIRST 4`: the list is distinct
            # over id and ordered by p, which it drops. Which p stands for an id is
            # undefined -- the database keeps an arbitrary one -- so the cut has no defined
            # answer (finding 117; the reference interpreter and SQLite gave different rows).
            shown = {name for name, _ in (q.projections or [])}
            if shown and _mentions_distinct(q.body):
                dropped = [k.key or ("a computed key" if k.expr is not None else k.end or "")
                           for k in q.ordering if k.expr is not None or k.key not in shown]
                if dropped:
                    self.out.note(CAUTION, "checks",
                                  "The list is DISTINCT over %s but ordered by %s, which it "
                                  "drops: which %s stands for a listed row is undefined, so "
                                  "which rows the limit keeps is too. List the ordering key "
                                  "as well, or order by one figure per row -- THE MINIMUM "
                                  "or THE MAXIMUM of it GROUPED BY what you list."
                                  % (", ".join(sorted(shown)), ", ".join(dropped),
                                     dropped[0]))

    def _element_name(self, path):
        spec = path.parts[0] if isinstance(path, cq.Seq) else path
        if isinstance(spec, cq.TypeSpec):
            return self.cname(spec.concept)
        st = spec if isinstance(spec, cq.Step) else (path.parts[-1] if isinstance(path, cq.Seq) else None)
        if isinstance(st, cq.Step) and isinstance(st.target, cq.TypeSpec):
            return self.cname(st.target.concept)
        return "a value"

    def path(self, ast, head_concept):
        """Walk the AST, appending words and recording every resolution. Returns the concept
        the path has reached, so the next verb can be resolved the way the lowering will."""
        if isinstance(ast, cq.TypeSpec):
            name = self.cname(ast.concept)
            kind = self.lex.concepts.get(ast.concept, {}).get("kind")
            if head_concept is None or not self.lex.compatible(head_concept, ast.concept):
                if not (self.out.sentence
                        and self.out.sentence[-1].split()[-1:] in (["each"], ["the"])):
                    self.out.sentence.append("the" if head_concept else "each")
            self.out.sentence.append(name)
            if ast.var:
                self.out.sentence.append("(called %s)" % ast.var)
                self.var_concepts[ast.var] = ast.concept
            if ast.denotation is not None:
                self.denotation(ast, name, kind)
            return ast.concept

        if isinstance(ast, cq.RoleSpec):
            role = self.lex.roles[ast.roles[0]]
            owner = self.cname(self.lex.rel(ast.roles[0]))
            self.out.resolved.append((ast.text, "the %s role of %s, played by %s"
                                      % (role.get("name") or "?", owner,
                                         self.cname(role["player"]))))
            self.out.sentence.append("its %s" % (role.get("name") or "role"))
            return role["player"]

        if isinstance(ast, cq.Constant):
            self.out.sentence.append("'%s'" % ast.lexical)
            return None

        if isinstance(ast, cq.VarRef):
            self.out.sentence.append(ast.name)
            # the variable's type, so a path continuing from it -- `AND ALSO a has
            # AssignmentHours h` -- reads on instead of stopping at "a has" (finding 40)
            return self.var_concepts.get(ast.name)

        if isinstance(ast, cq.ImplicitHead):
            return head_concept

        if isinstance(ast, cq.Seq):
            here = self.path(ast.parts[0], head_concept)
            for part in ast.parts[1:]:
                if isinstance(part, cq.Filter):
                    # A sub-expression tests that a path exists without joining it, which in
                    # English is a relative clause. Printing the brackets instead left ConQuer
                    # syntax sitting in the middle of the sentence, which is what this whole
                    # output exists not to make a reader parse.
                    self.out.sentence.append("that")
                    self.path(part.expr, here)
                    self.out.sentence.append(",")
                    continue
                if part.optional:
                    self.out.sentence.append("optionally")
                here = self.step(part.verb, here, part.target, part.optional)
            return here

        if isinstance(ast, cq.SubExpr):
            here = head_concept
            for i, p in enumerate(ast.parts):
                if i:
                    self.out.sentence.append("and")
                self.path(p, head_concept)
            return here

        if isinstance(ast, cq.Binary):
            words = {"and": "and also", "or": "or otherwise", "butnot": "but not",
                     "union": "united with", "intersect": "intersected with",
                     "except": "minus"}
            if ast.op in ("union", "intersect", "except"):
                # §6.2: two whole paths, each read on its own; the rows of both, of both at
                # once, or of the left less the right. A set, so duplicates go.
                self.out.sentence.append("the rows of")
                self.path(ast.left, None)
                self.out.sentence.append(words[ast.op])
                self.out.sentence.append("the rows of")
                self.path(ast.right, None)
                self.out.note(NOTE, "expanded",
                    "%s is a set operation (§6.2): each side is a separate query listing the "
                    "same number of things, and the result keeps %s. Duplicate rows are "
                    "removed." % (words[ast.op].upper(),
                                  {"union": "the rows of either", "intersect": "only rows "
                                   "in both", "except": "the left's rows that are not in "
                                   "the right"}[ast.op]))
                return None
            if ast.op == "and":
                self.sibling_fanout(ast, head_concept)
            tail = self.path(ast.left, head_concept)
            self.out.sentence.append(words.get(ast.op, ast.op))
            # AND ALSO / OR OTHERWISE / BUT NOT are Fr: the right operand continues from the
            # HEAD, not from where the left operand ended. Passing the tail made every such
            # operand resolve against a value type and fail.
            resume = self.starts_at(ast.left, head_concept)
            self.path(ast.right, resume)
            return resume

        if isinstance(ast, cq.Compare):
            here = self.path(ast.left, head_concept)
            self.out.sentence.append({"=": "is", "<>": "is not", "<": "is less than",
                                      "<=": "is at most", ">": "is greater than",
                                      ">=": "is at least"}.get(ast.op, ast.op))
            self.path(ast.right, here)
            return here

        if isinstance(ast, cq.SetCompare):
            words = {"subset": "which are all among", "superset": "which include all of",
                     "match": "which are exactly", "disjoint": "which share none of",
                     "properSubset": "which are strictly among",
                     "properSuperset": "which strictly include all of"}
            here = self.path(ast.left, head_concept)
            self.out.sentence.append(words.get(ast.op, ast.op))
            self.path(ast.right, head_concept)
            self.out.note(CAUTION, "checks", 
                "The %s comparison is a set test: it holds for a head only when the whole "
                "set on the left stands in that relation to the whole set on the right."
                % words.get(ast.op, ast.op))
            return here

        if isinstance(ast, cq.Where):
            here = self.path(ast.path, head_concept)
            self.out.sentence.append("where")
            self.condition(ast.condition, here)
            return here

        if isinstance(ast, cq.Distinct):
            self.out.sentence.append("the distinct")
            return self.path(ast.path, head_concept)

        if isinstance(ast, cq.Front):
            self.out.sentence.append("only the start of")
            return self.path(ast.path, head_concept)

        if isinstance(ast, cq.Aggregate):
            self.out.sentence.append({"count": "the number of", "sum": "the total",
                                      "min": "the smallest", "max": "the largest",
                                      "avg": "the average"}.get(ast.func, ast.func))
            if ast.distinct:
                self.out.sentence.append("distinct")
            if ast.over:
                # B.2's `<variable> IN`: what is aggregated, then where it comes from
                self.out.sentence.append("%s in" % ast.over)
            was_in_aggregate = getattr(self, "_in_aggregate", False)
            self._in_aggregate = True           # the aggregate's own caution covers fan-out
            try:
                here = self.path(ast.path, head_concept)
            finally:
                self._in_aggregate = was_in_aggregate
            if ast.group_by:
                # A key is a bound name or a computed value -- `GROUPED BY year(d)`,
                # `WITHIN 1` -- and joining the list as strings crashed `--check` on every
                # computed key ever written (two LiveSQLBench writers, on `WITHIN 1`).
                self.out.sentence.append(", %s by " % ("partitioned" if ast.windowed
                                                        else "grouped")
                                         + ", ".join(k if isinstance(k, str)
                                                     else self.scalar_words(k)
                                                     for k in ast.group_by))
            grain = self.cname(here) if here else "the last thing reached"
            self.out.note(CAUTION, "checks",
                "The %s is computed over every row the path reaches. Its grain is %s: one "
                "per row, not one per distinct %s%s. If a step on the way fans out, each "
                "value is counted once per row, not once per instance."
                % (ast.func, grain, grain,
                   "" if ast.distinct else "; THE DISTINCT COUNT OF counts the distinct ones"))
            # conquer-2026.md §9. `THE MAXIMUM Frpm [...]` is the maximum of an entity type,
            # which is the maximum of its identifier -- a CDS code, a string. The compiler did
            # exactly what it was told on BIRD Q12 and returned one; nothing could refuse it,
            # because it is well-formed. It is also almost never what anyone means.
            kind = self.lex.concepts.get(here, {}).get("kind") if here else None
            if ast.func in ("min", "max", "sum", "avg") and not ast.over and kind == "entity":
                name = self.cname(here)
                self.out.note(CAUTION, "checks",
                    "This takes the %s of %s -- an entity type -- which means the %s of its "
                    "identifier. If you meant a value the %s has, name it: `... has "
                    "%sSomething v` and take the %s of v."
                    % (ast.func, name, ast.func, name, name, ast.func))
            return here

        if isinstance(ast, cq.Named):
            # `... AS n`: say the thing, then what it is called, the way a bound variable is
            here = self.path(ast.path, head_concept)
            self.out.sentence.append("(called %s)" % ast.name)
            return here

        if isinstance(ast, (cq.Arith, cq.Call, cq.Conditional)):
            self.out.sentence.append(self.scalar_words(ast))
            return head_concept

        if isinstance(ast, cq.SubQuery):
            self.out.sentence.append("(")
            sub = Verbaliser(self.lex).query(ast.query)
            self.out.sentence.append(" ".join(sub.sentence).strip())
            self.out.sentence.append(")")
            self.out.findings.extend(sub.findings)
            return head_concept

        self.out.sentence.append("...")
        return head_concept

    _OPS = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}

    def scalar_words(self, ast) -> str:
        """A scalar expression, read back the way it was written."""
        if isinstance(ast, cq.Arith):
            return "%s %s %s" % (self.scalar_words(ast.left), self._OPS.get(ast.op, ast.op),
                                 self.scalar_words(ast.right))
        if isinstance(ast, cq.Call):
            if ast.name.casefold() == "negate" and len(ast.args) == 1:
                return "-" + self.scalar_words(ast.args[0])
            return "%s(%s)" % (ast.name, ", ".join(self.scalar_words(a) for a in ast.args))
        if isinstance(ast, cq.Conditional):
            return "if %s then %s else %s" % (self.condition_words(ast.condition),
                                              self.scalar_words(ast.then),
                                              self.scalar_words(ast.otherwise))
        if isinstance(ast, cq.Constant):
            return ast.lexical if ast.numeric else repr(ast.lexical)
        if isinstance(ast, cq.VarRef):
            return ast.name
        if isinstance(ast, cq.TypeSpec):
            return ast.var or self.cname(ast.concept)
        return "..."

    def condition_words(self, cond) -> str:
        if isinstance(cond, cq.Compare):
            return "%s %s %s" % (self.scalar_words(cond.left), cond.op,
                                 self.scalar_words(cond.right))
        if isinstance(cond, cq.Logical):
            return (" %s " % cond.op).join(self.condition_words(o) for o in cond.operands)
        if isinstance(cond, cq.Not):
            return "not " + self.condition_words(cond.operand)
        return "..."

    def starts_at(self, ast, fallback):
        """The concept a path begins from, which is what an Fr operand resumes at."""
        if isinstance(ast, cq.TypeSpec):
            return ast.concept
        if isinstance(ast, cq.Seq):
            return self.starts_at(ast.parts[0], fallback)
        if isinstance(ast, (cq.Distinct, cq.Front, cq.Named)):
            return self.starts_at(ast.path, fallback)
        if isinstance(ast, (cq.Binary, cq.Compare, cq.SetCompare)):
            return self.starts_at(ast.left, fallback)
        if isinstance(ast, cq.Where):
            return self.starts_at(ast.path, fallback)
        return fallback

    def sibling_fanout(self, ast, head_concept):
        """Finding 58: the one genuine fan trap in a hundred authoring attempts compiled
        cleanly, because `check_aggregate_locality` guards aggregates and this multiplied a
        *projection* -- two branches from one head, each reaching many per head, listed side
        by side. Every name was paired with every value of the same hero, six-fold, and the
        compiler said nothing. The author caught it by reading the row count.

        A single fanning branch is often the point (the employees of each department). Two
        or more *independent* ones from the same head almost never are: the writer meant one
        value beside another and got their cross product. So this is a caution, at two.
        """
        if getattr(self, "_in_aggregate", False):
            return
        done = self.__dict__.setdefault("_fanout_done", set())
        if id(ast) in done or not getattr(self.lex, "uniqueness_known", False):
            return
        operands, node = [], ast
        while isinstance(node, cq.Binary) and node.op == "and":
            done.add(id(node))
            operands.append(node.right)
            node = node.left
        operands.append(node)
        operands.reverse()
        resume = self.starts_at(node, head_concept)
        if resume is None:
            return
        fanning = []
        for op in operands:
            inner = op.path if isinstance(op, cq.Where) else op
            if not isinstance(inner, cq.Seq):
                continue                             # a bracket, an aggregate, a computed value
            step, last = None, None
            for part in inner.parts:
                if isinstance(part, cq.Step):
                    if step is None:
                        step = part
                    if isinstance(part.target, cq.TypeSpec):
                        last = part.target
                elif step is None and not isinstance(part, (cq.TypeSpec, cq.ImplicitHead)):
                    break                            # starts from a bound name, or a bracket
            if step is None:
                continue
            try:
                kind, from_role, _ = self.resolver.resolve_move(step.verb, resume, step.target)
            except (cq.ParseError, cq.Ambiguous):
                continue
            entered = from_role if kind in ("enter", "enter_exit") else None
            if entered and not self.lex.is_functional(entered):
                # Name the branch by what it reaches, not by its first step: two branches
                # that both begin `has Assignment` are told apart by AssignmentHours and
                # ProjectName, which is also what gets multiplied.
                target = last if last is not None else step.target
                label = self.cname(target.concept) if isinstance(target, cq.TypeSpec) \
                    else step.verb
                if isinstance(step.target, cq.TypeSpec) and target is not step.target:
                    label = "%s (via %s)" % (label, self.cname(step.target.concept))
                fanning.append(label)
        if len(fanning) >= 2:
            head = self.cname(resume)
            self.out.note(CAUTION, "checks",
                "%d branches from %s each reach many per %s: %s. Their rows multiply -- every "
                "%s is paired with every %s of the same %s -- so a LIST here has one row per "
                "combination, not one per %s. If one value belongs beside the other, continue "
                "the second branch from the first (`... has T t AND ALSO t has ...`), or gather "
                "one with THE LIST OF."
                % (len(fanning), head, head, ", ".join("`%s`" % f for f in fanning),
                   fanning[0], fanning[1], head, head))

    def step(self, verb, here, target, optional=False):
        """Resolve one verb by asking the lowering, so the explanation cannot disagree
        with the compilation.

        Reimplementing the candidate search here was a bug: it answered `Employee has
        Assignment` with the wrong fact type, because it did not know about the enter-only
        shape an objectified fact type takes. An explanation that differs from what runs is
        worse than none, so resolution has exactly one implementation and this borrows it.
        """
        if here is None:
            self.out.sentence.append(verb)
            return None

        self.out.sentence.append(verb)
        try:
            kind, from_role, to_role = self.resolver.resolve_move(verb, here, target)
        except cq.Ambiguous as e:
            self.out.note(RISK, "checks", "%s The first reading would be taken." % e)
            self.out.sentence.append("???")
            return None
        except cq.ParseError as e:
            self.out.note(CAUTION, "checks", str(e))
            self.out.sentence.append("???")
            return None

        entered = from_role if kind in ("enter", "enter_exit") else None
        if kind == "enter":
            reached = self.lex.rel(from_role)
            role_name = (self.lex.roles[from_role].get("name") or "").strip()
            how = "the fact type %s itself, entered by its %s role of %s" % (
                self.cname(reached), role_name or "?",
                self.cname(self.lex.roles[from_role]["player"])) if role_name \
                else "the fact type %s itself" % self.cname(reached)
        else:
            reached = self.lex.roles[to_role]["player"]
            how = "the fact type %s, reaching %s" % (
                self.cname(self.lex.rel(to_role)), self.cname(reached))
        self.out.resolved.append(("%s %s" % (self.cname(here), verb), how))

        # Section 6.11: a derived fact type is a rule, and the rule is part of what the
        # query means. Say it, in the form the rule was written in.
        fact_id = self.lex.rel(from_role) if kind == "enter" else self.lex.rel(to_role)
        fact = self.lex.concepts.get(fact_id or "", {})
        if fact.get("derivation"):
            rule = next((r for r in self.lex.model.get("derivationRules", [])
                         if r["id"] == fact["derivation"]), None)
            if rule is not None:
                from model import forml
                self.out.note(NOTE, "expanded", "%s is derived (§6.11): %s" % (
                    self.cname(fact_id), forml.Verbalizer(self.lex).derivation(rule)))

        # Optionality lives on the role the path ENTERS by: reverse engineering puts the
        # column's nullability on the entity's side of an attribute fact, not the value's.
        gate = entered or to_role
        if optional:
            self.out.note(NOTE, "expanded",
                          "OPTIONALLY: rows without the %s fact are kept, with empty values."
                          % self.cname(reached))
        elif gate and not self.lex.roles[gate].get("isMandatory"):
            reached_name = self.cname(reached)
            article = "an" if reached_name[:1].upper() in "AEIOU" else "a"
            self.out.note(RISK, "requires", 
                "%s must actually have %s %s -- rows where it is absent are dropped."
                % (self.cname(here), article, reached_name))

        if target is not None and not isinstance(target, cq.RoleSpec):
            self.path(target, reached)
        return reached

    def denotation(self, ast, name, kind):
        d = ast.denotation
        if isinstance(d, tuple) and d and d[0] == "!":
            self.out.sentence.append("(called %s)" % d[1])
            self.out.note(NOTE, "expanded", 
                "%s: !%s binds %s to the %s itself, not to its identifying value."
                % (name, d[1], d[1], name))
            return
        items = list(d) if isinstance(d, tuple) else [d]
        self.out.sentence.append("is")
        for it in items:
            self.path(it, None)
        if kind == "entity":
            # The identifier names the entity's own role in its reference-scheme fact; the
            # value the query is really compared against is the OTHER role's player.
            ident = self.lex.concepts[ast.concept].get("identifier") or []
            via = []
            for r in ident:
                fact = self.lex.concepts.get(self.lex.rel(r) or "", {})
                for other in fact.get("roles", []):
                    if other["id"] != r:
                        via.append(self.cname(other["player"]))
            via = ", ".join(via)
            self.out.note(NOTE, "expanded", 
                "%s: <value> was expanded through its reference scheme%s, so the comparison "
                "is against the identifying value, not the entity."
                % (name, " (%s)" % via if via else ""))

    def condition(self, cond, here):
        if isinstance(cond, cq.Logical):
            for i, operand in enumerate(cond.operands):
                if i:
                    self.out.sentence.append(cond.op)
                self.condition(operand, here)
        elif isinstance(cond, cq.Not):
            self.out.sentence.append("not")
            self.condition(cond.operand, here)
        elif isinstance(cond, cq.Some):
            self.out.sentence.append("there is some")
            self.path(cond.path, None)
            self.out.note(CAUTION, "checks", 
                "SOME is an existence test on its own path; it is tied to the enclosing "
                "query only through variables it names.")
        else:
            self.path(cond, here)


def _mentions_distinct(node) -> bool:
    """Does DISTINCT occur anywhere in this body (section 14a: then the result is distinct)?"""
    if isinstance(node, cq.Distinct):
        return True
    for attr in ("path", "left", "right", "expr", "condition"):
        child = getattr(node, attr, None)
        if child is not None and not isinstance(child, (str, int, float)) and _mentions_distinct(child):
            return True
    for child in getattr(node, "parts", None) or []:
        if _mentions_distinct(child):
            return True
    return False


def reentered_fact_types(model, text, lex) -> list:
    """Fact types a path enters twice, by different roles.

    `Superhero [...] has Attribute a AND ALSO a is of HeroAttribute has ...` enters
    HeroAttribute once from the hero and once from the attribute, and nothing says the two
    are the same row -- so it pairs this hero's attributes with *every* hero's rows for
    those attributes. 3,738 rows where 6 are right, and no existing check speaks: the
    finding-109 caution looks for two fanning branches from one head, and this is one branch
    folding back on itself.

    Measured over the 1,992 recorded corpus answers: it occurs in 2, and both are wrong,
    against a 70% base rate. Rare enough to be worth reading, which the mandatory RISK at
    79% is not (finding 128).
    """
    import collections
    import lower as lower_mod
    try:
        ext, rest, lx, _ = _expand(model, text, lex)
        block = lower_mod.lower(ext, cq.Parser(lx, rest).parse_query(), lx)
    except Exception:                                                # noqa: BLE001
        return []
    found, blocks = [], [block]
    while blocks:
        blk = blocks.pop()
        if not isinstance(blk, dict):
            continue
        by = collections.defaultdict(set)
        for s in blk.get("steps", []):
            if s["kind"] == "enter":
                by[lx.role_owner[s["role"]]].add(s["role"])
        for fact, roles in by.items():
            if len(roles) > 1:
                found.append(lx.concepts.get(fact, {}).get("name", fact))
        blocks.extend(blk.get("subBlocks", []) or [])
        for c in blk.get("calculations", []) or []:
            if c.get("_block"):
                blocks.append(c["_block"])
    return sorted(set(found))


def _expand(model, text, lex):
    import conquer as driver
    ext, rest, lx, _ = driver.expand_definitions(model, text, lex)
    return ext, rest, (lx or lex), None


def explain(model: dict, text: str, lexicon=None) -> Interpretation:
    lex = lexicon or cq.Lexicon(model)
    parser = cq.Parser(lex, text)
    ast = parser.parse_query()
    v = Verbaliser(lex)
    v.out.query = text
    out = v.query(ast)
    for name in reentered_fact_types(model, text, lex):
        out.note(CAUTION, "checks",
                 "This query enters %s twice, by different roles, so it is talking about two "
                 "different %s -- one reached one way and one the other -- and nothing says "
                 "they are the same. Every one of the first is paired with every one of the "
                 "second. If you meant one %s, reach it once and continue from it."
                 % (name, name, name))
    for invocation, expansion in parser.expanded_macros:
        out.note(NOTE, "expanded", "Macro (§6.9): %s stands for %s" % (invocation, expansion))
    return out


MARK = {RISK: "!", CAUTION: "?", NOTE: "-"}


def render(interp: Interpretation) -> str:
    lines = ["  " + interp.text(), ""]
    if interp.normalised:
        lines += ["  Normalised", "    " + interp.normalised, ""]
    if interp.resolved:
        lines.append("  Resolved")
        for typed, meaning in interp.resolved:
            lines.append("    %-34s -> %s" % (typed, meaning))
        lines.append("")
    if interp.expanded:
        lines.append("  Expanded")
        for e in interp.expanded:
            lines.append("    -  %s" % e)
        lines.append("")
    if interp.requires:
        lines.append("  This query requires")
        for r in interp.requires:
            lines.append("    !  %s" % r)
        lines.append("")
    if interp.checks:
        lines.append("  Worth checking")
        for c in interp.checks:
            lines.append("    ?  %s" % c)
    return "\n".join(lines)
