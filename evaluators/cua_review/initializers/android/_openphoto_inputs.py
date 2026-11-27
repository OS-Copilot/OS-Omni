"""Shared preparation for the v1 Android OpenPhoto calibrated-export tasks.

The four ``android.openphoto.*_dual_calibrated_export_*`` briefs ask the agent
to import photos that carry a three-colour calibration area, and their
evaluators measure that area in the exports.  The emulator snapshot holds no
such photos, so before the application is brought to the foreground these
initializers install them: see
:mod:`evaluators.cua_review.platforms.android.openphoto_calibration`.
"""

from __future__ import annotations

from typing import Any, Mapping

from evaluators.cua_review.core.evaluation import EvalResult, EvalStatus
from evaluators.cua_review.initializers.android._base import BaseAndroidInitializer
from evaluators.cua_review.platforms.android.openphoto_calibration import (
    DEFAULT_EXPORT_DIR,
    install_task_fixtures,
)


class OpenPhotoCalibratedInputsInitializer(BaseAndroidInitializer):
    """Install the task's calibrated input photos, then launch OpenPhotoEdit."""

    #: Key into ``openphoto_calibration.TASK_FIXTURES``.
    FIXTURE_KEY = ""

    APP_PACKAGE = "com.killt.openphotoedit"

    SETTLE_MS = 2500

    def initialize(self, context: Mapping[str, Any]) -> EvalResult:
        params = {**dict(self.TASK_PARAMS), **dict(context.get("params") or {})}
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "execute_adb"):
            return super().initialize(context)
        try:
            self._validate_binding(controller)
            inputs = install_task_fixtures(
                controller,
                self.FIXTURE_KEY,
                run_dir=context.get("run_dir"),
                export_dir=str(params.get("export_dir") or DEFAULT_EXPORT_DIR),
            )
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            return self._result(
                EvalStatus.ERROR,
                f"the calibrated input photos could not be installed: {exc}",
                {"read_only": False, "fixture_key": self.FIXTURE_KEY},
            )
        launched = super().initialize(context)
        summary = {
            "fixtures": inputs["fixtures"],
            "pre_existing_exports": inputs["paths"],
            "baseline_file": inputs.get("baseline_file"),
        }
        return EvalResult(
            status=launched.status,
            message=(f"installed {len(inputs['fixtures'])} calibrated input photos; {launched.message}"
                     if launched.status == EvalStatus.PASS else launched.message),
            metadata={**dict(launched.metadata), "read_only": False, "calibrated_inputs": summary},
        )


__all__ = ["OpenPhotoCalibratedInputsInitializer"]
