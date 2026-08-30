$pyCode = @'
import configparser
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import time
from email import policy
from email.parser import BytesParser, Parser

EXPECTED_CONTACT_NAME = "Anonymous Helloworld"
EXPECTED_NICKNAME = "hello2026"
EXPECTED_TO = "anonym-x2026@outlook.com"
EXPECTED_ADDRESS_TOKENS = ["70 washington square s", "new york", "10012", "usa"]
EXPECTED_SUBJECT = "Morning"
EXPECTED_BODY_LINES = ["Good Morning"]
WAIT_TIMEOUT_SECONDS = 45

def fail(message):
    print(f"EVAL_RESULT:FAIL {message}")
    sys.exit(0)

def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")

def split_mbox(raw_text: str):
    text = normalize_newlines(raw_text)
    parts = re.split(r"^From - .*$", text, flags=re.MULTILINE)
    return [part for part in parts if part.strip()]

def parse_email_message(raw):
    if isinstance(raw, str):
        return Parser(policy=policy.default).parsestr(raw)
    return BytesParser(policy=policy.default).parsebytes(raw)

def body_text(message) -> str:
    try:
        if message.is_multipart():
            part = message.get_body(preferencelist=("plain",))
            if part is None:
                return ""
            return part.get_content()
        return message.get_content()
    except Exception:
        return ""

def semantic_lines(text: str):
    return [line.strip() for line in normalize_newlines(text).split("\n") if line.strip()]

def is_expected_message(raw: str) -> bool:
    msg = parse_email_message(raw)
    to_value = str(msg.get("to", "")).lower()
    subject_value = str(msg.get("subject", "")).strip()
    return (
        EXPECTED_TO in to_value
        and subject_value == EXPECTED_SUBJECT
        and semantic_lines(body_text(msg)) == EXPECTED_BODY_LINES
    )

def message_has_expected_body(raw: str) -> bool:
    msg = parse_email_message(raw)
    return semantic_lines(body_text(msg)) == EXPECTED_BODY_LINES

def find_profile_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        fail("APPDATA is missing")
    tb_root = pathlib.Path(appdata) / "Thunderbird"
    profiles_ini = tb_root / "profiles.ini"
    if not profiles_ini.exists():
        fail(f"profiles.ini not found: {profiles_ini}")

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
        fail("no Thunderbird profile section found")

    prof_path = cfg.get(profile_section, "Path", fallback="").strip()
    if not prof_path:
        fail("profile Path is empty")
    is_relative = cfg.get(profile_section, "IsRelative", fallback="1").strip() == "1"
    profile_dir = (tb_root / prof_path) if is_relative else pathlib.Path(prof_path)
    if not profile_dir.exists():
        fail(f"resolved profile directory does not exist: {profile_dir}")
    return profile_dir

def get_mailbox_paths(profile_dir: pathlib.Path):
    local_folders = profile_dir / "Mail" / "Local Folders"
    if not local_folders.exists():
        fail(f"Local Folders directory not found: {local_folders}")
    return {
        "sent": local_folders / "Sent",
        "drafts": local_folders / "Drafts",
        "unsent": local_folders / "Unsent Messages",
        "imap_outbox": profile_dir / "ImapMail" / "outlook.office365.com" / "Outbox",
    }

