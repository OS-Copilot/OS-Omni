"""Evaluate Safari tasks from simulator history, bookmarks, and tabs databases."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.ios.safari_store import (
    DEFAULT_BUNDLE_ID,
    IOSSafariStore,
    coerce_bookmark_specs,
    coerce_tab_specs,
    normalize_text,
    normalize_url,
)


class SafariStateEvaluator(BaseEvaluator):
    DEFAULT_TIMEOUT_SECONDS = 8.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        bundle_id = str(params.get("bundle_id") or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        present_history_urls = self._coerce_url_list(params.get("present_history_urls"))
        absent_history_urls = self._coerce_url_list(params.get("absent_history_urls"))
        present_bookmarks = coerce_bookmark_specs(params.get("present_bookmarks"))
        present_folders = coerce_bookmark_specs(params.get("present_folders"), default_is_folder=True)
        absent_bookmark_urls = self._coerce_url_list(params.get("absent_bookmark_urls"))
        absent_bookmark_titles = self._coerce_text_list(params.get("absent_bookmark_titles"))
        present_tabs = coerce_tab_specs(params.get("present_tabs"))
        absent_tab_urls = self._coerce_url_list(params.get("absent_tab_urls"))
        active_tab_url = normalize_url(params.get("active_tab_url"))
        require_foreground = bool(params.get("require_foreground", False))

        if (
            not present_history_urls
            and not absent_history_urls
            and not present_bookmarks
            and not present_folders
            and not absent_bookmark_urls
            and not absent_bookmark_titles
            and not present_tabs
            and not absent_tab_urls
            and not active_tab_url
            and not require_foreground
        ):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires at least one Safari expectation",
            )

        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        try:
            store = self._build_store(controller=controller, params=params, bundle_id=bundle_id)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to resolve Safari state store: {type(exc).__name__}: {exc}",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_failures: list[str] = []
        last_metadata: dict[str, Any] = {}

        while True:
            attempts += 1
            try:
                bookmarks = store.list_bookmarks()
                tabs = store.list_tabs()
                history = store.list_history()
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query Safari state: {type(exc).__name__}: {exc}",
                )

            id_to_bookmark = {record.rowid: record for record in bookmarks}
            history_urls = {record.url for record in history}
            bookmark_urls = {record.url for record in bookmarks if record.url}
            bookmark_titles = {record.title for record in bookmarks if record.title}
            tab_urls = {record.user_visible_url or record.url for record in tabs if (record.user_visible_url or record.url)}
            latest_tab = tabs[0] if tabs else None

            failures: list[str] = []

            if require_foreground and controller is not None:
                actual_bundle_id = ""
                try:
                    observation = controller.observe()
                    actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
                except Exception:
                    actual_bundle_id = ""
                if actual_bundle_id != bundle_id:
                    failures.append(
                        f"foreground bundle expected {bundle_id} but got {actual_bundle_id or '<unknown>'}"
                    )

            for url in present_history_urls:
                if url not in history_urls:
                    failures.append(f"missing history url: {url}")

            for url in absent_history_urls:
                if url in history_urls:
                    failures.append(f"unexpected history url still present: {url}")

            for spec in present_bookmarks + present_folders:
                matched = any(
                    store.bookmark_matches_spec(record, spec, id_to_bookmark)
                    for record in bookmarks
                )
                if not matched:
                    expected_kind = "folder" if spec.is_folder else "bookmark"
                    failures.append(
                        f"missing {expected_kind}: title={spec.title or '<any>'}, "
                        f"url={spec.url or '<any>'}, parent={spec.parent_title or '<any>'}"
                    )

            for url in absent_bookmark_urls:
                if url in bookmark_urls:
                    failures.append(f"unexpected bookmark url still present: {url}")

            for title in absent_bookmark_titles:
                if title in bookmark_titles:
                    failures.append(f"unexpected bookmark title still present: {title}")

            for spec in present_tabs:
                matched = any(store.tab_matches_spec(record, spec) for record in tabs)
                if not matched:
                    failures.append(
                        f"missing tab: url={spec.url or '<any>'}, title={spec.title or '<any>'}"
                    )

            for url in absent_tab_urls:
                if url in tab_urls:
                    failures.append(f"unexpected tab still present: {url}")

            if active_tab_url:
                observed_active_url = latest_tab.user_visible_url or latest_tab.url if latest_tab else ""
                if observed_active_url != active_tab_url:
                    failures.append(
                        f"active tab expected {active_tab_url} but got {observed_active_url or '<none>'}"
                    )

            last_failures = failures
            last_metadata = {
                "history_urls": sorted(history_urls),
                "bookmark_titles": sorted(bookmark_titles),
                "bookmark_urls": sorted(bookmark_urls),
                "tab_urls": sorted(tab_urls),
                "active_tab_url": (latest_tab.user_visible_url or latest_tab.url) if latest_tab else "",
            }

            if not failures:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Safari state matches the expected task outcome",
                    metadata={"attempts": attempts, **last_metadata},
                )

            if time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Safari state does not match the expected task outcome",
            metadata={"attempts": attempts, "failures": last_failures, **last_metadata},
        )

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any], bundle_id: str) -> IOSSafariStore:
        safari_root = str(params.get("safari_root") or "").strip()
        if safari_root:
            return IOSSafariStore(safari_root, bundle_id=bundle_id)

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Safari evaluator needs params.safari_root or a controller with runtime.udid")
        return IOSSafariStore.from_simulator(udid, bundle_id=bundle_id)

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [value for item in raw if (value := normalize_text(item))]

    @staticmethod
    def _coerce_url_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [value for item in raw if (value := normalize_url(item))]
