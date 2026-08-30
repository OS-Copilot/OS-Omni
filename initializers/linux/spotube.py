"""Initializer utilities for Spotube desktop tasks on Linux."""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class SpotubeInitializer(BaseInitializer):
    """Reset Spotube into a deterministic welcome state and seed local libraries."""

    DEFAULT_APP_COMMAND = "spotube"
    DEFAULT_FALLBACK_COMMANDS = ("rhythmbox",)
    DEFAULT_FINAL_WAIT_MS = 3500
    DEFAULT_TRACK_DURATION_SECONDS = 180
    DEFAULT_SAMPLE_RATE = 22050

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        libraries = self._normalize_libraries(params.get("libraries"))
        autoplay_track_name = str(params.get("autoplay_track_name") or "").strip()

        try:
            app_command = self._resolve_app_command(controller, app_command, params.get("fallback_app_commands"))
            self._stop_app(controller)
            self._clear_app_state(controller, app_command)
            if libraries:
                self._seed_libraries(controller, libraries)
            self._launch_app(controller, app_command)
            if autoplay_track_name:
                self._autoplay_track(
                    controller,
                    app_command=app_command,
                    libraries=libraries,
                    track_name=autoplay_track_name,
                )
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Spotube app state: {exc}",
                metadata={"app_command": app_command, "library_count": len(libraries)},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Spotube welcome state",
            metadata={
                "app_command": app_command,
                "library_count": len(libraries),
                "libraries": [
                    {
                        "path": library["path"],
                        "display_name": library["display_name"],
                        "track_count": len(library["tracks"]),
                    }
                    for library in libraries
                ],
            },
        )

    def _resolve_app_command(
        self,
        controller: Any,
        app_command: str,
        raw_fallbacks: Any,
    ) -> str:
        candidates = [app_command]
        if isinstance(raw_fallbacks, list):
            candidates.extend(str(item).strip() for item in raw_fallbacks if str(item).strip())
        else:
            candidates.extend(self.DEFAULT_FALLBACK_COMMANDS)
        for candidate in candidates:
            if not candidate:
                continue
            result = controller.run_bash_script(
                f"command -v {shlex.quote(candidate)} >/dev/null 2>&1",
                timeout=10,
            )
            if int(result.get("returncode", -1)) == 0:
                return candidate
        raise RuntimeError(f"no compatible music app found for requested command {app_command!r}")

    @classmethod
    def _normalize_libraries(cls, raw_libraries: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        if not isinstance(raw_libraries, list):
            return normalized

        for index, raw_library in enumerate(raw_libraries):
            if not isinstance(raw_library, Mapping):
                continue

            root_segments = raw_library.get("root_segments")
            if not isinstance(root_segments, list) or not root_segments:
                continue
            segments = [str(item).strip() for item in root_segments if str(item).strip()]
            if not segments:
                continue

            display_name = str(raw_library.get("display_name") or segments[-1]).strip() or segments[-1]
            duration_seconds = int(
                raw_library.get("duration_seconds", cls.DEFAULT_TRACK_DURATION_SECONDS) or cls.DEFAULT_TRACK_DURATION_SECONDS
            )
            sample_rate = int(raw_library.get("sample_rate", cls.DEFAULT_SAMPLE_RATE) or cls.DEFAULT_SAMPLE_RATE)

            tracks: list[dict[str, Any]] = []
            for track_index, raw_track in enumerate(raw_library.get("tracks") or []):
                if not isinstance(raw_track, Mapping):
                    continue
                base_name = str(raw_track.get("name") or "").strip()
                if not base_name:
                    continue
                filename = str(raw_track.get("filename") or f"{base_name}.wav").strip() or f"{base_name}.wav"
                frequency_hz = float(raw_track.get("frequency_hz", 330.0 + track_index * 30.0) or 330.0)
                tracks.append(
                    {
                        "name": base_name,
                        "filename": filename,
                        "frequency_hz": frequency_hz,
                    }
                )

            if not tracks:
                continue

            normalized.append(
                {
                    "display_name": display_name,
                    "root_segments": segments,
                    "path": f"/home/user/Music/{'/'.join(segments)}",
                    "duration_seconds": duration_seconds,
                    "sample_rate": sample_rate,
                    "tracks": tracks,
                    "seed_root": segments[0],
                    "seed_index": index,
                }
            )
        return normalized

    @staticmethod
    def _run(controller: Any, script: str, *, timeout: int) -> Mapping[str, Any]:
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        if returncode != 0:
            output = str(result.get("output", "")).strip()
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        return result

    def _stop_app(self, controller: Any) -> None:
        self._run(
            controller,
            "\n".join(
                [
                    "pkill -TERM -f 'spotube' || true",
                    "sleep 1",
                    "pkill -KILL -f 'spotube' || true",
                    "sleep 1",
                ]
            ),
            timeout=15,
        )

    def _clear_app_state(self, controller: Any, app_command: str) -> None:
        if app_command == "rhythmbox":
            self._run(
                controller,
                "\n".join(
                    [
                        "rm -rf /home/user/.local/share/rhythmbox",
                        "mkdir -p /home/user/.local/share",
                    ]
                ),
                timeout=20,
            )
            return

        self._run(
            controller,
            "\n".join(
                [
                    "rm -rf /home/user/.local/share/spotube",
                    "mkdir -p /home/user/.local/share",
                ]
            ),
            timeout=20,
        )

    def _seed_libraries(self, controller: Any, libraries: list[dict[str, Any]]) -> None:
        payload = json.dumps({"libraries": libraries}, ensure_ascii=False)
        script = f"""python3 - <<'PY'
import json
import math
import pathlib
import shutil
import struct
import wave

payload = json.loads({json.dumps(payload, ensure_ascii=False)})
music_root = pathlib.Path("/home/user/Music")
music_root.mkdir(parents=True, exist_ok=True)

for library in payload["libraries"]:
    seed_root = music_root / str(library["seed_root"])
    if seed_root.exists():
        shutil.rmtree(seed_root)

for library in payload["libraries"]:
    library_path = pathlib.Path(str(library["path"]))
    library_path.mkdir(parents=True, exist_ok=True)
    sample_rate = int(library["sample_rate"])
    duration_seconds = int(library["duration_seconds"])
    total_frames = sample_rate * duration_seconds
    for track in library["tracks"]:
        file_path = library_path / str(track["filename"])
        frequency = float(track["frequency_hz"])
        with wave.open(str(file_path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            frames = bytearray()
            for index in range(total_frames):
                value = int(32767 * 0.18 * math.sin(2 * math.pi * frequency * index / sample_rate))
                frames.extend(struct.pack("<h", value))
            wav_file.writeframes(bytes(frames))
print(json.dumps({{"status": "ok", "library_count": len(payload["libraries"])}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=120)

    def _launch_app(self, controller: Any, app_command: str) -> None:
        launch_script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                f"setsid -f bash -lc {shlex.quote(app_command)} >/dev/null 2>&1",
            ]
        )
        self._run(controller, launch_script, timeout=15)

    def _autoplay_track(
        self,
        controller: Any,
        *,
        app_command: str,
        libraries: list[dict[str, Any]],
        track_name: str,
    ) -> None:
        matched_path = ""
        for library in libraries:
            library_path = str(library.get("path") or "").rstrip("/")
            for track in library.get("tracks") or []:
                if str(track.get("name") or "").strip() == track_name:
                    matched_path = f"{library_path}/{str(track.get('filename') or '').strip()}"
                    break
            if matched_path:
                break

        if not matched_path:
            raise RuntimeError(f"autoplay track not found in seeded libraries: {track_name}")

        if app_command != "rhythmbox":
            raise RuntimeError("autoplay_track_name currently supports only Rhythmbox-backed tasks")

        file_uri = f"file://{matched_path}"
        script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                "sleep 2",
                f"rhythmbox-client --no-start --clear-queue || true",
                f"rhythmbox-client --no-start --enqueue {shlex.quote(file_uri)}",
                "sleep 1",
                "rhythmbox-client --no-start --play",
            ]
        )
        self._run(controller, script, timeout=30)
