"""Initializer utilities for the OpenShop shopping desktop app on macOS."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class OpenShopInitializer(BaseInitializer):
    """Reset and seed the OpenShop app state before a macOS episode starts."""

    REPO_ROOT = Path(__file__).resolve().parents[2]
    DEFAULT_APP_NAME = "OpenShop"
    DEFAULT_BUNDLE_ID = "com.killt.openshop"
    DEFAULT_PORT = 4310
    DEFAULT_BOOT_TIMEOUT = 30
    DEFAULT_FINAL_WAIT_MS = 2500
    DEFAULT_UI_READY_WAIT_MS = 12000
    DEFAULT_REMOTE_APP_PATH = "~/Applications/OpenShop.app"
    DEFAULT_REMOTE_ARCHIVE_PATH = "/tmp/openshop-macos-bundle.zip"
    LOCAL_APP_CANDIDATES = (
        "apps/openshop/dist/mac-arm64/OpenShop.app",
        "apps/openshop/dist/mac-arm64/openshop.app",
    )
    LOCAL_BUNDLE_SOURCE_PATHS = (
        "apps/openshop/electron",
        "apps/openshop/public",
        "apps/openshop/shared",
        "apps/openshop/server.js",
        "apps/openshop/package.json",
    )

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        task = context.get("task")
        run_dir = context.get("run_dir")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")
        if not hasattr(controller, "run_python_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_python_script is required")

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        port = int(params.get("port", self.DEFAULT_PORT) or self.DEFAULT_PORT)
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or 0)
        ui_ready_wait_ms = int(params.get("ui_ready_wait_ms", self.DEFAULT_UI_READY_WAIT_MS) or 0)
        boot_timeout = int(params.get("boot_timeout_seconds", self.DEFAULT_BOOT_TIMEOUT) or self.DEFAULT_BOOT_TIMEOUT)
        remote_app_path = (
            str(params.get("remote_app_path") or self.DEFAULT_REMOTE_APP_PATH).strip()
            or self.DEFAULT_REMOTE_APP_PATH
        )
        remote_archive_path = (
            str(params.get("remote_archive_path") or self.DEFAULT_REMOTE_ARCHIVE_PATH).strip()
            or self.DEFAULT_REMOTE_ARCHIVE_PATH
        )

        login = params.get("login") if isinstance(params.get("login"), Mapping) else {}
        cart_items = params.get("cart_items") if isinstance(params.get("cart_items"), list) else []
        benchmark_mode = str(
            params.get("benchmark_mode")
            or params.get("benchmarkMode")
            or getattr(task, "task_id", "")
            or getattr(task, "id", "")
            or ""
        ).strip()

        try:
            resolved_app_path = self._ensure_app_ready(
                controller,
                task=task,
                run_dir=run_dir,
                params=params,
                app_name=app_name,
                bundle_id=bundle_id,
                remote_app_path=remote_app_path,
                remote_archive_path=remote_archive_path,
            )
            self._stop_app(controller, app_name=app_name, app_path=resolved_app_path)
            self._launch_app(controller, app_name=app_name, app_path=resolved_app_path)
            self._seed_state(
                controller,
                port=port,
                boot_timeout=boot_timeout,
                login=login,
                cart_items=cart_items,
                benchmark_mode=benchmark_mode,
            )
            if ui_ready_wait_ms > 0:
                time.sleep(ui_ready_wait_ms / 1000.0)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare OpenShop app state: {exc}",
                metadata={
                    "app_name": app_name,
                    "bundle_id": bundle_id,
                    "port": port,
                    "login_seeded": bool(login),
                    "cart_item_count": len(cart_items),
                    "remote_app_path": remote_app_path,
                    "ui_ready_wait_ms": ui_ready_wait_ms,
                    "benchmark_mode": benchmark_mode,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared OpenShop app state",
            metadata={
                "app_name": app_name,
                "bundle_id": bundle_id,
                "port": port,
                "login_seeded": bool(login),
                "cart_item_count": len(cart_items),
                "remote_app_path": remote_app_path,
                "ui_ready_wait_ms": ui_ready_wait_ms,
                "benchmark_mode": benchmark_mode,
            },
        )

    @staticmethod
    def _ensure_success(result: Mapping[str, Any], *, action: str) -> None:
        returncode = int(result.get("returncode", 0))
        if returncode != 0:
            output = str(result.get("output", "") or result.get("stderr", "")).strip()
            raise RuntimeError(output or f"{action} failed with exit code {returncode}")

    def _ensure_app_ready(
        self,
        controller: Any,
        *,
        task: Any,
        run_dir: Any,
        params: Mapping[str, Any],
        app_name: str,
        bundle_id: str,
        remote_app_path: str,
        remote_archive_path: str,
    ) -> str:
        existing = self._find_remote_app_path(controller, app_name=app_name, bundle_id=bundle_id)
        if existing:
            return existing

        if not hasattr(controller, "upload_file"):
            raise RuntimeError("controller.upload_file is required to install OpenShop.app into the macOS guest")

        local_app_path = self._ensure_local_app_bundle(task=task, run_dir=run_dir, params=params)
        archive_path = self._archive_local_app_bundle(local_app_path, run_dir=run_dir)
        controller.upload_file(str(archive_path), remote_archive_path)

        install_script = dedent(
            f"""
            set -euo pipefail
            REMOTE_ARCHIVE={json.dumps(remote_archive_path)}
            TARGET_APP=$(python3 - <<'PY'
from pathlib import Path
print(Path({json.dumps(remote_app_path)}).expanduser())
PY
            )
            INSTALL_ROOT=$(dirname "$TARGET_APP")
            STAGING_DIR=$(mktemp -d /tmp/openshop-install.XXXXXX)
            trap 'rm -rf "$STAGING_DIR"' EXIT
            mkdir -p "$INSTALL_ROOT"
            rm -rf "$TARGET_APP"
            ditto -x -k "$REMOTE_ARCHIVE" "$STAGING_DIR"
            APP_BUNDLE=$(find "$STAGING_DIR" -maxdepth 2 -type d -iname '*.app' | head -n 1 || true)
            if [ -z "$APP_BUNDLE" ]; then
              echo "OpenShop archive did not contain an app bundle" >&2
              exit 1
            fi
            ditto "$APP_BUNDLE" "$TARGET_APP"
            xattr -dr com.apple.quarantine "$TARGET_APP" >/dev/null 2>&1 || true
            """
        ).strip()
        install_result = controller.run_bash_script(install_script, timeout=180)
        self._ensure_success(install_result, action="install_openshop_app")

        installed = self._find_remote_app_path(controller, app_name=app_name, bundle_id=bundle_id)
        if not installed:
            raise RuntimeError(f"OpenShop.app still missing after installation to {remote_app_path}")
        return installed

    def _find_remote_app_path(self, controller: Any, *, app_name: str, bundle_id: str) -> str | None:
        script = dedent(
            f"""
            set -euo pipefail
            for ROOT in "$HOME/Applications" "/Applications"; do
              if [ -d "$ROOT" ]; then
                FOUND=$(find "$ROOT" -maxdepth 1 -type d -iname {json.dumps(app_name + '.app')} | head -n 1 || true)
                if [ -n "$FOUND" ]; then
                  printf '%s\\n' "$FOUND"
                  exit 0
                fi
              fi
            done
            APP_PATH=$(mdfind "kMDItemCFBundleIdentifier == '{bundle_id}'" | grep '\\.app$' | head -n 1 || true)
            if [ -n "$APP_PATH" ]; then
              printf '%s\\n' "$APP_PATH"
              exit 0
            fi
            exit 1
            """
        ).strip()
        result = controller.run_bash_script(script, timeout=20)
        if int(result.get("returncode", 1)) != 0:
            return None
        output = str(result.get("stdout") or result.get("output") or "").strip()
        return output or None

    def _ensure_local_app_bundle(self, *, task: Any, run_dir: Any, params: Mapping[str, Any]) -> Path:
        explicit = str(params.get("local_app_path") or params.get("host_app_path") or "").strip()
        candidates: list[Path] = []
        if explicit:
            candidates.append(self._resolve_local_path(explicit, task=task, run_dir=run_dir))
        for relative in self.LOCAL_APP_CANDIDATES:
            candidates.append((self.REPO_ROOT / relative).resolve())

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir() and self._local_bundle_is_fresh(candidate):
                return candidate

        self._build_local_app_bundle()

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        raise FileNotFoundError(
            "OpenShop macOS bundle not found after build; checked: "
            + ", ".join(str(candidate) for candidate in candidates)
        )

    def _local_bundle_is_fresh(self, local_app_path: Path) -> bool:
        try:
            bundle_mtime = local_app_path.stat().st_mtime
        except FileNotFoundError:
            return False

        latest_source_mtime = bundle_mtime
        for relative in self.LOCAL_BUNDLE_SOURCE_PATHS:
            source = (self.REPO_ROOT / relative).resolve()
            if not source.exists():
                continue
            if source.is_file():
                latest_source_mtime = max(latest_source_mtime, source.stat().st_mtime)
                continue
            for path in source.rglob("*"):
                if path.exists():
                    latest_source_mtime = max(latest_source_mtime, path.stat().st_mtime)

        return bundle_mtime >= latest_source_mtime

    def _build_local_app_bundle(self) -> None:
        app_dir = self.REPO_ROOT / "apps" / "openshop"
        if not app_dir.exists():
            raise FileNotFoundError(f"OpenShop source directory not found: {app_dir}")

        env = os.environ.copy()
        env.setdefault("CSC_IDENTITY_AUTO_DISCOVERY", "false")

        if not (app_dir / "node_modules").exists():
            subprocess.run(
                ["npm", "install"],
                cwd=app_dir,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        subprocess.run(
            ["npm", "run", "sync:seed"],
            cwd=app_dir,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        subprocess.run(
            ["npx", "electron-builder", "--mac", "dir", "--arm64"],
            cwd=app_dir,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    @staticmethod
    def _resolve_local_path(raw_path: str, *, task: Any, run_dir: Any) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        task_source = getattr(task, "source_file", None)
        if task_source:
            candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
            if candidate.exists():
                return candidate
        if run_dir is not None:
            candidate = (Path(run_dir) / path).resolve()
            if candidate.exists():
                return candidate
        return (Path.cwd() / path).resolve()

    @staticmethod
    def _archive_local_app_bundle(local_app_path: Path, *, run_dir: Any) -> Path:
        archive_root = Path(run_dir).resolve() if run_dir is not None else local_app_path.parent
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / "openshop-macos-bundle.zip"
        if archive_path.exists():
            archive_path.unlink()
        subprocess.run(
            [
                "ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(local_app_path),
                str(archive_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return archive_path

    def _stop_app(self, controller: Any, *, app_name: str, app_path: str) -> None:
        script = dedent(
            f"""
            set +e
            osascript -e 'tell application "{app_name}" to quit' >/dev/null 2>&1 || true
            sleep 1
            pkill -x "{app_name}" >/dev/null 2>&1 || true
            pkill -f {json.dumps(app_path)} >/dev/null 2>&1 || true
            sleep 1
            """
        ).strip()
        result = controller.run_bash_script(script, timeout=15)
        self._ensure_success(result, action="stop_app")

    def _launch_app(self, controller: Any, *, app_name: str, app_path: str) -> None:
        script = dedent(
            f"""
            set -euo pipefail
            open {json.dumps(app_path)} >/dev/null 2>&1
            sleep 1
            osascript -e 'tell application "{app_name}" to activate' >/dev/null 2>&1 || true
            """
        ).strip()
        result = controller.run_bash_script(script, timeout=20)
        self._ensure_success(result, action="launch_app")

    def _seed_state(
        self,
        controller: Any,
        *,
        port: int,
        boot_timeout: int,
        login: Mapping[str, Any],
        cart_items: list[Any],
        benchmark_mode: str,
    ) -> None:
        login_phone = str(login.get("phone") or "").strip()
        login_password = str(login.get("password") or "").strip()
        normalized_cart_items: list[dict[str, Any]] = []
        for raw_item in cart_items:
            if not isinstance(raw_item, Mapping):
                continue
            payload = {
                "productId": str(raw_item.get("productId") or "").strip(),
                "quantity": int(raw_item.get("quantity", 1) or 1),
            }
            selected_spec = str(raw_item.get("selectedSpec") or "").strip()
            if selected_spec:
                payload["selectedSpec"] = selected_spec
            if payload["productId"]:
                normalized_cart_items.append(payload)

        code = f"""
