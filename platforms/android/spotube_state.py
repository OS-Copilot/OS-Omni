"""Shared Spotube Android SQLite helpers."""

from __future__ import annotations

import base64
import json
import shlex
import time
from typing import Any

from platforms.android.apk_cache import ensure_package_installed_from_cache


DEFAULT_APP_PACKAGE = "oss.krtirtho.spotube"
DEFAULT_APP_ACTIVITY = "com.ryanheise.audioservice.AudioServiceActivity"


def default_database_path(app_package: str = DEFAULT_APP_PACKAGE) -> str:
    package = app_package.strip() or DEFAULT_APP_PACKAGE
    return f"/data/user/0/{package}/files/db.sqlite"


def ensure_app_installed(controller: Any, app_package: str = DEFAULT_APP_PACKAGE) -> str:
    return ensure_package_installed_from_cache(
        controller,
        app_package.strip() or DEFAULT_APP_PACKAGE,
        label="Spotube",
    )


def ensure_adb_root(controller: Any) -> None:
    root_output = str(controller.execute_adb(["root"]) or "").strip().lower()
    if "cannot run as root" in root_output or "production builds" in root_output:
        raise RuntimeError(root_output)
    if "restarting adbd as root" in root_output:
        controller.execute_adb(["wait-for-device"])
        time.sleep(1.0)


def database_exists(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    database_path: str | None = None,
) -> bool:
    db_path = database_path or default_database_path(app_package)
    output = str(
        controller.execute_adb(
            ["shell", f"if [ -f {shlex.quote(db_path)} ]; then echo present; fi"]
        )
        or ""
    ).strip()
    return output == "present"


def ensure_database_created(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    database_path: str | None = None,
    wait_ms: int = 2200,
    timeout_seconds: float = 20.0,
) -> str:
    db_path = database_path or default_database_path(app_package)
    if database_exists(controller, app_package=app_package, database_path=db_path):
        return "existing"

    controller.execute_adb(["shell", "am", "force-stop", app_package])
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"])
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)

    deadline = time.time() + max(timeout_seconds, 0.0)
    while time.time() < deadline:
        if database_exists(controller, app_package=app_package, database_path=db_path):
            controller.execute_adb(["shell", "am", "force-stop", app_package])
            return "created"
        time.sleep(0.5)

    raise RuntimeError(f"Spotube database was not created: {db_path}")


def reset_profile_settings_to_baseline(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    database_path: str | None = None,
    wait_ms: int = 2200,
    baseline_audio_source: str = "YouTube Audio",
) -> dict[str, Any]:
    """Reset profile settings to a known non-target baseline before the task."""

    app_package = app_package.strip() or DEFAULT_APP_PACKAGE
    db_path = database_path or default_database_path(app_package)
    ensure_app_installed(controller, app_package)
    ensure_adb_root(controller)
    database_state = ensure_database_created(
        controller,
        app_package=app_package,
        app_activity=app_activity,
        database_path=db_path,
        wait_ms=wait_ms,
    )

    controller.execute_adb(["shell", "am", "force-stop", app_package])
    time.sleep(0.4)
    baseline_locale = json.dumps(
        {"languageCode": "system", "countryCode": "system"},
        separators=(",", ":"),
    )
    sql = f"""
UPDATE preferences_table
SET normalize_audio = 0,
    accent_color_scheme = {_sql_quote("Slate:0xff64748b")},
    locale = {_sql_quote(baseline_locale)},
    market = {_sql_quote("US")},
    theme_mode = {_sql_quote("system")},
    audio_source_id = {_sql_quote("")}
WHERE id = (SELECT id FROM preferences_table ORDER BY id LIMIT 1);
UPDATE plugins_table SET selected_for_audio_source = 0;
UPDATE plugins_table
SET selected_for_audio_source = 1
WHERE lower(name) = lower({_sql_quote(baseline_audio_source)});
"""
    sql_output = _execute_sql(controller, database_path=db_path, sql=sql)
    state = read_profile_state(controller, app_package=app_package, database_path=db_path)
    baseline_checks = evaluate_profile_baseline(
        state,
        forbidden_audio_source="Jiosaavn Audio",
        forbidden_market="AT",
        forbidden_theme="light",
        forbidden_accent="rose",
    )
    return {
        "database_path": db_path,
        "database_state": database_state,
        "sql_output": sql_output,
        "baseline_audio_source": baseline_audio_source,
        "baseline_checks": baseline_checks,
        "state": state,
    }


