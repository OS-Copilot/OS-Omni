$script = @'

import glob, os, shutil, sqlite3, tempfile, sys
EXPECTED = {'accounts': [('Bench Checking', 5000), ('Bench Savings', 10000), ('Bench Emergency', 2500), ('Bench Travel Reserve', 1200), ('Bench Gift Fund', 650), ('Bench Utilities Escrow', 900), ('Bench Education Reserve', 1100), ('Bench Medical Reserve', 1450), ('Bench Auto Fund', 875), ('Bench Holiday Reserve', 525)], 'categories': ['Housing Reserve', 'Pantry Restock', 'Weekend Fun', 'Utilities Buffer', 'Healthcare Buffer', 'School Supplies', 'Pet Care', 'Home Repairs', 'Childcare Buffer', 'Dental Care', 'Auto Maintenance', 'Holiday Gifts'], 'budgets': [('Housing Reserve', 1500), ('Pantry Restock', 400), ('Weekend Fun', 200), ('Utilities Buffer', 275), ('Healthcare Buffer', 180), ('School Supplies', 150), ('Pet Care', 95), ('Home Repairs', 320), ('Childcare Buffer', 410), ('Dental Care', 260), ('Auto Maintenance', 340), ('Holiday Gifts', 225)], 'transactions': [('Bench Checking', 'Atlas Property', 'Housing Reserve', 1500), ('Bench Checking', 'Corner Market', 'Pantry Restock', 350), ('Bench Savings', 'Metro Utilities', 'Utilities Buffer', 125), ('Bench Emergency', 'City Clinic', 'Healthcare Buffer', 90), ('Bench Travel Reserve', 'Rail Depot', 'Weekend Fun', 210), ('Bench Checking', 'Campus Store', 'School Supplies', 84), ('Bench Gift Fund', 'North Vet', 'Pet Care', 72), ('Bench Utilities Escrow', 'Repair Hub', 'Home Repairs', 188), ('Bench Education Reserve', 'Bright Tutors', 'Childcare Buffer', 275), ('Bench Medical Reserve', 'Smile Clinic', 'Dental Care', 142), ('Bench Auto Fund', 'Torque Garage', 'Auto Maintenance', 296), ('Bench Holiday Reserve', 'Gift Market', 'Holiday Gifts', 118)], 'transfers': [('Bench Checking', 'Bench Savings', 1000), ('Bench Savings', 'Bench Emergency', 250), ('Bench Checking', 'Bench Gift Fund', 150), ('Bench Savings', 'Bench Utilities Escrow', 300), ('Bench Checking', 'Bench Education Reserve', 225), ('Bench Savings', 'Bench Medical Reserve', 180), ('Bench Checking', 'Bench Auto Fund', 240), ('Bench Gift Fund', 'Bench Holiday Reserve', 95), ('Bench Travel Reserve', 'Bench Holiday Reserve', 60), ('Bench Checking', 'Bench Travel Reserve', 130), ('Bench Savings', 'Bench Gift Fund', 85), ('Bench Medical Reserve', 'Bench Emergency', 110)]}
PATHS = [os.path.expandvars(r'%USERPROFILE%\Documents\Actual'), os.path.expandvars(r'%APPDATA%\Actual'), os.path.expandvars(r'%LOCALAPPDATA%\actual'), os.path.expandvars(r'%APPDATA%\actual')]
def money_candidates(amount): return {int(round(abs(float(amount))*s)) for s in (1,10,100,1000,10000)}
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
def has_transfer(rows, source, destination, amount):
    # Actual links each transaction to the counterpart transaction's ID;
    # transfer_id is not a group ID shared by both rows.
    by_id = {text(row.get('id')): row for row in rows if row.get('id')}
    for outgoing in rows:
        if lower(outgoing.get('account_name') or outgoing.get('account')) != lower(source):
            continue
        counterpart_id = text(outgoing.get('transfer_id') or outgoing.get('transferred_id'))
        incoming = by_id.get(counterpart_id)
        if not incoming:
            continue
        if text(incoming.get('transfer_id') or incoming.get('transferred_id')) != text(outgoing.get('id')):
            continue
        if lower(incoming.get('account_name') or incoming.get('account')) != lower(destination):
            continue
        if not money_matches(outgoing.get('amount'), amount) or not money_matches(incoming.get('amount'), amount):
            continue
        try:
            if float(outgoing['amount']) < 0 < float(incoming['amount']):
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False

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
    for src,dst,amount in EXPECTED['transfers']:
        if not has_transfer(rows, src, dst, amount):
            failures.append(f'missing transfer: {src} -> {dst} / {amount}')
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
