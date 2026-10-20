#!/usr/bin/env python3
"""Run Linux (or, with --platform windows, Windows) execution tasks against an existing QEMU VM with per-task reset.

The VM must already expose its guest runtime and a QMP Unix socket, and have
a clean snapshot containing the required applications and running runtime.
Model configuration is read from configs/models.yaml as in the standard CLI.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.specs.loader import load_execution_spec, load_task_spec  # noqa: E402
from platforms.linux.runners.episode import wait_for_runtime_ready  # noqa: E402
from platforms.linux.runtime_env.controller import LinuxRuntimeController  # noqa: E402
from platforms.windows.runners.episode import wait_for_runtime_ready as wait_for_windows_runtime_ready  # noqa: E402
from platforms.windows.runtime_env.controller import WindowsRuntimeController  # noqa: E402

START_MARKER = "/tmp/.os_omni_task_start"
# The guest uses a pc105 keymap where "less" is the extra ISO key, so pyautogui types "<" as
# Shift+that key and gets ">". Clearing the key lets "<" resolve to Shift+comma. The keypad
# paren keys (187/188) are cleared too: pyautogui types "(" and ")" through them, which a
# mirrored phone drops; without them it uses Shift+9 and Shift+0.
ISO_LESS_KEY_FIX = "xmodmap -e 'keycode 94 = NoSymbol' -e 'keycode 187 = NoSymbol' -e 'keycode 188 = NoSymbol'"
# Most ~/Desktop/webpage entries are symlinks to HTML redirect pages that open the app in
# Chrome. OpenBlender, OpenCode, OpenFinance and OpenWireshark are extension-less .desktop
# files instead, which Nautilus 42 opens in a text editor. Give them the same kind of
# redirect page (target taken from the launcher's --app URL) and keep the launcher aside.
WEBPAGE_LAUNCHER_FIX = r"""
set -e
dir="$HOME/Desktop/webpage"; pages="$HOME/Applications/webpage_shortcuts"; mkdir -p "$pages/legacy-webpage-items"
n=0
for f in "$dir"/*; do
  [ -f "$f" ] && [ ! -L "$f" ] && grep -q '^\[Desktop Entry\]' "$f" || continue
  name=$(basename "$f"); url=$(sed -n 's/^Exec=.*--app=\([^ ]*\).*/\1/p' "$f")
  [ -n "$url" ] || continue
  if [ ! -f "$pages/$name.html" ]; then
    cat > "$pages/$name.html" <<HTML
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0; url=$url">
    <title>$name</title>
    <script>window.location.replace('$url');</script>
  </head>
  <body>
    <a href="$url">$name</a>
  </body>
</html>
HTML
  fi
  mv "$f" "$pages/legacy-webpage-items/$name.desktop"; ln -s "$pages/$name.html" "$dir/$name"; n=$((n+1))
done
echo "$n"
"""
END_STATE_ARCHIVE = "/tmp/os_omni_end_state.tar.gz"
# Files under these guest roots that changed after the task started are archived.
END_STATE_SCRIPT = f"""set -u
cd /
find home/user tmp -xdev -type f -newer {START_MARKER} -size -50M \\
  -not -path '*/.cache/*' -not -path '*/Cache/*' -not -path '*/cache2/*' \\
  -not -path 'tmp/os_omni_live_runtime/*' -not -path '{END_STATE_ARCHIVE[1:]}' 2>/dev/null | sort > /tmp/os_omni_end_state.list
