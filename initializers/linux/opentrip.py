"""OpenTrip snapshot initializers reconstructed from review artifacts."""

from __future__ import annotations

import json
import shlex
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, run_guest, verify_paths, write_text_files


class OpenTripInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        requested = str(params.get("app_command") or "opentrip")
        static_path = str(params.get("static_web_path") or "")
        target = f"file://{static_path}" if static_path else requested
        try:
            if static_path:
                verify_paths(controller, [static_path])
            written = write_text_files(controller, params.get("seed_files", []))
            launch_guest(controller, target, wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare OpenTrip: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Prepared OpenTrip initial state from the restored snapshot",
            {
                "requested_app_command": requested,
                "static_web_path": static_path,
                "seed_file_count": len(written),
                "vm_snapshot_name": str(params.get("vm_snapshot_name") or ""),
            },
        )


class OpenTripSnapshotPreflightInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        candidates = [str(value) for value in params.get("desktop_entry_candidates", [])]
        quoted = " ".join(shlex.quote(value) for value in candidates)
        script = f"""command -v {shlex.quote(str(params.get('app_command') or 'opentrip'))} >/dev/null 2>&1 && exit 0
for name in {quoted}; do
  test -e "/home/user/Desktop/$name" && exit 0
  test -e "/home/user/Desktop/webpage/$name" && exit 0
done
exit 1"""
        try:
            run_guest(controller, script, timeout=20)
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenTrip snapshot preflight failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenTrip snapshot preflight recorded; no app state was changed",
            {
                "snapshot_name": str(params.get("snapshot_name") or ""),
                "expected_account": str(params.get("expected_account") or ""),
                "readonly": True,
                "app_launched": False,
            },
        )


class OpenTripBaselineInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_dir = str(params.get("app_dir") or "/home/user/Applications/opentrip_web")
        launcher = str(params.get("launcher_path") or "/home/user/Desktop/webpage/OpenTrip")
        profile_dir = str(params.get("profile_dir") or "/home/user/.config/google-chrome")
        required = ["OpenTrip.html", "app.js", "seed-data.js", "bookings.html"]
        payload = json.dumps(
            {
                "seed": [str(value) for value in params.get("required_seed_text", [])],
                "targets": [str(value) for value in params.get("target_notes", [])],
                "app_dir": app_dir,
                "profile_dir": profile_dir,
            },
            ensure_ascii=False,
        )
        script = f"""python3 - <<'PY'
import json, pathlib
payload = json.loads({payload!r})
app_dir = pathlib.Path(payload['app_dir'])
corpus = '\\n'.join(path.read_text(encoding='utf-8', errors='replace') for path in app_dir.glob('*') if path.is_file())
for value in payload['seed']:
    if value not in corpus:
        raise SystemExit('missing OpenTrip seed: ' + value)
storage = pathlib.Path(payload['profile_dir']) / 'Default/Local Storage/leveldb'
if not storage.is_dir():
    raise SystemExit('missing Chrome local storage')
storage_corpus = b''.join(path.read_bytes() for path in storage.glob('*') if path.is_file())
if b'opentrip.localState.v1' not in storage_corpus:
    raise SystemExit('missing OpenTrip local-state key')
for value in payload['targets']:
    if value.encode() in storage_corpus:
        raise SystemExit('target note already present: ' + value)
PY
test -e {shlex.quote(launcher)}
"""
        try:
            verify_paths(controller, [*(f"{app_dir}/{name}" for name in required)])
            run_guest(controller, script, timeout=int(params.get("timeout", 30) or 30))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenTrip baseline validation failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenTrip snapshot dependencies are present and target evidence is absent",
            {
                "app_dir": app_dir,
                "launcher_path": launcher,
                "profile_dir": profile_dir,
                "snapshot_name": str(params.get("snapshot_name") or ""),
            },
        )
