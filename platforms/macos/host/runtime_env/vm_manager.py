"""VM lifecycle abstraction for macOS benchmark providers."""

from __future__ import annotations

from typing import Protocol

from .tart_manager import TartManager
from .virtual_buddy_manager import VirtualBuddyManager


class MacOSVMManager(Protocol):
    provider_name: str

    def vm_exists(self, vm_name: str) -> bool:
        """Return whether the configured base VM exists."""

    def prepare_benchmark_environment(self, base_vm_name: str, clone_name: str | None = None) -> str | None:
        """Prepare a fresh ephemeral VM and return its name."""

    def cleanup_benchmark_environment(self, clone_name: str) -> bool:
        """Stop and delete the ephemeral VM."""

    def resolve_runtime_host(self, vm_name: str, fallback_host: str | None = None) -> str:
        """Resolve the runtime host/IP for the prepared VM."""



def create_macos_vm_manager(provider_name: str | None, *, tart_home: str | None = None) -> MacOSVMManager:
    normalized = str(provider_name or "virtualbuddy").strip().lower()
    if normalized in {"virtualbuddy", "virtual_buddy", "vb"}:
        return VirtualBuddyManager()
    if normalized == "tart":
        return TartManager(tart_home=tart_home)
    raise ValueError(
        "Unsupported macOS VM provider. Use vm_provider=virtualbuddy or vm_provider=tart."
    )
