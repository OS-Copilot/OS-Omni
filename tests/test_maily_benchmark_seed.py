"""Isolated mocked tests for the Maily baseline seeder.

Static implementation checks plus fully mocked initializer runs. No network,
no simulator, no GreenMail, no model calls: ``smtplib.SMTP``, the module's
``urlopen``, the reused GreenMail helpers, and the iOS controller are all
faked. The evaluators' pure constants are the oracle throughout.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from evaluators.ios import maily_instruction_3_1 as e31
from evaluators.ios import maily_instruction_3_2 as e32
from evaluators.ios import maily_instruction_3_3 as e33
from initializers.ios import maily_benchmark_seed as seed_mod
from initializers.ios.maily_benchmark_seed import MailyBenchmarkSeedInitializer

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "tasks" / "v1" / "ios"


def _load_asset_script():
    path = REPO / "scripts" / "prepare_maily_assets.py"
    spec = importlib.util.spec_from_file_location("prepare_maily_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assets_mod = _load_asset_script()

PASSWORD = "bench-secret-pw"
SENDER = "alex.rivera@example.test"


# ---------------------------------------------------------------------------
# Grounding: seed specs preserve the original evaluator identities.
# ---------------------------------------------------------------------------

def test_sender_identity_matches_all_three_evaluators() -> None:
    assert seed_mod.SENDER_EMAIL == e31.SENDER == e32.SENDER_EMAIL == e33.SENDER_EMAIL


def test_task_yaml_ids_match_module_tasks() -> None:
    for filename, task_id in (
        ("maily_instruction_3_1.yaml", seed_mod.TASK_3_1),
        ("maily_instruction_3_2.yaml", seed_mod.TASK_3_2),
        ("maily_instruction_3_3.yaml", seed_mod.TASK_3_3),
    ):
        payload = yaml.safe_load((TASKS / filename).read_text(encoding="utf-8"))
        assert payload["task_id"] == task_id


def test_3_1_seed_ids_match_original_fragments() -> None:
    expected = {
        str(spec["source_subject"]): f"<{spec['source_message_id_fragment']}>"
        for spec in e31.CHECKPOINT_SPECS
        if spec.get("source_message_id_fragment")
    }
    assert len(expected) == 7
    observed = {spec["subject"]: spec["message_id"] for spec in seed_mod.SEED_SPECS[seed_mod.TASK_3_1]}
    assert observed == expected


def test_3_2_seed_ids_contain_original_references() -> None:
    expected = {
        str(spec["source_subject"]): str(spec["source_reference"])
        for spec in e32.CHECKPOINT_SPECS
        if spec.get("source_reference")
    }
    assert len(expected) == 7
    for spec in seed_mod.SEED_SPECS[seed_mod.TASK_3_2]:
        reference = expected[spec["subject"]]
        assert spec["source_reference"] == reference
        # The verifier checks the reference as a whitespace-stripped,
        # case-folded substring of the reply's In-Reply-To/References.
        assert reference in spec["message_id"].casefold().replace(" ", "")


def test_3_3_seed_ids_match_original_message_ids() -> None:
    expected = {
        str(spec["source_subject"]): str(spec["source_message_id"])
        for spec in e33.MESSAGE_SPECS
        if spec.get("source_message_id")
    }
    assert len(expected) == 5
    observed = {spec["subject"]: spec["message_id"] for spec in seed_mod.SEED_SPECS[seed_mod.TASK_3_3]}
    assert observed == expected


def test_seed_bodies_use_quoted_convention() -> None:
    for task_id, specs in seed_mod.SEED_SPECS.items():
        for spec in specs:
            assert spec["body"] == f"Seed body for {spec['subject']}."


def test_target_recipients_preserve_original_addresses() -> None:
    expected = (
        {str(spec["mailbox"]) for spec in e31.CHECKPOINT_SPECS}
        | {str(spec["recipient"]) for spec in e32.CHECKPOINT_SPECS}
        | {str(spec["mailbox"]) for spec in e33.MESSAGE_SPECS}
    )
    assert set(seed_mod.ALL_TARGET_RECIPIENTS) == expected


# ---------------------------------------------------------------------------
# Seeds are inbound only: never the target final sent messages.
# ---------------------------------------------------------------------------

def test_seeds_are_inbound_only_and_disjoint_from_targets() -> None:
    for task_id in seed_mod.TASK_IDS:
        seed_subjects = {spec["subject"] for spec in seed_mod.SEED_SPECS[task_id]}
        target_subjects = {spec["subject"] for spec in seed_mod.TARGET_SPECS[task_id]}
        # No seed subject may equal a target subject: seeds live in the sender
        # INBOX, targets in the recipient mailboxes.
        assert seed_subjects.isdisjoint(target_subjects)
        # Every reply/forward target must link back to exactly one seed.
        for target in seed_mod.TARGET_SPECS[task_id]:
            if target["kind"] in ("reply", "forward"):
                assert target["source_subject"] in seed_subjects
            else:
                assert target["source_subject"] is None


def test_target_counts_match_original_evaluators() -> None:
    assert len(seed_mod.TARGET_SPECS[seed_mod.TASK_3_1]) == len(e31.CHECKPOINT_SPECS) == 10
    assert len(seed_mod.TARGET_SPECS[seed_mod.TASK_3_2]) == len(e32.CHECKPOINT_SPECS) == 9
    assert len(seed_mod.TARGET_SPECS[seed_mod.TASK_3_3]) == len(e33.MESSAGE_SPECS) == 9


def test_no_fourth_task_seed_spec() -> None:
    assert set(seed_mod.SEED_SPECS) == {seed_mod.TASK_3_1, seed_mod.TASK_3_2, seed_mod.TASK_3_3}
    assert set(seed_mod.TARGET_SPECS) == {seed_mod.TASK_3_1, seed_mod.TASK_3_2, seed_mod.TASK_3_3}


def test_build_seed_email_carries_exact_wire_headers() -> None:
    from email import message_from_bytes

    spec = seed_mod.SEED_SPECS[seed_mod.TASK_3_3][0]
    message = seed_mod.build_seed_email(spec=spec, seed_index=3)
    raw = message.as_bytes()
    # Ground truth is the wire: the byte-exact original ID must be present
    # verbatim (the doubled domain must survive serialization).
    assert spec["message_id"].encode("utf-8") in raw
    parsed = message_from_bytes(raw)
    assert parsed["Message-ID"] == spec["message_id"]
    assert parsed["Subject"] == spec["subject"]
    assert SENDER in str(parsed["From"])
    assert SENDER in str(parsed["To"])
    # Stable pre-run Date: the July baseline always predates any run window.
    assert "Jul 2026" in str(parsed["Date"])
    assert str(parsed.get_payload()).strip() == f"Seed body for {spec['subject']}."

    # Every task's every seed ID must survive the wire verbatim.
    for specs in seed_mod.SEED_SPECS.values():
        for item in specs:
            wire = seed_mod.build_seed_email(spec=item).as_bytes()
            assert item["message_id"].encode("utf-8") in wire


# ---------------------------------------------------------------------------
# Initializer behaviour, fully mocked.
# ---------------------------------------------------------------------------

def _failing_network(*args, **kwargs):
    raise AssertionError("network must not be touched on this path")


def _make_controller():
    calls: list[str] = []

    def _record(name):
        def _inner(*args, **kwargs):
            calls.append(name)
        return _inner

    controller = SimpleNamespace(
        runtime=SimpleNamespace(udid=""),
        terminate_app=_record("terminate_app"),
        press_home=_record("press_home"),
        activate_app=_record("activate_app"),
    )
    return controller, calls


@pytest.fixture
def quiet_sleep(monkeypatch):
    monkeypatch.setattr(seed_mod.time, "sleep", lambda _seconds: None)


def _assert_no_password_leak(result) -> None:
    blob = repr(result.to_dict())
    assert PASSWORD not in blob
    assert "password_provided" in blob  # only the boolean flag is recorded


def test_reset_requires_root_confirmation_and_touches_nothing(monkeypatch, quiet_sleep) -> None:
    monkeypatch.setattr(seed_mod.smtplib, "SMTP", _failing_network)
    monkeypatch.setattr(seed_mod, "urlopen", _failing_network)
    monkeypatch.setattr(
        seed_mod.GreenMailOpenAppInitializer, "_ensure_greenmail_ready", _failing_network
    )
    monkeypatch.setattr(seed_mod.GreenMailOpenAppInitializer, "_purge_greenmail", _failing_network)
    monkeypatch.setattr(seed_mod, "purge_local_state_for_bundle", _failing_network)

    controller, _ = _make_controller()
    result = MailyBenchmarkSeedInitializer().initialize(
        {
            "controller": controller,
            "params": {"task_id": seed_mod.TASK_3_1, "sender_password": PASSWORD},
        }
    )
    assert result.status.value == "FAIL"
    assert "greenmail_reset_confirmed" in (result.message or "")
    _assert_no_password_leak(result)


def test_missing_password_fails_without_side_effects(monkeypatch, quiet_sleep) -> None:
    monkeypatch.setattr(seed_mod.smtplib, "SMTP", _failing_network)
    monkeypatch.setattr(seed_mod, "urlopen", _failing_network)

    controller, calls = _make_controller()
    result = MailyBenchmarkSeedInitializer().initialize(
        {
            "controller": controller,
            "params": {"task_id": seed_mod.TASK_3_2, "greenmail_reset_confirmed": True},
        }
    )
    assert result.status.value == "FAIL"
    assert calls == []


def test_unknown_and_orphan_task_ids_fail(monkeypatch, quiet_sleep) -> None:
    monkeypatch.setattr(seed_mod.smtplib, "SMTP", _failing_network)
    monkeypatch.setattr(seed_mod, "urlopen", _failing_network)

    controller, _ = _make_controller()
    for bad_id in ("ios.maily.instruction_3_4", "ios.maily.nope"):
        result = MailyBenchmarkSeedInitializer().initialize(
            {"controller": controller, "params": {"task_id": bad_id, "sender_password": PASSWORD}}
        )
        assert result.status.value == "FAIL"


def test_full_mocked_seed_run_passes_and_stays_inbound(monkeypatch, quiet_sleep) -> None:
    sent: list[object] = []
    logins: list[tuple[str, str]] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            logins.append((user, password))

        def send_message(self, message):
            sent.append(message)

    class FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self._payload

    specs = seed_mod.seed_specs_for(seed_mod.TASK_3_3)
    mailbox_rows = [
        {"subject": spec["subject"], "Message-ID": spec["message_id"]} for spec in specs
    ]
    posted_users: list[dict[str, str]] = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        method = request.get_method()
        if url.endswith("/api/service/readiness"):
            return FakeResponse(json.dumps({"message": "Service running"}).encode())
        if url.endswith("/api/mail/purge"):
            return FakeResponse(b"")
        if url.endswith("/api/user") and method == "GET":
            return FakeResponse(json.dumps([]).encode())
        if url.endswith("/api/user") and method == "POST":
            body = json.loads((request.data or b"").decode("utf-8"))
            assert set(body) == {"email", "login", "password"}
            assert body["login"] == body["email"]
            assert body["password"] == PASSWORD
            posted_users.append(body)
            return FakeResponse(json.dumps({"email": body["email"], "login": body["login"]}).encode())
        if "/api/user/" in url and url.endswith("/messages/INBOX"):
            if url.split("/api/user/")[1].split("/messages")[0] == SENDER.replace("@", "%40"):
                return FakeResponse(json.dumps(mailbox_rows).encode())
            return FakeResponse(json.dumps([]).encode())
        raise AssertionError(f"unexpected {method} {url}")

    readiness_calls: list[str] = []
    purge_calls: list[str] = []

    def fake_ready(api_base_url: str) -> None:
        readiness_calls.append(api_base_url)

    def fake_purge(api_base_url: str) -> None:
        purge_calls.append(api_base_url)

    # The reused GreenMail helpers own their module's urlopen, so their
    # network layer is faked at their boundary; the seeder's own REST reads
    # go through the module-level urlopen fake above.
    monkeypatch.setattr(seed_mod.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(seed_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(seed_mod.GreenMailOpenAppInitializer, "_ensure_greenmail_ready", fake_ready)
    monkeypatch.setattr(seed_mod.GreenMailOpenAppInitializer, "_purge_greenmail", fake_purge)
    monkeypatch.setattr(
        seed_mod, "purge_local_state_for_bundle", lambda **kwargs: {"applied": False, "reason": "missing_udid"}
    )

    controller, calls = _make_controller()
    result = MailyBenchmarkSeedInitializer().initialize(
        {
            "controller": controller,
            "params": {
                "task_id": seed_mod.TASK_3_3,
                "sender_password": PASSWORD,
                "greenmail_reset_confirmed": True,
                "wait_ms": 0,
            },
        }
    )
    assert result.status.value == "PASS"
    assert result.metadata["seeded_message_count"] == 5
    # Provisioning ran after purge and before SMTP: sender + this task's
    # recipients created, baseline seeds still verify read-only.
    expected_needed = sorted({SENDER} | set(seed_mod.recipients_for(seed_mod.TASK_3_3)))
    assert result.metadata["provision_result"]["needed"] == expected_needed
    assert sorted(body["email"] for body in posted_users) == expected_needed
    assert result.metadata["verification"]["pass"] is True
    assert result.metadata["verification"]["seed_count"] == 5
    assert len(sent) == 5
    # The shared-host reset ran exactly once through the reused helpers.
    assert len(readiness_calls) == 1
    assert len(purge_calls) == 1
    # All seeds authenticate as the sender and land in the sender mailbox;
    # reply-source seeds carry the original sender the app's Reply must reach.
    assert logins and all(user == SENDER for user, _secret in logins)
    expected_from = [spec.get("sender", SENDER) for spec in specs]
    assert [message["From"] for message in sent] == expected_from
    assert [message["To"] for message in sent] == [SENDER] * len(sent)
    assert expected_from.count("benchsender@example.test") == 3
    assert "activate_app" in calls
    _assert_no_password_leak(result)


def _provision_fake_urlopen(monkeypatch, *, existing: list[str], inbox_rows: dict[str, list[dict]] | None = None,
                           fail_post: Exception | None = None):
    """Shared isolated HTTP fake for provisioning tests. Returns posted bodies."""
    from urllib.parse import unquote

    posted: list[dict[str, str]] = []
    inboxes = inbox_rows or {}

    class FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self._payload

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        method = request.get_method()
        if url.endswith("/api/user") and method == "GET":
            return FakeResponse(json.dumps([{"email": email, "login": email} for email in existing]).encode())
        if url.endswith("/api/user") and method == "POST":
            if fail_post is not None:
                raise fail_post
            body = json.loads((request.data or b"").decode("utf-8"))
            posted.append(body)
            return FakeResponse(json.dumps({"email": body["email"], "login": body["login"]}).encode())
        if "/api/user/" in url and url.endswith("/messages/INBOX"):
            encoded = url.split("/api/user/")[1].split("/messages")[0]
            email = unquote(encoded)
            return FakeResponse(json.dumps(inboxes.get(email, [])).encode())
        raise AssertionError(f"unexpected {method} {url}")

    monkeypatch.setattr(seed_mod, "urlopen", fake_urlopen)
    return posted


def test_recipients_for_covers_only_selected_task() -> None:
    for task_id in seed_mod.TASK_IDS:
        expected = sorted({str(spec["mailbox"]) for spec in seed_mod.TARGET_SPECS[task_id]})
        assert list(seed_mod.recipients_for(task_id)) == expected
    # 3_3 must not pull in 3_1-only / 3_2-only recipients.
    assert "benchrecv@example.test" not in seed_mod.recipients_for(seed_mod.TASK_3_3)
    assert "field3@mail.test" not in seed_mod.recipients_for(seed_mod.TASK_3_3)


def test_provisioning_posts_missing_users_with_openapi_shape(monkeypatch) -> None:
    posted = _provision_fake_urlopen(monkeypatch, existing=[])
    result = seed_mod.ensure_users_provisioned(
        api_base_url="http://127.0.0.1:8081",
        sender_email=SENDER,
        task_id=seed_mod.TASK_3_1,
        password=PASSWORD,
    )
    expected = sorted({SENDER} | set(seed_mod.recipients_for(seed_mod.TASK_3_1)))
    assert result["needed"] == expected
    assert result["created"] == expected
    assert result["preserved"] == []
    assert len(posted) == len(expected)
    for body in posted:
        # GreenMail 2.1.14 create_user contract: email + login + password.
        assert set(body) == {"email", "login", "password"}
        assert body["login"] == body["email"]
        assert body["email"] in expected
    # The result itself carries no secret.
    assert PASSWORD not in repr(result)


def test_provisioning_preserves_existing_users_idempotent(monkeypatch) -> None:
    needed = sorted({SENDER} | set(seed_mod.recipients_for(seed_mod.TASK_3_2)))
    posted = _provision_fake_urlopen(monkeypatch, existing=needed)
    result = seed_mod.ensure_users_provisioned(
        api_base_url="http://127.0.0.1:8081",
        sender_email=SENDER,
        task_id=seed_mod.TASK_3_2,
        password=PASSWORD,
    )
    assert posted == []
    assert result["created"] == []
    assert result["preserved"] == needed


def test_provisioning_scopes_posts_to_selected_task(monkeypatch) -> None:
    posted = _provision_fake_urlopen(monkeypatch, existing=[])
    seed_mod.ensure_users_provisioned(
        api_base_url="http://127.0.0.1:8081",
        sender_email=SENDER,
        task_id=seed_mod.TASK_3_3,
        password=PASSWORD,
    )
    posted_emails = {body["email"] for body in posted}
    assert posted_emails == set([SENDER] + list(seed_mod.recipients_for(seed_mod.TASK_3_3)))
    assert "benchrecv@example.test" not in posted_emails
    assert "field3@mail.test" not in posted_emails


def test_provisioning_requires_empty_recipient_inboxes(monkeypatch) -> None:
    first_recipient = seed_mod.recipients_for(seed_mod.TASK_3_3)[0]
    _provision_fake_urlopen(
        monkeypatch,
        existing=[],
        inbox_rows={first_recipient: [{"subject": "leftover", "Message-ID": "<leftover>"}]},
    )
    with pytest.raises(RuntimeError, match="not empty"):
        seed_mod.ensure_users_provisioned(
            api_base_url="http://127.0.0.1:8081",
            sender_email=SENDER,
            task_id=seed_mod.TASK_3_3,
            password=PASSWORD,
        )


def test_provisioning_failure_surfaces_error(monkeypatch, quiet_sleep) -> None:
    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            pass

        def send_message(self, message):
            raise AssertionError("SMTP must not run when provisioning fails")

    _provision_fake_urlopen(
        monkeypatch, existing=[], fail_post=RuntimeError("POST /api/user boom")
    )
    monkeypatch.setattr(seed_mod.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(
        seed_mod.GreenMailOpenAppInitializer, "_ensure_greenmail_ready", lambda _url: None
    )
    monkeypatch.setattr(seed_mod.GreenMailOpenAppInitializer, "_purge_greenmail", lambda _url: None)
    monkeypatch.setattr(
        seed_mod, "purge_local_state_for_bundle", lambda **kwargs: {"applied": False, "reason": "missing_udid"}
    )

    controller, _ = _make_controller()
    result = MailyBenchmarkSeedInitializer().initialize(
        {
            "controller": controller,
            "params": {
                "task_id": seed_mod.TASK_3_1,
                "sender_password": PASSWORD,
                "greenmail_reset_confirmed": True,
                "wait_ms": 0,
            },
        }
    )
    assert result.status.value == "ERROR"
    _assert_no_password_leak(result)


def test_seeder_assumes_no_preferences_key_names() -> None:
    source = (REPO / "initializers" / "ios" / "maily_benchmark_seed.py").read_text(encoding="utf-8")
    for forbidden in ("plist", "flutter.", "nextUids", "not_first_run", "SecItem", "keychain", "get_app_container"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# Asset hash tables preserve the original evaluator contracts.
# ---------------------------------------------------------------------------

def test_asset_file_hashes_match_original_evaluators() -> None:
    assert seed_mod.EXPECTED_FILE_HASHES["Sprint Review Draft.md"]["sha256"] == e31.FILE_SHA256
    assert seed_mod.EXPECTED_FILE_HASHES["Shipping Notes.md"]["sha256"] == e32.SHIPPING_NOTES_SHA256
    assert seed_mod.EXPECTED_FILE_HASHES["Team Contacts.md"]["sha256"] == e33.TEAM_CONTACTS_SHA256


def test_asset_photo_hashes_match_original_evaluators() -> None:
    live = [entry for entry in seed_mod.EXPECTED_PHOTO_HASHES if "orphan" not in str(entry["task"])]
    live_hashes = {entry["sha256"] for entry in live}
    assert e31.PHOTO_SHA256 in live_hashes
    assert e32.CLOWN_PHOTO_SHA256 in live_hashes
    assert e32.GUITAR_PHOTO_SHA256 in live_hashes
    assert e33.AIRPORT_SELFIE_SHA256 in live_hashes
    assert e33.ORANGE_BOXES_SHA256 in live_hashes
    assert e33.TABLE_COOKING_SHA256 in live_hashes
    assert len(live) == 6
    # Orphan 3_4 rows exist as seek-only references, never as task wiring.
    orphan = [entry for entry in seed_mod.EXPECTED_PHOTO_HASHES if "orphan" in str(entry["task"])]
    assert len(orphan) == 2
    assert len(seed_mod.EXPECTED_PHOTO_HASHES) == 8


def test_asset_script_tables_match_seeder_tables() -> None:
    assert assets_mod.expected_files() == {
        name: entry["sha256"]
        for name, entry in seed_mod.EXPECTED_FILE_HASHES.items()
        if "orphan" not in str(entry["task"])
    }
    assert {entry["sha256"] for entry in assets_mod.expected_photos()} == {
        entry["sha256"] for entry in seed_mod.EXPECTED_PHOTO_HASHES if "orphan" not in str(entry["task"])
    }


def test_asset_extract_needs_no_private_directories(tmp_path: Path) -> None:
    source = tmp_path / "caller-source"
    source.mkdir()
    (source / "Shipping Notes.md").write_bytes(b"wrong bytes, must not verify")
    files = assets_mod.find_verified_files(source)
    assert files == {}
    out = tmp_path / "out"
    report_code = assets_mod.main(
        ["extract", "--source", str(source), "--out", str(out)]
    )
    # Missing assets are reported, never faked: nonzero exit, provenance kept.
    assert report_code == 1
    assert (out / "provenance.json").is_file()


def test_asset_verify_rejects_wrong_bytes(tmp_path: Path) -> None:
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "Team Contacts.md").write_bytes(b"re-minted bytes do not match the original hash")
    assert assets_mod.cmd_verify(
        SimpleNamespace(assets_dir=str(assets_dir), include_orphan=False)
    ) == 1


def test_asset_script_touches_no_simulator_or_server() -> None:
    source = (REPO / "scripts" / "prepare_maily_assets.py").read_text(encoding="utf-8")
    for forbidden in ("simctl", "xcrun", "CoreSimulator", "smtplib", "subprocess", "urlopen", "/Users/"):
        assert forbidden not in source
