"""Freeze independent GUI references, validate positive/negative photo v2 cases."""
from pathlib import Path
import json,yaml,shutil,tempfile,types,hashlib
from PIL import Image
from local_eval.photo_v2_evaluator import AuthorPhotoV2Evaluator
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'local_eval/benchmark-v2';REFERENCE=BASE/'references'
def configure():
 for group in ('guitar','cooking'):
  path=ROOT/f'local_eval/tasks/openphoto_{group}_dual_calibrated_export_20260804.yaml';data=yaml.safe_load(path.read_text(encoding='utf-8'));params=data['evaluation']['params']
  for p in params['profiles']:
   result=json.loads((REFERENCE/p['profile_id']/'result.json').read_text(encoding='utf-8'))
   if result['expected_median_rgb']!=result['repeat_median_rgb']:raise RuntimeError('Reference repeat not deterministic '+p['profile_id'])
   p['expected_median_rgb']=result['expected_median_rgb'];p['reference_image']=str(Path(result['correct']).relative_to(ROOT)).replace('\\','/')
   p['reference_sha256']=hashlib.sha256(Path(result['correct']).read_bytes()).hexdigest()
  params['channel_tolerance']=1;params['reference_mae_tolerance']=2.0;data['evaluation']['evaluator_id']='local_eval.photo_v2_evaluator:AuthorPhotoV2Evaluator'
  data.setdefault('metadata',{})['benchmark_revision']={'version':'author-rebuilt-photo-v2','author_authorization':'Generate missing cooking source; recalibrate evaluation locally','reference_origin':'Exact task recipe on real original Android APK, independent probe; no DS traces used','legacy_task':f'local_eval/benchmark-v2/legacy/{group}-task.yaml','calibration':'Unclipped primary RGB patches; per-channel tolerance1 plus whole-image MAE<=2','recipe_changed':False}
  path.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False,width=110),encoding='utf-8')
class FilesController:
 def __init__(self,files):self.files={f'/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_test_{i}.jpg':p for i,p in enumerate(files)}
 def execute_adb(self,args):
  if args[0]=='pull':shutil.copy2(self.files[args[1]],args[2]);return 'pulled'
  if args[0]=='shell':return '\n'.join(f'{remote}\t{p.stat().st_size}\t{1000+i}' for i,(remote,p) in enumerate(self.files.items()))
  raise ValueError(args)
 def observe(self,**kwargs):return types.SimpleNamespace(ui_nodes=[{'text':'Export','package':'com.killt.openphotoedit'},{'text':'Edit','package':'com.killt.openphotoedit'}])
def validate():
 checks=[]
 for group in ('guitar','cooking'):
  data=yaml.safe_load((ROOT/f'local_eval/tasks/openphoto_{group}_dual_calibrated_export_20260804.yaml').read_text(encoding='utf-8'));params=data['evaluation']['params'];folders=[REFERENCE/p['profile_id'] for p in params['profiles']];good=[p/'correct-repeat.jpg' for p in folders]
  cases={'positive-repeat':(good,'PASS'),'unedited':([p/'unedited-negative.jpg' for p in folders],'FAIL'),'wrong-exposure':([p/'wrong-exposure-negative.jpg' for p in folders],'FAIL'),'duplicate-source':([good[0],good[0]],'FAIL'),'wrong-source':([p/'correct.jpg' for p in REFERENCE.iterdir() if p.is_dir() and p not in folders][:2],'FAIL')}
  for name,(files,expected) in cases.items():
   controller=FilesController(files);result=AuthorPhotoV2Evaluator().evaluate({'params':params,'controller':controller});actual=result.status.value;checks.append({'group':group,'case':name,'expected':expected,'actual':actual,'metadata':result.metadata});print(group,name,actual,flush=True)
   if actual!=expected:raise RuntimeError('Validator discriminative check failed '+group+name)
  with tempfile.TemporaryDirectory() as tmp:
   controller=FilesController(good);(Path(tmp)/'openphoto_calibrated_baseline.json').write_text(json.dumps({'paths':list(controller.files)}),encoding='utf-8');result=AuthorPhotoV2Evaluator().evaluate({'params':params,'controller':controller,'run_dir':tmp});checks.append({'group':group,'case':'preexisting-export-baseline','expected':'FAIL','actual':result.status.value,'metadata':result.metadata});assert result.status.value=='FAIL'
 (BASE/'validation.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
if __name__=='__main__':configure();validate()
