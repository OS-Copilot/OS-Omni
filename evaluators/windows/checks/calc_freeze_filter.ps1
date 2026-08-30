py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1); pyautogui.press('enter'); time.sleep(1)"
Start-Sleep -Seconds 2

$pyCode = @'
import os, sys, subprocess
try:
    from openpyxl import load_workbook
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'openpyxl', '-q'])
    from openpyxl import load_workbook
import zipfile

workbook_path = os.path.join(os.environ['USERPROFILE'], 'Downloads', 'sales.xlsx')
wb = load_workbook(workbook_path)
ws = wb.active

# Step 0: workbook structure preserved
if len(wb.sheetnames) != 1 or ws.title != 'Sales':
    print(f'EVAL_RESULT:FAIL Step0_workbook_structure sheets={wb.sheetnames}')
    sys.exit()

# Step 1: freeze panes set to A2 (header row frozen)
fp = ws.freeze_panes
if fp is None or str(fp) != 'A2':
    # XML fallback for LibreOffice-saved files
    found_freeze = False
    with zipfile.ZipFile(workbook_path) as z:
        for name in z.namelist():
            if 'worksheet' in name.lower() and name.endswith('.xml'):
                xml = z.read(name).decode('utf-8', errors='ignore')
                has_frozen_state = ('state="frozen"' in xml or "state='frozen'" in xml)
                has_row_split = ('ySplit="1"' in xml or "ySplit='1'" in xml)
                has_any_split = ('ySplit="' in xml or "ySplit='" in xml)
                has_top_left = ('topLeftCell="' in xml or "topLeftCell='" in xml)
                if has_frozen_state and (has_row_split or has_any_split or has_top_left):
                    found_freeze = True
                break
    if not found_freeze:
        if fp is None:
            print('EVAL_RESULT:FAIL Step1_no_freeze_panes')
        else:
            print(f'EVAL_RESULT:FAIL Step1_wrong_freeze got={fp} expected=A2')
        sys.exit()

# Step 2: auto-filter enabled on the full data range
af = ws.auto_filter.ref
if af is None or af == '':
    print('EVAL_RESULT:FAIL Step2_no_auto_filter')
    sys.exit()
normalized_af = str(af).replace('$', '').split('.')[-1]
if normalized_af != 'A1:E7':
    print(f'EVAL_RESULT:FAIL Step2_wrong_auto_filter_range got={af} expected=A1:E7')
    sys.exit()

# Step 3: headers preserved
if [ws['A1'].value, ws['B1'].value, ws['C1'].value, ws['D1'].value, ws['E1'].value] != ['Product', 'Region', 'Q1 Sales', 'Q2 Sales', 'Q3 Sales']:
    print('EVAL_RESULT:FAIL Step3_headers_damaged')
    sys.exit()

# Step 4: exact data table preserved
expected_rows = [
    ('Widget A', 'North', 15000, 18000, 21000),
    ('Widget B', 'South', 12000, 14000, 16000),
    ('Widget C', 'East', 22000, 19000, 25000),
    ('Widget D', 'North', 8000, 9500, 11000),
    ('Widget E', 'West', 17000, 20000, 23000),
    ('Widget F', 'South', 13000, 15500, 18000),
]
actual_rows = [tuple(ws.cell(r, c).value for c in range(1, 6)) for r in range(2, 8)]
if actual_rows != expected_rows:
    print(f'EVAL_RESULT:FAIL Step4_data_table_changed got={actual_rows}')
    sys.exit()

print('EVAL_RESULT:PASS all_4_checks_passed')
'@
$pyCode | py -3 -W ignore -
