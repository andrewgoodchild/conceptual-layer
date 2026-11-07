#!/usr/bin/env python3
"""The comparisons PLAN.md fixed in advance.

A verdict of "wrong" is a flag. The catch rate is the share of wrong answers flagged, the
false-alarm rate the share of right ones flagged, and their difference is Youden's J, which
a checker who flags everything or nothing scores 0 on. An item without a verdict is not
flagged. The interval resamples whole questions, since the answers to one question are not
independent; the McNemar tests are bench/minidev2026/compare.py's. Per-item rows go to the
git-ignored results.json.
"""
import collections, importlib.util, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location(
    "october", os.path.join(ROOT, "bench/minidev2026/compare.py"))
october = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(october)

ARMS = ("plain", "readback")
RESAMPLES, SEED = 10000, 20261108


def flags(arm, items):
    out = {}
    for db in sorted({r["db_id"] for r in items}):
        for c in json.load(open(os.path.join(HERE, "work", arm, db, "checks.json"))):
            out[c.get("item")] = c.get("verdict") == "wrong"
    return {r["item"]: out.get(r["item"], False) for r in items}


def rates(items, f):
    wrong = [f[r["item"]] for r in items if r["label"] == "wrong"]
    ok = [f[r["item"]] for r in items if r["label"] == "ok"]
    catch = sum(wrong) / len(wrong) if wrong else 0.0
    alarm = sum(ok) / len(ok) if ok else 0.0
    return catch, alarm, catch - alarm


def main():
    items = json.load(open(os.path.join(HERE, "data", "key.json")))
    f = {arm: flags(arm, items) for arm in ARMS}
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump([dict(r, **{arm: f[arm][r["item"]] for arm in ARMS}) for r in items],
                  fh, indent=1)
    for arm in ARMS:
        catch, alarm, j = rates(items, f[arm])
        print("%-9s catch %5.1f%%  false alarm %5.1f%%  J %+5.1f" % (
            arm, 100 * catch, 100 * alarm, 100 * j))
    by_q = collections.defaultdict(list)
    for r in items:
        by_q[r["question_id"]].append(r)
    qids = sorted(by_q)

    def diff(sample):
        return 100 * (rates(sample, f["readback"])[2] - rates(sample, f["plain"])[2])

    rng, draws = random.Random(SEED), []
    for _ in range(RESAMPLES):
        draws.append(diff([r for q in (rng.choice(qids) for _ in qids) for r in by_q[q]]))
    draws.sort()
    lo, hi = draws[int(0.025 * RESAMPLES)], draws[int(0.975 * RESAMPLES) - 1]
    d = diff(items)
    shown = abs(d) >= 10 and (lo > 0 or hi < 0)
    print("\nprimary: J, readback minus plain, %+.1f points, 95%% interval %+.1f to %+.1f: %s"
          % (d, lo, hi, "a difference" if shown else "no difference shown"))
    print("\nsecondary")
    for label, name in (("wrong", "caught"), ("ok", "false alarms")):
        mine = [r["item"] for r in items if r["label"] == label]
        b = sum(1 for i in mine if f["readback"][i] and not f["plain"][i])
        c = sum(1 for i in mine if f["plain"][i] and not f["readback"][i])
        print("%-13s readback only %3d, plain only %3d, McNemar p = %.3f"
              % (name, b, c, october.mcnemar(b, c)))


if __name__ == "__main__":
    main()
