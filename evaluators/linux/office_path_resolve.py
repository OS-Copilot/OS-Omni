"""Shared host/guest path resolution for office file evaluators."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


def unlink_if_temp(path: Path, is_temp: bool) -> None:
    if not is_temp:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def resolve_office_file_path(
    path_value: str,
    controller: Any,
    *,
    temp_prefix: str = "helloworld_office_",
    default_suffix: str = "",
) -> tuple[Path, bool]:
    """Return a local path and whether it is a temporary download from the guest.

    If ``path_value`` exists on the host, use it. Otherwise fetch via ``controller.get_file``.
    """
    candidate = Path(path_value).expanduser()
    # Linux task specs normally use guest absolute paths such as /tmp/... and
    # /home/user/....  Prefer the controller for those paths so stale host files
    # under the same absolute path cannot shadow the VM artifact.
    guest_absolute = str(candidate).startswith(("/tmp/", "/home/user/", "/home/oai/"))
    if guest_absolute and controller is not None and hasattr(controller, "get_file"):
        data = controller.get_file(path_value)
        suffix = Path(path_value).suffix or default_suffix
        tmp = tempfile.NamedTemporaryFile(prefix=temp_prefix, suffix=suffix, delete=False)
        try:
            tmp.write(data)
            tmp.flush()
        finally:
            tmp.close()
        return Path(tmp.name), True
    if candidate.exists():
        return candidate, False
    if controller is None or not hasattr(controller, "get_file"):
        raise FileNotFoundError(f"path not found on host: {candidate}")
    data = controller.get_file(path_value)
    suffix = Path(path_value).suffix or default_suffix
    tmp = tempfile.NamedTemporaryFile(prefix=temp_prefix, suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.flush()
    finally:
        tmp.close()
    return Path(tmp.name), True


def resolve_office_file_pair(
    actual: str,
    expected: str,
    controller: Any,
    *,
    actual_prefix: str = "helloworld_actual_",
    expected_prefix: str = "helloworld_expected_",
    actual_suffix: str = "",
    expected_suffix: str = "",
) -> tuple[Path, Path, bool, bool]:
    """Resolve actual and expected paths; cleans up the first temp file if the second resolution fails."""
    a_path, a_tmp = resolve_office_file_path(
        actual, controller, temp_prefix=actual_prefix, default_suffix=actual_suffix
    )
    try:
        e_path, e_tmp = resolve_office_file_path(
            expected, controller, temp_prefix=expected_prefix, default_suffix=expected_suffix
        )
    except BaseException:
        if a_tmp:
            try:
                a_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return a_path, e_path, a_tmp, e_tmp
