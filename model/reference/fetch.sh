#!/bin/sh
# Restore the source that is downloaded rather than authored here. The analysis notes in this
# folder are authored here and versioned; the metamodel they cite is not -- it is fetched.
#
#   the metamodel  NORMA's ORM2Core.xsd and friends, zlib/libpng licence -- see
#                  orm-metamodel.md for the licence text and what each file is
set -e
here=$(cd "$(dirname "$0")" && pwd)

mkdir -p "$here/orm-metamodel"
base="https://raw.githubusercontent.com/ormsolutions/NORMA/main"
for f in "ORMModel/ObjectModel/ORM2Core.xsd:ORM2Core.xsd" \
         "ORMModel/Load/ORM2Root.xsd:ORM2Root.xsd" \
         "Documentation/ORMCoreMetaModel.orm:ORMCoreMetaModel.orm" \
         "Documentation/OrmMetaModel.orm:OrmMetaModel.orm"; do
  src=${f%%:*}; dst=${f##*:}
  [ -f "$here/orm-metamodel/$dst" ] || {
    echo "fetch  $dst"
    curl -sfL -o "$here/orm-metamodel/$dst" "$base/$src"
  }
done
ls -la "$here/orm-metamodel"
