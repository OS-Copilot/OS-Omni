#!/usr/bin/env bash
set -euo pipefail

LAB_LABEL="com.yourlab.macui.runtime"
INSTALL_DIR="/Applications/MacUIBenchRuntime/runtime"
VENV_DIR="$INSTALL_DIR/.venv"
TOKEN_FILE="$INSTALL_DIR/token.txt"
PLIST_PATH="$HOME/Library/LaunchAgents/${LAB_LABEL}.plist"

MACUI_BIND="${MACUI_BIND:-0.0.0.0}"
MACUI_PORT="${MACUI_PORT:-5000}"
MACUI_TOKEN="${MACUI_TOKEN:-}"
TOKEN_FIXED_DEFAULT="macuibench-runtime-token"
MACUI_HEALTH_RETRIES="${MACUI_HEALTH_RETRIES:-80}"
MACUI_HEALTH_INTERVAL="${MACUI_HEALTH_INTERVAL:-0.25}"
MACUI_SCREENSHOT_RETRIES="${MACUI_SCREENSHOT_RETRIES:-20}"
MACUI_SCREENSHOT_INTERVAL="${MACUI_SCREENSHOT_INTERVAL:-1}"

log() { printf '%s\n' "$*" >&2; }

if [[ ${EUID} -eq 0 ]]; then
  log "Please run as the login user (do not use sudo for the whole script)."
  log "Example: bash install_macos_vm.sh"
  exit 1
fi

# Check SIP status early and warn
sip_status="$(csrutil status 2>&1 || true)"
if echo "$sip_status" | grep -q "enabled"; then
  log ""
  log "⚠️  WARNING: System Integrity Protection (SIP) is ENABLED"
  log "   TCC permissions cannot be auto-injected."
  log "   You will need to manually grant permissions in System Settings."
  log "   To enable auto-injection, disable SIP via Recovery Mode:"
  log "     1. Restart and hold Cmd+R"
  log "     2. Open Terminal from Utilities menu"
  log "     3. Run: csrutil disable"
  log "     4. Reboot and re-run this script"
  log ""
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { log "Missing required command: $1"; exit 1; }
}

run_with_retry() {
  local max_tries="$1"
  shift
  local attempt=1
  while (( attempt <= max_tries )); do
    if "$@"; then
      return 0
    fi
    if (( attempt == max_tries )); then
      return 1
    fi
    log "Retry ${attempt}/${max_tries} failed; trying again..."
    sleep $((attempt * 2))
    attempt=$((attempt + 1))
  done
}

ensure_runtime_python_modules() {
  "$VENV_DIR/bin/python" - <<'PY'
import importlib

required = ["flask", "Quartz", "AppKit", "ApplicationServices"]
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name}: {exc}")

if missing:
    print("Missing python modules:")
    for item in missing:
        print(f"  - {item}")
    raise SystemExit(1)

print("Python runtime modules OK.")
PY
}

write_launchagent_plist() {
  local tmp_plist
  tmp_plist="$(mktemp /tmp/macui-runtime.plist.XXXXXX)"
  cat >"$tmp_plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LAB_LABEL}</string>

  <key>WorkingDirectory</key>
  <string>${INSTALL_DIR}</string>

  <key>ProgramArguments</key>
  <array>
    <string>${VENV_DIR}/bin/python</string>
    <string>${INSTALL_DIR}/runtime_server.py</string>
    <string>--bind</string>
    <string>${MACUI_BIND}</string>
    <string>--port</string>
    <string>${MACUI_PORT}</string>
    <string>--token-file</string>
    <string>${TOKEN_FILE}</string>
  </array>

  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/tmp/macui-runtime.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/macui-runtime.err.log</string>
</dict>
</plist>
PLIST

  /usr/bin/plutil -lint "$tmp_plist" >/dev/null

  if ! /usr/bin/install -m 644 "$tmp_plist" "$PLIST_PATH" 2>/dev/null; then
    sudo_if_needed /usr/bin/install -m 644 "$tmp_plist" "$PLIST_PATH"
  fi

  rm -f "$tmp_plist"
}

