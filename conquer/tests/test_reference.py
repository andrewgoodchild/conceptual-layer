#!/usr/bin/env python3
"""Differential test: the compiler's SQL against the reference interpreter, on the same data.

The reference (`conquer/reference.py`) evaluates Proper's P directly. The compiler is supposed
to implement P. Where the two disagree, one of them is wrong -- and that is a check the
recorded corpus cannot make, because it detects change rather than wrongness.

Three sources of queries, each run through both and compared as multisets:

    the fan-trap cases     `test_fanout.CASES` -- every one carries hand-written truth SQL,
                           so here the reference is checked against the truth as well
    the primer             every executable block in `conquer/primer.md`
    hand-picked            shapes the 1992 core covers that neither of those exercises

A query the reference does not support is counted, not hidden: coverage is part of the result.

    test_reference.py [-v] [--only SUBSTRING]
"""

import argparse
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "..", ".work")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import conquer as driver          # noqa: E402
import parser as parser_mod       # noqa: E402
import sql as sql_mod             # noqa: E402
import reference as ref_mod       # noqa: E402

DB = os.path.join(WORK, "company.sqlite")
MODEL = os.path.join(WORK, "company.ccm.json")

# Queries where the compiler is known to disagree with the reference, each with the finding
# that says why and what closing it takes. A gap is reported, not failed; a gap that starts
# agreeing fails, so this table cannot go stale.
GAPS = {
    # (none at present; the two GROUPED BY cases of finding 112 closed in finding 117)
}

EXTRA = [
    "LIST n FROM Employee has EmployeeName n",
    "LIST n, d FROM Employee has EmployeeName n AND ALSO has Department has DepartmentCode d",
    "LIST n FROM Employee [has EmployeeGender: 'F'] has EmployeeName n",
    "LIST n FROM Employee has EmployeeName n BUT NOT has Department: 'ENG'",
    "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > 100000",
    "LIST n, s FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s WHERE s > 100000 AND s < 180000",
    "THE COUNT OF Employee",
    "THE COUNT OF Employee has Department: 'ENG'",
    "THE SUM OF s IN Employee has EmployeeSalary s",
    "THE AVERAGE s IN Employee has EmployeeSalary s",
    "THE MAXIMUM s IN Employee has EmployeeSalary s",
    "THE DISTINCT COUNT OF Employee has Department",
    # the round trip that collapsed (finding 101): P says concatenation is a join
    "LIST a, b FROM Employee has EmployeeName a AND ALSO has Department is of Employee has EmployeeName b",
    # a bracket that binds a name joins (finding 80)
    "LIST n, g FROM Employee [has EmployeeGender g] has EmployeeName n",
    # a bracket on the far side of a step
    "LIST c FROM Department [is of Employee has EmployeeSalary s WHERE s > 150000] has DepartmentCode c",
    # projection arithmetic
    "LIST n, s / 1000 FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s",
    # section 14b under GROUPED BY -- tracked in GAPS above
    ("LIST d, t FROM Employee has Department has DepartmentCode d AND ALSO has Project has "
     "ProjectPriority p AND ALSO THE SUM OF p GROUPED BY d AS t"),
    ("LIST d, t FROM Employee has Department has DepartmentCode d AND ALSO has Project has "
     "ProjectPriority p AND ALSO THE AVERAGE p GROUPED BY d AS t"),
    # a verb step from a derived subtype through a ring fact type is a step, not item 16's
    # narrowing (the reference relabelled the heads instead of walking the ring; finding 114)
    ("DEFINE Senior ::= LIST e FROM Employee e has EmployeeSalary s WHERE s > 100000 "
     "THE COUNT OF Senior has manager Employee"),
    ("DEFINE Senior ::= LIST e FROM Employee e has EmployeeSalary s WHERE s > 100000 "
     "LIST n FROM Senior has manager Employee has EmployeeName n"),
    # DISTINCT inside the bag an aggregate ranges over is section 14a's DISTINCT: the normal
    # form of this query is `THE COUNT OF v1 IN (DISTINCT Employee v1 ...)` and the
    # normal-form check reads both (finding 114)
    "THE COUNT OF DISTINCT Employee [has Department is of Employee has EmployeeSalary s WHERE s > 50000]",
    # a comparison written into a path restricts its tail
    "THE COUNT OF Employee [has EmployeeSalary > 50000]",
    "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary >= 100000",
    "THE COUNT OF DISTINCT Employee [has Department is of Employee has EmployeeSalary > 50000]",
    "LIST n FROM Employee has EmployeeName n AND ALSO has EmployeeSalary s AND ALSO has Department "
    "has DepartmentBudget > s * 10",
    # B.2's !x: a correlated bag reads what the enclosing row bound
    "LIST n FROM Employee has EmployeeName n AND ALSO has Department d "
    "WHERE THE COUNT OF Employee [has Department: !d] > 2",
    "LIST n, c FROM Employee has EmployeeName n AND ALSO has Department d "
    "AND ALSO THE COUNT OF Employee [has Department: !d] AS c",
    # OR OTHERWISE is a union over what the left started from, not over what it admitted
    "THE COUNT OF Employee [has Department: 'ENG'] OR OTHERWISE [has Department: 'HR']",
    "LIST n FROM Employee has EmployeeName n AND ALSO ([has Department: 'HR'] OR OTHERWISE [has EmployeeSalary > 150000])",
    # a union at the head is a front expression the steps continue from; its normal form
    # keeps the parentheses (the compiler refused card_games/346's without them)
    "LIST n FROM (Employee BUT NOT [has Department: 'ENG'] OR OTHERWISE Employee [has EmployeeSalary > 150000]) "
    "has EmployeeName n",
    "LIST n, d FROM DISTINCT (Employee [has EmployeeGender: 'F'] OR OTHERWISE Employee [has Department: 'HR']) "
    "has EmployeeName n AND ALSO has Department has DepartmentCode d",
]


