"""Reproducible per-task Maily baseline seeder (three live tasks only).

Scope: ``ios.maily.instruction_3_1``, ``ios.maily.instruction_3_2`` and
``ios.maily.instruction_3_3``. There is deliberately NO fourth task here:
``evaluators/ios/maily_instruction_3_4.py`` is an orphaned evaluator with no
task YAML and no execution entry, so this module defines no seed spec for it.
Task YAML wiring is left to root after review.

What this module seeds: ONLY the initial inbound messages that must already
sit in the sender-visible store before step 1. It NEVER seeds, fabricates, or
replays the agents' final sent (target completion) messages; those remain the
durable outputs the original evaluators verify. Every seed is delivered to the
sender mailbox (``alex.rivera@example.test``); reply-source seeds additionally
carry the original sender as ``From`` so the app's Reply is addressed to the
mailbox the matching evaluator checkpoint reads (derived from
``TARGET_SPECS``). Every target-only recipient mailbox starts empty after the
reset.

Grounding (read in full before any edit):
- ``tasks/v1/ios/maily_instruction_3_[123].yaml`` (instruction text).
- ``evaluators/ios/maily_instruction_3_1.py`` (``CHECKPOINT_SPECS``
  ``source_message_id_fragment`` values; ``SENDER``; file/photo hashes).
- ``evaluators/ios/maily_instruction_3_2.py`` (``CHECKPOINT_SPECS``
  ``source_reference`` values; quoted ``Seed body for <Subject>.`` rule).
- ``evaluators/ios/maily_instruction_3_3.py`` (``MESSAGE_SPECS`` exact
  ``source_message_id`` values; ``_check_seed_messages``).

Reuse, not fork: GreenMail readiness/purge behaviour is delegated to
``initializers.ios.greenmail_open_app.GreenMailOpenAppInitializer``, and Maily
local-state purge to
``initializers.ios.greenmail_local_state.purge_local_state_for_bundle``.
This module adds only what those helpers lack: per-task GreenMail user
provisioning (``GET``/``POST /api/user`` per the GreenMail 2.1.14 OpenAPI)
plus exact per-task ``Message-ID`` / ``Date`` seed construction over SMTP.

Safety rules enforced by the initializer:
- Host GreenMail reset (readiness check + ``POST /api/mail/purge``) runs ONLY
  when the caller passes ``greenmail_reset_confirmed=True``. That flag may be
  set only by the root initializer/CLI after confirming no competing formal
  mail task is using the server. Without it the initializer fails before any
  network call. The reset touches the isolated local fake accounts only; it
  never touches the iOS simulator, app containers, GUI, or processes.
- Maily REMAINS ON iOS: UDID/container health checks stay applicable. This
  module neither drops them nor re-implements them.
- Account handling never logs passwords: result messages and metadata carry
  only account identifiers plus a boolean ``password_provided`` flag. No
  Maily preferences key names are assumed anywhere in this module (local
  state handling is fully delegated to ``greenmail_local_state``).
"""

from __future__ import annotations

import copy
import json
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from typing import Any, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.ios.greenmail_local_state import purge_local_state_for_bundle
from initializers.ios.greenmail_open_app import GreenMailOpenAppInitializer


SENDER_EMAIL = "alex.rivera@example.test"
MAILY_BUNDLE_ID = "de.enough.maily"

TASK_3_1 = "ios.maily.instruction_3_1"
TASK_3_2 = "ios.maily.instruction_3_2"
TASK_3_3 = "ios.maily.instruction_3_3"
TASK_IDS: tuple[str, ...] = (TASK_3_1, TASK_3_2, TASK_3_3)

DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
DEFAULT_SMTP_HOST = "127.0.0.1"
DEFAULT_SMTP_PORT = 3025
DEFAULT_WAIT_MS = 800

#: Fixed baseline seed date. Subjects carry a ``0708`` stamp; seeds are sent
#: with this stable Date (plus per-seed minute offsets) so they always predate
#: any run window anchored at ``args.json.created_at``.
SEED_BASE_DATE = datetime(2026, 7, 8, 8, 0, 0, tzinfo=timezone.utc)


