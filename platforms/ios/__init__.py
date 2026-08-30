"""iOSWorld automation module exports."""

from typing import Any

__all__ = ["iOSController", "Observation", "ACTION_SCHEMA"]


def __getattr__(name: str) -> Any:
    """
    Lazily expose heavy controller symbols so importing `ios` does not
    immediately require Appium runtime dependencies.
    """
    if name in __all__:
        from .runtime_env.controller import ACTION_SCHEMA, Observation, iOSController

        exports = {
            "iOSController": iOSController,
            "Observation": Observation,
            "ACTION_SCHEMA": ACTION_SCHEMA,
        }
        return exports[name]
    raise AttributeError(f"module 'ios' has no attribute '{name}'")
