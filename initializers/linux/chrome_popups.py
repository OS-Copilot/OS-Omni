"""Keep Google Chrome's own pop-ups off the Web apps in the Linux guest.

The image ships Chrome 120 (built January 2024). Two of its bubbles cover the page and take
the focus while an agent works:

* "Can't update Chrome": every Chrome process that is not started with
  ``--disable-background-networking`` (the ``launch-*`` app windows, the desktop and dock
  icons, initializers that call ``google-chrome``) finds its build far older than the guest
  clock and offers to reinstall. ``--simulate-outdated-no-au`` with a far-future date sets the
  build date Chrome compares against, so the install never counts as outdated.
* "Save password?" (and the matching address and card prompts) after a sign-in or checkout
  form is submitted. The managed policy below turns these prompts off for every profile.

Every launch path ends in ``/opt/google/chrome/google-chrome``, so the flags are added there,
once, together with ``--hide-crash-restore-bubble`` for the "Restore pages?" bubble that
appears when a snapshot was taken with Chrome running. Both files are root-owned; the script
uses sudo with the configured guest password when the runtime user cannot write them. It is
idempotent and must run before Chrome starts (the managed policy also applies to a running
Chrome, the flags only to processes started afterwards).
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Mapping

CHROME_POLICY_PATH = "/etc/opt/chrome/policies/managed/osomni-web-popups.json"
CHROME_POLICY = {
    "PasswordManagerEnabled": False,
    "PasswordLeakDetectionEnabled": False,
    "AutofillAddressEnabled": False,
    "AutofillCreditCardEnabled": False,
}
CHROME_WRAPPER_PATH = "/opt/google/chrome/google-chrome"
CHROME_WRAPPER_EXEC = 'exec -a "$0" "$HERE/chrome" "$@"'
CHROME_EXTRA_FLAGS = (
    "--simulate-outdated-no-au=Tue, 31 Dec 2099 23:59:59 GMT",
    "--hide-crash-restore-bubble",
)


def chrome_popup_fix_script(
    password: str | None = None,
    *,
    policy_path: str = CHROME_POLICY_PATH,
    wrapper_path: str = CHROME_WRAPPER_PATH,
) -> str:
    """Bash script that installs the policy and the wrapper flags; prints one status line."""

    policy = json.dumps(CHROME_POLICY, indent=2, sort_keys=True) + "\n"
    patched_exec = 'exec -a "$0" "$HERE/chrome" %s "$@"' % " ".join(shlex.quote(flag) for flag in CHROME_EXTRA_FLAGS)
    marker = CHROME_EXTRA_FLAGS[0].split("=", 1)[0]
    return f"""set -u
policy={shlex.quote(policy_path)}
wrapper={shlex.quote(wrapper_path)}
password={shlex.quote(password or "")}
as_root() {{
  # Run directly when the target is writable (root runtime, tests), else through sudo.
  target=$1; shift
  if [ "$(id -u)" = 0 ] || [ -w "$target" ]; then "$@"; return; fi
  if [ -n "$password" ]; then printf '%s\\n' "$password" | sudo -S -p '' "$@"; else sudo -n "$@"; fi
}}
existing() {{ d=$1; while [ ! -e "$d" ]; do d=$(dirname "$d"); done; echo "$d"; }}
policy_tmp=$(mktemp); wrapper_tmp=$(mktemp)
trap 'rm -f "$policy_tmp" "$wrapper_tmp"' EXIT
cat > "$policy_tmp" <<'POLICY'
{policy}POLICY
policy_state=ok
if ! cmp -s "$policy_tmp" "$policy"; then
  dir=$(dirname "$policy")
  [ -d "$dir" ] || as_root "$(existing "$dir")" mkdir -p "$dir"
  as_root "$dir" install -m 0644 "$policy_tmp" "$policy"
  cmp -s "$policy_tmp" "$policy" && policy_state=installed || policy_state=failed
fi
wrapper_state=ok
if [ ! -f "$wrapper" ]; then
  wrapper_state=missing
elif ! grep -qF -- {shlex.quote(marker)} "$wrapper"; then
  if grep -qxF -- {shlex.quote(CHROME_WRAPPER_EXEC)} "$wrapper"; then
    python3 - "$wrapper" "$wrapper_tmp" <<'PY'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\\n")
lines = [{json.dumps(patched_exec)} if line == {json.dumps(CHROME_WRAPPER_EXEC)} else line for line in lines]
open(sys.argv[2], "w", encoding="utf-8").write("\\n".join(lines))
PY
    as_root "$wrapper" cp "$wrapper_tmp" "$wrapper"
    grep -qF -- {shlex.quote(marker)} "$wrapper" && wrapper_state=patched || wrapper_state=failed
  else
    wrapper_state=unexpected
  fi
fi
echo "chrome_popups policy=$policy_state wrapper=$wrapper_state"
case "$policy_state $wrapper_state" in *failed*|*unexpected*) exit 1;; esac
"""


def suppress_chrome_popups(controller: Any, password: str | None = None, *, timeout: int = 60) -> Mapping[str, Any]:
    """Apply :func:`chrome_popup_fix_script` in the guest and return the runtime's result."""

    if controller is None or not hasattr(controller, "run_bash_script"):
        raise RuntimeError("controller.run_bash_script is required")
    return controller.run_bash_script(chrome_popup_fix_script(password), timeout=timeout)
