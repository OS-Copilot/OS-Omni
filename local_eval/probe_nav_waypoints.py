import os,sys,json,time,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['ANDROID_SDK_ROOT']=str(Path.home()/'AppData/Local/Android/Sdk');os.environ['ANDROID_HOME']=os.environ['ANDROID_SDK_ROOT']
from platforms.android.controller import AdbController
from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools
from evaluators.android.opennavigation_silicon_station_campus_records_20260803 import OpenNavigationRecordsEvaluator
import yaml
c=AdbController(adb_device='emulator-5582');page=WebViewDevTools(c,'com.killt.opennavigation');task=yaml.safe_load((ROOT/'local_eval/tasks/opennavigation_silicon_station_campus_records_20260803.yaml').read_text(encoding='utf-8'));original=ROOT/'local_eval/runs'/task['task_id']/'20261009_070944/end-state.json';state=json.loads(json.loads(original.read_text(encoding='utf-8'))['storage']['opennavigation.records-repair-v1']);out=ROOT/'local_eval/monitor-audits/20261009_0729-nav-waypoint-device';out.mkdir(exist_ok=True)
# Audit-only replay of immutable DS saved business state, never a formal score.
assert page.evaluate('String(recordsStore.routes.length===0 && recordsStore.incidents.length===0)')=='true'
def fixture(s):
 page.evaluate("localStorage.setItem('opennavigation.records-repair-v1',"+json.dumps(json.dumps(s))+");setTimeout(()=>location.reload(),250);")
 time.sleep(4);page.evaluate("document.querySelector('#records-button').click();");time.sleep(.5)
ev=OpenNavigationRecordsEvaluator();results=[]
for name,data in [('original_saved_state',state),('wrong_waypoints',copy.deepcopy(state))]:
 if name=='wrong_waypoints':
  for route in data['routes']:route['waypoints']=[]
 fixture(data);c.screenshot(out/(name+'.png'));result=ev.evaluate({'controller':c,'params':task['evaluation']['params']});results.append({'case':name,'status':result.status.value,'checks':result.metadata['checks'],'evidence':result.metadata['route_record_evidence']});assert result.status.value==('PASS' if name=='original_saved_state' else 'FAIL'),results[-1]
(out/'regressions.json').write_text(json.dumps({'audit_only':True,'never_count_as_model_score':True,'results':results},indent=2),encoding='utf-8');print('WAYPOINT_DEVICE_POSITIVE_NEGATIVE_PASS')
