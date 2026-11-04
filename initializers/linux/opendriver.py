"""OpenDriver (Electron + Flutter web) initializer for the Linux image."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import InitResult, InitStatus
from initializers.linux.setup import DesktopSetupInitializer


# The Flutter web build loads CanvasKit from www.gstatic.com and the Roboto text font
# from fonts.gstatic.com. The guest clock stays at the snapshot date (Sep 2026), before
# the notBefore date of Google's current certificates, so both requests fail with
# ERR_CERT_DATE_INVALID and the window stays blank. The build ships CanvasKit under
# public/canvaskit/ and the image has Roboto installed: point the Flutter loader at the
# local CanvasKit and at a local font base URL that serves the guest's Roboto under the
# file name the engine requests. Nothing else in the app reaches Google.
OFFLINE_ASSETS_PATCH = r"""set -e
public=/home/user/Applications/opendriver/public
bootstrap="$public/flutter_bootstrap.js"
roboto_rel=osomni-fonts/roboto/v32/KFOmCnqEu92Fr1Me4GZLCzYlKw.woff2
test -f "$public/canvaskit/canvaskit.js" -a -f "$public/canvaskit/canvaskit.wasm"
roboto=""
for candidate in "$(fc-match -f '%{file}' 'Roboto:style=Regular' 2>/dev/null || true)" \
    /usr/share/fonts/font23341/Roboto-Regular.ttf /usr/share/fonts/Roboto/Roboto-Regular-14.ttf; do
  if [ -f "$candidate" ] && fc-scan -f '%{family}|%{style}\n' "$candidate" 2>/dev/null | grep -q '^Roboto.*|Regular'; then
    roboto="$candidate"; break
  fi
done
if [ -z "$roboto" ]; then echo "no Roboto Regular font in the guest" >&2; exit 1; fi
mkdir -p "$(dirname "$public/$roboto_rel")"
cp "$roboto" "$public/$roboto_rel"
python3 - "$bootstrap" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
config = 'config: { canvasKitBaseUrl: "canvaskit/", fontFallbackBaseUrl: "osomni-fonts/" },'
if config in source:
    print("already patched")
elif source.count("_flutter.loader.load({") == 1:
    path.write_text(source.replace("_flutter.loader.load({", "_flutter.loader.load({\n  " + config, 1), encoding="utf-8")
    print("patched")
else:
    raise SystemExit("OpenDriver flutter_bootstrap.js loader call not found")
PY
# A service worker registered before the patch would keep serving the old bootstrap.
rm -rf "/home/user/.config/opendriver/Service Worker"
"""


class OpenDriverInitializer(DesktopSetupInitializer):
    """Serve OpenDriver's web assets locally, then run the task's setup steps."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")
        try:
            patch = controller.run_bash_script(OFFLINE_ASSETS_PATCH, timeout=60)
        except Exception as exc:  # noqa: BLE001 - reported as an initializer error
            return InitResult(status=InitStatus.ERROR, message=f"OpenDriver offline-assets patch failed: {exc}")
        if int(patch.get("returncode", patch.get("return_code", 1)) or 0) != 0:
            return InitResult(status=InitStatus.ERROR, message=f"OpenDriver offline-assets patch failed: {patch}")
        result = super().initialize(context)
        metadata = dict(result.metadata)
        metadata["offline_assets_patch"] = str(patch.get("output") or "").strip()
        return InitResult(status=result.status, message=result.message, metadata=metadata)