def read_profile_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    database_path: str | None = None,
) -> dict[str, Any]:
    app_package = app_package.strip() or DEFAULT_APP_PACKAGE
    db_path = database_path or default_database_path(app_package)
    ensure_adb_root(controller)

    preference_rows = _query_rows(
        controller,
        database_path=db_path,
        sql="""
SELECT
  COALESCE(id, ''),
  COALESCE(normalize_audio, ''),
  COALESCE(accent_color_scheme, ''),
  COALESCE(locale, ''),
  COALESCE(market, ''),
  COALESCE(theme_mode, ''),
  COALESCE(audio_source_id, '')
FROM preferences_table
ORDER BY id
LIMIT 1;
""",
    )
    plugin_rows = _query_rows(
        controller,
        database_path=db_path,
        sql="""
SELECT
  COALESCE(id, ''),
  COALESCE(name, ''),
  COALESCE(author, ''),
  COALESCE(selected_for_audio_source, '')
FROM plugins_table
ORDER BY id;
""",
    )

    preference = None
    if preference_rows:
        row = _pad_row(preference_rows[0], 7)
        preference = {
            "id": row[0],
            "normalize_audio": _to_int(row[1]),
            "accent_color_scheme": row[2],
            "locale": row[3],
            "market": row[4],
            "theme_mode": row[5],
            "audio_source_id": row[6],
        }

    plugins = []
    for raw_row in plugin_rows:
        row = _pad_row(raw_row, 4)
        plugins.append(
            {
                "id": row[0],
                "name": row[1],
                "author": row[2],
                "selected_for_audio_source": _to_int(row[3]),
            }
        )

    return {
        "database_path": db_path,
        "preference": preference,
        "plugins": plugins,
    }


def evaluate_expected_profile(
    state: dict[str, Any],
    *,
    expected_audio_source: str = "Jiosaavn Audio",
    expected_language_code: str = "en",
    expected_market: str = "AT",
    expected_theme: str = "light",
    expected_accent: str = "rose",
    expected_normalize_audio: bool = True,
) -> dict[str, Any]:
    preference = state.get("preference") or {}
    plugins = list(state.get("plugins") or [])

    locale = _parse_locale(str(preference.get("locale") or ""))
    selected_plugins = [
        str(plugin.get("name") or "")
        for plugin in plugins
        if _to_int(plugin.get("selected_for_audio_source")) == 1
    ]
    expected_source_lower = expected_audio_source.lower()

    checks = {
        "database_preference_present": bool(preference),
        "normalize_audio_on": (
            _to_int(preference.get("normalize_audio")) == (1 if expected_normalize_audio else 0)
        ),
        "language_code_expected": str(locale.get("languageCode") or "").lower()
        == expected_language_code.lower(),
        "market_expected": str(preference.get("market") or "").upper()
        == expected_market.upper(),
        "theme_expected": str(preference.get("theme_mode") or "").lower()
        == expected_theme.lower(),
        "accent_expected": str(preference.get("accent_color_scheme") or "")
        .lower()
        .startswith(expected_accent.lower()),
        "expected_audio_source_selected": any(
            name.lower() == expected_source_lower for name in selected_plugins
        ),
        "only_expected_audio_source_selected": selected_plugins == [expected_audio_source],
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "selected_audio_sources": selected_plugins,
        "locale": locale,
        "expected": {
            "audio_source": expected_audio_source,
            "language_code": expected_language_code,
            "market": expected_market,
            "theme": expected_theme,
            "accent": expected_accent,
            "normalize_audio": expected_normalize_audio,
        },
    }


def evaluate_profile_baseline(
    state: dict[str, Any],
    *,
    forbidden_audio_source: str,
    forbidden_market: str,
    forbidden_theme: str,
    forbidden_accent: str,
) -> dict[str, Any]:
    preference = state.get("preference") or {}
    plugins = list(state.get("plugins") or [])
    selected_plugins = [
        str(plugin.get("name") or "")
        for plugin in plugins
        if _to_int(plugin.get("selected_for_audio_source")) == 1
    ]
    checks = {
        "database_preference_present": bool(preference),
        "normalize_audio_off": _to_int(preference.get("normalize_audio")) == 0,
        "market_not_target": str(preference.get("market") or "").upper()
        != forbidden_market.upper(),
        "theme_not_target": str(preference.get("theme_mode") or "").lower()
        != forbidden_theme.lower(),
        "accent_not_target": not str(preference.get("accent_color_scheme") or "")
        .lower()
        .startswith(forbidden_accent.lower()),
        "forbidden_audio_source_not_selected": forbidden_audio_source not in selected_plugins,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "selected_audio_sources": selected_plugins,
    }


def _execute_sql(controller: Any, *, database_path: str, sql: str) -> str:
    encoded_sql = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    command = (
        f"printf %s {encoded_sql} | base64 -d | "
        f"sqlite3 {shlex.quote(database_path)}"
    )
    return str(controller.execute_adb(["shell", command]) or "")


def _query_rows(controller: Any, *, database_path: str, sql: str) -> list[list[str]]:
    encoded_sql = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    command = (
        f"printf %s {encoded_sql} | base64 -d | "
        f"sqlite3 -separator '|' {shlex.quote(database_path)}"
    )
    output = str(controller.execute_adb(["shell", command]) or "").strip()
    if not output:
        return []
    return [line.split("|") for line in output.splitlines() if line.strip()]


def _sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _pad_row(row: list[str], length: int) -> list[str]:
    return row + [""] * max(0, length - len(row))


def _to_int(value: Any) -> int:
    try:
        return int(str(value).strip() or "0")
    except (TypeError, ValueError):
        return 0


def _parse_locale(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
