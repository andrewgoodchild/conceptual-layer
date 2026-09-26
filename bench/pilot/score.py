#!/usr/bin/env python3
"""Score the pilot: three arms, one metric, BIRD's own.

BIRD's execution accuracy is `set(predicted) == set(gold)` over raw tuples. That is what
`ok` counts here. Two further columns matter more for the question the pilot was run to
answer, so they are counted separately:

    failed loudly   the answer did not compile or did not run -- a parse error, an
                    ambiguity the compiler refused to resolve, a SQL error. The author
                    sees this before anyone reads the result.
    wrong quietly   the answer ran and returned the wrong rows. Nobody sees this.

A language that trades the second for the first is doing something valuable even when its
execution accuracy is no better.
"""
import json, os, sqlite3, sys, collections, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "conquer"))
DBS = os.path.join(ROOT, "bench/bird/minidev/MINIDEV/dev_databases")

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402

ARMS = ["direct", "conquer", "modelled", "conquer_forml", "modelled_full",
        "direct_noev", "conquer_noev", "conquer_sem",
        "modelled_sem",
        "conquer_run2", "conquer_run3", "conquer_opus", "direct_opus",
        "conquer_noev_lookup", "conquer_verified", "conquer_select", "conquer_vote",
        "conquer_logged",                     # finding 57: `conquer` again, attempts logged
        # Model quality, not prompt or strategy: the same questions and materials against
        # three models differing only in which references they were built from (finding 125).
        "conquer_refs_declared", "conquer_refs_rules", "conquer_refs_judged",
        # 14 Sep: candidates that differ in *strategy* rather than in sampling, which is what
        # CHASE-SQL's claim actually rests on. The earlier trio was one prompt three times.
        "conquer_dc", "conquer_plan", "conquer_shots", "conquer_chase", "conquer_chase_vote",
        # 15 Sep: the model's English said at Bird's second level of abstraction rather than
        # flat, for each language
        "modelled_abstract", "conquer_abstract",
        # the prompt control for those two
        "modelled_full_v2", "direct_v2",
        # finding 72's two-sided ablation: cardinality removed from the flat text, and added
        # to the summary
        "modelled_nouniq", "modelled_abstract_card",
        # finding 74's last shot at the ceiling: the method and the stronger writer together
        "conquer_dc_v2", "conquer_dc_opus", "conquer_dc_old",
        # 19 Sep, finding 133: `conquer_dc_opus` again with one paragraph added to the brief
        # telling the writer to count the things the question asks for and check the LIST has
        # that many. Projecting the wrong number of columns is fatal by construction and cost
        # the best arm three answers; the brief is the only variable between the two arms.
        "conquer_dc_arity",
        # 25 Sep: the same two languages with nothing but the MCP server as the interface --
        # the description, the runners and the brief fetched over the protocol (mcp/).
        "conquer_mcp", "direct_mcp"]
SEMANTIC = {"conquer_sem"}                    # arms that query the semantic-layer model

# Arms whose model is a variant of the base one, as `bench/ablation/models.py` writes them:
# arm -> the infix in `bench/models/<db>.<infix>.ccm.json`. `SEMANTIC` is the original case
# of this and is kept as it is; without the general form the three reference arms would each
# have been scored against the *declared* model, which is the one thing the experiment varies.
VARIANT = {"conquer_refs_declared": "refs-declared",
           "conquer_refs_rules": "refs-rules",
           "conquer_refs_judged": "refs-judged"}


TIMEOUT = 120


def rows(conn, statement, params=()):
    """Run with a deadline. A query that does not finish in two minutes is a loud failure;
    an author would see it hang."""
    deadline = time.time() + TIMEOUT
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    try:
        return conn.execute(statement, params).fetchall()
    finally:
        conn.set_progress_handler(None, 0)


def bird_ex(got, want):
    """BIRD's own comparison: the result sets, as sets of raw tuples."""
    return set(got) == set(want)


