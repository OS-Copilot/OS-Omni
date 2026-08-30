"""Evaluate native Apple Photos tasks through UI text and Photos.sqlite state."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Iterable, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


DEFAULT_PHOTOS_DB_PATH = "~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite"
TEXT_KEYS = {"text", "title", "description", "value", "label", "name"}


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()


class PhotosStateEvaluator(BaseEvaluator):
    """Validate Photos foreground state, visible text, assets, favorites, and albums."""

    DEFAULT_BUNDLE_ID = "com.apple.Photos"
    DEFAULT_MIN_NODE_COUNT = 10

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None:
            return EvalResult(status=EvalStatus.ERROR, message="controller is required")

        params = dict(context.get("params") or {})
        required_texts = self._string_list(params.get("required_texts"))
        any_text_groups = [
            self._string_list(group)
            for group in list(params.get("any_text_groups") or [])
            if self._string_list(group)
        ]
        forbidden_texts = self._string_list(params.get("forbidden_texts"))
        min_node_count = int(params.get("min_node_count", self.DEFAULT_MIN_NODE_COUNT) or 0)
        expected_bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip()
        require_foreground = bool(params.get("require_foreground", True))

        metadata: dict[str, Any] = {
            "required_texts": required_texts,
            "forbidden_texts": forbidden_texts,
            "any_text_groups": any_text_groups,
        }

        try:
            failures: list[str] = []
            ui_state = self._collect_ui_state(controller)
            metadata.update(ui_state)
            failures.extend(
                self._validate_ui_state(
                    ui_state,
                    expected_bundle_id=expected_bundle_id,
                    require_foreground=require_foreground,
                    required_texts=required_texts,
                    any_text_groups=any_text_groups,
                    forbidden_texts=forbidden_texts,
                    min_node_count=min_node_count,
                )
            )

            sqlite_summary = self._evaluate_sqlite(controller, params)
            metadata["sqlite"] = sqlite_summary
            failures.extend(list(sqlite_summary.get("failures") or []))
            if sqlite_summary.get("status") == "error":
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=str(sqlite_summary.get("message") or "Photos SQLite evaluation failed"),
                    metadata=metadata,
                )

            if failures:
                metadata["failures"] = failures
                return EvalResult(status=EvalStatus.FAIL, message="Photos checks failed: " + "; ".join(failures), metadata=metadata)

            return EvalResult(status=EvalStatus.PASS, message="Photos state evaluation passed", metadata=metadata)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Photos evaluation failed: {exc}", metadata=metadata)

    @classmethod
    def _collect_ui_state(cls, controller: Any) -> dict[str, Any]:
        observe_error = ""
        observation = None
        if hasattr(controller, "observe"):
            try:
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            except Exception as exc:
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
        return {
            "foreground_app": foreground_app,
            "foreground_bundle_id": foreground_bundle_id,
            "ui_node_count": len(ui_nodes),
            "ui_text_count": len(all_texts),
            "ui_text_sample": all_texts[:80],
            "observe_error": observe_error,
            "fallback_foreground": fallback_foreground,
            "combined_text": "\n".join(all_texts),
        }

    @classmethod
    def _validate_ui_state(
        cls,
        ui_state: Mapping[str, Any],
        *,
        expected_bundle_id: str,
        require_foreground: bool,
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

        if require_foreground and expected_bundle_id and foreground_bundle_id != expected_bundle_id:
            failures.append(f"expected foreground bundle {expected_bundle_id!r}, got {foreground_bundle_id!r} ({foreground_app!r})")
        if min_node_count > 0 and ui_node_count < min_node_count and ui_text_count < min_node_count:
            failures.append(f"expected at least {min_node_count} UI nodes or text entries, got {ui_node_count} nodes and {ui_text_count} text entries")

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
                tell process "Photos"
                  repeat with w in windows
                    try
                      set end of collected to name of w
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

            return frontName & linefeed & frontBundle & linefeed & "----PHOTOS_TEXT----" & linefeed & joinLines(collected)
            APPLESCRIPT
            """
        ).strip()
        result = controller.run_bash_script(script, timeout=30)
        returncode = int(result.get("returncode", 0))
        if returncode != 0:
            return {"texts": [], "foreground": {}, "error": str(result.get("output") or result.get("message") or "")}

        output = str(result.get("stdout") or result.get("output") or result.get("message") or "")
        before, sep, after = output.partition("----PHOTOS_TEXT----")
        header = before.splitlines()
        return {
            "texts": [line.strip() for line in after.splitlines() if line.strip()] if sep else [],
            "foreground": {
                "app": header[0].strip() if len(header) >= 1 else "",
                "bundle_id": header[1].strip() if len(header) >= 2 else "",
            },
        }

    def _evaluate_sqlite(self, controller: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        if not hasattr(controller, "run_python_script"):
            return {"status": "error", "message": "controller.run_python_script is required for SQLite checks"}

        payload = {
            "db_path": str(params.get("db_path") or DEFAULT_PHOTOS_DB_PATH),
            "expected_assets": self._string_list(params.get("expected_assets")),
            "forbidden_assets": self._string_list(params.get("forbidden_assets")),
            "exact_asset_set": bool(params.get("exact_asset_set", False)),
            "favorite_assets": self._string_list(params.get("favorite_assets")),
            "not_favorite_assets": self._string_list(params.get("not_favorite_assets")),
            "albums": [dict(item) for item in params.get("albums") or [] if isinstance(item, Mapping)],
            "forbidden_albums": self._string_list(params.get("forbidden_albums")),
        }
        script = _SQLITE_SCAN_SCRIPT.replace("__PARAMS_JSON__", json.dumps(payload, ensure_ascii=False))
        result = controller.run_python_script(script, timeout=30)
        returncode = int(result.get("returncode", 0))
        output = str(result.get("stdout") or result.get("output") or "").strip()
        if returncode != 0:
            return {"status": "error", "message": output or f"SQLite scan exited with code {returncode}", "failures": []}
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

result = {
    "status": "fail",
    "message": "Photos SQLite checks failed",
    "db_path": str(db_path),
    "assets": [],
    "albums": [],
    "failures": [],
}

def normalize(value):
    return " ".join(str(value or "").split()).strip().lower()

def asset_key(row):
    return normalize(row.get("original_filename") or row.get("filename") or "")

def find_asset(rows, expected):
    needle = normalize(expected)
    for row in rows:
        if needle in asset_key(row):
            return row
    return None

if not db_path.exists():
    result["status"] = "error"
    result["message"] = f"Photos SQLite DB missing: {db_path}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

workdir = Path(tempfile.mkdtemp(prefix="photos-eval-"))
local_db = workdir / "Photos.sqlite"
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

    if not table_exists("ZASSET"):
        result["status"] = "error"
        result["message"] = "Photos ZASSET table missing"
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0)

    assets = [
        {
            "pk": int(row["Z_PK"]),
            "filename": str(row["ZFILENAME"] or ""),
            "directory": str(row["ZDIRECTORY"] or ""),
            "favorite": int(row["ZFAVORITE"] or 0),
            "original_filename": str(row["ZORIGINALFILENAME"] or ""),
            "title": str(row["ZTITLE"] or ""),
        }
        for row in cur.execute(
            """
            SELECT s.Z_PK, s.ZFILENAME, s.ZDIRECTORY, s.ZFAVORITE, aa.ZORIGINALFILENAME, aa.ZTITLE
            FROM ZASSET s
            LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = s.Z_PK
            ORDER BY s.Z_PK
            """
        ).fetchall()
    ]
    result["assets"] = assets

    albums = []
    if table_exists("ZGENERICALBUM"):
        for album in cur.execute(
            "SELECT Z_PK, ZTITLE, ZCACHEDCOUNT, ZKIND FROM ZGENERICALBUM WHERE ZTITLE IS NOT NULL ORDER BY Z_PK"
        ).fetchall():
            members = []
            if table_exists("Z_30ASSETS"):
                members = [
                    {
                        "pk": int(row["Z_PK"]),
                        "filename": str(row["ZFILENAME"] or ""),
                        "original_filename": str(row["ZORIGINALFILENAME"] or ""),
                        "favorite": int(row["ZFAVORITE"] or 0),
                    }
                    for row in cur.execute(
                        """
                        SELECT s.Z_PK, s.ZFILENAME, s.ZFAVORITE, aa.ZORIGINALFILENAME
                        FROM Z_30ASSETS x
                        JOIN ZASSET s ON s.Z_PK = x.Z_3ASSETS
                        LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = s.Z_PK
                        WHERE x.Z_30ALBUMS = ?
                        ORDER BY s.Z_PK
                        """,
                        (album["Z_PK"],),
                    ).fetchall()
                ]
            albums.append(
                {
                    "pk": int(album["Z_PK"]),
                    "title": str(album["ZTITLE"] or ""),
                    "cached_count": int(album["ZCACHEDCOUNT"] or 0),
                    "kind": int(album["ZKIND"] or 0),
                    "members": members,
                }
            )
    result["albums"] = albums

    failures = []
    expected_assets = [str(x).strip() for x in params.get("expected_assets") or [] if str(x).strip()]
    forbidden_assets = [str(x).strip() for x in params.get("forbidden_assets") or [] if str(x).strip()]
    favorite_assets = [str(x).strip() for x in params.get("favorite_assets") or [] if str(x).strip()]
    not_favorite_assets = [str(x).strip() for x in params.get("not_favorite_assets") or [] if str(x).strip()]

    for expected in expected_assets:
        if find_asset(assets, expected) is None:
            failures.append(f"missing imported asset: {expected}")
    for forbidden in forbidden_assets:
        if find_asset(assets, forbidden) is not None:
            failures.append(f"forbidden asset was imported: {forbidden}")
    if params.get("exact_asset_set"):
        expected_keys = {normalize(name) for name in expected_assets}
        actual_keys = {asset_key(row) for row in assets}
        unexpected = sorted(actual_keys - expected_keys)
        if unexpected:
            failures.append(f"unexpected imported assets: {unexpected}")

    for expected in favorite_assets:
        row = find_asset(assets, expected)
        if row is None:
            failures.append(f"favorite asset missing: {expected}")
        elif int(row.get("favorite") or 0) != 1:
            failures.append(f"asset is not favorite: {expected}")
    for expected in not_favorite_assets:
        row = find_asset(assets, expected)
        if row is not None and int(row.get("favorite") or 0) != 0:
            failures.append(f"asset should not be favorite: {expected}")

    forbidden_albums = [normalize(x) for x in params.get("forbidden_albums") or [] if str(x).strip()]
    for album in albums:
        if normalize(album["title"]) in forbidden_albums:
            failures.append(f"forbidden album present: {album['title']}")

    for spec in params.get("albums") or []:
        title = str(spec.get("title") or "").strip()
        if not title:
            continue
        matched = next((album for album in albums if normalize(album["title"]) == normalize(title)), None)
        if matched is None:
            failures.append(f"missing album: {title}")
            continue
        members = list(matched.get("members") or [])
        expected_members = [str(x).strip() for x in spec.get("expected_assets") or [] if str(x).strip()]
        forbidden_members = [str(x).strip() for x in spec.get("forbidden_assets") or [] if str(x).strip()]
        for expected in expected_members:
            if find_asset(members, expected) is None:
                failures.append(f"album {title!r} missing asset: {expected}")
        for forbidden in forbidden_members:
            if find_asset(members, forbidden) is not None:
                failures.append(f"album {title!r} contains forbidden asset: {forbidden}")
        if spec.get("exact_assets"):
            expected_keys = {normalize(name) for name in expected_members}
            actual_keys = {asset_key(row) for row in members}
            unexpected = sorted(actual_keys - expected_keys)
            missing = sorted(expected_keys - actual_keys)
            if unexpected or missing:
                failures.append(f"album {title!r} asset set mismatch: missing={missing}, unexpected={unexpected}")
        min_count = spec.get("min_count")
        if min_count is not None and int(matched.get("cached_count") or 0) < int(min_count):
            failures.append(f"album {title!r} cached count below {min_count}: {matched.get('cached_count')}")

    result["failures"] = failures
    result["status"] = "pass" if not failures else "fail"
    result["message"] = "Photos SQLite checks passed" if not failures else "Photos SQLite checks failed"
except Exception as exc:
    result["status"] = "error"
    result["message"] = f"Photos SQLite scan failed: {exc}"
finally:
    try:
        shutil.rmtree(workdir)
    except Exception:
        pass

print(json.dumps(result, ensure_ascii=False))
'''
