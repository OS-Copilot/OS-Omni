"""Author rebuilt photo benchmark v2: calibrated pixels plus whole-photo identity."""
from pathlib import Path
import tempfile,hashlib
from PIL import Image, ImageChops, ImageStat
from core.evaluation import EvalResult, EvalStatus
from evaluators.android.openphoto_guitar_dual_calibrated_export_20260804 import OpenPhotoCoastalCalibrationEvaluator
ROOT=Path(__file__).resolve().parents[1]
class AuthorPhotoV2Evaluator(OpenPhotoCoastalCalibrationEvaluator):
 def evaluate(self,context):
  params=context.get('params') or {};profiles=params.get('profiles',[])
  refs={}
  try:
   for p in profiles:
    path=(ROOT/p['reference_image']).resolve()
    if not path.is_relative_to(ROOT/'local_eval/benchmark-v2/references'):raise ValueError('Reference outside versioned benchmark directory')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=p['reference_sha256']:raise ValueError('Reference checksum mismatch')
    refs[p['profile_id']]=Image.open(path).convert('RGB')
  except Exception as exc:return EvalResult(EvalStatus.ERROR,'v2 reference asset unavailable',{'error':str(exc),'benchmark_version':'author-rebuilt-photo-v2'})
  result=super().evaluate(context)
  if result.status==EvalStatus.ERROR:return result
  evidence=[];matches={};used=set();threshold=float(params.get('reference_mae_tolerance',2.0))
  with tempfile.TemporaryDirectory(prefix='photo-v2-grade-') as temp:
   images={}
   for i,item in enumerate(result.metadata.get('file_evidence',[])):
    remote=item['remote_path'];dest=Path(temp)/f'{i}.jpg'
    try:
     context['controller'].execute_adb(['pull',remote,str(dest)]);images[remote]=Image.open(dest).convert('RGB')
    except Exception as exc:evidence.append({'remote_path':remote,'error':str(exc)})
   for profile in profiles:
    pid=profile['profile_id'];candidates=[]
    for item in result.metadata.get('file_evidence',[]):
     remote=item['remote_path'];im=images.get(remote)
     if im is None or im.size!=refs[pid].size:continue
     mae=sum(ImageStat.Stat(ImageChops.difference(im,refs[pid])).mean)/3
     rgb=next((s for s in item.get('profile_scores',[]) if s['profile_id']==pid),{})
     ok=bool(rgb.get('within_tolerance')) and mae<=threshold
     evidence.append({'profile_id':pid,'remote_path':remote,'whole_image_mae':mae,'mae_tolerance':threshold,'calibration_ok':bool(rgb.get('within_tolerance')),'accepted':ok})
     if ok and remote not in used:candidates.append((mae,remote))
    if candidates:_,remote=min(candidates);matches[pid]=remote;used.add(remote)
  meta=dict(result.metadata);meta.update(benchmark_version='author-rebuilt-photo-v2',reference_image_evidence=evidence,reference_matches=matches)
  checks=dict(meta['checks']);checks['all_expected_profiles_matched']=len(matches)==len(profiles);checks['distinct_files_for_profiles']=len(used)==len(profiles);checks['correct_source_and_render']=len(matches)==len(profiles);meta['checks']=checks;meta['failures']=[k for k,v in checks.items() if not v]
  return EvalResult(EvalStatus.FAIL if meta['failures'] else EvalStatus.PASS,'Author photo v2 export checks '+('failed' if meta['failures'] else 'passed'),meta)
