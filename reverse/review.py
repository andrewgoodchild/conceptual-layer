#!/usr/bin/env python3
"""The worklist as a file someone can sign: each claim the draft makes, its evidence as a query
anyone can re-run, and what a person decided about it.

The report has always said which claims are guesses -- "Confirm it. Containment is not
reference" -- and then nothing recorded whether anyone did. A rebuild wrote the same guesses
back, the confirmed and the refuted alike, and the only memory of a review was whoever did it.
So `reverse.py` writes `<name>.review.json` beside the model:

    {"claims": [{"id", "rule", "confidence", "subject", "claim", "action",
                 "probe"?,                       SQL whose rows are counter-examples
                 "status": "proposed" | "accepted" | "rejected",
                 "reviewedBy"?, "reviewedAt"?, "reason"?}]}

and reads it back on the next build. A decision outlives the build that prompted it, and a
**rejected** claim is not applied again: the passes that change the model -- an undeclared
key or reference read from the rows, a mandatory role, a referenced key preferred, a second
identifier, a reference guessed from a name -- skip what was rejected (`vetoed`).

The probe is the evidence, written so it can be checked rather than believed: the query whose
rows would refute the claim, shaped like a constraint's `violation` (model/model.md §2.4) --
empty means it holds. A claim about rows can go stale on the next insert, and `--check` is how
to find out which ones have, accepted ones included.

    review.py out/x.review.json                         the claims, least trustworthy first
    review.py out/x.review.json --db x.sqlite --check   re-run every probe
    review.py out/x.review.json accept ID... --by NAME [--reason TEXT]
    review.py out/x.review.json reject ID... --by NAME --reason TEXT
"""

import argparse
import datetime
import json
import os
import re
import sqlite3
import sys

STATUSES = ("proposed", "accepted", "rejected")
CONFIDENCE = {"blocker-adjacent": 0, "guess": 1, "heuristic": 2, "population": 3,
              "catalogue": 4, "sound": 5}

# (rule, subject) pairs a person rejected, read from the previous review file before the
# passes run. Empty by default, so every caller other than reverse.py sees no change.
VETO = set()


def vetoed(rule, subject):
    return (rule, subject) in VETO


def claim_id(rule, subject):
    """Stable across rebuilds: the rule and the subject, which the passes write the same way
    every time for the same finding."""
    slug = re.sub(r"[^a-z0-9]+", "-", ("%s %s" % (rule, subject)).casefold()).strip("-")
    return "rv." + slug


# --------------------------------------------------------------------------- probes

def _q(name):
    return '"%s"' % name.replace('"', '""')


def contained(table, cols, target, target_cols):
    """Rows of `table` whose `cols` are not in `target`: a reference's counter-examples."""
    near = " AND ".join("t.%s IS NOT NULL" % _q(c) for c in cols)
    on = " AND ".join("p.%s = t.%s" % (_q(tc), _q(c)) for c, tc in zip(cols, target_cols))
    return ("SELECT %s FROM %s t WHERE %s AND NOT EXISTS (SELECT 1 FROM %s p WHERE %s)"
            % (", ".join("t.%s" % _q(c) for c in cols), _q(table), near, _q(target), on))


def unique(table, cols, total=True):
    """Values of `cols` held by more than one row -- and, for a key, rows with none."""
    c = ", ".join(_q(x) for x in cols)
    dup = "SELECT %s FROM %s GROUP BY %s HAVING COUNT(*) > 1" % (c, _q(table), c)
    if not total:
        return dup
    return "SELECT %s FROM %s WHERE %s UNION ALL %s" % (
        c, _q(table), " OR ".join("%s IS NULL" % _q(x) for x in cols), dup)


def never_null(table, col):
    return "SELECT * FROM %s WHERE %s IS NULL" % (_q(table), _q(col))


# --------------------------------------------------------------------------- the file

def load(path):
    """The claims in a review file, or [] when there is none yet."""
    if not path or not os.path.exists(path):
        return []
    return json.load(open(path)).get("claims", [])


def decided(claims):
    return {c["id"]: c for c in claims if c.get("status") in ("accepted", "rejected")}


def merge(report, previous):
    """This build's claims, with every earlier decision carried onto the claim it was about.
    A decided claim this build no longer makes is kept, marked `notMade`: a rejection that
    worked is the reason it is not made, and dropping it would lose that."""
    old = decided(previous)
    out, seen = [], set()
    for r in report.refinements:
        cid = claim_id(r["rule"], r["subject"])
        if cid in seen:
            continue
        seen.add(cid)
        rec = {"id": cid, "rule": r["rule"], "confidence": r["confidence"],
               "subject": r["subject"], "claim": r["message"], "action": r["action"]}
        if r.get("probe"):
            rec["probe"] = r["probe"]
        rec["status"] = "proposed"
        if cid in old:
            for k in ("status", "reviewedBy", "reviewedAt", "reason"):
                if k in old[cid]:
                    rec[k] = old[cid][k]
        out.append(rec)
    for cid, rec in sorted(old.items()):
        if cid not in seen:
            out.append(dict(rec, notMade=True))
    return out


