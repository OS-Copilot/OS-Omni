"""Reusable Android UI bootstrap helpers and communication-app onboarding."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from platforms.android.apk_cache import ensure_package_installed_from_cache
from platforms.android.controller import AdbController


Selector = Mapping[str, Any]


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() == "true"


def _normalize_string(value: Any) -> str:
    return str(value or "").strip()


def _iter_expected_values(expected: Any) -> list[str]:
    if isinstance(expected, (list, tuple, set)):
        return [_normalize_string(item) for item in expected]
    return [_normalize_string(expected)]


def node_matches_selector(node: Mapping[str, Any], selector: Selector) -> bool:
    resource_id = _normalize_string(selector.get("resource_id"))
    if resource_id and _normalize_string(node.get("resource_id")) != resource_id:
        return False

    text = selector.get("text")
    if text not in (None, ""):
        actual_text = _normalize_string(node.get("text"))
        if actual_text not in _iter_expected_values(text):
            return False

    text_contains = selector.get("text_contains")
    if text_contains not in (None, ""):
        actual_text = _normalize_string(node.get("text"))
        expected_values = _iter_expected_values(text_contains)
        if not any(expected in actual_text for expected in expected_values):
            return False

    content_description = selector.get("content_description")
    if content_description not in (None, ""):
        actual_desc = _normalize_string(node.get("content_description") or node.get("content-desc"))
        if actual_desc not in _iter_expected_values(content_description):
            return False

    class_name = _normalize_string(selector.get("class_name") or selector.get("class"))
    if class_name and _normalize_string(node.get("class")) != class_name:
        return False

    package = _normalize_string(selector.get("package"))
    if package and _normalize_string(node.get("package")) != package:
        return False

    for bool_key in ("focused", "clickable", "enabled", "scrollable", "password"):
        if bool_key in selector and _normalize_bool(node.get(bool_key)) != bool(selector.get(bool_key)):
            return False

    return True


def _selector_label(selector: Selector) -> str:
    for key in ("resource_id", "text", "text_contains", "content_description", "class_name"):
        value = selector.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    return json.dumps(dict(selector), ensure_ascii=False, sort_keys=True)


class AndroidBootstrapDriver:
    """UI-tree driven helper for deterministic Android onboarding flows."""

    def __init__(
        self,
        controller: AdbController,
        *,
        settle_delay_seconds: float = 0.4,
        poll_interval_seconds: float = 0.5,
        expected_package: str | None = None,
    ) -> None:
        self.controller = controller
        self.settle_delay_seconds = settle_delay_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.expected_package = expected_package

    def observe(self):
        return self.controller.observe(include_ui_tree=True, include_screenshot_data=False)

    def observe_nodes(self) -> list[dict[str, Any]]:
        observation = self.observe()
        return list(observation.ui_nodes or [])

    def find_node(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        nodes: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        selector_list = self._normalize_selectors(selectors)
        candidate_nodes = list(nodes) if nodes is not None else self.observe_nodes()
        for selector in selector_list:
            for node in candidate_nodes:
                if node_matches_selector(node, selector):
                    return dict(node)
        return None

    def node_exists(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        timeout_seconds: float = 0.0,
    ) -> bool:
        return self.wait_for_node(selectors, timeout_seconds=timeout_seconds, raise_on_timeout=False) is not None

    def wait_for_node(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        timeout_seconds: float = 10.0,
        raise_on_timeout: bool = True,
    ) -> dict[str, Any] | None:
        deadline = time.time() + max(timeout_seconds, 0.0)
        selector_list = self._normalize_selectors(selectors)
        while True:
            observation = self.observe()
            nodes = list(observation.ui_nodes or [])
            node = self.find_node(selector_list, nodes=nodes)
            if node is not None:
                return node
            if self._recover_expected_app(_normalize_string(observation.foreground_bundle_id)):
                continue
            if self._recover_from_nodes(nodes):
                continue
            if time.time() >= deadline:
                if not raise_on_timeout:
                    return None
                raise RuntimeError(
                    "Timed out waiting for node "
                    f"{self._selector_list_label(selector_list)}.\nVisible nodes:\n{self.summarize_nodes(nodes)}"
                )
            time.sleep(self.poll_interval_seconds)

    def wait_for_absent(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        deadline = time.time() + max(timeout_seconds, 0.0)
        selector_list = self._normalize_selectors(selectors)
        while True:
            observation = self.observe()
            nodes = list(observation.ui_nodes or [])
            node = self.find_node(selector_list, nodes=nodes)
            if node is None:
                return
            if self._recover_expected_app(_normalize_string(observation.foreground_bundle_id)):
                continue
            if self._recover_from_nodes(nodes):
                continue
            if time.time() >= deadline:
                raise RuntimeError(
                    "Timed out waiting for node to disappear "
                    f"{self._selector_list_label(selector_list)}.\nVisible nodes:\n{self.summarize_nodes(nodes)}"
                )
            time.sleep(self.poll_interval_seconds)

    def tap_selector(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        node = self.wait_for_node(selectors, timeout_seconds=timeout_seconds)
        x, y = self._tap_point_for_node(node)
        self.controller.tap(x, y)
        time.sleep(self.settle_delay_seconds)
        return node

    def tap_if_present(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        timeout_seconds: float = 1.0,
    ) -> bool:
        node = self.wait_for_node(selectors, timeout_seconds=timeout_seconds, raise_on_timeout=False)
        if node is None:
            return False
        tap = node.get("tap")
        if not isinstance(tap, Mapping):
            return False
        self.controller.tap(int(tap["x"]), int(tap["y"]))
        time.sleep(self.settle_delay_seconds)
        return True

    def focus_selector(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        timeout_seconds: float = 10.0,
        retries: int = 3,
    ) -> dict[str, Any]:
        selector_list = self._normalize_selectors(selectors)
        deadline = time.time() + max(timeout_seconds, 0.0)
        last_error: str | None = None
        for _attempt in range(retries):
            node = self.wait_for_node(selector_list, timeout_seconds=max(deadline - time.time(), 0.0))
            if _normalize_bool(node.get("focused")):
                return node

            x, y = self._tap_point_for_node(node, prefer_text_cursor_end=True)
            self.controller.tap(x, y)
            time.sleep(self.settle_delay_seconds)

            focused_node = self.wait_for_node(
                [dict(selector, focused=True) for selector in selector_list],
                timeout_seconds=min(2.0, max(deadline - time.time(), 0.0)),
                raise_on_timeout=False,
            )
            if focused_node is not None:
                return focused_node
            last_error = self.summarize_nodes(self.observe_nodes())

        raise RuntimeError(
            "Failed to focus node "
            f"{self._selector_list_label(selector_list)}.\nVisible nodes:\n{last_error or self.summarize_nodes(self.observe_nodes())}"
        )

    def replace_text(
        self,
        selectors: Selector | Sequence[Selector],
        text: str,
        *,
        timeout_seconds: float = 10.0,
        verify: bool = True,
        expected_text: str | None = None,
        clear_key_presses: int = 32,
        retries: int = 3,
        visible_node: Mapping[str, Any] | None = None,
        move_cursor_end_before_clear: bool = False,
    ) -> dict[str, Any]:
        selector_list = self._normalize_selectors(selectors)
        expected_value = text if expected_text is None else expected_text
        last_actual = ""
        for _attempt in range(retries):
            if visible_node is not None:
                x, y = self._tap_point_for_node(visible_node, prefer_text_cursor_end=True)
                self.controller.tap(x, y)
                time.sleep(self.settle_delay_seconds)
                focused_node = self.wait_for_node(
                    [dict(selector, focused=True) for selector in selector_list],
                    timeout_seconds=1.5,
                    raise_on_timeout=False,
                )
                if focused_node is None:
                    self.controller.tap(x, y)
                    time.sleep(self.settle_delay_seconds)
            else:
                self.focus_selector(selector_list, timeout_seconds=timeout_seconds)
            if move_cursor_end_before_clear:
                self.controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_MOVE_END"])
                time.sleep(0.1)
            self.controller.execute_adb(["shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A"])
            time.sleep(0.1)
            self._repeat_key("KEYCODE_DEL", clear_key_presses)
            self.controller.input_text(text)
            time.sleep(self.settle_delay_seconds + 0.2)
            node = self.wait_for_node(selector_list, timeout_seconds=2.0, raise_on_timeout=False)
            if node is None or not verify:
                return dict(node or {})
            actual_text = _normalize_string(node.get("text"))
            last_actual = actual_text
            if actual_text == expected_value:
                return node
        raise RuntimeError(
            "Failed to set text for "
            f"{self._selector_list_label(selector_list)}; expected={expected_value!r}, actual={last_actual!r}"
        )

    def choose_spinner_option(
        self,
        spinner_selectors: Selector | Sequence[Selector],
        option_selectors: Selector | Sequence[Selector],
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.tap_selector(spinner_selectors, timeout_seconds=timeout_seconds)
        self.tap_selector(option_selectors, timeout_seconds=timeout_seconds)

    def find_labeled_node(
        self,
        label_selectors: Selector | Sequence[Selector],
        *,
        target_class_name: str = "android.widget.EditText",
        timeout_seconds: float = 10.0,
        raise_on_timeout: bool = True,
    ) -> dict[str, Any] | None:
        deadline = time.time() + max(timeout_seconds, 0.0)
        selector_list = self._normalize_selectors(label_selectors)
        while True:
            observation = self.observe()
            nodes = list(observation.ui_nodes or [])
            label_node = self.find_node(selector_list, nodes=nodes)
            if label_node is not None:
                target_node = self._find_label_anchored_node(
                    nodes,
                    label_node,
                    target_class_name=target_class_name,
                )
                if target_node is not None:
                    return target_node
            if self._recover_expected_app(_normalize_string(observation.foreground_bundle_id)):
                continue
            if self._recover_from_nodes(nodes):
                continue
            if time.time() >= deadline:
                if not raise_on_timeout:
                    return None
                raise RuntimeError(
                    "Timed out waiting for node anchored to label "
                    f"{self._selector_list_label(selector_list)}.\nVisible nodes:\n{self.summarize_nodes(nodes)}"
                )
            time.sleep(self.poll_interval_seconds)

    def tap_labeled_node(
        self,
        label_selectors: Selector | Sequence[Selector],
        *,
        target_class_name: str = "android.widget.EditText",
        timeout_seconds: float = 10.0,
        prefer_text_cursor_end: bool = False,
    ) -> dict[str, Any]:
        node = self.find_labeled_node(
            label_selectors,
            target_class_name=target_class_name,
            timeout_seconds=timeout_seconds,
        )
        assert node is not None
        x, y = self._tap_point_for_node(node, prefer_text_cursor_end=prefer_text_cursor_end)
        self.controller.tap(x, y)
        time.sleep(self.settle_delay_seconds)
        return node

    def replace_labeled_text(
        self,
        label_selectors: Selector | Sequence[Selector],
        text: str,
        *,
        timeout_seconds: float = 10.0,
        verify: bool = True,
        expected_text: str | None = None,
        clear_key_presses: int = 32,
        retries: int = 3,
        target_class_name: str = "android.widget.EditText",
        move_cursor_end_before_clear: bool = False,
        prefer_text_cursor_end: bool = False,
    ) -> dict[str, Any]:
        selector_list = self._normalize_selectors(label_selectors)
        expected_value = text if expected_text is None else expected_text
        last_actual = ""
        for _attempt in range(retries):
            node = self.find_labeled_node(
                selector_list,
                target_class_name=target_class_name,
                timeout_seconds=timeout_seconds,
            )
            assert node is not None
            x, y = self._tap_point_for_node(node, prefer_text_cursor_end=prefer_text_cursor_end)
            self.controller.tap(x, y)
            time.sleep(self.settle_delay_seconds)
            focused_node = self.find_labeled_node(
                selector_list,
                target_class_name=target_class_name,
                timeout_seconds=2.0,
                raise_on_timeout=False,
            )
            if focused_node is None or not _normalize_bool(focused_node.get("focused")):
                fx, fy = self._tap_point_for_node(node, prefer_text_cursor_end=True)
                self.controller.tap(fx, fy)
                time.sleep(self.settle_delay_seconds)
            if move_cursor_end_before_clear:
                self.controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_MOVE_END"])
                time.sleep(0.1)
            self.controller.execute_adb(["shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A"])
            time.sleep(0.1)
            self._repeat_key("KEYCODE_DEL", clear_key_presses)
            self.controller.input_text(text)
            time.sleep(self.settle_delay_seconds + 0.2)
            node = self.find_labeled_node(
                selector_list,
                target_class_name=target_class_name,
                timeout_seconds=2.0,
                raise_on_timeout=False,
            )
            if node is None or not verify:
                return dict(node or {})
            actual_text = _normalize_string(node.get("text"))
            last_actual = actual_text
            if actual_text == expected_value:
                return node
        raise RuntimeError(
            "Failed to set text for label "
            f"{self._selector_list_label(selector_list)}; expected={expected_value!r}, actual={last_actual!r}"
        )

    def choose_labeled_spinner_option(
        self,
        label_selectors: Selector | Sequence[Selector],
        option_selectors: Selector | Sequence[Selector],
        *,
        target_class_name: str = "android.widget.EditText",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.tap_labeled_node(
            label_selectors,
            target_class_name=target_class_name,
            timeout_seconds=timeout_seconds,
            prefer_text_cursor_end=False,
        )
        self.tap_selector(option_selectors, timeout_seconds=timeout_seconds)

    def tap_below_node(
        self,
        node: Mapping[str, Any],
        *,
        y_offset: int,
        timeout_seconds: float = 1.0,
    ) -> None:
        rect = node.get("rect")
        if not isinstance(rect, Mapping):
            raise RuntimeError(f"Node is missing rect data: {node}")
        x = int(rect.get("x", 0)) + int(rect.get("w", 0)) // 2
        y = int(rect.get("y", 0)) + int(rect.get("h", 0)) + y_offset
        y = max(0, min(self.controller.height - 1, y))
        self.controller.tap(x, y)
        time.sleep(max(timeout_seconds, self.settle_delay_seconds))

    def scroll_until_visible(
        self,
        selectors: Selector | Sequence[Selector],
        *,
        max_swipes: int = 5,
        timeout_seconds: float = 1.0,
    ) -> dict[str, Any]:
        for _attempt in range(max_swipes + 1):
            observation = self.observe()
            nodes = list(observation.ui_nodes or [])
            node = self.find_node(selectors, nodes=nodes)
            if node is not None:
                if self._input_method_visible(nodes):
                    self.controller.press_back()
                    time.sleep(self.settle_delay_seconds + 0.2)
                    refreshed_node = self.wait_for_node(selectors, timeout_seconds=timeout_seconds, raise_on_timeout=False)
                    if refreshed_node is not None:
                        return refreshed_node
                return node
            self.controller.swipe(
                self.controller.width // 2,
                int(self.controller.height * 0.66),
                self.controller.width // 2,
                int(self.controller.height * 0.36),
                250,
            )
            time.sleep(self.settle_delay_seconds + 0.2)
        raise RuntimeError(f"Failed to reveal node {self._selector_list_label(self._normalize_selectors(selectors))}")

    def summarize_nodes(self, nodes: Sequence[Mapping[str, Any]], *, limit: int = 15) -> str:
        lines: list[str] = []
        for node in list(nodes)[:limit]:
            bits = []
            for key in ("resource_id", "text", "content_description", "class"):
                value = _normalize_string(node.get(key))
                if value:
                    bits.append(f"{key}={value}")
            if _normalize_bool(node.get("focused")):
                bits.append("focused=true")
            if _normalize_bool(node.get("clickable")):
                bits.append("clickable=true")
            if bits:
                lines.append(" | ".join(bits))
        return "\n".join(lines) if lines else "<no visible nodes>"

    @staticmethod
    def _normalize_selectors(selectors: Selector | Sequence[Selector]) -> list[Selector]:
        if isinstance(selectors, Mapping):
            return [selectors]
        return list(selectors)

    @staticmethod
    def _selector_list_label(selectors: Sequence[Selector]) -> str:
        return " or ".join(_selector_label(selector) for selector in selectors)

    def _repeat_key(self, keycode: str, times: int) -> None:
        if times <= 0:
            return
        for _ in range(times):
            self.controller.execute_adb(["shell", "input", "keyevent", keycode])

    def _recover_expected_app(self, foreground_package: str) -> bool:
        if not self.expected_package:
            return False
        if not foreground_package or foreground_package == self.expected_package:
            return False
        if foreground_package == "com.android.systemui":
            self._collapse_system_ui()
            return True
        if foreground_package in {"com.android.permissioncontroller", "com.google.android.permissioncontroller", "android"}:
            return False
        if foreground_package == "com.android.launcher3":
            self.controller.press_back()
            time.sleep(self.settle_delay_seconds + 0.2)
            return True
        return False

    def _recover_from_nodes(self, nodes: Sequence[Mapping[str, Any]]) -> bool:
        if not self.expected_package:
            return False
        system_dialog = self._find_system_dialog_button(nodes)
        if system_dialog is not None:
            x, y = self._tap_point_for_node(system_dialog)
            self.controller.tap(x, y)
            time.sleep(self.settle_delay_seconds + 0.4)
            return True
        if any(_normalize_string(node.get("package")) == "com.android.systemui" for node in nodes):
            self._collapse_system_ui()
            return True
        if any(_normalize_string(node.get("package")) == "com.google.android.inputmethod.latin" for node in nodes):
            self.controller.press_back()
            time.sleep(self.settle_delay_seconds + 0.2)
            return True
        launcher_nodes = [node for node in nodes if _normalize_string(node.get("package")) == "com.android.launcher3"]
        if not launcher_nodes:
            return False
        if any(
            _normalize_string(node.get("resource_id"))
            in {
                "com.android.launcher3:id/overview_panel",
                "com.android.launcher3:id/apps_view",
                "com.android.launcher3:id/apps_list_view",
            }
            for node in launcher_nodes
        ):
            self.controller.press_back()
            time.sleep(self.settle_delay_seconds + 0.2)
            return True
        return False

    @staticmethod
    def _find_system_dialog_button(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
        preferred_resource_ids = {
            "android:id/aerr_wait",
            "android:id/aerr_close",
            "android:id/close_app",
        }
        preferred_texts = {"Wait", "Close app", "OK"}
        for node in nodes:
            if _normalize_string(node.get("resource_id")) in preferred_resource_ids:
                return dict(node)
        for node in nodes:
            if _normalize_string(node.get("text")) in preferred_texts:
                return dict(node)
        return None

    def _collapse_system_ui(self) -> None:
        try:
            self.controller.execute_adb(["shell", "cmd", "statusbar", "collapse"])
        except Exception:
            pass
        try:
            self.controller.press_back()
        except Exception:
            pass
        time.sleep(self.settle_delay_seconds + 0.2)

    @staticmethod
    def _input_method_visible(nodes: Sequence[Mapping[str, Any]]) -> bool:
        return any(_normalize_string(node.get("package")) == "com.google.android.inputmethod.latin" for node in nodes)

    @staticmethod
    def _tap_point_for_node(
        node: Mapping[str, Any],
        *,
        prefer_text_cursor_end: bool = False,
    ) -> tuple[int, int]:
        rect = node.get("rect")
        if isinstance(rect, Mapping):
            x = int(rect.get("x", 0))
            y = int(rect.get("y", 0))
            w = int(rect.get("w", 0))
            h = int(rect.get("h", 0))
            if w > 0 and h > 0:
                center_y = y + h // 2
                class_name = _normalize_string(node.get("class"))
                if prefer_text_cursor_end or class_name.endswith("EditText"):
                    text_value = _normalize_string(node.get("text"))
                    hint_value = _normalize_string(node.get("hint"))
                    if text_value and hint_value and text_value == hint_value:
                        return x + w // 2, center_y
                    return x + max(int(w * 0.88), w // 2), center_y
                return x + w // 2, center_y
        tap = node.get("tap")
        if isinstance(tap, Mapping):
            return int(tap["x"]), int(tap["y"])
        raise RuntimeError(f"Node is missing tap coordinates: {node}")

    @staticmethod
    def _find_label_anchored_node(
        nodes: Sequence[Mapping[str, Any]],
        label_node: Mapping[str, Any],
        *,
        target_class_name: str,
    ) -> dict[str, Any] | None:
        label_rect = label_node.get("rect")
        if not isinstance(label_rect, Mapping):
            return None
        label_center_x = int(label_rect.get("x", 0)) + int(label_rect.get("w", 0)) // 2
        label_center_y = int(label_rect.get("y", 0)) + int(label_rect.get("h", 0)) // 2
        strict_candidates: list[tuple[int, dict[str, Any]]] = []
        fallback_candidates: list[tuple[int, dict[str, Any]]] = []
        for node in nodes:
            if _normalize_string(node.get("class")) != target_class_name:
                continue
            rect = node.get("rect")
            if not isinstance(rect, Mapping):
                continue
            x = int(rect.get("x", 0))
            y = int(rect.get("y", 0))
            w = int(rect.get("w", 0))
            h = int(rect.get("h", 0))
            if w <= 0 or h <= 0:
                continue
            center_y = y + h // 2
            score = abs(center_y - label_center_y)
            candidate = dict(node)
            if x <= label_center_x <= x + w and y <= label_center_y <= y + h:
                strict_candidates.append((score, candidate))
                continue
            if x <= label_center_x <= x + w and abs(center_y - label_center_y) <= max(h, 120):
                fallback_candidates.append((score, candidate))
        if strict_candidates:
            strict_candidates.sort(key=lambda item: item[0])
            return strict_candidates[0][1]
        if fallback_candidates:
            fallback_candidates.sort(key=lambda item: item[0])
            return fallback_candidates[0][1]
        return None


@dataclass
class DeltaChatBootstrapConfig:
    profile_name: str = "BenchSender"
    email: str = "benchsender@example.test"
    password: str = "benchpass"
    imap_login: str = "benchsender@example.test"
    imap_server: str = "10.0.2.2"
    imap_port: str = "3143"
    imap_security: str = "Off"
    smtp_login: str = "benchsender@example.test"
    smtp_password: str = "benchpass"
    smtp_server: str = "10.0.2.2"
    smtp_port: str = "3025"
    smtp_security: str = "Off"
    api_base_url: str = "http://127.0.0.1:8081"
    clear_app_data: bool = False
    wait_after_submit_seconds: float = 8.0


def _ensure_package_installed(controller: AdbController, package_name: str, *, label: str) -> None:
    ensure_package_installed_from_cache(controller, package_name, label=label)


def _ensure_greenmail_ready(api_base_url: str) -> None:
    request = Request(f"{api_base_url.rstrip('/')}/api/service/readiness", method="GET")
    try:
        with urlopen(request, timeout=5.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GreenMail readiness check failed: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("message") != "Service running":
        raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")


class DeltaChatBootstrapper:
    """Automate the first-time Delta Chat Classic Email onboarding flow."""

    APP_PACKAGE = "chat.delta"
    APP_ACTIVITY = "org.thoughtcrime.securesms.RoutingActivity"

    def __init__(
        self,
        controller: AdbController,
        config: DeltaChatBootstrapConfig,
        *,
        driver_factory: Callable[[AdbController], AndroidBootstrapDriver] = AndroidBootstrapDriver,
    ) -> None:
        self.controller = controller
        self.config = config
        self.driver = driver_factory(controller)
        if hasattr(self.driver, "expected_package"):
            setattr(self.driver, "expected_package", self.APP_PACKAGE)

    def run(self) -> None:
        self._log("checking GreenMail readiness")
        _ensure_greenmail_ready(self.config.api_base_url)
        self._log("checking app installation")
        _ensure_package_installed(self.controller, self.APP_PACKAGE, label="Delta Chat")
        if self.config.clear_app_data:
            self._log("clearing app data")
            self.controller.execute_adb(["shell", "pm", "clear", self.APP_PACKAGE])
        self._log("launching Delta Chat")
        self.controller.execute_adb(["shell", "am", "force-stop", self.APP_PACKAGE])
        self.controller.execute_adb(["shell", "am", "start", "-n", f"{self.APP_PACKAGE}/{self.APP_ACTIVITY}"])
        time.sleep(1.2)

        if self.driver.node_exists({"resource_id": "chat.delta:id/signup_button", "text": "CREATE NEW PROFILE"}, timeout_seconds=3.0):
            self._log("opening create-profile flow")
            self.driver.tap_selector({"resource_id": "chat.delta:id/signup_button"})

        if self.driver.node_exists({"resource_id": "chat.delta:id/name_text"}, timeout_seconds=3.0):
            self._log("setting profile name")
            self.driver.replace_text({"resource_id": "chat.delta:id/name_text"}, self.config.profile_name)
            self.driver.tap_selector({"resource_id": "chat.delta:id/other_options_button"})

        if self.driver.node_exists({"resource_id": "chat.delta:id/login_button"}, timeout_seconds=3.0):
            self._log("choosing classic email relay")
            self.driver.tap_selector({"resource_id": "chat.delta:id/login_button"})

        self._log("filling basic relay credentials")
        self.driver.wait_for_node({"resource_id": "chat.delta:id/email_text"}, timeout_seconds=8.0)
        self.driver.replace_text({"resource_id": "chat.delta:id/email_text"}, self.config.email)
        self.driver.replace_text(
            {"resource_id": "chat.delta:id/password_text"},
            self.config.password,
            verify=False,
        )

        if not self.driver.node_exists({"resource_id": "chat.delta:id/imap_login_text"}, timeout_seconds=1.0):
            self._log("expanding advanced relay options")
            self.driver.tap_selector({"resource_id": "chat.delta:id/advanced_text"})

        self._log("filling IMAP settings")
        self.driver.scroll_until_visible({"resource_id": "chat.delta:id/imap_login_text"})
        imap_login_node = self.driver.scroll_until_visible({"resource_id": "chat.delta:id/imap_login_text"})
        self.driver.replace_text(
            {"resource_id": "chat.delta:id/imap_login_text"},
            self.config.imap_login,
            visible_node=imap_login_node,
        )
        imap_server_node = self.driver.scroll_until_visible({"resource_id": "chat.delta:id/imap_server_text"})
        self.driver.replace_text(
            {"resource_id": "chat.delta:id/imap_server_text"},
            self.config.imap_server,
            visible_node=imap_server_node,
        )
        self._replace_next_focused_text_field(self.config.imap_port)
        self._trim_field_to_text({"resource_id": "chat.delta:id/imap_port_text"}, self.config.imap_port)
        self.controller.press_back()
        time.sleep(getattr(self.driver, "settle_delay_seconds", 0.4) + 0.2)
        self.driver.scroll_until_visible({"resource_id": "chat.delta:id/imap_security"})
        self.driver.choose_spinner_option(
            {"resource_id": "chat.delta:id/imap_security"},
            {"text": self.config.imap_security, "class_name": "android.widget.TextView"},
        )

        self._log("filling SMTP settings")
        smtp_login_node = self.driver.scroll_until_visible({"resource_id": "chat.delta:id/smtp_login_text"})
        self.driver.replace_text(
            {"resource_id": "chat.delta:id/smtp_login_text"},
            self.config.smtp_login,
            visible_node=smtp_login_node,
        )
        smtp_password_node = self.driver.scroll_until_visible({"resource_id": "chat.delta:id/smtp_password_text"})
        self.driver.replace_text(
            {"resource_id": "chat.delta:id/smtp_password_text"},
            self.config.smtp_password,
            verify=False,
            visible_node=smtp_password_node,
        )
        self._replace_next_focused_text_field(self.config.smtp_server)
        smtp_port_node = self.driver.scroll_until_visible({"resource_id": "chat.delta:id/smtp_port_text"})
        smtp_port_rect = smtp_port_node.get("rect")
        if isinstance(smtp_port_rect, Mapping) and int(smtp_port_rect.get("y", 0)) > int(self.controller.height * 0.78):
            self._log("lifting the SMTP port field away from the bottom navigation area")
            self.controller.swipe(
                self.controller.width // 2,
                int(self.controller.height * 0.62),
                self.controller.width // 2,
                int(self.controller.height * 0.28),
                220,
            )
            time.sleep(getattr(self.driver, "settle_delay_seconds", 0.4) + 0.2)
            smtp_port_node = self.driver.wait_for_node({"resource_id": "chat.delta:id/smtp_port_text"}, timeout_seconds=5.0)
        self._replace_next_focused_text_field(self.config.smtp_port)
        self._trim_field_to_text({"resource_id": "chat.delta:id/smtp_port_text"}, self.config.smtp_port)
        self.controller.press_back()
        time.sleep(getattr(self.driver, "settle_delay_seconds", 0.4) + 0.2)
        self._log("revealing and selecting the SMTP security spinner")
        if not self.driver.node_exists({"resource_id": "chat.delta:id/smtp_security"}, timeout_seconds=2.0):
            self.controller.swipe(
                self.controller.width // 2,
                int(self.controller.height * 0.58),
                self.controller.width // 2,
                int(self.controller.height * 0.38),
                220,
            )
            time.sleep(getattr(self.driver, "settle_delay_seconds", 0.4) + 0.2)
        self.driver.scroll_until_visible({"resource_id": "chat.delta:id/smtp_security"}, max_swipes=2)
        self.driver.choose_spinner_option(
            {"resource_id": "chat.delta:id/smtp_security"},
            {"text": self.config.smtp_security, "class_name": "android.widget.TextView"},
        )

        self._log("submitting relay configuration")
        self.driver.tap_selector({"resource_id": "chat.delta:id/do_register"})
        self.driver.tap_if_present(
            [
                {"resource_id": "com.android.permissioncontroller:id/permission_allow_button"},
                {"resource_id": "com.android.permissioncontroller:id/permission_allow_foreground_only_button"},
                {"text": ["Allow", "ALLOW", "允许"]},
            ],
            timeout_seconds=6.0,
        )
        if self.config.wait_after_submit_seconds > 0:
            time.sleep(self.config.wait_after_submit_seconds)
        self._log("waiting for onboarding form to disappear")
        self.driver.wait_for_absent({"resource_id": "chat.delta:id/email_text"}, timeout_seconds=20.0)

    @staticmethod
    def _log(message: str) -> None:
        print(f"[DeltaChatBootstrap] {message}", flush=True)

    def _replace_next_focused_text_field(self, text: str) -> None:
        self.controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_TAB"])
        time.sleep(getattr(self.driver, "settle_delay_seconds", 0.4))
        self.driver.replace_text(
            {"class_name": "android.widget.EditText", "focused": True},
            text,
            verify=False,
            clear_key_presses=16,
            move_cursor_end_before_clear=True,
        )

    def _trim_field_to_text(self, selectors: Selector | Sequence[Selector], expected_text: str) -> None:
        node = self.driver.wait_for_node(selectors, timeout_seconds=3.0, raise_on_timeout=False)
        if node is None:
            return
        actual_text = _normalize_string(node.get("text"))
        if actual_text == expected_text:
            return
        if not actual_text.startswith(expected_text):
            return
        for _ in range(len(actual_text) - len(expected_text)):
            self.controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_DEL"])
            time.sleep(0.05)


@dataclass
class K9BootstrapConfig:
    email: str = "benchsender@example.test"
    username: str = "benchsender@example.test"
    password: str = "benchpass"
    incoming_server: str = "10.0.2.2"
    incoming_port: str = "3143"
    incoming_security: str = "None"
    outgoing_server: str = "10.0.2.2"
    outgoing_port: str = "3025"
    outgoing_security: str = "None"
    display_name: str = "BenchSender"
    api_base_url: str = "http://127.0.0.1:8081"
    clear_app_data: bool = False


class K9Bootstrapper:
    """Automate the first-time K-9 Mail account onboarding flow."""

    APP_PACKAGE = "com.fsck.k9"
    APP_ACTIVITY = "net.thunderbird.app.common.MainActivity"
    INBOX_MARKERS = (
        {"resource_id": "com.fsck.k9:id/toolbarTitle", "text": "Inbox"},
        {"resource_id": "com.fsck.k9:id/floating_action_button"},
    )

    def __init__(
        self,
        controller: AdbController,
        config: K9BootstrapConfig,
        *,
        driver_factory: Callable[[AdbController], AndroidBootstrapDriver] = AndroidBootstrapDriver,
    ) -> None:
        self.controller = controller
        self.config = config
        self.driver = driver_factory(controller)
        if hasattr(self.driver, "expected_package"):
            setattr(self.driver, "expected_package", self.APP_PACKAGE)

    def run(self) -> None:
        self._log("checking GreenMail readiness")
        _ensure_greenmail_ready(self.config.api_base_url)
        self._log("checking app installation")
        _ensure_package_installed(self.controller, self.APP_PACKAGE, label="K-9 Mail")
        if self.config.clear_app_data:
            self._log("clearing app data")
            self.controller.execute_adb(["shell", "pm", "clear", self.APP_PACKAGE])
        self._log("launching K-9 Mail")
        self.controller.execute_adb(["shell", "am", "force-stop", self.APP_PACKAGE])
        self.controller.execute_adb(["shell", "am", "start", "-n", f"{self.APP_PACKAGE}/{self.APP_ACTIVITY}"])
        time.sleep(1.2)

        if self.driver.node_exists(self.INBOX_MARKERS, timeout_seconds=3.0):
            self._log("account is already configured; K-9 is already in the inbox view")
            return

        self._log("starting the welcome flow")
        self.driver.tap_selector({"resource_id": "onboarding_welcome_start_button"}, timeout_seconds=8.0)

        self._log("entering the email address")
        self.driver.replace_labeled_text(
            {"text": "Email address"},
            self.config.email,
            clear_key_presses=64,
            move_cursor_end_before_clear=True,
        )
        self._tap_next()
        self._log("waiting for the manual configuration entry point")
        self.driver.tap_selector({"text": "Configure manually"}, timeout_seconds=25.0)

        self._log("configuring incoming IMAP settings")
        self.driver.replace_labeled_text(
            {"text": "Server"},
            self.config.incoming_server,
            clear_key_presses=40,
            move_cursor_end_before_clear=True,
        )
        self.driver.choose_labeled_spinner_option(
            {"text": "Security"},
            {"text": self.config.incoming_security, "class_name": "android.widget.TextView"},
        )
        self.driver.replace_labeled_text(
            {"text": "Port"},
            self.config.incoming_port,
            clear_key_presses=8,
            move_cursor_end_before_clear=True,
        )
        self.driver.replace_labeled_text(
            {"text": "Username"},
            self.config.username,
            clear_key_presses=64,
            move_cursor_end_before_clear=True,
        )
        self._replace_next_focused_text_field(self.config.password)
        self._tap_next()

        self._log("configuring outgoing SMTP settings")
        self.driver.replace_labeled_text(
            {"text": "Server*"},
            self.config.outgoing_server,
            clear_key_presses=40,
            move_cursor_end_before_clear=True,
        )
        self.driver.choose_labeled_spinner_option(
            {"text": "Security"},
            {"text": self.config.outgoing_security, "class_name": "android.widget.TextView"},
        )
        self.driver.replace_labeled_text(
            {"text": "Port*"},
            self.config.outgoing_port,
            clear_key_presses=8,
            move_cursor_end_before_clear=True,
        )
        self.driver.replace_labeled_text(
            {"text": "Username*"},
            self.config.username,
            clear_key_presses=64,
            move_cursor_end_before_clear=True,
        )
        self._replace_next_focused_text_field(self.config.password)
        self._tap_next()

        self._log("keeping the default special-folder mapping")
        self._tap_next()

        self._log("setting the sender display name")
        self.driver.replace_labeled_text(
            {"text": "Your name*"},
            self.config.display_name,
            clear_key_presses=64,
            move_cursor_end_before_clear=True,
        )
        self._tap_next()

        self._log("keeping the default sync options")
        self._tap_next()

        if self.driver.node_exists({"resource_id": "onboarding_permissions_skip_button"}, timeout_seconds=6.0):
            self._log("skipping optional onboarding permissions")
            self.driver.tap_selector({"resource_id": "onboarding_permissions_skip_button"})

        self._log("waiting for the inbox view")
        self.driver.wait_for_node(self.INBOX_MARKERS, timeout_seconds=25.0)

    def _tap_next(self) -> None:
        self.driver.tap_selector(
            [
                {"resource_id": "account_setup_next_button"},
                {"text": "Next"},
            ],
            timeout_seconds=10.0,
        )

    def _replace_next_focused_text_field(self, text: str) -> None:
        self.controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_TAB"])
        time.sleep(getattr(self.driver, "settle_delay_seconds", 0.4))
        self.driver.replace_text(
            {"class_name": "android.widget.EditText", "focused": True},
            text,
            verify=False,
            clear_key_presses=64,
            move_cursor_end_before_clear=True,
        )

    @staticmethod
    def _log(message: str) -> None:
        print(f"[K9Bootstrap] {message}", flush=True)
