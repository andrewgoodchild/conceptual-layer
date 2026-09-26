#!/bin/sh
# Fetch the BIRD mini-dev benchmark: 500 questions with gold SQL over 11 SQLite databases.
#   questions  https://huggingface.co/datasets/birdsql/bird_mini_dev
#   databases  https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip   (800 MB)
set -e
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/bird}
mkdir -p "$out"

[ -f "$out/mini_dev_sqlite.json" ] || curl -sfL -o "$out/mini_dev_sqlite.json" \
  "https://huggingface.co/datasets/birdsql/bird_mini_dev/resolve/main/data/mini_dev_sqlite-00000-of-00001.json"

if [ ! -d "$out/minidev" ]; then
  echo "fetching minidev.zip (800 MB) ..."
  curl -sfL -o "$out/minidev.zip" "https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip"
  unzip -q -o "$out/minidev.zip" -d "$out"
  rm -f "$out/minidev.zip"
fi
echo "databases: $out/minidev/MINIDEV/dev_databases"
