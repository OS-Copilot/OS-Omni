"""Evaluator for Android Spotube artist-search play-attempt task."""

from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.android.spotube_support import read_spotube_state


class SpotubeSearchArtistPlayAttemptEvaluator(BaseEvaluator):
    """Validate artist-page navigation and a recent song play attempt signal."""

    DEFAULT_APP_PACKAGE = "oss.krtirtho.spotube"
    DEFAULT_ARTIST_NAME = "Taylor Swift"
    DEFAULT_MAX_MEDIA_UPDATED_AGE_SECONDS = 45

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Spotube evaluation",
            )

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        artist_name = str(params.get("artist_name") or self.DEFAULT_ARTIST_NAME).strip()
        max_updated_age_seconds = float(
            params.get(
                "max_media_updated_age_seconds",
                self.DEFAULT_MAX_MEDIA_UPDATED_AGE_SECONDS,
            )
            or 0.0
        )

        if not app_package or not artist_name:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params app_package and artist_name are required",
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
                },
            )

        ui_tokens, mini_player_text = self._collect_ui_tokens_and_miniplayer(
            ui_dump_text=ui_dump_text,
        )
        artist_token = artist_name.lower()
        artist_visible = any(artist_token in token for token in ui_tokens)
        mini_player_has_artist = artist_token in mini_player_text

        media_dump = str(controller.execute_adb(["shell", "dumpsys", "media_session"]) or "")
        media_info = self._extract_spotube_media_info(media_dump=media_dump, app_package=app_package)
        uptime_seconds = self._get_uptime_seconds(controller)
        media_age_seconds = None
        if uptime_seconds is not None and media_info.get("updated_ms") is not None:
            media_age_seconds = max(
                0.0,
                (uptime_seconds * 1000.0 - float(media_info["updated_ms"])) / 1000.0,
            )

        has_recent_play_attempt = bool(
            media_info.get("session_found")
            and media_info.get("metadata_non_null")
            and (
                (
                    media_age_seconds is not None
                    and media_age_seconds <= max(max_updated_age_seconds, 0.0)
                )
                or mini_player_has_artist
            )
        )
        state_fallback = self._load_state_fallback(
            controller=controller,
            app_package=app_package,
            artist_name=artist_name,
        )

        if (
            is_spotube_foreground
            and artist_visible
            and has_recent_play_attempt
            and mini_player_has_artist
        ):
            return EvalResult(
                status=EvalStatus.PASS,
                message="Spotube shows the target artist and a recent song click/play-attempt signal",
                metadata={
                    "app_package": app_package,
                    "artist_name": artist_name,
                    "is_spotube_foreground": is_spotube_foreground,
                    "artist_visible": artist_visible,
                    "media_session_state": media_info.get("state"),
                    "media_updated_ms": media_info.get("updated_ms"),
                    "media_age_seconds": media_age_seconds,
                    "max_media_updated_age_seconds": max_updated_age_seconds,
                    "metadata_non_null": media_info.get("metadata_non_null"),
                    "mini_player_text": mini_player_text,
                    "mini_player_has_artist": mini_player_has_artist,
                    "state_fallback": state_fallback,
                },
            )

        if is_spotube_foreground and has_recent_play_attempt and state_fallback.get("artist_match"):
            return EvalResult(
                status=EvalStatus.PASS,
                message="Spotube player state and recent media-session signal match the target artist",
                metadata={
                    "app_package": app_package,
                    "artist_name": artist_name,
                    "is_spotube_foreground": is_spotube_foreground,
                    "artist_visible": artist_visible,
                    "media_session_state": media_info.get("state"),
                    "media_updated_ms": media_info.get("updated_ms"),
                    "media_age_seconds": media_age_seconds,
                    "max_media_updated_age_seconds": max_updated_age_seconds,
                    "metadata_non_null": media_info.get("metadata_non_null"),
                    "mini_player_text": mini_player_text,
                    "mini_player_has_artist": mini_player_has_artist,
                    "state_fallback": state_fallback,
                },
            )

        if (
            is_spotube_foreground
            and media_info.get("session_found")
            and media_info.get("metadata_non_null")
            and state_fallback.get("artist_match")
        ):
            return EvalResult(
                status=EvalStatus.PASS,
                message="Spotube persisted player state matches the target artist",
                metadata={
                    "app_package": app_package,
                    "artist_name": artist_name,
                    "is_spotube_foreground": is_spotube_foreground,
                    "artist_visible": artist_visible,
                    "media_session_state": media_info.get("state"),
                    "media_updated_ms": media_info.get("updated_ms"),
                    "media_age_seconds": media_age_seconds,
                    "max_media_updated_age_seconds": max_updated_age_seconds,
                    "metadata_non_null": media_info.get("metadata_non_null"),
                    "mini_player_text": mini_player_text,
                    "mini_player_has_artist": mini_player_has_artist,
                    "state_fallback": state_fallback,
                },
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message=(
                "Spotube task verification failed: need artist-page evidence and a recent song click signal "
                "(without requiring actual playback success)"
            ),
            metadata={
                "app_package": app_package,
                "artist_name": artist_name,
                "is_spotube_foreground": is_spotube_foreground,
                "artist_visible": artist_visible,
                "media_session_found": media_info.get("session_found"),
                "media_session_state": media_info.get("state"),
                "media_updated_ms": media_info.get("updated_ms"),
                "media_age_seconds": media_age_seconds,
                "max_media_updated_age_seconds": max_updated_age_seconds,
                "metadata_non_null": media_info.get("metadata_non_null"),
                "mini_player_text": mini_player_text,
                "mini_player_has_artist": mini_player_has_artist,
                "focus_output": focus_output,
                "state_fallback": state_fallback,
            },
        )

    @staticmethod
    def _load_state_fallback(
        *,
        controller: Any,
        app_package: str,
        artist_name: str,
    ) -> dict[str, Any]:
        try:
            state = read_spotube_state(controller, app_package=app_package)
        except Exception as exc:
            return {"loaded": False, "error": f"{type(exc).__name__}: {exc}"}

        tracks = state.get("parsed_tracks") if isinstance(state.get("parsed_tracks"), list) else []
        artist_token = artist_name.lower()
        artist_match = False
        active_track_name = ""
        for track in tracks:
            if not isinstance(track, dict):
                continue
            track_name = str(track.get("name") or "").strip()
            if not active_track_name and track_name:
                active_track_name = track_name
            artists = track.get("artists") if isinstance(track.get("artists"), list) else []
            artist_names = [str(item.get("name") or "").strip() for item in artists if isinstance(item, dict)]
            combined = "\n".join([track_name, *artist_names]).lower()
            if artist_token in combined:
                artist_match = True
                if track_name:
                    active_track_name = track_name
                break

        return {
            "loaded": True,
            "artist_match": artist_match,
            "active_track_name": active_track_name,
            "track_count": len(tracks),
        }

    @staticmethod
    def _is_foreground(*, controller: Any, app_package: str) -> tuple[bool, str]:
        window_dump = str(controller.execute_adb(["shell", "dumpsys", "window"]) or "")
        activity_dump = str(controller.execute_adb(["shell", "dumpsys", "activity", "activities"]) or "")

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
        remote_path = "/sdcard/spotube_eval_ui.xml"
        with tempfile.TemporaryDirectory(prefix="spotube-ui-") as tmpdir:
            local_path = Path(tmpdir) / "spotube_eval_ui.xml"
            controller.execute_adb(["shell", "uiautomator", "dump", remote_path])
            controller.execute_adb(["pull", remote_path, str(local_path)])
            if not local_path.exists() or local_path.stat().st_size <= 0:
                return None
            return local_path.read_text(encoding="utf-8", errors="ignore")

    @staticmethod
    def _collect_ui_tokens_and_miniplayer(*, ui_dump_text: str) -> tuple[list[str], str]:
        tokens: list[str] = []
        mini_player_text = ""
        try:
            root = ET.fromstring(ui_dump_text)
        except ET.ParseError:
            return tokens, mini_player_text

        display_height = 0
        for node in root.iter("node"):
            bounds = str(node.attrib.get("bounds") or "")
            matched = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not matched:
                continue
            y2 = int(matched.group(4))
            if y2 > display_height:
                display_height = y2

        for node in root.iter("node"):
            text = str(node.attrib.get("text") or "").strip()
            desc = str(node.attrib.get("content-desc") or "").strip()
            if text:
                tokens.append(text.lower())
            if desc:
                tokens.append(desc.lower())

            # Mini-player in Spotube is typically an ImageView with multiline content-desc
            # near the bottom; we require this stronger evidence to avoid false PASS.
            node_class = str(node.attrib.get("class") or "")
            if node_class != "android.widget.ImageView":
                continue
            if "\n" not in desc:
                continue
            bounds = str(node.attrib.get("bounds") or "")
            matched = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not matched:
                continue
            y1 = int(matched.group(2))
            if display_height > 0 and y1 < int(display_height * 0.72):
                continue
            mini_player_text = desc.lower()

        return tokens, mini_player_text

    @staticmethod
    def _extract_spotube_media_info(*, media_dump: str, app_package: str) -> dict[str, Any]:
        package_line = f"package={app_package}"
        lines = media_dump.splitlines()
        block_lines: list[str] = []

        for idx, line in enumerate(lines):
            if package_line not in line:
                continue
            start = max(0, idx - 8)
            end = min(len(lines), idx + 20)
            block_lines = lines[start:end]
            break

        if not block_lines:
            return {
                "session_found": False,
                "state": None,
                "updated_ms": None,
                "metadata_non_null": False,
            }

        block_text = "\n".join(block_lines)
        state_match = re.search(r"state=PlaybackState \{state=([A-Z_]+)\(\d+\).*?updated=(\d+)", block_text)
        metadata_non_null = bool(re.search(r"metadata:\s*(?!null\b).+", block_text))

        return {
            "session_found": True,
            "state": state_match.group(1) if state_match else None,
            "updated_ms": int(state_match.group(2)) if state_match else None,
            "metadata_non_null": metadata_non_null,
        }

    @staticmethod
    def _get_uptime_seconds(controller: Any) -> float | None:
        raw = str(controller.execute_adb(["shell", "cat", "/proc/uptime"]) or "").strip()
        if not raw:
            return None
        first = raw.split()[0]
        try:
            return float(first)
        except ValueError:
            return None
