#!/usr/bin/env python3
"""Run the shell examples in docs/ and README.md, so the documentation cannot rot quietly.

Every fenced `sh` block is treated as a script and run against the fixture `run-tests.sh`
builds. A block is *skipped* when it names something this cannot supply -- a placeholder path,
a download, a database of your own -- and the skips are printed, so a block that stops being
runnable is visible rather than silently unchecked.

    check-examples.py [-v] [--only SUBSTRING]

`cq` in the docs is the alias the pages define; it is provided here, so the examples can be
read and run exactly as written.
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, ".work")

# What this harness cannot supply: a database you have not got, a 800 MB download, a
# placeholder, or a command that writes outside the scratch directory.
SKIP = ("fetch.sh", "run-tests.sh", "examples/run.sh", "bench/", "MODEL.ccm.json", "DB.sqlite",
        "yours.sqlite", "nokeys.sqlite", "one.sqlite", "model.html", "MODEL.orm",
        "edited.ccm.json", "reverse/reverse.py", "ormcheck.py", "sqlite3 ")

PRELUDE = """
set -e
cd %s
cq() { python3 conquer/conquer.py .work/company.ccm.json --db .work/company.sqlite "$@"; }
""" % ROOT

BLOCK = re.compile(r"```sh\n(.*?)```", re.S)


def blocks(path):
    text = open(path).read()
    for m in BLOCK.finditer(text):
        line = text[: m.start()].count("\n") + 1
        yield line, m.group(1)


def following(path, line, chars=1500):
    """The page's text just after the block at `line` -- where a shown refusal is quoted."""
    text = open(path).read().split("\n")
    return "\n".join(text[line - 1:line + 40])[:chars]


def runnable(body):
    for bad in SKIP:
        if bad in body:
            return bad
    return None


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if not os.path.exists(os.path.join(WORK, "company.ccm.json")):
        print("fixture missing: run ./run-tests.sh first (it builds %s)" % WORK)
        return 2

    paths = [os.path.join(ROOT, "README.md")] + [
        os.path.join(HERE, f) for f in sorted(os.listdir(HERE)) if f.endswith(".md")]
    passed = failed = skipped = 0
    for path in paths:
        rel = os.path.relpath(path, ROOT)
        if args.only and args.only.lower() not in rel.lower():
            continue
        for line, body in blocks(path):
            why = runnable(body)
            if why:
                skipped += 1
                if args.verbose:
                    print("skip  %s:%d  (mentions %r)" % (rel, line, why))
                continue
            run = subprocess.run(["sh", "-c", PRELUDE + body], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
            out = run.stdout.decode("utf-8", "replace")
            # Some blocks are meant to fail: the page shows the refusal underneath. Accept
            # one when the page quotes what came back, so the quote is checked too.
            first = (out.split("\n", 1)[0].replace("parse error: ", "")[:60]).strip()
            quoted = bool(first) and first in following(path, line)
            if run.returncode == 0 or quoted:
                passed += 1
                if args.verbose:
                    print("ok    %s:%d  %s" % (rel, line, body.strip().split("\n")[0][:60]))
            else:
                failed += 1
                print("FAIL  %s:%d\n%s" % (rel, line, out[-600:]))

    print("\n%d passed, %d failed, %d total (%d blocks skipped as not runnable here)"
          % (passed, failed, passed + failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
