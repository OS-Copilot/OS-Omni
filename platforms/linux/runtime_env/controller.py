#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_RUNTIME_URL = "http://127.0.0.1:5000"
DEFAULT_RUNTIME_TOKEN = "linuxbench-runtime-token"


class LinuxRuntimeError(RuntimeError):
    pass


@dataclass
class Observation:
    timestamp: str
    width: int
    height: int
    ui_nodes: List[Dict[str, Any]] = field(default_factory=list)
    foreground_app: str = ""
    foreground_bundle_id: str = ""
    foreground_window: str = ""
    screenshot_data: Optional[bytes] = None

    def to_json(self) -> str:
        data = {
            "timestamp": self.timestamp,
            "width": self.width,
            "height": self.height,
            "ui_nodes": self.ui_nodes,
            "foreground_app": self.foreground_app,
            "foreground_bundle_id": self.foreground_bundle_id,
            "foreground_window": self.foreground_window,
        }
        return json.dumps(data, ensure_ascii=False)


class LinuxRuntimeController:
    def __init__(
        self,
        runtime_url: str = DEFAULT_RUNTIME_URL,
        token: str = DEFAULT_RUNTIME_TOKEN,
        screenshot_dir: Optional[str] = None,
        timeout: float = 20.0,
    ):
        self.runtime_url = runtime_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.width = 1920
        self.height = 1080
        self._refresh_device_info()

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        request_timeout: Optional[float] = None,
    ) -> tuple[int, bytes, str]:
        url = f"{self.runtime_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        effective_timeout = self.timeout if request_timeout is None else float(request_timeout)
        try:
            with opener.open(req, timeout=effective_timeout) as resp:
                body = resp.read()
                status = int(resp.getcode())
                content_type = resp.headers.get("Content-Type", "")
                return status, body, content_type
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LinuxRuntimeError(f"HTTP {exc.code} {method} {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LinuxRuntimeError(f"Request failed {method} {url}: {exc.reason}") from exc
        except Exception as exc:
            raise LinuxRuntimeError(f"Request failed {method} {url}: {type(exc).__name__}: {exc}") from exc

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        request_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        status, body, content_type = self._request(method, path, payload, request_timeout=request_timeout)
        if status != 200:
            raise LinuxRuntimeError(f"Unexpected status {status} for {method} {path}")
        if "application/json" not in content_type:
            raise LinuxRuntimeError(f"Unexpected content-type for {method} {path}: {content_type}")
        try:
            parsed = json.loads(body.decode("utf-8"))
            if isinstance(parsed, dict):
                return parsed
            raise LinuxRuntimeError(f"Expected JSON object for {method} {path}")
        except json.JSONDecodeError as exc:
            raise LinuxRuntimeError(f"Invalid JSON for {method} {path}: {exc}") from exc

    def _request_binary(self, method: str, path: str) -> bytes:
        status, body, _ = self._request(method, path, None)
        if status != 200:
            raise LinuxRuntimeError(f"Unexpected status {status} for {method} {path}")
        return body

    def _request_multipart(
        self,
        path: str,
        fields: Dict[str, str],
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        boundary = "----HelloWorldLinuxRuntimeBoundary"
        body = bytearray()

        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        for file_part in files or []:
            field_name = str(file_part["field_name"])
            filename = str(file_part["filename"])
            content = file_part["content"]
            if not isinstance(content, (bytes, bytearray)):
                raise TypeError("multipart file content must be bytes")
            mime_type = str(file_part.get("mime_type") or "application/octet-stream")
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8")
            )
            body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
            body.extend(content)
            body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        url = f"{self.runtime_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        req = urllib.request.Request(url=url, data=bytes(body), method="POST", headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                payload = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" not in content_type:
                    raise LinuxRuntimeError(f"Unexpected content-type for POST {path}: {content_type}")
                return json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LinuxRuntimeError(f"HTTP {exc.code} POST {url}: {detail}") from exc

    def _refresh_device_info(self) -> None:
        try:
            info = self.get_device_info()
            self.width = int(info.get("screen_width", self.width))
            self.height = int(info.get("screen_height", self.height))
        except LinuxRuntimeError:
            pass

    def update_screenshot_dir(self, new_dir: str) -> None:
        self.screenshot_dir = Path(new_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def get_device_info(self) -> Dict[str, Any]:
        return self._request_json("GET", "/device_info")

    def health(self) -> Dict[str, Any]:
        return self._request_json("GET", "/health")

    def observe(self, include_ui_tree: bool = True, include_screenshot_data: bool = True) -> Observation:
        params = urllib.parse.urlencode(
            {
                "include_ui_tree": "1" if include_ui_tree else "0",
                "include_screenshot_data": "1" if include_screenshot_data else "0",
            }
        )
        payload = self._request_json("GET", f"/observe?{params}")
        self.width = int(payload.get("width", self.width))
        self.height = int(payload.get("height", self.height))
        screenshot_data: Optional[bytes] = None
        if include_screenshot_data:
            b64 = payload.get("screenshot_data_base64", "")
            if isinstance(b64, str) and b64:
                screenshot_data = base64.b64decode(b64.encode("ascii"))
            else:
                screenshot_data = b""
        return Observation(
            timestamp=str(payload.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3])),
            width=self.width,
            height=self.height,
            ui_nodes=payload.get("ui_nodes", []) if isinstance(payload.get("ui_nodes"), list) else [],
            foreground_app=str(payload.get("foreground_app", "")),
            foreground_bundle_id=str(payload.get("foreground_bundle_id", "")),
            foreground_window=str(payload.get("foreground_window", "")),
            screenshot_data=screenshot_data,
        )

    def save_screenshot(self, prefix: str = "screenshot") -> str:
        if self.screenshot_dir is None:
            raise LinuxRuntimeError(
                "Screenshot directory is not configured. "
                "Call update_screenshot_dir(...) or pass screenshot_dir when creating LinuxRuntimeController."
            )
        if prefix == "final":
            filename = "final.png"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{prefix}_{timestamp}.png"
        filepath = self.screenshot_dir / filename
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        data = self._request_binary("GET", "/screenshot")
        filepath.write_bytes(data)
        return str(filepath)

    def execute_action(self, action_dict: Dict[str, Any], ui_nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        payload = {"action": action_dict, "ui_nodes": ui_nodes or []}
        return self._request_json("POST", "/action", payload)

    def get_action_schema_list_str(self) -> str:
        payload = self._request_json("GET", "/action_schema")
        schema_text = payload.get("schema_text")
        if isinstance(schema_text, str) and schema_text.strip():
            return schema_text
        schema = payload.get("schema", {})
        return json.dumps(schema, ensure_ascii=False, indent=2)

    def get_action_schema_json(self) -> Dict[str, Any]:
        payload = self._request_json("GET", "/action_schema")
        schema = payload.get("schema")
        if isinstance(schema, dict):
            return schema
        return {}

    def run_python_script(self, code: str, *, timeout: int = 30) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            "/run_python",
            {"code": code, "timeout": int(timeout)},
            request_timeout=max(self.timeout, float(timeout) + 5.0),
        )

    def execute_command(
        self,
        command: str | List[str],
        *,
        shell: bool = False,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            "/setup/execute",
            {
                "command": command,
                "shell": shell,
                "timeout": timeout,
            },
        )

    def execute_command_with_verification(
        self,
        command: str | List[str],
        *,
        shell: bool = False,
        verification: Optional[Dict[str, Any]] = None,
        max_wait_time: int = 10,
        check_interval: float = 1.0,
    ) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            "/setup/execute_with_verification",
            {
                "command": command,
                "shell": shell,
                "verification": dict(verification or {}),
                "max_wait_time": max_wait_time,
                "check_interval": check_interval,
            },
        )

    def run_bash_script(
        self,
        script: str,
        *,
        timeout: int = 30,
        working_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {"script": script, "timeout": timeout, "working_dir": working_dir}
        return self._request_json(
            "POST",
            "/run_bash_script",
            payload,
            request_timeout=max(self.timeout, float(timeout) + 5.0),
        )

    def launch_app(self, app_name: str) -> Dict[str, Any]:
        return self._request_json("POST", "/launch", {"app_name": app_name})

    def upload_file(self, local_path: str, remote_path: str) -> Dict[str, Any]:
        src = Path(local_path).expanduser().resolve()
        if not src.exists() or not src.is_file():
            raise LinuxRuntimeError(f"Local file not found: {src}")
        mime_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
        return self._request_multipart(
            "/setup/upload",
            {"file_path": remote_path},
            [
                {
                    "field_name": "file_data",
                    "filename": src.name,
                    "content": src.read_bytes(),
                    "mime_type": mime_type,
                }
            ],
        )

    def download_file(self, url: str, remote_path: str, *, overwrite: bool = True) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            "/setup/download",
            {"url": url, "path": remote_path, "overwrite": overwrite},
        )

    def write_file(
        self,
        remote_path: str,
        content: str,
        *,
        encoding: str = "utf-8",
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            "/setup/write_file",
            {
                "path": remote_path,
                "content": content,
                "encoding": encoding,
                "overwrite": overwrite,
            },
        )

    def change_wallpaper(self, path: str) -> Dict[str, Any]:
        return self._request_json("POST", "/setup/change_wallpaper", {"path": path})

    def get_terminal_output(self) -> str:
        payload = self._request_json("GET", "/terminal")
        return str(payload.get("output", ""))

    def get_desktop_path(self) -> str:
        payload = self._request_json("POST", "/desktop_path", {})
        return str(payload.get("desktop_path", ""))

    def get_directory_tree(self, path: str) -> Dict[str, Any]:
        payload = self._request_json("POST", "/list_directory", {"path": path})
        tree = payload.get("directory_tree")
        return tree if isinstance(tree, dict) else {}

    def get_file(self, file_path: str) -> bytes:
        url = f"{self.runtime_url}/file"
        boundary = "----HelloWorldLinuxBoundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file_path"\r\n\r\n'
            f"{file_path}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        req = urllib.request.Request(url=url, data=body, method="POST", headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LinuxRuntimeError(f"HTTP {exc.code} POST {url}: {detail}") from exc
