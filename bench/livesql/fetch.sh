#!/bin/sh
# Fetch LiveSQLBench Large-v1 metadata: 480 questions over 18 PostgreSQL databases of
# ~54 tables and ~986 columns each.  https://huggingface.co/datasets/birdsql/livesqlbench-large-v1
#
# What this pulls is everything the public release carries: the questions, each database's
# schema, its column meanings and its hierarchical knowledge base. About 7 MB.
#
# What it does NOT pull, because the public release withholds it: `sol_sql`, `test_cases`
# and `external_knowledge`. Those arrive by return of email --
#   to bird.bench25@gmail.com, subject "[livesqlbench-large-v1 GT&Test Cases]"
# -- and drop into this directory as the file the auto-reply sends.
#
# Nor does it pull the databases themselves: those are PostgreSQL dumps on Google Drive,
# linked from the dataset card, and need a running server. Everything the scouting run does
# works from the schema text alone.
set -e
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/data}
repo=https://huggingface.co/datasets/birdsql/livesqlbench-large-v1/resolve/main
mkdir -p "$out"

[ -f "$out/livesqlbench_large_v1_data.jsonl" ] || \
  curl -sfL -o "$out/livesqlbench_large_v1_data.jsonl" "$repo/livesqlbench_large_v1_data.jsonl"
[ -f "$out/README.md" ] || curl -sfL -o "$out/README.md" "$repo/README.md"

for db in $(python3 -c "
import json,sys
seen=[]
for line in open('$out/livesqlbench_large_v1_data.jsonl'):
    d=json.loads(line)
    if d['selected_database'] not in seen: seen.append(d['selected_database'])
print(' '.join(seen))
"); do
  mkdir -p "$out/$db"
  for f in "${db}_schema.txt" "${db}_column_meaning_base.json" "${db}_kb.jsonl"; do
    [ -f "$out/$db/$f" ] || curl -sfL -o "$out/$db/$f" "$repo/$db/$f"
  done
done
echo "questions: $(wc -l < "$out/livesqlbench_large_v1_data.jsonl" | tr -d ' ')  databases: $(ls -d "$out"/*/ | wc -l | tr -d ' ')"