def read_mailbox(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")

def matching_sent_messages(sent_path: pathlib.Path):
    return [message for message in split_mbox(read_mailbox(sent_path)) if is_expected_message(message)]

def read_smtp_messages(smtp_log_dir: pathlib.Path):
    messages = []
    for path in sorted(smtp_log_dir.glob("message_*.eml")):
        raw_bytes = path.read_bytes()
        msg = parse_email_message(raw_bytes)
        messages.append((path, msg, raw_bytes))
    return messages

def expected_smtp_messages(smtp_log_dir: pathlib.Path):
    matches = []
    for path, msg, raw_bytes in read_smtp_messages(smtp_log_dir):
        to_value = str(msg.get("to", "")).lower()
        subject_value = str(msg.get("subject", "")).strip()
        if (
            EXPECTED_TO in to_value
            and subject_value == EXPECTED_SUBJECT
            and semantic_lines(body_text(msg)) == EXPECTED_BODY_LINES
        ):
            matches.append(path)
    return matches

def read_card_properties(conn):
    cur = conn.cursor()
    tables = {row[0].lower() for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    grouped = {}
    if "properties" in tables:
        try:
            for card, name, value in cur.execute("SELECT card, name, value FROM properties"):
                grouped.setdefault(str(card), []).append(str(value or ""))
            return list(grouped.values())
        except Exception:
            pass
    return []

def database_text(conn) -> str:
    chunks = []
    cur = conn.cursor()
    tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        if table.startswith("sqlite_"):
            continue
        quoted = '"' + table.replace('"', '""') + '"'
        try:
            for row in cur.execute(f"SELECT * FROM {quoted}"):
                chunks.extend(str(cell or "") for cell in row)
        except Exception:
            continue
    return " ".join(chunks).lower()

def contact_values_match(values) -> bool:
    joined = " ".join(str(value or "").lower() for value in values)
    has_name = "anonymous helloworld" in joined or ("anonymous" in joined and "helloworld" in joined)
    has_nickname = EXPECTED_NICKNAME.lower() in joined
    has_email = EXPECTED_TO.lower() in joined
    has_address = all(token in joined for token in EXPECTED_ADDRESS_TOKENS)
    return has_name and has_nickname and has_email and has_address

def address_book_has_expected_contact(profile_dir: pathlib.Path):
    db_candidates = [profile_dir / "abook.sqlite", profile_dir / "history.sqlite"]
    db_candidates.extend(sorted(path for path in profile_dir.glob("*.sqlite") if path not in db_candidates))
    checked = []
    for db_path in db_candidates:
        if not db_path.exists():
            continue
        checked.append(db_path.name)
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except Exception:
            continue
        try:
            for values in read_card_properties(conn):
                if contact_values_match(values):
                    return True, db_path.name
            if contact_values_match([database_text(conn)]):
                return True, db_path.name
        finally:
            conn.close()
    return False, ",".join(checked) if checked else "none"

profile_dir = find_profile_dir()
paths = get_mailbox_paths(profile_dir)
smtp_log_dir = pathlib.Path(r"C:\Users\User\fake_smtp_contact_messages")
if not smtp_log_dir.exists():
    fail(f"fake SMTP log directory not found: {smtp_log_dir}")

deadline = time.time() + WAIT_TIMEOUT_SECONDS
sent_matches = []
smtp_matches = []
total_smtp_count = 0
while time.time() < deadline:
    sent_matches = matching_sent_messages(paths["sent"])
    smtp_matches = expected_smtp_messages(smtp_log_dir)
    total_smtp_count = len(list(smtp_log_dir.glob("message_*.eml")))
    if len(smtp_matches) == 1 and total_smtp_count == 1:
        break
    time.sleep(1.0)

# Stop Thunderbird before reading the address book database so sqlite/WAL state is flushed.
subprocess.run(["taskkill", "/IM", "thunderbird.exe", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.0)

all_smtp_paths = sorted(smtp_log_dir.glob("message_*.eml"))
smtp_matches = expected_smtp_messages(smtp_log_dir)
if len(all_smtp_paths) != 1:
    fail(f"expected exactly 1 fake SMTP receipt, got {len(all_smtp_paths)}")
if len(smtp_matches) != 1:
    fail("fake SMTP receipt does not match expected recipient, subject, and body")

if paths["sent"].exists():
    sent_matches = matching_sent_messages(paths["sent"])
    if len(sent_matches) > 1:
        fail(f"expected at most 1 matching Sent copy, got {len(sent_matches)}")
    if len(sent_matches) == 1:
        sent_msg = parse_email_message(sent_matches[0])
        from_value = str(sent_msg.get("from", "")).lower()
        if "helloworld@outlook.com" not in from_value:
            fail(f"sent message From header unexpected: {from_value!r}")
        if str(sent_msg.get("bcc", "")).strip():
            fail("sent message should not contain Bcc")

for leftover_name in ("drafts", "unsent", "imap_outbox"):
    for message in split_mbox(read_mailbox(paths[leftover_name])):
        if message_has_expected_body(message):
            fail(f"target message still exists in {leftover_name}")

has_contact, checked = address_book_has_expected_contact(profile_dir)
if not has_contact:
    fail(
        "expected contact was not found in Thunderbird address books; "
        f"checked={checked}; required name={EXPECTED_CONTACT_NAME!r}, nickname={EXPECTED_NICKNAME!r}, "
        f"email={EXPECTED_TO!r}, address tokens={EXPECTED_ADDRESS_TOKENS!r}"
    )

print("EVAL_RESULT:PASS contact exists with required fields and one exact email was sent by the configured account")
'@

$pyCode | py -3 -W ignore -