def main():
    qs = {q["question_id"]: q for q in json.load(open(os.path.join(HERE, "questions.json")))}
    if "--summarise" in sys.argv:
        summarise(json.load(open(os.path.join(HERE, "results.json"))), qs)
        return
    if "--merge" in sys.argv:
        # fold per-arm result files (from `--arms X --out F`, run in parallel) into results.json
        files = []
        for a in sys.argv[sys.argv.index("--merge") + 1:]:
            if a.startswith("--"):
                break
            files.append(a)
        results = os.path.join(HERE, "results.json")
        out = json.load(open(results)) if os.path.exists(results) else []
        for f in files:
            added = json.load(open(f))
            arms = {r["arm"] for r in added}
            out = [r for r in out if r["arm"] not in arms] + added
        json.dump(out, open(results, "w"), indent=1)
        summarise(out, qs)
        return
    # `--arms a b`: score only those, and keep the other arms' rows from the last run --
    # re-scoring eight arms to add one is an hour of correlated subqueries.
    arms = ARMS
    if "--arms" in sys.argv:
        arms = []
        for a in sys.argv[sys.argv.index("--arms") + 1:]:
            if a.startswith("--"):
                break
            arms.append(a)
        unknown = [a for a in arms if a not in ARMS]
        if unknown:
            sys.exit("unknown arm(s): %s" % ", ".join(unknown))
    conns, models, lexicons, emitters = {}, {}, {}, {}

    def conn_for(db):
        if db not in conns:
            c = sqlite3.connect(os.path.join(DBS, db, db + ".sqlite"))
            c.text_factory = lambda b: b.decode("utf-8", "replace")
            conns[db] = c
        return conns[db]

    out = []
    for arm in arms:
        for db in sorted({q["db_id"] for q in qs.values()}):
            path = os.path.join(HERE, "work", arm, db, "answers.json")
            try:
                answers = json.load(open(path))
            except Exception as e:                                    # noqa: BLE001
                print("!! %s/%s: %s" % (arm, db, e), file=sys.stderr)
                continue
            for a in answers:
                qid = a.get("question_id")
                q = qs.get(qid)
                if q is None:
                    continue
                row = {"arm": arm, "question_id": qid, "db_id": db,
                       "difficulty": q["difficulty"], "answer": a.get("answer"),
                       "attempts": a.get("attempts"), "note": a.get("note")}
                c = conn_for(db)
                try:
                    gold = rows(c, q["SQL"])
                except sqlite3.Error as e:
                    row["outcome"] = "gold_error"; row["error"] = str(e)
                    out.append(row); continue
                if not a.get("answer"):
                    row["outcome"] = "not_answered"
                    out.append(row); continue
                try:
                    if arm.startswith("conquer"):
                        infix = "semantic" if arm in SEMANTIC else VARIANT.get(arm)
                        key = (db, infix)
                        if key not in models:
                            path = os.path.join(ROOT, "bench/models/%s.%sccm.json"
                                                % (db, (infix + ".") if infix else ""))
                            models[key] = json.load(open(path))
                            lexicons[key] = parser_mod.Lexicon(models[key])
                            emitters[key] = sql_mod.Emitter(models[key])
                        _, st, p = driver.transpile(models[key], a["answer"],
                                                    lexicons[key], emitters[key])
                        row["sql"] = st
                        got = rows(c, st, p)
                    else:
                        got = rows(c, a["answer"])
                except (parser_mod.ParseError, parser_mod.Ambiguous, sql_mod.SqlError) as e:
                    row["outcome"] = "failed_loudly"
                    row["error"] = "%s: %s" % (type(e).__name__, e)
                    out.append(row); continue
                except sqlite3.Error as e:
                    row["outcome"] = "failed_loudly"
                    row["error"] = ("timeout after %ds" % TIMEOUT) if "interrupted" in str(e) \
                        else "sqlite: %s" % e
                    out.append(row); continue
                row["rows"] = len(got)
                row["outcome"] = "ok" if bird_ex(got, gold) else "wrong_quietly"
                row["gold_rows"] = len(gold)
                out.append(row)

    if "--out" in sys.argv:                      # this run's rows only; merge later
        json.dump(out, open(sys.argv[sys.argv.index("--out") + 1], "w"), indent=1)
        summarise(out, qs)
        return
    results = os.path.join(HERE, "results.json")
    if arms is not ARMS and os.path.exists(results):
        kept = [r for r in json.load(open(results)) if r["arm"] not in arms]
        out = kept + out
    json.dump(out, open(results, "w"), indent=1)
    summarise(out, qs)


def summarise(out, qs):
    n = len(qs)
    print("%d questions, %d in the sample\n" % (len(out), n))
    print("%-10s %8s %8s %8s %8s %8s" % ("arm", "correct", "loud", "quiet", "skipped", "EX"))
    print("-" * 56)
    for arm in ARMS:
        r = [x for x in out if x["arm"] == arm]
        c = collections.Counter(x["outcome"] for x in r)
        print("%-10s %8d %8d %8d %8d %7.0f%%"
              % (arm, c["ok"], c["failed_loudly"], c["wrong_quietly"], c["not_answered"],
                 100.0 * c["ok"] / max(len(r), 1)))
    print("\nby difficulty (correct / asked)")
    print("%-10s %14s %14s %14s" % ("arm", "simple", "moderate", "challenging"))
    print("-" * 56)
    for arm in ARMS:
        r = [x for x in out if x["arm"] == arm]
        cells = []
        for d in ("simple", "moderate", "challenging"):
            sub = [x for x in r if x["difficulty"] == d]
            ok = sum(1 for x in sub if x["outcome"] == "ok")
            cells.append("%d/%d" % (ok, len(sub)))
        print("%-10s %14s %14s %14s" % (arm, *cells))
    print("\nby database (correct / asked)")
    fmt = "%-26s" + " %14s" * len(ARMS)
    print(fmt % ("database", *ARMS))
    print("-" * (26 + 15 * len(ARMS)))
    for db in sorted({x["db_id"] for x in out}):
        cells = []
        for arm in ARMS:
            sub = [x for x in out if x["arm"] == arm and x["db_id"] == db]
            cells.append("%d/%d" % (sum(1 for x in sub if x["outcome"] == "ok"), len(sub)))
        print(fmt % (db, *cells))
    print("\nagreement: questions every arm got right / every arm got wrong")
    by_q = collections.defaultdict(dict)
    for x in out:
        by_q[x["question_id"]][x["arm"]] = x["outcome"]
    full = [q for q, v in by_q.items() if len(v) == len(ARMS)]
    allok = [q for q in full if all(v == "ok" for v in by_q[q].values())]
    nonok = [q for q in full if all(v != "ok" for v in by_q[q].values())]
    print("  scored by every arm:      %d" % len(full))
    print("  every arm correct:        %d" % len(allok))
    print("  none correct:             %d" % len(nonok))
    only = {a: [q for q in full if by_q[q][a] == "ok"
                and all(by_q[q][b] != "ok" for b in ARMS if b != a)] for a in ARMS}
    for a in ARMS:
        print("  only %-9s correct:  %d  %s" % (a, len(only[a]), sorted(only[a])[:10]))


if __name__ == "__main__":
    main()