def seed_body_for(subject: str) -> str:
    """Quoted seed-body convention required by the 3_2/3_3 evaluators."""
    return f"Seed body for {subject}."


def _message_id(fragment_or_reference: str) -> str:
    """Wrap a bare fragment/reference in angle brackets for the wire."""
    text = fragment_or_reference.strip()
    if text.startswith("<") and text.endswith(">"):
        return text
    return f"<{text}>"


# ---------------------------------------------------------------------------
# Inbound seed specs. ``message_id`` values below are the ORIGINAL evaluator
# identities: exact ``source_message_id`` for 3_3, exact
# ``source_message_id_fragment`` for 3_1. For 3_2 the evaluator records only a
# ``source_reference`` substring, so the seed Message-ID is minted by the
# documented convention ``<reference>-sender@domain`` and flagged as such;
# any ID containing the reference satisfies that verifier.
# ---------------------------------------------------------------------------

SEED_SPECS: dict[str, tuple[dict[str, str], ...]] = {
    TASK_3_1: tuple(
        {
            "subject": subject,
            "message_id": _message_id(fragment),
            "body": seed_body_for(subject),
        }
        for subject, fragment in (
            ("AlphaReply0708", "baseline-23-alphareply0708-alex.rivera@example.test@example.test"),
            ("AlphaFwd0708", "baseline-24-alphafwd0708-alex.rivera@example.test@example.test"),
            ("AlphaRead0708", "baseline-22-alpharead0708-alex.rivera@example.test@example.test"),
            ("AlphaBulkA", "baseline-26-alphabulka-alex.rivera@example.test@example.test"),
            ("AlphaShare0708", "baseline-28-alphashare0708-alex.rivera@example.test@example.test"),
            ("AlphaBulkB", "baseline-27-alphabulkb-alex.rivera@example.test@example.test"),
            ("AlphaTrash0708", "baseline-25-alphatrash0708-alex.rivera@example.test@example.test"),
        )
    ),
    TASK_3_2: tuple(
        {
            "subject": subject,
            # Convention-derived (see module docstring): the evaluator pins
            # only the ``source_reference`` substring, not a full Message-ID.
            "message_id": _message_id(f"{reference}-alex.rivera@example.test@example.test"),
            "source_reference": reference,
            "body": seed_body_for(subject),
        }
        for subject, reference in (
            ("RouteFwd0708", "baseline-1-routefwd0708"),
            ("RouteBulkA", "baseline-4-routebulka"),
            ("RouteReply0708", "baseline-3-routereply0708"),
            ("RouteBulkB", "baseline-5-routebulkb"),
            ("RouteShare0708", "baseline-7-routeshare0708"),
            ("RouteRead0708", "baseline-2-routeread0708"),
            ("RouteTrash0708", "baseline-6-routetrash0708"),
        )
    ),
    TASK_3_3: tuple(
        {
            "subject": subject,
            "message_id": message_id,
            "body": seed_body_for(subject),
        }
        for subject, message_id in (
            ("FieldRead0708", "<baseline-15-fieldread0708-alex.rivera@example.test@example.test>"),
            ("FieldFwd0708", "<baseline-18-fieldfwd0708-alex.rivera@example.test@example.test>"),
            ("FieldReply0708", "<baseline-17-fieldreply0708-alex.rivera@example.test@example.test>"),
            ("FieldShare0708", "<baseline-21-fieldshare0708-alex.rivera@example.test@example.test>"),
            ("FieldTrash0708", "<baseline-16-fieldtrash0708-alex.rivera@example.test@example.test>"),
        )
    ),
}

SEED_MESSAGE_IDS_3_2_MINTED_BY_CONVENTION = True

# ---------------------------------------------------------------------------
# Target (final sent) message descriptors, mirrored from the original
# evaluators for cross-checking ONLY. They are never seeded; tests assert the
# seed set and the target set are disjoint and correctly linked.
# ---------------------------------------------------------------------------

