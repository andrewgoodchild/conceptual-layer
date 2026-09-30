#!/usr/bin/env python3
"""The DDL, annotated from the conceptual layer: the model's difference, not its restatement.

Two pre-registered rounds at scale (findings 166, 167) found the conceptual description no
better than a narrowed DDL, and the writers said why. It was too large to read -- 80 kB
narrowed -- so they skimmed it and found the structure themselves with queries, and what
they did credit (the value cautions, the routes that disagree, the date formats, the units
inside JSON) was buried in a restatement of a schema they could read off the DDL anyway.
The same rounds found the model's linking kept every table the gold needed on 72 of 100
questions against 51 for a DDL retriever of the same size.

So this keeps the two things the model did well and drops the rest. The model chooses the
tables; the writer reads them as the DDL it is fluent in; and beside each column goes only
what the DDL does not say -- the values a column holds, what profiling found, what is inside
a JSON column -- as SQL comments, inside a character budget.

    annotate.py MODEL.ccm.json SCHEMA.txt --for "question [extra words]" [--budget N]
    annotate.py MODEL.ccm.json SCHEMA.txt              # every table, annotated
    annotate.py SCHEMA.txt --plain --for "..."         # the control: the same view, chosen
                                                       # lexically and with no annotation

SCHEMA.txt is a DDL file as LiveSQLBench ships one: each CREATE TABLE followed by a few
sample rows. The sample rows are kept, cut to a readable width.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "bench", "livesql"))
import link as link_mod                                                  # noqa: E402
from ddl_link import DdlLinker                                           # noqa: E402

BUDGET = 16000          # characters; see bench/livesql/SCALE3.md
ROW_WIDTH = 160         # a sample row is cut here: a JSON cell alone can run to 2,000
MAX_VALUES = 12         # a domain longer than this is summarised
MAX_FIELDS = 24         # JSON fields listed under one column
_COLLINE = re.compile(r'^(\s*)"?(\w+)"?\s')


def _short(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 3] + "..."


class Notes:
    """What the model knows about each table and column that the DDL does not say."""

    def __init__(self, model):
        mapping = model.get("mapping") or {}
        tables = {t["id"]: t["name"] for t in mapping.get("tables", [])}
        columns = {c["id"]: c for c in mapping.get("columns", [])}
        concepts = {c["id"]: c for c in model.get("concepts", [])}
        role_map = {rm["role"]: rm for rm in mapping.get("roleMap", [])}
        self.concept_tables = {}            # concept id -> tables it lives in
        self.column = {}                    # (table, column) -> [note]
        self.fields = {}                    # (table, column) -> [(path, type, [note])]
        self.table = {}                     # table -> [note]
        seen = set()
        for m in mapping.get("conceptMap", []):
            if m.get("table") in tables:
                self.concept_tables.setdefault(m["concept"], set()).add(tables[m["table"]])
        for f in concepts.values():
            if f["kind"] != "fact":
                continue
            for r in f.get("roles", []):
                m = role_map.get(r["id"])
                if not m:
                    continue
                for cid in m.get("columns", []):
                    col = columns.get(cid)
                    if not col or col.get("table") not in tables:
                        continue
                    t = tables[col["table"]]
                    self.concept_tables.setdefault(f["id"], set()).add(t)
                    p = concepts.get(r["player"], {})
                    if p.get("kind") != "value" or (p["id"], cid) in seen:
                        continue
                    seen.add((p["id"], cid))
                    self.concept_tables.setdefault(p["id"], set()).add(t)
                    said = self._value_notes(p)
                    if col.get("path"):
                        typ = (col.get("dataType") or {}).get("name", "")
                        self.fields.setdefault((t, col["name"]), []).append(
                            (col["path"], typ, said))
                    elif said:
                        self.column.setdefault((t, col["name"]), []).extend(said)
        self.entity_table = {c["name"]: sorted(self.concept_tables[c["id"]])[0]
                             for c in concepts.values()
                             if c["kind"] == "entity" and self.concept_tables.get(c["id"])}
        for c in concepts.values():
            if c["kind"] == "entity" and c.get("dataQuality"):
                for t in self.concept_tables.get(c["id"], ()):
                    self.table.setdefault(t, []).extend(
                        _route(q, self.entity_table) for q in c["dataQuality"][:2])

    @staticmethod
    def _value_notes(c):
        out = []
        vals = (c.get("restriction") or {}).get("values") or []
        if vals:
            shown = ", ".join(repr(v) for v in vals[:MAX_VALUES])
            out.append("values: " + shown + (" (+%d more)" % (len(vals) - MAX_VALUES)
                                             if len(vals) > MAX_VALUES else ""))
        if c.get("description") and not c["description"].startswith("A JSON document"):
            out.append(_short(c["description"], 200))
        out += [_short(q, 220) for q in c.get("dataQuality", [])]
        return out


_ROUTE = re.compile(r"Reaches (\w+) by (\d+) routes: (.*?); (they .*?)\.?$")


def _route(said, table_of):
    """A route caution in table terms, shortened: which routes, not how many pairs each
    carries. The model says it of entity types; the reader here sees tables."""
    m = _ROUTE.match(" ".join(said.split()))
    if not m:
        return _short(said, 220)
    ways = [re.sub(r" \(\d+ pairs\)", "", w) for w in re.split(r", (?:and )?", m.group(3))]
    verdict = re.sub(r"the (\d+) \w+ they share", r"the \1 rows they share", m.group(4))
    return "rows here reach %s by %s join routes (%s); %s" % (
        table_of.get(m.group(1), m.group(1)), m.group(2), ", ".join(ways[:4]), verdict)


def _cut_rows(block):
    """The CREATE TABLE as shipped; the sample rows under it cut to ROW_WIDTH."""
    if ");" not in block:
        return block
    head, rows = block.split(");", 1)
    lines = [l if len(l) <= ROW_WIDTH else l[:ROW_WIDTH - 3] + "..."
             for l in rows.splitlines()]
    return head + ");" + "\n".join(lines).rstrip() + "\n"


def render(name, block, notes=None, desc=None, max_fields=MAX_FIELDS):
    """One table: its DDL, with the model's notes and any descriptions as comments. A JSON
    column lists up to `max_fields` of its fields; the full view lists them all."""
    block = _cut_rows(block)
    if notes is None and desc is None:
        return block
    head, rest = block.split(");", 1) if ");" in block else (block, "")
    out = []
    for n in (notes.table.get(name, []) if notes else []):
        out.append("-- " + n)
    for line in head.splitlines():
        m = _COLLINE.match(line)
        col = m.group(2) if m and not line.strip().upper().startswith(
            ("CREATE", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT")) else None
        said = []
        if col:
            said += desc.column.get((name, col), []) if desc else []
            said += notes.column.get((name, col), []) if notes else []
        out.append(line + ("   -- " + "; ".join(said) if said else ""))
        if not col:
            continue
        fields = {}
        for path, typ, fnotes in (notes.fields.get((name, col), []) if notes else []):
            fields.setdefault(tuple(path), [typ, []])[1].extend(fnotes)
        for path, texts in (desc.fields.get((name, col), {}).items() if desc else ()):
            fields.setdefault(path, ["", []])[1][:0] = texts
        for path, (typ, texts) in list(fields.items())[:max_fields]:
            where = col + "".join("->'%s'" % p for p in path[:-1]) + "->>'%s'" % path[-1]
            out.append("    --   %s%s%s" % (where, " " + typ if typ else "",
                                            ("  " + "; ".join(texts)) if texts else ""))
        if len(fields) > max_fields:
            out.append("    --   and %d more fields; ./schema with no words lists them all"
                       % (len(fields) - max_fields))
    return "\n".join(out) + (");" + rest if rest or ");" in block else "")


class Descriptions:
    """What someone wrote about each column: `"table|column"` or `"table|column|a.b"` ->
    text, from one file or several. A benchmark's column meanings are one such file; the
    descriptions an LLM writes from a profile are another. With more than one source each
    text is labelled with its source's name."""

    def __init__(self, sources):
        self.column, self.fields, self.bag = {}, {}, {}
        many = len(sources) > 1
        for label, path in sources:
            for key, text in json.load(open(path)).items():
                parts = key.split("|")
                if len(parts) < 2 or not str(text).strip():
                    continue
                said = (label + ": " if many else "") + _short(text, 170)
                t, c = parts[0], parts[1]
                if len(parts) == 2:
                    self.column.setdefault((t, c), []).append(said)
                else:
                    self.fields.setdefault((t, c), {}).setdefault(
                        tuple(parts[2].split(".")), []).append(said)
                self.bag.setdefault(t, set()).update(link_mod.tokens(str(text)))


