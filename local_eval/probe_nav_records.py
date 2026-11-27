import os,sys,time,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['ANDROID_SDK_ROOT']=str(Path.home()/'AppData/Local/Android/Sdk');os.environ['ANDROID_HOME']=os.environ['ANDROID_SDK_ROOT']
from platforms.android.controller import AdbController
from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools
from evaluators.android.opennavigation_meta_campus_transit_records_20260803 import OpenNavigationRecordsEvaluator
c=AdbController(adb_device='emulator-5582');page=WebViewDevTools(c,'com.killt.opennavigation');out=ROOT/'local_eval/monitor-audits/20261009_0614-nav-device';out.mkdir(exist_ok=True)
def js(s):return page.evaluate(s)
def click(selector):js('document.querySelector('+json.dumps(selector)+').click();');time.sleep(.3)
assert js("String(recordsStore.routes.length===0 && recordsStore.incidents.length===0)")=='true'
click('#options-button');assert js("String(document.querySelector('dialog').innerText.includes('Route preferences'))")=='true';click('dialog input[name="avoid_highways"]');click('dialog button[type="submit"]')
for _ in range(40):
 if js('String((state.routePlan?.routes?.length||0)>0)')=='true':break
 time.sleep(1)
else:raise RuntimeError('No genuine backend route plan returned')
assert js('String(state.routePreferences.avoid_highways)')=='true'
js("document.querySelector('#route-name').value='WorkflowProbe';");click('#save-route-button');click('#records-button');c.screenshot(out/'route-record.png');click('#workflow-records [data-record-id]');js('startNavigationMode();');time.sleep(.5);click('#report-button');assert js("String(document.querySelector('dialog').innerText.includes('Report an incident'))")=='true';js("document.querySelector('dialog [name=note]').value='ProbeNote';");click('dialog button[type="submit"]');click('#records-button');c.screenshot(out/'records-screen.png')
s=page.read_key_as_document('opennavigation.records-repair-v1');assert len(s['routes'])==1 and len(s['incidents'])==1;route=s['routes'][0];assert s['incidents'][0]['routeId']==route['id'];assert route['preferences']['avoid_highways'] is True
(out/'state.json').write_text(json.dumps(s,indent=2),encoding='utf-8');dest=js('displayPlaceName(recordsStore.routes[0].destination)');mode=route['mode'].title();params={'expected_route_records':[{'required_texts':['WorkflowProbe',mode,dest]}],'expected_incident_records':[{'required_texts':['Heavy traffic','ProbeNote','WorkflowProbe']}],'expected_visible_texts':['Saved routes','Incident reports'],'forbidden_texts':['No saved routes','No incident reports']};ev=OpenNavigationRecordsEvaluator();results=[]
for name,change in [('real_device',{}),('wrong_destination',{'expected_route_records':[{'required_texts':['WorkflowProbe',mode,'NonexistentEndpoint']}]}),('wrong_link',{'expected_incident_records':[{'required_texts':['Heavy traffic','ProbeNote','OtherRoute']}]} )]:
 result=ev.evaluate({'controller':c,'params':{**params,**change}});results.append({'case':name,'status':result.status.value,'metadata':result.metadata});assert result.status.value==('PASS' if name=='real_device' else 'FAIL'),(name,result.metadata)
(out/'regressions.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print('NAV_DEVICE_REGRESSIONS_PASS')