TARGET_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    TASK_3_1: (
        {"mailbox": "benchsender@example.test", "subject": "Re: AlphaReply0708", "kind": "reply", "source_subject": "AlphaReply0708"},
        {"mailbox": "benchrecv@example.test", "subject": "Alpha gate opened", "kind": "compose", "source_subject": None},
        {"mailbox": "planbox@mail.test", "subject": "Fwd: AlphaFwd0708", "kind": "forward", "source_subject": "AlphaFwd0708"},
        {"mailbox": "benchsender@example.test", "subject": "Re: AlphaRead0708", "kind": "reply", "source_subject": "AlphaRead0708"},
        {"mailbox": "planbox@mail.test", "subject": "Fwd: AlphaBulkA . batch-1", "kind": "forward", "source_subject": "AlphaBulkA"},
        {"mailbox": "benchrecv@example.test", "subject": "Alpha gate midway", "kind": "compose", "source_subject": None},
        {"mailbox": "benchsender@example.test", "subject": "Re: AlphaShare0708", "kind": "reply", "source_subject": "AlphaShare0708"},
        {"mailbox": "planbox@mail.test", "subject": "Fwd: AlphaBulkB . batch-b", "kind": "forward", "source_subject": "AlphaBulkB"},
        {"mailbox": "benchsender@example.test", "subject": "Re: AlphaTrash0708", "kind": "reply", "source_subject": "AlphaTrash0708"},
        {"mailbox": "planbox@mail.test", "subject": "Alpha record index", "kind": "compose", "source_subject": None},
    ),
    TASK_3_2: (
        {"mailbox": "field3@mail.test", "subject": "Fwd: RouteFwd0708", "kind": "forward", "source_subject": "RouteFwd0708"},
        {"mailbox": "field3@mail.test", "subject": "Fwd: RouteBulkA \u00b7 follow up", "kind": "forward", "source_subject": "RouteBulkA"},
        {"mailbox": "benchsender@example.test", "subject": "Re: RouteReply0708", "kind": "reply", "source_subject": "RouteReply0708"},
        {"mailbox": "rein@mail.test", "subject": "Route relay midway", "kind": "compose", "source_subject": None},
        {"mailbox": "field3@mail.test", "subject": "Fwd: RouteBulkB \u00b7 check tomorrow", "kind": "forward", "source_subject": "RouteBulkB"},
        {"mailbox": "rain@mail.test", "subject": "Route depot note", "kind": "compose", "source_subject": None},
        {"mailbox": "field3@mail.test", "subject": "Fwd: RouteShare0708 \u00b7 share-pack", "kind": "forward", "source_subject": "RouteShare0708"},
        {"mailbox": "benchsender@example.test", "subject": "Re: RouteRead0708 \u00b7 read-log", "kind": "reply", "source_subject": "RouteRead0708"},
        {"mailbox": "field3@mail.test", "subject": "Fwd: RouteTrash0708", "kind": "forward", "source_subject": "RouteTrash0708"},
    ),
    TASK_3_3: (
        {"mailbox": "benchsender@example.test", "subject": "Re: FieldRead0708", "kind": "reply", "source_subject": "FieldRead0708"},
        {"mailbox": "ops4@mail.test", "subject": "Field crew roster", "kind": "compose", "source_subject": None},
        {"mailbox": "benchchat@example.test", "subject": "Fwd: FieldFwd0708", "kind": "forward", "source_subject": "FieldFwd0708"},
        {"mailbox": "ops4@mail.test", "subject": "Field water note", "kind": "compose", "source_subject": None},
        {"mailbox": "benchsender@example.test", "subject": "Re: FieldReply0708", "kind": "reply", "source_subject": "FieldReply0708"},
        {"mailbox": "ops4@mail.test", "subject": "Field soil note", "kind": "compose", "source_subject": None},
        {"mailbox": "ops4@mail.test", "subject": "Field safety brief", "kind": "compose", "source_subject": None},
        {"mailbox": "benchsender@example.test", "subject": "Re: FieldShare0708", "kind": "reply", "source_subject": "FieldShare0708"},
        {"mailbox": "benchchat@example.test", "subject": "Fwd: FieldTrash0708 . retain", "kind": "forward", "source_subject": "FieldTrash0708"},
    ),
}

