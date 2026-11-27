"""Grade an iOS app's durable event record by what the English brief states.

Shared by the iOS evaluators that replay an app event log or persisted
timestamps (the ``durable_events_and_required_order`` check):

* business events (create, submit, toggle, save, place, review, ...) are
  compared as a multiset: every required one is present and no unexpected or
  duplicate one was recorded. Browsing (search, view, open, list, filter,
  navigation) is never counted unless the brief asks for it as a deliverable;
* only the orders the brief states with temporal language ("then", "after",
  "before", "following", "in this exact sequence", ...) or that are logically
  necessary (a recipient exists before a transfer to it, an order exists before
  its review) are enforced, as (before, after) pairs. Enumerations and record
  labels ("the first new post", "the second order") impose no order.

Same rule as the OpenBank 448872 / 086132 and OpenTwitter 451238 / 483271
evaluators, which implement it inline.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from itertools import permutations
from typing import Any, Callable, Hashable, Iterable, Mapping, Sequence, TypeVar

T = TypeVar("T")


def multiset_diff(
    expected: Iterable[Hashable],
    actual: Iterable[Hashable],
) -> tuple[list[Any], list[Any]]:
    """Return (missing, extra) between two multisets of business events.

    Both sides are iterated as event sequences (a Mapping is not read as counts).
    """
    wanted = Counter(list(expected))
    seen = Counter(list(actual))
    return list((wanted - seen).elements()), list((seen - wanted).elements())


def order_violations(
    sequence: Sequence[Hashable],
    pairs: Iterable[tuple[Hashable, Hashable]],
) -> list[list[Any]]:
    """Return the (before, after) pairs whose first occurrences are out of order.

    A pair with either side absent is not a violation here: a missing event is
    graded by the multiset comparison.
    """
    first: dict[Hashable, int] = {}
    for index, label in enumerate(sequence):
        first.setdefault(label, index)
    return [
        [before, after]
        for before, after in pairs
        if before in first and after in first and first[before] > first[after]
    ]


def time_order_violations(
    times: Mapping[str, Any],
    pairs: Iterable[tuple[str, str]],
) -> list[list[str]]:
    """Return the (before, after) pairs of named timestamps not strictly ordered.

    A missing timestamp on either side is a violation: the required order
    cannot be shown.
    """
    violations: list[list[str]] = []
    for before, after in pairs:
        left, right = times.get(before), times.get(after)
        if left is None or right is None or not left < right:
            violations.append([before, after])
    return violations


def best_assignment(
    candidates: Sequence[T],
    specs: Sequence[Any],
    grade: Callable[[T, Any], bool],
) -> list[T | None]:
    """Match records to specs by content rather than by creation order.

    Returns one candidate (or None) per spec. The assignment that satisfies the
    most specs wins; ties keep the given (chronological) order, so a record
    whose content matches no spec is still reported against its slot.
    """
    slots = len(specs)
    padded: list[T | None] = list(candidates[:slots]) + [None] * max(0, slots - len(candidates))
    if len(candidates) < 2 or slots < 2:
        return padded
    best = padded
    best_score = sum(1 for item, spec in zip(best, specs) if item is not None and grade(item, spec))
    for perm in permutations(range(len(candidates)), min(slots, len(candidates))):
        chosen: list[T | None] = [candidates[index] for index in perm]
        chosen += [None] * (slots - len(chosen))
        score = sum(1 for item, spec in zip(chosen, specs) if item is not None and grade(item, spec))
        if score > best_score:
            best, best_score = chosen, score
    return best


def align_by_key(
    items: Sequence[T],
    expected: Sequence[Any],
    *,
    item_key: Callable[[T], Hashable],
    expected_key: Callable[[Any], Hashable],
) -> list[T | None]:
    """Line items up with expected rows by key, ignoring their stored position.

    For lists whose order the brief does not state. Returns one item (or None)
    per expected row; unmatched items are appended after them so a cardinality
    check still sees them.
    """
    remaining = list(items)
    aligned: list[T | None] = []
    for row in expected:
        key = expected_key(row)
        match = next((item for item in remaining if item_key(item) == key), None)
        if match is not None:
            remaining.remove(match)
        aligned.append(match)
    return aligned + remaining


def single_record_transitions(
    flag_rows: Sequence[Sequence[bool]],
    *,
    history_truncated: bool,
    allow_idle_commits: bool,
    record_times: Sequence[datetime | None] | None = None,
) -> tuple[list[str], list[int | None]]:
    """Grade committed WAL states as single-record business transitions in any order.

    The brief states no order between the target records, so the history is a
    multiset of transitions: every record lands exactly once (never undone and
    never two in one commit, except in the first observable state when a
    checkpoint folded earlier commits into the main file) and the last commit
    holds all of them. A record that carries an app timestamp must agree with
    the commit in which it first appears (integrity, not a required order).
    """
    if not flag_rows:
        return ["committed WAL history is missing"], []
    width = len(flag_rows[0])
    reasons: list[str] = []
    first_commit: list[int | None] = [None] * width
    previous = (False,) * width
    for index, row in enumerate(flag_rows, start=1):
        flags = tuple(bool(value) for value in row)
        if any(old and not new for old, new in zip(previous, flags)):
            reasons.append(f"target state regressed at commit {index}")
        added = [position for position in range(width) if flags[position] and not previous[position]]
        for position in added:
            if first_commit[position] is None:
                first_commit[position] = index
        if len(added) > 1 and not (history_truncated and index == 1):
            reasons.append(f"commit {index} adds {len(added)} target records at once")
        if not added and not allow_idle_commits:
            reasons.append(f"commit {index} adds no target record")
        previous = flags
    if not all(previous):
        reasons.append("last committed WAL state does not contain every exact target record")
    stamped = [
        (first_commit[position], record_times[position])
        for position in range(width)
        if record_times is not None
        and position < len(record_times)
        and first_commit[position] is not None
        and record_times[position] is not None
    ]
    if any(
        earlier_commit < later_commit and not earlier_time < later_time  # type: ignore[operator]
        for earlier_commit, earlier_time in stamped
        for later_commit, later_time in stamped
    ):
        reasons.append("a record first committed later carries an earlier app timestamp")
    return reasons, first_commit
