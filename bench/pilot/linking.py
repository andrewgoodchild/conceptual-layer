#!/usr/bin/env python3
"""Does schema linking over the conceptual model find the tables the answer needs?

The leaderboards agree that picking the right subset of a schema is the largest single lever in
text-to-SQL, and BIRD hands us a labelled set for it for free: the gold SQL names the tables the
answer touches. So the question has an answer that needs no agent, no scoring run and no
judgement -- for each question, does `conquer/link.py`'s subset contain every table the gold
uses, and how much of the schema did it drop to do it?

Two numbers, and both matter only together:

    recall        the share of questions whose gold tables are ALL kept. A method that keeps
                  everything scores 100% and is worthless.
    kept          the share of the model's concepts it kept. A method that keeps nothing
                  scores 0% and is worthless.

Reported against the baseline of keeping the whole model, which is what every arm of the pilot
did.

    linking.py [--questions N] [--seeds N] [--hops N] [-v]
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import link as link_mod               # noqa: E402

MODELS = os.path.join(ROOT, "bench/models")
MINIDEV = os.path.join(ROOT, "bench/bird/mini_dev_sqlite.json")
SPIDER = os.path.join(ROOT, "bench/spider2/spider2-lite")
SPIDER_MODELS = os.path.join(ROOT, "bench/spider2-models")


def bird():
    """(db, model path, question, gold SQL) for every mini-dev question."""
    if not os.path.exists(MINIDEV):
        return
    for q in json.load(open(MINIDEV)):
        yield (q["db_id"], os.path.join(MODELS, "%s.ccm.json" % q["db_id"]),
               q["question"] + " " + (q.get("evidence") or ""), q["SQL"])


def spider2():
    """The same, for Spider 2.0's local tasks.

    The regime the leaderboards' schema-linking claim is about: these databases average 100
    columns and 14 tables against BIRD's 54 and 7, and `f1` alone derives to 216 fact types.
    Only 24 of the 135 ship their gold SQL, which is the labelled set for table recall; the
    rest ship an answer and no query.
    """
    tasks = os.path.join(SPIDER, "spider2-lite.jsonl")
    if not os.path.exists(tasks):
        return
    for line in open(tasks):
        row = json.loads(line)
        if not row["instance_id"].startswith("local"):
            continue
        gold = os.path.join(SPIDER, "evaluation_suite/gold/sql", row["instance_id"] + ".sql")
        model = os.path.join(SPIDER_MODELS, "%s.ccm.json" % row["db"])
        if not (os.path.exists(gold) and os.path.exists(model)):
            continue
        knowledge = row.get("external_knowledge") or ""
        yield (row["db"], model,
               row["question"] + ("" if knowledge in ("None", "") else " " + knowledge),
               open(gold).read())


def gold_tables(sql: str, tables):
    """Which of the model's tables the gold SQL names. Word-boundary matching against the
    known table names, which is blunt but cannot invent a table the schema does not have."""
    low = sql.lower()
    return {t for t in tables if re.search(r"\b%s\b" % re.escape(t.lower()), low)}


def tables_of(model):
    return {t["id"]: t["name"] for t in model.get("mapping", {}).get("tables", [])}


def concept_tables(model):
    """concept id -> the tables it reads. A concept the query needs is a table the SQL needs."""
    tabs = tables_of(model)
    out = {}
    for m in model.get("mapping", {}).get("conceptMap", []):
        if m.get("table") in tabs:
            out.setdefault(m["concept"], set()).add(tabs[m["table"]])
    roles = {}
    for c in model.get("concepts", []):
        for r in c.get("roles", []):
            roles[r["id"]] = c["id"]
    for m in model.get("mapping", {}).get("roleMap", []):
        cid = roles.get(m.get("role"))
        if cid and m.get("table") in tabs:
            out.setdefault(cid, set()).add(tabs[m["table"]])
    return out


def sufficiency(args):
    """Does a pruned model still compile the queries people actually wrote?

    Table recall against gold SQL says the subset contains the answer's tables. It does not say
    the subset is *usable*: a model missing one value type is a model a query cannot be written
    against. The pilot left 1,186 real ConQuer queries with the questions that produced them,
    so this asks the question directly -- prune by the question, compile the query that was
    written, and count what survives.
    """
    import conquer as driver, parser as parser_mod, sql as sql_mod, corpus
    questions = {}
    for q in json.load(open(MINIDEV)):
        questions[(q["db_id"], str(q["question_id"]))] = q
    whole = pruned = total = 0
    lost = []
    tools = {}
    for arm, db, qid, text in corpus.answers():
        if arm in corpus.SEMANTIC:
            continue                       # its concepts are hand-written, not derived
        q = questions.get((db, str(qid)))
        path = os.path.join(MODELS, "%s.ccm.json" % db)
        if not q or not os.path.exists(path):
            continue
        if path not in tools:
            m = json.load(open(path))
            tools[path] = (m, link_mod.Linker(m))
        model, linker = tools[path]
        total += 1
        try:
            driver.transpile(model, text, parser_mod.Lexicon(model), sql_mod.Emitter(model))
            whole += 1
        except Exception:                                             # noqa: BLE001
            continue                       # it did not compile whole either; not linking's fault
        keep = linker.relevant(q["question"] + " " + (q.get("evidence") or ""),
                               args.seeds, args.hops, args.connect, args.attributes)
        small = dict(model, concepts=[c for c in model["concepts"] if c["id"] in keep])
        try:
            driver.transpile(small, text, parser_mod.Lexicon(small), sql_mod.Emitter(small))
            pruned += 1
        except Exception as e:                                        # noqa: BLE001
            lost.append((db, qid, "%s: %s" % (type(e).__name__, str(e)[:70])))
    print("%d queries, %d of which compile against the whole model" % (total, whole))
    print("  still compile against the pruned model  %3.0f%%  (%d of %d)"
          % (100.0 * pruned / whole if whole else 0, pruned, whole))
    if args.verbose:
        for db, qid, why in lost[:15]:
            print("    lost %-24s q%-6s %s" % (db, qid, why))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--questions", type=int, default=0, help="stop after this many")
    p.add_argument("--corpus", default="bird", choices=("bird", "spider2"),
                   help="bird is 11 databases of 7 tables; spider2 is 30 of 14, which is the "
                        "regime the schema-linking claim is actually about")
    p.add_argument("--seeds", type=int, default=40)
    p.add_argument("--hops", type=int, default=0)
    p.add_argument("--connect", type=int, default=2,
                   help="how far apart two seeds may be and still be joined")
    p.add_argument("--queries", action="store_true",
                   help="instead of gold tables, ask whether the pruned model still compiles "
                        "the 1,186 ConQuer queries the pilot actually wrote")
    p.add_argument("--attributes", default="anchors", choices=("none", "anchors", "all"),
                   help="whose value facts to keep: only the entities the question\n                        named, or every entity kept")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if args.queries:
        return sufficiency(args)

    corpus_rows = list(spider2() if args.corpus == "spider2" else bird())
    if not corpus_rows:
        print("no %s corpus here (bench/fetch.sh, or bench/spider2-trial/README.md)"
              % args.corpus)
        return 2
    linkers, models = {}, {}
    n = recalled = 0
    kept_concepts = total_concepts = kept_tables = total_tables = 0
    misses = []
    for db, path, question, sql in corpus_rows:
        if not os.path.exists(path):
            continue
        if db not in linkers:
            models[db] = json.load(open(path))
            linkers[db] = link_mod.Linker(models[db])
        model, linker = models[db], linkers[db]
        tabs = set(tables_of(model).values())
        want = gold_tables(sql, tabs)
        if not want:
            continue
        n += 1
        keep = linker.relevant(question, args.seeds, args.hops, args.connect, args.attributes)
        ct = concept_tables(model)
        got = set().union(*[ct.get(c, set()) for c in keep]) if keep else set()
        total_concepts += len(model["concepts"])
        kept_concepts += len(keep)
        total_tables += len(tabs)
        kept_tables += len(got)
        if want <= got:
            recalled += 1
        else:
            misses.append((db, question[:28], sorted(want - got)))
        if args.questions and n >= args.questions:
            break

    if not n:
        print("no questions scored: are the models built? (bench/run.sh)")
        return 2
    print("%d questions over %d databases" % (n, len(linkers)))
    print("  every gold table kept   %3.0f%%  (%d of %d)" % (100.0 * recalled / n, recalled, n))
    print("  concepts kept           %3.0f%%  (%d of %d)"
          % (100.0 * kept_concepts / total_concepts, kept_concepts, total_concepts))
    print("  tables kept             %3.0f%%  (%d of %d)"
          % (100.0 * kept_tables / total_tables, kept_tables, total_tables))
    if args.verbose:
        for db, qid, lost in misses[:20]:
            print("    missed %-24s q%-6s %s" % (db, qid, ", ".join(lost)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
