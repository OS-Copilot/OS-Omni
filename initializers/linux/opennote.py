"""OpenNote snapshot initializer recovered from reviewed run artifacts."""

from initializers.linux.cua_review import SnapshotOpenAppInitializer


class OpenNoteInitializer(SnapshotOpenAppInitializer):
    default_app_name = "OpenNote"
    default_app_command = "opennote"
