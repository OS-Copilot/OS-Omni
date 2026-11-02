$script = @'

import glob, os, shutil, sqlite3, tempfile, sys
EXPECTED = {'accounts': [('Ops Checking', 3200), ('Emergency Buffer', 8000), ('Travel Envelope', 1200), ('Tax Reserve', 2400), ('Audit Escrow', 900), ('Vendor Holdback', 700), ('Compliance Reserve', 1100), ('Equipment Lease', 1600), ('Payroll Buffer', 4200), ('Legal Reserve', 1300), ('Training Fund', 950), ('Cloud Escrow', 2250)], 'categories': ['Utility Buffer', 'Conference Travel', 'Client Meals', 'SaaS Tools', 'Hardware Refresh', 'Launch Collateral', 'Renewal Fees', 'Security Review', 'Compliance Audit', 'Lease Payments', 'Team Offsite', 'Payroll Fees', 'Legal Filing', 'Staff Training', 'Cloud Hosting'], 'budgets': [('Utility Buffer', 250), ('Conference Travel', 600), ('Client Meals', 180), ('SaaS Tools', 75), ('Hardware Refresh', 350), ('Launch Collateral', 220), ('Renewal Fees', 140), ('Security Review', 260), ('Compliance Audit', 320), ('Lease Payments', 540), ('Team Offsite', 375), ('Payroll Fees', 425), ('Legal Filing', 360), ('Staff Training', 285), ('Cloud Hosting', 490)], 'transactions': [('Ops Checking', 'City Utilities', 'Utility Buffer', 210), ('Ops Checking', 'Skyline Air', 'Conference Travel', 480), ('Ops Checking', 'Harbor Bistro', 'Client Meals', 64.5), ('Ops Checking', 'StackTools', 'SaaS Tools', 75), ('Ops Checking', 'North Desk', 'Hardware Refresh', 315), ('Ops Checking', 'Print Depot', 'Launch Collateral', 129), ('Tax Reserve', 'License Bureau', 'Renewal Fees', 118), ('Vendor Holdback', 'Shield Audit', 'Security Review', 244), ('Compliance Reserve', 'Audit Circle', 'Compliance Audit', 290), ('Equipment Lease', 'LeaseWorks', 'Lease Payments', 515), ('Travel Envelope', 'Summit Venue', 'Team Offsite', 332), ('Payroll Buffer', 'Payroll Bureau', 'Payroll Fees', 390), ('Legal Reserve', 'Legal Desk', 'Legal Filing', 345), ('Training Fund', 'Skill Forge', 'Staff Training', 210), ('Cloud Escrow', 'Cloud Grid', 'Cloud Hosting', 470)], 'transfers': [('Ops Checking', 'Travel Envelope', 300), ('Ops Checking', 'Audit Escrow', 450), ('Tax Reserve', 'Vendor Holdback', 200), ('Ops Checking', 'Compliance Reserve', 275), ('Vendor Holdback', 'Equipment Lease', 180), ('Emergency Buffer', 'Travel Envelope', 125), ('Ops Checking', 'Payroll Buffer', 550), ('Tax Reserve', 'Legal Reserve', 260), ('Emergency Buffer', 'Training Fund', 175), ('Ops Checking', 'Cloud Escrow', 325), ('Compliance Reserve', 'Legal Reserve', 90), ('Payroll Buffer', 'Tax Reserve', 210), ('Cloud Escrow', 'Audit Escrow', 145), ('Legal Reserve', 'Compliance Reserve', 115)]}
PATHS = [os.path.expandvars(r'%USERPROFILE%\Documents\Actual'), os.path.expandvars(r'%APPDATA%\Actual'), os.path.expandvars(r'%LOCALAPPDATA%\actual'), os.path.expandvars(r'%APPDATA%\actual')]
def money_candidates(amount):
    # Task params are dollars; Actual stores integer cents (tasks/windows/files/actual/blank-budget-template.zip).
    return [int(round(abs(float(amount)) * 100))]
def money_matches(observed, expected):
    try: return abs(int(round(float(observed)))) in money_candidates(expected)
    except Exception: return False
def lower(v): return str(v or '').strip().lower()
def text(v): return str(v or '').strip()
def find_dbs():
    out=[]
    for base in PATHS:
        if os.path.exists(base):
            out += glob.glob(os.path.join(base,'**','db.sqlite'), recursive=True); out += glob.glob(os.path.join(base,'**','*.sqlite'), recursive=True)
    return sorted(set(map(os.path.abspath,out)), key=lambda x: os.path.getmtime(x), reverse=True)
