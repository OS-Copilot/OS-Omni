py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1); pyautogui.press('enter'); time.sleep(1)"
Start-Sleep -Seconds 2

$pyCode = @'
import os, sys, subprocess
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-docx', '-q'])
    from docx import Document
from docx.shared import Pt

WNS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
def is_bold(run):
    if run.bold:
        return True
    rpr = run._element.find(f'{WNS}rPr')
    if rpr is not None:
        b = rpr.find(f'{WNS}b')
        if b is not None:
            val = b.get(f'{WNS}val')
            return val is None or val.lower() in ('true', '1', 'on')
    return False
def paragraph_is_bold(paragraph):
    runs = [r for r in paragraph.runs if r.text.strip()]
    if not runs:
        return False
    if any(is_bold(r) for r in runs):
        return True
    ppr = paragraph._element.find(f'{WNS}pPr')
    if ppr is not None:
        rpr = ppr.find(f'{WNS}rPr')
        if rpr is not None:
            b = rpr.find(f'{WNS}b')
            if b is not None:
                val = b.get(f'{WNS}val')
                return val is None or val.lower() in ('true', '1', 'on')
        bcs = rpr.find(f'{WNS}bCs')
        if bcs is not None:
            val = bcs.get(f'{WNS}val')
            return val is None or val.lower() in ('true', '1', 'on')
    return False

doc_path = os.path.join(os.environ['USERPROFILE'], 'Downloads', 'announcement.docx')
doc = Document(doc_path)
if len(doc.paragraphs) != 3:
    print(f'EVAL_RESULT:FAIL Step0_paragraph_count_wrong got={len(doc.paragraphs)}')
    sys.exit()

title = doc.paragraphs[0]
body1 = doc.paragraphs[1]
body2 = doc.paragraphs[2]

# Step 1: title text preserved exactly
if title.text.strip() != 'Company Announcement':
    print(f'EVAL_RESULT:FAIL Step1_title_text_wrong got=[{title.text}]')
    sys.exit()

# Step 2: title is bold
runs = [r for r in title.runs if r.text.strip()]
title_xml = title._element.xml.lower()
if not paragraph_is_bold(title) and '<w:b' not in title_xml and '<w:bcs' not in title_xml:
    print('EVAL_RESULT:FAIL Step2_title_not_bold')
    sys.exit()

# Step 3: title font size 24pt
sizes = [r.font.size for r in runs if r.font.size is not None]
if not sizes or not all(s == Pt(24) for s in sizes):
    print(f'EVAL_RESULT:FAIL Step3_title_size_wrong')
    sys.exit()

# Step 4: first body paragraph preserved exactly
expected_body1 = 'We are pleased to announce that our company has been recognized as one of the top employers in the region for the third consecutive year.'
if body1.text.strip() != expected_body1:
    print(f'EVAL_RESULT:FAIL Step4_body1_text_wrong got=[{body1.text}]')
    sys.exit()

# Step 5: second body paragraph preserved exactly
expected_body2 = 'This achievement reflects our ongoing commitment to creating a supportive and innovative workplace for all employees.'
if body2.text.strip() != expected_body2:
    print(f'EVAL_RESULT:FAIL Step5_body2_text_wrong got=[{body2.text}]')
    sys.exit()

print('EVAL_RESULT:PASS all_5_checks_passed')
'@
$pyCode | py -3 -W ignore -
