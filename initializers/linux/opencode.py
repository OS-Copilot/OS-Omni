"""Read-only OpenCode snapshot validator."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import run_guest


class OpenCodeWorkspaceInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        payload = json.dumps(
            {
                "seed_path": str(params.get("seed_path") or ""),
                "required_files": list(params.get("required_files") or []),
                "forbidden_text": dict(params.get("forbidden_text") or {}),
            },
            ensure_ascii=False,
        )
        script = """python3 - <<'PY'
import json, pathlib
payload = json.loads(%r)
seed_path = pathlib.Path(payload['seed_path'])
if not seed_path.is_file():
    raise SystemExit('missing seed data: ' + str(seed_path))
text = seed_path.read_text(encoding='utf-8', errors='replace')
for relative in payload['required_files']:
    if relative not in text:
        raise SystemExit('missing seeded file declaration: ' + relative)
for relative, forbidden_values in payload['forbidden_text'].items():
    for forbidden in forbidden_values:
        if forbidden in text:
            raise SystemExit('target text already present in seed: ' + relative + ': ' + forbidden)
PY
test -e /home/user/Desktop/webpage/OpenCode
command -v code >/dev/null 2>&1 || command -v codium >/dev/null 2>&1
""" % payload
        try:
            run_guest(controller, script, timeout=int(params.get("timeout", 20) or 20))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenCode snapshot validation failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Verified OpenCode seed data exists in the current snapshot state",
            {
                "seed_path": str(params.get("seed_path") or ""),
                "expected_snapshot": str(params.get("expected_snapshot") or ""),
                "app_name": str(params.get("app_name") or "OpenCode"),
            },
        )