tar -czf {END_STATE_ARCHIVE} --ignore-failed-read -T /tmp/os_omni_end_state.list 2>/dev/null
wc -l < /tmp/os_omni_end_state.list
"""


WINDOWS_TEMP = r"C:\Users\User\AppData\Local\Temp"
WINDOWS_START_MARKER = WINDOWS_TEMP + r"\os_omni_task_start.txt"
WINDOWS_END_STATE_ARCHIVE = WINDOWS_TEMP + r"\os_omni_end_state.zip"
WINDOWS_END_STATE_LIST = WINDOWS_TEMP + r"\os_omni_end_state.txt"
WINDOWS_END_STATE_STAGE = WINDOWS_TEMP + r"\os_omni_end_state"
# Files under the user profile that changed after the task started are archived.
WINDOWS_END_STATE_SCRIPT = f"""$start = [datetime]::Parse((Get-Content -Raw '{WINDOWS_START_MARKER}').Trim())
$files = Get-ChildItem -LiteralPath $env:USERPROFILE -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object {{ $_.LastWriteTime -gt $start -and $_.Length -lt 50MB -and $_.FullName -notmatch '\\\\AppData\\\\' }}
$files.FullName | Set-Content -Encoding UTF8 '{WINDOWS_END_STATE_LIST}'
Remove-Item -LiteralPath '{WINDOWS_END_STATE_ARCHIVE}' -ErrorAction SilentlyContinue
# Copied with read/write sharing first: Compress-Archive skips files an application keeps open.
$stage = '{WINDOWS_END_STATE_STAGE}'
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
foreach ($file in @($files)) {{
  $target = Join-Path $stage $file.FullName.Substring($env:USERPROFILE.Length).TrimStart('\')
  New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
  try {{
    $in = [IO.File]::Open($file.FullName, 'Open', 'Read', 'ReadWrite')
    try {{ $out = [IO.File]::Create($target); try {{ $in.CopyTo($out) }} finally {{ $out.Dispose() }} }} finally {{ $in.Dispose() }}
  }} catch {{ }}
}}
if ($files) {{
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [IO.Compression.ZipFile]::CreateFromDirectory($stage, '{WINDOWS_END_STATE_ARCHIVE}')
}}
@($files).Count
"""
# Windows initializers run with a 180 s timeout by default; companion-phone setup can take longer.
WINDOWS_INITIALIZER_TIMEOUT_SECONDS = "600"


def qmp_command(socket_path: Path, command: str, arguments: dict | None = None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(180)
        connection.connect(str(socket_path))
        stream = connection.makefile("rwb")
        greeting = json.loads(stream.readline())
        if "QMP" not in greeting:
            raise RuntimeError("Invalid QMP greeting")
        for request_id, payload in enumerate((
            {"execute": "qmp_capabilities"},
            {"execute": command, "arguments": arguments or {}},
        ), start=1):
            stream.write(json.dumps(dict(payload, id=request_id)).encode() + b"\n")
            stream.flush()
            while True:
                line = stream.readline()
                if not line:
                    raise RuntimeError("QMP connection closed without a response")
                response = json.loads(line)
                if response.get("id") != request_id:
                    continue
                if "error" in response:
                    raise RuntimeError(f"QMP command failed: {response['error']}")
                break
        return response.get("return")


def restore_snapshot(socket_path: Path, snapshot: str) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", snapshot):
        raise ValueError("Snapshot names must contain only letters, digits, _, ., or -")
    reply = qmp_command(socket_path, "human-monitor-command", {"command-line": f"loadvm {snapshot}"})
    if reply and str(reply).strip():
        raise RuntimeError(f"Snapshot restore failed: {reply}")
    qmp_command(socket_path, "cont")


def classify_result(result: dict) -> str:
    initializer = result.get("initializer") or {}
    evaluator = result.get("evaluation") or {}
    if initializer and initializer.get("status") != "PASS":
        return "INITIALIZATION_ERROR"
    if evaluator.get("status") in {"ERROR", "SKIP"}:
        return "EVALUATION_ERROR"
    if evaluator.get("status") == "FAIL" and (evaluator.get("metadata") or {}).get("returncode") in {126, 127}:
        return "EVALUATION_ERROR"
    if result.get("status") == "PASS":
        return "PASS"
    if result.get("status") == "FAIL":
        return "FAIL"
    return "EXECUTION_ERROR"


def capture_end_state(controller, task_dir: Path) -> dict:
    """Archive guest files changed during the task, before the next snapshot restore."""
    try:
        if isinstance(controller, WindowsRuntimeController):
            result = controller.run_powershell_script(WINDOWS_END_STATE_SCRIPT, timeout=180)
            count = int((result.get("output") or "0").strip() or 0)
            if count:
                (task_dir / "end_state.zip").write_bytes(controller.get_file(WINDOWS_END_STATE_ARCHIVE))
            (task_dir / "end_state_files.txt").write_bytes(controller.get_file(WINDOWS_END_STATE_LIST))
            return {"status": "captured", "files": count}
        result = controller.run_bash_script(END_STATE_SCRIPT, timeout=180)
        (task_dir / "end_state.tar.gz").write_bytes(controller.get_file(END_STATE_ARCHIVE))
        (task_dir / "end_state_files.txt").write_bytes(controller.get_file("/tmp/os_omni_end_state.list"))
        return {"status": "captured", "files": int((result.get("output") or "0").strip() or 0)}
    except Exception as error:
        return {"status": "error", "error": f"{type(error).__name__}: {error}"}


def write_summary(path: Path, run: dict, rows: list[dict]) -> None:
    counts = Counter(row["classification"] for row in rows)
    payload = dict(run, completed=len(rows), counts=dict(counts), tasks=rows)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def append_run_log(path: Path, run: dict, rows: list[dict], output: Path, summary_path: Path) -> None:
    passed = sum(row.get("status") == "PASS" for row in rows)
    record = dict(run, platform=run.get("platform", "linux"), finished_at=datetime.now(timezone.utc).isoformat(),
                  output_dir=str(output), summary=str(summary_path), completed=len(rows), passed=passed,
                  score=f"{passed}/{len(rows)}", counts=dict(Counter(row["classification"] for row in rows)),
                  task_ids=[row["task_id"] for row in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--platform", choices=("linux", "windows"), default="linux", help="Guest OS of the VM and tasks")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary-file", type=Path, help="Separate summary path for a disjoint task shard")
    parser.add_argument("--run-log", type=Path, default=REPO_ROOT / "logs" / "runs.jsonl",
                        help="Append one record per finished run here (default: logs/runs.jsonl, git-ignored)")
    parser.add_argument("--no-run-log", action="store_true", help="Do not append to --run-log")
    parser.add_argument("--qmp-socket", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, required=True)
    parser.add_argument("--runtime-token-env", help="Default: OS_OMNI_LINUX_RUNTIME_TOKEN or OS_OMNI_WINDOWS_RUNTIME_TOKEN")
    parser.add_argument("--task-id", action="append", help="Run only these task IDs, in execution order")
    parser.add_argument("--resume", action="store_true", help="Reuse completed results with matching task/model/run settings")
    parser.add_argument("--max-steps-cap", type=int, help="Lower step limits above this value; smaller TaskSpec limits are kept")
    parser.add_argument("--llm-exchange-log", action="store_true",
                        help="Save each model request and response to llm_exchange.jsonl, with inline images replaced by digests")
    parser.add_argument("--fix-webpage-launchers", action="store_true",
                        help="Replace extension-less .desktop entries in ~/Desktop/webpage with HTML redirect pages")
    parser.add_argument("--capture-end-state", action="store_true",
                        help="Archive guest files changed during each task to end_state.tar.gz")
    parser.add_argument("--deepseek-request-audit", action="store_true",
                        help="Verify every request is deepseek-flash Responses with reasoning.effort=none")
    args = parser.parse_args()
    windows = args.platform == "windows"
    if windows and args.fix_webpage_launchers:
        parser.error("--fix-webpage-launchers applies to Linux guests only")
    args.runtime_token_env = args.runtime_token_env or f"OS_OMNI_{args.platform.upper()}_RUNTIME_TOKEN"
    token = os.environ.get(args.runtime_token_env)
    if not token:
        parser.error(f"Set {args.runtime_token_env} to the guest runtime token")
    execution = load_execution_spec(args.execution)
    tasks = [(path, load_task_spec(path)) for path in execution.task_paths]
    if any(task.platform != args.platform for _, task in tasks):
        parser.error(f"Every task must target {args.platform}")
    if args.task_id:
        selected = set(args.task_id)
        unknown = selected - {task.task_id for _, task in tasks}
        if unknown:
            parser.error(f"Unknown task IDs: {sorted(unknown)}")
        tasks = [(path, task) for path, task in tasks if task.task_id in selected]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary_path = args.summary_file.resolve() if args.summary_file else output / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    run = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "execution": str(args.execution.resolve()), "model": args.model,
        "snapshot": args.snapshot, "task_count": len(tasks),
        "observation_mode": execution.observation_mode or "screenshot_only",
        "action_mode": execution.action_mode or "code_adapter",
        "history_window": execution.history_window or 3,
        "max_steps_cap": args.max_steps_cap,
    }
    if windows:
        run["platform"] = "windows"
    rows = []
    for index, (path, task) in enumerate(tasks, start=1):
        task_dir = output / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        fingerprint = {
            "task_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "models_sha256": hashlib.sha256((REPO_ROOT / "configs/models.yaml").read_bytes()).hexdigest(),
            **{key: run[key] for key in ("model", "snapshot", "observation_mode", "action_mode", "history_window")},
        }
        max_steps = task.limits.max_steps
        if args.max_steps_cap and max_steps > args.max_steps_cap:
            max_steps = args.max_steps_cap
            fingerprint["max_steps"] = max_steps
        marker = task_dir / "batch_run.json"
        result_path = task_dir / "result.json"
        if args.resume and result_path.is_file() and marker.is_file():
            previous = json.loads(marker.read_text())
            if previous.get("fingerprint") != fingerprint:
                raise RuntimeError(f"Run settings changed for {task.task_id}; choose a new output directory")
            rows.append(previous["summary"])
            write_summary(summary_path, run, rows)
            print(f"[{index}/{len(tasks)}] reused {task.task_id}", flush=True)
            continue
        if any(task_dir.iterdir()):
            raise RuntimeError(f"Task output already exists: {task_dir}; use --resume or a new directory")
        print(f"[{index}/{len(tasks)}] {task.task_id}: restoring {args.snapshot}", flush=True)
        started = time.monotonic()
        row = {"task_id": task.task_id, "task_path": str(path), "output_dir": str(task_dir),
               "task_sha256": fingerprint["task_sha256"], "max_steps": max_steps}
        try:
            restore_snapshot(args.qmp_socket, args.snapshot)
            runtime_url = f"http://{args.runtime_host}:{args.runtime_port}"
            if windows:
                wait_for_windows_runtime_ready(runtime_url, token, timeout_seconds=90)
                controller = WindowsRuntimeController(runtime_url=runtime_url, token=token, timeout=60.0)
                if args.capture_end_state:
                    controller.run_powershell_script(
                        f"(Get-Date).ToString('o') | Set-Content -Encoding ASCII '{WINDOWS_START_MARKER}'", timeout=30)
            else:
                wait_for_runtime_ready(runtime_url, token, timeout_seconds=90)
                controller = LinuxRuntimeController(runtime_url=runtime_url, token=token, timeout=60.0)
                keymap = controller.run_bash_script(ISO_LESS_KEY_FIX, timeout=30)
                row["iso_less_key_fix"] = keymap.get("returncode")
                if args.fix_webpage_launchers:
                    launchers = controller.run_bash_script(WEBPAGE_LAUNCHER_FIX, timeout=30)
                    row["webpage_launcher_fix"] = (launchers.get("output") or "").strip() or launchers.get("returncode")
                if args.capture_end_state:
                    controller.run_bash_script(f"touch {START_MARKER}", timeout=30)
            command = [
                sys.executable, "-m", f"platforms.{args.platform}.cli", "__benchmark_task",
                "--task-file", str(path), "--execution-file", str(args.execution.resolve()),
                "--model", args.model, "--action-mode", run["action_mode"],
                "--observation-mode", run["observation_mode"], "--history-window", str(run["history_window"]),
                "--vm-ip", args.runtime_host, "--runtime-port", str(args.runtime_port), "--runtime-token", token,
            ]
            if max_steps != task.limits.max_steps:
                command += ["--max-steps", str(max_steps)]
            if windows:
                # No VM provider: this script owns the VM and its snapshot resets.
                env = dict(os.environ, WINDOWS_OUTPUT_DIR=str(task_dir), HELLOWORLD_WINDOWS_VM_PROVIDER="")
                env.setdefault("HELLOWORLD_WINDOWS_INITIALIZER_TIMEOUT_SECONDS", WINDOWS_INITIALIZER_TIMEOUT_SECONDS)
            else:
                env = dict(os.environ, LINUX_OUTPUT_DIR=str(task_dir))
            if args.llm_exchange_log:
                env["OS_OMNI_LLM_EXCHANGE_LOG"] = str(task_dir / "llm_exchange.jsonl")
            if args.deepseek_request_audit:
                env["OS_OMNI_DEEPSEEK_REQUEST_AUDIT"] = str(task_dir / "deepseek_request_audit.jsonl")
            # The full per-task step limit and step timeout are taken from its TaskSpec.
            with (task_dir / "runner.log").open("w") as log:
                process = subprocess.run(command, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            row["return_code"] = process.returncode
            if args.capture_end_state:
                row["end_state"] = capture_end_state(controller, task_dir)
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                row.update(classification=classify_result(result), status=result.get("status"),
                           steps=result.get("steps_taken"), initializer=result.get("initializer"),
                           evaluation=result.get("evaluation"), episode_result=result.get("episode_result"))
            else:
                row.update(classification="EXECUTION_ERROR", error="Worker did not produce result.json; inspect runner.log")
        except Exception as error:
            row.update(classification="INFRASTRUCTURE_ERROR", error=f"{type(error).__name__}: {error}")
        row["duration_seconds"] = round(time.monotonic() - started, 2)
        rows.append(row)
        marker.write_text(json.dumps({"fingerprint": fingerprint, "summary": row}, ensure_ascii=False, indent=2) + "\n")
        write_summary(summary_path, run, rows)
        print(f"[{index}/{len(tasks)}] {row['classification']}: {row.get('steps', 0)} steps, {row['duration_seconds']}s", flush=True)
    counts = dict(Counter(row["classification"] for row in rows))
    print(json.dumps(counts), flush=True)
    if not args.no_run_log:
        append_run_log(args.run_log, run, rows, output, summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
