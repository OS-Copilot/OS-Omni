#!/bin/bash
# Run Windows executions against one live VM session.
# This mode starts the VM once, runs selected execution YAMLs one by one, and
# runs the generic in-guest cleanup between executions instead of shutting down
# after every execution.

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."
HELLOWORLD_DIR="$WINDOWS_DIR/../.."
EXECUTIONS_DIR="$HELLOWORLD_DIR/executions/windows"
RESULTS_DIR="${HELLOWORLD_WINDOWS_RESULTS_DIR:-$HELLOWORLD_DIR/results}"
PATTERN=""
START_FROM=""
MAX_TASKS=0
STOP_ON_FAIL=false
SHUTDOWN_ON_EXIT=false
RESTART_ON_RUNTIME_FAIL=true
CONTAINER_NAME="${HELLOWORLD_WINDOWS_CONTAINER_NAME:-helloworld_windows_vm}"
WINDOWS_VM_IP="${HELLOWORLD_WINDOWS_VM_IP:-20.20.20.21}"
RUNTIME_PORT="${HELLOWORLD_WINDOWS_RUNTIME_PORT:-5000}"
RUNTIME_TOKEN="${HELLOWORLD_WINDOWS_RUNTIME_TOKEN:-windowsbench-runtime-token}"
ENV_DOCKER_ARGS=()
DOCKER_BIN="${DOCKER_BIN:-docker}"

usage() {
  cat <<'EOF'
Usage: run_windows_executions_live.sh [options]

Starts one Windows VM, runs selected executions sequentially inside it, and
cleans generic guest state between executions without shutting down the VM.

Options:
  --executions-dir <path>         Directory of Windows execution YAMLs (default: executions/windows)
  --results-dir <path>            Host directory to sync results into (default: results)
  --pattern <regex>               Only run execution paths matching this regex
  --start-from <name-or-path>     Skip until this execution basename or path is reached
  --max-tasks <n>                 Stop after running n matched executions (default: 0 = no limit)
  --stop-on-fail <true|false>     Stop immediately after a failed execution (default: false)
  --shutdown-on-exit <true|false> Shut down the VM after the batch (default: false)
  --restart-on-runtime-fail <true|false>
                                  Restart VM automatically when runtime is unreachable (default: true)
  --help                          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --executions-dir) EXECUTIONS_DIR="$2"; shift 2 ;;
    --results-dir) RESULTS_DIR="$2"; shift 2 ;;
    --pattern) PATTERN="$2"; shift 2 ;;
    --start-from) START_FROM="$2"; shift 2 ;;
    --max-tasks) MAX_TASKS="$2"; shift 2 ;;
    --stop-on-fail) STOP_ON_FAIL="$2"; shift 2 ;;
    --shutdown-on-exit) SHUTDOWN_ON_EXIT="$2"; shift 2 ;;
    --restart-on-runtime-fail) RESTART_ON_RUNTIME_FAIL="$2"; shift 2 ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [ ! -d "$EXECUTIONS_DIR" ]; then
  echo "Error: executions dir does not exist: $EXECUTIONS_DIR"
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

if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
  if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    DOCKER_BIN="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
  fi
fi

if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  echo "Error: Docker is not available via '$DOCKER_BIN'. Start Docker Desktop and try again." >&2
  exit 1
fi

cleanup_guest_state() {
  if ! container_running; then
    echo "Warning: cannot clean guest state because $CONTAINER_NAME is not running."
    return 1
  fi
  "$DOCKER_BIN" exec -i "$CONTAINER_NAME" sh -lc 'cat >/tmp/hw_cleanup.json && curl -s -m 240 -X POST -H "Authorization: Bearer '"$RUNTIME_TOKEN"'" -H "Content-Type: application/json" --data @/tmp/hw_cleanup.json http://'"$WINDOWS_VM_IP"':'"$RUNTIME_PORT"'/setup/execute >/tmp/hw_cleanup_resp.json 2>/tmp/hw_cleanup_err.txt || true' <<'JSON'
{"command":["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File","\\\\host.lan\\Data\\cleanup-generic-state.ps1"],"shell":false,"timeout":240}
JSON
}

container_running() {
  [ "$("$DOCKER_BIN" inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || true)" = "true" ]
}

