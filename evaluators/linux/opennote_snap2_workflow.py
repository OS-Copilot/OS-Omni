"""Final-state checks for the Linux OpenNote snap_2 workflows (desk_cable_followup, home_food_profile).

OpenNote keeps one Local Storage document (``opennote.localState.v2``) holding the session, the users,
the notes, every note's comments and each account's ``following`` / ``likedNoteIds`` / ``savedNoteIds``
and notifications.  The document is decoded with the shared LevelDB reader (log records, sorted tables,
Snappy blocks, Chrome's value encodings) and the declared outcome is read from its fields:

* a seeded note is liked / saved when its id is in the signed-in account's liked / saved lists, and
  commented when its comment list holds the declared text by that account;
* a published note is a note of the signed-in account with the declared title, body, category,
  location and tags; OpenNote stores every cover (uploaded or "Use text cover") as a data:image URL;
* the author is followed when the account's ``following`` list holds the author's handle;
* alerts are read when none of the account's notifications is unread;
* profile fields are the account's user record.

The tasks' search strings are not graded: the briefs do not name what to search for.
"""

from __future__ import annotations

from typing import Any, Mapping

from evaluators.cua_review.core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.cua_review.evaluators.linux.opennote import read_opennote_state

__all__ = ["OpenNoteSnap2WorkflowEvaluator", "grade_state"]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _tag(value: Any) -> str:
    return _norm(str(value or "").lstrip("#"))


def _session_handle(state: Mapping[str, Any]) -> str:
    session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
    user = session.get("user") if isinstance(session.get("user"), Mapping) else {}
    return str(user.get("handle") or "")


