"""Focus a launched Electron window without assuming its position on screen."""

import json
from typing import Any


def focus_electron_window(controller, process_name: str, title: str, timeout: int = 15):
    code = (
        "import json,time,psutil,pyautogui,win32gui,win32process,win32con\n"
        f"wanted={process_name.lower()!r};title={title.lower()!r}\n"
        f"deadline=time.monotonic()+{timeout!r}\n"
        "while time.monotonic()<deadline:\n"
        "    owners={p.pid for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower()==wanted}\n"
        "    windows=[]\n"
        "    win32gui.EnumWindows(lambda hwnd,_: windows.append(hwnd) if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] in owners and title in win32gui.GetWindowText(hwnd).lower() else None,None)\n"
        "    if windows:\n"
        "        hwnd=windows[0];win32gui.ShowWindow(hwnd,win32con.SW_RESTORE)\n"
        "        was_topmost=bool(win32gui.GetWindowLong(hwnd,win32con.GWL_EXSTYLE)&win32con.WS_EX_TOPMOST)\n"
        "        flags=win32con.SWP_NOMOVE|win32con.SWP_NOSIZE|win32con.SWP_SHOWWINDOW\n"
        "        win32gui.SetWindowPos(hwnd,win32con.HWND_TOPMOST,0,0,0,0,flags)\n"
        "        left,top,right,bottom=win32gui.GetWindowRect(hwnd)\n"
        "        try:\n"
        "            pyautogui.click((left+right)//2,top+15);time.sleep(0.3)\n"
        "        finally:\n"
        "            if not was_topmost:\n"
        "                win32gui.SetWindowPos(hwnd,win32con.HWND_NOTOPMOST,0,0,0,0,flags)\n"
        "        if win32gui.GetForegroundWindow()==hwnd:\n"
        "            print(json.dumps({'foreground_confirmed':True}));break\n"
        "    time.sleep(0.3)\n"
        "else:\n"
        "    raise RuntimeError('launched application window could not be focused')\n"
    )
    result = controller.run_python_script(code, timeout=timeout + 5)
    if int(result.get('returncode', -1)) != 0:
        raise RuntimeError('launched application window could not be focused')
    report = json.loads(str(result.get('stdout') or result.get('output') or ''))
    if report.get('foreground_confirmed') is not True:
        raise RuntimeError('launched application foreground was not confirmed')
    return report


def probe_electron_backend(controller: Any, port: int, *, ready: bool) -> dict:
    script = (
        "import json, psutil, urllib.request\n"
        f"port = {port!r}\n"
        "listeners = []\n"
        "for conn in psutil.net_connections(kind='tcp'):\n"
        "    if conn.status != 'LISTEN' or conn.laddr.port != port:\n"
        "        continue\n"
        "    try:\n"
        "        process = psutil.Process(conn.pid)\n"
        "        listeners.append({'pid': conn.pid, 'name': process.name()})\n"
        "    except psutil.NoSuchProcess:\n"
        "        continue\n"
        "result = {'listeners': listeners}\n"
        + (
            "with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/evaluation', timeout=3) as response:\n"
            "    state = json.load(response)\n"
            "result['session'] = state.get('session')\n"
            "result['event_count'] = len(state.get('events', []))\n"
            if ready else ""
        )
        + "print(json.dumps(result))\n"
    )
    result = controller.run_python_script(script, timeout=10)
    if int(result.get("returncode", -1)) != 0:
        raise RuntimeError("Electron backend port/state probe failed")
    return json.loads(str(result.get("stdout") or result.get("output") or ""))
