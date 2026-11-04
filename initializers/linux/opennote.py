"""OpenNote snapshot initializer recovered from reviewed run artifacts."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.init import InitResult, InitStatus
from evaluators.cua_review.platforms.linux.local_storage import LOCAL_STORAGE_SOURCE
from initializers.linux.cua_review import SnapshotOpenAppInitializer, run_guest

PROFILE_DIR = "/home/user/.config/osomni-openapps/launch-openrednote"
APP_URL = "file:///home/user/OpenApps/source/apps/openrednote/public/index.html"
STATE_KEY = "opennote.localState.v2"
DEVTOOLS_PORT = 9233

# Runs in the guest. With the OpenNote window closed, a headless Chrome on the OpenNote
# profile opens the app, adds the declared notes to the signed-in account's saved list
# (localStorage, as the app's Save button does), checks the declared baseline, leaves the
# page so Chrome commits the origin's storage, and closes. The state on disk is read
# back before the regular launcher starts the app. Exits nonzero when anything is off.
_BASELINE_PROGRAM = r'''
import base64, json, os, socket, struct, subprocess, time, urllib.request
from urllib.parse import urlparse

CFG = json.loads(__CFG__)
PORT = CFG["port"]


def fail(message):
    print(json.dumps({"ok": False, "error": message}))
    raise SystemExit(1)


def http_json(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d%s" % (PORT, path), timeout=5) as response:
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

    def call(self, method, params=None, wait=True):
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
        if not wait:
            return {}
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


def evaluate(page, expression):
    result = page.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return (result.get("result") or {}).get("value")


chrome = subprocess.Popen(
    ["/usr/bin/google-chrome-stable", "--headless=new", "--remote-debugging-port=%d" % PORT,
     "--user-data-dir=" + CFG["profile"], "--no-first-run", "--disable-default-apps", CFG["url"]],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
page = None
deadline = time.time() + 60
while time.time() < deadline and page is None:
    try:
        for target in http_json("/json/list"):
            if target.get("type") == "page" and target.get("url", "").startswith(CFG["url"]):
                page = Socket(target["webSocketDebuggerUrl"])
                break
    except Exception:
        pass
    if page is None:
        time.sleep(0.5)
if page is None:
    chrome.kill()
    fail("OpenNote page did not open in headless Chrome")
ready = "document.readyState === 'complete' && !!window.OPENNOTE_SEED && !!localStorage.getItem(%s)" % json.dumps(CFG["key"])
while time.time() < deadline and not evaluate(page, ready):
    time.sleep(0.5)
summary = json.loads(evaluate(page, CFG["edit_js"]) or "{}")
page.call("Page.navigate", {"url": "about:blank"})
time.sleep(3)
storage = os.path.join(CFG["profile"], "Default", "Local Storage", "leveldb")
for _ in range(20):
    newest = max([os.path.getmtime(os.path.join(storage, name)) for name in os.listdir(storage)] or [0])
    if time.time() - newest >= 2:
        break
    time.sleep(1)
try:
    Socket(http_json("/json/version")["webSocketDebuggerUrl"]).call("Browser.close", wait=False)
except Exception:
    pass
try:
    chrome.wait(timeout=20)
except subprocess.TimeoutExpired:
    chrome.terminate()
    chrome.wait(timeout=10)

problems = []
if CFG["expected_logged_in"] is not None and summary.get("loggedIn") != CFG["expected_logged_in"]:
    problems.append("session loggedIn=%r" % summary.get("loggedIn"))
missing = sorted(set(CFG["required"]) - set(summary.get("present") or []))
if missing:
    problems.append("missing notes %s" % missing)
if summary.get("forbidden"):
    problems.append("notes that must not exist yet: %s" % summary["forbidden"])
absent = sorted(set(CFG["notifications"]) - set(summary.get("notifications") or []))
if absent:
    problems.append("missing notifications %s" % absent)
stored = read_state(storage, CFG["key"]) or {}
handle = str(((stored.get("session") or {}).get("user") or {}).get("handle") or "")
saved = set(((stored.get("userState") or {}).get(handle) or {}).get("savedNoteIds") or [])
unsaved = sorted(set(CFG["saved"]) - saved)
if unsaved:
    problems.append("not saved on disk for %r: %s" % (handle, unsaved))
summary["saved_on_disk"] = sorted(set(CFG["saved"]) & saved)
if problems:
    fail("; ".join(problems) + " | " + json.dumps(summary))
print(json.dumps({"ok": True, **summary}))
'''

# Runs in the OpenNote page: the app reads this document on every action.
_EDIT_JS = r"""
(() => {
  const cfg = __CFG__;
  const state = JSON.parse(localStorage.getItem(cfg.key));
  const handle = String(((state.session || {}).user || {}).handle || "");
  const own = (state.userState || {})[handle];
  const added = [];
  if (own) {
    for (const id of cfg.saved) {
      if (!own.savedNoteIds.includes(id)) { own.savedNoteIds.push(id); added.push(id); }
    }
  }
  if (added.length) localStorage.setItem(cfg.key, JSON.stringify(state));
  const notes = state.notes || [];
  const notifications = (state.userNotifications || {})[handle] || [];
  return JSON.stringify({
    loggedIn: !!(state.session || {}).loggedIn,
    handle,
    added,
    present: cfg.required.filter((id) => notes.some((note) => note.id === id)),
    forbidden: notes.filter((note) => cfg.forbidden.includes(note.title)).map((note) => note.title),
    notifications: notifications.map((row) => row.text).filter((text) => cfg.notifications.includes(text)),
  });
})()
"""


class OpenNoteInitializer(SnapshotOpenAppInitializer):
    default_app_name = "OpenNote"
    default_app_command = "opennote"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        params = dict(context.get("params") or {})
        saved = [str(item) for item in params.get("saved_note_ids") or []]
        if not saved:
            return super().initialize(context)
        # Notes the task says are already saved but the snapshot's notebook lacks.
        try:
            baseline = self._establish_baseline(context.get("controller"), params, saved)
        except Exception as exc:  # noqa: BLE001 - reported as an initializer error
            return InitResult(InitStatus.ERROR, f"OpenNote baseline not established: {exc}", {"saved_note_ids": saved})
        result = super().initialize(context)
        metadata = dict(result.metadata)
        metadata["baseline"] = baseline
        try:
            added = list(json.loads(baseline.splitlines()[-1]).get("added") or [])
        except (IndexError, ValueError, AttributeError):
            added = []
        metadata["business_state_mutated"] = bool(added)
        message = result.message
        if result.status == InitStatus.PASS and added:
            message = f"{message}; saved {', '.join(added)} for the signed-in account"
        return InitResult(result.status, message, metadata)

    @staticmethod
    def _establish_baseline(controller: Any, params: Mapping[str, Any], saved: list[str]) -> str:
        expected = params.get("expected_logged_in")
        cfg = {
            "port": DEVTOOLS_PORT,
            "profile": PROFILE_DIR,
            "url": APP_URL,
            "key": STATE_KEY,
            "saved": saved,
            "required": [str(item) for item in params.get("required_note_ids") or []],
            "forbidden": [str(item) for item in params.get("forbidden_note_titles") or []],
            "notifications": [str(item) for item in params.get("required_notifications") or []],
            "expected_logged_in": None if expected is None else bool(expected),
        }
        cfg["edit_js"] = _EDIT_JS.replace("__CFG__", json.dumps(cfg))
        program = LOCAL_STORAGE_SOURCE + _BASELINE_PROGRAM.replace("__CFG__", repr(json.dumps(cfg)))
        script = "\n".join(
            [
                f"pkill -f -- {json.dumps('--user-data-dir=' + PROFILE_DIR)} || true",
                f"for i in $(seq 1 20); do pgrep -f -- {json.dumps('--user-data-dir=' + PROFILE_DIR)} >/dev/null || break; sleep 0.5; done",
                "python3 - <<'OSOMNI_PY'",
                program,
                "OSOMNI_PY",
            ]
        )
        return str(run_guest(controller, script, timeout=150).get("output") or "").strip()
