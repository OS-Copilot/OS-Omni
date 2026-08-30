"""Helpers for resolving Linux oracle task specs and their base tasks."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


_REPO_ROOT = Path(__file__).resolve().parents[3]
_TASK_ROOT = _REPO_ROOT / "tasks" / "linux"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - mirrored by task loading behavior
        raise ImportError(
            f"Loading YAML task files requires PyYAML. Missing dependency while reading: {path}"
        ) from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Task file must contain an object: {path}")
    return data


@lru_cache(maxsize=1)
def _task_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in sorted(_TASK_ROOT.rglob("*.yaml")):
        try:
            data = _load_yaml(path)
        except Exception:
            continue
        task_id = str(data.get("task_id") or "").strip()
        if task_id:
            index[task_id] = path
    return index


def load_task_spec_from_path(path: str | Path) -> dict[str, Any]:
    return _load_yaml(Path(path).resolve())


def find_task_path(task_id: str) -> Optional[Path]:
    return _task_index().get(str(task_id or "").strip())


def load_task_spec_by_id(task_id: str) -> dict[str, Any]:
    path = find_task_path(task_id)
    if path is None:
        raise FileNotFoundError(f"Could not find task file for task_id={task_id!r}")
    return load_task_spec_from_path(path)


def derive_base_task_id(oracle_spec: dict[str, Any]) -> Optional[str]:
    metadata = oracle_spec.get("metadata")
    if isinstance(metadata, dict):
        explicit = str(metadata.get("oracle_for") or "").strip()
        if explicit and find_task_path(explicit) is not None:
            return explicit

    task_id = str(oracle_spec.get("task_id") or "").strip()
    if not task_id:
        return None
    derived = task_id.replace(".oracle.", ".", 1)
    if derived != task_id and find_task_path(derived) is not None:
        return derived
    return None


def load_oracle_and_base_specs(task_id: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    oracle_spec = load_task_spec_by_id(task_id)
    base_task_id = derive_base_task_id(oracle_spec)
    if not base_task_id:
        return oracle_spec, None
    return oracle_spec, load_task_spec_by_id(base_task_id)
