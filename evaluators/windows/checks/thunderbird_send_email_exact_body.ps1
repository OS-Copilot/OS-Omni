$pyCode = @'
import configparser
import os
import pathlib
import re
import sys
import time

EXPECTED_TO = "anonym-x2026@outlook.com"
EXPECTED_FROM = "helloworld@outlook.com"
EXPECTED_SUBJECT = "Weekly Meeting Plan"
EXPECTED_BODY_LINES = ["Hi,", "When do we meet this week?", "Best,", "Ben"]
FOLLOWUP_SUBJECT = "Weekly Meeting Follow-up"
FOLLOWUP_BODY_LINES = ["Please confirm by Thursday."]
AGENDA_SUBJECT = "Weekly Meeting Agenda"
AGENDA_BODY_LINES = ["Agenda:", "1. Timeline review", "2. Open risks"]
WAIT_TIMEOUT_SECONDS = 30

appdata = os.environ.get("APPDATA")
if not appdata:
    print("EVAL_RESULT:FAIL APPDATA is missing")
    sys.exit(0)

smtp_log_dir = pathlib.Path(r"C:\Users\User\fake_smtp_messages")
if not smtp_log_dir.exists():
    print(f"EVAL_RESULT:FAIL fake SMTP log directory not found: {smtp_log_dir}")
    sys.exit(0)

tb_root = pathlib.Path(appdata) / "Thunderbird"
profiles_ini = tb_root / "profiles.ini"
if not profiles_ini.exists():
    print(f"EVAL_RESULT:FAIL profiles.ini not found: {profiles_ini}")
    sys.exit(0)

cfg = configparser.ConfigParser(interpolation=None, strict=False)
cfg.read(profiles_ini, encoding="utf-8")

profile_section = None
for sec in cfg.sections():
    if sec.startswith("Profile") and cfg.get(sec, "Default", fallback="0").strip() == "1":
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
profile_dir = (tb_root / prof_path) if is_relative else pathlib.Path(prof_path)
if not profile_dir.exists():
    print(f"EVAL_RESULT:FAIL resolved profile directory does not exist: {profile_dir}")
    sys.exit(0)

local_folders = profile_dir / "Mail" / "Local Folders"
if not local_folders.exists():
    print(f"EVAL_RESULT:FAIL Local Folders directory not found: {local_folders}")
    sys.exit(0)

sent_path = local_folders / "Sent"
drafts_path = local_folders / "Drafts"
unsent_path = local_folders / "Unsent Messages"

if not sent_path.exists():
    print(f"EVAL_RESULT:FAIL Sent mailbox not found: {sent_path}")
    sys.exit(0)

def split_mbox(raw_text: str):
    parts = re.split(r'^From - .*$', raw_text, flags=re.MULTILINE)
    return [part for part in parts if part.strip()]

def header_value(message: str, name: str) -> str:
    match = re.search(rf'^{re.escape(name)}:\s*(.+)$', message, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""

def normalize_body(message: str) -> str:
    if "\r\n\r\n" in message:
        body = message.split("\r\n\r\n", 1)[1]
    elif "\n\n" in message:
        body = message.split("\n\n", 1)[1]
    else:
        body = ""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"\n+$", "", body)
    return body

def semantic_body_lines(raw_body: str):
    raw_body = raw_body.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw_body.split("\n")]
    return [line for line in lines if line]

def mailbox_contains_semantic_body(raw_text: str) -> bool:
    for message in split_mbox(raw_text):
        if semantic_body_lines(normalize_body(message)) == EXPECTED_BODY_LINES:
            return True
    return False

def is_target_message(message: str) -> bool:
    to_value = header_value(message, "To").lower()
    subject_value = header_value(message, "Subject")
    body = normalize_body(message)
    return (
        EXPECTED_TO in to_value
        and subject_value == EXPECTED_SUBJECT
        and semantic_body_lines(body) == EXPECTED_BODY_LINES
    )

deadline = time.time() + WAIT_TIMEOUT_SECONDS
target_sent_messages = []
smtp_messages = []
last_sent_count = 0
last_smtp_count = 0

while time.time() < deadline:
    sent_text = sent_path.read_text(encoding="utf-8", errors="ignore")
    sent_messages = split_mbox(sent_text)
    target_sent_messages = [message for message in sent_messages if is_target_message(message)]
    last_sent_count = len(target_sent_messages)

    smtp_messages = sorted(smtp_log_dir.glob("message_*.eml"))
    last_smtp_count = len(smtp_messages)

    if len(target_sent_messages) == 1 and len(smtp_messages) == 3:
        break

    time.sleep(1.0)

