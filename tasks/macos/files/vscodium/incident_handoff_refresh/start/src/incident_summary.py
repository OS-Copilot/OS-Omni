INCIDENT_SEVERITY = "SEV3"
DEFAULT_OWNER = "Day Shift"


def render_summary(queue_name: str) -> str:
    return f"{INCIDENT_SEVERITY}: {queue_name} -> owner {DEFAULT_OWNER}"
