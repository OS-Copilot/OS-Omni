#!/usr/bin/env python3
"""Probe one Linux task on a QEMU VM without a model.

Restores the clean snapshot, then runs any of the task's initializer, a shell
or pyautogui reference step, and its evaluator. Use it for negative checks
(initialize, then evaluate) and independent positive references (initialize,
apply a reference solution, then evaluate). Every step writes its output and a
screenshot under --output-dir.

Example:
  python scripts/linux_task_probe.py --task tasks/v1/linux/vscode_update_heading_easy.yaml \\
      --qmp-socket /path/qmp-1.sock --snapshot os_omni_v3_ready --runtime-port 15001 \\
      --output-dir /path/probe/vscode --restore --init --bash ref.sh --evaluate
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from platforms.linux.core.types import load_task_from_file  # noqa: E402
from platforms.linux.runners.episode import wait_for_runtime_ready  # noqa: E402
from platforms.linux.runners.evaluation import run_task_evaluation  # noqa: E402
from platforms.linux.runners.initialization import run_task_initialization  # noqa: E402
from platforms.linux.runtime_env.controller import LinuxRuntimeController  # noqa: E402
from scripts.run_linux_qemu_batch import restore_snapshot  # noqa: E402


def screenshot(controller: LinuxRuntimeController, output: Path, name: str) -> None:
    observation = controller.observe(include_ui_tree=False)
    (output / f"{name}.png").write_bytes(observation.screenshot_data)
    print(f"{name}: screenshot {observation.width}x{observation.height}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--qmp-socket", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, required=True)
    parser.add_argument("--runtime-token-env", default="OS_OMNI_LINUX_RUNTIME_TOKEN")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--restore", action="store_true", help="Restore the snapshot first")
    parser.add_argument("--init", action="store_true", help="Run the task initializer")
    parser.add_argument("--bash", type=Path, action="append", default=[], help="Run this guest bash script")
    parser.add_argument("--python", type=Path, action="append", default=[], help="Run this guest Python script")
    parser.add_argument("--evaluate", action="store_true", help="Run the task evaluator")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    token = os.environ[args.runtime_token_env]
    url = f"http://{args.runtime_host}:{args.runtime_port}"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    task = load_task_from_file(str(args.task))
    report: dict = {"task_id": task.id, "task": str(args.task), "snapshot": args.snapshot, "steps": []}

    if args.restore:
        restore_snapshot(args.qmp_socket, args.snapshot)
        report["steps"].append({"step": "restore"})
    wait_for_runtime_ready(url, token, timeout_seconds=90)
    controller = LinuxRuntimeController(runtime_url=url, token=token, timeout=20.0)
    screenshot(controller, output, "00_start")

    if args.init:
        run = run_task_initialization(task=task, controller=controller, model_id="probe", run_dir=output)
        summary = run.summary if run else None
        report["steps"].append({"step": "init", "result": summary})
        print("init:", json.dumps(summary, ensure_ascii=False), flush=True)
        screenshot(controller, output, "01_after_init")

    for index, script in enumerate(args.bash + args.python, start=1):
        if script in args.bash:
            result = controller.run_bash_script(script.read_text(), timeout=300)
        else:
            result = controller.run_python_script(script.read_text(), timeout=300)
        report["steps"].append({"step": "script", "path": str(script), "result": result})
        print(f"script {script.name}:", json.dumps(result, ensure_ascii=False)[:2000], flush=True)
        screenshot(controller, output, f"02_after_script_{index}")

    if args.evaluate:
        final = controller.observe(include_ui_tree=False)
        run = run_task_evaluation(task=task, controller=controller, final_observation=final,
                                  model_id="probe", run_dir=output)
        summary = run.summary if run else None
        report["steps"].append({"step": "evaluate", "result": summary})
        print("evaluate:", json.dumps(summary, ensure_ascii=False)[:4000], flush=True)

    (output / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
