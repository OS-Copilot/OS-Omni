"""Oracle-only state seeding helpers for iOS benchmark tasks.

These helpers intentionally live outside the public iOS action schema.  They are
only invoked by scripted oracle task YAMLs through metadata.oracle_actions.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from initializers.ios.greenmail_open_app import GreenMailOpenAppInitializer
from initializers.ios.greenmail_seed_open_app import GreenMailSeedOpenAppInitializer
from platforms.ios.calendar_store import IOSCalendarStore, coerce_event_specs, default_timezone_name
from platforms.ios.contacts_store import IOSContactsStore, coerce_contact_specs
from platforms.ios.flow_store import (
    DEFAULT_BUNDLE_ID as FLOW_BUNDLE_ID,
    DEFAULT_SUBDIRECTORY,
    IOSFlowStore,
    resolve_flow_repo_path,
)
from platforms.ios.fsnotes_store import DEFAULT_BUNDLE_ID as FSNOTES_BUNDLE_ID
from platforms.ios.fsnotes_store import FSNotesStore
from platforms.ios.habit_store import DEFAULT_BUNDLE_ID as HABIT_BUNDLE_ID
from platforms.ios.habit_store import IOSHabitStore
from platforms.ios.openshop_store import DEFAULT_BUNDLE_ID as OPENSHOP_BUNDLE_ID
from platforms.ios.openshop_store import OpenShopStore, coerce_cart_item_specs
from platforms.ios.reminder_store import DEFAULT_BUNDLE_ID as REMINDERS_BUNDLE_ID
from platforms.ios.reminder_store import IOSReminderStore, coerce_present_titles
from platforms.ios.safari_store import DEFAULT_BUNDLE_ID as SAFARI_BUNDLE_ID
from platforms.ios.safari_store import IOSSafariStore, normalize_text, normalize_url


def apply_seed_state(runtime: Any, action: Mapping[str, Any]) -> dict[str, Any]:
    store_name = str(action.get("store") or action.get("target") or "").strip().lower()
    params = _mapping(action.get("params") or action.get("state"))
    if not store_name:
        raise ValueError("seed_state requires 'store'")

    if store_name == "openshop":
        return _seed_openshop(runtime, params)
    if store_name == "calendar":
        return _seed_calendar(runtime, params)
    if store_name == "contacts":
        return _seed_contacts(runtime, params)
    if store_name == "habit":
        return _seed_habit(runtime, params)
    if store_name == "fsnotes":
        return _seed_fsnotes(runtime, params)
    if store_name == "flow":
        return _seed_flow(runtime, params)
    if store_name == "greenmail":
        return _seed_greenmail(params)
    if store_name == "safari":
        return _seed_safari(runtime, params)
    if store_name == "reminders":
        return _seed_reminders(runtime, params)

    raise ValueError(f"Unsupported seed_state store: {store_name}")


def _seed_openshop(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or OPENSHOP_BUNDLE_ID
    _terminate_app(runtime, bundle_id)
    store = OpenShopStore.from_simulator(_runtime_udid(runtime, params), bundle_id=bundle_id)

    state = store.build_fresh_state(login_session=bool(params.get("session_logged_in", False)))
    latest_order = params.get("latest_order") if isinstance(params.get("latest_order"), Mapping) else None
    order_count = _optional_int(params.get("order_count"))

    if latest_order:
        order = _build_openshop_order(store, latest_order)
        state["orders"] = [order]
        state["cart"] = []
    else:
        state["cart"] = store.build_cart_entries(params.get("present_cart_items") or [])
        state["orders"] = []

    if order_count is not None:
        if order_count <= 0:
            state["orders"] = []
        elif state["orders"]:
            while len(state["orders"]) < order_count:
                extra = dict(state["orders"][-1])
                extra["id"] = f"TB-ORACLE-{len(state['orders']) + 1:04d}"
                state["orders"].append(extra)

    store.write_state(state)
    store.clear_saved_state()
    if bool(params.get("activate_app", False)):
        _activate_app(runtime, bundle_id)
    return {
        "success": True,
        "message": "Seeded OpenShop oracle state",
        "terminal": False,
        "details": {
            "cart_size": len(state.get("cart") or []),
            "order_count": len(state.get("orders") or []),
        },
    }


def _build_openshop_order(store: OpenShopStore, expectation: Mapping[str, Any]) -> dict[str, Any]:
    items = []
    subtotal = 0.0
    for index, spec in enumerate(coerce_cart_item_specs(expectation.get("items")), start=1):
        product = store.find_product(spec.product_id)
        if product is None:
            raise ValueError(f"Unknown OpenShop product_id: {spec.product_id}")
        specs_list = product.get("specs") if isinstance(product, Mapping) else None
        default_spec = (
            _string(specs_list[0])
            if isinstance(specs_list, list) and specs_list and _string(specs_list[0])
            else ""
        )
        quantity = max(1, int(spec.quantity))
        subtotal += float(product.get("price") or 0) * quantity
        items.append(
            {
                "id": f"cart-oracle-{index:04d}",
                "quantity": quantity,
                "selectedSpec": spec.selected_spec or default_spec,
                "product": product,
            }
        )

    shipping = 12 if items else 0
    discount = 30 if subtotal >= 300 else 0
    total = expectation.get("total")
    if total is None:
        total = subtotal + shipping - discount

    address_id = _string(expectation.get("address_id"))
    payment_id = _string(expectation.get("payment_method_id"))
    address = _find_seed_record(store, "addresses", address_id)
    payment = _find_seed_record(store, "paymentMethods", payment_id)

    return {
        "id": f"TB-ORACLE-{int(time.time() * 1000)}",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "address": address,
        "payment": payment,
        "note": _string(expectation.get("note")),
        "items": items,
        "total": total,
        "status": _string(expectation.get("status")) or "Awaiting Shipment",
    }


def _find_seed_record(store: OpenShopStore, key: str, record_id: str) -> dict[str, Any]:
    for item in store.load_seed_payload().get(key, []) or []:
        if isinstance(item, Mapping) and _string(item.get("id")) == record_id:
            return dict(item)
    raise ValueError(f"Unknown OpenShop {key} id: {record_id}")


def _seed_calendar(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or "com.apple.mobilecal"
    timezone_name = _string(params.get("timezone")) or default_timezone_name()
    _terminate_app(runtime, bundle_id)
    store = IOSCalendarStore.from_simulator(_runtime_udid(runtime, params), timezone_name=timezone_name)
    present_events = coerce_event_specs(params.get("present_events"))
    absent_summaries = _text_list(params.get("absent_summaries"))
    purge_summaries = sorted({*absent_summaries, *(event.summary for event in present_events)})
    deleted_count = store.purge_events_by_summaries(purge_summaries)
    seeded_rowids = store.seed_events(present_events)
    if bool(params.get("activate_app", False)):
        _activate_app(runtime, bundle_id)
    return {
        "success": True,
        "message": "Seeded Calendar oracle state",
        "terminal": False,
        "details": {"deleted_count": deleted_count, "seeded_rowids": seeded_rowids},
    }


def _seed_reminders(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or REMINDERS_BUNDLE_ID
    list_name = _string(params.get("list_name")) or "Reminders"
    present_titles = coerce_present_titles(params.get("present_titles"))
    if not present_titles:
        present_titles = coerce_present_titles(params.get("seed_reminders"))

    _terminate_app(runtime, bundle_id)
    store = IOSReminderStore.from_simulator(_runtime_udid(runtime, params))
    seed_result = store.seed_present_titles(list_name=list_name, present_titles=present_titles)
    if bool(params.get("activate_app", True)):
        _activate_app(runtime, bundle_id)
        _open_reminders_list(runtime, list_name)
    return {
        "success": True,
        "message": "Seeded Reminders oracle state",
        "terminal": False,
        "details": {
            "list_name": seed_result["list_name"],
            "deleted_count": seed_result["deleted_count"],
            "seeded_rowids": seed_result["seeded_rowids"],
        },
    }


def _open_reminders_list(runtime: Any, list_name: str) -> None:
    driver = getattr(runtime, "driver", None)
    if driver is None:
        return

    try:
        from appium.webdriver.common.appiumby import AppiumBy
    except Exception:
        return

    # Reminders evaluators verify both DB state and that the expected list is
    # visible. After direct DB writes, tap the list once if Reminders restores to
    # the lists home screen.
    for _attempt in range(3):
        if _reminders_list_view_active(driver, AppiumBy, list_name):
            return
        if _tap_first_matching_element(driver, AppiumBy, _text_predicate(list_name)):
            time.sleep(0.8)
            if _reminders_list_view_active(driver, AppiumBy, list_name):
                return
        if _tap_first_matching_element(driver, AppiumBy, _text_predicate("Back")):
            time.sleep(0.5)
            continue
        time.sleep(0.4)


def _reminders_list_view_active(driver: Any, appium_by: Any, list_name: str) -> bool:
    has_title = bool(_find_elements(driver, appium_by, _text_predicate(list_name)))
    has_back = bool(_find_elements(driver, appium_by, _text_predicate("Back")))
    return has_title and has_back


def _tap_first_matching_element(driver: Any, appium_by: Any, predicate: str) -> bool:
    for element in _find_elements(driver, appium_by, predicate):
        try:
            if hasattr(element, "is_displayed") and not element.is_displayed():
                continue
            element.click()
            return True
        except Exception:
            continue
    return False


def _find_elements(driver: Any, appium_by: Any, predicate: str) -> list[Any]:
    try:
        return list(driver.find_elements(appium_by.IOS_PREDICATE, predicate))
    except Exception:
        return []


def _text_predicate(text: str) -> str:
    value = _predicate_string(text)
    return f"name == {value} OR label == {value} OR value == {value}"


def _predicate_string(text: str) -> str:
    return '"' + str(text or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _seed_contacts(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or "com.apple.MobileAddressBook"
    _terminate_app(runtime, bundle_id)
    store = IOSContactsStore.from_simulator(_runtime_udid(runtime, params))
    present_contacts = coerce_contact_specs(params.get("present_contacts"))
    deleted_count = store.purge_all_contacts()
    seeded_rowids = store.seed_contacts(present_contacts)
    if bool(params.get("activate_app", False)):
        _activate_app(runtime, bundle_id)
    return {
        "success": True,
        "message": "Seeded Contacts oracle state",
        "terminal": False,
        "details": {"deleted_count": deleted_count, "seeded_rowids": seeded_rowids},
    }


def _seed_habit(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or HABIT_BUNDLE_ID
    _terminate_app(runtime, bundle_id)
    store = IOSHabitStore.from_simulator(_runtime_udid(runtime, params), bundle_id=bundle_id)
    assert_spec = _mapping(params.get("assert_spec"))
    habits = list(_mapping_list(assert_spec.get("present_habits")))
    if not habits:
        habits = [{"title": title} for title in _text_list(assert_spec.get("exact_titles"))]
    records = store.reset_habits(habits)
    store.clear_saved_state()
    if bool(params.get("activate_app", False)):
        _activate_app(runtime, bundle_id)
    return {
        "success": True,
        "message": "Seeded Habit oracle state",
        "terminal": False,
        "details": {"habit_count": len(records)},
    }


def _seed_fsnotes(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or FSNOTES_BUNDLE_ID
    _terminate_app(runtime, bundle_id)
    store = FSNotesStore.from_simulator(_runtime_udid(runtime, params), bundle_id=bundle_id)
    seed_spec = _fsnotes_seed_spec_from_assert(_mapping(params.get("assert_spec")))
    seed_result = store.seed(seed_spec)
    store.clear_saved_state()
    if bool(params.get("activate_app", False)):
        _activate_app(runtime, bundle_id)
    return {
        "success": True,
        "message": "Seeded FSNotes oracle state",
        "terminal": False,
        "details": seed_result,
    }


def _fsnotes_seed_spec_from_assert(assert_spec: Mapping[str, Any]) -> dict[str, Any]:
    folders = [{"path": folder} for folder in _text_list(assert_spec.get("present_folders"))]
    notes = []
    for note in _mapping_list(assert_spec.get("present_notes")):
        resolved = dict(note)
        if "content" not in resolved and "body" not in resolved:
            if "exact_content" in resolved:
                resolved["content"] = str(resolved.get("exact_content") or "")
            else:
                fragments = [str(item) for item in _text_list(resolved.get("content_contains"))]
                title = _string(resolved.get("title")) or Path(_string(resolved.get("path"))).stem
                resolved["content"] = "\n".join([title, *fragments]).strip() + "\n"
        notes.append(resolved)
    return {"purge_all_notes": True, "folders": folders, "notes": notes}


def _seed_flow(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or FLOW_BUNDLE_ID
    flow_repo_path = str(resolve_flow_repo_path(_string(params.get("flow_repo_path"))))
    subdirectory = _string(params.get("subdirectory")) or DEFAULT_SUBDIRECTORY
    _terminate_app(runtime, bundle_id)
    store = IOSFlowStore.from_simulator(
        _runtime_udid(runtime, params),
        bundle_id=bundle_id,
        flow_repo_path=flow_repo_path,
        subdirectory=subdirectory,
    )
    seed_spec = _flow_seed_spec_from_assert(
        _mapping(params.get("seed_spec")),
        _mapping(params.get("assert_spec")),
    )
    seed_result = store.seed(seed_spec)
    store.clear_saved_state()
    if bool(params.get("activate_app", False)):
        _activate_app(runtime, bundle_id)
    return {
        "success": True,
        "message": "Seeded Flow oracle state",
        "terminal": False,
        "details": {
            "account_count": len(seed_result.get("accounts", []) or []),
            "transaction_count": len(seed_result.get("transactions", []) or []),
        },
    }


def _flow_seed_spec_from_assert(seed_spec: Mapping[str, Any], assert_spec: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "accounts": list(_mapping_list(seed_spec.get("accounts"))),
        "categories": list(_mapping_list(seed_spec.get("categories"))),
        "opening_balances": list(_mapping_list(seed_spec.get("opening_balances"))),
        "transactions": [],
    }
    known_categories = {_string(item.get("name")) for item in result["categories"]}
    seen_transfer_keys: set[tuple[str, str, str, str]] = set()
    for item in _mapping_list(assert_spec.get("present_transactions")):
        tx_type = _string(item.get("type")).lower()
        title = _string(item.get("title"))
        description = _string(item.get("description"))
        amount = float(item.get("amount") or 0)
        if tx_type in {"expense", "income"}:
            category = _string(item.get("category"))
            if category and category not in known_categories:
                result["categories"].append({"name": category})
                known_categories.add(category)
            result["transactions"].append(
                {
                    "kind": tx_type,
                    "account": _string(item.get("account")),
                    "category": category,
                    "amount": abs(amount),
                    "title": title,
                    "description": description,
                }
            )
        elif tx_type == "transfer":
            from_account = _string(item.get("from_account"))
            to_account = _string(item.get("to_account"))
            key = (from_account, to_account, title, description)
            if amount > 0 or key in seen_transfer_keys:
                continue
            seen_transfer_keys.add(key)
            result["transactions"].append(
                {
                    "kind": "transfer",
                    "from_account": from_account,
                    "to_account": to_account,
                    "amount": abs(amount),
                    "title": title,
                    "description": description,
                }
            )
    return result


def _seed_greenmail(params: Mapping[str, Any]) -> dict[str, Any]:
    api_base_url = _string(params.get("api_base_url")) or GreenMailOpenAppInitializer.DEFAULT_API_BASE_URL
    api_base_url = api_base_url.rstrip("/")
    if bool(params.get("purge", True)):
        GreenMailOpenAppInitializer._ensure_greenmail_ready(api_base_url)
        GreenMailOpenAppInitializer._purge_greenmail(api_base_url)

    messages = _mapping_list(params.get("messages"))
    for message in messages:
        GreenMailSeedOpenAppInitializer._seed_message(_normalize_greenmail_message(message))
    return {
        "success": True,
        "message": "Seeded GreenMail oracle state",
        "terminal": False,
        "details": {"message_count": len(messages), "api_base_url": api_base_url},
    }


def _normalize_greenmail_message(message: Mapping[str, Any]) -> dict[str, Any]:
    sender = _string(message.get("sender_email"))
    recipient = _string(message.get("recipient_email"))
    body = str(message.get("body") or message.get("required_body_fragment") or "")
    subject = _string(message.get("subject")) or "iOS Oracle Message"
    if not sender or not recipient or not body:
        raise ValueError("GreenMail oracle messages require sender_email, recipient_email, and body")
    normalized = {
        "sender_email": sender,
        "sender_password": _string(message.get("sender_password")) or "benchpass",
        "recipient_email": recipient,
        "subject": subject,
        "body": body,
        "smtp_host": _string(message.get("smtp_host")) or GreenMailSeedOpenAppInitializer.DEFAULT_SMTP_HOST,
        "smtp_port": int(message.get("smtp_port") or GreenMailSeedOpenAppInitializer.DEFAULT_SMTP_PORT),
    }
    chat_version = _string(message.get("chat_version"))
    if chat_version:
        normalized["chat_version"] = chat_version
    return normalized


def _seed_safari(runtime: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = _string(params.get("bundle_id")) or SAFARI_BUNDLE_ID
    _terminate_app(runtime, bundle_id)
    store = IOSSafariStore.from_simulator(_runtime_udid(runtime, params), bundle_id=bundle_id)
    store.ensure_ready()

    present_history_urls = _text_list(params.get("present_history_urls"))
    present_bookmarks = _mapping_list(params.get("present_bookmarks"))
    present_folders = _mapping_list(params.get("present_folders"))
    present_tabs = _mapping_list(params.get("present_tabs"))
    active_tab_url = normalize_url(params.get("active_tab_url"))

    deleted_history = store.purge_history(purge_all=bool(params.get("purge_all_history", True)))
    deleted_bookmarks = store.purge_bookmarks(
        urls=[*present_history_urls, *_urls_from_specs(present_bookmarks), *_text_list(params.get("absent_bookmark_urls"))],
        titles=[*_titles_from_specs(present_bookmarks), *_text_list(params.get("absent_bookmark_titles"))],
        folder_titles=[*_titles_from_specs(present_folders)],
    )
    deleted_tabs = store.purge_tabs(purge_all=bool(params.get("purge_all_tabs", True)))

    _seed_safari_history(store, present_history_urls)
    _seed_safari_bookmarks(store, present_folders, present_bookmarks)
    _seed_safari_tabs(store, present_tabs, active_tab_url)

    if bool(params.get("require_foreground")) or bool(params.get("activate_app", True)):
        _activate_app(runtime, bundle_id)
    return {
        "success": True,
        "message": "Seeded Safari oracle state",
        "terminal": False,
        "details": {
            "history_count": len(present_history_urls),
            "folder_count": len(present_folders),
            "bookmark_count": len(present_bookmarks),
            "tab_count": len(present_tabs),
            "deleted_history": deleted_history,
            "deleted_bookmarks": deleted_bookmarks,
            "deleted_tabs": deleted_tabs,
        },
    }


def _seed_safari_history(store: IOSSafariStore, urls: Sequence[str]) -> None:
    if not urls:
        return
    with _connect_sqlite(store.history_db_path) as conn:
        now = time.time()
        for index, url in enumerate(urls):
            normalized_url = normalize_url(url)
            if not normalized_url:
                continue
            domain = urlsplit(normalized_url).netloc.split(":")[0].lower()
            conn.execute(
                """
                INSERT OR IGNORE INTO history_items(
                    url, domain_expansion, visit_count, daily_visit_counts,
                    weekly_visit_counts, autocomplete_triggers,
                    should_recompute_derived_visit_counts, visit_count_score, status_code
                ) VALUES (?, ?, 0, ?, NULL, NULL, 0, 0, 0)
                """,
                (normalized_url, domain, sqlite3.Binary(b"")),
            )
            row = conn.execute("SELECT id, visit_count FROM history_items WHERE url = ?", (normalized_url,)).fetchone()
            if row is None:
                continue
            item_id = int(row[0])
            conn.execute(
                "UPDATE history_items SET visit_count = visit_count + 1 WHERE id = ?",
                (item_id,),
            )
            conn.execute(
                """
                INSERT INTO history_visits(history_item, visit_time, title, load_successful)
                VALUES (?, ?, ?, 1)
                """,
                (item_id, now + index, normalized_url),
            )
        conn.commit()


def _seed_safari_bookmarks(
    store: IOSSafariStore,
    folders: Sequence[Mapping[str, Any]],
    bookmarks: Sequence[Mapping[str, Any]],
) -> None:
    if not folders and not bookmarks:
        return
    with _connect_sqlite(store.bookmarks_db_path) as conn:
        parent_by_title: dict[str, int] = {}
        root_parent = _safari_bookmarks_parent(conn)
        for folder in folders:
            title = normalize_text(folder.get("title"))
            if not title:
                continue
            parent_by_title[title] = _ensure_safari_folder(conn, title, root_parent)

        for bookmark in bookmarks:
            title = normalize_text(bookmark.get("title"))
            url = normalize_url(bookmark.get("url"))
            if not title and not url:
                continue
            parent_title = normalize_text(bookmark.get("parent_title"))
            parent = parent_by_title.get(parent_title)
            if parent is None and parent_title:
                parent = _ensure_safari_folder(conn, parent_title, root_parent)
                parent_by_title[parent_title] = parent
            if parent is None:
                parent = root_parent
            conn.execute(
                "DELETE FROM bookmarks WHERE deleted = 0 AND type = 0 AND (title = ? OR url = ?)",
                (title, url),
            )
            order_index = _next_safari_bookmark_order(conn, parent)
            conn.execute(
                """
                INSERT INTO bookmarks(
                    special_id, parent, type, title, url, num_children,
                    editable, deletable, hidden, hidden_ancestor_count, order_index,
                    external_uuid, added, deleted, fetched_icon, dav_generation,
                    locally_added, archive_status, syncable, web_filter_status,
                    modified_attributes, subtype
                ) VALUES (0, ?, 0, ?, ?, 0, 1, 1, 0, 0, ?, ?, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0)
                """,
                (parent, title or url, url, order_index, str(uuid.uuid4()).upper()),
            )
        _refresh_safari_bookmark_child_counts(conn)
        conn.commit()


def _safari_bookmarks_parent(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM bookmarks WHERE special_id = 1 AND type = 1 AND deleted = 0 LIMIT 1"
    ).fetchone()
    if row is not None:
        return int(row[0])
    row = conn.execute("SELECT id FROM bookmarks WHERE id = 1 LIMIT 1").fetchone()
    return int(row[0]) if row is not None else 0


def _ensure_safari_folder(conn: sqlite3.Connection, title: str, parent: int) -> int:
    row = conn.execute(
        "SELECT id FROM bookmarks WHERE deleted = 0 AND type = 1 AND title = ? LIMIT 1",
        (title,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    order_index = _next_safari_bookmark_order(conn, parent)
    cursor = conn.execute(
        """
        INSERT INTO bookmarks(
            special_id, parent, type, title, url, num_children,
            editable, deletable, hidden, hidden_ancestor_count, order_index,
            external_uuid, added, deleted, fetched_icon, dav_generation,
            locally_added, archive_status, syncable, web_filter_status,
            modified_attributes, subtype
        ) VALUES (0, ?, 1, ?, NULL, 0, 1, 1, 0, 0, ?, ?, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0)
        """,
        (parent, title, order_index, str(uuid.uuid4()).upper()),
    )
    return int(cursor.lastrowid)


def _next_safari_bookmark_order(conn: sqlite3.Connection, parent: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) + 1 FROM bookmarks WHERE parent = ? AND deleted = 0",
        (parent,),
    ).fetchone()
    return int(row[0] or 0)


def _refresh_safari_bookmark_child_counts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE bookmarks
        SET num_children = (
            SELECT COUNT(*)
            FROM bookmarks child
            WHERE child.parent = bookmarks.id AND child.deleted = 0
        )
        WHERE type = 1
        """
    )


