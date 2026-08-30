$pyCode = @'
import configparser
import os
import pathlib
import re
import sys
import time

TARGET_TO = "anonym-x2026@outlook.com"
WAIT_TIMEOUT_SECONDS = 45
RELEVANT = {
    "<stclub-001@campus.edu>": {
        "subject": "Draft Ready for Review",
        "snippet": "the constitution draft for the st club is ready for the founding officers to review and sign this afternoon",
    },
    "<stclub-002@campus.edu>": {
        "subject": "Numbers Updated",
        "snippet": "the budget revision for starting the st club now includes booth supplies, banner printing, and member sign-up sheets",
    },
    "<stclub-003@campus.edu>": {
        "subject": "Space Confirmed",
        "snippet": "room 204 has been reserved for the st club kickoff planning meeting on april 18",
    },
    "<stclub-004@campus.edu>": {
        "subject": "Approval Came In",
        "snippet": "the faculty advisor approval for the st club registration packet was submitted this morning",
    },
}
IRRELEVANT = {
    "<misc-005@campus.edu>": "Receipt Processed",
}

def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")

def header_value(message: str, name: str) -> str:
    pattern = re.compile(rf"^{re.escape(name)}:\s*(.+(?:\n[ \t].+)*)$", re.MULTILINE)
    match = pattern.search(normalize_text(message))
    if not match:
        return ""
    return re.sub(r"\n[ \t]+", " ", match.group(1)).strip()

def split_mbox(raw_text: str):
    text = normalize_text(raw_text)
    parts = re.split(r"^From - .*$", text, flags=re.MULTILINE)
    return [part for part in parts if part.strip()]

def parse_mbox(path: pathlib.Path):
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    messages = []
    for message in split_mbox(text):
        status_match = re.search(r"^X-Mozilla-Status:\s*([0-9A-Fa-f]{4})$", normalize_text(message), flags=re.MULTILINE)
        status_value = int(status_match.group(1), 16) if status_match else 0
        messages.append(
            {
                "subject": header_value(message, "Subject"),
                "message_id": header_value(message, "Message-ID"),
                "status": status_value,
                "starred": bool(status_value & 0x0004),
                "expunged": bool(status_value & 0x0008),
                "raw": normalize_text(message),
            }
        )
    return messages

appdata = os.environ.get("APPDATA")
if not appdata:
    print("EVAL_RESULT:FAIL APPDATA is missing")
    sys.exit(0)

smtp_log_dir = pathlib.Path(r"C:\Users\User\fake_smtp_stclub_messages")
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

bills_path = local_folders / "Bills"
club_path = local_folders / "Club"

deadline = time.time() + WAIT_TIMEOUT_SECONDS
bills_messages = []
club_messages = []
receipt_paths = []

while time.time() < deadline:
    bills_messages = parse_mbox(bills_path)
    club_messages = parse_mbox(club_path)
    receipt_paths = sorted(smtp_log_dir.glob("message_*.eml"))

    bills_active = {m["message_id"]: m for m in bills_messages if not m["expunged"]}
    club_active = {m["message_id"]: m for m in club_messages if not m["expunged"]}

    if (
        set(bills_active.keys()) == set(IRRELEVANT.keys())
        and set(club_active.keys()) == set(RELEVANT.keys())
        and len(receipt_paths) == len(RELEVANT)
    ):
        break

    time.sleep(1.0)

if not club_path.exists():
    print(f"EVAL_RESULT:FAIL Club folder mailbox was not created: {club_path}")
    sys.exit(0)

bills_messages = parse_mbox(bills_path)
club_messages = parse_mbox(club_path)
bills_active = {m["message_id"]: m for m in bills_messages if not m["expunged"]}
club_active = {m["message_id"]: m for m in club_messages if not m["expunged"]}

if set(club_active.keys()) != set(RELEVANT.keys()):
    print(
        "EVAL_RESULT:FAIL Club folder active message ids mismatch "
        f"got={sorted(club_active.keys())} expected={sorted(RELEVANT.keys())}"
    )
    sys.exit(0)

