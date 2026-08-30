"""Evaluator for the Android Oinkoin create-expense task."""

from __future__ import annotations

import sqlite3
import tempfile
import os
import time
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class OinkoinCreateExpenseEvaluator(BaseEvaluator):
    """Validate that Oinkoin persisted the expected expense record."""

    DEFAULT_APP_PACKAGE = "com.github.emavgl.piggybankpro"
    DEFAULT_DATABASE_PATH = "/data/user/0/com.github.emavgl.piggybankpro/databases/movements.db"
    DEFAULT_TIMEOUT_SECONDS = 10.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0
    DEFAULT_VALUE_TOLERANCE = 1e-3
    DEFAULT_CATEGORY_TYPE = 0

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Oinkoin evaluation",
            )

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        database_path = str(
            params.get("database_path") or self._default_database_path(app_package)
        ).strip()
        title = str(params.get("title") or "").strip()
        note = str(params.get("note") or "").strip()
        category_name = str(params.get("category_name") or "").strip()
        amount = float(params.get("amount") or 0.0)
        is_expense = bool(params.get("is_expense", True))
        category_type = int(params.get("category_type", self.DEFAULT_CATEGORY_TYPE))
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )
        value_tolerance = float(params.get("value_tolerance", self.DEFAULT_VALUE_TOLERANCE) or 0.0)

        if not title or not note or not category_name or amount <= 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params title, note, category_name, and positive amount are required",
            )

        expected_value = -abs(amount) if is_expense else abs(amount)
        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_seen_rows: list[dict[str, Any]] = []

        try:
            package_path = str(controller.execute_adb(["shell", "pm", "path", app_package]) or "").strip()
            if "package:" not in package_path:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Oinkoin package not installed: {app_package}",
                    metadata={"app_package": app_package},
                )

            self._ensure_adb_root(controller)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to prepare Oinkoin DB inspection: {type(exc).__name__}: {exc}",
                metadata={"app_package": app_package, "database_path": database_path},
            )

        while True:
            attempts += 1
            try:
                controller.execute_adb(["shell", "am", "force-stop", app_package])
                time.sleep(0.5)
                last_seen_rows = self._pull_and_query_rows(
                    controller=controller,
                    database_path=database_path,
                )
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to inspect Oinkoin database: {type(exc).__name__}: {exc}",
                    metadata={
                        "app_package": app_package,
                        "database_path": database_path,
                        "attempts": attempts,
                    },
                )

            match = self._find_matching_row(
                rows=last_seen_rows,
                title=title,
                note=note,
                category_name=category_name,
                category_type=category_type,
                expected_value=expected_value,
                value_tolerance=value_tolerance,
            )
            if match is not None:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Expected Oinkoin expense record was persisted",
                    metadata={
                        "attempts": attempts,
                        "database_path": database_path,
                        "matched_row": match,
                    },
                )

            if time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Expected Oinkoin expense record was not found in the local database",
            metadata={
                "attempts": attempts,
                "database_path": database_path,
                "expected": {
                    "title": title,
                    "note": note,
                    "category_name": category_name,
                    "expected_value": expected_value,
                    "category_type": category_type,
                },
                "rows_seen": last_seen_rows[:5],
            },
        )

    @staticmethod
    def _ensure_adb_root(controller: Any) -> None:
        root_output = str(controller.execute_adb(["root"]) or "").strip().lower()
        if "cannot run as root" in root_output or "production builds" in root_output:
            raise RuntimeError(root_output)
        if "restarting adbd as root" in root_output:
            controller.execute_adb(["wait-for-device"])
            time.sleep(1.0)

    @staticmethod
    def _default_database_path(app_package: str) -> str:
        package = app_package.strip() or OinkoinCreateExpenseEvaluator.DEFAULT_APP_PACKAGE
        return f"/data/user/0/{package}/databases/movements.db"

    @staticmethod
    def _pull_and_query_rows(
        *,
        controller: Any,
        database_path: str,
    ) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="oinkoin-db-") as tmpdir:
            local_dir = Path(tmpdir)
            controller.execute_adb(["pull", database_path, str(local_dir)])
            local_db = OinkoinCreateExpenseEvaluator._find_pulled_database(local_dir)
            if local_db is None:
                raise RuntimeError(f"Database pull failed: {database_path}")

            connection = sqlite3.connect(local_db)
            try:
                cursor = connection.cursor()
                rows = cursor.execute(
                    """
                    SELECT id, datetime, timezone, value, title, description, category_name, category_type
                    FROM records
                    ORDER BY id DESC
                    """
                ).fetchall()
            finally:
                connection.close()

        return [
            {
                "id": row[0],
                "datetime": row[1],
                "timezone": row[2],
                "value": row[3],
                "title": row[4],
                "description": row[5],
                "category_name": row[6],
                "category_type": row[7],
            }
            for row in rows
        ]

    @staticmethod
    def _find_pulled_database(local_dir: Path) -> Path | None:
        direct_path = local_dir / "movements.db"
        if direct_path.is_file():
            return direct_path

        for root, _dirs, files in os.walk(local_dir):
            if "movements.db" in files:
                candidate = Path(root) / "movements.db"
                if candidate.is_file():
                    return candidate
        return None

    @staticmethod
    def _find_matching_row(
        *,
        rows: list[dict[str, Any]],
        title: str,
        note: str,
        category_name: str,
        category_type: int,
        expected_value: float,
        value_tolerance: float,
    ) -> dict[str, Any] | None:
        for row in rows:
            if str(row.get("title") or "").strip() != title:
                continue
            if str(row.get("description") or "").strip() != note:
                continue
            if str(row.get("category_name") or "").strip() != category_name:
                continue
            if int(row.get("category_type")) != category_type:
                continue
            actual_value = float(row.get("value") or 0.0)
            if abs(actual_value - expected_value) > value_tolerance:
                continue
            return row
        return None
