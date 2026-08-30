py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1); pyautogui.press('enter'); time.sleep(1)"
Start-Sleep -Seconds 2

$pyCode = @'
import os, sys, subprocess, zipfile
try:
    from openpyxl import load_workbook
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'openpyxl', '-q'])
    from openpyxl import load_workbook

path = os.path.join(os.environ['USERPROFILE'], 'Downloads', 'scores.xlsx')
if not os.path.exists(path):
    print('EVAL_RESULT:FAIL workbook_missing')
    sys.exit(1)

wb = load_workbook(path, data_only=True)
wbf = load_workbook(path, data_only=False)
if wb.sheetnames != ['Scores', 'Rules', 'Cohort Summary']:
    print(f'EVAL_RESULT:FAIL sheets_wrong {wb.sheetnames}')
    sys.exit(1)
ws, wsf = wb['Scores'], wbf['Scores']
rules = wb['Rules']
summary, summaryf = wb['Cohort Summary'], wbf['Cohort Summary']

expected_rules = [
    ('Math weight', 0.30),
    ('Science weight', 0.30),
    ('English weight', 0.25),
    ('Project weight', 0.15),
    ('Honors threshold', 85),
    ('On Track threshold', 75),
    ('Review threshold', 60),
]
if [rules.cell(r, 1).value for r in range(1, 9)] != ['Metric'] + [x[0] for x in expected_rules]:
    print('EVAL_RESULT:FAIL rules_labels_changed')
    sys.exit(1)
for idx, (_, value) in enumerate(expected_rules, start=2):
    got = rules.cell(idx, 2).value
    if got is None or abs(float(got) - float(value)) > 1e-6:
        print(f'EVAL_RESULT:FAIL rules_value_changed row={idx} got={got}')
        sys.exit(1)

headers = ['Student', 'Cohort', 'Math', 'Science', 'English', 'Project', 'Attendance', 'Total', 'Weighted Average', 'Status', 'Rank', 'Advisor Flag', 'Priority Code']
actual_headers = [wsf.cell(1, c).value for c in range(1, 14)]
if actual_headers != headers:
    print(f'EVAL_RESULT:FAIL scores_headers_wrong {actual_headers}')
    sys.exit(1)
if ws.max_row != 13 or ws.max_column < 13:
    print(f'EVAL_RESULT:FAIL scores_dimensions_wrong rows={ws.max_row} cols={ws.max_column}')
    sys.exit(1)

raw = {
    'Mina': ('Blue', 92, 88, 91, 95, 96),
    'Owen': ('Red', 61, 58, 63, 70, 89),
    'Priya': ('Blue', 84, 90, 79, 88, 93),
    'Leo': ('Green', 55, 49, 60, 57, 91),
    'Nora': ('Red', 73, 78, 69, 74, 87),
    'Sam': ('Green', 88, 82, 85, 80, 94),
    'Tara': ('Blue', 68, 72, 75, 70, 92),
    'Quinn': ('Red', 95, 94, 90, 96, 98),
    'Iris': ('Green', 77, 81, 76, 79, 88),
    'Hugo': ('Blue', 43, 52, 47, 50, 85),
    'Yara': ('Green', 89, 91, 93, 86, 97),
    'Ben': ('Red', 66, 62, 59, 64, 90),
}
weights = (0.30, 0.30, 0.25, 0.15)
def weighted(row):
    return row[1] * weights[0] + row[2] * weights[1] + row[3] * weights[2] + row[4] * weights[3]
def status(avg):
    if avg >= 85: return 'Honors'
    if avg >= 75: return 'On Track'
    if avg >= 60: return 'Review'
    return 'Recovery'

expected_order = sorted(raw.keys(), key=lambda n: (raw[n][0], -weighted(raw[n]), n))
actual_order = [ws.cell(r, 1).value for r in range(2, 14)]
if actual_order != expected_order:
    print(f'EVAL_RESULT:FAIL sort_order_wrong got={actual_order} expected={expected_order}')
    sys.exit(1)

all_avgs = {name: weighted(values) for name, values in raw.items()}
ranked = sorted(all_avgs.items(), key=lambda kv: -kv[1])
ranks = {name: idx + 1 for idx, (name, _) in enumerate(ranked)}

