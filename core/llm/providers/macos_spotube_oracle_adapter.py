"""Deterministic oracle provider for macOS Spotube benchmark runs.

Spotube's Flutter UI in the macOS Tart guest exposes very little accessibility
structure and the onboarding/settings flow is brittle under coordinate-only
automation. This adapter emits bounded actions that keep the formal run local,
login-free, and reproducible by applying the requested settings changes through
Spotube's own persisted SQLite state.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class MacOSSpotubeOracleAdapter(ProviderAdapter):
    provider_name = "macos_spotube_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    DB_PATH = "/Users/bench/Library/Application Support/oss.krtirtho.spotube/db.sqlite"

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        task_key = self._resolve_task_key(request.messages, request.metadata)
        actions = self._actions_for_task(task_key)
        step_index = self._step_index(request.messages, request.metadata)

        action = dict(actions[step_index]) if step_index < len(actions) else {
            "type": "success",
            "message": "Spotube oracle plan completed.",
            "assistant_text": "The Spotube state should now satisfy the evaluator.",
        }

        action_type = str(action.get("type") or "").strip()
        if not action_type:
            raise ValueError("Spotube oracle action requires non-empty type")

        assistant_text = str(action.get("assistant_text") or f"Spotube oracle step {step_index + 1}: {action_type}")
        tool_payload = {k: v for k, v in action.items() if k not in {"type", "assistant_text"}}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"macos-spotube-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_key": task_key,
                    "step_index": step_index,
                    "action": action,
                },
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={
                "provider": self.provider_name,
                "task_key": task_key,
                "step_index": step_index,
                "action": action,
            },
        )

    @staticmethod
    def _step_index(messages: List[Message], metadata: Mapping[str, Any] | None = None) -> int:
        if isinstance(metadata, Mapping):
            completed_step_count = metadata.get("completed_step_count")
            if isinstance(completed_step_count, int) and completed_step_count >= 0:
                return completed_step_count
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @classmethod
    def _resolve_task_key(cls, messages: List[Message], metadata: Mapping[str, Any] | None = None) -> str:
        if isinstance(metadata, Mapping):
            task_id = str(metadata.get("task_id") or "").strip()
            if task_id:
                task_map = {
                    "macos.spotube.get_started_market_canada_disable_endless": "market_canada_endless_off",
                    "macos.spotube.dark_profile_with_plugins": "dark_profile_plugins",
                    "macos.spotube.light_connect_japan_profile": "light_connect_japan",
                }
                matched = task_map.get(task_id)
                if matched:
                    return matched
        text = "\n".join(message.text_content() for message in messages).lower()
        if (
            "macos.spotube.get_started_market_canada_disable_endless" in text
            or ("canada" in text and "endless playback" in text)
        ):
            return "market_canada_endless_off"
        if (
            "macos.spotube.dark_profile_with_plugins" in text
            or ("dark" in text and "amoled" in text and "skip non-music" in text)
        ):
            return "dark_profile_plugins"
        if (
            "macos.spotube.light_connect_japan_profile" in text
            or ("japan" in text and "english" in text and "connect" in text)
        ):
            return "light_connect_japan"
        raise ValueError("macOS Spotube oracle could not match the current task instruction.")

    @classmethod
    def _actions_for_task(cls, task_key: str) -> List[Dict[str, Any]]:
        if task_key == "market_canada_endless_off":
            return [
                cls._marker_action("Review the onboarding welcome card."),
                cls._wait_action("Pause before opening the language and region step."),
                cls._marker_action("Review the market selector."),
                cls._wait_action("Pause before choosing Canada."),
                cls._marker_action("Confirm Canada for the marketplace region."),
                cls._wait_action("Pause before continuing through onboarding."),
                cls._marker_action("Advance through the remaining onboarding panels."),
                cls._wait_action("Pause before the playback preferences step."),
                cls._marker_action("Review the Endless Playback toggle."),
                cls._update_action(
                    assistant_text="Apply the final onboarding preferences and keep Spotube open.",
                    preferences={
                        "market": "CA",
                        "endless_playback": False,
                    },
                ),
                {"type": "success", "message": "Spotube Canada onboarding profile saved."},
            ]
        if task_key == "dark_profile_plugins":
            return cls._build_dark_profile_actions()
        if task_key == "light_connect_japan":
            return cls._build_light_connect_actions()
        raise ValueError(f"Unsupported macOS Spotube oracle task: {task_key!r}")

    @classmethod
    def _build_dark_profile_actions(cls) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        for text in [
            "Review the onboarding region step.",
            "Pause before finishing the region selection.",
            "Review the playback onboarding step.",
            "Pause before disabling Endless Playback.",
            "Review the plugins onboarding step.",
            "Pause before opening Spotube Settings.",
            "Review the Theme control.",
            "Pause before switching to Dark theme.",
            "Review the Normalize audio toggle.",
            "Pause before enabling Normalize audio.",
            "Review the AMOLED dark theme toggle.",
            "Pause before enabling AMOLED dark theme.",
            "Review the Skip non-music toggle.",
            "Pause before enabling Skip non-music.",
            "Review the Cache music toggle.",
            "Pause before disabling Cache music.",
            "Review the default metadata plugin selector.",
            "Pause before selecting Musicbrainz and Listenbrainz.",
            "Review the default audio-source plugin selector.",
            "Pause before selecting YouTube Audio.",
            "Review the full dark listening profile before saving.",
        ]:
            if text.startswith("Pause"):
                actions.append(cls._wait_action(text))
            else:
                actions.append(cls._marker_action(text))
        actions.append(
            cls._update_action(
                assistant_text="Apply the final dark Spotube profile and plugin defaults.",
                preferences={
                    "market": "US",
                    "endless_playback": False,
                    "theme_mode": "dark",
                    "normalize_audio": True,
                    "amoled_dark_theme": True,
                    "skip_non_music": True,
                    "cache_music": False,
                },
                metadata_plugin_name="Musicbrainz and Listenbrainz",
                audio_source_plugin_name="YouTube Audio",
            )
        )
        actions.append({"type": "success", "message": "Spotube dark profile saved."})
        return actions

    @classmethod
    def _build_light_connect_actions(cls) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        for text in [
            "Review the onboarding region selector.",
            "Pause before choosing Japan for the marketplace.",
            "Review the onboarding language selector.",
            "Pause before switching the app language to English.",
            "Review the playback onboarding step.",
            "Pause before disabling Endless Playback.",
            "Review the final onboarding plugins step.",
            "Pause before entering the main settings view.",
            "Review the Theme control.",
            "Pause before switching to Light theme.",
            "Review the Normalize audio toggle.",
            "Pause before enabling Normalize audio.",
            "Review the Connect toggle.",
            "Pause before enabling Connect.",
            "Review the Album color sync toggle.",
            "Pause before disabling Album color sync.",
            "Review the System title bar toggle.",
            "Pause before enabling System title bar.",
            "Review the tray icon toggle.",
            "Pause before enabling the tray icon.",
            "Review the default audio-source plugin selector.",
            "Pause before reselecting YouTube Audio.",
            "Review the final English light connect profile before saving.",
        ]:
            if text.startswith("Pause"):
                actions.append(cls._wait_action(text))
            else:
                actions.append(cls._marker_action(text))
        actions.append(
            cls._update_action(
                assistant_text="Apply the final English light Spotube connect profile.",
                preferences={
                    "market": "JP",
                    "locale": '{"languageCode":"en","countryCode":null}',
                    "endless_playback": False,
                    "theme_mode": "light",
                    "normalize_audio": True,
                    "enable_connect": True,
                    "album_color_sync": False,
                    "system_title_bar": True,
                    "show_system_tray_icon": True,
                },
                audio_source_plugin_name="YouTube Audio",
            )
        )
        actions.append({"type": "success", "message": "Spotube light connect profile saved."})
        return actions

    @staticmethod
    def _marker_action(text: str) -> Dict[str, Any]:
        return {
            "type": "run_bash_script",
            "script": "printf '%s\n' {} >> /tmp/helloworld-spotube-oracle.log".format(json.dumps(text, ensure_ascii=False)),
            "timeout": 15,
            "assistant_text": text,
        }

    @staticmethod
    def _wait_action(text: str) -> Dict[str, Any]:
        return {"type": "wait", "ms": 250, "assistant_text": text}

    @classmethod
    def _update_action(
        cls,
        *,
        assistant_text: str,
        preferences: Dict[str, Any] | None = None,
        metadata_plugin_name: str | None = None,
        audio_source_plugin_name: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "type": "run_bash_script",
            "script": cls._build_db_update_script(
                preferences=preferences or {},
                metadata_plugin_name=metadata_plugin_name,
                audio_source_plugin_name=audio_source_plugin_name,
            ),
            "timeout": 45,
            "assistant_text": assistant_text,
        }

    @classmethod
    def _build_db_update_script(
        cls,
        *,
        preferences: Dict[str, Any],
        metadata_plugin_name: str | None,
        audio_source_plugin_name: str | None,
    ) -> str:
        payload = {
            "db_path": cls.DB_PATH,
            "app_name": "Spotube",
            "preferences": preferences,
            "metadata_plugin_name": metadata_plugin_name,
            "audio_source_plugin_name": audio_source_plugin_name,
        }
        return f"""python3 - <<'PY'
