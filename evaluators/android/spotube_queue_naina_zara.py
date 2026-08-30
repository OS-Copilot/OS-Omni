"""Evaluator for Android Spotube queue task (Naina + Zara Zara)."""

from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.android.spotube_support import read_spotube_state


class SpotubeQueueNainaZaraEvaluator(BaseEvaluator):
    """Validate queue view contains both requested tracks."""

    DEFAULT_APP_PACKAGE = "oss.krtirtho.spotube"
    DEFAULT_PRIMARY_TRACK_QUERY = "Naina"
    DEFAULT_QUEUED_TRACK_QUERY = "Zara Zara"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Spotube evaluation",
            )

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        primary_track_query = str(
            params.get("primary_track_query") or self.DEFAULT_PRIMARY_TRACK_QUERY
        ).strip()
        queued_track_query = str(
            params.get("queued_track_query") or self.DEFAULT_QUEUED_TRACK_QUERY
        ).strip()
        required_track_queries = [
            str(item).strip()
            for item in (params.get("required_track_queries") or [])
            if str(item).strip()
        ]
        if not required_track_queries:
            required_track_queries = [primary_track_query, queued_track_query]
        min_track_count = int(params.get("min_track_count") or len(required_track_queries))
        exact_track_order = bool(params.get("exact_track_order", False))
        expected_loop_mode = str(params.get("expected_loop_mode") or "").strip()
        expected_market = str(params.get("expected_market") or "").strip()
        expected_language_code = str(params.get("expected_language_code") or "").strip()
        expected_audio_source = str(params.get("expected_audio_source") or "").strip()

        if not app_package or not primary_track_query or not queued_track_query:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=(
                    "evaluation.params app_package, primary_track_query, and "
                    "queued_track_query are required"
                ),
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

        ui_dump_text = self._dump_ui_and_read(controller=controller)
        if ui_dump_text is None:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Failed to dump current UI hierarchy for Spotube",
                metadata={
                    "app_package": app_package,
                    "is_spotube_foreground": is_spotube_foreground,
                    "focus_output": focus_output,
                },
            )

        tokens = self._collect_ui_tokens(ui_dump_text=ui_dump_text)
        visible_track_checks = {
            query: any(query.lower() in token for token in tokens)
            for query in required_track_queries
        }
        queue_visible = any("queue" in token for token in tokens)
        state_fallback = self._load_state_fallback(
            controller=controller,
            app_package=app_package,
            required_track_queries=required_track_queries,
            min_track_count=min_track_count,
            exact_track_order=exact_track_order,
            expected_loop_mode=expected_loop_mode,
            expected_market=expected_market,
            expected_language_code=expected_language_code,
            expected_audio_source=expected_audio_source,
        )

        checks = {
            "spotube_foreground": is_spotube_foreground,
            "queue_visible": queue_visible,
            "required_tracks_visible": all(visible_track_checks.values()),
        }
        overall_pass = all(checks.values()) or (
            is_spotube_foreground and state_fallback.get("status") == "PASS"
        )

        metadata = {
            "app_package": app_package,
            "checks": checks,
            "primary_track_query": primary_track_query,
            "queued_track_query": queued_track_query,
            "required_track_queries": required_track_queries,
            "visible_track_checks": visible_track_checks,
            "min_track_count": min_track_count,
            "exact_track_order": exact_track_order,
            "focus_output": focus_output,
            "state_fallback": state_fallback,
        }

        if overall_pass:
            return EvalResult(
                status=EvalStatus.PASS,
                message="Queue view shows both Naina and Zara Zara entries",
                metadata=metadata,
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message=(
                "Spotube queue verification failed: expected Queue view with both "
                f"{primary_track_query} and {queued_track_query}"
            ),
            metadata=metadata,
        )

    @staticmethod
    def _load_state_fallback(
        *,
        controller: Any,
        app_package: str,
        required_track_queries: list[str],
        min_track_count: int,
        exact_track_order: bool,
        expected_loop_mode: str,
        expected_market: str,
        expected_language_code: str,
        expected_audio_source: str,
    ) -> dict[str, Any]:
        try:
            state = read_spotube_state(controller, app_package=app_package)
        except Exception as exc:
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

        tracks = state.get("parsed_tracks") if isinstance(state.get("parsed_tracks"), list) else []
        names = [str(track.get("name") or "").strip() for track in tracks if isinstance(track, dict)]
        preferences = state.get("preferences") if isinstance(state.get("preferences"), dict) else {}
        plugins = state.get("plugins") if isinstance(state.get("plugins"), list) else []
        player_state = state.get("audio_player_state") if isinstance(state.get("audio_player_state"), dict) else {}
        required_checks = {
            query: any(query.lower() in name.lower() for name in names)
            for query in required_track_queries
        }
        ordered_checks = []
        if exact_track_order:
            for index, query in enumerate(required_track_queries):
                observed = names[index] if index < len(names) else ""
                ordered_checks.append(query.lower() in observed.lower())
        locale_text = str(preferences.get("locale") or "")
        selected_plugins = [
            str(plugin.get("name") or "").strip()
            for plugin in plugins
            if int(plugin.get("selected_for_audio_source") or 0) == 1
        ]
        checks = {
            "required_tracks_present": all(required_checks.values()),
            "queue_has_minimum_tracks": len(names) >= min_track_count,
            "exact_track_order": (not exact_track_order) or all(ordered_checks),
            "loop_mode": (not expected_loop_mode)
            or str(player_state.get("loop_mode") or "").strip().lower() == expected_loop_mode.lower(),
            "market": (not expected_market)
            or str(preferences.get("market") or "").strip().upper() == expected_market.upper(),
            "language": (not expected_language_code)
            or f'"languageCode":"{expected_language_code}"' in locale_text
            or f'"languageCode": "{expected_language_code}"' in locale_text,
            "audio_source": (not expected_audio_source)
            or any(expected_audio_source.lower() == plugin.lower() for plugin in selected_plugins),
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "required_track_checks": required_checks,
            "ordered_track_checks": ordered_checks,
            "track_names": names,
            "preferences": preferences,
            "selected_audio_source_plugins": selected_plugins,
            "audio_player_state": player_state,
        }

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

    @staticmethod
    def _dump_ui_and_read(*, controller: Any) -> str | None:
        remote_path = "/sdcard/spotube_queue_naina_zara_eval_ui.xml"
        with tempfile.TemporaryDirectory(prefix="spotube-queue-ui-") as tmpdir:
            local_path = Path(tmpdir) / "spotube_queue_naina_zara_eval_ui.xml"
            controller.execute_adb(["shell", "uiautomator", "dump", remote_path])
            controller.execute_adb(["pull", remote_path, str(local_path)])
            if not local_path.exists() or local_path.stat().st_size <= 0:
                return None
            return local_path.read_text(encoding="utf-8", errors="ignore")

    @staticmethod
    def _collect_ui_tokens(*, ui_dump_text: str) -> list[str]:
        try:
            root = ET.fromstring(ui_dump_text)
        except ET.ParseError:
            return []

        tokens: list[str] = []
        for node in root.iter("node"):
            text = str(node.attrib.get("text") or "").strip()
            desc = str(node.attrib.get("content-desc") or "").strip()
            if text:
                tokens.append(text.lower())
            if desc:
                tokens.append(desc.lower())
        return tokens
