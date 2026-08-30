py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1); pyautogui.press('enter'); time.sleep(1)"
Start-Sleep -Seconds 2

$pyCode = @'
import os, sys, subprocess, zipfile
try:
    from pptx import Presentation
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-pptx', '-q'])
    from pptx import Presentation
from lxml import etree

pptx_path = os.path.join(os.environ['USERPROFILE'], 'Downloads', 'conference.pptx')
prs = Presentation(pptx_path)

# Step 1: still 5 slides
if len(prs.slides) != 5:
    print(f'EVAL_RESULT:FAIL Step1_slide_count expected=5 got={len(prs.slides)}')
    sys.exit()

# Step 2: slide order - verify by title projection only.
expected_titles = ['Tech Conference 2025', 'About Us', 'Key Topics', 'Closing', 'Speakers']
actual_titles = []
for s in prs.slides:
    title_text = ''
    for sh in s.shapes:
        if hasattr(sh, 'text') and str(sh.text or '').strip():
            title_text = str(sh.text).splitlines()[0].strip()
            break
    actual_titles.append(title_text)
if actual_titles != expected_titles:
    print(f'EVAL_RESULT:FAIL Step2_slide_order_wrong got={actual_titles}')
    sys.exit()

# Step 3: Slide 1 title has a Fly In style entrance animation
ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
with zipfile.ZipFile(pptx_path) as z:
    slide1_xml = z.read('ppt/slides/slide1.xml')
    root1 = etree.fromstring(slide1_xml)
    timing = root1.findall('.//p:timing', ns)
    anim_els = root1.findall('.//p:anim', ns) + root1.findall('.//p:animEffect', ns) + root1.findall('.//p:set', ns)
    has_anim_s1 = len(timing) > 0 or len(anim_els) > 0
    # Also check for any child of timing
    if not has_anim_s1:
        for t in timing:
            if len(t) > 0:
                has_anim_s1 = True
    slide1_text = slide1_xml.decode('utf-8', errors='ignore').lower()
if not has_anim_s1:
    print('EVAL_RESULT:FAIL Step3_no_animation_slide1')
    sys.exit()
fly_in_markers = ['fly', 'fly-in', 'fly in', 'entr', 'animate']
if not any(marker in slide1_text for marker in fly_in_markers):
    print('EVAL_RESULT:FAIL Step3_animation_not_fly_in_like')
    sys.exit()
slide1_visible = '\n'.join(sh.text for sh in prs.slides[0].shapes if hasattr(sh, 'text'))
normalized_slide1 = '\n'.join(line.strip() for line in slide1_visible.splitlines() if line.strip())
expected_slide1 = 'Tech Conference 2025\nInnovation Meets Execution'
if normalized_slide1 != expected_slide1:
    print(f'EVAL_RESULT:FAIL Step3_slide1_content_changed got=[{normalized_slide1}]')
    sys.exit()

# Step 4: Slide 3 (Key Topics) has animation for bullet items one-by-one
with zipfile.ZipFile(pptx_path) as z:
    slide3_xml = z.read('ppt/slides/slide3.xml')
    xml3_str = slide3_xml.decode('utf-8', errors='ignore')
    xml3_lower = xml3_str.lower()
    has_anim_s3 = 'anim' in xml3_lower or 'timing' in xml3_lower
if not has_anim_s3:
    print('EVAL_RESULT:FAIL Step4_no_animation_slide3')
    sys.exit()
paragraph_count = 0
for sh in prs.slides[2].shapes:
    if hasattr(sh, 'text_frame'):
        for para in sh.text_frame.paragraphs:
            if para.text.strip():
                paragraph_count += 1
slide3_text = '\n'.join(sh.text for sh in prs.slides[2].shapes if hasattr(sh, 'text'))
expected_slide3 = 'Key Topics\nMachine Learning\nCloud Infrastructure\nCybersecurity\nDevOps Best Practices'
normalized_slide3 = '\n'.join(line.strip() for line in slide3_text.splitlines() if line.strip())
if normalized_slide3 != expected_slide3:
    print(f'EVAL_RESULT:FAIL Step4_slide3_content_wrong got=[{normalized_slide3}]')
    sys.exit()
if paragraph_count != 5:
    print(f'EVAL_RESULT:FAIL Step4_bullets_missing expected=5 got={paragraph_count}')
    sys.exit()
target_refs = xml3_lower.count('spid')
click_markers = xml3_lower.count('nodeclick') + xml3_lower.count('onclick')
seq_markers = xml3_lower.count('<p:seq') + xml3_lower.count('<p:par')
if click_markers == 0 and seq_markers == 0 and target_refs < paragraph_count:
    print('EVAL_RESULT:FAIL Step4_not_one_by_one_animation')
    sys.exit()

