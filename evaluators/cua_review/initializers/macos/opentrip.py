# Author-maintained boundary reset for serial single-VM macOS runs.
"""Restore and verify OpenTrip's seeded, signed-out task starting state.

The original VM-clone workflow implicitly reset OpenTrip between tasks. The
author queue now reuses one VM, so this initializer restores the app's own
developer seed endpoint at each task boundary. It refuses to reset an
unexpected signed-in account and never logs in or creates task results.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from evaluators.cua_review.core.initialization import InitializationError, MacAppInitializer

DEFAULT_PORT = 4330
DEFAULT_VISIBLE_TIMEOUT_SECONDS = 45.0


class OpenTripInitializer(MacAppInitializer):
    """Reset only the benchmark app's task seed, then verify its sign-in page."""

    INITIALIZER_ID = "initializers.macos.opentrip:OpenTripInitializer"
    APP_NAME = "OpenTrip"
    BUNDLE_ID = "local.osomni.opentrip"
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
        if task_id:
            params.setdefault("benchmark_mode", task_id)
        evaluation = getattr(task, "evaluation", None)
        session = dict(getattr(evaluation, "params", {}) or {}).get("session") or {}
        params.setdefault("expected_account_phone", session.get("phone"))
        return super().initialize({**context, "params": params})

    def verify_preconditions(self, controller: Any, params: Mapping[str, Any]) -> str:
        app_name = str(params.get("app_name") or self.APP_NAME).strip()
        port = int(params.get("port") or DEFAULT_PORT)
        paths = ["/api/session", "/api/bookings", "/api/benchmark"]
        observed_port, state, notes = self._read_loopback(
            controller, [port], paths, what="OpenTrip state"
        )
        if observed_port is None:
            raise InitializationError(
                "OpenTrip did not answer its session, bookings, and benchmark APIs"
                + (f" ({'; '.join(notes)})" if notes else "")
            )

        session = dict(self._endpoint_body(state, "/api/session").get("session") or {})
        user = dict(session.get("user") or {})
        observed_logged_in = bool(session.get("loggedIn") or user)
        expected_phone = str(params.get("expected_account_phone") or "").strip()
        if observed_logged_in:
            observed_phone = str(user.get("phone") or session.get("phone") or "").strip()
            if not expected_phone or observed_phone != expected_phone:
                raise InitializationError(
                    "OpenTrip is signed in as an unexpected account; refusing to reset it"
                )

        benchmark_mode = str(params.get("benchmark_mode") or "macos.opentrip")
        self._restore_task_seed(controller, observed_port, app_name, benchmark_mode)
        self._did_boundary_reset = True

        observed_port, state, notes = self._read_loopback(
            controller, [port], paths, what="OpenTrip state after task seed reset"
        )
        if observed_port is None:
            raise InitializationError(
                "OpenTrip did not recover after restoring its task seed"
                + (f" ({'; '.join(notes)})" if notes else "")
            )
        session = dict(self._endpoint_body(state, "/api/session").get("session") or {})
        if bool(session.get("loggedIn") or session.get("user")):
            raise InitializationError("OpenTrip remained signed in after task seed reset")
        benchmark = self._endpoint_body(state, "/api/benchmark")
        if benchmark.get("events"):
            raise InitializationError("OpenTrip benchmark event ledger was not empty after reset")

        account = dict((params.get("expected_seed") or {}).get("account") or {})
        markers = [account.get("phone"), params.get("expected_sign_in_label") or "Sign In"]
        timeout = float(params.get("visible_timeout_seconds") or DEFAULT_VISIBLE_TIMEOUT_SECONDS)
        self._wait_for_visible(
            controller, markers, timeout=timeout, what="the OpenTrip sign-in page"
        )
        return (
            f"OpenTrip task seed reset for {benchmark_mode}; signed out with an empty event ledger "
            f"and the {account.get('name') or 'expected'} account prefilled"
        )

    def _restore_task_seed(
        self, controller: Any, port: int, app_name: str, benchmark_mode: str
    ) -> None:
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
                "print(json.dumps({'ok': reset.get('ok') is True, 'logged_in': bool(session.get('loggedIn')), 'benchmark_mode': reset.get('benchmarkMode')}))",
            ]
        )
        response = self._guest_python(controller, script, timeout=30)
        output = str(response.get("stdout") or response.get("output") or "")
        error = str(response.get("stderr") or response.get("error") or "")
        if int(response.get("returncode", -1)) != 0:
            raise InitializationError(
                "OpenTrip could not restore its task seed: "
                + (error.strip() or output.strip() or "reset failed")
            )
        try:
            reset = json.loads([line for line in output.splitlines() if line.strip()][-1])
        except (IndexError, ValueError) as exc:
            raise InitializationError("OpenTrip seed reset did not return confirmation") from exc
        if reset.get("ok") is not True or reset.get("logged_in") is not False:
            raise InitializationError(
                "OpenTrip task seed reset was not confirmed clean "
                f"(ok={reset.get('ok')!r}, logged_in={reset.get('logged_in')!r})"
            )

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
                "OpenTrip could not restart after seed reset: "
                + (stop_error.strip() or stop_output.strip() or "guest process stop failed")
            )
        try:
            state = json.loads([line for line in stop_output.splitlines() if line.strip()][-1])
        except (IndexError, ValueError) as exc:
            raise InitializationError("OpenTrip shutdown did not return confirmation") from exc
        if not state.get("stopped") or not state.get("pid_count"):
            raise InitializationError("OpenTrip did not stop cleanly after seed reset")
        self._dismiss_unrelated_thunderbird_ui(controller)
        launch = controller.launch_app(app_name)
        if isinstance(launch, Mapping) and launch.get("success") is False:
            raise InitializationError(
                f"OpenTrip could not relaunch after seed reset: {launch.get('error') or launch.get('message')}"
            )
        self._wait_for_process(controller, app_path)
        self._settle({"wait_ms": 2000})

    def _dismiss_unrelated_thunderbird_ui(self, controller: Any) -> None:
        """Quit a stray Thunderbird window before the OpenTrip task starts.

        A persistent Thunderbird survey window was observed covering the lower
        rows of OpenTrip's date picker. OpenTrip tasks do not depend on
        Thunderbird, so the initializer closes that unrelated app gracefully
        and verifies that its process has exited before foregrounding OpenTrip.
        """
        script = "\n".join(
            [
                "import json, os, subprocess, time",
                "def thunderbird_pids():",
                "    out = subprocess.run(['/bin/ps', '-axo', 'pid=,comm='], capture_output=True, text=True, check=True).stdout",
                "    found = []",
                "    for line in out.splitlines():",
                "        fields = line.strip().split(None, 1)",
                "        if len(fields) != 2 or not fields[0].isdigit(): continue",
                "        command = fields[1]",
                "        if command.lower().endswith('/thunderbird') or os.path.basename(command).lower() == 'thunderbird': found.append(int(fields[0]))",
                "    return found",
                "before = thunderbird_pids()",
                "if before:",
                "    quit_result = subprocess.run(['/usr/bin/osascript', '-e', 'tell application id \\\"org.mozilla.thunderbird\\\" to quit'], capture_output=True, text=True, timeout=15)",
                "    if quit_result.returncode != 0: raise RuntimeError('Thunderbird quit request failed')",
                "    deadline = time.monotonic() + 20",
                "    while time.monotonic() < deadline and thunderbird_pids(): time.sleep(0.25)",
                "after = thunderbird_pids()",
                "print(json.dumps({'running_before': bool(before), 'stopped': not bool(after)}))",
            ]
        )
        response = self._guest_python(controller, script, timeout=40)
        output = str(response.get("stdout") or response.get("output") or "")
        error = str(response.get("stderr") or response.get("error") or "")
        if int(response.get("returncode", -1)) != 0:
            raise InitializationError(
                "OpenTrip could not close unrelated Thunderbird UI: "
                + (error.strip() or output.strip() or "quit request failed")
            )
        try:
            state = json.loads([line for line in output.splitlines() if line.strip()][-1])
        except (IndexError, ValueError) as exc:
            raise InitializationError(
                "OpenTrip Thunderbird cleanup did not return confirmation"
            ) from exc
        if state.get("stopped") is not True:
            raise InitializationError(
                "Thunderbird remained open and could obscure OpenTrip controls"
            )
