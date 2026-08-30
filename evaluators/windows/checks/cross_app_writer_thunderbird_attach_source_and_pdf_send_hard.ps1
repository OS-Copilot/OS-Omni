$script = @'
import email
import io
import os
import pathlib
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from email.header import decode_header, make_header

SUBJECT = "Bench Dual Attachment Review"
TO = "bench-review@example.com"
DESKTOP = pathlib.Path(os.environ["USERPROFILE"]) / "Desktop"
SEARCH_DIRS = [
    DESKTOP,
    pathlib.Path(os.environ["USERPROFILE"]) / "Documents",
    pathlib.Path(os.environ["USERPROFILE"]) / "Downloads",
    pathlib.Path(os.environ["USERPROFILE"]),
]
SMTP_DIR = pathlib.Path(r"C:\Users\User\fake_smtp_messages")

EXPECTED_ODT_FILES = {
    "Bench_Launch_Attachments.odt": [
        "Bench_Launch_Memo.docx",
        "Bench_Launch_Memo_Copy.docx",
        "Bench_Launch_Memo.pdf",
    ],
    "Bench_Launch_Readme.odt": [
        "Export verified",
        "Keep draft sent",
    ],
    "Bench_Launch_Metadata.odt": [
        "Draft owner: PMO",
        "Attachment count: 28",
        "Send status: sent",
    ],
    "Bench_Launch_QA.odt": [
        "PDF opens locally",
        "All filenames verified",
    ],
    "Bench_Launch_Routing.odt": [
        "Routing: launch reviewers",
        "Archive: Bench launch packet",
    ],
    "Bench_Launch_Checksum.odt": [
        "Checksum status: pending",
        "Packet version: v3",
    ],
    "Bench_Launch_Approval.odt": [
        "Approval owner: Maya Chen",
        "Approval window: Friday 16:00",
    ],
    "Bench_Launch_Evidence.odt": [
        "Evidence bundle: source-pdf-manifest",
        "Review lane: launch-readiness",
    ],
    "Bench_Launch_Final_Check.odt": [
        "Final check: attachments complete",
        "Draft disposition: sent",
    ],
    "Bench_Launch_Risk.odt": [
        "Risk owner: Launch PMO",
        "Risk lane: attachment-integrity",
    ],
    "Bench_Launch_Audit_Trail.odt": [
        "Audit source: Bench_Launch_Memo.docx",
        "Audit result: ready-for-review",
    ],
    "Bench_Launch_Distribution.odt": [
        "Distribution: bench-review@example.com",
        "Cc status: none",
    ],
    "Bench_Launch_Retention.odt": [
        "Retention class: launch-packet",
        "Retention owner: PMO",
    ],
    "Bench_Launch_Handoff.odt": [
        "Handoff owner: Maya Chen",
        "Handoff status: staged",
    ],
    "Bench_Launch_QC_Owner.odt": [
        "QC owner: Priya Nair",
        "QC status: needs-director-view",
    ],
    "Bench_Launch_Packet_Index.odt": [
        "Packet index: 25-files-plus-mail",
        "Index status: final",
    ],
    "Bench_Launch_Send_Gate.odt": [
        "Send gate: manual-review",
        "Gate owner: Maya Chen",
    ],
    "Bench_Launch_Signoff_Roster.odt": [
        "Signoff roster: Maya/Jordan/Priya",
        "Roster status: pending",
    ],
    "Bench_Launch_Reviewer_Notes.odt": [
        "Reviewer note: verify PDF export",
        "Reviewer lane: launch-readiness",
    ],
    "Bench_Launch_Exception_Log.odt": [
        "Exception count: 0",
        "Exception owner: Launch PMO",
    ],
    "Bench_Launch_Archive_Index.odt": [
        "Archive index: launch-final",
        "Archive owner: PMO",
    ],
    "Bench_Launch_Director_Gate.odt": [
        "Director gate: hold",
        "Gate evidence: pending",
    ],
    "Bench_Launch_Transfer_Receipt.odt": [
        "Transfer receipt: launch_review",
        "Transfer status: staged",
    ],
    "Bench_Launch_Attachment_Crosswalk.odt": [
        "file depends_on status",
        "Bench_Launch_Metadata.odt depends_on Bench_Launch_Attachments.odt status linked",
        "Bench_Launch_Packet_Index.odt depends_on Bench_Launch_Metadata.odt status linked",
        "Bench_Launch_Transfer_Receipt.odt depends_on Bench_Launch_Director_Gate.odt status linked",
    ],
    "Bench_Launch_Final_Bundle_Index.odt": [
        "root=Bench_Launch_Memo.docx",
        "attachment_manifest=Bench_Launch_Attachments.odt",
        "crosswalk=Bench_Launch_Attachment_Crosswalk.odt",
        "terminal=Bench_Launch_Transfer_Receipt.odt",
    ],
}
EXPECTED_FILES = {
    "Bench_Launch_Memo.docx",
    "Bench_Launch_Memo_Copy.docx",
    "Bench_Launch_Memo.pdf",
    *EXPECTED_ODT_FILES.keys(),
}

