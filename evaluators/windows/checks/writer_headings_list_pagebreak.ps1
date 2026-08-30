$py = @'
import os, sys, subprocess
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

path = os.path.join(os.environ["USERPROFILE"], "Downloads", "essay_references.docx")
doc = Document(path)
texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
body = "\n".join(texts)
reference = 'Steinberg, F. M., Bearden, M. M., & Keen, C. L. (2003). Cocoa and chocolate flavonoids: Implications for cardiovascular health. Journal of the American Dietetic Association, 103(2), 215-223. doi: 10.1053/jada.2003.50028'

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
'@
$py | py -3 -W ignore -
