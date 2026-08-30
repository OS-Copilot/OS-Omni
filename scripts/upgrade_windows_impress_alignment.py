from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = r"C:\Users\User\Documents\helloworld_office"
PPTX = r"C:\Users\User\Downloads\impress_kiosk_actual.pptx"


TEXT_ARTIFACTS = {
    rf"{WORKSPACE}\impress_image_manifest.txt": "slide1=pic1.png\nslide2=pic2.png\nslide3=pic3.png\nslide4=pic4.png\nslide5=pic5.png\nslide6=pic6.png",
    rf"{WORKSPACE}\impress_kiosk_manifest.txt": "mode=continuous-playback\nslide_count=6\nimages=one-per-slide",
    rf"{WORKSPACE}\impress_slide_checks.txt": "slide1=checked\nslide2=checked\nslide3=checked\nslide4=checked\nslide5=checked\nslide6=checked",
    rf"{WORKSPACE}\impress_timing_manifest.txt": "slide1=00:05\nslide2=00:05\nslide3=00:06\nslide4=00:06\nslide5=00:07\nslide6=00:07",
    rf"{WORKSPACE}\impress_playback_manifest.txt": "transition=none\nloop=true\nadvance=timed\ndeck=windows-kiosk",
    rf"{WORKSPACE}\impress_qc_manifest.txt": "blank_slides=true\npicture_count=6\nlayout=reference-fit",
    rf"{WORKSPACE}\impress_accessibility_manifest.txt": "alt_text=source-filenames\nreading_order=slide-number\ndecorative_shapes=false",
    rf"{WORKSPACE}\impress_export_manifest.txt": "export_target=kiosk\nexpected_format=pptx\nreview_status=ready",
    rf"{WORKSPACE}\impress_asset_manifest.txt": rf"asset_count=6\nasset_folder={WORKSPACE}\nnaming=pic1-pic6",
    rf"{WORKSPACE}\impress_operator_manifest.txt": "operator=media-desk\nhandoff=continuous-playback\nstatus=staged",
    rf"{WORKSPACE}\impress_quality_gate_manifest.txt": "gate=visual-review\nreviewer=media-desk\nblockers=none\napproval=hold-for-human",
    rf"{WORKSPACE}\impress_handoff_audit.txt": "source_images=pic1-pic6\ndeck_path=impress_kiosk_actual.pptx\nplayback_owner=media-desk\naudit_status=ready",
    rf"{WORKSPACE}\impress_asset_receipt.csv": "slide,image,status\n1,pic1.png,placed\n2,pic2.png,placed\n3,pic3.png,placed",
    rf"{WORKSPACE}\impress_operator_queue.txt": "queue=kiosk-playback\nowner=media-desk\nnext_check=manual-preview\nstatus=hold",
    rf"{WORKSPACE}\impress_export_receipt.txt": "deck=impress_kiosk_actual.pptx\nexpected=pptx\nalt_text=verified\nexport_status=staged",
    rf"{WORKSPACE}\impress_asset_timing_crosswalk.tsv": "slide\timage\ttiming\talt_text\n1\tpic1.png\t00:05\tpic1.png\n2\tpic2.png\t00:05\tpic2.png\n3\tpic3.png\t00:06\tpic3.png\n4\tpic4.png\t00:06\tpic4.png\n5\tpic5.png\t00:07\tpic5.png\n6\tpic6.png\t00:07\tpic6.png",
    rf"{WORKSPACE}\impress_bundle_dependency_index.txt": "source=impress_image_manifest.txt\ntiming=impress_timing_manifest.txt\nreceipt=impress_export_receipt.txt\ncrosswalk=impress_asset_timing_crosswalk.tsv",
}


def load_yaml(relpath: str):
    return yaml.safe_load((ROOT / relpath).read_text(encoding="utf-8"))


def dump_yaml(relpath: str, data) -> None:
    (ROOT / relpath).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def ps_here_python(code: str) -> str:
    return "$py = @'\n" + code.strip() + "\n'@\n$py | py -3 -W ignore -\n"


