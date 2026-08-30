"""Tart VM manager for headless macOS benchmark execution."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class TartManager:
    """Manage Tart VMs for clone -> headless run -> stop -> delete benchmark flows."""

    provider_name = "tart"
    DEFAULT_TART_HOME = Path.home() / ".tart"

    def __init__(self, tart_home: Optional[str | Path] = None):
        self.tart_home = Path(tart_home).expanduser() if tart_home else self.DEFAULT_TART_HOME
        self._run_processes: Dict[str, subprocess.Popen[str]] = {}

    def _env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["TART_HOME"] = str(self.tart_home)
        return env

    def _run_tart(self, *args: str, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        cmd = ["tart", *args]
        return subprocess.run(
            cmd,
            env=self._env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=check,
        )

    def _tart_vm_dir(self, vm_name: str) -> Path:
        return self.tart_home / "vms" / vm_name

    def vm_exists(self, vm_name: str) -> bool:
        vm_dir = self._tart_vm_dir(vm_name)
        return (vm_dir / "config.json").exists() and (vm_dir / "disk.img").exists() and (vm_dir / "nvram.bin").exists()

    def _vm_state(self, vm_name: str) -> str:
        try:
            result = self._run_tart("list", check=True, timeout=15)
        except Exception as exc:
            logger.warning("Failed to query Tart VM state for '%s': %s", vm_name, exc)
            return "unknown"

        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and parts[1] == vm_name:
                return parts[-1].strip().lower()
        return "missing"

    def stop_vm(self, vm_name: str, timeout: int = 60) -> bool:
        state = self._vm_state(vm_name)
        if state in {"stopped", "missing"}:
            return True

        logger.info("Stopping Tart VM '%s'...", vm_name)
        try:
            self._run_tart("stop", vm_name, check=True, timeout=timeout)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            logger.error("Failed to stop Tart VM '%s': %s", vm_name, stderr)
            return False
        except Exception as exc:
            logger.error("Failed to stop Tart VM '%s': %s", vm_name, exc)
            return False

        process = self._run_processes.pop(vm_name, None)
        if process is not None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        return self._vm_state(vm_name) == "stopped"

    def ensure_vm_stopped(self, vm_name: str, timeout: int = 60) -> bool:
        if self._vm_state(vm_name) == "running":
            return self.stop_vm(vm_name, timeout=timeout)
        return True

    def clone_vm(self, source_name: str, clone_name: str) -> bool:
        logger.info("Cloning Tart VM '%s' -> '%s'...", source_name, clone_name)
        try:
            self._run_tart("clone", source_name, clone_name, check=True, timeout=120)
            return True
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            logger.error("Failed to clone Tart VM '%s' -> '%s': %s", source_name, clone_name, stderr)
            return False
        except Exception as exc:
            logger.error("Failed to clone Tart VM '%s' -> '%s': %s", source_name, clone_name, exc)
            return False

    def boot_vm(self, vm_name: str, timeout: int = 120) -> bool:
        if self._vm_state(vm_name) == "running":
            logger.info("Tart VM '%s' already running.", vm_name)
            return True

        logger.info("Booting Tart VM '%s' headlessly...", vm_name)
        process = subprocess.Popen(
            ["tart", "run", "--no-graphics", vm_name],
            env=self._env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._run_processes[vm_name] = process

        deadline = time.time() + timeout
        while time.time() < deadline:
            if process.poll() is not None:
                logger.error("Tart VM '%s' exited before becoming ready (code=%s)", vm_name, process.returncode)
                self._run_processes.pop(vm_name, None)
                return False
            if self._vm_state(vm_name) == "running":
                try:
                    _ = self.resolve_runtime_host(vm_name)
                except RuntimeError:
                    time.sleep(1)
                    continue
                return True
            time.sleep(1)

        logger.error("Timed out waiting for Tart VM '%s' to boot.", vm_name)
        return False

    def delete_clone(self, clone_name: str) -> bool:
        logger.info("Deleting Tart VM '%s'...", clone_name)
        try:
            self._run_tart("delete", clone_name, check=True, timeout=60)
            return True
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            logger.error("Failed to delete Tart VM '%s': %s", clone_name, stderr)
            return False
        except Exception as exc:
            logger.error("Failed to delete Tart VM '%s': %s", clone_name, exc)
            return False

    def resolve_runtime_host(self, vm_name: str, fallback_host: str | None = None) -> str:
        try:
            result = self._run_tart("ip", vm_name, check=True, timeout=30)
            host = (result.stdout or "").strip()
            if host:
                return host
        except subprocess.CalledProcessError:
            pass
        except Exception as exc:
            logger.warning("Failed to resolve Tart IP for '%s': %s", vm_name, exc)
        if fallback_host:
            return str(fallback_host).strip()
        raise RuntimeError(f"Unable to resolve runtime host for Tart VM '{vm_name}'")

    def prepare_benchmark_environment(self, base_vm_name: str, clone_name: str | None = None) -> str | None:
        if not self.ensure_vm_stopped(base_vm_name, timeout=60):
            logger.error("Base Tart VM '%s' must be stopped before clone.", base_vm_name)
            return None

        resolved_clone_name = (clone_name or "").strip() or f"{base_vm_name}_{int(time.time() * 1000)}"
        if not self.clone_vm(base_vm_name, resolved_clone_name):
            return None
        if not self.boot_vm(resolved_clone_name, timeout=180):
            self.cleanup_benchmark_environment(resolved_clone_name)
            return None
        return resolved_clone_name

    def cleanup_benchmark_environment(self, clone_name: str) -> bool:
        if self._vm_state(clone_name) == "running":
            if not self.stop_vm(clone_name, timeout=60):
                return False
        return self.delete_clone(clone_name)
