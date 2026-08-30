$script = @'
import glob
import os
import shutil
import sqlite3
import tempfile


ACTUAL_DATA_PATHS = [
    os.path.expandvars(r'%USERPROFILE%\Documents\Actual'),
    os.path.expandvars(r'%APPDATA%\Actual'),
    os.path.expandvars(r'%LOCALAPPDATA%\actual'),
    os.path.expandvars(r'%APPDATA%\actual'),
]


def money_candidates(amount):
    value = float(amount)
    return sorted({int(round(abs(value) * scale)) for scale in (1, 10, 100, 1000, 10000)})


def money_matches(observed, expected):
    if observed is None:
        return False
    try:
        return abs(int(round(float(observed)))) in money_candidates(expected)
    except Exception:
        return False


def lower(value):
    return str(value or '').strip().lower()


def actual_db_candidates():
    candidates = []
    for base in ACTUAL_DATA_PATHS:
        if not os.path.exists(base):
            continue
        candidates.extend(glob.glob(os.path.join(base, '**', 'db.sqlite'), recursive=True))
        candidates.extend(glob.glob(os.path.join(base, '**', '*.sqlite'), recursive=True))
    unique = []
    seen = set()
    for candidate in candidates:
        real = os.path.abspath(candidate)
        if real not in seen:
            unique.append(real)
            seen.add(real)
    return sorted(unique, key=lambda path: os.path.getmtime(path), reverse=True)


def table_exists(cur, name):
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def qall(cur, sql, args=()):
    return [dict(row) for row in cur.execute(sql, args).fetchall()]


def qone(cur, sql, args=()):
    row = cur.execute(sql, args).fetchone()
    return dict(row) if row else None


def check_real_actual_db(cur):
    if not table_exists(cur, 'accounts') or not table_exists(cur, 'transactions'):
        return None

    account = qone(cur, "SELECT * FROM accounts WHERE lower(name)=lower(?) AND tombstone=0", ('Checking Account',))
    if not account:
        return False, 'Checking Account missing from accounts table'

    if table_exists(cur, 'v_transactions'):
        opening_rows = qall(
            cur,
            """
            SELECT t.*
            FROM v_transactions t
            LEFT JOIN accounts a ON a.id = t.account AND a.tombstone = 0
            WHERE lower(a.name)=lower(?) AND t.starting_balance_flag=1
            """,
            ('Checking Account',),
        )
    else:
        opening_rows = qall(
            cur,
            'SELECT * FROM transactions WHERE acct=? AND starting_balance_flag=1 AND tombstone=0',
            (account['id'],),
        )

    if not any(money_matches(row.get('amount'), 5000) for row in opening_rows):
        return False, 'Checking Account opening balance transaction for 5000 missing'

    balance_values = [
        account.get('balance_current'),
        account.get('balance_available'),
        account.get('balance_limit'),
    ]
    if any(value is not None for value in balance_values) and not any(money_matches(value, 5000) for value in balance_values):
        return False, f'Checking Account balance columns do not match 5000: {balance_values}'

    return True, 'Checking Account with strict 5000 opening balance found'


def check_legacy_oracle_db(cur):
    if not table_exists(cur, 'entries'):
        return None
    row = qone(
        cur,
        """
        SELECT * FROM entries
        WHERE lower(kind)=lower(?) AND lower(name)=lower(?) AND lower(memo) LIKE ? AND amount=?
        """,
        ('account', 'Checking Account', '%opening balance%', '5000.00'),
    )
    if row:
        return True, 'legacy oracle account row found'
    return False, 'legacy oracle account row missing'


failures = []
checked = 0
for source_db in actual_db_candidates():
    workdir = tempfile.mkdtemp(prefix='actual_eval_')
    try:
        local_db = os.path.join(workdir, 'db.sqlite')
        shutil.copy2(source_db, local_db)
        for suffix in ('-wal', '-shm'):
            sidecar = source_db + suffix
            if os.path.exists(sidecar):
                shutil.copy2(sidecar, local_db + suffix)
        conn = sqlite3.connect(local_db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        checked += 1
        outcome = check_real_actual_db(cur)
        if outcome is None:
            outcome = check_legacy_oracle_db(cur)
        conn.close()
        if outcome is None:
            failures.append(f'{source_db}: unsupported schema')
            continue
        ok, message = outcome
        if ok:
            print('EVAL_RESULT:PASS ' + message)
            raise SystemExit(0)
        failures.append(f'{source_db}: {message}')
    except SystemExit:
        raise
    except Exception as exc:
        failures.append(f'{source_db}: {type(exc).__name__}: {exc}')
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

if checked == 0:
    print('EVAL_RESULT:FAIL no Actual sqlite database found')
else:
    print('EVAL_RESULT:FAIL ' + ' | '.join(failures[:5]))
'@
$tmp = Join-Path $env:TEMP 'budget_create_account_eval.py'
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
