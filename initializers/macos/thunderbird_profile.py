"""Prepare a deterministic Thunderbird profile baseline on macOS."""

from __future__ import annotations

import json
import time
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class ThunderbirdProfileInitializer(BaseInitializer):
    """Reset Thunderbird into a deterministic profile with optional seeded local mailboxes."""

    DEFAULT_WAIT_MS = 5000
    DEFAULT_APP_NAME = "Thunderbird"
    DEFAULT_APP_PATH = "/Applications/Thunderbird.app"
    DEFAULT_PROFILE_NAME = "benchprofile"
    DEFAULT_PROFILE_SUFFIX = "default-release"
    DEFAULT_BUNDLE_ID = "org.mozilla.thunderbird"
    CONTACT_PROMPT_BUNDLE_ID = "com.apple.UserNotificationCenter"
    CONTACT_PROMPT_TEXTS = {"Don't Allow", "不允许"}
    CONTACT_PROMPT_IDENTIFIERS = {"action-button-3"}
    CALENDAR_PROFILE_UUID = "00000000-0000-0000-0000-000000000001"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required for Thunderbird initialization")

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        app_path = str(params.get("app_path") or self.DEFAULT_APP_PATH).strip() or self.DEFAULT_APP_PATH
        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        profile_name = str(params.get("profile_name") or self.DEFAULT_PROFILE_NAME).strip() or self.DEFAULT_PROFILE_NAME
        profile_suffix = str(params.get("profile_suffix") or self.DEFAULT_PROFILE_SUFFIX).strip() or self.DEFAULT_PROFILE_SUFFIX
        open_calendar = bool(params.get("open_calendar", False))
        launch_mail = bool(params.get("launch_mail", False))
        enable_home_calendar = bool(params.get("enable_home_calendar", open_calendar))
        deny_contacts_prompt = bool(params.get("deny_contacts_prompt", True))
        start_fake_smtp = bool(params.get("start_fake_smtp", False))
        smtp_port = int(params.get("smtp_port", 1025) or 1025)
        smtp_capture_dir = str(
            params.get("smtp_capture_dir") or "~/Library/Application Support/ThunderbirdBench/fake_smtp"
        ).strip() or "~/Library/Application Support/ThunderbirdBench/fake_smtp"
        seed_mailboxes = [item for item in (params.get("seed_mailboxes") or []) if isinstance(item, Mapping)]
        extra_user_prefs = [str(item).strip() for item in (params.get("user_prefs") or []) if str(item).strip()]

        try:
            resolved_app_path = self._resolve_remote_app_path(
                controller,
                app_name=app_name,
                app_path=app_path,
                bundle_id=bundle_id,
            )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Thunderbird app lookup failed: {exc}",
                metadata={"app_name": app_name, "app_path": app_path, "bundle_id": bundle_id},
            )
        if not resolved_app_path:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Thunderbird app not found in guest (checked {app_path}, ~/Applications, /Applications, Spotlight)",
                metadata={"app_name": app_name, "app_path": app_path, "bundle_id": bundle_id},
            )

        script = self._build_script(
            app_path=resolved_app_path,
            profile_name=profile_name,
            profile_suffix=profile_suffix,
            start_fake_smtp=start_fake_smtp,
            smtp_port=smtp_port,
            smtp_capture_dir=smtp_capture_dir,
            seed_mailboxes=seed_mailboxes,
            extra_user_prefs=extra_user_prefs,
        )

        try:
            result = controller.run_bash_script(script, timeout=int(params.get("timeout", 120) or 120))
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Thunderbird profile: {exc}",
                metadata={"app_name": app_name, "profile_name": profile_name},
            )

        status = str(result.get("status") or "").lower()
        returncode = result.get("returncode")
        if status in {"error", "failed", "fail"} or (isinstance(returncode, int) and returncode != 0):
            return InitResult(
                status=InitStatus.ERROR,
                message=(
                    "Thunderbird profile setup failed: "
                    f"{result.get('error') or result.get('message') or result.get('output') or result}"
                ),
                metadata={"setup_result": result},
            )

        launch_args: list[str] = []
        if open_calendar:
            launch_args.append("-calendar")
        elif launch_mail:
            launch_args.append("-mail")

        try:
            if launch_args:
                controller.run_bash_script(
                    self._build_relaunch_script(
                        app_path=resolved_app_path,
                        profile_name=profile_name,
                        profile_suffix=profile_suffix,
                        launch_args=launch_args,
                    ),
                    timeout=30,
                )
            else:
                controller.run_bash_script(self._build_open_app_script(app_path=resolved_app_path), timeout=30)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Thunderbird launch failed after profile reset: {exc}",
                metadata={"setup_result": result, "launch_args": launch_args},
            )

        if deny_contacts_prompt:
            try:
                dismissed = self._dismiss_contacts_prompt(controller)
                if dismissed:
                    controller.run_bash_script(self._build_open_app_script(app_path=resolved_app_path), timeout=30)
                    if wait_ms > 0:
                        time.sleep(min(wait_ms, 2500) / 1000.0)
            except Exception:
                dismissed = False
        else:
            dismissed = False

        calendar_enable_result: dict[str, Any] | None = None
        if enable_home_calendar:
            try:
                calendar_enable_result = controller.run_bash_script(
                    self._build_enable_calendar_script(
                        profile_name=profile_name,
                        profile_suffix=profile_suffix,
                    ),
                    timeout=30,
                )
            except Exception as exc:
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"Failed to enable Thunderbird Home calendar: {exc}",
                    metadata={"setup_result": result, "launch_args": launch_args},
                )

            enable_status = str(calendar_enable_result.get("status") or "").lower()
            enable_returncode = calendar_enable_result.get("returncode")
            if enable_status in {"error", "failed", "fail"} or (
                isinstance(enable_returncode, int) and enable_returncode != 0
            ):
                return InitResult(
                    status=InitStatus.ERROR,
                    message=(
                        "Thunderbird calendar setup failed: "
                        f"{calendar_enable_result.get('error') or calendar_enable_result.get('message') or calendar_enable_result.get('output') or calendar_enable_result}"
                    ),
                    metadata={"setup_result": result, "calendar_enable_result": calendar_enable_result},
                )

            try:
                if launch_args:
                    controller.run_bash_script(
                        self._build_relaunch_script(
                            app_path=resolved_app_path,
                            profile_name=profile_name,
                            profile_suffix=profile_suffix,
                            launch_args=launch_args,
                        ),
                        timeout=30,
                    )
                else:
                    controller.run_bash_script(self._build_open_app_script(app_path=resolved_app_path), timeout=30)
                if wait_ms > 0:
                    time.sleep(min(wait_ms, 3000) / 1000.0)
            except Exception as exc:
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"Thunderbird relaunch failed after enabling Home calendar: {exc}",
                    metadata={"setup_result": result, "calendar_enable_result": calendar_enable_result},
                )

        try:
            controller.run_bash_script(
                self._build_window_arrange_script(app_name=app_name),
                timeout=20,
            )
        except Exception:
            pass

        return InitResult(
            status=InitStatus.PASS,
            message=f"Prepared Thunderbird profile '{profile_name}'",
            metadata={
                "app_name": app_name,
                "app_path": resolved_app_path,
                "bundle_id": bundle_id,
                "profile_name": profile_name,
                "profile_suffix": profile_suffix,
                "open_calendar": open_calendar,
                "launch_mail": launch_mail,
                "enable_home_calendar": enable_home_calendar,
                "deny_contacts_prompt": deny_contacts_prompt,
                "contacts_prompt_dismissed": dismissed,
                "start_fake_smtp": start_fake_smtp,
                "smtp_port": smtp_port,
                "smtp_capture_dir": smtp_capture_dir,
                "seed_mailbox_count": len(seed_mailboxes),
                "setup_result": result,
                "calendar_enable_result": calendar_enable_result,
            },
        )

    def _dismiss_contacts_prompt(self, controller: Any) -> bool:
        if not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            return False

        for _ in range(3):
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            foreground_bundle = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
            if foreground_bundle != self.CONTACT_PROMPT_BUNDLE_ID:
                return False
            ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            target_node_id = self._find_contacts_prompt_button(ui_nodes)
            if not target_node_id:
                time.sleep(0.5)
                continue
            controller.execute_action({"type": "tap", "target": target_node_id}, ui_nodes)
            time.sleep(1.0)
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            foreground_bundle = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
            if foreground_bundle != self.CONTACT_PROMPT_BUNDLE_ID:
                return True
        return False

    def _find_contacts_prompt_button(self, ui_nodes: list[dict[str, Any]]) -> str | None:
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "AXButton":
                continue
            identifier = str(node.get("identifier") or "").strip()
            text = str(node.get("text") or "").strip()
            if identifier in self.CONTACT_PROMPT_IDENTIFIERS or text in self.CONTACT_PROMPT_TEXTS:
                node_id = str(node.get("id") or "").strip()
                if node_id:
                    return node_id
        return None

    @classmethod
    def _build_relaunch_script(
        cls,
        *,
        app_path: str,
        profile_name: str,
        profile_suffix: str,
        launch_args: Iterable[str],
    ) -> str:
        args = " ".join(json.dumps(str(arg)) for arg in launch_args)
        profile_dir = f'$HOME/Library/Thunderbird/Profiles/{profile_name}.{profile_suffix}'
        return dedent(
            f"""
            set -euo pipefail
            APP_PATH=$(python3 - <<'PY'
            from pathlib import Path
            print(Path({json.dumps(app_path)}).expanduser())
            PY
            )
            pkill -x thunderbird >/dev/null 2>&1 || true
            pkill -x Thunderbird >/dev/null 2>&1 || true
            [ -d "$APP_PATH" ] || {{ echo "Thunderbird.app missing: $APP_PATH" >&2; exit 1; }}
            open -a "$APP_PATH" --args -profile "{profile_dir}" {args} >/dev/null 2>&1
            """
        ).strip()

    @staticmethod
    def _build_open_app_script(*, app_path: str) -> str:
        return dedent(
            f"""
            set -euo pipefail
            APP_PATH=$(python3 - <<'PY'
            from pathlib import Path
            print(Path({json.dumps(app_path)}).expanduser())
            PY
            )
            [ -d "$APP_PATH" ] || {{ echo "Thunderbird.app missing: $APP_PATH" >&2; exit 1; }}
            open -a "$APP_PATH" >/dev/null 2>&1
            """
        ).strip()

    @staticmethod
    def _resolve_remote_app_path(controller: Any, *, app_name: str, app_path: str, bundle_id: str) -> str | None:
        script = dedent(
            f"""
            python3 - <<'PY'
            import json
            import subprocess
            import sys
            from pathlib import Path

            app_name = {json.dumps(app_name)}
            bundle_id = {json.dumps(bundle_id)}
            candidates = [
                Path({json.dumps(app_path)}).expanduser(),
                Path.home() / "Applications" / f"{{app_name}}.app",
                Path("/Applications") / f"{{app_name}}.app",
            ]
            for candidate in candidates:
                if candidate.is_dir():
                    print(candidate)
                    raise SystemExit(0)

            queries = [
                f'kMDItemCFBundleIdentifier == "{{bundle_id}}"',
                f'kMDItemFSName == "{{app_name}}.app"',
            ]
            for query in queries:
                proc = subprocess.run(
                    ["mdfind", query],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                for line in proc.stdout.splitlines():
                    path = Path(line.strip())
                    if path.suffix == ".app" and path.is_dir():
                        print(path)
                        raise SystemExit(0)

            raise SystemExit(1)
            PY
            """
        ).strip()
        result = controller.run_bash_script(script, timeout=20)
        if int(result.get("returncode", 1)) != 0:
            return None
        output = str(result.get("stdout") or result.get("output") or "").strip()
        return output or None

    @classmethod
    def _build_enable_calendar_script(cls, *, profile_name: str, profile_suffix: str) -> str:
        profile_dir = f'$HOME/Library/Thunderbird/Profiles/{profile_name}.{profile_suffix}'
        calendar_uuid = cls.CALENDAR_PROFILE_UUID
        return dedent(
            f"""
            set -euo pipefail
            PROFILE_DIR="{profile_dir}"
            PREFS_PATH="$PROFILE_DIR/prefs.js"
            pkill -x thunderbird >/dev/null 2>&1 || true
            pkill -x Thunderbird >/dev/null 2>&1 || true
            sleep 1
            python3 - <<'PY'
            import json
            import re
            import sys
            from pathlib import Path

            prefs = Path.home() / "Library/Thunderbird/Profiles/{profile_name}.{profile_suffix}/prefs.js"
            if not prefs.exists():
                print(json.dumps({{"status": "error", "message": f"prefs.js not found: {{prefs}}"}}))
                sys.exit(1)

            text = prefs.read_text(encoding="utf-8", errors="ignore")
            pattern = r'(calendar\\.registry\\.[^.]+\\.disabled",\\s*)true(\\);)'
            updated_text, replacements = re.subn(pattern, r'\\1false\\2', text)
            appended = False

            if replacements == 0 and "calendar.registry." not in updated_text:
                appended = True
                registry_lines = [
                    'user_pref("calendar.registry.{calendar_uuid}.calendar-main-default", true);',
                    'user_pref("calendar.registry.{calendar_uuid}.calendar-main-in-composite", true);',
                    'user_pref("calendar.registry.{calendar_uuid}.disabled", false);',
                    'user_pref("calendar.registry.{calendar_uuid}.name", "Home");',
                    'user_pref("calendar.registry.{calendar_uuid}.type", "storage");',
                    'user_pref("calendar.registry.{calendar_uuid}.uri", "moz-storage-calendar://");',
                ]
                separator = "" if updated_text.endswith("\\n") or not updated_text else "\\n"
                updated_text = updated_text + separator + "\\n".join(registry_lines) + "\\n"

            prefs.write_text(updated_text, encoding="utf-8")
            print(json.dumps({{
                "status": "success",
                "prefs": str(prefs),
                "replacements": replacements,
                "appended_registry": appended,
            }}, ensure_ascii=False))
            PY
            """
        ).strip()

    @classmethod
    def _build_script(
        cls,
        *,
        app_path: str,
        profile_name: str,
        profile_suffix: str,
        start_fake_smtp: bool,
        smtp_port: int,
        smtp_capture_dir: str,
        seed_mailboxes: list[Mapping[str, Any]],
        extra_user_prefs: list[str],
    ) -> str:
        profile_rel = f"Profiles/{profile_name}.{profile_suffix}"
        thunderbird_bin = str(Path(app_path).expanduser() / "Contents/MacOS/thunderbird")
        user_prefs = [
            'user_pref("mail.provider.enabled", false);',
            'user_pref("mail.provider.suppress_dialog_on_startup", true);',
            'user_pref("mailnews.start_page.enabled", false);',
            'user_pref("mailnews.start_page.url", "about:blank");',
            'user_pref("app.update.auto", false);',
            'user_pref("app.update.enabled", false);',
            'user_pref("browser.shell.checkDefaultBrowser", false);',
            'user_pref("calendar.integration.notify", false);',
            'user_pref("mail.shell.checkDefaultClient", false);',
            'user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);',
            'user_pref("mail.accountmanager.accounts", "account1");',
            'user_pref("mail.account.account1.server", "server1");',
            'user_pref("mail.account.account1.identities", "id1");',
            'user_pref("mail.accountmanager.defaultaccount", "account1");',
            'user_pref("mail.accountmanager.localfoldersserver", "server1");',
            'user_pref("mail.server.server1.type", "none");',
            'user_pref("mail.server.server1.name", "Local Folders");',
            'user_pref("mail.server.server1.userName", "bench");',
            'user_pref("mail.server.server1.hostname", "Local Folders");',
            'user_pref("mail.server.server1.directory-rel", "[ProfD]Mail/Local Folders");',
            'user_pref("mail.identity.id1.fullName", "Bench User");',
            'user_pref("mail.identity.id1.useremail", "bench@example.com");',
            'user_pref("mail.identity.id1.smtpServer", "smtp1");',
            'user_pref("mail.smtpservers", "smtp1");',
            'user_pref("mail.smtpserver.smtp1.hostname", "127.0.0.1");',
            f'user_pref("mail.smtpserver.smtp1.port", {smtp_port});',
            'user_pref("mail.smtpserver.smtp1.try_ssl", 0);',
            'user_pref("mail.smtpserver.smtp1.authMethod", 0);',
        ]
        user_prefs.extend(extra_user_prefs)
        seed_json = json.dumps(seed_mailboxes)
        lines = [
            "set -euo pipefail",
            'PROFILE_ROOT="$HOME/Library/Thunderbird"',
            f'PROFILE_DIR="$HOME/Library/Thunderbird/{profile_rel}"',
            f'THUNDERBIRD_APP={json.dumps(app_path)}',
            f'THUNDERBIRD_BIN={json.dumps(thunderbird_bin)}',
            f"SMTP_CAPTURE_DIR={json.dumps(smtp_capture_dir)}",
            'SMTP_ROOT="$HOME/Library/Application Support/ThunderbirdBench"',
            'SMTP_SCRIPT="$SMTP_ROOT/fake_smtp_server.py"',
            'SMTP_PID_FILE="$SMTP_ROOT/fake_smtp_server.pid"',
            'pkill -x thunderbird >/dev/null 2>&1 || true',
            'pkill -x Thunderbird >/dev/null 2>&1 || true',
            'mkdir -p "$SMTP_ROOT"',
            'if [ -f "$SMTP_PID_FILE" ]; then',
            '  old_pid="$(cat "$SMTP_PID_FILE" 2>/dev/null || true)"',
            '  if [ -n "$old_pid" ]; then',
            '    kill "$old_pid" >/dev/null 2>&1 || true',
            "  fi",
            '  rm -f "$SMTP_PID_FILE"',
            "fi",
            f'if [ "{str(start_fake_smtp).lower()}" = "true" ]; then',
            '  rm -rf "$SMTP_CAPTURE_DIR"',
            '  mkdir -p "$SMTP_CAPTURE_DIR"',
            '  cat > "$SMTP_SCRIPT" <<\'EOF\'',
            "import asyncore",
            "import pathlib",
            "import smtpd",
            "import time",
            "",
            'output_dir = pathlib.Path.home() / "Library/Application Support/ThunderbirdBench/fake_smtp"',
            "output_dir.mkdir(parents=True, exist_ok=True)",
            "",
            "class RecordingServer(smtpd.SMTPServer):",
            "    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):",
            "        timestamp = int(time.time() * 1000)",
            '        message_path = output_dir / f"message_{timestamp}.eml"',
            "        if isinstance(data, bytes):",
            "            message_path.write_bytes(data)",
            "        else:",
            '            message_path.write_text(data, encoding="utf-8", errors="ignore")',
            '        (output_dir / "events.log").open("a", encoding="utf-8").write(',
            '            f"{timestamp}\\t{mailfrom}\\t{\',\'.join(rcpttos)}\\n"',
            "        )",
            "        return None",
            "",
            f'server = RecordingServer(("127.0.0.1", {smtp_port}), None, decode_data=False)',
            "asyncore.loop()",
            "EOF",
            '  nohup python3 "$SMTP_SCRIPT" >/dev/null 2>&1 &',
            '  echo $! > "$SMTP_PID_FILE"',
            "  sleep 1",
            "fi",
            'if [ -d "$PROFILE_ROOT" ]; then',
            '  mv "$PROFILE_ROOT" "$PROFILE_ROOT.bak.$(date +%s)" >/dev/null 2>&1 || rm -rf "$PROFILE_ROOT"',
            "fi",
            'mkdir -p "$PROFILE_DIR/Mail/Local Folders"',
            'cat > "$PROFILE_ROOT/profiles.ini" <<\'EOF\'',
            "[Install4F96D1932A9F858E]",
            f"Default={profile_rel}",
            "Locked=1",
            "",
            "[Profile0]",
            f"Name={profile_name}",
            "IsRelative=1",
            f"Path={profile_rel}",
            "Default=1",
            "",
            "[General]",
            "StartWithLastProfile=1",
            "Version=2",
            "EOF",
            'cat > "$PROFILE_DIR/user.js" <<\'EOF\'',
            *user_prefs,
            "EOF",
            ': > "$PROFILE_DIR/Mail/Local Folders/Inbox"',
            ': > "$PROFILE_DIR/Mail/Local Folders/Sent"',
            ': > "$PROFILE_DIR/Mail/Local Folders/Trash"',
            "python3 - <<'PY'",
            "import datetime",
            "from email.utils import format_datetime",
            "from pathlib import Path",
            "",
            f"seed_mailboxes = {seed_json}",
            f'profile_dir = Path.home() / "Library/Thunderbird/{profile_rel}"',
            'local_dir = profile_dir / "Mail" / "Local Folders"',
            "local_dir.mkdir(parents=True, exist_ok=True)",
            "",
            "def write_mbox_message(path: Path, subject: str, sender: str, body: str, *, flagged: bool = False, msg_id: str = \"\") -> None:",
            "    path.parent.mkdir(parents=True, exist_ok=True)",
            '    status = "0009" if flagged else "0001"',
            "    now = datetime.datetime.now(datetime.timezone.utc)",
            '    from_line = now.astimezone().strftime("%a %b %d %H:%M:%S %Y")',
            "    payload = [",
            '        f"From - {from_line}",',
            '        f"X-Mozilla-Status: {status}",',
            '        "X-Mozilla-Status2: 00000000",',
            '        f"From: {sender}",',
            '        "To: bench@example.com",',
            '        f"Subject: {subject}",',
            '        f"Date: {format_datetime(now)}",',
            '        f"Message-ID: <{msg_id or subject.lower().replace(\' \', \'-\')}@helloworld.local>",',
            '        "MIME-Version: 1.0",',
            '        "Content-Type: text/plain; charset=UTF-8",',
            '        "Content-Transfer-Encoding: 8bit",',
            '        "",',
            "        body,",
            '        "",',
            "    ]",
            '    with path.open("a", encoding="utf-8") as fh:',
            '        fh.write("\\\\r\\\\n".join(payload))',
            '        fh.write("\\\\r\\\\n")',
            "",
            "for mailbox in seed_mailboxes:",
            '    folder = str(mailbox.get("folder") or "Inbox").strip() or "Inbox"',
            '    messages = mailbox.get("messages") or []',
            "    mbox_path = local_dir / folder",
            '    mbox_path.write_text("", encoding="utf-8")',
            '    msf_path = Path(str(mbox_path) + ".msf")',
            "    if msf_path.exists():",
            "        msf_path.unlink()",
            "    for idx, item in enumerate(messages, start=1):",
            "        if not isinstance(item, dict):",
            "            continue",
            "        write_mbox_message(",
            "            mbox_path,",
            '            subject=str(item.get("subject") or f"Seed {idx}"),',
            '            sender=str(item.get("from") or "seed@example.com"),',
            '            body=str(item.get("body") or ""),',
            '            flagged=bool(item.get("flagged", False)),',
            '            msg_id=str(item.get("message_id") or f"{folder.lower()}-{idx}"),',
            "        )",
            "PY",
            'if [ ! -x "$THUNDERBIRD_BIN" ]; then',
            '  echo "Thunderbird executable missing: $THUNDERBIRD_BIN" >&2',
            '  exit 1',
            "fi",
            'if [ -x "$THUNDERBIRD_BIN" ]; then',
            '  "$THUNDERBIRD_BIN" -headless -profile "$PROFILE_DIR" >/dev/null 2>&1 &',
            "  pid=$!",
            "  sleep 5",
            '  kill "$pid" >/dev/null 2>&1 || true',
            '  wait "$pid" >/dev/null 2>&1 || true',
            "fi",
        ]
        return "\n".join(lines)

    @staticmethod
    def _build_window_arrange_script(*, app_name: str) -> str:
        return dedent(
            f"""
            osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
            tell application "{app_name}" to activate
            tell application "System Events"
                tell process "{app_name}"
                    set frontmost to true
                    if (count of windows) > 0 then
                        try
                            set position of front window to {{40, 40}}
                        end try
                        try
                            set size of front window to {{1500, 960}}
                        end try
                    end if
                end tell
            end tell
            APPLESCRIPT
            """
        ).strip()
