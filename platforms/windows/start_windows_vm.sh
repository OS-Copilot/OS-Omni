#!/bin/bash
# HelloWorld Windows VM launcher
# Usage:
#   bash start_windows_vm.sh
#   bash start_windows_vm.sh --execution executions/windows/json/openshop_login.yaml
# Optional env:
#   HELLOWORLD_WINDOWS_IMAGE=yourlab/helloworld-winvm:latest

set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
HELLOWORLD_DIR="$SCRIPT_DIR/../.."
DEFAULT_WINDOWS_IMAGE="helloworld/windows-vm:latest"
CONTAINER_NAME="${HELLOWORLD_WINDOWS_CONTAINER_NAME:-helloworld_windows_vm}"
WINDOWS_VM_IP="${HELLOWORLD_WINDOWS_VM_IP:-20.20.20.21}"
VNC_HOST_PORT="${HELLOWORLD_WINDOWS_VNC_PORT:-8006}"
RDP_HOST_PORT="${HELLOWORLD_WINDOWS_RDP_PORT:-3390}"
PRIMARY_RUNTIME_PORT="${HELLOWORLD_WINDOWS_RUNTIME_PORT:-5000}"
FALLBACK_RUNTIME_PORT="${HELLOWORLD_WINDOWS_FALLBACK_RUNTIME_PORT:-5001}"
ACTIVE_RUNTIME_PORT="$PRIMARY_RUNTIME_PORT"
ALLOW_RUNTIME_FALLBACK_5001="${HELLOWORLD_WINDOWS_ALLOW_RUNTIME_FALLBACK_5001:-false}"
RUNTIME_TOKEN="${HELLOWORLD_WINDOWS_RUNTIME_TOKEN:-windowsbench-runtime-token}"
AUDIO_QEMU_ARGS_DEFAULT="-audiodev none,id=snd0 -device ich9-intel-hda,bus=pcie.0,addr=0x1b -device hda-output,audiodev=snd0"
AUDIO_QEMU_ARGS="${HELLOWORLD_WINDOWS_AUDIO_QEMU_ARGS:-$AUDIO_QEMU_ARGS_DEFAULT}"
WINDOWS_RAM_SIZE="${HELLOWORLD_WINDOWS_RAM_SIZE:-4G}"
WINDOWS_CPU_CORES="${HELLOWORLD_WINDOWS_CPU_CORES:-8}"

