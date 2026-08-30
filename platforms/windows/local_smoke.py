#!/usr/bin/env python3
"""Start a local Windows guest runtime and run an offline smoke execution."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXECUTION_PATH = REPO_ROOT / "executions" / "windows" / "json" / "openshop_login.yaml"
DEFAULT_TOKEN = "windowsbench-runtime-token"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_runtime(port: int, token: str, timeout_seconds: float = 20.0) -> None:
    from platforms.windows.runtime_env.controller import WindowsRuntimeController

    controller = WindowsRuntimeController(
        runtime_url=f"http://127.0.0.1:{port}",
        token=token,
        timeout=5.0,
    )
    start = time.time()
    last_error = None
    while time.time() - start < timeout_seconds:
        try:
            payload = controller.health()
            if str(payload.get("status", "")).upper() == "HEALTHY":
                return
            last_error = payload
        except Exception as exc:  # pragma: no cover - subprocess readiness timing
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"Windows runtime failed to become healthy on port {port}: {last_error}")


def _build_execution_path(execution_arg: str) -> Path:
    execution_path = Path(execution_arg)
    if not execution_path.is_absolute():
        execution_path = (REPO_ROOT / execution_path).resolve()
    return execution_path


def _run_execution(
    *,
    execution_path: Path,
    vm_ip: str,
    runtime_port: int,
    runtime_token: str,
) -> int:
    env = os.environ.copy()
    env["HELLOWORLD_MOCK_API_KEY"] = env.get("HELLOWORLD_MOCK_API_KEY", "local-smoke-token")
    env["HELLOWORLD_SCRIPTED_API_KEY"] = env.get("HELLOWORLD_SCRIPTED_API_KEY", "local-scripted-token")
    env["HELLOWORLD_WINDOWS_VM_IP"] = vm_ip
    env["HELLOWORLD_WINDOWS_RUNTIME_PORT"] = str(runtime_port)
    env["HELLOWORLD_WINDOWS_RUNTIME_TOKEN"] = runtime_token

    result = subprocess.run(
        [sys.executable, "-m", "platforms.windows.cli", "--execution", str(execution_path)],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
    )
    return int(result.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local Windows execution against a temporary guest runtime.")
    parser.add_argument(
        "--execution",
        default=str(DEFAULT_EXECUTION_PATH),
        help="Path to execution YAML file. Defaults to the minimal OS-Omni Windows smoke test.",
    )
    parser.add_argument(
        "--vm-ip",
        default=None,
        help="Existing Windows runtime host/IP. When provided, local_smoke will use that runtime instead of starting one locally.",
    )
    parser.add_argument(
        "--runtime-port",
        type=int,
        default=5000,
        help="Port for an existing Windows runtime when --vm-ip is provided.",
    )
    parser.add_argument(
        "--runtime-token",
        default=DEFAULT_TOKEN,
        help="Bearer token for the Windows runtime.",
    )
    args = parser.parse_args(argv)

    execution_path = _build_execution_path(args.execution)
    runtime_token = str(args.runtime_token or DEFAULT_TOKEN)
    remote_vm_ip: Optional[str] = str(args.vm_ip).strip() if args.vm_ip else None

    if remote_vm_ip:
        return _run_execution(
            execution_path=execution_path,
            vm_ip=remote_vm_ip,
            runtime_port=int(args.runtime_port),
            runtime_token=runtime_token,
        )

    if sys.platform != "win32":
        raise RuntimeError(
            "local_smoke can only start the guest runtime locally on Windows. "
            "On macOS/Linux, pass --vm-ip/--runtime-port to target a runtime already running inside the Windows VM."
        )

    port = _find_free_port()
    runtime_env = os.environ.copy()
    runtime_env["HELLOWORLD_WINDOWS_RUNTIME_TOKEN"] = runtime_token

    runtime_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "platforms.windows.guest.runtime_server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--token",
            runtime_token,
        ],
        cwd=str(REPO_ROOT),
        env=runtime_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_for_runtime(port, runtime_token)
        return _run_execution(
            execution_path=execution_path,
            vm_ip="127.0.0.1",
            runtime_port=port,
            runtime_token=runtime_token,
        )
    finally:
        runtime_proc.terminate()
        try:
            runtime_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - best effort cleanup
            runtime_proc.kill()
            runtime_proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