# Step 5: Slide 2 has an inserted image in the top-right area and original body content is preserved
s2 = prs.slides[1]
has_image = False
image_top_right = False
picture_count = 0
slide_width = prs.slide_width
slide_height = prs.slide_height
for sh in s2.shapes:
    counted_picture = False
    if sh.shape_type is not None:
        st = str(sh.shape_type)
        if 'PICTURE' in st or 'LINKED' in st:
            has_image = True
            picture_count += 1
            counted_picture = True
            try:
                if int(sh.left) > int(slide_width) * 0.55 and int(sh.top) < int(slide_height) * 0.45:
                    image_top_right = True
            except:
                pass
        try:
            if int(sh.shape_type) == 13 and not counted_picture:  # MSO_SHAPE_TYPE.PICTURE
                has_image = True
                picture_count += 1
                if int(sh.left) > int(slide_width) * 0.55 and int(sh.top) < int(slide_height) * 0.45:
                    image_top_right = True
        except:
            pass
if not has_image:
    # Fallback: check for image relationships in slide2
    with zipfile.ZipFile(pptx_path) as z:
        rels_path = 'ppt/slides/_rels/slide2.xml.rels'
        if rels_path in z.namelist():
            rels_xml = z.read(rels_path).decode('utf-8', errors='ignore')
            if 'image' in rels_xml.lower():
                has_image = True
if not has_image:
    print('EVAL_RESULT:FAIL Step5_no_image_slide2')
    sys.exit()
if picture_count != 1:
    print(f'EVAL_RESULT:FAIL Step5_picture_count_wrong count={picture_count}')
    sys.exit()
if not image_top_right:
    print('EVAL_RESULT:FAIL Step5_image_not_top_right')
    sys.exit()
s2_text = '\n'.join(sh.text for sh in s2.shapes if hasattr(sh, 'text'))
normalized_s2_lines = [line.strip() for line in s2_text.splitlines() if line.strip()]
if 'About Us' not in normalized_s2_lines or 'We are a leading technology company focused on AI and cloud solutions.' not in normalized_s2_lines:
    print(f'EVAL_RESULT:FAIL Step5_slide2_body_damaged got={normalized_s2_lines}')
    sys.exit()
# Step 6: All slides have a Fade transition
fade_count = 0
with zipfile.ZipFile(pptx_path) as z:
    for i in range(1, 6):
        slide_path = f'ppt/slides/slide{i}.xml'
        if slide_path in z.namelist():
            sxml = z.read(slide_path)
            root = etree.fromstring(sxml)
            transition = root.find('.//p:transition', ns)
            if transition is None:
                continue
            if transition.find('p:fade', ns) is not None:
                fade_count += 1
if fade_count != 5:
    print(f'EVAL_RESULT:FAIL Step6_fade_transitions expected=5 got={fade_count}')
    sys.exit()
with zipfile.ZipFile(pptx_path) as z:
    slide4_xml = z.read('ppt/slides/slide4.xml').decode('utf-8', errors='ignore').lower()
    slide5_xml = z.read('ppt/slides/slide5.xml').decode('utf-8', errors='ignore').lower()
if 'closing' not in slide4_xml or 'speakers' not in slide5_xml:
    print('EVAL_RESULT:FAIL Step6_slide_xml_order_mismatch')
    sys.exit()

# Step 7: key slide content preserved
all_text = ''
for s in prs.slides:
    for sh in s.shapes:
        if hasattr(sh, 'text'):
            all_text += sh.text + '\n'
if 'Machine Learning' not in all_text or 'Thank you for attending. See you next year!' not in all_text:
    print('EVAL_RESULT:FAIL Step7_content_damaged')
    sys.exit()
closing_text = '\n'.join(sh.text for sh in prs.slides[3].shapes if hasattr(sh, 'text'))
normalized_closing = '\n'.join(line.strip() for line in closing_text.splitlines() if line.strip())
if normalized_closing != 'Closing\nThank you for attending. See you next year!':
    print(f'EVAL_RESULT:FAIL Step7_closing_slide_changed got=[{normalized_closing}]')
    sys.exit()
speakers_text = '\n'.join(sh.text for sh in prs.slides[4].shapes if hasattr(sh, 'text'))
normalized_speakers = '\n'.join(line.strip() for line in speakers_text.splitlines() if line.strip())
if 'Hard mode: transition audit complete' not in normalized_speakers:
    print(f'EVAL_RESULT:FAIL Step7_hard_footer_missing got=[{normalized_speakers}]')
    sys.exit()
for required_speaker_line in ['Speakers', 'Dr. Smith - AI Research', 'Ms. Chen - Cloud Arch', 'Mr. Kumar - Security']:
    if required_speaker_line not in normalized_speakers.splitlines():
        print(f'EVAL_RESULT:FAIL Step7_speakers_slide_changed got=[{normalized_speakers}]')
        sys.exit()
if 'Hard mode: transition audit complete' not in normalized_speakers:
    print(f'EVAL_RESULT:FAIL Step7_speakers_slide_changed got=[{normalized_speakers}]')
    sys.exit()

print('EVAL_RESULT:PASS all_7_checks_passed')
'@
$pyCode | py -3 -W ignore -
