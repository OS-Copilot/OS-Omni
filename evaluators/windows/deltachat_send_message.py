"""Evaluator for Windows Delta Chat send-message tasks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from email.parser import Parser
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class DeltaChatSendMessageEvaluator(BaseEvaluator):
    """Validate that Delta Chat delivered the expected message(s) to GreenMail."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    LOCAL_API_BASE_URL = "http://127.0.0.1:8081"
    FALLBACK_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_MAILBOX = "INBOX"
    DEFAULT_TIMEOUT_SECONDS = 20.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0
    AUTO_START_GREENMAIL_ENV = "HELLOWORLD_AUTO_START_GREENMAIL"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        allow_missing_greenmail = bool(params.get("allow_missing_greenmail", False))
        controller = context.get("controller")
        proof_path = str(params.get("proof_path") or "").strip()

        requested_api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        try:
            api_base_url = self._resolve_api_base_url(requested_api_base_url)
            greenmail_error = ""
        except Exception as exc:
            if not allow_missing_greenmail:
                raise
            api_base_url = requested_api_base_url or self.DEFAULT_API_BASE_URL
            greenmail_error = f"{type(exc).__name__}: {exc}"
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        expected_messages = self._normalize_expected_messages(params)
        if not expected_messages:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params expected_messages (or recipient_email/body) are required",
            )

        if greenmail_error:
            return self._evaluate_from_proof(
                controller=controller,
                proof_path=proof_path,
                expected_messages=expected_messages,
                greenmail_error=greenmail_error,
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_messages_by_recipient: dict[str, list[dict[str, Any]]] = {}
        recipients = list(dict.fromkeys(item["recipient_email"] for item in expected_messages))

        while True:
            attempts += 1
            try:
                last_messages_by_recipient = {
                    recipient_email: self._fetch_mailbox_messages(
                        api_base_url=api_base_url,
                        recipient_email=recipient_email,
                        mailbox=mailbox,
                    )
                    for recipient_email in recipients
                }
            except Exception as exc:
                if allow_missing_greenmail:
                    return self._evaluate_from_proof(
                        controller=controller,
                        proof_path=proof_path,
                        expected_messages=expected_messages,
                        greenmail_error=f"{type(exc).__name__}: {exc}",
                    )
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query GreenMail: {type(exc).__name__}: {exc}",
                    metadata={"api_base_url": api_base_url},
                )

            missing = [
                item
                for item in expected_messages
                if self._find_matching_message(
                    messages=last_messages_by_recipient.get(item["recipient_email"], []),
                    recipient_email=item["recipient_email"],
                    sender_email=item.get("sender_email", ""),
                    body=item["body"],
                )
                is None
            ]
            if not missing:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Expected Delta Chat message(s) were delivered to GreenMail",
                    metadata={
                        "attempts": attempts,
                        "expected_messages": expected_messages,
                    },
                )

            if time.time() >= deadline:
                break

            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Expected Delta Chat message(s) were not found in GreenMail",
            metadata={
                "attempts": attempts,
                "missing": missing,
                "mailbox_sizes": {
                    recipient_email: len(messages)
                    for recipient_email, messages in last_messages_by_recipient.items()
                },
            },
        )

    @staticmethod
    def _evaluate_from_proof(
        *,
        controller: Any,
        proof_path: str,
        expected_messages: list[dict[str, Any]],
        greenmail_error: str,
    ) -> EvalResult:
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"GreenMail unavailable and controller.run_python_script missing: {greenmail_error}",
            )
        if not proof_path:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"GreenMail unavailable and proof_path missing: {greenmail_error}",
            )

        code = f"""
import json
from pathlib import Path

proof_path = Path({proof_path!r})
expected_messages = {expected_messages!r}
if not proof_path.exists():
    raise SystemExit(json.dumps({{"error": "proof missing", "path": str(proof_path)}}))

payload = json.loads(proof_path.read_text(encoding="utf-8"))
messages = payload.get("messages", [])
missing = []
for expected in expected_messages:
    found = False
    for item in messages:
        if str(item.get("recipient_email") or "") != str(expected.get("recipient_email") or ""):
            continue
        if str(item.get("body") or "") != str(expected.get("body") or ""):
            continue
        sender_expected = str(expected.get("sender_email") or "")
        if sender_expected and str(item.get("sender_email") or "") != sender_expected:
            continue
        found = True
        break
    if not found:
        missing.append(expected)

print(json.dumps({{"path": str(proof_path), "missing": missing, "message_count": len(messages)}}))
"""
        result = controller.run_python_script(code)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"GreenMail unavailable and oracle proof validation failed: {greenmail_error}",
                metadata={"proof_output": output, "proof_path": proof_path},
            )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = {"raw_output": output}
        missing = payload.get("missing") or []
        if missing:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="GreenMail unavailable and oracle proof did not contain all expected Delta Chat messages",
                metadata={"proof": payload, "greenmail_error": greenmail_error},
            )
        return EvalResult(
            status=EvalStatus.PASS,
            message="GreenMail unavailable; oracle proof matched expected Delta Chat messages",
            metadata={"proof": payload, "greenmail_error": greenmail_error, "delivery_skipped": True},
        )

    @staticmethod
    def _normalize_expected_messages(params: Mapping[str, Any]) -> list[dict[str, Any]]:
        expected_messages: list[dict[str, Any]] = []
        raw_expected = params.get("expected_messages")
        if isinstance(raw_expected, list):
            for item in raw_expected:
                if not isinstance(item, Mapping):
                    continue
                recipient = str(item.get("recipient_email") or "").strip()
                body = str(item.get("body") or "").strip()
                if not recipient or not body:
                    continue
                expected_messages.append(
                    {
                        "recipient_email": recipient,
                        "body": body,
                        "sender_email": str(item.get("sender_email") or "").strip(),
                    }
                )
            if expected_messages:
                return expected_messages

        recipient_email = str(params.get("recipient_email") or "").strip()
        body = str(params.get("body") or "").strip()
        sender_email = str(params.get("sender_email") or "").strip()
        if recipient_email and body:
            expected_messages.append(
                {
                    "recipient_email": recipient_email,
                    "body": body,
                    "sender_email": sender_email,
                }
            )

        recipients = params.get("recipient_emails")
        if isinstance(recipients, list) and body:
            for recipient in recipients:
                recipient_str = str(recipient or "").strip()
                if recipient_str:
                    expected_messages.append(
                        {
                            "recipient_email": recipient_str,
                            "body": body,
                            "sender_email": sender_email,
                        }
                    )

        return expected_messages

    @staticmethod
    def _fetch_mailbox_messages(
        *,
        api_base_url: str,
        recipient_email: str,
        mailbox: str,
    ) -> list[dict[str, Any]]:
        encoded_user = quote(recipient_email, safe="")
        encoded_mailbox = quote(mailbox, safe="")
        request = Request(
            f"{api_base_url}/api/user/{encoded_user}/messages/{encoded_mailbox}",
            method="GET",
        )
        try:
            with urlopen(request, timeout=5.0) as response:
                payload = response.read()
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"GET mailbox failed: {exc}") from exc

        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, list):
            raise RuntimeError(f"GreenMail mailbox payload must be a list, got {type(data)!r}")
        return [msg for msg in data if isinstance(msg, dict)]

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
                request = Request(f"{candidate}/api/service/readiness", method="GET")
                try:
                    with urlopen(request, timeout=5.0) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    if isinstance(payload, dict) and payload.get("message") == "Service running":
                        return candidate
                    errors.append(f"{candidate}: unexpected readiness payload {payload!r}")
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
    def _find_matching_message(
        *,
        messages: list[dict[str, Any]],
        recipient_email: str,
        sender_email: str,
        body: str,
    ) -> dict[str, Any] | None:
        for message in messages:
            mime_message = str(message.get("mimeMessage") or "")
            headers = Parser().parsestr(mime_message, headersonly=True)
            to_headers = headers.get_all("To", [])
            from_headers = headers.get_all("From", [])

            if not any(recipient_email.lower() in header.lower() for header in to_headers):
                continue
            if sender_email and not any(sender_email.lower() in header.lower() for header in from_headers):
                continue
            if body not in mime_message:
                continue
            return message
        return None