ensure_brew_in_path() {
  if command -v brew >/dev/null 2>&1; then
    return 0
  fi
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

have_working_python3() {
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import sys, venv; print(sys.version)' >/dev/null 2>&1
}

ensure_xcode_clt() {
  if /usr/bin/xcode-select -p >/dev/null 2>&1; then
    return 0
  fi

  log "Xcode Command Line Tools not found; requesting install popup..."
  /usr/bin/xcode-select --install >/dev/null 2>&1 || true
  log "Please complete the popup install. Waiting for completion..."

  local waited=0
  local timeout=2700
  while ! /usr/bin/xcode-select -p >/dev/null 2>&1; do
    sleep 5
    waited=$((waited + 5))
    if (( waited % 60 == 0 )); then
      log "Still waiting for Xcode CLT install... ${waited}s"
    fi
    if (( waited >= timeout )); then
      log "Timed out waiting for Xcode CLT install."
      log "Re-run this script after CLT finishes."
      exit 1
    fi
  done

  log "Xcode Command Line Tools detected."
}

ensure_homebrew() {
  ensure_brew_in_path
  if command -v brew >/dev/null 2>&1; then
    return 0
  fi

  ensure_xcode_clt
  need_cmd curl
  log "Homebrew not found; installing (NONINTERACTIVE=1)..."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ensure_brew_in_path
  command -v brew >/dev/null 2>&1 || { log "Homebrew install finished but brew is not on PATH"; exit 1; }
}

ensure_python3() {
  if have_working_python3; then
    return 0
  fi

  ensure_xcode_clt
  if have_working_python3; then
    log "Using python3 from Xcode Command Line Tools."
    return 0
  fi

  ensure_homebrew
  log "python3 not found; installing via Homebrew..."
  if ! brew list python@3 >/dev/null 2>&1; then
    run_with_retry 3 brew install python@3 || run_with_retry 3 brew install python
  fi

  ensure_brew_in_path
  have_working_python3 || {
    log "python3 still not usable after brew install"
    log "If Homebrew asked for admin rights, run this in an admin account or install Python 3 manually."
    exit 1
  }
}

install_optional_tools() {
  ensure_brew_in_path
  if ! command -v brew >/dev/null 2>&1; then
    log "Homebrew not found; skip optional tool install (cliclick)."
    return 0
  fi
  if command -v cliclick >/dev/null 2>&1; then
    return 0
  fi
  log "Installing optional tool: cliclick (best effort)"
  if ! run_with_retry 2 brew install cliclick; then
    log "Warning: failed to install cliclick. Continuing without it."
  fi
}

inject_tcc_permissions() {
  # Only works if SIP is disabled
  local sip_status
  sip_status="$(csrutil status 2>&1 || true)"
  if echo "$sip_status" | grep -q "enabled"; then
    log "SIP is enabled - cannot auto-inject TCC permissions."
    log "Disable SIP via Recovery Mode (csrutil disable) for auto-permission injection."
    return 1
  fi

  log "SIP is disabled - injecting TCC permissions..."

  local python_bin="$VENV_DIR/bin/python"
  local python_real=""
  python_real="$("$python_bin" - <<'PY'
import os, sys
print(os.path.realpath(sys.executable))
PY
)"
  local python_clients=("$python_bin")
  if [[ -n "$python_real" && "$python_real" != "$python_bin" ]]; then
    python_clients+=("$python_real")
  fi
  local osascript_bin="/usr/bin/osascript"
  local terminal_app="/System/Applications/Utilities/Terminal.app"
  local system_events="com.apple.systemevents"

  # System-level TCC.db (for Accessibility, Screen Recording)
  local system_tcc_db="/Library/Application Support/com.apple.TCC/TCC.db"
  # User-level TCC.db (for AppleEvents/Automation)
  local user_tcc_db="$HOME/Library/Application Support/com.apple.TCC/TCC.db"
  
  # Ensure user TCC.db directory exists
  mkdir -p "$HOME/Library/Application Support/com.apple.TCC" 2>/dev/null || true

  upsert_path_permission() {
    local db="$1"
    local use_sudo="$2"
    local service="$3"
    local client_path="$4"
    if [[ "$use_sudo" == "1" ]]; then
      sudo sqlite3 "$db" "DELETE FROM access WHERE service='$service' AND client='$client_path';" 2>/dev/null || true
      if ! sudo sqlite3 "$db" "INSERT OR REPLACE INTO access (service, client, client_type, auth_value, auth_reason, auth_version, flags) VALUES ('$service', '$client_path', 1, 2, 4, 1, 0);" 2>/dev/null; then
        sudo sqlite3 "$db" "INSERT OR REPLACE INTO access (service, client, client_type, allowed, prompt_count) VALUES ('$service', '$client_path', 1, 1, 0);" 2>/dev/null || true
      fi
    else
      sqlite3 "$db" "DELETE FROM access WHERE service='$service' AND client='$client_path';" 2>/dev/null || true
      if ! sqlite3 "$db" "INSERT OR REPLACE INTO access (service, client, client_type, auth_value, auth_reason, auth_version, flags) VALUES ('$service', '$client_path', 1, 2, 4, 1, 0);" 2>/dev/null; then
        sqlite3 "$db" "INSERT OR REPLACE INTO access (service, client, client_type, allowed, prompt_count) VALUES ('$service', '$client_path', 1, 1, 0);" 2>/dev/null || true
      fi
    fi
  }

  # ========== Path-based permissions (Accessibility, Screen Recording) ==========
  local services=("kTCCServiceAccessibility" "kTCCServiceScreenCapture")
  for service in "${services[@]}"; do
    for client in "${python_clients[@]}"; do
      if [[ -f "$system_tcc_db" ]]; then
        log "Injecting $service -> $client (system TCC.db)"
        upsert_path_permission "$system_tcc_db" 1 "$service" "$client"
      fi
      if [[ -f "$user_tcc_db" ]]; then
        log "Injecting $service -> $client (user TCC.db)"
        upsert_path_permission "$user_tcc_db" 0 "$service" "$client"
      fi
    done
  done

  if [[ -f "$system_tcc_db" ]]; then
    log "Injecting Accessibility -> Terminal.app (system TCC.db)"
    upsert_path_permission "$system_tcc_db" 1 "kTCCServiceAccessibility" "$terminal_app"
  else
    log "System TCC.db not found at: $system_tcc_db"
  fi

  # ========== User-level permissions (AppleEvents/Automation) ==========
  log "Injecting TCC permission: AppleEvents (user-level TCC.db)"
  
  # Create user TCC.db if it doesn't exist (copy schema from system)
  if [[ ! -f "$user_tcc_db" ]]; then
    log "Creating user TCC.db..."
    # Try to trigger its creation by running a harmless osascript
    osascript -e 'return ""' 2>/dev/null || true
    sleep 0.5
  fi
  
  if [[ -f "$user_tcc_db" ]]; then
    # Grant Python (symlink + realpath) -> System Events
    for client in "${python_clients[@]}"; do
      log "Injecting AppleEvents: $client -> System Events"
      sqlite3 "$user_tcc_db" "DELETE FROM access WHERE service='kTCCServiceAppleEvents' AND client='$client' AND indirect_object_identifier='$system_events';" 2>/dev/null || true
      if ! sqlite3 "$user_tcc_db" "INSERT OR REPLACE INTO access (service, client, client_type, auth_value, auth_reason, auth_version, indirect_object_identifier, indirect_object_identifier_type, flags) VALUES ('kTCCServiceAppleEvents', '$client', 1, 2, 4, 1, '$system_events', 0, 0);" 2>/dev/null; then
        sqlite3 "$user_tcc_db" "INSERT OR REPLACE INTO access (service, client, client_type, allowed, prompt_count, indirect_object_identifier, indirect_object_identifier_type) VALUES ('kTCCServiceAppleEvents', '$client', 1, 1, 0, '$system_events', 0);" 2>/dev/null || true
      fi
    done
    
    # Grant osascript -> System Events
    log "Injecting: osascript -> System Events"
    sqlite3 "$user_tcc_db" "DELETE FROM access WHERE service='kTCCServiceAppleEvents' AND client='$osascript_bin' AND indirect_object_identifier='$system_events';" 2>/dev/null || true
    if ! sqlite3 "$user_tcc_db" "INSERT OR REPLACE INTO access (service, client, client_type, auth_value, auth_reason, auth_version, indirect_object_identifier, indirect_object_identifier_type, flags) VALUES ('kTCCServiceAppleEvents', '$osascript_bin', 1, 2, 4, 1, '$system_events', 0, 0);" 2>/dev/null; then
      sqlite3 "$user_tcc_db" "INSERT OR REPLACE INTO access (service, client, client_type, allowed, prompt_count, indirect_object_identifier, indirect_object_identifier_type) VALUES ('kTCCServiceAppleEvents', '$osascript_bin', 1, 1, 0, '$system_events', 0);" 2>/dev/null || true
    fi
    
    # Grant Terminal -> System Events
    log "Injecting: Terminal -> System Events"
    sqlite3 "$user_tcc_db" "DELETE FROM access WHERE service='kTCCServiceAppleEvents' AND client='com.apple.Terminal' AND indirect_object_identifier='$system_events';" 2>/dev/null || true
    if ! sqlite3 "$user_tcc_db" "INSERT OR REPLACE INTO access (service, client, client_type, auth_value, auth_reason, auth_version, indirect_object_identifier, indirect_object_identifier_type, flags) VALUES ('kTCCServiceAppleEvents', 'com.apple.Terminal', 0, 2, 4, 1, '$system_events', 0, 0);" 2>/dev/null; then
      sqlite3 "$user_tcc_db" "INSERT OR REPLACE INTO access (service, client, client_type, allowed, prompt_count, indirect_object_identifier, indirect_object_identifier_type) VALUES ('kTCCServiceAppleEvents', 'com.apple.Terminal', 0, 1, 0, '$system_events', 0);" 2>/dev/null || true
    fi
  else
    log "User TCC.db not found at: $user_tcc_db (will be created on first permission prompt)"
  fi

  log "TCC permission injection complete."
  
  # Restart TCC daemon to apply changes
  sudo killall -HUP tccd 2>/dev/null || true
  sleep 0.5
  
  return 0
}


