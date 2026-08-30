#!/bin/bash
# Prepare a fresh Windows golden storage from setup.iso.
# Example:
#   bash platforms/windows/scripts/prepare_windows_golden_image.sh
#   bash platforms/windows/scripts/prepare_windows_golden_image.sh --clean-storage true

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."
HELLOWORLD_DIR="$WINDOWS_DIR/../.."
ENV_FILE="$HELLOWORLD_DIR/.env"

DEFAULT_IMAGE="helloworld/windows-vm:latest"
DEFAULT_CONTAINER_NAME="helloworld_windows_vm_prepare"
DEFAULT_TIMEOUT_SECONDS=7200
DEFAULT_RAM_SIZE="4G"
DEFAULT_CPU_CORES="8"
DEFAULT_BROWSER_PORT="8006"
DEFAULT_RDP_PORT="3390"

HELLOWORLD_WINDOWS_IMAGE="${HELLOWORLD_WINDOWS_IMAGE:-}"
VM_STORAGE_DIR="${VM_STORAGE_DIR:-}"
ISO_PATH="${ISO_PATH:-}"
VM_SHARED_DIR="${VM_SHARED_DIR:-}"
VM_CLIENT_DIR="${VM_CLIENT_DIR:-}"
CONTAINER_NAME="$DEFAULT_CONTAINER_NAME"
TIMEOUT_SECONDS="$DEFAULT_TIMEOUT_SECONDS"
RAM_SIZE="$DEFAULT_RAM_SIZE"
CPU_CORES="$DEFAULT_CPU_CORES"
BROWSER_PORT="$DEFAULT_BROWSER_PORT"
RDP_PORT="$DEFAULT_RDP_PORT"
CLEAN_STORAGE=false
KEEP_CONTAINER=false
DOCKER_BIN="docker"

if [ -f "$ENV_FILE" ]; then
  if [ -z "$HELLOWORLD_WINDOWS_IMAGE" ]; then
    HELLOWORLD_WINDOWS_IMAGE=$(grep -E '^HELLOWORLD_WINDOWS_IMAGE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  fi
  if [ -z "$VM_STORAGE_DIR" ]; then
    VM_STORAGE_DIR=$(grep -E '^VM_STORAGE_DIR=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  fi
fi

HELLOWORLD_WINDOWS_IMAGE="${HELLOWORLD_WINDOWS_IMAGE:-$DEFAULT_IMAGE}"
VM_STORAGE_DIR="${VM_STORAGE_DIR:-$WINDOWS_DIR/vm/storage}"
ISO_PATH="${ISO_PATH:-$WINDOWS_DIR/vm/image/setup.iso}"
VM_SHARED_DIR="${VM_SHARED_DIR:-$WINDOWS_DIR/vm/setup}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      HELLOWORLD_WINDOWS_IMAGE="$2"
      shift 2
      ;;
    --storage-dir)
      VM_STORAGE_DIR="$2"
      shift 2
      ;;
    --iso-path)
      ISO_PATH="$2"
      shift 2
      ;;
    --shared-dir)
      VM_SHARED_DIR="$2"
      shift 2
      ;;
    --client-dir)
      VM_CLIENT_DIR="$2"
      shift 2
      ;;
    --container-name)
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --ram-size)
      RAM_SIZE="$2"
      shift 2
      ;;
    --cpu-cores)
      CPU_CORES="$2"
      shift 2
      ;;
    --browser-port)
      BROWSER_PORT="$2"
      shift 2
      ;;
    --rdp-port)
      RDP_PORT="$2"
      shift 2
      ;;
    --clean-storage)
      CLEAN_STORAGE="$2"
      shift 2
      ;;
    --keep-container)
      KEEP_CONTAINER="$2"
      shift 2
      ;;
    --help)
      cat <<'EOF'
Usage: prepare_windows_golden_image.sh [options]

Options:
  --image <image:tag>             VM container image (default: helloworld/windows-vm:latest)
  --storage-dir <path>            VM storage directory (default: platforms/windows/vm/storage)
  --iso-path <path>               Windows ISO path (default: platforms/windows/vm/image/setup.iso)
  --shared-dir <path>             Shared setup directory (default: platforms/windows/vm/setup)
  --client-dir <path>             Optional host client mount directory (default: temp dir)
  --container-name <name>         Docker container name (default: helloworld_windows_vm_prepare)
  --timeout-seconds <n>           Timeout waiting for completion (default: 7200)
  --ram-size <size>               VM RAM size (default: 4G)
  --cpu-cores <n>                 VM CPU cores (default: 8)
  --browser-port <port>           Host port mapped to VNC web UI (default: 8006)
  --rdp-port <port>               Host port mapped to RDP (default: 3390)
  --clean-storage <true|false>    Remove existing files in storage before prepare (default: false)
  --keep-container <true|false>   Keep container after completion for debugging (default: false)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if ! docker info >/dev/null 2>&1; then
  if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    DOCKER_BIN="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
  fi
fi

if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  echo "Docker daemon is not running."
  exit 1
fi

if [ ! -e /dev/kvm ]; then
  echo "Error: /dev/kvm is not available in this environment."
  exit 1
fi

if [ ! -f "$ISO_PATH" ]; then
  echo "Error: ISO file not found: $ISO_PATH"
  exit 1
fi

