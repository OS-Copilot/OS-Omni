"""Read-only state evaluator for the OpenZotero ToolBench-X reliability review (web build).

The imported OpenZoteroEvidenceEvaluator matched the required strings anywhere in
files or UI text, so duplicate items or collections still passed, although the task
forbids adding, deleting or modifying other items and its verifier rules make the
persisted library state authoritative. This evaluator reads that state.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from evaluators.cua_review.core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.cua_review.platforms.linux.local_storage import LOCAL_STORAGE_SOURCE

TASK_ID = "linux.openzotero.toolbenchx_reliability_review_snapshot2"
PAPER_TITLE = "Beyond Function Calling: Benchmarking Tool-Using Agents under Tool-Environment Unreliability"
LOG_TITLE = "Tool Hazard Reading Log"
COLLECTION = "Agent Reliability Review"
PAPER_NOTE = "ToolBench-X reliability hazards reviewed."
LOG_ABSTRACT = "Companion log for ToolBench-X reliability reading."
DEFAULT_PROFILE = "/home/user/.config/google-chrome/Default/Local Storage/leveldb"


def read_script(profile: str) -> str:
    return LOCAL_STORAGE_SOURCE + r'''
_h = replay_history(%s, "openzotero.localState.v1")
_state = {}
for _row in _h["versions"][-1:]:
    try:
        _state = json.loads(_row.get("text") or "{}")
    except ValueError:
        _state = {}
print(json.dumps({"state": _state, "version_count": len(_h["versions"]), "sources": _h["sources"], "errors": _h["errors"]}, ensure_ascii=False))
''' % json.dumps(profile)


def other_references_digest(references: list[Mapping[str, Any]]) -> tuple[int, str]:
    """Count and digest of every reference except the edited paper and the new log item."""
    others = sorted((dict(row) for row in references if row.get("title") not in (PAPER_TITLE, LOG_TITLE)),
                    key=lambda row: str(row.get("id")))
    blob = json.dumps(others, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return len(others), hashlib.sha256(blob.encode()).hexdigest()


def evaluate_state(state: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    collections = [row for row in state.get("collections") or [] if isinstance(row, Mapping)]
    references = [row for row in state.get("references") or [] if isinstance(row, Mapping)]
    names = {str(row.get("id")): row.get("name") for row in collections}
    names.setdefault("library", "My Library")
    checks: list[dict[str, Any]] = []

    def add(check_id: str, expected: Any, actual: Any) -> None:
        checks.append({"check_id": check_id, "expected": expected, "actual": actual, "passed": expected == actual})

    targets = [row for row in collections if row.get("name") == COLLECTION]
    add("collection", {"count": 1, "parent": "My Library"},
        {"count": len(targets), "parent": names.get(str((targets[0] if targets else {}).get("parentId")))})
    target_id = str(targets[0].get("id")) if len(targets) == 1 else None

    papers = [row for row in references if row.get("title") == PAPER_TITLE]
    paper = papers[0] if len(papers) == 1 else {}
    add("paper", {"count": 1, "status": "In Review", "tool_reliability_tags": 1, "notes": PAPER_NOTE, "in_collection": True},
        {"count": len(papers), "status": paper.get("status"), "tool_reliability_tags": list(paper.get("tags") or []).count("tool-reliability"),
         "notes": paper.get("notes"), "in_collection": target_id is not None and str(paper.get("collectionId")) == target_id})

    logs = [row for row in references if row.get("title") == LOG_TITLE]
    log = logs[0] if len(logs) == 1 else {}
    add("log_item", {"count": 1, "type": "Report", "creators": ["Maya Chen"], "year": "2026", "in_collection": True,
                     "tags": ["notes", "tool-reliability"], "abstract_has_text": True},
        {"count": len(logs), "type": log.get("type"), "creators": list(log.get("creators") or []), "year": str(log.get("year") or ""),
         "in_collection": target_id is not None and str(log.get("collectionId")) == target_id,
         "tags": sorted(log.get("tags") or []), "abstract_has_text": LOG_ABSTRACT in str(log.get("abstract") or "")})

    count, digest = other_references_digest(references)
    add("other_references_unchanged", {"count": int(params["baseline_other_count"]), "sha256": str(params["baseline_other_sha256"])},
        {"count": count, "sha256": digest})

    failures = [check["check_id"] for check in checks if not check["passed"]]
    return {"checks": checks, "failures": failures}


class OpenZoteroToolbenchxReliabilityReviewEvaluator(BaseEvaluator):
    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="the stored library document is not readable")
        observed: dict[str, Any] = {}
        for _round in range(2):
            try:
                raw = controller.run_python_script(read_script(str(params.get("profile_dir") or DEFAULT_PROFILE)),
                                                   timeout=int(params.get("timeout", 60)))
                text = str(raw.get("stdout") or raw.get("output") or "").strip()
                if text:
                    observed = json.loads(text.splitlines()[-1])
                    break
            except Exception:
                observed = {}
        state = observed.get("state") if isinstance(observed.get("state"), Mapping) else {}
        if not state:
            return EvalResult(status=EvalStatus.ERROR, message="the stored library document is not readable",
                              metadata={"source_errors": observed.get("errors")})
        verdict = evaluate_state(state, params)
        verdict.update({"task_id": TASK_ID, "history_sources": observed.get("sources") or [],
                        "history_version_count": observed.get("version_count") or 0, "source_errors": observed.get("errors") or []})
        if verdict["failures"]:
            return EvalResult(status=EvalStatus.FAIL, message="OpenZotero ToolBench-X mismatches: " + ", ".join(verdict["failures"]),
                              metadata=verdict)
        return EvalResult(status=EvalStatus.PASS, message="OpenZotero ToolBench-X review state verified", metadata=verdict)
