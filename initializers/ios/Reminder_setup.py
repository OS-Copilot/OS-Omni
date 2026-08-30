from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class ReminderInitializer(BaseInitializer):
    DEFAULT_WAIT_MS = 350
    DEFAULT_LIST_NAME = "Reminders"
    DEFAULT_SWIPE_DURATION_S = 0.16
    DEFAULT_AFTER_SWIPE_WAIT_MS = 180
    DEFAULT_SWIPE_DIRECTION = "left"
    MAX_DELETE_PASSES = 20

    DELETE_BUTTON_TEXTS = ("Delete",)
    ADD_LIST_BUTTON_TEXTS = ("Add List",)
    BACK_BUTTON_TEXTS = ("Back",)
    LIST_NAME_FIELD_TEXTS = ("List Name", "Name")
    CREATE_LIST_CONFIRM_TEXTS = ("Done", "Add", "Create")
    NEW_REMINDER_BUTTON_TEXTS = ("New Reminder",)
    REMINDER_TITLE_FIELD_TEXTS = ("Title",)
    NAV_DONE_BUTTON_TEXTS = ("Done",)
    WELCOME_SCREEN_TEXTS = ("Welcome to Reminders",)
    STARTUP_CONTINUE_BUTTON_TEXTS = ("Continue", "Get Started")
    STARTUP_DISMISS_BUTTON_TEXTS = (
        "Don’t Allow",
        "Don't Allow",
        "Not Now",
        "Later",
        "OK",
        "Done",
    )
    MAX_STARTUP_PROMPT_PASSES = 4

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
            or "com.apple.reminders"
        ).strip()
        if not bundle_id:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires params.bundle_id or params.app_id",
            )

        list_name = str(params.get("list_name") or self.DEFAULT_LIST_NAME).strip() or self.DEFAULT_LIST_NAME
        wait_ms = self._coerce_int(params.get("wait_ms"), default=self.DEFAULT_WAIT_MS, minimum=0)
        after_swipe_wait_ms = self._coerce_int(
            params.get("after_swipe_wait_ms"),
            default=self.DEFAULT_AFTER_SWIPE_WAIT_MS,
            minimum=0,
        )
        swipe_duration_s = self._coerce_float(
            params.get("swipe_duration_s"),
            default=self.DEFAULT_SWIPE_DURATION_S,
            minimum=0.01,
        )
        swipe_direction = self._coerce_direction(
            params.get("swipe_direction"),
            default=self.DEFAULT_SWIPE_DIRECTION,
        )
        purge_existing_reminders = self._coerce_bool(
            params.get("purge_existing_reminders"),
            default=True,
        )
        terminate_after_setup = self._coerce_bool(
            params.get("terminate_after_setup"),
            default=False,
        )
        return_to_lists_home_before_terminate = self._coerce_bool(
            params.get("return_to_lists_home_before_terminate"),
            default=False,
        )
        reminder_texts = self._resolve_reminder_texts(params)

        try:
            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)

            controller.activate_app(bundle_id)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            startup_error = self._dismiss_startup_prompts(controller, wait_ms)
            if startup_error is not None:
                return startup_error

            ui_nodes = self._ensure_lists_home(controller, wait_ms)
            if ui_nodes is None:
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Could not return to reminders list home",
                )

            target_list = self._find_list_cell(ui_nodes, list_name)
            already_inside_target_list = False
            if target_list is None:
                create_result = self._create_list(
                    controller=controller,
                    list_name=list_name,
                    wait_ms=wait_ms,
                )
                if create_result is not None:
                    return create_result
                ui_nodes = self._observe_ui_nodes(controller)
                target_list = self._find_list_cell(ui_nodes, list_name)
                already_inside_target_list = self._is_expected_list_view(ui_nodes, list_name)
                if target_list is None and not already_inside_target_list:
                    return InitResult(
                        status=InitStatus.FAIL,
                        message=f"Could not find reminder list '{list_name}' after creating it",
                    )

            if target_list is not None:
                open_result = controller.execute_action(
                    {"type": "tap", "target": target_list["id"]},
                    ui_nodes,
                )
                if not bool(open_result.get("success")):
                    return InitResult(
                        status=InitStatus.FAIL,
                        message=f"Tap action failed for list '{list_name}'",
                        metadata={"action_result": open_result, "target_list": target_list},
                    )
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)

            deleted_count = 0
            if purge_existing_reminders:
                delete_error, deleted_count = self._delete_all_visible_reminders(
                    controller=controller,
                    swipe_direction=swipe_direction,
                    swipe_duration_s=swipe_duration_s,
                    after_swipe_wait_ms=after_swipe_wait_ms,
                    wait_ms=wait_ms,
                )
                if delete_error is not None:
                    return delete_error

            created_texts: list[str] = []
            if reminder_texts:
                create_error, created_texts = self._create_reminders(
                    controller=controller,
                    reminder_texts=reminder_texts,
                    wait_ms=wait_ms,
                )
                if create_error is not None:
                    return create_error

            if terminate_after_setup:
                if return_to_lists_home_before_terminate:
                    self._ensure_lists_home(controller, wait_ms)
                if hasattr(controller, "terminate_app"):
                    controller.terminate_app(bundle_id)
                    time.sleep(0.5)
                elif hasattr(controller, "press_home"):
                    controller.press_home()
                    time.sleep(0.5)

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare reminders: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "list_name": list_name,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Reminder cleanup finished",
            metadata={
                "bundle_id": bundle_id,
                "list_name": list_name,
                "purge_existing_reminders": purge_existing_reminders,
                "terminate_after_setup": terminate_after_setup,
                "return_to_lists_home_before_terminate": return_to_lists_home_before_terminate,
                "deleted_count": deleted_count,
                "created_texts": created_texts,
            },
        )

    def _delete_all_visible_reminders(
        self,
        *,
        controller: Any,
        swipe_direction: str,
        swipe_duration_s: float,
        after_swipe_wait_ms: int,
        wait_ms: int,
    ) -> tuple[InitResult | None, int]:
        deleted_count = 0

        for _ in range(self.MAX_DELETE_PASSES):
            ui_nodes = self._observe_ui_nodes(controller)
            reminder_cell = self._find_first_reminder_cell(ui_nodes)
            if reminder_cell is None:
                return None, deleted_count

            swipe_error = self._swipe_cell(
                controller=controller,
                cell_node=reminder_cell,
                direction=swipe_direction,
                duration_s=swipe_duration_s,
            )
            if swipe_error is not None:
                return swipe_error
            if after_swipe_wait_ms > 0:
                time.sleep(after_swipe_wait_ms / 1000.0)

            swiped_nodes = self._observe_ui_nodes(controller)
            delete_button = self._find_delete_button_for_cell(swiped_nodes, reminder_cell)
            if delete_button is None:
                fallback_direction = self._opposite_direction(swipe_direction)
                if fallback_direction is not None:
                    retry_cell = self._find_first_reminder_cell(swiped_nodes)
                    if retry_cell is not None:
                        swipe_error = self._swipe_cell(
                            controller=controller,
                            cell_node=retry_cell,
                            direction=fallback_direction,
                            duration_s=swipe_duration_s,
                        )
                        if swipe_error is not None:
                            return swipe_error
                        if after_swipe_wait_ms > 0:
                            time.sleep(after_swipe_wait_ms / 1000.0)
                        swiped_nodes = self._observe_ui_nodes(controller)
                        delete_button = self._find_delete_button_for_cell(
                            swiped_nodes,
                            retry_cell,
                        )
            if delete_button is None:
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Could not find delete button for a reminder cell",
                    metadata={"cell_node": reminder_cell},
                ), deleted_count

            delete_result = controller.execute_action(
                {"type": "tap", "target": delete_button["id"]},
                swiped_nodes,
            )
            if not bool(delete_result.get("success")):
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Failed to delete reminder cell",
                    metadata={
                        "delete_button": delete_button,
                        "action_result": delete_result,
                    },
                ), deleted_count
            deleted_count += 1
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

        final_nodes = self._observe_ui_nodes(controller)
        if self._find_first_reminder_cell(final_nodes) is not None:
            return InitResult(
                status=InitStatus.FAIL,
                message="Could not delete all visible reminder cells",
                metadata={"deleted_count": deleted_count},
            ), deleted_count
        return None, deleted_count

    def _create_reminders(
        self,
        *,
        controller: Any,
        reminder_texts: list[str],
        wait_ms: int,
    ) -> tuple[InitResult | None, list[str]]:
        created_texts: list[str] = []

        for index, reminder_text in enumerate(reminder_texts):
            create_error = self._create_single_reminder(
                controller=controller,
                reminder_text=reminder_text,
                start_new=index == 0,
                is_last=index == len(reminder_texts) - 1,
                wait_ms=wait_ms,
            )
            if create_error is not None:
                return create_error, created_texts
            created_texts.append(reminder_text)

        finalize_error = self._finalize_reminder_creation(
            controller=controller,
            wait_ms=wait_ms,
        )
        if finalize_error is not None:
            return finalize_error, created_texts

        return None, created_texts

    def _create_single_reminder(
        self,
        *,
        controller: Any,
        reminder_text: str,
        start_new: bool,
        is_last: bool,
        wait_ms: int,
    ) -> InitResult | None:
        editor_nodes, title_field, field_error = self._ensure_reminder_entry_field(
            controller=controller,
            wait_ms=wait_ms,
            tap_new=start_new,
        )
        if field_error is not None:
            return field_error
        if title_field is None:
            return InitResult(
                status=InitStatus.FAIL,
                message="Could not find reminder title input field",
            )

        type_result = controller.execute_action(
            {
                "type": "type_text",
                "target": title_field["id"],
                "text": reminder_text,
                "clear_first": True,
            },
            editor_nodes,
        )
        if not bool(type_result.get("success")):
            return InitResult(
                status=InitStatus.FAIL,
                message=f"Failed to type reminder text '{reminder_text}'",
                metadata={"action_result": type_result, "title_field": title_field},
            )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        submit_nodes = self._observe_ui_nodes(controller)
        submit_result = controller.execute_action(
            {"type": "keyboard", "action": "enter"},
            submit_nodes,
        )
        if not bool(submit_result.get("success")):
            return InitResult(
                status=InitStatus.FAIL,
                message=f"Failed to submit reminder '{reminder_text}'",
                metadata={"action_result": submit_result},
            )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        if is_last:
            final_nodes = self._observe_ui_nodes(controller)
            controller.execute_action(
                {"type": "system", "action": "hideKeyboard"},
                final_nodes,
            )

        return None

    def _finalize_reminder_creation(
        self,
        *,
        controller: Any,
        wait_ms: int,
    ) -> InitResult | None:
        ui_nodes = self._observe_ui_nodes(controller)
        done_button = self._find_nav_done_button(ui_nodes)
        if done_button is not None:
            done_result = controller.execute_action(
                {"type": "tap", "target": done_button["id"]},
                ui_nodes,
            )
            if not bool(done_result.get("success")):
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Failed to finish reminder editing state",
                    metadata={"action_result": done_result, "done_button": done_button},
                )
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

        final_nodes = self._observe_ui_nodes(controller)
        controller.execute_action(
            {"type": "system", "action": "hideKeyboard"},
            final_nodes,
        )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        return None

    def _dismiss_startup_prompts(
        self,
        controller: Any,
        wait_ms: int,
    ) -> InitResult | None:
        for _ in range(self.MAX_STARTUP_PROMPT_PASSES):
            ui_nodes = self._observe_ui_nodes(controller)

            if self._has_alert(ui_nodes):
                alert_result = controller.execute_action(
                    {"type": "alert", "action": "dismiss"},
                    ui_nodes,
                )
                if not bool(alert_result.get("success")):
                    dismiss_button = self._find_button_by_texts(
                        ui_nodes,
                        self.STARTUP_DISMISS_BUTTON_TEXTS,
                    )
                    if dismiss_button is None:
                        return InitResult(
                            status=InitStatus.FAIL,
                            message="Could not dismiss Reminders startup alert",
                            metadata={"action_result": alert_result},
                        )
                    alert_result = controller.execute_action(
                        {"type": "tap", "target": dismiss_button["id"]},
                        ui_nodes,
                    )
                    if not bool(alert_result.get("success")):
                        return InitResult(
                            status=InitStatus.FAIL,
                            message="Failed to dismiss Reminders startup alert",
                            metadata={
                                "action_result": alert_result,
                                "dismiss_button": dismiss_button,
                            },
                        )
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)
                continue

            if not self._is_welcome_screen(ui_nodes):
                return None

            continue_button = self._find_button_by_texts(
                ui_nodes,
                self.STARTUP_CONTINUE_BUTTON_TEXTS,
            )
            if continue_button is None:
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Could not find Reminders startup continue button",
                )

            continue_result = controller.execute_action(
                {"type": "tap", "target": continue_button["id"]},
                ui_nodes,
            )
            if not bool(continue_result.get("success")):
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Failed to dismiss Reminders startup screen",
                    metadata={
                        "action_result": continue_result,
                        "continue_button": continue_button,
                    },
                )
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

        final_nodes = self._observe_ui_nodes(controller)
        if self._has_alert(final_nodes) or self._is_welcome_screen(final_nodes):
            return InitResult(
                status=InitStatus.FAIL,
                message="Could not dismiss Reminders startup prompts",
            )
        return None

    def _ensure_reminder_entry_field(
        self,
        *,
        controller: Any,
        wait_ms: int,
        tap_new: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, InitResult | None]:
        ui_nodes = self._observe_ui_nodes(controller)
        title_field = self._find_reminder_title_field(ui_nodes)

        if title_field is not None and not tap_new:
            return ui_nodes, title_field, None

        new_button = self._find_button_by_texts(ui_nodes, self.NEW_REMINDER_BUTTON_TEXTS)
        if new_button is None:
            return ui_nodes, None, InitResult(
                status=InitStatus.FAIL,
                message="Could not find 'New Reminder' button",
            )

        open_result = controller.execute_action(
            {"type": "tap", "target": new_button["id"]},
            ui_nodes,
        )
        if not bool(open_result.get("success")):
            return ui_nodes, None, InitResult(
                status=InitStatus.FAIL,
                message="Failed to open new reminder editor",
                metadata={"action_result": open_result},
            )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        editor_nodes = self._observe_ui_nodes(controller)
        title_field = self._find_reminder_title_field(editor_nodes)
        return editor_nodes, title_field, None

    def _swipe_cell(
        self,
        *,
        controller: Any,
        cell_node: dict[str, Any],
        direction: str,
        duration_s: float,
    ) -> InitResult | None:
        rect = cell_node.get("rect") or {}
        try:
            x = float(rect["x"])
            y = float(rect["y"])
            w = float(rect["w"])
            h = float(rect["h"])
        except Exception:
            return InitResult(
                status=InitStatus.FAIL,
                message="Target reminder cell does not have a usable rect",
                metadata={"cell_node": cell_node},
            )

        normalized_direction = self._normalize_direction(direction)
        if normalized_direction == "right":
            start_x = int(x + w * 0.18)
            end_x = int(x + w * 0.72)
        else:
            start_x = int(x + w * 0.82)
            end_x = int(x + w * 0.38)
        center_y = int(y + h / 2)

        try:
            controller.drag_px(start_x, center_y, end_x, center_y, duration_s=duration_s)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to swipe reminder cell: {exc}",
                metadata={"cell_node": cell_node},
            )
        return None

    def _find_list_cell(
        self,
        ui_nodes: list[dict[str, Any]],
        list_name: str,
    ) -> dict[str, Any] | None:
        wanted = self._normalize_text(list_name)
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Cell":
                continue
            raw_text = str(node.get("text") or "").strip()
            title_text = self._extract_list_title(raw_text)
            if self._normalize_text(title_text) == wanted:
                return node
        return None

    def _ensure_lists_home(
        self,
        controller: Any,
        wait_ms: int,
    ) -> list[dict[str, Any]] | None:
        ui_nodes = self._observe_ui_nodes(controller)
        if self._find_button_by_texts(ui_nodes, self.ADD_LIST_BUTTON_TEXTS) is not None:
            return ui_nodes

        back_button = self._find_back_button(ui_nodes)
        if back_button is None:
            return ui_nodes

        back_result = controller.execute_action(
            {"type": "tap", "target": back_button["id"]},
            ui_nodes,
        )
        if not bool(back_result.get("success")):
            return None
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        return self._observe_ui_nodes(controller)

    def _is_expected_list_view(
        self,
        ui_nodes: list[dict[str, Any]],
        list_name: str,
    ) -> bool:
        wanted = self._normalize_text(list_name)
        has_back_button = self._find_back_button(ui_nodes) is not None
        for node in ui_nodes:
            node_type = str(node.get("type") or "").strip()
            if node_type not in {"NavigationBar", "StaticText"}:
                continue
            rect = node.get("rect") or {}
            node_y = float(rect.get("y", 0.0))
            if node_y > 170.0:
                continue
            text = self._normalize_text(str(node.get("text") or node.get("selector") or ""))
            if text == wanted and has_back_button:
                return True
        return False

    def _create_list(
        self,
        *,
        controller: Any,
        list_name: str,
        wait_ms: int,
    ) -> InitResult | None:
        ui_nodes = self._observe_ui_nodes(controller)
        add_list_button = self._find_button_by_texts(ui_nodes, self.ADD_LIST_BUTTON_TEXTS)
        if add_list_button is None:
            return InitResult(
                status=InitStatus.FAIL,
                message="Could not find 'Add List' button",
            )

        add_result = controller.execute_action(
            {"type": "tap", "target": add_list_button["id"]},
            ui_nodes,
        )
        if not bool(add_result.get("success")):
            return InitResult(
                status=InitStatus.FAIL,
                message="Failed to open create-list dialog",
                metadata={"action_result": add_result},
            )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        dialog_nodes = self._observe_ui_nodes(controller)
        name_field = self._find_list_name_field(dialog_nodes)
        if name_field is None:
            return InitResult(
                status=InitStatus.FAIL,
                message="Could not find list name input field",
            )

        type_result = controller.execute_action(
            {"type": "type_text", "target": name_field["id"], "text": list_name},
            dialog_nodes,
        )
        if not bool(type_result.get("success")):
            return InitResult(
                status=InitStatus.FAIL,
                message="Failed to type list name",
                metadata={"action_result": type_result, "name_field": name_field},
            )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        confirm_nodes = self._observe_ui_nodes(controller)
        confirm_button = self._find_button_by_texts(confirm_nodes, self.CREATE_LIST_CONFIRM_TEXTS)
        if confirm_button is None:
            return InitResult(
                status=InitStatus.FAIL,
                message="Could not find create-list confirm button",
            )

        confirm_result = controller.execute_action(
            {"type": "tap", "target": confirm_button["id"]},
            confirm_nodes,
        )
        if not bool(confirm_result.get("success")):
            return InitResult(
                status=InitStatus.FAIL,
                message="Failed to confirm list creation",
                metadata={"action_result": confirm_result, "confirm_button": confirm_button},
            )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        return None

    def _find_first_reminder_cell(
        self,
        ui_nodes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for node in ui_nodes:
            if self._is_reminder_cell(node):
                return node
        return None

    def _find_delete_button_for_cell(
        self,
        ui_nodes: list[dict[str, Any]],
        cell_node: dict[str, Any],
    ) -> dict[str, Any] | None:
        cell_rect = cell_node.get("rect") or {}
        cell_y = float(cell_rect.get("y", 0.0))
        cell_h = float(cell_rect.get("h", 0.0))
        wanted = {self._normalize_text(text) for text in self.DELETE_BUTTON_TEXTS}

        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text not in wanted and selector not in wanted:
                continue

            rect = node.get("rect") or {}
            node_y = float(rect.get("y", 0.0))
            if cell_h > 0 and abs(node_y - cell_y) > max(30.0, cell_h):
                continue
            return node

        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector in wanted:
                return node
        return None

    def _observe_ui_nodes(self, controller: Any) -> list[dict[str, Any]]:
        try:
            observation = controller.observe(include_ui_tree=True)
        except Exception:
            return []
        return list(getattr(observation, "ui_nodes", []) or [])

    def _is_reminder_cell(self, node: dict[str, Any]) -> bool:
        if str(node.get("type") or "").strip() != "Cell":
            return False

        selector = self._normalize_text(str(node.get("selector") or ""))
        text = self._normalize_text(str(node.get("text") or ""))

        if "x-apple-reminderkit://remcdreminder/" in selector:
            return True
        if text.endswith(", incomplete") or text.endswith(",incomplete"):
            return True
        return False

    def _find_button_by_texts(
        self,
        ui_nodes: list[dict[str, Any]],
        texts: tuple[str, ...],
    ) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in texts}
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector in wanted:
                return node
        return None

    def _is_welcome_screen(self, ui_nodes: list[dict[str, Any]]) -> bool:
        wanted = {self._normalize_text(text) for text in self.WELCOME_SCREEN_TEXTS}
        for node in ui_nodes:
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector in wanted:
                return True
        return False

    def _has_alert(self, ui_nodes: list[dict[str, Any]]) -> bool:
        for node in ui_nodes:
            node_type = str(node.get("type") or "").strip()
            if node_type in {"Alert", "Sheet"}:
                return True
        return False

    def _find_back_button(self, ui_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in self.BACK_BUTTON_TEXTS}
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector == self._normalize_text("BackButton"):
                return node
        return None

    def _find_nav_done_button(self, ui_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in self.NAV_DONE_BUTTON_TEXTS}
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            rect = node.get("rect") or {}
            node_y = float(rect.get("y", 0.0))
            if node_y > 120.0:
                continue
            if text in wanted or selector in wanted:
                return node
        return None

    def _find_list_name_field(
        self,
        ui_nodes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in self.LIST_NAME_FIELD_TEXTS}
        fallback_field: dict[str, Any] | None = None

        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "TextField":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector in wanted:
                return node
            if fallback_field is None:
                fallback_field = node
        return fallback_field

    def _find_text_field_by_texts(
        self,
        ui_nodes: list[dict[str, Any]],
        texts: tuple[str, ...],
    ) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in texts}
        fallback_field: dict[str, Any] | None = None

        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "TextField":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector in wanted:
                return node
            if fallback_field is None:
                fallback_field = node
        return fallback_field

    def _find_reminder_title_field(
        self,
        ui_nodes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in self.REMINDER_TITLE_FIELD_TEXTS}
        candidates: list[dict[str, Any]] = []

        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "TextField":
                continue
            candidates.append(node)

        if not candidates:
            return None

        preferred: list[dict[str, Any]] = []
        for node in candidates:
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector in wanted or not text:
                preferred.append(node)

        pool = preferred or candidates
        return max(pool, key=lambda node: float((node.get("rect") or {}).get("y", 0.0)))

    def _resolve_reminder_texts(self, params: dict[str, Any]) -> list[str]:
        values: list[str] = []

        raw_seed_reminders = params.get("seed_reminders")
        if isinstance(raw_seed_reminders, list):
            for item in raw_seed_reminders:
                if isinstance(item, dict):
                    text = str(item.get("title") or item.get("text") or "").strip()
                else:
                    text = str(item or "").strip()
                if text:
                    values.append(text)

        raw = params.get("reminder_texts")
        if isinstance(raw, list):
            for item in raw:
                text = str(item or "").strip()
                if text:
                    values.append(text)

        target_text = str(params.get("target_text") or "").strip()
        if target_text:
            values.append(target_text)

        raw_decoys = params.get("decoy_texts")
        if isinstance(raw_decoys, list):
            for item in raw_decoys:
                text = str(item or "").strip()
                if text:
                    values.append(text)

        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize_text(value)
            if not normalized or normalized in seen:
                continue
            deduped.append(value)
            seen.add(normalized)
        return deduped

    @staticmethod
    def _coerce_bool(raw: Any, *, default: bool) -> bool:
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().casefold()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    @staticmethod
    def _coerce_int(raw: Any, *, default: int, minimum: int) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(minimum, value)

    @staticmethod
    def _coerce_float(raw: Any, *, default: float, minimum: float) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return max(minimum, value)

    @staticmethod
    def _coerce_direction(raw: Any, *, default: str) -> str:
        normalized = str(raw or "").strip().casefold()
        if normalized in {"left", "l"}:
            return "left"
        if normalized in {"right", "r"}:
            return "right"
        return default

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text).strip().casefold().split())

    @staticmethod
    def _extract_list_title(text: str) -> str:
        raw = str(text or "").strip()
        for sep in ("，", ","):
            if sep in raw:
                return raw.split(sep, 1)[0].strip()
        return raw

    @staticmethod
    def _normalize_direction(direction: str) -> str:
        normalized = str(direction or "").strip().casefold()
        if normalized in {"right", "r"}:
            return "right"
        return "left"

    @staticmethod
    def _opposite_direction(direction: str) -> str | None:
        normalized = str(direction or "").strip().casefold()
        if normalized in {"left", "l"}:
            return "right"
        if normalized in {"right", "r"}:
            return "left"
        return None
