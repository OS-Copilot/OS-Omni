"""Controlled initializer/evaluator audit; never calls a model or resumes queue."""
import os, sys, json, time, importlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ['ANDROID_SDK_ROOT'] = str(Path.home()/'AppData/Local/Android/Sdk')
import yaml
from platforms.android.controller import AdbController
from platforms.android.core.types import load_task_from_file
from core.init import load_initializer
from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools

controller = AdbController(adb_device='emulator-5582')
output = ROOT/'local_eval/audit-smoke'/time.strftime('%Y%m%d_%H%M%S')
output.mkdir(parents=True)
rows = []
for path in sorted((ROOT/'local_eval/tasks').glob('*.yaml')):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    package = data.get('init',{}).get('params',{}).get('app_package','')
    if package not in {'com.killt.opennote','com.killt.opentwitter','com.killt.openshop','com.killt.openbank'}:
        continue
    run = output/data['task_id']; run.mkdir()
    row = {'task_id': data['task_id']}
    try:
        # Factory APK seed reset, explicitly separate from historical model runs.
        controller.execute_adb(['shell','pm','clear',package])
        task = load_task_from_file(str(path))
        context = {'task':task,'controller':controller,'run_dir':run,'params':data['init']['params']}
        init = load_initializer(data['init']['initializer_id']).initialize(context)
        row['initializer'] = {'status':init.status.value,'message':init.message}
        if init.status.value == 'PASS':
            controller.screenshot(run/'starting-screen.png')
            page = WebViewDevTools(controller,package)
            state = page.evaluate('JSON.stringify({url:location.href,storage:Object.fromEntries(Object.entries(localStorage))})')
            (run/'starting-state.json').write_text(state,encoding='utf-8')
            module, cls = data['evaluation']['evaluator_id'].split(':')
            result = getattr(importlib.import_module(module),cls)().evaluate(dict(context, params=data['evaluation'].get('params',{}),task_id=task.id))
            record = {'status':result.status.value,'message':result.message,'metadata':result.metadata}
            (run/'baseline-evaluation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            row['baseline_evaluator'] = result.status.value
    except Exception as exc:
        row['error'] = f'{type(exc).__name__}: {exc}'
    rows.append(row)
    (output/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(row,ensure_ascii=False),flush=True)
print('AUDIT_OUTPUT', output, flush=True)
