from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class OpenAppAndClickInitializer(BaseInitializer):
    DEFAULT_WAIT_MS = 500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS initialization",
            )

        bundle_id = str(
            params.get("bundle_id")
            or params.get("app_id")
            or params.get("launch_app_bundle_id")
            or ""
        ).strip()
        if not bundle_id:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires params.bundle_id or params.app_id",
            )

        raw_target_texts = params.get("target_texts") or []
        if not isinstance(raw_target_texts, list):
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires params.target_texts as a list",
            )
        target_texts = [str(item).strip() for item in raw_target_texts if str(item).strip()]
        if not target_texts:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires non-empty params.target_texts",
            )

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)

        try:
            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)

            controller.activate_app(bundle_id)

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            observation = controller.observe(include_ui_tree=True)
            ui_nodes = list(getattr(observation, "ui_nodes", []) or [])

            target_node = None
            for node in ui_nodes:
                candidates = [
                    str(node.get("text") or "").strip(),
                    str(node.get("selector") or "").strip(),
                ]
                if any(candidate in target_texts for candidate in candidates):
                    target_node = node
                    break

            if target_node is None:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Could not find target element: {target_texts}",
                    metadata={
                        "bundle_id": bundle_id,
                        "target_texts": target_texts,
                        "ui_node_count": len(ui_nodes),
                    },
                )

            action_result = controller.execute_action(
                {"type": "tap", "target": target_node["id"]},
                ui_nodes,
            )

            if not bool(action_result.get("success")):
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Tap action failed for target element: {target_texts}",
                    metadata={
                        "bundle_id": bundle_id,
                        "target_texts": target_texts,
                        "target_node": target_node,
                        "action_result": action_result,
                    },
                )

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to open app '{bundle_id}' and click target: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "target_texts": target_texts,
                    "wait_ms": wait_ms,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Opened app '{bundle_id}' and clicked target",
            metadata={
                "bundle_id": bundle_id,
                "target_texts": target_texts,
                "wait_ms": wait_ms,
                "target_node": target_node,
            },
        )
