#!/usr/bin/env bash
# Works around a bug where `npm install` downloads Electron correctly but
# extract-zip silently fails to unpack it (see docs/ARCHITECTURE.md for why).
# Run this if `npm run dev` fails with "Electron failed to install correctly"
# or a `spawn ... ENOENT` error mentioning Electron.
set -euo pipefail
cd "$(dirname "$0")"

ZIP=$(ls -t ~/Library/Caches/electron/*/electron-v*-darwin-*.zip 2>/dev/null | head -1)
if [ -z "$ZIP" ]; then
  echo "No cached Electron zip found -- run 'npm install' first so it downloads." >&2
  exit 1
fi

echo "Extracting $ZIP with the system unzip (bypassing the buggy extract-zip)..."
rm -rf node_modules/electron/dist
mkdir -p node_modules/electron/dist
unzip -q "$ZIP" -d node_modules/electron/dist

# printf, not echo -- echo appends a trailing newline that corrupts the path
# Electron's launcher reads from this file.
printf 'Electron.app/Contents/MacOS/Electron' > node_modules/electron/path.txt

echo "Done. Verifying:"
node -e "console.log(require('electron'))"
