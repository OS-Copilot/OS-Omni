from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus

class AddReminderInitializer(BaseInitializer):
    DEFAULT_WAIT_MS = 500

    def initialize(self,context:Mapping[str,Any]) -> InitResult:
        controller = context.get("controller")
        params=dict(context.get("params") or {})
        input_text = params.get("input_text")

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="No controller defined",
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
                message="No bundle id defined",
            )

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)

        try:
            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)

            controller.activate_app(bundle_id)

            if wait_ms > 0:
                time.sleep(wait_ms/1000)

            ob_result=controller.observe(include_ui_tree=True)
            ui_node=list(getattr(ob_result,"ui_nodes",[]) or [])

            target_node=None

            for node in ui_node:
                if node.get("text") == "New Reminder":
                    target_node=node

            if target_node is None:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Could not find target element",
                )

            action_result = controller.execute_action(
                {"type": "tap", "target": target_node["id"]},
                ui_node,
            )

            if not bool(action_result.get("success")):
                return InitResult(
                status=InitStatus.FAIL,
                message='Failed to open reminder',
                )

            ob_result=controller.observe(include_ui_tree=True)
            ui_node=list(getattr(ob_result,"ui_nodes",[]) or [])
            input_node=None
            complete_node=None
            for node in ui_node:
                if node.get("text") == "Title":
                    input_node=node
                if node.get("text") == "Done":
                    complete_node=node
            if input_node is None or complete_node is None:
                return InitResult(
                status=InitStatus.FAIL,
                message=f"Could not find element",
                )

            input_result=controller.execute_action({"type": "type_text", "target": input_node['id'],'text':input_text},ui_node)
            complete_result=controller.execute_action({"type": "tap", "target": complete_node["id"]},
                ui_node,)

            if not bool(input_result.get("success")) or not bool(complete_result.get("success")):
                return InitResult(
                status=InitStatus.FAIL,
                message=f"Failed to input text",
                )


        except Exception:
            return InitResult(
                status=InitStatus.ERROR,
                message="Failed to activate app bundle",
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Successfully activated app bundle",
        )
