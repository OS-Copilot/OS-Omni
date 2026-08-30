#!/bin/bash
# Restore working VM storage from a known-good golden storage copy.
# Example:
#   bash platforms/windows/scripts/reset_windows_storage.sh --source-dir /mnt/d/path/to/golden

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."
HELLOWORLD_DIR="$WINDOWS_DIR/../.."
ENV_FILE="$HELLOWORLD_DIR/.env"

SOURCE_DIR="${HELLOWORLD_WINDOWS_GOLDEN_STORAGE:-}"
TARGET_DIR="${VM_STORAGE_DIR:-}"
CONTAINER_NAME="helloworld_windows_vm"
STOP_CONTAINER=true
SHOW_PROGRESS=true
DOCKER_BIN="docker"

if [ -f "$ENV_FILE" ] && [ -z "$TARGET_DIR" ]; then
  TARGET_DIR=$(grep -E '^VM_STORAGE_DIR=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
fi

TARGET_DIR="${TARGET_DIR:-$WINDOWS_DIR/vm/storage}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-dir)
      SOURCE_DIR="$2"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    --container-name)
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --stop-container)
      STOP_CONTAINER="$2"
      shift 2
      ;;
    --show-progress)
      SHOW_PROGRESS="$2"
      shift 2
      ;;
    --help)
      cat <<'EOF'
Usage: reset_windows_storage.sh --source-dir <path> [options]

Options:
  --source-dir <path>             Known-good golden storage directory (required)
  --target-dir <path>             Working storage directory (default: VM_STORAGE_DIR or platforms/windows/vm/storage)
  --container-name <name>         Running container to stop before reset (default: helloworld_windows_vm)
  --stop-container <true|false>   Stop container before syncing (default: true)
  --show-progress <true|false>    Show rsync progress bar (default: true)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [ -z "$SOURCE_DIR" ]; then
  echo "Error: --source-dir is required."
  exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
  echo "Error: source dir does not exist: $SOURCE_DIR"
  exit 1
fi

if [ ! -f "$SOURCE_DIR/data.img" ]; then
  echo "Error: source dir does not look like VM storage (missing data.img): $SOURCE_DIR"
  exit 1
fi

mkdir -p "$TARGET_DIR"

SRC_REAL=$(realpath "$SOURCE_DIR")
DST_REAL=$(realpath "$TARGET_DIR")
if [ "$SRC_REAL" = "$DST_REAL" ]; then
  echo "Source and target are the same path, nothing to do."
  exit 0
fi

if [ "$STOP_CONTAINER" = true ]; then
  if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
    if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
      DOCKER_BIN="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
    fi
  fi
  "$DOCKER_BIN" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

echo "=== HelloWorld Windows Storage Reset ==="
echo "Source (golden): $SRC_REAL"
echo "Target (working): $DST_REAL"

RSYNC_ARGS=(-a --delete)
if [ "$SHOW_PROGRESS" = true ]; then
  RSYNC_ARGS+=(--info=progress2)
fi

rsync "${RSYNC_ARGS[@]}" "${SRC_REAL}/" "${DST_REAL}/"

SRC_SIZE=$(wc -c < "$SRC_REAL/data.img")
DST_SIZE=$(wc -c < "$DST_REAL/data.img")

if [ "$SRC_SIZE" != "$DST_SIZE" ]; then
  echo "Reset completed but size mismatch detected:"
  echo "  source data.img: $SRC_SIZE"
  echo "  target data.img: $DST_SIZE"
  exit 1
fi

echo ""
echo "Storage reset completed successfully."
echo "Working storage is now synchronized from golden source."
