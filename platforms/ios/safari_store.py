"""Helpers for reading and resetting Safari simulator state."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


DEFAULT_BUNDLE_ID = "com.apple.mobilesafari"


@dataclass(frozen=True)
class SafariBookmarkSpec:
    title: str = ""
    url: str = ""
    parent_title: str = ""
    is_folder: bool = False


@dataclass(frozen=True)
class SafariTabSpec:
    url: str = ""
    title: str = ""


@dataclass(frozen=True)
class SafariBookmarkRecord:
    rowid: int
    parent: int | None
    record_type: int
    title: str
    url: str
    deleted: bool
    order_index: int
    num_children: int
    special_id: int

    @property
    def is_folder(self) -> bool:
        return self.record_type == 1


@dataclass(frozen=True)
class SafariHistoryRecord:
    item_id: int
    url: str
    title: str
    visit_time: float


@dataclass(frozen=True)
class SafariTabRecord:
    rowid: int
    title: str
    url: str
    user_visible_url: str
    order_index: int
    last_viewed_time: float | None
    private_browsing: bool
    browser_window_id: int


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")
    path = parts.path or "/"
    normalized = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            parts.query,
            "",
        )
    )
    return normalized


def coerce_bookmark_specs(raw: Any, *, default_is_folder: bool = False) -> list[SafariBookmarkSpec]:
    if not isinstance(raw, list):
        return []

    specs: list[SafariBookmarkSpec] = []
    for item in raw:
        if isinstance(item, Mapping):
            title = normalize_text(item.get("title"))
            url = normalize_url(item.get("url"))
            parent_title = normalize_text(item.get("parent_title"))
            is_folder = bool(item.get("is_folder", default_is_folder))
        else:
            title = normalize_text(item)
            url = ""
            parent_title = ""
            is_folder = default_is_folder

        if not title and not url:
            continue
        specs.append(
            SafariBookmarkSpec(
                title=title,
                url=url,
                parent_title=parent_title,
                is_folder=is_folder,
            )
        )
    return specs


def coerce_tab_specs(raw: Any) -> list[SafariTabSpec]:
    if not isinstance(raw, list):
        return []

    specs: list[SafariTabSpec] = []
    for item in raw:
        if isinstance(item, Mapping):
            url = normalize_url(item.get("url"))
            title = normalize_text(item.get("title"))
        else:
            url = normalize_url(item)
            title = ""
        if not url and not title:
            continue
        specs.append(SafariTabSpec(url=url, title=title))
    return specs


class IOSSafariStore:
    """Read Safari history/bookmarks/tabs directly from simulator databases."""

    def __init__(
        self,
        safari_root: str | Path,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
    ) -> None:
        self.safari_root = Path(safari_root).expanduser().resolve()
        self.bundle_id = str(bundle_id or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        self.history_db_path = self.safari_root / "History.db"
        self.bookmarks_db_path = self.safari_root / "Bookmarks.db"
        self.safari_tabs_db_path = self.safari_root / "SafariTabs.db"

    @classmethod
    def from_simulator(
        cls,
        udid: str,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
    ) -> "IOSSafariStore":
        resolved_udid = str(udid or "").strip()
        if not resolved_udid:
            raise ValueError("Simulator UDID is required")
        safari_root = (
            Path.home()
            / "Library"
            / "Developer"
            / "CoreSimulator"
            / "Devices"
            / resolved_udid
            / "data"
            / "Library"
            / "Safari"
        )
        return cls(safari_root, bundle_id=bundle_id)

    def ensure_ready(self) -> None:
        missing = [
            str(path.name)
            for path in (self.history_db_path, self.bookmarks_db_path, self.safari_tabs_db_path)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(
                f"Safari simulator databases are missing under {self.safari_root}: {', '.join(missing)}"
            )

    def list_history(self) -> list[SafariHistoryRecord]:
        self.ensure_ready()
        with self._snapshot_db_path(self.history_db_path) as db_path:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT hi.id AS item_id, hi.url AS url, hv.title AS title, hv.visit_time AS visit_time
                    FROM history_items hi
                    JOIN history_visits hv ON hv.history_item = hi.id
                    ORDER BY hv.visit_time DESC, hv.id DESC
                    """
                ).fetchall()
            finally:
                conn.close()

        return [
            SafariHistoryRecord(
                item_id=int(row["item_id"]),
                url=normalize_url(row["url"]),
                title=normalize_text(row["title"]),
                visit_time=float(row["visit_time"] or 0.0),
            )
            for row in rows
        ]

    def list_bookmarks(self, *, include_deleted: bool = False) -> list[SafariBookmarkRecord]:
        self.ensure_ready()
        with self._snapshot_db_path(self.bookmarks_db_path) as db_path:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                query = """
                    SELECT id, parent, type, title, url, deleted, order_index, num_children, special_id
                    FROM bookmarks
                """
                if not include_deleted:
                    query += " WHERE deleted = 0"
                query += " ORDER BY id ASC"
                rows = conn.execute(query).fetchall()
            finally:
                conn.close()

        return [
            SafariBookmarkRecord(
                rowid=int(row["id"]),
                parent=int(row["parent"]) if row["parent"] is not None else None,
                record_type=int(row["type"] or 0),
                title=normalize_text(row["title"]),
                url=normalize_url(row["url"]),
                deleted=bool(row["deleted"]),
                order_index=int(row["order_index"] or 0),
                num_children=int(row["num_children"] or 0),
                special_id=int(row["special_id"] or 0),
            )
            for row in rows
        ]

    def list_tabs(self) -> list[SafariTabRecord]:
        self.ensure_ready()
        return self._list_tabs_from_safari_tabs_db()

    def _list_tabs_from_safari_tabs_db(self) -> list[SafariTabRecord]:
        """Read current Safari tabs from SafariTabs.db.

        Current iOS/Safari simulator builds keep foreground tabs in SafariTabs.db.
        The active tab is represented by
        windows_tab_groups.active_tab_id pointing at a type=0 row in bookmarks.
        """
        with self._snapshot_db_path(self.safari_tabs_db_path) as db_path:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                if not self._table_exists(conn, "bookmarks") or not self._table_exists(
                    conn,
                    "windows_tab_groups",
                ):
                    raise RuntimeError("SafariTabs.db does not contain the expected tab schema")
                rows = conn.execute(
                    """
                    SELECT b.id AS id,
                           b.title AS title,
                           b.url AS url,
                           b.order_index AS order_index,
                           b.parent AS tab_group_id,
                           wtg.active_tab_id AS active_tab_id,
                           wtg.window_id AS browser_window_id
                    FROM bookmarks b
                    JOIN windows_tab_groups wtg ON wtg.tab_group_id = b.parent
                    WHERE b.type = 0
                      AND b.deleted = 0
                      AND b.date_closed IS NULL
                    ORDER BY CASE WHEN b.id = wtg.active_tab_id THEN 0 ELSE 1 END,
                             wtg.window_id ASC,
                             b.order_index ASC,
                             b.id DESC
                    """
                ).fetchall()
            finally:
                conn.close()

        return [
            SafariTabRecord(
                rowid=int(row["id"]),
                title=normalize_text(row["title"]),
                url=normalize_url(row["url"]),
                user_visible_url=normalize_url(row["url"]),
                order_index=int(row["order_index"] or 0),
                last_viewed_time=1.0 if row["id"] == row["active_tab_id"] else None,
                private_browsing=False,
                browser_window_id=int(row["browser_window_id"] or 0),
            )
            for row in rows
        ]

    def purge_history(
        self,
        *,
        urls: Sequence[str] | None = None,
        purge_all: bool = False,
    ) -> int:
        self.ensure_ready()
        normalized_urls = {normalize_url(url) for url in (urls or []) if normalize_url(url)}
        with self._connect_writable(self.history_db_path) as conn:
            if purge_all:
                deleted_visits = int(conn.execute("SELECT COUNT(*) FROM history_visits").fetchone()[0] or 0)
                conn.execute("DELETE FROM history_visits")
                conn.execute("DELETE FROM history_items")
                conn.commit()
                return deleted_visits

            if not normalized_urls:
                return 0

            rows = conn.execute("SELECT id, url FROM history_items").fetchall()
            target_item_ids = [
                int(row[0])
                for row in rows
                if normalize_url(row[1]) in normalized_urls
            ]
            if not target_item_ids:
                return 0

            placeholders = ",".join("?" for _ in target_item_ids)
            deleted_visits = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM history_visits WHERE history_item IN ({placeholders})",
                    target_item_ids,
                ).fetchone()[0]
                or 0
            )
            conn.execute(
                f"DELETE FROM history_visits WHERE history_item IN ({placeholders})",
                target_item_ids,
            )
            conn.execute(
                f"DELETE FROM history_items WHERE id IN ({placeholders})",
                target_item_ids,
            )
            conn.commit()
            return deleted_visits

    def purge_bookmarks(
        self,
        *,
        titles: Sequence[str] | None = None,
        urls: Sequence[str] | None = None,
        folder_titles: Sequence[str] | None = None,
    ) -> int:
        self.ensure_ready()
        normalized_titles = {normalize_text(title) for title in (titles or []) if normalize_text(title)}
        normalized_urls = {normalize_url(url) for url in (urls or []) if normalize_url(url)}
        normalized_folder_titles = {
            normalize_text(title) for title in (folder_titles or []) if normalize_text(title)
        }
        if not normalized_titles and not normalized_urls and not normalized_folder_titles:
            return 0

        with self._connect_writable(self.bookmarks_db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, parent, type, title, url, deleted, order_index, num_children, special_id
                FROM bookmarks
                WHERE deleted = 0
                ORDER BY id ASC
                """
            ).fetchall()

            records = [
                SafariBookmarkRecord(
                    rowid=int(row["id"]),
                    parent=int(row["parent"]) if row["parent"] is not None else None,
                    record_type=int(row["type"] or 0),
                    title=normalize_text(row["title"]),
                    url=normalize_url(row["url"]),
                    deleted=bool(row["deleted"]),
                    order_index=int(row["order_index"] or 0),
                    num_children=int(row["num_children"] or 0),
                    special_id=int(row["special_id"] or 0),
                )
                for row in rows
            ]
            id_to_record = {record.rowid: record for record in records}
            children_by_parent: dict[int, list[int]] = {}
            for record in records:
                if record.parent is None:
                    continue
                children_by_parent.setdefault(record.parent, []).append(record.rowid)

            target_ids: set[int] = set()

            def add_descendants(rowid: int) -> None:
                if rowid in target_ids:
                    return
                target_ids.add(rowid)
                for child_id in children_by_parent.get(rowid, []):
                    add_descendants(child_id)

            for record in records:
                if record.rowid in {0, 1, 2}:
                    continue
                if record.is_folder and record.title in normalized_folder_titles:
                    add_descendants(record.rowid)
                    continue
                if record.title in normalized_titles or record.url in normalized_urls:
                    add_descendants(record.rowid if record.is_folder else record.rowid)

            if not target_ids:
                return 0

            ordered_ids = sorted(
                target_ids,
                key=lambda rowid: self._bookmark_depth(rowid, id_to_record),
                reverse=True,
            )
            for rowid in ordered_ids:
                conn.execute("DELETE FROM bookmarks WHERE id = ?", (rowid,))

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
            conn.commit()
            return len(target_ids)

    def purge_tabs(
        self,
        *,
        urls: Sequence[str] | None = None,
        purge_all: bool = False,
    ) -> int:
        self.ensure_ready()
        normalized_urls = {normalize_url(url) for url in (urls or []) if normalize_url(url)}
        return self._purge_safari_tabs_db(urls=normalized_urls, purge_all=purge_all)

    def _purge_safari_tabs_db(self, *, urls: set[str], purge_all: bool) -> int:
        if not self.safari_tabs_db_path.exists():
            return 0

        with self._connect_writable(self.safari_tabs_db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not self._table_exists(conn, "bookmarks"):
                return 0

            if purge_all:
                target_rowids = [
                    int(row["id"])
                    for row in conn.execute(
                        """
                        SELECT id
                        FROM bookmarks
                        WHERE type = 0
                          AND deleted = 0
                          AND date_closed IS NULL
                        """
                    ).fetchall()
                ]
            elif urls:
                rows = conn.execute(
                    """
                    SELECT id, url
                    FROM bookmarks
                    WHERE type = 0
                      AND deleted = 0
                      AND date_closed IS NULL
                    """
                ).fetchall()
                target_rowids = [
                    int(row["id"])
                    for row in rows
                    if normalize_url(row["url"]) in urls
                ]
            else:
                return 0

            if not target_rowids:
                return 0

            placeholders = ",".join("?" for _ in target_rowids)
            conn.execute(f"DELETE FROM bookmarks WHERE id IN ({placeholders})", target_rowids)

            if self._table_exists(conn, "windows_tab_groups"):
                conn.execute(
                    f"""
                    UPDATE windows_tab_groups
                    SET active_tab_id = NULL
                    WHERE active_tab_id IN ({placeholders})
                    """,
                    target_rowids,
                )

            if self._table_exists(conn, "bookmarks"):
                conn.execute(
                    """
                    UPDATE bookmarks
                    SET num_children = (
                        SELECT COUNT(*)
                        FROM bookmarks child
                        WHERE child.parent = bookmarks.id
                          AND child.deleted = 0
                          AND child.date_closed IS NULL
                    )
                    WHERE type = 1
                    """
                )
            conn.commit()
            return len(target_rowids)

    def bookmark_matches_spec(
        self,
        record: SafariBookmarkRecord,
        spec: SafariBookmarkSpec,
        id_to_record: Mapping[int, SafariBookmarkRecord],
    ) -> bool:
        if spec.is_folder and not record.is_folder:
            return False
        if spec.title and record.title != spec.title:
            return False
        if spec.url and record.url != spec.url:
            return False
        if spec.parent_title:
            parent_title = self.parent_title_for_bookmark(record, id_to_record)
            if parent_title != spec.parent_title:
                return False
        return True

    def tab_matches_spec(self, record: SafariTabRecord, spec: SafariTabSpec) -> bool:
        record_url = record.user_visible_url or record.url
        if spec.url and record_url != spec.url:
            return False
        if spec.title and record.title != spec.title:
            return False
        return True

    def parent_title_for_bookmark(
        self,
        record: SafariBookmarkRecord,
        id_to_record: Mapping[int, SafariBookmarkRecord],
    ) -> str:
        if record.parent is None:
            return ""
        parent = id_to_record.get(record.parent)
        return parent.title if parent else ""

    def latest_tab(self) -> SafariTabRecord | None:
        tabs = self.list_tabs()
        return tabs[0] if tabs else None

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _bookmark_depth(
        rowid: int,
        id_to_record: Mapping[int, SafariBookmarkRecord],
    ) -> int:
        depth = 0
        current = id_to_record.get(rowid)
        while current and current.parent is not None and current.parent in id_to_record:
            depth += 1
            current = id_to_record.get(current.parent)
        return depth

    @contextmanager
    def _snapshot_db_path(self, db_path: Path) -> Iterator[Path]:
        with tempfile.TemporaryDirectory(prefix="ios_safari_db_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            snapshot_path = tmp_root / db_path.name
            for suffix in ("", "-wal", "-shm"):
                source = Path(f"{db_path}{suffix}")
                if source.exists():
                    shutil.copy2(source, tmp_root / source.name)
            yield snapshot_path

    @staticmethod
    def _connect_writable(db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
