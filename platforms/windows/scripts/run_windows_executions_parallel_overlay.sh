#!/bin/bash
# Run Windows executions with clean per-task disposable overlays in parallel.
# This preserves the same disk isolation as overlay-per-task sequential runs,
# while reducing wall-clock time by running multiple Windows VM containers.

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."
HELLOWORLD_DIR="$WINDOWS_DIR/../.."
ENV_FILE="$HELLOWORLD_DIR/.env"

SOURCE_DIR="${HELLOWORLD_WINDOWS_GOLDEN_STORAGE:-}"
EXECUTIONS_DIR="$HELLOWORLD_DIR/executions/windows"
RUN_ROOT="$HELLOWORLD_DIR/.tmp/windows_parallel_overlays/$(date +%Y%m%d_%H%M%S)"
PATTERN=""
START_FROM=""
MAX_TASKS=0
STOP_ON_FAIL=false
JOBS="${HELLOWORLD_WINDOWS_PARALLEL_JOBS:-2}"
BASE_VNC_PORT="${HELLOWORLD_WINDOWS_PARALLEL_BASE_VNC_PORT:-8106}"
BASE_RDP_PORT="${HELLOWORLD_WINDOWS_PARALLEL_BASE_RDP_PORT:-3490}"
CONTAINER_PREFIX="${HELLOWORLD_WINDOWS_CONTAINER_PREFIX:-helloworld_windows_vm_p}"
KEEP_OVERLAYS=false
DOCKER_BIN="${DOCKER_BIN:-docker}"

usage() {
  cat <<'EOF'
Usage: run_windows_executions_parallel_overlay.sh [options]

Runs selected Windows executions in parallel. Each task gets its own disposable
qcow2 overlay backed by storage.golden/data.img, so golden storage is not
modified and task state cannot leak through disk.

Options:
  --source-dir <path>             Golden storage directory (default: HELLOWORLD_WINDOWS_GOLDEN_STORAGE or platforms/windows/vm/storage.golden)
  --executions-dir <path>         Directory of Windows execution YAMLs (default: executions/windows)
  --run-root <path>               Directory for temporary per-task overlays
  --pattern <regex>               Only run execution paths matching this regex
  --start-from <name-or-path>     Skip until this execution basename or path is reached
  --max-tasks <n>                 Stop after running n matched executions (default: 0 = no limit)
  --jobs <n>                      Number of parallel Windows VMs (default: 2)
  --stop-on-fail <true|false>     Stop scheduling new tasks after a failure (default: false)
  --base-vnc-port <port>          First host VNC/web port; each worker increments from here (default: 8106)
  --base-rdp-port <port>          First host RDP port; each worker increments from here (default: 3490)
  --container-prefix <prefix>     Container name prefix (default: helloworld_windows_vm_p)
  --keep-overlays <true|false>    Keep temporary overlay dirs after completion (default: false)
  --help                          Show this help
EOF
}

if [ -f "$ENV_FILE" ] && [ -z "$SOURCE_DIR" ]; then
  SOURCE_DIR=$(grep -E '^HELLOWORLD_WINDOWS_GOLDEN_STORAGE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
fi
SOURCE_DIR="${SOURCE_DIR:-$WINDOWS_DIR/vm/storage.golden}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --executions-dir) EXECUTIONS_DIR="$2"; shift 2 ;;
    --run-root) RUN_ROOT="$2"; shift 2 ;;
    --pattern) PATTERN="$2"; shift 2 ;;
    --start-from) START_FROM="$2"; shift 2 ;;
    --max-tasks) MAX_TASKS="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --stop-on-fail) STOP_ON_FAIL="$2"; shift 2 ;;
    --base-vnc-port) BASE_VNC_PORT="$2"; shift 2 ;;
    --base-rdp-port) BASE_RDP_PORT="$2"; shift 2 ;;
    --container-prefix) CONTAINER_PREFIX="$2"; shift 2 ;;
    --keep-overlays) KEEP_OVERLAYS="$2"; shift 2 ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [ ! -f "$SOURCE_DIR/data.img" ]; then
  echo "Error: golden storage source dir does not look valid (missing data.img): $SOURCE_DIR"
  exit 1
fi
if [ ! -d "$EXECUTIONS_DIR" ]; then
  echo "Error: executions dir does not exist: $EXECUTIONS_DIR"
  exit 1
fi
if [ "$JOBS" -lt 1 ]; then
  echo "Error: --jobs must be >= 1"
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

mapfile -t ALL_EXECUTIONS < <(find "$EXECUTIONS_DIR" -maxdepth 1 -type f -name '*.yaml' | sort)

SELECTED=()
STARTED=false
if [ -z "$START_FROM" ]; then
  STARTED=true
fi

for execution in "${ALL_EXECUTIONS[@]}"; do
  rel_path="${execution#$HELLOWORLD_DIR/}"
  base_name=$(basename "$execution")
  stem="${base_name%.yaml}"

  if [ -n "$PATTERN" ] && ! echo "$rel_path" | grep -E "$PATTERN" >/dev/null; then
    continue
  fi

  if [ "$STARTED" = false ]; then
    if [ "$START_FROM" = "$base_name" ] || [ "$START_FROM" = "$stem" ] || [ "$START_FROM" = "$rel_path" ] || [ "$START_FROM" = "$execution" ]; then
      STARTED=true
    else
      continue
    fi
  fi

  SELECTED+=("$execution")
  if [ "$MAX_TASKS" -gt 0 ] && [ "${#SELECTED[@]}" -ge "$MAX_TASKS" ]; then
    break
  fi
