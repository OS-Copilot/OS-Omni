"""Restore and verify all Android artifacts using only Python's standard library."""
import argparse, hashlib, json, pathlib, shutil, subprocess, urllib.request, urllib.error, zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--verify-only',action='store_true')
parser.add_argument('--cache',type=pathlib.Path,default=ROOT/'.android-delivery-cache')
args=parser.parse_args()
manifest=json.loads((ROOT/'docs/android/release-manifest.json').read_text(encoding='utf-8'))
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
if not args.verify_only:
    args.cache.mkdir(parents=True,exist_ok=True)
    for part in manifest['parts']:
        dest=args.cache/part['name']
        if not dest.exists() or dest.stat().st_size!=part['size'] or digest(dest)!=part['sha256']:
            url=f"https://github.com/BaoZhuhan/os-omni/releases/download/{manifest['release']}/{part['name']}"
            temp=dest.with_suffix('.download')
            print('Downloading',part['name'],flush=True)
            try:
                with urllib.request.urlopen(url,timeout=120) as response,temp.open('wb') as out:shutil.copyfileobj(response,out,8*1024*1024)
            except urllib.error.HTTPError as error:
                if error.code not in (401,403,404) or not shutil.which('gh'):raise
                subprocess.run(['gh','release','download',manifest['release'],'--repo','BaoZhuhan/os-omni','--pattern',part['name'],'--dir',str(args.cache),'--clobber'],check=True)
                dest.replace(temp)
            if temp.stat().st_size!=part['size'] or digest(temp)!=part['sha256']:raise RuntimeError('Release asset checksum mismatch')
            temp.replace(dest)
        print('Cache verified:',part['name'],flush=True)
    archive=args.cache/'android-complete.zip'
    with archive.open('wb') as out:
        for part in manifest['parts']:
            with (args.cache/part['name']).open('rb') as src:shutil.copyfileobj(src,out,8*1024*1024)
            print('Joined:',part['name'],flush=True)
    with zipfile.ZipFile(archive) as z:
        for i in z.infolist():
            if not (ROOT/i.filename).resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('Unsafe release path')
        for number,entry in enumerate(z.infolist(),1):
            z.extract(entry,ROOT)
            if number%1000==0:print('Restored files:',number,flush=True)
failures=[]
for number,record in enumerate(manifest['files'],1):
    p=ROOT/record['path']
    if not p.is_file() or p.stat().st_size!=record['size'] or digest(p)!=record['sha256']:failures.append(record['path'])
    if number%1000==0:print('Verified files:',number,flush=True)
for task,record in manifest['final_valid_runs'].items():
    p=ROOT/record['report']
    if not p.is_file():failures.append(task+': missing final result')
    elif json.loads(p.read_text(encoding='utf-8'))['status']!=record['result']:failures.append(task+': verdict mismatch')
if failures:raise SystemExit('Verification failed:\n'+'\n'.join(failures))
print(f"Verified {manifest['total_files']} files and {len(manifest['final_valid_runs'])} final valid runs.")
