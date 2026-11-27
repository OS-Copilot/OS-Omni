"""OpenBank event helpers: the dispute route and the stated business-action orders."""

from typing import Any, Mapping, Sequence


def find_dispute_route(
    events: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, Mapping[str, Any] | None]:
    if not target:
        return None, None, None
    searches = [row for row in events if row.get("type") == "transactions_viewed"
                and row.get("q") == expected["query"] and int(row.get("total", 0)) > 0]
    details = [row for row in events if row.get("type") == "transaction_details_viewed"
               and row.get("transactionId") == target.get("transactionId")]
    submits = sorted(
        (row for row in events if row.get("type") == "transaction_dispute_submitted"
         and row.get("disputeId") == target.get("id")
         and row.get("transactionId") == target.get("transactionId")
         and row.get("reason") == expected["reason"]),
        key=lambda row: int(row.get("seq", -1)),
    )
    for submit in submits:
        for detail in sorted(details, key=lambda row: int(row.get("seq", -1)), reverse=True):
            if int(detail.get("seq", -1)) >= int(submit.get("seq", -1)):
                continue
            before = [row for row in searches if int(row.get("seq", -1)) < int(detail.get("seq", -1))]
            if before:
                return max(before, key=lambda row: int(row.get("seq", -1))), detail, submit
    return None, None, None


def check_precedence(
    events: Mapping[str, Mapping[str, Any] | None],
    pairs: Sequence[Sequence[str]],
) -> tuple[bool, list[dict[str, Any]]]:
    """Check only the business-action orders a brief states or that logic forces.

    ``events`` maps each business action to the event that proved it (``None``
    when its own checkpoint found none); ``pairs`` lists ``(before, after)``
    action names.  Every action outside the pairs may happen in any order.  A
    pair holds when both events exist and ``before`` has the smaller ``seq``.
    """
    rows: list[dict[str, Any]] = []
    for before, after in pairs:
        first, second = events.get(before), events.get(after)
        first_seq = int(first.get("seq", -1)) if first else None
        second_seq = int(second.get("seq", -1)) if second else None
        rows.append({
            "before": before,
            "after": after,
            "before_seq": first_seq,
            "after_seq": second_seq,
            "passed": first_seq is not None and second_seq is not None and first_seq < second_seq,
        })
    return all(row["passed"] for row in rows), rows
