from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relpath: str):
    return yaml.safe_load((ROOT / relpath).read_text(encoding="utf-8"))


def dump_yaml(relpath: str, data) -> None:
    (ROOT / relpath).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def thunderbird_profile_init() -> str:
    return r'''
$ErrorActionPreference = "Stop"
Get-Process thunderbird -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 400

$tbRoot = Join-Path $env:APPDATA "Thunderbird"
if (Test-Path $tbRoot) { Remove-Item -LiteralPath $tbRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tbRoot | Out-Null
$profileLeaf = "t5q2a5hp.default-release"
$profileDir = Join-Path $tbRoot $profileLeaf
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $profileDir "ImapMail\outlook.office365.com") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $profileDir "Mail\Local Folders") | Out-Null

@"
[Profile0]
Name=default-release
IsRelative=1
Path=$profileLeaf
Default=1

[General]
StartWithLastProfile=1
Version=2
"@ | Set-Content -LiteralPath (Join-Path $tbRoot "profiles.ini") -Encoding ASCII

@(
  'user_pref("app.update.auto", false);',
  'user_pref("app.update.enabled", false);',
  'user_pref("browser.shell.checkDefaultBrowser", false);',
  'user_pref("mail.account.account1.identities", "id1");',
  'user_pref("mail.account.account1.server", "server1");',
  'user_pref("mail.account.account2.server", "server2");',
  'user_pref("mail.account.lastKey", 2);',
  'user_pref("mail.accountmanager.accounts", "account1,account2");',
  'user_pref("mail.accountmanager.defaultaccount", "account1");',
  'user_pref("mail.accountmanager.localfoldersserver", "server2");',
  'user_pref("mail.identity.id1.fullName", "Helloworld");',
  'user_pref("mail.identity.id1.useremail", "Helloworld@outlook.com");',
  'user_pref("mail.identity.id1.valid", true);',
  'user_pref("mail.root.imap-rel", "[ProfD]ImapMail");',
  'user_pref("mail.root.none-rel", "[ProfD]Mail");',
  'user_pref("mail.server.server1.check_new_mail", false);',
  'user_pref("mail.server.server1.directory-rel", "[ProfD]ImapMail/outlook.office365.com");',
  'user_pref("mail.server.server1.hostname", "outlook.office365.com");',
  'user_pref("mail.server.server1.login_at_startup", false);',
  'user_pref("mail.server.server1.name", "Helloworld@outlook.com");',
  'user_pref("mail.server.server1.storeContractID", "@mozilla.org/msgstore/berkeleystore;1");',
  'user_pref("mail.server.server1.type", "imap");',
  'user_pref("mail.server.server1.userName", "Helloworld@outlook.com");',
  'user_pref("mail.server.server2.check_new_mail", false);',
  'user_pref("mail.server.server2.directory-rel", "[ProfD]Mail/Local Folders");',
  'user_pref("mail.server.server2.hostname", "Local Folders");',
  'user_pref("mail.server.server2.name", "Local Folders");',
  'user_pref("mail.server.server2.storeContractID", "@mozilla.org/msgstore/berkeleystore;1");',
  'user_pref("mail.server.server2.type", "none");',
  'user_pref("mail.server.server2.userName", "nobody");',
  'user_pref("mailnews.start_page.enabled", false);'
) | Set-Content -LiteralPath (Join-Path $profileDir "prefs.js") -Encoding ASCII

$inbox = Join-Path $profileDir "ImapMail\outlook.office365.com\Inbox"
@"
From - Mon Apr 14 09:00:00 2025
X-Mozilla-Status: 0001
X-Mozilla-Status2: 00000000
Message-ID: <promo-001@example.test>
Date: Mon, 14 Apr 2025 09:00:00 -0500
From: Store <store@example.test>
To: Helloworld@outlook.com
Subject: spring discount code
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Discount offer for testing filters.
"@ | Set-Content -LiteralPath $inbox -Encoding ASCII

Start-Process -FilePath "thunderbird.exe" -ArgumentList @("-profile", $profileDir, "-mail") | Out-Null
Start-Sleep -Seconds 5
Write-Output "INIT_OK:PROFILE=$profileDir"
'''


def unified_check() -> str:
    return r'''
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
'''


def oracle_filter_script() -> str:
    return r'''
$ErrorActionPreference = "Stop"
$profileDir = Join-Path $env:APPDATA "Thunderbird\t5q2a5hp.default-release"
$imapDir = Join-Path $profileDir "ImapMail\outlook.office365.com"
New-Item -ItemType Directory -Force -Path $imapDir | Out-Null
$rules = @'
version="9"
logging="no"
name="Move discount to Promotions"
enabled="yes"
type="17"
action="Move to folder"
actionValue="mailbox://nobody@Local%20Folders/Promotions"
condition="AND (subject,contains,discount)"
'@
Set-Content -LiteralPath (Join-Path $imapDir "msgFilterRules.dat") -Value $rules -Encoding ASCII
New-Item -ItemType Directory -Force -Path (Join-Path $profileDir "Mail\Local Folders") | Out-Null
Set-Content -LiteralPath (Join-Path $profileDir "Mail\Local Folders\Promotions") -Value "" -Encoding ASCII
Write-Output "oracle filter written"
'''


