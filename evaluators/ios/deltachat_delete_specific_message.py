"""SQLite-backed evaluator for deleting one specific Delta Chat message."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from initializers.ios.greenmail_local_state import DELTACHAT_APP_GROUP_ID, _find_shared_app_group_root


class DeltaChatDeleteSpecificMessageEvaluator(BaseEvaluator):
    DEFAULT_BUNDLE_ID = "chat.delta"
    DEFAULT_TIMEOUT_SECONDS = 12.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        final_observation = context.get("final_observation")
        params = dict(context.get("params") or {})

        target_body = str(params.get("target_body") or "").strip()
        decoy_bodies = self._coerce_text_list(params.get("decoy_bodies"))
        contact_text = str(params.get("contact_text") or "").strip()
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        if not target_body:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params target_body is required",
            )
        if not decoy_bodies:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params decoy_bodies must be a non-empty list",
            )

        db_paths = self._resolve_db_paths(controller=controller, params=params)
        if db_paths:
            return self._evaluate_from_sqlite(
                db_paths=db_paths,
                target_body=target_body,
                decoy_bodies=decoy_bodies,
                contact_text=contact_text,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

        return self._evaluate_from_ui(
            controller=controller,
            final_observation=final_observation,
            params=params,
            target_body=target_body,
            decoy_bodies=decoy_bodies,
            contact_text=contact_text,
        )

    def _evaluate_from_sqlite(
        self,
        *,
        db_paths: Sequence[Path],
        target_body: str,
        decoy_bodies: list[str],
        contact_text: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> EvalResult:
        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_summary: dict[str, Any] = {"db_count": len(db_paths), "dbs": []}
        last_failures: list[str] = []

        while True:
            attempts += 1
            try:
                summary = self._collect_sqlite_summary(
                    db_paths=db_paths,
                    target_body=target_body,
                    decoy_bodies=decoy_bodies,
                    contact_text=contact_text,
                )
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query Delta Chat local state: {type(exc).__name__}: {exc}",
                    metadata={"db_paths": [str(path) for path in db_paths]},
                )

            last_summary = summary
            last_failures = list(summary.get("failures") or [])
            if not last_failures:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Target Delta Chat message is absent while decoys remain in local state",
                    metadata={
                        "attempts": attempts,
                        **summary,
                    },
                )

            if time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Delta Chat local state does not match the expected deletion outcome",
            metadata={
                "attempts": attempts,
                "failures": last_failures,
                **last_summary,
            },
        )

    @classmethod
    def _collect_sqlite_summary(
        cls,
        *,
        db_paths: Sequence[Path],
        target_body: str,
        decoy_bodies: list[str],
        contact_text: str,
    ) -> dict[str, Any]:
        db_summaries: list[dict[str, Any]] = []
        matched_db: dict[str, Any] | None = None

        for db_path in db_paths:
            db_summary = cls._inspect_single_db(
                db_path=db_path,
                target_body=target_body,
                decoy_bodies=decoy_bodies,
                contact_text=contact_text,
            )
            db_summaries.append(db_summary)
            if db_summary.get("matched_chat"):
                matched_db = db_summary

        failures: list[str] = []
        if matched_db is None:
            failures.append(f"Could not find Delta Chat conversation for '{contact_text}' in local state")
        else:
            visible_texts = list(matched_db.get("visible_texts") or [])
            normalized_visible = {cls._normalize_text(text) for text in visible_texts}
            if cls._normalize_text(target_body) in normalized_visible:
                failures.append(f"Target Delta Chat message '{target_body}' is still present in local state")
            missing_decoys = [
                body for body in decoy_bodies if cls._normalize_text(body) not in normalized_visible
            ]
            if missing_decoys:
                failures.append("One or more decoy Delta Chat messages are missing from local state")

        return {
            "db_count": len(db_paths),
            "matched_db_path": str(matched_db["db_path"]) if matched_db else None,
            "matched_chat_ids": list(matched_db.get("chat_ids") or []) if matched_db else [],
            "visible_texts": list(matched_db.get("visible_texts") or []) if matched_db else [],
            "dbs": db_summaries,
            "failures": failures,
        }

    @classmethod
    def _inspect_single_db(
        cls,
        *,
        db_path: Path,
        target_body: str,
        decoy_bodies: list[str],
        contact_text: str,
    ) -> dict[str, Any]:
        visible_rows: list[tuple[int, str, str]] = []
        normalized_contact = cls._normalize_text(contact_text)

        with cls._snapshot_db_path(db_path) as snapshot_path:
            connection = sqlite3.connect(str(snapshot_path))
            try:
                cursor = connection.cursor()
                rows = cursor.execute(
                    """
                    SELECT
                        m.id,
                        COALESCE(c.name, ''),
                        COALESCE(ct.addr, ''),
                        COALESCE(ct.name, ''),
                        COALESCE(m.txt, '')
                    FROM msgs m
                    LEFT JOIN chats c ON c.id = m.chat_id
                    LEFT JOIN contacts ct ON ct.id = m.from_id
                    WHERE m.hidden = 0
                      AND COALESCE(m.deleted, 0) = 0
                      AND TRIM(COALESCE(m.txt, '')) != ''
                    ORDER BY m.id
                    """
                ).fetchall()
            finally:
                connection.close()

        chat_ids: list[int] = []
        visible_texts: list[str] = []
        for message_id, chat_name, from_addr, from_name, body in rows:
            normalized_chat = cls._normalize_text(chat_name)
            normalized_addr = cls._normalize_text(from_addr)
            normalized_from_name = cls._normalize_text(from_name)
            normalized_body = cls._normalize_text(body)

            if normalized_contact and normalized_contact not in {
                normalized_chat,
                normalized_addr,
                normalized_from_name,
            }:
                continue

            if not normalized_body:
                continue

            visible_rows.append((int(message_id), chat_name, body))
            visible_texts.append(body)

        target_norm = cls._normalize_text(target_body)
        decoy_norms = {cls._normalize_text(body) for body in decoy_bodies}
        matched_chat = bool(visible_rows) or any(
            body_norm in {target_norm, *decoy_norms}
            for body_norm in (cls._normalize_text(row[2]) for row in visible_rows)
        )

        if visible_rows:
            # We do not expose internal chat ids in the join above, so infer them from target/decoy rows.
            with cls._snapshot_db_path(db_path) as snapshot_path:
                connection = sqlite3.connect(str(snapshot_path))
                try:
                    cursor = connection.cursor()
                    chat_ids = [
                        int(row[0])
                        for row in cursor.execute(
                            """
                            SELECT DISTINCT m.chat_id
                            FROM msgs m
                            LEFT JOIN chats c ON c.id = m.chat_id
                            LEFT JOIN contacts ct ON ct.id = m.from_id
                            WHERE m.hidden = 0
                              AND COALESCE(m.deleted, 0) = 0
                              AND TRIM(COALESCE(m.txt, '')) != ''
                              AND (
                                LOWER(COALESCE(c.name, '')) = ?
                                OR LOWER(COALESCE(ct.addr, '')) = ?
                                OR LOWER(COALESCE(ct.name, '')) = ?
                              )
                            ORDER BY m.chat_id
                            """,
                            (normalized_contact, normalized_contact, normalized_contact),
                        ).fetchall()
                    ]
                finally:
                    connection.close()

        return {
            "db_path": str(db_path),
            "matched_chat": matched_chat,
            "chat_ids": chat_ids,
            "visible_texts": visible_texts,
        }

    @classmethod
    def _resolve_db_paths(cls, *, controller: Any, params: Mapping[str, Any]) -> list[Path]:
        db_path_raw = str(params.get("db_path") or "").strip()
        if db_path_raw:
            path = Path(db_path_raw).expanduser().resolve()
            return [path] if path.exists() else []

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            return []

        try:
            shared_group_root = _find_shared_app_group_root(udid=udid, group_id=DELTACHAT_APP_GROUP_ID)
        except Exception:
            return []

        return sorted(
            path.expanduser().resolve()
            for path in (shared_group_root / "accounts").glob("*/dc.db")
            if path.exists()
        )

    @classmethod
    def _evaluate_from_ui(
        cls,
        *,
        controller: Any,
        final_observation: Any,
        params: Mapping[str, Any],
        target_body: str,
        decoy_bodies: list[str],
        contact_text: str,
    ) -> EvalResult:
        observation = final_observation
        if observation is None:
            if controller is None or not hasattr(controller, "observe"):
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message="final_observation is missing and controller.observe is unavailable",
                )
            observation = controller.observe(include_ui_tree=True)

        required_bundle_id = str(params.get("bundle_id") or cls.DEFAULT_BUNDLE_ID).strip()
        actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        if actual_bundle_id != required_bundle_id:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"Expected foreground bundle '{required_bundle_id}', "
                    f"got '{actual_bundle_id or 'unknown'}'"
                ),
                metadata={
                    "required_bundle_id": required_bundle_id,
                    "actual_bundle_id": actual_bundle_id,
                    "strategy": "ui_fallback",
                },
            )

        node_strings = cls._collect_node_strings(getattr(observation, "ui_nodes", []) or [])
        target_still_visible = cls._contains_text(node_strings, target_body)
        missing_decoys = [body for body in decoy_bodies if not cls._contains_text(node_strings, body)]
        contact_visible = not contact_text or cls._contains_text(node_strings, contact_text)

        if not contact_visible:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Expected to stay inside the chat for '{contact_text}'",
                metadata={
                    "contact_text": contact_text,
                    "observed_node_count": len(node_strings),
                    "strategy": "ui_fallback",
                },
            )

        if target_still_visible:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Target Delta Chat message '{target_body}' is still visible",
                metadata={
                    "target_body": target_body,
                    "decoy_bodies": decoy_bodies,
                    "contact_text": contact_text,
                    "strategy": "ui_fallback",
                },
            )

        if missing_decoys:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="One or more decoy Delta Chat messages are missing after deletion",
                metadata={
                    "target_body": target_body,
                    "decoy_bodies": decoy_bodies,
                    "missing_decoys": missing_decoys,
                    "contact_text": contact_text,
                    "strategy": "ui_fallback",
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Target Delta Chat message is gone while decoys remain visible",
            metadata={
                "target_body": target_body,
                "decoy_bodies": decoy_bodies,
                "contact_text": contact_text,
                "strategy": "ui_fallback",
            },
        )

    @staticmethod
    def _snapshot_db_path(db_path: Path):
        class _SnapshotContext:
            def __init__(self, source_path: Path) -> None:
                self.source_path = source_path
                self.temp_dir = tempfile.TemporaryDirectory(prefix="ios-deltachat-db-")
                self.snapshot_path = Path(self.temp_dir.name) / source_path.name

            def __enter__(self) -> Path:
                shutil.copy2(self.source_path, self.snapshot_path)
                for suffix in ("-wal", "-shm"):
                    source_sidecar = Path(f"{self.source_path}{suffix}")
                    if source_sidecar.exists():
                        shutil.copy2(source_sidecar, Path(f"{self.snapshot_path}{suffix}"))
                return self.snapshot_path

            def __exit__(self, exc_type, exc, tb) -> None:
                self.temp_dir.cleanup()

        return _SnapshotContext(db_path)

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text:
                values.append(text)
        return values

    @classmethod
    def _collect_node_strings(cls, ui_nodes: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        for node in ui_nodes:
            for key in ("text", "selector"):
                text = cls._normalize_text(str(node.get(key) or ""))
                if text:
                    values.append(text)
        return values

    @classmethod
    def _contains_text(cls, haystack: list[str], needle: str) -> bool:
        wanted = cls._normalize_text(needle)
        if not wanted:
            return False
        return any(wanted in value for value in haystack)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text).strip().casefold().split())
