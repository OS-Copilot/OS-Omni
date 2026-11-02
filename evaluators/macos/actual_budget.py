"""Evaluate Actual Budget tasks on macOS via local SQLite state."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_SCAN_SCRIPT = r'''
import glob
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

params = __PARAMS_JSON__
state_root = Path(os.path.expanduser(str(params.get("state_root") or "~/Library/Application Support/Actual")))
document_root = Path(os.path.expanduser(str(params.get("document_root") or "~/Documents/Actual")))
global_store_path = state_root / "global-store.json"

result = {
    "status": "fail",
    "message": "Actual checks failed",
    "state_root": str(state_root),
    "document_root": str(document_root),
    "global_store_path": str(global_store_path),
}

store = {}
if global_store_path.exists():
    try:
        store = json.loads(global_store_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["message"] = f"failed to parse global-store.json: {exc}"
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0)

result["store"] = store
last_budget = str(store.get("lastBudget") or "").strip()
document_dir_keys = ["document-dir", "documentDir"]
resolved_document_root = document_root
for key in document_dir_keys:
    value = str(store.get(key) or "").strip()
    if value:
        resolved_document_root = Path(os.path.expanduser(value))
        break
result["resolved_document_root"] = str(resolved_document_root)

candidates = []
if last_budget:
    candidates.append(resolved_document_root / last_budget / "db.sqlite")
for path in sorted(resolved_document_root.glob("*/db.sqlite")):
    if path not in candidates:
        candidates.append(path)
for path in sorted(document_root.glob("*/db.sqlite")):
    if path not in candidates:
        candidates.append(path)

if not candidates:
    result["message"] = "no Actual db.sqlite found"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

source_db = None
for candidate in candidates:
    if candidate.exists():
        source_db = candidate
        break
if source_db is None:
    result["message"] = "no existing Actual db.sqlite candidate"
    result["db_candidates"] = [str(c) for c in candidates]
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

result["source_db"] = str(source_db)
source_dir = source_db.parent

workdir = Path(tempfile.mkdtemp(prefix="actual-eval-"))
local_db = workdir / "db.sqlite"
shutil.copy2(source_db, local_db)
for suffix in ("-wal", "-shm"):
    sidecar = source_db.with_name(source_db.name + suffix)
    if sidecar.exists():
        shutil.copy2(sidecar, workdir / ("db.sqlite" + suffix))

conn = sqlite3.connect(local_db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def table_exists(name):
    row = cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name=?", (name,)).fetchone()
    return row is not None


def qall(sql, args=()):
    return [dict(row) for row in cur.execute(sql, args).fetchall()]


def qone(sql, args=()):
    row = cur.execute(sql, args).fetchone()
    return dict(row) if row else None


def money_candidates(amount):
    # Task params are dollar amounts and Actual's DB stores integer cents
    # (tasks/macos/files/actual/blank-budget-template.zip), so round(dollars *
    # 100) is the only valid representation. The old helper multiplied by 1,
    # 10, 100, 1000 and 10000, letting wrong-magnitude entries pass (MAC-004/005).
    value = float(amount)
    return [int(round(abs(value) * 100))]


def money_matches(observed, expected):
    if observed is None:
        return False
    return abs(int(observed)) in money_candidates(expected)


def find_account(name):
    return qone("SELECT * FROM accounts WHERE lower(name)=lower(?) AND tombstone=0", (name,))


def find_category(name):
    return qone("SELECT * FROM categories WHERE lower(name)=lower(?) AND tombstone=0", (name,))


def find_payee(name):
    if table_exists("v_payees"):
        return qone("SELECT * FROM v_payees WHERE lower(name)=lower(?)", (name,))
    return qone("SELECT * FROM payees WHERE lower(name)=lower(?) AND tombstone=0", (name,))


def transaction_rows(where_sql="", args=()):
    if table_exists("v_transactions"):
        base_sql = """
            SELECT
                t.*,
                a.name AS account_name,
                c.name AS category_name,
                vp.name AS payee_name
            FROM v_transactions t
            LEFT JOIN accounts a ON a.id = t.account AND a.tombstone = 0
            LEFT JOIN categories c ON c.id = t.category AND c.tombstone = 0
            LEFT JOIN v_payees vp ON vp.id = t.payee
        """
    else:
        base_sql = """
            SELECT
                t.*,
                a.name AS account_name,
                c.name AS category_name,
                p.name AS payee_name
            FROM transactions t
            LEFT JOIN accounts a ON a.id = t.acct AND a.tombstone = 0
            LEFT JOIN categories c ON c.id = t.category AND c.tombstone = 0
            LEFT JOIN payees p ON p.id = t.description AND p.tombstone = 0
            WHERE t.tombstone = 0
        """
        if where_sql:
            base_sql += " AND " + where_sql
        return qall(base_sql, args)
    if where_sql:
        base_sql += " WHERE " + where_sql
    return qall(base_sql, args)


def find_transactions_for_account(account_name):
    if table_exists("v_transactions"):
        return transaction_rows("lower(a.name)=lower(?)", (account_name,))
    account = find_account(account_name)
    if not account:
        return []
    return qall(
        """
        SELECT
            t.*,
            a.name AS account_name,
            c.name AS category_name,
            p.name AS payee_name
        FROM transactions t
        LEFT JOIN accounts a ON a.id = t.acct AND a.tombstone = 0
        LEFT JOIN categories c ON c.id = t.category AND c.tombstone = 0
        LEFT JOIN payees p ON p.id = t.description AND p.tombstone = 0
        WHERE t.acct=? AND t.tombstone=0
        """,
        (account["id"],),
    )


mode = str(params.get("mode") or "").strip()
result["mode"] = mode

if mode == "create_account":
    account_name = str(params.get("account_name") or "").strip()
    opening_balance = float(params.get("opening_balance") or 0)
    account = find_account(account_name)
    result["account"] = account
    if not account:
        result["message"] = f"account missing: {account_name}"
    else:
        tx_rows = []
        if table_exists("v_transactions"):
            tx_rows = transaction_rows(
                "lower(a.name)=lower(?) AND t.starting_balance_flag=1",
                (account_name,),
            )
        if not tx_rows:
            tx_rows = qall(
                "SELECT * FROM transactions WHERE acct=? AND starting_balance_flag=1 AND tombstone=0",
                (account["id"],),
            )
        result["starting_balance_transactions"] = tx_rows
        observed_balances = {
            "balance_current": account.get("balance_current"),
            "balance_available": account.get("balance_available"),
            "balance_limit": account.get("balance_limit"),
        }
        result["observed_balances"] = observed_balances
        balance_ok = any(
            money_matches(value, opening_balance)
            for value in observed_balances.values()
        )
        tx_ok = any(money_matches(row.get("amount"), opening_balance) for row in tx_rows)
        if tx_ok and (balance_ok or all(value is None for value in observed_balances.values())):
            result["status"] = "pass"
            if balance_ok:
                result["message"] = "account and opening balance found"
            else:
                result["message"] = "account found and opening balance transaction found (account balance columns unset)"
        elif not balance_ok:
            result["message"] = (
                "account found but balance mismatch: "
                f"{observed_balances}"
            )
        else:
            result["message"] = "account found but opening balance transaction missing"

elif mode == "add_transactions":
    account_name = str(params.get("account_name") or "").strip()
    opening_balance_raw = params.get("opening_balance")
    required_transactions = list(params.get("transactions") or [])
    account = find_account(account_name)
    result["account"] = account
    rows = find_transactions_for_account(account_name)
    result["transactions_preview"] = rows[:20]
    failures = []
    if not account:
        failures.append(f"account missing: {account_name}")
    elif opening_balance_raw not in (None, ""):
        opening_balance = float(opening_balance_raw or 0)
        opening_rows = []
        if table_exists("v_transactions"):
            opening_rows = transaction_rows(
                "lower(a.name)=lower(?) AND t.starting_balance_flag=1",
                (account_name,),
            )
        if not opening_rows:
            opening_rows = qall(
                "SELECT * FROM transactions WHERE acct=? AND starting_balance_flag=1 AND tombstone=0",
                (account["id"],),
            )
        observed_balances = {
            "balance_current": account.get("balance_current"),
            "balance_available": account.get("balance_available"),
            "balance_limit": account.get("balance_limit"),
        }
        result["starting_balance_transactions"] = opening_rows
        result["observed_balances"] = observed_balances
        balance_ok = any(
            money_matches(value, opening_balance)
            for value in observed_balances.values()
        )
        tx_ok = any(money_matches(row.get("amount"), opening_balance) for row in opening_rows)
        if not tx_ok:
            failures.append(f"opening balance transaction missing for {account_name}: {opening_balance}")
        elif not balance_ok and not all(value is None for value in observed_balances.values()):
            failures.append(f"opening balance mismatch for {account_name}: {observed_balances}")
    for spec in required_transactions:
        payee = str(dict(spec).get("payee") or "").strip()
        category = str(dict(spec).get("category") or "").strip()
        amount = float(dict(spec).get("amount") or 0)
        matched = False
        for row in rows:
            row_payee = str(row.get("payee_name") or row.get("payee") or row.get("description") or "").strip()
            row_category = str(row.get("category_name") or row.get("category") or "").strip()
            payee_ok = True if not payee else row_payee.lower() == payee.lower()
            if payee_ok and row_category.lower() == category.lower() and money_matches(row.get("amount"), amount):
                matched = True
                break
        if not matched:
            if payee:
                failures.append(f"missing transaction: {payee} / {category} / {amount}")
            else:
                failures.append(f"missing transaction: {category} / {amount}")
    if not failures:
        result["status"] = "pass"
        result["message"] = "required transactions found"
    else:
        result["message"] = "; ".join(failures)

elif mode == "full_setup":
    failures = []
    account_specs = list(params.get("accounts") or [])
    category_specs = list(params.get("categories") or [])
    payee_specs = list(params.get("payees") or [])
    budget_specs = list(params.get("budgets") or [])
    transaction_specs = list(params.get("transactions") or [])
    transfer_specs = []
    if params.get("transfer"):
        transfer_specs.append(dict(params.get("transfer") or {}))
    for item in params.get("transfers") or []:
        if isinstance(item, dict):
            transfer_specs.append(dict(item))

    account_dump = {}
    for spec in account_specs:
        name = str(dict(spec).get("name") or "").strip()
        opening_balance = float(dict(spec).get("opening_balance") or 0)
        account = find_account(name)
        account_dump[name] = account
        if not account:
            failures.append(f"missing account: {name}")
            continue
        opening_rows = transaction_rows(
            "lower(a.name)=lower(?) AND t.starting_balance_flag=1",
            (name,),
        ) if table_exists("v_transactions") else qall(
            "SELECT * FROM transactions WHERE acct=? AND starting_balance_flag=1 AND tombstone=0",
            (account["id"],),
        )
        if not any(money_matches(row.get("amount"), opening_balance) for row in opening_rows):
            failures.append(f"opening balance transaction missing for {name}: {opening_balance}")
    result["accounts"] = account_dump

    category_dump = {}
    for spec in category_specs:
        name = str(dict(spec).get("name") or "").strip()
        category = find_category(name)
        category_dump[name] = category
        if not category:
            failures.append(f"missing category: {name}")
    result["categories"] = category_dump

    payee_dump = {}
    for spec in payee_specs:
        if isinstance(spec, str):
            name = spec.strip()
        else:
            name = str(dict(spec).get("name") or "").strip()
        payee = find_payee(name)
        payee_dump[name] = payee
        if not payee:
            failures.append(f"missing payee: {name}")
    result["payees"] = payee_dump

    budget_rows = []
    if table_exists("zero_budgets"):
        budget_rows = qall(
            "SELECT z.*, c.name AS category_name FROM zero_budgets z LEFT JOIN categories c ON z.category = c.id"
        )
    result["budget_rows_preview"] = budget_rows[:30]
    for spec in budget_specs:
        name = str(dict(spec).get("category") or "").strip()
        amount = float(dict(spec).get("amount") or 0)
        matched = False
        for row in budget_rows:
            row_name = str(row.get("category_name") or "").strip()
            if row_name.lower() == name.lower() and money_matches(row.get("amount"), amount):
                matched = True
                break
        if not matched:
            failures.append(f"missing budget amount: {name} / {amount}")

    all_rows = transaction_rows()
    result["transactions_preview"] = all_rows[:30]
    for spec in transaction_specs:
        account_name = str(dict(spec).get("account") or "").strip()
        payee = str(dict(spec).get("payee") or "").strip()
        category = str(dict(spec).get("category") or "").strip()
        amount = float(dict(spec).get("amount") or 0)
        matched = False
        for row in all_rows:
            payee_ok = (
                True
                if not payee
                else str(row.get("payee_name") or row.get("payee") or row.get("description") or "").strip().lower() == payee.lower()
            )
            if (
                str(row.get("account_name") or row.get("account") or "").strip().lower() == account_name.lower()
                and payee_ok
                and str(row.get("category_name") or row.get("category") or "").strip().lower() == category.lower()
                and money_matches(row.get("amount"), amount)
            ):
                matched = True
                break
        if not matched:
            if payee:
                failures.append(f"missing transaction: {account_name} / {payee} / {category} / {amount}")
            else:
                failures.append(f"missing transaction: {account_name} / {category} / {amount}")

    for transfer_spec in transfer_specs:
        from_account = str(transfer_spec.get("from_account") or "").strip().lower()
        to_account = str(transfer_spec.get("to_account") or "").strip().lower()
        amount = float(transfer_spec.get("amount") or 0)
        transfer_rows = [
            row for row in all_rows
            if str(row.get("account_name") or row.get("account") or "").strip().lower() in {from_account, to_account}
            and row.get("transfer_id")
            and money_matches(row.get("amount"), amount)
        ]
        result["transfer_rows"] = transfer_rows
        hit_accounts = {str(row.get("account_name") or row.get("account") or "").strip().lower() for row in transfer_rows}
        if not {from_account, to_account}.issubset(hit_accounts):
            failures.append(f"missing transfer pair: {transfer_spec}")

    if not failures:
        result["status"] = "pass"
        result["message"] = "full Actual setup found"
    else:
        result["message"] = "; ".join(failures)

else:
    result["status"] = "error"
    result["message"] = f"unsupported Actual evaluation mode: {mode}"

conn.close()
print(json.dumps(result, ensure_ascii=False))
'''


class ActualBudgetEvaluator(BaseEvaluator):
    """Guest-side evaluator for Actual Budget tasks on macOS."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        mode = str(params.get("mode") or "").strip()
        if not mode:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires params.mode")

        script = dedent(_SCAN_SCRIPT).replace("__PARAMS_JSON__", json.dumps(params, ensure_ascii=False))
        try:
            result = controller.run_python_script(script, timeout=int(params.get("timeout", 60) or 60))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Actual evaluation failed: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Actual evaluator returned non-JSON output",
                metadata={"runtime_result": result},
            )

        status_name = str(payload.get("status") or "").strip().lower()
        eval_status = EvalStatus.PASS if status_name == "pass" else EvalStatus.FAIL if status_name == "fail" else EvalStatus.ERROR
        return EvalResult(
            status=eval_status,
            message=str(payload.get("message") or "Actual evaluation completed"),
            metadata=payload,
        )
