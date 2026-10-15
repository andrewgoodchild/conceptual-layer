#!/usr/bin/env python3
"""--infer-additivity: which numeric values must not be summed, from their names, as guesses.

Each case is a column that must be marked and one beside it that must not -- a rate next to an
amount, a balance next to a deposit -- because a pass that marks every number passes every
"is it marked" test. Then the guess's life: on the review file, in the schema listing, and
gone on the next build once someone rejects it.

    test_additivity.py [-v]
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "conquer"))

import reverse as reverse_mod                                         # noqa: E402
import review                                                         # noqa: E402
import conquer as driver                                              # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed += ok
    failed += not ok
    print("%-5s %s%s" % ("ok" if ok else "FAIL", name,
                         ("\n        " + detail) if detail and not ok else ""))


SCHEMA = """
CREATE TABLE loan (loan_id INTEGER PRIMARY KEY, amount REAL NOT NULL,
                   interest_rate REAL NOT NULL, borrower_age INTEGER, term_months INTEGER);
CREATE TABLE snapshot (account_id INTEGER NOT NULL, taken_on DATE NOT NULL,
                       balance REAL NOT NULL, deposits REAL NOT NULL,
                       PRIMARY KEY (account_id, taken_on));
CREATE TABLE ledger (entry_id INTEGER PRIMARY KEY, opened DATE, closed DATE, balance REAL);
INSERT INTO loan VALUES (1, 1000, 0.05, 40, 12), (2, 2500, 0.07, 31, 24);
INSERT INTO snapshot VALUES (1, '2026-01-31', 100, 20), (1, '2026-02-28', 120, 30);
INSERT INTO ledger VALUES (1, '2026-01-01', NULL, 50);
"""


def build(db, out):
    with contextlib.redirect_stdout(io.StringIO()):
        reverse_mod.main([db, "-o", out, "-n", "fin", "--infer-additivity"])
    model = json.load(open(os.path.join(out, "fin.ccm.json")))
    return model, {c["name"]: c for c in model["concepts"]}


def main(argv):
    work = tempfile.mkdtemp(prefix="additivity-")
    try:
        db = os.path.join(work, "fin.sqlite")
        c = sqlite3.connect(db)
        c.executescript(SCHEMA)
        c.close()
        model, by = build(db, work)
        how = {n: c.get("additivity") for n, c in by.items() if c["kind"] == "value"}

        check("a rate is not additive", how.get("LoanInterestRate") == "nonAdditive", str(how))
        check("an age is not additive", how.get("LoanBorrowerAge") == "nonAdditive", str(how))
        check("an amount beside them is left alone", how.get("LoanAmount") is None, str(how))
        check("so is a term in months", how.get("LoanTermMonths") is None, str(how))
        bal = by.get("SnapshotBalance", {})
        check("a balance beside one date is a level over that date",
              bal.get("additivity") == "semiAdditive"
              and "taken" in (bal.get("additiveExcept") or "").casefold(), json.dumps(bal))
        check("a flow beside it is left alone", how.get("SnapshotDeposits") is None, str(how))
        check("a balance beside two dates is not guessed at",
              how.get("LedgerBalance") is None, str(how))
        check("nothing is marked additive: it is the default and says nothing",
              "additive" not in how.values())

        text = driver.describe(model)
        check("the listing says not to sum them",
              "Additivity" in text and "LoanInterestRate" in text and "a level" in text,
              text[text.find("Additivity"):][:300])

        rv = os.path.join(work, "fin.review.json")
        claims = {c["subject"]: c for c in review.load(rv) if c["rule"] == "additivity"}
        check("each guess is a claim on the review file, at confidence guess",
              {"LoanInterestRate", "SnapshotBalance"} <= set(claims)
              and claims["LoanInterestRate"]["confidence"] == "guess", str(sorted(claims)))
        with contextlib.redirect_stdout(io.StringIO()):
            review.main([rv, "reject", claims["LoanBorrowerAge"]["id"], "--by", "tester",
                         "--reason", "summed for a portfolio age-weighting report"])
        _, by = build(db, work)
        check("a rejected guess is not made again", "additivity" not in by["LoanBorrowerAge"])
        check("and the others are", by["LoanInterestRate"].get("additivity") == "nonAdditive")
    finally:
        review.VETO.clear()
        shutil.rmtree(work, ignore_errors=True)

    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