def norm_formula(sheet, cell):
    value = sheet[cell].value
    return str(value or '').replace('$', '').replace(' ', '').replace(';', ',').upper()

for r in range(2, 14):
    name = ws.cell(r, 1).value
    cohort, m, s, e, p, attendance = raw[name]
    if tuple(ws.cell(r, c).value for c in range(2, 8)) != (cohort, m, s, e, p, attendance):
        print(f'EVAL_RESULT:FAIL raw_row_changed row={r} name={name}')
        sys.exit(1)

    total = m + s + e + p
    avg = all_avgs[name]
    expected_status = status(avg)
    expected_flag = 'Contact' if attendance < 90 or expected_status in ('Review', 'Recovery') else 'Clear'
    expected_priority = f'{cohort}-{expected_status}-{ranks[name]}'

    total_formula = norm_formula(wsf, f'H{r}')
    avg_formula = norm_formula(wsf, f'I{r}')
    status_formula = norm_formula(wsf, f'J{r}')
    rank_formula = norm_formula(wsf, f'K{r}')
    flag_formula = norm_formula(wsf, f'L{r}')
    priority_formula = norm_formula(wsf, f'M{r}')

    if not total_formula.startswith('=') or ('SUM(' not in total_formula and '+' not in total_formula):
        print(f'EVAL_RESULT:FAIL total_not_formula row={r} formula={total_formula}')
        sys.exit(1)
    if not all(f'{col}{r}' in total_formula for col in ['C', 'D', 'E', 'F']) and f'C{r}:F{r}' not in total_formula:
        print(f'EVAL_RESULT:FAIL total_refs_wrong row={r} formula={total_formula}')
        sys.exit(1)
    if not avg_formula.startswith('=') or not all(ref in avg_formula for ref in ['RULES!B2', 'RULES!B3', 'RULES!B4', 'RULES!B5']):
        print(f'EVAL_RESULT:FAIL weighted_average_formula_wrong row={r} formula={avg_formula}')
        sys.exit(1)
    if not all(f'{col}{r}' in avg_formula for col in ['C', 'D', 'E', 'F']):
        print(f'EVAL_RESULT:FAIL weighted_average_refs_wrong row={r} formula={avg_formula}')
        sys.exit(1)
    if not status_formula.startswith('=') or 'IF(' not in status_formula:
        print(f'EVAL_RESULT:FAIL status_not_formula row={r} formula={status_formula}')
        sys.exit(1)
    for token in ['RULES!B6', 'RULES!B7', 'RULES!B8', 'HONORS', 'ONTRACK', 'REVIEW', 'RECOVERY']:
        if token not in status_formula.replace('"', ''):
            print(f'EVAL_RESULT:FAIL status_logic_missing row={r} token={token} formula={status_formula}')
            sys.exit(1)
    if not rank_formula.startswith('=') or ('RANK' not in rank_formula and 'COUNTIF' not in rank_formula):
        print(f'EVAL_RESULT:FAIL rank_not_formula row={r} formula={rank_formula}')
        sys.exit(1)
    if not flag_formula.startswith('=') or 'IF(' not in flag_formula or 'CONTACT' not in flag_formula.replace('"', '') or 'CLEAR' not in flag_formula.replace('"', ''):
        print(f'EVAL_RESULT:FAIL advisor_flag_formula_wrong row={r} formula={flag_formula}')
        sys.exit(1)
    if not priority_formula.startswith('=') or f'B{r}' not in priority_formula or f'J{r}' not in priority_formula or f'K{r}' not in priority_formula:
        print(f'EVAL_RESULT:FAIL priority_code_formula_wrong row={r} formula={priority_formula}')
        sys.exit(1)

    checks = [
        ('total', ws.cell(r, 8).value, total),
        ('avg', ws.cell(r, 9).value, avg),
    ]
    for label, got, exp in checks:
        if got is not None and abs(float(got) - exp) > 0.05:
            print(f'EVAL_RESULT:FAIL {label}_value_wrong row={r} got={got} expected={exp}')
            sys.exit(1)
    if ws.cell(r, 10).value is not None and str(ws.cell(r, 10).value) != expected_status:
        print(f'EVAL_RESULT:FAIL status_value_wrong row={r} got={ws.cell(r, 10).value} expected={expected_status}')
        sys.exit(1)
    if ws.cell(r, 11).value is not None and int(float(ws.cell(r, 11).value)) != ranks[name]:
        print(f'EVAL_RESULT:FAIL rank_value_wrong row={r} got={ws.cell(r, 11).value} expected={ranks[name]}')
        sys.exit(1)
    if ws.cell(r, 12).value is not None and str(ws.cell(r, 12).value) != expected_flag:
        print(f'EVAL_RESULT:FAIL flag_value_wrong row={r} got={ws.cell(r, 12).value} expected={expected_flag}')
        sys.exit(1)
    if ws.cell(r, 13).value is not None and str(ws.cell(r, 13).value) != expected_priority:
        print(f'EVAL_RESULT:FAIL priority_value_wrong row={r} got={ws.cell(r, 13).value} expected={expected_priority}')
        sys.exit(1)
    fmt = str(wsf.cell(r, 9).number_format or '')
    if '0.0' not in fmt.replace('"', ''):
        print(f'EVAL_RESULT:FAIL weighted_average_format_wrong row={r} fmt={fmt}')
        sys.exit(1)

