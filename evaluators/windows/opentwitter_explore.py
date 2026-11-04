"""What the Windows OpenTwitter build showed in an Explore topic stream, rebuilt from its evaluation state.

The trend cards of the shipped desktop build (C:\\OS-Omni\\Apps\\OpenTwitter\\resources\\app.asar)
open ``/api/feed?view=explore&q=<trend.query>``.  Its ``server.js`` ``filterPosts`` answers with
``state.posts`` in stored order (the seed newest first; a new post is unshifted to the front, a
deleted one is spliced out) and keeps a post when
``[text, topic, author.displayName, author.handle].join(" ").toLowerCase()`` contains the
lower-cased query.  ``/api/evaluation`` serves the same ``state.posts`` list, so the stream a user
saw at a ``timeline_view`` event is that list filtered the same way, minus the posts created after
the view, with the signed-in author's display name as it was then (``PATCH /api/profile`` renames
the author of every post the account owns, and the evaluation state only holds the final name).

Repost/like/save buttons toggle (``togglePostSet``), so an action that was already active when the
stream was opened is already done: clicking it again would undo it.  Such an action needs no new
event, only to be active in the final state.

No brief states an order between repost, like and save ("repost, like, and save the first post"
enumerates them), so they may happen in any order after the stream was opened.  Where a brief does
not ask for the stream to be opened, the stream as it stood at sign-in also identifies the first
post, so no view of it is required (``require_view=False``).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

ACTIONS = ("post_repost_toggled", "post_like_toggled", "post_bookmark_toggled")
ACTIVE_SET_KEYS = {
    "post_repost_toggled": "repostedPostIds",
    "post_like_toggled": "likedPostIds",
    "post_bookmark_toggled": "bookmarkedPostIds",
}
#: ``shared/seed-data.json`` users[alex].displayName in the shipped build: the name the signed-in
#: account had before any profile update in the episode.
SEED_DISPLAY_NAMES = {"alex": "Alex Chen"}


def _seq(row: Mapping[str, Any] | None) -> int:
    try:
        return int((row or {}).get("seq", -1))
    except (TypeError, ValueError):
        return -1


def _js_text(value: Any) -> str:
    # Array.prototype.join renders null/undefined as "".
    return "" if value is None else str(value)


def _author(post: Mapping[str, Any]) -> Mapping[str, Any]:
    author = post.get("author")
    return author if isinstance(author, Mapping) else {}


def display_name_at(
    handle: str,
    current_name: Any,
    events: Iterable[Mapping[str, Any]],
    seq: int,
    *,
    account_handle: str = "alex",
) -> Any:
    """The display name ``handle`` had at event ``seq`` (only the signed-in account can be renamed)."""
    if handle != account_handle:
        return current_name
    updates = sorted(
        (row for row in events if row.get("type") == "profile_updated" and row.get("displayName")),
        key=_seq,
    )
    earlier = [row for row in updates if _seq(row) < seq]
    if earlier:
        return earlier[-1].get("displayName")
    if updates:
        return SEED_DISPLAY_NAMES.get(handle, current_name)
    return current_name


def stream_at(
    posts: list[Mapping[str, Any]],
    events: list[Mapping[str, Any]],
    query: str,
    seq: int,
    *,
    account_handle: str = "alex",
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """The Explore results for ``query`` at event ``seq``, and the ids of matching posts deleted since.

    A post deleted after the view was on screen but is no longer in the state, so its place in
    the stream is unknown; callers treat a non-empty second value as an unreadable stream.
    """
    needle = str(query or "").strip().lower()
    created_after = {
        str(row.get("postId"))
        for row in events
        if row.get("type") == "post_created" and _seq(row) > seq
    }
    results: list[Mapping[str, Any]] = []
    for post in posts:
        post_id = str(post.get("id") or "")
        if not post_id or post_id in created_after:
            continue
        author = _author(post)
        handle = _js_text(author.get("handle"))
        name = display_name_at(handle, author.get("displayName"), events, seq, account_handle=account_handle)
        haystack = " ".join(_js_text(value) for value in (post.get("text"), post.get("topic"), name, handle))
        if not needle or needle in haystack.lower():
            results.append(post)
    # Only the signed-in account's own posts can be deleted.
    account_name = display_name_at(account_handle, None, events, seq, account_handle=account_handle)
    deleted = []
    for row in events:
        if row.get("type") != "post_deleted" or _seq(row) <= seq:
            continue
        if str(row.get("postId")) in created_after:
            continue  # published after ``seq`` too: it was not on screen then
        haystack = " ".join(_js_text(value) for value in (row.get("text"), row.get("topic"), account_name, account_handle))
        if needle and needle in haystack.lower():
            deleted.append(str(row.get("postId")))
    return results, deleted


def active_at(
    events: list[Mapping[str, Any]],
    post_id: str,
    action: str,
    seq: int,
    *,
    final_active: bool,
) -> bool:
    """Whether ``action`` was active on ``post_id`` just before event ``seq``.

    Every toggle event records the new state; before the first one the state is the seed's,
    which is the final state flipped once per toggle.
    """
    toggles = sorted(
        (row for row in events if row.get("type") == action and str(row.get("postId")) == post_id),
        key=_seq,
    )
    earlier = [row for row in toggles if _seq(row) < seq]
    if earlier:
        return earlier[-1].get("active") is True
    return bool(final_active) ^ (len(toggles) % 2 == 1)


def active_sets(state: Mapping[str, Any]) -> dict[str, set[str]]:
    return {
        action: {str(value) for value in (state.get(key) or []) if value}
        for action, key in ACTIVE_SET_KEYS.items()
    }


def _summary(row: Mapping[str, Any] | None) -> dict[str, Any]:
    keys = ("seq", "type", "timestamp", "postId", "authorHandle", "active", "text", "topic", "query", "view", "handle", "total", "id", "createdAt")
    return {key: row.get(key) for key in keys if key in (row or {})}


def _engage(
    target: Mapping[str, Any],
    view: Mapping[str, Any],
    *,
    all_events: list[Mapping[str, Any]],
    session_events: list[Mapping[str, Any]],
    final_sets: Mapping[str, set[str]],
) -> dict[str, Any]:
    """Every action not yet active on ``target`` at ``view``, activated after it in any order."""
    view_seq = _seq(view)
    target_id = str(target.get("id"))
    final_active = {action: target_id in final_sets.get(action, set()) for action in ACTIONS}
    already = {
        action: active_at(all_events, target_id, action, view_seq, final_active=final_active[action])
        for action in ACTIONS
    }
    chosen: list[Mapping[str, Any]] = []
    missing: list[str] = []
    for action in ACTIONS:
        if already[action]:
            continue
        event = next((
            row for row in session_events
            if _seq(row) > view_seq
            and row.get("type") == action
            and str(row.get("postId")) == target_id
            and row.get("active") is True
        ), None)
        if event is None:
            missing.append(action)
        else:
            chosen.append(event)
    chosen.sort(key=_seq)
    return {
        "passed": not missing and all(final_active.values()),
        "target_id": target_id,
        "first_post": _summary(target),
        "view": _summary(view),
        "already_active_at_view": already,
        "actions": [_summary(row) for row in chosen],
        "missing_actions": missing,
        "active_final": all(final_active.values()),
        "active_final_by_action": final_active,
    }


def first_post_engagement(
    *,
    posts: list[Mapping[str, Any]],
    all_events: list[Mapping[str, Any]],
    session_events: list[Mapping[str, Any]],
    query: str,
    final_sets: Mapping[str, set[str]],
    require_view: bool = True,
    account_handle: str = "alex",
) -> dict[str, Any]:
    """Repost, like and save of the first post of the ``query`` stream.

    For each Explore view of ``query`` (in order) the first post is the one the stream listed at
    that view.  When a post the agent itself published in the episode matches the query it is
    listed on top (newest first); "the first post in the topic stream" then also reads as the
    first post the stream held before the agent posted, so that post is accepted as well.  With
    ``require_view=False`` the stream as it stood at the first session event (the sign-in) is a
    reference too, so a brief that does not ask for the stream to be opened needs no view of it.

    A reference counts when every action not yet active on the post then is activated after it,
    in any order, and the post ends reposted, liked and saved.
    """
    views = [
        row for row in session_events
        if row.get("type") == "timeline_view"
        and str(row.get("view") or "").casefold() == "explore"
        and str(row.get("query") or "").strip().casefold() == str(query).strip().casefold()
    ]
    references = list(views)
    if not require_view and session_events:
        references.append({"seq": _seq(session_events[0]), "type": "session_start"})
    created_ids = {str(row.get("postId")) for row in all_events if row.get("type") == "post_created"}
    attempts: list[dict[str, Any]] = []
    for view in references:
        stream, deleted = stream_at(posts, all_events, query, _seq(view), account_handle=account_handle)
        if not stream or deleted:
            attempts.append({"view": _summary(view), "stream_total": len(stream), "deleted_matching_post_ids": deleted})
            continue
        candidates = [("first_listed", stream[0])]
        preexisting = next((post for post in stream if str(post.get("id")) not in created_ids), None)
        if preexisting is not None and preexisting is not stream[0]:
            candidates.append(("first_listed_not_published_by_agent", preexisting))
        for kind, target in candidates:
            result = _engage(target, view, all_events=all_events, session_events=session_events, final_sets=final_sets)
            result.update({"target_kind": kind, "stream_total": len(stream)})
            if result["passed"]:
                result["matching_view_count"] = len(views)
                return result
            attempts.append(result)
    first = next((row for row in attempts if row.get("first_post")), attempts[0] if attempts else {})
    return {
        "passed": False,
        "target_id": first.get("target_id"),
        "first_post": first.get("first_post") or {},
        "view": {},
        "actions": [],
        "missing_actions": first.get("missing_actions", list(ACTIONS)),
        "active_final": bool(first.get("active_final")),
        "matching_view_count": len(views),
        "attempts": attempts[:6],
    }


def stream_views_in_order(
    session_events: list[Mapping[str, Any]],
    queries: Iterable[str],
) -> list[Mapping[str, Any] | None]:
    """The earliest chain of Explore views that opens ``queries`` one after another.

    For a brief that says to open the streams "in that specific order".  Opening a stream early by
    mistake or reopening one does not matter: entry ``i`` is the first view of query ``i`` after
    the chosen view of the previous query (``None`` when there is none), so the views are in the
    stated order exactly when some view of each query follows a view of the one before.
    """
    chain: list[Mapping[str, Any] | None] = []
    cursor = -1
    for query in queries:
        view = next((
            row for row in session_events
            if row.get("type") == "timeline_view"
            and str(row.get("view") or "").casefold() == "explore"
            and str(row.get("query") or "").strip().casefold() == str(query).strip().casefold()
            and _seq(row) > cursor
        ), None)
        chain.append(view)
        if view is not None:
            cursor = _seq(view)
    return chain
