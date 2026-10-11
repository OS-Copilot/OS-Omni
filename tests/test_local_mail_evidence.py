"""Focused mocked tests for read-only GreenMail admin evidence (2.1.14).

Covers ``core.evidence.local_mail``: loopback-only base URLs, fake
``.test`` user enforcement (never ``GET /api/user``), bounded response and
MIME truncation with SHA256 integrity, per-target errors that never affect
the verdict, and absence of passwords/keys/headers in stored artifacts. All
HTTP is faked in-process; no GreenMail, network, GUI, model, or credential
use, and mail bodies are synthetic fixtures only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

from core.evidence import local_mail


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, limit: int = -1) -> bytes:
        if limit is not None and limit >= 0:
            return self._payload[:limit]
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _opener(payloads: dict[str, bytes], calls: list[str], *, error: Any = None):
    def _open(request: Any, timeout: Any = None) -> _FakeResponse:
        calls.append(request.full_url)
        assert request.get_method() == "GET", "evidence must be GET-only"
        assert request.data is None, "evidence must send no body"
        if error is not None:
            raise error
        for key, payload in payloads.items():
            if request.full_url.endswith(key):
                return _FakeResponse(payload)
        raise HTTPError(request.full_url, 404, "missing", None, None)

    return _open


def _message(uid: int, subject: str = "s") -> dict[str, Any]:
    return {
        "uid": uid,
        "messageId": f"<{uid}@example.test>",
        "subject": subject,
        "contentType": "text/plain",
        "mimeMessage": f"From: a@example.test\r\nSubject: {subject}\r\n\r\nbody-{uid}",
    }


TARGETS = [
    {"email": "benchrecv@example.test", "folder": "INBOX"},
    {"email": "planbox@mail.test", "folder": "INBOX"},
]


def test_non_loopback_base_url_rejected(tmp_path: Path) -> None:
    for bad in (
        "http://192.168.1.10:8081",
        "http://example.com:8081",
        "http://127.0.0.1.evil.com/",
        "ftp://127.0.0.1/",
        "http://user:pass@127.0.0.1:8081/",
        "",
    ):
        with pytest.raises(ValueError):
            local_mail.capture_local_mail_evidence(
                base_url=bad, targets=TARGETS, output_dir=tmp_path
            )


def test_non_test_user_rejected_and_user_list_never_called(tmp_path: Path) -> None:
    calls: list[str] = []
    opener = _opener({}, calls)
    with pytest.raises(ValueError):
        local_mail.capture_local_mail_evidence(
            base_url="http://127.0.0.1:8081",
            targets=[{"email": "someone@real.com", "folder": "INBOX"}],
            output_dir=tmp_path,
            urlopen=opener,
        )
    assert calls == []
    with pytest.raises(ValueError):
        local_mail.discover_maily_targets([{"mailbox": "someone@real.com"}])


def test_maily_discovery_uses_specs_without_guessing() -> None:
    specs = [
        {"mailbox": "planbox@mail.test"},
        {"mailbox": "benchrecv@example.test"},
        {"mailbox": "planbox@mail.test"},
    ]
    assert local_mail.discover_maily_targets(specs) == [
        {"email": "benchrecv@example.test", "folder": "INBOX"},
        {"email": "planbox@mail.test", "folder": "INBOX"},
    ]


def test_capture_writes_bounded_json_and_mime_with_hashes(tmp_path: Path) -> None:
    payloads = {
        "/api/user/benchrecv%40example.test/messages/INBOX": json.dumps(
            [_message(11), _message(12)]
        ).encode(),
        "/api/user/planbox%40mail.test/messages/INBOX": json.dumps([]).encode(),
    }
    calls: list[str] = []
    manifest = local_mail.capture_local_mail_evidence(
        base_url="http://127.0.0.1:8081",
        targets=TARGETS,
        output_dir=tmp_path,
        urlopen=_opener(payloads, calls),
    )
    assert manifest["evidence_kind"] == "administrative-local-mail"
    assert manifest["for_decision_system"] is False
    assert manifest["mailbox_message_counts"] == {
        "benchrecv@example.test/INBOX": 2,
        "planbox@mail.test/INBOX": 0,
    }
    assert manifest["errors"] == []
    assert all("/api/user" in url and "/messages/" in url for url in calls)
    assert not any(url.rstrip("/").endswith("/api/user") for url in calls)

    evidence_dir = tmp_path / local_mail.EVIDENCE_DIRNAME
    for entry in manifest["files"]:
        stored = (evidence_dir / entry["path"]).read_bytes()
        assert entry["sha256"] == _sha(stored)
        assert entry["size"] == len(stored)
        assert entry["truncated"] is False
    assert (evidence_dir / local_mail.MANIFEST_NAME).is_file()
    dumped = json.dumps(manifest)
    assert "password" not in dumped.lower()
    assert "api_key" not in dumped.lower() and "apikey" not in dumped.lower()


def test_oversized_response_truncated_and_reported(tmp_path: Path) -> None:
    big = json.dumps([_message(1)]).encode() + b"x" * 4096
    payloads = {"/messages/INBOX": big}
    calls: list[str] = []
    manifest = local_mail.capture_local_mail_evidence(
        base_url="http://localhost:8081",
        targets=[{"email": "benchrecv@example.test", "folder": "INBOX"}],
        output_dir=tmp_path,
        max_response_bytes=64,
        urlopen=_opener(payloads, calls),
    )
    raw_entry = manifest["files"][0]
    assert raw_entry["truncated"] is True
    assert raw_entry["size"] == 64
    assert manifest["errors"] == [
        {"target": "benchrecv@example.test/INBOX", "reason": "response-size-exceeded"}
    ]
    assert manifest["mailbox_message_counts"]["benchrecv@example.test/INBOX"] == 0


def test_oversized_mime_truncated_per_message(tmp_path: Path) -> None:
    msg = _message(7)
    msg["mimeMessage"] = "A" * 1024
    payloads = {"/messages/INBOX": json.dumps([msg]).encode()}
    manifest = local_mail.capture_local_mail_evidence(
        base_url="http://127.0.0.1:8081",
        targets=[{"email": "benchrecv@example.test", "folder": "INBOX"}],
        output_dir=tmp_path,
        max_mime_bytes=16,
        urlopen=_opener(payloads, []),
    )
    eml = [entry for entry in manifest["files"] if entry["path"].endswith(".eml")]
    assert len(eml) == 1 and eml[0]["size"] == 16 and eml[0]["truncated"] is True
    stored = (tmp_path / local_mail.EVIDENCE_DIRNAME / eml[0]["path"]).read_bytes()
    assert stored == b"A" * 16 and eml[0]["sha256"] == _sha(stored)
    assert manifest["errors"] == [
        {"target": "benchrecv@example.test/INBOX/uid-7", "reason": "mime-size-exceeded"}
    ]


def test_http_error_recorded_without_verdict_effect(tmp_path: Path) -> None:
    good = json.dumps([_message(3)]).encode()
    calls: list[str] = []

    def _open(request: Any, timeout: Any = None) -> _FakeResponse:
        calls.append(request.full_url)
        if "planbox" in request.full_url:
            raise HTTPError(request.full_url, 500, "boom", None, None)
        return _FakeResponse(good)

    manifest = local_mail.capture_local_mail_evidence(
        base_url="http://127.0.0.1:8081", targets=TARGETS, output_dir=tmp_path, urlopen=_open
    )
    assert manifest["mailbox_message_counts"]["benchrecv@example.test/INBOX"] == 1
    assert {"target": "planbox@mail.test/INBOX", "reason": "HTTPError"} in manifest["errors"]
    assert len([entry for entry in manifest["files"] if entry["path"].endswith(".eml")]) == 1


def test_opt_in_wrapper_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(local_mail.CAPTURE_ENV_VAR, raising=False)
    assert (
        local_mail.maybe_capture_local_mail_evidence(
            base_url="http://127.0.0.1:8081", targets=TARGETS, output_dir=tmp_path
        )
        is None
    )
    assert not (tmp_path / local_mail.EVIDENCE_DIRNAME).exists()


def test_task_eval_params_discovery_reads_file_without_guessing(tmp_path: Path) -> None:
    task = tmp_path / "task.yaml"
    task.write_text(
        "task_id: ios.maily.instruction_3_1\n"
        "evaluation:\n"
        "  evaluator_id: evaluators.ios.maily_instruction_3_1:MailyInstruction31StateEvaluator\n"
        "  params:\n"
        "    api_base_url: http://127.0.0.1:8081\n",
        encoding="utf-8",
    )
    params = local_mail.discover_task_eval_params(task)
    assert params["task_id"] == "ios.maily.instruction_3_1"
    assert "maily_instruction_3_1" in params["evaluator_id"]
    assert params["params"].get("api_base_url") == "http://127.0.0.1:8081"

@pytest.mark.parametrize("suffix", [1, 2, 3])
def test_task_capture_uses_actual_evaluator_mailboxes(tmp_path, monkeypatch, suffix):
    monkeypatch.setenv(local_mail.CAPTURE_ENV_VAR, "1")
    seen = {}
    def capture(**kwargs):
        seen.update(kwargs)
        return {"errors": [], "for_decision_system": False}
    monkeypatch.setattr(local_mail, "capture_local_mail_evidence", capture)
    task = Path(__file__).resolve().parents[1] / f"tasks/v1/ios/maily_instruction_3_{suffix}.yaml"
    result = local_mail.capture_task_local_mail_evidence(task_file=task, output_dir=tmp_path)
    assert result["errors"] == []
    assert seen["base_url"] == "http://127.0.0.1:8081"
    emails = {target["email"] for target in seen["targets"]}
    assert "alex.rivera@example.test" in emails
    assert all(email.endswith(".test") for email in emails)
    assert len(emails) >= 3

def test_task_capture_disabled_does_not_read_task(tmp_path, monkeypatch):
    monkeypatch.delenv(local_mail.CAPTURE_ENV_VAR, raising=False)
    assert local_mail.capture_task_local_mail_evidence(task_file=tmp_path / "missing", output_dir=tmp_path) is None

def test_default_capture_preserves_large_attachment_mime(tmp_path):
    mime = "MIME-Version: 1.0\r\n\r\n" + "A" * (700 * 1024)
    data = json.dumps([{"uid": 1, "mimeMessage": mime}]).encode()
    manifest = local_mail.capture_local_mail_evidence(
        base_url="http://127.0.0.1:8081", targets=[{"email": "photo@example.test"}],
        output_dir=tmp_path, urlopen=_opener({"http://127.0.0.1:8081/api/user/photo%40example.test/messages/INBOX": data}, []))
    assert not manifest["errors"]
    eml = next((tmp_path / local_mail.EVIDENCE_DIRNAME).glob("*.eml"))
    assert eml.read_bytes() == mime.encode()

def test_ios_parent_hook_keeps_mail_evidence_admin_only(tmp_path, monkeypatch):
    from platforms.ios.runners import benchmark
    monkeypatch.setenv(benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    calls = []
    def simulator_capture(**kwargs):
        calls.append("simulator")
        return {"errors": [], "success": False}
    def mail_capture(**kwargs):
        calls.append("mail")
        assert kwargs["output_dir"] == tmp_path
        return {"errors": [], "for_decision_system": False}
    monkeypatch.setattr(benchmark, "capture_ios_final_state", simulator_capture)
    monkeypatch.setattr(local_mail, "capture_task_local_mail_evidence", mail_capture)
    result = benchmark.IOSBenchmarkRunner()._maybe_capture_ios_final_state(
        udid="fixture", task_id="ios.maily.instruction_3_1", task_file="fixture.yaml",
        model_output_dir=tmp_path, run_index=1, success=False, return_code=1)
    assert calls == ["simulator", "mail"]
    assert result["success"] is False
    assert result["local_mail_evidence"]["for_decision_system"] is False
