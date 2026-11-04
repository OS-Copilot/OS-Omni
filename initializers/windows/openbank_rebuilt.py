"""Prepare the published seed customer without completing benchmark goals."""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.windows.electron_window import focus_electron_window, probe_electron_backend


class OpenBankRebuiltInitializer(BaseInitializer):
    def initialize(self, context):
        controller = context.get('controller')
        if controller is None:
            return InitResult(status=InitStatus.ERROR, message='controller is required')
        params = dict(context.get('params') or {})
        port = int(params.get('port', 4340))
        if port != 4340:
            return InitResult(status=InitStatus.ERROR, message='Published OpenBank uses evaluator port 4340')
        seed = json.loads((Path(__file__).parent / 'assets/openbank-published-seed.json').read_text(encoding='utf-8'))
        account = seed['account']
        password = secrets.token_urlsafe(18)
        body = dict(identityValue=seed['accounts'][0]['accountNumber'], taxIdLast4=account['taxIdLast4'],
                    email=account['email'], username=account['username'], password=password,
                    confirmPassword=password)
        stage = 'stop_previous_instances'
        try:
            stopped = controller.run_powershell_script(
                "Get-Process OpenBank -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction Stop; Write-Output 'STOPPED'", timeout=10)
            if int(stopped.get('returncode', -1)) != 0:
                raise RuntimeError('previous OpenBank instances could not be stopped')
            stage = 'check_port'
            deadline = time.monotonic() + 8
            while True:
                owners = [owner for candidate in (port, 9434)
                          for owner in probe_electron_backend(controller, candidate, ready=False)['listeners']]
                if not owners:
                    break
                if any(owner['name'].lower() != 'openbank.exe' for owner in owners):
                    raise RuntimeError('OpenBank backend/debug port is owned by another process')
                if time.monotonic() >= deadline:
                    raise RuntimeError('Previous OpenBank ports did not close after process shutdown')
                time.sleep(0.2)
            stage = 'launch'
            launched = controller.run_powershell_script(
                "Start-Process -FilePath 'C:\\OS-Omni\\Apps\\OpenBank\\openbank.exe' "
                "-ArgumentList @('--force-renderer-accessibility','--remote-debugging-port=9434','--remote-debugging-address=127.0.0.1')", timeout=10)
            if int(launched.get('returncode', -1)) != 0:
                raise RuntimeError('OpenBank launch failed')
            stage = 'backend_readiness'
            deadline = time.monotonic() + 30
            while True:
                try:
                    ready = probe_electron_backend(controller, port, ready=True)
                    if not ready['listeners'] or any(p['name'].lower() != 'openbank.exe' for p in ready['listeners']):
                        raise RuntimeError('OpenBank port is owned by another process')
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('OpenBank backend did not become ready') from None
                    time.sleep(0.5)
            # Enrollment is setup only. Return to the account page afterwards so its
            # in-memory UI consumes the authenticated bootstrap. Reloading login.html leaves the sign-in form visible even when the
            # backend is authenticated. Coordinate-based
            # typing into a presumed login form can leave GUI and API divergent.
            stage = 'focus_window'
            focus_electron_window(controller, 'openbank.exe', 'OpenBank')
            stage = 'enroll_and_reload_gui'
            code = 'import urllib.request,json,time,pyautogui,psutil,win32gui,win32process,win32con\n'
            code += 'body=' + repr(json.dumps(body)) + '\n'
            code += "req=urllib.request.Request('http://127.0.0.1:4340/api/enroll',data=body.encode(),headers={'Content-Type':'application/json'})\n"
            code += "r=json.load(urllib.request.urlopen(req,timeout=10));assert r['session']['loggedIn']\n"
            code += "owners={x.pid for x in psutil.net_connections(kind='tcp') if x.status=='LISTEN' and x.laddr.port==4340}\n"
            code += "windows=[]\nwin32gui.EnumWindows(lambda hwnd,_: windows.append(hwnd) if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] in owners and 'openbank' in win32gui.GetWindowText(hwnd).lower() else None,None)\n"
            code += "assert windows, 'OpenBank GUI missing';assert win32gui.GetForegroundWindow()==windows[0], 'OpenBank GUI not foreground'\n"
            code += "time.sleep(0.3)\n"
            code += "s=json.load(urllib.request.urlopen('http://127.0.0.1:4340/api/bootstrap',timeout=10));assert s['session']['loggedIn'];assert s['customer']['displayName']=='Jordan Lee';print('SEED_CUSTOMER_READY')"
            result = controller.run_python_script(code, timeout=30)
            if int(result.get('returncode', -1)) != 0 or 'SEED_CUSTOMER_READY' not in str(result.get('output') or result.get('stdout') or ''):
                raise RuntimeError('OpenBank seed/UI synchronization failed')
            stage = 'navigate_authenticated_page'
            navigation = controller.run_powershell_script(
                (Path(__file__).parent / 'assets/navigate-openbank.ps1').read_text(encoding='utf8'), timeout=20)
            if int(navigation.get('returncode', -1)) != 0 or 'OPENBANK_GUI_AUTHENTICATED' not in str(navigation.get('output') or ''):
                raise RuntimeError('OpenBank authenticated page navigation failed')
            stage = 'confirm_foreground_window'
            focus_electron_window(controller, 'openbank.exe', 'OpenBank')
            observation = controller.observe(include_ui_tree=False, include_screenshot_data=False)
            if str(observation.foreground_app).lower() not in {'openbank', 'openbank.exe'}:
                raise RuntimeError('OpenBank foreground window was not confirmed')
            return InitResult(
                status=InitStatus.PASS,
                message='Prepared authenticated Jordan Lee in both GUI and evaluator backend',
                metadata={'rebuild_version': 'author-windows-openbank-init-v2', 'port': port,
                          'gui_authenticated': True, 'business_goal_actions': False})
        except Exception as exc:
            # Do not include guest source/errors: enrollment source contains a
            # randomly generated password, which is never returned or logged.
            return InitResult(status=InitStatus.ERROR, message='OpenBank seed/UI/port preflight failed; task must not run', metadata={'stage': stage, 'error_type': type(exc).__name__})
