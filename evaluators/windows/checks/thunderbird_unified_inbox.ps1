
$ErrorActionPreference = "Stop"
$py = @'
import configparser
import json
import os
import pathlib
import sys

appdata = os.environ.get("APPDATA")
profiles_ini = pathlib.Path(appdata) / "Thunderbird" / "profiles.ini"
if not profiles_ini.exists():
    print("EVAL_RESULT:FAIL profiles.ini missing")
    sys.exit(1)

cfg = configparser.ConfigParser(interpolation=None, strict=False)
cfg.read(profiles_ini, encoding="utf-8")
profile = None
for sec in cfg.sections():
    if sec.startswith("Profile") and cfg.get(sec, "Default", fallback="0") == "1":
        profile = sec
        break
if profile is None:
    print("EVAL_RESULT:FAIL default profile missing")
    sys.exit(1)
path = cfg.get(profile, "Path")
profile_dir = pathlib.Path(appdata) / "Thunderbird" / path
xulstore = profile_dir / "xulstore.json"
if not xulstore.exists():
    print("EVAL_RESULT:FAIL xulstore.json missing")
    sys.exit(1)
data = json.loads(xulstore.read_text(encoding="utf-8"))
mode = data.get("chrome://messenger/content/messenger.xhtml", {}).get("folderTree", {}).get("mode")
if "smart" not in str(mode).lower():
    print(f"EVAL_RESULT:FAIL folderTree.mode is not smart: {mode!r}")
    sys.exit(1)
print("EVAL_RESULT:PASS Thunderbird unified inbox smart-folder mode persisted")
'@
$py | py -3 -W ignore -
exit $LASTEXITCODE
