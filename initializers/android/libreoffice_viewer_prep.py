"""Prepare LibreOffice Viewer: launch app, open create sheet, tap New Text Document row.

This moves the agent past the bottom-right FAB toggle loop by scripting the first
two UI hops. The agent still types, saves, and reopens per the task instruction.
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

from core.init import BaseInitializer, InitResult, InitStatus

_LIBREOFFICE_PACKAGE = "org.documentfoundation.libreoffice"
_LIBREOFFICE_ACTIVITY = "org.libreoffice.ui.LibreOfficeUIActivity"
_HOME_MARKERS = (
    "Recent files",
    "header_recents",
    "SELECT FILE TO OPEN",
    "list_recent",
    "open_file_button",
)
_SETTINGS_TITLE_MARKERS = (
    "General",
    "Experimental Mode",
    "Developer Mode",
)
_DEFAULT_CLEANUP_DIRS = (
    "/sdcard/Documents",
    "/sdcard/Download",
    "/sdcard/Downloads",
    "/sdcard",
)


def _rid(n: dict[str, Any]) -> str:
    return str(n.get("resource_id") or n.get("resource-id") or "")


def _text(n: dict[str, Any]) -> str:
    return str(n.get("text") or "")


def _fab_node(ui_nodes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for n in ui_nodes:
        if "editFAB" in _rid(n):
            return n
    return None


def _desc(n: dict[str, Any]) -> str:
    return str(n.get("content_description") or n.get("content-desc") or "")


def _has_text(n: dict[str, Any], needle: str) -> bool:
    blob = f"{_text(n)} {_desc(n)}".strip().lower()
    return needle.strip().lower() in blob


def _find_text_node(ui_nodes: list[dict[str, Any]], needle: str) -> Optional[dict[str, Any]]:
    for n in ui_nodes:
        if _has_text(n, needle):
            return n
    return None


def _find_clickable_ancestor_like(
    ui_nodes: list[dict[str, Any]],
    child: dict[str, Any],
) -> Optional[dict[str, Any]]:
    child_rect = child.get("rect") or {}
    try:
        cx = int(child_rect["x"])
        cy = int(child_rect["y"])
        cw = int(child_rect["w"])
        ch = int(child_rect["h"])
    except (TypeError, ValueError, KeyError):
        return None

    best: Optional[dict[str, Any]] = None
    best_area: Optional[int] = None
    for n in ui_nodes:
        if str(n.get("clickable") or "").lower() != "true":
            continue
        rect = n.get("rect") or {}
        try:
            nx = int(rect["x"])
            ny = int(rect["y"])
            nw = int(rect["w"])
            nh = int(rect["h"])
        except (TypeError, ValueError, KeyError):
            continue
        if nx <= cx and ny <= cy and (nx + nw) >= (cx + cw) and (ny + nh) >= (cy + ch):
            area = nw * nh
            if best_area is None or area < best_area:
                best = n
                best_area = area
    return best


def _node_vertical_center(n: dict[str, Any]) -> Optional[int]:
    rect = n.get("rect") or {}
    try:
        y1 = int(rect["y"])
        h = int(rect["h"])
        return y1 + h // 2
    except (TypeError, ValueError, KeyError):
        pass
    tap = n.get("tap") or {}
    try:
        return int(tap["y"])
    except (TypeError, ValueError, KeyError):
        return None


def _best_new_text_document_node(ui_nodes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Pick the real template row, not a tall parent: prefer tight bounds + lowest on screen.

    In LibreOffice Viewer's FAB sheet, options stack vertically; New Text Document is the
    bottom template (just above ×). A large parent node can span all rows—its y_mid hits
    Spreadsheet by mistake.
    """
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for n in ui_nodes:
        raw = _text(n).strip()
        if "New Text Document" not in raw:
            continue
        # Skip combined / wrong rows if the node bundles other template names.
        lower = raw.lower()
        if any(
            bad in lower
            for bad in ("spreadsheet", "presentation", "drawing", "new spreadsheet")
        ):
            continue
        rect = n.get("rect") or {}
        try:
            h = int(rect["h"])
            y1 = int(rect["y"])
        except (TypeError, ValueError, KeyError):
            h, y1 = 0, 0
        yc = _node_vertical_center(n)
        if yc is None:
            continue
        # Prefer label-sized rows; penalize very tall nodes (multi-row containers).
        if h <= 0:
            tier = 2
        elif h <= 220:
            tier = 0
        else:
            tier = 1
        # tier, then lowest on screen (largest yc), then smaller height (tighter label).
        candidates.append((tier, yc, -h, n))

    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], -t[1], t[2]))
    return candidates[0][3]


