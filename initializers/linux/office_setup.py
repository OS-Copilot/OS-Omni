"""Linux office setup initializer for LibreOffice UNO workflow."""

from __future__ import annotations

import shlex
import json
from pathlib import Path
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.asset_cache import local_cache_for_url


# Dedicated profile so LibreOffice does not attach to the user's desktop soffice on :0
# (which would leave Xvfb :99 empty and screenshots all black).
_LO_USER_INSTALL = "file:///tmp/helloworld_lo_soffice_profile"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_host_seed_path(host_raw: str, run_dir: Path) -> Path:
    """Resolve a host-side seed path: absolute, or relative to run_dir, or relative to repo root."""
    p = Path(host_raw.strip())
    if p.is_absolute():
        return p
    cand = (run_dir / p).resolve()
    if cand.is_file():
        return cand
    return (_REPO_ROOT / p).resolve()


class LinuxOfficeSetupInitializer(BaseInitializer):
    """Prepare Linux runtime for Office tool-based tasks.

    Optional ``params``:
    - ``open_documents_after_download``: path or list of paths; after UNO starts, runs
      ``libreoffice --writer|calc|impress`` on each so the first observation shows the doc.
    - ``open_documents_wait_seconds``: seconds to sleep after launching (default 4).
    - ``open_documents_focus_substring``: substring to pass to ``wmctrl -a`` to raise the
      app window; default is the basename of the first opened path (e.g. ``file.docx``).
    - ``libreoffice_user_install_uri``: LibreOffice ``-env:UserInstallation=`` URI (default
      ``file:///tmp/helloworld_lo_soffice_profile``) so UNO/UI use an isolated profile and
      do not merge with an existing desktop LibreOffice on another ``DISPLAY`` (e.g. Xvfb).
    - Per ``seed_downloads`` item (optional):
      - ``host_path``: copy this **host** file to ``path`` via ``upload_file`` (no HTTP fetch).
        Relative paths first try ``run_dir``, then **repository root** (so
        ``tasks/v1/linux/.../seeds/foo.docx`` works). If the file is missing but ``url`` is set,
        falls back to downloading from ``url``.
      - ``skip_download_if_remote_exists``: if true, skip ``download_file`` when the guest
        file at ``path`` already exists (e.g. you copied it into ``/tmp/helloworld_office/``).
    """

    DEFAULT_TOOL_NAMES = [
        "libreoffice_writer.py",
        "libreoffice_calc.py",
        "libreoffice_impress.py",
    ]

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required")

        run_dir = Path(context.get("run_dir") or ".").resolve()
        setup_report: dict[str, Any] = {"uploaded_tools": [], "checks": []}

        try:
            self._run_dependency_checks(controller, setup_report)
            cleaned = self._cleanup_paths(controller, params=params)
            setup_report["cleanup_paths"] = cleaned
            seeded = self._write_seed_files(controller, params=params)
            setup_report["seed_files"] = seeded
            uploaded = self._upload_office_tools(controller, params=params, run_dir=run_dir)
            setup_report["uploaded_tools"] = uploaded
            downloads = self._download_seed_files(controller, params=params, run_dir=run_dir)
            setup_report["downloads"] = downloads
            self._start_uno_service(controller, params=params)
            self._open_documents_after_download(controller, params=params, setup_report=setup_report)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Office setup failed: {type(exc).__name__}: {exc}",
                metadata=setup_report,
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Linux office runtime is ready",
            metadata=setup_report,
        )

    def _run_dependency_checks(self, controller: Any, setup_report: dict[str, Any]) -> None:
        checks = {
            "soffice": "command -v soffice >/dev/null",
            "wmctrl": "command -v wmctrl >/dev/null",
            "xprop": "command -v xprop >/dev/null",
        }
        for name, cmd in checks.items():
            result = controller.run_bash_script(cmd, timeout=10)
            ok = int(result.get("returncode", 1)) == 0
            setup_report["checks"].append({"name": name, "ok": ok})
            if not ok:
                raise RuntimeError(f"missing dependency in guest: {name}")

    def _cleanup_paths(self, controller: Any, *, params: Mapping[str, Any]) -> list[str]:
        cleanup_paths = params.get("cleanup_paths") or []
        if not cleanup_paths:
            return []
        if not isinstance(cleanup_paths, list):
            raise ValueError("cleanup_paths must be a list")
        normalized = [str(path).strip() for path in cleanup_paths if str(path).strip()]
        if not normalized:
            return []
        script = f"""python3 - <<'PY'
import json
import shutil
from pathlib import Path

paths = json.loads({json.dumps(json.dumps(normalized, ensure_ascii=False))})
for raw_path in paths:
    path = Path(str(raw_path))
    if not path.is_absolute():
        raise SystemExit(f"cleanup path must be absolute: {{path}}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
print(json.dumps(paths, ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=30)
        if int(result.get("returncode", 1)) != 0:
            raise RuntimeError(str(result.get("output", "")).strip() or "cleanup_paths failed")
        return normalized

    def _write_seed_files(self, controller: Any, *, params: Mapping[str, Any]) -> list[str]:
        seed_files = params.get("seed_files") or []
        if not seed_files:
            return []
        if not isinstance(seed_files, list):
            raise ValueError("seed_files must be a list")
        normalized: list[dict[str, str]] = []
        for raw_file in seed_files:
            if not isinstance(raw_file, Mapping):
                continue
            path = str(raw_file.get("path") or "").strip()
            if not path:
                continue
            normalized.append({"path": path, "content": str(raw_file.get("content") or "")})
        if not normalized:
            return []
        script = f"""python3 - <<'PY'
