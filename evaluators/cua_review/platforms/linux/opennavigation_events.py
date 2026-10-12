"""Navigation event log for the OpenNavigation web build.

The web build at http://127.0.0.1:4321 keeps navigation sessions only in page
memory: Start, Overview and End never reach its backend or Local Storage. To
judge route-review tasks from what the application actually did, the task
initializer installs a passive recorder in the page through Chrome DevTools.
It samples the page's own ``state`` object and records each change of the
navigation flag (start/end) with the current mode, origin and destination, and
it records clicks on the navigation overlay buttons (Overview, Mute, ...). The
log is kept in the page's Local Storage under ``EVENT_KEY`` so it survives a
reload, and the recorder reinstalls itself on every new document.

Both directions run inside the guest through the runtime controller.
"""

from __future__ import annotations

import json
from typing import Any

EVENT_KEY = "osomni.opennavigation.events.v1"
DEFAULT_DEVTOOLS_PORT = 1337
PAGE_TERMS = ("127.0.0.1:4321", "localhost:4321")

RECORDER_JS = r"""
(function () {
  var KEY = %(key)s;
  function ready() {
    try { return typeof state === "object" && state !== null && typeof displayPlaceName === "function"; }
    catch (e) { return false; }
  }
  function snapshot() {
    try {
      return { mode: state.mode || null, origin: displayPlaceName(state.origin),
               destination: displayPlaceName(state.destination), navigating: !!state.isNavigating };
    } catch (e) { return { error: String(e) }; }
  }
  function log(action, extra) {
    var rows = [];
    try { rows = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { rows = []; }
    var row = { t: Date.now(), action: action };
    var snap = snapshot();
    for (var k in snap) row[k] = snap[k];
    for (var j in (extra || {})) row[j] = extra[j];
    rows.push(row);
    localStorage.setItem(KEY, JSON.stringify(rows));
  }
  function install() {
    if (window.__osomniNavRecorder || !ready()) return !!window.__osomniNavRecorder;
    window.__osomniNavRecorder = true;
    var navigating = !!state.isNavigating;
    setInterval(function () {
      var now = !!state.isNavigating;
      window.__osomniNavRecorderTick = Date.now();
      if (now !== navigating) { navigating = now; log(now ? "start" : "end"); }
    }, 250);
    // Buttons may act on pointerdown and hide the overlay before "click" fires.
    var last = { label: null, t: 0 };
    function onPress(event) {
      var el = event.target && event.target.closest ? event.target.closest("button,[role=button]") : null;
      if (!el) return;
      var label = (el.textContent || el.getAttribute("aria-label") || "").trim();
      if (!/^(Overview|Report|Voice|Mute|Unmute|End|Leave now|Other time)$/.test(label)) return;
      var now = Date.now();
      if (label === last.label && now - last.t < 600) return;
      last = { label: label, t: now };
      log("click", { label: label });
    }
    document.addEventListener("pointerdown", onPress, true);
    document.addEventListener("click", onPress, true);
    return true;
  }
  if (!install()) {
    var timer = setInterval(function () { if (install()) clearInterval(timer); }, 250);
  }
  return window.__osomniNavRecorder ? "installed" : "pending";
})()
""" % {"key": json.dumps(EVENT_KEY)}

_GUEST_PROGRAM = r'''
import base64, json, os, socket, struct, urllib.request
from urllib.parse import urlparse
PORT = __PORT__
TERMS = __TERMS__
CALLS = __CALLS__

def cdp(ws_url, calls, timeout=8.0):
    parsed = urlparse(ws_url)
    sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)
    state = {"buf": b""}
    def read(count):
        while len(state["buf"]) < count:
            chunk = sock.recv(65536)
            if not chunk:
                raise OSError("websocket closed")
            state["buf"] += chunk
        out, state["buf"] = state["buf"][:count], state["buf"][count:]
        return out
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(("GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                      % (parsed.path, parsed.hostname, parsed.port, key)).encode())
        while b"\r\n\r\n" not in state["buf"]:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("websocket handshake closed")
            state["buf"] += chunk
        head, state["buf"] = state["buf"].split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise OSError("websocket handshake refused")
        results = []
        for number, (method, params) in enumerate(calls, start=1):
            payload = json.dumps({"id": number, "method": method, "params": params}).encode()
            mask = os.urandom(4)
            header = bytearray([0x81])
            if len(payload) < 126:
                header.append(0x80 | len(payload))
            elif len(payload) < 65536:
                header += bytes([0x80 | 126]) + struct.pack(">H", len(payload))
            else:
                header += bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
            sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
            message = b""
            while True:
                first, second = read(2)
                length = second & 0x7F
                if length == 126:
                    length = struct.unpack(">H", read(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", read(8))[0]
                if second & 0x80:
                    read(4)
                data = read(length)
                if first & 0x0F == 0x8:
                    raise OSError("websocket closed by peer")
                if first & 0x0F not in (0x0, 0x1):
                    continue
                message += data
                if not first & 0x80:
                    continue
                reply = json.loads(message.decode("utf-8", "replace"))
                message = b""
                if reply.get("id") == number:
                    results.append(reply.get("result") or {"error": reply.get("error")})
                    break
        return results
    finally:
        sock.close()

out = {"pages": [], "errors": []}
try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d/json/list" % PORT, timeout=5) as response:
        pages = json.loads(response.read().decode("utf-8", "replace"))
except Exception as exc:
    pages = []
    out["errors"].append("devtools list: %s" % exc)
for page in pages:
    hay = (page.get("url") or "").lower()
    if page.get("type") != "page" or not page.get("webSocketDebuggerUrl") or not any(t in hay for t in TERMS):
        continue
    try:
        out["pages"].append({"url": page.get("url"), "results": cdp(page["webSocketDebuggerUrl"], CALLS)})
    except Exception as exc:
        out["errors"].append("%s: %s" % (page.get("url"), exc))
print(json.dumps(out, ensure_ascii=False))
'''