# There is no list of known departures here any more. Both of conquer-2026 section 14's
# departures are computed by the reference itself, so a query where the compiler applied one
# simply agrees. The one thing still reported as known is mechanical and comes from the
# reference: an ordered cut that fell on rows tying on the sort key, where no engine promises
# which survives. A label list was a list of things someone noticed once, and it hid a real
# bug for a day (finding 108).


def _cell(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, int):
        return float(v)
    if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
        try:                                   # a gathered bag: order is not promised
            return tuple(sorted((str(_cell(x)) for x in json.loads(v))))
        except ValueError:
            return v
    return v


def canon(rows):
    out = [tuple(_cell(v) for v in r) for r in rows]
    return sorted(out, key=lambda t: tuple(str(x) for x in t))


def primer_queries():
    text = open(os.path.join(HERE, "..", "primer.md")).read()
    for block in re.findall(r"```conquer\n(.*?)```", text, re.S):
        q = "\n".join(l for l in block.splitlines() if not l.strip().startswith("--")).strip()
        if q:
            yield q


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (os.path.exists(MODEL) and os.path.exists(DB)):
        print("fixture missing: run ./run-tests.sh first")
        return 2

    model = json.load(open(MODEL))
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    lex, em = parser_mod.Lexicon(model), sql_mod.Emitter(model)
    ref = ref_mod.Reference(model, conn, lex)

    sources = [("extra", q, None) for q in EXTRA]
    sources += [("primer", q, None) for q in primer_queries()]
    try:
        import test_fanout
        for name, q, expect in test_fanout.CASES:
            truth = expect[1] if expect[0] == "same_as" else None
            sources.append(("fanout: " + name, q, truth))
    except ImportError:
        pass

    agree = differ = unsupported = compiler_refused = known = gaps = 0
    nf_agree = nf_differ = nf_skipped = 0
    perm_agree = perm_differ = perm_skipped = 0
    for label, q, truth in sources:
        if args.only and args.only.lower() not in (label + q).lower():
            continue
        try:
            block, sql, params = driver.transpile(model, q, lex, em)
            got = canon(conn.execute(sql, params).fetchall())
        except Exception as e:                                          # noqa: BLE001
            compiler_refused += 1
            if args.verbose:
                print("skip  %-50s compiler: %s" % (label[:50], str(e)[:50]))
            # Refusal soundness. A judgement refusal sits on top of an emission: under
            # --permissive the judgements become notes and the SQL comes out. That SQL is a
            # claim about P as published, so it is checked against the reference under the
            # 1992 semantics -- if it differs, a real emission defect is hiding behind the
            # refusal, where nothing else would ever look at it.
            try:
                _, psql, pparams = driver.transpile(model, q, lex, em, permissive=True)
                pgot = canon(conn.execute(psql, pparams).fetchall())
                ref92 = ref_mod.Reference(model, conn, lex, semantics="1992")
                pwant = canon(ref92.query(parser_mod.Parser(lex, q).parse_query()))
            except ref_mod.Unsupported:
                perm_skipped += 1
                continue
            except Exception as e:                                      # noqa: BLE001
                perm_skipped += 1
                if args.verbose:
                    print("      permissive not checkable: %s: %s" % (type(e).__name__, str(e)[:90]))
                continue
            if pgot == pwant:
                perm_agree += 1
                print("ok    %-50s permissive SQL is what P says" % label[:50])
            else:
                perm_differ += 1
                print("DIFF  %s\n        (permissive) %s\n        compiler  %s\n        P (1992)  %s"
                      % (label, q[:100], str(pgot[:3])[:110], str(pwant[:3])[:110]))
            continue
        try:
            ext, rest, lex2, _ = driver.expand_definitions(model, q, lex)
            r = ref if ext is model else ref_mod.Reference(ext, conn, lex2)
            want = canon(r.query(parser_mod.Parser(lex2 or lex, rest).parse_query()))
        except ref_mod.Unsupported as e:
            unsupported += 1
            if args.verbose:
                print("--    %-50s reference: %s" % (label[:50], str(e)[:60]))
            continue
        except Exception as e:                                          # noqa: BLE001
            differ += 1
            print("FAIL  %-50s reference crashed: %s: %s" % (label[:50], type(e).__name__,
                                                             str(e)[:60]))
            continue
        if got == want and q in GAPS:
            differ += 1
            print("CLOSED %s\n        agrees with the reference now: remove it from GAPS (%s)"
                  % (label, GAPS[q]))
            continue
        if got != want and q in GAPS:
            gaps += 1
            print("gap   %-50s %s" % (label[:50], GAPS[q]))
            continue
        if got == want:
            agree += 1
            print("ok    %-50s %d row(s)" % (label[:50], len(got)))
            # The normal form (section 8). Two queries with the same normal form must mean
            # the same thing; the cheapest half of that claim is that a query and its own
            # normal form do. Round-trip tested until now; checked against P here.
            try:
                nf = driver.normalise(model, q, lex)
                ext2, rest2, lex3, _ = driver.expand_definitions(model, nf, lex)
                r2 = ref if ext2 is model else ref_mod.Reference(ext2, conn, lex3)
                nf_want = canon(r2.query(parser_mod.Parser(lex3 or lex, rest2).parse_query()))
            except ref_mod.Unsupported:
                nf_skipped += 1
            except Exception as e:                                      # noqa: BLE001
                nf_differ += 1
                print("DIFF  %s\n        normal form does not parse or evaluate: %s\n        %s"
                      % (label, str(e)[:100], q[:140]))
                if args.verbose:
                    import traceback; traceback.print_exc()
            else:
                if nf_want == want:
                    nf_agree += 1
                else:
                    nf_differ += 1
                    print("DIFF  %s\n        normal form means something else\n        %s\n"
                          "        query     %s\n        normal    %s"
                          % (label, nf[:140], str(want[:3])[:110], str(nf_want[:3])[:110]))
        elif r.tied_cut:
            known += 1
            print("known %-50s an ordered cut on a tie has no defined answer" % label[:50])
        else:
            differ += 1
            print("DIFF  %s\n        %s\n        compiler  %s\n        reference %s"
                  % (label, q[:100], str(got[:3])[:110], str(want[:3])[:110]))
            if truth:
                t = canon(conn.execute(truth).fetchall())
                print("        truth     %s  <- %s agrees with it"
                      % (str(t[:3])[:110], "compiler" if t == got else
                         "reference" if t == want else "neither"))

    total = agree + differ + unsupported + compiler_refused + known + gaps
    print("\n%d queries: %d agree, %d known departures from P, %d tracked gaps, %d DIFFER, "
          "%d outside the reference's scope, %d refused by the compiler"
          % (total, agree, known, gaps, differ, unsupported, compiler_refused))
    print("normal form: %d of %d agreeing queries mean the same as their normal form, "
          "%d DIFFER, %d outside scope" % (nf_agree, agree, nf_differ, nf_skipped))
    print("refusals: %d permissive emissions match P as published, %d DIFFER, %d not checkable"
          % (perm_agree, perm_differ, perm_skipped))
    return 1 if (differ or nf_differ or perm_differ) else 0


if __name__ == "__main__":
    sys.exit(main())
