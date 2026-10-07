INCIDENT_SEVERITY = "SEV2"
DEFAULT_OWNER = "Night Watch"


def render_summary(queue_name: str) -> str:
    return f"{INCIDENT_SEVERITY}: {queue_name} -> owner {DEFAULT_OWNER}"
