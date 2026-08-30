#!/bin/bash
# Run Windows executions one by one, restoring VM storage before each execution.
# Example:
#   bash platforms/windows/scripts/run_all_windows_executions.sh \
#     --source-dir platforms/windows/vm/storage.golden

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."
HELLOWORLD_DIR="$WINDOWS_DIR/../.."
ENV_FILE="$HELLOWORLD_DIR/.env"

SOURCE_DIR="${HELLOWORLD_WINDOWS_GOLDEN_STORAGE:-}"
TARGET_DIR="${VM_STORAGE_DIR:-}"
EXECUTIONS_DIR="$HELLOWORLD_DIR/executions/windows"
PATTERN=""
START_FROM=""
MAX_TASKS=0
STOP_ON_FAIL=false
DRY_RUN=false
RESET_BEFORE_EACH=true
RESET_MODE="${HELLOWORLD_WINDOWS_RESET_MODE:-overlay}"
SHOW_PROGRESS=false

if [ -f "$ENV_FILE" ]; then
  if [ -z "$SOURCE_DIR" ]; then
    SOURCE_DIR=$(grep -E '^HELLOWORLD_WINDOWS_GOLDEN_STORAGE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  fi
  if [ -z "$TARGET_DIR" ]; then
    TARGET_DIR=$(grep -E '^VM_STORAGE_DIR=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '\r' | tr -d '"' | tr -d "'" || true)
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
    --executions-dir)
      EXECUTIONS_DIR="$2"
      shift 2
      ;;
    --pattern)
      PATTERN="$2"
      shift 2
      ;;
    --start-from)
      START_FROM="$2"
      shift 2
      ;;
    --max-tasks)
      MAX_TASKS="$2"
      shift 2
      ;;
    --stop-on-fail)
      STOP_ON_FAIL="$2"
      shift 2
      ;;
    --reset-before-each)
      RESET_BEFORE_EACH="$2"
      shift 2
      ;;
    --reset-mode)
      RESET_MODE="$2"
      shift 2
      ;;
    --show-progress)
      SHOW_PROGRESS="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help)
      cat <<'EOF'
Usage: run_all_windows_executions.sh [options]

Runs every execution YAML under executions/windows one by one. By default, the
script restores working VM storage from a golden storage directory before each
execution using a lightweight qcow2 overlay, then runs
platforms/windows/start_windows_vm.sh --execution <file>.

Options:
  --source-dir <path>             Golden storage directory (default: HELLOWORLD_WINDOWS_GOLDEN_STORAGE or platforms/windows/vm/storage.golden)
  --target-dir <path>             Working storage directory (default: VM_STORAGE_DIR or platforms/windows/vm/storage)
  --executions-dir <path>         Directory of Windows execution YAMLs (default: executions/windows)
  --pattern <regex>               Only run execution paths matching this regex
  --start-from <name-or-path>     Skip until this execution basename or path is reached
  --max-tasks <n>                 Stop after running n matched executions (default: 0 = no limit)
  --stop-on-fail <true|false>     Stop immediately after a failed execution (default: false)
  --reset-before-each <true|false> Restore storage before each execution (default: true)
  --reset-mode <overlay|copy>      Restore strategy when reset is enabled (default: overlay)
  --show-progress <true|false>    Show rsync progress during storage reset (default: false)
  --dry-run                       Print the planned commands without running them
  --help                          Show this help
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [ ! -d "$EXECUTIONS_DIR" ]; then
  echo "Error: executions dir does not exist: $EXECUTIONS_DIR"
  exit 1
fi

if [ "$RESET_BEFORE_EACH" = true ]; then
  case "$RESET_MODE" in
    overlay|copy) ;;
    *)
      echo "Error: --reset-mode must be 'overlay' or 'copy' (got: $RESET_MODE)"
      exit 1
      ;;
  esac
  if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: golden storage source dir does not exist: $SOURCE_DIR"
    exit 1
  fi
  if [ ! -f "$SOURCE_DIR/data.img" ]; then
    echo "Error: golden storage source dir does not look valid (missing data.img): $SOURCE_DIR"
    exit 1
  fi
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

echo "=== HelloWorld Windows Batch Runner ==="
echo "Executions dir: $EXECUTIONS_DIR"
echo "Matched:        ${#SELECTED[@]}"
echo "Reset storage:  $RESET_BEFORE_EACH"
if [ "$RESET_BEFORE_EACH" = true ]; then
  echo "Reset mode:     $RESET_MODE"
  echo "Golden source:  $SOURCE_DIR"
  echo "Working target: $TARGET_DIR"
fi
echo "Stop on fail:   $STOP_ON_FAIL"
echo "Dry run:        $DRY_RUN"
echo ""

if [ "$DRY_RUN" = true ]; then
  for execution in "${SELECTED[@]}"; do
    rel_path="${execution#$HELLOWORLD_DIR/}"
    if [ "$RESET_BEFORE_EACH" = true ]; then
      if [ "$RESET_MODE" = overlay ]; then
        echo "bash platforms/windows/scripts/create_windows_overlay_storage.sh --source-dir '$SOURCE_DIR' --target-dir '$TARGET_DIR'"
      else
        echo "bash platforms/windows/scripts/reset_windows_storage.sh --source-dir '$SOURCE_DIR' --target-dir '$TARGET_DIR' --show-progress '$SHOW_PROGRESS'"
      fi
    fi
    echo "bash platforms/windows/start_windows_vm.sh --execution '$rel_path'"
  done
  exit 0
fi

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

  if [ "$RESET_BEFORE_EACH" = true ]; then
    if [ "$RESET_MODE" = overlay ]; then
      bash "$SCRIPT_DIR/create_windows_overlay_storage.sh" \
        --source-dir "$SOURCE_DIR" \
        --target-dir "$TARGET_DIR"
    else
      bash "$SCRIPT_DIR/reset_windows_storage.sh" \
        --source-dir "$SOURCE_DIR" \
        --target-dir "$TARGET_DIR" \
        --show-progress "$SHOW_PROGRESS"
    fi
  fi

  set +e
  bash "$WINDOWS_DIR/start_windows_vm.sh" --execution "$rel_path"
  exit_code=$?
  set -e

  if [ "$exit_code" -eq 0 ]; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "[$run_number/${#SELECTED[@]}] PASS $rel_path"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED+=("$rel_path:$exit_code")
    echo "[$run_number/${#SELECTED[@]}] FAIL exit_code=$exit_code $rel_path"
    if [ "$STOP_ON_FAIL" = true ]; then
      break
    fi
  fi
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "=== Windows Batch Complete ==="
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
