import time
from pathlib import Path
from core.init import BaseInitializer,InitResult,InitStatus
ROOT=Path(__file__).resolve().parents[2]/'tasks/v1/windows/files/author-routes-v1'
class RebuiltRoutesInitializer(BaseInitializer):
 def initialize(self,context):
  c=context['controller'];remote=r'C:\Users\User\Documents\author_routes_v1'
  try:
   c.run_powershell_script(f"New-Item -ItemType Directory -Force -Path '{remote}' | Out-Null\nRemove-Item -LiteralPath '{remote}\\state.json' -ErrorAction SilentlyContinue",timeout=15)
   c.upload_file(str(ROOT/'server.py'),remote+'\\server.py')
   script=f"$env:AUTHOR_ROUTE_STATE='{remote}\\state.json'\nStart-Process -WindowStyle Hidden -FilePath 'C:\\Users\\User\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' -ArgumentList @('{remote}\\server.py')\nStart-Sleep -Seconds 2"
   r=c.run_powershell_script(script,timeout=15)
   if r.get('returncode')!=0:raise RuntimeError('launch failed')
   browser="import subprocess\nsubprocess.Popen([r'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe','--no-first-run','--app=http://127.0.0.1:4388/'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
   r=c.run_python_script(browser,timeout=10)
   if r.get('returncode')!=0:raise RuntimeError('Browser spawn failed')
   time.sleep(4)
   focus="import win32gui,win32con,pyautogui,time\nwindows=[]\nwin32gui.EnumWindows(lambda h,_:windows.append(h) if win32gui.IsWindowVisible(h) and 'Author Route Planner' in win32gui.GetWindowText(h) else None,None)\nassert windows,'Planner browser not ready'\npyautogui.press('alt');win32gui.ShowWindow(windows[-1],win32con.SW_RESTORE);win32gui.SetForegroundWindow(windows[-1]);time.sleep(2)"
   r=c.run_python_script(focus,timeout=10)
   if r.get('returncode')!=0:raise RuntimeError('Planner focus failed')
   return InitResult(status=InitStatus.PASS,message='Author offline route planner ready; empty route history')
  except Exception as exc:return InitResult(status=InitStatus.ERROR,message=f'Author route setup failed: {type(exc).__name__}: {exc}')
