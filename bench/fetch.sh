#!/bin/sh
# Fetch the BIRD mini-dev benchmark: 500 questions with gold SQL over 11 SQLite databases.
#   questions  https://huggingface.co/datasets/birdsql/bird_mini_dev
#   databases  https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip   (800 MB)
#
# The questions are the 2025-07-04 annotations, pinned by revision and checksum: every BIRD
# number here was measured on them, and the October 2026 release is close to a new test set
# under the same ids, so taking the current file would score recorded answers against other
# questions. The database zip has no revision to pin.
set -e
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/bird}
mkdir -p "$out"

revision=38818fcbc46038129592680c51b2c8b597aac27c
sha256=88ceb0710163cae46a256ecea8f0a8c98286599530b60587fda5c3cfe57d45d2

[ -f "$out/mini_dev_sqlite.json" ] || curl -sfL -o "$out/mini_dev_sqlite.json" \
  "https://huggingface.co/datasets/birdsql/bird_mini_dev/resolve/$revision/archive/bird_mini_dev_2025-07-04/data/mini_dev_sqlite-00000-of-00001.json"

got=$( (command -v sha256sum >/dev/null && sha256sum "$out/mini_dev_sqlite.json" ||
        shasum -a 256 "$out/mini_dev_sqlite.json") | cut -d' ' -f1)
if [ "$got" != "$sha256" ]; then
  echo "$out/mini_dev_sqlite.json is not the 2025-07-04 annotations the numbers here were" >&2
  echo "measured on: sha256 $got, expected $sha256" >&2
  exit 1
fi

if [ ! -d "$out/minidev" ]; then
  echo "fetching minidev.zip (800 MB) ..."
  curl -sfL -o "$out/minidev.zip" "https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip"
  unzip -q -o "$out/minidev.zip" -d "$out"
  rm -f "$out/minidev.zip"
fi
echo "databases: $out/minidev/MINIDEV/dev_databases"
