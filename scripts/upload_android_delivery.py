"""Resumable GitHub release uploader; server digest must match before skipping."""
import pathlib,subprocess,os,concurrent.futures,time,json,argparse,threading
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--cache',type=pathlib.Path,default=ROOT/'.android-delivery-cache');parser.add_argument('--workers',type=int,default=16);args=parser.parse_args()
manifest_path=ROOT/'docs/android/release-manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'));release=manifest['release'];repo='BaoZhuhan/os-omni'
state_path=args.cache/'upload-status.json';lock=threading.Lock();done={};errors={}
def remote():
    p=subprocess.run(['gh','api',f'repos/{repo}/releases/tags/{release}'],capture_output=True,text=True,check=True,timeout=90)
    return {a['name']:a for a in json.loads(p.stdout)['assets']}
assets=remote()
def matches(part,asset):return asset and asset.get('state')=='uploaded' and asset['size']==part['size'] and asset.get('digest')=='sha256:'+part['sha256']
for part in manifest['parts']:
    if matches(part,assets.get(part['name'])):done[part['name']]=part['sha256']
def save(phase='uploading'):
    with lock:
        state={'phase':phase,'pid':os.getpid(),'updated_at':time.time(),'release':release,'expected_parts':len(manifest['parts']),'completed_parts':len(done),'completed_bytes':sum(p['size'] for p in manifest['parts'] if p['name'] in done),'total_bytes':sum(p['size'] for p in manifest['parts']),'errors':errors}
        t=state_path.with_suffix('.tmp');t.write_text(json.dumps(state,indent=2),encoding='utf-8');t.replace(state_path)
def upload(part):
    p=args.cache/part['name']
    with p.open('rb') as f:actual=__import__('hashlib').file_digest(f,'sha256').hexdigest()
    if p.stat().st_size!=part['size'] or actual!=part['sha256']:raise RuntimeError('Bad local part '+p.name)
    for attempt in range(4):
        try:
            r=subprocess.run(['gh','release','upload',release,str(p),'--repo',repo,'--clobber'],capture_output=True,text=True,timeout=2700)
            if r.returncode==0:
                with lock:done[p.name]=part['sha256'];errors.pop(p.name,None)
                save();print('UPLOADED',p.name,len(done),'/',len(manifest['parts']),flush=True);return
            message=r.stderr[-600:]
        except subprocess.TimeoutExpired:message='Upload exceeded 45 minutes'
        with lock:errors[p.name]=message
        save();print('RETRY',p.name,attempt+1,message,flush=True);time.sleep(5)
    raise RuntimeError('Upload failed '+p.name)
save()
failed=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
    futures={pool.submit(upload,p):p['name'] for p in manifest['parts'] if p['name'] not in done}
    for future in concurrent.futures.as_completed(futures):
        try:future.result()
        except Exception as e:failed.append(str(e))
if failed:
    save('retry_required');raise SystemExit('\n'.join(failed))
assets=remote();bad=[p['name'] for p in manifest['parts'] if not matches(p,assets.get(p['name']))]
if bad:save('remote_verification_failed');raise SystemExit(str(bad))
subprocess.run(['gh','release','upload',release,str(manifest_path),'--repo',repo,'--clobber'],check=True)
(ROOT/'docs/android/remote-assets-verified.json').write_text(json.dumps({'verified_at':time.time(),'parts':len(manifest['parts']),'bytes':sum(p['size'] for p in manifest['parts']),'digest_algorithm':'sha256','all_server_digests_match':True},indent=2),encoding='utf-8')
validation_path=ROOT/'docs/android/delivery-validation.json'
validation=json.loads(validation_path.read_text(encoding='utf-8'))
validation['large_assets_remote_upload']='complete_remote_verified'
validation_path.write_text(json.dumps(validation,indent=2),encoding='utf-8')
save('complete_remote_verified');print('ALL_UPLOADS_COMPLETE',flush=True)
