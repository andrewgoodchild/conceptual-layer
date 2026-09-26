#!/bin/sh
# Reverse engineer BIRD mini-dev's eleven databases into bench/models/, which every BIRD
# experiment reads, and rebuild the semantic-layer arms' merged models from their fragments.
set -e
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
bird=${1:-$here/bird}
dbs="$bird/minidev/MINIDEV/dev_databases"

[ -d "$dbs" ] || "$here/fetch.sh" "$bird"
mkdir -p "$here/models"

# Every dev database, with rule 9 applied (--infer-fks) and the value domains the data
# supports put on the value types (--infer-domains), so the schema listing tells a query
# author how a code is spelled instead of leaving them to probe for it.
# debit_card_specializing declares no
# foreign keys at all, and without the guess half its questions cannot be asked. Each
# inferred key is listed in the database's report as the guess it is.
#
# --infer-enforced checks each declared foreign key against the data and marks the ones no
# row breaks, which lets the compiler drop the join that would have checked the referent
# exists and the join that would have fetched back a value already in hand. Measured at 26%
# of the inner joins in the recorded corpus with 0 of 1,580 answers moved (finding 131). It
# changes the emitted SQL for most queries, so the first rebuild after adding it needs
# `corpus.py --update` once; it does not change what any of them answer.
for db in "$dbs"/*/; do
  db=$(basename "$db")
  python3 "$root/reverse/reverse.py" "$dbs/$db/$db.sqlite" -o "$here/models" -n "$db" \
          --infer-fks --infer-domains --infer-enforced || true
done

# The semantic-layer arms read a merged model, not the base one. Rebuilt from the tracked
# fragments here so a clone can reproduce those arms too.
"$root/bench/pilot/semantic/build.sh" || echo "semantic models not rebuilt (see the output above)"
