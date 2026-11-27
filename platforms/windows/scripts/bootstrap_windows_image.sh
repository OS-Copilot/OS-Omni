#!/bin/bash
# Bootstrap a local HelloWorld Windows VM container image tag.
# Example:
#   bash platforms/windows/scripts/bootstrap_windows_image.sh
#   bash platforms/windows/scripts/bootstrap_windows_image.sh --source-image your/image:tag --target-image helloworld/windows-vm:latest

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
HELLOWORLD_DIR="$SCRIPT_DIR/../../.."
ENV_FILE="$HELLOWORLD_DIR/.env"

DEFAULT_SOURCE_IMAGE="yunta88/helloworld-windows-vm:latest"
DEFAULT_TARGET_IMAGE="helloworld/windows-vm:latest"

SOURCE_IMAGE="${HELLOWORLD_WINDOWS_SOURCE_IMAGE:-}"
TARGET_IMAGE="${HELLOWORLD_WINDOWS_IMAGE:-}"
SKIP_PULL=false
DOCKER_BIN="docker"

if [ -f "$ENV_FILE" ]; then
  if [ -z "$SOURCE_IMAGE" ]; then
    SOURCE_IMAGE=$(grep -E '^HELLOWORLD_WINDOWS_SOURCE_IMAGE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  fi
  if [ -z "$TARGET_IMAGE" ]; then
    TARGET_IMAGE=$(grep -E '^HELLOWORLD_WINDOWS_IMAGE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  fi
fi

SOURCE_IMAGE="${SOURCE_IMAGE:-$DEFAULT_SOURCE_IMAGE}"
TARGET_IMAGE="${TARGET_IMAGE:-$DEFAULT_TARGET_IMAGE}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-image)
      SOURCE_IMAGE="$2"
      shift 2
      ;;
    --target-image)
      TARGET_IMAGE="$2"
      shift 2
      ;;
    --skip-pull)
      SKIP_PULL=true
      shift
      ;;
    --help)
      cat <<'EOF'
Usage: bootstrap_windows_image.sh [options]

Options:
  --source-image <image:tag>  Source image to use (default: yunta88/helloworld-windows-vm:latest)
  --target-image <image:tag>  Local HelloWorld image tag (default: helloworld/windows-vm:latest)
  --skip-pull                 Skip pulling source image and only retag locally
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

echo "=== HelloWorld Windows Image Bootstrap ==="
echo "Source image: $SOURCE_IMAGE"
echo "Target image: $TARGET_IMAGE"

if [ "$SKIP_PULL" = false ]; then
  echo "[1/2] Pulling source image..."
  "$DOCKER_BIN" pull "$SOURCE_IMAGE"
else
  echo "[1/2] Skipping pull as requested."
fi

echo "[2/2] Tagging source as target..."
"$DOCKER_BIN" tag "$SOURCE_IMAGE" "$TARGET_IMAGE"

echo ""
echo "Bootstrap complete."
echo "You can now run:"
echo "  bash platforms/windows/start_windows_vm.sh --execution executions/v1/windows.yaml"
