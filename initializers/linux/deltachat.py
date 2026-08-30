"""Initializer utilities for Delta Chat desktop tasks on Linux."""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class DeltaChatInitializer(BaseInitializer):
    """Restore a seeded Delta Chat profile and launch the desktop app."""

    DEFAULT_APP_COMMAND = "deltachat-desktop"
    DEFAULT_PROFILE_ROOT = "/tmp/helloworld_deltachat_profile"
    DEFAULT_CACHE_ARCHIVE = "/home/user/.cache/helloworld_deltachat/seed_v2.tar.gz"
    DEFAULT_TEMP_ROOT = "/tmp/helloworld_deltachat_seed_contacts"
    DEFAULT_CHATMAIL_QR = "dcaccount:ci-chatmail.testrun.org"
    DEFAULT_RPC_PATH = (
        "/opt/DeltaChat/resources/app.asar.unpacked/node_modules/"
        "@deltachat/stdio-rpc-server-linux-x64/deltachat-rpc-server"
    )
    DEFAULT_FINAL_WAIT_MS = 5000
    DEFAULT_BOOT_TIMEOUT = 240

    CONTACT_SEEDS = [
        {
            "key": "alice",
            "display_name": "Alice",
            "messages": [
                "Hey, can we move our meeting to 3 PM?",
                "Please use room Cedar-3 if you confirm.",
                "Bob still needs the budget file after the meeting.",
            ],
        },
        {
            "key": "bob",
            "display_name": "Bob",
            "messages": [
                "Please send me the latest budget sheet today.",
                "Use the file name budget-april-v7.xlsx.",
                "I need it by 5 PM.",
            ],
        },
        {
            "key": "nora",
            "display_name": "Nora",
            "messages": [
                "What is the order number for the coffee restock?",
                "Use order number CFX-2048 in the outgoing update.",
                "The vendor is Northwind Beans.",
                "I need the details before 4:30 PM.",
            ],
        },
        {
            "key": "support",
            "display_name": "Support Desk",
            "messages": [
                "Can you describe what happened after the restart?",
                "Please include ticket SR-88 and error code WX-17.",
                "Mention that the app recovered after the second launch.",
            ],
        },
        {
            "key": "finance",
            "display_name": "Finance Desk",
            "messages": [
                "Keep the budget filename as budget-april-v7.xlsx.",
                "The owner initials should stay MK.",
            ],
        },
        {
            "key": "malik",
            "display_name": "Malik",
            "messages": [
                "I can own the escalation window.",
                "Use 19:30-20:00 as the deployment window.",
            ],
        },
    ]

    GROUP_SEED = {
        "name": "Ops Sprint",
        "members": ["alice", "bob"],
        "messages": [
            "Ops Sprint memo: QA update due 6 PM.",
            "Escalation owner is Malik.",
            "Deployment window is 19:30-20:00.",
        ],
    }

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        profile_root = str(params.get("profile_root") or self.DEFAULT_PROFILE_ROOT).strip()
        cache_archive = str(params.get("cache_archive") or self.DEFAULT_CACHE_ARCHIVE).strip()
        temp_root = str(params.get("temp_root") or self.DEFAULT_TEMP_ROOT).strip()
        chatmail_qr = str(params.get("chatmail_qr") or self.DEFAULT_CHATMAIL_QR).strip()
        rpc_path = str(params.get("rpc_path") or self.DEFAULT_RPC_PATH).strip()
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        boot_timeout = int(params.get("boot_timeout_seconds", self.DEFAULT_BOOT_TIMEOUT) or self.DEFAULT_BOOT_TIMEOUT)
        force_reseed = bool(params.get("force_reseed", False))

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._run(controller, f"test -x {shlex.quote(rpc_path)}", timeout=10)
            self._stop_app(controller)
            if force_reseed:
                self._run(
                    controller,
                    f"rm -f {shlex.quote(cache_archive)} && rm -rf {shlex.quote(profile_root)}",
                    timeout=20,
                )
            if not self._cache_exists(controller, cache_archive):
                self._seed_profile(
                    controller,
                    profile_root=profile_root,
                    temp_root=temp_root,
                    cache_archive=cache_archive,
                    chatmail_qr=chatmail_qr,
                    rpc_path=rpc_path,
                    timeout=boot_timeout,
                )
            self._restore_cache(
                controller,
                profile_root=profile_root,
                cache_archive=cache_archive,
            )
            self._launch_app(controller, app_command=app_command, profile_root=profile_root)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Delta Chat profile: {exc}",
                metadata={
                    "profile_root": profile_root,
                    "cache_archive": cache_archive,
                    "chatmail_qr": chatmail_qr,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Delta Chat benchmark profile",
            metadata={
                "profile_root": profile_root,
                "cache_archive": cache_archive,
                "manifest_path": f"{profile_root}/benchmark_manifest.json",
            },
        )

    @staticmethod
    def _normalize_expectations(params: Mapping[str, Any]) -> list[dict[str, str]]:
        expectations = params.get("expectations")
        if expectations is None:
            chat_name = str(params.get("chat_name") or "").strip()
            expected_text = str(params.get("expected_text") or "").strip()
            if chat_name and expected_text:
                expectations = [{"chat_name": chat_name, "expected_text": expected_text}]
        normalized: list[dict[str, str]] = []
        if not isinstance(expectations, list):
            return normalized
        for item in expectations:
            if not isinstance(item, Mapping):
                continue
            chat_name = str(item.get("chat_name") or "").strip()
            expected_text = str(item.get("expected_text") or "").strip()
            if chat_name and expected_text:
                normalized.append({"chat_name": chat_name, "expected_text": expected_text})
        return normalized

    @staticmethod
    def _run(controller: Any, script: str, *, timeout: int) -> Mapping[str, Any]:
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        if returncode != 0:
            output = str(result.get("output", "")).strip()
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        return result

    def _cache_exists(self, controller: Any, cache_archive: str) -> bool:
        result = controller.run_bash_script(
            f"test -f {shlex.quote(cache_archive)}",
            timeout=5,
        )
        return int(result.get("returncode", 1)) == 0

    def _stop_app(self, controller: Any) -> None:
        self._run(
            controller,
            "\n".join(
                [
                    "pkill -TERM -f 'deltachat-desktop|/opt/DeltaChat/deltachat-desktop' || true",
                    "sleep 1",
                    "pkill -KILL -f 'deltachat-desktop|/opt/DeltaChat/deltachat-desktop' || true",
                    "sleep 1",
                ]
            ),
            timeout=15,
        )

    def _seed_profile(
        self,
        controller: Any,
        *,
        profile_root: str,
        temp_root: str,
        cache_archive: str,
        chatmail_qr: str,
        rpc_path: str,
        timeout: int,
    ) -> None:
        guest_script = Path(__file__).with_name("deltachat_guest_seed.py").read_text(encoding="utf-8")
        payload = {
            "profile_root": profile_root,
            "temp_root": temp_root,
            "rpc_path": rpc_path,
            "chatmail_qr": chatmail_qr,
            "owner_display_name": "Benchmark Owner",
            "contacts": self.CONTACT_SEEDS,
            "group": self.GROUP_SEED,
        }
        script = "\n".join(
            [
                f"export HELLOWORLD_DELTA_SEED_JSON={shlex.quote(json.dumps(payload, ensure_ascii=False))}",
                f"mkdir -p {shlex.quote(str(Path(cache_archive).parent))}",
                "python3 - <<'PY'",
                guest_script.rstrip(),
                "PY",
                f"rm -f {shlex.quote(cache_archive)}",
                f"tar -czf {shlex.quote(cache_archive)} -C {shlex.quote(str(Path(profile_root).parent))} {shlex.quote(Path(profile_root).name)}",
            ]
        )
        self._run(controller, script, timeout=max(timeout, 300))

    def _restore_cache(self, controller: Any, *, profile_root: str, cache_archive: str) -> None:
        parent = str(Path(profile_root).parent)
        profile_name = Path(profile_root).name
        script = "\n".join(
            [
                f"rm -rf {shlex.quote(profile_root)}",
                f"mkdir -p {shlex.quote(parent)}",
                f"tar -xzf {shlex.quote(cache_archive)} -C {shlex.quote(parent)}",
                f"test -f {shlex.quote(str(Path(profile_root) / 'benchmark_manifest.json'))}",
                f"test -d {shlex.quote(str(Path(profile_root) / 'accounts'))}",
                f"printf '%s\\n' {shlex.quote(profile_name)} >/dev/null",
            ]
        )
        self._run(controller, script, timeout=30)

    def _launch_app(self, controller: Any, *, app_command: str, profile_root: str) -> None:
        launch_script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                f"export DC_TEST_DIR={shlex.quote(profile_root)}",
                f"setsid -f bash -lc {shlex.quote(app_command)} >/tmp/helloworld_deltachat_launch.log 2>&1",
            ]
        )
        self._run(controller, launch_script, timeout=15)

    def _apply_expected_messages(
        self,
        controller: Any,
        *,
        profile_root: str,
        expectations: list[dict[str, str]],
        timeout: int = 30,
    ) -> None:
        payload = json.dumps(expectations, ensure_ascii=False)
        script = "\n".join(
            [
                f"export HELLOWORLD_DELTA_EXPECTATIONS={shlex.quote(payload)}",
                "python3 - <<'PY'",
                "import json",
                "import os",
                "import pathlib",
                "import sqlite3",
                "import time",
                f"root = pathlib.Path({json.dumps(profile_root, ensure_ascii=False)})",
                "manifest = json.loads((root / 'benchmark_manifest.json').read_text(encoding='utf-8'))",
                "db_path = root / manifest['main_account']['db_path']",
                "expectations = json.loads(os.environ['HELLOWORLD_DELTA_EXPECTATIONS'])",
                "con = sqlite3.connect(db_path)",
                "try:",
                "    cur = con.cursor()",
                "    self_row = cur.execute(\"select id from contacts where name='self' order by id limit 1\").fetchone()",
                "    if self_row is None:",
                "        raise SystemExit('missing self contact in Delta Chat db')",
                "    self_contact_id = int(self_row[0])",
                "    base_ts = int(time.time())",
                "    for index, item in enumerate(expectations):",
                "        row = cur.execute(\"select id from chats where name = ? order by id limit 1\", (str(item['chat_name']),)).fetchone()",
                "        if row is None:",
                "            raise SystemExit(f\"missing chat named {item['chat_name']!r}\")",
                "        text = str(item['expected_text'])",
                "        ts = base_ts + index",
                "        cur.execute(",
                "            \"insert into msgs (chat_id, from_id, to_id, timestamp, type, state, msgrmsg, txt, hidden, timestamp_sent, timestamp_rcvd, txt_normalized) values (?, ?, 0, ?, 10, 26, 1, ?, 0, 0, 0, ?)\",",
                "            (int(row[0]), self_contact_id, ts, text, text.casefold()),",
                "        )",
                "    con.commit()",
                "finally:",
                "    con.close()",
                "PY",
            ]
        )
        self._run(controller, script, timeout=timeout)


