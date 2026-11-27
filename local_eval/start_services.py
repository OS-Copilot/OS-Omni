"""Start missing local benchmark services without touching machine settings."""
import json
import os
import sys
import shutil
import tempfile
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

def healthy(url):
    try:
        with urllib.request.urlopen(url,timeout=3) as response:
            return response.status==200 and bool(json.load(response))
    except Exception:
        return False

def ensure_services():
    java = os.environ.get('JAVA_EXE') or shutil.which('java')
    if not java:
        raise RuntimeError('Install JDK 25 and put java on PATH, or set JAVA_EXE')
    temp_dir = Path(tempfile.gettempdir())/'os-omni'
    temp_dir.mkdir(exist_ok=True)
    definitions=[
        ('backend','http://127.0.0.1:4321/health',[sys.executable,'-X','utf8','-u','local_eval/opendriver_backend.py']),
        ('greenmail','http://127.0.0.1:8081/api/service/readiness',[
            java,
            '-Djava.net.preferIPv4Stack=true',f'-Djava.io.tmpdir={temp_dir}',f'-Djdk.net.unixdomain.tmpdir={temp_dir}',
            '-Dgreenmail.setup.test.smtp','-Dgreenmail.setup.test.imap','-Dgreenmail.hostname=127.0.0.1',
            '-Dgreenmail.api.hostname=127.0.0.1','-Dgreenmail.api.port=8081',
            '-Dgreenmail.users=benchsender@example.test:benchpass,benchrecv@example.test:benchpass,benchchat@example.test:benchpass',
            '-Dgreenmail.users.login=email','-jar',str(ROOT/'.tools/greenmail/greenmail-standalone-2.1.8.jar')]),
    ]
    for name,url,command in definitions:
        if healthy(url):
            continue
        with (ROOT/f'local_eval/{name}.stdout.log').open('a') as output,(ROOT/f'local_eval/{name}.stderr.log').open('a') as errors:
            process=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline and process.poll() is None:
            if healthy(url):break
            time.sleep(1)
        else:
            raise RuntimeError(f'{name} service did not become ready; see its stderr log')

if __name__=='__main__':
    ensure_services()
    print('OpenDriver and GreenMail services ready')
