#!/usr/bin/env bash
set -euo pipefail

choose_runtime() {
  if [[ -n "${GREENMAIL_CONTAINER_RUNTIME:-}" ]]; then
    echo "${GREENMAIL_CONTAINER_RUNTIME}"
    return 0
  fi

  if command -v podman >/dev/null 2>&1; then
    echo "podman"
    return 0
  fi

  if command -v docker >/dev/null 2>&1; then
    echo "docker"
    return 0
  fi

  if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    echo "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
    return 0
  fi

  echo "Neither podman nor docker is available in PATH." >&2
  return 1
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Required command not found: $cmd" >&2
    exit 1
  fi
}

require_runtime() {
  local runtime="$1"
  if [[ "$runtime" == */* ]]; then
    if [ ! -x "$runtime" ]; then
      echo "Required container runtime is not executable: $runtime" >&2
      exit 1
    fi
    return 0
  fi

  require_cmd "$runtime"
}

RUNTIME="$(choose_runtime)"
require_runtime "$RUNTIME"
require_cmd curl

CONTAINER_NAME="${GREENMAIL_CONTAINER_NAME:-greenmail-bench}"
IMAGE="${GREENMAIL_IMAGE:-docker.io/greenmail/standalone:2.1.8}"
HOSTNAME_BIND="${GREENMAIL_HOSTNAME:-0.0.0.0}"
HTTP_PORT="${GREENMAIL_HTTP_PORT:-8081}"
SMTP_PORT="${GREENMAIL_SMTP_PORT:-3025}"
IMAP_PORT="${GREENMAIL_IMAP_PORT:-3143}"
WAIT_TIMEOUT_SECONDS="${GREENMAIL_WAIT_TIMEOUT_SECONDS:-30}"
GREENMAIL_USERS="${GREENMAIL_USERS:-benchsender@example.test:benchpass,benchrecv@example.test:benchpass,benchchat@example.test:benchpass,avery.design@example.test:benchpass,morgan.ops@example.test:benchpass,jordan.travel@example.test:benchpass}"
GREENMAIL_OPTS_VALUE="${GREENMAIL_OPTS_OVERRIDE:--Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap -Dgreenmail.hostname=${HOSTNAME_BIND} -Dgreenmail.users=${GREENMAIL_USERS} -Dgreenmail.users.login=email -Dgreenmail.verbose}"
READINESS_URL="${GREENMAIL_API_BASE_URL:-http://127.0.0.1:${HTTP_PORT}}/api/service/readiness"

if payload="$(curl -fsS "$READINESS_URL" 2>/dev/null)" && [[ "$payload" == *"Service running"* ]]; then
  echo "GreenMail is already ready at $READINESS_URL"
  echo "$payload"
  exit 0
fi

echo "Starting GreenMail with $RUNTIME..."
"$RUNTIME" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
"$RUNTIME" run -d \
  --name "$CONTAINER_NAME" \
  -e "GREENMAIL_OPTS=${GREENMAIL_OPTS_VALUE}" \
  -p "${SMTP_PORT}:3025" \
  -p "${IMAP_PORT}:3143" \
  -p "${HTTP_PORT}:8080" \
  "$IMAGE" >/dev/null

deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
while true; do
  if payload="$(curl -fsS "$READINESS_URL" 2>/dev/null)" && [[ "$payload" == *"Service running"* ]]; then
    echo "GreenMail is ready."
    echo "Runtime: $RUNTIME"
    echo "Container: $CONTAINER_NAME"
    echo "Readiness URL: $READINESS_URL"
    echo "$payload"
    exit 0
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for GreenMail readiness: $READINESS_URL" >&2
    "$RUNTIME" logs --tail 80 "$CONTAINER_NAME" || true
    exit 1
  fi

  sleep 1
done
