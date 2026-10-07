"""OpenFood snapshot initializer recovered from reviewed run artifacts."""

from initializers.linux.cua_review import SnapshotOpenAppInitializer


class OpenFoodInitializer(SnapshotOpenAppInitializer):
    default_app_name = "OpenFood"
    default_app_command = "openfood"
