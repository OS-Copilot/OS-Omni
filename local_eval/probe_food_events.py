"""Device probe for actual OpenFood event handlers; never a formal DS result."""
import sys,json,time,copy,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['ANDROID_SDK_ROOT']=str(Path.home()/'AppData/Local/Android/Sdk')
os.environ['ANDROID_HOME']=os.environ['ANDROID_SDK_ROOT']
from platforms.android.controller import AdbController
from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools
from evaluators.android.openfood_poke_sushi_wallet_merchant_clean_20260729 import OpenFoodSmokehousePizzaMerchantOpsEvaluator
c=AdbController(adb_device='emulator-5582');page=WebViewDevTools(c,'com.killt.openfood')
out=ROOT/'local_eval/monitor-audits/20261009_0500-food-events';out.mkdir(exist_ok=True)
def click(selector):
 result=page.evaluate("(() => {const e=document.querySelector("+json.dumps(selector)+");if(!e)throw Error('Missing probe control');e.click();return 'clicked';})()")
 time.sleep(.25)
def state(): return page.read_key_as_document('openfood-static-state-v1')
assert page.evaluate("String(localStorage.getItem('openfood-static-state-v1')===null)")=='true'
click('[data-action="open-restaurant"]');click('[data-action="add-item"]')
# Use the real checkout button, without writing target business state.
click('[data-action="checkout"]');s=state();first=s['createdOrders'][0]['id']
click('[data-action="reorder"][data-id="'+first+'"]');click('[data-action="checkout"]');s=state();second=s['createdOrders'][0]['id']
click('[data-action="advance-order"][data-id="'+second+'"]');click('[data-action="advance-order"][data-id="'+second+'"]')
s=state();assert s['createdOrders'][0]['sourceOrderId']==first
assert s['reorderEvents']==[{'sourceOrderId':first,'newOrderId':second,'timestamp':s['reorderEvents'][0]['timestamp']}]
assert [e['status'] for e in s['orderStatusHistory'] if e['orderId']==second]==['Preparing','Out for delivery','Delivered']
(out/'device-state.json').write_text(json.dumps(s,indent=2),encoding='utf-8');c.screenshot(out/'delivered-screen.png')
e=OpenFoodSmokehousePizzaMerchantOpsEvaluator();params={'required_reorder_events':[{'source_order_index':0,'new_order_index':1}],'required_status_history':[{'order_index':1,'statuses':['Preparing','Out for delivery','Delivered']}]};obs=[{'matches':[{'id':first}]},{'matches':[{'id':second}]}]
normalized={'orders':s['createdOrders'],'reorder_events':s['reorderEvents'],'order_status_history':s['orderStatusHistory']}
results=[]
for name,doc in [('real_device',normalized),('missing_events',{'orders':[{'id':first},{'id':second}]}),('wrong_source',{'orders':[{'id':first},{'id':second}],'reorder_events':[{'sourceOrderId':'wrong','newOrderId':second}],'order_status_history':s['orderStatusHistory']}),('missing_middle_status',{'orders':s['createdOrders'],'reorder_events':s['reorderEvents'],'order_status_history':[x for x in s['orderStatusHistory'] if x['status']!='Out for delivery']})]:
 m={'checks':[]};f=[];e._check_process_events(doc,params,m,f,obs);results.append({'case':name,'failures':f,'checks':m['checks']})
 assert bool(f)==(name!='real_device'),(name,f)
# Reorder then Clear must not leak a source link into a fresh order.
click('[data-action="reorder"][data-id="'+first+'"]');click('[data-action="clear-cart"]');assert state()['pendingReorderSourceOrderId'] is None
(out/'regressions.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print('DEVICE_AND_GRADER_REGRESSIONS_PASS')
