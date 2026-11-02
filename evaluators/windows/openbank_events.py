"""Match a completed dispute route without letting later inspection erase it."""

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