import json
from pathlib import Path

files = json.loads({json.dumps(json.dumps(normalized, ensure_ascii=False))})
for item in files:
    path = Path(str(item.get("path") or ""))
    if not path.is_absolute():
        raise SystemExit(f"seed file path must be absolute: {{path}}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(item.get("content") or ""), encoding="utf-8")
print(json.dumps([item["path"] for item in files], ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=30)
        if int(result.get("returncode", 1)) != 0:
            raise RuntimeError(str(result.get("output", "")).strip() or "seed_files failed")
        return [item["path"] for item in normalized]

    def _upload_office_tools(self, controller: Any, *, params: Mapping[str, Any], run_dir: Path) -> list[str]:
        source_dir_raw = str(
            params.get("tool_source_dir")
            or "platforms/linux/office_tools"
        ).strip()
        source_dir = Path(source_dir_raw)
        if not source_dir.is_absolute():
            source_dir = (run_dir / source_dir).resolve()
            if not source_dir.exists():
                source_dir = (Path(__file__).resolve().parents[2] / "platforms" / "linux" / "office_tools").resolve()

        remote_dir = str(params.get("remote_tool_dir") or "~").strip() or "~"
        tool_names = params.get("tool_names") or self.DEFAULT_TOOL_NAMES
        if not isinstance(tool_names, list) or not tool_names:
            raise ValueError("tool_names must be a non-empty list when provided")

        uploaded: list[str] = []
        for file_name in tool_names:
            name = str(file_name).strip()
            if not name:
                continue
            local_path = source_dir / name
            if not local_path.exists():
                raise FileNotFoundError(f"office tool file not found: {local_path}")
            remote_path = f"{remote_dir.rstrip('/')}/{name}"
            controller.upload_file(str(local_path), remote_path)
            uploaded.append(remote_path)
        return uploaded

    def _download_seed_files(
        self,
        controller: Any,
        *,
        params: Mapping[str, Any],
        run_dir: Path,
    ) -> list[dict[str, Any]]:
        seed_downloads = params.get("seed_downloads") or []
        if not seed_downloads:
            return []
        if not isinstance(seed_downloads, list):
            raise ValueError("seed_downloads must be a list")

        downloaded: list[dict[str, Any]] = []
        for item in seed_downloads:
            if not isinstance(item, Mapping):
                raise ValueError("seed_downloads items must be objects")
            path = str(item.get("path") or "").strip()
            if not path:
                raise ValueError("seed_downloads item requires path")

            parent = str(Path(path).parent)
            if parent and parent != ".":
                controller.run_bash_script(f"mkdir -p {shlex.quote(parent)}", timeout=15)

            host_raw = str(item.get("host_path") or item.get("local_path") or "").strip()
            url = str(item.get("url") or "").strip()
            if host_raw:
                host_p = _resolve_host_seed_path(host_raw, run_dir)
                if host_p.is_file():
                    controller.upload_file(str(host_p), path)
                    downloaded.append({"path": path, "source": "host_upload", "host_path": str(host_p)})
                    continue
                if not url:
                    raise FileNotFoundError(f"seed host_path not found: {host_p}")

            skip_if_exists = bool(item.get("skip_download_if_remote_exists", False))
            if skip_if_exists:
                probe = controller.run_bash_script(f"test -f {shlex.quote(path)}", timeout=15)
                if int(probe.get("returncode", 1)) == 0:
                    downloaded.append(
                        {
                            "path": path,
                            "source": "skipped_existing",
                            "url": url,
                        }
                    )
                    continue

            if not url:
                raise ValueError(
                    "seed_downloads item requires url unless host_path is set, "
                    "or skip_download_if_remote_exists with file already on guest"
                )
            cached_path = local_cache_for_url(url)
            if cached_path is not None:
                controller.upload_file(str(cached_path), path)
                downloaded.append({"path": path, "source": "local_cache", "host_path": str(cached_path)})
                continue
            controller.download_file(url, path, overwrite=bool(item.get("overwrite", True)))
            downloaded.append({"url": url, "path": path, "source": "download"})
        return downloaded

    def _start_uno_service(self, controller: Any, *, params: Mapping[str, Any]) -> None:
        uno_port = int(params.get("uno_port", 2002) or 2002)
        install_uri = str(params.get("libreoffice_user_install_uri") or _LO_USER_INSTALL).strip()
        reset_profile = (
            "rm -rf /tmp/helloworld_lo_soffice_profile 2>/dev/null || true; "
            "mkdir -p /tmp/helloworld_lo_soffice_profile; "
            if install_uri == _LO_USER_INSTALL
            else ""
        )
        start_cmd = (
            'pkill -f "soffice.*port=' + str(uno_port) + '" >/dev/null 2>&1 || true; '
            + reset_profile
            + f'soffice "-env:UserInstallation={install_uri}" '
            '--accept="socket,host=localhost,port=' + str(uno_port) + ';urp;" '
            "--norestore --nologo --nodefault >/tmp/helloworld_soffice.log 2>&1 &"
        )
        controller.run_bash_script(start_cmd, timeout=20)

        wait_seconds = int(params.get("startup_wait_seconds", 5) or 5)
        verify_cmd = (
            "python3 - <<'PY'\n"
            "import socket\n"
            f"port = {uno_port}\n"
            "s = socket.socket()\n"
            "s.settimeout(1.0)\n"
            "ok = 1\n"
            "try:\n"
            "    s.connect(('127.0.0.1', port))\n"
            "except Exception:\n"
            "    ok = 0\n"
            "finally:\n"
            "    s.close()\n"
            "raise SystemExit(0 if ok else 1)\n"
            "PY"
        )
        for _ in range(max(1, wait_seconds)):
            probe = controller.run_bash_script(verify_cmd, timeout=5)
            if int(probe.get("returncode", 1)) == 0:
                return
            controller.run_bash_script("sleep 1", timeout=2)
        raise RuntimeError(f"UNO service is not reachable on localhost:{uno_port}")

    def _open_documents_after_download(
        self,
        controller: Any,
        *,
        params: Mapping[str, Any],
        setup_report: dict[str, Any],
    ) -> None:
        """Launch LibreOffice on seed files so the first observation shows the document (OSWorld-style)."""
        raw = params.get("open_documents_after_download")
        if not raw:
            setup_report.setdefault("opened_documents", [])
            return
        if isinstance(raw, str):
            paths = [raw]
        elif isinstance(raw, list):
            paths = [str(p).strip() for p in raw if str(p).strip()]
        else:
            raise ValueError("open_documents_after_download must be a string or list of strings")

        wait_sec = int(params.get("open_documents_wait_seconds", 4) or 4)
        opened: list[str] = []
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext in (".docx", ".odt", ".doc"):
                component = "writer"
            elif ext in (".xlsx", ".ods", ".xls"):
                component = "calc"
            elif ext in (".pptx", ".odp", ".ppt"):
                component = "impress"
            else:
                component = "writer"
            install_uri = str(params.get("libreoffice_user_install_uri") or _LO_USER_INSTALL).strip()
            cmd = (
                "nohup libreoffice "
                f'"-env:UserInstallation={install_uri}" '
                f"--{component} {shlex.quote(path)} "
                ">/tmp/helloworld_lo_open.log 2>&1 &"
            )
            controller.run_bash_script(cmd, timeout=25)
            opened.append(path)

        if opened:
            controller.run_bash_script(f"sleep {max(1, wait_sec)}", timeout=wait_sec + 10)
            raw_focus = params.get("open_documents_focus_substring")
            if isinstance(raw_focus, str) and raw_focus.strip():
                focus = raw_focus.strip()
            else:
                focus = Path(opened[0]).name
            # Raise LibreOffice window so the first screenshot is the document, not the desktop.
            esc = shlex.quote(focus)
            focus_cmd = (
                f"wmctrl -a {esc} 2>/dev/null || "
                "wmctrl -a 'LibreOffice' 2>/dev/null || "
                "wmctrl -a 'soffice' 2>/dev/null || true; "
                "sleep 1"
            )
            controller.run_bash_script(focus_cmd, timeout=20)
            setup_report["focus_substring"] = focus
        setup_report["opened_documents"] = opened
