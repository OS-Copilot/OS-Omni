"""SQLite-backed evaluator for Spotube desktop tasks on Linux."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class SpotubeStateEvaluator(BaseEvaluator):
    """Validate Spotube preferences and current player state through SQLite."""

    DEFAULT_TIMEOUT = 20
    DEFAULT_DB_PATH = "/home/user/.local/share/spotube/db.sqlite"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        db_path = str(params.get("db_path") or self.DEFAULT_DB_PATH).strip()
        expectations = dict(params.get("state") or {})
        if not expectations:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.state is required")

        prefer_rhythmbox = self._should_prefer_rhythmbox(expectations)
        if prefer_rhythmbox:
            payload = self._evaluate_rhythmbox(controller, timeout=timeout)
            if payload is None:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message="Rhythmbox evaluator could not read player state",
                )
            try:
                self._validate(expectations, payload)
            except AssertionError as exc:
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payload)
            except Exception as exc:
                return EvalResult(status=EvalStatus.ERROR, message=f"Spotube evaluator failed: {exc}", metadata=payload)
            return EvalResult(status=EvalStatus.PASS, message="Spotube state evaluation passed", metadata=payload)

        script = f"""python3 - <<'PY'
import json
import sqlite3

db_path = {json.dumps(db_path, ensure_ascii=False)}
con = sqlite3.connect(db_path)
cur = con.cursor()

pref_row = cur.execute(
    "select market, locale, local_library_location from preferences_table limit 1"
).fetchone()
player_row = cur.execute(
    "select playing, loop_mode, shuffled, tracks, current_index from audio_player_state_table limit 1"
).fetchone()

payload = {{
    "preferences": {{
        "market": pref_row[0] if pref_row else None,
        "locale": pref_row[1] if pref_row else None,
        "local_library_location": pref_row[2] if pref_row else None,
    }},
    "player": {{
        "playing": bool(player_row[0]) if player_row else False,
        "loop_mode": player_row[1] if player_row else None,
        "shuffled": bool(player_row[2]) if player_row else False,
        "current_index": int(player_row[4]) if player_row else -1,
        "tracks": json.loads(player_row[3]) if player_row and player_row[3] else [],
    }},
}}

tracks = list(payload["player"]["tracks"])
current_index = int(payload["player"]["current_index"])
if 0 <= current_index < len(tracks):
    payload["player"]["current_track"] = tracks[current_index]
else:
    payload["player"]["current_track"] = None

print(json.dumps(payload, ensure_ascii=False))
PY"""

        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            fallback = self._evaluate_rhythmbox(controller, timeout=timeout)
            if fallback is None:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=output or f"guest command failed with exit code {returncode}",
                )
            payload = fallback
        else:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Spotube evaluator returned invalid JSON: {exc}: {output}",
                )

        try:
            self._validate(expectations, payload)
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payload)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Spotube evaluator failed: {exc}", metadata=payload)

        return EvalResult(status=EvalStatus.PASS, message="Spotube state evaluation passed", metadata=payload)

    @staticmethod
    def _evaluate_rhythmbox(controller: Any, *, timeout: int) -> Mapping[str, Any] | None:
        script = """python3 - <<'PY'
import json
import pathlib
import re
import subprocess
import urllib.parse

def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)

check = run(["rhythmbox-client", "--check-running"])
if check.returncode != 0:
    raise SystemExit(1)

title = run(["rhythmbox-client", "--print-playing-format", "%tt"]).stdout.strip()
title = pathlib.Path(title).stem if title else ""
uri = run(["rhythmbox-client", "--print-playing-format", "%tu"]).stdout.strip()
if uri == "%tu":
    uri = ""
if not uri:
    metadata_output = run(
        [
            "dbus-send",
            "--print-reply",
            "--dest=org.mpris.MediaPlayer2.rhythmbox",
            "/org/mpris/MediaPlayer2",
            "org.freedesktop.DBus.Properties.Get",
            "string:org.mpris.MediaPlayer2.Player",
            "string:Metadata",
        ]
    ).stdout
    candidates = re.findall(r'string "(file://[^"]+)"', metadata_output)
    if candidates:
        uri = candidates[0]
    else:
        match = re.search(r'string "xesam:url".*?variant\\s+string "(.*?)"', metadata_output, re.S)
        if match:
            uri = match.group(1).strip()
track_path = ""
if uri.startswith("file://"):
    track_path = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
elif uri:
    track_path = uri
status_output = run(
    [
        "dbus-send",
        "--print-reply",
        "--dest=org.mpris.MediaPlayer2.rhythmbox",
        "/org/mpris/MediaPlayer2",
        "org.freedesktop.DBus.Properties.Get",
        "string:org.mpris.MediaPlayer2.Player",
        "string:PlaybackStatus",
    ]
).stdout
match = re.search(r'string "(.*?)"', status_output)
playback_status = match.group(1) if match else ""
payload = {
    "preferences": {},
    "player": {
        "playing": playback_status == "Playing",
        "loop_mode": None,
        "shuffled": False,
        "current_track": {"name": title, "path": track_path},
    },
}
print(json.dumps(payload, ensure_ascii=False))
PY"""
        script = "\n".join(
            [
                "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}",
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                script,
            ]
        )
        result = controller.run_bash_script(script, timeout=timeout)
        if int(result.get("returncode", -1)) != 0:
            return None
        output = str(result.get("output", "")).strip()
        if not output:
            return None
        return json.loads(output)

    @staticmethod
    def _validate(expectations: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        preferences = dict(payload.get("preferences") or {})
        player = dict(payload.get("player") or {})
        current_track = dict(player.get("current_track") or {})

        if "market" in expectations:
            actual = str(preferences.get("market") or "")
            expected = str(expectations.get("market") or "")
            assert actual == expected, f"expected market={expected}, got {actual}"

        if "locale" in expectations:
            actual = str(preferences.get("locale") or "")
            expected = str(expectations.get("locale") or "")
            assert actual == expected, f"expected locale={expected}, got {actual}"

        if "local_library_location" in expectations:
            actual = str(preferences.get("local_library_location") or "")
            expected = str(expectations.get("local_library_location") or "")
            assert actual == expected, f"expected local_library_location={expected}, got {actual}"

        if "playing" in expectations:
            actual = bool(player.get("playing"))
            expected = bool(expectations.get("playing"))
            assert actual == expected, f"expected playing={expected}, got {actual}"

        if "loop_mode" in expectations:
            actual = str(player.get("loop_mode") or "")
            expected = str(expectations.get("loop_mode") or "")
            assert actual == expected, f"expected loop_mode={expected}, got {actual}"

        if "shuffled" in expectations:
            actual = bool(player.get("shuffled"))
            expected = bool(expectations.get("shuffled"))
            assert actual == expected, f"expected shuffled={expected}, got {actual}"

        if "current_track_name" in expectations:
            actual = str(current_track.get("name") or "")
            expected = str(expectations.get("current_track_name") or "")
            assert actual == expected, f"expected current track name={expected}, got {actual}"

        if "current_track_path" in expectations:
            actual = str(current_track.get("path") or "")
            expected = str(expectations.get("current_track_path") or "")
            assert actual == expected, f"expected current track path={expected}, got {actual}"

    @staticmethod
    def _should_prefer_rhythmbox(expectations: Mapping[str, Any]) -> bool:
        if not expectations:
            return False
        rhythmbox_keys = {"playing", "current_track_name", "current_track_path"}
        return set(expectations).issubset(rhythmbox_keys)
