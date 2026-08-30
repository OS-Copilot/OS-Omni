$writer = Get-Process | Where-Object { $_.MainWindowTitle -like "*communication_notes*LibreOffice Writer*" } | Select-Object -First 1
if (-not $writer) {
  $writer = Get-Process | Where-Object { $_.MainWindowTitle -like "*LibreOffice Writer*" } | Select-Object -First 1
}
if ($writer) {
  $wshell = New-Object -ComObject WScript.Shell
  $null = $wshell.AppActivate($writer.Id)
}
Start-Sleep -Milliseconds 500

py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1.0)"
Start-Sleep -Seconds 1

$pyCode = @'
import sys
import subprocess

try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-docx', '-q'])
    from docx import Document

result_path = r'C:\Users\User\Downloads\communication_notes.docx'
expected = [
    'At the start of each week, post your objectives in the team channel.',
    '',
    'Before lunch every day, provide a short status update with blockers.',
    '',
    'By wednesday evening, summarize decisions made in meetings and link the related documents.',
    '',
    'On friday afternoon, publish a concise report that includes completed work, open risks, and next steps.',
    '',
    'At month end, write a retrospective that highlights one success, one failure, and one process change.'
]

try:
    doc = Document(result_path)
except Exception as e:
    print(f'EVAL_RESULT:FAIL cannot open document: {e}')
    sys.exit()

actual = [p.text for p in doc.paragraphs]
while actual and actual[-1] == '':
    actual.pop()

if actual == expected:
    print('EVAL_RESULT:PASS paragraphs match expected split format')
else:
    print(f'EVAL_RESULT:FAIL paragraph mismatch got={len(actual)} expected={len(expected)}')
    max_len = max(len(actual), len(expected))
    for i in range(max_len):
        a = actual[i] if i < len(actual) else '<MISSING>'
        e = expected[i] if i < len(expected) else '<MISSING>'
        if a != e:
            print(f'DIFF at {i}: got=[{a}] expected=[{e}]')
            break
'@
$pyCode | py -3 -W ignore -