probe_runtime_screenshot() {
  local screenshot_url="http://127.0.0.1:${MACUI_PORT}/screenshot"
  local status=""
  log "Probing runtime /screenshot endpoint..."
  for _ in $(seq 1 "$MACUI_SCREENSHOT_RETRIES"); do
    status="$(
      /usr/bin/curl -sS -m 10 -o /tmp/macui-runtime.screenshot.body -w "%{http_code}" \
        -H "Authorization: Bearer ${TOKEN}" \
        "$screenshot_url" || true
    )"
    if [[ "$status" == "200" ]]; then
      rm -f /tmp/macui-runtime.screenshot.body
      log "Runtime /screenshot probe OK."
      return 0
    fi
    sleep "$MACUI_SCREENSHOT_INTERVAL"
  done

  log "Runtime /screenshot probe failed (last HTTP status: ${status:-N/A})."
  if [[ -f /tmp/macui-runtime.screenshot.body ]]; then
    tail -n 20 /tmp/macui-runtime.screenshot.body 2>/dev/null || true
  fi

  log "Opening System Settings for manual grant..."
  /usr/bin/open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture" >/dev/null 2>&1 || true
  /usr/bin/open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" >/dev/null 2>&1 || true
  return 1
}

sudo_if_needed() {
  if [[ ${EUID} -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_SRC="$SCRIPT_DIR/runtime_server.py"
REQ_SRC="$SCRIPT_DIR/requirements.txt"

log "Installer script dir: $SCRIPT_DIR"
log "Runtime source file: $RUNTIME_SRC"

need_cmd id
need_cmd launchctl
need_cmd /usr/bin/plutil
need_cmd /usr/bin/curl
need_cmd sqlite3

ensure_python3

log "Creating install dir: $INSTALL_DIR"
sudo_if_needed mkdir -p "$INSTALL_DIR"
sudo_if_needed chown -R "$USER" "/Applications/MacUIBenchRuntime" || true

log "Deploying runtime_server.py + requirements.txt"
[[ -f "$RUNTIME_SRC" ]] || { log "Missing file: $RUNTIME_SRC"; exit 1; }
[[ -f "$REQ_SRC" ]] || { log "Missing file: $REQ_SRC"; exit 1; }

log "Checking runtime_server.py syntax (source)"
python3 - <<PY
import ast, pathlib, sys
path = pathlib.Path("$RUNTIME_SRC")
src = path.read_text(encoding="utf-8")
ast.parse(src)
print("syntax ok:", path)
PY

cp -f "$RUNTIME_SRC" "$INSTALL_DIR/runtime_server.py"
cp -f "$REQ_SRC" "$INSTALL_DIR/requirements.txt"

log "Creating venv: $VENV_DIR"
python3 -m venv "$VENV_DIR"

log "Installing Python deps"
export PIP_DISABLE_PIP_VERSION_CHECK=1
run_with_retry 5 "$VENV_DIR/bin/python" -m pip install --upgrade pip --timeout 30
run_with_retry 5 "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --timeout 30
log "Checking python runtime modules"
ensure_runtime_python_modules
install_optional_tools

log "Checking runtime_server.py syntax (deployed)"
"$VENV_DIR/bin/python" - <<PY
import ast, pathlib
path = pathlib.Path("$INSTALL_DIR/runtime_server.py")
src = path.read_text(encoding="utf-8")
ast.parse(src)
print("syntax ok:", path)
PY

if [[ -n "$MACUI_TOKEN" ]]; then
  TOKEN_OVERRIDE="${MACUI_TOKEN//$'\n'/}"
  if [[ -z "$TOKEN_OVERRIDE" ]]; then
    log "MACUI_TOKEN is empty after trimming newlines."
    exit 1
  fi
  TOKEN_TO_WRITE="$TOKEN_OVERRIDE"
  log "Using fixed token from MACUI_TOKEN"
else
  TOKEN_TO_WRITE="$TOKEN_FIXED_DEFAULT"
  log "Using default fixed token"
fi

umask 177
printf '%s\n' "$TOKEN_TO_WRITE" >"$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

mkdir -p "$HOME/Library/LaunchAgents"
if [[ ! -w "$HOME/Library/LaunchAgents" ]]; then
  sudo_if_needed chown "$USER":staff "$HOME/Library/LaunchAgents"
fi
if [[ -e "$PLIST_PATH" && ! -w "$PLIST_PATH" ]]; then
  sudo_if_needed chown "$USER":staff "$PLIST_PATH"
fi

log "Writing LaunchAgent: $PLIST_PATH"
write_launchagent_plist

UID_NUM="$(id -u)"

log "Restarting LaunchAgent (bootout -> bootstrap -> kickstart)"
launchctl bootout "gui/${UID_NUM}" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_PATH" || {
  log "launchctl bootstrap failed."
  log "Do not run this script with sudo; run as logged-in GUI user."
  exit 1
}
launchctl kickstart -k "gui/${UID_NUM}/${LAB_LABEL}" || {
  log "launchctl kickstart failed."
  exit 1
}

TOKEN="$(cat "$TOKEN_FILE")"
HEALTH_URL="http://127.0.0.1:${MACUI_PORT}/health"

log "Local health check: $HEALTH_URL"
ok=0
for _ in $(seq 1 "$MACUI_HEALTH_RETRIES"); do
  if /usr/bin/curl -fsS -H "Authorization: Bearer ${TOKEN}" "$HEALTH_URL" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep "$MACUI_HEALTH_INTERVAL"
done

if [[ "$ok" -ne 1 ]]; then
  log "Health check failed. Inspect logs:"
  log "LaunchAgent status:"
  launchctl print "gui/${UID_NUM}/${LAB_LABEL}" 2>/dev/null | tail -n 40 || true
  log "Health endpoint probe (headers + body):"
  /usr/bin/curl -sS -D /tmp/macui-runtime.health.headers \
    -H "Authorization: Bearer ${TOKEN}" "$HEALTH_URL" \
    -o /tmp/macui-runtime.health.body || true
  tail -n 20 /tmp/macui-runtime.health.headers 2>/dev/null || true
  tail -n 20 /tmp/macui-runtime.health.body 2>/dev/null || true
  log "---- /tmp/macui-runtime.out.log (tail) ----"
  tail -n 80 /tmp/macui-runtime.out.log 2>/dev/null || true
  log "---- /tmp/macui-runtime.err.log (tail) ----"
  tail -n 80 /tmp/macui-runtime.err.log 2>/dev/null || true
  log "  /tmp/macui-runtime.out.log"
  log "  /tmp/macui-runtime.err.log"
  exit 1
fi

inject_tcc_permissions || log "TCC injection skipped or failed (manual grant may be needed)"
launchctl kickstart -k "gui/${UID_NUM}/${LAB_LABEL}" >/dev/null 2>&1 || true

# Probe screenshot to verify permissions
if probe_runtime_screenshot; then
  log "OK. Runtime server is up and permissions are working."
else
  log "OK. Runtime server is up but screenshot probe failed."
  log "If SIP is enabled, manually grant permissions:"
  log "  System Settings -> Privacy & Security -> Screen Recording"
  log "  System Settings -> Privacy & Security -> Accessibility"
  log "Grant permission to: ${VENV_DIR}/bin/python"
fi

log ""
log "Token stored at: $TOKEN_FILE (chmod 600)"
log "Token value in use: $TOKEN"