def table(cur, name): return cur.execute("select name from sqlite_master where type in ('table','view') and name=?",(name,)).fetchone() is not None
def qall(cur, sql, args=()): return [dict(r) for r in cur.execute(sql,args).fetchall()]
def qone(cur, sql, args=()):
    r=cur.execute(sql,args).fetchone(); return dict(r) if r else None
def tx_rows(cur):
    if table(cur,'v_transactions'):
        return qall(cur, "select t.*, a.name account_name, c.name category_name, vp.name payee_name from v_transactions t left join accounts a on a.id=t.account and a.tombstone=0 left join categories c on c.id=t.category and c.tombstone=0 left join v_payees vp on vp.id=t.payee")
    if not table(cur,'transactions'): return []
    return qall(cur, "select t.*, a.name account_name, c.name category_name, p.name payee_name from transactions t left join accounts a on a.id=t.acct and a.tombstone=0 left join categories c on c.id=t.category and c.tombstone=0 left join payees p on p.id=t.description and p.tombstone=0 where t.tombstone=0")
def check(cur):
    failures=[]
    if not table(cur,'accounts') or not table(cur,'transactions'): return ['unsupported Actual schema']
    for name, bal in EXPECTED['accounts']:
        acct=qone(cur,"select * from accounts where lower(name)=lower(?) and tombstone=0",(name,))
        if not acct: failures.append('missing account: '+name); continue
        if table(cur,'v_transactions'):
            start=[r for r in tx_rows(cur) if lower(r.get('account_name'))==lower(name) and str(r.get('starting_balance_flag') or '') in {'1','True','true'}]
        else:
            start=qall(cur,"select * from transactions where acct=? and starting_balance_flag=1 and tombstone=0",(acct['id'],))
        if not any(money_matches(r.get('amount'), bal) for r in start): failures.append(f'missing opening balance: {name} / {bal}')
    for name in EXPECTED['categories']:
        if not qone(cur,"select * from categories where lower(name)=lower(?) and tombstone=0",(name,)): failures.append('missing category: '+name)
    budgets=[]
    if table(cur,'zero_budgets'): budgets=qall(cur,'select z.*, c.name category_name from zero_budgets z left join categories c on z.category=c.id')
    for cat, amount in EXPECTED['budgets']:
        if not any(lower(r.get('category_name'))==lower(cat) and money_matches(r.get('amount'), amount) for r in budgets): failures.append(f'missing budget: {cat} / {amount}')
    rows=tx_rows(cur)
    for account,payee,cat,amount in EXPECTED['transactions']:
        if not any(lower(r.get('account_name') or r.get('account'))==lower(account) and lower(r.get('payee_name') or r.get('payee') or r.get('description'))==lower(payee) and lower(r.get('category_name') or r.get('category'))==lower(cat) and money_matches(r.get('amount'), amount) for r in rows): failures.append(f'missing transaction: {account} / {payee} / {cat} / {amount}')
    by_transfer={}
    for r in rows:
        tid=text(r.get('transfer_id'))
        if tid: by_transfer.setdefault(tid,[]).append(r)
    for src,dst,amount in EXPECTED['transfers']:
        ok=False
        for pair in by_transfer.values():
            src_rows=[r for r in pair if lower(r.get('account_name') or r.get('account'))==lower(src) and money_matches(r.get('amount'), amount)]
            dst_rows=[r for r in pair if lower(r.get('account_name') or r.get('account'))==lower(dst) and money_matches(r.get('amount'), amount)]
            if src_rows and dst_rows:
                try:
                    if any(float(a.get('amount') or 0)*float(b.get('amount') or 0)<0 for a in src_rows for b in dst_rows): ok=True; break
                except Exception: ok=True; break
        if not ok: failures.append(f'missing transfer: {src} -> {dst} / {amount}')
    return failures
failures=[]
for source in find_dbs():
    tmp=tempfile.mkdtemp(prefix='actual_eval_')
    try:
        local=os.path.join(tmp,'db.sqlite'); shutil.copy2(source,local)
        for suf in ('-wal','-shm'):
            if os.path.exists(source+suf): shutil.copy2(source+suf, local+suf)
        con=sqlite3.connect(local); con.row_factory=sqlite3.Row; cur=con.cursor(); f=check(cur); con.close()
        if not f: print('EVAL_RESULT:PASS Actual Budget hard setup verified'); sys.exit(0)
        failures.append(source+': '+'; '.join(f[:8]))
    except Exception as e: failures.append(source+': '+type(e).__name__+': '+str(e))
    finally: shutil.rmtree(tmp, ignore_errors=True)
print('EVAL_RESULT:FAIL '+(' | '.join(failures[:3]) if failures else 'no Actual sqlite database found'))

'@
$tmp = Join-Path $env:TEMP ('actual_budget_hard_eval_' + [guid]::NewGuid().ToString('N') + '.py')
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
