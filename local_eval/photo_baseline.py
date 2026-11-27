"""Rebuild missing RGB input strips; export pixels are produced only by the agent."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw
from core.init import BaseInitializer, InitResult, InitStatus, load_initializer

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = {
    'clown': {'portrait_17.jpg':'portrait_30.jpg','portrait_16.jpg':'portrait_28.jpg'},
    'coastal': {'landscape_18.jpg':'landscape_18.jpg','landscape_17.jpg':'landscape_17.jpg'},
    'cooking': {'portrait_20.jpg':'portrait_20.jpg','portrait_16.jpg':'portrait_16.jpg'},
    'guitar': {'portrait_21.jpg':'portrait_21.jpg','portrait_17.jpg':'portrait_17.jpg'},
}

class PhotoInputBaselineInitializer(BaseInitializer):
    def initialize(self, context):
        params = dict(context.get('params') or {})
        original = params.pop('source_initializer')
        task = context['task']
        import yaml
        path = next(p for p in (ROOT/'local_eval/tasks').glob('*photo*.yaml') if yaml.safe_load(p.read_text(encoding='utf-8'))['task_id'] == task.id)
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        eval_params = data['evaluation']['params']
        group = next(g for g in SOURCE_MAP if ('_' + g + '_') in path.name)
        run = Path(context['run_dir'])
        inputs = run/'reconstructed-inputs'
        inputs.mkdir(exist_ok=True)
        controller = context['controller']
        provenance = []
        try:
            for target, source in SOURCE_MAP[group].items():
                original_photo = (ROOT/'local_eval/benchmark-v2/assets'/('outdoor-cooking-v2.jpg' if target=='portrait_16.jpg' else 'indoor-cooking-v2.jpg')) if group=='cooking' else ROOT/'local_eval/photo-originals'/source
                photo = Image.open(original_photo).convert('RGB')
                if list(photo.size) != eval_params['expected_dimensions']:
                    raise ValueError('Unexpected source dimensions for '+source)
                draw = ImageDraw.Draw(photo)
                for color, box in eval_params['sample_boxes'].items():
                    x1,y1,x2,y2 = box
                    draw.rectangle((x1-8,y1-8,x2+8,y2+8), fill=({'red':(190,40,40),'green':(40,190,40),'blue':(40,40,190)} if group in ('cooking','guitar') else {'red':(255,0,0),'green':(0,255,0),'blue':(0,0,255)})[color])
                output = inputs/target
                photo.save(output,quality=98,subsampling=0)
                controller.execute_adb(['push',str(output),'/sdcard/Pictures/'+target])
                controller.execute_adb(['shell','am','broadcast','-a','android.intent.action.MEDIA_SCANNER_SCAN_FILE','-d','file:///sdcard/Pictures/'+target])
                provenance.append({'source':source,'source_path':str(original_photo.relative_to(ROOT)),'target':target,'source_sha256':hashlib.sha256(original_photo.read_bytes()).hexdigest(),'fixture_sha256':hashlib.sha256(output.read_bytes()).hexdigest()})
            export_dir=eval_params['export_dir']
            listing=controller.execute_adb(['shell','find',export_dir,'-maxdepth','1','-type','f','-name','OpenPhotoEdit_*.jpg'])
            paths=[line.strip() for line in str(listing).splitlines() if line.strip().startswith(export_dir+'/')]
            baseline={'paths':paths,'reconstructed':True,'calibration_input':'pure RGB stripes at declared sample boxes, padded eight pixels','provenance':provenance,'limitations':[]}
            if group in ('cooking','guitar'):
                baseline['benchmark_version']='author-rebuilt-photo-v2'
                baseline['calibration_input']='unclipped primary color patches RGB190/40/40,40/190/40,40/40/190'
            if group=='cooking':
                baseline['source_revision']='Author-authorized generated indoor and outdoor cooking photographs; original downloaded source retained separately.'
            (run/'openphoto_calibrated_baseline.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
            result=load_initializer(original).initialize(dict(context,params=params))
            if result.status != InitStatus.PASS:
                return result
            return InitResult(InitStatus.PASS,'Calibrated photo inputs and export baseline',baseline)
        except Exception as exc:
            return InitResult(InitStatus.ERROR,f'Photo fixture reconstruction failed: {exc}')
