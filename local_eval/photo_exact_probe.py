import subprocess, pathlib, xml.etree.ElementTree as E, re, time, json, os
ADB=str(pathlib.Path(os.environ['LOCALAPPDATA'])/'Android/Sdk/platform-tools/adb.exe')
OUT=pathlib.Path('local_eval/monitor-audits/20261009_1744-guitar-driver')
def adb(*args): return subprocess.check_output([ADB,*map(str,args)],timeout=30).decode('utf-8',errors='replace')
def ui():
 adb('shell','uiautomator','dump','/sdcard/probe.xml'); return E.fromstring(adb('shell','cat','/sdcard/probe.xml'))
def tap(x,y): adb('shell','input','tap',x,y)
def click(label):
 r=ui(); ns=[n for n in r.iter('node') if n.get('content-desc')==label] or [n for n in r.iter('node') if n.get('text')==label]
 if not ns: raise ValueError(label)
 b=list(map(int,re.findall(r'\d+',ns[0].get('bounds')))); tap((b[0]+b[2])//2,(b[1]+b[3])//2)
def setval(v):
 r=ui(); s=next(n for n in r.iter('node') if n.get('class')=='android.widget.SeekBar'); b=list(map(int,re.findall(r'\d+',s.get('bounds')))); y=(b[1]+b[3])//2
 lo,hi=b[0],b[2]
 for i in range(12):
  x=(lo+hi)//2;tap(x,y);r=ui();vals=[int(n.get('text')) for n in r.iter('node') if re.fullmatch(r'-?\d+',n.get('text',''))];got=vals[0]
  if got==v:
   OUT.mkdir(exist_ok=True);(OUT/f'probe-setting-{time.time_ns()}.xml').write_bytes(E.tostring(r)); print('verified',v,flush=True);return
  if got<v:lo=x+1
  else:hi=x-1
 raise ValueError((v,got))
if __name__=='__main__':
 click('Blue');click('Hue');setval(-4);click('Saturation');setval(18);click('Luminance');setval(-6);click('Cyan');setval(5)
 click('Edit');click('Exposure');setval(4);click('Contrast');setval(15);click('Brightness');setval(6)
 adb('shell','input','swipe',900,2010,300,2010,400);click('Temperature');setval(-3)
 click('Landscape');print([(n.get('text'),n.get('content-desc'),n.get('bounds')) for n in ui().iter('node') if n.get('text') or n.get('content-desc')],flush=True)