if str(wsf.freeze_panes) != 'A2':
    found_freeze = False
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith('xl/worksheets/') and name.endswith('.xml'):
                xml = z.read(name).decode('utf-8', 'ignore')
                if 'state="frozen"' in xml and ('ySplit="1"' in xml or 'topLeftCell=' in xml):
                    found_freeze = True
                    break
    if not found_freeze:
        print(f'EVAL_RESULT:FAIL freeze_wrong got={wsf.freeze_panes}')
        sys.exit(1)

af = str(wsf.auto_filter.ref or '').replace('$', '')
if af != 'A1:M13':
    print(f'EVAL_RESULT:FAIL scores_autofilter_wrong got={af}')
    sys.exit(1)

comment = getattr(getattr(wsf['J1'], 'comment', None), 'text', None)
if str(comment or '').strip() != 'Status thresholds come from Rules':
    print(f'EVAL_RESULT:FAIL status_comment_wrong got={comment}')
    sys.exit(1)

cf_list = list(wsf.conditional_formatting)
red_ok = green_ok = range_ok = False
for cf in cf_list:
    sqref = str(cf.sqref).replace('$', '')
    if sqref == 'I2:I13':
        range_ok = True
    for rule in getattr(cf, 'rules', []) or []:
        operator = str(getattr(rule, 'operator', '') or '').lower()
        formulas = [str(x).strip() for x in (getattr(rule, 'formula', None) or [])]
        joined = ' '.join(formulas)
        if sqref == 'I2:I13' and '60' in joined and ('less' in operator or '<' in joined):
            red_ok = True
        if sqref == 'I2:I13' and '85' in joined and ('greater' in operator or '>=' in joined or 'equal' in operator):
            green_ok = True
if not range_ok or not red_ok or not green_ok:
    print(f'EVAL_RESULT:FAIL scores_conditional_formatting_wrong range={range_ok} red={red_ok} green={green_ok}')
    sys.exit(1)

summary_headers = ['Cohort', 'Student Count', 'Average Weighted', 'Contact Count', 'Honors Count', 'Recovery Count', 'Top Student']
if [summaryf.cell(1, c).value for c in range(1, 8)] != summary_headers:
    print('EVAL_RESULT:FAIL summary_headers_wrong')
    sys.exit(1)
if [summary.cell(r, 1).value for r in range(2, 5)] != ['Blue', 'Green', 'Red']:
    print(f'EVAL_RESULT:FAIL summary_cohort_order_wrong {[summary.cell(r, 1).value for r in range(2, 5)]}')
    sys.exit(1)
if summary.max_row != 4 or summary.max_column < 7:
    print(f'EVAL_RESULT:FAIL summary_dimensions_wrong rows={summary.max_row} cols={summary.max_column}')
    sys.exit(1)

by_cohort = {}
for name, values in raw.items():
    by_cohort.setdefault(values[0], []).append(name)