#: Every mailbox the agents' target messages are delivered to. These GreenMail
#: users must exist on the server so delivery succeeds, but they start EMPTY
#: each run: the reset purges everything, then only the sender mailbox is
#: seeded. Kept here so root's server provisioning can be checked.
ALL_TARGET_RECIPIENTS: tuple[str, ...] = tuple(
    sorted(
        {
            str(spec["mailbox"])
            for specs in TARGET_SPECS.values()
            for spec in specs
        }
    )
)


def reply_source_senders(task_id: str) -> dict[str, str]:
    """Map each reply-source seed subject to the mailbox its reply must reach.

    Maily's Reply action addresses the seed's ``From`` header, while every reply
    checkpoint in the three evaluators reads a fixed mailbox declared on the
    matching ``kind == "reply"`` target spec (``benchsender@example.test`` for
    all three tasks). Deriving the seed sender from ``TARGET_SPECS`` keeps
    3_1/3_2/3_3 consistent and keeps the evaluator as the single source of
    truth; self-addressing the seeds made replies land in the agent's own
    mailbox, so the graded mailboxes stayed empty (scan.CSV rows IOS-007 /
    IOS-009 / IOS-010, issue_class ``seed_mismatch``).
    """
    if task_id not in TARGET_SPECS:
        raise KeyError(f"unknown Maily benchmark task: {task_id!r} (expected one of {list(TARGET_SPECS)})")
    return {
        str(spec["source_subject"]): str(spec["mailbox"])
        for spec in TARGET_SPECS[task_id]
        if spec.get("kind") == "reply" and spec.get("source_subject")
    }

# ---------------------------------------------------------------------------
# Asset hash tables (byte-exact contracts from the original evaluators).
# FSNotes/photo BYTES are resolved by scripts/prepare_maily_assets.py; the
# hashes here are the acceptance gate. The two 3_4 rows are seek-only
# references for the orphaned evaluator: no task wiring, no seeding.
# ---------------------------------------------------------------------------

EXPECTED_FILE_HASHES: dict[str, dict[str, str]] = {
    "Sprint Review Draft.md": {
        "sha256": "a0869ffd08ca7775b3e0125272e89ae2559ecae652e413e24e319e921b52c891",
        "task": TASK_3_1,
    },
    "Shipping Notes.md": {
        "sha256": "36e924648e96f5608e189c92d30f19b2780438730b44b5d975d96fffa8c35b60",
        "task": TASK_3_2,
    },
    "Team Contacts.md": {
        "sha256": "8015c51c4036b70ac1231b0bc6f38d43231039eac3ea7bfc6a0ccc9bec52565e",
        "task": TASK_3_3,
    },
    "Mobile Gates Gates.markdown": {
        "sha256": "7d1cef45a68f9ff199d6c78429f5973a8644082ad82e73c9c59c9b7ab8f1dc05",
        "task": "ios.maily.instruction_3_4 (orphan evaluator; seek-only, not seeded)",
    },
}

