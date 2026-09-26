#!/bin/sh
# Reverse engineer each sample database, render its ORM diagram, and check every ConQuer
# query against its reference SQL.
set -e
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
out=${1:-$here/out}
xsd="$root/model/reference/orm-metamodel/ORM2Core.xsd"

[ -d "$here/db" ] || "$here/fetch.sh"
mkdir -p "$out"

for pair in chinook:Chinook northwind:Northwind; do
  name=${pair%%:*}
  db="$here/db/$name.sqlite"
  [ -f "$db" ] || db="$here/db/$name.db"

  echo
  echo "=== $name ==="
  python3 "$root/reverse/reverse.py" "$db" -o "$out" -n "$name"
  python3 "$root/model/validate.py" "$out/$name.ccm.json"

  # The XSD is NORMA's and is fetched rather than redistributed, so a clone may not have it.
  # Say so when skipping: a validation that silently does not run reads as one that passed.
  if ! [ -f "$xsd" ]; then
    echo "ORM2Core.xsd not here: skipping .orm schema validation (./model/reference/fetch.sh gets it)"
  elif ! command -v xmllint >/dev/null 2>&1; then
    echo "xmllint not found: skipping .orm schema validation"
  else
    python3 -c "
import sys, xml.etree.ElementTree as ET
ORM='http://schemas.neumont.edu/ORM/2006-04/ORMCore'
ET.register_namespace('orm', ORM)
r = ET.parse('$out/$name.orm').getroot()
open('$out/$name-model.xml','wb').write(ET.tostring(r.find('{%s}ORMModel' % ORM), encoding='utf-8'))"
    xmllint --noout --schema "$xsd" "$out/$name-model.xml"
  fi
  # The schema types ids as xs:ID and refs as xs:IDREF, but libxml2 does not resolve IDREFs
  # in schema mode -- and even when it does, IDREF cannot check that a reference points at
  # the right KIND of element. ormcheck covers what the schema cannot.
  python3 "$root/model/ormcheck.py" "$out/$name.orm"

  python3 "$root/render/orm_render.py" "$out/$name.ccm.json" -o "$out/$name.html"
  for cases in "$root/conquer/tests/cases/$name.cases" \
               "$root/conquer/tests/cases/$name-hard.cases"; do
    [ -f "$cases" ] || continue
    python3 "$root/conquer/tests/compare.py" "$out/$name.ccm.json" "$db" "$cases"
  done
done
