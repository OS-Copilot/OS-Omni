"""macOS OpenNote Harbor Coffee: the brief's start state matches the initializer.

scan.CSV MAC-024: the brief said OpenNote starts "logged in as Lina Park", while
the initializer waits for the prefilled login page ("Log In") and the evaluator
requires a Lina Park session at the end.  The brief now names the login page.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/v1/macos/opennote_macos1_harbor_coffee_saved_workflow.yaml"
INSTRUCTION_MAP = ROOT / "tasks/v1/cua_tasks_review_instructions.json"


def test_brief_start_state_is_the_prefilled_login_page() -> None:
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    instruction = task["instruction"]

    assert task["init"]["params"]["expected_login_label"] == "Log In"
    assert task["init"]["params"]["expected_account_name"] == "lina@opennote.local"
    assert "application logged in as Lina Park" not in instruction
    assert "login page with the Lina Park account prefilled" in instruction
    assert "must be signed in as Lina Park" in instruction
    # The evaluator still requires the Lina Park session at the end.
    params = task["evaluation"]["params"]
    assert (params["current_user_handle"], params["current_user_name"]) == ("lina", "Lina Park")

    records = json.loads(INSTRUCTION_MAP.read_text(encoding="utf-8"))["instructions"]
    assert records[task["task_id"]]["instruction"] == instruction
