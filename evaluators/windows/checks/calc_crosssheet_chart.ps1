py -3 -W ignore -c "import pyautogui,time; pyautogui.hotkey('ctrl','s'); time.sleep(1); pyautogui.press('enter'); time.sleep(1)"
Start-Sleep -Seconds 2

$pyCode = @'
import os, sys, subprocess, zipfile
try:
    from openpyxl import load_workbook
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'openpyxl', '-q'])
    from openpyxl import load_workbook

path = os.path.join(os.environ['USERPROFILE'], 'Downloads', 'quarterly.xlsx')
if not os.path.exists(path):
    print('EVAL_RESULT:FAIL workbook_missing')
    sys.exit(1)

wb = load_workbook(path, data_only=True)
wbf = load_workbook(path, data_only=False)
expected_sheets = ['Q1', 'Q2', 'Q3', 'Q4', 'Products', 'Summary']
if wb.sheetnames != expected_sheets:
    print(f'EVAL_RESULT:FAIL sheets_wrong {wb.sheetnames}')
    sys.exit(1)

quarter_data = {
    "Q1": [("Alpha", 120, 36000), ("Beta", 85, 25500), ("Gamma", 200, 40000), ("Delta", 95, 28500), ("Epsilon", 160, 38400)],
    "Q2": [("Gamma", 180, 36000), ("Alpha", 150, 45000), ("Epsilon", 170, 40800), ("Beta", 90, 27000), ("Delta", 110, 33000)],
    "Q3": [("Delta", 125, 37500), ("Beta", 110, 33000), ("Alpha", 130, 39000), ("Gamma", 160, 32000), ("Epsilon", 155, 37200)],
    "Q4": [("Epsilon", 190, 45600), ("Gamma", 210, 42000), ("Delta", 140, 42000), ("Alpha", 170, 51000), ("Beta", 118, 35400)],
}
for sheet, rows in quarter_data.items():
    ws = wb[sheet]
    if [ws.cell(1, c).value for c in range(1, 4)] != ['Product', 'Units', 'Revenue']:
        print(f'EVAL_RESULT:FAIL {sheet}_headers_changed')
        sys.exit(1)
    actual = [tuple(ws.cell(r, c).value for c in range(1, 4)) for r in range(2, 7)]
    if actual != rows:
        print(f'EVAL_RESULT:FAIL {sheet}_rows_changed got={actual}')
        sys.exit(1)

products = {
    "Alpha": ("Hardware", 165000),
    "Beta": ("Software", 125000),
    "Gamma": ("Hardware", 155000),
    "Delta": ("Services", 145000),
    "Epsilon": ("Software", 168000),
}
pws = wb['Products']
if [pws.cell(1, c).value for c in range(1, 4)] != ['Product', 'Category', 'Annual Target']:
    print('EVAL_RESULT:FAIL products_headers_changed')
    sys.exit(1)
actual_products = [tuple(pws.cell(r, c).value for c in range(1, 4)) for r in range(2, 7)]
if actual_products != [(k, *v) for k, v in products.items()]:
    print(f'EVAL_RESULT:FAIL products_table_changed got={actual_products}')
    sys.exit(1)

ws = wb['Summary']
wsf = wbf['Summary']
headers = ['Product', 'Category', 'Q1 Revenue', 'Q2 Revenue', 'Q3 Revenue', 'Q4 Revenue', 'Total Revenue', 'Average Revenue', 'Q4 Share', 'Target Variance', 'Target Status']
if [wsf.cell(1, c).value for c in range(1, 12)] != headers:
    print('EVAL_RESULT:FAIL summary_headers_wrong')
    sys.exit(1)
if ws.max_row != 6 or ws.max_column < 11:
    print(f'EVAL_RESULT:FAIL summary_dimensions_wrong rows={ws.max_row} cols={ws.max_column}')
    sys.exit(1)

rev = {}
for prod in products:
    rev[prod] = {q: next(row[2] for row in rows if row[0] == prod) for q, rows in quarter_data.items()}
def total(prod):
    return sum(rev[prod].values())
def avg(prod):
    return total(prod) / 4
def q4_share(prod):
    return rev[prod]['Q4'] / total(prod)
def variance(prod):
    return total(prod) - products[prod][1]

expected_order = sorted(products.keys(), key=lambda p: (products[p][0], -total(p), p))
actual_order = [ws.cell(r, 1).value for r in range(2, 7)]
if actual_order != expected_order:
    print(f'EVAL_RESULT:FAIL summary_sort_wrong got={actual_order} expected={expected_order}')
    sys.exit(1)

def norm(cell):
    return str(wsf[cell].value or '').replace('$', '').replace(' ', '').replace(';', ',').replace("'", '').upper()

