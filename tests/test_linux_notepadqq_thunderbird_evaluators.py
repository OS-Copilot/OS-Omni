"""Linux Gedit workspace and Thunderbird filter evaluators read what the briefs ask for."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.linux.thunderbird import ThunderbirdTaskEvaluator
from evaluators.linux.notepadqq import NotepadqqWorkspaceEvaluator


# --------------------------------------------------------------------------- Gedit workspace

OPS_INI = "[ops]\nowner=Samir Cole\nregion=eu-west\n"


class _WorkspaceController:
    def __init__(self, content: str) -> None:
        self.content = content

    def run_bash_script(self, script, timeout=30):
        payload = {"workspace_path": "/w", "results": [{"path": "config/ops.ini", "exists": True, "content": self.content}]}
        return {"output": json.dumps(payload), "returncode": 0}


def _workspace_status(content: str) -> EvalStatus:
    context = {
        "controller": _WorkspaceController(content),
        "params": {"workspace_path": "/w", "files": [{"path": "config/ops.ini", "equals": OPS_INI}]},
    }
    return NotepadqqWorkspaceEvaluator().evaluate(context).status


def test_newlines_at_end_of_file_do_not_matter() -> None:
    assert _workspace_status(OPS_INI) == EvalStatus.PASS
    assert _workspace_status(OPS_INI + "\n") == EvalStatus.PASS  # Gedit's ensure-trailing-newline
    assert _workspace_status(OPS_INI.rstrip("\n")) == EvalStatus.PASS


def test_other_whitespace_still_counts() -> None:
    assert _workspace_status(OPS_INI.replace("eu-west", "eu-west ")) == EvalStatus.FAIL
    assert _workspace_status(OPS_INI.replace("\nregion", "\n\nregion")) == EvalStatus.FAIL
    assert _workspace_status(OPS_INI + " \n") == EvalStatus.FAIL


# --------------------------------------------------------------------------- Thunderbird filters

RULES = '''version="9"
logging="no"
name="Bill64Route"
enabled="yes"
type="401"
action="Move to folder"
actionValue="mailbox://nobody@Local%20Folders/BillsDesk64"
condition="OR (subject,contains,receipt64) OR (subject,contains,invoice64)"
name="Travel64Route"
enabled="yes"
type="401"
action="Mark read"
action="Move to folder"
actionValue="mailbox://nobody@Local%20Folders/TripsDesk64"
condition="OR (subject,contains,booking64) OR (subject,contains,checkin64)"
'''


class _GuestController:
    """Runs the evaluator's guest programs locally; answers the window-close step itself."""

    def __init__(self, profile: Path, on_close=None) -> None:
        self.profile = profile
        self.on_close = on_close
        self.calls: list[str] = []

    def run_python_script(self, code, timeout=30):
        if "wmctrl" in code:
            self.calls.append("close_window")
            if self.on_close:
                self.on_close()
            return {"output": json.dumps({"matched": ["0x1"], "still_open": [], "error": None}), "returncode": 0}
        self.calls.append("read")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout)
        return {"output": done.stdout, "stderr": done.stderr, "returncode": done.returncode}


def _params(profile: Path, *, name="Bill64Route", flags=("archive", "periodic")) -> dict:
    def rule(rule_name, folder, terms):
        return {
            "name": rule_name,
            "enabled": "yes",
            "type_flags": list(flags),
            "action": "Move to folder",
            "actionValue": "mailbox://nobody@Local%20Folders/" + folder,
            "condition": [terms],
        }

    return {
        "required_folders": ["BillsDesk64", "TripsDesk64"],
        "osworld_evaluator": {
            "postconfig": [
                {"type": "close_window", "parameters": {"window_name": "Message Filters", "strict": False}},
                {"type": "sleep", "parameters": {"seconds": 0}},
            ],
            "result": {"type": "vm_file", "path": str(profile / "Mail" / "Local Folders" / "msgFilterRules.dat")},
            "expected": {
                "type": "rule",
                "rules": {
                    "expect": [
                        rule(name, "BillsDesk64", "OR (subject,contains,invoice64) OR (subject,contains,receipt64)"),
                        rule("Travel64Route", "TripsDesk64", "OR (subject,contains,booking64) OR (subject,contains,checkin64)"),
                    ]
                },
            },
        },
    }


def _profile(tmp_path: Path, rules: str | None = RULES) -> Path:
    local = tmp_path / "profile" / "Mail" / "Local Folders"
    local.mkdir(parents=True)
    for folder in ("BillsDesk64", "TripsDesk64"):
        (local / folder).write_text("")
        (local / (folder + ".msf")).write_text("")
    (local / "msgFilterRules.dat").write_text(rules if rules is not None else 'version="9"\nlogging="no"\n')
    return tmp_path / "profile"


def _evaluate(profile: Path, controller=None, **params_kwargs):
    controller = controller or _GuestController(profile)
    result = ThunderbirdTaskEvaluator().evaluate({"controller": controller, "params": _params(profile, **params_kwargs)})
    return result, controller


def test_whole_filter_blocks_are_parsed_and_matched(tmp_path) -> None:
    result, controller = _evaluate(_profile(tmp_path))
    assert result.status == EvalStatus.PASS, result.message
    rules = {rule["name"]: rule for rule in result.metadata["rules"]}
    assert rules["Travel64Route"]["actions"] == [
        {"action": "Mark read"},
        {"action": "Move to folder", "actionValue": "mailbox://nobody@Local%20Folders/TripsDesk64"},
    ]
    # The window is closed before the rule file is read.
    assert controller.calls[:2] == ["close_window", "read"]


def test_name_triggers_and_conditions_are_graded(tmp_path) -> None:
    profile = _profile(tmp_path)
    assert _evaluate(profile, name="Bills64Route")[0].status == EvalStatus.FAIL
    assert _evaluate(profile, flags=("archive", "periodic", "after_sending"))[0].status == EvalStatus.FAIL

    wrong_terms = RULES.replace("(subject,contains,receipt64)", "(subject,contains,receipt65)")
    other = _profile(tmp_path / "other", wrong_terms)
    result, _ = _evaluate(other)
    assert result.status == EvalStatus.FAIL
    assert result.metadata["failures"] == ["filter_rule:mailbox://nobody@Local%20Folders/BillsDesk64"]


def test_missing_folder_fails(tmp_path) -> None:
    profile = _profile(tmp_path)
    (profile / "Mail" / "Local Folders" / "TripsDesk64").unlink()
    (profile / "Mail" / "Local Folders" / "TripsDesk64.msf").unlink()
    result, _ = _evaluate(profile)
    assert result.status == EvalStatus.FAIL
    assert result.metadata["failures"] == ["folder:TripsDesk64"]


def test_rules_written_on_window_close_are_read(tmp_path) -> None:
    profile = _profile(tmp_path, rules=None)
    rules_file = profile / "Mail" / "Local Folders" / "msgFilterRules.dat"
    controller = _GuestController(profile, on_close=lambda: rules_file.write_text(RULES))
    result, _ = _evaluate(profile, controller=controller)
    assert result.status == EvalStatus.PASS, result.message
    assert result.metadata["postconfig"][0]["type"] == "close_window"