def _users(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = state.get("users")
    if isinstance(rows, Mapping):
        rows = list(rows.values())
    return [dict(row) for row in (rows or []) if isinstance(row, Mapping)]


def _account_state(state: Mapping[str, Any], handle: str) -> dict[str, Any]:
    table = state.get("userState") if isinstance(state.get("userState"), Mapping) else {}
    row = table.get(handle)
    return dict(row) if isinstance(row, Mapping) else {}


def _notes_titled(state: Mapping[str, Any], title: str) -> list[dict[str, Any]]:
    wanted = _norm(title)
    return [dict(row) for row in (state.get("notes") or []) if isinstance(row, Mapping) and _norm(row.get("title")) == wanted]


def _comments(state: Mapping[str, Any], note_id: str) -> list[dict[str, Any]]:
    table = state.get("comments") if isinstance(state.get("comments"), Mapping) else {}
    return [dict(row) for row in (table.get(note_id) or []) if isinstance(row, Mapping)]


def grade_state(state: Mapping[str, Any], params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the checks for ``state`` (the decoded OpenNote document) against the task ``params``."""
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any = None, expected: Any = None) -> None:
        checks.append({"name": name, "passed": bool(passed), "observed": observed, "expected": expected})

    handle = _session_handle(state) or str(params.get("account_handle") or "lina")
    account = _account_state(state, handle)
    liked = {str(item) for item in account.get("likedNoteIds") or []}
    saved = {str(item) for item in account.get("savedNoteIds") or []}
    following = {str(item) for item in account.get("following") or []}

    def engagement(notes: list[dict[str, Any]]) -> dict[str, Any]:
        ids = [str(row.get("id") or "") for row in notes]
        return {"ids": ids, "liked": [i for i in ids if i in liked], "saved": [i for i in ids if i in saved]}

    for note in _as_list(params.get("existing_notes")):
        title = str((note or {}).get("title") or "") if isinstance(note, Mapping) else str(note)
        rows = _notes_titled(state, title)
        seen = engagement(rows)
        add("existing_note_present:" + title, bool(rows), seen["ids"], title)
        add("liked_note:" + title, bool(seen["liked"]), seen, title)
        add("saved_note:" + title, bool(seen["saved"]), seen, title)

    for comment in _as_list(params.get("comments")):
        if not isinstance(comment, Mapping):
            continue
        title = str(comment.get("note_title") or "")
        text = str(comment.get("text") or "")
        found = []
        for row in _notes_titled(state, title):
            for item in _comments(state, str(row.get("id") or "")):
                author = str(item.get("authorHandle") or handle)
                if author == handle and _norm(item.get("text")) == _norm(text):
                    found.append({"note_id": row.get("id"), "comment_id": item.get("id")})
        add("comment_on_note:" + title + ":" + text, bool(found), found, {"note_title": title, "text": text})

    for note in _as_list(params.get("created_notes")):
        if not isinstance(note, Mapping):
            continue
        title = str(note.get("title") or "")
        rows = [row for row in _notes_titled(state, title) if str(row.get("authorHandle") or "") == handle]
        add("created_note_present:" + title, bool(rows), [row.get("id") for row in rows], {"title": title, "author": handle})
        body = note.get("body")
        if body:
            add("created_note_body:" + title, any(_norm(body) in _norm(row.get("text") or row.get("body")) for row in rows),
                [row.get("text") for row in rows], body)
        for field in ("category", "location"):
            wanted = note.get(field)
            if wanted:
                add("created_note_%s:%s" % (field, title), any(_norm(row.get(field)) == _norm(wanted) for row in rows),
                    [row.get(field) for row in rows], wanted)
        for tag in _as_list(note.get("tags")):
            add("created_note_tag:%s:%s" % (title, tag),
                any(_tag(tag) in {_tag(item) for item in _as_list(row.get("tags"))} for row in rows),
                [row.get("tags") for row in rows], tag)
        if note.get("use_text_cover"):
            covers = [str(row.get("cover") or "")[:32] for row in rows]
            add("created_note_use_text_cover:" + title, any(cover.startswith("data:image/") for cover in covers), covers,
                "generated data:image cover")
        seen = engagement(rows)
        if note.get("liked"):
            add("liked_created_note:" + title, bool(seen["liked"]), seen, title)
        if note.get("saved"):
            add("saved_created_note:" + title, bool(seen["saved"]), seen, title)

    for follow in _as_list(params.get("expected_follows")):
        author = str(follow.get("author") or "") if isinstance(follow, Mapping) else str(follow)
        handles = {str(follow.get("handle"))} if isinstance(follow, Mapping) and follow.get("handle") else set()
        handles |= {str(row.get("handle")) for row in _users(state) if _norm(row.get("displayName")) == _norm(author)}
        add("followed_author:" + author, bool(handles & following), {"handles": sorted(handles), "followed": sorted(handles & following)}, author)

    if params.get("require_alerts_read"):
        table = state.get("userNotifications") if isinstance(state.get("userNotifications"), Mapping) else {}
        alerts = [row for row in (table.get(handle) or []) if isinstance(row, Mapping)]
        unread = [row.get("id") for row in alerts if row.get("read") is not True]
        add("alerts_marked_all_read", not unread, {"alerts": len(alerts), "unread": unread}, "no unread alerts")

    profile = next((row for row in _users(state) if str(row.get("handle") or "") == handle), {})
    for field in _as_list(params.get("profile_fields")):
        if not isinstance(field, Mapping):
            continue
        name = str(field.get("name") or "")
        add("profile_field:" + name, _norm(profile.get(name)) == _norm(field.get("value")), profile.get(name), field.get("value"))

    return checks


class OpenNoteSnap2WorkflowEvaluator(BaseEvaluator):
    """Grade the decoded OpenNote document against the declared notes, engagement, follows and alerts."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        state = read_opennote_state(context, params)
        if not state:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="the OpenNote document (opennote.localState.v2) is not stored",
                metadata={"passed": False, "checks": []},
            )
        checks = grade_state(state, params)
        failures = [check["name"] for check in checks if not check["passed"]]
        passed = bool(checks) and not failures
        metadata = {
            "passed": passed,
            "checks": checks,
            "failures": failures,
            "evidence": {
                "source": "opennote.localState.v2 (decoded Local Storage)",
                "account": _session_handle(state),
                "note_count": len(state.get("notes") or []),
                "search_queries_not_graded": _as_list(params.get("search_queries")),
            },
        }
        message = "OpenNote workflow checks passed" if passed else "OpenNote workflow checks failed: " + ", ".join(failures[:8])
        return EvalResult(status=EvalStatus.PASS if passed else EvalStatus.FAIL, message=message, metadata=metadata)

