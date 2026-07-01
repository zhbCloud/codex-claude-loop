#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
SKILL_ROOT="${SCRIPT_DIR:h}"
PYTHON_SCRIPT="${1:-}"

if [[ -z "$PYTHON_SCRIPT" ]]; then
  print -u2 "Missing Python script name."
  exit 2
fi

shift
RUNTIME_SCRIPT="$SKILL_ROOT/scripts/$PYTHON_SCRIPT"

if [[ ! -f "$RUNTIME_SCRIPT" ]]; then
  print -u2 "Missing shared Python runtime: $RUNTIME_SCRIPT"
  exit 1
fi

find_python() {
  local candidate
  local -a candidates
  candidates=()
  if [[ -n "${PYTHON:-}" ]]; then
    candidates+=("$PYTHON")
  fi
  candidates+=(python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python)

  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  print -u2 "Python 3.10+ was not found. Install Python or set PYTHON to a Python 3.10+ executable."
  exit 1
fi

exec "$PYTHON_BIN" "$RUNTIME_SCRIPT" "$@"