if set(bills_active.keys()) != set(IRRELEVANT.keys()):
    print(
        "EVAL_RESULT:FAIL Bills folder active message ids mismatch "
        f"got={sorted(bills_active.keys())} expected={sorted(IRRELEVANT.keys())}"
    )
    sys.exit(0)

for message_id, spec in RELEVANT.items():
    message = club_active[message_id]
    if message["subject"] != spec["subject"]:
        print(
            "EVAL_RESULT:FAIL Club subject mismatch "
            f"msgid={message_id} got={message['subject']!r} expected={spec['subject']!r}"
        )
        sys.exit(0)
    if not message["starred"]:
        print(
            "EVAL_RESULT:FAIL Club message is not starred "
            f"msgid={message_id} subject={message['subject']!r} status=0x{message['status']:04x}"
        )
        sys.exit(0)

for message_id, subject in IRRELEVANT.items():
    message = bills_active[message_id]
    if message["subject"] != subject:
        print(
            "EVAL_RESULT:FAIL Bills subject mismatch "
            f"msgid={message_id} got={message['subject']!r} expected={subject!r}"
        )
        sys.exit(0)
    if message["starred"]:
        print(
            "EVAL_RESULT:FAIL unrelated Bills message should not be starred "
            f"msgid={message_id} subject={subject!r} status=0x{message['status']:04x}"
        )
        sys.exit(0)

receipt_paths = sorted(smtp_log_dir.glob("message_*.eml"))
if len(receipt_paths) != len(RELEVANT):
    print(
        "EVAL_RESULT:FAIL wrong number of forwarded SMTP receipts "
        f"got={len(receipt_paths)} expected={len(RELEVANT)}"
    )
    sys.exit(0)

receipt_data = []
for path in receipt_paths:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    receipt_data.append(
        {
            "name": path.name,
            "raw": normalize_text(raw),
            "to": header_value(raw, "To").lower(),
            "subject": header_value(raw, "Subject").lower(),
        }
    )

for receipt in receipt_data:
    if TARGET_TO not in receipt["to"]:
        print(
            "EVAL_RESULT:FAIL forwarded receipt missing expected target recipient "
            f"file={receipt['name']} to={receipt['to']!r}"
        )
        sys.exit(0)

used_receipts = set()
for message_id, spec in RELEVANT.items():
    matches = []
    subject_needle = spec["subject"].lower()
    snippet_needle = spec["snippet"].lower()
    for receipt in receipt_data:
        if subject_needle in receipt["subject"] and snippet_needle in receipt["raw"].lower():
            matches.append(receipt["name"])
    if len(matches) != 1:
        print(
            "EVAL_RESULT:FAIL expected exactly one forwarded receipt for relevant message "
            f"msgid={message_id} subject={spec['subject']!r} matches={matches}"
        )
        sys.exit(0)
    used_receipts.add(matches[0])

if len(used_receipts) != len(RELEVANT):
    print(
        "EVAL_RESULT:FAIL forwarded receipts are not uniquely matched to relevant messages "
        f"used={sorted(used_receipts)}"
    )
    sys.exit(0)

for receipt in receipt_data:
    raw_lower = receipt["raw"].lower()
    for message_id, subject in IRRELEVANT.items():
        if subject.lower() in receipt["subject"] or subject.lower() in raw_lower:
            print(
                "EVAL_RESULT:FAIL unrelated email appears in forwarded output "
                f"receipt={receipt['name']} subject={subject!r}"
            )
            sys.exit(0)

print(
    "EVAL_RESULT:PASS "
    f"club={sorted(m['subject'] for m in club_active.values())} "
    f"bills={sorted(m['subject'] for m in bills_active.values())} "
    f"forwarded={len(receipt_data)}"
)
'@

$pyCode | py -3 -W ignore -
