#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "Local Event Photo Prep requires Python 3.10 or newer. Your macOS Python is too old."
  echo "Install Python 3.12 with: brew install python@3.12"
  echo "Then run ./install_macos.sh again."
  exit 1
fi

if [ -d ".venv" ] && [ -f ".venv/bin/pip" ]; then
  EXPECTED_INTERPRETER="$PROJECT_DIR/.venv/bin/python"
  if ! head -n 1 ".venv/bin/pip" | grep -F "$EXPECTED_INTERPRETER" >/dev/null 2>&1; then
    BACKUP_NAME=".venv-moved-$(date +%Y%m%d-%H%M%S)"
    mv .venv "$BACKUP_NAME"
    echo "Moved a virtual environment copied from another checkout to $BACKUP_NAME"
  fi
fi

if [ -d ".venv" ] && ! .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
  BACKUP_NAME=".venv-old-$(date +%Y%m%d-%H%M%S)"
  mv .venv "$BACKUP_NAME"
  echo "Moved the incompatible environment to $BACKUP_NAME"
fi

"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[all]'
PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" .venv/bin/event-photo-prep doctor
if ! command -v exiftool >/dev/null 2>&1; then
  echo
  echo "Recommended metadata fallback is not installed: ExifTool"
  echo "Install it with: brew install exiftool"
fi
echo
echo "Installed Local Event Photo Prep from $PROJECT_DIR"
echo "Launch with: ./run_event_photo_prep.sh"
echo "Test a RAW file with: .venv/bin/event-photo-prep doctor /path/to/sample.RAF"
