from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .store import WorkbenchStore


class WorkbenchHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        store: WorkbenchStore,
        frontend_root: Path,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.store = store
        self.frontend_root = frontend_root


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    server_version = "BenchmarkWorkbench/0.2"

    @property
    def app(self) -> WorkbenchHTTPServer:
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed, head_only=False)
            return
        self._serve_static(parsed.path, head_only=False)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed, head_only=True)
            return
        self._serve_static(parsed.path, head_only=True)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/reload":
            workspace = self.app.store.get_workspace(force_refresh=True)
            self._send_json({"ok": True, "workspace": workspace}, status=HTTPStatus.OK)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle_api_get(self, parsed, head_only: bool) -> None:
        params = parse_qs(parsed.query)
        force_refresh = params.get("refresh") == ["1"]
        if parsed.path == "/api/health":
            self._send_json({"ok": True}, status=HTTPStatus.OK, head_only=head_only)
            return
        if parsed.path == "/api/workspace":
            payload = self.app.store.get_workspace(force_refresh=force_refresh)
            self._send_json(payload, status=HTTPStatus.OK, head_only=head_only)
            return
        if parsed.path.startswith("/api/executions/"):
            execution_id = parsed.path.rsplit("/", 1)[-1]
            payload = self.app.store.get_execution(execution_id, force_refresh=force_refresh)
            if payload is None:
                self._send_json({"error": "execution_not_found"}, status=HTTPStatus.NOT_FOUND, head_only=head_only)
                return
            self._send_json(payload, status=HTTPStatus.OK, head_only=head_only)
            return
        if parsed.path.startswith("/api/runs/"):
            run_id = parsed.path.rsplit("/", 1)[-1]
            payload = self.app.store.get_run(run_id, force_refresh=force_refresh)
            if payload is None:
                self._send_json({"error": "run_not_found"}, status=HTTPStatus.NOT_FOUND, head_only=head_only)
                return
            self._send_json(payload, status=HTTPStatus.OK, head_only=head_only)
            return
        if parsed.path.startswith("/api/assets/"):
            asset_id = parsed.path.rsplit("/", 1)[-1]
            asset = self.app.store.get_asset(asset_id, force_refresh=force_refresh)
            if asset is None:
                self._send_json({"error": "asset_not_found"}, status=HTTPStatus.NOT_FOUND, head_only=head_only)
                return
            self._send_file(asset["path"], content_type=asset["mimeType"], head_only=head_only)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND, head_only=head_only)

    def _serve_static(self, request_path: str, head_only: bool) -> None:
        relative = request_path.lstrip("/") or "index.html"
        target = (self.app.frontend_root / relative).resolve()
        try:
            target.relative_to(self.app.frontend_root.resolve())
        except ValueError:
            self._send_json({"error": "forbidden"}, status=HTTPStatus.FORBIDDEN, head_only=head_only)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            target = self.app.frontend_root / "index.html"
        self._send_file(target, head_only=head_only)

    def _send_json(self, payload: Any, status: HTTPStatus, head_only: bool = False) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str | None = None, head_only: bool = False) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json({"error": "file_not_found"}, status=HTTPStatus.NOT_FOUND, head_only=head_only)
            return
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type or _content_type(path))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript; charset=utf-8"
    if suffix == ".json":
        return "application/json; charset=utf-8"
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


def run_server(host: str, port: int, store: WorkbenchStore, frontend_root: Path) -> WorkbenchHTTPServer:
    server = WorkbenchHTTPServer((host, port), WorkbenchRequestHandler, store=store, frontend_root=frontend_root)
    server.serve_forever()
    return server
