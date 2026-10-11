"""Register extracted Android V3 without embedding a Windows user path."""
import argparse,os,shutil
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--avd-home',type=Path,default=Path(os.environ.get('ANDROID_AVD_HOME',str(Path.home()/'.android/avd'))))
p.add_argument('--baseline-only',action='store_true')
args=p.parse_args()
root=Path(__file__).resolve().parent
source=root/'AndroidWorldAvd.avd'
baseline=root/'host/local_eval/vm-original-disks'
if baseline.exists():raise SystemExit('Existing baseline; use a fresh extraction')
if not args.baseline_only and (args.avd_home/'AndroidWorldAvd.avd').exists():raise SystemExit('Existing AVD; choose a separate --avd-home')
baseline.mkdir(parents=True)
for src in source.iterdir():
    if src.suffix in {'.img','.qcow2'}:shutil.copyfile(src,baseline/src.name)
if not args.baseline_only:
    dest=args.avd_home/'AndroidWorldAvd.avd'
    args.avd_home.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,dest)
    (args.avd_home/'AndroidWorldAvd.ini').write_text('avd.ini.encoding=UTF-8\npath='+str(dest.resolve())+'\npath.rel=avd/AndroidWorldAvd.avd\ntarget=android-33\n',encoding='utf-8')
print('V3 baseline installed. Set ANDROID_AVD_HOME to chosen AVD directory. Set OS_OMNI_VM_ARCHIVE to a non-existing path to prevent historical v2 archive from replacing V3 baselines. Historical score uses v2 plus per-task repairs; V3 is newly baked.')
