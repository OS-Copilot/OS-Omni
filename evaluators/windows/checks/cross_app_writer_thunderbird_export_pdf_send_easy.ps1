$script = @'
import os
import pathlib
import sys
import email
from email.header import decode_header, make_header
import time

SUBJECT = "Bench PDF Review"
TO = "bench-review@example.com"
EXPECTED_FILES = {"Bench_Status_Update.pdf"}
SEARCH_FILES = [
    pathlib.Path(os.environ["USERPROFILE"]) / "Desktop" / "Bench_Status_Update.pdf",
    pathlib.Path(os.environ["USERPROFILE"]) / "Documents" / "Bench_Status_Update.pdf",
    pathlib.Path(os.environ["USERPROFILE"]) / "Downloads" / "Bench_Status_Update.pdf",
]
SMTP_DIR = pathlib.Path(r"C:\Users\User\fake_smtp_messages")

def attachment_payloads(msg):
    payloads = {}
    for part in msg.walk():
        filename = part.get_filename()
        if filename:
            payloads[pathlib.Path(filename).name] = part.get_payload(decode=True) or b""
    return payloads

def decoded_header(msg, name):
    return str(make_header(decode_header(str(msg.get(name, ""))))).strip()

def is_valid_pdf(data):
    return data.startswith(b"%PDF") and len(data) > 1000 and b"%%EOF" in data[-4096:]

def find_matching_email(subject, to_address, required_attachments, timeout=30):
    deadline = time.time() + timeout
    to_address = to_address.lower()
    last_seen = []
    while time.time() < deadline:
        messages = sorted(SMTP_DIR.glob("*.eml")) if SMTP_DIR.exists() else []
        for eml_path in messages:
            msg = email.message_from_bytes(eml_path.read_bytes())
            subject_value = decoded_header(msg, "Subject")
            to_value = decoded_header(msg, "To").lower()
            payloads = attachment_payloads(msg)
            last_seen.append((eml_path.name, subject_value, sorted(payloads)))
            if subject_value == subject and to_address in to_value and set(required_attachments).issubset(payloads):
                return eml_path, payloads
        time.sleep(1)
    print(f"EVAL_RESULT:FAIL matching email not found; seen={last_seen[-5:]}")
    sys.exit(0)
existing = [p for p in SEARCH_FILES if p.exists()]
if not existing:
    print("EVAL_RESULT:FAIL exported PDF not found on disk")
    sys.exit(0)

_eml_path, payloads = find_matching_email(SUBJECT, TO, EXPECTED_FILES)
pdf_data = payloads["Bench_Status_Update.pdf"]
if not is_valid_pdf(pdf_data):
    print("EVAL_RESULT:FAIL attached Bench_Status_Update.pdf is not a valid PDF payload")
    sys.exit(0)

if existing[0].stat().st_size < 1000:
    print("EVAL_RESULT:FAIL exported PDF on disk is too small")
    sys.exit(0)

print("EVAL_RESULT:PASS exported and sent valid PDF attachment")
'@
$tmp = Join-Path $env:TEMP "cross_app_writer_thunderbird_export_pdf_send_easy.py"
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