if len(target_sent_messages) != 1:
    print(
        "EVAL_RESULT:FAIL expected exactly 1 matching sent message, "
        f"got {len(target_sent_messages)} after waiting {WAIT_TIMEOUT_SECONDS}s"
    )
    sys.exit(0)

target_message = target_sent_messages[0]
from_value = header_value(target_message, "From").lower()
if EXPECTED_FROM not in from_value:
    print(f"EVAL_RESULT:FAIL sent message From header unexpected: {from_value!r}")
    sys.exit(0)

if header_value(target_message, "Bcc"):
    print("EVAL_RESULT:FAIL sent message should not contain Bcc")
    sys.exit(0)

if header_value(target_message, "Subject") != EXPECTED_SUBJECT:
    print("EVAL_RESULT:FAIL sent message subject does not match expected value")
    sys.exit(0)

if len(smtp_messages) != 3:
    print(
        "EVAL_RESULT:FAIL expected exactly 3 fake SMTP receipts, "
        f"got {len(smtp_messages)} after waiting {WAIT_TIMEOUT_SECONDS}s"
    )
    sys.exit(0)

smtp_texts = [
    path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
    for path in smtp_messages
]
smtp_text = next((text for text in smtp_texts if f"subject: {EXPECTED_SUBJECT}".lower() in text.lower()), "")
if not smtp_text:
    print("EVAL_RESULT:FAIL fake SMTP receipts missing primary expected Subject header")
    sys.exit(0)
if f"to: {EXPECTED_TO}" not in smtp_text.lower():
    print("EVAL_RESULT:FAIL fake SMTP receipt missing expected To header")
    sys.exit(0)
if f"subject: {EXPECTED_SUBJECT}".lower() not in smtp_text.lower():
    print("EVAL_RESULT:FAIL fake SMTP receipt missing expected Subject header")
    sys.exit(0)
smtp_body = normalize_body(smtp_text)
if semantic_body_lines(smtp_body) != EXPECTED_BODY_LINES:
    print("EVAL_RESULT:FAIL fake SMTP receipt body does not semantically match expected content")
    sys.exit(0)

followup_text = next((text for text in smtp_texts if f"subject: {FOLLOWUP_SUBJECT}".lower() in text.lower()), "")
if not followup_text:
    print("EVAL_RESULT:FAIL fake SMTP receipts missing follow-up Subject header")
    sys.exit(0)
if f"to: {EXPECTED_TO}" not in followup_text.lower():
    print("EVAL_RESULT:FAIL follow-up fake SMTP receipt missing expected To header")
    sys.exit(0)
if semantic_body_lines(normalize_body(followup_text)) != FOLLOWUP_BODY_LINES:
    print("EVAL_RESULT:FAIL follow-up fake SMTP receipt body does not match expected content")
    sys.exit(0)

agenda_text = next((text for text in smtp_texts if f"subject: {AGENDA_SUBJECT}".lower() in text.lower()), "")
if not agenda_text:
    print("EVAL_RESULT:FAIL fake SMTP receipts missing agenda Subject header")
    sys.exit(0)
if f"to: {EXPECTED_TO}" not in agenda_text.lower():
    print("EVAL_RESULT:FAIL agenda fake SMTP receipt missing expected To header")
    sys.exit(0)
if semantic_body_lines(normalize_body(agenda_text)) != AGENDA_BODY_LINES:
    print("EVAL_RESULT:FAIL agenda fake SMTP receipt body does not match expected content")
    sys.exit(0)

drafts_text = drafts_path.read_text(encoding="utf-8", errors="ignore") if drafts_path.exists() else ""
unsent_text = unsent_path.read_text(encoding="utf-8", errors="ignore") if unsent_path.exists() else ""

if mailbox_contains_semantic_body(drafts_text):
    print("EVAL_RESULT:FAIL target message still exists in Drafts")
    sys.exit(0)

if mailbox_contains_semantic_body(unsent_text):
    print("EVAL_RESULT:FAIL target message still exists in Unsent Messages")
    sys.exit(0)

imap_root = profile_dir / "ImapMail" / "outlook.office365.com"
outbox_text = ""
if imap_root.exists():
    outbox_path = imap_root / "Outbox"
    if outbox_path.exists():
        outbox_text = outbox_path.read_text(encoding="utf-8", errors="ignore")
if mailbox_contains_semantic_body(outbox_text):
    print("EVAL_RESULT:FAIL target message still exists in IMAP Outbox")
    sys.exit(0)

print("EVAL_RESULT:PASS exact message captured by fake SMTP and found in Sent without leftovers")
'@

$pyCode | py -3 -W ignore -
