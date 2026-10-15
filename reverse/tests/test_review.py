#!/usr/bin/env python3
"""The review file: claims with their evidence, decisions that survive a rebuild, and a
rejection the next build respects.

One small database with nothing declared -- no key, no reference, nothing NOT NULL -- so every
key, reference and mandatory role in its model is an inference from the rows, and each one is
a claim on the review file. The cases walk the life of a claim: written with a probe that
holds, accepted or rejected by a named person, carried across a rebuild, not applied again
once rejected, and caught by `--check` when a later insert refutes it.

    test_review.py [-v]
"""
import contextlib
import io
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import reverse as reverse_mod                                         # noqa: E402
import review                                                         # noqa: E402

FLAGS = ["--infer-keys", "--infer-mandatory", "--infer-identifiers"]
REF = "rv.rule-9c-orders-customer-id-customer"

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed += ok
    failed += not ok
    print("%-5s %s%s" % ("ok" if ok else "FAIL", name,
                         ("\n        " + detail) if detail and not ok else ""))


def shop(path):
    rnd = random.Random(1)
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE customer (customer_id INTEGER, customer_code TEXT, "
                    "name TEXT, region TEXT);"
                    "CREATE TABLE orders (order_id INTEGER, customer_id INTEGER, "
                    "amount REAL, channel TEXT);")
    c.executemany("INSERT INTO customer VALUES (?,?,?,?)",
                  [(i, "CU%05d" % (i * 7), "n%d" % i, rnd.choice("NSEW")) for i in range(1, 301)])
    c.executemany("INSERT INTO orders VALUES (?,?,?,?)",
                  [(i, rnd.randint(1, 300), round(rnd.random() * 100, 2),
                    rnd.choice(["web", "shop"])) for i in range(1, 2001)])
    c.commit()
    c.close()


def build(db, out):
    with contextlib.redirect_stdout(io.StringIO()):
        reverse_mod.main([db, "-o", out, "-n", "shop"] + FLAGS)
    return (json.load(open(os.path.join(out, "shop.ccm.json"))),
            json.load(open(os.path.join(out, "shop.review.json")))["claims"])


def cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = review.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


def refers(model):
    """Does the model have orders.customer_id as a reference to Customer?"""
    return any(c["kind"] == "fact" and
               {r["player"] for r in c["roles"]} == {"et.Order", "et.Customer"}
               for c in model["concepts"])


def main(argv):
    work = tempfile.mkdtemp(prefix="review-")
    try:
        db = os.path.join(work, "shop.sqlite")
        shop(db)
        model, claims = build(db, work)
        by = {c["id"]: c for c in claims}
        rv = os.path.join(work, "shop.review.json")

        check("an inferred reference is in the model", refers(model))
        check("and is a claim on the review file, proposed", by.get(REF, {}).get("status") == "proposed",
              ", ".join(sorted(by)))
        probed = [c for c in claims if c.get("probe")]
        check("every key, reference and mandatory role inferred carries a probe",
              {c["rule"] for c in probed} >= {"rule 9a", "rule 9b", "rule 9c", "alternate identifier"},
              str(sorted({c["rule"] for c in probed})))
        conn = sqlite3.connect(db)
        empty = [c["id"] for c in probed if conn.execute(c["probe"]).fetchall()]
        check("and every probe holds on the rows it was inferred from", not empty, str(empty))
        conn.close()
        check("a fresh file is valid", not review.problems(claims))

        code, out = cli(rv, "reject", REF, "--by", "tester")
        check("a rejection without a reason is refused", code == 2 and "--reason" in out, out)
        code, out = cli(rv, "accept", "rv.nothing-like-this", "--by", "tester")
        check("a decision about a claim that does not exist is refused", code not in (0, None), out)
        code, _ = cli(rv, "reject", REF, "--by", "tester", "--reason", "a loyalty id, not the customer")
        code2, _ = cli(rv, "accept", "rv.rule-9a-orders-amount", "--by", "tester")
        check("accept and reject write the file", code == 0 and code2 == 0)
        after = {c["id"]: c for c in review.load(rv)}
        check("a decision records who and when", after[REF].get("reviewedBy") == "tester"
              and after[REF].get("reviewedAt") and after[REF]["status"] == "rejected")

        model, claims = build(db, work)
        again = {c["id"]: c for c in claims}
        check("the rebuild does not apply the rejected reference", not refers(model))
        check("the rejection survives the rebuild, marked as no longer made",
              again[REF]["status"] == "rejected" and again[REF].get("notMade")
              and "loyalty" in again[REF].get("reason", ""))
        check("an acceptance survives the rebuild",
              again["rv.rule-9a-orders-amount"]["status"] == "accepted")
        check("an undecided claim is still proposed",
              again["rv.rule-9b-orders-order-id"]["status"] == "proposed")

        code, out = cli(rv, "--db", db, "--check")
        check("--check passes on the rows the claims were made from", code == 0, out)
        later = os.path.join(work, "later.sqlite")
        shutil.copy(db, later)
        c = sqlite3.connect(later)
        c.execute("INSERT INTO orders VALUES (2001, 999, NULL, 'web')")
        c.commit()
        c.close()
        code, out = cli(rv, "--db", later, "--check")
        check("--check fails when a later insert refutes an accepted claim",
              code == 1 and "FAILS   accepted  rv.rule-9a-orders-amount" in out, out)
        check("and notes the rejected one the insert refutes, without failing on it",
              "as the reviewer said" in out, out)

        broken = review.load(rv)
        broken[0].update(status="accepted")
        broken[0].pop("reviewedBy", None)
        review.write(rv, broken)
        check("an unsigned decision makes the file invalid", bool(review.problems(broken)))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                reverse_mod.main([db, "-o", work, "-n", "shop"] + FLAGS)
            check("and the build refuses it rather than guess", False)
        except SystemExit as e:
            check("and the build refuses it rather than guess", "not a valid review file" in str(e))
    finally:
        review.VETO.clear()
        shutil.rmtree(work, ignore_errors=True)

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
