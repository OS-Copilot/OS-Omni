"""Evaluate native Apple Maps tasks through UI text and read-only Maps SQLite state."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Iterable, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


DEFAULT_MAPS_DB_PATH = "~/Library/Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1"
TEXT_KEYS = {"text", "title", "description", "value", "label", "name"}


def normalize_text(value: Any) -> str:
    """Collapse whitespace and case for substring-style UI and SQLite checks."""

    return " ".join(str(value or "").split()).strip().lower()


class MapsStateEvaluator(BaseEvaluator):
    """Validate Apple Maps foreground state, visible text, and optional SQLite state."""

    DEFAULT_BUNDLE_ID = "com.apple.Maps"
    DEFAULT_MIN_NODE_COUNT = 10

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None:
            return EvalResult(status=EvalStatus.ERROR, message="controller is required")

        params = dict(context.get("params") or {})
        required_texts = self._string_list(params.get("required_texts"))
        forbidden_texts = self._string_list(params.get("forbidden_texts"))
        any_text_groups = [
            self._string_list(group)
            for group in list(params.get("any_text_groups") or [])
            if self._string_list(group)
        ]
        min_node_count = int(params.get("min_node_count", self.DEFAULT_MIN_NODE_COUNT) or 0)
        expected_bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip()

        metadata: dict[str, Any] = {
            "required_texts": required_texts,
            "forbidden_texts": forbidden_texts,
            "any_text_groups": any_text_groups,
        }

        try:
            ui_state = self._collect_ui_state(controller)
            metadata.update(ui_state)

            failures = self._validate_ui_state(
                ui_state,
                expected_bundle_id=expected_bundle_id,
                required_texts=required_texts,
                any_text_groups=any_text_groups,
                forbidden_texts=forbidden_texts,
                min_node_count=min_node_count,
            )

            sqlite_expectation = params.get("sqlite")
            if isinstance(sqlite_expectation, Mapping):
                sqlite_summary = self._evaluate_sqlite(controller, dict(sqlite_expectation))
                metadata["sqlite"] = sqlite_summary
                failures.extend(list(sqlite_summary.get("failures") or []))
                if sqlite_summary.get("status") == "error":
                    return EvalResult(
                        status=EvalStatus.ERROR,
                        message=str(sqlite_summary.get("message") or "Maps SQLite evaluation failed"),
                        metadata=metadata,
                    )

            if failures:
                metadata["failures"] = failures
                return EvalResult(status=EvalStatus.FAIL, message="Maps checks failed: " + "; ".join(failures), metadata=metadata)

            return EvalResult(status=EvalStatus.PASS, message="Maps state evaluation passed", metadata=metadata)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Maps evaluation failed: {exc}", metadata=metadata)

    @classmethod
    def _collect_ui_state(cls, controller: Any) -> dict[str, Any]:
        observe_error = ""
        observation = None
        if hasattr(controller, "observe"):
            try:
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            except Exception as exc:  # pragma: no cover - exercised through fallback behavior
                observe_error = str(exc)

        foreground_app = ""
        foreground_bundle_id = ""
        ui_nodes: list[Any] = []
        ui_texts: list[str] = []
        if observation is not None:
            foreground_app = str(getattr(observation, "foreground_app", "") or "")
            foreground_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "")
            ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            ui_texts = cls._extract_ui_texts(ui_nodes)

        fallback_texts: list[str] = []
        fallback_foreground: dict[str, str] = {}
        if (not ui_texts or observe_error) and hasattr(controller, "run_bash_script"):
            fallback = cls._system_events_dump(controller)
            fallback_texts = cls._string_list(fallback.get("texts"))
            fallback_foreground = dict(fallback.get("foreground") or {})
            foreground_app = foreground_app or str(fallback_foreground.get("app") or "")
            foreground_bundle_id = foreground_bundle_id or str(fallback_foreground.get("bundle_id") or "")

        all_texts = cls._dedupe_texts([*ui_texts, *fallback_texts])
        combined_text = "\n".join(all_texts)

        return {
            "foreground_app": foreground_app,
            "foreground_bundle_id": foreground_bundle_id,
            "ui_node_count": len(ui_nodes),
            "ui_text_count": len(all_texts),
            "ui_text_sample": all_texts[:80],
            "observe_error": observe_error,
            "fallback_foreground": fallback_foreground,
            "combined_text": combined_text,
        }

    @classmethod
    def _validate_ui_state(
        cls,
        ui_state: Mapping[str, Any],
        *,
        expected_bundle_id: str,
        required_texts: list[str],
        any_text_groups: list[list[str]],
        forbidden_texts: list[str],
        min_node_count: int,
    ) -> list[str]:
        failures: list[str] = []
        foreground_bundle_id = str(ui_state.get("foreground_bundle_id") or "")
        foreground_app = str(ui_state.get("foreground_app") or "")
        ui_node_count = int(ui_state.get("ui_node_count") or 0)
        ui_text_count = int(ui_state.get("ui_text_count") or 0)
        haystack = normalize_text(ui_state.get("combined_text") or "")

        if expected_bundle_id and foreground_bundle_id != expected_bundle_id:
            failures.append(
                f"expected foreground bundle {expected_bundle_id!r}, got {foreground_bundle_id!r} ({foreground_app!r})"
            )

        if min_node_count > 0 and ui_node_count < min_node_count and ui_text_count < min_node_count:
            failures.append(
                f"expected at least {min_node_count} UI nodes or fallback text entries, "
                f"got {ui_node_count} nodes and {ui_text_count} text entries"
            )

        missing = [text for text in required_texts if normalize_text(text) not in haystack]
        if missing:
            failures.append(f"missing required text: {missing}")

        missing_groups = [
            group for group in any_text_groups
            if not any(normalize_text(text) in haystack for text in group)
        ]
        if missing_groups:
            failures.append(f"missing one item from each text group: {missing_groups}")

        present_forbidden = [text for text in forbidden_texts if normalize_text(text) in haystack]
        if present_forbidden:
            failures.append(f"forbidden text present: {present_forbidden}")

        return failures

    @classmethod
    def _extract_ui_texts(cls, value: Any) -> list[str]:
        texts: list[str] = []

        def visit(item: Any) -> None:
            if isinstance(item, Mapping):
                for key, child in item.items():
                    if str(key) in TEXT_KEYS and isinstance(child, (str, int, float)):
                        text = str(child).strip()
                        if text:
                            texts.append(text)
                    elif isinstance(child, (Mapping, list, tuple)):
                        visit(child)
                return
            if isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)

        visit(value)
        return cls._dedupe_texts(texts)

    @classmethod
    def _system_events_dump(cls, controller: Any) -> dict[str, Any]:
        script = dedent(
            """
            osascript <<'APPLESCRIPT'
            on joinLines(theItems)
              set AppleScript's text item delimiters to linefeed
              set outText to theItems as text
              set AppleScript's text item delimiters to ""
              return outText
            end joinLines

            tell application "System Events"
              set frontProc to first application process whose frontmost is true
              set frontName to name of frontProc
              set frontBundle to ""
              try
                set frontBundle to bundle identifier of frontProc
              end try
              set collected to {}
              try
                tell process "Maps"
                  repeat with w in windows
                    try
                      set end of collected to name of w
                    end try
                    try
                      set end of collected to value of w as text
                    end try
                    try
                      set end of collected to description of w
                    end try
                    try
                      repeat with e in entire contents of w
                        try
                          set t to name of e
                          if t is not "" then set end of collected to t
                        end try
                        try
                          set v to value of e as text
                          if v is not "" then set end of collected to v
                        end try
                        try
                          set d to description of e
                          if d is not "" then set end of collected to d
                        end try
                      end repeat
                    end try
                  end repeat
                end tell
              end try
            end tell

            return frontName & linefeed & frontBundle & linefeed & "----MAPS_TEXT----" & linefeed & joinLines(collected)
            APPLESCRIPT
            """
        ).strip()
        result = controller.run_bash_script(script, timeout=30)
        returncode = int(result.get("returncode", 0))
        if returncode != 0:
            return {"texts": [], "foreground": {}, "error": str(result.get("output") or result.get("message") or "")}

        output = str(result.get("stdout") or result.get("output") or result.get("message") or "")
        before, sep, after = output.partition("----MAPS_TEXT----")
        header = before.splitlines()
        foreground = {
            "app": header[0].strip() if len(header) >= 1 else "",
            "bundle_id": header[1].strip() if len(header) >= 2 else "",
        }
        texts = [line.strip() for line in after.splitlines() if line.strip()] if sep else []
        return {"texts": cls._dedupe_texts(texts), "foreground": foreground}

    def _evaluate_sqlite(self, controller: Any, expectation: Mapping[str, Any]) -> dict[str, Any]:
        if not hasattr(controller, "run_python_script"):
            return {"status": "error", "message": "controller.run_python_script is required for SQLite checks"}

        payload = {
            "db_path": str(expectation.get("db_path") or DEFAULT_MAPS_DB_PATH),
            "collections": self._string_list(expectation.get("collections")),
            "history_queries": self._string_list(expectation.get("history_queries")),
            "collection_item_names": self._string_list(expectation.get("collection_item_names")),
        }
        script = _SQLITE_SCAN_SCRIPT.replace("__PARAMS_JSON__", json.dumps(payload, ensure_ascii=False))
        result = controller.run_python_script(script, timeout=30)
        returncode = int(result.get("returncode", 0))
        output = str(result.get("stdout") or result.get("output") or "").strip()
        if returncode != 0:
            return {
                "status": "error",
                "message": output or f"SQLite scan exited with code {returncode}",
                "failures": [],
            }
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            return {"status": "error", "message": f"SQLite scan returned invalid JSON: {exc}: {output}", "failures": []}
        return parsed if isinstance(parsed, dict) else {"status": "error", "message": "SQLite scan returned non-object JSON"}

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _dedupe_texts(values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            key = normalize_text(text)
            if text and key not in seen:
                seen.add(key)
                result.append(text)
        return result


_SQLITE_SCAN_SCRIPT = r'''
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

params = json.loads(r"""__PARAMS_JSON__""")
db_path = Path(os.path.expanduser(str(params.get("db_path") or "")))
expected_collections = [str(x).strip() for x in params.get("collections") or [] if str(x).strip()]
expected_history = [str(x).strip() for x in params.get("history_queries") or [] if str(x).strip()]
expected_items = [str(x).strip() for x in params.get("collection_item_names") or [] if str(x).strip()]

result = {
    "status": "fail",
    "message": "Maps SQLite checks failed",
    "db_path": str(db_path),
    "collections": [],
    "history_queries": [],
    "collection_item_texts": [],
    "failures": [],
}

def normalize(value):
    return " ".join(str(value or "").split()).strip().lower()

def contains(actual_values, expected):
    needle = normalize(expected)
    return any(needle in normalize(value) for value in actual_values)

if not db_path.exists():
    result["status"] = "error"
    result["message"] = f"Maps SQLite DB missing: {db_path}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

workdir = Path(tempfile.mkdtemp(prefix="maps-eval-"))
local_db = workdir / "MapsSync_0.0.1"
try:
    shutil.copy2(db_path, local_db)
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, workdir / (local_db.name + suffix))

    conn = sqlite3.connect(local_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def table_exists(name):
        return cur.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
            (name,),
        ).fetchone() is not None

    def table_columns(name):
        return [dict(row) for row in cur.execute(f"PRAGMA table_info({name})").fetchall()]

    def safe_text_rows(table, column):
        try:
            return [
                str(row[0]).strip()
                for row in cur.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL').fetchall()
                if str(row[0]).strip()
            ]
        except sqlite3.Error:
            return []

    if table_exists("ZCOLLECTION"):
        collection_columns = {str(col.get("name")) for col in table_columns("ZCOLLECTION")}
        if "ZTITLE" in collection_columns:
            result["collections"] = safe_text_rows("ZCOLLECTION", "ZTITLE")

    if table_exists("ZHISTORYITEM"):
        history_columns = {str(col.get("name")) for col in table_columns("ZHISTORYITEM")}
        for candidate in ("ZQUERY", "ZSEARCHQUERY", "ZTITLE", "ZDISPLAYNAME"):
            if candidate in history_columns:
                result["history_queries"].extend(safe_text_rows("ZHISTORYITEM", candidate))
        seen = set()
        result["history_queries"] = [
            value for value in result["history_queries"]
            if not (normalize(value) in seen or seen.add(normalize(value)))
        ]

    # Collection item schemas have varied across macOS releases. Gather likely text
    # columns read-only instead of assuming a single CoreData relationship shape.
    tables = [
        str(row[0])
        for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if str(row[0]).startswith("Z")
    ]
    item_texts = []
    for table in tables:
        if not any(token in table for token in ("COLLECTION", "PLACE", "MAPITEM", "MUID")):
            continue
        for column in table_columns(table):
            column_name = str(column.get("name") or "")
            column_type = str(column.get("type") or "").upper()
            if column_name in {"ZTITLE", "ZNAME", "ZDISPLAYNAME", "ZQUERY", "ZADDRESS", "ZSHORTADDRESS"} or "CHAR" in column_type or "TEXT" in column_type:
                item_texts.extend(safe_text_rows(table, column_name))
    seen = set()
    result["collection_item_texts"] = [
        value for value in item_texts
        if not (normalize(value) in seen or seen.add(normalize(value)))
    ][:200]

    failures = []
    for expected in expected_collections:
        if not contains(result["collections"], expected):
            failures.append(f"missing collection title: {expected}")
    for expected in expected_history:
        if not contains(result["history_queries"], expected):
            failures.append(f"missing history query: {expected}")
    for expected in expected_items:
        if not contains(result["collection_item_texts"], expected):
            failures.append(f"missing collection item text: {expected}")

    result["failures"] = failures
    result["status"] = "pass" if not failures else "fail"
    result["message"] = "Maps SQLite checks passed" if not failures else "Maps SQLite checks failed"
except Exception as exc:
    result["status"] = "error"
    result["message"] = f"Maps SQLite scan failed: {exc}"
finally:
    try:
        shutil.rmtree(workdir)
    except Exception:
        pass

print(json.dumps(result, ensure_ascii=False))
'''
