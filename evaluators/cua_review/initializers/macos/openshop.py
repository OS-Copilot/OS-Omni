# Author-maintained single-VM repair based on the vendored CUA initializer.
"""Prepare OpenShop for an episode.

OpenShop's episodes start on its account chooser: a signed-out session with the
episode's preset account already selected and its password field showing.  The
loopback session endpoint reports the signed-out state; the selected account and
the password field are part of the page itself, so preparation confirms them
from the guest's own window tree.  It signs nothing in, adds nothing to the cart
and places no order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from evaluators.cua_review.core.initialization import InitializationError, MacAppInitializer

#: Port OpenShop serves on inside the guest.
DEFAULT_PORT = 4310

#: How long the account chooser is given to render.
DEFAULT_VISIBLE_TIMEOUT_SECONDS = 45.0


class OpenShopSnapshotInitializer(MacAppInitializer):
    """Restore and verify the signed-out OpenShop starting point.

    The original initializer only checked a per-task snapshot. That worked
    with a fresh VM clone but left account, cart, orders and benchmark events
    behind when tasks share one VM. Restore the app's seed before checking the
    same task preconditions. If a different account is signed in, refuse to
    reset it rather than silently modifying unrelated user state.
    """

    INITIALIZER_ID = "initializers.macos.openshop:OpenShopSnapshotInitializer"
    APP_NAME = "OpenShop"
    BUNDLE_ID = "local.osomni.openshop"
    SETTLE_MS = 2500

    def __init__(self) -> None:
        self._did_boundary_reset = False

    def _result(self, status, message, metadata):
        result = super()._result(status, message, metadata)
        if self._did_boundary_reset:
            result.metadata["read_only"] = False
            result.metadata["inter_task_snapshot_reset"] = True
        return result

    def initialize(self, context: Mapping[str, Any]):
        params = dict(context.get("params") or {})
        task = context.get("task")
        task_id = str(getattr(task, "task_id", "") or getattr(task, "id", ""))
        params.setdefault("benchmark_mode", task_id)
        evaluation = getattr(task, "evaluation", None)
        evaluation_params = dict(getattr(evaluation, "params", {}) or {})
        session = dict(evaluation_params.get("session") or {})
        params.setdefault("expected_phone", session.get("phone", "13800138000"))
        orders = dict(evaluation_params.get("orders") or {})
        params.setdefault(
            "expected_historical_order_ids",
            [str(item.get("order_id")) for item in orders.get("by_id", []) if item.get("order_id")],
        )
        return super().initialize({**context, "params": params})

    def verify_preconditions(self, controller: Any, params: Mapping[str, Any]) -> str:
        port, state, notes = self._read_loopback(
            controller,
            [params.get("port") or DEFAULT_PORT],
            ["/api/session"],
            what="OpenShop state",
        )
        if port is None:
            raise InitializationError(
                "OpenShop did not answer GET /api/session"
                + (f" ({'; '.join(notes)})" if notes else "")
            )
        session = dict(self._endpoint_body(state, "/api/session").get("session") or {})
        user = dict(session.get("user") or {})
        observed_logged_in = bool(session.get("loggedIn") or user)
        if observed_logged_in:
            expected_phone = str(params.get("expected_phone") or "13800138000").strip()
            observed_phone = str(user.get("phone") or "").strip()
            if not expected_phone or observed_phone != expected_phone:
                raise InitializationError(
                    "OpenShop is signed in as an unexpected account; refusing to reset it"
                )

        if params.get("restore_seed_state", True):
            app_name = str(params.get("app_name") or self.APP_NAME).strip()
            mode = str(params.get("benchmark_mode") or "macos.openshop")
            self._reset_task_snapshot(controller, port, app_name, mode)
            self._did_boundary_reset = True
            port, state, notes = self._read_loopback(
                controller,
                [params.get("port") or DEFAULT_PORT],
                ["/api/session", "/api/benchmark"],
                what="OpenShop state after task snapshot reset",
            )
            if port is None:
                raise InitializationError(
                    "OpenShop did not recover after restoring the task snapshot"
                    + (f" ({'; '.join(notes)})" if notes else "")
                )
            session = dict(self._endpoint_body(state, "/api/session").get("session") or {})
            observed_logged_in = bool(session.get("loggedIn") or session.get("user"))
            if observed_logged_in:
                raise InitializationError("OpenShop remained signed in after task snapshot reset")
            benchmark = self._endpoint_body(state, "/api/benchmark")
            events = benchmark.get("events") or []
            if events:
                raise InitializationError("OpenShop benchmark event ledger was not empty after reset")
            if benchmark.get("benchmarkMode") != mode:
                raise InitializationError("OpenShop benchmark mode did not match the current task")
            self._verify_seed_assets(controller, params)
        else:
            expected_logged_in = bool(params.get("expected_logged_in"))
            observed_logged_in = bool(session.get("loggedIn") or session.get("user"))
            if observed_logged_in != expected_logged_in:
                raise InitializationError(
                    f"OpenShop signed-in state is {observed_logged_in}, "
                    f"expected {expected_logged_in}"
                )

        card = str(params.get("expected_account_card") or "")
        timeout = float(params.get("visible_timeout_seconds") or DEFAULT_VISIBLE_TIMEOUT_SECONDS)
        self._wait_for_visible(
            controller,
            [card, params.get("expected_password_label") or "Password"],
            timeout=timeout,
            what="the OpenShop account chooser",
        )

        return (
            "restored the task seed and verified historical order fixtures and an empty event ledger; "
            if self._did_boundary_reset else ""
        ) + (
            f"OpenShop answers on port {port}, signed_in={observed_logged_in}, "
            f"with the {card or 'expected'} account selected and its password field showing"
        )

    def _reset_task_snapshot(
        self, controller: Any, port: int, app_name: str, benchmark_mode: str
    ) -> None:
        """Reset the app seed and restart its window so the UI reflects it."""
        payload = json.dumps({"benchmarkMode": benchmark_mode}, ensure_ascii=False)
        script = "\n".join(
            [
                "import json, urllib.request",
                f"url = 'http://127.0.0.1:{int(port)}/api/dev/reset'",
                f"payload = {payload!r}.encode('utf-8')",
                "request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')",
                "with urllib.request.urlopen(request, timeout=20) as response:",
                "    reset = json.loads(response.read().decode('utf-8'))",
                "session = reset.get('session') or {}",
                "cart = reset.get('cart') or {}",
                "print(json.dumps({'ok': reset.get('ok') is True, 'logged_in': bool(session.get('loggedIn')), 'cart_empty': not bool(cart.get('items')), 'benchmark_mode': reset.get('benchmarkMode')}))",
            ]
        )
        response = self._guest_python(controller, script, timeout=30)
        output = str(response.get("stdout") or response.get("output") or "")
        error = str(response.get("stderr") or response.get("error") or "")
        if int(response.get("returncode", -1)) != 0:
            raise InitializationError(
                f"OpenShop could not restore the task snapshot: {error.strip() or output.strip() or 'reset failed'}"
            )
        try:
            state = json.loads([line for line in output.splitlines() if line.strip()][-1])
        except (IndexError, ValueError) as exc:
            raise InitializationError("OpenShop snapshot reset did not return confirmation") from exc
        if (
            state.get("ok") is not True
            or state.get("logged_in") is not False
            or state.get("cart_empty") is not True
            or state.get("benchmark_mode") != benchmark_mode
        ):
            raise InitializationError("OpenShop snapshot reset was not confirmed as clean")
        self._did_boundary_reset = True

        app_path, _ = self._inspect_installation(controller, app_name)
        stop_script = "\n".join(
            [
                "import json, os, plistlib, signal, subprocess, time",
                f"app = {app_path!r}",
                "with open(os.path.join(app, 'Contents', 'Info.plist'), 'rb') as stream:",
                "    executable = plistlib.load(stream)['CFBundleExecutable']",
                "expected = os.path.join(app, 'Contents', 'MacOS', executable)",
                "lines = subprocess.check_output(['/bin/ps', '-axo', 'pid=,comm='], text=True).splitlines()",
                "pids = []",
                "for line in lines:",
                "    fields = line.strip().split(None, 1)",
                "    if len(fields) == 2 and fields[1] == expected and fields[0].isdigit(): pids.append(int(fields[0]))",
                "for pid in pids:",
                "    try: os.kill(pid, signal.SIGTERM)",
                "    except ProcessLookupError: pass",
                "deadline = time.monotonic() + 8",
                "while time.monotonic() < deadline:",
                "    active = []",
                "    for pid in pids:",
                "        try: os.kill(pid, 0); active.append(pid)",
                "        except ProcessLookupError: pass",
                "    if not active: break",
                "    time.sleep(0.2)",
                "print(json.dumps({'stopped': not bool(active), 'pid_count': len(pids)}))",
            ]
        )
        stopped = self._guest_python(controller, stop_script, timeout=15)
        stop_output = str(stopped.get("stdout") or stopped.get("output") or "")
        stop_error = str(stopped.get("stderr") or stopped.get("error") or "")
        if int(stopped.get("returncode", -1)) != 0:
            raise InitializationError(
                f"OpenShop could not restart after seed reset: {stop_error.strip() or stop_output.strip() or 'guest process stop failed'}"
            )
        try:
            stop_state = json.loads([line for line in stop_output.splitlines() if line.strip()][-1])
        except (IndexError, ValueError) as exc:
            raise InitializationError("OpenShop shutdown did not return a verifiable result") from exc
        if not stop_state.get("stopped") or not stop_state.get("pid_count"):
            raise InitializationError("OpenShop did not stop cleanly after seed reset")
        launched = controller.launch_app(app_name)
        if isinstance(launched, Mapping) and launched.get("success") is False:
            raise InitializationError(
                f"OpenShop could not relaunch after seed reset: {launched.get('error') or launched.get('message')}"
            )
        self._wait_for_process(controller, app_path)
        self._settle({"wait_ms": 2000})

    def _verify_seed_assets(self, controller: Any, params: Mapping[str, Any]) -> None:
        """Verify the packaged seed still contains the historical task orders."""
        phone = json.dumps(str(params.get("expected_phone") or "13800138000"))
        order_ids = json.dumps(list(params.get("expected_historical_order_ids") or []))
        expected_count = int(params.get("expected_seed_order_count", 4))
        script = f'''import json, pathlib
seed_path = pathlib.Path("/Applications/OS-Omni Open Runtime/apps/openshop/shared/seed-data.json")
seed = json.loads(seed_path.read_text(encoding="utf-8"))
phone = {phone}
expected_ids = set({order_ids})
accounts = seed.get("accounts") or []
account = next((item for item in accounts if str(item.get("phone") or "") == phone), None)
if account is None:
    raise SystemExit("expected OpenShop seed account is missing")
orders = account.get("orders") or []
ids = {{str(order.get("id") or "") for order in orders}}
missing = sorted(expected_ids - ids)
print(json.dumps({{"order_count": len(orders), "expected_order_count": {expected_count}, "missing_historical_order_count": len(missing)}}))
if len(orders) != {expected_count} or missing:
    raise SystemExit("OpenShop historical seed does not match task preconditions")
'''
        result = self._guest_python(controller, script, timeout=30)
        if int(result.get("returncode", -1)) != 0:
            detail = str(result.get("stderr") or result.get("error") or result.get("output") or "seed validation failed").strip()
            raise InitializationError(f"OpenShop seed fixtures are incomplete: {detail}")
