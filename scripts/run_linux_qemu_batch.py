#!/usr/bin/env python3
"""Run Linux execution tasks against an existing QEMU VM with per-task reset.

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


def capture_end_state(controller: LinuxRuntimeController, task_dir: Path) -> dict:
    """Archive guest files changed during the task, before the next snapshot restore."""
    try:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary-file", type=Path, help="Separate summary path for a disjoint task shard")
    parser.add_argument("--qmp-socket", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, required=True)
    parser.add_argument("--runtime-token-env", default="OS_OMNI_LINUX_RUNTIME_TOKEN")
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
    token = os.environ.get(args.runtime_token_env)
    if not token:
        parser.error(f"Set {args.runtime_token_env} to the guest runtime token")
    execution = load_execution_spec(args.execution)
    tasks = [(path, load_task_spec(path)) for path in execution.task_paths]
    if any(task.platform != "linux" for _, task in tasks):
        parser.error("Every task must target Linux")
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
                sys.executable, "-m", "platforms.linux.cli", "__benchmark_task",
                "--task-file", str(path), "--execution-file", str(args.execution.resolve()),
                "--model", args.model, "--action-mode", run["action_mode"],
                "--observation-mode", run["observation_mode"], "--history-window", str(run["history_window"]),
                "--vm-ip", args.runtime_host, "--runtime-port", str(args.runtime_port), "--runtime-token", token,
            ]
            if max_steps != task.limits.max_steps:
                command += ["--max-steps", str(max_steps)]
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
    print(json.dumps(dict(Counter(row["classification"] for row in rows))), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
