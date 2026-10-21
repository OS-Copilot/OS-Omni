EMAIL_SUBJECT = "Draft digest pending"
DEFAULT_SIGNOFF = "Operations"
RETRY_WINDOW = "5 minutes"


def build_reminder(name: str) -> str:
    return f"{EMAIL_SUBJECT}\n{name}, please review the preview handoff packet within {RETRY_WINDOW}.\n-- {DEFAULT_SIGNOFF}"
