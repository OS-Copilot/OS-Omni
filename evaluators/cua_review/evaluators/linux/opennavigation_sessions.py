"""Session-level verifier for the OpenNavigation route-review tasks (web build).

The web build keeps navigation sessions only in page memory, so the route
review is judged from the event log the task initializer records in the page
(evaluators.cua_review.platforms.linux.opennavigation_events). Each pair of
start/end events is one navigation session, carrying the destination and travel
mode the application held when navigation started, plus the overlay buttons
pressed during it.

Parameters:
  expected_sessions: list of {destination, mode, overview: bool, voice: bool}
  ordered: when true the expected sessions must occur in this order (other
           sessions may come in between)
  forbidden_terms: terms that must not appear in any session destination
  min_trajectory_records: optional minimum number of trajectory records
"""

from __future__ import annotations

from typing import Any, Mapping

from evaluators.cua_review.core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.cua_review.platforms.linux.opennavigation_events import DEFAULT_DEVTOOLS_PORT, read_events

VOICE_LABELS = {"Voice", "Mute", "Unmute"}


def sessions_from_events(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in events:
        action = event.get("action")
        if action == "start":
            if current is not None:
                sessions.append(current)
            current = {"destination": event.get("destination"), "origin": event.get("origin"),
                       "mode": event.get("mode"), "clicks": [], "ended": False}
        elif action == "click" and current is not None:
            current["clicks"].append(event.get("label"))
        elif action == "end" and current is not None:
            current["ended"] = True
            sessions.append(current)
            current = None
    if current is not None:
        sessions.append(current)
    return sessions


def _matches(expected: Mapping[str, Any], session: Mapping[str, Any]) -> bool:
    if str(session.get("destination") or "") != str(expected.get("destination") or ""):
        return False
    if str(session.get("mode") or "").lower() != str(expected.get("mode") or "").lower():
        return False
    if expected.get("origin") and str(session.get("origin") or "") != str(expected["origin"]):
        return False
    if not session.get("ended"):
        return False
    clicks = set(session.get("clicks") or [])
    if expected.get("overview") and "Overview" not in clicks:
        return False
    if expected.get("voice") and not (clicks & VOICE_LABELS):
        return False
    return True


def _trajectory_records(context: Mapping[str, Any]) -> int | None:
    path = context.get("trajectory_path")
    if not path:
        return None
    try:
        with open(str(path), encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return None


class OpenNavigationSessionEvaluator(BaseEvaluator):
    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        expected = [dict(item) for item in params.get("expected_sessions") or []]
        if not expected:
            return EvalResult(status=EvalStatus.FAIL, message="no expected navigation sessions declared")
        port = int(params.get("devtools_port", DEFAULT_DEVTOOLS_PORT) or DEFAULT_DEVTOOLS_PORT)
        reading = read_events(context.get("controller"), port=port)
        pages = [page for page in reading.get("pages") or [] if page.get("recorder") or page.get("events")]
        events = [event for page in pages for event in page.get("events") or []]
        events.sort(key=lambda event: event.get("t") or 0)
        sessions = sessions_from_events(events)
        # The recorder must still be live at the end: a page without it lost events after a reload.
        live = any(page.get("recorder") for page in pages)
        checks: list[dict[str, Any]] = [{"check_id": "recorder", "passed": live, "errors": reading.get("errors")}]

        if params.get("ordered", True):
            position = 0
            for index, item in enumerate(expected, start=1):
                found = next((i for i in range(position, len(sessions)) if _matches(item, sessions[i])), None)
                checks.append({"check_id": "session.%d" % index, "expected": item, "passed": found is not None,
                               "matched": found})
                if found is not None:
                    position = found + 1
        else:
            used: set[int] = set()
            for index, item in enumerate(expected, start=1):
                found = next((i for i, s in enumerate(sessions) if i not in used and _matches(item, s)), None)
                if found is not None:
                    used.add(found)
                checks.append({"check_id": "session.%d" % index, "expected": item, "passed": found is not None,
                               "matched": found})

        for term in params.get("forbidden_terms") or []:
            hit = [s.get("destination") for s in sessions if str(term).lower() in str(s.get("destination") or "").lower()]
            checks.append({"check_id": "forbidden:%s" % term, "passed": not hit, "observed": hit})

        minimum = params.get("min_trajectory_records")
        if minimum:
            count = _trajectory_records(context)
            checks.append({"check_id": "trajectory_records", "expected": int(minimum), "observed": count,
                           "passed": count is not None and count >= int(minimum)})

        failed = [check["check_id"] for check in checks if not check["passed"]]
        metadata = {"checks": checks, "failures": failed, "sessions": sessions, "event_count": len(events)}
        if not live:
            return EvalResult(status=EvalStatus.ERROR,
                              message="OpenNavigation recorder is not active; the event log is incomplete",
                              metadata=metadata)
        if failed:
            return EvalResult(status=EvalStatus.FAIL,
                              message="OpenNavigation route review incomplete: " + ", ".join(failed[:10]),
                              metadata=metadata)
        return EvalResult(status=EvalStatus.PASS, message="OpenNavigation navigation sessions verified", metadata=metadata)
