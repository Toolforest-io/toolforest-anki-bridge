#!/usr/bin/env bash
# Symlink the add-on source into the local Anki addons folder for development.
# Usage: link.sh [anki_base_dir]   (defaults to the macOS location)
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
src="$repo_root/anki-addon/src/toolforest_bridge"
base="${1:-$HOME/Library/Application Support/Anki2}"
addons="$base/addons21"

[ -d "$addons" ] || { echo "Anki addons dir not found: $addons" >&2; exit 1; }
target="$addons/toolforest_bridge"
[ -e "$target" ] && { echo "Already exists: $target" >&2; exit 1; }
ln -s "$src" "$target"
echo "Linked $target -> $src. Restart Anki to load."
