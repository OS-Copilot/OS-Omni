"""SQLite-backed evaluator for Delta Chat desktop tasks on Linux."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


def normalize_message_text(value: object) -> str:
    """Normalize human-entered chat text for evaluator comparison."""

    return " ".join(str(value or "").split())


class DeltaChatMessageEvaluator(BaseEvaluator):
    """Validate the latest visible message in a Delta Chat chat."""

    DEFAULT_PROFILE_ROOT = "/tmp/helloworld_deltachat_profile"
    DEFAULT_TIMEOUT = 20

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        profile_root = str(params.get("profile_root") or self.DEFAULT_PROFILE_ROOT).strip()
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        expectations = params.get("expectations")
        if expectations is None:
            chat_name = str(params.get("chat_name") or "").strip()
            expected_text = str(params.get("expected_text") or "").strip()
            if chat_name and expected_text:
                expectations = [{"chat_name": chat_name, "expected_text": expected_text}]

        if not isinstance(expectations, list) or not expectations:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params must provide either chat_name+expected_text or a non-empty expectations list",
            )

        script = f"""python3 - <<'PY'
import json
import pathlib
import sqlite3
import sys

root = pathlib.Path({json.dumps(profile_root, ensure_ascii=False)})
manifest = json.loads((root / "benchmark_manifest.json").read_text(encoding="utf-8"))
db_path = root / manifest["main_account"]["db_path"]
con = sqlite3.connect(db_path)
cur = con.cursor()
self_row = cur.execute("select id from contacts where name='self' order by id limit 1").fetchone()
if self_row is None:
    raise SystemExit("missing self contact in Delta Chat db")
self_contact_id = int(self_row[0])
expectations = json.loads({json.dumps(json.dumps(expectations, ensure_ascii=False), ensure_ascii=False)})
results = []
for expected in expectations:
    chat_name = str(expected["chat_name"])
    row = cur.execute(
        \"\"\"
        select m.id, m.txt, m.from_id, c.name
        from msgs m
        join chats c on c.id = m.chat_id
        where c.name = ?
          and m.hidden = 0
          and m.txt != ''
          and m.txt != 'Messages are end-to-end encrypted.'
        order by m.id desc
        limit 1
        \"\"\",
        (chat_name,),
    ).fetchone()
    if row is None:
        results.append({{"status": "missing", "chat_name": chat_name, "expected_text": str(expected["expected_text"])}})
        continue
    results.append(
        {{
            "status": "ok",
            "chat_name": row[3],
            "message_id": int(row[0]),
            "text": row[1],
            "from_self": int(row[2]) == self_contact_id,
            "expected_text": str(expected["expected_text"]),
        }}
    )
print(json.dumps({{"results": results}}, ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=output or f"guest command failed with exit code {returncode}",
            )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Delta Chat evaluator returned invalid JSON: {exc}: {output}",
            )

        results = list(payload.get("results") or [])
        if not results:
            return EvalResult(status=EvalStatus.ERROR, message="Delta Chat evaluator returned no chat results")
        for item in results:
            chat_name = str(item.get("chat_name") or "")
            expected_text = str(item.get("expected_text") or "")
            if item.get("status") != "ok":
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"chat {chat_name} has no visible messages to validate",
                    metadata=payload,
                )
            if not bool(item.get("from_self")):
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"latest visible message in chat {chat_name} was not sent by the benchmark account",
                    metadata=payload,
                )
            actual_text_raw = str(item.get("text") or "")
            if normalize_message_text(actual_text_raw) != normalize_message_text(expected_text):
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=(
                        f"expected latest message in chat {chat_name} to be {expected_text!r}, "
                        f"got {actual_text_raw!r}"
                    ),
                    metadata=payload,
                )
        return EvalResult(
            status=EvalStatus.PASS,
            message="Delta Chat message evaluation passed",
            metadata=payload,
        )