runtime_ready() {
  container_running || return 1

  local health_code schema_code powershell_code
  health_code=$("$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 8 -o /tmp/hw_live_health.json -w "%{http_code}" \
    -H "Authorization: Bearer $RUNTIME_TOKEN" \
    "http://$WINDOWS_VM_IP:$RUNTIME_PORT/health" 2>/dev/null || echo "000")
  schema_code=$("$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 8 -o /tmp/hw_live_schema.json -w "%{http_code}" \
    -H "Authorization: Bearer $RUNTIME_TOKEN" \
    "http://$WINDOWS_VM_IP:$RUNTIME_PORT/action_schema" 2>/dev/null || echo "000")
  powershell_code=$("$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 12 -o /tmp/hw_live_powershell.json -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $RUNTIME_TOKEN" \
    -H "Content-Type: application/json" \
    --data '{"script":"Write-Output HW_POWERSHELL_READY","timeout":5}' \
    "http://$WINDOWS_VM_IP:$RUNTIME_PORT/run_powershell" 2>/dev/null || echo "000")

  [ "$health_code" = "200" ] && [ "$schema_code" = "200" ] \
    && [ "$powershell_code" = "200" ] \
    && "$DOCKER_BIN" exec "$CONTAINER_NAME" grep -q "HW_POWERSHELL_READY" /tmp/hw_live_powershell.json 2>/dev/null
}

restart_vm() {
  echo "Runtime is unreachable; restarting Windows VM..."
  sync_results_to_host
  HELLOWORLD_WINDOWS_RESULTS_DIR="$RESULTS_DIR" HELLOWORLD_WINDOWS_ALLOW_FORCE_REMOVE=true bash "$WINDOWS_DIR/start_windows_vm.sh"
}

ensure_runtime_ready() {
  local reason="$1"

  for _ in $(seq 1 3); do
    if runtime_ready; then
      return 0
    fi
    sleep 5
  done

  if [ "$RESTART_ON_RUNTIME_FAIL" != true ]; then
    echo "Runtime is not ready ($reason), and restart-on-runtime-fail=false."
    return 1
  fi

  echo "Runtime health check failed before $reason."
  restart_vm

  for _ in $(seq 1 6); do
    if runtime_ready; then
      echo "Runtime recovered."
      return 0
    fi
    sleep 5
  done

  echo "Runtime is still not ready after VM restart."
  return 1
}

sync_results_to_host() {
  mkdir -p "$RESULTS_DIR"
  if ! container_running; then
    echo "Warning: cannot sync results because $CONTAINER_NAME is not running."
    return 0
  fi

  local probe=".host_bind_probe_$$"
  rm -f "$RESULTS_DIR/$probe"
  if "$DOCKER_BIN" exec "$CONTAINER_NAME" sh -lc "mkdir -p /HelloWorld/results && touch /HelloWorld/results/$probe" 2>/dev/null \
      && [ -f "$RESULTS_DIR/$probe" ]; then
    rm -f "$RESULTS_DIR/$probe"
    "$DOCKER_BIN" exec "$CONTAINER_NAME" rm -f "/HelloWorld/results/$probe" >/dev/null 2>&1 || true
    return 0
  fi
  "$DOCKER_BIN" exec "$CONTAINER_NAME" rm -f "/HelloWorld/results/$probe" >/dev/null 2>&1 || true

  echo "Warning: /HelloWorld/results is not a bind mount; falling back to docker cp."
  "$DOCKER_BIN" cp "$CONTAINER_NAME":/HelloWorld/results/. "$RESULTS_DIR/"
}

shutdown_vm() {
  "$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 10 -H "Authorization: Bearer $RUNTIME_TOKEN" -X POST "http://$WINDOWS_VM_IP:$RUNTIME_PORT/shutdown" >/dev/null 2>&1 || true
  sleep 20
  "$DOCKER_BIN" stop -t 90 "$CONTAINER_NAME" >/dev/null 2>&1 || true
}

if ! runtime_ready; then
  echo "Starting Windows VM for live batch..."
  HELLOWORLD_WINDOWS_RESULTS_DIR="$RESULTS_DIR" HELLOWORLD_WINDOWS_ALLOW_FORCE_REMOVE=true bash "$WINDOWS_DIR/start_windows_vm.sh"
fi

add_env_arg_if_present() {
  local key="$1"
  local value="${!key:-}"
  if [ -n "$value" ]; then
    ENV_DOCKER_ARGS+=( -e "$key=$value" )
  fi
}

if [ -f "$HELLOWORLD_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line=$(echo "$line" | tr -d '\r')
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" != *"="* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"

    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    ENV_DOCKER_ARGS+=( -e "$key=$value" )
  done < "$HELLOWORLD_DIR/.env"
fi
add_env_arg_if_present "OPENAI_API_KEY"
add_env_arg_if_present "OPENAI_BASE_URL"
add_env_arg_if_present "OPENAI_ORG_ID"
add_env_arg_if_present "OPENAI_PROJECT"

trap 'sync_results_to_host; if [ "$SHUTDOWN_ON_EXIT" = true ]; then shutdown_vm; fi' EXIT

echo "=== HelloWorld Windows Live Batch Runner ==="
echo "Matched:        ${#SELECTED[@]}"
echo "Results dir:    $RESULTS_DIR"
echo "Stop on fail:   $STOP_ON_FAIL"
echo "Shutdown exit:  $SHUTDOWN_ON_EXIT"
echo "Runtime restart:$RESTART_ON_RUNTIME_FAIL"
echo ""

PASS_COUNT=0
FAIL_COUNT=0
FAILED=()
START_TIME=$(date +%s)

for index in "${!SELECTED[@]}"; do
  execution="${SELECTED[$index]}"
  rel_path="${execution#$HELLOWORLD_DIR/}"
  run_number=$((index + 1))

  echo ""
  echo "================================================================"
  echo "[$run_number/${#SELECTED[@]}] $rel_path"
  echo "================================================================"

  if [ "$run_number" -gt 1 ]; then
    if ! ensure_runtime_ready "execution $run_number before cleanup"; then
      FAIL_COUNT=$((FAIL_COUNT + 1))
      FAILED+=("$rel_path:runtime_unavailable_before_cleanup")
      echo "[$run_number/${#SELECTED[@]}] FAIL runtime_unavailable_before_cleanup $rel_path"
      if [ "$STOP_ON_FAIL" = true ]; then
        break
      fi
      continue
    fi

    echo "Cleaning guest state before next execution..."
    if ! cleanup_guest_state; then
      echo "Guest cleanup could not run; attempting runtime recovery before execution."
    fi
    if ! ensure_runtime_ready "execution $run_number after cleanup"; then
      FAIL_COUNT=$((FAIL_COUNT + 1))
      FAILED+=("$rel_path:runtime_unavailable_after_cleanup")
      echo "[$run_number/${#SELECTED[@]}] FAIL runtime_unavailable_after_cleanup $rel_path"
      if [ "$STOP_ON_FAIL" = true ]; then
        break
      fi
      continue
    fi
  else
    if ! ensure_runtime_ready "execution $run_number"; then
      FAIL_COUNT=$((FAIL_COUNT + 1))
      FAILED+=("$rel_path:runtime_unavailable")
      echo "[$run_number/${#SELECTED[@]}] FAIL runtime_unavailable $rel_path"
      if [ "$STOP_ON_FAIL" = true ]; then
        break
      fi
      continue
    fi
  fi

  set +e
  "$DOCKER_BIN" exec \
    "${ENV_DOCKER_ARGS[@]}" \
    -e HELLOWORLD_WINDOWS_VM_IP="$WINDOWS_VM_IP" \
    -e HELLOWORLD_WINDOWS_RUNTIME_PORT="$RUNTIME_PORT" \
    -e HELLOWORLD_WINDOWS_RUNTIME_TOKEN="$RUNTIME_TOKEN" \
    "$CONTAINER_NAME" \
    bash -c "cd /HelloWorld && python -m platforms.windows.cli --execution '$rel_path'"
  exit_code=$?
  set -e

  sync_results_to_host

  if [ "$exit_code" -eq 0 ]; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "[$run_number/${#SELECTED[@]}] PASS $rel_path"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED+=("$rel_path:$exit_code")
    echo "[$run_number/${#SELECTED[@]}] FAIL exit_code=$exit_code $rel_path"
    if ! runtime_ready; then
      echo "Runtime became unreachable during execution $run_number."
      if [ "$RESTART_ON_RUNTIME_FAIL" = true ]; then
        if restart_vm && ensure_runtime_ready "execution $run_number restart recovery"; then
          echo "Runtime recovered after execution $run_number failure."
        else
          echo "Runtime did not recover after execution $run_number failure."
        fi
      fi
    fi
    if [ "$STOP_ON_FAIL" = true ]; then
      break
    fi
  fi
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "=== Windows Live Batch Complete ==="
echo "Attempted: $((PASS_COUNT + FAIL_COUNT))"
echo "Passed:    $PASS_COUNT"
echo "Failed:    $FAIL_COUNT"
echo "Duration:  ${DURATION}s"

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo ""
  echo "Failed executions:"
  for item in "${FAILED[@]}"; do
    echo "  $item"
  done
  exit 1
fi

exit 0