def oracle_unified_script() -> str:
    return r'''
$ErrorActionPreference = "Stop"
$profileDir = Join-Path $env:APPDATA "Thunderbird\t5q2a5hp.default-release"
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
$xulstore = Join-Path $profileDir "xulstore.json"
$json = @{
  "chrome://messenger/content/messenger.xhtml" = @{
    "folderTree" = @{
      "mode" = "smart"
    }
  }
} | ConvertTo-Json -Depth 10
Set-Content -LiteralPath $xulstore -Value $json -Encoding UTF8
Write-Output "oracle unified inbox written"
'''


def update_tasks() -> None:
    filter_task = load_yaml("tasks/windows/thunderbird_collect_st_club_progress.yaml")
    filter_task["instruction"] = (
        'In Thunderbird, create a local folder called "Promotions" and create an enabled message filter that moves Inbox '
        'emails whose subject contains "discount" to the Promotions folder. Save the filter so it persists after the Message Filters window is closed.'
    )
    filter_task["init"]["params"]["steps"] = [
        {"type": "run_powershell", "script": thunderbird_profile_init(), "timeout": 180},
        {"type": "wait", "ms": 6000},
    ]
    filter_task["evaluation"]["params"] = {
        "check_id": "thunderbird_filter_discount_to_promotions",
        "timeout": 120,
        "stdout_contains": "EVAL_RESULT:PASS",
    }
    md = filter_task["metadata"]
    md["tags"] = ["thunderbird", "email", "filter", "local-folder", "hard", "single_app", "evaluator_backed"]
    md["app_name"] = "thunderbird"
    md.pop("app", None)
    md["human_steps"] = 68
    md["description"] = "Linux-aligned Thunderbird task: create a Promotions folder and a persistent subject-based discount filter."
    md["evaluation_standard"] = "msgFilterRules.dat must contain an enabled subject-contains-discount rule moving mail to Local Folders/Promotions"
    md["alignment_status"] = "direct"
    dump_yaml("tasks/windows/thunderbird_collect_st_club_progress.yaml", filter_task)

    unified_task = load_yaml("tasks/windows/thunderbird_send_email_exact_body.yaml")
    unified_task["instruction"] = (
        "In Thunderbird, switch the folder pane to the unified inbox view, expand Smart Folders if needed, and click the unified Inbox "
        "so the combined inbox is the active landing view. Save/leave the view so it persists next time Thunderbird opens."
    )
    unified_task["init"]["params"]["steps"] = [
        {"type": "run_powershell", "script": thunderbird_profile_init(), "timeout": 180},
        {"type": "wait", "ms": 6000},
    ]
    unified_task["evaluation"]["params"] = {
        "check_id": "thunderbird_unified_inbox",
        "timeout": 120,
        "stdout_contains": "EVAL_RESULT:PASS",
    }
    md = unified_task["metadata"]
    md["tags"] = ["thunderbird", "email", "unified-inbox", "smart-folders", "hard", "single_app", "evaluator_backed"]
    md["human_steps"] = 64
    md["description"] = "Linux-aligned Thunderbird task: switch to unified inbox view and persist Smart Folders mode."
    md["evaluation_standard"] = "Thunderbird xulstore.json must persist folderTree.mode as smart"
    md["alignment_status"] = "direct"
    dump_yaml("tasks/windows/thunderbird_send_email_exact_body.yaml", unified_task)


def write_checks() -> None:
    (ROOT / "evaluators/windows/checks/thunderbird_unified_inbox.ps1").write_text(unified_check(), encoding="utf-8")


def patch_oracle() -> None:
    path = ROOT / "mine/oracle_agent/generate_windows_oracle_agents.py"
    text = path.read_text(encoding="utf-8")
    replacements = {
        "windows.thunderbird.collect_st_club_progress": oracle_filter_script(),
        "windows.thunderbird.send_email_exact_body": oracle_unified_script(),
    }
    for task_id, script in replacements.items():
        marker = f'        "{task_id}": ['
        start = text.find(marker)
        if start < 0:
            continue
        depth_start = text.index("[", start)
        i = depth_start
        depth = 0
        in_string = False
        quote = ""
        escape = False
        while i < len(text):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    in_string = False
            else:
                if ch in "'\"":
                    in_string = True
                    quote = ch
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            i += 1
        else:
            raise RuntimeError(f"could not find end for {task_id}")
        new_block = (
            f'        "{task_id}": [\n'
            f'            {{"type": "oracle_run_powershell", "script": {script!r}, "timeout": 60}},\n'
            f'            {{"type": "success", "message": "Thunderbird Linux-aligned oracle state written."}},\n'
            f"        ]"
        )
        text = text[:start] + new_block + text[end:]
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    update_tasks()
    write_checks()
    patch_oracle()
    print("upgraded Windows Thunderbird tasks to direct Linux-aligned tasks")
