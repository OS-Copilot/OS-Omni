"""OS-Omni binding for the CUA-Tasks-Review initializers.

The reviewed initializers are vendored below ``evaluators.cua_review`` like
their evaluators.  They return the release's evaluation result instead of an
:class:`core.init.InitResult`, read the iOS simulator ``udid`` from the
context, and talk to the runtime controller through the release controller
API.  :class:`ReleaseInitializerAdapter` bridges all three so the OS-Omni
runners can load them through :func:`core.init.load_initializer`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from core.init import BaseInitializer, InitResult, InitStatus

_INIT_STATUSES = {status.value for status in InitStatus}
_SCRIPT_METHODS = {"run_bash_script", "run_python_script"}


def _normalize_script_result(body: Any) -> dict[str, Any]:
    """Expose runtime output under both names the release reads.

    Mirrors ``runtime.controller._normalize_script_result`` in the release:
    OS-Omni controllers return the runtime payload as is, which carries the
    text under ``output``/``error`` while the release reads ``stdout``/``stderr``.
    """

    if not isinstance(body, Mapping):
        return {"returncode": -1, "stdout": "", "output": "",
                "stderr": f"unexpected runtime payload: {body!r}", "error": ""}
    returncode = body.get("returncode", body.get("return_code"))
    try:
        returncode = int(returncode)
    except (TypeError, ValueError):
        returncode = 0 if str(body.get("status", "")).lower() == "success" else -1
    stdout = str(body.get("output") or body.get("stdout") or "")
    stderr = str(body.get("error") or body.get("stderr") or "")
    return {**dict(body), "returncode": returncode, "stdout": stdout, "output": stdout,
            "stderr": stderr, "error": stderr}


def _observation_mapping(observation: Any) -> Any:
    if isinstance(observation, Mapping) or observation is None:
        return observation
    return dict(vars(observation))


# Mirrors runtime.adb.AdbController.foreground_package in the release.  Android
# 13 reports topResumedActivity/ResumedActivity, older releases mResumedActivity,
# so OS-Omni's get_current_activity() is not enough on its own.
_FOREGROUND_PATTERNS = (
    r"topResumedActivity=ActivityRecord\{[0-9a-f]+ u\d+ ([^\s/}]+)",
    r"ResumedActivity: ActivityRecord\{[0-9a-f]+ u\d+ ([^\s/}]+)",
    r"mCurrentFocus=Window\{[0-9a-f]+ u\d+ ([^\s/}]+)",
    r"mFocusedApp=ActivityRecord\{[0-9a-f]+ u\d+ ([^\s/}]+)",
)


def _foreground_package(controller: Any) -> str:
    for arguments in (["shell", "dumpsys", "activity", "activities"], ["shell", "dumpsys", "window"]):
        output = str(controller.execute_adb(arguments) or "")
        for pattern in _FOREGROUND_PATTERNS:
            match = re.search(pattern, output)
            if match:
                return match.group(1)
    return ""


def _start_app(controller: Any, app_package: str, activity: str = "") -> Any:
    activity = str(activity or "").strip()
    if activity and activity.lower() != "launcher":
        component = activity if "/" in activity else f"{app_package}/{activity}"
        return controller.execute_adb(["shell", "am", "start", "-n", component])
    return controller.execute_adb(
        ["shell", "monkey", "-p", app_package, "-c", "android.intent.category.LAUNCHER", "1"]
    )


def _is_alive(controller: Any) -> bool:
    try:
        health = controller.health()
    except Exception:  # noqa: BLE001 - an unreachable runtime is simply not alive
        return False
    return isinstance(health, Mapping) and str(health.get("status", "")).upper() in {"HEALTHY", "OK"}


# Release controller methods OS-Omni controllers lack, keyed by the primitive
# they are built from.  A fallback is offered only when that primitive exists,
# so ``hasattr`` probes in the release code keep their meaning.
_FALLBACKS = {
    "foreground_package": ("execute_adb", _foreground_package),
    "start_app": ("execute_adb", _start_app),
    "is_alive": ("health", _is_alive),
}


class ReleaseControllerView:
    """Present an OS-Omni controller through the release controller API."""

    def __init__(self, controller: Any) -> None:
        self._controller = controller

    def __getattr__(self, name: str) -> Any:
        controller = self.__dict__["_controller"]
        if hasattr(controller, name):
            attr = getattr(controller, name)
            if name in _SCRIPT_METHODS and callable(attr):
                return lambda *args, **kwargs: _normalize_script_result(attr(*args, **kwargs))
            if name == "observe" and callable(attr):
                return lambda *args, **kwargs: _observation_mapping(attr(*args, **kwargs))
            return attr
        fallback = _FALLBACKS.get(name)
        if fallback is not None and hasattr(controller, fallback[0]):
            return lambda *args, **kwargs: fallback[1](controller, *args, **kwargs)
        raise AttributeError(name)


class ReleaseInitializerAdapter(BaseInitializer):
    """Run a vendored release initializer under the OS-Omni contract."""

    def __init__(self, release_initializer: Any) -> None:
        self.release_initializer = release_initializer

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        release_context = dict(context)
        controller = release_context.get("controller")
        if controller is not None:
            release_context["controller"] = ReleaseControllerView(controller)
            # Reviewed iOS initializers read the run-bound simulator from the
            # context, as the iOS evaluation runner provides for evaluators.
            udid = getattr(getattr(controller, "runtime", None), "udid", None)
            if udid and not release_context.get("udid"):
                release_context["udid"] = str(udid)
        result = self.release_initializer.initialize(release_context)
        status = getattr(result, "status", None)
        status = str(getattr(status, "value", status) or "").strip().upper()
        message = getattr(result, "message", None)
        if status not in _INIT_STATUSES:
            message = f"release initializer returned {status or 'no status'}: {message}"
            status = InitStatus.ERROR.value
        metadata = getattr(result, "metadata", None)
        return InitResult(
            status=status,
            message=message,
            metadata={
                **(dict(metadata) if isinstance(metadata, Mapping) else {}),
                "release_initializer": type(self.release_initializer).__module__
                + ":" + type(self.release_initializer).__name__,
            },
        )


__all__ = ["ReleaseControllerView", "ReleaseInitializerAdapter"]