import json
import time
import urllib.request

BASE_URL = "http://127.0.0.1:{port}"
DEADLINE = time.time() + {boot_timeout}
LOGIN_PHONE = {json.dumps(login_phone, ensure_ascii=False)}
LOGIN_PASSWORD = {json.dumps(login_password, ensure_ascii=False)}
CART_ITEMS = {json.dumps(normalized_cart_items, ensure_ascii=False)}
BENCHMARK_MODE = {json.dumps(benchmark_mode, ensure_ascii=False)}


def request_json(path, method="GET", payload=None):
    data = None
    headers = {{"Content-Type": "application/json"}}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {{}}


while time.time() < DEADLINE:
    try:
        request_json("/api/bootstrap")
        break
    except Exception:
        time.sleep(0.5)
else:
    raise SystemExit("Timed out waiting for OpenShop app API")

request_json("/api/dev/reset", method="POST", payload={{"benchmarkMode": BENCHMARK_MODE}})

if LOGIN_PHONE and LOGIN_PASSWORD:
    request_json(
        "/api/login",
        method="POST",
        payload={{"phone": LOGIN_PHONE, "password": LOGIN_PASSWORD}},
    )

for item in CART_ITEMS:
    request_json("/api/cart/items", method="POST", payload=item)

print(json.dumps({{
    "status": "ok",
    "login_seeded": bool(LOGIN_PHONE and LOGIN_PASSWORD),
    "cart_item_count": len(CART_ITEMS),
    "benchmark_mode": BENCHMARK_MODE,
}}, ensure_ascii=False))
"""
        result = controller.run_python_script(code, timeout=max(boot_timeout + 10, 35))
        self._ensure_success(result, action="seed_state")
