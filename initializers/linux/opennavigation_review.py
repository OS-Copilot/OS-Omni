"""Initializer for the OpenNavigation route-review tasks (web build).

Runs the task's desktop setup steps, then installs the passive navigation
recorder (see evaluators.cua_review.platforms.linux.opennavigation_events) in
the open OpenNavigation page, clears any earlier log, and keeps it installed
across page reloads.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from evaluators.cua_review.platforms.linux.opennavigation_events import (
    DEFAULT_DEVTOOLS_PORT,
    install_recorder,
    start_recorder_keeper,
)
from initializers.linux.setup import DesktopSetupInitializer


class OpenNavigationReviewInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        setup = DesktopSetupInitializer().initialize(context)
        if setup.status != InitStatus.PASS:
            return setup
        params = dict(context.get("params") or {})
        port = int(params.get("devtools_port", DEFAULT_DEVTOOLS_PORT) or DEFAULT_DEVTOOLS_PORT)
        deadline = time.monotonic() + float(params.get("recorder_wait_seconds", 60) or 60)
        reply: dict[str, Any] = {}
        while True:
            reply = install_recorder(context.get("controller"), port=port, clear=True)
            values = [((result.get("result") or {}).get("value")) for page in reply.get("pages") or []
                      for result in page.get("results") or []]
            if "installed" in values:
                keeper = start_recorder_keeper(context.get("controller"), port=port)
                if "keeper-started" not in str(keeper.get("output") or ""):
                    return InitResult(InitStatus.ERROR, "OpenNavigation recorder keeper did not start", {"keeper": keeper})
                metadata = dict(setup.metadata or {})
                metadata["navigation_recorder"] = {"pages": [page.get("url") for page in reply.get("pages") or []],
                                                   "keeper": True}
                return InitResult(InitStatus.PASS, (setup.message or "") + "; navigation recorder installed", metadata)
            if time.monotonic() > deadline:
                return InitResult(InitStatus.ERROR, "OpenNavigation navigation recorder could not be installed",
                                  {"reply": reply})
            time.sleep(2)
