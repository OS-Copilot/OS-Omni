#!/bin/bash
# Convenience wrapper around start_windows_vm.sh for Windows executions.
# Example:
#   bash platforms/windows/scripts/run_windows_execution.sh executions/v1/windows.yaml

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WINDOWS_DIR="$SCRIPT_DIR/.."

EXECUTION="${1:-executions/v1/windows.yaml}"

if [ "$EXECUTION" = "--help" ] || [ "$EXECUTION" = "-h" ]; then
  cat <<'EOF'
Usage: run_windows_execution.sh [execution_name]

Examples:
  run_windows_execution.sh
  run_windows_execution.sh executions/v1/windows.yaml
EOF
  exit 0
fi

bash "$WINDOWS_DIR/start_windows_vm.sh" --execution "$EXECUTION"