for r in range(2, 7):
    prod = ws.cell(r, 1).value
    if prod not in products:
        print(f'EVAL_RESULT:FAIL unknown_product row={r} prod={prod}')
        sys.exit(1)
    expected_category, expected_target = products[prod]
    if ws.cell(r, 2).value is not None and ws.cell(r, 2).value != expected_category:
        print(f'EVAL_RESULT:FAIL category_value_wrong row={r}')
        sys.exit(1)
    category_formula = norm(f'B{r}')
    if not category_formula.startswith('=') or 'PRODUCTS' not in category_formula:
        print(f'EVAL_RESULT:FAIL category_not_lookup_formula row={r} formula={category_formula}')
        sys.exit(1)

    for idx, q in enumerate(['Q1', 'Q2', 'Q3', 'Q4'], start=3):
        cell = ws.cell(r, idx)
        formula = norm(f'{cell.column_letter}{r}')
        if not formula.startswith('=') or q not in formula or ('VLOOKUP' not in formula and 'INDEX' not in formula and 'MATCH' not in formula and 'XLOOKUP' not in formula):
            print(f'EVAL_RESULT:FAIL {q}_not_lookup_formula row={r} formula={formula}')
            sys.exit(1)
        if cell.value is not None and abs(float(cell.value) - rev[prod][q]) > 1:
            print(f'EVAL_RESULT:FAIL {q}_value_wrong row={r} got={cell.value} expected={rev[prod][q]}')
            sys.exit(1)

    checks = [
        ('G', total(prod), ['SUM(', f'C{r}:F{r}']),
        ('H', avg(prod), ['AVERAGE(', f'C{r}:F{r}']),
        ('I', q4_share(prod), [f'F{r}', f'G{r}']),
        ('J', variance(prod), [f'G{r}', 'PRODUCTS']),
    ]
    for col, exp, tokens in checks:
        formula = norm(f'{col}{r}')
        if not formula.startswith('=') or not all(tok in formula for tok in tokens):
            print(f'EVAL_RESULT:FAIL derived_formula_wrong cell={col}{r} formula={formula}')
            sys.exit(1)
        value = ws[f'{col}{r}'].value
        if value is not None and abs(float(value) - exp) > 1e-3:
            print(f'EVAL_RESULT:FAIL derived_value_wrong cell={col}{r} got={value} expected={exp}')
            sys.exit(1)

    status_formula = norm(f'K{r}')
    if not status_formula.startswith('=') or 'IF(' not in status_formula or 'ABOVETARGET' not in status_formula.replace('"', '') or 'BELOWTARGET' not in status_formula.replace('"', ''):
        print(f'EVAL_RESULT:FAIL target_status_formula_wrong row={r} formula={status_formula}')
        sys.exit(1)
    visible_status = ws.cell(r, 11).value
    exp_status = 'Above Target' if variance(prod) >= 0 else 'Below Target'
    if visible_status is not None and visible_status != exp_status:
        print(f'EVAL_RESULT:FAIL target_status_value_wrong row={r} got={visible_status} expected={exp_status}')
        sys.exit(1)
    fmt = str(wsf.cell(r, 9).number_format or '')
    if '%' not in fmt or ('0.0' not in fmt and '0,0' not in fmt):
        print(f'EVAL_RESULT:FAIL q4_share_format_wrong row={r} fmt={fmt}')
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
if af != 'A1:K6':
    print(f'EVAL_RESULT:FAIL autofilter_wrong got={af}')
    sys.exit(1)

comment = getattr(getattr(wsf['K1'], 'comment', None), 'text', None)
if str(comment or '').strip() != 'Target status is based on Products targets':
    print(f'EVAL_RESULT:FAIL target_status_comment_wrong got={comment}')
    sys.exit(1)

charts = getattr(wsf, '_charts', [])
if len(charts) != 1:
    print(f'EVAL_RESULT:FAIL chart_count_wrong got={len(charts)}')
    sys.exit(1)
chart = charts[0]
if 'bar' not in chart.__class__.__name__.lower():
    print(f'EVAL_RESULT:FAIL chart_not_bar type={chart.__class__.__name__}')
    sys.exit(1)
if 'Annual Revenue by Product' not in str(getattr(chart, 'title', '') or ''):
    print(f'EVAL_RESULT:FAIL chart_title_wrong got={getattr(chart, "title", None)}')
    sys.exit(1)

cf_list = list(wsf.conditional_formatting)
red_ok = green_ok = range_ok = False
for cf in cf_list:
    sqref = str(cf.sqref).replace('$', '')
    if sqref == 'J2:J6':
        range_ok = True
    for rule in getattr(cf, 'rules', []) or []:
        op = str(getattr(rule, 'operator', '') or '').lower()
        formulas = [str(x).strip() for x in (getattr(rule, 'formula', None) or [])]
        joined = ' '.join(formulas)
        if sqref == 'J2:J6' and '0' in joined and ('less' in op or '<' in joined):
            red_ok = True
        if sqref == 'J2:J6' and '0' in joined and ('greater' in op or '>=' in joined or 'equal' in op):
            green_ok = True
if not range_ok or not red_ok or not green_ok:
    print(f'EVAL_RESULT:FAIL conditional_formatting_wrong range={range_ok} red={red_ok} green={green_ok}')
    sys.exit(1)

print('EVAL_RESULT:PASS all_calc_crosssheet_chart_checks_passed')
'@
$pyCode | py -3 -W ignore -
