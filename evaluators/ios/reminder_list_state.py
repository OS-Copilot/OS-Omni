"""Generic UI evaluator for seeded iOS Reminders list tasks."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class ReminderListStateEvaluator(BaseEvaluator):
    DEFAULT_BUNDLE_ID = "com.apple.reminders"
    DEFAULT_LIST_NAME = "Reminders"
    BACK_BUTTON_TEXTS = ("Back",)
    DEFAULT_SCROLL_DISTANCE = 0.65
    DEFAULT_SCROLL_DURATION_MS = 180
    DEFAULT_SETTLE_SECONDS = 0.35
    MAX_EDGE_SCROLL_ATTEMPTS = 8
    MAX_COLLECTION_SCROLL_ATTEMPTS = 24

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        final_observation = context.get("final_observation")

        observation = final_observation
        if observation is None:
            if controller is None or not hasattr(controller, "observe"):
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message="final_observation is missing and controller.observe is unavailable",
                )
            observation = controller.observe(include_ui_tree=True)

        params = dict(context.get("params") or {})
        required_bundle_id = str(params.get("bundle_id", self.DEFAULT_BUNDLE_ID)).strip()
        required_list_name = str(params.get("list_name") or self.DEFAULT_LIST_NAME).strip()
        present_titles = self._coerce_text_list(
            params.get("present_titles") or params.get("required_titles")
        )
        absent_titles = self._coerce_text_list(
            params.get("absent_titles") or params.get("forbidden_titles")
        )
        exact_titles = self._coerce_text_list(
            params.get("exact_titles") or params.get("expected_titles")
        )
        ordered_titles = self._coerce_text_list(
            params.get("ordered_titles") or params.get("expected_ordered_titles")
        )

        if not present_titles and not absent_titles and not exact_titles and not ordered_titles:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires present_titles, absent_titles, exact_titles, and/or ordered_titles",
            )

        actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
        list_view_ok, observed_titles = self._is_expected_list_view(ui_nodes, required_list_name)

        # Opt-in for tasks whose brief grades only the list's contents: when the
        # agent ends elsewhere (another app, the lists home, another list), open
        # the list here instead of failing on where the run stopped.
        navigation: dict[str, Any] | None = None
        if self._coerce_bool(params.get("navigate_to_list")) and (
            actual_bundle_id != required_bundle_id or not list_view_ok
        ):
            navigated, navigation = self._navigate_to_list(
                controller=controller,
                bundle_id=required_bundle_id,
                list_name=required_list_name,
            )
            if navigated is not None:
                observation = navigated
                actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
                ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
                list_view_ok, observed_titles = self._is_expected_list_view(ui_nodes, required_list_name)

        if actual_bundle_id != required_bundle_id:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"Expected foreground bundle '{required_bundle_id}', "
                    f"got '{actual_bundle_id or 'unknown'}'"
                ),
                metadata={
                    "required_bundle_id": required_bundle_id,
                    "actual_bundle_id": actual_bundle_id,
                    "navigation": navigation,
                },
            )

        if not list_view_ok:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Expected to be inside reminder list '{required_list_name}'",
                metadata={
                    "required_list_name": required_list_name,
                    "observed_titles": observed_titles,
                    "navigation": navigation,
                },
            )

        observed_reminder_titles_in_order = self._collect_all_reminder_titles_in_order(
            controller=controller,
            list_name=required_list_name,
            initial_ui_nodes=ui_nodes,
        )
        observed_reminder_titles = set(observed_reminder_titles_in_order)
        missing_titles = [
            text for text in present_titles if not self._contains_title(observed_reminder_titles, text)
        ]
        unexpected_titles = [
            text for text in absent_titles if self._contains_title(observed_reminder_titles, text)
        ]
        exact_missing_titles: list[str] = []
        exact_unexpected_titles: list[str] = []
        order_mismatch = False
        expected_ordered_titles_normalized: list[str] = []

        if exact_titles:
            expected_normalized_titles = {
                normalized
                for text in exact_titles
                if (normalized := self._normalize_text(text))
            }
            exact_missing_titles = [
                text
                for text in exact_titles
                if self._normalize_text(text) not in observed_reminder_titles
            ]
            exact_unexpected_titles = sorted(observed_reminder_titles - expected_normalized_titles)

        if ordered_titles:
            expected_ordered_titles_normalized = [
                normalized
                for text in ordered_titles
                if (normalized := self._normalize_text(text))
            ]
            order_mismatch = observed_reminder_titles_in_order != expected_ordered_titles_normalized

        if (
            missing_titles
            or unexpected_titles
            or exact_missing_titles
            or exact_unexpected_titles
            or order_mismatch
        ):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Reminder list does not match the expected visible titles",
                metadata={
                    "required_list_name": required_list_name,
                    "missing_titles": missing_titles,
                    "unexpected_titles": unexpected_titles,
                    "exact_missing_titles": exact_missing_titles,
                    "exact_unexpected_titles": exact_unexpected_titles,
                    "observed_reminder_titles": sorted(observed_reminder_titles),
                    "expected_exact_titles": sorted(exact_titles),
                    "observed_reminder_titles_in_order": observed_reminder_titles_in_order,
                    "expected_ordered_titles": expected_ordered_titles_normalized,
                    "order_mismatch": order_mismatch,
                    "navigation": navigation,
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Reminder list matches the expected visible titles",
            metadata={
                "required_list_name": required_list_name,
                "observed_reminder_titles": sorted(observed_reminder_titles),
                "expected_exact_titles": sorted(exact_titles),
                "observed_reminder_titles_in_order": observed_reminder_titles_in_order,
                "expected_ordered_titles": expected_ordered_titles_normalized,
                "navigation": navigation,
            },
        )

    MAX_NAVIGATION_STEPS = 4

    def _navigate_to_list(
        self,
        *,
        controller: Any,
        bundle_id: str,
        list_name: str,
    ) -> tuple[Any | None, dict[str, Any]]:
        """Bring Reminders forward and open *list_name* using Back and the list row only.

        Never taps Done/Cancel or edits anything; if the app shows a sheet or an
        editor without a Back button, navigation stops and the caller fails as before.
        """
        evidence: dict[str, Any] = {"attempted": True, "steps": [], "reached_list": False}
        if controller is None or not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            evidence.update({"attempted": False, "reason": "controller cannot observe and act"})
            return None, evidence
        try:
            observation = controller.observe(include_ui_tree=True)
            if str(getattr(observation, "foreground_bundle_id", "") or "").strip() != bundle_id:
                if not hasattr(controller, "activate_app"):
                    evidence["reason"] = "controller cannot activate the app"
                    return observation, evidence
                controller.activate_app(bundle_id)
                evidence["steps"].append("activate_app")
                time.sleep(self.DEFAULT_SETTLE_SECONDS)
                observation = controller.observe(include_ui_tree=True)

            for _ in range(self.MAX_NAVIGATION_STEPS):
                if str(getattr(observation, "foreground_bundle_id", "") or "").strip() != bundle_id:
                    evidence["reason"] = "app is not in the foreground"
                    break
                ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
                if self._is_expected_list_view(ui_nodes, list_name)[0]:
                    evidence["reached_list"] = True
                    break
                target = self._find_list_cell(ui_nodes, list_name)
                step = "open_list"
                if target is None:
                    target = self._find_back_button(ui_nodes)
                    step = "back"
                if target is None or target.get("id") is None:
                    evidence["reason"] = "neither the list row nor a Back button is visible"
                    break
                result = controller.execute_action({"type": "tap", "target": target["id"]}, ui_nodes)
                if not bool((result or {}).get("success")):
                    evidence["reason"] = f"{step} tap failed"
                    break
                evidence["steps"].append(step)
                time.sleep(self.DEFAULT_SETTLE_SECONDS)
                observation = controller.observe(include_ui_tree=True)
            else:
                ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
                evidence["reached_list"] = self._is_expected_list_view(ui_nodes, list_name)[0]
        except Exception as exc:
            evidence["reason"] = f"{type(exc).__name__}: {exc}"
            return None, evidence
        return observation, evidence

    @classmethod
    def _find_list_cell(cls, ui_nodes: list[dict[str, Any]], list_name: str) -> dict[str, Any] | None:
        wanted = cls._normalize_text(list_name)
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Cell" or cls._is_reminder_cell(node):
                continue
            raw = str(node.get("text") or "").strip()
            for sep in ("，", ","):
                if sep in raw:
                    raw = raw.split(sep, 1)[0].strip()
                    break
            if cls._normalize_text(raw) == wanted and node.get("id") is not None:
                return node
        return None

    @staticmethod
    def _coerce_bool(raw: Any) -> bool:
        if isinstance(raw, bool):
            return raw
        return str(raw or "").strip().casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text:
                values.append(text)
        return values

    @classmethod
    def _extract_reminder_titles(cls, ui_nodes: list[dict[str, Any]]) -> set[str]:
        titles: set[str] = set()
        for node in ui_nodes:
            if not cls._is_reminder_cell(node):
                continue
            raw_text = str(node.get("text") or "").strip()
            title = cls._extract_reminder_title(raw_text)
            normalized = cls._normalize_text(title)
            if normalized:
                titles.add(normalized)
        return titles

    @classmethod
    def _extract_visible_reminder_titles_in_order(cls, ui_nodes: list[dict[str, Any]]) -> list[str]:
        titles: list[str] = []
        for node in ui_nodes:
            if not cls._is_reminder_cell(node):
                continue
            raw_text = str(node.get("text") or "").strip()
            title = cls._extract_reminder_title(raw_text)
            normalized = cls._normalize_text(title)
            if normalized:
                titles.append(normalized)
        return titles

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text).strip().casefold().split())

    def _collect_all_reminder_titles(
        self,
        *,
        controller: Any,
        list_name: str,
        initial_ui_nodes: list[dict[str, Any]],
    ) -> set[str]:
        collected = self._extract_reminder_titles(initial_ui_nodes)
        if controller is None or not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            return collected

        top_ui_nodes = self._scroll_to_edge(
            controller=controller,
            list_name=list_name,
            ui_nodes=initial_ui_nodes,
            direction="down",
            attempts=self.MAX_EDGE_SCROLL_ATTEMPTS,
        )
        collected.update(self._extract_reminder_titles(top_ui_nodes))

        current_ui_nodes = top_ui_nodes
        previous_signature: tuple[str, ...] | None = None
        stagnant_passes = 0

        for _ in range(self.MAX_COLLECTION_SCROLL_ATTEMPTS):
            visible_titles = tuple(self._extract_visible_reminder_titles_in_order(current_ui_nodes))
            collected.update(visible_titles)

            if visible_titles == previous_signature:
                stagnant_passes += 1
            else:
                stagnant_passes = 0
            if stagnant_passes >= 1:
                break

            previous_signature = visible_titles
            next_ui_nodes = self._scroll_and_observe(controller, current_ui_nodes, direction="up")
            if next_ui_nodes is None:
                break

            list_view_ok, _observed_titles = self._is_expected_list_view(next_ui_nodes, list_name)
            if not list_view_ok:
                break
            current_ui_nodes = next_ui_nodes

        return collected

    def _collect_all_reminder_titles_in_order(
        self,
        *,
        controller: Any,
        list_name: str,
        initial_ui_nodes: list[dict[str, Any]],
    ) -> list[str]:
        if controller is None or not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            return self._dedupe_preserving_order(
                self._extract_visible_reminder_titles_in_order(initial_ui_nodes)
            )

        top_ui_nodes = self._scroll_to_edge(
            controller=controller,
            list_name=list_name,
            ui_nodes=initial_ui_nodes,
            direction="down",
            attempts=self.MAX_EDGE_SCROLL_ATTEMPTS,
        )

        ordered_titles: list[str] = []
        seen: set[str] = set()

        current_ui_nodes = top_ui_nodes
        previous_signature: tuple[str, ...] | None = None
        stagnant_passes = 0

        for _ in range(self.MAX_COLLECTION_SCROLL_ATTEMPTS):
            visible_titles = tuple(self._extract_visible_reminder_titles_in_order(current_ui_nodes))
            for title in visible_titles:
                if title in seen:
                    continue
                ordered_titles.append(title)
                seen.add(title)

            if visible_titles == previous_signature:
                stagnant_passes += 1
            else:
                stagnant_passes = 0
            if stagnant_passes >= 1:
                break

            previous_signature = visible_titles
            next_ui_nodes = self._scroll_and_observe(controller, current_ui_nodes, direction="up")
            if next_ui_nodes is None:
                break

            list_view_ok, _observed_titles = self._is_expected_list_view(next_ui_nodes, list_name)
            if not list_view_ok:
                break
            current_ui_nodes = next_ui_nodes

        return ordered_titles

    @staticmethod
    def _dedupe_preserving_order(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            deduped.append(value)
            seen.add(value)
        return deduped

    def _scroll_to_edge(
        self,
        *,
        controller: Any,
        list_name: str,
        ui_nodes: list[dict[str, Any]],
        direction: str,
        attempts: int,
    ) -> list[dict[str, Any]]:
        current_ui_nodes = ui_nodes
        previous_signature: tuple[str, ...] | None = None
        stagnant_passes = 0

        for _ in range(max(attempts, 0)):
            visible_titles = tuple(self._extract_visible_reminder_titles_in_order(current_ui_nodes))
            if visible_titles == previous_signature:
                stagnant_passes += 1
            else:
                stagnant_passes = 0
            if stagnant_passes >= 1:
                break

            previous_signature = visible_titles
            next_ui_nodes = self._scroll_and_observe(controller, current_ui_nodes, direction=direction)
            if next_ui_nodes is None:
                break

            list_view_ok, _observed_titles = self._is_expected_list_view(next_ui_nodes, list_name)
            if not list_view_ok:
                break
            current_ui_nodes = next_ui_nodes

        return current_ui_nodes

    def _scroll_and_observe(
        self,
        controller: Any,
        ui_nodes: list[dict[str, Any]],
        *,
        direction: str,
    ) -> list[dict[str, Any]] | None:
        try:
            result = controller.execute_action(
                {
                    "type": "scroll",
                    "direction": direction,
                    "distance": self.DEFAULT_SCROLL_DISTANCE,
                    "duration_ms": self.DEFAULT_SCROLL_DURATION_MS,
                },
                ui_nodes,
            )
        except Exception:
            return None

        if not bool((result or {}).get("success")):
            return None

        time.sleep(self.DEFAULT_SETTLE_SECONDS)
        observation = controller.observe(include_ui_tree=True)
        return list(getattr(observation, "ui_nodes", []) or [])

    @classmethod
    def _contains_title(cls, observed_titles: set[str], target_text: str) -> bool:
        wanted = cls._normalize_text(target_text)
        if not wanted:
            return False
        return wanted in observed_titles

    @classmethod
    def _is_reminder_cell(cls, node: dict[str, Any]) -> bool:
        if str(node.get("type") or "").strip() != "Cell":
            return False

        selector = cls._normalize_text(str(node.get("selector") or ""))
        text = cls._normalize_text(str(node.get("text") or ""))

        if "x-apple-reminderkit://remcdreminder/" in selector:
            return True
        if text.endswith(", incomplete") or text.endswith(",incomplete"):
            return True
        return False

    @classmethod
    def _is_expected_list_view(
        cls,
        ui_nodes: list[dict[str, Any]],
        list_name: str,
    ) -> tuple[bool, list[str]]:
        wanted = cls._normalize_text(list_name)
        observed_titles = cls._extract_top_titles(ui_nodes)
        has_back_button = cls._has_back_button(ui_nodes)
        matched_title = any(cls._normalize_text(title) == wanted for title in observed_titles)
        return has_back_button and matched_title, observed_titles

    @classmethod
    def _extract_top_titles(cls, ui_nodes: list[dict[str, Any]]) -> list[str]:
        titles: list[str] = []
        for node in ui_nodes:
            node_type = str(node.get("type") or "").strip()
            if node_type not in {"NavigationBar", "StaticText"}:
                continue
            rect = node.get("rect") or {}
            node_y = float(rect.get("y", 0.0))
            if node_y > 170.0:
                continue
            text = str(node.get("text") or node.get("selector") or "").strip()
            if text:
                titles.append(text)
        return titles

    @classmethod
    def _has_back_button(cls, ui_nodes: list[dict[str, Any]]) -> bool:
        return cls._find_back_button(ui_nodes) is not None

    @classmethod
    def _find_back_button(cls, ui_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        wanted = {cls._normalize_text(text) for text in cls.BACK_BUTTON_TEXTS}
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            rect = node.get("rect") or {}
            node_y = float(rect.get("y", 0.0))
            if node_y > 120.0:
                continue
            text = cls._normalize_text(str(node.get("text") or ""))
            selector = cls._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector == cls._normalize_text("BackButton"):
                return node
        return None

    @staticmethod
    def _extract_reminder_title(text: str) -> str:
        raw = str(text or "").strip()
        for sep in ("、", ",", "，"):
            if sep in raw:
                return raw.split(sep, 1)[0].strip()
        return raw