if [ ! -f "$VM_SHARED_DIR/on-logon.ps1" ] || [ ! -d "$VM_SHARED_DIR/server" ]; then
  echo "Error: shared dir must contain on-logon.ps1 and server/: $VM_SHARED_DIR"
  exit 1
fi

mkdir -p "$VM_STORAGE_DIR"

if [ "$CLEAN_STORAGE" = true ]; then
  if [ "$VM_STORAGE_DIR" = "/" ] || [ "$VM_STORAGE_DIR" = "" ]; then
    echo "Refusing to clean unsafe storage path: '$VM_STORAGE_DIR'"
    exit 1
  fi
  echo "Cleaning storage directory: $VM_STORAGE_DIR"
  find "$VM_STORAGE_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
fi

TEMP_CLIENT=""
if [ -z "$VM_CLIENT_DIR" ]; then
  TEMP_CLIENT=$(mktemp -d)
  VM_CLIENT_DIR="$TEMP_CLIENT"
else
  mkdir -p "$VM_CLIENT_DIR"
fi

cleanup() {
  if [ "$KEEP_CONTAINER" != true ]; then
    "$DOCKER_BIN" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  if [ -n "$TEMP_CLIENT" ]; then
    rm -rf "$TEMP_CLIENT"
  fi
}
trap cleanup EXIT

OPENAI_KEY=""
if [ -f "$ENV_FILE" ]; then
  OPENAI_KEY=$(grep -E '^OPENAI_API_KEY=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' || true)
fi

"$DOCKER_BIN" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "=== HelloWorld Windows Golden Image Prepare ==="
echo "Image:      $HELLOWORLD_WINDOWS_IMAGE"
echo "ISO:        $ISO_PATH"
echo "Storage:    $VM_STORAGE_DIR"
echo "Shared dir: $VM_SHARED_DIR"
echo "Container:  $CONTAINER_NAME"
echo "VNC:        http://localhost:$BROWSER_PORT"
echo ""
echo "Please do not interact with the VM while preparation is running."

"$DOCKER_BIN" run -d \
  -p "$BROWSER_PORT:8006" -p "$RDP_PORT:3389" \
  --name "$CONTAINER_NAME" \
  --platform linux/amd64 \
  --device=/dev/kvm \
  -e RAM_SIZE="$RAM_SIZE" -e CPU_CORES="$CPU_CORES" \
  --mount "type=bind,source=$ISO_PATH,target=/custom.iso" \
  -v "${VM_STORAGE_DIR}/.:/storage" \
  -v "${VM_SHARED_DIR}/.:/shared" \
  -v "${VM_CLIENT_DIR}/.:/client" \
  --cap-add NET_ADMIN --stop-timeout 120 \
  --entrypoint /bin/bash \
  ${OPENAI_KEY:+-e OPENAI_API_KEY=$OPENAI_KEY} \
  "$HELLOWORLD_WINDOWS_IMAGE" \
  -c './entry.sh --prepare-image true --start-client false --agent navi --model gpt-4-vision-preview --som-origin oss --a11y-backend uia' \
  > /dev/null

start_ts=$(date +%s)
last_status_report=0

while true; do
  if ! "$DOCKER_BIN" inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "Error: container disappeared unexpectedly: $CONTAINER_NAME"
    exit 1
  fi

  status=$("$DOCKER_BIN" inspect -f '{{.State.Status}}' "$CONTAINER_NAME")
  if [ "$status" = "exited" ] || [ "$status" = "dead" ]; then
    break
  fi

  now_ts=$(date +%s)
  elapsed=$((now_ts - start_ts))
  if (( elapsed - last_status_report >= 30 )); then
    echo "Preparing... ${elapsed}s elapsed (status: $status)"
    last_status_report=$elapsed
  fi

  if (( elapsed > TIMEOUT_SECONDS )); then
    echo "Error: timed out after ${TIMEOUT_SECONDS}s."
    echo "Last logs:"
    "$DOCKER_BIN" logs --tail 120 "$CONTAINER_NAME" || true
    exit 1
  fi

  sleep 5
done

exit_code=$("$DOCKER_BIN" inspect -f '{{.State.ExitCode}}' "$CONTAINER_NAME")
log_path="$WINDOWS_DIR/vm/prepare_windows_image.log"
"$DOCKER_BIN" logs "$CONTAINER_NAME" > "$log_path" 2>&1 || true

if [ "$exit_code" != "0" ]; then
  # Some WAA base images can exit with 127 at the end of --prepare-image
  # due to a wait/no-child edge case in entry.sh, even when prepare succeeded.
  if [ "$exit_code" = "127" ] \
    && [ -f "$VM_STORAGE_DIR/data.img" ] \
    && [ -f "$VM_STORAGE_DIR/windows.boot" ] \
    && grep -q "Windows VM is shutting down" "$log_path" \
    && grep -q "Shutdown completed" "$log_path"; then
    echo "Prepare exited with 127, but shutdown markers and artifacts are present."
    echo "Treating this run as successful (known container exit-code quirk)."
  else
    echo "Prepare failed with exit code: $exit_code"
    echo "Log file: $log_path"
    exit "$exit_code"
  fi
fi

if [ ! -f "$VM_STORAGE_DIR/data.img" ]; then
  echo "Prepare finished but data.img not found in: $VM_STORAGE_DIR"
  exit 1
fi

echo ""
echo "Golden image preparation completed successfully."
echo "Storage is ready at: $VM_STORAGE_DIR"
echo "Log file: $log_path"
