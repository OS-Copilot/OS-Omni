"""Helpers for seeding and validating Habit local state in an iOS simulator."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from platforms.ios.runtime_env.simulator_manager import get_app_data_container_path


DEFAULT_BUNDLE_ID = "co.nazariizomko.Habit"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class HabitSeedSpec:
    title: str
    motivation: str = ""
    color: str = "blue"


@dataclass(frozen=True)
class HabitAssertSpec:
    title: str
    motivation: str | None = None
    color: str | None = None


@dataclass(frozen=True)
class HabitRecord:
    row_id: int
    title: str
    motivation: str
    color: str
    creation_date: float
    id_hex: str
    completed_dates_size: int


def coerce_habit_specs(raw: Any) -> list[HabitSeedSpec]:
    if not isinstance(raw, list):
        return []

    specs: list[HabitSeedSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        specs.append(
            HabitSeedSpec(
                title=title,
                motivation=str(item.get("motivation") or "").strip(),
                color=str(item.get("color") or "blue").strip() or "blue",
            )
        )
    return specs


def coerce_habit_assert_specs(raw: Any) -> list[HabitAssertSpec]:
    if not isinstance(raw, list):
        return []

    specs: list[HabitAssertSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue

        title = str(item.get("title") or "").strip()
        if not title:
            continue

        motivation = None
        if "motivation" in item:
            motivation = str(item.get("motivation") or "").strip()

        color = None
        if "color" in item:
            color = str(item.get("color") or "").strip()

        specs.append(HabitAssertSpec(title=title, motivation=motivation, color=color))

    return specs


class IOSHabitStore:
    """Bridge into Habit's Core Data SQLite store for benchmark setup/evaluation."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        data_container_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.bundle_id = str(bundle_id or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        self.data_container_path = (
            Path(data_container_path).expanduser().resolve()
            if data_container_path is not None
            else self.db_path.parents[2]
        )

    @classmethod
    def from_simulator(
        cls,
        udid: str,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
    ) -> "IOSHabitStore":
        data_container = Path(get_app_data_container_path(udid, bundle_id)).expanduser().resolve()
        db_path = data_container / "Library" / "Application Support" / "Habit.sqlite"
        return cls(db_path, bundle_id=bundle_id, data_container_path=data_container)

    def reset_habits(
        self,
        habits: Sequence[HabitSeedSpec] | Sequence[Mapping[str, Any]] | None = None,
    ) -> list[HabitRecord]:
        resolved_habits = (
            list(habits)
            if habits and all(isinstance(item, HabitSeedSpec) for item in habits)
            else coerce_habit_specs(list(habits or []))
        )
        self._ensure_store_exists()

        with self._connect_writable() as conn:
            conn.execute("DELETE FROM ZHABIT")
            conn.execute("UPDATE Z_PRIMARYKEY SET Z_MAX = 0 WHERE Z_ENT = 1")

            for index, spec in enumerate(resolved_habits, start=1):
                conn.execute(
                    """
                    INSERT INTO ZHABIT(
                        Z_PK,
                        Z_ENT,
                        Z_OPT,
                        ZCREATIONDATE_,
                        ZCOLOR_,
                        ZMOTIVATION_,
                        ZTITLE_,
                        ZID_,
                        ZCOMPLETEDDATES_
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        index,
                        1,
                        1,
                        self._apple_timestamp(datetime.now(timezone.utc)),
                        spec.color,
                        spec.motivation,
                        spec.title,
                        sqlite3.Binary(uuid.uuid4().bytes),
                        None,
                    ),
                )

            conn.execute("UPDATE Z_PRIMARYKEY SET Z_MAX = ? WHERE Z_ENT = 1", (len(resolved_habits),))
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        return self.list_habits()

    def list_habits(self, titles: Sequence[str] | None = None) -> list[HabitRecord]:
        self._ensure_store_exists()
        with self._snapshot_db_path() as snapshot_db_path:
            conn = sqlite3.connect(snapshot_db_path)
            conn.row_factory = sqlite3.Row
            try:
                normalized_titles = [
                    self._normalize_text(item)
                    for item in (titles or [])
                    if self._normalize_text(item)
                ]
                where_clause = ""
                params: list[Any] = []
                if normalized_titles:
                    placeholders = ", ".join("?" for _ in normalized_titles)
                    where_clause = f"WHERE lower(trim(ZTITLE_)) IN ({placeholders})"
                    params.extend(normalized_titles)

                rows = conn.execute(
                    f"""
                    SELECT
                        Z_PK AS row_id,
                        COALESCE(ZTITLE_, '') AS title,
                        COALESCE(ZMOTIVATION_, '') AS motivation,
                        COALESCE(ZCOLOR_, '') AS color,
                        COALESCE(ZCREATIONDATE_, 0) AS creation_date,
                        hex(ZID_) AS id_hex,
                        length(ZCOMPLETEDDATES_) AS completed_dates_size
                    FROM ZHABIT
                    {where_clause}
                    ORDER BY Z_PK ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()

        return [
            HabitRecord(
                row_id=int(row["row_id"] or 0),
                title=str(row["title"] or "").strip(),
                motivation=str(row["motivation"] or "").strip(),
                color=str(row["color"] or "").strip(),
                creation_date=float(row["creation_date"] or 0.0),
                id_hex=str(row["id_hex"] or "").strip(),
                completed_dates_size=int(row["completed_dates_size"] or 0),
            )
            for row in rows
        ]

    def summary(self) -> dict[str, Any]:
        habits = self.list_habits()
        return {
            "habit_count": len(habits),
            "habits": [
                {
                    "title": record.title,
                    "motivation": record.motivation,
                    "color": record.color,
                    "completed_dates_size": record.completed_dates_size,
                }
                for record in habits
            ],
        }

    def assert_state(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        present_habits = coerce_habit_assert_specs(spec.get("present_habits"))
        absent_titles = self._coerce_text_list(spec.get("absent_titles"))
        exact_titles = self._coerce_text_list(spec.get("exact_titles"))
        habit_count_raw = spec.get("habit_count")
        habit_count = None if habit_count_raw is None else int(habit_count_raw)

        observed = self.list_habits()
        failures: list[str] = []

        if habit_count is not None and len(observed) != habit_count:
            failures.append(f"Expected habit_count={habit_count}, observed {len(observed)}")

        observed_titles = {self._normalize_text(record.title) for record in observed if record.title}
        observed_by_title: dict[str, list[HabitRecord]] = {}
        for record in observed:
            observed_by_title.setdefault(self._normalize_text(record.title), []).append(record)

        for expected in present_habits:
            matches = observed_by_title.get(self._normalize_text(expected.title), [])
            if not matches:
                failures.append(f"Missing habit titled '{expected.title}'")
                continue

            if expected.motivation is not None:
                normalized_motivation = self._normalize_motivation(expected.motivation)
                if not any(
                    self._normalize_motivation(candidate.motivation) == normalized_motivation
                    for candidate in matches
                ):
                    failures.append(
                        f"Habit '{expected.title}' motivation mismatch; "
                        f"expected '{expected.motivation}'"
                    )

            if expected.color is not None:
                normalized_color = self._normalize_text(expected.color)
                if not any(self._normalize_text(candidate.color) == normalized_color for candidate in matches):
                    failures.append(
                        f"Habit '{expected.title}' color mismatch; expected '{expected.color}'"
                    )

        for title in absent_titles:
            if self._normalize_text(title) in observed_titles:
                failures.append(f"Habit titled '{title}' should be absent")

        if exact_titles:
            wanted = sorted(self._normalize_text(title) for title in exact_titles)
            got = sorted(title for title in observed_titles if title)
            if wanted != got:
                failures.append(f"exact_titles mismatch; expected {wanted}, observed {got}")

        return {
            "status": "pass" if not failures else "fail",
            "failures": failures,
            "summary": self.summary(),
        }

    def clear_saved_state(self) -> None:
        candidates = [
            self.data_container_path
            / "Library"
            / "Saved Application State"
            / f"{self.bundle_id}.savedState",
            self.data_container_path
            / "Library"
            / "SplashBoard"
            / "Snapshots"
            / f"sceneID:{self.bundle_id}-default",
            self.data_container_path
            / "Library"
            / "SplashBoard"
            / "Snapshots"
            / f"{self.bundle_id} - {{DEFAULT GROUP}}",
        ]
        for candidate in candidates:
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)

    def _ensure_store_exists(self) -> None:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Habit SQLite store not found: {self.db_path}")

    def _connect_writable(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _snapshot_db_path(self):
        class _SnapshotContext:
            def __init__(self, store: "IOSHabitStore") -> None:
                self._store = store
                self._tmpdir = tempfile.TemporaryDirectory(prefix="ios_habit_snapshot_")

            def __enter__(self) -> str:
                snapshot_root = Path(self._tmpdir.name)
                base_name = self._store.db_path.name
                for candidate in self._store.db_path.parent.glob(f"{base_name}*"):
                    if candidate.is_file():
                        shutil.copy2(candidate, snapshot_root / candidate.name)
                return str(snapshot_root / base_name)

            def __exit__(self, exc_type, exc, tb) -> bool:
                self._tmpdir.cleanup()
                return False

        return _SnapshotContext(self)

    @staticmethod
    def _apple_timestamp(value: datetime) -> float:
        return (value.astimezone(timezone.utc) - APPLE_EPOCH).total_seconds()

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

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    @classmethod
    def _normalize_motivation(cls, value: Any) -> str:
        text = cls._normalize_text(value)
        if text.endswith("."):
            text = text[:-1].rstrip()
        return text
