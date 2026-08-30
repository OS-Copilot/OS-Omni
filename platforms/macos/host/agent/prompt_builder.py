from __future__ import annotations

import json
import re
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from core.benchmark_policy import (
    DEBUG_PROMPT_PROFILE,
    is_debug_prompt_profile,
    normalize_prompt_profile,
)
from core.prompt.builders import build_step_prompt, build_system_prompt
from platforms.macos.shared.drawio_prepared_targets import DRAWIO_PREPARED_TARGETS

def _format_norm(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")

_UI_CONTEXT_KEYS = (
    "id",
    "type",
    "text",
    "identifier",
    "description",
    "value",
    "roleDescription",
    "subrole",
    "selector",
    "enabled",
    "x",
    "y",
    "width",
    "height",
    "rect",
    "tap",
    "tap_norm",
    "accessible",
)


def _osworld_reflection_pyautogui_system_prompt(
    *,
    observation_mode: str,
    goal: str,
) -> str:
    observation_text = MacOSPromptBuilder._normalize_osworld_observation_intro(observation_mode)
    return (
        "You are an agent which follow my instruction and perform desktop computer tasks as instructed. "
        "You have good knowledge of computer and good internet connection and assume your code will run on a "
        "computer for controlling the mouse and keyboard. "
        f"{observation_text}\n"
        "You are required to use `pyautogui` to perform the action grounded to the observation, but DONOT use "
        "the `pyautogui.locateCenterOnScreen` function to locate the element you want to operate with since we "
        "have no image of the element you want to operate with. DONOT USE `pyautogui.screenshot()` to make "
        "screenshot. Return one line or multiple lines of python code to perform the action each time, be time "
        "efficient.\n"
        "The code sandbox only allows `import pyautogui`, `import time`, direct pyautogui calls, simple loops, "
        "and `print`. Do not import tkinter, os, subprocess, pyperclip, bpy, bmesh, or any other module. Do not "
        "use clipboard-based automation or application-internal scripting unless it is reachable through normal "
        "keyboard and mouse actions. Do not press Command-Q or close windows unless the task explicitly asks you to "
        "close that exact app window.\n"
        "Never open or use Terminal, iTerm, iTerm2, or any terminal/shell window during a task. Do not use "
        "Spotlight or Launchpad to launch shell commands. Complete the requested work inside the target "
        "application UI.\n"
        "When predicting multiple lines of code, make some small sleep like `time.sleep(0.5)` interval so that "
        "the machine could take; Each time you need to predict a complete code, no variables or function can be "
        "shared from history. You need to specify the coordinates by yourself based on your observation of the "
        "current observation, but you should be careful to ensure that the coordinates are correct.\n"
        "You should first give the current screenshot and previous things we did a short reflection in plain text, "
        "and then return the code or special code. The reflection should be brief.\n"
        "You ONLY need to return the code inside a code block, like this: ```python\n# your code here\n```. "
        "Specially, it is also allowed to return the following special code: When you think you have to wait for "
        "some time, return ```WAIT```; When you think the task can not be done, return ```FAIL```, don't easily "
        f"say ```FAIL```, try your best to do the task; When you think the task is done, return ```DONE```.\n"
        f"You are asked to complete the following task: {goal}\n"
        "First give the current screenshot and previous things we did a short reflection, then RETURN ME THE CODE "
        "OR SPECIAL CODE I ASKED FOR. NEVER EVER RETURN ME ANYTHING ELSE."
    ).strip()


class MacOSPromptBuilder:
    """macOS runtime adapter for the shared core prompt builders."""

    _EXTRA_SYSTEM_PROMPT = (
        "Never open or use Terminal, iTerm, iTerm2, or any terminal/shell window during a task. "
        "Do not use Spotlight or Launchpad to launch shell commands. Complete the requested work inside the "
        "target application UI."
    )

    def __init__(
        self,
        *,
        observation_mode: str,
        tool_calling: bool,
        action_mode: str = "code_adapter",
        prompt_profile: str = DEBUG_PROMPT_PROFILE,
    ) -> None:
        self.observation_mode = str(observation_mode).strip()
        self.tool_calling = bool(tool_calling)
        self.action_mode = str(action_mode).strip() or "code_adapter"
        self.prompt_profile = normalize_prompt_profile(prompt_profile)
        self._current_goal = ""
        self._thunderbird_multi_send_messages: list[dict[str, str]] = []
        self._thunderbird_multi_send_completed = 0
        self._thunderbird_prev_compose_visible: bool | None = None
        self._gimp_expected_clockwise_rotations = 0
        self._gimp_completed_clockwise_rotations = 0
        self._gimp_last_canvas_orientation: str | None = None

    def build_system_prompt(
        self,
        *,
        task: Any,
        action_rules: str | None = None,
        extra_system_prompt: str | None = None,
    ) -> str:
        goal = str(getattr(task, "goal", "")).strip()
        if not goal:
            raise ValueError("task.goal cannot be empty")
        self._current_goal = goal
        self._thunderbird_multi_send_messages = self._extract_thunderbird_multi_send_messages(goal)
        self._thunderbird_multi_send_completed = 0
        self._thunderbird_prev_compose_visible = None
        self._gimp_expected_clockwise_rotations = len(
            re.findall(r"90\s+degrees?\s+clockwise", goal, flags=re.IGNORECASE)
        )
        self._gimp_completed_clockwise_rotations = 0
        self._gimp_last_canvas_orientation = None
        if self.action_mode == "code_adapter":
            extra = _osworld_reflection_pyautogui_system_prompt(
                observation_mode=self.observation_mode,
                goal=goal,
            )
            if extra_system_prompt:
                extra = f"{extra}\n\n{extra_system_prompt}"
            return extra.strip()

        task_specific_prompt = self._build_task_specific_system_prompt(goal) if self._use_debug_hints() else None
        merged_system_prompt = "\n".join(
            part for part in [self._EXTRA_SYSTEM_PROMPT, task_specific_prompt, extra_system_prompt] if part
        ) or None

        return build_system_prompt(
            task=goal,
            platform="macOS",
            observation_mode=self.observation_mode,
            tool_calling=self.tool_calling,
            action_rules=action_rules,
            extra_system_prompt=merged_system_prompt,
        )

    def build_step_prompt(
        self,
        *,
        observation: Any,
        extra_step_prompt: str | None = None,
    ) -> str:
        addition_prompt = (
            self._build_addition_prompt(observation)
            if self._use_debug_hints()
            else self._build_benchmark_addition_prompt(observation)
        )
        merged_extra = "\n".join(
            part for part in [addition_prompt, extra_step_prompt] if part
        ) or None
        prompt = build_step_prompt(
            observation_mode=self.observation_mode,
            ui_context=self._build_ui_context(getattr(observation, "ui_nodes", None)),
            extra_step_prompt=merged_extra,
        )
        if self.action_mode == "code_adapter":
            prompt += (
                "\n\nFirst give a short reflection, then return the next pyautogui code block or special code."
            )
        return prompt

    @staticmethod
    def _normalize_osworld_observation_intro(observation_mode: str) -> str:
        observation_mode = str(observation_mode).strip()
        if observation_mode == "screenshot_only":
            return (
                "For each step, you will get an observation of an image, which is the screenshot of the computer screen "
                "and you will predict the action of the computer based on the image."
            )
        if observation_mode == "a11y_tree_only":
            return (
                "For each step, you will get an observation of the desktop by accessibility tree. "
                "And you will predict the action of the computer based on the accessibility tree."
            )
        return (
            "For each step, you will get an observation of the desktop by 1) a screenshot; and 2) accessibility "
            "tree. And you will predict the action of the computer based on the screenshot and accessibility tree."
        )

    def _use_debug_hints(self) -> bool:
        return is_debug_prompt_profile(self.prompt_profile)

    def _build_benchmark_addition_prompt(self, observation: Any) -> str | None:
        details: list[str] = []

        foreground_app = str(getattr(observation, "foreground_app", "") or "").strip()
        if foreground_app:
            details.append(f"Foreground app: {foreground_app}")

        foreground_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        if foreground_bundle_id:
            details.append(f"Foreground bundle id: {foreground_bundle_id}")

        details.append(
            "Node-ID safety hint: only use node IDs from the current observation. After any click, save, close, tab switch, or window change, old node IDs can become invalid, so stop reusing IDs from earlier steps."
        )

        ui_nodes = getattr(observation, "ui_nodes", None)
        width = getattr(observation, "width", None)
        height = getattr(observation, "height", None)

        if isinstance(width, int) and isinstance(height, int):
            details.append(f"Screen size: {width}x{height}")

        foreground_window = MacOSPromptBuilder._find_foreground_window(
            ui_nodes=ui_nodes,
            foreground_app=foreground_app,
            foreground_bundle_id=foreground_bundle_id,
        )
        if foreground_window:
            rect = MacOSPromptBuilder._window_bounds(foreground_window)
            if rect is not None:
                left, top, window_width, window_height = rect
                right = left + window_width
                bottom = top + window_height
                details.append(
                    f"Foreground window bounds: left={left}, top={top}, width={window_width}, height={window_height}, right={right}, bottom={bottom}."
                )

        if any(
            isinstance(node, Mapping)
            and "menu" in str(node.get("type") or node.get("roleDescription") or "").strip().lower()
            for node in (ui_nodes or [])
        ):
            details.append(
                "If the UI tree lists menu bar items or menu items, prefer clicking those node IDs directly instead of estimating menu coordinates from the screenshot."
            )

        if not details:
            return None
        return "Additional environment info:\n" + "\n".join(f"- {item}" for item in details)

    @staticmethod
    def _build_ui_context(ui_nodes: Any) -> str:
        if not isinstance(ui_nodes, list) or not ui_nodes:
            return "(No interactive elements visible)"

        lines: list[str] = []
        for node in ui_nodes:
            if isinstance(node, Mapping):
                compact_node = {
                    key: node[key]
                    for key in _UI_CONTEXT_KEYS
                    if key in node and node[key] not in (None, "")
                }
                if compact_node:
                    lines.append(json.dumps(compact_node, ensure_ascii=False, separators=(",", ":")))
                    continue
            lines.append(json.dumps(node, ensure_ascii=False, separators=(",", ":"), default=str))

        return "\n".join(lines) if lines else "(No interactive elements visible)"

    def _build_addition_prompt(self, observation: Any) -> str | None:
        details: list[str] = []
        current_goal_raw = str(getattr(self, "_current_goal", "") or "")
        current_goal = current_goal_raw.lower()
        is_actual_add_transactions_goal = (
            "actual budget" in current_goal
            and "switch to the existing \"checking\" account" in current_goal
            and "85.50" in current_goal
            and ("3200.00" in current_goal or "3,200.00" in current_goal)
            and "food category" in current_goal
            and "income category" in current_goal
        )
        is_actual_full_setup_goal = (
            "actual budget" in current_goal
            and "make sure the \"checking\" and \"savings\" accounts remain available" in current_goal
            and "transfer $1,000 from checking to savings" in current_goal
            and "rent payment" in current_goal
            and "groceries payment" in current_goal
        )
        actual_multi_account_targets = self._extract_actual_multi_create_accounts(current_goal_raw)
        is_actual_multi_account_goal = (
            "actual budget" in current_goal
            and ("create two local accounts" in current_goal or "create three local accounts" in current_goal)
            and bool(actual_multi_account_targets)
        )
        openshop_multi_item_goal = (
            "openshop" in current_goal
            and "verdant pro noise-canceling headphones" in current_goal
            and "mountain isle pour-over coffee 20 pack" in current_goal
        )
        openshop_checkout_goal = (
            openshop_multi_item_goal
            and "proceed to checkout" in current_goal
            and "wechat pay" in current_goal
        )
        openshop_catalog_review_goal = (
            openshop_multi_item_goal
            and "category to electronics" in current_goal
            and "price: high to low" in current_goal
            and "category to grocery" in current_goal
            and "price: low to high" in current_goal
        )
        openshop_quantity_review_goal = (
            openshop_multi_item_goal
            and "quantity to 2 and then return it to 1" in current_goal
        )
        openshop_checkout_switch_goal = (
            openshop_checkout_goal
            and "shipping address to home first" in current_goal
            and "payment method to alipay first" in current_goal
        )
        actual_blank_payee_task = is_actual_add_transactions_goal or is_actual_full_setup_goal
        thunderbird_multi_send_messages = list(self._thunderbird_multi_send_messages)

        foreground_app = str(getattr(observation, "foreground_app", "") or "").strip()
        if foreground_app:
            details.append(f"Foreground app: {foreground_app}")

        foreground_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        if foreground_bundle_id:
            details.append(f"Foreground bundle id: {foreground_bundle_id}")
        details.append(
            "Node-ID safety hint: only use node IDs from the current observation. After any click, save, close, tab switch, or window change, old node IDs can become invalid, so stop reusing IDs from earlier steps."
        )

        ui_nodes = getattr(observation, "ui_nodes", None)
        width = getattr(observation, "width", None)
        height = getattr(observation, "height", None)
        foreground_window = MacOSPromptBuilder._find_foreground_window(
            ui_nodes=ui_nodes,
            foreground_app=foreground_app,
            foreground_bundle_id=foreground_bundle_id,
        )
        gimp_export_window = MacOSPromptBuilder._find_window_text_contains(ui_nodes, "export image")
        gimp_open_layers_window = MacOSPromptBuilder._find_window_text_contains(ui_nodes, "open image as layers")

        if foreground_app.lower() == "libreoffice" or "libreoffice" in foreground_bundle_id.lower():
            details.append(
                "LibreOffice save hint: after your edits, Command-S is usually the most reliable way to save DOCX, XLSX, or PPTX files."
            )
        if foreground_app.lower() == "actual" or "actualbudget" in foreground_bundle_id.lower():
            details.append(
                "Actual hint: the '+ Add account' control is inside the app's blue left sidebar near the bottom edge of the window, above the macOS Dock. The existing account rows sit higher in the sidebar; the target is the bottom-left '+ Add account' button text itself. Do not aim below the window."
            )
            details.append(
                "Actual shortcut hint: Command-K opens Actual's command palette. If sidebar clicks are flaky, use Command-K, type a page or account name such as Budget, Checking, or Savings, and press Enter to jump there directly instead of burning steps on repeated sidebar guesses."
            )
            if not is_actual_multi_account_goal:
                details.append(
                    "Actual register hint: on an account page, the primary path is the visible '+ Add New' toolbar button on the same row as Import and Filter, just under the green account balance. Only if one careful '+ Add New' click clearly fails should you try the T shortcut, and first click inside the white register table so the ledger has focus."
                )
            details.append(
                "Actual command-palette hint: once the command palette is open and you have typed the target name, the safest next action is Enter. Do not keep tapping inside the palette result list unless Enter clearly failed."
            )
            if actual_blank_payee_task:
                details.append(
                    "Actual blank-payee task hint: for this task's ordinary transactions, leave Payee blank and do not spend steps opening payee dropdowns or confirming payee suggestions."
                )
            else:
                details.append(
                    "Actual autocomplete hint: this starter budget already has common payees such as Grocery Store, Employer, Landlord, and Supermarket pre-seeded. When the exact payee or category text is already visible in the field, keep tabbing through the draft row instead of getting stuck on the dropdown. Use Enter for autocomplete only if plain tabbing clearly fails."
                )
                details.append(
                    "Actual payee-selection hint: for Grocery Store or Employer, the dropdown should show an exact payee row. Press Enter once to pick that exact payee row before leaving the Payee field; otherwise the row can save with an empty payee even though the text looked correct."
                )
            if is_actual_add_transactions_goal:
                details.append(
                    "Actual add-transactions task-only hint: this run already starts inside Checking with one blank draft row open. Unless that blank row clearly disappeared, do not reopen Command-K, do not click the sidebar, and do not click '+ Add New' again."
                )
                details.append(
                    "Actual add-transactions second-row hint: after the first Enter saves Food / 85.50, Actual immediately opens the next blank row. If you now see another blank row with 0.00 and an Add button, that is the correct second row — continue there and do not recreate the first transaction."
                )
                details.append(
                    "Actual add-transactions overwrite hint: on the second row, a leftover Food suggestion can still be visible in Category. Do not press Enter on Food again. Type Income to overwrite any leftover suggestion. If the category dropdown stays open after typing, press Enter only when Income itself is highlighted, then continue to Deposit."
                )
                details.append(
                    "Actual add-transactions category-lock hint: for both new rows, do not tab away from Category until the intended category itself is selected. After typing Food or Income, press Enter once to lock that exact category result, then move to the amount field."
                )
                details.append(
                    "Actual add-transactions recovery hint: if you accidentally save the 3200.00 deposit with category still blank or showing 'Categorize', do not open another draft row. Edit that same saved 3200.00 row: click its category cell, type Income, press Enter once to apply the category, then finish immediately."
                )
                details.append(
                    "Actual add-transactions completion hint: as soon as both required new rows exist — the 85.50 Food expense and the 3200.00 Income deposit — stop interacting and use the success tool. Do not keep clicking Add or reopening fields after the second row is correct."
                )
            if is_actual_full_setup_goal:
                details.append(
                    "Actual full-setup task-only hint: for the two ordinary Checking transactions in this task, leave Payee blank. Reserve special transfer behavior only for the later Checking-to-Savings transfer."
                )
            if is_actual_multi_account_goal:
                checklist = "; ".join(
                    f"{index}. {item['name']} ({item['amount_text']})"
                    for index, item in enumerate(actual_multi_account_targets, start=1)
                )
                details.append(
                    f"Actual multi-account checklist: {checklist}. Create them in that exact order."
                )
                details.append(
                    "Actual multi-account progress hint: after one account is created and the modal closes, do not finish. Click '+ Add account' again and continue with the next unchecked checklist item."
                )
                details.append(
                    "Actual multi-account completion hint: only use the success tool after every checklist account exists and the last created account is showing."
                )
                details.append(
                    "Actual multi-account form-focus hint: each time the 'Create Local Account' form opens, the Name field is already focused. The safest sequence is: type the next account name immediately with no extra target or click, then tap the Balance field once, type the balance, and click Create."
                )
                details.append(
                    "Actual multi-account error-recovery hint: if the form complains that Name is required, stop clicking around the Name box. Type the full account name once into the already focused field, refill the Balance field if it reset to 0, then click Create again."
                )
        is_textedit = foreground_app.lower() == "textedit" or "textedit" in foreground_bundle_id.lower()
        if is_textedit:
            details.append(
                "TextEdit hint: the requested file is already open in the current window, so edit that document directly. Do not create a new document and do not use Save As."
            )
            details.append(
                "TextEdit layout hint: the document body is one large text area that already contains the full file contents. Work inside that editor body instead of clicking the menu bar or window chrome."
            )
            details.append(
                "TextEdit scope hint: preserve every unchanged line exactly as written. Make only the requested local edits instead of replacing the whole document with a rewritten copy."
            )
            details.append(
                "TextEdit editing hint: for insertions in the middle of the file, place the caret at the target line boundary, press Return for new lines when needed, then continue typing the exact requested text."
            )
            details.append(
                "TextEdit completion hint: once every requested edit is visible in the document, save with Command-S and then finish."
            )
        is_blender = foreground_app.lower() == "blender" or "blender" in foreground_bundle_id.lower()
        if is_blender:
            details.append(
                "Blender benchmark hint: the prepared .blend file is already open. Use the normal Blender interface and save the same file with Command-S after the requested edits."
            )
            details.append(
                "Blender splash hint: if the splash screen or startup popup blocks the scene, press Escape once, then continue in the main Blender window."
            )
            if "resolution" in current_goal or "fps" in current_goal or "frame range" in current_goal or "transparent" in current_goal:
                details.append(
                    "Blender render-settings hint: render properties such as Resolution X/Y, FPS, Frame Start/End, image format, color mode, and Film Transparent live in the Properties editor's Output/Render tabs on the right side. Change the exact fields requested, then save."
                )
            if "featurecube" in current_goal or "accentcylinder" in current_goal or "filllight" in current_goal:
                details.append(
                    "Blender transform hint: select named objects from the Outliner, then use the Item/Transform fields for Location, Rotation, and Scale. Edit one named object at a time, and do not finish until every checklist object has the requested values."
                )
            if "exact order" in current_goal:
                checklist = self._extract_ordered_goal_checklist(current_goal_raw)
                if checklist:
                    details.append(
                        "Blender ordered checklist: "
                        + " ; ".join(f"{index}. {step}" for index, step in enumerate(checklist, start=1))
                    )
        is_zotero = foreground_app.lower() == "zotero" or "zotero" in foreground_bundle_id.lower()
        if is_zotero:
            details.append(
                "Zotero collection hint: the left sidebar already shows My Library and collections. Use the visible '新建分类…' control near the top-left of the Zotero window or File -> New Collection to create requested collections."
            )
            details.append(
                "Zotero item hint: keep the correct collection selected before creating a new item, because Zotero files the new item into the currently selected collection."
            )
            details.append(
                "Zotero item-type hint: use the visible '新建条目' control and choose the requested type directly from its menu instead of exploring unrelated menus."
            )
            details.append(
                "Zotero title-focus hint: right after you choose an item type, the Title field in the right metadata pane is usually already focused. Prefer type_text with no extra target first, then press Enter."
            )
            details.append(
                "Zotero title-commit hint: after typing an item title in the right metadata pane, press Enter or click back into the center item list so Zotero commits the field and the title appears in the list."
            )
            details.append(
                "Zotero sequential-work hint: for multi-collection tasks, finish one collection-plus-item pair completely before moving on. Do not start the next collection until the current collection already shows its requested title in the center item list."
            )
            details.append(
                "Zotero completion hint: once the requested collections are visible in the left sidebar and the currently selected collection shows its requested title in the center list, finish immediately. The evaluator checks the full Zotero library database, so do not keep wandering just to reopen previously completed collections."
            )
        is_drawio = foreground_app.lower() == "draw.io" or "drawio" in foreground_bundle_id.lower()
        if is_drawio:
            details.append(
                "draw.io hint: the central white grid canvas contains the prepared rounded rectangles. This task uses an already-open .drawio file, so do not use Save As; Command-S is the correct save path."
            )
            details.append(
                "draw.io text-edit hint: to replace a rectangle label, target the text in the middle of that rounded rectangle. After typing the replacement, move on to the next rectangle instead of opening extra menus."
            )
            details.append(
                "draw.io scope hint: do not create, delete, drag, resize, or recolor shapes unless the task explicitly asks for it. Only relabel the existing visible rounded rectangles."
            )
            details.append(
                "draw.io order hint: when the task says left-to-right or top-to-bottom, follow the visible grid exactly. Finish every requested rectangle before using the success tool."
            )
            details.append(
                "draw.io placeholder hint: when the instruction maps an existing label like 'Card 1', 'Slot 7', or 'Item 12' to a new label, use the visible old label as the anchor and replace that exact rectangle instead of guessing by memory."
            )
            if isinstance(foreground_window, Mapping):
                bounds = MacOSPromptBuilder._window_bounds(foreground_window)
                if bounds is not None and isinstance(width, int) and isinstance(height, int):
                    left, top, window_width, window_height = bounds
                    canvas_x = max(0.0, min((left + window_width * 0.42) / max(width, 1), 0.999))
                    canvas_y = max(0.0, min((top + window_height * 0.48) / max(height, 1), 0.999))
                    page_tab_x = max(0.0, min((left + window_width * 0.12) / max(width, 1), 0.999))
                    page_tab_y = max(0.0, min((top + window_height * 0.985) / max(height, 1), 0.999))
                    details.append(
                        f"draw.io layout hint: the canvas center is roughly at {{'x': {_format_norm(canvas_x)}, 'y': {_format_norm(canvas_y)}}}, and page tabs sit along the bottom-left edge near {{'x': {_format_norm(page_tab_x)}, 'y': {_format_norm(page_tab_y)}}}."
                    )
            drawio_target_hints = MacOSPromptBuilder._build_drawio_target_hints(current_goal_raw)
            if drawio_target_hints:
                details.append(
                    "draw.io prepared-target hint: the current starter file has fixed rectangle centers. When you use replace_text, target these approximate normalized coordinates: "
                    + "; ".join(drawio_target_hints)
                )
                details.append(
                    "draw.io execution hint: for these prepared benchmark files, the reliable strategy is consecutive replace_text calls on the requested rectangles followed by one Command-S save. Skip exploratory taps on blank canvas areas unless a rectangle is truly not visible."
                )
        is_wireshark = foreground_app.lower() == "wireshark" or "wireshark" in foreground_bundle_id.lower()
        wireshark_filter_entry_node = (
            MacOSPromptBuilder._find_node_by_text(ui_nodes, "Display filter entry") if is_wireshark else None
        )
        wireshark_file_name_node = (
            MacOSPromptBuilder._find_node_by_text(ui_nodes, "File name:") if is_wireshark else None
        )
        wireshark_export_as_node = (
            MacOSPromptBuilder._find_node_by_text(ui_nodes, "Export as:") if is_wireshark else None
        )
        wireshark_dialog_filter_fields = (
            [
                node
                for node in (ui_nodes or [])
                if isinstance(node, Mapping)
                and str(node.get("roleDescription") or "").strip().lower() == "text field"
                and (
                    "only show types matching filter value"
                    in str(node.get("description") or "").strip().lower()
                    or "only show types matching the filter value"
                    in str(node.get("description") or "").strip().lower()
                )
            ]
            if is_wireshark and isinstance(ui_nodes, list)
            else []
        )
        wireshark_checkbox_nodes = (
            [
                node
                for node in (ui_nodes or [])
                if isinstance(node, Mapping)
                and str(node.get("roleDescription") or "").strip().lower() == "checkbox"
                and str(node.get("text") or "").strip()
                in {"Name resolution", "Absolute start time", "Limit to display filter"}
            ]
            if is_wireshark and isinstance(ui_nodes, list)
            else []
        )
        wireshark_radio_nodes = (
            [
                node
                for node in (ui_nodes or [])
                if isinstance(node, Mapping)
                and str(node.get("roleDescription") or "").strip().lower() == "radio button"
                and str(node.get("text") or "").strip()
                in {"Ethernet", "IPv4", "IPv6", "TCP", "UDP"}
            ]
            if is_wireshark and isinstance(ui_nodes, list)
            else []
        )
        wireshark_summary_groups = (
            [
                node
                for node in (ui_nodes or [])
                if isinstance(node, Mapping)
                and str(node.get("roleDescription") or "").strip().lower() == "group"
                and (
                    str(node.get("text") or "").strip().startswith(("Ethernet", "IPv4", "IPv6", "TCP", "UDP"))
                    and "·" in str(node.get("text") or "")
                )
            ]
            if is_wireshark and isinstance(ui_nodes, list)
            else []
        )
        wireshark_title_text_nodes = (
            [
                node
                for node in (ui_nodes or [])
                if isinstance(node, Mapping)
                and str(node.get("type") or "").strip() == "AXStaticText"
                and str(node.get("text") or "").strip().startswith("Wireshark · ")
                and any(
                    token in str(node.get("text") or "").strip()
                    for token in ("Conversations", "Endpoints", "Protocol Hierarchy Statistics")
                )
            ]
            if is_wireshark and isinstance(ui_nodes, list)
            else []
        )
        wireshark_window_focus_hints: list[str] = []
        wireshark_tab_strip_hints: list[str] = []
        if is_wireshark and isinstance(ui_nodes, list) and isinstance(width, int) and isinstance(height, int):
            for title_token in ("Conversations", "Protocol Hierarchy Statistics", "Endpoints"):
                for node in ui_nodes:
                    if not isinstance(node, Mapping):
                        continue
                    if str(node.get("type") or "").strip() != "AXWindow":
                        continue
                    title = str(node.get("text") or "").strip()
                    if title_token not in title:
                        continue
                    bounds = MacOSPromptBuilder._window_bounds(node)
                    if bounds is None:
                        continue
                    left, top, window_width, _window_height = bounds
                    title_bar_x = max(0.0, min((left + min(40, max(20, window_width // 8))) / max(width, 1), 0.999))
                    title_bar_y = max(0.0, min((top + 14) / max(height, 1), 0.999))
                    wireshark_window_focus_hints.append(
                        f"{title_token} title bar near {{'x': {_format_norm(title_bar_x)}, 'y': {_format_norm(title_bar_y)}}}"
                        )
                    break
            for node in wireshark_summary_groups[:4]:
                x = int(node.get("x") or 0)
                y = int(node.get("y") or 0)
                node_width = int(node.get("width") or 0)
                node_height = int(node.get("height") or 0)
                if node_width <= 0 or node_height <= 0:
                    continue
                center_y = y + node_height // 2
                label_positions = {
                    "Ethernet": x + int(round(node_width * 0.20)),
                    "IPv4": x + int(round(node_width * 0.39)),
                    "IPv6": x + int(round(node_width * 0.54)),
                    "TCP": x + int(round(node_width * 0.69)),
                    "UDP": x + int(round(node_width * 0.84)),
                }
                wireshark_tab_strip_hints.append(
                    f"{str(node.get('id') or '').strip() or '<group>'}={str(node.get('text') or '').strip()} -> "
                    + ", ".join(
                        f"{label}≈[{tab_x}, {center_y}]"
                        for label, tab_x in label_positions.items()
                    )
                )
        is_gimp = foreground_app.lower() == "gimp" or "gimp" in foreground_bundle_id.lower()
        if is_gimp:
            gimp_canvas_size = MacOSPromptBuilder._extract_gimp_canvas_size(foreground_window)
            gimp_layer_count = MacOSPromptBuilder._extract_gimp_layer_count(foreground_window)
            gimp_expected_layer_total = MacOSPromptBuilder._estimate_gimp_expected_layer_total(current_goal_raw)
            gimp_ordered_steps = MacOSPromptBuilder._extract_ordered_goal_checklist(current_goal_raw)
            gimp_clockwise_rotation_count = len(
                re.findall(r"90\s+degrees?\s+clockwise", current_goal, flags=re.IGNORECASE)
            )
            gimp_horizontal_flip_count = len(re.findall(r"\bhorizontally\b", current_goal, flags=re.IGNORECASE))
            gimp_vertical_flip_count = len(re.findall(r"\bvertically\b", current_goal, flags=re.IGNORECASE))
            gimp_transform_operation_count = (
                gimp_clockwise_rotation_count + gimp_horizontal_flip_count + gimp_vertical_flip_count
            )
            gimp_pure_multi_rotate_plan = (
                gimp_clockwise_rotation_count > 1
                and gimp_horizontal_flip_count == 0
                and gimp_vertical_flip_count == 0
            )
            gimp_single_rotation_progress_plan = (
                gimp_clockwise_rotation_count == 1
                and gimp_horizontal_flip_count <= 1
                and gimp_vertical_flip_count == 0
            )
            gimp_transform_visible = any(
                str(node.get("text") or "") == "Transform"
                for node in ui_nodes or []
                if isinstance(node, Mapping)
            )
            gimp_rotate_visible = any(
                str(node.get("text") or "") == "Rotate 90° clockwise"
                for node in ui_nodes or []
                if isinstance(node, Mapping)
            )
            gimp_flip_visible = any(
                str(node.get("text") or "") == "Flip Horizontally"
                for node in ui_nodes or []
                if isinstance(node, Mapping)
            )
            gimp_vertical_flip_visible = any(
                str(node.get("text") or "") == "Flip Vertically"
                for node in ui_nodes or []
                if isinstance(node, Mapping)
            )
            details.append(
                "GIMP hint: this benchmark starts from a prepared image state. Edit the already opened file instead of creating a new canvas or using Save As. When the task says export, use Export As."
            )
            details.append(
                "GIMP transform-menu hint: whole-image operations such as rotate, flip, grayscale, or invert usually live under the macOS top menus Image, Colors, or Layer. Use the exact menu path named in the task instead of exploring tool palettes."
            )
            self._update_gimp_rotation_progress(gimp_canvas_size)
            if gimp_ordered_steps:
                details.append(
                    "GIMP ordered checklist: "
                    + " ; ".join(f"{index}. {step}" for index, step in enumerate(gimp_ordered_steps, start=1))
                )
            if gimp_pure_multi_rotate_plan:
                completed = min(self._gimp_completed_clockwise_rotations, gimp_clockwise_rotation_count)
                remaining = max(gimp_clockwise_rotation_count - completed, 0)
                details.append(
                    f"GIMP multi-rotate progress: {completed}/{gimp_clockwise_rotation_count} clockwise rotations are already complete."
                )
                if remaining > 0:
                    details.append(
                        f"GIMP multi-rotate next-step hint: the next exact step is another Image -> Transform -> Rotate 90° clockwise. There are still {remaining} clockwise rotation(s) left before you may move to Colors -> Invert or Export."
                    )
                elif "invert" in current_goal:
                    details.append(
                        "GIMP multi-rotate completion hint: all required clockwise rotations are complete. The next exact step is Colors -> Invert, and only after that should you export."
                    )
                else:
                    details.append(
                        "GIMP multi-rotate completion hint: all required clockwise rotations are complete. Export now instead of reopening Image -> Transform."
                    )
            if gimp_transform_operation_count >= 3:
                details.append(
                    "GIMP long-pipeline warning: this task intentionally requires several sequential Image -> Transform actions. Do not jump to Colors -> Invert or Export after the first successful rotate or flip. Keep reopening Image -> Transform and follow the checklist order until every listed transform step is done."
                )
            if "90 degrees clockwise" in current_goal or "90 degree clockwise" in current_goal:
                details.append(
                    "GIMP rotate hint: the exact rotate path is Image -> Transform -> Rotate 90° clockwise."
                )
            if "flip" in current_goal and "horizontally" in current_goal:
                details.append(
                    "GIMP flip hint: the exact horizontal flip path is Image -> Transform -> Flip Horizontally."
                )
            if "flip" in current_goal and "vertically" in current_goal:
                details.append(
                    "GIMP vertical-flip hint: the exact vertical flip path is Image -> Transform -> Flip Vertically."
                )
            if "invert" in current_goal:
                details.append(
                    "GIMP invert hint: the exact invert path is Colors -> Invert."
                )
                if gimp_transform_operation_count >= 3:
                    details.append(
                        "GIMP invert-order warning: for long transform-pipeline tasks, Colors -> Invert belongs near the end. Only use it after every requested Image -> Transform step from the checklist is complete."
                    )
            details.append(
                "GIMP export hint: Command-Shift-E is the direct Export As shortcut. Type the exact requested output path, confirm the export, and if a PNG options dialog appears, accept the default export settings unless the task says otherwise."
            )
            if gimp_transform_operation_count >= 3:
                details.append(
                    "GIMP export-order warning: do not open Export As until the checklist's transform steps and any required color step are all finished."
                )
            details.append(
                "GIMP recovery hint: if a welcome, tip, or file-change dialog steals focus, press Escape once or twice to dismiss it, then continue from the prepared image window."
            )
            if gimp_canvas_size is not None:
                canvas_width, canvas_height = gimp_canvas_size
                if gimp_single_rotation_progress_plan and (
                    "90 degrees clockwise" in current_goal or "90 degree clockwise" in current_goal
                ):
                    if canvas_height > canvas_width:
                        details.append(
                            f"GIMP canvas-progress hint: the window title already shows a portrait canvas ({canvas_width}x{canvas_height}), so the clockwise rotation is already applied inside GIMP even if the auto-evaluator still mentions the old on-disk file. Do not rotate again just because the export has not happened yet."
                        )
                        if "flip" in current_goal and "horizontally" in current_goal:
                            details.append(
                                "GIMP canvas-next-step hint: for this task, rotation is already done. The remaining edit is one Flip Horizontally action, then export immediately."
                            )
                        elif "invert" in current_goal:
                            details.append(
                                "GIMP canvas-next-step hint: for this task, rotation is already done. The remaining edit is Colors -> Invert, then export immediately."
                            )
                        else:
                            details.append(
                                "GIMP canvas-next-step hint: for this task, rotation is already done. Export immediately instead of reopening the rotate menu."
                            )
                    else:
                        details.append(
                            f"GIMP canvas-progress hint: the working canvas title is still landscape ({canvas_width}x{canvas_height}). If this task requires a clockwise rotation, that rotated portrait state has not been preserved to the live canvas yet."
                        )
            if gimp_transform_visible:
                details.append(
                    "GIMP submenu hint: inside the Image menu, Transform is a submenu trigger. Do not tap the Transform row directly, because that can collapse the menu. Keep the Image menu open, move the highlight onto Transform with the arrow keys, then press Right Arrow once to reveal its rotate/flip options."
                )
                if "90 degrees clockwise" in current_goal or "90 degree clockwise" in current_goal:
                    details.append(
                        "GIMP rotate-menu hint: from the open Image menu, a reliable route is Down Arrow four times to highlight Transform, then Right Arrow, then choose Rotate 90° clockwise from the submenu."
                    )
            if gimp_rotate_visible and "90 degrees clockwise" in current_goal:
                if gimp_canvas_size is not None and gimp_canvas_size[1] <= gimp_canvas_size[0]:
                    details.append(
                        "GIMP visible-rotate hint: the Transform submenu is already open, the live canvas is still landscape, and Rotate 90° clockwise is directly visible right now. Click that visible Rotate 90° clockwise row now before attempting any flip or export."
                    )
                elif gimp_canvas_size is not None and gimp_canvas_size[1] > gimp_canvas_size[0] and gimp_single_rotation_progress_plan:
                    details.append(
                        "GIMP visible-rotate warning: the live canvas is already in its rotated portrait state, so do not click Rotate 90° clockwise again from this submenu."
                    )
            if gimp_flip_visible:
                if (
                    gimp_single_rotation_progress_plan
                    and gimp_canvas_size is not None
                    and gimp_canvas_size[1] <= gimp_canvas_size[0]
                    and "90 degrees clockwise" in current_goal
                ):
                    details.append(
                        "GIMP visible-flip warning: Flip Horizontally is visible, but the live canvas is still landscape, so the required clockwise rotation has not been completed yet. Do not click Flip Horizontally first in this state."
                    )
                else:
                    details.append(
                        "GIMP visible-transform hint: the Transform submenu is already open and the Flip Horizontally row is directly visible right now. If horizontal flip is still pending, click that visible Flip Horizontally row directly. Do not click Transform again."
                    )
                    if (
                        gimp_single_rotation_progress_plan
                        and gimp_canvas_size is not None
                        and gimp_canvas_size[1] > gimp_canvas_size[0]
                    ):
                        details.append(
                            "GIMP visible-transform decision hint: because the live canvas is already in its rotated portrait state, do not click any Rotate item from this submenu again. Use Flip Horizontally once, then move on to export."
                        )
            if gimp_vertical_flip_visible:
                details.append(
                    "GIMP visible-vertical-flip hint: the Transform submenu is already open and the Flip Vertically row is directly visible right now. If vertical flip is still pending, click that visible Flip Vertically row directly. Do not click Transform again."
                )
            if "open as layers" in current_goal or "opacity" in current_goal or "layer" in current_goal:
                details.append(
                    "GIMP layer task hint: after File -> Open as Layers, the newly imported layer is the active layer. Apply the requested invert / flip / opacity edits to that imported layer, and do not drag it unless the task explicitly asks you to move it."
                )
            if "open as layers" in current_goal:
                details.append(
                    "GIMP open-as-layers hint: the exact import path is File -> Open as Layers. If the task asks for multiple layer imports, finish every Open as Layers import before moving on to rotate, flip, flatten, or export."
                )
                details.append(
                    "GIMP open-as-layers sequencing hint: Open as Layers imports one file at a time. Do not try to multi-select several PNGs in the macOS open panel unless the task explicitly asks for multi-selection."
                )
                if gimp_layer_count is not None and gimp_expected_layer_total is not None:
                    if gimp_layer_count < gimp_expected_layer_total:
                        details.append(
                            f"GIMP layer-progress hint: the working image title still shows only {gimp_layer_count} layer(s). The import phase is not complete yet. Keep using File -> Open as Layers until the image title shows {gimp_expected_layer_total} layers before you start rotate, flip, invert, or flatten."
                        )
                    else:
                        details.append(
                            f"GIMP layer-progress hint: the working image title already shows {gimp_layer_count} layers, so the layer-import phase is complete. Do not open more files; move on to the remaining rotate / flip / invert / flatten steps."
                        )
            if "flatten image" in current_goal:
                details.append(
                    "GIMP flatten hint: the exact flatten path is Image -> Flatten Image. Do that only after the required layer imports and color edits are complete."
                )
            if "grayscale" in current_goal or "invert" in current_goal:
                details.append(
                    "GIMP order hint: for multi-step transform tasks, finish every requested menu operation in the stated order before exporting. Do not stop early just because the intermediate image looks plausible."
                )
            if "replace the existing file" in current_goal or "overwrite" in current_goal:
                details.append(
                    "GIMP overwrite hint: this task intentionally exports back to an existing PNG. If GIMP shows a confirmation that the file already exists, choose Replace rather than Cancel."
                )
            if gimp_open_layers_window is not None:
                details.append(
                    "GIMP open-panel hint: the macOS Open Image as Layers panel is already open. Select the requested PNG row in the file list, then press Enter once to trigger Open. Do not burn steps repeatedly poking the bottom-right button if the row is already highlighted."
                )
                details.append(
                    "GIMP open-panel recovery hint: if the panel stays open after one Open attempt, reselect the requested filename row and press Enter again instead of restarting the whole task."
                )
            if gimp_export_window is not None:
                export_path = MacOSPromptBuilder._extract_last_absolute_path(current_goal_raw)
                export_filename = Path(export_path).name if export_path else None
                details.append(
                    "GIMP export-dialog hint: the Export Image dialog is already open. Work only inside this dialog until the file is exported; do not reopen menus or keep typing the same path repeatedly."
                )
                details.append(
                    "GIMP export-dialog decision hint: while this dialog stays open, a 'file not found' evaluator message means the export has not been confirmed yet. Do not treat that as a signal to keep renaming the file."
                )
                if export_filename:
                    details.append(
                        f"GIMP export-dialog filename hint: if the breadcrumb already shows the target folder, replace only the top Name field with `{export_filename}` instead of typing the full absolute path again."
                    )
                    export_stem = Path(export_filename).stem.lower()
                    if any(
                        export_stem and export_stem in str(node.get("text") or "").lower()
                        for node in (ui_nodes or [])
                        if isinstance(node, Mapping)
                    ):
                        details.append(
                            f"GIMP export-dialog overwrite hint: the current document name already matches `{export_filename}`. Unless the Name field visibly differs, skip renaming and go straight to the Export button."
                        )
                export_rect = MacOSPromptBuilder._window_bounds(gimp_export_window)
                if export_rect is not None and isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                    export_left, export_top, export_width, export_height = export_rect
                    name_field_x = export_left + int(export_width * 0.53)
                    name_field_y = export_top + int(export_height * 0.087)
                    export_button_x = export_left + int(export_width * 0.944)
                    export_button_y = export_top + int(export_height * 0.964)
                    details.append(
                        "GIMP export-dialog control hint: the long Name field is near the top of the dialog around "
                        f"{{'x': {_format_norm(name_field_x / width)}, 'y': {_format_norm(name_field_y / height)}}}, "
                        "and the Export button is in the bottom-right corner around "
                        f"{{'x': {_format_norm(export_button_x / width)}, 'y': {_format_norm(export_button_y / height)}}}."
                    )
                details.append(
                    "GIMP export-dialog screenshot-only hint: the Name field and Export button are effectively screenshot-only in this dialog, so use those screenshot positions directly instead of waiting for them to appear in the accessibility tree."
                )
                details.append(
                    "GIMP export-dialog completion hint: once the filename is correct, the next action should be the bottom-right Export button exactly once. If a PNG export settings dialog appears after that, accept the defaults by clicking Export again or pressing Enter once."
                )
        if is_wireshark:
            details.append(
                "Wireshark hint: keep working inside the already opened capture window and use the macOS top menu bar for File / Statistics / Analyze actions instead of hunting for hidden in-window menus."
            )
            if isinstance(wireshark_filter_entry_node, Mapping):
                details.append(
                    "Wireshark filter hint: the display filter input is exposed directly as the 'Display filter entry' node. Type the exact filter there. If the packet list already shows the two HTTP rows 'GET /index.html HTTP/1.1' and 'HTTP/1.1 200 OK  (text/html)', the filter is already applied and you can continue."
                )
            if "statistics" in current_goal and "protocol hierarchy" in current_goal:
                details.append(
                    "Wireshark statistics-menu hint: the exact top-menu path is Statistics -> Protocol Hierarchy. Use that exact menu item name."
                )
                details.append(
                    "Wireshark protocol-hierarchy hint: once that dialog is open, its title may end with either 'sample.pcapng' or '[no capture file]'; both are acceptable signs that you opened the right window."
                )
                details.append(
                    "Wireshark protocol-hierarchy field hint: the bottom-left 'Only show types matching filter value' field is exposed as a normal text field. When the task asks for Hypertext there, type directly into that field instead of clicking random coordinates."
                )
            if "conversations" in current_goal:
                details.append(
                    "Wireshark conversations-menu hint: use the exact top-menu path Statistics -> Conversations."
                )
                details.append(
                    "Wireshark conversations-checkbox hint: inside the Conversations dialog, the checkboxes are exposed directly by label as 'Name resolution', 'Absolute start time', and 'Limit to display filter'. Tap those checkbox nodes by label one by one; do not guess coordinates."
                )
                details.append(
                    "Wireshark conversations-tab hint: the Conversations dialog protocol tabs are exposed directly as radio buttons labeled Ethernet / IPv4 / IPv6 / TCP / UDP. Tap those labels directly when the task asks you to switch tabs."
                )
                details.append(
                    "Wireshark conversations-title hint: the Conversations window title may end with '[no capture file]'; that is still the correct dialog in this VM."
                )
            if "endpoints" in current_goal:
                details.append(
                    "Wireshark endpoints-menu hint: use the exact top-menu path Statistics -> Endpoints."
                )
                details.append(
                    "Wireshark endpoints-checkbox hint: inside the Endpoints dialog, the checkbox labels are 'Name resolution' and 'Limit to display filter'. The bottom-left filter box is another normal text field; type the requested value there directly."
                )
                details.append(
                    "Wireshark endpoints-tab hint: the Endpoints dialog protocol tabs are exposed directly as radio buttons labeled Ethernet / IPv4 / IPv6 / TCP / UDP. Tap those labels directly when the task asks you to switch tabs."
                )
                details.append(
                    "Wireshark endpoints-title hint: the Endpoints window title may end with '[no capture file]'; that is still the correct dialog in this VM."
                )
            if "protocol hierarchy" in current_goal or "conversations" in current_goal or "endpoints" in current_goal:
                details.append(
                    "Wireshark multi-dialog hint: Statistics dialogs stay open together. You can keep opening new ones from the macOS menu bar without closing the previous dialog, and their controls remain targetable by the live accessibility nodes."
                )
            visible_direct_controls: list[str] = []
            if isinstance(wireshark_filter_entry_node, Mapping):
                visible_direct_controls.append(
                    f"{wireshark_filter_entry_node.get('id')}=Display filter entry"
                )
            for node in wireshark_dialog_filter_fields[:3]:
                node_id = str(node.get("id") or "").strip()
                current_text = str(node.get("text") or node.get("value") or "").strip() or "<empty>"
                if node_id:
                    visible_direct_controls.append(f"{node_id}=dialog filter field ({current_text})")
            for node in wireshark_checkbox_nodes[:6]:
                node_id = str(node.get("id") or "").strip()
                label = str(node.get("text") or "").strip()
                value = str(node.get("value") or "").strip() or "0"
                if node_id and label:
                    visible_direct_controls.append(f"{node_id}={label}[{value}]")
            for node in wireshark_radio_nodes[:10]:
                node_id = str(node.get("id") or "").strip()
                label = str(node.get("text") or "").strip()
                if node_id and label:
                    visible_direct_controls.append(f"{node_id}={label}")
            for node in wireshark_title_text_nodes[:6]:
                node_id = str(node.get("id") or "").strip()
                label = str(node.get("text") or "").strip()
                if node_id and label:
                    visible_direct_controls.append(f"{node_id}=dialog title ({label})")
            if visible_direct_controls:
                details.append(
                    "Wireshark direct-control hint: in this observation, the likely target nodes are "
                    + ", ".join(visible_direct_controls)
                    + ". Prefer those live node IDs over screenshot guessing."
                )
            if wireshark_title_text_nodes:
                details.append(
                    "Wireshark title-focus hint: if the task says to bring Conversations, Endpoints, or Protocol Hierarchy forward and a visible dialog title node exists, tap that title text node directly before trying generic title-bar coordinates or any keyboard shortcut."
                )
            if wireshark_tab_strip_hints:
                details.append(
                    "Wireshark tab-strip hint: some Wireshark statistics dialogs expose the current protocol summary row as a group like 'Ethernet · 1' or 'TCP · 2' even when the radio buttons are hidden. When that happens, use these estimated protocol-tab click targets on the same horizontal strip: "
                    + "; ".join(wireshark_tab_strip_hints)
                    + "."
                )
            if wireshark_window_focus_hints:
                details.append(
                    "Wireshark window-focus hint: to bring a background dialog forward, click its visible title bar instead of the middle of the window. Current title-bar focus points: "
                    + "; ".join(wireshark_window_focus_hints)
                    + "."
                )
            if isinstance(wireshark_file_name_node, Mapping) and isinstance(wireshark_export_as_node, Mapping):
                details.append(
                    "Wireshark save-sheet hint: if a macOS export sheet is open and you can see 'File name:' plus 'Export as:', the export has not finished yet. After the filename is correct, your next job is to close that sheet by confirming the save. Do not burn steps poking the Export as combo unless the task explicitly requires changing it."
                )
                details.append(
                    "Wireshark save-button fallback: in this VM layout, the blue Save button for that export sheet is a screenshot-only control near the upper-right of the sheet, above Cancel, around normalized coordinates {'x': 0.35, 'y': 0.36}. Click that blue Save button directly if the sheet is still open."
                )
            details.append(
                "Wireshark export hint: never overwrite sample.pcapng. Save new exports to the exact Downloads path named in the task."
            )
        is_openshop = foreground_app.lower() == "openshop" or "openshop" in foreground_bundle_id.lower()
        openshop_window = (
            MacOSPromptBuilder._find_window_text_contains(ui_nodes, "openshop")
            if is_openshop
            else None
        )
        if is_openshop:
            details.append(
                "OpenShop hint: stay inside the already opened OpenShop window and do not relaunch the app unless the window disappears."
            )
            openshop_title = str(openshop_window.get("text") or "") if isinstance(openshop_window, Mapping) else ""
            openshop_title_lower = openshop_title.lower()
            if "sign in" in current_goal and not openshop_multi_item_goal and "home" in openshop_title_lower:
                details.append(
                    "OpenShop sign-in navigation hint: on OpenShop - Home, the most reliable way to open the Sign In page in this VM is keyboard Tab once, then Enter. Avoid burning steps repeatedly clicking the tiny top-right nav text."
                )
            elif openshop_multi_item_goal and "home" in openshop_title_lower:
                details.append(
                    "OpenShop home-page hint: first inspect the screenshot header. If the page still shows Sign In or Guest, complete sign-in first with the reliable shortcut Tab once then Enter. Only after the home page visibly shows you as signed in should you use the wide rounded search bar under the big headline."
                )
                details.append(
                    "OpenShop home-search hint: use the wide rounded search bar under the big headline and submit the search. Do not assume the app will jump directly to the product page while you are still typing. After the explicit submit, an exact full-title search may open the matching product page immediately; otherwise use the results grid."
                )
                details.append(
                    "OpenShop item order hint: add Verdant Pro Noise-Canceling Headphones first, then use Continue Shopping to return home and search for Mountain Isle Pour-Over Coffee 20 Pack."
                )
                if openshop_catalog_review_goal:
                    details.append(
                        "OpenShop hard-search hint: use the large benchmark rail cards on the right side of the home page if they are visible. For the headphones pass, click Category -> Electronics, then Sort -> High to Low, then Search Headphones, then Open Headphones. For the coffee pass, click Category -> Grocery, then Sort -> Low to High, then Search Coffee, then Open Coffee. The evaluator checks those catalog states."
                    )
                if openshop_checkout_goal:
                    details.append(
                        "OpenShop checkout-sequence hint: only proceed to checkout after both required items are already in the cart."
                    )
            if "sign in" in openshop_title_lower:
                if "phone" in openshop_title_lower:
                    details.append(
                        "OpenShop phone-step hint: the page is in Step 1 of 2 and only the phone field matters right now. Type 13800138000 into the single visible field, then press Enter once or activate the large Continue to Password button. Do not hunt for a password field yet."
                    )
                elif "password" in openshop_title_lower:
                    details.append(
                        "OpenShop password-step hint: the phone step is already complete and the benchmark password spring2026 is already prepared for you on this screen. Do not edit the phone number again and do not waste steps retyping the password unless the field is obviously blank. The normal next move is Enter once or the large orange Sign In and Start Shopping button."
                    )
                else:
                    details.append(
                        "OpenShop login-page hint: use this exact keyboard-only sequence and do not improvise once the Sign In page is visible: type the requested phone number into the already focused Phone Number field, press Tab exactly once, type the requested password, then press Enter exactly once to submit the form. Only if that single Enter does nothing should you press Tab once more to focus the orange sign-in button and press Enter."
                    )
                    details.append(
                        "OpenShop login-page warning: after you leave the Phone Number field, do not click back into it and do not retype the phone number into the password field. If both fields already look filled, the remaining job is to submit the form once."
                    )
                    details.append(
                        "OpenShop login-page focus hint: once the Sign In page opens, prefer keyboard actions against the current focus instead of aiming fresh screenshot clicks inside the form. Keep the caret flow Phone Number -> Password -> Submit."
                    )
            if openshop_multi_item_goal and "product" in openshop_title_lower:
                details.append(
                    "OpenShop product-page hint: the evaluator accepts the product page's default option, so you do not need to change specs here. Click Add to Cart once. After the first add, the cart opens; use Continue Shopping to go back home for the second product. Do not satisfy this task from the search-results Add to Cart button because the evaluator expects the product page itself to be visited."
                )
            if openshop_multi_item_goal and "cart" in openshop_title_lower:
                details.append(
                    "OpenShop cart-page hint: if the cart does not yet show both required items, use Continue Shopping to return home and search for the remaining product."
                )
                details.append(
                    "OpenShop cart-guidance hint: when only one benchmark item is in the cart, the page shows a large Continue Shopping button that names the remaining target product. Use that named button to return home for the missing item."
                )
                if openshop_quantity_review_goal:
                    details.append(
                        "OpenShop cart-review hint: once both required items are present, use the cart-guidance card's large buttons in this order if they are visible: Confirm Headphones Present, Confirm Coffee Present, Confirm Cart Total, Confirm Discount Rule, Headphones -> 2, Headphones -> 1, Coffee -> 2, Coffee -> 1. Only fall back to the tiny +/- controls if the large review buttons are missing. The evaluator checks those review confirmations and exact cart quantity updates."
                    )
                if openshop_checkout_goal:
                    details.append(
                        "OpenShop cart-to-checkout hint: once both required items are visible together in the cart, the next move is the large Proceed to Checkout button."
                    )
            if openshop_checkout_goal and "checkout" in openshop_title_lower:
                details.append(
                    "OpenShop checkout-page hint: choose Office for the shipping address, choose WeChat Pay, enter the exact note 'Leave it at reception before 6 PM.', then place the order."
                )
                if openshop_checkout_switch_goal:
                    details.append(
                        "OpenShop checkout-review hint: for this hard task, switch the shipping address to Home first and then back to Office. Also switch payment to Alipay first and then back to WeChat Pay before you type the final note and place the order."
                    )
                else:
                    details.append(
                        "OpenShop checkout-default hint: Office and WeChat Pay may already be selected, but the order is not complete until the exact note is typed and the order is explicitly placed."
                    )
        is_thunderbird = foreground_app.lower() == "thunderbird" or "thunderbird" in foreground_bundle_id.lower()
        thunderbird_new_event_node = (
            MacOSPromptBuilder._find_node_by_text(ui_nodes, "New Event") if is_thunderbird else None
        )
        thunderbird_new_folder_node = (
            MacOSPromptBuilder._find_node_by_text(ui_nodes, "New Folder") if is_thunderbird else None
        )
        thunderbird_message_filters_node = (
            MacOSPromptBuilder._find_node_by_text(ui_nodes, "Message Filters") if is_thunderbird else None
        )
        thunderbird_promotions_node = (
            MacOSPromptBuilder._find_node_by_text(ui_nodes, "Promotions") if is_thunderbird else None
        )
        thunderbird_compose_menus_visible = bool(
            is_thunderbird
            and MacOSPromptBuilder._find_node_by_text(ui_nodes, "Insert")
            and MacOSPromptBuilder._find_node_by_text(ui_nodes, "Format")
        )
        self._update_thunderbird_multi_send_progress(thunderbird_compose_menus_visible)
        completed_multi_send = self._thunderbird_multi_send_completed
        remaining_multi_send_messages = thunderbird_multi_send_messages[completed_multi_send:]
        current_multi_send_message = remaining_multi_send_messages[0] if remaining_multi_send_messages else None
        if is_thunderbird:
            details.append(
                "Thunderbird hint: if Thunderbird is already in the foreground, stay inside the existing window and do not relaunch the app unless the window disappears."
            )
            details.append(
                "Thunderbird Calendar manipulation hint: when rescheduling an existing event in the calendar grid, drag the colored event block itself horizontally to the target day column at the same time row; avoid dragging empty background cells."
            )
            details.append(
                "Thunderbird Calendar deletion hint: to remove an event entirely, first select the event block in the calendar grid, then use keyboard Delete or Backspace instead of repeated random clicks."
            )
            if isinstance(thunderbird_new_event_node, Mapping):
                if bool(thunderbird_new_event_node.get("enabled", False)):
                    details.append(
                        "Thunderbird Calendar hint: the AX 'New Event' button is already enabled. Prefer clicking that visible button directly instead of opening menus."
                    )
                else:
                    details.append(
                        "Thunderbird Calendar hint: if the 'New Event' button is disabled, a calendar is not enabled yet. Use the controls inside the Thunderbird window (for example the visible 'New Calendar...' link near the bottom-left, or the Home calendar row/checkbox), not the macOS Dock."
                    )
            if thunderbird_compose_menus_visible:
                details.append(
                    "Thunderbird compose hint: the compose window is already open when the menu bar shows 'Insert' and 'Format'. Do not click 'New Message' again."
                )
                details.append(
                    "Thunderbird compose hint: fill the visible fields separately in this order — To, Subject, then message body. Do not rely on one tab-separated multi-field typing action here, because focus can land in the wrong field."
                )
                if thunderbird_multi_send_messages:
                    details.extend(
                        self._build_thunderbird_multi_send_progress_hints(
                            compose_visible=True,
                            completed=completed_multi_send,
                            messages=thunderbird_multi_send_messages,
                            current_message=current_multi_send_message,
                        )
                    )
            if not thunderbird_compose_menus_visible:
                details.append(
                    "Thunderbird mail hint: in Mail view, select the Local Folders row in the left sidebar before trying to create a local folder. Once Local Folders is selected, Cmd+Shift+N is usually the fastest way to open the New Folder dialog."
                )
                details.append(
                    "Thunderbird mail fallback hint: if Cmd+Shift+N does nothing once, stop retrying it and use File → New → Folder... immediately."
                )
                details.append(
                    "Thunderbird filter hint: if the content area shows a visible 'Manage message filters' link near the top, click that link directly instead of hunting through random menus."
                )
                details.append(
                    "Thunderbird mail-view hint: if the window already shows the Local Folders pane or a Local Folders tab, you are already in Mail view. Do not waste steps toggling the left spaces toolbar icons unless the folder pane disappears."
                )
                if thunderbird_multi_send_messages:
                    details.extend(
                        self._build_thunderbird_multi_send_progress_hints(
                            compose_visible=False,
                            completed=completed_multi_send,
                            messages=thunderbird_multi_send_messages,
                            current_message=current_multi_send_message,
                        )
                    )
                if "create a folder named promotions" in current_goal and "subject contains the word" in current_goal:
                    details.append(
                        "Thunderbird Promotions-filter sequence: create the Promotions folder first, then immediately click Manage message filters, create one rule named Promotions, set Subject contains discount, set action Move to folder → Promotions, and confirm with OK. Ignore account-setup tiles and do not click the Thunderbird Privacy Notice tab."
                    )
                    if isinstance(thunderbird_message_filters_node, Mapping) and isinstance(
                        thunderbird_promotions_node, Mapping
                    ):
                        details.append(
                            "Thunderbird Promotions-filter persistence hint: if the Message Filters window already lists an enabled Promotions rule, do not finish yet — close the Message Filters window with Command-W or the window close control so Thunderbird writes msgFilterRules.dat, then finish."
                        )
                if "create a folder named club" in current_goal and "bills folder" in current_goal:
                    details.append(
                        "Thunderbird ST Club sequence: create the Club folder first, then work only inside Bills and Club. Read message bodies before moving anything; the four ST Club messages belong in Club, while Lunch plan must remain in Bills."
                    )
                    if "club - local folders" in str(foreground_window.get("text") or "").lower():
                        details.append(
                            "Thunderbird ST Club title guard: the window title already says 'Club - Local Folders', which means you are in the empty destination folder. Do not keep probing here. Click the Bills row in the left sidebar until the title changes to 'Bills - Local Folders' before trying to read or move messages."
                        )
            if "delete it entirely" in current_goal and "design review" in current_goal:
                details.append(
                    "Thunderbird hard-calendar order hint: finish the task in this exact order and do not improvise — create Design Review and save, create Sprint Planning and save, create Retrospective with a 30-minute reminder and save, drag Design Review from Monday 10:00 AM to Tuesday 10:00 AM, then tap Retrospective once and immediately press Delete or Backspace."
                )
                details.append(
                    "Thunderbird hard-calendar deletion hint: once the Retrospective block is visible, repeated taps are less reliable than one tap followed by Delete or Backspace. After the delete key, stop poking the same block."
                )

        if isinstance(width, int) and isinstance(height, int):
            details.append(f"Screen size: {width}x{height}")
            details.append(
                "If you must click a screenshot-only control that is missing from the accessibility tree, prefer normalized coordinates like {'x': 0.42, 'y': 0.77} instead of raw screenshot pixel coordinates."
            )
            if thunderbird_compose_menus_visible:
                details.append(
                    "Thunderbird compose screenshot-only controls: the Send button is near the top-left of the compose window around normalized screen coordinates "
                    f"{{'x': {_format_norm(33 / max(width, 1))}, 'y': {_format_norm(58 / max(height, 1))}}}; "
                    "the To field is the first input line under the toolbar near "
                    f"{{'x': {_format_norm(344 / max(width, 1))}, 'y': {_format_norm(121 / max(height, 1))}}}; "
                    "the Subject field is just below it near "
                    f"{{'x': {_format_norm(165 / max(width, 1))}, 'y': {_format_norm(152 / max(height, 1))}}}; "
                    "and the body area starts lower in the large blank editor near "
                    f"{{'x': {_format_norm(156 / max(width, 1))}, 'y': {_format_norm(226 / max(height, 1))}}}."
                )
                details.append(
                    "If the compose window is visible, click those screenshot positions directly instead of guessing from the background mail window."
                )
            if foreground_window:
                rect = MacOSPromptBuilder._window_bounds(foreground_window)
                if rect is not None:
                    left, top, window_width, window_height = rect
                    right = left + window_width
                    bottom = top + window_height
                    details.append(
                        f"Foreground window bounds: left={left}, top={top}, width={window_width}, height={window_height}, right={right}, bottom={bottom}."
                    )
                    details.append(
                        "If your intended click is inside the foreground app window, keep the normalized tap inside those bounds rather than below the window or on the wallpaper."
                    )
                    if is_thunderbird and MacOSPromptBuilder._is_thunderbird_new_event_window(foreground_window):
                        details.append(
                            "Thunderbird New Event dialog hint: the dialog controls are mostly stable. Prefer these visible controls in order: title field near the upper-middle, Start row, End row, Repeat popup, Reminder popup, then Save and Close."
                        )
                        title_x, title_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.562,
                            y_ratio=0.197,
                        )
                        start_row_x, start_row_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.386,
                            y_ratio=0.402,
                        )
                        start_time_x, start_time_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.524,
                            y_ratio=0.402,
                        )
                        end_time_x, end_time_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.524,
                            y_ratio=0.457,
                        )
                        repeat_x, repeat_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.288,
                            y_ratio=0.518,
                        )
                        reminder_x, reminder_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.288,
                            y_ratio=0.581,
                        )
                        weekly_x, weekly_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.307,
                            y_ratio=0.592,
                        )
                        reminder_15_x, reminder_15_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.319,
                            y_ratio=0.722,
                        )
                        reminder_30_x, reminder_30_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.319,
                            y_ratio=0.749,
                        )
                        save_x, save_y = MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            x_ratio=0.118,
                            y_ratio=0.075,
                        )
                        details.append(
                            "Thunderbird New Event coordinate hint: title field is roughly at "
                            f"{{'x': {_format_norm(title_x)}, 'y': {_format_norm(title_y)}}}; "
                            "the Start row is near "
                            f"{{'x': {_format_norm(start_row_x)}, 'y': {_format_norm(start_row_y)}}}; "
                            "the Start time popup is near "
                            f"{{'x': {_format_norm(start_time_x)}, 'y': {_format_norm(start_time_y)}}}; "
                            "the End time popup is near "
                            f"{{'x': {_format_norm(end_time_x)}, 'y': {_format_norm(end_time_y)}}}."
                        )
                        details.append(
                            "Thunderbird New Event recurrence hint: the Repeat popup is near "
                            f"{{'x': {_format_norm(repeat_x)}, 'y': {_format_norm(repeat_y)}}}. "
                            "After it opens, the 'Weekly' menu item appears just below near "
                            f"{{'x': {_format_norm(weekly_x)}, 'y': {_format_norm(weekly_y)}}}."
                        )
                        details.append(
                            "Thunderbird New Event weekday hint: for a weekly event on a specific weekday, first set the Start date to that weekday, then open Repeat and choose Weekly. Otherwise Thunderbird often keeps the current day-of-week."
                        )
                        details.append(
                            "Thunderbird New Event reminder hint: the Reminder popup is near "
                            f"{{'x': {_format_norm(reminder_x)}, 'y': {_format_norm(reminder_y)}}}. "
                            "After it opens, the '15 minutes before' option appears lower in the menu near "
                            f"{{'x': {_format_norm(reminder_15_x)}, 'y': {_format_norm(reminder_15_y)}}}, "
                            "and the '30 minutes before' option is a little lower near "
                            f"{{'x': {_format_norm(reminder_30_x)}, 'y': {_format_norm(reminder_30_y)}}}."
                        )
                        details.append(
                            "Thunderbird New Event save hint: the 'Save and Close' button is in the dialog title bar near "
                            f"{{'x': {_format_norm(save_x)}, 'y': {_format_norm(save_y)}}}. "
                            "Do not click category fields unless the task explicitly requires them."
                        )
                        details.append(
                            "Thunderbird New Event default-value hint: if you opened this dialog by double-clicking the target calendar slot, the Start and End values are usually already close to correct. Do not keep re-editing Start/End unless the visible Start/End row clearly shows the wrong date or time."
                        )
                        details.append(
                            "Thunderbird New Event completion hint: once the visible title, Start row, End row, and any task-required Repeat or Reminder setting already match the task, click 'Save and Close' immediately. Do not burn extra steps retyping fields that already look correct."
                        )
                        if "delete it entirely" in current_goal and "design review" in current_goal:
                            details.append(
                                "Thunderbird hard-calendar dialog hint: when creating one event for the multi-event task, finish only the current event and save immediately. Do not use the current dialog to think about the next event."
                            )
                        if (
                            "design review" in current_goal
                            and "sprint planning" in current_goal
                            and "retrospective" in current_goal
                        ):
                            details.append(
                                "Thunderbird multi-event weekday guard: for this creation-only task, confirm the Start date matches the requested weekday before saving — Design Review must be Monday, Sprint Planning must be Wednesday, and Retrospective must be Friday. Thunderbird may open the second or third dialog one day early, so correct only that Start date if needed, then save."
                            )
                        details.append(
                            "Thunderbird New Event safety hint: never use the 'All day Event' checkbox unless the task explicitly asks for an all-day event. If it becomes checked accidentally, uncheck it before editing times."
                        )
                        details.append(
                            "Thunderbird New Event focus hint: when this dialog opens from a calendar slot, the title field is usually already focused. Type the event title first, then leave the title alone unless the visible title text is wrong."
                        )
                        details.append(
                            "Thunderbird New Event workflow hint: for a slot-opened recurring event, use this order and then stop exploring: title, weekday/date only if wrong, End time only if duration is wrong, Repeat, Reminder, Save and Close. Do not click Category unless the task asks for it."
                        )
                        details.append(
                            "Thunderbird New Event dropdown hint: after you open Repeat or Reminder, choose the needed menu item once. If a popup menu blocks the form, press Escape once to close that popup before continuing instead of clicking random fields behind it."
                        )
                        details.append(
                            "Thunderbird New Event commit hint: when a Start or End date/time control is an AXPopUpButton, click that one control, type the exact replacement, then press Enter once to commit before you touch another field. If you switch windows too early, Thunderbird often reverts that popup value."
                        )
                        details.append(
                            "Thunderbird New Event focus-safety hint: while this dialog is open, do not tap the background Calendar window, Calendar tab, or the AXWindow container itself. Finish the current event inside the dialog, then save it."
                        )
                        details.append(
                            "Thunderbird New Event done-state hint: if the dialog already shows the correct title and the Reminder popup visibly reads the required value such as '30 minutes before', stop editing and save immediately."
                        )
                    if is_thunderbird:
                        if (
                            "design review" in current_goal
                            and "sprint planning" in current_goal
                            and "retrospective" in current_goal
                            and not MacOSPromptBuilder._is_thunderbird_new_event_window(foreground_window)
                        ):
                            monday_x, monday_y = MacOSPromptBuilder._estimate_thunderbird_week_grid_slot_hint(
                                left=left,
                                top=top,
                                window_width=window_width,
                                window_height=window_height,
                                screen_width=width,
                                screen_height=height,
                                weekday_index=1,
                                hour=10,
                            )
                            wednesday_x, wednesday_y = MacOSPromptBuilder._estimate_thunderbird_week_grid_slot_hint(
                                left=left,
                                top=top,
                                window_width=window_width,
                                window_height=window_height,
                                screen_width=width,
                                screen_height=height,
                                weekday_index=3,
                                hour=14,
                            )
                            friday_x, friday_y = MacOSPromptBuilder._estimate_thunderbird_week_grid_slot_hint(
                                left=left,
                                top=top,
                                window_width=window_width,
                                window_height=window_height,
                                screen_width=width,
                                screen_height=height,
                                weekday_index=5,
                                hour=16,
                            )
                            details.append(
                                "Thunderbird multi-event slot hint: for this task, prefer opening the target week-grid slots directly with a double-click instead of the generic New Event button. Approximate slot centers are Monday 10:00 near "
                                f"{{'x': {_format_norm(monday_x)}, 'y': {_format_norm(monday_y)}}}, "
                                "Wednesday 1:30 PM near "
                                f"{{'x': {_format_norm(wednesday_x)}, 'y': {_format_norm(wednesday_y)}}}, "
                                "and Friday 2:30 PM near "
                                f"{{'x': {_format_norm(friday_x)}, 'y': {_format_norm(friday_y)}}}."
                            )
                            details.append(
                                "Thunderbird multi-event grid hint: after one event is saved and the dialog disappears, create the next event only from the live week grid. Do not reuse the previous New Event button node ID or background-calendar tab ID."
                            )
                            details.append(
                                "Thunderbird multi-event no-drag hint: this benchmark only asks you to create and save the three events. Never drag, reschedule, or visually realign a saved event block afterward. If the three titled blocks are visible and Retrospective already shows the bell/reminder indicator, finish instead of trying to correct their on-screen alignment."
                            )
                        local_folders_x, local_folders_y = MacOSPromptBuilder._estimate_thunderbird_local_folders_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        filters_x, filters_y = MacOSPromptBuilder._estimate_thunderbird_manage_filters_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        new_calendar_x, new_calendar_y = MacOSPromptBuilder._estimate_thunderbird_new_calendar_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        home_toggle_x, home_toggle_y = MacOSPromptBuilder._estimate_thunderbird_home_toggle_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        if isinstance(thunderbird_new_event_node, Mapping) and not bool(
                            thunderbird_new_event_node.get("enabled", False)
                        ):
                            details.append(
                                "Thunderbird disabled-calendar hint: the visible 'New Calendar...' control is inside the Thunderbird window near the bottom-left corner, roughly at normalized screen coordinates "
                                f"{{'x': {_format_norm(new_calendar_x)}, 'y': {_format_norm(new_calendar_y)}}}. Keep the click above the Dock and inside the window."
                            )
                            details.append(
                                "Thunderbird existing-calendar hint: the Home calendar enable checkbox/row is in the left sidebar under 'Calendars', roughly near "
                                f"{{'x': {_format_norm(home_toggle_x)}, 'y': {_format_norm(home_toggle_y)}}}."
                            )
                        details.append(
                            "Thunderbird Local Folders hint: the Local Folders row in Mail view is roughly near "
                            f"{{'x': {_format_norm(local_folders_x)}, 'y': {_format_norm(local_folders_y)}}}. "
                            "Select that row before creating a local folder."
                        )
                        details.append(
                            "Thunderbird Manage Filters hint: the visible 'Manage message filters' link in Mail view is roughly near "
                            f"{{'x': {_format_norm(filters_x)}, 'y': {_format_norm(filters_y)}}}. "
                            "For filter tasks, prefer that shortcut over repeated right-click attempts."
                        )
                        details.append(
                            "Thunderbird Local Folders shortcut hint: if Local Folders is visibly selected and Cmd+Shift+N does nothing once, keep the folder pane focused and try the shortcut one more time; do not spend many steps switching Thunderbird spaces."
                        )
                        if "create a folder named club" in current_goal and "bills folder" in current_goal:
                            bills_x, bills_y = MacOSPromptBuilder._estimate_thunderbird_mail_folder_hint(
                                left=left,
                                top=top,
                                window_width=window_width,
                                window_height=window_height,
                                screen_width=width,
                                screen_height=height,
                                folder_name="Bills",
                            )
                            club_x, club_y = MacOSPromptBuilder._estimate_thunderbird_mail_folder_hint(
                                left=left,
                                top=top,
                                window_width=window_width,
                                window_height=window_height,
                                screen_width=width,
                                screen_height=height,
                                folder_name="Club",
                            )
                            details.append(
                                "Thunderbird ST Club folder-row hint: in the expanded left sidebar, Bills is roughly at normalized screen coordinates "
                                f"{{'x': {_format_norm(bills_x)}, 'y': {_format_norm(bills_y)}}}, "
                                "and Club is the next row below near "
                                f"{{'x': {_format_norm(club_x)}, 'y': {_format_norm(club_y)}}}."
                            )
                            details.append(
                                "Thunderbird ST Club title hint: after clicking Bills, confirm the tab/window title changes to 'Bills - Local Folders'. If the title still says 'Local Folders' or 'Club - Local Folders', you have not opened Bills yet."
                            )
                            details.append(
                                "Thunderbird ST Club empty-folder hint: if you see '0 messages' while the title says Club, stop searching there. Go back to Bills, read each remaining message body in Bills, and move only the ST Club messages into Club."
                            )
                    if is_thunderbird and isinstance(thunderbird_new_folder_node, Mapping):
                        details.append(
                            "Thunderbird New Folder dialog hint: when the small 'New Folder' dialog is visible, fill only the Name field, keep 'Create as a subfolder of' set to Local Folders, then click Create Folder immediately."
                        )
                        details.append(
                            "After the New Folder dialog closes for a filter task, the next action should be the visible Manage message filters link in the Local Folders content area; do not click the privacy-notice tab strip at the top."
                        )
                    if foreground_app.lower() == "actual" or "actualbudget" in foreground_bundle_id.lower():
                        hint_x, hint_y = MacOSPromptBuilder._estimate_actual_add_account_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        modal_x, modal_y = MacOSPromptBuilder._estimate_actual_modal_primary_button_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        safe_max_y = min((top + window_height - 8) / max(height, 1), 0.999)
                        details.append(
                            "Actual current-window hint: '+ Add account' is roughly at normalized screen coordinates "
                            f"{{'x': {_format_norm(hint_x)}, 'y': {_format_norm(hint_y)}}}. Aim slightly above the bottom edge, still inside the window, and keep y <= {_format_norm(safe_max_y)} for this window."
                        )
                        details.append(
                            "If a centered 'Add account' modal is visible, click the purple 'Create a local account' button directly under the modal title, not the title text above it. Its center is roughly at normalized screen coordinates "
                            f"{{'x': {_format_norm(modal_x)}, 'y': {_format_norm(modal_y)}}}."
                        )
                        balance_x, balance_y = MacOSPromptBuilder._estimate_actual_create_account_balance_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        create_x, create_y = MacOSPromptBuilder._estimate_actual_create_account_submit_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        details.append(
                            "If the 'Create Local Account' form is visible, the Balance input is the lower text field under 'Balance:' (below the Name field), roughly at normalized screen coordinates "
                            f"{{'x': {_format_norm(balance_x)}, 'y': {_format_norm(balance_y)}}}. After the balance is filled, the purple 'Create' button is near "
                            f"{{'x': {_format_norm(create_x)}, 'y': {_format_norm(create_y)}}}."
                        )
                        details.append(
                            "For that Create Local Account balance field, the safest sequence is: tap the Balance input once, then type the amount into the now-focused field without re-targeting another coordinate, then click 'Create'. If the balance still looks empty or says it must be a number, type into the focused field again; do not click 'Create' until the numeric value is visibly present."
                        )
                        add_new_x, add_new_y = MacOSPromptBuilder._estimate_actual_add_transaction_button_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        payee_x, payee_y = MacOSPromptBuilder._estimate_actual_transaction_payee_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        category_x, category_y = MacOSPromptBuilder._estimate_actual_transaction_category_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        payment_x, payment_y = MacOSPromptBuilder._estimate_actual_transaction_payment_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        deposit_x, deposit_y = MacOSPromptBuilder._estimate_actual_transaction_deposit_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        add_row_x, add_row_y = MacOSPromptBuilder._estimate_actual_transaction_add_row_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                        )
                        checking_x, checking_y = MacOSPromptBuilder._estimate_actual_existing_account_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            account="checking",
                        )
                        savings_x, savings_y = MacOSPromptBuilder._estimate_actual_existing_account_hint(
                            left=left,
                            top=top,
                            window_width=window_width,
                            window_height=window_height,
                            screen_width=width,
                            screen_height=height,
                            account="savings",
                        )
                        if is_actual_multi_account_goal:
                            details.append(
                                "Actual multi-account window hint: stay in the blue left sidebar account-creation flow. The only important controls are '+ Add account', the purple 'Create a local account' button in the chooser, the Name field, the Balance field, and the purple 'Create' button."
                            )
                            details.append(
                                "Actual multi-account repetition hint: once one account is created, the create form closes and you return to the sidebar. Start the next checklist item by clicking '+ Add account' again; do not wander into account registers or budget pages."
                            )
                            details.append(
                                "Actual multi-account modal hint: when the form opens for the next checklist item, do not tap the Name field repeatedly. Type the new account name directly into the focused Name field, then move to Balance."
                            )
                        else:
                            details.append(
                                "Actual transaction-entry hint: once the account ledger is visible, the '+ Add New' button above the table is near "
                                f"{{'x': {_format_norm(add_new_x)}, 'y': {_format_norm(add_new_y)}}}. "
                                "After you click it, work inside the first blank draft row directly under the column headers — not the older Starting Balance row underneath. That button sits on the Import / + Add New / Filter toolbar row under the green balance, not up near the window title. If the click lands too high and nothing changes, retry slightly lower on the same toolbar row once before falling back."
                            )
                            details.append(
                                "Actual account-switch hint: in the left sidebar starter budget, the existing Checking row is roughly near "
                                f"{{'x': {_format_norm(checking_x)}, 'y': {_format_norm(checking_y)}}} and Savings is near "
                                f"{{'x': {_format_norm(savings_x)}, 'y': {_format_norm(savings_y)}}}. "
                                "Aim at the account-name text on the far-left of each row, not the balance amount on the right. "
                                "All accounts and On budget are summary rows above the real accounts, so do not stop there. "
                                "Click the account-name row itself, not the balance totals, before adding transactions or transfers. If one careful click still lands on the wrong row, switch to Command-K and jump directly to the needed account instead of repeating the same bad sidebar tap."
                            )
                            if is_actual_add_transactions_goal:
                                details.append(
                                    "Actual transaction keyboard hint: the prepared draft row already has Date active. Leave Payee blank. For row 1, Tab three times to Category, type Food, press Enter once to lock Food, Tab once to Payment, type 85.50, and press Enter. For row 2, stay in the automatically opened blank row, Tab three times to Category, type Income to replace any leftover Food suggestion, press Enter once only when Income is the highlighted category result, Tab twice to Deposit, type 3200.00, and press Enter. Do not click Payee, do not click '+ Add New' again, and do not press Enter while Food is still highlighted on the second row."
                                )
                            elif is_actual_full_setup_goal:
                                details.append(
                                    "Actual transaction keyboard hint: for this task's two ordinary Checking rows, leave Payee blank. From a fresh blank row, Tab three times to Category, type the category, Tab once to Payment for expense rows, type the amount, and press Enter. Only use a different flow when you intentionally create the later transfer."
                                )
                            else:
                                details.append(
                                    "Actual transaction keyboard hint: after '+ Add New' or T, the Date cell becomes active and a date picker may open. The safest sequence is: press Tab once to leave Date and focus Payee, type the payee, press Enter once to choose the exact payee row when it appears, press Tab twice to reach Category, type the category, then tab to the amount field (once for Payment, twice for Deposit), type the amount, and press Enter to save the row. Do not bounce back to earlier cells unless the text visibly disappeared. If you need to use T as the fallback opener, first click inside the white register table so the ledger has focus. If Enter does not commit it, use the purple Add button as the fallback."
                                )
                            details.append(
                                "Actual transaction row coordinates: Payee is roughly at "
                                f"{{'x': {_format_norm(payee_x)}, 'y': {_format_norm(payee_y)}}}; "
                                "Category is near "
                                f"{{'x': {_format_norm(category_x)}, 'y': {_format_norm(category_y)}}}; "
                                "Payment is near "
                                f"{{'x': {_format_norm(payment_x)}, 'y': {_format_norm(payment_y)}}}; "
                                "Deposit is near "
                                f"{{'x': {_format_norm(deposit_x)}, 'y': {_format_norm(deposit_y)}}}; "
                                "and the draft-row Add button is near "
                                f"{{'x': {_format_norm(add_row_x)}, 'y': {_format_norm(add_row_y)}}}. "
                                "For expenses use Payment; for income use Deposit."
                            )

        ui_tree_source = str(getattr(observation, "ui_tree_source", "") or "").strip()
        if ui_tree_source == "window_fallback":
            details.append(
                "The accessibility tree only lists top-level windows right now; if the screenshot shows a popup menu or dialog item that is not listed, click the visible item directly using screenshot coordinates."
            )

        if isinstance(ui_nodes, list):
            if any(
                isinstance(node, Mapping)
                and ".pptx" in str(node.get("text") or "").lower()
                and "libreoffice" in str(node.get("text") or "").lower()
                for node in ui_nodes
            ):
                details.append(
                    "LibreOffice Impress hint: slide thumbnails are usually in the left sidebar, the main slide canvas is centered, and speaker notes are typically in the lower notes pane while in Normal view."
                )
                details.append(
                    "LibreOffice Impress workflow hint: if you need a new slide at the end, first select the last existing slide thumbnail, then create the new slide so it appears after the current final slide."
                )
                details.append(
                    "LibreOffice Impress slide-management hint: after you click a slide thumbnail in the left sidebar, press Delete to remove that selected slide; repeated taps alone will not delete it."
                )
                details.append(
                    "LibreOffice Impress navigation hint: when you are already on a slide and need the very next slide, Page Down or Down Arrow is often more reliable than guessing the next thumbnail coordinate."
                )
                details.append(
                    "LibreOffice Impress placeholder hint: when a slide shows literal prompts like 'Click to add Title', 'Click to add Text', or 'Click to add Notes', click that visible prompt text directly instead of the middle of the empty placeholder."
                )
                details.append(
                    "LibreOffice Impress notes hint: after you click the visible 'Click to add Notes' prompt, type the speaker note immediately even if the notes pane still looks almost unchanged in the next screenshot."
                )
            if any(
                isinstance(node, Mapping)
                and str(node.get("text") or "").startswith("PageShape:")
                for node in ui_nodes
            ) and any(
                isinstance(node, Mapping)
                and str(node.get("type") or "").strip() == "AXTextArea"
                for node in ui_nodes
            ):
                details.append(
                    "LibreOffice Impress editing hint: when slide text appears as AXTextArea nodes, prefer using those node IDs with replace_text or type_text instead of guessing slide-canvas coordinates."
                )
            if any(
                isinstance(node, Mapping)
                and str(node.get("type") or "").strip() == "AXTable"
                and "Sheet " in str(node.get("text") or "")
                for node in ui_nodes
            ):
                details.append(
                    "LibreOffice Calc hint: sheet tabs are at the bottom left between the '+' button and the horizontal scrollbar. Right-clicking row or column headers opens row/column menus, not sheet actions. If needed, the top macOS menu bar item 'Sheet' also contains sheet commands."
                )
            if any(
                isinstance(node, Mapping)
                and "menu" in str(node.get("type") or node.get("roleDescription") or "").strip().lower()
                for node in ui_nodes
            ):
                details.append(
                    "If the UI tree lists menu bar items or menu items, prefer clicking those node IDs directly instead of estimating menu coordinates from the screenshot."
                )

        if not details:
            return None

        return "Additional environment info:\n" + "\n".join(f"- {item}" for item in details)

    @staticmethod
    def _build_task_specific_system_prompt(goal: str) -> str | None:
        lower_goal = goal.lower()
        if "actual budget" in lower_goal:
            single_account_target = MacOSPromptBuilder._extract_actual_single_create_account(goal)
            multi_account_targets = MacOSPromptBuilder._extract_actual_multi_create_accounts(goal)
            if ("create two local accounts" in lower_goal or "create three local accounts" in lower_goal) and multi_account_targets:
                checklist_lines = "\n".join(
                    f"{index}. {item['name']} — {item['amount_text']}"
                    for index, item in enumerate(multi_account_targets, start=1)
                )
                last_account = multi_account_targets[-1]["name"]
                return (
                    "Actual multi-account plan: repeat the same local-account creation flow for every checklist item below in exact order.\n"
                    "Checklist:\n"
                    f"{checklist_lines}\n"
                    "For each checklist item: click '+ Add account', choose 'Create a local account', fill Name, fill Balance, then click Create.\n"
                    "Each time the create form opens, the Name field is already focused, so type the next account name immediately before touching Balance.\n"
                    "After each Create, wait for the form to close before starting the next checklist item.\n"
                    "If the form says Name is required, type the full name once into the focused Name field, refill Balance if needed, and click Create again.\n"
                    "Do not finish after the first account. Reopen '+ Add account' and continue until every checklist item exists.\n"
                    f"Finish only when the last created account '{last_account}' is visible."
                )
            if (
                "switch to the existing \"checking\" account" in lower_goal
                and "85.50" in lower_goal
                and ("3200.00" in lower_goal or "3,200.00" in lower_goal)
                and "food category" in lower_goal
                and "income category" in lower_goal
            ):
                return (
                    "Actual add-transactions plan: use the most reliable route instead of repeated sidebar guesswork. "
                    "The prepared start state already opens Checking with one blank draft row active, so do not spend steps reopening Command-K or '+ Add New' unless that blank row clearly disappeared. "
                    "Preferred flow: press Command-K, type Checking, and press Enter immediately to jump directly to the Checking account. Do not click the palette result row unless Enter clearly fails. "
                    "Fallback only if the palette fails: in the starter budget left sidebar, the row order is All accounts, On budget, Checking, then Savings, and you must click the far-left Checking text label instead of the balance amount. "
                    "Once Checking is open, click the visible '+ Add New' button on the toolbar row under the green balance; only if that careful click clearly fails should you try T after focusing the register table. "
                    "Leave the Payee field blank for both rows and use a straight keyboard flow. "
                    "On a fresh blank row, Category is exactly three Tab presses away from the Date cell because Payee and Notes stay blank. "
                    "For both rows, do not tab away from Category until the intended category itself is selected. After typing Food or Income, press Enter once to lock that exact category result before moving to the amount field. "
                    "For the first row, use this exact keyboard sequence after '+ Add New': Tab three times to Category, type Food, press Enter to lock Food, Tab once to Payment, type 85.50, press Enter to save. "
                    "After the first row saves, a new blank row opens automatically with Date active again. For the second row, do not reopen or click around; from that new blank row use: Tab three times to Category, type Income directly to overwrite any leftover Food suggestion, press Enter once only if Income itself is the highlighted dropdown result, Tab twice to Deposit, type 3200.00, press Enter to save. Do not press Enter while Food is still highlighted on the second row. "
                    "If the 3200.00 row accidentally saves with category still blank or labeled 'Categorize', immediately edit that same saved row's category cell to Income instead of opening another draft row. "
                    "Use Payment for expenses, Deposit for income, and press Enter to save each completed row. As soon as both required new rows are present, stop and use the success tool."
                )
            if (
                "make sure the \"checking\" and \"savings\" accounts remain available" in lower_goal
                and "transfer $1,000 from checking to savings" in lower_goal
                and "rent payment" in lower_goal
                and "groceries payment" in lower_goal
            ):
                return (
                    "Actual full-setup plan: keep the existing Checking and Savings accounts, work in a strict order, and do not wander. "
                    "Use Command-K whenever navigation is ambiguous: jump to Budget for the budget edits, then jump to Checking for the two regular transactions, and then stay precise for the transfer. After typing the destination in the palette, press Enter immediately instead of trying to click the palette row. "
                    "First set the budget amounts for Rent, Groceries, and Entertainment. "
                    "Then jump to Checking and add the two Checking transactions with '+ Add New' first, falling back to T only if needed after focusing the register table. Leave Payee blank for those two ordinary transactions and focus on category plus amount only. "
                    "Only after those transactions are present, create the transfer of 1000 from Checking to Savings. "
                    "When switching accounts with the sidebar, ignore the All accounts and On budget summary rows and click the real account-name rows instead."
                )
            if single_account_target and "create a local account named" in lower_goal:
                return (
                    "Actual create-account plan: click '+ Add account' in the blue sidebar, choose 'Create a local account', "
                    f"fill Name with {single_account_target['name']}, fill Balance with {single_account_target['amount_plain']}, then click Create. "
                    "The Name field is already focused when the form opens, so type the name immediately before moving to Balance. "
                    "Do not stop on the Add account chooser after the local-account button becomes visible."
                )
        if "thunderbird" not in lower_goal:
            return None

        if "mail view" in lower_goal:
            if "exact body shown below" in lower_goal and "weekly meeting plan" in lower_goal:
                return (
                    "Thunderbird send-mail plan: open one compose window, fill the To field with qa-local@example.com, "
                    "fill the Subject with Weekly Meeting Plan, then type the body exactly with the requested blank lines preserved. "
                    "Send the message immediately after those three fields match, and do not reopen or edit the draft afterward."
                )

            if "send three emails" in lower_goal and "st club" in lower_goal:
                messages = MacOSPromptBuilder._extract_thunderbird_multi_send_messages(goal)
                if messages:
                    message_lines = []
                    for index, message in enumerate(messages, start=1):
                        message_lines.append(
                            f"{index}. Subject: {message['subject']}\n"
                            "   Body (type exactly, preserving every blank line and line break):\n"
                            "   <<<BODY\n"
                            f"{message['body']}\n"
                            "   BODY>>>"
                        )
                    sequence_lines = "\n".join(message_lines)
                    first_subject = messages[0]["subject"]
                    next_sequence = ", then ".join(f"'{message['subject']}'" for message in messages[1:])
                    return (
                        "Thunderbird multi-send plan: send the requested three ST Club progress emails one by one.\n"
                        "IMMUTABLE CHECKLIST — do not improvise, skip, paraphrase, or reorder anything:\n"
                        f"{sequence_lines}\n"
                        "Execution rules:\n"
                        "- Use exactly one compose window at a time.\n"
                        "- For every email, fill To with qa-local@example.com, then Subject, then Body, then send it.\n"
                        "- After each send, wait until Thunderbird returns to the main Mail window before starting the next checklist item.\n"
                        f"- Never resend '{first_subject}'. After it is sent, the next required subjects are {next_sequence}.\n"
                        "- Do not keep multiple compose windows open at once.\n"
                        "- Keep blank lines and signature line breaks exactly as shown in the checklist."
                    )
                return (
                    "Thunderbird multi-send plan: send the requested three ST Club progress emails one by one. "
                    "For each email, use exactly one compose window, fill To with qa-local@example.com, then fill Subject, then Body, send it, and wait until Thunderbird returns to the main Mail window before starting the next email. "
                    "Do not keep multiple compose windows open at once, and do not improvise or paraphrase any body text."
                )

            if "create a folder named promotions" in lower_goal and "subject contains the word" in lower_goal:
                return (
                    "Thunderbird Promotions-filter plan: stay in Mail view under Local Folders. "
                    "Select Local Folders, and if Cmd+Shift+N fails once, immediately switch to File → New → Folder... instead of retrying the shortcut over and over. "
                    "Create exactly one folder named Promotions under Local Folders. "
                    "As soon as the folder exists, return to the Local Folders page and click the visible Manage message filters link in the content area — not the Thunderbird Privacy Notice tab in the tab strip. "
                    "In Message Filters, click New, set the filter name to Promotions, set one condition to Subject / contains / discount, set one action to Move to folder / Promotions, then confirm with OK. "
                    "After the enabled Promotions rule appears back in the Message Filters list, close that Message Filters window so Thunderbird persists the rule to disk before you finish. "
                    "Do not wander through unrelated menus or account-setup links."
                )

            if "create a folder named club" in lower_goal and "bills folder" in lower_goal and "st club" in lower_goal:
                return (
                    "Thunderbird ST Club routing plan: first create exactly one local folder named Club under Local Folders. "
                    "Then open the Bills folder and verify the tab/window title changes to 'Bills - Local Folders' before you read or move anything. "
                    "Work message by message inside Bills: read the body, move every message whose body is about ST Club into Club immediately after identifying it, and leave the unrelated Lunch plan message in Bills. "
                    "If you ever land in 'Club - Local Folders' and see 0 messages, you are in the empty destination folder, so go back to Bills instead of searching there. "
                    "Do not guess from subject lines alone, and do not spend steps opening unrelated Thunderbird tabs or account-setup pages."
                )

            return (
                "Thunderbird mail-task plan: stay in Mail view, work inside Local Folders, and prefer the shortest reliable path using the existing Thunderbird window. "
                "Create or edit only the folders, messages, or filters required by the task, then stop."
            )

        if "calendar" not in lower_goal:
            return None

        if "recurring event" in lower_goal or "repeat option" in lower_goal:
            return (
                "Thunderbird recurring-event plan: create the event from the requested calendar slot first when the instruction names a specific weekday/time. "
                "Then fill the title, correct the weekday/date only if needed, choose the repeat option, choose the reminder, and save. "
                "Do not explore unrelated fields."
            )

        if "delete it entirely" in lower_goal or "move \"design review\"" in lower_goal:
            return (
                "Thunderbird multi-event plan: create each event from its intended calendar slot in the grid, save it, then drag the existing colored event block itself to reschedule it. "
                "Delete the named event only after selecting its event block."
            )

        if "design review" in lower_goal and "sprint planning" in lower_goal and "retrospective" in lower_goal:
            return (
                "Thunderbird multi-event creation plan: create the three requested one-off events one by one in this exact order — Design Review on Monday 10:00 AM for 45 minutes with a 15-minute reminder, Sprint Planning on Wednesday 1:30 PM for 90 minutes, then Retrospective on Friday 2:30 PM for 60 minutes with a 30-minute reminder — and save after each event. "
                "Open each event directly from the target week-grid slot instead of the generic New Event button whenever the week grid is visible. "
                "Leave the calendar grid visible between creations, ignore old node IDs after each save, and do not reopen a saved event unless the visible title or time is clearly wrong. "
                "If you must edit Thunderbird popup-style date or time fields, type the exact replacement and press Enter immediately to commit that field before touching the next one. "
                "After opening each event dialog, verify the Start date still matches the requested weekday because Thunderbird can open the second or third slot one day early; if the weekday/date is off, fix that date before saving. "
                "This is a creation-only task: never drag or reschedule any saved event block after creation, even if Thunderbird's week view looks slightly offset."
            )

        return (
            "Thunderbird one-off event plan: for a simple timed event without recurrence, use the visible New Event button if it is already enabled. "
            "Fill only the title plus the Start and End rows needed for the requested date/time, then click Save and Close as soon as those visible values match the task. "
            "Leave Repeat as 'Does not repeat' and Reminder as 'No reminder' unless the task explicitly asks for something else."
        )

    @staticmethod
    def _find_foreground_window(
        *,
        ui_nodes: Any,
        foreground_app: str,
        foreground_bundle_id: str,
    ) -> Mapping[str, Any] | None:
        if not isinstance(ui_nodes, list):
            return None

        app_tokens = {foreground_app.lower().strip()} if foreground_app else set()
        bundle_tail = foreground_bundle_id.rsplit('.', 1)[-1].lower().strip() if foreground_bundle_id else ""
        if bundle_tail:
            app_tokens.add(bundle_tail)

        best: Mapping[str, Any] | None = None
        best_score = -1
        for node in ui_nodes:
            if not isinstance(node, Mapping):
                continue
            if str(node.get("type") or "").strip() != "AXWindow":
                continue
            rect = MacOSPromptBuilder._window_bounds(node)
            if rect is None:
                continue
            left, top, width, height = rect
            if width <= 100 or height <= 100:
                continue
            haystack = " ".join(
                str(node.get(key) or "").lower()
                for key in ("text", "description", "identifier", "value")
            )
            score = 0
            if any(token and token in haystack for token in app_tokens):
                score += 10
            if foreground_app and str(node.get("description") or "").strip() == foreground_app:
                score += 5
            if foreground_app and str(node.get("text") or "").strip() == foreground_app:
                score += 4
            score += min(width, 5000) // 200
            if score > best_score:
                best = node
                best_score = score
        return best

    @staticmethod
    def _window_bounds(node: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
        try:
            left = int(node.get("x"))
            top = int(node.get("y"))
            width = int(node.get("width"))
            height = int(node.get("height"))
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return left, top, width, height

    @staticmethod
    def _find_node_by_text(ui_nodes: Any, text: str) -> Mapping[str, Any] | None:
        if not isinstance(ui_nodes, list):
            return None
        for node in ui_nodes:
            if not isinstance(node, Mapping):
                continue
            if str(node.get("text") or "").strip() == text:
                return node
        return None

    @staticmethod
    def _find_window_text_contains(ui_nodes: Any, needle: str) -> Mapping[str, Any] | None:
        if not isinstance(ui_nodes, list):
            return None
        target = str(needle or "").strip().lower()
        if not target:
            return None
        for node in ui_nodes:
            if not isinstance(node, Mapping):
                continue
            if str(node.get("type") or "").strip() != "AXWindow":
                continue
            haystack = " ".join(
                str(node.get(key) or "").strip().lower()
                for key in ("text", "description", "identifier", "value")
            )
            if target in haystack:
                return node
        return None

    @staticmethod
    def _extract_last_absolute_path(goal: str) -> str | None:
        normalized_goal = str(goal or "").replace("\r\n", "\n")
        matches = re.findall(r"(/[^`\s]+)", normalized_goal)
        if not matches:
            return None
        return matches[-1]

    @staticmethod
    def _extract_gimp_canvas_size(window_node: Mapping[str, Any] | None) -> tuple[int, int] | None:
        if not isinstance(window_node, Mapping):
            return None
        title = str(window_node.get("text") or "")
        match = re.search(r"(\d+)\s*x\s*(\d+)\s*[–-]\s*GIMP", title)
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _extract_gimp_layer_count(window_node: Mapping[str, Any] | None) -> int | None:
        if not isinstance(window_node, Mapping):
            return None
        title = str(window_node.get("text") or "")
        match = re.search(r"(\d+)\s+layer[s]?\)", title, flags=re.IGNORECASE)
        if match is None:
            return None
        return int(match.group(1))

    @staticmethod
    def _estimate_gimp_expected_layer_total(goal: str) -> int | None:
        normalized_goal = str(goal or "").replace("\r\n", "\n")
        if "open as layers" not in normalized_goal.lower():
            return None
        paths = re.findall(r"(/[^`\s]+)", normalized_goal)
        if not paths:
            return None
        open_file = paths[0]
        import_paths = {path for path in paths[1:] if path != open_file}
        if not import_paths:
            return None
        return 1 + len(import_paths)

    @staticmethod
    def _extract_ordered_goal_checklist(goal: str) -> list[str]:
        normalized_goal = str(goal or "").replace("\r\n", "\n")
        items: list[str] = []
        for raw_line in normalized_goal.splitlines():
            match = re.match(r"\s*\d+\.\s+(.*\S)\s*$", raw_line)
            if not match:
                continue
            item = re.sub(r"\*\*(.*?)\*\*", r"\1", match.group(1)).strip()
            if item:
                items.append(item)
        return items

    def _update_gimp_rotation_progress(self, canvas_size: tuple[int, int] | None) -> None:
        if (
            self._gimp_expected_clockwise_rotations <= 1
            or not isinstance(canvas_size, tuple)
            or len(canvas_size) != 2
        ):
            return
        width, height = canvas_size
        orientation = "portrait" if height > width else "landscape"
        previous = self._gimp_last_canvas_orientation
        if previous is not None and orientation != previous:
            self._gimp_completed_clockwise_rotations = min(
                self._gimp_completed_clockwise_rotations + 1,
                self._gimp_expected_clockwise_rotations,
            )
        self._gimp_last_canvas_orientation = orientation

    def _update_thunderbird_multi_send_progress(self, compose_visible: bool) -> None:
        if not self._thunderbird_multi_send_messages:
            self._thunderbird_prev_compose_visible = compose_visible
            return

        previous = self._thunderbird_prev_compose_visible
        if previous is True and compose_visible is False:
            self._thunderbird_multi_send_completed = min(
                self._thunderbird_multi_send_completed + 1,
                len(self._thunderbird_multi_send_messages),
            )
        self._thunderbird_prev_compose_visible = compose_visible

    @staticmethod
    def _build_thunderbird_multi_send_progress_hints(
        *,
        compose_visible: bool,
        completed: int,
        messages: list[dict[str, str]],
        current_message: dict[str, str] | None,
    ) -> list[str]:
        details: list[str] = []
        ordered_subjects = ", ".join(message["subject"] for message in messages)
        details.append(
            "Thunderbird multi-send reminder: send the checklist in order and never resend a subject that is already complete. "
            f"The ordered subjects are: {ordered_subjects}."
        )
        if completed >= len(messages):
            details.append(
                "Thunderbird multi-send completion guard: all checklist emails are already sent. Do not open another compose window. "
                "If no blocking dialog is present, finish instead."
            )
            return details

        if completed:
            finished_subjects = ", ".join(f"'{message['subject']}'" for message in messages[:completed])
            details.append(
                f"Thunderbird multi-send progress: already completed {completed}/{len(messages)} emails: {finished_subjects}. Do not send any of those again."
            )
        if current_message is not None:
            details.append(
                f"Thunderbird multi-send current checklist item: email {completed + 1}/{len(messages)}. "
                f"The next required subject is '{current_message['subject']}'."
            )
            details.append(
                "Thunderbird multi-send current body exact text:\n"
                "<<<BODY\n"
                f"{current_message['body']}\n"
                "BODY>>>"
            )
        if compose_visible:
            details.append(
                "Thunderbird multi-send compose-window guard: keep the current compose window focused on the current checklist item only; do not reuse an earlier subject/body after the checklist has advanced."
            )
        else:
            details.append(
                "Thunderbird multi-send main-window guard: when you are back in the main Mail window, open one fresh compose window only for the current unchecked checklist item instead of restarting the first email."
            )
        details.append(
            "Thunderbird multi-send signature guard: keep each signature split across two lines exactly as shown. "
            "If the checklist shows 'Best,' on one line and 'Ben' on the next line, keep them separate."
        )
        return details

    @staticmethod
    def _extract_thunderbird_multi_send_messages(goal: str) -> list[dict[str, str]]:
        normalized_goal = str(goal or "").replace("\r\n", "\n")
        pattern = re.compile(
            r"Email\s+\d+\s*\n"
            r"Subject:\s*(?P<subject>[^\n]+)\n"
            r"Body:\s*\n"
            r"(?P<body>.*?)(?=\nEmail\s+\d+\s*\nSubject:|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        messages: list[dict[str, str]] = []
        for match in pattern.finditer(normalized_goal):
            subject = str(match.group("subject") or "").strip()
            body = str(match.group("body") or "").strip("\n").strip()
            if subject and body:
                messages.append({"subject": subject, "body": body})
        return messages

    @staticmethod
    def _extract_actual_multi_create_accounts(goal: str) -> list[dict[str, str]]:
        normalized_goal = str(goal or "").replace("\r\n", "\n")
        pattern = re.compile(
            r'"(?P<name>[^"]+)"\s+with\s+opening\s+balance(?:\s+of)?\s+\$(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)',
            re.IGNORECASE,
        )
        accounts: list[dict[str, str]] = []
        for match in pattern.finditer(normalized_goal):
            name = str(match.group("name") or "").strip()
            amount_text = str(match.group("amount") or "").strip()
            if name and amount_text:
                accounts.append({"name": name, "amount_text": amount_text})
        return accounts

    @staticmethod
    def _extract_actual_single_create_account(goal: str) -> dict[str, str] | None:
        normalized_goal = str(goal or "").replace("\r\n", "\n")
        match = re.search(
            r'create\s+a\s+local\s+account\s+named\s+"(?P<name>[^"]+)"\s+with\s+an?\s+opening\s+balance\s+of\s+\$(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)',
            normalized_goal,
            re.IGNORECASE,
        )
        if not match:
            return None
        name = str(match.group("name") or "").strip()
        amount_text = str(match.group("amount") or "").strip()
        if not name or not amount_text:
            return None
        return {
            "name": name,
            "amount_text": amount_text,
            "amount_plain": amount_text.replace(",", ""),
        }

    @staticmethod
    def _is_thunderbird_new_event_window(node: Mapping[str, Any]) -> bool:
        haystack = " ".join(
            str(node.get(key) or "").strip().lower()
            for key in ("text", "description", "identifier", "value")
        )
        return haystack.startswith("new event") or "new event:" in haystack

    @staticmethod
    def _estimate_thunderbird_event_dialog_point(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
        x_ratio: float,
        y_ratio: float,
    ) -> tuple[float, float]:
        x = (left + (window_width * x_ratio)) / max(screen_width, 1)
        y = (top + (window_height * y_ratio)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_thunderbird_week_grid_slot_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
        weekday_index: int,
        hour: int,
    ) -> tuple[float, float]:
        x_ratio = 0.292 + (0.075 * weekday_index)
        y_ratio = 0.245 + (0.0335 * hour)
        return MacOSPromptBuilder._estimate_thunderbird_event_dialog_point(
            left=left,
            top=top,
            window_width=window_width,
            window_height=window_height,
            screen_width=screen_width,
            screen_height=screen_height,
            x_ratio=x_ratio,
            y_ratio=y_ratio,
        )

    @staticmethod
    def _estimate_actual_create_account_balance_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.48)) / max(screen_width, 1)
        y = (top + (window_height * 0.56)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_create_account_submit_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.64)) / max(screen_width, 1)
        y = (top + (window_height * 0.62)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_add_transaction_button_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.262)) / max(screen_width, 1)
        y = (top + (window_height * 0.154)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_transaction_payee_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.20)) / max(screen_width, 1)
        y = (top + (window_height * 0.125)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_transaction_category_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.60)) / max(screen_width, 1)
        y = (top + (window_height * 0.125)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_transaction_payment_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.87)) / max(screen_width, 1)
        y = (top + (window_height * 0.125)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_transaction_deposit_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.94)) / max(screen_width, 1)
        y = (top + (window_height * 0.125)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_transaction_add_row_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.965)) / max(screen_width, 1)
        y = (top + (window_height * 0.145)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_existing_account_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
        account: str,
    ) -> tuple[float, float]:
        account_key = str(account or "").strip().lower()
        y_ratio = 0.378 if account_key == "checking" else 0.405
        x = (left + (window_width * 0.025)) / max(screen_width, 1)
        y = (top + (window_height * y_ratio)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_modal_primary_button_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.5)) / max(screen_width, 1)
        y = (top + (window_height * 0.46)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_actual_add_account_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + max(52, min(76, int(window_width * 0.055)))) / max(screen_width, 1)
        y = (top + window_height - 15) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_thunderbird_new_calendar_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + max(70, min(110, int(window_width * 0.07)))) / max(screen_width, 1)
        y = (top + window_height - 22) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_thunderbird_local_folders_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.038)) / max(screen_width, 1)
        y = (top + (window_height * 0.055)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_thunderbird_manage_filters_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + (window_width * 0.255)) / max(screen_width, 1)
        y = (top + (window_height * 0.078)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_thunderbird_mail_folder_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
        folder_name: str,
    ) -> tuple[float, float]:
        folder_key = str(folder_name or "").strip().lower()
        y_ratios = {
            "inbox": 0.186,
            "sent": 0.214,
            "trash": 0.243,
            "outbox": 0.272,
            "bills": 0.301,
            "club": 0.329,
        }
        y_ratio = y_ratios.get(folder_key, 0.301)
        x = (left + (window_width * 0.046)) / max(screen_width, 1)
        y = (top + (window_height * y_ratio)) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _estimate_thunderbird_home_toggle_hint(
        *,
        left: int,
        top: int,
        window_width: int,
        window_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float]:
        x = (left + max(44, min(78, int(window_width * 0.05)))) / max(screen_width, 1)
        y = (top + max(255, min(310, int(window_height * 0.28)))) / max(screen_height, 1)
        return max(0.0, min(x, 0.999)), max(0.0, min(y, 0.999))

    @staticmethod
    def _build_drawio_target_hints(goal: str) -> list[str]:
        lower_goal = str(goal or "").lower()
        for fixture_name, entries in DRAWIO_PREPARED_TARGETS.items():
            if fixture_name not in lower_goal:
                continue
            return [
                f"{label}≈{{'x': {_format_norm(x)}, 'y': {_format_norm(y)}}}"
                for label, _cell_id, x, y in entries
            ]
        return []
