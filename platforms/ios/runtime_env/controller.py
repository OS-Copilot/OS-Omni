"""
Facade controller that composes runtime, observation, and action engine.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .action_engine import ACTION_SCHEMA, iOSActionEngine
from .observation import Observation, iOSObservationEngine

if TYPE_CHECKING:
    from appium.options.ios import XCUITestOptions
    from .runtime import iOSRuntime


class iOSController:
    """Public controller API used by runners."""

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:4723",
        options: Optional["XCUITestOptions"] = None,
        screenshot_dir: str = "screenshot",
        default_timeout: int = 10,
        ui_summary_limit: int = 100,
        udid: Optional[str] = None,
        wda_local_port: Optional[int] = None,
        mjpeg_server_port: Optional[int] = None,
        derived_data_path: Optional[str] = None,
    ):
        from .runtime import iOSRuntime

        self.runtime: "iOSRuntime" = iOSRuntime(
            server_url=server_url,
            options=options,
            screenshot_dir=screenshot_dir,
            default_timeout=default_timeout,
            ui_summary_limit=ui_summary_limit,
            udid=udid,
            wda_local_port=wda_local_port,
            mjpeg_server_port=mjpeg_server_port,
            derived_data_path=derived_data_path,
        )
        self.observer = iOSObservationEngine(self.runtime)
        self.action_engine = iOSActionEngine(self.runtime)

    @property
    def driver(self):
        return self.runtime.driver

    def __getattr__(self, name: str):
        for layer in (self.runtime, self.observer, self.action_engine):
            if hasattr(layer, name):
                return getattr(layer, name)
        raise AttributeError(f"{type(self).__name__} has no attribute '{name}'")

    def update_screenshot_dir(self, new_dir: str):
        self.runtime.update_screenshot_dir(new_dir)

    def get_app_data_container_path(self, bundle_id: str, udid: Optional[str] = None) -> str:
        return self.runtime.get_app_data_container_path(bundle_id, udid)

    def quit(self):
        self.runtime.quit()

    def observe(self, include_ui_tree: bool = True) -> Observation:
        return self.observer.observe(include_ui_tree=include_ui_tree)

    def get_action_schema_list_str(self) -> str:
        return self.action_engine.get_action_schema_list_str()

    def get_action_schema_json(self) -> Dict[str, Any]:
        return self.action_engine.get_action_schema_json()

    def execute_action(self, action: Any, ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.action_engine.execute_action(action, ui_nodes)

    def run_python_script(self, code: str, *, timeout: int = 120) -> Dict[str, Any]:
        return self.action_engine.run_python_script(code, timeout=timeout)
