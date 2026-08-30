#!/bin/bash
# Create a lightweight Windows VM overlay storage directory.
# The golden data.img is mounted read-only as /storage.golden/data.img, while
# /storage/data.qcow2 stores only per-run writes.

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."
HELLOWORLD_DIR="$WINDOWS_DIR/../.."
ENV_FILE="$HELLOWORLD_DIR/.env"

SOURCE_DIR="${HELLOWORLD_WINDOWS_GOLDEN_STORAGE:-}"
TARGET_DIR="${VM_STORAGE_DIR:-}"
CONTAINER_NAME="helloworld_windows_vm"
WINDOWS_IMAGE="${HELLOWORLD_WINDOWS_IMAGE:-helloworld/windows-vm:latest}"
OVERWRITE=true
DOCKER_BIN="${DOCKER_BIN:-docker}"

if [ -f "$ENV_FILE" ]; then
  if [ -z "$SOURCE_DIR" ]; then
    SOURCE_DIR=$(grep -E '^HELLOWORLD_WINDOWS_GOLDEN_STORAGE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  fi
  if [ -z "$TARGET_DIR" ]; then
    TARGET_DIR=$(grep -E '^VM_STORAGE_DIR=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  fi
  if [ "$WINDOWS_IMAGE" = "helloworld/windows-vm:latest" ]; then
    WINDOWS_IMAGE=$(grep -E '^HELLOWORLD_WINDOWS_IMAGE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
    WINDOWS_IMAGE="${WINDOWS_IMAGE:-helloworld/windows-vm:latest}"
  fi
fi

SOURCE_DIR="${SOURCE_DIR:-$WINDOWS_DIR/vm/storage.golden}"
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
    --image)
      WINDOWS_IMAGE="$2"
      shift 2
      ;;
    --overwrite)
      OVERWRITE="$2"
      shift 2
      ;;
    --help)
      cat <<'EOF'
Usage: create_windows_overlay_storage.sh --source-dir <golden> [options]

Options:
  --source-dir <path>       Golden storage directory containing data.img
  --target-dir <path>       Overlay storage directory to recreate
  --container-name <name>   Running container to stop first
  --image <name>            Docker image with qemu-img
  --overwrite <true|false>  Delete existing target contents first
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [ ! -f "$SOURCE_DIR/data.img" ]; then
  echo "Error: source dir does not look like VM storage (missing data.img): $SOURCE_DIR"
  exit 1
fi

if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
  if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    DOCKER_BIN="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
  fi
fi

if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  echo "Error: Docker is not available via '$DOCKER_BIN'. Start Docker Desktop and try again." >&2
  exit 1
fi

SRC_REAL=$(realpath "$SOURCE_DIR")
mkdir -p "$TARGET_DIR"
DST_REAL=$(realpath "$TARGET_DIR")

if [ "$SRC_REAL" = "$DST_REAL" ]; then
  echo "Error: source and target must be different directories."
  exit 1
fi

"$DOCKER_BIN" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

if [ "$OVERWRITE" = true ]; then
  find "$DST_REAL" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
fi

rsync -a --delete --exclude 'data.img' --exclude 'data.qcow2' "${SRC_REAL}/" "${DST_REAL}/"
printf '%s\n' "$SRC_REAL" > "$DST_REAL/.backing_storage_dir"

"$DOCKER_BIN" run --rm --platform linux/amd64 \
  -v "${DST_REAL}/.:/overlay" \
  -v "${SRC_REAL}/.:/storage.golden:ro" \
  "$WINDOWS_IMAGE" \
  "qemu-img create -f qcow2 -F raw -b /storage.golden/data.img /overlay/data.qcow2" >/dev/null

echo "=== HelloWorld Windows Overlay Storage Created ==="
echo "Golden backing: $SRC_REAL"
echo "Overlay target: $DST_REAL"
echo "data.qcow2 stores per-task writes; data.img remains in golden storage."
