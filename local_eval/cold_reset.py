"""Reset the VM from downloaded disks when live snapshot restores are unstable."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile
import psutil

ROOT = Path(__file__).resolve().parents[1]
AVD = Path(os.environ.get('ANDROID_AVD_HOME', str(Path.home()/'.android/avd')))/'AndroidWorldAvd.avd'
SDK = Path(os.environ.get('ANDROID_SDK_ROOT', os.environ.get('ANDROID_HOME', str(Path.home()/'AppData/Local/Android/Sdk'))))
DISKS = ('userdata-qemu.img', 'userdata-qemu.img.qcow2', 'cache.img', 'cache.img.qcow2', 'encryptionkey.img', 'encryptionkey.img.qcow2')

def cold_reset(run_dir, gpu="swiftshader_indirect"):
    if gpu not in {"swiftshader_indirect", "angle_indirect", "host"}:
        raise ValueError("Unsupported audited GPU backend")
    print('VM_RESET validating original disk baseline', flush=True)
    baseline = ROOT/'local_eval/vm-original-disks'
    baseline.mkdir(exist_ok=True)
    archive = Path(os.environ.get('OS_OMNI_VM_ARCHIVE', str(Path.home()/'Downloads/OS-Omni-VM/android/v2/AndroidWorldAvd_v2_20260625.zip')))
    if not archive.exists() and not all((baseline/name).is_file() for name in DISKS):
        raise RuntimeError('Restore Android release assets or set OS_OMNI_VM_ARCHIVE before running')
    if archive.exists():
      with zipfile.ZipFile(archive) as source:
        for name in DISKS:
            info = source.getinfo('AndroidWorldAvd.avd/'+name)
            target = baseline/name
            if not target.exists() or target.stat().st_size != info.file_size:
                temporary = target.with_suffix(target.suffix+'.part')
                with source.open(info) as incoming, temporary.open('wb') as output:
                    shutil.copyfileobj(incoming, output, 8*1024*1024)
                temporary.replace(target)
    # Restrict shutdown to this task's named AVD; preserve other virtual machines.
    processes = []
    for process in psutil.process_iter(['name','cmdline']):
        try:
            if process.info['name'] in ('emulator.exe','qemu-system-x86_64.exe') and 'AndroidWorldAvd' in process.info['cmdline']:
                processes.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        subprocess.run([str(SDK/'platform-tools/adb.exe'),'-s','emulator-5582','emu','kill'],capture_output=True,timeout=8)
    except subprocess.TimeoutExpired:
        pass
    _, remaining = psutil.wait_procs(processes,timeout=8)
    for process in remaining:
        try: process.kill()
        except psutil.NoSuchProcess: pass
    _, still_running = psutil.wait_procs(remaining,timeout=8)
    if still_running:
        raise RuntimeError('Cannot reset disks while the benchmark emulator is still running')
    print('VM_RESET copying pristine disks', flush=True)
    for name in DISKS:
        shutil.copyfile(baseline/name, AVD/name)
    with (ROOT/'local_eval/emulator-cold.stdout.log').open('w') as output, (ROOT/'local_eval/emulator-cold.stderr.log').open('w') as errors:
        process = subprocess.Popen([str(SDK/'emulator/emulator.exe'),'-avd','AndroidWorldAvd','-port','5582','-no-snapshot-load','-no-snapshot-save','-gpu',gpu,'-feature','-Vulkan'],stdout=output,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW)
    Path(run_dir,'vm-reset-provenance.json').write_text(json.dumps({'method':'cold_boot_original_downloaded_disks','archive':str(archive),'disks':list(DISKS),'gpu':gpu,'emulator_pid':process.pid,'reason':'Repeated live snapshot restores caused Android service and shared-storage failures'},indent=2),encoding='utf-8')
    print('VM_RESET emulator started', process.pid, flush=True)
    time.sleep(15)
