"""Author reconstruction v1: deterministic graphics, four exact GUI exports."""
from pathlib import Path
import time
from core.init import BaseInitializer,InitResult,InitStatus

ROOT=Path(__file__).resolve().parents[2]/'tasks/v1/windows/files/author-rebuilt-images-v1'
class RebuiltImageInitializer(BaseInitializer):
    def initialize(self,context):
        c=context['controller'];key=context['params']['asset_set'];remote=rf'C:\Users\User\Documents\author_rebuilt_images\{key}'
        try:
            c.run_powershell_script(f"New-Item -ItemType Directory -Force -Path '{remote}' | Out-Null\nGet-Process gimp-2.10 -ErrorAction SilentlyContinue | Stop-Process -Force",timeout=15)
            for p in sorted((ROOT/key).glob('source*.png')):c.upload_file(str(p),remote+'\\'+p.name)
            c.run_powershell_script(f"Start-Process -FilePath 'C:\\Program Files\\GIMP 2\\bin\\gimp-2.10.exe' -ArgumentList @('{remote}\\source1.png')",timeout=15)
            time.sleep(8)
            focus="import win32gui,win32con,pyautogui,time\nwindows=[]\ndeadline=time.monotonic()+60\nwhile not windows and time.monotonic()<deadline:\n win32gui.EnumWindows(lambda h,_:windows.append(h) if win32gui.IsWindowVisible(h) and '[source1]' in win32gui.GetWindowText(h) and 'GIMP' in win32gui.GetWindowText(h) else None,None)\n if not windows:time.sleep(2)\nassert windows,'GIMP imported source window not ready'\npyautogui.press('alt');time.sleep(0.3);win32gui.ShowWindow(windows[-1],win32con.SW_RESTORE);win32gui.SetForegroundWindow(windows[-1]);time.sleep(2)"
            r=c.run_python_script(focus,timeout=75)
            if r.get('returncode')!=0:raise RuntimeError('GIMP focus failed: '+r.get('output','')[-350:])
            if 'gimp' not in str(c.observe(include_ui_tree=False).foreground_app).lower():raise RuntimeError('GIMP foreground not confirmed')
            return InitResult(status=InitStatus.PASS,message='Four author-generated sources uploaded; GIMP launched',metadata={'version':'author-rebuilt-images-v1','asset_set':key})
        except Exception as exc:
            return InitResult(status=InitStatus.ERROR,message=f'Author image setup failed: {type(exc).__name__}: {exc}')
