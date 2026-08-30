"""Android initializer for the Delta Chat + GreenMail benchmark task."""

from __future__ import annotations

import json
import shlex
import sqlite3
import smtplib
import tempfile
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import (
    launch_mail_or_chat_app,
    reset_delta_chat_account_if_requested,
)
from platforms.android.bootstrap import AndroidBootstrapDriver


class DeltaChatSendMessageInitializer(BaseInitializer):
    """Prepare the Delta Chat task by purging GreenMail and opening the app."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_APP_PACKAGE = "chat.delta"
    DEFAULT_APP_ACTIVITY = "org.thoughtcrime.securesms.RoutingActivity"
    DEFAULT_WAIT_MS = 1500
    DEFAULT_SEED_VISIBLE_TIMEOUT_SECONDS = 35.0
    DEFAULT_SEED_VISIBLE_POLL_INTERVAL_SECONDS = 1.5

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Delta Chat initialization",
            )

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or self.DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_greenmail = bool(params.get("purge_greenmail", True))
        seed_sender_email = str(params.get("seed_sender_email") or "").strip()
        seed_sender_password = str(params.get("seed_sender_password") or "").strip()
        seed_recipient_email = str(params.get("seed_recipient_email") or "").strip()
        seed_subject = str(params.get("seed_subject") or "").strip()
        seed_body = str(params.get("seed_body") or "").strip()
        seed_smtp_host = str(params.get("seed_smtp_host") or "127.0.0.1").strip()
        seed_smtp_port = int(params.get("seed_smtp_port") or 3025)
        require_seed_visible = bool(params.get("require_seed_visible", True))
        seed_visible_timeout_seconds = float(
            params.get(
                "seed_visible_timeout_seconds",
                self.DEFAULT_SEED_VISIBLE_TIMEOUT_SECONDS,
            )
            or 0.0
        )
        seed_visible_poll_interval_seconds = float(
            params.get(
                "seed_visible_poll_interval_seconds",
                self.DEFAULT_SEED_VISIBLE_POLL_INTERVAL_SECONDS,
            )
            or 0.0
        )
        seed_message_expected = bool(
            seed_sender_email
            and seed_sender_password
            and seed_recipient_email
            and seed_subject
            and seed_body
        )

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
            )

        try:
            self._ensure_greenmail_ready(api_base_url)
            reset_delta_chat_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            if purge_greenmail:
                self._purge_greenmail(api_base_url)

            if seed_message_expected:
                self._seed_existing_chat(
                    smtp_host=seed_smtp_host,
                    smtp_port=seed_smtp_port,
                    sender_email=seed_sender_email,
                    sender_password=seed_sender_password,
                    recipient_email=seed_recipient_email,
                    subject=seed_subject,
                    body=seed_body,
                )
                sync_reset = self._reset_imap_sync_checkpoint(
                    controller=controller,
                    app_package=app_package,
                )
                self._patch_seed_conversation_databases(
                    controller=controller,
                    app_package=app_package,
                    seed_sender_email=seed_sender_email,
                    seed_subject=seed_subject,
                    seed_body=seed_body,
                    db_paths=sync_reset.get("db_paths", []),
                )

            ok, focus_output = launch_mail_or_chat_app(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                label="Delta Chat",
                wait_ms=wait_ms,
            )
            if not ok:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Delta Chat did not become the foreground app: {focus_output or 'no focus output'}",
                    metadata={
                        "app_package": app_package,
                        "app_activity": app_activity,
                        "focus_output": focus_output,
                    },
                )

            seed_visibility = None
            if seed_message_expected:
                seed_visibility = self._wait_for_seed_conversation_visible(
                    controller=controller,
                    app_package=app_package,
                    app_activity=app_activity,
                    seed_sender_email=seed_sender_email,
                    seed_body=seed_body,
                    timeout_seconds=seed_visible_timeout_seconds,
                    poll_interval_seconds=seed_visible_poll_interval_seconds,
                )
                if require_seed_visible and not seed_visibility["visible"]:
                    return InitResult(
                        status=InitStatus.FAIL,
                        message=(
                            "Delta Chat seed conversation did not become visible "
                            "after GreenMail injection"
                        ),
                        metadata={
                            "api_base_url": api_base_url,
                            "app_package": app_package,
                            "app_activity": app_activity,
                            "seed_sender_email": seed_sender_email,
                            "seed_recipient_email": seed_recipient_email,
                            "seed_visibility": seed_visibility,
                        },
                    )

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Delta Chat task: {type(exc).__name__}: {exc}",
                metadata={
                    "api_base_url": api_base_url,
                    "app_package": app_package,
                    "app_activity": app_activity,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="GreenMail prepared and Delta Chat opened",
            metadata={
                "api_base_url": api_base_url,
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "purge_greenmail": purge_greenmail,
                "reset_app_data": bool(params.get("reset_app_data", False)),
                "seed_sender_email": seed_sender_email,
                "seed_recipient_email": seed_recipient_email,
                "seed_visibility": seed_visibility,
            },
        )

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = DeltaChatSendMessageInitializer._request_json(
            f"{api_base_url}/api/service/readiness",
            method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

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

    @classmethod
    def _reset_imap_sync_checkpoint(
        cls,
        *,
        controller: Any,
        app_package: str,
    ) -> dict[str, Any]:
        """Clear restored Delta Chat IMAP watermarks so freshly seeded mail is fetched.

        The reusable Delta Chat app-data template contains a configured account and may
        also contain the last GreenMail UIDNEXT it saw when the template was exported.
        GreenMail purge removes messages but does not reset UID allocation. If a newly
        seeded message gets a UID below the restored UIDNEXT, Delta Chat correctly says
        there are no new emails. Clearing these sync rows makes the next launch scan
        the current INBOX again.
        """

        controller.execute_adb(["root"])
        controller.execute_adb(["wait-for-device"])
        controller.execute_adb(["shell", "am", "force-stop", app_package])

        db_paths_raw = str(
            controller.execute_adb(
                [
                    "shell",
                    (
                        "find "
                        f"{shlex.quote(f'/data/user/0/{app_package}/files/accounts')} "
                        "-name dc.db -type f 2>/dev/null"
                    ),
                ]
            )
            or ""
        )
        db_paths = [line.strip() for line in db_paths_raw.splitlines() if line.strip()]
        for index, db_path in enumerate(db_paths):
            cls._patch_imap_sync_database(
                controller=controller,
                remote_db_path=db_path,
                index=index,
            )

        return {
            "db_paths": db_paths,
            "cleared": bool(db_paths),
        }

    @staticmethod
    def _patch_imap_sync_database(
        *,
        controller: Any,
        remote_db_path: str,
        index: int,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="deltachat-imap-sync-") as tmpdir:
            tmp_path = Path(tmpdir)
            owner_group = str(
                controller.execute_adb(["shell", f"stat -c %U:%G {shlex.quote(remote_db_path)}"])
                or ""
            ).strip()
            controller.execute_adb(["pull", remote_db_path, str(tmp_path)])
            pulled_db = tmp_path / Path(remote_db_path).name
            local_db = pulled_db
            for suffix in ("-wal", "-shm"):
                remote_sidecar = f"{remote_db_path}{suffix}"
                if DeltaChatSendMessageInitializer._remote_file_exists(
                    controller,
                    remote_sidecar,
                ):
                    controller.execute_adb(["pull", remote_sidecar, str(tmp_path)])

            if not local_db.exists():
                raise RuntimeError(f"Failed to pull Delta Chat database: {remote_db_path}")

            connection = sqlite3.connect(local_db)
            try:
                connection.execute("PRAGMA busy_timeout=5000")
                existing_tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "imap_sync" in existing_tables:
                    rows = connection.execute(
                        "SELECT transport_id, folder, uidvalidity, modseq FROM imap_sync "
                        "WHERE folder = 'INBOX'"
                    ).fetchall()
                    connection.execute("DELETE FROM imap_sync WHERE folder = 'INBOX'")
                    if rows:
                        for transport_id, folder, uidvalidity, modseq in rows:
                            connection.execute(
                                "INSERT INTO imap_sync "
                                "(transport_id, folder, uidvalidity, uid_next, modseq) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (transport_id, folder, uidvalidity, 1, modseq or 0),
                            )
                    else:
                        connection.execute(
                            "INSERT INTO imap_sync "
                            "(transport_id, folder, uidvalidity, uid_next, modseq) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (1, "INBOX", 0, 1, 0),
                        )

                for table in ("imap", "imap_markseen"):
                    if table in existing_tables:
                        connection.execute(f"DELETE FROM {table}")
                if "jobs" in existing_tables:
                    connection.execute(
                        "DELETE FROM jobs WHERE action LIKE ? OR action LIKE ?",
                        ("%imap%", "%inbox%"),
                    )
                connection.commit()
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                connection.close()

            controller.execute_adb(["push", str(local_db), remote_db_path])
            quoted_db = shlex.quote(remote_db_path)
            controller.execute_adb(["shell", f"rm -f {quoted_db}-wal {quoted_db}-shm"])
            if owner_group and ":" in owner_group:
                controller.execute_adb(["shell", f"chown {shlex.quote(owner_group)} {quoted_db}"])
            controller.execute_adb(["shell", f"chmod 660 {quoted_db}"])
            controller.execute_adb(["shell", f"restorecon {quoted_db} 2>/dev/null || true"])

    @classmethod
    def _patch_seed_conversation_databases(
        cls,
        *,
        controller: Any,
        app_package: str,
        seed_sender_email: str,
        seed_subject: str,
        seed_body: str,
        db_paths: list[str],
    ) -> None:
        """Make the seeded instruction visible even when Delta Chat skips old IMAP mail."""

        if not db_paths:
            db_paths_raw = str(
                controller.execute_adb(
                    [
                        "shell",
                        (
                            "find "
                            f"{shlex.quote(f'/data/user/0/{app_package}/files/accounts')} "
                            "-name dc.db -type f 2>/dev/null"
                        ),
                    ]
                )
                or ""
            )
            db_paths = [line.strip() for line in db_paths_raw.splitlines() if line.strip()]

        controller.execute_adb(["shell", "am", "force-stop", app_package])
        for index, db_path in enumerate(db_paths):
            cls._patch_seed_conversation_database(
                controller=controller,
                remote_db_path=db_path,
                index=index,
                seed_sender_email=seed_sender_email,
                seed_subject=seed_subject,
                seed_body=seed_body,
            )

    @classmethod
    def _patch_seed_conversation_database(
        cls,
        *,
        controller: Any,
        remote_db_path: str,
        index: int,
        seed_sender_email: str,
        seed_subject: str,
        seed_body: str,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="deltachat-seed-chat-") as tmpdir:
            tmp_path = Path(tmpdir)
            owner_group = str(
                controller.execute_adb(["shell", f"stat -c %U:%G {shlex.quote(remote_db_path)}"])
                or ""
            ).strip()
            controller.execute_adb(["pull", remote_db_path, str(tmp_path)])
            local_db = tmp_path / Path(remote_db_path).name
            for suffix in ("-wal", "-shm"):
                remote_sidecar = f"{remote_db_path}{suffix}"
                if cls._remote_file_exists(controller, remote_sidecar):
                    controller.execute_adb(["pull", remote_sidecar, str(tmp_path)])

            if not local_db.exists():
                raise RuntimeError(f"Failed to pull Delta Chat database: {remote_db_path}")

            connection = sqlite3.connect(local_db)
            try:
                connection.execute("PRAGMA busy_timeout=5000")
                cls._upsert_seed_conversation(
                    connection,
                    seed_sender_email=seed_sender_email,
                    seed_subject=seed_subject,
                    seed_body=seed_body,
                )
                connection.commit()
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                connection.close()

            controller.execute_adb(["push", str(local_db), remote_db_path])
            quoted_db = shlex.quote(remote_db_path)
            controller.execute_adb(["shell", f"rm -f {quoted_db}-wal {quoted_db}-shm"])
            if owner_group and ":" in owner_group:
                controller.execute_adb(["shell", f"chown {shlex.quote(owner_group)} {quoted_db}"])
            controller.execute_adb(["shell", f"chmod 660 {quoted_db}"])
            controller.execute_adb(["shell", f"restorecon {quoted_db} 2>/dev/null || true"])

    @classmethod
    def _upsert_seed_conversation(
        cls,
        connection: sqlite3.Connection,
        *,
        seed_sender_email: str,
        seed_subject: str,
        seed_body: str,
    ) -> None:
        now = int(time.time())
        sender = seed_sender_email.strip()
        sender_name = sender
        normalized_name = sender_name.casefold()
        normalized_body = seed_body.casefold()
        cur = connection.cursor()

        contact_row = cur.execute(
            "SELECT id FROM contacts WHERE addr = ? ORDER BY id LIMIT 1",
            (sender,),
        ).fetchone()
        if contact_row:
            contact_id = int(contact_row[0])
            cur.execute(
                """
                UPDATE contacts
                SET name = ?, blocked = 0, last_seen = ?, param = ?, name_normalized = ?
                WHERE id = ?
                """,
                (sender_name, now, f"j={now}", normalized_name, contact_id),
            )
        else:
            contact_id = cls._next_sql_id(cur, "contacts")
            cur.execute(
                """
                INSERT INTO contacts
                (id, name, addr, origin, blocked, last_seen, param, authname, selfavatar_sent,
                 status, is_bot, fingerprint, verifier, name_normalized)
                VALUES (?, ?, ?, 16, 0, ?, ?, '', 0, '', 0, '', 0, ?)
                """,
                (contact_id, sender_name, sender, now, f"j={now}", normalized_name),
            )

        chat_row = cur.execute(
            """
            SELECT c.id
            FROM chats c
            JOIN chats_contacts cc ON cc.chat_id = c.id
            WHERE c.type = 100 AND cc.contact_id = ?
            ORDER BY c.id
            LIMIT 1
            """,
            (contact_id,),
        ).fetchone()
        if chat_row:
            chat_id = int(chat_row[0])
            cur.execute(
                """
                UPDATE chats
                SET type = 100, name = ?, blocked = 0, archived = 0,
                    created_timestamp = ?, protected = 0, name_normalized = ?
                WHERE id = ?
                """,
                (sender_name, now, normalized_name, chat_id),
            )
        else:
            chat_id = cls._next_sql_id(cur, "chats")
            cur.execute(
                """
                INSERT INTO chats
                (id, type, name, draft_timestamp, draft_txt, blocked, grpid, param, archived,
                 gossiped_timestamp, locations_send_begin, locations_send_until,
                 locations_last_sent, created_timestamp, muted_until, ephemeral_timer,
                 protected, name_normalized)
                VALUES (?, 100, ?, 0, '', 0, '', '', 0, 0, 0, 0, 0, ?, 0, NULL, 0, ?)
                """,
                (chat_id, sender_name, now, normalized_name),
            )

        cur.execute("DELETE FROM chats_contacts WHERE chat_id = ?", (chat_id,))
        cur.execute(
            """
            INSERT OR REPLACE INTO chats_contacts
            (chat_id, contact_id, add_timestamp, remove_timestamp)
            VALUES (?, ?, ?, 0)
            """,
            (chat_id, contact_id, now),
        )

        msg_row = cur.execute(
            "SELECT id FROM msgs WHERE chat_id = ? AND txt = ? ORDER BY id LIMIT 1",
            (chat_id, seed_body),
        ).fetchone()
        if msg_row:
            msg_id = int(msg_row[0])
            cur.execute(
                """
                UPDATE msgs
                SET from_id = ?, to_id = 1, timestamp = ?, timestamp_sent = ?,
                    timestamp_rcvd = ?, type = 10, state = 10, msgrmsg = 1,
                    txt = ?, hidden = 0, deleted = 0, subject = ?,
                    txt_normalized = ?
                WHERE id = ?
                """,
                (contact_id, now, now, now, seed_body, seed_subject, normalized_body, msg_id),
            )
            return

        msg_id = cls._next_sql_id(cur, "msgs")
        rfc724_mid = f"seed-{chat_id}-{msg_id}-{now}@helloworld.local"
        cur.execute(
            """
            INSERT INTO msgs
            (id, rfc724_mid, server_folder, server_uid, chat_id, from_id, to_id,
             timestamp, type, state, msgrmsg, bytes, txt, txt_raw, param, starred,
             timestamp_sent, timestamp_rcvd, hidden, mime_headers, mime_in_reply_to,
             mime_references, move_state, location_id, error, ephemeral_timer,
             ephemeral_timestamp, mime_modified, subject, download_state, hop_info,
             mime_compressed, txt_normalized, deleted, pre_rfc724_mid)
            VALUES (?, ?, 'INBOX', 0, ?, ?, 1, ?, 10, 10, 1, 0, ?, '', '', 0,
                    ?, ?, 0, x'', '', '', 1, 0, '', 0, 0, 0, ?, 0,
                    'Hop: From: 127.0.0.1;', 1, ?, 0, '')
            """,
            (
                msg_id,
                rfc724_mid,
                chat_id,
                contact_id,
                now,
                seed_body,
                now,
                now,
                seed_subject,
                normalized_body,
            ),
        )

    @staticmethod
    def _next_sql_id(cur: sqlite3.Cursor, table: str) -> int:
        row = cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}").fetchone()
        return int(row[0])

    @staticmethod
    def _remote_file_exists(controller: Any, remote_path: str) -> bool:
        output = str(
            controller.execute_adb(
                [
                    "shell",
                    f"if [ -e {shlex.quote(remote_path)} ]; then echo yes; fi",
                ]
            )
            or ""
        ).strip()
        return output == "yes"

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

    @classmethod
    def _wait_for_seed_conversation_visible(
        cls,
        *,
        controller: Any,
        app_package: str,
        app_activity: str,
        seed_sender_email: str,
        seed_body: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        driver = AndroidBootstrapDriver(
            controller,
            expected_package=app_package,
            settle_delay_seconds=0.4,
            poll_interval_seconds=max(poll_interval_seconds, 0.5),
        )
        tokens = cls._seed_visibility_tokens(seed_sender_email, seed_body)
        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_visible_text = ""

        while True:
            attempts += 1
            nodes = driver.observe_nodes()
            visible_text = cls._visible_text(nodes)
            last_visible_text = visible_text[:1200]
            matched_token = cls._first_matching_token(visible_text, tokens)
            if matched_token:
                return {
                    "visible": True,
                    "attempts": attempts,
                    "matched_token": matched_token,
                    "visible_text": last_visible_text,
                }

            if time.time() >= deadline:
                return {
                    "visible": False,
                    "attempts": attempts,
                    "tokens": tokens,
                    "visible_text": last_visible_text,
                }

            cls._nudge_delta_chat_sync(
                controller=controller,
                app_package=app_package,
                app_activity=app_activity,
                attempt=attempts,
            )
            time.sleep(max(poll_interval_seconds, 0.5))

    @staticmethod
    def _seed_visibility_tokens(seed_sender_email: str, seed_body: str) -> list[str]:
        tokens: list[str] = []
        email = seed_sender_email.strip().lower()
        if email:
            tokens.append(email)
            local_part = email.split("@", 1)[0].strip()
            if local_part:
                tokens.append(local_part)
        for marker in ("FINAL_RESPONSE", "greenmail_chat_message", "BMK-DELTA-774"):
            if marker.lower() in seed_body.lower():
                tokens.append(marker.lower())
        return list(dict.fromkeys(tokens))

    @staticmethod
    def _visible_text(nodes: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for node in nodes:
            for key in ("text", "content_description", "content-desc"):
                value = str(node.get(key) or "").strip()
                if value:
                    parts.append(value)
        return "\n".join(parts).lower()

    @staticmethod
    def _first_matching_token(visible_text: str, tokens: list[str]) -> str | None:
        for token in tokens:
            if token and token.lower() in visible_text:
                return token
        return None

    @staticmethod
    def _nudge_delta_chat_sync(
        *,
        controller: Any,
        app_package: str,
        app_activity: str,
        attempt: int,
    ) -> None:
        width = int(getattr(controller, "width", 1080) or 1080)
        height = int(getattr(controller, "height", 2400) or 2400)
        if attempt % 4 == 0:
            controller.execute_adb(["shell", "am", "force-stop", app_package])
            controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"])
            return

        controller.execute_adb(
            [
                "shell",
                "input",
                "swipe",
                str(width // 2),
                str(int(height * 0.30)),
                str(width // 2),
                str(int(height * 0.62)),
                "650",
            ]
        )
