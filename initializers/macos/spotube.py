"""Prepare a deterministic Spotube baseline on macOS."""

from __future__ import annotations

import json
import time
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus

_BOOTSTRAP_SCRIPT = r'''
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

params = json.loads(__PARAMS_JSON__)
app_name = str(params.get("app_name") or "Spotube").strip() or "Spotube"
bundle_id = str(params.get("bundle_id") or "oss.krtirtho.spotube").strip() or "oss.krtirtho.spotube"
done_key = str(params.get("done_key") or "doneGettingStarted").strip() or "doneGettingStarted"
allow_headless_fallback = bool(params.get("allow_headless_fallback", False))
state_root = Path(
    os.path.expanduser(
        str(params.get("state_root") or f"~/Library/Application Support/{bundle_id}")
    )
)
preferences_path = Path(
    os.path.expanduser(
        str(params.get("preferences_path") or f"~/Library/Preferences/{bundle_id}.plist")
    )
)
db_path = state_root / "db.sqlite"
plugin_root = state_root / "metadata-plugins"
bootstrap_timeout = int(params.get("bootstrap_timeout", 120) or 120)
poll_interval = float(params.get("poll_interval_seconds", 1.0) or 1.0)
baseline_market = str(params.get("baseline_market") or "US").strip().upper() or "US"
baseline_endless_playback = bool(params.get("baseline_endless_playback", True))
expected_plugin_names = [
    str(item).strip()
    for item in (
        params.get("expected_plugin_names")
        or ["Musicbrainz and Listenbrainz", "YouTube Audio"]
    )
    if str(item).strip()
]
quit_wait_seconds = float(params.get("quit_wait_seconds", 2.0) or 2.0)

result = {
    "status": "fail",
    "message": "Spotube bootstrap failed",
    "app_name": app_name,
    "bundle_id": bundle_id,
    "state_root": str(state_root),
    "preferences_path": str(preferences_path),
    "db_path": str(db_path),
    "plugin_root": str(plugin_root),
    "expected_plugin_names": expected_plugin_names,
    "allow_headless_fallback": allow_headless_fallback,
    "logs": [],
}


def run(command, *, check=False, timeout=30):
    proc = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    entry = {
        "command": command,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-1200:],
        "stderr": (proc.stderr or "")[-1200:],
    }
    result["logs"].append(entry)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(command)} :: {entry['stderr'] or entry['stdout']}"
        )
    return proc


def quit_app():
    run(["osascript", "-e", f'tell application "{app_name}" to quit'], timeout=15)
    time.sleep(quit_wait_seconds)
    run(["pkill", "-x", app_name], timeout=15)
    time.sleep(1.0)


def resolve_app_target():
    candidates = [
        Path.home() / "Applications" / f"{app_name}.app",
        Path("/Applications") / f"{app_name}.app",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate)

    queries = [
        f'kMDItemCFBundleIdentifier == "{bundle_id}"',
        f'kMDItemFSName == "{app_name}.app"',
    ]
    for query in queries:
        proc = run(["mdfind", query], check=False, timeout=15)
        if proc.returncode != 0:
            continue
        for line in (proc.stdout or "").splitlines():
            path = Path(line.strip())
            if path.suffix == ".app" and path.is_dir():
                return str(path)

    return app_name


def snapshot_database(path: Path):
    workdir = Path(tempfile.mkdtemp(prefix="spotube-bootstrap-"))
    local_db = workdir / "db.sqlite"
    shutil.copy2(path, local_db)
    for suffix in ("-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, workdir / ("db.sqlite" + suffix))
    return workdir, local_db


def create_headless_fallback_state(reason: str):
    state_root.mkdir(parents=True, exist_ok=True)
    plugin_root.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS plugins_table (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            author TEXT NOT NULL,
            selected_for_metadata INTEGER NOT NULL DEFAULT 0,
            selected_for_audio_source INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS preferences_table (
            id INTEGER PRIMARY KEY,
            market TEXT NOT NULL DEFAULT 'US',
            endless_playback INTEGER NOT NULL DEFAULT 1,
            audio_source_id TEXT,
            album_color_sync INTEGER NOT NULL DEFAULT 1,
            amoled_dark_theme INTEGER NOT NULL DEFAULT 0,
            normalize_audio INTEGER NOT NULL DEFAULT 0,
            show_system_tray_icon INTEGER NOT NULL DEFAULT 0,
            system_title_bar INTEGER NOT NULL DEFAULT 0,
            skip_non_music INTEGER NOT NULL DEFAULT 0,
            close_behavior TEXT NOT NULL DEFAULT 'close',
            layout_mode TEXT NOT NULL DEFAULT 'adaptive',
            locale TEXT NOT NULL DEFAULT '{"languageCode":"system","countryCode":"system"}',
            search_mode TEXT NOT NULL DEFAULT 'youtube',
            theme_mode TEXT NOT NULL DEFAULT 'system',
            youtube_client_engine TEXT NOT NULL DEFAULT 'youtubeExplode',
            enable_connect INTEGER NOT NULL DEFAULT 0,
            connect_port INTEGER NOT NULL DEFAULT -1,
            cache_music INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    cur.execute('DELETE FROM plugins_table')
    cur.execute('DELETE FROM preferences_table')
    cur.executemany(
        'INSERT INTO plugins_table (id, name, author, selected_for_metadata, selected_for_audio_source) VALUES (?, ?, ?, ?, ?)',
        [
            (1, 'Musicbrainz and Listenbrainz', 'Spotube', 0, 0),
            (2, 'YouTube Audio', 'Spotube', 0, 0),
        ],
    )
    cur.execute(
        """
        INSERT INTO preferences_table (
            id,
            market,
            endless_playback,
            audio_source_id,
            album_color_sync,
            amoled_dark_theme,
            normalize_audio,
            show_system_tray_icon,
            system_title_bar,
            skip_non_music,
            close_behavior,
            layout_mode,
            locale,
            search_mode,
            theme_mode,
            youtube_client_engine,
            enable_connect,
            connect_port,
            cache_music
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            0,
            baseline_market,
            1 if baseline_endless_playback else 0,
            None,
            1,
            0,
            0,
            0,
            0,
            0,
            'close',
            'adaptive',
            '{"languageCode":"system","countryCode":"system"}',
            'youtube',
            'system',
            'youtubeExplode',
            0,
            -1,
            1,
        ),
    )
    conn.commit()
    preferences = cur.execute(
        'SELECT id, market, endless_playback, theme_mode, locale, cache_music FROM preferences_table WHERE id=0'
    ).fetchone()
    plugins = [
        dict(row)
        for row in conn.execute(
            'SELECT name, author, selected_for_metadata, selected_for_audio_source FROM plugins_table ORDER BY id'
        ).fetchall()
    ]
    conn.close()
    return {
        'mode': 'headless_fallback',
        'reason': reason,
        'plugins': plugins,
        'preferences': dict(preferences) if preferences else None,
        'launch_app_after_bootstrap': False,
    }


try:
    quit_app()
    shutil.rmtree(state_root, ignore_errors=True)
    if preferences_path.exists():
        preferences_path.unlink()
    run(["defaults", "delete", bundle_id], timeout=15)
    run(["defaults", "write", bundle_id, done_key, "-bool", "true"], check=True, timeout=15)
    preferences_path.parent.mkdir(parents=True, exist_ok=True)
    with preferences_path.open("wb") as fh:
        plistlib.dump({done_key: True}, fh)

    app_target = resolve_app_target()
    result["app_target"] = app_target
    open_proc = run(["open", "-a", app_target], check=False, timeout=20)

    bootstrap_snapshot = None
    last_probe = None
    if open_proc.returncode == 0:
        deadline = time.time() + bootstrap_timeout
        while time.time() < deadline:
            if not db_path.exists():
                time.sleep(poll_interval)
                continue
            try:
                workdir, local_db = snapshot_database(db_path)
                try:
                    conn = sqlite3.connect(local_db)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    tables = {
                        row[0]
                        for row in cur.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                    if "plugins_table" not in tables or "preferences_table" not in tables:
                        last_probe = {"tables": sorted(tables)}
                        conn.close()
                        shutil.rmtree(workdir, ignore_errors=True)
                        time.sleep(poll_interval)
                        continue
                    plugins = [
                        dict(row)
                        for row in cur.execute(
                            "SELECT name, author, selected_for_metadata, selected_for_audio_source FROM plugins_table ORDER BY id"
                        ).fetchall()
                    ]
                    preferences = cur.execute(
                        "SELECT id, market, endless_playback FROM preferences_table ORDER BY id LIMIT 1"
                    ).fetchone()
                    probe = {
                        "tables": sorted(tables),
                        "plugins": plugins,
                        "preferences": dict(preferences) if preferences else None,
                    }
                    last_probe = probe
                    observed_names = {str(item.get("name") or "") for item in plugins}
                    if all(name in observed_names for name in expected_plugin_names) and preferences is not None:
                        bootstrap_snapshot = probe
                        conn.close()
                        shutil.rmtree(workdir, ignore_errors=True)
                        break
                    conn.close()
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)
            except Exception as exc:
                last_probe = {"error": str(exc)}
            time.sleep(poll_interval)
    elif allow_headless_fallback:
        last_probe = {
            "fallback_reason": open_proc.stderr or open_proc.stdout or f"open -a {app_target} failed",
            "open_returncode": open_proc.returncode,
        }
        bootstrap_snapshot = create_headless_fallback_state(str(last_probe["fallback_reason"]))
    else:
        raise RuntimeError(
            f"command failed ({open_proc.returncode}): open -a {app_target} :: "
            f"{open_proc.stderr or open_proc.stdout}"
        )

    result["bootstrap_probe"] = last_probe
    if bootstrap_snapshot is None:
        if allow_headless_fallback:
            bootstrap_snapshot = create_headless_fallback_state(
                "Spotube did not create the expected plugin and preference state before timeout"
            )
        else:
            raise RuntimeError("Spotube did not create the expected plugin and preference state before timeout")

    if bootstrap_snapshot.get("launch_app_after_bootstrap", True):
        quit_app()

    state_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO preferences_table (id) VALUES (0)")
    cur.execute(
        """
        UPDATE preferences_table
        SET market=?,
            endless_playback=?,
            audio_source_id=NULL,
            album_color_sync=1,
            amoled_dark_theme=0,
            normalize_audio=0,
            show_system_tray_icon=0,
            system_title_bar=0,
            skip_non_music=0,
            close_behavior='close',
            layout_mode='adaptive',
            locale='{"languageCode":"system","countryCode":"system"}',
            search_mode='youtube',
            theme_mode='system',
            youtube_client_engine='youtubeExplode',
            enable_connect=0,
            connect_port=-1,
            cache_music=1
        WHERE id=0
        """,
        (baseline_market, 1 if baseline_endless_playback else 0),
    )
    cur.execute(
        "UPDATE plugins_table SET selected_for_metadata=0, selected_for_audio_source=0"
    )
    conn.commit()
    plugin_rows = [
        dict(row)
        for row in cur.execute(
            "SELECT name, author, selected_for_metadata, selected_for_audio_source FROM plugins_table ORDER BY id"
        ).fetchall()
    ]
    preferences_row = cur.execute(
        "SELECT id, market, endless_playback, audio_source_id FROM preferences_table WHERE id=0"
    ).fetchone()
    conn.close()

    result["plugins"] = plugin_rows
    result["preferences"] = dict(preferences_row) if preferences_row else None
    result["launch_app_after_bootstrap"] = bool(bootstrap_snapshot.get("launch_app_after_bootstrap", True))
    result["bootstrap_mode"] = str(bootstrap_snapshot.get("mode") or "app_bootstrap")

    if not plugin_rows:
        raise RuntimeError("Spotube plugins_table is empty after bootstrap")
    if preferences_row is None:
        raise RuntimeError("Spotube preferences_table row id=0 is missing after bootstrap")
    if any(int(row.get("selected_for_metadata") or 0) for row in plugin_rows):
        raise RuntimeError("baseline metadata plugin should be cleared before the task starts")
    if any(int(row.get("selected_for_audio_source") or 0) for row in plugin_rows):
        raise RuntimeError("baseline audio-source plugin should be cleared before the task starts")
    if str(preferences_row["market"] or "").upper() != baseline_market:
        raise RuntimeError(
            f"baseline market mismatch: expected {baseline_market}, observed {preferences_row['market']}"
        )
    if bool(preferences_row["endless_playback"]) != baseline_endless_playback:
        raise RuntimeError(
            "baseline endless_playback mismatch: "
            f"expected {baseline_endless_playback}, observed {bool(preferences_row['endless_playback'])}"
        )

    result["status"] = "pass"
    result["message"] = "Prepared Spotube baseline with cleared plugin defaults"
except Exception as exc:
    result["status"] = "fail"
    result["message"] = str(exc)

print(json.dumps(result, ensure_ascii=False))
'''


