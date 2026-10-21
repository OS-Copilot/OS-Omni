"""Run one released task, keeping initialization/evaluation evidence separate."""
import sys, os, json, argparse, logging, time, importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
secret_path = Path(os.environ.get('OS_OMNI_SECRET_FILE', str(Path.home()/'.codex/secrets/os-omni-deepseek.json')))
if secret_path.is_file():
    for key, value in json.loads(secret_path.read_text(encoding='utf-8-sig')).items():
        os.environ.setdefault(key, value)
os.environ.setdefault('ANDROID_SDK_ROOT', os.environ.get('ANDROID_HOME', str(Path.home()/'AppData/Local/Android/Sdk')))
os.environ['ANDROID_HOME'] = os.environ['ANDROID_SDK_ROOT']
os.environ['PYTHONUTF8'] = '1'

import yaml
from platforms.android.controller import AdbController
from platforms.android.core.types import load_task_from_file
from core.init import load_initializer
from platforms.android.runners.benchmark import run_benchmark

parser = argparse.ArgumentParser()
parser.add_argument('--task', required=True)
parser.add_argument('--preflight', action='store_true')
parser.add_argument('--max-steps', type=int, default=180)
parser.add_argument('--gpu', choices=['host', 'angle_indirect', 'swiftshader_indirect'], help='Explicit backend for controlled compatibility probes')
args = parser.parse_args()
path = ROOT / args.task
data = yaml.safe_load(path.read_text(encoding='utf-8'))
run = ROOT/'local_eval/runs'/data['task_id']/time.strftime('%Y%m%d_%H%M%S')
run.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s', handlers=[logging.StreamHandler(),logging.FileHandler(run/'run.log',encoding='utf-8')])
from local_eval.cold_reset import cold_reset
from local_eval.start_services import ensure_services
ensure_services()
# Original OpenPhoto shader exceeds the software backend's uniform limit.
# Audited host GPU retains the original shader and supports edit/export.
host_gpu = data['task_id'].startswith('android.openphoto.') or data['task_id'] == 'android.opendriver.seeded_driver_profile_document_arrival_5930_20260729'
cold_reset(run, gpu=args.gpu or ('host' if host_gpu else 'swiftshader_indirect'))
controller = AdbController(adb_device='emulator-5582')
time.sleep(5)
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    boot = controller.execute_adb(['shell','getprop','sys.boot_completed']).strip()
    package_service = controller.execute_adb(['shell','pm','path','com.android.settings']).strip()
    storage = controller.execute_adb(['shell','test -d /sdcard/Android && echo ready']).strip()
    if boot == '1' and package_service.startswith('package:') and storage == 'ready':
        break
    time.sleep(3)
else:
    raise RuntimeError('Restored emulator did not recover Android services and shared storage within 180 seconds')
if data['task_id'].startswith('android.deltachat.'):
    controller.execute_adb(['root'])
    controller.execute_adb(['wait-for-device'])
    time.sleep(3)
package = data['init'].get('params',{}).get('app_package')
if package == 'com.killt.openphotoedit':
    # Pristine restored SystemUI repeatedly ANRs on PhotoPicker. Recover only
    # during preparation, before any model action; application inputs untouched.
    controller.execute_adb(['root'])
    controller.execute_adb(['wait-for-device'])
    old_ui = controller.execute_adb(['shell','pidof','com.android.systemui']).strip()
    if not old_ui.isdigit():
        raise RuntimeError('Cannot identify SystemUI preparation process')
    controller.execute_adb(['shell','kill','-9',old_ui])
    time.sleep(5)
    new_ui = controller.execute_adb(['shell','pidof','com.android.systemui']).strip()
    if not new_ui.isdigit() or new_ui == old_ui:
        raise RuntimeError('SystemUI recovery failed before OpenPhoto episode')
    (run/'systemui-recovery.json').write_text(json.dumps({'repair':'openphoto-systemui-preparation-v1','old_pid':old_ui,'new_pid':new_ui,'reason':'Repeated actual PhotoPicker SystemUI ANRs; recovery validated on device'},indent=2),encoding='utf-8')