def init_code() -> str:
    return rf"""
import os, struct, subprocess, sys, zlib
from pathlib import Path
try:
    from pptx import Presentation
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-pptx", "-q"])
    from pptx import Presentation

desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
workspace = Path({WORKSPACE!r})
downloads = Path(os.environ["USERPROFILE"]) / "Downloads"
workspace.mkdir(parents=True, exist_ok=True)
downloads.mkdir(parents=True, exist_ok=True)

def png(path, color):
    w, h = 640, 360
    def chunk(t, data):
        x = t + data
        return struct.pack(">I", len(data)) + x + struct.pack(">I", zlib.crc32(x) & 0xffffffff)
    raw = b"".join(b"\\x00" + bytes(color) * w for _ in range(h))
    path.write_bytes(b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

colors = [(220,70,70),(70,130,220),(80,180,120),(210,170,60),(150,90,210),(60,180,190)]
for i, color in enumerate(colors, 1):
    png(desktop / f"pic{{i}}.png", color)

prs = Presentation()
blank = prs.slide_layouts[6]
prs.slides.add_slide(blank)
prs.save({PPTX!r})
print("INIT_OK", {PPTX!r})
"""


def launch_script() -> str:
    return rf"""
$pptPath = "{PPTX}"
$candidates = @(
  "C:\Program Files\LibreOffice\program\simpress.exe",
  "C:\Program Files\LibreOffice\program\soffice.exe",
  "C:\Program Files (x86)\LibreOffice\program\simpress.exe",
  "C:\Program Files (x86)\LibreOffice\program\soffice.exe"
)
$exe = $candidates | Where-Object {{ Test-Path $_ }} | Select-Object -First 1
if (-not $exe) {{ throw "LibreOffice Impress not found" }}
if ($exe -like "*\soffice.exe") {{
  Start-Process -FilePath $exe -ArgumentList @("--impress", $pptPath)
}} else {{
  Start-Process -FilePath $exe -ArgumentList @($pptPath)
}}
"""


def eval_code() -> str:
    return rf"""
import os, subprocess, sys
try:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-pptx", "-q"])
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

pptx_path = {PPTX!r}
prs = Presentation(pptx_path)

def fail(message):
    print("EVAL_RESULT:FAIL " + message)
    sys.exit(1)

if len(prs.slides) != 6:
    fail(f"expected 6 slides got {{len(prs.slides)}}")

reference_box = None
for idx, slide in enumerate(prs.slides, 1):
    pictures = [shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or int(shape.shape_type) == 13]
    if len(pictures) != 1:
        fail(f"slide {{idx}} expected exactly one picture got {{len(pictures)}}")
    text_shapes = [shape for shape in slide.shapes if hasattr(shape, "text") and str(shape.text or "").strip()]
    if text_shapes:
        fail(f"slide {{idx}} contains nonblank text shapes")
    pic = pictures[0]
    descr = pic._element.nvPicPr.cNvPr.get("descr")
    expected_descr = f"pic{{idx}}.png"
    if descr != expected_descr:
        fail(f"slide {{idx}} alt text expected {{expected_descr}} got {{descr!r}}")
    box = (int(pic.left), int(pic.top), int(pic.width), int(pic.height))
    if reference_box is None:
        reference_box = box
        if pic.width <= 0 or pic.height <= 0:
            fail("first picture has invalid size")
    elif box != reference_box:
        fail(f"slide {{idx}} picture placement/size differs from slide 1")

expected_files = {TEXT_ARTIFACTS!r}
for path, want in expected_files.items():
    if not os.path.exists(path):
        fail("missing text artifact " + path)
    got = open(path, encoding="utf-8").read().replace("\\r\\n", "\\n").rstrip("\\n")
    if got != want:
        fail("text artifact mismatch " + path)

print("EVAL_RESULT:PASS Impress Linux-aligned kiosk deck verified")
"""


