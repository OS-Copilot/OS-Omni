#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PLATFORM_PROFILE="${HELLOWORLD_SETUP_PLATFORM:-auto}"

if [[ "$PLATFORM_PROFILE" == "auto" ]]; then
  case "$(uname -s)" in
    Linux) PLATFORM_PROFILE="linux" ;;
    Darwin) PLATFORM_PROFILE="macos" ;;
    *) PLATFORM_PROFILE="base" ;;
  esac
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ "$PLATFORM_PROFILE" == "linux" && -x /usr/bin/python3 ]]; then
    PYTHON_BIN="/usr/bin/python3"
  else
    PYTHON_BIN="python3"
  fi
fi

REQ_FILE="$ROOT_DIR/requirements.txt"
case "$PLATFORM_PROFILE" in
  linux) REQ_FILE="$ROOT_DIR/requirements-linux.txt" ;;
  macos) REQ_FILE="$ROOT_DIR/requirements-macos.txt" ;;
  base) REQ_FILE="$ROOT_DIR/requirements.txt" ;;
  *)
    echo "Unsupported HELLOWORLD_SETUP_PLATFORM: $PLATFORM_PROFILE" >&2
    exit 2
    ;;
esac

echo "Root: $ROOT_DIR"
echo "Python: $PYTHON_BIN"
echo "Venv: $VENV_DIR"
echo "Platform profile: $PLATFORM_PROFILE"
echo "Requirements: $REQ_FILE"

if [[ -d "$VENV_DIR" ]]; then
  rm -rf "$VENV_DIR"
fi

VENV_ARGS=()
if [[ "$PLATFORM_PROFILE" == "linux" ]]; then
  VENV_ARGS+=(--system-site-packages)
  if [[ ! -f "$HOME/.Xauthority" ]]; then
    touch "$HOME/.Xauthority"
  fi
fi

"$PYTHON_BIN" -m venv "${VENV_ARGS[@]}" "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/pip" install -r "$REQ_FILE"

echo
echo "Environment created."
echo "Activate with:"
echo "  source .venv/bin/activate"
echo
echo "Doctor check:"
"$VENV_DIR/bin/python" "$ROOT_DIR/scripts/check_env.py" --platform "$PLATFORM_PROFILE" || true
