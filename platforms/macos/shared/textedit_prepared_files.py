from __future__ import annotations

import re
from typing import Optional

PREPARED_TEXTEDIT_FILENAMES = {
    "ops_note.txt",
    "shift_log.txt",
    "app.ini",
}


def extract_textedit_filename_from_window_title(title: str) -> Optional[str]:
    raw_title = str(title or "").strip()
    if not raw_title:
        return None
    match = re.search(r"([^/\\]+\.(?:txt|ini))\b", raw_title, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def _normalize_lines(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n").split("\n") if normalized else []


def _serialize_lines(lines: list[str]) -> str:
    return "\n".join(lines) + ("\n" if lines else "")


def _replace_prefixed_line(lines: list[str], prefix: str, new_line: str) -> bool:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = new_line
            return True
    return False


def _remove_exact_line(lines: list[str], target: str) -> bool:
    try:
        lines.remove(target)
    except ValueError:
        return False
    return True


def _insert_after_line(lines: list[str], anchor: str, new_line: str) -> bool:
    try:
        anchor_index = lines.index(anchor)
    except ValueError:
        return False

    lines[:] = [line for line in lines if line != new_line]
    lines.insert(anchor_index + 1, new_line)
    return True


def _append_line(lines: list[str], new_line: str) -> bool:
    lines[:] = [line for line in lines if line != new_line]
    lines.append(new_line)
    return True


def _normalized_payload(payload_text: str) -> str:
    return str(payload_text or "").strip()


def apply_prepared_textedit_mutation(filename: str, current_text: str, payload_text: str) -> Optional[str]:
    filename = str(filename or "").strip()
    payload_text = _normalized_payload(payload_text)
    lines = _normalize_lines(current_text)
    if not payload_text:
        return None

    if filename == "ops_note.txt":
        footer = [
            "Follow-up:",
            "Owner: Riley",
            "Status: ready",
            "Badge count: 12",
            "Next check: 15:30",
            "Desk phone: 555-0187",
        ]
        if payload_text in footer and payload_text not in lines:
            payload_index = footer.index(payload_text)
            if all(previous in lines for previous in footer[:payload_index]):
                _append_line(lines, payload_text)
                return _serialize_lines(lines)
        return None

    elif filename == "shift_log.txt":
        operations = {
            "Coordinator: Mina": lambda: _insert_after_line(lines, "Shift Summary", "Coordinator: Mina")
            if "Coordinator: Mina" not in lines
            else False,
            "Priority: high": lambda: _insert_after_line(lines, "Coordinator: Mina", "Priority: high")
            if "Priority: high" not in lines
            else False,
            "Desk: South Lobby": lambda: _insert_after_line(lines, "Priority: high", "Desk: South Lobby")
            if "Desk: South Lobby" not in lines
            else False,
            "Front desk status: badges delivered": lambda: _replace_prefixed_line(
                lines, "Front desk status:", "Front desk status: badges delivered"
            )
            if "Front desk status: badges delivered" not in lines
            else False,
            "Runner status: escort list delivered": lambda: _replace_prefixed_line(
                lines, "Runner status:", "Runner status: escort list delivered"
            )
            if "Runner status: escort list delivered" not in lines
            else False,
            "Kitchen status: coffee restock completed": lambda: _replace_prefixed_line(
                lines, "Kitchen status:", "Kitchen status: coffee restock completed"
            )
            if "Kitchen status: coffee restock completed" not in lines
            else False,
            "Security status: badge desk reopened": lambda: _replace_prefixed_line(
                lines, "Security status:", "Security status: badge desk reopened"
            )
            if "Security status: badge desk reopened" not in lines
            else False,
            "Ops notes: facilities confirmed for 19:30": lambda: _replace_prefixed_line(
                lines, "Ops notes:", "Ops notes: facilities confirmed for 19:30"
            )
            if "Ops notes: facilities confirmed for 19:30" not in lines
            else False,
            "Escalation owner: Avery": lambda: _insert_after_line(
                lines,
                "Ops notes: facilities confirmed for 19:30",
                "Escalation owner: Avery",
            )
            if "Escalation owner: Avery" not in lines
            else False,
            "Handoff complete": lambda: _append_line(lines, "Handoff complete")
            if "Handoff complete" not in lines
            else False,
            "Reviewed by: ops_lead": lambda: _append_line(lines, "Reviewed by: ops_lead")
            if "Reviewed by: ops_lead" not in lines
            else False,
            "Queue: evening": lambda: _append_line(lines, "Queue: evening")
            if "Queue: evening" not in lines
            else False,
            "Archive: yes": lambda: _append_line(lines, "Archive: yes")
            if "Archive: yes" not in lines
            else False,
            "Follow-up window: 19:30-20:00": lambda: _append_line(lines, "Follow-up window: 19:30-20:00")
            if "Follow-up window: 19:30-20:00" not in lines
            else False,
        }
        operation = operations.get(payload_text)
        if operation and operation():
            return _serialize_lines(lines)
        return None

    elif filename == "app.ini":
        operations = {
            "remove Version=1.0.0": lambda: _remove_exact_line(lines, "Version=1.0.0")
            if "Version=1.0.0" in lines
            else False,
            "remove Author=Admin": lambda: _remove_exact_line(lines, "Author=Admin")
            if "Author=Admin" in lines
            else False,
            "Environment=QA": lambda: _insert_after_line(lines, "[Settings]", "Environment=QA")
            if "Environment=QA" not in lines
            else False,
            "ReleaseTrack=Canary": lambda: _insert_after_line(lines, "Environment=QA", "ReleaseTrack=Canary")
            if "ReleaseTrack=Canary" not in lines
            else False,
            "Region=West": lambda: _insert_after_line(lines, "ReleaseTrack=Canary", "Region=West")
            if "Region=West" not in lines
            else False,
            "Theme=Light": lambda: _replace_prefixed_line(lines, "Theme=", "Theme=Light")
            if "Theme=Light" not in lines
            else False,
            "Timeout=45": lambda: _replace_prefixed_line(lines, "Timeout=", "Timeout=45")
            if "Timeout=45" not in lines
            else False,
            "Mode=Staging": lambda: _replace_prefixed_line(lines, "Mode=", "Mode=Staging")
            if "Mode=Staging" not in lines
            else False,
            "Logging=On": lambda: _replace_prefixed_line(lines, "Logging=", "Logging=On")
            if "Logging=On" not in lines
            else False,
            "Retries=5": lambda: _replace_prefixed_line(lines, "Retries=", "Retries=5")
            if "Retries=5" not in lines
            else False,
            "Cache=True": lambda: _replace_prefixed_line(lines, "Cache=", "Cache=True")
            if "Cache=True" not in lines
            else False,
            "Host=db.qa.internal": lambda: _replace_prefixed_line(lines, "Host=", "Host=db.qa.internal")
            if "Host=db.qa.internal" not in lines
            else False,
            "Port=6432": lambda: _replace_prefixed_line(lines, "Port=", "Port=6432")
            if "Port=6432" not in lines
            else False,
            "Replica=enabled": lambda: _replace_prefixed_line(lines, "Replica=", "Replica=enabled")
            if "Replica=enabled" not in lines
            else False,
            "Pool=burst": lambda: _replace_prefixed_line(lines, "Pool=", "Pool=burst")
            if "Pool=burst" not in lines
            else False,
            "Owner=ops_lead": lambda: _replace_prefixed_line(lines, "Owner=", "Owner=ops_lead")
            if "Owner=ops_lead" not in lines
            else False,
            "Window=overnight": lambda: _replace_prefixed_line(lines, "Window=", "Window=overnight")
            if "Window=overnight" not in lines
            else False,
            "Queue=night": lambda: _replace_prefixed_line(lines, "Queue=", "Queue=night")
            if "Queue=night" not in lines
            else False,
            "Alerts=Escalate": lambda: _replace_prefixed_line(lines, "Alerts=", "Alerts=Escalate")
            if "Alerts=Escalate" not in lines
            else False,
            "Export=Enabled": lambda: _replace_prefixed_line(lines, "Export=", "Export=Enabled")
            if "Export=Enabled" not in lines
            else False,
            "Escalation=enabled": lambda: _replace_prefixed_line(lines, "Escalation=", "Escalation=enabled")
            if "Escalation=enabled" not in lines
            else False,
            "# Canary window starts at 22:00": lambda: _append_line(lines, "# Canary window starts at 22:00")
            if "# Canary window starts at 22:00" not in lines
            else False,
            "# Ticket: TW-104": lambda: _append_line(lines, "# Ticket: TW-104")
            if "# Ticket: TW-104" not in lines
            else False,
            "# Notify qa-watch before rollout": lambda: _append_line(lines, "# Notify qa-watch before rollout")
            if "# Notify qa-watch before rollout" not in lines
            else False,
        }
        operation = operations.get(payload_text)
        if operation and operation():
            return _serialize_lines(lines)
        return None

    return None