if package in {'com.killt.openfood','com.killt.opennavigation'}:
    # Original VM APK omits event provenance required by the released graders.
    # Reinstall from the audited patch on every pristine VM restore.
    import hashlib
    patched_name = 'openfood-events-v1.apk' if package == 'com.killt.openfood' else 'opennavigation-records-v1.apk'
    patched_apk = ROOT/'local_eval/apks'/patched_name
    provenance = json.loads(patched_apk.with_suffix('.json').read_text(encoding='utf-8'))
    if hashlib.sha256(patched_apk.read_bytes()).hexdigest() != provenance['patched_sha256']:
        raise RuntimeError('OpenFood provenance APK checksum mismatch')
    removal = controller.execute_adb(['uninstall',package])
    if removal.strip() != 'Success':
        raise RuntimeError('Cannot remove original OpenFood APK: '+removal)
    installed = controller.execute_adb(['install',str(patched_apk)])
    if 'Success' not in installed:
        raise RuntimeError('Cannot install OpenFood event provenance repair: '+installed)
    (run/'app-patch.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
if package:
    # Recreate WebViews after restoring a VM snapshot; old CDP targets can be stale.
    controller.execute_adb(['shell','am','force-stop',package])
    if package in {'com.killt.opennote','com.killt.opentwitter','com.killt.openbank','com.killt.openshop'}:
        reset_output = controller.execute_adb(['shell','pm','clear',package])
        if reset_output.strip() != 'Success':
            raise RuntimeError('Unable to reset app to its bundled APK seed: '+reset_output)
        (run/'app-reset.json').write_text(json.dumps({'package':package,'method':'pm clear; reconstructed session initializer',
            'original_snapshot_available':False}),encoding='utf-8')
task = load_task_from_file(str(path))
if args.preflight:
    init = load_initializer(data['init']['initializer_id']).initialize({'task':task,'params':data['init'].get('params',{}),'controller':controller,'run_dir':run})
    init_record = {'status':init.status.value,'message':init.message,'metadata':init.metadata}
    time.sleep(5)
    (run/'initialization.json').write_text(json.dumps(init_record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('INITIALIZER',init_record['status'],init_record['message'],flush=True)
    spec = data['evaluation']['evaluator_id']
    module, cls = spec.split(':')
    evaluator = getattr(importlib.import_module(module),cls)()
    result = evaluator.evaluate({'task':task,'task_id':task.id,'params':data['evaluation'].get('params',{}),'controller':controller,'run_dir':run})
    record = {'status':result.status.value,'message':result.message,'metadata':result.metadata}
    (run/'baseline-evaluation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('BASELINE_EVALUATOR',record['status'],record['message'],flush=True)
    controller.screenshot(run/'starting-screen.png')
    captured = run/'starting-screen.png'
    if not captured.exists() or captured.stat().st_size < 1000:
        raise RuntimeError('Preflight could not capture the actual starting screen')
    from PIL import Image
    with Image.open(captured) as starting_image:
        starting_image.verify()
    if package in {'com.killt.opennote','com.killt.openbank','com.killt.openshop','com.killt.opentrip','com.killt.opentwitter','com.killt.openfood','com.killt.opennavigation'}:
        from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools
        page = WebViewDevTools(controller,package)
        summary = page.evaluate('JSON.stringify({url:location.href,keys:Object.keys(localStorage),text:document.body.innerText.slice(0,2000)})')
        (run/'starting-page.json').write_text(summary,encoding='utf-8')
        print('STARTING_PAGE',summary[:2000],flush=True)
    sys.exit(0 if init_record['status']=='PASS' and record['status']=='FAIL' else 1)
print('RUN_DIRECTORY',run,flush=True)
step_limit = min(180, args.max_steps, task.max_steps)
model_settings = yaml.safe_load((ROOT/'configs/models.yaml').read_text(encoding='utf-8'))
model_entry = model_settings.get('models', model_settings)['deepseek_flash']
(run/'execution-profile.json').write_text(json.dumps({'model_id':'deepseek_flash','reasoning_effort':model_entry.get('metadata',{}).get('reasoning_effort'),'max_steps':step_limit},indent=2),encoding='utf-8')
sys.exit(run_benchmark(task_path=path,model_id='deepseek_flash',adb_device='emulator-5582',run_dir=run,observation_mode='screenshot_only',history_window=None,max_steps=step_limit))
