"""Sequential, resumable Android evaluation; environment errors are not model FAILs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
parser = argparse.ArgumentParser()
parser.add_argument('--groups', nargs='*')
args = parser.parse_args()
queue_dir = ROOT / 'local_eval' / 'queue'
queue_dir.mkdir(exist_ok=True)
# OS releases this lock on exit, including a host/app interruption.
if os.name == 'nt':
    import msvcrt
    queue_lock = (queue_dir/'queue.lock').open('a+b')
    queue_lock.seek(0)
    try:
        msvcrt.locking(queue_lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit('Another Android queue is already running')
status_path = queue_dir / 'status.json'
status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}

def save():
    temporary = status_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(status_path)

tasks = list((ROOT / 'tasks/v1/android').glob('*.yaml'))
# Start with apps whose bundled inputs have already been verified.
priority = ['openbank','opennote','opentwitter','openshop','opentrip','openfood','opennavigation','opendriver','deltachat','openphoto']
tasks.sort(key=lambda p: (next((i for i,g in enumerate(priority) if p.name.startswith(g)),99),p.name))
for path in tasks:
    if args.groups and not any(path.name.startswith(g) for g in args.groups):
        continue
    task = yaml.safe_load(path.read_text(encoding='utf-8'))
    task_id = task['task_id']
    previous = status.get(task_id, {})
    # A host/app restart can kill the coordinator after the episode has already
    # written its verdict. Recover that verdict instead of spending another run.
    if previous.get('state') == 'running':
        candidates = list((ROOT/'local_eval/runs'/task_id).glob('*/result.json'))
        candidates = [p for p in candidates if p.stat().st_mtime >= previous.get('started_at', 0)]
        if candidates:
            report_path = max(candidates, key=lambda p:p.stat().st_mtime)
            report = json.loads(report_path.read_text(encoding='utf-8'))
            previous.update(state='completed',result=report['status'],steps=report['steps_taken'],report=str(report_path),ended_at=report_path.stat().st_mtime,recovered_after_interruption=True)
            save()
    if previous.get('state') == 'completed':
        continue
    status[task_id] = {'state':'preflight','task':str(path.relative_to(ROOT)), 'started_at':time.time(), 'python':sys.version}
    save()
    stem = path.stem
    with (queue_dir / (stem + '.preflight.log')).open('w',encoding='utf-8') as output:
        try:
            result = subprocess.run([sys.executable,'-u','local_eval/run_one.py','--task',str(path),'--preflight'], stdout=output,stderr=subprocess.STDOUT,timeout=600)
        except subprocess.TimeoutExpired:
            status[task_id].update(state='environment_error',reason='Preflight exceeded 600 seconds')
            save()
            continue
    if result.returncode:
        status[task_id].update(state='environment_error',preflight_exit_code=result.returncode)
        save()
        continue
    status[task_id]['state'] = 'running'
    save()
    before = set((ROOT/'local_eval/runs'/task_id).iterdir())
    with (queue_dir / (stem + '.model.log')).open('w',encoding='utf-8') as output:
        result = subprocess.run([sys.executable,'-u','local_eval/run_one.py','--task',str(path)],stdout=output,stderr=subprocess.STDOUT)
    after = set((ROOT/'local_eval/runs'/task_id).iterdir()) - before
    reports = [p/'result.json' for p in after if (p/'result.json').exists()]
    if reports:
        report_path = max(reports, key=lambda p:p.stat().st_mtime)
        report = json.loads(report_path.read_text(encoding='utf-8'))
        status[task_id].update(state='completed',result=report['status'],steps=report['steps_taken'],report=str(report_path),ended_at=time.time())
        if report.get('episode_result',{}).get('execution_valid') is False:
            status[task_id].update(state='execution_error',reason=report['episode_result'].get('execution_message'),excluded_from_model_score=True)
    else:
        status[task_id].update(state='runner_error',exit_code=result.returncode,ended_at=time.time())
    save()
