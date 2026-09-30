#!/usr/bin/env python3
"""The DDL narrowed to a question: the control arm for SCALE.md.

A conceptual description narrowed by `conquer/link.py` has to beat *something* narrowed, or a
win at scale is only narrowing, which needs no conceptual layer. This is that something: a
plain lexical retriever over what a DDL file already holds -- table names, column names,
declared foreign keys and the sample rows -- with nothing from the model.

It uses the same tokeniser as `link.py` (camelCase and snake_case split, plurals folded), so
the two arms differ in what they read, not in how they read a question. Each table is scored
by the question's words in its name (weighted double) and its column names, each word
weighted by how few tables carry it, with a bonus when a quoted value or any question word
appears in the table's sample rows. The top `--tables` are kept, then every table on a
declared-foreign-key path of at most two steps between two kept tables, and the kept
tables' DDL blocks are printed exactly as the benchmark ships them.

    ddl_link.py SCHEMA.txt --for "question [extra words]" [--tables N]
    ddl_link.py SCHEMA.txt                     # everything, like ./schema with no arguments
"""
import argparse
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "conquer"))
from link import tokens, literals                                        # noqa: E402

BLOCK = re.compile(r"CREATE TABLE\s+(\"?[\w]+\"?)\s*\(", re.I)
FK = re.compile(r"FOREIGN KEY\s*\([^)]*\)\s*REFERENCES\s+\"?(\w+)\"?", re.I)
DEFAULT_TABLES = 22          # calibrated against link.py's narrowing; see SCALE.md


def blocks(text):
    """[(table, block text)] in file order, each block running to the next CREATE TABLE."""
    starts = [(m.start(), m.group(1).strip('"')) for m in BLOCK.finditer(text)]
    out = []
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        out.append((name, text[pos:end].rstrip() + "\n"))
    return out


def columns(block):
    head = block.split(");", 1)[0]
    cols = []
    for line in head.splitlines()[1:]:
        line = line.strip()
        if not line or line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE",
                                                "CHECK", "CONSTRAINT")):
            continue
        cols.append(line.split()[0].strip('"'))
    return cols


def sample(block):
    return block.split(");", 1)[1].lower() if ");" in block else ""


class DdlLinker:
    def __init__(self, text):
        self.blocks = blocks(text)
        self.name_bag, self.col_bag, self.rows, self.fk = {}, {}, {}, {}
        for name, b in self.blocks:
            self.name_bag[name] = tokens(name)
            self.col_bag[name] = set().union(*[tokens(c) for c in columns(b)] or [set()])
            self.rows[name] = sample(b)
            self.fk.setdefault(name, set())
            for ref in FK.findall(b):
                if ref != name:
                    self.fk[name].add(ref)
                    self.fk.setdefault(ref, set()).add(name)
        n = len(self.blocks)
        df = {}
        for name, _ in self.blocks:
            for w in self.name_bag[name] | self.col_bag[name]:
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log(1 + n / d) for w, d in df.items()}

    def score(self, question):
        qt = tokens(question)
        lits = [v.lower() for v in literals(question)]
        out = {}
        for name, _ in self.blocks:
            s = sum(2 * self.idf[w] for w in qt & self.name_bag[name])
            s += sum(self.idf[w] for w in (qt & self.col_bag[name]) - self.name_bag[name])
            rows = self.rows[name]
            if any(v and v in rows for v in lits):
                s += 4.0
            if s:
                out[name] = s
        return out

    def path(self, a, b, limit=2):
        seen, frontier = {a}, [(a, [])]
        for _ in range(limit):
            nxt = []
            for here, via in frontier:
                for other in sorted(self.fk.get(here, ())):
                    if other == b:
                        return via
                    if other not in seen:
                        seen.add(other)
                        nxt.append((other, via + [other]))
            frontier = nxt
        return None

    def relevant(self, question, tables=DEFAULT_TABLES):
        ranked = sorted(self.score(question).items(), key=lambda kv: -kv[1])
        keep = [t for t, _ in ranked[:tables]]
        extra = []
        for i, a in enumerate(keep):
            for b in keep[i + 1:]:
                for t in self.path(a, b) or []:
                    if t not in keep and t not in extra:
                        extra.append(t)
        return set(keep) | set(extra)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("schema")
    p.add_argument("--for", dest="about", default="")
    p.add_argument("--tables", type=int, default=DEFAULT_TABLES)
    args = p.parse_args(argv)
    text = open(args.schema).read()
    linker = DdlLinker(text)
    if not args.about.strip():
        sys.stdout.write(text)
        return 0
    keep = linker.relevant(args.about, args.tables)
    if not keep:
        # as `conquer.py --schema --for` does when no word matches: everything, not nothing
        sys.stdout.write(text)
        return 0
    shown = [b for name, b in linker.blocks if name in keep]
    print("-- %d of %d tables, narrowed to: %s" % (len(shown), len(linker.blocks),
                                                    args.about.strip()))
    print("-- ./schema with no arguments prints every table; more words widen the view.\n")
    sys.stdout.write("\n".join(shown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
