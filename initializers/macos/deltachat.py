"""Prepare seeded Delta Chat profiles on macOS for benchmark and oracle runs."""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class DeltaChatInitializer(BaseInitializer):
    """Install-free Delta Chat profile bootstrapper for macOS guest VMs."""

    DEFAULT_APP_NAME = "DeltaChat"
    DEFAULT_APP_PATH = "/Applications/DeltaChat.app"
    DEFAULT_BUNDLE_ID = "chat.delta.desktop.electron"
    DEFAULT_PROFILE_ROOT = "/Users/bench/Library/Application Support/HelloWorldDeltaChat/profile"
    DEFAULT_CACHE_ARCHIVE = "/Users/bench/Library/Application Support/HelloWorldDeltaChat/cache/seed_v1.tar.gz"
    DEFAULT_TEMP_ROOT = "/tmp/helloworld_deltachat_seed_contacts"
    DEFAULT_CHATMAIL_QR = "dcaccount:ci-chatmail.testrun.org"
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

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        app_path = str(params.get("app_path") or self.DEFAULT_APP_PATH).strip() or self.DEFAULT_APP_PATH
        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        profile_root = str(params.get("profile_root") or self.DEFAULT_PROFILE_ROOT).strip() or self.DEFAULT_PROFILE_ROOT
        cache_archive = str(params.get("cache_archive") or self.DEFAULT_CACHE_ARCHIVE).strip() or self.DEFAULT_CACHE_ARCHIVE
        temp_root = str(params.get("temp_root") or self.DEFAULT_TEMP_ROOT).strip() or self.DEFAULT_TEMP_ROOT
        chatmail_qr = str(params.get("chatmail_qr") or self.DEFAULT_CHATMAIL_QR).strip() or self.DEFAULT_CHATMAIL_QR
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        boot_timeout = int(params.get("boot_timeout_seconds", self.DEFAULT_BOOT_TIMEOUT) or self.DEFAULT_BOOT_TIMEOUT)
        force_reseed = bool(params.get("force_reseed", False))

        try:
            app_info = self._resolve_app_bundle(controller, app_name=app_name, app_path=app_path, bundle_id=bundle_id)
            self._prepare_profile(
                controller,
                app_info=app_info,
                profile_root=profile_root,
                cache_archive=cache_archive,
                temp_root=temp_root,
                chatmail_qr=chatmail_qr,
                boot_timeout=boot_timeout,
                force_reseed=force_reseed,
                expectations=None,
            )
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Delta Chat profile: {exc}",
                metadata={
                    "profile_root": profile_root,
                    "cache_archive": cache_archive,
                    "app_name": app_name,
                    "app_path": app_path,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Delta Chat benchmark profile",
            metadata={
                "profile_root": profile_root,
                "cache_archive": cache_archive,
                "manifest_path": f"{Path(profile_root).expanduser() / 'benchmark_manifest.json'}",
                "app_name": app_name,
                "resolved_app_path": app_info["app_path"],
                "rpc_path": app_info["rpc_path"],
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
            output = str(result.get("output") or result.get("stdout") or "").strip()
            error = str(result.get("error") or result.get("stderr") or "").strip()
            raise RuntimeError(error or output or f"guest command failed with exit code {returncode}")
        return result

    def _resolve_app_bundle(
        self,
        controller: Any,
        *,
        app_name: str,
        app_path: str,
        bundle_id: str,
    ) -> dict[str, str]:
        script = dedent(
            f"""
            python3 - <<'PY'
            import json
            import plistlib
            import subprocess
            from pathlib import Path

            app_name = {app_name!r}
            app_path = {app_path!r}
            bundle_id = {bundle_id!r}

            def iter_candidates():
                seen = set()
                direct = [
                    Path(app_path).expanduser(),
                    Path.home() / 'Applications' / f'{{app_name}}.app',
                    Path('/Applications') / f'{{app_name}}.app',
                ]
                for candidate in direct:
                    candidate = candidate.expanduser()
                    key = str(candidate)
                    if key in seen:
                        continue
                    seen.add(key)
                    yield candidate
                queries = [
                    f'kMDItemCFBundleIdentifier == "{{bundle_id}}"',
                    f'kMDItemFSName == "{{app_name}}.app"',
                ]
                for query in queries:
                    proc = subprocess.run(['mdfind', query], capture_output=True, text=True, check=False)
                    if proc.returncode != 0:
                        continue
                    for raw in (proc.stdout or '').splitlines():
                        candidate = Path(raw.strip())
                        if not candidate.is_dir():
                            continue
                        key = str(candidate)
                        if key in seen:
                            continue
                        seen.add(key)
                        yield candidate

            selected = None
            for candidate in iter_candidates():
                if candidate.is_dir() and candidate.suffix == '.app':
                    selected = candidate
                    break
            if selected is None:
                raise SystemExit(json.dumps({{'error': f'Delta Chat app not found for {{app_name}}'}}))

            info_plist = selected / 'Contents' / 'Info.plist'
            info = plistlib.loads(info_plist.read_bytes()) if info_plist.exists() else {{}}
            executable = str(info.get('CFBundleExecutable') or selected.stem).strip() or selected.stem
            binary_path = selected / 'Contents' / 'MacOS' / executable
            if not binary_path.exists():
                raise SystemExit(json.dumps({{'error': f'App binary missing: {{binary_path}}'}}))

            resources_root = selected / 'Contents' / 'Resources'
            rpc_candidates = []
            if resources_root.exists():
                rpc_candidates.extend(sorted(resources_root.rglob('deltachat-rpc-server')))
            rpc_path = None
            for candidate in rpc_candidates:
                if candidate.is_file():
                    rpc_path = candidate
                    break
            if rpc_path is None:
                raise SystemExit(json.dumps({{'error': f'deltachat-rpc-server missing inside {{resources_root}}'}}))

            payload = {{
                'app_path': str(selected),
                'binary_path': str(binary_path),
                'rpc_path': str(rpc_path),
                'process_name': executable,
            }}
            print(json.dumps(payload, ensure_ascii=False))
            PY
            """
        ).strip()
        result = self._run(controller, script, timeout=30)
        raw = str(result.get("output") or result.get("stdout") or "").strip()
        payload = json.loads(raw)
        if "error" in payload:
            raise RuntimeError(str(payload["error"]))
        return {str(key): str(value) for key, value in payload.items()}

    def _prepare_profile(
        self,
        controller: Any,
        *,
        app_info: Mapping[str, str],
        profile_root: str,
        cache_archive: str,
        temp_root: str,
        chatmail_qr: str,
        boot_timeout: int,
        force_reseed: bool,
        expectations: list[dict[str, str]] | None,
    ) -> None:
        profile_root_path = str(Path(profile_root).expanduser())
        cache_archive_path = str(Path(cache_archive).expanduser())
        temp_root_path = str(Path(temp_root).expanduser())
        self._stop_app(
            controller,
            process_name=str(app_info.get("process_name") or self.DEFAULT_APP_NAME),
            binary_path=str(app_info["binary_path"]),
            profile_root=profile_root_path,
        )
        if force_reseed:
            self._run(
                controller,
                "\n".join(
                    [
                        f"rm -f {shlex.quote(cache_archive_path)}",
                        f"rm -rf {shlex.quote(profile_root_path)}",
                    ]
                ),
                timeout=20,
            )
        if not self._cache_exists(controller, cache_archive_path):
            self._seed_profile(
                controller,
                profile_root=profile_root_path,
                temp_root=temp_root_path,
                cache_archive=cache_archive_path,
                chatmail_qr=chatmail_qr,
                rpc_path=str(app_info["rpc_path"]),
                timeout=boot_timeout,
            )
        self._restore_cache(controller, profile_root=profile_root_path, cache_archive=cache_archive_path)
        if expectations:
            self._apply_expected_messages(
                controller,
                profile_root=profile_root_path,
                expectations=expectations,
                timeout=max(30, len(expectations) * 5),
            )
        self._launch_app(
            controller,
            app_name=self.DEFAULT_APP_NAME,
            binary_path=str(app_info["binary_path"]),
            profile_root=profile_root_path,
        )
        try:
            self._arrange_window(controller, process_name=str(app_info.get("process_name") or self.DEFAULT_APP_NAME))
        except Exception:
            pass

    def _cache_exists(self, controller: Any, cache_archive: str) -> bool:
        result = controller.run_bash_script(f"test -f {shlex.quote(cache_archive)}", timeout=5)
        return int(result.get("returncode", 1)) == 0

    def _stop_app(self, controller: Any, *, process_name: str, binary_path: str, profile_root: str) -> None:
        script = "\n".join(
            [
                f"killall -TERM {shlex.quote(process_name)} >/dev/null 2>&1 || true",
                f"pkill -TERM -f {shlex.quote(binary_path)} >/dev/null 2>&1 || true",
                "sleep 1",
                f"killall -KILL {shlex.quote(process_name)} >/dev/null 2>&1 || true",
                f"pkill -KILL -f {shlex.quote(binary_path)} >/dev/null 2>&1 || true",
                "sleep 1",
                f"mkdir -p {shlex.quote(profile_root)}",
                f"test -f {shlex.quote(str(Path(profile_root) / 'config.json'))} || printf '{{}}\\n' > {shlex.quote(str(Path(profile_root) / 'config.json'))}",
            ]
        )
        self._run(controller, script, timeout=20)

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
        guest_script = (
            Path(__file__).resolve().parents[1] / "linux" / "deltachat_guest_seed.py"
        ).read_text(encoding="utf-8")
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

    def _launch_app(self, controller: Any, *, app_name: str, binary_path: str, profile_root: str) -> None:
        script = "\n".join(
            [
                "set -euo pipefail",
                f"mkdir -p {shlex.quote(profile_root)}",
                f"test -f {shlex.quote(str(Path(profile_root) / 'config.json'))} || printf '{{}}\\n' > {shlex.quote(str(Path(profile_root) / 'config.json'))}",
                f"export DC_TEST_DIR={shlex.quote(profile_root)}",
                f"nohup {shlex.quote(binary_path)} >/tmp/helloworld_deltachat_launch.log 2>&1 </dev/null &",
                "sleep 3",
                f"osascript -e 'tell application \"{app_name}\" to activate' >/dev/null 2>&1 || true",
            ]
        )
        self._run(controller, script, timeout=20)

    def _arrange_window(self, controller: Any, *, process_name: str) -> None:
        script = dedent(
            f"""
            osascript <<'APPLESCRIPT'
            tell application "System Events"
              if exists process "{process_name}" then
                tell process "{process_name}"
                  if exists window 1 then
                    set position of window 1 to {{60, 80}}
                    set size of window 1 to {{1500, 980}}
                  end if
                end tell
              end if
            end tell
            APPLESCRIPT
            """
        ).strip()
        self._run(controller, script, timeout=20)

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
    """Prepare the seeded Delta Chat profile, then apply evaluator-visible replies."""

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

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        app_path = str(params.get("app_path") or self.DEFAULT_APP_PATH).strip() or self.DEFAULT_APP_PATH
        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        profile_root = str(params.get("profile_root") or self.DEFAULT_PROFILE_ROOT).strip() or self.DEFAULT_PROFILE_ROOT
        cache_archive = str(params.get("cache_archive") or self.DEFAULT_CACHE_ARCHIVE).strip() or self.DEFAULT_CACHE_ARCHIVE
        temp_root = str(params.get("temp_root") or self.DEFAULT_TEMP_ROOT).strip() or self.DEFAULT_TEMP_ROOT
        chatmail_qr = str(params.get("chatmail_qr") or self.DEFAULT_CHATMAIL_QR).strip() or self.DEFAULT_CHATMAIL_QR
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        boot_timeout = int(params.get("boot_timeout_seconds", self.DEFAULT_BOOT_TIMEOUT) or self.DEFAULT_BOOT_TIMEOUT)
        force_reseed = bool(params.get("force_reseed", False))

        try:
            app_info = self._resolve_app_bundle(controller, app_name=app_name, app_path=app_path, bundle_id=bundle_id)
            self._prepare_profile(
                controller,
                app_info=app_info,
                profile_root=profile_root,
                cache_archive=cache_archive,
                temp_root=temp_root,
                chatmail_qr=chatmail_qr,
                boot_timeout=boot_timeout,
                force_reseed=force_reseed,
                expectations=expectations,
            )
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
                    "app_name": app_name,
                    "app_path": app_path,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Delta Chat oracle profile",
            metadata={
                "profile_root": profile_root,
                "cache_archive": cache_archive,
                "manifest_path": f"{Path(profile_root).expanduser() / 'benchmark_manifest.json'}",
                "expected_message_count": len(expectations),
            },
        )
