#!/bin/sh
# Fetch the sample databases the test cases run against. They are not committed -- Northwind
# alone is 24 MB, and both are better taken from source.
#
#   Chinook    https://github.com/lerocha/chinook-database     digital music store, 11 tables
#   Northwind  https://github.com/jpwhite3/northwind-SQLite3   the classic Microsoft sample
set -e
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$here/db"

fetch() {
  if [ -f "$here/db/$2" ]; then
    echo "have   $2"
  else
    echo "fetch  $2"
    curl -sfL -o "$here/db/$2" "$1"
  fi
}

fetch "https://github.com/lerocha/chinook-database/raw/master/ChinookDatabase/DataSources/Chinook_Sqlite.sqlite" chinook.sqlite
fetch "https://github.com/jpwhite3/northwind-SQLite3/raw/main/dist/northwind.db" northwind.db

for f in "$here"/db/*; do
  printf '%-16s %6s KB  ' "$(basename "$f")" "$(( $(wc -c < "$f") / 1024 ))"
  python3 -c "
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
t = [r[0] for r in c.execute(
    \"select name from sqlite_master where type='table' and name not like 'sqlite_%'\")]
rows = sum(c.execute('select count(*) from \\\"%s\\\"' % x).fetchone()[0] for x in t)
print('%d tables, %d rows' % (len(t), rows))" "$f"
done
