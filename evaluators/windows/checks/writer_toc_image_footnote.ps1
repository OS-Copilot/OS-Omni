$py = @'
import os, re, sys, subprocess
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document

path = os.path.join(os.environ["USERPROFILE"], "Downloads", "hk_train_record.docx")
doc = Document(path)
texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
expected = ["HK Train Records"] + ['time_06:02:00, A101, ST-01, 1', 'time_06:05:00, B202, ST-03, 2', 'time_06:12:00, C303, ST-04, 3', 'time_06:18:00, D404, ST-05, 1', 'time_06:30:00, E505, ST-02, 4', 'time_06:44:00, F606, ST-08, 1', 'time_06:51:00, G707, ST-09, 2', 'time_07:04:00, H808, ST-11, 1']

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
'@
$py | py -3 -W ignore -
