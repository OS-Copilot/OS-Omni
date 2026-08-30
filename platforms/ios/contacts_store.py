"""Helpers for reading and seeding iOS Simulator Contacts data."""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PHONE_PROPERTY_ID = 3
EMAIL_PROPERTY_ID = 4
DEFAULT_PHONE_LABEL_ID = 3
DEFAULT_EMAIL_LABEL_ID = 2


@dataclass(frozen=True)
class IOSContactSpec:
    first_name: str
    last_name: str
    organization: str = ""
    note: str = ""
    phones: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()

    @property
    def full_name(self) -> str:
        joined = " ".join(part for part in (self.first_name, self.last_name) if part).strip()
        return joined or self.organization


@dataclass(frozen=True)
class IOSContactRecord:
    rowid: int
    first_name: str
    last_name: str
    organization: str
    note: str
    phones: tuple[str, ...]
    emails: tuple[str, ...]
    guid: str

    @property
    def full_name(self) -> str:
        joined = " ".join(part for part in (self.first_name, self.last_name) if part).strip()
        return joined or self.organization


def contacts_db_path_for_udid(udid: str) -> Path:
    resolved_udid = str(udid or "").strip()
    if not resolved_udid:
        raise ValueError("Simulator UDID is required")
    return (
        Path.home()
        / "Library"
        / "Developer"
        / "CoreSimulator"
        / "Devices"
        / resolved_udid
        / "data"
        / "Library"
        / "AddressBook"
        / "AddressBook.sqlitedb"
    )


