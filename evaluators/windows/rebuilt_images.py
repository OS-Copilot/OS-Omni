"""Read-only independent image oracle; never alter model output."""
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageChops,ImageStat
from core.evaluation import BaseEvaluator,EvalResult,EvalStatus
ROOT=Path(__file__).resolve().parents[2]/'tasks/v1/windows/files/author-rebuilt-images-v1'
def check_image(actual,reference):
    if actual.size!=reference.size:return False,'dimensions differ'
    diff=ImageChops.difference(actual.convert('RGB'),reference.convert('RGB'))
    error=max(ImageStat.Stat(diff).mean)
    return error<=1.0,{'mean_channel_error':error,'tolerance':1.0}
class RebuiltImageEvaluator(BaseEvaluator):
    def evaluate(self,context):
        c=context['controller'];key=context['params']['asset_set'];checks=[]
        for i in range(1,5):
            path=rf'C:\Users\User\Documents\author_rebuilt_images\{key}\export{i}.png'
            try:
                data=c.get_file(path)
                with Image.open(BytesIO(data)) as actual,Image.open(ROOT/key/f'reference{i}.png') as ref:passed,detail=check_image(actual,ref)
            except Exception:passed,detail=False,'required readable PNG missing'
            checks.append({'file':path,'passed':passed,'detail':detail})
        return EvalResult(status=EvalStatus.PASS if all(x['passed'] for x in checks) else EvalStatus.FAIL,message='Four exact exports passed' if all(x['passed'] for x in checks) else 'Author image exports mismatch',metadata={'version':'author-rebuilt-images-v1','read_only':True,'checks':checks})