class Values:
    """Where a value the question names is stored: lower-cased text value -> the columns
    and JSON fields that hold it. The literal index of Shkapenyuk et al., exact."""

    def __init__(self, path):
        self.index = json.load(open(path))

    def find(self, question, limit=6):
        """Values the question names: anything it quotes, any run of two to four words, and
        any single word with a digit or an underscore in it -- not every word, which in a
        database of free-text columns is stored somewhere, nor every capitalised one, since
        questions capitalise the business's terms. A value stored in more than four places
        says nothing. `question` may carry the literals of a draft query too (`Links`),
        which is where Shkapenyuk et al. take theirs from."""
        words = re.findall(r"[\w'./+-]+", question)
        found, taken = [], set()
        grams = [q.lower() for q in link_mod.literals(question)]
        for n in (4, 3, 2):
            grams += [" ".join(words[i:i + n]).strip(".,'").lower()
                      for i in range(len(words) - n + 1)]
        grams += [w.strip(".,'").lower() for w in words if re.search(r"[\d_]", w)]
        for g in grams:
            if len(g) < 3 or g in link_mod.STOP or g in taken or g not in self.index:
                continue
            if any(g in t for t in taken) or len(self.index[g]) > 4:
                continue
            taken.add(g)
            found.append((g, self.index[g]))
            if len(found) >= limit:
                break
        return found


