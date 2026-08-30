"""Initializer for the multimodal Fossify Calendar -> Organic Maps -> Delta Chat task."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import shlex
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import reset_delta_chat_account_if_requested
from initializers.android.fossify_calendar import (
    DEFAULT_DATABASE_PATH as DEFAULT_CALENDAR_DATABASE_PATH,
    DEFAULT_TIMEZONE as DEFAULT_CALENDAR_TIMEZONE,
    FossifyCalendarInitializer,
    _sql_quote,
)
from platforms.android.bootstrap import AndroidBootstrapDriver
from platforms.android.bench_storage_support import ensure_app_installed


class CalendarMapDeltaChatInitializer(BaseInitializer):
    """Prepare GreenMail state, Organic Maps data, and a fresh Fossify calendar event."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_CALENDAR_PACKAGE = "org.fossify.calendar"
    DEFAULT_MAP_PACKAGE = "app.organicmaps.web"
    DEFAULT_DELTA_CHAT_PACKAGE = "chat.delta"

    DEFAULT_EVENT_TITLE = "Bench Coffee Task"
    DEFAULT_EVENT_LOCATION = "Monaco"
    DEFAULT_EVENT_DESCRIPTION = (
        "Find the cafe on Boulevard Princesse Charlotte."
    )

    DEFAULT_MAP_REGION_QUERY = "Monaco"
    DEFAULT_MAP_TARGET_QUERY = "Richmond Bar Monaco"
    DEFAULT_MAP_TARGET_TITLE = "Richmond Bar"
    DEFAULT_ORGANIC_MAPS_APK_PATH = ".cache/apks/OrganicMaps-26040708-web-release.apk"
    DEFAULT_MAP_DOWNLOAD_BASE_URLS = (
        "https://cdn.organicmaps.app/maps",
        "https://omaps.webfreak.org/maps",
    )

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Android initialization",
            )

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        calendar_package = str(params.get("calendar_package") or self.DEFAULT_CALENDAR_PACKAGE).strip()
        map_package = str(params.get("map_package") or self.DEFAULT_MAP_PACKAGE).strip()
        delta_chat_package = str(params.get("delta_chat_package") or self.DEFAULT_DELTA_CHAT_PACKAGE).strip()

        event_title = str(params.get("calendar_event_title") or self.DEFAULT_EVENT_TITLE).strip()
        event_location = str(params.get("calendar_event_location") or self.DEFAULT_EVENT_LOCATION).strip()
        event_description = str(params.get("calendar_event_description") or self.DEFAULT_EVENT_DESCRIPTION).strip()
        calendar_database_path = str(
            params.get("calendar_database_path") or DEFAULT_CALENDAR_DATABASE_PATH
        ).strip()
        calendar_timezone = str(params.get("calendar_timezone") or DEFAULT_CALENDAR_TIMEZONE).strip()

        map_region_query = str(params.get("map_region_query") or self.DEFAULT_MAP_REGION_QUERY).strip()
        map_target_query = str(params.get("map_target_query") or self.DEFAULT_MAP_TARGET_QUERY).strip()
        map_target_title = str(params.get("map_target_title") or self.DEFAULT_MAP_TARGET_TITLE).strip()
        seed_map_files_from_host = bool(params.get("seed_map_files_from_host", False))
        map_file_ids = params.get("organic_map_file_ids") or ["World", "WorldCoasts", map_region_query]
        organic_maps_apk_path = str(
            params.get("organic_maps_apk_path") or self.DEFAULT_ORGANIC_MAPS_APK_PATH
        ).strip()
        organic_maps_cache_dir = str(params.get("organic_maps_cache_dir") or ".cache/organicmaps").strip()
        map_download_base_urls = params.get("organic_maps_download_base_urls") or list(
            self.DEFAULT_MAP_DOWNLOAD_BASE_URLS
        )

        seed_sender_email = str(params.get("seed_sender_email") or "").strip()
        seed_sender_password = str(params.get("seed_sender_password") or "").strip()
        seed_recipient_email = str(params.get("seed_recipient_email") or "").strip()
        seed_subject = str(params.get("seed_subject") or "").strip()
        seed_body = str(params.get("seed_body") or "").strip()
        seed_smtp_host = str(params.get("seed_smtp_host") or "127.0.0.1").strip()
        seed_smtp_port = int(params.get("seed_smtp_port") or 3025)
        purge_greenmail = bool(params.get("purge_greenmail", True))
        require_map_ready = bool(params.get("require_map_ready", False))
        map_ready = True
        map_warning = ""
        map_seed_metadata: dict[str, Any] = {}

        try:
            self._require_package_installed(controller, calendar_package)
            self._require_package_installed(controller, map_package)
            self._require_package_installed(controller, delta_chat_package)

            reset_delta_chat_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            self._prepare_greenmail_and_seed_chat(
                api_base_url=api_base_url,
                purge_greenmail=purge_greenmail,
                seed_sender_email=seed_sender_email,
                seed_sender_password=seed_sender_password,
                seed_recipient_email=seed_recipient_email,
                seed_subject=seed_subject,
                seed_body=seed_body,
                seed_smtp_host=seed_smtp_host,
                seed_smtp_port=seed_smtp_port,
            )

            if seed_map_files_from_host:
                map_seed_metadata = self._seed_organic_maps_from_host(
                    controller=controller,
                    map_package=map_package,
                    apk_path=organic_maps_apk_path,
                    cache_dir=organic_maps_cache_dir,
                    map_file_ids=[str(file_id).strip() for file_id in map_file_ids if str(file_id).strip()],
                    download_base_urls=map_download_base_urls,
                )

            try:
                self._ensure_organic_maps_ready(
                    controller=controller,
                    map_package=map_package,
                    region_query=map_region_query,
                    target_query=map_target_query,
                    target_title=map_target_title,
                )
            except RuntimeError as exc:
                if require_map_ready:
                    raise
                map_ready = False
                map_warning = str(exc)
                controller.execute_adb(["shell", "am", "force-stop", map_package])

            self._prepare_calendar_event(
                controller=controller,
                calendar_package=calendar_package,
                database_path=calendar_database_path,
                timezone_name=calendar_timezone,
                event_title=event_title,
                event_location=event_location,
                event_description=event_description,
            )
        except RuntimeError as exc:
            return InitResult(
                status=InitStatus.FAIL,
                message=str(exc),
                metadata={
                    "calendar_package": calendar_package,
                    "map_package": map_package,
                    "delta_chat_package": delta_chat_package,
                },
            )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare cross-app scene: {type(exc).__name__}: {exc}",
                metadata={
                    "calendar_package": calendar_package,
                    "map_package": map_package,
                    "delta_chat_package": delta_chat_package,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared GreenMail, Organic Maps, and a Fossify Calendar event",
            metadata={
                "calendar_package": calendar_package,
                "calendar_database_path": calendar_database_path,
                "map_package": map_package,
                "delta_chat_package": delta_chat_package,
                "event_title": event_title,
                "event_location": event_location,
                "map_target_title": map_target_title,
                "map_ready": map_ready,
                "map_warning": map_warning,
                "map_seed": map_seed_metadata,
                "reset_app_data": bool(params.get("reset_app_data", False)),
            },
        )

    @staticmethod
    def _request_json(url: str, *, method: str, allow_empty: bool = False) -> Any:
        request = Request(url, method=method)
        try:
            with urlopen(request, timeout=5.0) as response:
                raw = response.read()
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc

        if not raw:
            if allow_empty:
                return None
            raise RuntimeError(f"{method} {url} returned an empty response")

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{method} {url} returned invalid JSON") from exc

    def _prepare_greenmail_and_seed_chat(
        self,
        *,
        api_base_url: str,
        purge_greenmail: bool,
        seed_sender_email: str,
        seed_sender_password: str,
        seed_recipient_email: str,
        seed_subject: str,
        seed_body: str,
        seed_smtp_host: str,
        seed_smtp_port: int,
    ) -> None:
        readiness = self._request_json(f"{api_base_url}/api/service/readiness", method="GET")
        if not isinstance(readiness, dict) or readiness.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {readiness!r}")

        if purge_greenmail:
            self._request_json(f"{api_base_url}/api/mail/purge", method="POST", allow_empty=True)

        if not all(
            (
                seed_sender_email,
                seed_sender_password,
                seed_recipient_email,
                seed_subject,
                seed_body,
            )
        ):
            return

        message = EmailMessage()
        message["From"] = seed_sender_email
        message["To"] = seed_recipient_email
        message["Subject"] = seed_subject
        message["Chat-Version"] = "1.0"
        message.set_content(seed_body)

        with smtplib.SMTP(host=seed_smtp_host, port=seed_smtp_port, timeout=10.0) as client:
            client.login(seed_sender_email, seed_sender_password)
            client.send_message(message)

    def _seed_organic_maps_from_host(
        self,
        *,
        controller: Any,
        map_package: str,
        apk_path: str,
        cache_dir: str,
        map_file_ids: list[str],
        download_base_urls: Any,
    ) -> dict[str, Any]:
        repo_root = Path(__file__).resolve().parents[2]
        local_apk = self._resolve_repo_path(repo_root, apk_path)
        local_cache_dir = self._resolve_repo_path(repo_root, cache_dir)
        countries = self._load_organic_maps_countries(local_apk)
        version = int(countries.get("v") or 0)
        if version <= 0:
            raise RuntimeError(f"Organic Maps countries.txt in {local_apk} does not contain a valid version")

        entries = self._find_organic_map_entries(countries, map_file_ids)
        missing = [file_id for file_id in map_file_ids if file_id not in entries]
        if missing:
            raise RuntimeError(f"Organic Maps countries.txt is missing map entries: {', '.join(missing)}")

        local_files = self._ensure_local_organic_map_files(
            version=version,
            entries=entries,
            cache_dir=local_cache_dir,
            download_base_urls=self._normalize_download_base_urls(download_base_urls),
        )
        remote_dir = self._push_organic_map_files_to_internal_storage(
            controller=controller,
            map_package=map_package,
            version=version,
            local_files=local_files,
        )
        return {
            "version": version,
            "file_ids": list(entries),
            "cache_dir": str(local_cache_dir),
            "remote_dir": remote_dir,
        }

    @staticmethod
    def _resolve_repo_path(repo_root: Path, path_value: str) -> Path:
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        return path

    @staticmethod
    def _load_organic_maps_countries(apk_path: Path) -> dict[str, Any]:
        if not apk_path.exists():
            raise RuntimeError(f"Organic Maps APK not found for host map seeding: {apk_path}")
        with ZipFile(apk_path) as apk:
            with apk.open("assets/countries.txt") as countries_file:
                payload = countries_file.read().decode("utf-8")
        countries = json.loads(payload)
        if not isinstance(countries, dict):
            raise RuntimeError(f"Organic Maps countries.txt in {apk_path} is not a JSON object")
        return countries

    def _find_organic_map_entries(
        self,
        countries: dict[str, Any],
        map_file_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        wanted = set(map_file_ids)
        found: dict[str, dict[str, Any]] = {}

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return
            file_id = str(node.get("id") or "")
            if file_id in wanted and file_id not in found:
                size = int(node.get("s") or 0)
                sha1 = str(node.get("sha1_base64") or "")
                if size <= 0 or not sha1:
                    raise RuntimeError(f"Organic Maps entry {file_id!r} is missing size or sha1")
                found[file_id] = {"size": size, "sha1_base64": sha1}
            for child in node.get("g") or []:
                visit(child)

        visit(countries)
        return found

    @staticmethod
    def _normalize_download_base_urls(value: Any) -> list[str]:
        if isinstance(value, str):
            urls = [part.strip() for part in value.split(",")]
        else:
            urls = [str(part).strip() for part in value or []]
        return [url.rstrip("/") for url in urls if url.strip()]

    def _ensure_local_organic_map_files(
        self,
        *,
        version: int,
        entries: dict[str, dict[str, Any]],
        cache_dir: Path,
        download_base_urls: list[str],
    ) -> dict[str, Path]:
        version_dir = cache_dir / str(version)
        version_dir.mkdir(parents=True, exist_ok=True)
        local_files: dict[str, Path] = {}

        for file_id, entry in entries.items():
            local_file = version_dir / f"{file_id}.mwm"
            if not self._organic_map_file_matches(local_file, entry):
                self._download_organic_map_file(
                    version=version,
                    file_id=file_id,
                    local_file=local_file,
                    entry=entry,
                    download_base_urls=download_base_urls,
                )
            local_files[file_id] = local_file

        return local_files

    @staticmethod
    def _organic_map_file_matches(path: Path, entry: dict[str, Any]) -> bool:
        if not path.exists() or path.stat().st_size != int(entry["size"]):
            return False
        digest = hashlib.sha1(path.read_bytes()).digest()
        return base64.b64encode(digest).decode("ascii") == str(entry["sha1_base64"])

    def _download_organic_map_file(
        self,
        *,
        version: int,
        file_id: str,
        local_file: Path,
        entry: dict[str, Any],
        download_base_urls: list[str],
    ) -> None:
        if not download_base_urls:
            raise RuntimeError(f"No Organic Maps download base URLs configured for {file_id}.mwm")

        errors: list[str] = []
        tmp_file = local_file.with_suffix(local_file.suffix + ".tmp")
        for base_url in download_base_urls:
            url = f"{base_url}/{version}/{file_id}.mwm"
            try:
                request = Request(url, headers={"User-Agent": "HelloWorld Android initializer"})
                with urlopen(request, timeout=60.0) as response, tmp_file.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                if not self._organic_map_file_matches(tmp_file, entry):
                    raise RuntimeError("downloaded file failed size or sha1 verification")
                tmp_file.replace(local_file)
                return
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                if tmp_file.exists():
                    tmp_file.unlink()

        raise RuntimeError(f"Failed to download Organic Maps file {file_id}.mwm: {'; '.join(errors)}")

    def _push_organic_map_files_to_internal_storage(
        self,
        *,
        controller: Any,
        map_package: str,
        version: int,
        local_files: dict[str, Path],
    ) -> str:
        self._ensure_adb_root(controller)
        app_files_dir = f"/data/data/{map_package}/files"
        remote_dir = f"{app_files_dir}/{version}"
        quoted_app_files_dir = shlex.quote(app_files_dir)
        quoted_remote_dir = shlex.quote(remote_dir)
        owner_group = str(
            controller.execute_adb(["shell", f"stat -c %U:%G {quoted_app_files_dir}"])
            or ""
        ).strip()
        if not owner_group or ":" not in owner_group:
            raise RuntimeError(f"Could not determine Organic Maps app data owner for {app_files_dir}")

        controller.execute_adb(["shell", f"mkdir -p {quoted_remote_dir}"])
        controller.execute_adb(["shell", f"rm -f {quoted_remote_dir}/*.downloading {quoted_remote_dir}/*.resume"])
        for local_file in local_files.values():
            controller.execute_adb(["push", str(local_file), f"{remote_dir}/{local_file.name}"])

        settings_path = f"{app_files_dir}/settings.ini"
        quoted_settings_path = shlex.quote(settings_path)
        internal_storage_path = f"{app_files_dir}/"
        controller.execute_adb(
            [
                "shell",
                (
                    f"touch {quoted_settings_path}; "
                    f"if grep -q '^StoragePath=' {quoted_settings_path}; then "
                    f"sed -i 's#^StoragePath=.*#StoragePath={internal_storage_path}#' {quoted_settings_path}; "
                    f"else echo 'StoragePath={internal_storage_path}' >> {quoted_settings_path}; fi"
                ),
            ]
        )
        controller.execute_adb(["shell", f"chown -R {owner_group} {quoted_remote_dir} {quoted_settings_path}"])
        controller.execute_adb(["shell", f"chmod 771 {quoted_remote_dir}"])
        controller.execute_adb(["shell", f"chmod 660 {quoted_remote_dir}/*.mwm {quoted_settings_path}"])
        controller.execute_adb(["shell", f"restorecon -R {quoted_remote_dir} {quoted_settings_path}"])
        controller.execute_adb(["shell", "am", "force-stop", map_package])
        return remote_dir

    @staticmethod
    def _ensure_adb_root(controller: Any) -> None:
        output = str(controller.execute_adb(["root"]) or "").strip().lower()
        if "cannot run as root" in output or "adbd cannot run as root" in output:
            raise RuntimeError("Organic Maps host seeding requires adb root on the emulator")
        controller.execute_adb(["wait-for-device"])

    @staticmethod
    def _require_package_installed(controller: Any, package_name: str) -> None:
        labels = {
            "org.fossify.calendar": "Fossify Calendar",
            "app.organicmaps.web": "Organic Maps",
            "chat.delta": "Delta Chat",
        }
        ensure_app_installed(controller, package_name, label=labels.get(package_name, package_name))

    def _prepare_calendar_event(
        self,
        *,
        controller: Any,
        calendar_package: str,
        database_path: str,
        timezone_name: str,
        event_title: str,
        event_location: str,
        event_description: str,
    ) -> None:
        controller.execute_adb(["shell", "pm", "clear", calendar_package])
        FossifyCalendarInitializer._grant_permissions(controller, calendar_package)
        controller.execute_adb(["shell", "monkey", "-p", calendar_package, "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(0.8)
        FossifyCalendarInitializer._wait_for_database(
            controller,
            database_path=database_path,
            app_package=calendar_package,
        )
        FossifyCalendarInitializer._execute_sql(
            controller,
            database_path=database_path,
            sql=f"DELETE FROM events WHERE title = {_sql_quote(event_title)} OR title LIKE 'BMK %';",
        )
        start, end = self._calendar_today_event_window(controller)
        FossifyCalendarInitializer._insert_event(
            controller,
            database_path=database_path,
            timezone_name=timezone_name,
            event={
                "title": event_title,
                "location": event_location,
                "description": event_description,
                "start": start,
                "end": end,
            },
        )
        controller.execute_adb(["shell", "am", "force-stop", calendar_package])
        controller.execute_adb(["shell", "monkey", "-p", calendar_package, "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(0.8)

    @staticmethod
    def _calendar_today_event_window(controller: Any) -> tuple[str, str]:
        today = str(controller.execute_adb(["shell", "date", "+%Y-%m-%d"]) or "").strip()
        if not today:
            today = dt.date.today().isoformat()
        return f"{today}T09:00:00", f"{today}T10:00:00"

    def _replace_calendar_description(self, driver: AndroidBootstrapDriver, event_description: str) -> None:
        selector = {"resource_id": "org.fossify.calendar:id/event_description"}
        last_actual = ""

        for _attempt in range(4):
            node = driver.wait_for_node(selector, timeout_seconds=4.0)
            tap = dict(node.get("tap") or {})
            if not tap:
                raise RuntimeError("Fossify Calendar description field is missing tap coordinates")

            # This field is flaky when treated like a normal EditText; a direct focus + type flow is steadier.
            driver.controller.tap(int(tap["x"]), int(tap["y"]))
            time.sleep(1.0)
            driver.controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_MOVE_END"])
            time.sleep(0.1)
            self._send_repeated_keyevent(driver.controller, "KEYCODE_DEL", 160)
            driver.controller.input_text(event_description)
            time.sleep(1.2)

            current = driver.wait_for_node(selector, timeout_seconds=2.0, raise_on_timeout=False)
            last_actual = str((current or {}).get("text") or "").strip()
            if last_actual == event_description:
                return

        raise RuntimeError(
            "Failed to set Fossify Calendar event description; "
            f"expected={event_description!r}, actual={last_actual!r}"
        )

    def _save_calendar_event(self, driver: AndroidBootstrapDriver) -> None:
        for _attempt in range(4):
            if driver.node_exists({"resource_id": "org.fossify.calendar:id/month_view_background"}, timeout_seconds=1.0):
                return

            if driver.tap_if_present({"resource_id": "org.fossify.calendar:id/save"}, timeout_seconds=1.0):
                time.sleep(1.0)
                continue
            if driver.tap_if_present({"text": "OK"}, timeout_seconds=1.0):
                time.sleep(1.0)
                continue
            if driver.tap_if_present({"text": "Cancel"}, timeout_seconds=1.0):
                time.sleep(1.0)
                continue
            if driver.tap_if_present(self._notification_deny_selectors(), timeout_seconds=1.0):
                time.sleep(1.0)
                continue
            time.sleep(1.0)

        if not driver.node_exists({"resource_id": "org.fossify.calendar:id/month_view_background"}, timeout_seconds=1.0):
            raise RuntimeError("Fossify Calendar did not return to month view after saving the event")

    def _ensure_organic_maps_ready(
        self,
        *,
        controller: Any,
        map_package: str,
        region_query: str,
        target_query: str,
        target_title: str,
    ) -> None:
        controller.execute_adb(["shell", "monkey", "-p", map_package, "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(2.0)

        driver = AndroidBootstrapDriver(controller, expected_package=map_package, settle_delay_seconds=0.7)
        self._dismiss_organic_maps_noise(driver)

        if self._organic_maps_has_target(driver, target_query=target_query, target_title=target_title):
            controller.execute_adb(["shell", "am", "force-stop", map_package])
            return

        self._open_organic_maps_search(driver)
        self._set_organic_maps_query(driver, region_query)

        driver.tap_selector(
            {"resource_id": "app.organicmaps.web:id/title", "text": region_query},
            timeout_seconds=5.0,
        )
        if driver.node_exists({"resource_id": "app.organicmaps.web:id/downloader_status_frame"}, timeout_seconds=2.0):
            driver.tap_selector({"resource_id": "app.organicmaps.web:id/downloader_status_frame"}, timeout_seconds=2.0)
            self._wait_for_organic_maps_download(driver)

        driver.tap_if_present({"resource_id": "app.organicmaps.web:id/close_button"}, timeout_seconds=2.0)

        if not self._organic_maps_has_target(driver, target_query=target_query, target_title=target_title):
            raise RuntimeError(f"Organic Maps did not expose the target place {target_title!r}")

        controller.execute_adb(["shell", "am", "force-stop", map_package])

    def _organic_maps_has_target(
        self,
        driver: AndroidBootstrapDriver,
        *,
        target_query: str,
        target_title: str,
    ) -> bool:
        self._open_organic_maps_search(driver)
        self._set_organic_maps_query(driver, target_query)
        time.sleep(1.5)
        return driver.node_exists(
            {"resource_id": "app.organicmaps.web:id/title", "text_contains": target_title},
            timeout_seconds=3.0,
        )

    def _open_organic_maps_search(self, driver: AndroidBootstrapDriver) -> None:
        for _attempt in range(5):
            self._dismiss_organic_maps_noise(driver)
            if driver.node_exists({"resource_id": "app.organicmaps.web:id/query"}, timeout_seconds=1.0):
                return
            if driver.tap_if_present({"resource_id": "app.organicmaps.web:id/close_button"}, timeout_seconds=1.0):
                continue
            if driver.tap_if_present({"resource_id": "app.organicmaps.web:id/btn_search"}, timeout_seconds=1.0):
                time.sleep(1.0)
                if driver.node_exists({"resource_id": "app.organicmaps.web:id/query"}, timeout_seconds=1.0):
                    return
            driver.controller.press_back()
            time.sleep(1.0)

        raise RuntimeError("Failed to open the Organic Maps search screen")

    def _dismiss_organic_maps_noise(self, driver: AndroidBootstrapDriver) -> None:
        for _attempt in range(4):
            if self._handle_organic_maps_download_prompt(driver):
                continue
            if driver.tap_if_present(self._notification_deny_selectors(), timeout_seconds=1.0):
                continue
            if driver.tap_if_present({"text": "CLOSE"}, timeout_seconds=1.0):
                continue
            if driver.tap_if_present({"text": "Close"}, timeout_seconds=1.0):
                continue
            if driver.tap_if_present({"resource_id": "app.organicmaps.web:id/close_button"}, timeout_seconds=1.0):
                continue
            break

    def _handle_organic_maps_download_prompt(self, driver: AndroidBootstrapDriver) -> bool:
        button = driver.wait_for_node(
            {"resource_id": "app.organicmaps.web:id/btn_download_resources"},
            timeout_seconds=0.5,
            raise_on_timeout=False,
        )
        if button is None:
            return False

        deadline = time.time() + 45.0
        while time.time() < deadline:
            button = driver.wait_for_node(
                {"resource_id": "app.organicmaps.web:id/btn_download_resources"},
                timeout_seconds=0.5,
                raise_on_timeout=False,
            )
            progress = driver.wait_for_node(
                [
                    {"resource_id": "app.organicmaps.web:id/progressbar"},
                    {"resource_id": "app.organicmaps.web:id/downloader_progress_wheel"},
                    {"resource_id": "app.organicmaps.web:id/downloader_status_frame"},
                ],
                timeout_seconds=0.2,
                raise_on_timeout=False,
            )
            if button is None and progress is None:
                time.sleep(1.0)
                return True

            label = str((button or {}).get("text") or "").strip().upper()
            if label and label not in {"PAUSE", "CANCEL"}:
                tap = dict((button or {}).get("tap") or {})
                if tap:
                    driver.controller.tap(int(tap["x"]), int(tap["y"]))
            time.sleep(2.0)

        raise RuntimeError("Timed out while waiting for Organic Maps initial map download")

    def _set_organic_maps_query(self, driver: AndroidBootstrapDriver, query: str) -> None:
        query_node = driver.wait_for_node(
            {"resource_id": "app.organicmaps.web:id/query"},
            timeout_seconds=5.0,
        )
        tap = dict(query_node.get("tap") or {})
        if not tap:
            raise RuntimeError("Organic Maps query field is missing tap coordinates")

        for _attempt in range(3):
            driver.controller.tap(int(tap["x"]), int(tap["y"]))
            time.sleep(0.5)
            driver.controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_MOVE_END"])
            time.sleep(0.1)
            self._send_repeated_keyevent(driver.controller, "KEYCODE_DEL", 36)
            driver.controller.input_text(query)
            time.sleep(1.2)
            current = driver.wait_for_node(
                {"resource_id": "app.organicmaps.web:id/query"},
                timeout_seconds=2.0,
                raise_on_timeout=False,
            )
            if str((current or {}).get("text") or "").strip() == query:
                return

        raise RuntimeError(f"Failed to set Organic Maps query to {query!r}")

    @staticmethod
    def _send_repeated_keyevent(controller: Any, keycode: str, times: int, *, chunk_size: int = 40) -> None:
        remaining = max(times, 0)
        while remaining:
            chunk = min(remaining, chunk_size)
            controller.execute_adb(["shell", "input", "keyevent", *([keycode] * chunk)])
            remaining -= chunk

    @staticmethod
    def _wait_for_organic_maps_download(driver: AndroidBootstrapDriver) -> None:
        deadline = time.time() + 45.0
        while time.time() < deadline:
            progress_visible = driver.node_exists(
                {"resource_id": "app.organicmaps.web:id/downloader_progress_wheel"},
                timeout_seconds=1.0,
            )
            status_visible = driver.node_exists(
                {"resource_id": "app.organicmaps.web:id/downloader_status_frame"},
                timeout_seconds=1.0,
            )
            if not progress_visible and not status_visible:
                return
            time.sleep(1.0)

        raise RuntimeError("Timed out while waiting for Organic Maps to finish downloading Monaco")

    @staticmethod
    def _notification_deny_selectors() -> list[dict[str, str]]:
        return [
            {"resource_id": "com.android.permissioncontroller:id/permission_deny_button"},
            {"resource_id": "com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button"},
            {"text": "DON’T ALLOW"},
            {"text": "Don't allow"},
            {"text": "DENY"},
        ]
