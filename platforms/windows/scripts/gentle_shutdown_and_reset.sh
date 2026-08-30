#!/bin/bash
# Gracefully shut down the Windows VM, then reset working storage from golden.
#
# Usage:
#   bash platforms/windows/scripts/gentle_shutdown_and_reset.sh
#   bash platforms/windows/scripts/gentle_shutdown_and_reset.sh --show-progress true

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."
HELLOWORLD_DIR="$WINDOWS_DIR/../.."
ENV_FILE="$HELLOWORLD_DIR/.env"

CONTAINER_NAME="${HELLOWORLD_WINDOWS_CONTAINER_NAME:-helloworld_windows_vm}"
WINDOWS_VM_IP="${HELLOWORLD_WINDOWS_VM_IP:-20.20.20.21}"
RUNTIME_PORT="${HELLOWORLD_WINDOWS_RUNTIME_PORT:-5000}"
RUNTIME_TOKEN="${HELLOWORLD_WINDOWS_RUNTIME_TOKEN:-windowsbench-runtime-token}"
SOURCE_DIR="${HELLOWORLD_WINDOWS_GOLDEN_STORAGE:-$WINDOWS_DIR/vm/storage.golden}"
TARGET_DIR="${VM_STORAGE_DIR:-}"
SHOW_PROGRESS=false
RESET_MODE="${HELLOWORLD_WINDOWS_RESET_MODE:-overlay}"
DOCKER_BIN="docker"

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
    --show-progress)
      SHOW_PROGRESS="$2"
      shift 2
      ;;
    --reset-mode)
      RESET_MODE="$2"
      shift 2
      ;;
    --container-name)
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --help)
      cat <<'EOF'
Usage: gentle_shutdown_and_reset.sh [options]

Options:
  --source-dir <path>             Golden storage directory (default: platforms/windows/vm/storage.golden)
  --target-dir <path>             Working storage directory (default: VM_STORAGE_DIR or platforms/windows/vm/storage)
  --show-progress <true|false>    Show rsync progress during reset (default: false)
  --reset-mode <overlay|copy>      Reset strategy (default: overlay)
  --container-name <name>         Windows VM container name (default: helloworld_windows_vm)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [ -z "$TARGET_DIR" ] && [ -f "$ENV_FILE" ]; then
  TARGET_DIR=$(grep -E '^VM_STORAGE_DIR=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
fi
TARGET_DIR="${TARGET_DIR:-$WINDOWS_DIR/vm/storage}"

case "$RESET_MODE" in
  overlay|copy) ;;
  *)
    echo "Error: --reset-mode must be 'overlay' or 'copy' (got: $RESET_MODE)"
    exit 1
    ;;
esac

if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
  if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    DOCKER_BIN="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
  fi
fi

echo "=== HelloWorld Windows Gentle Shutdown + Reset ==="
echo "Container: $CONTAINER_NAME"
echo "Golden:    $SOURCE_DIR"
echo "Working:   $TARGET_DIR"
echo "Reset:     $RESET_MODE"

if "$DOCKER_BIN" container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "[1/3] Requesting graceful Windows shutdown..."
  SHUTDOWN_REQUESTED=true
  "$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 10 \
    -H "Authorization: Bearer $RUNTIME_TOKEN" \
    -X POST "http://$WINDOWS_VM_IP:$RUNTIME_PORT/shutdown" >/dev/null 2>&1 || SHUTDOWN_REQUESTED=false

  if [ "$SHUTDOWN_REQUESTED" = true ]; then
    QEMU_WAIT_ATTEMPTS="${HELLOWORLD_WINDOWS_SHUTDOWN_WAIT_ATTEMPTS:-36}"
    STOP_TIMEOUT="${HELLOWORLD_WINDOWS_DOCKER_STOP_TIMEOUT:-120}"
  else
    echo "      Shutdown endpoint did not respond; using shorter recovery wait."
    QEMU_WAIT_ATTEMPTS="${HELLOWORLD_WINDOWS_DEAD_RUNTIME_WAIT_ATTEMPTS:-6}"
    STOP_TIMEOUT="${HELLOWORLD_WINDOWS_DEAD_RUNTIME_STOP_TIMEOUT:-30}"
  fi

  echo "      Waiting for QEMU to exit..."
  for _ in $(seq 1 "$QEMU_WAIT_ATTEMPTS"); do
    if ! "$DOCKER_BIN" container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
      break
    fi
    if ! "$DOCKER_BIN" exec "$CONTAINER_NAME" pgrep -f qemu-system-x86_64 >/dev/null 2>&1; then
      echo "      VM process exited cleanly"
      break
    fi
    sleep 5
  done

  echo "[2/3] Stopping/removing VM container..."
  "$DOCKER_BIN" stop -t "$STOP_TIMEOUT" "$CONTAINER_NAME" >/dev/null 2>&1 || true
  "$DOCKER_BIN" rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
else
  echo "[1/3] No running VM container found; skipping shutdown."
fi

echo "[3/3] Resetting working storage from golden..."
if [ "$RESET_MODE" = overlay ]; then
  bash "$SCRIPT_DIR/create_windows_overlay_storage.sh" \
    --source-dir "$SOURCE_DIR" \
    --target-dir "$TARGET_DIR" \
    --container-name "$CONTAINER_NAME" \
    --overwrite true
else
  bash "$SCRIPT_DIR/reset_windows_storage.sh" \
    --source-dir "$SOURCE_DIR" \
    --target-dir "$TARGET_DIR" \
    --container-name "$CONTAINER_NAME" \
    --stop-container false \
    --show-progress "$SHOW_PROGRESS"
fi

echo ""
echo "Done. Next Windows VM start will boot from the golden storage copy."
