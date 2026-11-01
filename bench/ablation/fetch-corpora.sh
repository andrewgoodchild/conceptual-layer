#!/bin/sh
# AdventureWorks and MusicBrainz's sample, as text and data, pinned; corpora.py builds them.
# Nothing fetched here is run. MusicBrainz's DDL is from master, pinned by checksum, so it goes
# stale when upstream changes: take the commit of the dump's SCHEMA_SEQUENCE then.
set -e
here=$(cd "$(dirname "$0")" && pwd)
src=${1:-$here/work/bar-source}
out=$here/work
mkdir -p "$src/aw" "$src/mb" "$out/bar" "$out/bar-blind"

get() { [ -f "$2" ] || curl -sSL -o "$2" "$1"; }
check() { echo "$2  $1" | shasum -a 256 -c -; }

get https://github.com/microsoft/sql-server-samples/releases/download/adventureworks/AdventureWorks-oltp-install-script.zip "$src/aw.zip"
check "$src/aw.zip" 58962e94ea386ef7cd3d8a08211bfd42a79d9b81bdd68fd4b6b0051de6c5bd42
base=https://raw.githubusercontent.com/metabrainz/musicbrainz-server/master/admin/sql
get https://data.metabrainz.org/pub/musicbrainz/data/sample/20261001-000001/mbdump-sample.tar.xz "$src/mb.tar.xz"
check "$src/mb.tar.xz" 1adbe1da24e28ad0e88e9dcfb2b28c8a060cd32c9f4d70fbebc3bd2c6977e993
get $base/CreateTables.sql "$src/mb/CreateTables.sql"
check "$src/mb/CreateTables.sql" 92d1981a0d4f5032bca1565d27fafa8a0eac4d11b7f34feab71bfde8a00ecb13
get $base/CreatePrimaryKeys.sql "$src/mb/CreatePrimaryKeys.sql"
check "$src/mb/CreatePrimaryKeys.sql" 7875b55ebab0e99326bfc2ed6d12289e912a137e67d8c3f4269cbb16e021016e
get $base/CreateFKConstraints.sql "$src/mb/CreateFKConstraints.sql"
check "$src/mb/CreateFKConstraints.sql" c26fe5064af462526f9c9035e526a93d8b79800b8aa8ff116ad26855c1fe540c

unzip -qo "$src/aw.zip" -d "$src/aw"
tar -xJf "$src/mb.tar.xz" -C "$src/mb"
python3 "$here/corpora.py" adventureworks "$src/aw" "$out/bar/adventureworks.sqlite"
python3 "$here/corpora.py" musicbrainz "$src/mb" "$out/bar/musicbrainz.sqlite"
for db in adventureworks musicbrainz; do
    python3 "$here/corpora.py" destroy "$out/bar/$db.sqlite" "$out/bar-blind/$db.sqlite"
done
