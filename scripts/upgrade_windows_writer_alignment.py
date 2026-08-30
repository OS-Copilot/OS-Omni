from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

REFERENCE = (
    "Steinberg, F. M., Bearden, M. M., & Keen, C. L. (2003). Cocoa and chocolate flavonoids: "
    "Implications for cardiovascular health. Journal of the American Dietetic Association, 103(2), 215-223. "
    "doi: 10.1053/jada.2003.50028"
)

TRAIN_LINES = [
    "time_06:02:00, A101, ST-01, 1",
    "time_06:05:00, B202, ST-03, 2",
    "time_06:08:00, A101, ST-02, 1",
    "time_06:12:00, C303, ST-04, 3",
    "time_06:18:00, D404, ST-05, 1",
    "time_06:22:00, B202, ST-06, 2",
    "time_06:30:00, E505, ST-02, 4",
    "time_06:36:00, C303, ST-07, 3",
    "time_06:44:00, F606, ST-08, 1",
    "time_06:51:00, G707, ST-09, 2",
    "time_06:58:00, E505, ST-10, 4",
    "time_07:04:00, H808, ST-11, 1",
]

EXPECTED_TRAIN_LINES = [
    "time_06:02:00, A101, ST-01, 1",
    "time_06:05:00, B202, ST-03, 2",
    "time_06:12:00, C303, ST-04, 3",
    "time_06:18:00, D404, ST-05, 1",
    "time_06:30:00, E505, ST-02, 4",
    "time_06:44:00, F606, ST-08, 1",
    "time_06:51:00, G707, ST-09, 2",
    "time_07:04:00, H808, ST-11, 1",
]


def load_yaml(relpath: str):
    return yaml.safe_load((ROOT / relpath).read_text(encoding="utf-8"))


def dump_yaml(relpath: str, data) -> None:
    (ROOT / relpath).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def ps_here_python(code: str) -> str:
    return "$py = @'\n" + code.strip() + "\n'@\n$py | py -3 -W ignore -\n"


def open_doc_script(filename: str) -> str:
    return f"""$docPath = Join-Path $env:USERPROFILE "Downloads\\{filename}"
if (-not (Test-Path $docPath)) {{ throw "Document not found: $docPath" }}
$proc = Start-Process -FilePath $docPath -PassThru
Start-Sleep -Seconds 2
try {{
  $wshell = New-Object -ComObject WScript.Shell
  $null = $wshell.AppActivate($proc.Id)
}} catch {{}}
"""


def init_reference_doc_code() -> str:
    return f"""
import os, subprocess, sys
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

doc = Document()
for text in [
    "Chocolate Intake and Health Notes",
    "This short essay summarizes dietary evidence on cocoa, flavonoids, and cardiovascular outcomes.",
    "Several classroom readings discuss antioxidants, population cohorts, and nutrition recommendations.",
    "The strongest claim should be supported by the new reference <add here> before the paper is submitted.",
    "References",
    "[1] Arts, I. C. W., Hollman, P. C. H., & Kromhout, D. (1999). Chocolate as a source of tea flavonoids.",
    "[2] Kris-Etherton, P. M., & Keen, C. L. (2002). Evidence that the antioxidant flavonoids in tea and cocoa are beneficial.",
]:
    doc.add_paragraph(text)
path = os.path.join(os.environ["USERPROFILE"], "Downloads", "essay_references.docx")
doc.save(path)
print("INIT_OK", path)
"""


def eval_reference_code() -> str:
    return f"""
import os, sys, subprocess
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

path = os.path.join(os.environ["USERPROFILE"], "Downloads", "essay_references.docx")
doc = Document(path)
texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
body = "\\n".join(texts)
reference = {REFERENCE!r}

def fail(message):
    print("EVAL_RESULT:FAIL " + message)
    sys.exit(1)

if "<add here>" in body:
    fail("marker still present")
if reference not in body:
    fail("new reference missing")
if body.count(reference) != 1:
    fail("new reference duplicated")
if "[3]" not in body:
    fail("reference number [3] missing")
target = "The strongest claim should be supported by the new reference [3] before the paper is submitted."
if target not in texts:
    fail("fourth paragraph does not contain the inserted reference number")
expected_tail = [
    "References",
    "[1] Arts, I. C. W., Hollman, P. C. H., & Kromhout, D. (1999). Chocolate as a source of tea flavonoids.",
    "[2] Kris-Etherton, P. M., & Keen, C. L. (2002). Evidence that the antioxidant flavonoids in tea and cocoa are beneficial.",
    "[3] " + reference,
]
if texts[-4:] != expected_tail:
    fail("reference list order/content mismatch got=" + repr(texts[-4:]))
print("EVAL_RESULT:PASS Writer reference and cross-reference task verified")
"""


def oracle_reference_code() -> str:
    return f"""
import os, subprocess, sys
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

path = os.path.join(os.environ["USERPROFILE"], "Downloads", "essay_references.docx")
doc = Document(path)
for p in doc.paragraphs:
    if "<add here>" in p.text:
        for run in p.runs:
            run.text = run.text.replace("<add here>", "[3]")
doc.add_paragraph("[3] " + {REFERENCE!r})
doc.save(path)
print(path)
"""


