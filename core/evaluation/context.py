"""Task-bound evaluator context shared by the platform runners."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


def _task_metadata(task: Any) -> Mapping[str, Any]:
    metadata = getattr(task, "metadata", None)
    if isinstance(metadata, Mapping):
        return metadata
    # The macOS runner's Task type keeps no metadata; read it from the TaskSpec.
    source = getattr(task, "source_file", None) or getattr(task, "source_path", None)
    if source and Path(source).is_file():
        raw = yaml.safe_load(Path(source).read_text(encoding="utf-8")) or {}
        if isinstance(raw.get("metadata"), Mapping):
            return raw["metadata"]
    return {}


def task_binding_context(task: Any) -> dict[str, Any]:
    """Identify the task an evaluator is judging.

    Reviewed evaluators bind themselves to the task they were written for: they
    compare ``task_id``, their original ``evaluator_id`` and the digest of the
    instruction they were written against.  Imported tasks give the model an
    English brief, so the source instruction is supplied here from the import
    provenance instead of the brief.
    """

    provenance = _task_metadata(task).get("cua_tasks_review")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    evaluation = getattr(task, "evaluation", None)
    return {
        "task": task,
        "task_id": getattr(task, "task_id", None) or getattr(task, "id", None),
        "evaluator_id": provenance.get("original_evaluator_id")
        or getattr(evaluation, "evaluator_id", None),
        "instruction": provenance.get("source_instruction")
        or getattr(task, "instruction", None)
        or getattr(task, "goal", None),
    }


def with_task_binding(context: Mapping[str, Any], task: Any) -> dict[str, Any]:
    """Add the task binding without overriding keys a runner already set."""

    merged = dict(context)
    for key, value in task_binding_context(task).items():
        merged.setdefault(key, value)
    return merged
