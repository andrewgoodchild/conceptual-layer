#!/bin/sh
# Rebuild the fixture database, reverse engineer it, and run every query against the result.
# The whole pipeline, from CREATE TABLE to rows, in one command.
set -e
here=$(cd "$(dirname "$0")" && pwd)
root=$here
work=${1:-$here/.work}

mkdir -p "$work"
# Clear the previous run's outputs too. reverse.py exits 1 on blockers and this schema has
# one by design, so its failure is tolerated below -- with stale files left in place, a
# genuine crash would have been masked by the last good run's output.
rm -f "$work/company.sqlite" "$work/company.ccm.json" "$work/company.orm" \
      "$work/company.report.md" "$work/model-only.xml"
python3 -c "
import sqlite3, sys
c = sqlite3.connect('$work/company.sqlite')
c.executescript(open('$root/reverse/tests/company.sql').read())
c.commit()"

python3 "$root/reverse/reverse.py" "$work/company.sqlite" -o "$work" -n company || true
python3 "$root/model/validate.py" "$work/company.ccm.json"

# Validate the generated .orm against NORMA's own XSD. ORM2Core declares ORMModel as a
# global element; the ORM2 document root lives in the ORMRoot namespace, so validate the
# model element on its own.
#
# The schema is fetched rather than redistributed (it is NORMA's, under zlib), so a fresh
# clone does not have it. Skip with a note saying how to get it: a suite that fails on a
# clean checkout because of a missing download teaches the wrong lesson on the first run.
xsd="$root/model/reference/orm-metamodel/ORM2Core.xsd"
if ! [ -f "$xsd" ]; then
  echo "ORM2Core.xsd not here: skipping .orm schema validation (./model/reference/fetch.sh gets it)"
elif command -v xmllint >/dev/null 2>&1; then
  python3 -c "
import sys, xml.etree.ElementTree as ET
ORM = 'http://schemas.neumont.edu/ORM/2006-04/ORMCore'
ET.register_namespace('orm', ORM)
root = ET.parse('$work/company.orm').getroot()
open('$work/model-only.xml','wb').write(ET.tostring(root.find('{%s}ORMModel' % ORM), encoding='utf-8'))"
  xmllint --noout --schema "$xsd" "$work/model-only.xml"
else
  echo "xmllint not found: skipping .orm schema validation"
fi
python3 "$root/conquer/conquer.py" "$work/company.ccm.json" --db "$work/company.sqlite" \
        -f "$root/conquer/tests/queries.cq"

echo
python3 "$root/reverse/tests/test_scenarios.py"

echo
python3 "$root/reverse/tests/test_rules.py"

echo
python3 "$root/reverse/tests/test_population.py"

echo
python3 "$root/reverse/tests/test_inference.py"

echo
python3 "$root/conquer/tests/test_operators.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_verbalise.py" --model "$work/company.ccm.json"

echo
python3 "$root/conquer/tests/test_normalise.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_lowered_valid.py" --model "$work/company.ccm.json"

echo
python3 "$root/conquer/tests/test_errors.py" --model "$work/company.ccm.json"

echo
python3 "$root/conquer/tests/test_elision.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_mapping.py"

echo
python3 "$root/conquer/tests/test_identification.py"

echo
python3 "$root/conquer/tests/test_derived.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_metamorphic.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/model/tests/test_validate.py"

echo
python3 "$root/model/tests/test_forml.py"

echo
python3 "$root/model/tests/test_abstract.py"

echo
python3 "$root/conquer/tests/test_fanout.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_spec.py"

echo
python3 "$root/conquer/tests/test_reference.py"

echo
python3 "$root/conquer/tests/test_window.py"

echo
python3 "$root/conquer/tests/test_annotate.py"

echo
python3 "$root/conquer/tests/test_json.py"

echo
python3 "$root/conquer/tests/test_binding.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_readonly.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_primer.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/conquer/tests/test_linking.py" --model "$work/company.ccm.json"

echo
python3 "$root/conquer/tests/test_constraints.py" \
        --model "$work/company.ccm.json" --db "$work/company.sqlite"

echo
python3 "$root/model/tests/test_ormcheck.py"

echo
python3 "$root/reverse/tests/test_ormlint.py"

echo
python3 "$root/model/tests/test_names.py"

echo
python3 "$root/docs/check-examples.py"

echo
python3 "$root/model/ormcheck.py" "$work/company.orm"

echo
python3 "$root/reverse/ormlint.py" "$work/company.ccm.json" --db "$work/company.sqlite" \
    || echo "(ormlint reported findings on the round-trip model -- see above)"

echo
# The MCP server, when the `mcp` package is installed; it says so and passes when it is not.
python3 "$root/mcp/tests/test_server.py"
