PRIMARY_ENGINEER = "Nina"
BACKUP_ENGINEER = "Marco"
ESCALATION_OWNER = "Night Watch"


def current_rotation() -> str:
    return f"primary={PRIMARY_ENGINEER}, backup={BACKUP_ENGINEER}, owner={ESCALATION_OWNER}"
