"""Initializer for the browser-based OpenWireshark application."""

from __future__ import annotations

import json
import shlex
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, run_guest, verify_paths

STATE_KEY = "openwireshark.state.v1"
DEVTOOLS_PORT = 1337

# Runs in the guest after the page has opened in the default Chrome (started with
# --remote-debugging-port=1337 by the desktop's default-browser entry). It merges the requested
# fields into the stored workspace, reloads the page so the app reads them, and checks the
# app shows them.
_WORKSPACE_RESET = r'''
import base64, json, os, socket, struct, sys, time, urllib.request
from urllib.parse import urlparse

CFG = json.loads(__CFG__)


def fail(message):
    print(json.dumps({"ok": False, "error": message}))
    raise SystemExit(1)


def http_json(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d%s" % (CFG["port"], path), timeout=5) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


class Socket:
    def __init__(self, url):
        parsed = urlparse(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=15)
        self.buf = b""
        self.seq = 0
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(("GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                           % (parsed.path, parsed.hostname, parsed.port, key)).encode())
        while b"\r\n\r\n" not in self.buf:
            self._recv()
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise OSError("websocket handshake refused")

    def _recv(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise OSError("websocket closed")
        self.buf += chunk

    def _read(self, count):
        while len(self.buf) < count:
            self._recv()
        out, self.buf = self.buf[:count], self.buf[count:]
        return out

    def call(self, method, params=None):
        self.seq += 1
        payload = json.dumps({"id": self.seq, "method": method, "params": params or {}}).encode()
        mask = os.urandom(4)
        header = bytearray([0x81])
        if len(payload) < 126:
            header.append(0x80 | len(payload))
        elif len(payload) < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", len(payload))
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        message = b""
        while True:
            first, second = self._read(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            data = self._read(length)
            if first & 0x0F == 0x8:
                raise OSError("websocket closed by peer")
            if first & 0x0F not in (0x0, 0x1):
                continue
            message += data
            if not first & 0x80:
                continue
            reply = json.loads(message.decode("utf-8", "replace"))
            message = b""
            if reply.get("id") == self.seq:
                if "error" in reply:
                    raise OSError("%s: %s" % (method, reply["error"]))
                return reply.get("result") or {}


def page_socket():
    for target in http_json("/json/list"):
        if target.get("type") == "page" and target.get("url", "").startswith(CFG["url"]):
            return Socket(target["webSocketDebuggerUrl"])
    return None


def evaluate(page, expression):
    result = page.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return (result.get("result") or {}).get("value")


deadline = time.time() + CFG["timeout"]
page = None
while time.time() < deadline and page is None:
    try:
        page = page_socket()
    except Exception:
        page = None
    if page is None:
        time.sleep(0.5)
if page is None:
    fail("OpenWireshark page did not appear on the DevTools port %d" % CFG["port"])
ready = "document.readyState === 'complete' && !!window.OPENWIRESHARK_SEED && !!document.querySelector('#profile-select')"
while time.time() < deadline and not evaluate(page, ready):
    time.sleep(0.5)
evaluate(page, "(() => { const key = %s; let saved = {}; try { saved = JSON.parse(localStorage.getItem(key)) || {}; } catch (e) {} "
               "localStorage.setItem(key, JSON.stringify(Object.assign(saved, %s))); location.reload(); return true; })()"
               % (json.dumps(CFG["key"]), json.dumps(CFG["state"])))
time.sleep(1)
shown = None
while time.time() < deadline:
    try:
        page = page_socket()
        shown = page and evaluate(page, "document.readyState === 'complete' && JSON.stringify({profile: (document.querySelector('#profile-select') || {}).value, "
                                        "stored: JSON.parse(localStorage.getItem(%s) || '{}')})" % json.dumps(CFG["key"]))
    except Exception:
        shown = None
    if shown:
        shown = json.loads(shown)
        stored = shown.get("stored") or {}
        if all(stored.get(field) == value for field, value in CFG["state"].items()) and (
            "profile" not in CFG["state"] or shown.get("profile") == CFG["state"]["profile"]
        ):
            print(json.dumps({"ok": True, "profile": shown.get("profile"),
                              "stored": {field: stored.get(field) for field in CFG["state"]}}))
            raise SystemExit(0)
    time.sleep(0.5)
fail("OpenWireshark did not show the reset workspace: %r" % (shown,))
'''


class OpenWiresharkInitializer(BaseInitializer):
    """Open OpenWireshark in Chrome.

    ``workspace_state`` (optional) is merged into the app's stored workspace
    (``openwireshark.state.v1`` Local Storage) once the page is open, and the page is
    reloaded. The snapshot's stored workspace, like the app's built-in default, already
    has the Retail Incident Review profile and the ``tcp.port == 80`` filter, so a task
    that asks for those sets a neutral start here (``{"profile": "Default", "filter": ""}``).
    """

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        launch_url = str(
            params.get("launch_url")
            or "file:///home/user/Applications/openwireshark_web/public/index.html"
        )
        workspace_state = params.get("workspace_state")
        metadata: dict[str, Any] = {"launch_url": launch_url}
        try:
            if launch_url.startswith("file://"):
                verify_paths(controller, [launch_url.removeprefix("file://")])
            launch_guest(controller, launch_url, wait_ms=int(params.get("wait_ms", 5000) or 0))
            if isinstance(workspace_state, Mapping) and workspace_state:
                metadata["workspace_state"] = self._reset_workspace(
                    controller, launch_url, dict(workspace_state), timeout=int(params.get("reset_timeout", 45) or 45)
                )
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to open OpenWireshark: {exc}", metadata)
        message = "OpenWireshark launched"
        if "workspace_state" in metadata:
            message += " with the stored workspace reset"
        return InitResult(InitStatus.PASS, message, metadata)

    @staticmethod
    def _reset_workspace(controller: Any, launch_url: str, state: dict[str, Any], *, timeout: int) -> dict[str, Any]:
        config = {"url": launch_url, "key": STATE_KEY, "state": state, "port": DEVTOOLS_PORT, "timeout": timeout}
        program = _WORKSPACE_RESET.replace("__CFG__", repr(json.dumps(config)))
        result = run_guest(
            controller,
            "python3 -c " + shlex.quote(program),
            timeout=timeout + 15,
        )
        # The guest program exits non-zero (run_guest raises) unless the app shows the state.
        lines = str(result.get("output") or "").strip().splitlines()
        try:
            return dict(json.loads(lines[-1]))
        except (IndexError, TypeError, ValueError):
            return {"ok": True, "output": lines[-1] if lines else ""}
