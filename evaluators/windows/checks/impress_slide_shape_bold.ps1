$py = @'
import os, subprocess, sys
try:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-pptx", "-q"])
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

pptx_path = 'C:\\Users\\User\\Downloads\\impress_kiosk_actual.pptx'
prs = Presentation(pptx_path)

def fail(message):
    print("EVAL_RESULT:FAIL " + message)
    sys.exit(1)

if len(prs.slides) != 6:
    fail(f"expected 6 slides got {len(prs.slides)}")

reference_box = None
for idx, slide in enumerate(prs.slides, 1):
    pictures = [shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or int(shape.shape_type) == 13]
    if len(pictures) != 1:
        fail(f"slide {idx} expected exactly one picture got {len(pictures)}")
    text_shapes = [shape for shape in slide.shapes if hasattr(shape, "text") and str(shape.text or "").strip()]
    if text_shapes:
        fail(f"slide {idx} contains nonblank text shapes")
    pic = pictures[0]
    descr = pic._element.nvPicPr.cNvPr.get("descr")
    expected_descr = f"pic{idx}.png"
    if descr != expected_descr:
        fail(f"slide {idx} alt text expected {expected_descr} got {descr!r}")
    box = (int(pic.left), int(pic.top), int(pic.width), int(pic.height))
    if reference_box is None:
        reference_box = box
        if pic.width <= 0 or pic.height <= 0:
            fail("first picture has invalid size")
    elif box != reference_box:
        fail(f"slide {idx} picture placement/size differs from slide 1")

expected_files = {'C:\\Users\\User\\Documents\\helloworld_office\\impress_image_manifest.txt': 'slide1=pic1.png\nslide2=pic2.png\nslide3=pic3.png\nslide4=pic4.png\nslide5=pic5.png\nslide6=pic6.png', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_kiosk_manifest.txt': 'mode=continuous-playback\nslide_count=6\nimages=one-per-slide', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_slide_checks.txt': 'slide1=checked\nslide2=checked\nslide3=checked\nslide4=checked\nslide5=checked\nslide6=checked', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_timing_manifest.txt': 'slide1=00:05\nslide2=00:05\nslide3=00:06\nslide4=00:06\nslide5=00:07\nslide6=00:07', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_playback_manifest.txt': 'transition=none\nloop=true\nadvance=timed\ndeck=windows-kiosk', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_qc_manifest.txt': 'blank_slides=true\npicture_count=6\nlayout=reference-fit', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_accessibility_manifest.txt': 'alt_text=source-filenames\nreading_order=slide-number\ndecorative_shapes=false', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_export_manifest.txt': 'export_target=kiosk\nexpected_format=pptx\nreview_status=ready', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_asset_manifest.txt': 'asset_count=6\\nasset_folder=C:\\Users\\User\\Documents\\helloworld_office\\nnaming=pic1-pic6', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_operator_manifest.txt': 'operator=media-desk\nhandoff=continuous-playback\nstatus=staged', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_quality_gate_manifest.txt': 'gate=visual-review\nreviewer=media-desk\nblockers=none\napproval=hold-for-human', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_handoff_audit.txt': 'source_images=pic1-pic6\ndeck_path=impress_kiosk_actual.pptx\nplayback_owner=media-desk\naudit_status=ready', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_asset_receipt.csv': 'slide,image,status\n1,pic1.png,placed\n2,pic2.png,placed\n3,pic3.png,placed', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_operator_queue.txt': 'queue=kiosk-playback\nowner=media-desk\nnext_check=manual-preview\nstatus=hold', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_export_receipt.txt': 'deck=impress_kiosk_actual.pptx\nexpected=pptx\nalt_text=verified\nexport_status=staged', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_asset_timing_crosswalk.tsv': 'slide\timage\ttiming\talt_text\n1\tpic1.png\t00:05\tpic1.png\n2\tpic2.png\t00:05\tpic2.png\n3\tpic3.png\t00:06\tpic3.png\n4\tpic4.png\t00:06\tpic4.png\n5\tpic5.png\t00:07\tpic5.png\n6\tpic6.png\t00:07\tpic6.png', 'C:\\Users\\User\\Documents\\helloworld_office\\impress_bundle_dependency_index.txt': 'source=impress_image_manifest.txt\ntiming=impress_timing_manifest.txt\nreceipt=impress_export_receipt.txt\ncrosswalk=impress_asset_timing_crosswalk.tsv'}
for path, want in expected_files.items():
    if not os.path.exists(path):
        fail("missing text artifact " + path)
    want = want.replace("\\t", "\t").replace("\\n", "\n")
    got = open(path, encoding="utf-8").read().replace("\r\n", "\n").rstrip("\n")
    if got != want:
        fail("text artifact mismatch " + path)

print("EVAL_RESULT:PASS Impress Linux-aligned kiosk deck verified")
'@
$py | py -3 -W ignore -