class DeltaChatOracleInitializer(DeltaChatInitializer):
    """Prepare the normal Delta Chat profile, then synchronously apply oracle messages."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        expectations = self._normalize_expectations(params)
        if not expectations:
            return InitResult(
                status=InitStatus.ERROR,
                message="DeltaChatOracleInitializer requires params.expectations or chat_name+expected_text",
            )

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        profile_root = str(params.get("profile_root") or self.DEFAULT_PROFILE_ROOT).strip()
        cache_archive = str(params.get("cache_archive") or self.DEFAULT_CACHE_ARCHIVE).strip()
        temp_root = str(params.get("temp_root") or self.DEFAULT_TEMP_ROOT).strip()
        chatmail_qr = str(params.get("chatmail_qr") or self.DEFAULT_CHATMAIL_QR).strip()
        rpc_path = str(params.get("rpc_path") or self.DEFAULT_RPC_PATH).strip()
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        boot_timeout = int(params.get("boot_timeout_seconds", self.DEFAULT_BOOT_TIMEOUT) or self.DEFAULT_BOOT_TIMEOUT)
        force_reseed = bool(params.get("force_reseed", False))

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._run(controller, f"test -x {shlex.quote(rpc_path)}", timeout=10)
            self._stop_app(controller)
            if force_reseed:
                self._run(
                    controller,
                    f"rm -f {shlex.quote(cache_archive)} && rm -rf {shlex.quote(profile_root)}",
                    timeout=20,
                )
            if not self._cache_exists(controller, cache_archive):
                self._seed_profile(
                    controller,
                    profile_root=profile_root,
                    temp_root=temp_root,
                    cache_archive=cache_archive,
                    chatmail_qr=chatmail_qr,
                    rpc_path=rpc_path,
                    timeout=boot_timeout,
                )
            self._restore_cache(
                controller,
                profile_root=profile_root,
                cache_archive=cache_archive,
            )
            self._apply_expected_messages(
                controller,
                profile_root=profile_root,
                expectations=expectations,
                timeout=max(30, len(expectations) * 5),
            )
            self._launch_app(controller, app_command=app_command, profile_root=profile_root)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Delta Chat oracle profile: {exc}",
                metadata={
                    "profile_root": profile_root,
                    "cache_archive": cache_archive,
                    "expectations": expectations,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Delta Chat oracle profile",
            metadata={
                "profile_root": profile_root,
                "cache_archive": cache_archive,
                "manifest_path": f"{profile_root}/benchmark_manifest.json",
                "expected_message_count": len(expectations),
            },
        )
