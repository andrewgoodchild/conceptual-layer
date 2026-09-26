#!/usr/bin/env python3
"""Does anything the compiler accepts go unrecorded in the documents?

Three documents describe this language and none of them is generated from the code:

    conquer/conquer-2026-grammar.ebnf  the grammar as implemented
    conquer/conquer-2026.md                      what this project added to ConQuer-92, and why
    conquer/primer.md                            the one page a query writer is given

A language grows by someone adding a keyword to a table in `parser.py`, and nothing has ever
noticed when the documents did not follow. This is that check, as a test: every multi-word
phrase the parser will recognise has to appear in one of the three
documents, and every function in the standard library that is not an operator or an internal
has to be named in the primer. A writer cannot use what nothing tells them exists -- one
reported string concatenation as impossible because the primer's function list omitted
`concat`, and it had always worked (finding 99).

Adding a keyword and documenting it are now one task, because leaving the second undone fails.

    test_spec.py [-v]
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "reverse"))

import parser as parser_mod       # noqa: E402
import derive as derive_mod       # noqa: E402

DOCS = {
    "grammar2026": os.path.join(ROOT, "conquer", "conquer-2026-grammar.ebnf"),
    "spec": os.path.join(ROOT, "conquer", "conquer-2026.md"),
    "primer": os.path.join(ROOT, "conquer", "primer.md"),
}

# Operators are spelled as symbols and read as such; the primer documents `+ - * /` rather
# than `add`. These three are the mapping's business, never written by a query author.
OPERATOR_ONLY = {"add", "subtract", "multiply", "divide", "negate", "concat"}
INTERNAL = {"jsonPath", "castNumber", "castInteger"}
# Group functions a query names by keyword (`THE SUM OF`), checked as phrases instead.
#  Reached by an aggregate keyword rather than called by name, so the primer documents the
#  phrase and not the function. `stddev` and `variance` joined the list when SQLite stopped
#  declaring them absent: they are `THE STANDARD DEVIATION` and `THE VARIANCE` to a writer.
BY_KEYWORD = {"count", "sum", "min", "max", "avg", "list", "median", "rank", "lag",
              "stddev", "variance",
              # THE PERCENT RANK OF, THE OBJECT OF ... BY, THE LIST OF ... SEPARATED BY
              "percent_rank", "object", "join"}


def phrases():
    """Every multi-word upper-case phrase the parser will recognise."""
    out = set()
    for table in ("AGGREGATES", "FR_SET", "SET_OP", "SET_CMP", "VALUE_CMP", "LOGIC",
                  "UNLOWERED"):
        out |= {k for k in getattr(parser_mod, table, {}) if re.match(r"^[A-Z][A-Z ]*$", k)}
    src = open(os.path.join(HERE, "..", "parser.py")).read()
    for call in re.finditer(r"(?:try_phrase|at_phrase)\(([^)]*)\)", src):
        out |= set(re.findall(r'"([A-Z][A-Z ]*)"', call.group(1)))
    return {p for p in out if len(p) > 1}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    text = {k: open(v).read() for k, v in DOCS.items()}
    passed = failed = 0

    for phrase in sorted(phrases()):
        where = [k for k, t in text.items() if phrase in t]
        if where:
            passed += 1
            if args.verbose:
                print("ok    %-30s %s" % (phrase, ", ".join(where)))
        else:
            failed += 1
            print("FAIL  %-30s the parser accepts this and no document names it" % phrase)

    lib = derive_mod.standard_functions("sqlite")
    for f in lib:
        name = f["id"].split(".")[-1]
        if name in OPERATOR_ONLY or name in INTERNAL or name in BY_KEYWORD:
            continue
        if name in text["primer"]:
            passed += 1
            if args.verbose:
                print("ok    %-30s primer" % name)
        else:
            failed += 1
            print("FAIL  %-30s in the function library and not named in the primer" % name)

    # The 2026 grammar is descriptive, so it is checked the strict way round: every keyword
    # it quotes must be one the parser really accepts. A grammar that promises a construct
    # the compiler does not have is worse than no grammar -- it is a specification of
    # something that does not exist.
    body = re.sub(r"\(\*.*?\*\)", "", text["grammar2026"], flags=re.S)
    accepted = phrases() | {"IN", "if", "NOT", "AS", "FROM", "LIST", "WHERE", "THEN", "ELSE",
                            "ORDERED", "WITH", "ASCENDING", "DESCENDING", "PER", "DEFINE",
                            "DISTINCT", "ONLY", "GROUPED BY", "BY", "NOT"}
    for kw in sorted(set(re.findall(r"'([A-Za-z][A-Za-z ]*)'", body))):
        if kw in accepted:
            passed += 1
            if args.verbose:
                print("ok    %-30s quoted in the 2026 grammar and accepted" % kw)
        else:
            failed += 1
            print("FAIL  %-30s the 2026 grammar quotes it and the parser does not accept it"
                  % kw)

    # The other direction: a function the primer promises had better exist. A primer that
    # names something absent is worse than one that omits something present.
    have = {f["id"].split(".")[-1] for f in lib}
    promised = re.search(r"\*\*12 — functions\*\*:(.+?)A boolean", text["primer"], re.S)
    if promised:
        for name in re.findall(r"[a-z_]+", promised.group(1)):
            if name in ("a", "b", "c", "if", "function", "stands", "alone", "as", "condition",
                        "call", "them", "by", "name", "joins", "two", "strings", "and",
                        "there", "is", "no", "infix", "the", "or"):
                continue
            if name in have:
                passed += 1
            else:
                failed += 1
                print("FAIL  %-30s the primer names it and the library has no such function"
                      % name)

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