class Links:
    """The tables and columns a draft of each question used: SCALE4.md's linking by writing
    SQL. Looked up by the question's text, which the writer passes to `./schema`."""

    def __init__(self, path):
        self.by_q = {" ".join(q.lower().split()): v for q, v in json.load(open(path)).items()}

    def find(self, words):
        text = " ".join((words or "").lower().split())
        for q, v in self.by_q.items():
            if q and q in text:
                return v
        return None


class Annotator:
    def __init__(self, schema_text, model=None, desc=None, values=None, links=None,
                 knowledge=None):
        self.knowledge = knowledge
        self.ddl = DdlLinker(schema_text)
        self.model = model
        self.notes = Notes(model) if model else None
        self.linker = link_mod.Linker(model) if model else None
        self.desc, self.values, self.links = desc, values, links

    def ranked(self, question):
        """Tables, most relevant first. With a model, scored by the model's linking -- a
        table takes the best score of any concept stored in it, plus a little for each
        other; without one, by the DDL retriever. Either way, the words of any
        descriptions count too."""
        if not self.linker:
            score = dict(self.ddl.score(question))
        else:
            best, total = {}, {}
            for cid, s in self.linker.score(question).items():
                for t in self.notes.concept_tables.get(cid, ()):
                    best[t] = max(best.get(t, 0), s)
                    total[t] = total.get(t, 0) + s
            known = {n for n, _ in self.ddl.blocks}
            score = {t: best[t] + 0.1 * (total[t] - best[t]) for t in best if t in known}
        if self.desc:
            qt = link_mod.tokens(question)
            weight = 1.0 if not self.linker else 0.25
            for t, bag in self.desc.bag.items():
                hit = len(qt & bag)
                if hit and t in dict(self.ddl.blocks):
                    score[t] = score.get(t, 0) + weight * hit
        return [t for t, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))]

    def view(self, question, budget=BUDGET):
        blocks = dict(self.ddl.blocks)
        notes, desc = self.notes, self.desc
        if not (question or "").strip():
            return "\n".join(render(n, b, notes, desc, max_fields=10 ** 6)
                             for n, b in self.ddl.blocks)
        ranked = self.ranked(link_mod.widen(question, self.knowledge))
        forced, said = [], []
        linked = self.links.find(question) if self.links else None
        if linked:
            forced += [t for t in linked.get("tables", []) if t in blocks]
            if linked.get("columns"):
                said.append("-- Columns a draft of this question used: %s."
                            % ", ".join(linked["columns"][:30]))
        lits = " ".join("'%s'" % l.replace("'", "") for l in (linked or {}).get("literals", []))
        for value, where in (self.values.find(lits + " " + question) if self.values else []):
            said.append("-- The value '%s' is stored in %s." % (value, ", ".join(where[:4])))
            forced += [w.split(".")[0] for w in where[:2] if w.split(".")[0] in blocks]
        forced = list(dict.fromkeys(forced))
        ranked = forced + [t for t in ranked if t not in forced]
        if not ranked:
            return "\n".join(render(n, b, notes, desc) for n, b in self.ddl.blocks)
        keep, size = [], 0
        for t in ranked:
            text = render(t, blocks[t], notes, desc)
            if keep and size + len(text) > budget and t not in forced:
                continue            # a smaller table further down may still fit
            keep.append(t)
            size += len(text)
        # a table on a foreign-key path between two kept ones, where the budget allows:
        # the join the answer needs is often through a table no word of the question named
        for i, a in enumerate(list(keep)):
            for b in list(keep)[i + 1:]:
                for t in self.ddl.path(a, b) or []:
                    if t in keep:
                        continue
                    text = render(t, blocks[t], notes, desc)
                    if size + len(text) <= budget * 1.15:
                        keep.append(t)
                        size += len(text)
        order = [n for n, _ in self.ddl.blocks if n in keep]
        rest = sorted(n for n, _ in self.ddl.blocks if n not in keep)
        head = ["-- %d of %d tables, chosen for: %s" % (len(order), len(blocks),
                                                        _short(question, 200)),
                "-- Not shown: %s." % ", ".join(rest) if rest else "",
                "-- Name more words, or a table, to see it; no words prints every table."]
        if notes:
            head.insert(1, "-- Comments beside a column are what profiling the rows found: "
                           "the values it holds, how they are spelled, what is inside JSON.")
        if desc:
            head.insert(1, "-- Comments beside a column say what it holds.")
        return "\n".join([h for h in head if h] + said + [""] +
                          [render(n, blocks[n], notes, desc) for n in order])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+", help="[MODEL.ccm.json] SCHEMA.txt")
    p.add_argument("--for", dest="about", default="")
    p.add_argument("--budget", type=int, default=BUDGET)
    p.add_argument("--plain", action="store_true",
                   help="no model: lexical choice, no annotation (the control)")
    p.add_argument("--describe", action="append", default=[], metavar="[LABEL=]FILE",
                   help="descriptions to put beside each column: JSON, \"table|column\" or "
                        "\"table|column|a.b\" -> text. Repeat for several sources.")
    p.add_argument("--values", metavar="FILE",
                   help="a value index, lower-cased value -> [\"table.column\", ...]: says "
                        "where a value the question names is stored, and shows that table")
    p.add_argument("--links", metavar="FILE",
                   help="question text -> {tables, columns} a draft of it used")
    p.add_argument("--knowledge", metavar="FILE",
                   help="a knowledge base as JSON lines; the definitions of the terms a "
                        "question names widen the tables chosen for it")
    args = p.parse_args(argv)
    if args.plain:
        model, schema = None, args.paths[-1]
    else:
        if len(args.paths) != 2:
            p.error("a model and a schema, or --plain and a schema")
        model = json.load(open(args.paths[0]))
        schema = args.paths[1]
    desc = Descriptions([tuple(d.split("=", 1)) if "=" in d else ("", d)
                         for d in args.describe]) if args.describe else None
    knowledge = ([json.loads(l) for l in open(args.knowledge) if l.strip()]
                 if args.knowledge else None)
    print(Annotator(open(schema).read(), model, desc,
                    Values(args.values) if args.values else None,
                    Links(args.links) if args.links else None,
                    knowledge).view(args.about, args.budget))
    return 0


if __name__ == "__main__":
    sys.exit(main())
