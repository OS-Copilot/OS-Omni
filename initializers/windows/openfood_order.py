"""Prepare OpenFood with a read-only per-run state-write observer.

Chromium's LevelDB commits are delayed and coalesced. They cannot serve as a
complete GUI action history. The observer records successful application
localStorage writes without changing application state or performing actions.
"""
from __future__ import annotations

from pathlib import Path
import uuid

from evaluators.cua_review.initializers.windows.openfood import OpenFoodInitializer
from evaluators.cua_review.initializers.windows.setup import (
    WindowsPreparationError, run_powershell, run_python_json,
)
from evaluators.cua_review.core.init_binding import ReleaseInitializerAdapter


class _ObservedOpenFoodInitializer(OpenFoodInitializer):
    INITIALIZER_ID = 'initializers.windows.openfood_order:OpenFoodOrderInitializer'

    def _prepare(self, controller, params):
        prepared = super()._prepare(controller, params)
        self.run_id = uuid.uuid4().hex
        source = (Path(__file__).parent / 'assets/observe-openfood-order.ps1').read_text(encoding='utf8')
        self.paths = run_python_json(controller, f'''
import pathlib, os, json
root = pathlib.Path(os.environ['TEMP']) / 'os_omni_openfood_order'
root.mkdir(exist_ok=True)
script = root / 'observe.ps1'
script.write_text({source!r}, encoding='utf-8-sig')
trace = root / {self.run_id + '.jsonl'!r}
trace.write_text('', encoding='utf8')
manifest = {{'run_id': {self.run_id!r}, 'trace': str(trace)}}
(root / 'current.json').write_text(json.dumps(manifest), encoding='utf8')
print(json.dumps({{'script': str(script), **manifest}}))
''', timeout=20)
        return prepared + '; created a fresh, run-bound, read-only evidence destination'

    def _launch(self, controller, params):
        # A new instance avoids attaching to stale renderer state or another
        # task's browser debugging endpoint. The snapshot supplies the account.
        output = run_powershell(controller, r'''
$ErrorActionPreference='Stop'
$processes=@(Get-Process -Name openfood -ErrorAction SilentlyContinue)
foreach($p in $processes){[void]$p.CloseMainWindow()}
foreach($p in $processes){if(!$p.WaitForExit(8000)){$p.Kill();$p.WaitForExit()}}
if(Get-NetTCPConnection -LocalPort 4320,9435 -State Listen -ErrorAction SilentlyContinue){throw 'OpenFood backend or observer port is occupied'}
Start-Process 'C:\OS-Omni\Apps\OpenFood\openfood.exe' -ArgumentList '--force-renderer-accessibility','--remote-debugging-port=9435','--remote-debugging-address=127.0.0.1'
''', 30)
        command = r'''
$ErrorActionPreference='Stop'
$manifest=Get-Content (Join-Path $env:TEMP 'os_omni_openfood_order\current.json') -Raw|ConvertFrom-Json
$script=Join-Path $env:TEMP 'os_omni_openfood_order\observe.ps1'
$arguments="-NoProfile -ExecutionPolicy Bypass -File `"$script`" -TracePath `"$($manifest.trace)`" -RunId $($manifest.run_id)"
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $arguments|Out-Null
'''
        run_powershell(controller, command, 15)
        return output + '; started read-only state-write observer'

    def _confirm_started(self, controller, params):
        result = super()._confirm_started(controller, params)
        ready = run_python_json(controller, f'''
import pathlib,json,time
p=pathlib.Path({self.paths['trace']!r})
for _ in range(80):
    error=pathlib.Path(str(p)+'.error')
    ready=pathlib.Path(str(p)+'.ready')
    if error.exists():raise RuntimeError(error.read_text())
    if ready.exists():
        print(ready.read_text());break
    time.sleep(.25)
else:raise RuntimeError('OpenFood observer did not become ready')
''', timeout=25)
        initial = ready.get('initial') or {}
        state = initial.get('state') or {}
        if (state.get('userId') or initial.get('userId')) != 'lucas':
            raise WindowsPreparationError('OpenFood baseline must be signed in as Lucas Lin')
        if state.get('createdOrders') or state.get('cart'):
            raise WindowsPreparationError('OpenFood baseline contains a preexisting cart or created order')
        return result + '; fresh observer is ready and baseline is clean'


class OpenFoodOrderInitializer(ReleaseInitializerAdapter):
    """Expose the reviewed-family initializer through OS-Omni's runner contract."""

    def __init__(self):
        super().__init__(_ObservedOpenFoodInitializer())
