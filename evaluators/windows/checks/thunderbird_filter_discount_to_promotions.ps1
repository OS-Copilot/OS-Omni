$pyCode = @'
import configparser
import os
import pathlib
import re
import sys

appdata = os.environ.get("APPDATA")
if not appdata:
    print("EVAL_RESULT:FAIL APPDATA is missing")
    sys.exit(0)

profiles_ini = pathlib.Path(appdata) / "Thunderbird" / "profiles.ini"
if not profiles_ini.exists():
    print(f"EVAL_RESULT:FAIL profiles.ini not found: {profiles_ini}")
    sys.exit(0)

cfg = configparser.ConfigParser(interpolation=None, strict=False)
cfg.read(profiles_ini, encoding="utf-8")

profile_section = None
for sec in cfg.sections():
    if sec.startswith("Profile") and cfg.get(sec, "Default", fallback="0") == "1":
        profile_section = sec
        break
if profile_section is None:
    for sec in cfg.sections():
        if sec.startswith("Profile"):
            profile_section = sec
            break
if profile_section is None:
    print("EVAL_RESULT:FAIL no Thunderbird profile section found")
    sys.exit(0)

prof_path = cfg.get(profile_section, "Path", fallback="").strip()
if not prof_path:
    print("EVAL_RESULT:FAIL profile Path is empty")
    sys.exit(0)

is_relative = cfg.get(profile_section, "IsRelative", fallback="1").strip() == "1"
tb_root = pathlib.Path(appdata) / "Thunderbird"
profile_dir = (tb_root / prof_path) if is_relative else pathlib.Path(prof_path)
imap_root = profile_dir / "ImapMail"
if not imap_root.exists():
    print(f"EVAL_RESULT:FAIL ImapMail directory not found: {imap_root}")
    sys.exit(0)

rules_files = sorted(imap_root.rglob("msgFilterRules.dat"))
if not rules_files:
    print(f"EVAL_RESULT:FAIL no msgFilterRules.dat found under: {imap_root}")
    sys.exit(0)

checks = [
    r'enabled\s*=\s*"yes"',
    r'action\s*=\s*"Move to folder"',
    r'actionValue\s*=\s*"mailbox://nobody@Local%20Folders/Promotions"',
    r'condition\s*=\s*"AND\s*\(subject,contains,discount\)"',
]
pattern = re.compile(r'^name="(?P<name>[^"]+)"(?P<body>.*?)(?=^name="|\Z)', re.MULTILINE | re.DOTALL)

matched_path = None
for rules_path in rules_files:
    text = rules_path.read_text(encoding="utf-8", errors="ignore")
    for m in pattern.finditer(text):
        body = m.group("body")
        if all(re.search(c, body, flags=re.IGNORECASE) for c in checks):
            matched_path = rules_path
            break
    if matched_path is not None:
        break

if matched_path is None:
    print("EVAL_RESULT:FAIL expected Thunderbird filter rule not found in any ImapMail msgFilterRules.dat")
    sys.exit(0)

print(f"EVAL_RESULT:PASS expected Thunderbird filter rule found at {matched_path}")
'@

$pyCode | py -3 -W ignore -
