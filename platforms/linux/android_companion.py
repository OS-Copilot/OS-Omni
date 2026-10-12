"""Android phone mirrored into the Linux desktop (scrcpy) for single-screen cross-device tasks.

The emulator runs on the host. Its adbd port is forwarded to an address the Linux
guest can reach, the guest connects its own adb to it, and scrcpy shows the phone in
a window on the guest desktop. The agent only sees and drives the Linux desktop;
initializers and evaluators reach the phone from the host with adb.

The host-side settings come from the environment, so one task file serves any VM:

* ``OS_OMNI_ANDROID_SERIAL``: host adb serial of the companion emulator (``emulator-5570``)
* ``OS_OMNI_ANDROID_ADB``: host adb binary (default ``adb`` on PATH)
* ``ANDROID_ADB_SERVER_PORT``: host adb server port, as adb itself reads it
* ``OS_OMNI_ANDROID_FORWARD``: ``listen_host:listen_port`` reachable from the guest
* ``OS_OMNI_ANDROID_SNAPSHOT``: emulator snapshot restored before each task
"""

from __future__ import annotations

import asyncio
import os
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

WINDOW_TITLE = "Android phone"


@dataclass(frozen=True)
class CompanionSettings:
    serial: str
    adb_path: str
    adb_port: int | None
    forward_host: str
    forward_port: int
    snapshot: str

    @classmethod
    def from_env(cls) -> "CompanionSettings":
        serial = os.environ.get("OS_OMNI_ANDROID_SERIAL", "").strip()
        forward = os.environ.get("OS_OMNI_ANDROID_FORWARD", "").strip()
        if not serial or ":" not in forward:
            raise RuntimeError("OS_OMNI_ANDROID_SERIAL and OS_OMNI_ANDROID_FORWARD (host:port) are required")
        host, port = forward.rsplit(":", 1)
        adb_port = os.environ.get("ANDROID_ADB_SERVER_PORT", "").strip()
        return cls(serial=serial, adb_path=os.environ.get("OS_OMNI_ANDROID_ADB", "adb").strip() or "adb",
                   adb_port=int(adb_port) if adb_port else None, forward_host=host, forward_port=int(port),
                   snapshot=os.environ.get("OS_OMNI_ANDROID_SNAPSHOT", "").strip())

    @property
    def adbd_port(self) -> int:
        """The emulator's adbd port is its console port + 1 (emulator-5570 -> 5571)."""
        return int(self.serial.rsplit("-", 1)[1]) + 1

    def adb(self, *args: str, timeout: int = 60) -> str:
        env = dict(os.environ)
        if self.adb_port:
            env["ANDROID_ADB_SERVER_PORT"] = str(self.adb_port)
        result = subprocess.run([self.adb_path, "-s", self.serial, *args], capture_output=True, text=True,
                                timeout=timeout, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
        return result.stdout


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def ensure_forward(settings: CompanionSettings) -> None:
    """Start the host forwarder for the emulator's adbd port unless it already listens."""
    if _port_open(settings.forward_host, settings.forward_port):
        return
    subprocess.Popen([sys.executable, "-m", "platforms.linux.android_companion", "forward", settings.forward_host,
                      str(settings.forward_port), "127.0.0.1", str(settings.adbd_port)],
                     cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    deadline = time.monotonic() + 10
    while not _port_open(settings.forward_host, settings.forward_port):
        if time.monotonic() > deadline:
            raise RuntimeError(f"adb forwarder did not start on {settings.forward_host}:{settings.forward_port}")
        time.sleep(0.2)


def reset_phone(settings: CompanionSettings, *, boot_timeout: int = 180) -> None:
    """Restore the configured emulator snapshot and wait until Android has booted."""
    if settings.snapshot:
        settings.adb("emu", "avd", "snapshot", "load", settings.snapshot, timeout=120)
    deadline = time.monotonic() + boot_timeout
    while True:
        try:
            if settings.adb("shell", "getprop", "sys.boot_completed", timeout=20).strip() == "1":
                break
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("companion phone did not finish booting")
        time.sleep(2)
    settings.adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    settings.adb("shell", "wm", "dismiss-keyguard")


def scrcpy_script(settings: CompanionSettings, *, x: int, y: int, height: int) -> str:
    """Guest bash that (re)connects adb to the phone and opens the scrcpy window."""
    target = f"{settings.forward_host}:{settings.forward_port}"
    title = shlex.quote(WINDOW_TITLE)
    return "\n".join([
        "export DISPLAY=${DISPLAY:-:0}",
        # pyautogui types < ( ) through keycodes 94/187/188 (ISO and keypad keys), which the
        # phone drops or remaps; clearing them makes it use the main-keyboard keys.
        "xmodmap -e 'keycode 94 = NoSymbol' -e 'keycode 187 = NoSymbol' -e 'keycode 188 = NoSymbol' || true",
        "for attempt in 1 2 3; do",
        "  pkill -f /opt/scrcpy/scrcpy || true",
        f"  adb disconnect {target} >/dev/null 2>&1 || true",
        f"  for i in $(seq 20); do adb connect {target} | grep -q connected && break; sleep 1; done",
        f"  timeout 30 adb -s {target} wait-for-device",
        f"  setsid -f scrcpy -s {target} --window-title {title} --window-x {x} --window-y {y} "
        f"--window-height {height} --keyboard=uhid --no-audio >/tmp/osomni_scrcpy.log 2>&1 </dev/null",
        # Ready only if the window appears and is still open a few seconds later.
        f"  for i in $(seq 30); do wmctrl -l | grep -q {title} && break; sleep 1; done",
        f"  sleep 4; wmctrl -l | grep -q {title} && echo SCRCPY_READY && exit 0",
        "  echo \"scrcpy attempt $attempt failed\" >&2; cat /tmp/osomni_scrcpy.log >&2; sleep 3",
        "done",
        "exit 1",
    ])


async def _forward(listen_host: str, listen_port: int, target_host: str, target_port: int) -> None:
    async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(target_host, target_port)
        except OSError:
            writer.close()
            return
        await asyncio.gather(pipe(reader, upstream_writer), pipe(upstream_reader, writer), return_exceptions=True)

    server = await asyncio.start_server(handle, listen_host, listen_port)
    async with server:
        await server.serve_forever()


def main(argv: list[Any]) -> None:
    if len(argv) == 5 and argv[0] == "forward":
        asyncio.run(_forward(argv[1], int(argv[2]), argv[3], int(argv[4])))
        return
    raise SystemExit("usage: python -m platforms.linux.android_companion forward LISTEN_HOST LISTEN_PORT TARGET_HOST TARGET_PORT")


if __name__ == "__main__":
    main(sys.argv[1:])