def oracle_code() -> str:
    return rf"""
import os, subprocess, sys
from pathlib import Path
try:
    from pptx import Presentation
    from pptx.util import Inches
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-pptx", "-q"])
    from pptx import Presentation
    from pptx.util import Inches

desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
workspace = Path({WORKSPACE!r})
workspace.mkdir(parents=True, exist_ok=True)
prs = Presentation()
blank = prs.slide_layouts[6]
while len(prs.slides):
    r_id = prs.slides._sldIdLst[0].rId
    prs.part.drop_rel(r_id)
    del prs.slides._sldIdLst[0]
for i in range(1, 7):
    slide = prs.slides.add_slide(blank)
    pic = slide.shapes.add_picture(str(desktop / f"pic{{i}}.png"), Inches(0.5), Inches(0.5), width=Inches(9.0), height=Inches(5.1))
    pic._element.nvPicPr.cNvPr.set("descr", f"pic{{i}}.png")
prs.save({PPTX!r})
for path, content in {TEXT_ARTIFACTS!r}.items():
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content + "\\n", encoding="utf-8")
print({PPTX!r})
"""


def update_task() -> None:
    task = load_yaml("tasks/windows/impress_slide_shape_bold.yaml")
    task["instruction"] = (
        "In LibreOffice Impress, the presentation impress_kiosk_actual.pptx is already open. "
        "Create a kiosk deck with six blank slides. Insert exactly one image on each slide using the Desktop images pic1.png through pic6.png in order. "
        "Each slide must contain no text boxes or decorative shapes, only the one picture. Use the same placement and fitted size for every picture. "
        "Set the picture alternative-text description on each slide to the exact source filename for that slide: pic1.png through pic6.png. "
        f"Also create the required kiosk manifest files under {WORKSPACE}: impress_image_manifest.txt, impress_kiosk_manifest.txt, "
        "impress_slide_checks.txt, impress_timing_manifest.txt, impress_playback_manifest.txt, impress_qc_manifest.txt, "
        "impress_accessibility_manifest.txt, impress_export_manifest.txt, impress_asset_manifest.txt, impress_operator_manifest.txt, "
        "impress_quality_gate_manifest.txt, impress_handoff_audit.txt, impress_asset_receipt.csv, impress_operator_queue.txt, "
        "impress_export_receipt.txt, impress_asset_timing_crosswalk.tsv, and impress_bundle_dependency_index.txt. Save when finished."
    )
    task["init"]["params"]["steps"] = [
        {"type": "run_powershell", "script": ps_here_python(init_code()), "timeout": 120},
        {"type": "run_powershell", "script": launch_script(), "timeout": 120},
        {"type": "wait", "ms": 5000},
    ]
    task["evaluation"]["params"] = {
        "check_id": "impress_slide_shape_bold",
        "stdout_contains": "EVAL_RESULT:PASS",
        "timeout": 120,
    }
    md = task["metadata"]
    md["tags"] = ["libreoffice", "impress", "pptx", "kiosk", "images", "alt-text", "hard", "single_app", "evaluator_backed"]
    md["human_steps"] = 140
    md["description"] = "Linux-aligned Impress task: create a six-slide kiosk deck with one fitted image per blank slide, alt text, and manifest bundle."
    md["evaluation_standard"] = "six slides, exactly one picture per slide, no text shapes, exact alt text, equal placement/size, and all manifest files are checked"
    md["alignment_status"] = "direct"
    dump_yaml("tasks/windows/impress_slide_shape_bold.yaml", task)


def write_check() -> None:
    (ROOT / "evaluators/windows/checks/impress_slide_shape_bold.ps1").write_text(
        ps_here_python(eval_code()), encoding="utf-8"
    )


def patch_oracle() -> None:
    path = ROOT / "mine/oracle_agent/generate_windows_oracle_agents.py"
    text = path.read_text(encoding="utf-8")
    marker = '    if task_key == "impress_slide_shape_bold":'
    start = text.index(marker)
    next_start = text.index("\n    if task_key == ", start + len(marker))
    replacement = f'{marker}\n        return {oracle_code()!r}\n'
    path.write_text(text[:start] + replacement + text[next_start:], encoding="utf-8")


if __name__ == "__main__":
    update_task()
    write_check()
    patch_oracle()
    print("upgraded Windows Impress task to direct Linux-aligned kiosk deck")
