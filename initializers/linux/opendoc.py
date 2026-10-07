"""OpenDoc snapshot validation and clean-baseline initializers."""

from __future__ import annotations

import json
import shlex
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, run_guest, verify_paths


class OpenDocSnapshotValidator(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        workspace_dir = str(params.get("workspace_dir") or "/home/user/Desktop/webpage")
        source_document = str(params.get("source_document") or "")
        search_roots = [str(value) for value in params.get("search_roots", [])]
        payload = json.dumps({"roots": search_roots, "needle": source_document}, ensure_ascii=False)
        script = f"""test -d {shlex.quote(workspace_dir)}
test -e {shlex.quote(workspace_dir.rstrip('/') + '/OpenDoc')}
python3 - <<'PY'
import json, pathlib
payload = json.loads({payload!r})
needle = payload['needle'].encode()
def contains(path):
    try:
        return path.stat().st_size <= 32 * 1024 * 1024 and needle in path.read_bytes()
    except (OSError, PermissionError):
        return False
if needle and not any(
    contains(path)
    for root in payload['roots']
    for path in pathlib.Path(root).rglob('*')
    if path.is_file()
):
    raise SystemExit('source document seed not found: ' + payload['needle'])
PY"""
        try:
            run_guest(controller, script, timeout=int(params.get("timeout", 30) or 30))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenDoc snapshot validation failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenDoc snapshot prerequisites are present",
            {
                "workspace_dir": workspace_dir,
                "source_document": source_document,
                "search_roots": search_roots,
                "snapshot_name": str(params.get("snapshot_name") or ""),
            },
        )


class OpenDocCleanStorageInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_path = str(params.get("app_path") or "/home/user/Applications/opendoc_web/public/index.html")
        shortcut_path = str(params.get("shortcut_path") or "/home/user/Desktop/webpage/OpenDoc")
        try:
            verify_paths(controller, [app_path, shortcut_path])
            # The source run reported no removed files. Preserve the restored snapshot and
            # only open its clean OpenDoc entry point.
            launch_guest(controller, f"file://{app_path}", wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare clean OpenDoc state: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenDoc is ready on the restored desktop baseline",
            {
                "app_path": app_path,
                "shortcut_path": shortcut_path,
                "snapshot_name": str(params.get("snapshot_name") or ""),
                "target_state_created": False,
            },
        )
