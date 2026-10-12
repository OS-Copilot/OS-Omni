"""Initializer for the snapshot-backed OpenSlide application."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, verify_paths


# OpenSlide re-renders the slide on mousedown (selectObject -> renderSlide) and on any
# mousemove while the button is down, so the contenteditable text object under the
# pointer is replaced and loses focus: text can be edited only by tabbing ~47 times
# into the canvas. Selecting an already selected object no longer re-renders, and a
# drag starts after 3 px, so click-to-select then click-to-edit works as in other slide
# editors; dragging still works. Clicking the background re-rendered the stage before the
# edit was committed on focusout, leaving the old text displayed; it is now redrawn.
EDIT_FOCUS_PATCH = r"""python3 - <<'PY'
import pathlib
path = pathlib.Path("/home/user/Applications/openslide_web/public/app.js")
source = path.read_text()
replacements = [
    ("      selectObject(item.dataset.objectId);\n      const object = selectedObject();\n      state.drag = {",
     "      if (state.selectedId !== item.dataset.objectId) selectObject(item.dataset.objectId);\n"
     "      const object = selectedObject();\n      state.drag = {"),
    ("    if (!object) return;\n    commitTransform(transform);\n    object.x = ",
     "    if (!object) return;\n"
     "    if (!transform.committed && Math.abs(event.clientX - transform.startX) < 3"
     " && Math.abs(event.clientY - transform.startY) < 3) return;\n"
     "    commitTransform(transform);\n    object.x = "),
    ("      markDirty();\n      renderSlideStrip();\n    });",
     "      markDirty();\n      renderSlideStrip();\n      requestAnimationFrame(() => { if (!item.isConnected) renderSlide(); });\n    });"),
]
status = []
for old, new in replacements:
    if new in source:
        status.append("already patched")
    elif source.count(old) == 1:
        source = source.replace(old, new)
        status.append("patched")
    else:
        raise SystemExit("OpenSlide pointer handler not found")
path.write_text(source)
print(",".join(status))
PY
"""


class OpenSlideInitializer(BaseInitializer):
    APP_PATH = "/home/user/Applications/openslide_web/public/index.html"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_path = str(params.get("app_path") or self.APP_PATH)
        try:
            verify_paths(controller, [app_path])
            patch = controller.run_bash_script(EDIT_FOCUS_PATCH, timeout=30)
            if int(patch.get("returncode", patch.get("return_code", 1)) or 0) != 0:
                raise RuntimeError(f"OpenSlide edit-focus patch failed: {patch}")
            launch_guest(controller, f"file://{app_path}", wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare OpenSlide: {exc}", {"app_path": app_path})
        return InitResult(
            InitStatus.PASS,
            "OpenSlide ready without resetting persisted state",
            {"app_path": app_path, "cleared_state": False, "edit_focus_patch": (patch.get("output") or "").strip()},
        )
