#!/usr/bin/env bash
# Update vendored third-party libraries from PyPI.
#
# Downloads the pinned wheels, extracts the Python files that the project
# actually uses, and refreshes the upstream license files.
# Run from the repository root.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VENDOR="$ROOT/vendor"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- pinned versions (keep in sync with vendor/README.md) -------------
MSGPACK_VERSION="1.1.2"
FLATBUFFERS_VERSION="25.12.19"

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
fetch_license() { # fetch_license URL DEST
  local url="$1" dest="$2"
  curl -fsSL "$url" -o "$dest" || {
    printf 'WARNING: could not fetch %s (network off?)\n' "$url"
    return 1
  }
  printf '  license: %s\n' "$dest"
}

info "Updating msgpack $MSGPACK_VERSION"
python3 -m pip download --no-deps --no-binary :all: --quiet \
  "msgpack==$MSGPACK_VERSION" -d "$TMP/msgpack_src"
(cd "$TMP/msgpack_src" && tar xf ./*.tar.gz && cp -r msgpack-*/msgpack "$TMP/msgpack")
# keep only the modules this project imports
mkdir -p "$VENDOR/msgpack"
cp "$TMP/msgpack"/{__init__,ext,fallback,exceptions}.py "$VENDOR/msgpack/"
fetch_license \
  "https://raw.githubusercontent.com/msgpack/msgpack-python/v$MSGPACK_VERSION/COPYING" \
  "$VENDOR/msgpack/COPYING" || curl -fsSL \
    "https://raw.githubusercontent.com/msgpack/msgpack-python/master/COPYING" -o "$VENDOR/msgpack/COPYING"

info "Updating flatbuffers $FLATBUFFERS_VERSION"
python3 -m pip download --no-deps --quiet \
  "flatbuffers==$FLATBUFFERS_VERSION" -d "$TMP/fb_wheel"
(cd "$TMP/fb_wheel" && unzip -q -o ./*.whl -d "$TMP/fb")
mkdir -p "$VENDOR/flatbuffers"
cp "$TMP/fb/flatbuffers"/*.py "$VENDOR/flatbuffers/"
fetch_license \
  "https://raw.githubusercontent.com/google/flatbuffers/v$FLATBUFFERS_VERSION/LICENSE" \
  "$VENDOR/flatbuffers/LICENSE" || true

# strip bytecode cached during previous runs
find "$VENDOR" -name __pycache__ -type d -prune -exec rm -rf {} +

info "Done. Reminder: run 'ruff check --exclude vendor/ .' and update vendor/README.md versions if changed."
info "Testing bootstrap import:"
python3 - <<PY
import sys
sys.path.insert(0, "$VENDOR")
import msgpack, flatbuffers
print(f"  msgpack {msgpack.__version__}  flatbuffers ok")
PY