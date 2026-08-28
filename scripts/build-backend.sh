#!/usr/bin/env bash
# Builds the frozen backend and stages it where electron-builder expects it.
#
# WHY IT BUILDS FROM A COPY IN /tmp: this project lives under ~/Desktop,
# which is iCloud-synced. PyInstaller reads every file in the venv, and on
# a cold iCloud cache those reads stall long enough that the build appears
# to hang indefinitely (measured: 15+ minutes with no output, vs under 20
# seconds from local disk). Building from a local copy sidesteps it
# entirely.
#
# WHY IT CALLS `python -m PyInstaller` RATHER THAN THE `pyinstaller` SCRIPT:
# pip-installed console scripts hardcode an absolute shebang pointing at
# the venv they were installed into. Running the COPY's `pyinstaller`
# script would therefore re-execute via that shebang back into the
# ORIGINAL iCloud venv -- silently undoing the copy. Invoking the copied
# interpreter directly is what actually escapes it.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
BUILD_DIR="/tmp/cache-backend-build"
VENV="$HOME/.cache-venvs/cache-backend"
STAGE_DIR="$PROJECT_ROOT/desktop/resources/backend"

if [ ! -x "$VENV/bin/python" ]; then
  echo "error: expected a venv at $VENV" >&2
  echo "create it with:" >&2
  echo "  python3.14 -m venv $VENV" >&2
  echo "  $VENV/bin/pip install -r $BACKEND_DIR/requirements.txt" >&2
  exit 1
fi

echo "==> staging backend source in $BUILD_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp -R "$BACKEND_DIR/app" "$BACKEND_DIR/alembic" "$BUILD_DIR/"
cp "$BACKEND_DIR/run_backend.py" "$BACKEND_DIR/backend.spec" "$BACKEND_DIR/alembic.ini" "$BUILD_DIR/"

echo "==> freezing with PyInstaller"
cd "$BUILD_DIR"
"$VENV/bin/python" -m PyInstaller backend.spec --noconfirm

echo "==> staging build output into $STAGE_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$(dirname "$STAGE_DIR")"
cp -R "$BUILD_DIR/dist/cache-backend" "$STAGE_DIR"

echo "==> done: $STAGE_DIR/cache-backend"
