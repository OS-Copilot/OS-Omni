"""Evaluator for the Android Spotube profile setup task."""

from __future__ import annotations

import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.android.spotube_support import read_spotube_state
from platforms.android.spotube_state import (
    evaluate_expected_profile,
    read_profile_state,
)


class SpotubeProfileSetupEvaluator(BaseEvaluator):
    """Validate visible Spotube profile settings after setup."""

    DEFAULT_APP_PACKAGE = "oss.krtirtho.spotube"
    DEFAULT_AUDIO_SOURCE = "Jiosaavn Audio"
    DEFAULT_LANGUAGE = "English"
    DEFAULT_MARKETPLACE_REGION = "Austria"
    DEFAULT_THEME = "Light"
    DEFAULT_ACCENT_COLOR = "rose"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Spotube evaluation",
            )

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        expected_audio_source = str(
            params.get("expected_audio_source") or self.DEFAULT_AUDIO_SOURCE
        ).strip()
        expected_language = str(
            params.get("expected_language") or self.DEFAULT_LANGUAGE
        ).strip()
        expected_marketplace_region = str(
            params.get("expected_marketplace_region")
            or self.DEFAULT_MARKETPLACE_REGION
        ).strip()
        expected_theme = str(params.get("expected_theme") or self.DEFAULT_THEME).strip()
        expected_accent_color = str(
            params.get("expected_accent_color") or self.DEFAULT_ACCENT_COLOR
        ).strip()
        expected_language_code = str(params.get("expected_language_code") or "en").strip()
        expected_market = str(params.get("expected_market") or "AT").strip()
        expected_theme_code = str(params.get("expected_theme_code") or "light").strip()

        if not app_package:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params app_package is required",
            )

        try:
            is_spotube_foreground, focus_output = self._is_foreground(
                controller=controller,
                app_package=app_package,
            )
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to inspect foreground app: {type(exc).__name__}: {exc}",
                metadata={"app_package": app_package},
            )

        database_status = "ERROR"
        database_error = ""
        profile_state: dict[str, Any] | None = None
        database_profile = {
            "status": "FAIL",
            "checks": {"database_readable": False},
        }
        try:
            profile_state = read_profile_state(
                controller,
                app_package=app_package,
            )
            database_profile = evaluate_expected_profile(
                profile_state,
                expected_audio_source=expected_audio_source,
                expected_language_code=expected_language_code,
                expected_market=expected_market,
                expected_theme=expected_theme_code,
                expected_accent=expected_accent_color,
                expected_normalize_audio=True,
            )
            database_status = database_profile["status"]
        except Exception as exc:
            database_error = f"{type(exc).__name__}: {exc}"

        initial_nodes = self._dump_and_collect_nodes(controller=controller)
        settings_nodes = (
            self._collect_nodes_with_scroll_sampling(
                controller=controller,
                initial_nodes=initial_nodes,
            )
            if initial_nodes is not None
            else []
        )
        settings_tokens = [node["token"] for node in settings_nodes if node["token"]]
        app_settings = self._evaluate_app_settings(
            nodes=settings_nodes,
            tokens=settings_tokens,
            expected_language=expected_language,
            expected_marketplace_region=expected_marketplace_region,
            expected_theme=expected_theme,
            expected_accent_color=expected_accent_color,
        )

        plugins_navigation = (
            self._navigate_to_plugins(controller=controller)
            if initial_nodes is not None
            else {"opened": False, "reason": "ui_dump_failed"}
        )
        plugin_nodes = self._collect_nodes_with_scroll_sampling(
            controller=controller,
            initial_nodes=plugins_navigation.get("nodes"),
        ) if plugins_navigation.get("opened") else []
        plugin_tokens = [node["token"] for node in plugin_nodes if node["token"]]
        audio_source = self._evaluate_audio_source(
            tokens=plugin_tokens,
            expected_audio_source=expected_audio_source,
        )

        hard_checks = {
            "spotube_foreground": is_spotube_foreground,
            **database_profile.get("checks", {}),
        }
        state_fallback = self._evaluate_state_fallback(
            controller=controller,
            app_package=app_package,
            expected_audio_source=expected_audio_source,
            expected_language=expected_language,
            expected_marketplace_region=expected_marketplace_region,
            expected_theme=expected_theme,
            expected_accent_color=expected_accent_color,
        )
        overall_status = (
            "PASS"
            if all(hard_checks.values())
            else "FAIL"
        )
        metadata = {
            "app_package": app_package,
            "is_spotube_foreground": is_spotube_foreground,
            "database_profile": database_profile,
            "database_status": database_status,
            "database_error": database_error,
            "profile_state": profile_state,
            "ui_audio_source": audio_source,
            "ui_app_settings": app_settings,
            "checks": hard_checks,
            "overall": {
                "status": overall_status,
                "hard_requirements": list(hard_checks.keys()),
                "note": (
                    "Spotube profile setup is hard-checked through the app SQLite "
                    "database. UI sampling is retained only as diagnostic context."
                ),
            },
            "plugins_navigation": {
                key: value
                for key, value in plugins_navigation.items()
                if key != "nodes"
            },
            "focus_output": focus_output,
            "state_fallback": state_fallback,
        }

        if overall_status == "PASS":
            return EvalResult(
                status=EvalStatus.PASS,
                message="Spotube profile settings match the requested database values",
                metadata=metadata,
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message=(
                "Spotube profile setup verification failed: expected Jiosaavn Audio "
                "as the only default source plus English, Austria, Light, rose, and Normalize audio ON"
            ),
            metadata=metadata,
        )

    @staticmethod
    def _evaluate_state_fallback(
        *,
        controller: Any,
        app_package: str,
        expected_audio_source: str,
        expected_language: str,
        expected_marketplace_region: str,
        expected_theme: str,
        expected_accent_color: str,
    ) -> dict[str, Any]:
        try:
            state = read_spotube_state(controller, app_package=app_package)
        except Exception as exc:
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

        preferences = dict(state.get("preferences") or {})
        plugins = [dict(item) for item in (state.get("plugins") or []) if isinstance(item, dict)]
        selected_audio = next(
            (item for item in plugins if int(item.get("selected_for_audio_source") or 0) == 1),
            None,
        )

        locale_raw = str(preferences.get("locale") or "")
        language_code = ""
        expected_language_key = expected_language.strip().lower()
        if expected_language_key == "english":
            language_code = "en"
        region_code = expected_marketplace_region.strip()
        region_lookup = {
            "austria": "AT",
        }
        region_code = region_lookup.get(region_code.lower(), region_code)

        accent_raw = str(preferences.get("accent_color_scheme") or "")
        normalize_value = preferences.get("normalize_audio")
        audio_source_id = str(preferences.get("audio_source_id") or "").strip()
        checks = {
            "audio_source_selected": (
                str((selected_audio or {}).get("name") or "").strip() == expected_audio_source
                or bool(audio_source_id)
            ),
            "language_matches": bool(language_code and f'"languageCode":"{language_code}"' in locale_raw.replace(" ", "")),
            "market_matches": str(preferences.get("market") or "").strip().upper() == region_code.upper(),
            "theme_matches": str(preferences.get("theme_mode") or "").strip().lower() == expected_theme.strip().lower(),
            "accent_matches": accent_raw.strip().lower().startswith(expected_accent_color.strip().lower()),
            "normalize_audio_on": str(normalize_value).strip() in {"1", "true", "True"},
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "selected_audio_source": (selected_audio or {}).get("name"),
            "audio_source_id": audio_source_id,
            "preferences": preferences,
        }

    @staticmethod
    def _evaluate_audio_source(
        *,
        tokens: list[str],
        expected_audio_source: str,
    ) -> dict[str, Any]:
        source_token = expected_audio_source.lower()
        source_visible = any(source_token in token for token in tokens)
        set_as_default_visible = any("set as default audio source" in token for token in tokens)
        default_marker_visible = any(
            marker in token
            for marker in ("default audio source", "默认音频源")
            for token in tokens
        )

        if source_visible and default_marker_visible and not set_as_default_visible:
            status = "PASS"
        elif source_visible:
            status = "FAIL"
        else:
            status = "FAIL"

        return {
            "status": status,
            "expected_audio_source": expected_audio_source,
            "source_visible": source_visible,
            "default_marker_visible": default_marker_visible,
            "set_as_default_visible": set_as_default_visible,
            "note": (
                "This check uses the Plugins page after evaluator navigation. It passes "
                "when Jiosaavn Audio is visible with a default-audio-source marker and "
                "without a visible 'Set as default audio source' action."
            ),
        }

    @classmethod
    def _evaluate_app_settings(
        cls,
        *,
        nodes: list[dict[str, Any]],
        tokens: list[str],
        expected_language: str,
        expected_marketplace_region: str,
        expected_theme: str,
        expected_accent_color: str,
    ) -> dict[str, Any]:
        language_visible = cls._token_visible(tokens, expected_language)
        region_visible = cls._token_visible(tokens, expected_marketplace_region)
        theme_visible = cls._token_visible(tokens, expected_theme)
        accent_visible = cls._token_visible(tokens, expected_accent_color)
        normalize_visible = any("normalize audio" in token for token in tokens)
        normalize_on = cls._is_normalize_audio_on(nodes=nodes)

        checks = {
            "language_english": language_visible,
            "marketplace_region_austria": region_visible,
            "theme_light": theme_visible,
            "accent_color_rose": accent_visible,
            "normalize_audio_visible": normalize_visible,
            "normalize_audio_on_observable": normalize_on,
        }

        return {
            "status": (
                "PASS"
                if all(
                    [
                        language_visible,
                        region_visible,
                        theme_visible,
                        accent_visible,
                        normalize_visible,
                    ]
                )
                else "FAIL"
            ),
            "checks": checks,
            "expected": {
                "language": expected_language,
                "marketplace_region": expected_marketplace_region,
                "theme": expected_theme,
                "accent_color": expected_accent_color,
                "normalize_audio": "on",
            },
            "note": (
                "Normalize audio must be turned on by the task. The evaluator reports "
                "normalize_audio_on_observable when a checked state is exposed, but only "
                "hard-requires the row to be visible because the Flutter switch often "
                "does not expose on/off state through Android accessibility."
            ),
        }

    @staticmethod
    def _token_visible(tokens: list[str], expected: str) -> bool:
        expected_token = expected.lower()
        return any(expected_token in token for token in tokens)

    @staticmethod
    def _is_normalize_audio_on(*, nodes: list[dict[str, Any]]) -> bool:
        normalize_nodes = [
            node for node in nodes if "normalize audio" in str(node.get("token") or "")
        ]
        for label_node in normalize_nodes:
            label_bounds = label_node.get("bounds")
            if not label_bounds:
                continue
            label_center_y = (label_bounds[1] + label_bounds[3]) / 2.0
            label_center_x = (label_bounds[0] + label_bounds[2]) / 2.0
            for node in nodes:
                bounds = node.get("bounds")
                if not bounds:
                    continue
                center_x = (bounds[0] + bounds[2]) / 2.0
                center_y = (bounds[1] + bounds[3]) / 2.0
                same_row = abs(center_y - label_center_y) <= 120
                right_of_label = center_x >= label_center_x
                if same_row and right_of_label and node.get("checked") is True:
                    return True

        return any(
            "normalize audio" in str(node.get("token") or "")
            and any(marker in str(node.get("token") or "") for marker in (" on", "enabled", "true"))
            for node in nodes
        )

    @staticmethod
    def _is_foreground(*, controller: Any, app_package: str) -> tuple[bool, str]:
        window_dump = str(controller.execute_adb(["shell", "dumpsys", "window"]) or "")
        activity_dump = str(
            controller.execute_adb(["shell", "dumpsys", "activity", "activities"]) or ""
        )

        focus_lines: list[str] = []
        for line in window_dump.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                focus_lines.append(line.strip())
        for line in activity_dump.splitlines():
            if "mResumedActivity" in line or "topResumedActivity" in line:
                focus_lines.append(line.strip())

        focus_summary = " | ".join(focus_lines)
        combined = f"{window_dump}\n{activity_dump}"
        return (app_package in combined), focus_summary

    @classmethod
    def _collect_nodes_with_scroll_sampling(
        cls,
        *,
        controller: Any,
        initial_nodes: list[dict[str, Any]] | None,
        samples: int = 5,
    ) -> list[dict[str, Any]]:
        all_nodes = list(initial_nodes or [])
        seen_signatures = {cls._nodes_signature(all_nodes)}

        gestures = (
            ("540", "650", "540", "1800"),  # reveal content above the current viewport
            ("540", "1800", "540", "650"),  # reveal content below the current viewport
        )
        for start_x, start_y, end_x, end_y in gestures:
            for _ in range(samples):
                controller.execute_adb(
                    ["shell", "input", "swipe", start_x, start_y, end_x, end_y, "350"]
                )
                time.sleep(0.25)
                nodes = cls._dump_and_collect_nodes(controller=controller)
                if not nodes:
                    continue
                signature = cls._nodes_signature(nodes)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                all_nodes.extend(nodes)

        return all_nodes

    @classmethod
    def _navigate_to_plugins(cls, *, controller: Any) -> dict[str, Any]:
        for direction in ("up", "down"):
            for attempt in range(6):
                nodes = cls._dump_and_collect_nodes(controller=controller) or []
                plugin_node = cls._find_clickable_node(nodes=nodes, needle="plugins")
                if plugin_node and plugin_node.get("bounds"):
                    x, y = cls._center(plugin_node["bounds"])
                    controller.execute_adb(["shell", "input", "tap", str(x), str(y)])
                    time.sleep(0.6)
                    opened_nodes = cls._dump_and_collect_nodes(controller=controller) or []
                    opened_tokens = [node["token"] for node in opened_nodes if node["token"]]
                    return {
                        "opened": any("plugin" in token for token in opened_tokens),
                        "attempts": attempt + 1,
                        "direction": direction,
                        "nodes": opened_nodes,
                    }

                if direction == "up":
                    controller.execute_adb(["shell", "input", "swipe", "540", "650", "540", "1800", "350"])
                else:
                    controller.execute_adb(["shell", "input", "swipe", "540", "1800", "540", "650", "350"])
                time.sleep(0.25)

        return {
            "opened": False,
            "attempts": 12,
            "direction": "up_then_down",
        }

    @classmethod
    def _dump_and_collect_nodes(cls, *, controller: Any) -> list[dict[str, Any]] | None:
        ui_dump_text = cls._dump_ui_and_read(controller=controller)
        if ui_dump_text is None:
            return None
        return cls._collect_ui_nodes(ui_dump_text=ui_dump_text)

    @staticmethod
    def _dump_ui_and_read(*, controller: Any) -> str | None:
        remote_path = "/sdcard/spotube_profile_setup_eval_ui.xml"
        with tempfile.TemporaryDirectory(prefix="spotube-profile-ui-") as tmpdir:
            local_path = Path(tmpdir) / "spotube_profile_setup_eval_ui.xml"
            controller.execute_adb(["shell", "uiautomator", "dump", remote_path])
            controller.execute_adb(["pull", remote_path, str(local_path)])
            if not local_path.exists() or local_path.stat().st_size <= 0:
                return None
            return local_path.read_text(encoding="utf-8", errors="ignore")

    @staticmethod
    def _collect_ui_nodes(*, ui_dump_text: str) -> list[dict[str, Any]]:
        try:
            root = ET.fromstring(ui_dump_text)
        except ET.ParseError:
            return []

        nodes: list[dict[str, Any]] = []
        for node in root.iter("node"):
            text = str(node.attrib.get("text") or "").strip()
            desc = str(node.attrib.get("content-desc") or "").strip()
            token = " ".join(part for part in (text, desc) if part).lower()
            checked_raw = str(node.attrib.get("checked") or "").lower()
            clickable_raw = str(node.attrib.get("clickable") or "").lower()
            nodes.append(
                {
                    "token": token,
                    "class": str(node.attrib.get("class") or ""),
                    "checked": checked_raw == "true",
                    "clickable": clickable_raw == "true",
                    "bounds": SpotubeProfileSetupEvaluator._parse_bounds(
                        str(node.attrib.get("bounds") or "")
                    ),
                }
            )
        return nodes

    @staticmethod
    def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
        matched = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw)
        if not matched:
            return None
        return tuple(int(matched.group(idx)) for idx in range(1, 5))

    @staticmethod
    def _nodes_signature(nodes: list[dict[str, Any]]) -> tuple[str, ...]:
        return tuple(node["token"] for node in nodes if node.get("token"))[:24]

    @staticmethod
    def _find_clickable_node(
        *,
        nodes: list[dict[str, Any]],
        needle: str,
    ) -> dict[str, Any] | None:
        for node in nodes:
            if needle in str(node.get("token") or "") and node.get("clickable"):
                return node
        for node in nodes:
            if needle in str(node.get("token") or ""):
                return node
        return None

    @staticmethod
    def _center(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
        x1, y1, x2, y2 = bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)
