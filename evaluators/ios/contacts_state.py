"""Evaluator for iOS Contacts tasks backed by AddressBook.sqlitedb."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.ios.contacts_store import IOSContactsStore


class ContactsStateEvaluator(BaseEvaluator):
    DEFAULT_TIMEOUT_SECONDS = 8.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        try:
            store = self._build_store(controller=controller, params=params)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to resolve Contacts store: {type(exc).__name__}: {exc}",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_result: dict[str, Any] | None = None

        while True:
            attempts += 1
            try:
                last_result = store.assert_state(params)
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query Contacts database: {type(exc).__name__}: {exc}",
                )

            if (last_result or {}).get("status") == "pass":
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Contacts database matches the expected task outcome",
                    metadata={
                        "attempts": attempts,
                        "summary": (last_result or {}).get("summary", []),
                    },
                )

            if time.time() >= deadline:
                break

            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Contacts database does not match the expected task outcome",
            metadata={
                "attempts": attempts,
                "failures": (last_result or {}).get("failures", []),
                "summary": (last_result or {}).get("summary", []),
            },
        )

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any]) -> IOSContactsStore:
        db_path = str(params.get("db_path") or "").strip()
        if db_path:
            return IOSContactsStore(db_path)

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Contacts evaluator needs params.db_path or a controller with runtime.udid")
        return IOSContactsStore.from_simulator(udid)
