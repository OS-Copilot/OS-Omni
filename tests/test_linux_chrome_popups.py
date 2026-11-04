import json
import subprocess

from initializers.linux.chrome_popups import CHROME_EXTRA_FLAGS, CHROME_POLICY, chrome_popup_fix_script

WRAPPER = '#!/bin/bash\nHERE=/opt/google/chrome\n# Note: exec -a below is a bashism.\nexec -a "$0" "$HERE/chrome" "$@"\n'


def _run(tmp_path, wrapper_text):
    wrapper = tmp_path / "google-chrome"
    if wrapper_text is not None and not wrapper.exists():
        wrapper.write_text(wrapper_text)
        wrapper.chmod(0o755)
    policy = tmp_path / "policies" / "managed" / "osomni-web-popups.json"
    script = chrome_popup_fix_script(None, policy_path=str(policy), wrapper_path=str(wrapper))
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    return result, policy, wrapper


def test_fix_installs_policy_and_wrapper_flags_once(tmp_path):
    first, policy, wrapper = _run(tmp_path, WRAPPER)
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == "chrome_popups policy=installed wrapper=patched"
    assert json.loads(policy.read_text()) == CHROME_POLICY
    exec_line = wrapper.read_text().splitlines()[-1]
    assert all(flag in exec_line for flag in CHROME_EXTRA_FLAGS)
    assert exec_line.endswith('"$@"') and wrapper.stat().st_mode & 0o111

    second, _, _ = _run(tmp_path, WRAPPER)
    assert second.returncode == 0
    assert second.stdout.strip() == "chrome_popups policy=ok wrapper=ok"
    assert wrapper.read_text().splitlines()[-1] == exec_line


def test_fix_reports_an_unknown_wrapper_instead_of_editing_it(tmp_path):
    result, _, wrapper = _run(tmp_path, '#!/bin/bash\nexec /opt/google/chrome/chrome "$@"\n')
    assert result.returncode == 1
    assert "wrapper=unexpected" in result.stdout
    assert "simulate-outdated" not in wrapper.read_text()
