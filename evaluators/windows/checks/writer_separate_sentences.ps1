# Post-config step 1: activate Writer window
$writer = Get-Process | Where-Object { $_.MainWindowTitle -like "*CCCH9003*LibreOffice Writer*" } | Select-Object -First 1
if ($writer) {
  $wshell = New-Object -ComObject WScript.Shell
  $null = $wshell.AppActivate($writer.Id)
}
Start-Sleep -Milliseconds 500

# Post-config step 2: save the file
py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1)"

Start-Sleep -Seconds 2

# Download gold document and compare
$goldUrl = "https://raw.githubusercontent.com/rogeriobonatti/winarenafiles/main/task_files/writer/88fe4b2d-3040-4c70-9a70-546a47764b48-WOS/eval/CCCH9003_Tutorial_guidelines_Gold.docx"
Invoke-WebRequest -Uri $goldUrl -OutFile "$env:TEMP\gold_writer.docx" -UseBasicParsing

# Compare using python-docx
py -3 -W ignore -c "
import sys
try:
    from docx import Document
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-docx', '-q'])
    from docx import Document

import os

result_path = r'C:\Users\User\Downloads\CCCH9003_Tutorial_guidelines.docx'
gold_path = os.path.join(os.environ['TEMP'], 'gold_writer.docx')

try:
    doc_result = Document(result_path)
    doc_gold = Document(gold_path)
except Exception as e:
    print(f'EVAL_RESULT:FAIL cannot open documents: {e}')
    sys.exit()

# Extract all paragraph texts
result_paras = [p.text for p in doc_result.paragraphs]
gold_paras = [p.text for p in doc_gold.paragraphs]

# Compare paragraph-by-paragraph (including blank lines)
if result_paras == gold_paras:
    print(f'EVAL_RESULT:PASS paragraphs match ({len(result_paras)} paragraphs)')
else:
    # Show first difference
    max_len = max(len(result_paras), len(gold_paras))
    for i in range(max_len):
        r = result_paras[i] if i < len(result_paras) else '<MISSING>'
        g = gold_paras[i] if i < len(gold_paras) else '<MISSING>'
        if r != g:
            print(f'EVAL_RESULT:FAIL first diff at paragraph {i}: got=[{r[:50]}] expected=[{g[:50]}]')
            break
    else:
        print(f'EVAL_RESULT:FAIL paragraph count mismatch: got={len(result_paras)} expected={len(gold_paras)}')
"
