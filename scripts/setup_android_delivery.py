"""Register the supplied pristine Android disks as a new AVD; never overwrite an AVD."""
import os, pathlib, shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
home=pathlib.Path(os.environ.get('ANDROID_AVD_HOME',str(pathlib.Path.home()/'.android/avd')))
dest=home/'AndroidWorldAvd.avd';ini=home/'AndroidWorldAvd.ini'
if dest.exists() or ini.exists():raise SystemExit('AndroidWorldAvd already exists. Refusing to overwrite it; use the existing AVD or explicitly relocate it yourself.')
sdk=pathlib.Path(os.environ.get('ANDROID_SDK_ROOT',os.environ.get('ANDROID_HOME','')))
if not str(sdk) or not (sdk/'system-images/android-33/google_apis/x86_64/system.img').is_file():raise SystemExit('Set ANDROID_SDK_ROOT and install system-images;android-33;google_apis;x86_64')
baseline=ROOT/'local_eval/vm-original-disks'
required=['userdata-qemu.img','userdata-qemu.img.qcow2','cache.img','cache.img.qcow2','encryptionkey.img','encryptionkey.img.qcow2']
if not all((baseline/n).is_file() for n in required):raise SystemExit('VM disks are excluded from GitHub. Obtain the separately supplied HF VM baseline first; see docs/android/external-vm-assets.json')
dest.mkdir(parents=True)
for n in required:shutil.copyfile(baseline/n,dest/n)
config=(ROOT/'docs/android/vm/config.ini').read_text(encoding='utf-8')
changes={'image.sysdir.1':'system-images/android-33/google_apis/x86_64/','AvdId':'AndroidWorldAvd','avd.ini.displayname':'AndroidWorldAvd'}
lines=[s for s in config.splitlines() if s.split('=',1)[0].strip() not in changes]
lines.extend(f'{k}={v}' for k,v in changes.items())
(dest/'config.ini').write_text('\n'.join(lines)+'\n',encoding='utf-8')
ini.write_text(f'avd.ini.encoding=UTF-8\npath={dest}\npath.rel=avd/AndroidWorldAvd.avd\ntarget=android-33\n',encoding='utf-8')
print('Created AndroidWorldAvd. Run local_eval/run_one.py --task <YAML> --preflight before a model run.')