def write(path, claims, source=None):
    with open(path, "w") as fh:
        json.dump({"source": source, "claims": claims}, fh, indent=2)
        fh.write("\n")


def problems(claims):
    """What makes a review file wrong: an unknown status, a decision nobody signed."""
    out = []
    for c in claims:
        if c.get("status") not in STATUSES:
            out.append("%s: status %r is not one of %s" % (c.get("id"), c.get("status"),
                                                          ", ".join(STATUSES)))
        elif c["status"] != "proposed" and not (c.get("reviewedBy") and c.get("reviewedAt")):
            out.append("%s: %s with no reviewedBy and reviewedAt -- a decision says who "
                       "made it and when" % (c["id"], c["status"]))
        if c.get("status") == "rejected" and not c.get("reason"):
            out.append("%s: rejected with no reason" % c["id"])
    return out


# --------------------------------------------------------------------------- the CLI

def show(claims, everything=False):
    order = sorted(claims, key=lambda c: (STATUSES.index(c["status"]) if c.get("status")
                                          in STATUSES else len(STATUSES),
                                          CONFIDENCE.get(c.get("confidence"), 9), c["id"]))
    lines = []
    for c in order:
        if not everything and c.get("status") != "proposed" and not c.get("notMade"):
            continue
        mark = str(c.get("status")) + (" by %s on %s" % (c["reviewedBy"], c["reviewedAt"])
                              if c.get("reviewedBy") else "")
        lines.append("%s  [%s, %s]  %s%s" % (c["id"], c["confidence"], mark, c["subject"],
                                            "  (no longer made by the build)"
                                            if c.get("notMade") else ""))
        if c.get("reason"):
            lines.append("    reason: %s" % c["reason"])
        if c.get("probe"):
            lines.append("    probe: %s" % c["probe"])
    counts = {s: sum(1 for c in claims if c.get("status") == s) for s in STATUSES}
    lines.append("\n%d claims: %s" % (len(claims), ", ".join("%d %s" % (n, s)
                                                              for s, n in counts.items())))
    return "\n".join(lines)


def check(claims, conn, limit=3):
    """Re-run every probe. Returns the number of accepted or proposed claims the rows now
    refute; a rejected one that holds is only noted -- the person may know something the rows
    do not."""
    refuted = 0
    for c in claims:
        if not c.get("probe"):
            continue
        try:
            rows = conn.execute(c["probe"]).fetchmany(limit + 1)
        except Exception as e:                                       # noqa: BLE001
            print("BROKEN  %-9s %s: %s" % (c["status"], c["id"], str(e)[:80]))
            refuted += c["status"] != "rejected"
            continue
        if not rows:
            print("holds   %-9s %s" % (c["status"], c["id"]))
            continue
        if c["status"] == "rejected":
            print("refuted %-9s %s (as the reviewer said)" % (c["status"], c["id"]))
            continue
        refuted += 1
        print("FAILS   %-9s %s: %s%s" % (c["status"], c["id"],
                                         "; ".join(", ".join(map(str, r)) for r in rows[:limit]),
                                         " ..." if len(rows) > limit else ""))
    return refuted


def decide(claims, ids, status, by, reason):
    by_id = {c["id"]: c for c in claims}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit("no claim %s in this file; `review.py FILE --all` lists them"
                         % ", ".join(missing))
    today = datetime.date.today().isoformat()
    for i in ids:
        c = by_id[i]
        c.update(status=status, reviewedBy=by, reviewedAt=today)
        if reason:
            c["reason"] = reason
        else:
            c.pop("reason", None)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("file", help="a <name>.review.json written by reverse.py")
    p.add_argument("decision", nargs="?", choices=["accept", "reject"])
    p.add_argument("ids", nargs="*")
    p.add_argument("--by", help="who decided: required to accept or reject")
    p.add_argument("--reason", help="why; required to reject")
    p.add_argument("--db", help="a SQLite database to run the probes against")
    p.add_argument("--check", action="store_true", help="re-run every probe")
    p.add_argument("--all", action="store_true", help="list decided claims too")
    args = p.parse_args(argv)
    if not os.path.exists(args.file):
        p.error("no review file %s: reverse.py writes one beside the model" % args.file)
    doc = json.load(open(args.file))
    claims = doc.get("claims", [])
    if args.decision:
        if not args.ids:
            p.error("name the claims to %s" % args.decision)
        if not args.by:
            p.error("--by is required: a decision says who made it")
        if args.decision == "reject" and not args.reason:
            p.error("--reason is required to reject: the next reviewer needs it")
        decide(claims, args.ids, args.decision + "ed", args.by, args.reason)
        write(args.file, claims, doc.get("source"))
        print("%s %d claim%s; rebuild with reverse.py to apply" % (
            args.decision + "ed", len(args.ids), "" if len(args.ids) == 1 else "s"))
        return 0
    wrong = problems(claims)
    for w in wrong:
        print("INVALID %s" % w)
    if args.check:
        if not args.db:
            p.error("--check needs --db")
        conn = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
        n = check(claims, conn)
        print("\n%d claim%s the rows now refute" % (n, "" if n == 1 else "s"))
        return 1 if n or wrong else 0
    print(show(claims, args.all))
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
