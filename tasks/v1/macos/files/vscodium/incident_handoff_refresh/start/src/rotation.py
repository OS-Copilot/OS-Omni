PRIMARY_ENGINEER = "Avery"
BACKUP_ENGINEER = "Leo"
ESCALATION_OWNER = "Day Shift"


def current_rotation() -> str:
    return f"primary={PRIMARY_ENGINEER}, backup={BACKUP_ENGINEER}, owner={ESCALATION_OWNER}"