done

if [ "${#SELECTED[@]}" -eq 0 ]; then
  echo "No Windows executions matched."
  exit 1
fi

mkdir -p "$RUN_ROOT/logs" "$RUN_ROOT/status"

cleanup() {
  for ((slot=0; slot<JOBS; slot++)); do
    "$DOCKER_BIN" rm -f "${CONTAINER_PREFIX}${slot}" >/dev/null 2>&1 || true
  done
  if [ "$KEEP_OVERLAYS" != true ]; then
    rm -rf "$RUN_ROOT/overlays" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

run_one() {
  local execution="$1"
  local slot="$2"
  local index="$3"
  local rel_path="${execution#$HELLOWORLD_DIR/}"
  local stem
  stem=$(basename "$execution" .yaml)
  local container="${CONTAINER_PREFIX}${slot}"
  local overlay_dir="$RUN_ROOT/overlays/${index}_${stem}"
  local vnc_port=$((BASE_VNC_PORT + slot))
  local rdp_port=$((BASE_RDP_PORT + slot))
  local log_file="$RUN_ROOT/logs/${index}_${stem}.log"
  local status_file="$RUN_ROOT/status/${index}_${stem}.status"

  {
    echo "[$index/${#SELECTED[@]}] $rel_path"
    echo "Container: $container"
    echo "Overlay:   $overlay_dir"
    echo "VNC:       http://localhost:$vnc_port"
    echo "RDP:       localhost:$rdp_port"

    bash "$SCRIPT_DIR/create_windows_overlay_storage.sh" \
      --source-dir "$SOURCE_DIR" \
      --target-dir "$overlay_dir" \
      --container-name "$container"

    set +e
    HELLOWORLD_WINDOWS_CONTAINER_NAME="$container" \
    VM_STORAGE_DIR="$overlay_dir" \
    HELLOWORLD_WINDOWS_VNC_PORT="$vnc_port" \
    HELLOWORLD_WINDOWS_RDP_PORT="$rdp_port" \
      bash "$WINDOWS_DIR/start_windows_vm.sh" --execution "$rel_path"
    exit_code=$?
    set -e

    echo "$exit_code" > "$status_file"
    if [ "$exit_code" -eq 0 ]; then
      echo "PASS $rel_path"
    else
      echo "FAIL exit_code=$exit_code $rel_path"
    fi
    return "$exit_code"
  } 2>&1 | tee "$log_file"
}

echo "=== HelloWorld Windows Parallel Overlay Runner ==="
echo "Matched:          ${#SELECTED[@]}"
echo "Jobs:             $JOBS"
echo "Golden source:    $SOURCE_DIR"
echo "Run root:         $RUN_ROOT"
echo "Container prefix: $CONTAINER_PREFIX"
echo "VNC ports:        $BASE_VNC_PORT..$((BASE_VNC_PORT + JOBS - 1))"
echo "RDP ports:        $BASE_RDP_PORT..$((BASE_RDP_PORT + JOBS - 1))"
echo "Stop on fail:     $STOP_ON_FAIL"
echo ""

PASS_COUNT=0
FAIL_COUNT=0
FAILED=()
running=0
stop_scheduling=false
START_TIME=$(date +%s)

total="${#SELECTED[@]}"
start_index=0
while [ "$start_index" -lt "$total" ] && [ "$stop_scheduling" = false ]; do
  running=0
  for ((slot=0; slot<JOBS && start_index+slot<total; slot++)); do
    execution="${SELECTED[$((start_index + slot))]}"
    run_number=$((start_index + slot + 1))
    run_one "$execution" "$slot" "$run_number" &
    running=$((running + 1))
  done

  wave_failed=false
  while [ "$running" -gt 0 ]; do
    set +e
    wait -n
    wait_code=$?
    set -e
    running=$((running - 1))
    if [ "$wait_code" -ne 0 ]; then
      wave_failed=true
    fi
  done

  if [ "$wave_failed" = true ] && [ "$STOP_ON_FAIL" = true ]; then
    stop_scheduling=true
  fi
  start_index=$((start_index + JOBS))
done

for status_file in "$RUN_ROOT"/status/*.status; do
  [ -f "$status_file" ] || continue
  code=$(cat "$status_file")
  name=$(basename "$status_file" .status)
  if [ "$code" -eq 0 ]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED+=("$name:$code")
  fi
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "=== Windows Parallel Overlay Batch Complete ==="
echo "Attempted: $((PASS_COUNT + FAIL_COUNT))"
echo "Passed:    $PASS_COUNT"
echo "Failed:    $FAIL_COUNT"
echo "Duration:  ${DURATION}s"
echo "Logs:      $RUN_ROOT/logs"

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo ""
  echo "Failed executions:"
  for item in "${FAILED[@]}"; do
    echo "  $item"
  done
  exit 1
fi

exit 0
