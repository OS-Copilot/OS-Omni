"""Web OpenBank/OpenCode/OpenDoc/OpenFinance/OpenFood evaluator rows (scan rows WEB-001..048).

Each test builds the end state a run that follows the English brief leaves and checks that the
evaluator grades what the brief asks for, and that the expectation the scan flagged is gone.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from evaluators.cua_review.core.evaluation import EvalStatus

REPO = Path(__file__).resolve().parents[1]


def _task(name: str) -> dict:
    return yaml.safe_load((REPO / "tasks/v1/web" / name).read_text(encoding="utf-8"))


# --- Chrome's Local Storage log: records are split into 32 KiB blocks -------------------------

_BLOCK = 32768


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _leveldb_log(key: str, documents: list[dict]) -> bytes:
    """A LevelDB write-ahead log with one put of ``key`` per document, as Chrome writes it."""
    user_key = b"_file://\x00\x01" + key.encode("utf-8")
    out = bytearray()
    for sequence, document in enumerate(documents, start=1):
        value = b"\x01" + json.dumps(document).encode("utf-8")
        payload = struct.pack("<QI", sequence, 1) + b"\x01" + _varint(len(user_key)) + user_key + _varint(len(value)) + value
        first = True
        while True:
            left = _BLOCK - len(out) % _BLOCK
            if left <= 7:
                out += b"\x00" * left
                continue
            fragment, payload = payload[: left - 7], payload[left - 7 :]
            kind = (1 if not payload else 2) if first else (4 if not payload else 3)
            out += struct.pack("<IHB", 0, len(fragment), kind) + fragment
            first = False
            if not payload:
                break
    return bytes(out)


# --- WEB-001 (+ WEB-003 sibling): OpenBank lena_marco -------------------------------------------

from evaluators.linux import openbank_lena_marco_dispute_security_1787714650786_886074 as lena  # noqa: E402


def _lena_document() -> dict:
    document: dict = {}
    for collection, expected in lena.DECLARED:
        rows = document.setdefault(collection, [])
        rows.append({"id": "row-%d" % len(rows), **expected})
    for row in document["transfers"]:
        row.setdefault("scheduledDate", "2026-06-01")
    for row in document["transactions"]:
        row.setdefault("date", "2026-06-01")
    return document


def _lena_verdict(monkeypatch, document: dict):
    monkeypatch.setattr(lena, "_read_document", lambda controller, key, directories: (document, "leveldb"))
    params = _task("openbank_lena_marco_dispute_security_1787714650786_886074.yaml")["evaluation"]["params"]
    return lena.LinuxOpenBankLenaMarcoDisputeSecurity1787714650786886074Evaluator().evaluate(
        {"params": params, "controller": None}
    )


def _alert(document: dict, alert_id: str) -> dict:
    return next(row for row in document["alertSettings"] if row["id"] == alert_id)


def test_openbank_lena_marco_large_purchase_push_stays_enabled_as_the_brief_says(monkeypatch):
    document = _lena_document()
    assert _alert(document, "pref-large-purchase")["push"] is True  # the seed value, which the brief keeps
    assert _lena_verdict(monkeypatch, document).status == EvalStatus.PASS
    _alert(document, "pref-large-purchase")["push"] = False  # what the old grader demanded
    result = _lena_verdict(monkeypatch, document)
    assert result.status == EvalStatus.FAIL
    assert [c["name"] for c in result.metadata["checks"] if not c["passed"]] == ["alertSettings:Large purchase"]


def test_openbank_lena_marco_second_transfer_keeps_whatever_date_the_form_had(monkeypatch):
    document = _lena_document()
    marco = next(row for row in document["transfers"] if row["recipientName"] == "Marco Li")
    posted = next(row for row in document["transactions"] if row["merchant"] == "Marco Li")
    old_expectation = dict(marco, scheduledDate="2026-06-01")
    marco["scheduledDate"] = posted["date"] = "2026-05-28"  # still posted, inside Last 30 days
    assert not lena._matches(marco, old_expectation)  # the old grader required 2026-06-01
    assert _lena_verdict(monkeypatch, document).status == EvalStatus.PASS


def test_openbank_lena_marco_stated_fields_and_single_submission_still_count(monkeypatch):
    document = _lena_document()
    next(row for row in document["transfers"] if row["recipientName"] == "Lena Wu")["scheduledDate"] = "2026-06-05"
    assert _lena_verdict(monkeypatch, document).status == EvalStatus.FAIL  # the brief dates the first transfer
    document = _lena_document()
    next(row for row in document["transactions"] if row["merchant"] == "Marco Li")["status"] = "Pending"
    assert _lena_verdict(monkeypatch, document).status == EvalStatus.FAIL  # the dispute needs a posted debit
    document = _lena_document()
    document["transfers"].append(dict(document["transfers"][0], id="again"))  # Lena Wu submitted twice
    assert _lena_verdict(monkeypatch, document).status == EvalStatus.FAIL


# --- WEB-012/013: the OpenCode command checks read Local Storage through the LevelDB format -----

from evaluators.cua_review.evaluators.linux import command_check  # noqa: E402

_GUEST_LEVELDB = 'Path("/home/user/.config/google-chrome/Default/Local Storage/leveldb")'
_PADDING = {"docs/padding.md": {"content": "x" * 20000}}  # a realistic ~20 KB workspace document


def _hook_state(committed: bool) -> dict:
    files = {
        "src/hooks/useForecast.js": {"content": "  setState(next);\n// retry later\n  return state;\n"},
        "src/services/api.js": {"content": "export const API_DELAY = 300;\nexport function fetchForecast() {}\n"},
        **_PADDING,
    }
    changes = [] if committed else [{"path": "src/hooks/useForecast.js"}, {"path": "src/services/api.js"}]
    timeline = (["Now Tune hook debug"] if committed else []) + ["09:06 Saved RevenueDashboard.jsx"]
    return {"files": files, "git": {"timeline": timeline, "changes": changes}, "terminal": ["$ npm run lint"], "view": "debug"}


def _trend_state(committed: bool) -> dict:
    files = {"src/components/TrendCard.jsx": {"content": '<div className="skeleton" aria-label="Loading" role="status" />'}, **_PADDING}
    return {
        "files": files,
        "git": {"timeline": ["Now Fix loading label"] if committed else [], "changes": [] if committed else [{"path": "src/components/TrendCard.jsx"}]},
        "terminal": ["$ npm run lint", "$ npm run lint"],
        "tabs": ["package.json", "src/views/RevenueDashboard.jsx", "src/components/TrendCard.jsx"],
        "activeFile": "src/components/TrendCard.jsx",
        "assistant": [{"role": "user", "text": "tests for loading"}],
        "view": "scm",
    }


def _command(task: str, leveldb: Path) -> str:
    command = _task(task)["evaluation"]["params"]["command"]
    assert command.count(_GUEST_LEVELDB) == 1
    return command.replace(_GUEST_LEVELDB, "Path(%r)" % str(leveldb))


def _guest_script(command: str) -> dict:
    script = command.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    done = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=60)
    return json.loads(done.stdout)


@pytest.mark.parametrize(
    "task, state",
    [("opencode_sk2_hook_debug_commit.yaml", _hook_state), ("opencode_sk2_trendcard_loading_label_commit.yaml", _trend_state)],
)
def test_opencode_final_commit_split_across_log_blocks_is_read(tmp_path, task, state):
    log = _leveldb_log("opencode.workspace.v1", [state(False), state(True)])
    first_record = 7 + 12 + 1 + 1 + len(b"_file://\x00\x01opencode.workspace.v1") + 3 + 1 + len(json.dumps(state(False)))
    assert first_record < _BLOCK < len(log)  # the committed (final) document straddles a block boundary
    (tmp_path / "000003.log").write_bytes(log)
    command = _command(task, tmp_path)

    old = _guest_script(command)  # the reader line left as a comment: the old raw byte scan
    assert old["observed"]["candidate_count"] == 1
    assert "commit_message_recorded" in old["failures"]

    new = _guest_script(command_check.expand_command(command))
    assert new["observed"]["candidate_count"] == 2
    assert new["failures"] == []


def test_opencode_newest_of_equally_complete_states_is_graded(tmp_path):
    older = _trend_state(True)
    older["tabs"] = ["src/components/TrendCard.jsx"]  # committed before package.json/RevenueDashboard were opened
    (tmp_path / "000003.log").write_bytes(_leveldb_log("opencode.workspace.v1", [older, _trend_state(True)]))
    new = _guest_script(command_check.expand_command(_command("opencode_sk2_trendcard_loading_label_commit.yaml", tmp_path)))
    assert new["failures"] == []
    (tmp_path / "000003.log").write_bytes(_leveldb_log("opencode.workspace.v1", [_trend_state(True), older]))
    new = _guest_script(command_check.expand_command(_command("opencode_sk2_trendcard_loading_label_commit.yaml", tmp_path)))
    assert new["failures"] == ["required_tabs_opened"]  # the final state closed them again


class _LocalBash:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def run_bash_script(self, script, timeout=60):
        self.scripts.append(script)
        done = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=timeout)
        return {"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr}


def test_command_check_expands_the_reader_line_and_leaves_other_commands_alone(tmp_path, monkeypatch):
    assert command_check.expand_command("echo ok") == "echo ok"
    expanded = command_check.expand_command("python3 - <<'PY'\n# @osomni:local_storage_reader\nprint(1)\nPY")
    assert command_check.LOCAL_STORAGE_READER_LINE not in expanded and "def replay_history" in expanded

    (tmp_path / "000003.log").write_bytes(_leveldb_log("opencode.workspace.v1", [_hook_state(False), _hook_state(True)]))
    params = dict(_task("opencode_sk2_hook_debug_commit.yaml")["evaluation"]["params"])
    params["command"] = _command("opencode_sk2_hook_debug_commit.yaml", tmp_path)
    guest = _LocalBash()
    result = command_check.CommandCheckEvaluator().evaluate({"params": params, "controller": guest})
    assert result.status == EvalStatus.PASS, result.message
    assert "def replay_history" in guest.scripts[-1]
    monkeypatch.setattr(command_check, "expand_command", lambda command: command)  # the evaluator before the fix
    assert command_check.CommandCheckEvaluator().evaluate({"params": params, "controller": _LocalBash()}).status == EvalStatus.FAIL


# --- WEB-015/016: OpenCode tooling_notes grades the settings the brief names ------------------

from evaluators.cua_review.evaluators.linux import opencode  # noqa: E402


def _tooling_state(**settings) -> dict:
    notes = "# Review\n\nTooling notes\nVite helpers on\nReact snippets on\n"
    return {
        "files": {"notes/review-2026-04-30.md": {"content": notes}, "README.md": {"content": "# Revenue dashboard\n"}},
        "git": {"timeline": ["Now Add tooling notes"], "changes": []},
        "assistant": [{"role": "user", "text": "git changes"}],
        "search": "review",
        "activeFile": "notes/review-2026-04-30.md",
        "panelTab": "problems",  # the brief never names the Output panel
        "collapsed": {"notes": True},  # nor expanding the notes folder (Search opens the file)
        "installedExtensions": {"Vite Tools": True, "React Snippets": True, "ESLint": True},
        "settings": {"theme": "dark", "fontSize": 14, "wordWrap": True, "minimap": True, "formatOnSave": True, "autosave": True, **settings},
        "view": "scm",
    }


def _tooling_verdict(monkeypatch, state: dict):
    monkeypatch.setattr(opencode, "_read_document", lambda controller, key, directories: (state, "leveldb"))
    params = _task("opencode_tooling_notes_settings.yaml")["evaluation"]["params"]
    return opencode.OpenCodeWorkspaceEvaluator().evaluate({"params": params, "controller": None})


def test_opencode_tooling_notes_keeps_minimap_and_autosave_on_and_ignores_unstated_panels(monkeypatch):
    checks = _task("opencode_tooling_notes_settings.yaml")["evaluation"]["params"]["state_checks"]
    assert "panelTab" not in checks and "collapsed" not in checks
    result = _tooling_verdict(monkeypatch, _tooling_state())
    assert result.status == EvalStatus.PASS, result.message
    result = _tooling_verdict(monkeypatch, _tooling_state(minimap=False, autosave=False))  # the old expectation
    assert [c["name"] for c in result.metadata["checks"] if not c["passed"]] == ["setting.minimap", "setting.autosave"]


# --- WEB-020: OpenDoc Client Plan bold is read from the heading --------------------------------

from evaluators.cua_review.evaluators.linux import opendoc  # noqa: E402

_CLIENT_PLAN_BODY = (
    "<h1>Scope</h1><ul><li style=\"background-color: #fff2a8\">Audit portal</li><li>Draft workflow</li>"
    "<li>Ship handoff</li></ul><h1>Milestones</h1><table><tr><td>Phase</td><td>Owner</td><td>Due</td><td></td></tr>"
    "<tr><td>Audit</td><td>Maya</td><td>Jul 03</td><td></td></tr><tr><td></td><td></td><td></td><td></td></tr></table>"
    "<p>Check dates</p>"
)


def _client_plan_verdict(monkeypatch, heading: str):
    html = "<html><body>" + heading + _CLIENT_PLAN_BODY + "</body></html>"
    monkeypatch.setattr(opendoc, "_read_documents", lambda controller, params: ([], "leveldb"))
    monkeypatch.setattr(
        opendoc, "_scan_files", lambda *args, **kwargs: (1, [{"path": "/home/user/Downloads/Client Plan.html", "text": html}])
    )
    params = _task("opendoc_client_plan_export_html_hard.yaml")["evaluation"]["params"]
    return opendoc.OpenDocClientPlanHtmlEvaluator().evaluate({"params": params, "controller": None}), html.lower()


@pytest.mark.parametrize(
    "heading",
    [
        '<h1 style="font-family: Aptos; color: #000000"><font size="4">Client Plan</font></h1>',  # h1 is bold
        '<h2 style="font-family: Aptos; color: #000000"><strong><font size="4">Client Plan</font></strong></h2>',
        '<h3 style="font-family: Aptos; color: black"><b><span style="font-size: 14pt">Client Plan</span></b></h3>',
    ],
)
def test_opendoc_bold_heading_written_with_tags_is_bold(monkeypatch, heading):
    result, low = _client_plan_verdict(monkeypatch, heading)
    assert not (("bold" in low) or ("font-weight" in low))  # the old whole-file substring test saw no bold
    assert result.status == EvalStatus.PASS, result.metadata.get("format_markers")


def test_opendoc_heading_unbolded_inline_is_not_bold(monkeypatch):
    result, _ = _client_plan_verdict(
        monkeypatch, '<h1 style="font-family: Aptos; color: #000000; font-weight: normal"><font size="4">Client Plan</font></h1>'
    )
    assert result.status == EvalStatus.FAIL
    assert result.metadata["format_markers"]["bold"] is False


# --- WEB-034: OpenFinance 10_2 Peak Fitness "must remain unposted" -----------------------------

from evaluators.cua_review.evaluators.linux import openfinance  # noqa: E402


def _peak_checks(monkeypatch, transactions: list[dict], next_date: str = "2026-07-17") -> dict:
    document = {"schedules": [{"payee": "Peak Fitness", "nextDate": next_date}], "transactions": transactions}
    monkeypatch.setattr(openfinance, "_read_document", lambda controller, key, directories: (document, "leveldb"))
    params = _task("openfinance_10_2.yaml")["evaluation"]["params"]
    result = openfinance.OpenFinanceEvaluator().evaluate({"params": params, "controller": None})
    return {check["name"]: check["passed"] for check in result.metadata["checks"] if "Peak Fitness" in check["name"]}


def test_openfinance_10_2_peak_fitness_left_unposted_passes_without_skip(monkeypatch):
    assert _peak_checks(monkeypatch, []) == {"schedule.Peak Fitness unposted": True}  # untouched, as the brief says
    assert _peak_checks(monkeypatch, [], next_date="2026-08-17") == {"schedule.Peak Fitness unposted": True}  # skipped
    posted = [{"payee": "Peak Fitness", "date": "2026-07-17", "amount": -45}]
    assert _peak_checks(monkeypatch, posted, next_date="2026-08-17") == {"schedule.Peak Fitness unposted": False}


# --- WEB-040/042: OpenFood qa02 filters and the qa03 scalar storage path -----------------------

from evaluators.linux import openfood_qa02_s2_ops, openfood_qa03_s2_ops  # noqa: E402


class _GuestHome:
    """Runs the evaluator's bash program locally with HOME pointed at a scratch guest home."""

    def __init__(self, home: Path) -> None:
        self.home = home

    def run_bash_script(self, script, timeout=60):
        env = dict(os.environ, HOME=str(self.home))
        done = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=timeout, env=env)
        return {"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr}


def _food_store(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00_file://\x00\x01openfood-static-state-v1\x01" + json.dumps(state).encode("utf-8"))


def test_openfood_qa02_does_not_require_an_unstated_pancake_search(tmp_path):
    store = tmp_path / ".config/osomni-openapps/launch-openfood/Default/Local Storage/leveldb/000003.log"
    _food_store(store, {"claimedCoupons": ["SAVE15"], "filters": {"q": "", "cuisine": "All", "sort": "recommended"}})
    params = _task("openfood_qa02_s2_ops.yaml")["evaluation"]["params"]
    assert "restaurant_filters_set" in params["ignored_check_names"]
    result = openfood_qa02_s2_ops.OpenFoodWorkflowEvaluator().evaluate({"params": params, "controller": _GuestHome(tmp_path)})
    check = next(c for c in result.metadata["checks"] if c["name"] == "restaurant_filters_set")
    assert check["passed"] and check["ignored"]


def test_openfood_qa03_reads_a_single_declared_storage_path(tmp_path):
    store = tmp_path / "profile/Local Storage/leveldb/000003.log"  # outside the default roots
    _food_store(store, {"claimedCoupons": ["WELCOME12"], "filters": {"q": "golden", "cuisine": "All", "sort": "recommended"}})
    params = dict(_task("openfood_qa03_s2_ops.yaml")["evaluation"]["params"])
    assert isinstance(params["local_storage_paths"], str)
    params["local_storage_paths"] = str(store)
    result = openfood_qa03_s2_ops.OpenFoodWorkflowEvaluator().evaluate({"params": params, "controller": _GuestHome(tmp_path)})
    assert result.message != "OpenFood verifier output is not readable", result.metadata
    assert result.metadata["evidence"]["source_path"] == str(store)
    passed = {c["name"]: c["passed"] for c in result.metadata["checks"]}
    assert passed["coupon_claimed"] and passed["restaurant_filters_set"]