def _seed_safari_tabs(
    store: IOSSafariStore,
    tabs: Sequence[Mapping[str, Any]],
    active_tab_url: str,
) -> None:
    if not tabs:
        return
    with _connect_sqlite(store.browser_state_db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        window_id, window_uuid = _ensure_safari_browser_window(conn)
        now = time.time()
        active_index = 0
        for index, tab in enumerate(tabs):
            url = normalize_url(tab.get("url"))
            title = normalize_text(tab.get("title")) or url
            if not url and not title:
                continue
            if active_tab_url and url == active_tab_url:
                active_index = index
            conn.execute(
                """
                INSERT INTO tabs(
                    uuid, title, url, user_visible_url, order_index, last_viewed_time,
                    readinglist_bookmark_id, opened_from_link, showing_reader,
                    reader_view_top_scroll_offset, private_browsing,
                    displaying_standalone_image, browser_window_uuid, browser_window_id,
                    tab_group_uuid, profile_uuid
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, ?, ?, '', '')
                """,
                (
                    str(uuid.uuid4()).upper(),
                    title,
                    url,
                    url,
                    index,
                    now + index + (1000 if active_tab_url and url == active_tab_url else 0),
                    window_uuid,
                    window_id,
                ),
            )
        conn.execute(
            """
            UPDATE browser_windows
            SET active_document_index = ?,
                active_document_is_valid = 1,
                tab_state_successfully_loaded = 0
            WHERE id = ?
            """,
            (active_index, window_id),
        )
        conn.commit()


def _ensure_safari_browser_window(conn: sqlite3.Connection) -> tuple[int, str]:
    row = conn.execute("SELECT id, uuid FROM browser_windows ORDER BY id ASC LIMIT 1").fetchone()
    if row is not None:
        return int(row[0]), str(row[1])
    window_uuid = str(uuid.uuid4()).upper()
    cursor = conn.execute(
        """
        INSERT INTO browser_windows(
            uuid, type, active_document_index, active_private_document_index,
            active_document_is_valid, tab_state_successfully_loaded,
            legacy_plist_file_version, scene_ID, active_profile_identifier
        ) VALUES (?, 0, 0, 0, 1, 0, 0, NULL, '')
        """,
        (window_uuid,),
    )
    return int(cursor.lastrowid), window_uuid


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10.0)
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _runtime_udid(runtime: Any, params: Mapping[str, Any]) -> str:
    udid = _string(params.get("udid")) or _string(getattr(runtime, "udid", ""))
    if not udid:
        raise ValueError("seed_state requires params.udid or runtime.udid")
    return udid


def _terminate_app(runtime: Any, bundle_id: str) -> None:
    if not bundle_id or not hasattr(runtime, "terminate_app"):
        return
    try:
        runtime.terminate_app(bundle_id)
        deadline = time.time() + 4.0
        while time.time() < deadline:
            if not hasattr(runtime, "query_app_state"):
                break
            try:
                if int(runtime.query_app_state(bundle_id)) <= 1:
                    return
            except Exception:
                break
            time.sleep(0.2)
        time.sleep(0.8)
    except Exception:
        return


def _activate_app(runtime: Any, bundle_id: str) -> None:
    if not bundle_id or not hasattr(runtime, "activate_app"):
        return
    runtime.activate_app(bundle_id)
    time.sleep(0.6)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _string(item))]


def _urls_from_specs(items: Sequence[Mapping[str, Any]]) -> list[str]:
    return [url for item in items if (url := normalize_url(item.get("url")))]


def _titles_from_specs(items: Sequence[Mapping[str, Any]]) -> list[str]:
    return [title for item in items if (title := normalize_text(item.get("title")))]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str:
    return str(value or "").strip()
