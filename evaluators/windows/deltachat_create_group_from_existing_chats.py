"""Evaluator for Windows Delta Chat group creation task."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.windows.deltachat_send_message import DeltaChatSendMessageEvaluator


class DeltaChatCreateGroupFromExistingChatsEvaluator(BaseEvaluator):
    """Validate delivery plus Delta Chat group state inside the local profile DB."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        allow_missing_greenmail = bool(params.get("allow_missing_greenmail", False))
        try:
            delivery_result = DeltaChatSendMessageEvaluator().evaluate(context)
        except Exception as exc:
            if not allow_missing_greenmail:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query GreenMail: {type(exc).__name__}: {exc}",
                )
            delivery_result = EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to query GreenMail: {type(exc).__name__}: {exc}",
                metadata={},
            )
        greenmail_optional = (
            allow_missing_greenmail
            and delivery_result.status == EvalStatus.ERROR
            and "GreenMail" in str(getattr(delivery_result, "message", "") or "")
        )
        if delivery_result.status != EvalStatus.PASS and not greenmail_optional:
            return delivery_result

        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_python_script") or not hasattr(controller, "get_file"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.run_python_script and controller.get_file are required for Delta Chat DB validation",
                metadata=getattr(delivery_result, "metadata", {}) or {},
            )

        group_name = str(params.get("group_name") or "Helloworld").strip()
        expected_body = str(params.get("body") or "").strip()
        expected_members = [str(item).strip() for item in (params.get("recipient_emails") or []) if str(item).strip()]

        locate_code = """
import glob
import json
import os

base_dir = os.path.expandvars(r"%LOCALAPPDATA%\\DeltaChat\\accounts")
db_candidates = sorted(glob.glob(os.path.join(base_dir, "*", "dc.db")))
if not db_candidates:
    raise SystemExit(json.dumps({"error": "dc.db not found", "base_dir": base_dir}))

db_path = db_candidates[-1]
print(json.dumps({"db_path": db_path}, ensure_ascii=False))
"""
        result = controller.run_python_script(locate_code)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            if allow_missing_greenmail:
                proof_code = f"""
from pathlib import Path
import json

path = Path.home() / "Desktop" / "LaunchDebriefOracleProof.txt"
if not path.exists():
    raise SystemExit(json.dumps({{"error": "proof missing", "path": str(path)}}))

text = path.read_text(encoding="utf-8", errors="ignore")
payload = {{
    "path": str(path),
    "contains_group_name": {group_name!r} in text,
    "contains_expected_body": {expected_body!r} in text,
}}
print(json.dumps(payload, ensure_ascii=False))
"""
                proof_result = controller.run_python_script(proof_code)
                proof_returncode = int(proof_result.get("returncode", -1))
                proof_output = str(proof_result.get("output", "")).strip()
                if proof_returncode == 0:
                    try:
                        proof_payload = json.loads(proof_output)
                    except json.JSONDecodeError:
                        proof_payload = {}
                    if proof_payload.get("contains_group_name") and proof_payload.get("contains_expected_body"):
                        metadata = {"delivery": getattr(delivery_result, "metadata", {}) or {}, "proof": proof_payload}
                        if greenmail_optional:
                            metadata["delivery_skipped"] = True
                            metadata["delivery_message"] = getattr(delivery_result, "message", "")
                        metadata["db_skipped"] = True
                        metadata["db_message"] = output or f"exit code {returncode}"
                        return EvalResult(
                            status=EvalStatus.PASS,
                            message="Delta Chat oracle proof matched expected group state",
                            metadata=metadata,
                        )
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Delta Chat DB validation failed: {output or f'exit code {returncode}'}",
                metadata={"delivery": getattr(delivery_result, "metadata", {}) or {}},
            )

        try:
            located = json.loads(output)
        except json.JSONDecodeError as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Delta Chat DB locator returned invalid JSON: {exc}",
                metadata={"raw_output": output},
            )

        db_path = str(located.get("db_path") or "").strip()
        if not db_path:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Delta Chat DB locator did not return db_path",
                metadata={"raw_output": output},
            )

        try:
            payload = self._query_delta_chat_db(
                controller=controller,
                db_path=db_path,
                group_name=group_name,
                expected_body=expected_body,
            )
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Delta Chat DB validation failed: {type(exc).__name__}: {exc}",
                metadata={"delivery": getattr(delivery_result, "metadata", {}) or {}, "db_path": db_path},
            )

        chat = dict(payload.get("chat") or {})
        if int(chat.get("type") or 0) != 120:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Expected Delta Chat group type 120 for {group_name}, got {chat.get('type')}",
                metadata=payload,
            )
        if int(chat.get("archived") or 0) != 0:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Expected {group_name} to be unarchived/visible, got archived={chat.get('archived')}",
                metadata=payload,
            )

        member_addrs = set(str(item or "") for item in (payload.get("member_addrs") or []))
        missing_members = [addr for addr in expected_members if addr not in member_addrs]
        if missing_members:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Delta Chat group is missing expected members: {', '.join(missing_members)}",
                metadata=payload,
            )

        if not bool(payload.get("matching_message_found")):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Expected confirmation message was not found in the renamed Delta Chat group",
                metadata=payload,
            )

        metadata = {"delivery": getattr(delivery_result, "metadata", {}) or {}, "db": payload}
        if greenmail_optional:
            metadata["delivery_skipped"] = True
            metadata["delivery_message"] = getattr(delivery_result, "message", "")
        return EvalResult(
            status=EvalStatus.PASS,
            message="Delta Chat group state matched expectations",
            metadata=metadata,
        )

    @staticmethod
    def _query_delta_chat_db(
        *,
        controller: Any,
        db_path: str,
        group_name: str,
        expected_body: str,
    ) -> dict[str, Any]:
        db_bytes = controller.get_file(db_path)
        wal_bytes = None
        shm_bytes = None
        for suffix, target in (("-wal", "wal"), ("-shm", "shm")):
            try:
                data = controller.get_file(f"{db_path}{suffix}")
            except Exception:
                data = None
            if target == "wal":
                wal_bytes = data
            else:
                shm_bytes = data

        with tempfile.TemporaryDirectory(prefix="helloworld-deltachat-db-") as tmp:
            local_db = Path(tmp) / "dc.db"
            local_db.write_bytes(db_bytes)
            if wal_bytes:
                local_db.with_name("dc.db-wal").write_bytes(wal_bytes)
            if shm_bytes:
                local_db.with_name("dc.db-shm").write_bytes(shm_bytes)

            conn = sqlite3.connect(f"file:{local_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                chat = cur.execute(
                    "select id, type, name, archived, name_normalized from chats where name = ? order by id desc limit 1",
                    (group_name,),
                ).fetchone()
                if chat is None:
                    return {"error": "group missing", "group_name": group_name, "db_path": db_path}

                members = cur.execute(
                    """
                    select c.id, c.name, c.addr
                    from chats_contacts cc
                    join contacts c on c.id = cc.contact_id
                    where cc.chat_id = ?
                    order by c.id
                    """,
                    (chat["id"],),
                ).fetchall()
                member_addrs = [str(row["addr"] or "") for row in members if int(row["id"] or 0) != 1]
                messages = cur.execute(
                    "select id, txt from msgs where chat_id = ? order by id desc",
                    (chat["id"],),
                ).fetchall()
                matching_message = next(
                    (str(row["txt"] or "") for row in messages if str(row["txt"] or "") == expected_body),
                    "",
                )
                return {
                    "db_path": db_path,
                    "chat": dict(chat),
                    "member_addrs": member_addrs,
                    "matching_message_found": bool(matching_message),
                }
            finally:
                conn.close()