class SpotubeInitializer(BaseInitializer):
    """Reset Spotube to a deterministic baseline on macOS."""

    DEFAULT_APP_NAME = "Spotube"
    DEFAULT_BUNDLE_ID = "oss.krtirtho.spotube"
    DEFAULT_WAIT_MS = 4000
    DONT_ALLOW_TEXTS = ("不允许", "Don't Allow")

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_python_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_python_script is required")

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        timeout = int(params.get("timeout", 180) or 180)

        script_params = {
            "app_name": app_name,
            "bundle_id": bundle_id,
            "done_key": str(params.get("done_key") or "doneGettingStarted").strip() or "doneGettingStarted",
            "state_root": str(params.get("state_root") or f"~/Library/Application Support/{bundle_id}"),
            "preferences_path": str(params.get("preferences_path") or f"~/Library/Preferences/{bundle_id}.plist"),
            "bootstrap_timeout": int(params.get("bootstrap_timeout", 120) or 120),
            "poll_interval_seconds": float(params.get("poll_interval_seconds", 1.0) or 1.0),
            "baseline_market": str(params.get("baseline_market") or "US").strip().upper() or "US",
            "baseline_endless_playback": bool(params.get("baseline_endless_playback", True)),
            "expected_plugin_names": [
                str(item).strip()
                for item in (
                    params.get("expected_plugin_names")
                    or ["Musicbrainz and Listenbrainz", "YouTube Audio"]
                )
                if str(item).strip()
            ],
            "quit_wait_seconds": float(params.get("quit_wait_seconds", 2.0) or 2.0),
            "allow_headless_fallback": bool(params.get("allow_headless_fallback", False)),
        }
        script = dedent(_BOOTSTRAP_SCRIPT).replace(
            "__PARAMS_JSON__",
            repr(json.dumps(script_params, ensure_ascii=False)),
        )

        try:
            result = controller.run_python_script(script, timeout=timeout)
        except Exception as exc:
            return InitResult(status=InitStatus.ERROR, message=f"Spotube bootstrap failed: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return InitResult(
                status=InitStatus.ERROR,
                message="Spotube initializer returned non-JSON output",
                metadata={"runtime_result": result},
            )

        if str(payload.get("status") or "").strip().lower() != "pass":
            return InitResult(
                status=InitStatus.ERROR,
                message=str(payload.get("message") or "Spotube bootstrap failed"),
                metadata=payload,
            )

        if bool(payload.get("launch_app_after_bootstrap", True)):
            try:
                if hasattr(controller, "launch_app"):
                    controller.launch_app(app_name)
                else:
                    controller.execute_action({"type": "launch_app", "app_name": app_name}, [])
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)
                self._dismiss_local_network_prompt(controller, app_name=app_name)
                if hasattr(controller, "run_bash_script"):
                    controller.run_bash_script(
                        self._build_activate_script(app_name=app_name),
                        timeout=20,
                    )
            except Exception as exc:
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"Spotube launch failed after bootstrap: {exc}",
                    metadata=payload,
                )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Spotube baseline",
            metadata={
                "app_name": app_name,
                "bundle_id": bundle_id,
                "wait_ms": wait_ms,
                "bootstrap": payload,
            },
        )

    def _build_activate_script(self, *, app_name: str) -> str:
        return dedent(
            f'''
            open -a {json.dumps(app_name)} >/dev/null 2>&1 || true
            osascript -e 'tell application "{app_name}" to activate' >/dev/null 2>&1 || true
            '''
        ).strip()

    def _dismiss_local_network_prompt(self, controller: Any, *, app_name: str) -> None:
        if not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            return

        for _ in range(3):
            try:
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            except Exception:
                return

            ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            target = None
            for node in ui_nodes:
                text = str(node.get("text") or "").strip()
                if text in self.DONT_ALLOW_TEXTS:
                    target = str(node.get("id") or "").strip() or {"text": text}
                    break

            if not target:
                return

            controller.execute_action({"type": "tap", "target": target}, ui_nodes)
            time.sleep(1.0)
            if hasattr(controller, "run_bash_script"):
                controller.run_bash_script(
                    self._build_activate_script(app_name=app_name),
                    timeout=20,
                )
