"""OpenSheet snapshot environment validation."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import run_guest


class OpenSheetEnvironmentInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        payload = json.dumps(
            {
                "app_files": list(params.get("app_files") or []),
                "launchers": list(params.get("desktop_icon_candidates") or params.get("desktop_paths") or []),
                "required_terms": list(params.get("required_terms") or []),
            },
            ensure_ascii=False,
        )
        script = """python3 - <<'PY'
import json, pathlib
payload = json.loads(%r)
files = [pathlib.Path(value) for value in payload['app_files']]
missing = [str(path) for path in files if not path.is_file()]
if missing:
    raise SystemExit('missing app files: ' + ', '.join(missing))
if not any(pathlib.Path(value).exists() for value in payload['launchers']):
    raise SystemExit('OpenSheet launcher is missing')
corpus = '\\n'.join(path.read_text(encoding='utf-8', errors='replace') for path in files)
missing_terms = [value for value in payload['required_terms'] if value not in corpus]
if missing_terms:
    raise SystemExit('missing app terms: ' + ', '.join(missing_terms))
PY""" % payload
        try:
            run_guest(controller, script, timeout=30)
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenSheet environment validation failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenSheet launcher and app files are present in the snapshot",
            {"snapshot_display_name": str(params.get("snapshot_display_name") or "")},
        )