def init_dedupe_doc_code() -> str:
    return f"""
import os, subprocess, sys
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

doc = Document()
doc.add_paragraph("HK Train Records")
for line in {TRAIN_LINES!r}:
    doc.add_paragraph(line)
path = os.path.join(os.environ["USERPROFILE"], "Downloads", "hk_train_record.docx")
doc.save(path)
print("INIT_OK", path)
"""


def eval_dedupe_code() -> str:
    return f"""
import os, re, sys, subprocess
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

path = os.path.join(os.environ["USERPROFILE"], "Downloads", "hk_train_record.docx")
doc = Document(path)
texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
expected = ["HK Train Records"] + {EXPECTED_TRAIN_LINES!r}

def fail(message):
    print("EVAL_RESULT:FAIL " + message)
    sys.exit(1)

if texts != expected:
    fail("final train records mismatch got=" + repr(texts))
ids = []
for line in texts[1:]:
    parts = [x.strip() for x in line.split(",")]
    if len(parts) != 4:
        fail("bad line format " + line)
    ids.append(parts[1])
if len(ids) != len(set(ids)):
    fail("duplicate train ids remain")
print("EVAL_RESULT:PASS Writer train-record deduplication verified")
"""


def oracle_dedupe_code() -> str:
    return f"""
import os, subprocess, sys
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

path = os.path.join(os.environ["USERPROFILE"], "Downloads", "hk_train_record.docx")
doc = Document()
doc.add_paragraph("HK Train Records")
for line in {EXPECTED_TRAIN_LINES!r}:
    doc.add_paragraph(line)
doc.save(path)
print(path)
"""


def update_tasks() -> None:
    ref = load_yaml("tasks/windows/writer_headings_list_pagebreak.yaml")
    ref["instruction"] = (
        'In LibreOffice Writer, the document "essay_references.docx" is already open. '
        f'Add "{REFERENCE}" to the reference list as reference [3], then replace the marker "<add here>" in the fourth paragraph '
        'with a cross-reference using the reference number [3]. Save the document when finished.'
    )
    ref["init"]["params"]["steps"] = [
        {"type": "run_powershell", "script": ps_here_python(init_reference_doc_code()), "timeout": 120},
        {"type": "run_powershell", "script": open_doc_script("essay_references.docx"), "timeout": 120},
        {"type": "wait", "ms": 8000},
    ]
    ref["evaluation"]["params"].pop("supplemental_checks", None)
    md = ref["metadata"]
    md["tags"] = ["libreoffice", "writer", "docx", "reference", "cross-reference", "hard", "single_app", "evaluator_backed"]
    md["human_steps"] = 72
    md["description"] = "Linux-aligned Writer task: add a missing bibliography entry and insert its reference number at a marked location."
    md["evaluation_standard"] = "exact body text, reference-list order, inserted reference number, and marker removal are checked"
    md["alignment_status"] = "direct"
    dump_yaml("tasks/windows/writer_headings_list_pagebreak.yaml", ref)

    dedupe = load_yaml("tasks/windows/writer_toc_image_footnote.yaml")
    dedupe["instruction"] = (
        'In LibreOffice Writer, the document "hk_train_record.docx" is already open. '
        "Each record line has the format time_HH:MM:SS, train_id, station_id, platform_no. "
        "Remove duplicated train IDs so the document keeps only the first line for each train_id, preserving the original order of the kept lines. "
        "Do not change the title line. Save the document when finished."
    )
    dedupe["init"]["params"]["steps"] = [
        {"type": "run_powershell", "script": ps_here_python(init_dedupe_doc_code()), "timeout": 120},
        {"type": "run_powershell", "script": open_doc_script("hk_train_record.docx"), "timeout": 120},
        {"type": "wait", "ms": 8000},
    ]
    dedupe["evaluation"]["params"].pop("supplemental_checks", None)
    md = dedupe["metadata"]
    md["tags"] = ["libreoffice", "writer", "docx", "deduplication", "data-cleanup", "hard", "single_app", "evaluator_backed"]
    md["human_steps"] = 76
    md["description"] = "Linux-aligned Writer task: remove duplicate train-record lines so one record remains per train ID."
    md["evaluation_standard"] = "exact kept records, original order, title preservation, and absence of duplicate train IDs are checked"
    md["alignment_status"] = "direct"
    dump_yaml("tasks/windows/writer_toc_image_footnote.yaml", dedupe)


def write_checks() -> None:
    (ROOT / "evaluators/windows/checks/writer_headings_list_pagebreak.ps1").write_text(
        ps_here_python(eval_reference_code()), encoding="utf-8"
    )
    (ROOT / "evaluators/windows/checks/writer_toc_image_footnote.ps1").write_text(
        ps_here_python(eval_dedupe_code()), encoding="utf-8"
    )


def patch_oracle() -> None:
    path = ROOT / "mine/oracle_agent/generate_windows_oracle_agents.py"
    text = path.read_text(encoding="utf-8")

    replacements = {
        "writer_headings_list_pagebreak": oracle_reference_code(),
        "writer_toc_image_footnote": oracle_dedupe_code(),
    }
    for task_key, code in replacements.items():
        marker = f'    if task_key == "{task_key}":'
        start = text.index(marker)
        next_start = text.index("\n    if task_key == ", start + len(marker))
        replacement = f'{marker}\n        return {code!r}\n'
        text = text[:start] + replacement + text[next_start:]
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    update_tasks()
    write_checks()
    patch_oracle()
    print("upgraded Windows Writer tasks to direct Linux-aligned tasks")
