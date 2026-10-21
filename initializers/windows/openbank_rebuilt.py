"""Prepare the published seed customer without completing benchmark goals."""
import json
import secrets
import time
from pathlib import Path
from core.init import BaseInitializer, InitResult, InitStatus

class OpenBankRebuiltInitializer(BaseInitializer):
    def initialize(self, context):
        controller = context['controller']
        seed = json.loads((Path(__file__).parent/'assets/openbank-published-seed.json').read_text(encoding='utf-8'))
        account = seed['account']
        password = secrets.token_urlsafe(18)
        body = dict(identityValue=seed['accounts'][0]['accountNumber'], taxIdLast4=account['taxIdLast4'], email=account['email'], username=account['username'], password=password, confirmPassword=password)
        try:
            controller.run_powershell_script('Get-Process OpenBank -ErrorAction SilentlyContinue | Stop-Process -Force', timeout=10)
            controller.launch_app(r'C:\OS-Omni\Apps\OpenBank\openbank.exe')
            time.sleep(5)
            code = "import urllib.request,json,time,pyautogui\n"
            code += "body="+repr(json.dumps(body))+"\n"
            code += "req=urllib.request.Request('http://127.0.0.1:4340/api/enroll',data=body.encode(),headers={'Content-Type':'application/json'})\n"
            code += "r=json.load(urllib.request.urlopen(req,timeout=10));assert r['session']['loggedIn']\n"
            code += "pyautogui.click(600,350);pyautogui.hotkey('ctrl','a');pyautogui.write("+repr(account['username'])+",interval=0.1)\n"
            code += "pyautogui.click(600,429);pyautogui.hotkey('ctrl','a');pyautogui.write("+repr(password)+",interval=0.1)\n"
            code += "pyautogui.click(600,557);time.sleep(3)\n"
            code += "s=json.load(urllib.request.urlopen('http://127.0.0.1:4340/api/bootstrap',timeout=10));assert s['session']['loggedIn'];assert s['customer']['displayName']=='Jordan Lee';print('SEED_CUSTOMER_READY')"
            result=controller.run_python_script(code, timeout=30)
            if result.get('returncode') != 0 or 'SEED_CUSTOMER_READY' not in result.get('output',''):
                return InitResult(status=InitStatus.ERROR,message='Published seed initialization failed; formal task must not run')
            return InitResult(status=InitStatus.PASS,message='Prepared authenticated Jordan Lee seed; no recipients, transfers, bill payments or disputes created',metadata={'rebuild_version':'author-windows-openbank-init-v1','business_goal_actions':False})
        except Exception:
            return InitResult(status=InitStatus.ERROR,message='OpenBank seed preflight failed')
