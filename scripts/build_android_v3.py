import hashlib,json,os,shutil,subprocess,time,zipfile,traceback,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
SDK=Path(os.environ['LOCALAPPDATA'])/'Android/Sdk'
STAGE=BASE/'hf-android-v3'
OUT=STAGE/'android_V3'
AVD=Path.home()/'.android/avd/OSOmniAndroidV3Builder.avd'
ADB=SDK/'platform-tools/adb.exe'
STATE=STAGE/'build-status.json'
def state(phase,**kw):
    STAGE.mkdir(exist_ok=True); STATE.write_text(json.dumps(dict(phase=phase,pid=os.getpid(),updated_at=time.time(),**kw),indent=2),encoding='utf-8'); print(phase,flush=True)
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def adb(*args,check=True):
    p=subprocess.run([str(ADB),'-s','emulator-5584',*args],capture_output=True,text=True,timeout=240)
    if check and p.returncode:raise RuntimeError('ADB failed: '+str(args)+' '+p.stderr)
    return p.stdout.strip()
def main():
    resume='--resume-builder' in sys.argv
    if AVD.exists() and not resume:raise RuntimeError('Builder directory already exists; inspect rather than overwrite')
    state('copying_pristine_v2' if not resume else 'resuming_builder'); AVD.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
    baseline=ROOT/'local_eval/vm-original-disks'
    inventory=json.loads((ROOT/'docs/android/external-vm-assets.json').read_text(encoding='utf-8'))
    for item in inventory['files']:
        if not resume:
            src=ROOT/item['path']; assert digest(src)==item['sha256']; shutil.copyfile(src,AVD/src.name)
    archive=Path.home()/'Downloads/OS-Omni-VM/android/v2/AndroidWorldAvd_v2_20260625.zip'
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if item.filename.startswith('AndroidWorldAvd.avd/') and item.file_size<100000:
                rel=Path(item.filename).relative_to('AndroidWorldAvd.avd')
                if item.is_dir():continue
                dest=AVD/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(item))
    config=(AVD/'config.ini').read_text().replace('AndroidWorldAvd','OSOmniAndroidV3Builder')
    (AVD/'config.ini').write_text(config,encoding='utf-8')
    AVD.with_suffix('.ini').write_text('avd.ini.encoding=UTF-8\npath='+str(AVD)+'\npath.rel=avd/OSOmniAndroidV3Builder.avd\ntarget=android-33\n',encoding='utf-8')
    log=(STAGE/'emulator-build.log').open('w',encoding='utf-8')
    emu=subprocess.Popen([str(SDK/'emulator/emulator.exe'),'-avd','OSOmniAndroidV3Builder','-port','5584','-no-window','-no-audio','-no-snapshot-load','-no-snapshot-save','-gpu','host','-feature','-Vulkan'],stdout=log,stderr=subprocess.STDOUT)
    try:
        state('booting',emulator_pid=emu.pid)
        deadline=time.time()+300
        while time.time()<deadline:
            if emu.poll() is not None:raise RuntimeError('Builder emulator exited; inspect emulator-build.log')
            if adb('shell','getprop','sys.boot_completed',check=False)=='1':break
            time.sleep(5)
        else:raise RuntimeError('Builder boot timeout')
        state('installing_repairs',emulator_pid=emu.pid)
        for pkg,name in [('com.killt.openfood','openfood-events-v1'),('com.killt.opennavigation','opennavigation-records-v1')]:
            apk=ROOT/'local_eval/apks'/f'{name}.apk'; meta=json.loads(apk.with_suffix('.json').read_text())
            assert digest(apk)==meta['patched_sha256']
            adb('uninstall',pkg,check=False)
            assert 'Success' in adb('install',str(apk))
            remote=adb('shell','pm','path',pkg).split('package:')[-1].strip()
            assert adb('shell','sha256sum',remote).split()[0]==meta['patched_sha256']
        for pkg in ['com.killt.opennote','com.killt.opentwitter','com.killt.openbank','com.killt.openshop']:
            assert 'Success' in adb('shell','pm','clear',pkg)
        adb('shell','mkdir','-p','/sdcard/OSOmniFixtures/author-photo-v2')
        assets=ROOT/'local_eval/benchmark-v2/assets'
        fixtures=[]
        for name in ['indoor-cooking-v2.jpg','outdoor-cooking-v2.jpg']:
            src=assets/name; remote='/sdcard/OSOmniFixtures/author-photo-v2/'+name
            adb('push',str(src),remote); assert adb('shell','sha256sum',remote).split()[0]==digest(src)
            fixtures.append(dict(path=remote,sha256=digest(src)))
        # This new builder is disposable. Remove old image exports only here.
        adb('shell','rm','-f','/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_*.jpg')
        adb('shell','input','keyevent','KEYCODE_HOME')
        validation=dict(android_api=adb('shell','getprop','ro.build.version.sdk'),abi=adb('shell','getprop','ro.product.cpu.abi'),fixtures=fixtures,installed_repairs=['openfood-events-v1','opennavigation-records-v1.1'],task_specific_initialization='Required via included host code; never bake completed task state',ds_rerun=False)
        assert validation['android_api']=='33' and validation['abi']=='x86_64'
        adb('shell','sync'); adb('emu','kill');emu.wait(timeout=90)
        state('cold_boot_validation')
        emu=subprocess.Popen([str(SDK/'emulator/emulator.exe'),'-avd','OSOmniAndroidV3Builder','-port','5584','-no-window','-no-audio','-no-snapshot-load','-no-snapshot-save','-gpu','host','-feature','-Vulkan'],stdout=log,stderr=subprocess.STDOUT)
        deadline=time.time()+300
        while time.time()<deadline:
            if adb('shell','getprop','sys.boot_completed',check=False)=='1':break
            time.sleep(5)
        else:raise RuntimeError('Cold boot validation timeout')
        for pkg in ['com.killt.openfood','com.killt.opennavigation']:assert adb('shell','pm','path',pkg).startswith('package:')
        validation['cold_boot_verified']=True
        adb('shell','sync');adb('emu','kill');emu.wait(timeout=90)
        log.close();(OUT/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
        state('packaging')
        payload=STAGE/'payload'; target=payload/'AndroidWorldAvd.avd';target.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'scripts/install_android_v3.py',payload/'install_android_v3.py')
        for name in [Path(x['path']).name for x in inventory['files']]+['config.ini']:
            shutil.copyfile(AVD/name,target/name)
        (target/'config.ini').write_text(config.replace('OSOmniAndroidV3Builder','AndroidWorldAvd'),encoding='utf-8')
        (payload/'AndroidWorldAvd.ini').write_text('avd.ini.encoding=UTF-8\npath.rel=avd/AndroidWorldAvd.avd\ntarget=android-33\n',encoding='utf-8')
        # Include all Android reconstruction host sources/assets, omit evidence and disks.
        def ignore(directory,names):return [n for n in names if n in {'runs','queue','vm-original-disks','__pycache__','bootstrap','apks','.runtime','.git'} or n.endswith('.pyc')]
        shutil.copytree(ROOT/'local_eval',payload/'host/local_eval',ignore=ignore,dirs_exist_ok=True)
        shutil.copytree(ROOT/'osomni',payload/'host/osomni') if (ROOT/'osomni').exists() else None
        for folder in ['core','configs','evaluators','executions','initializers','tasks','tools','scripts']:
            shutil.copytree(ROOT/folder,payload/'host'/folder,dirs_exist_ok=True,ignore=ignore)
        shutil.copytree(ROOT/'platforms/android',payload/'host/platforms/android',dirs_exist_ok=True,ignore=ignore)
        shutil.copytree(ROOT/'.tools/greenmail',payload/'host/.tools/greenmail',dirs_exist_ok=True)
        shutil.copytree(ROOT/'docs/android',payload/'host/docs/android',dirs_exist_ok=True)
        for name in ['pyproject.toml','README.md','LICENSE']:
            if (ROOT/name).is_file():shutil.copyfile(ROOT/name,payload/'host'/name)
        for name in ['openfood-events-v1','opennavigation-records-v1']:
            dest=payload/'host/local_eval/apks';dest.mkdir(exist_ok=True)
            for ext in ['.apk','.json']:shutil.copyfile(ROOT/'local_eval/apks'/f'{name}{ext}',dest/f'{name}{ext}')
        (OUT/'README.md').write_text('# android_V3\n\nAuthor rebuilt Android OS-Omni image. Based on AndroidWorldAvd v2 (20260625), API33 Google APIs x86_64. Includes patched Food/Navigation apps and generated Cooking assets. No DeepSeek task completion state.\n\nInstall the Android SDK system image `system-images;android-33;google_apis;x86_64`. Extract AndroidWorldAvd.avd into your AVD directory and register an absolute path in AndroidWorldAvd.ini for your platform. The included host/local_eval contains task initializers, verifiers and author photo fixtures. Task-specific initialization and external OpenDriver/Greenmail services remain required; follow GitHub docs/android/HANDOVER.md. The original cold_reset.py uses the v2 disk baseline: configure a separate V3 baseline before evaluating V3; do not overwrite historical evaluation evidence.\n\nEvaluation evidence: https://github.com/BaoZhuhan/os-omni (48 tasks, 7 PASS / 41 FAIL; mixed author photo v2 and retained 46 results). This image is a new delivery, not a newly measured score.\n',encoding='utf-8')
        archive_out=OUT/'android_V3.zip'
        with zipfile.ZipFile(archive_out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
            for p in sorted(payload.rglob('*')):
                rel=p.relative_to(payload).as_posix()
                if rel.startswith('host/platforms/') and not rel.startswith('host/platforms/android/'):continue
                if p.is_file():z.write(p,rel)
        with zipfile.ZipFile(archive_out) as z:assert z.testzip() is None
        manifest=dict(version='android_V3',filename=archive_out.name,size=archive_out.stat().st_size,sha256=digest(archive_out),source_v2_sha256='32eac37f815ffa5c205c1ad53279e24cf8eef6d7cd0871ab188cf0ac28df656f',validation=validation)
        (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        state('ready_to_upload',manifest=manifest)
    finally:
        if emu.poll() is None:
            adb('emu','kill',check=False)
            try:emu.wait(timeout=60)
            except subprocess.TimeoutExpired:emu.terminate()
if __name__=='__main__':
    try:main()
    except Exception as e:state('failed',error=str(e));traceback.print_exc();raise
