"""Create a clean signed-out OpenDriver task state on the bound simulator."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from evaluators.cua_review.core.evaluation import EvalResult, EvalStatus
from evaluators.cua_review.core.initialization import (
    BaseInitializer,
    SimulatorError,
    app_data_container,
    simulator_is_booted,
    wait_until_running,
)
from platforms.ios.runtime_env.simulator_manager import launch_app, terminate_app


class OpenDriverCleanIOSInitializer(BaseInitializer):
    """Reset task data, remove cached authentication, and verify login UI."""

    INITIALIZER_ID = "initializers.ios.opendriver_clean:OpenDriverCleanIOSInitializer"
    BUNDLE_ID = "com.killt.opendriver"
    SETTLE_MS = 1800

    def initialize(self, context: Mapping[str, Any]) -> EvalResult:
        params = {**dict(self.TASK_PARAMS), **dict(context.get("params") or {})}
        udid = str(params.get("udid") or context.get("udid") or "").strip()
        bundle_id = str(params.get("bundle_id") or self.BUNDLE_ID).strip()
        if not udid or not simulator_is_booted(udid):
            return self._result(
                EvalStatus.ERROR,
                "the bound iOS simulator is unavailable",
                {"stages": {}, "udid": udid or None},
            )
        if bundle_id != self.BUNDLE_ID:
            return self._result(
                EvalStatus.ERROR,
                f"unexpected OpenDriver bundle identifier: {bundle_id}",
                {"stages": {}, "udid": udid},
            )

        stages: dict[str, Any] = {}
        try:
            if params.get("reset_backend") is True:
                stages["backend_seed_reset"] = self._reset_backend(
                    str(params.get("backend_url") or "http://127.0.0.1:4320")
                )

            container = app_data_container(udid, bundle_id)
            if container is None or not container.is_dir():
                raise SimulatorError("OpenDriver app data container was not found")

            terminate_app(udid, bundle_id)
            token_paths = (
                container / "Library" / "Application Support" / "opendriver" / "auth_token.txt",
                container / ".opendriver" / "auth_token.txt",
                container / "tmp" / "opendriver" / "auth_token.txt",
            )
            cleared = []
            for token_path in token_paths:
                if token_path.is_file():
                    token_path.unlink()
                    cleared.append(str(token_path.relative_to(container)))
            stages["local_auth_cleared"] = self._stage(
                "local_auth_cleared",
                "terminated app and removed cached authentication token"
                if cleared
                else "terminated app; no cached authentication token was present",
            )

            launch_app(udid, bundle_id)
            wait_until_running(udid, bundle_id)
            time.sleep(max(0, int(params.get("wait_ms") or self.SETTLE_MS)) / 1000.0)

            controller = context.get("controller")
            if controller is not None:
                controller.activate_app(bundle_id)
                page_source = str(controller.driver.page_source or "").lower()
                required = ("email", "password", "login", "driver")
                if not all(term in page_source for term in required) or "driver workspace" in page_source:
                    raise SimulatorError(
                        "OpenDriver did not reach the signed-out login surface after clearing auth"
                    )
                stages["login_surface"] = self._stage(
                    "login_surface", "signed-out role selection and login fields are visible"
                )
            return self._result(
                EvalStatus.PASS,
                "OpenDriver is at its signed-out login surface on the bound simulator",
                {
                    "read_only": False,
                    "stages": stages,
                    "udid": udid,
                    "bundle_id": bundle_id,
                    "data_container_path": str(container),
                    "cleared_auth_paths": cleared,
                    "backend_reset": params.get("reset_backend") is True,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self._result(
                EvalStatus.ERROR,
                f"OpenDriver clean initialization failed: {type(exc).__name__}: {exc}",
                {"read_only": False, "stages": stages, "udid": udid, "bundle_id": bundle_id},
            )

    @staticmethod
    def _reset_backend(backend_url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            backend_url.rstrip("/") + "/dev/reset",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or data.get("reset") is not True:
            raise SimulatorError("OpenDriver backend did not confirm its seed reset")
        schema_version = (data.get("meta") or {}).get("schemaVersion")
        if schema_version != 16:
            raise SimulatorError(f"OpenDriver backend schema must be 16, got {schema_version!r}")
        return OpenDriverCleanIOSInitializer._stage(
            "backend_seed_reset", f"seed data reset and schema v{schema_version} verified"
        )

    @staticmethod
    def _stage(name: str, detail: str) -> dict[str, Any]:
        return {"name": name, "status": "PASS", "detail": detail, "ended_at": time.time()}


__all__ = ["OpenDriverCleanIOSInitializer"]
