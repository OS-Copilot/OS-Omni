"""Start one OpenTwitter backend on the port used by the evaluator."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.windows.electron_window import focus_electron_window, probe_electron_backend


class OpenTwitterInitializer(BaseInitializer):
    """Reject port conflicts instead of silently evaluating another instance."""

    _probe = staticmethod(probe_electron_backend)

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required")
        port = int(params.get("port", 4350))
        try:
            if not 1 <= port <= 65535:
                raise ValueError("invalid OpenTwitter evaluator port")
            # App state is reset by starting a fresh process, before any agent
            # action. Never kill an unrelated process that owns the port.
            result = controller.run_powershell_script(
                "Get-Process -Name opentwitter -ErrorAction SilentlyContinue | "
                "Stop-Process -Force -ErrorAction Stop\nWrite-Output 'STOPPED'",
                timeout=20,
            )
            if int(result.get("returncode", -1)) != 0:
                raise RuntimeError("could not stop previous OpenTwitter instances")
            previous = self._probe(controller, port, ready=False)
            if previous["listeners"]:
                raise RuntimeError(f"evaluator port {port} is occupied; refusing fallback-port launch")
            controller.launch_app(str(params.get("app_name") or "OpenTwitter"))
            deadline = time.monotonic() + float(params.get("launch_timeout_seconds", 30))
            last_error = "backend did not become ready"
            while time.monotonic() < deadline:
                try:
                    state = self._probe(controller, port, ready=True)
                    owners = state["listeners"]
                    if not owners or any(x["name"].lower() != "opentwitter.exe" for x in owners):
                        raise RuntimeError("evaluator port is not owned by OpenTwitter")
                    if state.get("session", {}).get("loggedIn") or state.get("event_count"):
                        raise RuntimeError("OpenTwitter did not start with a clean signed-out session")
                    focus_electron_window(controller, "opentwitter.exe", "OpenTwitter")
                    return InitResult(
                        status=InitStatus.PASS,
                        message=f"Started a fresh OpenTwitter instance on evaluator port {port}",
                        metadata={"port": port, **state},
                    )
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(0.5)
            raise RuntimeError(last_error)
        except Exception as exc:
            return InitResult(status=InitStatus.ERROR, message=str(exc), metadata={"port": port})
