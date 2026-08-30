"""Evaluator for OpenShop shopping tasks backed by localStorage state."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.ios.openshop_store import DEFAULT_BUNDLE_ID, OpenShopStore, coerce_cart_item_specs


class OpenShopStateEvaluator(BaseEvaluator):
    DEFAULT_TIMEOUT_SECONDS = 8.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        session_logged_in = params.get("session_logged_in")
        expected_cart_size = params.get("cart_size")
        expected_order_count = params.get("order_count")
        present_cart_items = coerce_cart_item_specs(params.get("present_cart_items"))
        absent_cart_product_ids = self._coerce_text_list(params.get("absent_cart_product_ids"))
        latest_order = params.get("latest_order") if isinstance(params.get("latest_order"), Mapping) else None

        if (
            session_logged_in is None
            and expected_cart_size is None
            and expected_order_count is None
            and not present_cart_items
            and not absent_cart_product_ids
            and latest_order is None
        ):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires at least one OpenShop expectation",
            )

        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )
        bundle_id = str(params.get("bundle_id") or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID

        try:
            store = self._build_store(controller=controller, params=params, bundle_id=bundle_id)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to resolve OpenShop state store: {type(exc).__name__}: {exc}",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_cart_summary: list[dict[str, Any]] = []
        last_order_count = 0
        last_failures: list[str] = []

        while True:
            attempts += 1
            try:
                state = store.read_state()
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query OpenShop local state: {type(exc).__name__}: {exc}",
                )

            failures: list[str] = []
            session = state.get("session") if isinstance(state, dict) else {}
            cart = state.get("cart") if isinstance(state, dict) else []
            orders = state.get("orders") if isinstance(state, dict) else []
            last_cart_summary = store.summarize_cart(state)
            last_order_count = len(orders) if isinstance(orders, list) else 0

            if session_logged_in is not None:
                observed_logged_in = bool(session.get("loggedIn")) if isinstance(session, Mapping) else False
                if observed_logged_in != bool(session_logged_in):
                    failures.append(
                        f"session.loggedIn expected {bool(session_logged_in)} but got {observed_logged_in}"
                    )

            if expected_cart_size is not None:
                try:
                    resolved_cart_size = int(expected_cart_size)
                except (TypeError, ValueError):
                    return EvalResult(
                        status=EvalStatus.ERROR,
                        message=f"Invalid cart_size expectation: {expected_cart_size!r}",
                    )
                observed_cart_size = len(cart) if isinstance(cart, list) else 0
                if observed_cart_size != resolved_cart_size:
                    failures.append(
                        f"cart size expected {resolved_cart_size} but got {observed_cart_size}"
                    )

            if expected_order_count is not None:
                try:
                    resolved_order_count = int(expected_order_count)
                except (TypeError, ValueError):
                    return EvalResult(
                        status=EvalStatus.ERROR,
                        message=f"Invalid order_count expectation: {expected_order_count!r}",
                    )
                if last_order_count != resolved_order_count:
                    failures.append(
                        f"order count expected {resolved_order_count} but got {last_order_count}"
                    )

            if isinstance(cart, list):
                for spec in present_cart_items:
                    matched = any(
                        isinstance(item, Mapping) and store.cart_item_matches_spec(item, spec)
                        for item in cart
                    )
                    if not matched:
                        failures.append(
                            f"missing cart item {spec.product_id} x{spec.quantity}"
                        )

                for product_id in absent_cart_product_ids:
                    present = any(
                        isinstance(item, Mapping)
                        and str(item.get("productId") or "").strip() == product_id
                        for item in cart
                    )
                    if present:
                        failures.append(f"unexpected cart item still present: {product_id}")

            if latest_order is not None:
                if not isinstance(orders, list) or not orders:
                    failures.append("expected a latest order but orders list is empty")
                else:
                    observed_latest = orders[0]
                    if not store.order_matches_expectation(observed_latest, latest_order):
                        failures.append("latest order does not match expected address/payment/note/items")

            if not failures:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="OpenShop local state matches the expected task outcome",
                    metadata={
                        "attempts": attempts,
                        "cart_summary": last_cart_summary,
                        "order_count": last_order_count,
                    },
                )

            last_failures = failures
            if time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="OpenShop local state does not match the expected task outcome",
            metadata={
                "attempts": attempts,
                "failures": last_failures,
                "cart_summary": last_cart_summary,
                "order_count": last_order_count,
            },
        )

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any], bundle_id: str) -> OpenShopStore:
        db_path = str(params.get("db_path") or "").strip()
        seed_data_path = str(params.get("seed_data_path") or "").strip()
        data_container_path = str(params.get("data_container_path") or "").strip()
        if db_path:
            return OpenShopStore(
                db_path,
                bundle_id=bundle_id,
                seed_data_path=seed_data_path or None,
                data_container_path=data_container_path or None,
            )

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("OpenShop evaluator needs params.db_path or a controller with runtime.udid")
        return OpenShopStore.from_simulator(udid, bundle_id=bundle_id)

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            text = " ".join(str(item or "").strip().split())
            if text:
                values.append(text)
        return values
