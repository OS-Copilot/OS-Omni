"""Windows initializer for Delta Chat + GreenMail tasks."""

from __future__ import annotations

import json
import os
import smtplib
import subprocess
import time
from email.message import EmailMessage
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus


class DeltaChatSendMessageInitializer(BaseInitializer):
    """Prepare Delta Chat tasks by purging GreenMail, seeding a chat, and launching Delta Chat."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    LOCAL_API_BASE_URL = "http://127.0.0.1:8081"
    FALLBACK_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_PROFILE_ARCHIVE = "files/deltachat/profile.zip"
    DEFAULT_WAIT_MS = 1500
    AUTO_START_GREENMAIL_ENV = "HELLOWORLD_AUTO_START_GREENMAIL"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        task = context.get("task")

        if controller is None or not hasattr(controller, "launch_app"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.launch_app is required for Delta Chat initialization",
            )
        if not hasattr(controller, "run_powershell_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_powershell_script is required")
        if not hasattr(controller, "upload_file"):
            return InitResult(status=InitStatus.ERROR, message="controller.upload_file is required")

        requested_api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        api_base_url = requested_api_base_url
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_greenmail = bool(params.get("purge_greenmail", True))
        allow_missing_greenmail = bool(params.get("allow_missing_greenmail", False))
        profile_archive = str(params.get("profile_archive_path") or self.DEFAULT_PROFILE_ARCHIVE).strip()
        profile_archive_local = self._resolve_local_path(profile_archive, task=task)

        seed_sender_email = str(params.get("seed_sender_email") or "").strip()
        seed_sender_password = str(params.get("seed_sender_password") or "").strip()
        seed_recipient_email = str(params.get("seed_recipient_email") or "").strip()
        seed_subject = str(params.get("seed_subject") or "").strip()
        seed_body = str(params.get("seed_body") or "").strip()
        seed_smtp_host = str(params.get("seed_smtp_host") or "127.0.0.1").strip()
        seed_smtp_port = int(params.get("seed_smtp_port") or 3025)

        greenmail_available = True
        try:
            if not profile_archive_local.exists():
                raise FileNotFoundError(f"Delta Chat profile archive not found: {profile_archive_local}")
            remote_profile_archive = r"C:\Users\User\AppData\Local\Temp\deltachat-profile.zip"
            controller.upload_file(str(profile_archive_local), remote_profile_archive)
            restore_result = controller.run_powershell_script(
                self._build_profile_restore_script(remote_profile_archive),
                timeout=60,
            )
            returncode = int(restore_result.get("returncode", 0))
            if returncode != 0:
                raise RuntimeError(
                    str(restore_result.get("error") or restore_result.get("output") or "").strip()
                    or f"Delta Chat profile restore failed with exit code {returncode}"
                )

            if purge_greenmail:
                try:
                    api_base_url = self._resolve_api_base_url(requested_api_base_url)
                    self._purge_greenmail(api_base_url)
                    seed_smtp_host = self._resolve_seed_smtp_host(seed_smtp_host, api_base_url)
                except Exception:
                    greenmail_available = False
                    if not allow_missing_greenmail:
                        raise

            if (
                seed_sender_email
                and seed_sender_password
                and seed_recipient_email
                and seed_subject
                and seed_body
            ):
                try:
                    self._seed_existing_chat(
                        smtp_host=seed_smtp_host,
                        smtp_port=seed_smtp_port,
                        sender_email=seed_sender_email,
                        sender_password=seed_sender_password,
                        recipient_email=seed_recipient_email,
                        subject=seed_subject,
                        body=seed_body,
                    )
                except Exception:
                    greenmail_available = False
                    if not allow_missing_greenmail:
                        raise

            launch_result = controller.run_powershell_script(
                self._build_launch_script(),
                timeout=30,
            )
            launch_returncode = int(launch_result.get("returncode", 0))
            if launch_returncode != 0:
                raise RuntimeError(
                    str(launch_result.get("error") or launch_result.get("output") or "").strip()
                    or f"Delta Chat launch failed with exit code {launch_returncode}"
                )

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Delta Chat task: {type(exc).__name__}: {exc}",
                metadata={"api_base_url": api_base_url},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="GreenMail prepared and Delta Chat opened",
            metadata={
                "api_base_url": api_base_url,
                "wait_ms": wait_ms,
                "purge_greenmail": purge_greenmail,
                "allow_missing_greenmail": allow_missing_greenmail,
                "greenmail_available": greenmail_available,
                "profile_archive": str(profile_archive_local),
                "seed_sender_email": seed_sender_email,
                "seed_recipient_email": seed_recipient_email,
            },
        )

    @staticmethod
    def _resolve_local_path(raw_path: str, *, task: Any) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        task_source = getattr(task, "source_file", None)
        if task_source:
            candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
            if candidate.exists():
                return candidate
        return (Path.cwd() / path).resolve()

    @staticmethod
    def _build_profile_restore_script(remote_archive: str) -> str:
        return dedent(
            f"""
            $ErrorActionPreference = "Stop"

            Get-Process -Name "DeltaChat" -ErrorAction SilentlyContinue |
              Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 800

            $tempRoot = Join-Path $env:TEMP "helloworld-deltachat-profile"
            $profileRoot = Join-Path $env:LOCALAPPDATA "DeltaChat"
            $roamingRoot = Join-Path $env:APPDATA "DeltaChat"

            foreach ($path in @($tempRoot, $profileRoot, $roamingRoot)) {{
              if (Test-Path $path) {{
                Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
              }}
            }}

            New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
            Expand-Archive -LiteralPath "{remote_archive}" -DestinationPath $tempRoot -Force

            $expandedRoot = Join-Path $tempRoot "DeltaChat"
            if (-not (Test-Path $expandedRoot)) {{
              $expandedRoot = $tempRoot
            }}
            $db = Get-ChildItem -LiteralPath $expandedRoot -Recurse -Filter "dc.db" -File -ErrorAction SilentlyContinue |
              Select-Object -First 1
            if (-not $db) {{
              throw "Delta Chat profile archive does not contain accounts\\<id>\\dc.db"
            }}

            Copy-Item -LiteralPath $expandedRoot -Destination $profileRoot -Recurse -Force

            Write-Output "DELTACHAT_PROFILE_RESTORE_OK=True"
            Write-Output "DELTACHAT_PROFILE_ROOT=$profileRoot"
            """
        ).strip()

    @staticmethod
    def _build_launch_script() -> str:
        return dedent(
            r"""
            $ErrorActionPreference = "Stop"
            $candidates = @(
              "C:\Program Files\DeltaChat\DeltaChat.exe",
              "$env:LOCALAPPDATA\Programs\DeltaChat\DeltaChat.exe",
              "$env:USERPROFILE\Desktop\DeltaChat.lnk",
              "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\DeltaChat.lnk"
            )
            $target = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
            if (-not $target) {
              throw "Delta Chat executable or shortcut not found"
            }
            Start-Process -FilePath $target -WindowStyle Normal | Out-Null
            Write-Output "DELTACHAT_LAUNCH_OK=True"
            """
        ).strip()

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = DeltaChatSendMessageInitializer._request_json(
            f"{api_base_url}/api/service/readiness",
            method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @classmethod
    def _resolve_api_base_url(cls, api_base_url: str) -> str:
        candidates: list[str] = []
        if api_base_url:
            candidates.append(api_base_url.rstrip("/"))
        local = cls.LOCAL_API_BASE_URL.rstrip("/")
        if local not in candidates:
            candidates.append(local)
        fallback = cls.FALLBACK_API_BASE_URL.rstrip("/")
        if fallback not in candidates:
            candidates.append(fallback)

        errors: list[str] = []
        for attempt in range(2):
            errors.clear()
            for candidate in candidates:
                try:
                    cls._ensure_greenmail_ready(candidate)
                    return candidate
                except Exception as exc:
                    errors.append(f"{candidate}: {exc}")

            if attempt == 0 and cls._should_auto_start_greenmail():
                start_error = cls._try_start_greenmail()
                if start_error:
                    errors.append(f"auto-start GreenMail failed: {start_error}")
                else:
                    time.sleep(1.0)
                    continue
            break

        raise RuntimeError(" ; ".join(errors))

    @classmethod
    def _should_auto_start_greenmail(cls) -> bool:
        raw = os.environ.get(cls.AUTO_START_GREENMAIL_ENV, "true").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    @staticmethod
    def _try_start_greenmail() -> str:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "start_greenmail_no_docker.ps1"
        if not script.exists():
            return f"script not found: {script}"

        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                cwd=str(repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

        if completed.returncode != 0:
            output = (completed.stdout or "").strip()
            return output[-1000:] or f"exit code {completed.returncode}"
        return ""

    @staticmethod
    def _resolve_seed_smtp_host(seed_smtp_host: str, api_base_url: str) -> str:
        if seed_smtp_host and seed_smtp_host != "127.0.0.1":
            return seed_smtp_host
        parsed = urlparse(api_base_url)
        return parsed.hostname or seed_smtp_host

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        DeltaChatSendMessageInitializer._request_json(
            f"{api_base_url}/api/mail/purge",
            method="POST",
            allow_empty=True,
        )

    @staticmethod
    def _seed_existing_chat(
        *,
        smtp_host: str,
        smtp_port: int,
        sender_email: str,
        sender_password: str,
        recipient_email: str,
        subject: str,
        body: str,
    ) -> None:
        message = EmailMessage()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = subject
        message["Chat-Version"] = "1.0"
        message.set_content(body)

        with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=10.0) as client:
            client.login(sender_email, sender_password)
            client.send_message(message)

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