for r, cohort in enumerate(['Blue', 'Green', 'Red'], start=2):
    names = by_cohort[cohort]
    avgs = {name: all_avgs[name] for name in names}
    expected = {
        'count': len(names),
        'avg': sum(avgs.values()) / len(avgs),
        'contact': sum(1 for name in names if raw[name][5] < 90 or status(all_avgs[name]) in ('Review', 'Recovery')),
        'honors': sum(1 for name in names if status(all_avgs[name]) == 'Honors'),
        'recovery': sum(1 for name in names if status(all_avgs[name]) == 'Recovery'),
        'top': sorted(names, key=lambda n: (-all_avgs[n], n))[0],
    }
    formulas = {col: norm_formula(summaryf, f'{col}{r}') for col in ['B', 'C', 'D', 'E', 'F', 'G']}
    if not formulas['B'].startswith('=') or 'COUNTIF' not in formulas['B'] or 'SCORES!' not in formulas['B']:
        print(f'EVAL_RESULT:FAIL summary_count_formula_wrong row={r} formula={formulas["B"]}')
        sys.exit(1)
    if not formulas['C'].startswith('=') or 'AVERAGEIF' not in formulas['C'] or 'SCORES!' not in formulas['C']:
        print(f'EVAL_RESULT:FAIL summary_average_formula_wrong row={r} formula={formulas["C"]}')
        sys.exit(1)
    for col, label in [('D', 'CONTACT'), ('E', 'HONORS'), ('F', 'RECOVERY')]:
        if not formulas[col].startswith('=') or 'COUNTIFS' not in formulas[col] or label not in formulas[col] or 'SCORES!' not in formulas[col]:
            print(f'EVAL_RESULT:FAIL summary_{label.lower()}_formula_wrong row={r} formula={formulas[col]}')
            sys.exit(1)
    if not formulas['G'].startswith('=') or 'SCORES!' not in formulas['G'] or not any(tok in formulas['G'] for tok in ['INDEX', 'FILTER', 'LOOKUP']):
        print(f'EVAL_RESULT:FAIL summary_top_student_formula_wrong row={r} formula={formulas["G"]}')
        sys.exit(1)
    visible_checks = [
        ('count', summary.cell(r, 2).value, expected['count']),
        ('avg', summary.cell(r, 3).value, expected['avg']),
        ('contact', summary.cell(r, 4).value, expected['contact']),
        ('honors', summary.cell(r, 5).value, expected['honors']),
        ('recovery', summary.cell(r, 6).value, expected['recovery']),
    ]
    for label, got, exp in visible_checks:
        if got is not None and abs(float(got) - float(exp)) > 0.05:
            print(f'EVAL_RESULT:FAIL summary_{label}_value_wrong row={r} got={got} expected={exp}')
            sys.exit(1)
    if summary.cell(r, 7).value is not None and str(summary.cell(r, 7).value) != expected['top']:
        print(f'EVAL_RESULT:FAIL summary_top_value_wrong row={r} got={summary.cell(r, 7).value} expected={expected["top"]}')
        sys.exit(1)
    fmt = str(summaryf.cell(r, 3).number_format or '')
    if '0.0' not in fmt.replace('"', ''):
        print(f'EVAL_RESULT:FAIL summary_avg_format_wrong row={r} fmt={fmt}')
        sys.exit(1)

summary_af = str(summaryf.auto_filter.ref or '').replace('$', '')
if summary_af != 'A1:G4':
    print(f'EVAL_RESULT:FAIL summary_autofilter_wrong got={summary_af}')
    sys.exit(1)
summary_comment = getattr(getattr(summaryf['A1'], 'comment', None), 'text', None)
if str(summary_comment or '').strip() != 'Cohort metrics are formula-driven':
    print(f'EVAL_RESULT:FAIL summary_comment_wrong got={summary_comment}')
    sys.exit(1)
summary_cf_ok = False
for cf in list(summaryf.conditional_formatting):
    sqref = str(cf.sqref).replace('$', '')
    if sqref == 'C2:C4':
        for rule in getattr(cf, 'rules', []) or []:
            op = str(getattr(rule, 'operator', '') or '').lower()
            formulas = [str(x).strip() for x in (getattr(rule, 'formula', None) or [])]
            if '80' in ' '.join(formulas) and ('greater' in op or 'equal' in op):
                summary_cf_ok = True
if not summary_cf_ok:
    print('EVAL_RESULT:FAIL summary_conditional_formatting_missing')
    sys.exit(1)

print('EVAL_RESULT:PASS all_calc_formulas_conditional_checks_passed')
'@
$pyCode | py -3 -W ignore -
