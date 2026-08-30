"""Evaluate Spotube tasks on macOS via local SQLite state."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_SCAN_SCRIPT = r'''
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

params = json.loads(__PARAMS_JSON__)
bundle_id = str(params.get("bundle_id") or "oss.krtirtho.spotube").strip() or "oss.krtirtho.spotube"
state_root = Path(
    os.path.expanduser(
        str(params.get("state_root") or f"~/Library/Application Support/{bundle_id}")
    )
)
db_path = Path(os.path.expanduser(str(params.get("db_path") or state_root / "db.sqlite")))
mode = str(params.get("mode") or "state_check").strip() or "state_check"
expected_metadata_plugin_name = str(params.get("expected_metadata_plugin_name") or "").strip()
expected_audio_source_plugin_name = str(params.get("expected_audio_source_plugin_name") or "").strip()
expected_preferences = dict(params.get("expected_preferences") or {})
expected_locale_contains = str(params.get("expected_locale_contains") or "").strip()

explicit_expected_market = str(params.get("expected_market") or "").strip().upper()
explicit_expected_endless_playback = params.get("expected_endless_playback")
if explicit_expected_market and "market" not in expected_preferences:
    expected_preferences["market"] = explicit_expected_market
if explicit_expected_endless_playback not in (None, "") and "endless_playback" not in expected_preferences:
    expected_preferences["endless_playback"] = explicit_expected_endless_playback

result = {
    "status": "fail",
    "message": "Spotube checks failed",
    "mode": mode,
    "state_root": str(state_root),
    "db_path": str(db_path),
}


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"cannot normalize bool from {value!r}")


if mode != "state_check":
    result["status"] = "error"
    result["message"] = f"unsupported Spotube evaluation mode: {mode}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

if not any(
    value not in (None, "")
    for value in (
        expected_metadata_plugin_name,
        expected_audio_source_plugin_name,
        expected_preferences,
        expected_locale_contains,
    )
):
    result["status"] = "error"
    result["message"] = "Spotube evaluator requires at least one expected value"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

if not db_path.exists():
    result["message"] = f"Spotube db.sqlite missing: {db_path}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

workdir = Path(tempfile.mkdtemp(prefix="spotube-eval-"))
local_db = workdir / "db.sqlite"
shutil.copy2(db_path, local_db)
for suffix in ("-wal", "-shm"):
    sidecar = db_path.with_name(db_path.name + suffix)
    if sidecar.exists():
        shutil.copy2(sidecar, workdir / ("db.sqlite" + suffix))

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
    result["tables"] = sorted(tables)
    if "plugins_table" not in tables:
        result["message"] = "Spotube plugins_table is missing"
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0)
    if "preferences_table" not in tables:
        result["message"] = "Spotube preferences_table is missing"
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0)

    plugins = [
        dict(row)
        for row in cur.execute(
            "SELECT id, name, author, selected_for_metadata, selected_for_audio_source FROM plugins_table ORDER BY id"
        ).fetchall()
    ]
    preferences = cur.execute("SELECT * FROM preferences_table ORDER BY id LIMIT 1").fetchone()
    preferences_dict = dict(preferences) if preferences else None
    result["plugins"] = plugins
    result["preferences"] = preferences_dict

    metadata_selected = [row for row in plugins if normalize_bool(row.get("selected_for_metadata"))]
    audio_selected = [row for row in plugins if normalize_bool(row.get("selected_for_audio_source"))]
    result["selected_metadata_plugins"] = metadata_selected
    result["selected_audio_source_plugins"] = audio_selected

    failures = []
    if expected_metadata_plugin_name:
        if len(metadata_selected) != 1:
            failures.append(
                f"expected exactly one metadata plugin selected, found {len(metadata_selected)}"
            )
        elif str(metadata_selected[0].get("name") or "").strip() != expected_metadata_plugin_name:
            failures.append(
                "metadata plugin mismatch: "
                f"expected {expected_metadata_plugin_name}, observed {metadata_selected[0].get('name')}"
            )

    if expected_audio_source_plugin_name:
        if len(audio_selected) != 1:
            failures.append(
                f"expected exactly one audio-source plugin selected, found {len(audio_selected)}"
            )
        elif str(audio_selected[0].get("name") or "").strip() != expected_audio_source_plugin_name:
            failures.append(
                "audio-source plugin mismatch: "
                f"expected {expected_audio_source_plugin_name}, observed {audio_selected[0].get('name')}"
            )

    for key, expected_value in expected_preferences.items():
        observed_value = (preferences_dict or {}).get(key)
        if isinstance(expected_value, bool):
            observed_bool = normalize_bool(observed_value)
            if observed_bool != expected_value:
                failures.append(
                    f"{key} mismatch: expected {expected_value}, observed {observed_bool}"
                )
            continue
        if key == "market":
            observed_market = str(observed_value or "").strip().upper()
            expected_market = str(expected_value or "").strip().upper()
            if observed_market != expected_market:
                failures.append(
                    f"market mismatch: expected {expected_market}, observed {observed_market or '<missing>'}"
                )
            continue
        if observed_value != expected_value:
            failures.append(
                f"{key} mismatch: expected {expected_value!r}, observed {observed_value!r}"
            )

    if expected_locale_contains:
        observed_locale = str((preferences_dict or {}).get("locale") or "")
        if expected_locale_contains not in observed_locale:
            failures.append(
                f"locale mismatch: expected substring {expected_locale_contains!r}, observed {observed_locale!r}"
            )

    if failures:
        result["status"] = "fail"
        result["message"] = "; ".join(failures)
    else:
        result["status"] = "pass"
        result["message"] = "Spotube state matches expected values"
finally:
    try:
        conn.close()
    except Exception:
        pass
    shutil.rmtree(workdir, ignore_errors=True)

print(json.dumps(result, ensure_ascii=False))
'''


class SpotubeEvaluator(BaseEvaluator):
    """Guest-side evaluator for Spotube tasks on macOS."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        script = dedent(_SCAN_SCRIPT).replace(
            "__PARAMS_JSON__",
            repr(json.dumps(params, ensure_ascii=False)),
        )
        try:
            result = controller.run_python_script(script, timeout=int(params.get("timeout", 60) or 60))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Spotube evaluation failed: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Spotube evaluator returned non-JSON output",
                metadata={"runtime_result": result},
            )

        status_name = str(payload.get("status") or "").strip().lower()
        eval_status = (
            EvalStatus.PASS
            if status_name == "pass"
            else EvalStatus.FAIL
            if status_name == "fail"
            else EvalStatus.ERROR
        )
        return EvalResult(
            status=eval_status,
            message=str(payload.get("message") or "Spotube evaluation completed"),
            metadata=payload,
        )
