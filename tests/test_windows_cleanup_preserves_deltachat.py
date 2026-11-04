"""Exercise production profile cleanup against disposable Windows profiles."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell profile cleanup')
def test_cleanup_preserves_seeded_deltachat_but_clears_other_app_state(tmp_path):
    script = (Path(__file__).resolve().parents[1] /
              'platforms/windows/vm/setup/cleanup-generic-state.ps1').read_text()
    function = script[script.index('function Remove-IfExists {'):
                      script.index('function Clear-DirectoryContents {')]
    block = script[script.index('$appStatePaths = @('):
                   script.index('Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\\Temp"')]
    roaming, local, home = [tmp_path / name for name in ('Roaming', 'Local', 'User')]
    protected = {
        local / 'DeltaChat/accounts/account/dc.db': b'database sentinel',
        local / 'DeltaChat/accounts/account/dc.db-blobs/attachment.png': b'attachment',
        local / 'DeltaChat/accounts/accounts.toml': b'account config',
        roaming / 'DeltaChat/config.json': b'ui config',
    }
    for path, content in protected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    removable = roaming / 'draw.io/stale-state.json'
    removable.parent.mkdir(parents=True)
    removable.write_text('stale')
    env = {**os.environ, 'APPDATA': str(roaming), 'LOCALAPPDATA': str(local),
           'USERPROFILE': str(home)}
    result = subprocess.run([shutil.which('powershell.exe'), '-NoProfile',
                             '-NonInteractive', '-Command',
                             '$ErrorActionPreference="Stop"\n' + function + block],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not removable.exists(), 'Production cleanup loop did not execute'
    assert all(path.read_bytes() == data for path, data in protected.items())