def _run(controller: Any, calls: list[tuple[str, dict[str, Any]]], port: int, timeout: int) -> dict[str, Any]:
    program = (_GUEST_PROGRAM.replace("__PORT__", str(int(port)))
               .replace("__TERMS__", json.dumps(list(PAGE_TERMS)))
               .replace("__CALLS__", "json.loads(%r)" % json.dumps(calls)))
    raw = controller.run_python_script(program, timeout=timeout)
    text = str(raw.get("stdout") or raw.get("output") or "").strip()
    try:
        return json.loads(text.splitlines()[-1])
    except (IndexError, ValueError):
        return {"pages": [], "errors": ["guest program: %s" % (raw.get("error") or text)[:500]]}


def install_recorder(controller: Any, *, port: int = DEFAULT_DEVTOOLS_PORT, clear: bool = True, timeout: int = 30) -> dict[str, Any]:
    """Install the recorder in open OpenNavigation pages and for future documents."""
    calls: list[tuple[str, dict[str, Any]]] = [("Page.enable", {}),
                                               ("Page.addScriptToEvaluateOnNewDocument", {"source": RECORDER_JS})]
    if clear:
        calls.append(("Runtime.evaluate", {"expression": "localStorage.removeItem(%s); 'cleared'" % json.dumps(EVENT_KEY),
                                           "returnByValue": True}))
    calls.append(("Runtime.evaluate", {"expression": RECORDER_JS, "returnByValue": True}))
    return _run(controller, calls, port, timeout)


KEEPER_PATH = "/tmp/osomni_opennavigation_recorder.py"


def start_recorder_keeper(controller: Any, *, port: int = DEFAULT_DEVTOOLS_PORT, interval: float = 1.0,
                          hours: float = 4.0) -> dict[str, Any]:
    """Re-install the recorder every ``interval`` seconds so a page reload does not end recording.

    A script added with Page.addScriptToEvaluateOnNewDocument only lasts as long as the
    DevTools session that added it, so the guest keeps re-running the idempotent install.
    The loop stops after ``hours`` and with the next snapshot restore.
    """
    program = (_GUEST_PROGRAM.replace("__PORT__", str(int(port)))
               .replace("__TERMS__", json.dumps(list(PAGE_TERMS)))
               .replace("__CALLS__", "json.loads(%r)" % json.dumps(
                   [("Runtime.evaluate", {"expression": RECORDER_JS, "returnByValue": True})])))
    rounds = max(1, int(hours * 3600 / interval))
    script = "\n".join([
        "cat > %s <<'OSOMNI_PY'" % KEEPER_PATH,
        program,
        "OSOMNI_PY",
        "pkill -f '[o]somni_opennavigation_recorder' || true",
        "setsid -f bash -c 'for i in $(seq %d); do timeout 10 python3 %s >/dev/null 2>&1; sleep %s; done' "
        ">/dev/null 2>&1 </dev/null" % (rounds, KEEPER_PATH, interval),
        "echo keeper-started",
    ])
    return controller.run_bash_script(script, timeout=30)


def read_events(controller: Any, *, port: int = DEFAULT_DEVTOOLS_PORT, timeout: int = 30) -> dict[str, Any]:
    """Return the recorded events of each open OpenNavigation page."""
    expression = "JSON.stringify({events: JSON.parse(localStorage.getItem(%s) || '[]'), recorder: !!window.__osomniNavRecorder})" % json.dumps(EVENT_KEY)
    # A native dialog left open (for example Report's confirmation) blocks evaluation; accept it first.
    calls = [("Page.enable", {}), ("Page.handleJavaScriptDialog", {"accept": True}),
             ("Runtime.evaluate", {"expression": expression, "returnByValue": True})]
    reply = _run(controller, calls, port, timeout)
    pages = []
    for page in reply.get("pages") or []:
        value = (((page.get("results") or [{}])[-1].get("result") or {}).get("value"))
        try:
            parsed = json.loads(value) if isinstance(value, str) else {}
        except ValueError:
            parsed = {}
        pages.append({"url": page.get("url"), "events": list(parsed.get("events") or []), "recorder": bool(parsed.get("recorder"))})
    return {"pages": pages, "errors": list(reply.get("errors") or [])}
