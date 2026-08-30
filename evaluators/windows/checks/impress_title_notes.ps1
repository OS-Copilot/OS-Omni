py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1); pyautogui.press('enter'); time.sleep(1)"
Start-Sleep -Seconds 2

$pyCode = @'
import os, sys, subprocess
try:
    from pptx import Presentation
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-pptx', '-q'])
    from pptx import Presentation

ppt_path = os.path.join(os.environ['USERPROFILE'], 'Downloads', 'kickoff.pptx')
prs = Presentation(ppt_path)

# Step 1: slide count stays exactly 2
if len(prs.slides) != 2:
    print(f'EVAL_RESULT:FAIL Step1_slide_count got={len(prs.slides)}')
    sys.exit()

# Step 2: slide 1 title is "Project Kickoff Meeting"
s1 = prs.slides[0]
all_s1_texts = [' '.join(str(sh.text).split()) for sh in s1.shapes if hasattr(sh, 'text') and sh.text.strip()]
if 'Project Kickoff Meeting' not in all_s1_texts:
    print(f'EVAL_RESULT:FAIL Step2_title_wrong got={all_s1_texts}')
    sys.exit()

# Step 3: slide 1 subtitle preserved exactly
if 'Q2 2025 Planning Session' not in all_s1_texts:
    print(f'EVAL_RESULT:FAIL Step3_subtitle_wrong got={all_s1_texts}')
    sys.exit()

# Step 4: slide 2 has the exact speaker note text
s2 = prs.slides[1]
try:
    notes = s2.notes_slide.notes_text_frame.text.strip()
except:
    notes = ''
normalized_notes = ' '.join(notes.split())
expected_notes = 'Remember to demo the live system'
if normalized_notes != expected_notes:
    print(f'EVAL_RESULT:FAIL Step4_notes_wrong got=[{notes[:60]}]')
    sys.exit()

# Step 5: slide 2 content preserved exactly
if s2.shapes.title.text.strip() != 'Agenda':
    print('EVAL_RESULT:FAIL Step5_slide2_title_damaged')
    sys.exit()
slide2_text = '\n'.join(shape.text for shape in s2.shapes if hasattr(shape, 'text'))
normalized_slide2 = '\n'.join(line.strip() for line in slide2_text.splitlines() if line.strip())
expected_slide2 = 'Agenda\n1. Introductions\n2. Goals\n3. Timeline\n4. Q&A'
if normalized_slide2 != expected_slide2:
    print(f'EVAL_RESULT:FAIL Step5_slide2_body_damaged got=[{normalized_slide2}]')
    sys.exit()

print('EVAL_RESULT:PASS all_5_checks_passed')
'@
$pyCode | py -3 -W ignore -
