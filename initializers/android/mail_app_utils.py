"""Shared helpers for Android mail/chat initializers."""

from __future__ import annotations

from typing import Any, Mapping

from initializers.android.app_utils import ensure_package_installed, launch_app_cleanly
from platforms.android.bootstrap import (
    DeltaChatBootstrapConfig,
    DeltaChatBootstrapper,
    K9BootstrapConfig,
    K9Bootstrapper,
)
from platforms.android.comm_state import restore_app_data_template_if_available


def reset_delta_chat_account_if_requested(
    controller: Any,
    params: Mapping[str, Any],
    *,
    api_base_url: str,
) -> bool:
    """Clear and re-bootstrap Delta Chat when params.reset_app_data is true."""
    if not bool(params.get("reset_app_data", False)):
        return False

    if bool(params.get("use_app_data_template", True)):
        if restore_app_data_template_if_available(
            controller,
            "deltachat",
            template_dir=params.get("app_data_template_dir"),
        ):
            return True

    config = DeltaChatBootstrapConfig(
        api_base_url=api_base_url,
        clear_app_data=True,
    )
    DeltaChatBootstrapper(controller, config).run()
    return True


def reset_k9_account_if_requested(
    controller: Any,
    params: Mapping[str, Any],
    *,
    api_base_url: str,
) -> bool:
    """Clear and re-bootstrap K-9 when params.reset_app_data is true."""
    if not bool(params.get("reset_app_data", False)):
        return False

    if bool(params.get("use_app_data_template", True)):
        if restore_app_data_template_if_available(
            controller,
            "k9",
            template_dir=params.get("app_data_template_dir"),
        ):
            return True

    config = K9BootstrapConfig(
        api_base_url=api_base_url,
        clear_app_data=True,
    )
    K9Bootstrapper(controller, config).run()
    return True


def launch_mail_or_chat_app(
    controller: Any,
    *,
    app_package: str,
    app_activity: str,
    label: str,
    wait_ms: int,
    clear_app_data: bool = False,
) -> tuple[bool, str]:
    ensure_package_installed(controller, app_package, label=label)
    return launch_app_cleanly(
        controller,
        app_package=app_package,
        app_activity=app_activity,
        clear_app_data=clear_app_data,
        wait_ms=wait_ms,
        foreground_timeout_seconds=12.0,
    )
