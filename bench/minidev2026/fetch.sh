#!/bin/sh
# Fetch the October 2026 mini-dev questions, pinned by revision and checksum. They go beside
# the 2025 file, which every other BIRD number here is measured on; the databases are the
# ones bench/fetch.sh gets, and `pins.json` records their checksums.
set -e
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/../bird/mini_dev_1024}
mkdir -p "$out"

revision=5b256b5a9c17478f06ed6912612e9a14d17065c8
sha256=926af2a0d1b47e5d0d15a7aa8a34d4721007f4550a881555b6a89496b54a2606

[ -f "$out/mini_dev_sqlite.jsonl" ] || curl -sfL -o "$out/mini_dev_sqlite.jsonl" \
  "https://huggingface.co/datasets/birdsql/bird_mini_dev/resolve/$revision/data/mini_dev_sqlite.jsonl"

got=$( (command -v sha256sum >/dev/null && sha256sum "$out/mini_dev_sqlite.jsonl" ||
        shasum -a 256 "$out/mini_dev_sqlite.jsonl") | cut -d' ' -f1)
if [ "$got" != "$sha256" ]; then
  echo "$out/mini_dev_sqlite.jsonl: sha256 $got, expected $sha256" >&2
  exit 1
fi
echo "questions: $out/mini_dev_sqlite.jsonl"
