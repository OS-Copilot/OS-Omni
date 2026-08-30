from __future__ import annotations

import json
import time
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class ActualBudgetInitializer(BaseInitializer):
    """Reset Actual Budget on macOS to a deterministic local starter budget."""

    DEFAULT_APP_NAME = "Actual"
    DEFAULT_WAIT_MS = 2500
    DEFAULT_TEMPLATE_ARCHIVE = "files/actual/blank-budget-template.zip"
    DEFAULT_GLOBAL_STORE_TEMPLATE = "files/actual/global-store.blank.json"
    DEFAULT_SEED_PAYEES = [
        "Grocery Store",
        "Employer",
        "Landlord",
        "Supermarket",
    ]

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        task = context.get("task")
        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required for Actual initialization")

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        timeout = int(params.get("timeout", 120) or 120)
        document_root = str(params.get("document_root") or "~/Documents/Actual").strip() or "~/Documents/Actual"
        state_root = str(params.get("state_root") or "~/Library/Application Support/Actual").strip() or "~/Library/Application Support/Actual"
        template_archive = str(params.get("template_archive_path") or self.DEFAULT_TEMPLATE_ARCHIVE).strip()
        global_store_template = str(params.get("global_store_template_path") or self.DEFAULT_GLOBAL_STORE_TEMPLATE).strip()
        seed_payees = [
            str(name).strip()
            for name in (params.get("seed_payees") or self.DEFAULT_SEED_PAYEES)
            if str(name).strip()
        ]
        start_route = str(params.get("start_route") or "").strip()
        open_new_transaction = bool(params.get("open_new_transaction") or False)

        archive_local = self._resolve_local_path(template_archive, task=task)
        global_store_local = self._resolve_local_path(global_store_template, task=task)

        used_template_restore = False
        if archive_local.exists() and global_store_local.exists():
            try:
                result = self._restore_from_template(
                    controller,
                    archive_local=archive_local,
                    global_store_local=global_store_local,
                    document_root=document_root,
                    state_root=state_root,
                    timeout=timeout,
                )
                used_template_restore = True
            except Exception as exc:
                return InitResult(status=InitStatus.ERROR, message=f"Failed to restore Actual template: {exc}")
        else:
            try:
                result = controller.run_bash_script(
                    self._build_reset_script(document_root=document_root, state_root=state_root),
                    timeout=timeout,
                )
            except Exception as exc:
                return InitResult(status=InitStatus.ERROR, message=f"Failed to reset Actual state: {exc}")

        status = str(result.get("status") or "").lower()
        returncode = result.get("returncode")
        if status in {"error", "failed", "fail"} or (isinstance(returncode, int) and returncode != 0):
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Actual reset failed: {result.get('error') or result.get('message') or result.get('output') or result}",
                metadata={"reset_result": result},
            )

        try:
            seed_result = controller.run_python_script(
                self._build_seed_payees_script(
                    document_root=document_root,
                    state_root=state_root,
                    seed_payees=seed_payees,
                ),
                timeout=45,
            )
            seed_payload = json.loads(seed_result.get("stdout") or seed_result.get("output") or "{}")
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Actual payee seed failed: {exc}",
                metadata={"reset_result": result, "used_template_restore": used_template_restore},
            )

        if seed_payload.get("status") != "pass":
            return InitResult(
                status=InitStatus.ERROR,
                message=str(seed_payload.get("message") or "Actual payee seed failed"),
                metadata={"reset_result": result, "seed": seed_payload, "used_template_restore": used_template_restore},
            )

        try:
            controller.launch_app(app_name)
            time.sleep(max(wait_ms, 1000) / 1000.0)
            controller.run_bash_script(
                dedent(
                    f"""
                    open -a {json.dumps(app_name)} >/dev/null 2>&1 || true
                    osascript -e 'tell application "{app_name}" to activate' >/dev/null 2>&1 || true
                    """
                ).strip(),
                timeout=20,
            )
            controller.run_bash_script(
                self._build_window_arrange_script(app_name=app_name),
                timeout=20,
            )
            time.sleep(0.8)
            if not used_template_restore:
                self._bootstrap_blank_budget(controller)
            if start_route or open_new_transaction:
                self._position_starting_view(
                    controller,
                    start_route=start_route,
                    open_new_transaction=open_new_transaction,
                )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Actual launch/bootstrap failed: {exc}",
                metadata={
                    "reset_result": result,
                    "seed": seed_payload,
                    "used_template_restore": used_template_restore,
                },
            )

        verify_script = self._build_verify_script(document_root=document_root, state_root=state_root)
        try:
            verify_result = controller.run_python_script(verify_script, timeout=45)
            payload = json.loads(verify_result.get("stdout") or verify_result.get("output") or "{}")
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Actual verify failed: {exc}",
                metadata={"reset_result": result, "used_template_restore": used_template_restore},
            )

        if payload.get("status") != "pass":
            return InitResult(
                status=InitStatus.ERROR,
                message=str(payload.get("message") or "Actual did not reach blank budget state"),
                metadata={"reset_result": result, "verify": payload, "used_template_restore": used_template_restore},
            )

        return InitResult(
            status=InitStatus.PASS,
                message="Prepared Actual starter budget baseline",
            metadata={
                "app_name": app_name,
                "document_root": document_root,
                "state_root": state_root,
                "used_template_restore": used_template_restore,
                "template_archive": str(archive_local) if archive_local.exists() else None,
                "global_store_template": str(global_store_local) if global_store_local.exists() else None,
                "reset_result": result,
                "seed": seed_payload,
                "verify": payload,
                "start_route": start_route or None,
                "open_new_transaction": open_new_transaction,
            },
        )

    def _restore_from_template(
        self,
        controller: Any,
        *,
        archive_local: Path,
        global_store_local: Path,
        document_root: str,
        state_root: str,
        timeout: int,
    ) -> Mapping[str, Any]:
        remote_archive = "/tmp/actual-blank-budget-template.zip"
        remote_global_store = "/tmp/actual-global-store.blank.json"
        controller.upload_file(str(archive_local), remote_archive)
        controller.upload_file(str(global_store_local), remote_global_store)
        script = "\n".join(
            [
                "set -euo pipefail",
                self._build_expanduser_shell("DOCUMENT_ROOT", document_root),
                self._build_expanduser_shell("STATE_ROOT", state_root),
                f"REMOTE_ARCHIVE={json.dumps(remote_archive)}",
                f"REMOTE_GLOBAL_STORE={json.dumps(remote_global_store)}",
                "pkill -x Actual >/dev/null 2>&1 || true",
                "pkill -x Safari >/dev/null 2>&1 || true",
                'rm -rf "$DOCUMENT_ROOT"',
                'rm -rf "$STATE_ROOT"',
                'mkdir -p "$DOCUMENT_ROOT"',
                'mkdir -p "$STATE_ROOT"',
                'cp "$REMOTE_GLOBAL_STORE" "$STATE_ROOT/global-store.json"',
                'ditto -x -k "$REMOTE_ARCHIVE" "$DOCUMENT_ROOT"',
            ]
        )
        return controller.run_bash_script(script, timeout=timeout)

    def _bootstrap_blank_budget(self, controller: Any) -> None:
        # UI-only fallback when the blank-budget template asset is unavailable.
        sequence = [
            {"type": "keyboard", "action": "tab", "count": 1},
            {"type": "keyboard", "action": "tab", "count": 4},
            {"type": "keyboard", "action": "tab", "modifiers": ["shift"], "count": 1},
            {"type": "keyboard", "action": "enter", "count": 1},
            {"type": "keyboard", "action": "tab", "count": 1},
            {"type": "keyboard", "action": "tab", "count": 5},
            {"type": "keyboard", "action": "tab", "modifiers": ["shift"], "count": 1},
            {"type": "keyboard", "action": "enter", "count": 1},
        ]
        for action in sequence:
            controller.execute_action(action, [])
            time.sleep(0.8)
        time.sleep(2.5)

    def _position_starting_view(
        self,
        controller: Any,
        *,
        start_route: str,
        open_new_transaction: bool,
    ) -> None:
        if start_route:
            controller.execute_action({"type": "hotkey", "keys": "cmd+k"}, [])
            time.sleep(0.8)
            controller.execute_action({"type": "type_text", "text": start_route}, [])
            time.sleep(0.8)
            controller.execute_action({"type": "keyboard", "action": "enter", "count": 1}, [])
            time.sleep(1.4)

        if open_new_transaction:
            controller.execute_action({"type": "tap", "target": {"x": 0.193, "y": 0.149}}, [])
            time.sleep(1.2)

    @staticmethod
    def _resolve_local_path(raw_path: str, *, task: Any) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        task_source = getattr(task, "source_file", None)
        if task_source:
            candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
            if candidate.exists():
                return candidate
        return (Path.cwd() / path).resolve()

    @staticmethod
    def _build_reset_script(*, document_root: str, state_root: str) -> str:
        return "\n".join(
            [
                "set -euo pipefail",
                ActualBudgetInitializer._build_expanduser_shell("DOCUMENT_ROOT", document_root),
                ActualBudgetInitializer._build_expanduser_shell("STATE_ROOT", state_root),
                "pkill -x Actual >/dev/null 2>&1 || true",
                "pkill -x Safari >/dev/null 2>&1 || true",
                'rm -rf "$DOCUMENT_ROOT"',
                'mkdir -p "$DOCUMENT_ROOT"',
                'mkdir -p "$STATE_ROOT"',
                'cat > "$STATE_ROOT/global-store.json" <<\'EOF\'',
                "{}",
                "EOF",
            ]
        )

    @staticmethod
    def _build_expanduser_shell(var_name: str, raw_path: str) -> str:
        return dedent(
            f"""
            {var_name}=$(python3 - <<'PY'
            from pathlib import Path
            print(Path({json.dumps(raw_path)}).expanduser())
            PY
            )
            """
        ).strip()

    @staticmethod
    def _build_verify_script(*, document_root: str, state_root: str) -> str:
        document_root_json = json.dumps(document_root)
        state_root_json = json.dumps(state_root)
        return dedent(
            f"""
            import json
            import os
            from pathlib import Path

            state_root = Path(os.path.expanduser({state_root_json}))
            document_root = Path(os.path.expanduser({document_root_json}))
            global_store_path = state_root / 'global-store.json'
            payload = {{
                'status': 'fail',
                'message': 'starter budget not ready',
                'global_store_path': str(global_store_path),
                'document_root': str(document_root),
            }}
            if not global_store_path.exists():
                print(json.dumps(payload, ensure_ascii=False))
                raise SystemExit(0)
            try:
                store = json.loads(global_store_path.read_text(encoding='utf-8'))
            except Exception as exc:
                payload['message'] = f'failed to parse global-store.json: {{exc}}'
                print(json.dumps(payload, ensure_ascii=False))
                raise SystemExit(0)
            last_budget = str(store.get('lastBudget') or '').strip()
            payload['store'] = store
            if not last_budget:
                payload['message'] = 'lastBudget missing after bootstrap'
                print(json.dumps(payload, ensure_ascii=False))
                raise SystemExit(0)
            db_path = document_root / last_budget / 'db.sqlite'
            metadata_path = document_root / last_budget / 'metadata.json'
            payload['db_path'] = str(db_path)
            payload['metadata_path'] = str(metadata_path)
            if db_path.exists() and metadata_path.exists():
                payload['status'] = 'pass'
                payload['message'] = 'starter budget ready'
            print(json.dumps(payload, ensure_ascii=False))
            """
        ).strip()

    @staticmethod
    def _build_seed_payees_script(*, document_root: str, state_root: str, seed_payees: list[str]) -> str:
        document_root_json = json.dumps(document_root)
        state_root_json = json.dumps(state_root)
        seed_payees_json = json.dumps(seed_payees, ensure_ascii=False)
        return dedent(
            f"""
            import json
            import os
            import sqlite3
            import uuid
            from pathlib import Path

            state_root = Path(os.path.expanduser({state_root_json}))
            document_root = Path(os.path.expanduser({document_root_json}))
            seed_payees = [name for name in {seed_payees_json} if str(name).strip()]
            global_store_path = state_root / 'global-store.json'
            payload = {{
                'status': 'fail',
                'message': 'seed payees failed',
                'seed_payees': seed_payees,
                'global_store_path': str(global_store_path),
                'document_root': str(document_root),
            }}
            if not global_store_path.exists():
                payload['message'] = 'global-store.json missing before payee seed'
                print(json.dumps(payload, ensure_ascii=False))
                raise SystemExit(0)
            try:
                store = json.loads(global_store_path.read_text(encoding='utf-8'))
            except Exception as exc:
                payload['message'] = f'failed to parse global-store.json: {{exc}}'
                print(json.dumps(payload, ensure_ascii=False))
                raise SystemExit(0)
            last_budget = str(store.get('lastBudget') or '').strip()
            if not last_budget:
                payload['message'] = 'lastBudget missing before payee seed'
                print(json.dumps(payload, ensure_ascii=False))
                raise SystemExit(0)
            db_path = document_root / last_budget / 'db.sqlite'
            payload['db_path'] = str(db_path)
            if not db_path.exists():
                payload['message'] = 'db.sqlite missing before payee seed'
                print(json.dumps(payload, ensure_ascii=False))
                raise SystemExit(0)

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            inserted = []
            for name in seed_payees:
                row = cur.execute(
                    "SELECT id FROM payees WHERE lower(name)=lower(?) AND tombstone=0 LIMIT 1",
                    (name,),
                ).fetchone()
                if row:
                    continue
                payee_id = f'seed-payee-{{uuid.uuid4()}}'
                cur.execute(
                    '''
                    INSERT INTO payees (id, name, category, tombstone, transfer_acct, favorite, learn_categories)
                    VALUES (?, ?, NULL, 0, NULL, 0, 1)
                    ''',
                    (payee_id, name),
                )
                inserted.append({{'id': payee_id, 'name': name}})
            conn.commit()
            existing = [
                row[0]
                for row in cur.execute(
                    "SELECT name FROM payees WHERE tombstone=0 ORDER BY lower(name)"
                ).fetchall()
            ]
            conn.close()
            payload['status'] = 'pass'
            payload['message'] = 'seed payees ready'
            payload['inserted'] = inserted
            payload['existing_payees'] = existing
            print(json.dumps(payload, ensure_ascii=False))
            """
        ).strip()

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
