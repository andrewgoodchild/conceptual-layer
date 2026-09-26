#!/bin/sh
# Rebuild every semantic-layer model into bench/models/, from the fragments the modeller
# agents wrote. Run it after bench/run.sh, which builds the base models these merge into.
#
# Without this the four arms that use a semantic model (`conquer_sem`, and the arms derived
# from it) could not be reproduced from a clone: the merged models are outputs, so they are
# not tracked, and the fragments alone are not what the arms read.
set -e
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
models="$root/bench/models"

[ -d "$models" ] || { echo "run bench/run.sh first: $models does not exist"; exit 1; }
for frag in "$root"/bench/pilot/work/semantic/*/semantic.json; do
  db=$(basename "$(dirname "$frag")")
  echo "=== $db"
  python3 "$here/check.py" "$db" "$frag" "$models"
done
