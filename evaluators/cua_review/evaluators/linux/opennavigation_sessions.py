"""Session-level verifier for the OpenNavigation route-review tasks (web build).

The web build keeps navigation sessions only in page memory, so the route
review is judged from the event log the task initializer records in the page
(evaluators.cua_review.platforms.linux.opennavigation_events). Each pair of
start/end events is one navigation session, carrying the destination and travel
mode the application held when navigation started, plus the overlay buttons
pressed during it.

Parameters:
  expected_sessions: list of {destination, mode, overview: bool, voice: bool}
           plus, where the instruction states an order:
             final: true                  this session comes after every other
                                          expected session ("a final seventh
                                          session", "the eighth and final")
             voice_before_overview: true  in this session the voice icon is used
                                          before the Overview is viewed
  ordered: when true the expected sessions must occur in this order (other
           sessions may come in between); when false each expected session is
           matched to its own recorded session in any order, and only the
           orders above are judged
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
    if expected.get("voice_before_overview"):
        ordered_clicks = list(session.get("clicks") or [])
        voice = [i for i, label in enumerate(ordered_clicks) if label in VOICE_LABELS]
        overview = [i for i, label in enumerate(ordered_clicks) if label == "Overview"]
        if not voice or not overview or min(voice) > max(overview):
            return False
    return True


def _max_matching(candidates: list[list[int]]) -> list[int | None]:
    """Maximum bipartite matching of expected sessions to recorded ones (Kuhn's algorithm)."""
    owner: dict[int, int] = {}

    def augment(k: int, seen: set[int]) -> bool:
        for index in candidates[k]:
            if index in seen:
                continue
            seen.add(index)
            if index not in owner or augment(owner[index], seen):
                owner[index] = k
                return True
        return False

    for k in range(len(candidates)):
        augment(k, set())
    matched: list[int | None] = [None] * len(candidates)
    for index, k in owner.items():
        matched[k] = index
    return matched


def assign_sessions(expected: list[Mapping[str, Any]], sessions: list[Mapping[str, Any]],
                    respect_final: bool = True) -> list[int | None]:
    """Match each expected session to its own recorded session, in any order.

    Returns the recorded index per expected session (``None`` where no match is
    left), choosing an assignment that matches the most expected sessions.  With
    ``respect_final`` an expected session marked ``final`` must be matched to a
    session recorded after every matched expected session that is not final.
    """
    candidates = [[i for i, session in enumerate(sessions) if _matches(item, session)] for item in expected]
    finals = {k for k, item in enumerate(expected) if item.get("final")} if respect_final else set()
    if not finals:
        return _max_matching(candidates)
    best: list[int | None] = [None] * len(expected)
    for boundary in range(len(sessions) + 1):
        # Sessions before the boundary serve the other expected sessions, the rest the final one(s).
        split = [
            [i for i in options if (i >= boundary) == (k in finals)]
            for k, options in enumerate(candidates)
        ]
        matched = _max_matching(split)
        if sum(i is not None for i in matched) > sum(i is not None for i in best):
            best = matched
    return best


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
    # Reads the live page over DevTools: keep the browser running for evaluation (no flush).
    REQUIRES_LIVE_BROWSER = True

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
            # Session ordinals in the briefs ("the first session", "the second ...")
            # are labels, not a required order; each expected session needs its
            # own recorded session.  Only an order the brief states is judged.
            matched = assign_sessions(expected, sessions, respect_final=False)
            for index, (item, found) in enumerate(zip(expected, matched), start=1):
                checks.append({"check_id": "session.%d" % index, "expected": item, "passed": found is not None,
                               "matched": found})
            if any(item.get("final") for item in expected) and all(found is not None for found in matched):
                ordered_match = assign_sessions(expected, sessions, respect_final=True)
                checks.append({
                    "check_id": "stated_order.final_session",
                    "expected": [index for index, item in enumerate(expected, start=1) if item.get("final")],
                    "passed": all(found is not None for found in ordered_match),
                    "matched": ordered_match,
                })

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
