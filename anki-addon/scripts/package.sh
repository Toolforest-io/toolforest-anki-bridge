#!/usr/bin/env bash
# Build dist/toolforest_bridge.ankiaddon — a zip of the add-on package CONTENTS
# (no top-level folder), which is what AnkiWeb and "Install from file" expect.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
src="$repo_root/anki-addon/src/toolforest_bridge"
dist="$repo_root/dist"
out="$dist/toolforest_bridge.ankiaddon"

mkdir -p "$dist"
rm -f "$out"

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
cp -R "$src/" "$staging/"
find "$staging" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$staging" -name '*.pyc' -delete
# meta.json is local state and must never ship
rm -f "$staging/meta.json"

(cd "$staging" && zip -r -q "$out" .)
echo "Built $out ($(du -h "$out" | cut -f1))"
