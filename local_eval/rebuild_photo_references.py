"""Author-authorized disposable GUI reference generation; never a model run."""
from local_eval.photo_exact_probe import adb, ui, tap
from pathlib import Path
from PIL import Image,ImageDraw
import xml.etree.ElementTree as E,re,time,json,statistics
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'local_eval/benchmark-v2/references';OUT.mkdir(exist_ok=True)
RECIPES={
'electric_guitar_portrait_21':('guitar','portrait_21.jpg',[('HSL','Blue','Hue',-4),('HSL','Blue','Saturation',18),('HSL','Blue','Luminance',-6),('HSL','Cyan','Luminance',5),('Edit','Exposure',4),('Edit','Contrast',15),('Edit','Brightness',6),('Edit','Temperature',-3),('Landscape','Structure',20),('Landscape','HDR',8),('Filters','Clean',18),('Edit','Saturation',7)]),
'wood_guitar_portrait_17':('guitar','portrait_17.jpg',[('Edit','Exposure',5),('Edit','Contrast',10),('Edit','Temperature',12),('Edit','Brightness',4),('Landscape','Structure',16),('Landscape','Warm Sun',10),('HSL','Orange','Saturation',12),('HSL','Orange','Luminance',4),('HSL','Red','Hue',3),('HSL','Yellow','Hue',-4),('Filters','Film',24)]),
'indoor_cooking_portrait_20':('cooking','portrait_20.jpg',[('Edit','Exposure',9),('Edit','Brightness',7),('Edit','Contrast',6),('Edit','Temperature',8),('Edit','Saturation',5),('Landscape','Structure',10),('Landscape','HDR',12),('HSL','Orange','Luminance',8),('HSL','Orange','Saturation',6),('HSL','Yellow','Hue',-3),('Filters','Clean',16)]),
'outdoor_cooking_portrait_16':('cooking','portrait_16.jpg',[('Landscape','Structure',12),('Landscape','Foliage',8),('Landscape','Sky',6),('Landscape','HDR',10),('Edit','Exposure',6),('Edit','Brightness',5),('Edit','Contrast',8),('Edit','Temperature',6),('HSL','Green','Saturation',8),('HSL','Green','Luminance',5),('HSL','Orange','Luminance',6),('Filters','Clean',14)])}
def click(label):
 for trial in range(8):
  r=ui();ns=[n for n in r.iter('node') if n.get('content-desc')==label] or [n for n in r.iter('node') if n.get('text')==label]
  if ns:
   b=list(map(int,re.findall(r'\d+',ns[0].get('bounds'))))
   if b[2]-b[0]>40:tap((b[0]+b[2])//2,(b[1]+b[3])//2);return
  adb('shell','input','swipe',150 if trial%4<2 else 950,2080,950 if trial%4<2 else 150,2080,500)
 raise ValueError('Missing control '+label)
def setval(v,folder,index,amount=False):
 r=ui();s=next(n for n in r.iter('node') if n.get('class')=='android.widget.SeekBar');b=list(map(int,re.findall(r'\d+',s.get('bounds'))));left,right=b[0]+32,b[2]-32;y=(b[1]+b[3])//2;minimum=0 if amount else -100;maximum=100;x=round(left+(right-left)*(v-minimum)/(maximum-minimum))
 lo,hi=left,right
 for i in range(12):
  tap(x,y);r=ui();vals=[int(n.get('text')) for n in r.iter('node') if re.fullmatch(r'-?\d+',n.get('text',''))];got=vals[0]
  if got==v:(folder/f'setting-{index}.xml').write_bytes(E.tostring(r));print('verified',index,v,flush=True);return
  if got<v:lo=x+1
  else:hi=x-1
  guess=round(x+(v-got)*(right-left)/(maximum-minimum));x=guess if lo<=guess<=hi else (lo+hi)//2
 raise ValueError((v,got))
def export(folder,name):
 before=set(adb('shell','ls','/sdcard/Pictures/OpenPhotoEdit').splitlines());click('Export');time.sleep(2);after=set(adb('shell','ls','/sdcard/Pictures/OpenPhotoEdit').splitlines());new=after-before
 if len(new)!=1:raise RuntimeError(('export count',new))
 f=next(iter(new));dest=folder/(name+'.jpg');adb('pull','/sdcard/Pictures/OpenPhotoEdit/'+f,str(dest));return dest
if __name__=='__main__':
 import yaml
 for pid,(group,source,recipe) in RECIPES.items():
  folder=OUT/pid;folder.mkdir(exist_ok=True)
  if (folder/'result.json').exists():continue
  task=yaml.safe_load((ROOT/f'local_eval/tasks/openphoto_{group}_dual_calibrated_export_20260804.yaml').read_text(encoding='utf-8'));boxes=task['evaluation']['params']['sample_boxes']
  original=ROOT/'local_eval/benchmark-v2/assets'/('outdoor-cooking-v2.jpg' if 'outdoor_cooking' in pid else 'indoor-cooking-v2.jpg') if group=='cooking' else ROOT/'local_eval/photo-originals'/source
  im=Image.open(original).convert('RGB');d=ImageDraw.Draw(im)
  for c,b in boxes.items():x1,y1,x2,y2=b;d.rectangle((x1-8,y1-8,x2+8,y2+8),fill={'red':(190,40,40),'green':(40,190,40),'blue':(40,40,190)}[c])
  im.save(folder/'input.jpg',quality=98,subsampling=0)
  adb('shell','am','force-stop','com.killt.openphotoedit');adb('shell','pm','clear','com.killt.openphotoedit');adb('shell','monkey','-p','com.killt.openphotoedit','-c','android.intent.category.LAUNCHER','1')
  remote='/sdcard/Pictures/benchmark_probe_'+pid+'_'+str(time.time_ns())+'.jpg';adb('push',str(folder/'input.jpg'),remote);adb('shell','am','broadcast','-a','android.intent.action.MEDIA_SCANNER_SCAN_FILE','-d','file://'+remote);time.sleep(2)
  click('Import Photo');r=ui();nodes=[n for n in r.iter('node') if n.get('content-desc','').startswith('Photo taken')];b=list(map(int,re.findall(r'\d+',nodes[0].get('bounds'))));x,y=(b[0]+b[2])//2,(b[1]+b[3])//2;adb('shell','input','swipe',x,y,x,y,1100);click('Add');time.sleep(1)
  # Pristine negative export from the same input is captured before any recipe settings.
  adb('shell','mkdir','-p','/sdcard/Pictures/OpenPhotoEdit');export(folder,'unedited-negative')
  group_prev=None
  for i,step in enumerate(recipe):
   group_now=step[0]
   if group_now!=group_prev:click(group_now);group_prev=group_now
   if group_now=='HSL':click(step[1]);click(step[2])
   else:click(step[1])
   setval(step[-1],folder,i,amount=group_now=='Filters')
  positive=export(folder,'correct');repeat=export(folder,'correct-repeat')
  click('Edit');click('Exposure');setval(35,folder,'negative-exposure');negative=export(folder,'wrong-exposure-negative')
  def med(p):
   image=Image.open(p).convert('RGB');return {c:[int(statistics.median(px[ch] for px in image.crop(tuple(b)).getdata())) for ch in range(3)] for c,b in boxes.items()}
  result={'profile_id':pid,'group':group,'source':source,'recipe':recipe,'expected_median_rgb':med(positive),'repeat_median_rgb':med(repeat),'unedited_median_rgb':med(folder/'unedited-negative.jpg'),'wrong_exposure_median_rgb':med(negative),'correct':str(positive),'input':str(folder/'input.jpg'),'probe_only':True}
  (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('PROFILE_DONE',pid,result['expected_median_rgb'],flush=True)
