from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any


DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_json_blob(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_datetime(value: Any) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in DATETIME_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def isoformat(value: Any) -> str | None:
    parsed = parse_datetime(value)
    return parsed.isoformat() if parsed else None


def unix_timestamp(value: Any) -> float:
    parsed = parse_datetime(value)
    if parsed:
        return parsed.timestamp()
    return 0.0


def stable_id(prefix: str, raw: str) -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def relative_path(path: Path | None, repo_root: Path) -> str | None:
    if not path:
        return None
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def resolve_path(value: Any, base_dir: Path) -> Path | None:
    if not value or not isinstance(value, str):
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def compact_text(value: Any, limit: int = 220) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    squashed = " ".join(text.split())
    if len(squashed) <= limit:
        return squashed
    return squashed[: limit - 1].rstrip() + "…"


def pick_first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}, ()):
            return value
    return None


def ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
