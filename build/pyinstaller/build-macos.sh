#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV_PYTHON="$ROOT/.venv/bin/python"
SPEC_FILE="$ROOT/build/pyinstaller/SongWalk.spec"
DIST_PATH="$ROOT/build/pyinstaller/dist/macos"
WORK_PATH="$ROOT/build/pyinstaller/build/macos"

if [ ! -x "$VENV_PYTHON" ]; then
  "$PYTHON" -m venv "$ROOT/.venv"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROOT/requirements.txt" -r "$ROOT/build/pyinstaller/requirements.txt"

mkdir -p "$DIST_PATH" "$WORK_PATH"

"$VENV_PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_PATH" \
  --workpath "$WORK_PATH" \
  "$SPEC_FILE"

printf '\nBuild complete.\n'
printf 'Executable folder: %s\n' "$DIST_PATH/SongWalk"
printf 'Run: %s\n' "$DIST_PATH/SongWalk/SongWalk"