EXPECTED_PHOTO_HASHES: tuple[dict[str, str], ...] = (
    {"label": "uniformed person holding gun, IMG_0080.JPG", "sha256": "97d5ae0cb9f81db777d09af3240980ba588d7a551902e1662bef1d54bb5522fd", "task": TASK_3_1},
    {"label": "clown, white face / red nose / green hair", "sha256": "b6237067e7ca26eb618ca8f8d4cb7b09bb931ac8c2e5cdf2928146bbd9c5ad91", "task": TASK_3_2},
    {"label": "blue electric guitar close-up", "sha256": "3a3fda010a1c08174c0866c1135194eabcbdd38fc4278f451186af72f90043d1", "task": TASK_3_2},
    {"label": "airport-entrance group selfie", "sha256": "b7eba2f33fb661b273a5a7b311fe220efd925dddd4536e2175332e3d06d04faf", "task": TASK_3_3},
    {"label": "two people holding orange boxes", "sha256": "8b1c7cf4f3639b62f811cddcfce0471b8d2ae240dd14ddeae0a8fc647bf23815", "task": TASK_3_3},
    {"label": "people cooking around table", "sha256": "a61cd4fbf7687f24fe4024cf3459c838267fe33cce6bb95106148f0e8c8ec963", "task": TASK_3_3},
    {"label": "clown (3_4 orphan evaluator)", "sha256": "c70ca0ab1b961103079b3ef5fcc520804d2ede1d0660a39d029d375ae0d9760a", "task": "ios.maily.instruction_3_4 (orphan evaluator; seek-only, not seeded)"},
    {"label": "young man (3_4 orphan evaluator)", "sha256": "61b82f396615c18bb517fbb6572a9f805a09ad4c252c51147e5127469ca5650a", "task": "ios.maily.instruction_3_4 (orphan evaluator; seek-only, not seeded)"},
)


def seed_specs_for(task_id: str) -> tuple[dict[str, str], ...]:
    """Return a defensive copy of the inbound seed specs for one task.

    Reply-source seeds gain a ``sender`` field: the original mailbox whose
    reply checkpoint must receive the agent's Reply. That field is injected at
    read time from ``TARGET_SPECS``, so ``SEED_SPECS`` stays subject/Message-ID
    only and 3_1/3_2/3_3 cannot drift from their evaluators.
    """
    if task_id not in SEED_SPECS:
        raise KeyError(f"unknown Maily benchmark task: {task_id!r} (expected one of {list(SEED_SPECS)})")
    specs = copy.deepcopy(SEED_SPECS[task_id])
    senders = reply_source_senders(task_id)
    for spec in specs:
        sender = senders.get(spec["subject"])
        if sender:
            spec["sender"] = sender
    return specs


def build_seed_email(
    *,
    spec: Mapping[str, str],
    sender_email: str = SENDER_EMAIL,
    from_email: str | None = None,
    recipient_email: str = SENDER_EMAIL,
    seed_index: int = 0,
) -> Message:
    """Build the exact MIME message for one inbound seed.

    Seeds are delivered to the sender mailbox (``recipient_email``) so they are
    visible to the Maily account under test. Reply-source seeds pass their
    original mailbox as ``from_email`` (``spec["sender"]`` from
    ``TARGET_SPECS``) so the app's Reply is addressed to the graded mailbox;
    every other seed keeps ``From == sender_email``. ``Message-ID`` carries the
    original evaluator identity and ``Date`` is a stable pre-run timestamp.

    NOTE: this deliberately uses the plain (compat32-style) ``Message`` class
    with verbatim string headers, NOT ``EmailMessage``. The original baseline
    IDs contain a doubled domain (``...@example.test@example.test``), which
    the structured ``EmailMessage`` header registry silently rewrites on the
    wire; verbatim headers preserve the byte-exact IDs the verifiers bind.
    Bodies are ASCII by construction, so ``7bit`` transfer encoding applies.
    """
    message = Message()
    message["From"] = str(from_email or sender_email)
    message["To"] = recipient_email
    message["Subject"] = str(spec["subject"])
    message["Message-ID"] = str(spec["message_id"])
    message["Date"] = format_datetime(SEED_BASE_DATE + timedelta(minutes=seed_index))
    message["Content-Type"] = 'text/plain; charset="utf-8"'
    message["Content-Transfer-Encoding"] = "7bit"
    message.set_payload(str(spec["body"]))
    return message


def account_summary(*, sender_email: str, password_provided: bool) -> dict[str, Any]:
    """Non-secret account descriptor for logs and result metadata.

    Only identifiers are recorded; the secret itself is never included,
    specifically so configured-account discovery/update cannot leak passwords.
    """
    return {"email": sender_email, "password_provided": bool(password_provided)}


