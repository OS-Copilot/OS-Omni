"""Host-side Android SDK/AVD environment helpers."""

from __future__ import annotations

import os
from pathlib import Path


def android_tool_env(
    base_env: dict[str, str] | None = None,
    *,
    apply_to_process: bool = False,
) -> dict[str, str]:
    """Return an environment that points adb/emulator at the real AVD home.

    Some runners execute under a sandbox/service user while the Android SDK and
    AVD live under the interactive Windows user.  In that case adb tries to
    create ``%USERPROFILE%\.android`` for the sandbox user and fails before it
    can talk to the already-running emulator.  We infer the Android user home
    from existing AVD directories and from ANDROID_HOME when possible.
    """

    env = dict(os.environ if base_env is None else base_env)

    if not env.get("ANDROID_USER_HOME"):
        candidate_homes: list[Path] = []
        userprofile = env.get("USERPROFILE")
        if userprofile:
            candidate_homes.append(Path(userprofile))

        sdk_root = env.get("ANDROID_HOME") or env.get("ANDROID_SDK_ROOT")
        if sdk_root:
            for parent in Path(sdk_root).parents:
                if parent.name.lower() == "appdata":
                    candidate_homes.append(parent.parent)
                    break

        if os.name == "nt":
            users_dir = Path("C:/Users")
            if users_dir.exists():
                candidate_homes.extend(
                    path for path in users_dir.iterdir() if (path / ".android" / "avd").exists()
                )

        seen: set[str] = set()
        for home in candidate_homes:
            home_key = str(home).lower()
            if home_key in seen:
                continue
            seen.add(home_key)
            if (home / ".android" / "avd").exists():
                env["ANDROID_USER_HOME"] = str(home)
                break

    if not env.get("ANDROID_AVD_HOME"):
        android_user_home = env.get("ANDROID_USER_HOME") or env.get("USERPROFILE")
        if android_user_home:
            avd_home = Path(android_user_home) / ".android" / "avd"
            if avd_home.exists():
                env["ANDROID_AVD_HOME"] = str(avd_home)

    android_user_home = env.get("ANDROID_USER_HOME")
    if android_user_home:
        env.setdefault("ANDROID_SDK_HOME", android_user_home)
        env.setdefault("HOME", android_user_home)
        if os.name == "nt":
            home_path = Path(android_user_home)
            env["USERPROFILE"] = str(home_path)
            drive = home_path.drive
            if drive:
                env["HOMEDRIVE"] = drive
                env["HOMEPATH"] = str(home_path)[len(drive) :]

    if apply_to_process:
        for key in ("ANDROID_USER_HOME", "ANDROID_AVD_HOME", "ANDROID_SDK_HOME", "HOME"):
            value = env.get(key)
            if value and not os.environ.get(key):
                os.environ[key] = value

    return env
