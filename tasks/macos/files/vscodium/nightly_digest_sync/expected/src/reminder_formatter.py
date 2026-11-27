EMAIL_SUBJECT = "Canary digest ready"
DEFAULT_SIGNOFF = "Ops Desk"
RETRY_WINDOW = "15 minutes"


def build_reminder(name: str) -> str:
    return f"{EMAIL_SUBJECT}\n{name}, please review the canary handoff packet within {RETRY_WINDOW}.\n-- {DEFAULT_SIGNOFF}"