EXECUTION=""
RESET_BEFORE_START="${HELLOWORLD_WINDOWS_RESET_BEFORE_START:-false}"
RESET_BEFORE_EXECUTION="${HELLOWORLD_WINDOWS_RESET_BEFORE_EXECUTION:-true}"
RESET_AFTER_EXECUTION="${HELLOWORLD_WINDOWS_RESET_AFTER_EXECUTION:-true}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execution) EXECUTION="$2"; shift 2 ;;
    --reset-before-start) RESET_BEFORE_START="$2"; shift 2 ;;
    --reset-before-execution) RESET_BEFORE_EXECUTION="$2"; shift 2 ;;
    --reset-after-execution) RESET_AFTER_EXECUTION="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [ -z "$VM_STORAGE_DIR" ] && [ -f "$HELLOWORLD_DIR/.env" ]; then
  VM_STORAGE_DIR=$(grep -E '^VM_STORAGE_DIR=' "$HELLOWORLD_DIR/.env" | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'")
fi

if [ -z "$HELLOWORLD_WINDOWS_IMAGE" ] && [ -f "$HELLOWORLD_DIR/.env" ]; then
  HELLOWORLD_WINDOWS_IMAGE=$(grep -E '^HELLOWORLD_WINDOWS_IMAGE=' "$HELLOWORLD_DIR/.env" | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'")
fi
HELLOWORLD_WINDOWS_IMAGE="${HELLOWORLD_WINDOWS_IMAGE:-$DEFAULT_WINDOWS_IMAGE}"

if [ -z "$VM_STORAGE_DIR" ] && [ -f "$HELLOWORLD_DIR/.env" ]; then
  WAA_SCRIPTS_DIR=$(grep -E '^WAA_SCRIPTS_DIR=' "$HELLOWORLD_DIR/.env" | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'")
  if [ -n "$WAA_SCRIPTS_DIR" ] && [ -d "$WAA_SCRIPTS_DIR" ]; then
    WAA_ROOT=$(cd "$WAA_SCRIPTS_DIR/.." && pwd)
    VM_STORAGE_DIR="$WAA_ROOT/src/win-arena-container/vm/storage"
  fi
fi

if [ -z "$VM_STORAGE_DIR" ]; then
  LOCAL_VM_STORAGE="$HELLOWORLD_DIR/platforms/windows/vm/storage"
  if [ -d "$LOCAL_VM_STORAGE" ]; then
    VM_STORAGE_DIR="$LOCAL_VM_STORAGE"
  fi
fi

VM_STORAGE_DIR="${VM_STORAGE_DIR:?Please set VM_STORAGE_DIR to the Windows VM storage directory (or configure it in .env).}"

if [ ! -d "$VM_STORAGE_DIR" ]; then
  echo "Error: VM storage path does not exist: $VM_STORAGE_DIR"
  exit 1
fi

if [ -z "${HELLOWORLD_WINDOWS_BACKING_STORAGE:-}" ] && [ -f "$VM_STORAGE_DIR/.backing_storage_dir" ]; then
  HELLOWORLD_WINDOWS_BACKING_STORAGE=$(tr -d '\r' < "$VM_STORAGE_DIR/.backing_storage_dir")
fi

if [ -n "${HELLOWORLD_WINDOWS_BACKING_STORAGE:-}" ] && [ ! -d "$HELLOWORLD_WINDOWS_BACKING_STORAGE" ]; then
  echo "Error: Windows backing storage path does not exist: $HELLOWORLD_WINDOWS_BACKING_STORAGE"
  exit 1
fi

# Guest startup script and runtime payload are loaded from \\host.lan\Data (/shared).
VM_SHARED_DIR="${VM_SHARED_DIR:-$HELLOWORLD_DIR/platforms/windows/vm/setup}"
if [ ! -f "$VM_SHARED_DIR/on-logon.ps1" ] || [ ! -d "$VM_SHARED_DIR/server" ]; then
  echo "Error: VM shared directory must contain on-logon.ps1 and server/: $VM_SHARED_DIR"
  exit 1
fi

# Keep benchmark artifacts durable by writing /HelloWorld/results directly to
# the host from the start of the container lifetime.
HELLOWORLD_WINDOWS_RESULTS_DIR="${HELLOWORLD_WINDOWS_RESULTS_DIR:-$HELLOWORLD_DIR/results}"
mkdir -p "$HELLOWORLD_WINDOWS_RESULTS_DIR"

TEMP_CLIENT=""
if [ -z "$VM_CLIENT_DIR" ]; then
  TEMP_CLIENT=$(mktemp -d)
  VM_CLIENT_DIR="$TEMP_CLIENT"
else
  if [ ! -d "$VM_CLIENT_DIR" ]; then
    echo "Error: VM client directory does not exist: $VM_CLIENT_DIR"
    exit 1
  fi
fi
trap '[ -n "$TEMP_CLIENT" ] && rm -rf "$TEMP_CLIENT"' EXIT

DOCKER_BIN="docker"
if ! command -v docker >/dev/null 2>&1; then
  if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    DOCKER_BIN="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
  fi
fi

DOCKER_BIN_RESOLVED=$(command -v "$DOCKER_BIN" 2>/dev/null || echo "$DOCKER_BIN")
DOCKER_IS_WINDOWS_EXE=false
if [[ "$DOCKER_BIN" == *.exe ]] || [[ "$DOCKER_BIN_RESOLVED" == *.exe ]]; then
  DOCKER_IS_WINDOWS_EXE=true
fi
ALLOW_FORCE_REMOVE="${HELLOWORLD_WINDOWS_ALLOW_FORCE_REMOVE:-false}"

normalize_docker_mount_path() {
  local p="$1"
  local drive=""
  local rest=""

  # When using docker.exe from Windows shells, convert /mnt/d/... to D:/...
  if [ "$DOCKER_IS_WINDOWS_EXE" = true ]; then
    if [[ "$p" =~ ^/mnt/([a-zA-Z])/(.*)$ ]]; then
      drive="${BASH_REMATCH[1]}"
      rest="${BASH_REMATCH[2]}"
      drive=$(echo "$drive" | tr '[:lower:]' '[:upper:]')
      echo "${drive}:/${rest}"
      return 0
    fi
    if [[ "$p" =~ ^/([a-zA-Z])/(.*)$ ]]; then
      drive="${BASH_REMATCH[1]}"
      rest="${BASH_REMATCH[2]}"
      drive=$(echo "$drive" | tr '[:lower:]' '[:upper:]')
      echo "${drive}:/${rest}"
      return 0
    fi
  fi

  echo "$p"
}

graceful_shutdown_vm() {
  local reason="${1:-cleanup}"

  if ! "$DOCKER_BIN" container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    return 0
  fi

  echo ">>> Graceful cleanup ($reason)"
  echo ">>> Resetting guest to generic clean state..."
  cat <<'JSON' | "$DOCKER_BIN" exec -i "$CONTAINER_NAME" sh -lc 'cat >/tmp/hw_cleanup.json && curl -s -m 180 -X POST -H "Authorization: Bearer '"$RUNTIME_TOKEN"'" -H "Content-Type: application/json" --data @/tmp/hw_cleanup.json http://20.20.20.21:5000/setup/execute >/tmp/hw_cleanup_resp.json 2>/tmp/hw_cleanup_err.txt || true'
{"command":["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File","\\\\host.lan\\Data\\cleanup-generic-state.ps1"],"shell":false,"timeout":240}
JSON

  echo ">>> Requesting graceful Windows shutdown..."
  "$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 10 -H "Authorization: Bearer $RUNTIME_TOKEN" -X POST "http://$WINDOWS_VM_IP:5000/shutdown" >/dev/null 2>&1 || true

  for i in $(seq 1 36); do
    if ! "$DOCKER_BIN" container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
      break
    fi
    if ! "$DOCKER_BIN" exec "$CONTAINER_NAME" pgrep -f qemu-system-x86_64 >/dev/null 2>&1; then
      echo ">>> VM process exited cleanly"
      break
    fi
    sleep 5
  done

  "$DOCKER_BIN" stop -t 120 "$CONTAINER_NAME" >/dev/null 2>&1 || true
  "$DOCKER_BIN" rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

  if "$DOCKER_BIN" container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    if [ "$ALLOW_FORCE_REMOVE" = "true" ]; then
      echo ">>> Graceful stop did not finish, force-removing container..."
      "$DOCKER_BIN" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    else
      echo "Warning: $CONTAINER_NAME is still present after graceful cleanup."
      echo "Set HELLOWORLD_WINDOWS_ALLOW_FORCE_REMOVE=true to allow rm -f fallback."
      return 1
    fi
  fi
}

reset_working_storage_from_golden() {
  local reason="${1:-execution}"
  local source_dir="${HELLOWORLD_WINDOWS_GOLDEN_STORAGE:-$HELLOWORLD_DIR/platforms/windows/vm/storage.golden}"
  local target_dir="${VM_STORAGE_DIR:-$HELLOWORLD_DIR/platforms/windows/vm/storage}"

  echo ">>> Recreating Windows overlay storage from golden ($reason)..."
  bash "$HELLOWORLD_DIR/platforms/windows/scripts/create_windows_overlay_storage.sh" \
    --source-dir "$source_dir" \
    --target-dir "$target_dir" \
    --container-name "$CONTAINER_NAME" \
    --overwrite true
}

sync_results_to_host() {
  if ! "$DOCKER_BIN" container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    return 0
  fi
  mkdir -p "$HELLOWORLD_WINDOWS_RESULTS_DIR"
  local probe=".host_bind_probe_$$"
  rm -f "$HELLOWORLD_WINDOWS_RESULTS_DIR/$probe"
  if "$DOCKER_BIN" exec "$CONTAINER_NAME" sh -lc "mkdir -p /HelloWorld/results && touch /HelloWorld/results/$probe" 2>/dev/null \
      && [ -f "$HELLOWORLD_WINDOWS_RESULTS_DIR/$probe" ]; then
    rm -f "$HELLOWORLD_WINDOWS_RESULTS_DIR/$probe"
    "$DOCKER_BIN" exec "$CONTAINER_NAME" rm -f "/HelloWorld/results/$probe" >/dev/null 2>&1 || true
    echo ">>> Results are host bind-mounted at $HELLOWORLD_WINDOWS_RESULTS_DIR"
    return 0
  fi
  "$DOCKER_BIN" exec "$CONTAINER_NAME" rm -f "/HelloWorld/results/$probe" >/dev/null 2>&1 || true

  if "$DOCKER_BIN" cp "$CONTAINER_NAME":/HelloWorld/results/. "$HELLOWORLD_WINDOWS_RESULTS_DIR/" 2>/dev/null; then
    echo ">>> Results synced to host via docker cp"
    return 0
  fi

  echo ">>> docker cp result sync failed; trying tar-stream fallback..."
  if "$DOCKER_BIN" exec "$CONTAINER_NAME" sh -lc 'tar -C /HelloWorld/results -cf - .' | tar -C "$HELLOWORLD_WINDOWS_RESULTS_DIR" -xf -; then
    echo ">>> Results synced to host via tar stream fallback"
    return 0
  fi

  echo "Warning: Failed to sync /HelloWorld/results back to host."
  return 1
}

runtime_http_code() {
  local method="$1"
  local path="$2"
  local port="${3:-$ACTIVE_RUNTIME_PORT}"
  "$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 8 -o /tmp/hw_runtime_probe.txt -w "%{http_code}" -X "$method" \
    -H "Authorization: Bearer $RUNTIME_TOKEN" \
    "http://${WINDOWS_VM_IP}:${port}${path}" 2>/dev/null || echo "000"
}

log_runtime_endpoint_status() {
  local port="${1:-$ACTIVE_RUNTIME_PORT}"
  local probe_code health_code schema_code
  probe_code=$(runtime_http_code "GET" "/probe" "$port")
  health_code=$(runtime_http_code "GET" "/health" "$port")
  schema_code=$(runtime_http_code "GET" "/action_schema" "$port")
  echo ">>> Runtime endpoint status on :$port => probe=$probe_code health=$health_code action_schema=$schema_code"
}

runtime_has_helloworld_api() {
  local port="${1:-$ACTIVE_RUNTIME_PORT}"
  local health_code schema_code
  health_code=$(runtime_http_code "GET" "/health" "$port")
  schema_code=$(runtime_http_code "GET" "/action_schema" "$port")
  [ "$health_code" = "200" ] && [ "$schema_code" = "200" ]
}

bootstrap_unified_runtime_on_port() {
  local target_port="$1"

  if [ -z "$target_port" ]; then
    return 1
  fi

  cat <<'JSON' | sed "s/__TARGET_PORT__/$target_port/g; s/__RUNTIME_TOKEN__/$RUNTIME_TOKEN/g" | "$DOCKER_BIN" exec -i "$CONTAINER_NAME" sh -lc 'cat >/tmp/hw_bootstrap.json && curl -s -m 180 -X POST -H "Content-Type: application/json" --data @/tmp/hw_bootstrap.json http://'"$WINDOWS_VM_IP"':5000/setup/execute >/tmp/hw_bootstrap_resp.json 2>/tmp/hw_bootstrap_err.txt || true'
{"command":["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command","$ErrorActionPreference='SilentlyContinue'; $port='__TARGET_PORT__'; $token='__RUNTIME_TOKEN__'; $script='\\\\host.lan\\Data\\server\\helloworld_server.py'; if (-not (Test-Path $script)) { Write-Output 'MISSING_HELLOWORLD_SERVER'; exit 1 }; Remove-Item Env:WERKZEUG_SERVER_FD -ErrorAction SilentlyContinue; Remove-Item Env:WERKZEUG_RUN_MAIN -ErrorAction SilentlyContinue; if (-not (Get-NetFirewallRule -DisplayName ('HelloWorld-' + $port) -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName ('HelloWorld-' + $port) -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Any | Out-Null }; try { Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } catch {}; Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(python|py)\\.exe$' -and $_.CommandLine -and ($_.CommandLine -match 'main.py' -or $_.CommandLine -match 'helloworld_server.py') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 1; Start-Process -WindowStyle Hidden -FilePath 'py' -ArgumentList '-3',$script,'--host','0.0.0.0','--port',$port,'--token',$token; Start-Sleep -Seconds 3; Write-Output ('HELLOWORLD_RUNTIME_BOOTSTRAPPED_' + $port)"],"shell":false,"timeout":240}
JSON
}

stage_shared_assets() {
  # Copy files that tasks expect in known Windows locations from the shared
  # \\host.lan\Data folder (mapped from platforms/windows/vm/setup/). Runs on
  # every VM start so manual sessions and benchmark runs both see a consistent
  # starting state.
  cat <<'JSON' | "$DOCKER_BIN" exec -i "$CONTAINER_NAME" sh -lc 'cat >/tmp/hw_stage.json && curl -s -m 60 -X POST -H "Content-Type: application/json" --data @/tmp/hw_stage.json http://'"$WINDOWS_VM_IP"':5000/setup/execute >/dev/null 2>&1 || true'
{"command":["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command","$dl = 'C:\\Users\\Docker\\Downloads'; if (-not (Test-Path $dl)) { New-Item -ItemType Directory -Path $dl -Force | Out-Null }; $src = '\\\\host.lan\\Data\\sample.pcapng'; if (Test-Path $src) { Copy-Item $src (Join-Path $dl 'sample.pcapng') -Force }"],"shell":false,"timeout":60}
JSON
}

bootstrap_helloworld_runtime_if_needed() {
  log_runtime_endpoint_status "$PRIMARY_RUNTIME_PORT"
  if runtime_has_helloworld_api "$PRIMARY_RUNTIME_PORT"; then
    ACTIVE_RUNTIME_PORT="$PRIMARY_RUNTIME_PORT"
    echo ">>> Unified runtime API is ready on primary port $ACTIVE_RUNTIME_PORT"
    return 0
  fi

  echo ">>> Primary runtime on port $PRIMARY_RUNTIME_PORT is not unified; remediating in-guest runtime..."
  bootstrap_unified_runtime_on_port "$PRIMARY_RUNTIME_PORT"

  for i in $(seq 1 30); do
    if runtime_has_helloworld_api "$PRIMARY_RUNTIME_PORT"; then
      ACTIVE_RUNTIME_PORT="$PRIMARY_RUNTIME_PORT"
      echo ">>> HelloWorld runtime API is ready on port $ACTIVE_RUNTIME_PORT"
      return 0
    fi
    sleep 2
  done

  log_runtime_endpoint_status "$PRIMARY_RUNTIME_PORT"
  if [ "$ALLOW_RUNTIME_FALLBACK_5001" != "true" ]; then
    echo "Error: Unified runtime API is still unavailable on primary port $PRIMARY_RUNTIME_PORT."
    echo "       Refusing to run execution against legacy runtime."
    return 1
  fi

  echo "Warning: Primary port $PRIMARY_RUNTIME_PORT is not unified."
  echo "         Trying fallback port $FALLBACK_RUNTIME_PORT because HELLOWORLD_WINDOWS_ALLOW_RUNTIME_FALLBACK_5001=true"
  bootstrap_unified_runtime_on_port "$FALLBACK_RUNTIME_PORT"
  for i in $(seq 1 30); do
    if runtime_has_helloworld_api "$FALLBACK_RUNTIME_PORT"; then
      ACTIVE_RUNTIME_PORT="$FALLBACK_RUNTIME_PORT"
      echo ">>> HelloWorld runtime API is ready on fallback port $ACTIVE_RUNTIME_PORT"
      return 0
    fi
    sleep 2
  done

  log_runtime_endpoint_status "$FALLBACK_RUNTIME_PORT"
  echo "Error: Unified runtime API unavailable on both primary and fallback ports."
  return 1
}

if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  echo "Error: Docker daemon is not running."
  exit 1
fi

ensure_greenmail_for_execution_if_needed() {
  if [ -z "$EXECUTION" ]; then
    return 0
  fi

  local exec_path="$EXECUTION"
  if [[ "$exec_path" != */* ]]; then
    exec_path="executions/${exec_path}.yaml"
  fi
  if [[ "$exec_path" != /* ]]; then
    exec_path="$HELLOWORLD_DIR/$exec_path"
  fi

  if [ ! -f "$exec_path" ]; then
    return 0
  fi

  if ! grep -Eiq 'deltachat|greenmail' "$exec_path"; then
    return 0
  fi

  local greenmail_script="$HELLOWORLD_DIR/scripts/start_greenmail_no_docker.ps1"
  if [ ! -f "$greenmail_script" ]; then
    echo "Error: execution needs GreenMail, but no-Docker start script is missing: $greenmail_script"
    exit 1
  fi

  local powershell_bin="${POWERSHELL_BIN:-powershell.exe}"
  if ! command -v "$powershell_bin" >/dev/null 2>&1; then
    powershell_bin="${POWERSHELL_BIN:-powershell}"
  fi
  if ! command -v "$powershell_bin" >/dev/null 2>&1; then
    echo "Error: execution needs GreenMail, but PowerShell is unavailable for no-Docker startup."
    exit 1
  fi

  local greenmail_script_for_ps="$greenmail_script"
  if command -v wslpath >/dev/null 2>&1; then
    greenmail_script_for_ps="$(wslpath -w "$greenmail_script")"
  fi

  echo ">>> Execution references Delta Chat/GreenMail; ensuring no-Docker GreenMail is ready..."
  "$powershell_bin" -NoProfile -ExecutionPolicy Bypass -File "$greenmail_script_for_ps"
}

ensure_greenmail_for_execution_if_needed

VM_STORAGE_DIR_DOCKER=$(normalize_docker_mount_path "$VM_STORAGE_DIR")
VM_SHARED_DIR_DOCKER=$(normalize_docker_mount_path "$VM_SHARED_DIR")
VM_CLIENT_DIR_DOCKER=$(normalize_docker_mount_path "$VM_CLIENT_DIR")
RESULTS_DIR_DOCKER=$(normalize_docker_mount_path "$HELLOWORLD_WINDOWS_RESULTS_DIR")
BACKING_MOUNT_ARGS=()
if [ -n "${HELLOWORLD_WINDOWS_BACKING_STORAGE:-}" ]; then
  VM_BACKING_STORAGE_DOCKER=$(normalize_docker_mount_path "$HELLOWORLD_WINDOWS_BACKING_STORAGE")
  BACKING_MOUNT_ARGS=(-v "${VM_BACKING_STORAGE_DOCKER}/.:/storage.golden:ro")
fi

echo "=== HelloWorld Windows VM Launcher ==="
if [ -n "$EXECUTION" ]; then
  echo "    Mode: run execution then auto-shutdown"
  echo "    Execution: $EXECUTION"
else
  echo "    Mode: keep VM running (manual stop: graceful shutdown then docker stop)"
fi
echo "    Image: $HELLOWORLD_WINDOWS_IMAGE"
echo "    Storage: $VM_STORAGE_DIR_DOCKER"
echo "    Results: $RESULTS_DIR_DOCKER"
echo "    VNC Port: $VNC_HOST_PORT"
echo "    RDP Port: $RDP_HOST_PORT"
if [ -n "${HELLOWORLD_WINDOWS_BACKING_STORAGE:-}" ]; then
  echo "    Backing: $VM_BACKING_STORAGE_DOCKER"
fi
echo ""

echo "[1/6] Removing old container..."
if "$DOCKER_BIN" container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "       Found existing $CONTAINER_NAME container"
  graceful_shutdown_vm "startup_cleanup"
fi

if [[ "$RESET_BEFORE_START" =~ ^([Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])$ ]] || \
   { [ -n "$EXECUTION" ] && [[ "$RESET_BEFORE_EXECUTION" =~ ^([Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])$ ]]; }; then
  if [ -n "$EXECUTION" ]; then
    reset_working_storage_from_golden "before_execution"
  else
    reset_working_storage_from_golden "before_manual_start"
  fi
fi

echo "[2/6] Starting container..."

OPENAI_KEY=""
if [ -f "$HELLOWORLD_DIR/.env" ]; then
  OPENAI_KEY=$(grep -E '^OPENAI_API_KEY=' "$HELLOWORLD_DIR/.env" | cut -d'=' -f2- | tr -d '\r')
fi

"$DOCKER_BIN" run --rm -d \
  -p "${VNC_HOST_PORT}:8006" -p "${RDP_HOST_PORT}:3389" \
  -p "${PRIMARY_RUNTIME_PORT}:${PRIMARY_RUNTIME_PORT}" -p "${FALLBACK_RUNTIME_PORT}:${FALLBACK_RUNTIME_PORT}" \
  --name "$CONTAINER_NAME" \
  --platform linux/amd64 \
  --device=/dev/kvm \
  -e RAM_SIZE="$WINDOWS_RAM_SIZE" -e CPU_CORES="$WINDOWS_CPU_CORES" \
  -e ARGUMENTS="$AUDIO_QEMU_ARGS" \
  -v "${VM_STORAGE_DIR_DOCKER}/.:/storage" \
  "${BACKING_MOUNT_ARGS[@]}" \
  -v "${VM_SHARED_DIR_DOCKER}/.:/shared" \
  -v "${VM_CLIENT_DIR_DOCKER}/.:/client" \
  -v "${RESULTS_DIR_DOCKER}/.:/HelloWorld/results" \
  --cap-add NET_ADMIN --stop-timeout 120 \
  --entrypoint /bin/bash \
  ${OPENAI_KEY:+-e OPENAI_API_KEY=$OPENAI_KEY} \
  "$HELLOWORLD_WINDOWS_IMAGE" \
  -c 'tail -f /dev/null' \
  > /dev/null 2>&1 &

echo "       Waiting for container startup..."
for i in $(seq 1 30); do
  if "$DOCKER_BIN" container inspect "$CONTAINER_NAME" > /dev/null 2>&1; then
    echo "       Container is up"
    break
  fi
  sleep 2
done

echo "[3/6] Checking QEMU startup..."
sleep 5
if "$DOCKER_BIN" exec "$CONTAINER_NAME" pgrep -f qemu-system-x86_64 >/dev/null 2>&1; then
  echo "       QEMU already running from container entrypoint; skipping duplicate start"
else
  echo "       QEMU not detected; preparing fallback boot marker"
  "$DOCKER_BIN" exec "$CONTAINER_NAME" bash -c 'touch /storage/windows.boot 2>/dev/null || true'
  sleep 2
  echo "       Starting QEMU fallback..."
  "$DOCKER_BIN" exec -d "$CONTAINER_NAME" bash -c '/usr/bin/tini -s /run/entry.sh'
fi

echo "[4/6] Syncing HelloWorld code..."
"$DOCKER_BIN" exec "$CONTAINER_NAME" mkdir -p /HelloWorld
cd "$HELLOWORLD_DIR"
tar cf - \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='results' \
  --exclude='mine' \
  --exclude='.env' \
  --exclude='tests' \
  --exclude='workbench' \
  --exclude='*.pyc' \
  --exclude='platforms/windows/vm' \
  . 2>/dev/null | "$DOCKER_BIN" exec -i "$CONTAINER_NAME" tar xf - -C /HelloWorld
"$DOCKER_BIN" exec "$CONTAINER_NAME" bash -c "apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-yaml socat >/dev/null 2>&1" || true
"$DOCKER_BIN" exec "$CONTAINER_NAME" bash -c "ln -sf /usr/bin/python3 /usr/bin/python" || true
"$DOCKER_BIN" exec "$CONTAINER_NAME" bash -c "pip3 install --break-system-packages -q pyyaml requests pillow openai python-dotenv httpx 2>/dev/null" || true
echo "       Code synced"

echo "[5/6] Waiting for runtime server..."
echo "       VNC: http://localhost:$VNC_HOST_PORT"
echo ""

for i in $(seq 1 60); do
  result=$("$DOCKER_BIN" exec "$CONTAINER_NAME" curl -s -m 10 "http://$WINDOWS_VM_IP:5000/probe" 2>/dev/null || echo "")
  if echo "$result" | grep -q 'Probe'; then
    echo ""
    echo "=== VM runtime is ready ==="
    echo ""
    if ! bootstrap_helloworld_runtime_if_needed; then
      echo "=== Runtime protocol check failed ==="
      graceful_shutdown_vm "runtime_protocol_mismatch" || true
      exit 1
    fi

    "$DOCKER_BIN" exec "$CONTAINER_NAME" sh -lc "pkill -f 'socat TCP-LISTEN:${ACTIVE_RUNTIME_PORT}' >/dev/null 2>&1 || true; nohup socat TCP-LISTEN:${ACTIVE_RUNTIME_PORT},fork,reuseaddr TCP:${WINDOWS_VM_IP}:${ACTIVE_RUNTIME_PORT} >/tmp/hw_runtime_forward_${ACTIVE_RUNTIME_PORT}.log 2>&1 &" || true

    stage_shared_assets

    if [ -n "$EXECUTION" ]; then
      EXEC_PATH="$EXECUTION"
      if [[ "$EXEC_PATH" != */* ]]; then
        EXEC_PATH="executions/${EXEC_PATH}.yaml"
      fi

      echo ">>> Running execution: $EXEC_PATH"
      echo ""

      ENV_DOCKER_ARGS=()
      add_env_arg_if_present() {
        local key="$1"
        local value="${!key}"
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

          # Only pass valid shell environment variable names.
          [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
          ENV_DOCKER_ARGS+=( -e "$key=$value" )
        done < "$HELLOWORLD_DIR/.env"
      fi
      add_env_arg_if_present "OPENAI_API_KEY"
      add_env_arg_if_present "OPENAI_BASE_URL"
      add_env_arg_if_present "OPENAI_ORG_ID"
      add_env_arg_if_present "OPENAI_PROJECT"

      cleanup_execution() {
        echo ""
        echo ">>> Copying results to local..."
        sync_results_to_host || true
        graceful_shutdown_vm "post_execution" || true
        if [[ "$RESET_AFTER_EXECUTION" =~ ^([Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])$ ]]; then
          reset_working_storage_from_golden "after_execution"
        fi
      }
      trap cleanup_execution EXIT INT TERM

      set +e
      "$DOCKER_BIN" exec "${ENV_DOCKER_ARGS[@]}" "$CONTAINER_NAME" bash -c "cd /HelloWorld && \
        HELLOWORLD_WINDOWS_VM_IP=$WINDOWS_VM_IP \
        HELLOWORLD_WINDOWS_RUNTIME_PORT=$ACTIVE_RUNTIME_PORT \
        HELLOWORLD_WINDOWS_RUNTIME_TOKEN=$RUNTIME_TOKEN \
        python -m platforms.windows.cli --execution $EXEC_PATH"
      EXIT_CODE=$?
      set -e

      trap - EXIT INT TERM
      echo ""
      echo ">>> Execution finished (exit code: $EXIT_CODE)"
      cleanup_execution
      exit $EXIT_CODE
    fi

    echo "    VM IP:    $WINDOWS_VM_IP"
    echo "    Port:     $ACTIVE_RUNTIME_PORT"
    echo "    VNC:      http://localhost:$VNC_HOST_PORT"
    echo ""
    echo "    Stop (recommended):"
    echo "      docker exec $CONTAINER_NAME curl -H 'Authorization: Bearer $RUNTIME_TOKEN' -X POST http://$WINDOWS_VM_IP:5000/shutdown"
    echo "      docker stop $CONTAINER_NAME"
    echo ""
    echo "    Container is running in background"
    exit 0
  fi

  elapsed=$((i * 15))
  printf "\r       Waited %d seconds..." $elapsed
  sleep 15
done

echo ""
echo "=== Timeout waiting for runtime server ==="
graceful_shutdown_vm "runtime_timeout" || true

exit 1
