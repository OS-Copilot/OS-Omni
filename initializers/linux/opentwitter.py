"""OpenTwitter snapshot initializer recovered from reviewed run artifacts."""

from initializers.linux.cua_review import SnapshotOpenAppInitializer


class OpenTwitterInitializer(SnapshotOpenAppInitializer):
    default_app_name = "OpenTwitter"
    default_app_command = "/home/user/OpenApps/bin/launch-opentwitter"
