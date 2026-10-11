"""
Low-level Appium runtime operations for iOS simulator control.
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from appium import webdriver
from appium.options.ios import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

from . import simulator_manager

logger = logging.getLogger(__name__)


def get_device_capabilities(
    udid: Optional[str] = None,
    wda_local_port: Optional[int] = None,
    mjpeg_server_port: Optional[int] = None,
    derived_data_path: Optional[str] = None,
) -> dict:
    """Generate Appium capabilities for iOS Simulator."""
    if not udid:
        raise ValueError("Simulator UDID is required")

    caps = {
        "platformName": "iOS",
        "appium:automationName": "XCUITest",
        "appium:noReset": True,
        "appium:newCommandTimeout": 1200,
        "appium:udid": udid,
        "appium:usePrebuiltWDA": os.environ.get("OS_OMNI_WDA_USE_PREBUILT", "0").strip() == "1",
        "appium:useSimpleBuildTest": True,
        # A fresh per-run WDA build can exceed Appium's 60-second default
        # on Xcode 27. This startup budget does not change action timeouts
        # or any model step limit.
        "appium:wdaLaunchTimeout": 300000,
    }

    if wda_local_port is not None:
        caps["appium:wdaLocalPort"] = int(wda_local_port)
    if mjpeg_server_port is not None:
        caps["appium:mjpegServerPort"] = int(mjpeg_server_port)
    if derived_data_path:
        caps["appium:derivedDataPath"] = str(derived_data_path)

    return caps


class iOSRuntime:
    """
    Low-level runtime layer.

    Handles: Appium session lifecycle, gestures, system/app controls, screenshots,
    and raw device information queries.
    """

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:4723",
        options: Optional[XCUITestOptions] = None,
        screenshot_dir: str = "screenshot",
        default_timeout: int = 10,
        ui_summary_limit: int = 100,
        udid: Optional[str] = None,
        wda_local_port: Optional[int] = None,
        mjpeg_server_port: Optional[int] = None,
        derived_data_path: Optional[str] = None,
    ):
        self.udid = str(udid).strip() if udid is not None else None
        if options is None:
            device_caps = get_device_capabilities(
                udid=udid,
                wda_local_port=wda_local_port,
                mjpeg_server_port=mjpeg_server_port,
                derived_data_path=derived_data_path,
            )
            options = XCUITestOptions().load_capabilities(device_caps)

        self.device_type = "simulator"
        logger.info("Connecting to Appium at %s (device: simulator)...", server_url)
        self.server_url = server_url
        self.options = options
        self.default_timeout = int(default_timeout)
        self.ui_summary_limit = int(ui_summary_limit)
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self.driver = webdriver.Remote(server_url, options=options)
        logger.info("Connected.")

    # ---------- Session ----------

    def update_screenshot_dir(self, new_dir: str):
        self.screenshot_dir = Path(new_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def quit(self):
        if getattr(self, "driver", None):
            try:
                self.driver.quit()
            finally:
                self.driver = None

    # ---------- Basic info ----------

    def get_window_size(self) -> Dict[str, int]:
        s = self.driver.get_window_size()
        return {"width": int(s["width"]), "height": int(s["height"])}

    def get_viewport_rect(self) -> Dict[str, int]:
        raw = self.driver.execute_script("mobile: viewportRect", {})
        if not isinstance(raw, dict):
            return {}
        viewport: Dict[str, int] = {}
        for key in ("left", "top", "width", "height"):
            value = raw.get(key)
            if value is None:
                continue
            viewport[key] = int(value)
        return viewport

    def get_device_info(self) -> Dict[str, Any]:
        cached = getattr(self, "_cached_device_info", None)
        if isinstance(cached, dict):
            return dict(cached)

        raw = self.driver.execute_script("mobile: deviceInfo")
        li = (raw.get("lockdownInfo") or {}) if isinstance(raw, dict) else {}
        info = {
            "product_type": li.get("ProductType"),
            "product_version": li.get("ProductVersion"),
        }
        self._cached_device_info = info
        return dict(info)

    def is_keyboard_shown(self) -> bool:
        try:
            return bool(self.driver.execute_script("mobile: isKeyboardShown"))
        except Exception:
            return False

    # ---------- Element helpers ----------

    def find_element(self, locator: Tuple[str, str], timeout: Optional[int] = None, visible: bool = True):
        t = self.default_timeout if timeout is None else int(timeout)
        cond = EC.visibility_of_element_located(locator) if visible else EC.presence_of_element_located(locator)
        return WebDriverWait(self.driver, t).until(cond)

    def find_elements(self, locator: Tuple[str, str]):
        return self.driver.find_elements(*locator)

    def get_node_by_id(self, ui_nodes: List[Dict[str, Any]], node_id: str) -> Optional[Dict[str, Any]]:
        node_id = node_id.strip()
        for node in ui_nodes:
            if node.get("id", "").strip() == node_id:
                return node
        return None

    def _get_node_coords(self, node: Dict[str, Any]) -> Tuple[int, int]:
        if node.get("tap_norm"):
            return self._norm_to_px(node["tap_norm"][0], node["tap_norm"][1])
        if node.get("tap"):
            return int(node["tap"][0]), int(node["tap"][1])
        if node.get("rect"):
            rect = node["rect"]
            return int(rect["x"] + rect["w"] / 2), int(rect["y"] + rect["h"] / 2)
        raise ValueError(f"Cannot determine coordinates for node: {node.get('id')}")

    def _parse_target(self, target: Any, ui_nodes: List[Dict[str, Any]]) -> Tuple[int, int]:
        if isinstance(target, (list, tuple)) and len(target) == 2:
            return int(target[0]), int(target[1])

        if isinstance(target, dict) and "x" in target and "y" in target:
            return self._norm_to_px(float(target["x"]), float(target["y"]))

        if isinstance(target, str):
            node = self.get_node_by_id(ui_nodes, target)
            if node is None:
                raise ValueError(f"Node not found: {target}")
            return self._get_node_coords(node)

        raise ValueError(f"Invalid target format: {target}")

    def parse_target(self, target: Any, ui_nodes: List[Dict[str, Any]]) -> Tuple[int, int]:
        """Public target parser for action engine."""
        return self._parse_target(target, ui_nodes)

    # ---------- Text / clipboard ----------

    def type_text(
        self,
        text: str,
        clear_first: bool = False,
        *,
        timeout_seconds: float = 3.0,
        retry_interval_seconds: float = 0.2,
    ):
        """Type text into the current focused element, waiting for WDA focus readiness.

        iOS can show the software keyboard before WebDriverAgent exposes a stable
        active element, especially while Safari is expanding the address/search
        field. A short retry loop avoids surfacing transient WDA 404
        NoSuchElement errors to the agent.
        """
        deadline = time.time() + max(float(timeout_seconds), 0.0)
        last_error: Exception | None = None
        attempts = 0

        while True:
            attempts += 1
            try:
                el = self.driver.switch_to.active_element
                if clear_first:
                    try:
                        el.clear()
                    except Exception:
                        pass
                el.send_keys(text)
                if attempts > 1:
                    logger.debug("type_text succeeded after %d active-element attempts", attempts)
                return el
            except (NoSuchElementException, WebDriverException) as exc:
                last_error = exc
                if time.time() >= deadline:
                    break
                time.sleep(max(float(retry_interval_seconds), 0.05))

        raise last_error  # type: ignore[misc]

    def set_clipboard_text(self, text: str):
        self.driver.set_clipboard_text(text)

    def get_clipboard_text(self) -> str:
        try:
            return self.driver.get_clipboard_text()
        except Exception:
            return ""

    def paste(self):
        return self._mobile("mobile: paste", {})

    # ---------- Coordinates ----------

    def _norm_to_px(self, x: float, y: float) -> Tuple[int, int]:
        size = self.get_window_size()
        return int(x * size["width"]), int(y * size["height"])

    # ---------- Gestures ----------

    def _mobile(self, script: str, args: Dict[str, Any]):
        try:
            return self.driver.execute_script(script, args)
        except WebDriverException as e:
            raise WebDriverException(f"{script} failed: {e}") from e

    def mobile_exec(self, script: str, args: Dict[str, Any]):
        """Public mobile script executor."""
        return self._mobile(script, args)

    def tap_node(self, node_id: str, ui_nodes: List[Dict[str, Any]], timeout: float = 2.0):
        node = self.get_node_by_id(ui_nodes, node_id)
        if node is None:
            raise ValueError(f"Node not found: {node_id}")

        selector = (node.get("selector") or "").strip()
        if selector:
            try:
                el = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, selector))
                )
                el.click()
                return
            except (TimeoutException, WebDriverException):
                pass

        x, y = self._get_node_coords(node)
        self.tap_px(x, y)

    def tap_px(self, x: int, y: int):
        return self._mobile("mobile: tap", {"x": int(x), "y": int(y)})

    def tap_norm(self, x: float, y: float):
        x_px, y_px = self._norm_to_px(x, y)
        return self.tap_px(x_px, y_px)

    def double_tap_node(self, node_id: str, ui_nodes: List[Dict[str, Any]]):
        node = self.get_node_by_id(ui_nodes, node_id)
        if node is None:
            raise ValueError(f"Node not found: {node_id}")
        x, y = self._get_node_coords(node)
        return self._mobile("mobile: doubleTap", {"x": x, "y": y})

    def double_tap_px(self, x: int, y: int):
        return self._mobile("mobile: doubleTap", {"x": int(x), "y": int(y)})

    def long_press_node(self, node_id: str, ui_nodes: List[Dict[str, Any]], duration_ms: int = 1000):
        node = self.get_node_by_id(ui_nodes, node_id)
        if node is None:
            raise ValueError(f"Node not found: {node_id}")
        x, y = self._get_node_coords(node)
        self._mobile("mobile: touchAndHold", {"x": x, "y": y, "duration": duration_ms / 1000.0})

    def long_press_px(self, x: int, y: int, duration: float = 1.0):
        return self._mobile("mobile: touchAndHold", {"x": int(x), "y": int(y), "duration": float(duration)})

    def drag_px(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_s: float = 0.6):
        return self._mobile(
            "mobile: dragFromToForDuration",
            {
                "fromX": int(start_x),
                "fromY": int(start_y),
                "toX": int(end_x),
                "toY": int(end_y),
                "duration": float(duration_s),
            },
        )

    def _compute_scroll_endpoints(self, direction: str, distance: float, center_x: int, center_y: int) -> tuple:
        size = self.get_window_size()
        width, height = size["width"], size["height"]
        scroll_dist = int(height * distance) if direction in ("up", "down") else int(width * distance)

        offsets = {
            "up": (0, scroll_dist // 2, 0, -scroll_dist // 2),
            "down": (0, -scroll_dist // 2, 0, scroll_dist // 2),
            "left": (scroll_dist // 2, 0, -scroll_dist // 2, 0),
            "right": (-scroll_dist // 2, 0, scroll_dist // 2, 0),
        }
        if direction not in offsets:
            raise ValueError(f"Invalid scroll direction: {direction}")

        dx1, dy1, dx2, dy2 = offsets[direction]
        return (center_x + dx1, center_y + dy1, center_x + dx2, center_y + dy2)

    def scroll_screen(
        self,
        direction: str,
        distance: float = 0.5,
        container_id: Optional[str] = None,
        ui_nodes: Optional[List[Dict[str, Any]]] = None,
        duration_ms: int = 400,
    ):
        size = self.get_window_size()
        center_x, center_y = size["width"] // 2, size["height"] // 2

        if container_id and ui_nodes:
            node = self.get_node_by_id(ui_nodes, container_id)
            if node and node.get("rect"):
                rect = node["rect"]
                center_x = int(rect["x"] + rect["w"] / 2)
                center_y = int(rect["y"] + rect["h"] / 2)

        sx, sy, ex, ey = self._compute_scroll_endpoints(direction, distance, center_x, center_y)
        self.drag_px(sx, sy, ex, ey, duration_s=duration_ms / 1000.0)

    def scroll_at_point(
        self,
        direction: str,
        distance: float = 0.5,
        center_x: Optional[int] = None,
        center_y: Optional[int] = None,
        duration_ms: int = 400,
    ):
        size = self.get_window_size()
        if center_x is None:
            center_x = size["width"] // 2
        if center_y is None:
            center_y = size["height"] // 2

        sx, sy, ex, ey = self._compute_scroll_endpoints(direction, distance, center_x, center_y)
        self.drag_px(sx, sy, ex, ey, duration_s=duration_ms / 1000.0)

    def swipe(self, direction: str = "up"):
        return self._mobile("mobile: swipe", {"direction": direction})

    def pinch(self, scale: float = 0.5, velocity: float = 1.1):
        return self._mobile("mobile: pinch", {"scale": float(scale), "velocity": float(velocity)})

    # ---------- System / app ----------

    def press_button(self, name: str):
        return self._mobile("mobile: pressButton", {"name": name})

    def press_home(self):
        return self.press_button("home")

    def lock(self, seconds: Optional[int] = None):
        self.driver.lock() if seconds is None else self.driver.lock(int(seconds))

    def unlock(self):
        self.driver.unlock()

    def rotate(self, orientation: str):
        self.driver.orientation = orientation.upper()

    def background_app(self, seconds: int = 2):
        self.driver.background_app(int(seconds))

    def activate_app(self, bundle_id: str):
        self.driver.activate_app(bundle_id)

    def terminate_app(self, bundle_id: str):
        self.driver.terminate_app(bundle_id)

    def query_app_state(self, bundle_id: str) -> int:
        return int(self.driver.query_app_state(bundle_id))

    def get_app_data_container_path(self, bundle_id: str, udid: Optional[str] = None) -> str:
        resolved_udid = str(udid or self.udid or "").strip()
        if not resolved_udid:
            raise ValueError("Simulator UDID is required")
        return simulator_manager.get_app_data_container_path(resolved_udid, bundle_id)

    # ---------- Alerts ----------

    def alert_text(self) -> Optional[str]:
        try:
            return self.driver.switch_to.alert.text
        except WebDriverException:
            return None

    def alert_accept(self):
        try:
            self.driver.switch_to.alert.accept()
            return True
        except WebDriverException:
            return False

    def alert_dismiss(self):
        try:
            self.driver.switch_to.alert.dismiss()
            return True
        except WebDriverException:
            return False

    def active_app_info(self) -> Dict[str, Any]:
        return self.driver.execute_script("mobile: activeAppInfo")

    def send_keys_to_active_element(self, text: str, repeat: int = 1):
        el = self.driver.switch_to.active_element
        for _ in range(int(repeat)):
            el.send_keys(text)

    def hide_keyboard(self):
        return self.mobile_exec("mobile: hideKeyboard", {})

    # ---------- Screenshots ----------

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    def timestamp(self) -> str:
        return self._timestamp()

    def save_screenshot(self, prefix: str = "screen") -> str:
        if prefix == "final":
            filename = "final.png"
        else:
            filename = f"{prefix}_{self._timestamp()}.png"
        path = self.screenshot_dir / filename
        path.write_bytes(self.driver.get_screenshot_as_png())
        return str(path)

    def get_screenshot_png(self) -> bytes:
        return self.driver.get_screenshot_as_png()

    # ---------- Raw source ----------

    def get_page_source(self) -> str:
        return self.driver.page_source