def _tap_node_center(controller: Any, n: dict[str, Any]) -> bool:
    tap = n.get("tap") or {}
    try:
        x = int(tap.get("x"))
        y = int(tap.get("y"))
    except (TypeError, ValueError):
        return False
    controller.tap(x, y)
    return True


def _tap_new_text_icon_right(controller: Any, label_node: dict[str, Any], screen_w: int) -> None:
    """Tap the circular blue document icon: far right, same row as the label."""
    rect = label_node.get("rect") or {}
    try:
        y1 = int(rect["y"])
        h = int(rect["h"])
        # Tall container: bias toward bottom of bounds (text doc row is the lowest option).
        if h > 220:
            y_mid = y1 + int(h * 0.88)
        else:
            y_mid = y1 + h // 2
    except (TypeError, ValueError, KeyError):
        tap = label_node.get("tap") or {}
        y_mid = int(tap.get("y") or (controller.height // 2))
    tx = max(100, int(screen_w * 0.88))
    controller.tap(tx, y_mid)


def _looks_like_home(ui_nodes: list[dict[str, Any]]) -> bool:
    # Heuristic: if home-list markers are visible, we are still in file browser, not editor.
    for n in ui_nodes:
        blob = f"{_rid(n)} {_text(n)} {n.get('content_description','')} {n.get('content-desc','')}"
        if any(m in blob for m in _HOME_MARKERS):
            return True
    return False


def _looks_like_settings(ui_nodes: list[dict[str, Any]]) -> bool:
    for n in ui_nodes:
        blob = f"{_rid(n)} {_text(n)} {_desc(n)}"
        if any(marker.lower() in blob.lower() for marker in _SETTINGS_TITLE_MARKERS):
            return True
    return False


def _is_create_sheet_open(ui_nodes: list[dict[str, Any]]) -> bool:
    """Heuristic for LibreOffice create-sheet state.

    Home markers still exist behind the sheet, so use menu-item texts and enlarged FAB bounds.
    """
    menu_text_markers = (
        "New Drawing",
        "New Spreadsheet",
        "New Presentation",
        "New Text Document",
    )
    for n in ui_nodes:
        t = _text(n)
        if any(m in t for m in menu_text_markers):
            return True

    fab = _fab_node(ui_nodes)
    if fab:
        rect = fab.get("rect") or {}
        try:
            # In expanded state, this node usually grows (e.g., ~266x282 on 1080x2424).
            w = int(rect.get("w", 0))
            h = int(rect.get("h", 0))
            if w >= 240 or h >= 270:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _checkbox_is_checked(node: Optional[dict[str, Any]]) -> bool:
    if not node:
        return False
    return str(node.get("checked") or "").strip().lower() == "true"


def _open_more_options_and_settings(controller: Any, ui_nodes: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    more_options = _find_text_node(ui_nodes, "more options")
    if more_options is None:
        return False, ui_nodes
    if not _tap_node_center(controller, more_options):
        return False, ui_nodes
    time.sleep(0.7)
    obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
    ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
    settings = _find_text_node(ui_nodes, "settings")
    if settings is None:
        return False, ui_nodes
    settings_target = _find_clickable_ancestor_like(ui_nodes, settings) or settings
    if not _tap_node_center(controller, settings_target):
        return False, ui_nodes
    time.sleep(0.9)
    obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
    return True, list(getattr(obs, "ui_nodes", None) or [])


def _ensure_experimental_mode_enabled(controller: Any) -> tuple[bool, dict[str, Any]]:
    """Enable Experimental Mode when the home screen has no create FAB."""
    metadata: dict[str, Any] = {
        "attempted": False,
        "opened_settings": False,
        "already_enabled": False,
        "toggled": False,
        "returned_home": False,
    }
    obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
    ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
    if _fab_node(ui_nodes) is not None or _is_create_sheet_open(ui_nodes):
        return True, metadata

    metadata["attempted"] = True
    if not _looks_like_settings(ui_nodes):
        opened, ui_nodes = _open_more_options_and_settings(controller, ui_nodes)
        metadata["opened_settings"] = opened
        if not opened:
            return False, metadata

    if not _looks_like_settings(ui_nodes):
        return False, metadata

    experimental_title = _find_text_node(ui_nodes, "experimental mode")
    if experimental_title is None:
        return False, metadata

    checkbox = None
    for n in ui_nodes:
        if "android:id/checkbox" in _rid(n):
            checkbox = n
            break
    if _checkbox_is_checked(checkbox):
        metadata["already_enabled"] = True
    else:
        toggle_target = _find_clickable_ancestor_like(ui_nodes, experimental_title) or experimental_title
        if not _tap_node_center(controller, toggle_target):
            return False, metadata
        time.sleep(0.7)
        obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
        ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
        checkbox = None
        for n in ui_nodes:
            if "android:id/checkbox" in _rid(n):
                checkbox = n
                break
        if not _checkbox_is_checked(checkbox):
            return False, metadata
        metadata["toggled"] = True

    controller.press_back()
    time.sleep(0.9)
    obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
    ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
    metadata["returned_home"] = _looks_like_home(ui_nodes)
    return metadata["returned_home"], metadata


class LibreOfficeViewerNewTextPrepInitializer(BaseInitializer):
    """Launch LibreOffice Viewer, open the create sheet once, open New Text Document."""

    DEFAULT_WAIT_MS = 2000
    DEFAULT_SHEET_SETTLE_MS = 800
    DEFAULT_AFTER_TEMPLATE_MS = 1200
    DEFAULT_TEMPLATE_RETRIES = 3
    DEFAULT_HOME_READY_TIMEOUT_SECONDS = 8.0

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "observe"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller with observe() and tap() is required",
            )
        if not hasattr(controller, "tap"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.tap is required",
            )

        app_name = str(params.get("app_name") or "libreoffice").strip().lower()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        sheet_ms = int(params.get("sheet_settle_ms", self.DEFAULT_SHEET_SETTLE_MS) or 0)
        after_ms = int(params.get("after_template_ms", self.DEFAULT_AFTER_TEMPLATE_MS) or 0)
        retries = int(params.get("template_tap_retries", self.DEFAULT_TEMPLATE_RETRIES) or 0)
        home_ready_timeout_seconds = float(
            params.get("home_ready_timeout_seconds", self.DEFAULT_HOME_READY_TIMEOUT_SECONDS) or 0.0
        )
        cleanup_filename = str(params.get("cleanup_filename") or "").strip()
        if not cleanup_filename:
            task = context.get("task")
            evaluation = getattr(task, "evaluation", None)
            eval_params = getattr(evaluation, "params", None)
            if isinstance(eval_params, Mapping):
                cleanup_filename = str(eval_params.get("expected_filename") or "").strip()
        retries = max(1, min(retries, 5))

        if app_name != "libreoffice" or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.FAIL,
                message="LibreOffice prep requires params.app_name 'libreoffice' and controller.execute_adb",
                metadata={"app_name": app_name},
            )

        package = _LIBREOFFICE_PACKAGE
        activity = _LIBREOFFICE_ACTIVITY
        try:
            controller.execute_adb(["shell", "am", "force-stop", package])
            if cleanup_filename:
                self._remove_existing_output(controller, cleanup_filename)
            time.sleep(0.3)
            controller.execute_adb(
                ["shell", "am", "start", "-n", f"{package}/{activity}"],
            )
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to launch LibreOffice: {exc}",
                metadata={"app_name": app_name},
            )

        try:
            obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
            w = int(getattr(obs, "width", 0) or getattr(controller, "width", 0) or 1080)
            used_fallback = False
            success_opened_editor = False
            experimental_mode_trace: dict[str, Any] = {
                "attempted": False,
                "opened_settings": False,
                "already_enabled": False,
                "toggled": False,
                "returned_home": False,
            }
            tap_trace: list[dict[str, Any]] = []
            ready_deadline = time.time() + max(home_ready_timeout_seconds, 0.0)
            for attempt in range(retries):
                # Open FAB sheet only when it is not already open.
                if not _is_create_sheet_open(ui_nodes):
                    fab = _fab_node(ui_nodes)
                    if fab is None:
                        enabled, experimental_mode_trace = _ensure_experimental_mode_enabled(controller)
                        if enabled:
                            obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                            ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
                            w = int(getattr(obs, "width", 0) or getattr(controller, "width", 0) or w)
                            fab = _fab_node(ui_nodes)
                    while fab is None and time.time() < ready_deadline:
                        time.sleep(0.5)
                        obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                        ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
                        w = int(getattr(obs, "width", 0) or getattr(controller, "width", 0) or w)
                        if _is_create_sheet_open(ui_nodes):
                            break
                        fab = _fab_node(ui_nodes)
                    if fab is None and not _is_create_sheet_open(ui_nodes):
                        return InitResult(
                            status=InitStatus.FAIL,
                            message="LibreOffice prep: editFAB not found on home screen after waiting",
                            metadata={
                                "app_name": app_name,
                                "home_ready_timeout_seconds": home_ready_timeout_seconds,
                                "experimental_mode_trace": experimental_mode_trace,
                            },
                        )
                    if fab is not None and not _tap_node_center(controller, fab):
                        return InitResult(
                            status=InitStatus.FAIL,
                            message="LibreOffice prep: could not tap editFAB (missing bounds)",
                        )
                    if fab is not None:
                        tap_trace.append({"attempt": attempt + 1, "action": "tap_fab"})
                    if fab is not None and sheet_ms > 0:
                        time.sleep(sheet_ms / 1000.0)
                    if fab is not None:
                        obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                        ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
                        w = int(getattr(obs, "width", 0) or getattr(controller, "width", 0) or w)

                label = _best_new_text_document_node(ui_nodes)
                if label is not None:
                    _tap_new_text_icon_right(controller, label, w)
                    tap_trace.append({"attempt": attempt + 1, "action": "tap_text_doc_icon"})
                else:
                    used_fallback = True
                    h = int(getattr(obs, "height", 0) or getattr(controller, "height", 0) or 2400)
                    # Retry descending guesses around bottom template row (text-doc is lowest option).
                    y_fracs = (0.86, 0.83, 0.80, 0.78, 0.76)
                    y_frac = y_fracs[min(attempt, len(y_fracs) - 1)]
                    tx = max(100, int(w * 0.88))
                    ty = max(200, int(h * y_frac))
                    controller.tap(tx, ty)
                    tap_trace.append(
                        {
                            "attempt": attempt + 1,
                            "action": "tap_fallback_template_guess",
                            "x": tx,
                            "y": ty,
                            "y_frac": y_frac,
                        }
                    )

                if after_ms > 0:
                    time.sleep(after_ms / 1000.0)

                obs = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                ui_nodes = list(getattr(obs, "ui_nodes", None) or [])
                if not _looks_like_home(ui_nodes):
                    success_opened_editor = True
                    break

            if not success_opened_editor:
                return InitResult(
                    status=InitStatus.FAIL,
                    message="LibreOffice prep: still on home screen after template taps; not entering editor",
                    metadata={
                        "app_name": app_name,
                        "used_fallback_template_tap": used_fallback,
                        "template_tap_retries": retries,
                        "tap_trace": tap_trace,
                    },
                )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"LibreOffice prep UI automation failed: {exc}",
                metadata={"app_name": app_name},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="LibreOffice: launched, create sheet, opened New Text Document template",
            metadata={
                "app_name": app_name,
                "used_fallback_template_tap": used_fallback,
                "template_tap_retries": retries,
                "tap_trace": tap_trace,
                "experimental_mode_trace": experimental_mode_trace,
            },
        )

    @staticmethod
    def _remove_existing_output(controller: Any, filename: str) -> None:
        safe_name = filename.replace("'", "'\\''")
        for base in _DEFAULT_CLEANUP_DIRS:
            controller.execute_adb(["shell", "rm", "-f", f"{base.rstrip('/')}/{filename}"])
        controller.execute_adb(
            [
                "shell",
                "sh",
                "-c",
                f"find /sdcard -type f -name '{safe_name}' -delete 2>/dev/null",
            ]
        )
