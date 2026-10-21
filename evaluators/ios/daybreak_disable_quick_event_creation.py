"""Evaluator for the DayBreak quick-event setting task."""

from __future__ import annotations

import plistlib
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.ios.runtime_config import load_ios_runtime_config


class DayBreakDisableQuickEventCreationEvaluator(BaseEvaluator):
    """Validate DayBreak quick-event switch state from simulator UserDefaults."""

    DEFAULT_PREFS_KEY = "quickEventCreationEnabled"
    DEFAULT_PREFS_DIR = Path("Library") / "Preferences"
    DEFAULT_TIMEOUT_SECONDS = 60
    TERMINATE_FLUSH_DELAY_SECONDS = 1

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")

        udid = self._load_udid_from_runtime_config()
        if not udid:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Missing simulator UDID in configs/ios.yaml (source_simulator_udid).",
            )

        bundle_id = self._bundle_id_from_controller(controller)
        if not bundle_id:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Failed to get foreground bundleId from context.controller.active_app_info().",
            )

        prefs_key = self.DEFAULT_PREFS_KEY
        prefs_domain = bundle_id
        timeout_seconds = self.DEFAULT_TIMEOUT_SECONDS

        # Best-effort terminate so in-memory defaults are flushed to disk.
        terminate_result = self._run_cmd(
            ["xcrun", "simctl", "terminate", udid, bundle_id],
            timeout_seconds=timeout_seconds,
        )
        time.sleep(self.TERMINATE_FLUSH_DELAY_SECONDS)

        container_result = self._run_cmd(
            ["xcrun", "simctl", "get_app_container", udid, bundle_id, "data"],
            timeout_seconds=timeout_seconds,
        )
        if container_result.returncode != 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=(
                    "Failed to locate DayBreak app container using "
                    "configs/ios.yaml source_simulator_udid and controller foreground bundleId."
                ),
                metadata={
                    "udid": udid,
                    "bundle_id": bundle_id,
                    "prefs_key": prefs_key,
                    "terminate_returncode": terminate_result.returncode,
                    "get_container_returncode": container_result.returncode,
                    "get_container_stdout": str(container_result.stdout or "").strip(),
                    "get_container_stderr": str(container_result.stderr or "").strip(),
                },
            )

        container_path = str(container_result.stdout or "").strip()
        if not container_path:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="simctl get_app_container returned empty container path",
                metadata={
                    "udid": udid,
                    "bundle_id": bundle_id,
                    "prefs_key": prefs_key,
                    "terminate_returncode": terminate_result.returncode,
                    "get_container_returncode": container_result.returncode,
                },
            )

        from platforms.ios.runtime_env.simulator_manager import remap_simulator_container_path
        container = remap_simulator_container_path(container_path, udid)

        prefs_path = str(
            container / self.DEFAULT_PREFS_DIR / f"{prefs_domain}.plist"
        )
        prefs_data = self._load_prefs(Path(prefs_path))

        if prefs_key not in prefs_data:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"Preference key '{prefs_key}' is missing; "
                    "treating as quick event creation NOT disabled"
                ),
                metadata={
                    "udid": udid,
                    "bundle_id": bundle_id,
                    "prefs_domain": prefs_domain,
                    "prefs_path": prefs_path,
                    "prefs_key": prefs_key,
                    "terminate_returncode": terminate_result.returncode,
                    "prefs_keys": sorted(str(k) for k in prefs_data.keys()),
                },
            )

        raw_value_obj = prefs_data.get(prefs_key)
        parsed_value = self._parse_bool_like(raw_value_obj)
        raw_value = repr(raw_value_obj)

        metadata = {
            "udid": udid,
            "bundle_id": bundle_id,
            "prefs_domain": prefs_domain,
            "prefs_path": prefs_path,
            "prefs_key": prefs_key,
            "terminate_returncode": terminate_result.returncode,
            "raw_value": raw_value,
            "parsed_bool": parsed_value,
        }

        if parsed_value is False:
            return EvalResult(
                status=EvalStatus.PASS,
                message="Quick event creation is disabled in UserDefaults",
                metadata=metadata,
            )

        if parsed_value is True:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Quick event creation is still enabled in UserDefaults",
                metadata=metadata,
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message=(
                f"Preference key '{prefs_key}' has unsupported value '{raw_value}'. "
                "Expected one of: 0/false or 1/true."
            ),
            metadata=metadata,
        )

    @staticmethod
    def _load_udid_from_runtime_config() -> str:
        try:
            cfg = load_ios_runtime_config()
        except Exception:
            return ""
        return str(getattr(cfg, "source_simulator_udid", "") or "").strip()

    @staticmethod
    def _bundle_id_from_controller(controller: Any) -> str:
        if controller is None or not hasattr(controller, "active_app_info"):
            return ""

        try:
            info = controller.active_app_info()
        except Exception:
            return ""

        if not isinstance(info, Mapping):
            return ""
        return str(info.get("bundleId") or "").strip()

    @staticmethod
    def _run_cmd(cmd: list[str], *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=int(timeout_seconds),
        )

    @staticmethod
    def _load_prefs(prefs_path: Path) -> dict[str, Any]:
        if not prefs_path.exists():
            return {}
        with prefs_path.open("rb") as file_obj:
            loaded = plistlib.load(file_obj)
        if not isinstance(loaded, dict):
            return {}
        return loaded

    @staticmethod
    def _parse_bool_like(raw_value: Any) -> bool | None:
        if raw_value is False:
            return False
        if raw_value is True:
            return True
        if isinstance(raw_value, int):
            if raw_value == 0:
                return False
            if raw_value == 1:
                return True
            return None

        normalized = str(raw_value or "").strip().casefold()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
        try:
            numeric = int(normalized)
        except ValueError:
            return None
        if numeric == 0:
            return False
        if numeric == 1:
            return True
        return None