def fail(message):
    print("EVAL_RESULT:FAIL " + message)
    sys.exit(0)

def find_file(name):
    for root in SEARCH_DIRS:
        path = root / name
        if path.exists():
            return path
    return None

def normalized_lines(lines):
    return [" ".join(line.strip().split()) for line in lines if line.strip()]

def odt_nonempty_lines(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            raw = archive.read("content.xml")
    except Exception as exc:
        fail(f"invalid odt payload: {exc}")
    root = ET.fromstring(raw)
    ns = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
    lines = []
    for paragraph in root.findall(".//text:p", ns):
        text = "".join(paragraph.itertext()).strip()
        if text:
            lines.append(text)
    return normalized_lines(lines)

def decoded_header_value(value):
    return str(make_header(decode_header(str(value or "")))).strip()

def attachment_payloads(msg):
    payloads = {}
    for part in msg.walk():
        filename = part.get_filename()
        if filename:
            payloads[pathlib.Path(decoded_header_value(filename)).name] = part.get_payload(decode=True) or b""
    return payloads

def is_valid_docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and "word/document.xml" in names
    except Exception:
        return False

def docx_contains(data, text):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            raw = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        return text in raw
    except Exception:
        return False

def is_valid_pdf(data):
    return data.startswith(b"%PDF") and len(data) > 1000 and b"%%EOF" in data[-4096:]

def find_matching_email(timeout=30):
    deadline = time.time() + timeout
    last_seen = []
    while time.time() < deadline:
        for eml_path in sorted(SMTP_DIR.glob("*.eml")) if SMTP_DIR.exists() else []:
            msg = email.message_from_bytes(eml_path.read_bytes())
            subject = decoded_header_value(msg.get("Subject"))
            to_value = decoded_header_value(msg.get("To")).lower()
            payloads = attachment_payloads(msg)
            last_seen.append((eml_path.name, subject, sorted(payloads)))
            if subject == SUBJECT and TO.lower() in to_value and EXPECTED_FILES.issubset(payloads):
                return payloads
        time.sleep(1)
    fail(f"matching sent email not found; seen={last_seen[-5:]}")

for name in EXPECTED_FILES:
    if find_file(name) is None:
        fail(f"missing local file: {name}")

for name, expected_lines in EXPECTED_ODT_FILES.items():
    actual = odt_nonempty_lines(find_file(name).read_bytes())
    expected = normalized_lines(expected_lines)
    if actual != expected:
        fail(f"{name} content mismatch: {actual!r}")

payloads = find_matching_email()
source_data = payloads["Bench_Launch_Memo.docx"]
copy_data = payloads["Bench_Launch_Memo_Copy.docx"]
pdf_data = payloads["Bench_Launch_Memo.pdf"]
if not is_valid_docx(source_data) or not docx_contains(source_data, "Bench Launch Memo"):
    fail("attached Bench_Launch_Memo.docx is not the expected source document")
if not is_valid_docx(copy_data) or not docx_contains(copy_data, "Bench Launch Memo"):
    fail("attached Bench_Launch_Memo_Copy.docx is not the expected copied document")
if not is_valid_pdf(pdf_data):
    fail("attached Bench_Launch_Memo.pdf is not a valid PDF payload")

for name, expected_lines in EXPECTED_ODT_FILES.items():
    actual = odt_nonempty_lines(payloads[name])
    expected = normalized_lines(expected_lines)
    if actual != expected:
        fail(f"attached {name} content mismatch: {actual!r}")

print("EVAL_RESULT:PASS linux-aligned 28-file launch attachment package sent")
'@
$tmp = Join-Path $env:TEMP "cross_app_writer_thunderbird_attach_source_and_pdf_send_hard.py"
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