def _redacted_metadata(metadata: Mapping[str, Any], secrets: tuple[str, ...]) -> dict[str, Any]:
    """Return metadata with any secret values removed (defence in depth)."""
    redacted = copy.deepcopy(dict(metadata))
    for secret in secrets:
        if secret:
            for key in list(redacted):
                if redacted[key] == secret:
                    redacted[key] = "<redacted>"
    return redacted


def _fetch_mailbox_rows(api_base_url: str, recipient_email: str) -> list[dict[str, Any]]:
    """Read-only GreenMail REST fetch of one INBOX (HTTP GET only)."""
    encoded = quote(recipient_email, safe="")
    request = Request(f"{api_base_url}/api/user/{encoded}/messages/INBOX", method="GET")
    with urlopen(request, timeout=10.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise TypeError(f"mailbox payload for {recipient_email} must be a list")
    return [dict(item) for item in payload if isinstance(item, dict)]


def recipients_for(task_id: str) -> tuple[str, ...]:
    """Target recipient mailboxes needed by one task (sorted, de-duplicated)."""
    if task_id not in TARGET_SPECS:
        raise KeyError(f"unknown Maily benchmark task: {task_id!r} (expected one of {list(TARGET_SPECS)})")
    return tuple(sorted({str(spec["mailbox"]) for spec in TARGET_SPECS[task_id]}))


def _list_greenmail_users(api_base_url: str) -> list[dict[str, Any]]:
    """List existing GreenMail users via ``GET /api/user`` (no secrets)."""
    request = Request(f"{api_base_url}/api/user", method="GET")
    with urlopen(request, timeout=10.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise TypeError("GreenMail user list payload must be a list")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _create_greenmail_user(*, api_base_url: str, email: str, password: str) -> None:
    """Create one GreenMail user via ``POST /api/user``.

    Body follows the GreenMail 2.1.14 OpenAPI ``create_user`` contract:
    JSON ``{"email": ..., "login": ..., "password": ...}``. The secret
    travels only in the request body; it is never returned, logged, or
    stored by this module.
    """
    body = json.dumps({"email": email, "login": email, "password": password}).encode("utf-8")
    request = Request(
        f"{api_base_url}/api/user",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10.0) as response:
        response.read()


def ensure_users_provisioned(
    *,
    api_base_url: str,
    sender_email: str,
    task_id: str,
    password: str,
) -> dict[str, Any]:
    """Provision sender + this task's recipient mailboxes; verify emptiness.

    Runs after readiness/purge and before any SMTP seed. Only the initially
    selected task's recipients (plus the sender) are touched — never the
    unrelated tasks' mailboxes. Existing users are preserved (no delete or
    recreate); missing users are created with the caller-supplied fake-account
    password. Every target recipient INBOX must then read back empty;
    a non-empty recipient INBOX raises ``RuntimeError`` (surfaced as ERROR
    by the caller). Returns only non-secret identifiers and counts.
    """
    needed = tuple(sorted({sender_email} | set(recipients_for(task_id))))
    existing_rows = _list_greenmail_users(api_base_url)
    existing_ids = {
        str(row.get("email") or row.get("login") or "")
        for row in existing_rows
    } - {""}
    missing = [email for email in needed if email not in existing_ids]
    for email in missing:
        _create_greenmail_user(api_base_url=api_base_url, email=email, password=password)
    preserved = [email for email in needed if email in existing_ids]
    # Recipient INBOXes must exist (creation above guarantees users) and
    # start empty after the purge; the sender mailbox is excluded because
    # SMTP seeding fills it immediately afterwards.
    non_empty: list[str] = []
    for recipient in recipients_for(task_id):
        rows = _fetch_mailbox_rows(api_base_url, recipient)
        if rows:
            non_empty.append(recipient)
    if non_empty:
        raise RuntimeError(f"recipient mailboxes not empty after purge: {sorted(non_empty)}")
    return {
        "needed": list(needed),
        "created": list(missing),
        "preserved": sorted(preserved),
        "recipient_count": len(recipients_for(task_id)),
    }


def verify_seeds_present(
    *,
    api_base_url: str,
    task_id: str,
    sender_email: str = SENDER_EMAIL,
) -> dict[str, Any]:
    """Assert each seed subject + Message-ID exists exactly once (read-only)."""
    specs = seed_specs_for(task_id)
    rows = _fetch_mailbox_rows(api_base_url, sender_email)
    missing: list[str] = []
    duplicated: list[str] = []
    for spec in specs:
        matches = [
            row
            for row in rows
            if str(row.get("subject") or "") == spec["subject"]
            and str(row.get("Message-ID") or "") == spec["message_id"]
        ]
        if not matches:
            missing.append(spec["subject"])
        elif len(matches) > 1:
            duplicated.append(spec["subject"])
    return {
        "pass": not missing and not duplicated,
        "mailbox": sender_email,
        "seed_count": len(specs),
        "mailbox_message_count": len(rows),
        "missing": missing,
        "duplicated": duplicated,
    }


class MailyBenchmarkSeedInitializer(BaseInitializer):
    """Seed one task's inbound baseline, then foreground Maily on iOS.

    Recognised ``params`` (all other keys ignored):

    - ``task_id`` (required): one of the three ``ios.maily.instruction_3_*``
      task ids. Anything else, including the orphaned 3_4 id, fails fast.
    - ``sender_password`` or ``sender_password_env`` (required): GreenMail
      credential for the sender mailbox. Never logged; never echoed in
      results.
    - ``greenmail_reset_confirmed`` (required to be ``True`` when
      ``purge_greenmail`` is true): set ONLY by the root initializer/CLI
      after confirming no competing formal mail task is using the server.
    - ``purge_greenmail`` (default ``True``): purge the isolated local fake
      accounts before seeding.
    - ``api_base_url`` / ``smtp_host`` / ``smtp_port``: host GreenMail
      endpoints (defaults: REST 8081, SMTP 3025 on 127.0.0.1).
    - ``bundle_id`` (default ``de.enough.maily``), ``wait_ms`` (default 800),
      ``udid`` / ``app_data_container_path`` (local-state purge targeting),
      ``foreground_app_after_seed`` (default ``True``),
      ``verify_seeds`` (default ``True``).

    Run order: readiness GET → ``POST /api/mail/purge`` → local-state purge
    → user provisioning (sender + this task's recipients via ``GET``/``POST
    /api/user``, existing users preserved, recipient INBOXes verified empty)
    → SMTP seeds → read-only REST verification → foreground Maily on iOS.
    """

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        import os

        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS initialization",
            )

        task_id = str(params.get("task_id") or "").strip()
        if task_id not in SEED_SPECS:
            return InitResult(
                status=InitStatus.FAIL,
                message=f"maily benchmark seeder requires task_id one of {list(SEED_SPECS)}",
                metadata={"task_id": task_id or None},
            )

        sender_email = str(params.get("sender_email") or SENDER_EMAIL).strip() or SENDER_EMAIL
        sender_password = str(params.get("sender_password") or "").strip()
        password_env = str(params.get("sender_password_env") or "").strip()
        if not sender_password and password_env:
            sender_password = str(os.environ.get(password_env) or "").strip()
        if not sender_password:
            return InitResult(
                status=InitStatus.FAIL,
                message="maily benchmark seeder requires params.sender_password (or sender_password_env)",
                metadata={
                    "task_id": task_id,
                    "account": account_summary(sender_email=sender_email, password_provided=False),
                },
            )
        secrets = (sender_password,)

        api_base_url = str(params.get("api_base_url") or DEFAULT_API_BASE_URL).rstrip("/")
        smtp_host = str(params.get("smtp_host") or DEFAULT_SMTP_HOST).strip() or DEFAULT_SMTP_HOST
        smtp_port = int(params.get("smtp_port") or DEFAULT_SMTP_PORT)
        bundle_id = str(params.get("bundle_id") or MAILY_BUNDLE_ID).strip() or MAILY_BUNDLE_ID
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        purge_greenmail = bool(params.get("purge_greenmail", True))
        reset_confirmed = bool(params.get("greenmail_reset_confirmed", False))
        foreground_after_seed = bool(params.get("foreground_app_after_seed", True))
        verify_after_seed = bool(params.get("verify_seeds", True))
        udid = str(params.get("udid") or getattr(getattr(controller, "runtime", None), "udid", "") or "").strip() or None
        app_data_container_path = str(params.get("app_data_container_path") or "").strip() or None

        if purge_greenmail and not reset_confirmed:
            # Hard stop BEFORE any network side effect: only the root
            # initializer/CLI may authorise the shared-host reset, and only
            # when no competing formal mail task is running.
            return InitResult(
                status=InitStatus.FAIL,
                message="refusing host GreenMail reset without params.greenmail_reset_confirmed=True from the root initializer/CLI",
                metadata=_redacted_metadata(
                    {
                        "task_id": task_id,
                        "account": account_summary(sender_email=sender_email, password_provided=True),
                        "purge_greenmail": purge_greenmail,
                        "greenmail_reset_confirmed": False,
                    },
                    secrets,
                ),
            )

        base_metadata = {
            "task_id": task_id,
            "bundle_id": bundle_id,
            "api_base_url": api_base_url,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "account": account_summary(sender_email=sender_email, password_provided=True),
            "purge_greenmail": purge_greenmail,
            "greenmail_reset_confirmed": reset_confirmed,
            "greenmail_reset_scope": "isolated local fake accounts only (purge endpoint); no simulator, app, or account-config writes",
        }

        try:
            if hasattr(controller, "terminate_app"):
                controller.terminate_app(bundle_id)
                time.sleep(0.8)

            if purge_greenmail:
                GreenMailOpenAppInitializer._ensure_greenmail_ready(api_base_url)
                GreenMailOpenAppInitializer._purge_greenmail(api_base_url)
            local_purge_result: dict[str, object] = {"applied": False, "reason": "reset_not_requested"}
            if purge_greenmail:
                local_purge_result = purge_local_state_for_bundle(
                    bundle_id=bundle_id,
                    udid=udid,
                    app_data_container_path=app_data_container_path,
                )

            provision_result = ensure_users_provisioned(
                api_base_url=api_base_url,
                sender_email=sender_email,
                task_id=task_id,
                password=sender_password,
            )

            specs = seed_specs_for(task_id)
            for index, spec in enumerate(specs):
                message = build_seed_email(
                    spec=spec,
                    sender_email=sender_email,
                    from_email=str(spec.get("sender") or sender_email),
                    recipient_email=sender_email,
                    seed_index=index,
                )
                with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=10.0) as client:
                    client.login(sender_email, sender_password)
                    client.send_message(message)

            verification: dict[str, Any] = {"applied": False}
            if verify_after_seed:
                verification = {"applied": True, **verify_seeds_present(
                    api_base_url=api_base_url,
                    task_id=task_id,
                    sender_email=sender_email,
                )}
                if not verification["pass"]:
                    return InitResult(
                        status=InitStatus.FAIL,
                        message="seeded baseline failed read-only verification",
                        metadata=_redacted_metadata(
                            {**base_metadata, "local_purge_result": local_purge_result, "provision_result": provision_result, "verification": verification},
                            secrets,
                        ),
                    )

            if foreground_after_seed:
                if hasattr(controller, "press_home"):
                    controller.press_home()
                    time.sleep(0.5)
                controller.activate_app(bundle_id)
                time.sleep(0.5)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to seed Maily baseline for '{task_id}': {type(exc).__name__}: {exc}",
                metadata=_redacted_metadata({**base_metadata, "seeded_message_count": 0}, secrets),
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Seeded {len(seed_specs_for(task_id))} inbound baseline messages for '{task_id}'",
            metadata=_redacted_metadata(
                {
                    **base_metadata,
                    "local_purge_result": local_purge_result,
                    "provision_result": provision_result,
                    "seeded_message_count": len(specs),
                    "seed_subjects": [spec["subject"] for spec in specs],
                    "seed_message_ids": [spec["message_id"] for spec in specs],
                    "verification": verification,
                    "wait_ms": wait_ms,
                },
                secrets,
            ),
        )
