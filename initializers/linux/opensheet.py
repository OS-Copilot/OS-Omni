"""OpenSheet snapshot environment validation."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import run_guest

APP_JS = "/home/user/Applications/opensheet_web/public/app.js"

# OpenSheet commits a grid cell on focusout from the cell's textContent, which is the rendered
# display value: clicking a formula cell and then anything else replaced =SUM(B2:E2) with its
# result, and clicking a cell formatted as Number with one decimal stored 80 as "80.0". A cell
# is now committed on focusout only after its text was edited (an input event), so a typed edit
# still commits on Enter, Tab or clicking away; the formula bar is unchanged.
EDIT_COMMIT_PATCH = r"""python3 - <<'PY'
import json, pathlib
path = pathlib.Path(json.loads(__APP_JS__))
source = path.read_text()
old = (
    '    elements.sheetGrid.addEventListener("focusout", (event) => {\n'
    '      const cell = event.target.closest(".sheet-cell");\n'
    '      if (!cell) return;\n'
    '      commitCell(cell.dataset.address, cell.textContent);\n'
    '    });'
)
new = (
    '    elements.sheetGrid.addEventListener("input", (event) => {\n'
    '      const cell = event.target.closest(".sheet-cell");\n'
    '      if (cell) cell.dataset.edited = "1";\n'
    '    });\n'
    '    elements.sheetGrid.addEventListener("focusout", (event) => {\n'
    '      const cell = event.target.closest(".sheet-cell");\n'
    '      if (!cell || cell.dataset.edited !== "1") return;\n'
    '      commitCell(cell.dataset.address, cell.textContent);\n'
    '    });'
)
if new in source:
    print("already patched")
elif source.count(old) == 1:
    path.write_text(source.replace(old, new))
    print("patched")
else:
    raise SystemExit("OpenSheet focusout handler not found in %s" % path)
PY
"""


def patch_edit_commit(controller: Any, app_js: str = APP_JS) -> str:
    """Apply EDIT_COMMIT_PATCH in the guest; returns "patched" or "already patched"."""

    script = EDIT_COMMIT_PATCH.replace("__APP_JS__", repr(json.dumps(app_js)))
    result = run_guest(controller, script, timeout=30)
    return str(result.get("output") or result.get("stdout") or "").strip()


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
            patch = patch_edit_commit(controller)
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenSheet environment validation failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenSheet launcher and app files are present in the snapshot",
            {"snapshot_display_name": str(params.get("snapshot_display_name") or ""), "edit_commit_patch": patch},
        )