def coerce_contact_specs(raw: Any) -> list[IOSContactSpec]:
    if not isinstance(raw, list):
        return []

    specs: list[IOSContactSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        first_name, last_name = _coerce_name_parts(item)
        organization = _normalize_text(item.get("organization"))
        note = _normalize_text(item.get("note"))
        phones = _coerce_phone_values(item)
        emails = _coerce_email_values(item)

        if not any((first_name, last_name, organization)):
            continue

        specs.append(
            IOSContactSpec(
                first_name=first_name,
                last_name=last_name,
                organization=organization,
                note=note,
                phones=phones,
                emails=emails,
            )
        )
    return specs


class IOSContactsStore:
    """Read and mutate the iOS Simulator contacts database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()

    @classmethod
    def from_simulator(cls, udid: str) -> "IOSContactsStore":
        return cls(contacts_db_path_for_udid(udid))

    def list_contacts(self) -> list[IOSContactRecord]:
        with self._connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.ROWID,
                    COALESCE(p.First, ''),
                    COALESCE(p.Last, ''),
                    COALESCE(p.Organization, ''),
                    COALESCE(p.Note, ''),
                    COALESCE(p.guid, ''),
                    mv.property,
                    COALESCE(mv.value, '')
                FROM ABPerson p
                LEFT JOIN ABMultiValue mv ON mv.record_id = p.ROWID
                ORDER BY p.ROWID ASC, mv.property ASC, mv.identifier ASC, mv.UID ASC
                """
            ).fetchall()

        records_by_rowid: dict[int, dict[str, Any]] = {}
        for row in rows:
            rowid = int(row[0])
            entry = records_by_rowid.setdefault(
                rowid,
                {
                    "rowid": rowid,
                    "first_name": str(row[1] or "").strip(),
                    "last_name": str(row[2] or "").strip(),
                    "organization": str(row[3] or "").strip(),
                    "note": str(row[4] or "").strip(),
                    "guid": str(row[5] or "").strip(),
                    "phones": [],
                    "emails": [],
                },
            )
            property_id = row[6]
            value = str(row[7] or "").strip()
            if not value:
                continue
            if property_id == PHONE_PROPERTY_ID:
                entry["phones"].append(value)
            elif property_id == EMAIL_PROPERTY_ID:
                entry["emails"].append(value)

        records: list[IOSContactRecord] = []
        for rowid in sorted(records_by_rowid):
            item = records_by_rowid[rowid]
            records.append(
                IOSContactRecord(
                    rowid=rowid,
                    first_name=item["first_name"],
                    last_name=item["last_name"],
                    organization=item["organization"],
                    note=item["note"],
                    phones=tuple(item["phones"]),
                    emails=tuple(item["emails"]),
                    guid=item["guid"],
                )
            )
        return records

    def purge_all_contacts(self) -> int:
        with self._connect_writable() as conn:
            rowids = [int(row[0]) for row in conn.execute("SELECT ROWID FROM ABPerson").fetchall()]
            deleted = self._delete_contacts_by_rowid(conn, rowids)
            conn.commit()
            return deleted

    def purge_matching_contacts(self, specs: Sequence[IOSContactSpec] | Sequence[Mapping[str, Any]]) -> int:
        resolved_specs = self._coerce_seed_contacts(specs)
        if not resolved_specs:
            return 0

        existing = self.list_contacts()
        matched_rowids = [
            record.rowid
            for record in existing
            if any(self.contact_matches_spec(record, spec) for spec in resolved_specs)
        ]
        with self._connect_writable() as conn:
            deleted = self._delete_contacts_by_rowid(conn, matched_rowids)
            conn.commit()
            return deleted

    def seed_contacts(self, contacts: Sequence[IOSContactSpec] | Sequence[Mapping[str, Any]]) -> list[int]:
        resolved_contacts = self._coerce_seed_contacts(contacts)
        if not resolved_contacts:
            return []

        inserted_rowids: list[int] = []
        with self._connect_writable() as conn:
            now_ts = int(time.time())
            for spec in resolved_contacts:
                first_sort = spec.first_name or spec.organization or spec.last_name
                last_sort = spec.last_name or spec.organization or spec.first_name
                first_section = self._sort_section(first_sort)
                last_section = self._sort_section(last_sort)

                cursor = conn.execute(
                    """
                    INSERT INTO ABPerson (
                        First,
                        Last,
                        Organization,
                        Note,
                        Kind,
                        CreationDate,
                        ModificationDate,
                        StoreID,
                        FirstSort,
                        LastSort,
                        FirstSortSection,
                        LastSortSection,
                        FirstSortLanguageIndex,
                        LastSortLanguageIndex,
                        PersonLink,
                        IsPreferredName
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spec.first_name,
                        spec.last_name,
                        spec.organization,
                        spec.note,
                        0,
                        now_ts,
                        now_ts,
                        0,
                        first_sort,
                        last_sort,
                        first_section,
                        last_section,
                        0,
                        0,
                        -1,
                        1,
                    ),
                )
                person_rowid = int(cursor.lastrowid)
                inserted_rowids.append(person_rowid)

                for index, phone in enumerate(spec.phones):
                    conn.execute(
                        """
                        INSERT INTO ABMultiValue (record_id, property, identifier, label, value)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            person_rowid,
                            PHONE_PROPERTY_ID,
                            index,
                            DEFAULT_PHONE_LABEL_ID,
                            phone,
                        ),
                    )
                for index, email in enumerate(spec.emails):
                    conn.execute(
                        """
                        INSERT INTO ABMultiValue (record_id, property, identifier, label, value)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            person_rowid,
                            EMAIL_PROPERTY_ID,
                            index,
                            DEFAULT_EMAIL_LABEL_ID,
                            email,
                        ),
                    )

            conn.commit()

        return inserted_rowids

    def assert_state(self, assert_spec: Mapping[str, Any]) -> dict[str, Any]:
        present_contacts = self._coerce_seed_contacts(assert_spec.get("present_contacts"))
        absent_contacts = self._coerce_seed_contacts(assert_spec.get("absent_contacts"))
        exact_count = _coerce_int(assert_spec.get("exact_count"))

        if not present_contacts and not absent_contacts and exact_count is None:
            raise ValueError("Contacts assert_state requires present_contacts, absent_contacts, or exact_count")

        records = self.list_contacts()
        failures: list[str] = []

        for spec in present_contacts:
            if not any(self.contact_matches_spec(record, spec) for record in records):
                failures.append(f"Missing contact: {self._describe_spec(spec)}")

        for spec in absent_contacts:
            if any(self.contact_matches_spec(record, spec) for record in records):
                failures.append(f"Unexpected contact still present: {self._describe_spec(spec)}")

        if exact_count is not None and len(records) != exact_count:
            failures.append(f"Expected exactly {exact_count} contacts, found {len(records)}")

        summary = [
            {
                "full_name": record.full_name,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "organization": record.organization,
                "phones": list(record.phones),
                "emails": list(record.emails),
            }
            for record in records
        ]
        return {
            "status": "pass" if not failures else "fail",
            "failures": failures,
            "summary": summary,
        }

    @classmethod
    def contact_matches_spec(cls, record: IOSContactRecord, spec: IOSContactSpec) -> bool:
        if spec.first_name and cls._normalize_text(record.first_name) != cls._normalize_text(spec.first_name):
            return False
        if spec.last_name and cls._normalize_text(record.last_name) != cls._normalize_text(spec.last_name):
            return False
        if spec.organization and cls._normalize_text(record.organization) != cls._normalize_text(spec.organization):
            return False
        if spec.note and cls._normalize_text(record.note) != cls._normalize_text(spec.note):
            return False

        expected_phones = {cls._normalize_phone(value) for value in spec.phones if cls._normalize_phone(value)}
        observed_phones = {cls._normalize_phone(value) for value in record.phones if cls._normalize_phone(value)}
        if expected_phones and not expected_phones.issubset(observed_phones):
            return False

        expected_emails = {cls._normalize_email(value) for value in spec.emails if cls._normalize_email(value)}
        observed_emails = {cls._normalize_email(value) for value in record.emails if cls._normalize_email(value)}
        if expected_emails and not expected_emails.issubset(observed_emails):
            return False

        wanted_full_name = cls._normalize_text(spec.full_name)
        if wanted_full_name and cls._normalize_text(record.full_name) != wanted_full_name:
            return False
        return True

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _normalize_email(value: Any) -> str:
        return str(value or "").strip().casefold()

    @staticmethod
    def _normalize_phone(value: Any) -> str:
        text = str(value or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits or text.casefold()

    @staticmethod
    def _sort_section(value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return "#"
        first_char = normalized[0].upper()
        return first_char if first_char.isalpha() else "#"

    @staticmethod
    def _describe_spec(spec: IOSContactSpec) -> str:
        parts = [spec.full_name or "<unnamed>"]
        if spec.organization:
            parts.append(f"organization={spec.organization}")
        if spec.phones:
            parts.append(f"phones={list(spec.phones)}")
        if spec.emails:
            parts.append(f"emails={list(spec.emails)}")
        return ", ".join(parts)

    def _delete_contacts_by_rowid(self, conn: sqlite3.Connection, rowids: Sequence[int]) -> int:
        resolved_rowids = sorted({int(rowid) for rowid in rowids if int(rowid) > 0})
        if not resolved_rowids:
            return 0

        placeholders = ", ".join("?" for _ in resolved_rowids)
        multivalue_rowids = [
            int(row[0])
            for row in conn.execute(
                f"SELECT UID FROM ABMultiValue WHERE record_id IN ({placeholders})",
                resolved_rowids,
            ).fetchall()
        ]
        if multivalue_rowids:
            mv_placeholders = ", ".join("?" for _ in multivalue_rowids)
            conn.execute(
                f"DELETE FROM ABMultiValueEntry WHERE parent_id IN ({mv_placeholders})",
                multivalue_rowids,
            )
            conn.execute(
                f"DELETE FROM ABPhoneLastFour WHERE multivalue_id IN ({mv_placeholders})",
                multivalue_rowids,
            )
            conn.execute(
                f"DELETE FROM ABMultiValue WHERE UID IN ({mv_placeholders})",
                multivalue_rowids,
            )

        conn.execute(
            f"DELETE FROM ABPersonSearchKey WHERE person_id IN ({placeholders})",
            resolved_rowids,
        )
        conn.execute(
            f"DELETE FROM ABPersonChanges WHERE record IN ({placeholders})",
            resolved_rowids,
        )
        conn.execute(
            f"DELETE FROM ABPersonMultiValueDeletes WHERE record_id IN ({placeholders})",
            resolved_rowids,
        )
        conn.execute(
            f"DELETE FROM ABGroupMembers WHERE member_type = 0 AND member_id IN ({placeholders})",
            resolved_rowids,
        )
        self._delete_from_virtual_table(conn, "ABPersonFullTextSearch", resolved_rowids)
        self._delete_from_virtual_table(conn, "ABPersonSmartDialerFullTextSearch", resolved_rowids)
        cursor = conn.execute(
            f"DELETE FROM ABPerson WHERE ROWID IN ({placeholders})",
            resolved_rowids,
        )
        return int(cursor.rowcount or 0)

    @staticmethod
    def _delete_from_virtual_table(conn: sqlite3.Connection, table_name: str, rowids: Sequence[int]) -> None:
        if not rowids:
            return
        placeholders = ", ".join("?" for _ in rowids)
        try:
            conn.execute(f"DELETE FROM {table_name} WHERE docid IN ({placeholders})", rowids)
        except sqlite3.OperationalError:
            pass

    def _coerce_seed_contacts(
        self,
        raw: Sequence[IOSContactSpec] | Sequence[Mapping[str, Any]] | Any,
    ) -> list[IOSContactSpec]:
        if isinstance(raw, list) and raw and isinstance(raw[0], IOSContactSpec):
            return [item for item in raw if isinstance(item, IOSContactSpec)]
        return coerce_contact_specs(raw)

    def _connect_readonly(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _connect_writable(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.create_function("ab_generate_guid", 0, lambda: str(uuid.uuid4()).upper())
        conn.create_function("ab_update_value_from_trigger", 3, lambda value, _field, _rowid: value)
        return conn


def _coerce_name_parts(item: Mapping[str, Any]) -> tuple[str, str]:
    first_name = _normalize_text(
        item.get("first_name")
        or item.get("given_name")
        or item.get("first")
    )
    last_name = _normalize_text(
        item.get("last_name")
        or item.get("family_name")
        or item.get("last")
    )
    if first_name or last_name:
        return first_name, last_name

    full_name = _normalize_text(item.get("full_name") or item.get("name"))
    if not full_name:
        return "", ""
    if " " not in full_name:
        return full_name, ""
    first, last = full_name.split(" ", 1)
    return first.strip(), last.strip()


def _coerce_phone_values(item: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    raw_list = item.get("phones")
    if isinstance(raw_list, list):
        for entry in raw_list:
            if isinstance(entry, Mapping):
                text = _normalize_text(entry.get("value"))
            else:
                text = _normalize_text(entry)
            if text:
                values.append(text)
    else:
        text = _normalize_text(item.get("phone"))
        if text:
            values.append(text)
    return tuple(values)


def _coerce_email_values(item: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    raw_list = item.get("emails")
    if isinstance(raw_list, list):
        for entry in raw_list:
            if isinstance(entry, Mapping):
                text = str(entry.get("value") or "").strip()
            else:
                text = str(entry or "").strip()
            if text:
                values.append(text)
    else:
        text = str(item.get("email") or "").strip()
        if text:
            values.append(text)
    return tuple(values)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
