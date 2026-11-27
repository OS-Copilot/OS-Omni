"""Serialized formal queue with evidence-based exclusion, no model assistance."""
import json,sys,subprocess,datetime,os
from pathlib import Path
from PIL import Image
B=Path(os.environ["OS_OMNI_WINDOWS_EXPERIMENT"])
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,d):p.write_text(json.dumps(d,indent=2),encoding='utf-8')
def audit(task,run):
 result=read(run/'result.json');rows=[json.loads(x) for x in (run/'trajectory.jsonl').read_text(encoding='utf-8').splitlines()] if (run/'trajectory.jsonl').exists() else []
 init=result.get('initializer') or {};ev=result.get('evaluation') or {};issues=[]
 if init.get('status')!='PASS':issues.append('initializer_'+str(init.get('status')))
 if ev.get('status')=='ERROR' or result.get('status')=='ERROR':issues.append('explicit_execution_or_grader_error')
 screenshot=run/'screenshots/final.png'
 if not screenshot.exists():issues.append('missing_final_screenshot')
 else:
  with Image.open(screenshot) as im:im.verify()
 tokens=sorted({(r.get('llm_reasoning') or {}).get('reasoning_tokens',0) or 0 for r in rows})
 if len(rows)>task['max_steps']:issues.append('step_cap_violation')
 review={'task_id':task['id'],'report_path':str(run/'result.json'),'status':'excluded_explicit_infrastructure_error' if issues else 'valid_formal_result','count_as_model_failure':not issues and result.get('status')=='FAIL','steps':result.get('steps_taken'),'reasoning_tokens':tokens,'formal_checks':{'initializer':init.get('status'),'evaluation':ev.get('status'),'final_screenshot_exists':screenshot.exists(),'original_step_cap':task['max_steps']},'explicit_defects':issues,'termination':result.get('episode_result'),'policy':'Normal model FAIL unless explicit App/bench/execution evidence; no GPT goal actions or mandatory completion proof'}
 write(run/'end-state.json',{'review':review,'evaluation':ev,'final_observation':result.get('final_observation')})
 a=read(B/'failure-audit.json');a['reviews'].append(review);write(B/'failure-audit.json',a)
 e=read(B/'experiment.json')
 if not issues:e.setdefault('valid_results',{})[task['id']]={'verdict':result['status'],'classification':'model_failure' if result['status']=='FAIL' else 'model_success','report':str(run/'result.json')}
 else:
  e.setdefault('excluded_attempts',[]).append(str(run/'result.json'));e['deferred_tasks']=list(dict.fromkeys(e.get('deferred_tasks',[])+[task['id']]))
 e['valid_completed_tasks']=len(e.get('valid_results',{}));e['pending_model_reviews']=[x for x in e.get('pending_model_reviews',[]) if x!=task['id']];write(B/'experiment.json',e)
 counts={s:sum(v['verdict']==s for v in e['valid_results'].values()) for s in ['PASS','FAIL']}
 (B/'SUMMARY.md').write_text(f"# Windows evaluation\n\nValid completed:{e['valid_completed_tasks']}/48; PASS{counts['PASS']}; model FAIL{counts['FAIL']}.\n\nSerialized queue active. Explicit initialization/execution defects retained separately; normal FAIL does not require GPT completion proof.\n",encoding='utf-8')
 return not issues
def main():
 status={'pid':os.getpid(),'phase':'running','policy':'evidence_based_default_fail'};write(B/'queue-status.json',status)
 e=read(B/'experiment.json');e['audit_policy']=status['policy'];e['phase']='formal_queue';write(B/'experiment.json',e)
 # Finish already-completed reviews under the user's clarified policy.
 for task in e['tasks']:
  if task['id'] not in e.get('valid_results',{}):
   candidates=sorted((B/'runs'/task['id']).glob('attempt-*/result.json'))
   if candidates and str(candidates[-1]) not in e.get('excluded_attempts',[]):audit(task,candidates[-1].parent)
 for task in e['tasks']:
  state=read(B/'experiment.json')
  if task['id'] in state.get('valid_results',{}):continue
  if task['id'] in state.get('deferred_tasks',[]):continue
  runs=B/'runs'/task['id'];prior=list(runs.glob('attempt-*')) if runs.exists() else []
  attempt=max([int(p.name.split('-')[1]) for p in prior]+[0])+1;run=runs/('attempt-%03d'%attempt)
  status.update(task=task['id'],attempt=attempt,phase='running');write(B/'queue-status.json',status)
  with (B/'queue-worker.log').open('ab') as log:
   child=subprocess.Popen([sys.executable,str(Path(__file__).with_name("run_windows_task.py")),task['path'],str(attempt)],stdout=log,stderr=log)
   status['worker_pid']=child.pid;write(B/'queue-status.json',status)
   try:child.wait(timeout=5400)
   except subprocess.TimeoutExpired:
    # Kill only this worker tree, preserve artifacts, continue later.
    subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=log,stderr=log);status['last_issue']='worker_time_budget_exceeded';write(B/'queue-status.json',status)
    state=read(B/'experiment.json');state['deferred_tasks']=list(dict.fromkeys(state.get('deferred_tasks',[])+[task['id']]));write(B/'experiment.json',state)
    continue
  if (run/'result.json').exists():audit(task,run)
  else:
   state=read(B/'experiment.json');state['deferred_tasks']=list(dict.fromkeys(state.get('deferred_tasks',[])+[task['id']]));write(B/'experiment.json',state)
 status.update(phase='pass_finished_pending_defect_repairs',worker_pid=None);write(B/'queue-status.json',status)
if __name__=='__main__':main()
