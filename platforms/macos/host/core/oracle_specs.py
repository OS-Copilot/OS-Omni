"""Helpers for resolving macOS oracle task specs."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


_REPO_ROOT = Path(__file__).resolve().parents[4]
_TASK_ROOT = _REPO_ROOT / "tasks" / "v1" / "macos" / "oracle"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            f"Loading YAML oracle task files requires PyYAML. Missing dependency while reading: {path}"
        ) from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Oracle task file must contain an object: {path}")
    return data


@lru_cache(maxsize=1)
def _oracle_specs() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(_TASK_ROOT.rglob("*.yaml")):
        try:
            spec = _load_yaml(path)
        except Exception:
            continue
        spec["_source_path"] = str(path)
        items.append(spec)
    return items


def load_oracle_spec_from_path(path: str | Path) -> dict[str, Any]:
    spec = _load_yaml(Path(path).resolve())
    spec["_source_path"] = str(Path(path).resolve())
    return spec


def find_oracle_spec(
    *,
    task_id: str | None = None,
    message_text: str | None = None,
) -> Optional[dict[str, Any]]:
    normalized_task_id = str(task_id or "").strip()
    normalized_text = str(message_text or "").strip().lower()

    for spec in _oracle_specs():
        spec_task_id = str(spec.get("task_id") or "").strip()
        metadata = spec.get("metadata") if isinstance(spec.get("metadata"), dict) else {}
        oracle_for = str((metadata or {}).get("oracle_for") or "").strip()

        if normalized_task_id and normalized_task_id in {spec_task_id, oracle_for}:
            return dict(spec)

        if normalized_text:
            if spec_task_id and spec_task_id.lower() in normalized_text:
                return dict(spec)
            if oracle_for and oracle_for.lower() in normalized_text:
                return dict(spec)

    if not normalized_text:
        return None

    compact_text = " ".join(normalized_text.split())
    for spec in _oracle_specs():
        instruction = str(spec.get("instruction") or "").strip().lower()
        if not instruction:
            continue
        compact_instruction = " ".join(instruction.split())
        if compact_instruction and compact_instruction in compact_text:
            return dict(spec)

    return None