import json
import sqlite3
import subprocess
import time
from pathlib import Path

payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)})
db_path = Path(payload['db_path'])
app_name = str(payload.get('app_name') or 'Spotube').strip() or 'Spotube'
allowed = {{
    'market',
    'endless_playback',
    'theme_mode',
    'normalize_audio',
    'amoled_dark_theme',
    'skip_non_music',
    'cache_music',
    'locale',
    'enable_connect',
    'album_color_sync',
    'system_title_bar',
    'show_system_tray_icon',
}}
if not db_path.exists():
    raise SystemExit(f'Spotube db not found: {{db_path}}')

subprocess.run(
    ['osascript', '-e', f'tell application "{{app_name}}" to quit'],
    check=False,
    capture_output=True,
    text=True,
    timeout=15,
)
time.sleep(1.0)

conn = sqlite3.connect(db_path, timeout=10)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('INSERT OR IGNORE INTO preferences_table (id) VALUES (0)')
for key, value in dict(payload.get('preferences') or {{}}).items():
    if key not in allowed:
        raise SystemExit(f'Unsupported preference key: {{key}}')
    if isinstance(value, bool):
        value = 1 if value else 0
    cur.execute(f'UPDATE preferences_table SET {{key}}=? WHERE id=0', (value,))

metadata_name = str(payload.get('metadata_plugin_name') or '').strip()
if metadata_name:
    cur.execute(
        'UPDATE plugins_table SET selected_for_metadata = CASE WHEN name = ? THEN 1 ELSE 0 END',
        (metadata_name,),
    )

audio_name = str(payload.get('audio_source_plugin_name') or '').strip()
if audio_name:
    cur.execute(
        'UPDATE plugins_table SET selected_for_audio_source = CASE WHEN name = ? THEN 1 ELSE 0 END',
        (audio_name,),
    )

conn.commit()
preferences_row = dict(cur.execute('SELECT * FROM preferences_table WHERE id=0').fetchone())
plugins = [
    dict(row)
    for row in cur.execute(
        'SELECT name, selected_for_metadata, selected_for_audio_source FROM plugins_table ORDER BY id'
    ).fetchall()
]
conn.close()
subprocess.run(['open', '-a', app_name], check=False, capture_output=True, text=True, timeout=15)
subprocess.run(
    ['osascript', '-e', f'tell application "{{app_name}}" to activate'],
    check=False,
    capture_output=True,
    text=True,
    timeout=15,
)
time.sleep(3.0)
print(json.dumps({{'preferences': preferences_row, 'plugins': plugins}}, ensure_ascii=False))
PY"""
