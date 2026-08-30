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

SUBJECT = "Bench Supplier Summary"
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
    "Bench_Supplier_Summary_Attachments.odt": [
        "Vendor_Review_Notes.docx",
        "Bench_Supplier_Summary.docx",
        "Bench_Supplier_Summary.pdf",
    ],
    "Bench_Supplier_Checklist.odt": [
        "PDF exported from saved copy",
        "Original source included",
    ],
    "Bench_Supplier_Routing.odt": [
        "Review owner: Finance Ops",
        "Deadline: Friday 17:00",
    ],
    "Bench_Supplier_Audit.odt": [
        "Attachment count: 29",
        "PDF source: saved copy",
        "Send status: sent",
    ],
    "Bench_Supplier_Signoff.odt": [
        "Finance signoff pending",
        "Supplier summary archived",
    ],
    "Bench_Supplier_Review_Log.odt": [
        "Checked by: Procurement Desk",
        "Archive path: supplier-review",
    ],
    "Bench_Supplier_Archive.odt": [
        "Archive status: staged",
        "Retention owner: Finance Ops",
    ],
    "Bench_Supplier_Risk.odt": [
        "Risk owner: Finance Ops",
        "Escalation path: procurement-director",
    ],
    "Bench_Supplier_Evidence.odt": [
        "Evidence index: summary-pdf-routing",
        "Review packet: supplier-summary",
    ],
    "Bench_Supplier_Delivery.odt": [
        "Delivery channel: Thunderbird sent mail",
        "Send status: sent",
    ],
    "Bench_Supplier_Compliance.odt": [
        "Compliance owner: Finance Ops",
        "Evidence status: indexed",
    ],
    "Bench_Supplier_Exceptions.odt": [
        "Exception count: 0",
        "Escalation owner: Procurement Desk",
    ],
    "Bench_Supplier_Recipients.odt": [
        "Primary recipient: bench-review@example.com",
        "Send status: sent",
    ],
    "Bench_Supplier_Retention.odt": [
        "Retention class: supplier-review",
        "Retention owner: Finance Ops",
    ],
    "Bench_Supplier_Closeout.odt": [
        "Closeout owner: Finance Ops",
        "Closeout status: pending",
    ],
    "Bench_Supplier_QC.odt": [
        "QC owner: Procurement Desk",
        "QC status: finance-review",
    ],
    "Bench_Supplier_Packet_Index.odt": [
        "Packet index: 26-files-plus-mail",
        "Index status: final",
    ],
    "Bench_Supplier_Send_Gate.odt": [
        "Send gate: manual-review",
        "Gate owner: Finance Ops",
    ],
    "Bench_Supplier_Director_Packet.odt": [
        "Director packet: supplier-summary",
        "Packet status: pending-review",
    ],
    "Bench_Supplier_Source_Check.odt": [
        "Source check: original-and-copy",
        "PDF check: exported-from-copy",
    ],
    "Bench_Supplier_Handoff_Roster.odt": [
        "Handoff roster: Finance Ops",
        "Roster status: staged",
    ],
    "Bench_Supplier_Archive_Index.odt": [
        "Archive index: supplier-final",
        "Archive owner: Finance Ops",
    ],
    "Bench_Supplier_Review_Gate.odt": [
        "Review gate: hold",
        "Gate evidence: supplier-summary",
    ],
    "Bench_Supplier_Transfer_Receipt.odt": [
        "Transfer receipt: supplier_review",
        "Transfer status: staged",
    ],
    "Bench_Supplier_Attachment_Crosswalk.odt": [
        "file depends_on status",
        "Bench_Supplier_Audit.odt depends_on Bench_Supplier_Summary_Attachments.odt status linked",
        "Bench_Supplier_Packet_Index.odt depends_on Bench_Supplier_Audit.odt status linked",
        "Bench_Supplier_Transfer_Receipt.odt depends_on Bench_Supplier_Review_Gate.odt status linked",
    ],
    "Bench_Supplier_Final_Bundle_Index.odt": [
        "root=Vendor_Review_Notes.docx",
        "attachment_manifest=Bench_Supplier_Summary_Attachments.odt",
        "crosswalk=Bench_Supplier_Attachment_Crosswalk.odt",
        "terminal=Bench_Supplier_Transfer_Receipt.odt",
    ],
}
EXPECTED_FILES = {
    "Vendor_Review_Notes.docx",
    "Bench_Supplier_Summary.docx",
    "Bench_Supplier_Summary.pdf",
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
source_data = payloads["Vendor_Review_Notes.docx"]
copy_data = payloads["Bench_Supplier_Summary.docx"]
pdf_data = payloads["Bench_Supplier_Summary.pdf"]
if not is_valid_docx(source_data) or not docx_contains(source_data, "Vendor Review Notes"):
    fail("attached Vendor_Review_Notes.docx is not the expected source document")
if not is_valid_docx(copy_data) or not docx_contains(copy_data, "Vendor Review Notes"):
    fail("attached Bench_Supplier_Summary.docx is not the expected copied document")
if not is_valid_pdf(pdf_data):
    fail("attached Bench_Supplier_Summary.pdf is not a valid PDF payload")

for name, expected_lines in EXPECTED_ODT_FILES.items():
    actual = odt_nonempty_lines(payloads[name])
    expected = normalized_lines(expected_lines)
    if actual != expected:
        fail(f"attached {name} content mismatch: {actual!r}")

print("EVAL_RESULT:PASS linux-aligned 29-file supplier attachment package sent")
'@
$tmp = Join-Path $env:TEMP "cross_app_writer_thunderbird_save_copy_export_attach_send_hard.py"
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
