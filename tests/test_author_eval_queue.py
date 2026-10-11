"""Tests for scripts/author_eval_queue.py using a fake runner.

No GUI, VM, simulator, or real model is touched: every execution test drives
the public ``run_queue`` entry point with a fake ``runner`` and a fake
``preflight_fn`` on a temporary results root. The only test that touches
``default_runner`` stubs the platform ``run_benchmark_command`` so no
runtime ever starts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import author_eval_queue as queue


def _write_report(path: Path, platform: str = "ios", passed: bool = True) -> Path:
    path.write_text(
        json.dumps(
            {
                "passed": passed,
                "platform": platform,
                "checks": {"recorded": "simctl-devices, simctl-runtimes, appium"},
                "detail": "test-recorded preflight",
                "checked_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_initial_fail_evidence(
    path: Path, platform: str = "ios", task_ids=None
) -> Path:
    tasks = queue.load_manifest_tasks(queue.MANIFEST_PATH, platform)
    wanted = set(task_ids) if task_ids is not None else None
    probe = path.parent / "precheck-probe.txt"
    probe.write_text("precheck-fail-probe", encoding="utf-8")
    payload = {}
    for task in tasks:
        if wanted is not None and task["task_id"] not in wanted:
            continue
        task_file = queue._resolve_task_file(task["task_path"])
        payload[task["task_id"]] = {
            "status": "FAIL",
            "task_sha256": queue.sha256_file(task_file),
            "task_implementation_sha256": queue.task_implementation_hash(
                task_file
            ),
            "evidence": str(probe),
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_gate(path: Path, platform: str = "ios", task_ids=None, **overrides) -> Path:
    report = _write_report(path.parent / "preflight-report.json", platform)
    evidence = _write_initial_fail_evidence(
        path.parent / "initial-fails.json", platform, task_ids=task_ids
    )
    payload = {
        "platform": platform,
        "formal_run_approved": True,
        "clone_state": "fresh",
        "approved_by": "test-owner",
        "env_preflight_passed": True,
        "env_preflight_report": str(report),
        "initial_fail_evidence": str(evidence),
        "manifest_sha256": queue.manifest_hash(),
        "code_version": queue.code_version_hash(platform),
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_approval(path: Path) -> Path:
    path.write_text(json.dumps({"approved": True, "by": "main-agent"}), encoding="utf-8")
    return path


def _expected_for_task(task_id: str, platform: str = "ios") -> dict:
    entries = {e["task_id"]: e for e in queue.build_plan_entries(platform)}
    return queue.expected_evidence(entries[task_id], platform)


def _ok_preflight(platform: str, **kwargs):
    return True, "fake-preflight-ok"


def _fail_preflight(platform: str, **kwargs):
    return False, "fake-preflight-broken"


class FakeRunner:
    """Stand-in for the platform benchmark runner.

    ``plan`` maps task_id -> status. Every call is recorded; the fake writes
    its own result.json into the attempt directory it is given, so assertions
    do not mirror implementation internals.
    """

    def __init__(self, plan: dict[str, str], default: str = "PASS") -> None:
        self.plan = plan
        self.default = default
        self.calls: list[str] = []

    def __call__(self, entry, task_dir, **kwargs):
        task_id = entry["task_id"]
        self.calls.append(task_id)
        status = self.plan.get(task_id, self.default)
        task_dir = Path(task_dir)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "result.json").write_text(
            json.dumps({"task_id": task_id, "status": status}), encoding="utf-8"
        )
        return status, {"fake": True, "exit_code": 0 if status == "PASS" else 1}


class StepLimitTests(unittest.TestCase):
    def test_cap_keeps_lower_original(self) -> None:
        self.assertEqual(queue.effective_max_steps(100), 100)
        self.assertEqual(queue.effective_max_steps(44), 44)

    def test_cap_clamps_high_original(self) -> None:
        self.assertEqual(queue.effective_max_steps(240), 180)
        self.assertEqual(queue.effective_max_steps(1000), 180)
        self.assertEqual(queue.effective_max_steps(180), 180)


class PlanTests(unittest.TestCase):
    def test_each_platform_has_48_tasks(self) -> None:
        for platform in ("ios", "macos"):
            with self.subTest(platform=platform):
                entries = queue.build_plan_entries(platform)
                self.assertEqual(len(entries), 48)
                for entry in entries:
                    self.assertEqual(entry["model"], "deepseek_flash")
                    self.assertEqual(entry["action_mode"], "code_adapter")
                    self.assertEqual(entry["observation_mode"], "screenshot_only")
                    self.assertLessEqual(entry["effective_max_steps"], 180)
                    self.assertLessEqual(
                        entry["effective_max_steps"], entry["original_max_steps"]
                    )

    def test_plan_covers_both_step_limits(self) -> None:
        originals = {
            entry["original_max_steps"] for entry in queue.build_plan_entries("ios")
        }
        self.assertIn(100, originals)
        self.assertIn(240, originals)

    def test_results_root_is_independent_of_android_local_eval(self) -> None:
        for platform in ("ios", "macos"):
            root = queue.platform_results_root(platform)
            self.assertNotIn("local_eval", root.parts)
            self.assertEqual(root.parent.name, "author_eval")

    def test_main_refuses_local_eval_root(self) -> None:
        code = queue.main(
            ["--platform", "ios", "--plan", "--results-root", "/tmp/x/local_eval"]
        )
        self.assertEqual(code, 2)


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-"))

    def _run(self, gate: Path):
        return queue.run_queue(
            platform="ios",
            results_root=self.tmp / "results" / "ios",
            gate_path=gate,
            limit=1,
            runner=FakeRunner({}),
            preflight_fn=_ok_preflight,
        )

    def test_missing_gate_rejected(self) -> None:
        with self.assertRaises(queue.GateError):
            self._run(self.tmp / "no-such-gate.json")

    def test_wrong_platform_gate_rejected(self) -> None:
        with self.assertRaises(queue.GateError):
            self._run(_write_gate(self.tmp / "gate.json", platform="macos"))

    def test_unapproved_gate_rejected(self) -> None:
        with self.assertRaises(queue.GateError):
            self._run(_write_gate(self.tmp / "gate.json", formal_run_approved=False))

    def test_audit_complete_clone_state_rejected(self) -> None:
        for state in ("audit_complete", "AUDIT_COMPLETE", "audit-complete"):
            with self.subTest(state=state), self.assertRaises(queue.GateError):
                self._run(_write_gate(self.tmp / "gate.json", clone_state=state))

    def test_preflight_failure_rejected_without_running(self) -> None:
        runner = FakeRunner({})
        with self.assertRaises(queue.QueueError):
            queue.run_queue(
                platform="ios",
                results_root=self.tmp / "results" / "ios",
                gate_path=_write_gate(self.tmp / "gate.json"),
                limit=1,
                runner=runner,
                preflight_fn=_fail_preflight,
            )
        self.assertEqual(runner.calls, [])

    def test_gate_requires_preflight_record(self) -> None:
        gate = _write_gate(self.tmp / "gate.json")
        payload = json.loads(gate.read_text(encoding="utf-8"))
        del payload["env_preflight_passed"]
        del payload["env_preflight_report"]
        gate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(queue.GateError):
            self._run(gate)

    def test_gate_requires_initial_fail_evidence(self) -> None:
        gate = _write_gate(self.tmp / "gate.json")
        payload = json.loads(gate.read_text(encoding="utf-8"))
        del payload["initial_fail_evidence"]
        gate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(queue.GateError):
            self._run(gate)

    def test_gate_rejects_hash_mismatch(self) -> None:
        with self.assertRaises(queue.GateError):
            self._run(_write_gate(self.tmp / "gate.json", manifest_sha256="0" * 64))
        with self.assertRaises(queue.GateError):
            self._run(_write_gate(self.tmp / "gate.json", code_version="0" * 64))

    def test_gate_rejects_incomplete_initial_evidence(self) -> None:
        gate = _write_gate(self.tmp / "gate.json")
        payload = json.loads(gate.read_text(encoding="utf-8"))
        evidence_path = Path(payload["initial_fail_evidence"])
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence.pop(next(iter(evidence)))
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(queue.GateError):
            self._run(gate)


class PreflightProbeTests(unittest.TestCase):
    def test_which_only_never_passes_without_probes(self) -> None:
        with mock.patch.object(queue.shutil, "which", return_value="/usr/bin/xcrun"):
            with mock.patch.object(
                queue, "_run_cmd", return_value=(True, "no devices here")
            ):
                ok, _ = queue.preflight_check(
                    "ios", ios_clone_source_udid="AA112233"
                )
        self.assertFalse(ok)

    def test_macos_requires_real_tart_home(self) -> None:
        with mock.patch.object(queue.shutil, "which", return_value="/usr/bin/tart"):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TART_HOME", None)
                ok, detail = queue.preflight_check(
                    "macos", macos_base_vm_name="base", macos_vm_provider="tart"
                )
        self.assertFalse(ok)
        self.assertIn("TART_HOME", detail)


class LockTests(unittest.TestCase):
    def test_live_pid_lock_refuses_duplicate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lock-") as raw:
            lock = Path(raw) / "queue.lock"
            lock.write_text(str(os.getpid()), encoding="utf-8")
            with self.assertRaises(queue.QueueError):
                queue.acquire_lock(lock)

    def test_stale_lock_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lock-") as raw:
            lock = Path(raw) / "queue.lock"
            lock.write_text("999999999", encoding="utf-8")
            queue.acquire_lock(lock)
            content = lock.read_text(encoding="utf-8").strip().split()[0]
            self.assertEqual(content, str(os.getpid()))
            queue.release_lock(lock)
            self.assertFalse(lock.exists())

    def test_two_processes_race_for_one_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lock-race-") as raw:
            lock = str(Path(raw) / "queue.lock")
            worker = (
                "import sys, time; sys.path.insert(0, %r); sys.path.insert(0, %r);"
                "import author_eval_queue as q;"
                "q.acquire_lock(%r);"
                "open(%r, 'a').write('held\\n'); time.sleep(2); q.release_lock(%r)"
                % (
                    str(REPO_ROOT),
                    str(SCRIPTS_DIR),
                    lock,
                    str(Path(raw) / "marker"),
                    lock,
                )
            )
            first = subprocess.Popen([sys.executable, "-c", worker])
            try:
                # Wait until the first worker actually holds the lock.
                for _ in range(200):
                    if (Path(raw) / "marker").exists():
                        break
                    time.sleep(0.05)
                else:
                    self.fail("first lock holder never started")
                second = subprocess.run(
                    [sys.executable, "-c", worker],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertNotEqual(
                    second.returncode,
                    0,
                    "second concurrent queue must not acquire the lock",
                )
            finally:
                first.wait(timeout=30)
            self.assertEqual(first.returncode, 0)


class QueueBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="author-eval-"))
        self.results = self.tmp / "results" / "ios"
        self.gate = _write_gate(self.tmp / "gate.json")

    def _run(self, runner: FakeRunner, **kwargs):
        params = {
            "platform": "ios",
            "results_root": self.results,
            "gate_path": self.gate,
            "runner": runner,
            "preflight_fn": _ok_preflight,
        }
        params.update(kwargs)
        return queue.run_queue(**params)

    def _task_dir(self, task_id: str) -> Path:
        return self.results / queue.safe_task_dir(task_id)

    def test_fail_pauses_whole_queue(self) -> None:
        entries = queue.build_plan_entries("ios")
        failing = entries[1]["task_id"]
        runner = FakeRunner({failing: "FAIL"})
        summary = self._run(runner, limit=5)
        self.assertTrue(summary["paused"])
        self.assertIn("FAIL", summary["paused_reason"])
        self.assertEqual(runner.calls, [entries[0]["task_id"], failing])
        persisted = queue.load_queue(self.results / "queue.json")
        self.assertIsNotNone(persisted.get("paused_reason"))

    def test_error_pauses_whole_queue(self) -> None:
        entries = queue.build_plan_entries("ios")
        runner = FakeRunner({entries[0]["task_id"]: "ERROR"})
        summary = self._run(runner, limit=5)
        self.assertTrue(summary["paused"])
        self.assertIn("ERROR", summary["paused_reason"])
        self.assertEqual(len(runner.calls), 1)

    def test_three_new_completions_pause_for_link_audit(self) -> None:
        summary = self._run(FakeRunner({}), limit=5)
        self.assertTrue(summary["paused"])
        self.assertIn("new completions", summary["paused_reason"])
        self.assertEqual(summary["passed"], 3)

    def test_reuse_does_not_reset_audit_counter(self) -> None:
        entries = queue.build_plan_entries("ios")
        first_dir = self._task_dir(entries[0]["task_id"])
        first_dir.mkdir(parents=True, exist_ok=True)
        queue.audit_confirm_pass(
            first_dir, _expected_for_task(entries[0]["task_id"]), "auditor"
        )
        summary = self._run(FakeRunner({}), limit=5)
        self.assertTrue(summary["paused"])
        self.assertIn("new completions", summary["paused_reason"])
        self.assertEqual(summary["reused"], 1)
        self.assertEqual(summary["passed"], 3)

    def test_paused_queue_needs_explicit_approval_to_resume(self) -> None:
        runner = FakeRunner({})
        first = self._run(runner, limit=5)
        self.assertTrue(first["paused"])
        stalled = self._run(runner, limit=5)
        self.assertTrue(stalled["paused"])
        self.assertEqual(stalled.get("processed", 0), 0)
        with self.assertRaises(queue.QueueError):
            self._run(runner, limit=5, resume_after_audit=True)
        approval = _write_approval(self.tmp / "approval.json")
        resumed = self._run(
            runner, limit=6, resume_after_audit=True, audit_approval_file=approval
        )
        self.assertEqual(resumed["processed"], 3)

    def test_valid_result_is_reused_without_running(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        queue.audit_confirm_pass(
            task_dir, _expected_for_task(task_id), "auditor"
        )
        runner = FakeRunner({})
        self._run(runner, limit=5)
        self.assertNotIn(task_id, runner.calls)
        self.assertIn(entries[1]["task_id"], runner.calls)

    def test_entry_status_alone_never_skips(self) -> None:
        entries = queue.build_plan_entries("ios")
        self._run(FakeRunner({}), limit=1)
        persisted = queue.load_queue(self.results / "queue.json")
        self.assertEqual(persisted["entries"][0]["status"], "pending_audit")
        # Forge a stale terminal status with no valid verdict behind it.
        persisted["entries"][0]["status"] = "passed"
        queue.save_queue(self.results / "queue.json", persisted)
        runner = FakeRunner({})
        self._run(runner, limit=1)
        self.assertIn(entries[0]["task_id"], runner.calls)

    def test_unmarked_pass_result_is_not_reused(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "result.json").write_text(
            json.dumps({"task_id": task_id, "status": "PASS"}), encoding="utf-8"
        )
        runner = FakeRunner({})
        self._run(runner, limit=1)
        self.assertIn(task_id, runner.calls)

    def test_unaudited_pass_is_not_reused(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        first = self._run(FakeRunner({}), limit=1)
        self.assertEqual(first["passed"], 1)
        verdict = queue.read_verdict(self._task_dir(task_id))
        self.assertIsNotNone(verdict)
        self.assertIsNot(verdict.get("valid"), True)
        runner = FakeRunner({task_id: "FAIL"})
        summary = self._run(runner, limit=1)
        self.assertIn(task_id, runner.calls)
        self.assertTrue(summary["paused"])
        attempt_dirs = sorted(self._task_dir(task_id).glob("attempt_*"))
        self.assertEqual(len(attempt_dirs), 2)

    def test_stale_attempt_result_is_never_reused(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        # A stale directory from an older attempt (never a live index) holds
        # a PASS that must not leak into the current attempt's reading.
        stale = task_dir / "attempt_000"
        stale.mkdir(parents=True, exist_ok=True)
        (stale / "result.json").write_text(
            json.dumps({"task_id": task_id, "status": "PASS"}), encoding="utf-8"
        )
        runner = FakeRunner({task_id: "FAIL"})
        summary = self._run(runner, limit=1)
        self.assertIn(task_id, runner.calls)
        self.assertTrue(summary["paused"])
        # The stale attempt evidence is preserved untouched.
        self.assertEqual(
            json.loads((stale / "result.json").read_text(encoding="utf-8"))["status"],
            "PASS",
        )
        # The current unique attempt directory decides on its own evidence.
        self.assertEqual(queue.read_result_status(task_dir / "attempt_001"), "FAIL")
        self.assertIsNone(queue.read_result_status(task_dir / "attempt_002"))

    def test_valid_hash_mismatch_forces_retest(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        expected = _expected_for_task(task_id)
        queue.audit_confirm_pass(task_dir, expected, "auditor")
        tampered = dict(queue.read_verdict(task_dir))
        tampered["task_sha256"] = "0" * 64
        (task_dir / "verdict.json").write_text(
            json.dumps(tampered), encoding="utf-8"
        )
        runner = FakeRunner({})
        self._run(runner, limit=1)
        self.assertIn(task_id, runner.calls)

    def test_confirmed_model_fail_is_final(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        queue.confirm_model_fail(
            task_dir, _expected_for_task(task_id), "auditor"
        )
        runner = FakeRunner({})
        summary = self._run(runner, limit=2)
        self.assertNotIn(task_id, runner.calls)
        self.assertEqual(summary["skipped_confirmed"], 1)
        self.assertIn(entries[1]["task_id"], runner.calls)
        # A second run still never retests the confirmed failure.
        runner2 = FakeRunner({})
        summary2 = self._run(runner2, limit=2)
        self.assertNotIn(task_id, runner2.calls)
        self.assertEqual(summary2["skipped_confirmed"], 1)

    def test_excluded_without_audit_mark_pauses(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        queue.write_verdict(task_dir, status="environment_excluded", valid=False)
        runner = FakeRunner({})
        summary = self._run(runner, limit=1)
        self.assertNotIn(task_id, runner.calls)
        self.assertTrue(summary["paused"])
        self.assertIn("audit", summary["paused_reason"])

    def test_excluded_result_is_retested_only_after_explicit_audit(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        queue.audit_exclude_for_retest(
            task_dir, _expected_for_task(task_id), "auditor"
        )
        runner = FakeRunner({})
        summary = self._run(runner, limit=1)
        self.assertIn(task_id, runner.calls)
        self.assertEqual(summary["retested_excluded"], 1)

    def test_attempt_evidence_is_preserved(self) -> None:
        entries = queue.build_plan_entries("ios")
        self._run(FakeRunner({entries[0]["task_id"]: "FAIL"}), limit=1)
        task_dir = self._task_dir(entries[0]["task_id"])
        attempt = task_dir / "attempt_001"
        self.assertTrue((attempt / "result.json").is_file())
        self.assertTrue((attempt / "attempt_record.json").is_file())
        self.assertTrue((task_dir / "run_meta.json").is_file())
        self.assertTrue((task_dir / "verdict.json").is_file())

    def test_run_meta_records_hash_limits_and_model(self) -> None:
        entries = queue.build_plan_entries("ios")
        self._run(FakeRunner({}), limit=1)
        meta_path = self._task_dir(entries[0]["task_id"]) / "run_meta.json"
        self.assertTrue(meta_path.is_file())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["model"], "deepseek_flash")
        self.assertEqual(meta["action_mode"], "code_adapter")
        self.assertEqual(meta["observation_mode"], "screenshot_only")
        self.assertEqual(meta["task_sha256"], queue.sha256_file(REPO_ROOT / entries[0]["task_path"]))
        self.assertEqual(
            meta["task_implementation_sha256"],
            queue.task_implementation_hash(REPO_ROOT / entries[0]["task_path"]),
        )
        self.assertEqual(meta["original_max_steps"], entries[0]["original_max_steps"])
        self.assertEqual(meta["effective_max_steps"], entries[0]["effective_max_steps"])
        self.assertIn("code_version", meta)
        self.assertIn("git_revision", meta)
        self.assertIn("attempt_dir", meta)


class DefaultRunnerEvidenceTests(unittest.TestCase):
    def test_ios_direct_mode_bypasses_clone_source(self) -> None:
        entry = queue.build_plan_entries("ios")[0]
        fake_benchmark = mock.MagicMock()
        fake_benchmark.run_benchmark_command = mock.MagicMock(return_value=0)
        module_name = "platforms.ios.runners.benchmark"
        with tempfile.TemporaryDirectory(prefix="direct-runner-") as raw:
            attempt = Path(raw) / "attempt_001"
            attempt.mkdir(parents=True)
            with mock.patch.dict(sys.modules, {module_name: fake_benchmark}):
                with mock.patch.object(
                    queue,
                    "_load_committed_runtime_defaults",
                    return_value={
                        "appium_host": "127.0.0.1",
                        "appium_port": 4723,
                        "clone_source_udid": "BASELINE",
                    },
                ):
                    queue.default_runner(
                        entry,
                        attempt,
                        platform="ios",
                        ios_direct_udid="BOOTED-DEVICE",
                    )
        args = fake_benchmark.run_benchmark_command.call_args.args[0]
        self.assertIsNone(args.clone_source_udid)
        self.assertEqual(args.direct_udid, "BOOTED-DEVICE")

    def test_author_evidence_hooks_are_mandatory(self) -> None:
        entry = queue.build_plan_entries("ios")[0]
        fake_benchmark = mock.MagicMock()
        fake_benchmark.run_benchmark_command = mock.MagicMock(return_value=0)
        module_name = "platforms.ios.runners.benchmark"
        with tempfile.TemporaryDirectory(prefix="evidence-hooks-") as raw:
            attempt = Path(raw) / "attempt_001"
            attempt.mkdir(parents=True)
            with mock.patch.dict(
                os.environ,
                {
                    "OS_OMNI_DEEPSEEK_REQUEST_AUDIT": "",
                    "OS_OMNI_CAPTURE_IOS_FINAL_STATE": "",
                    "OS_OMNI_CAPTURE_MACOS_FINAL_STATE": "",
                    "OS_OMNI_WDA_DERIVED_DATA": "",
                },
            ), mock.patch.dict(sys.modules, {module_name: fake_benchmark}):
                with mock.patch.object(
                    queue,
                    "_load_committed_runtime_defaults",
                    return_value={
                        "appium_host": "127.0.0.1",
                        "appium_port": 4723,
                        "clone_source_udid": "AA112233",
                    },
                ):
                    queue.default_runner(entry, attempt, platform="ios")
                self.assertEqual(os.environ["OS_OMNI_DEEPSEEK_REQUEST_AUDIT"], "1")
                self.assertEqual(os.environ["OS_OMNI_CAPTURE_IOS_FINAL_STATE"], "1")
                self.assertEqual(os.environ["OS_OMNI_CAPTURE_MACOS_FINAL_STATE"], "")
                self.assertEqual(
                    os.environ["OS_OMNI_WDA_DERIVED_DATA"],
                    str(queue.REPO_ROOT.parent / "ios" / "wda-derived-data"),
                )

    def test_missing_result_is_error_despite_exit_zero(self) -> None:
        entries = queue.build_plan_entries("ios")
        entry = entries[0]
        fake_benchmark = mock.MagicMock()
        fake_benchmark.run_benchmark_command = mock.MagicMock(return_value=0)
        with tempfile.TemporaryDirectory(prefix="norunner-") as raw:
            attempt = Path(raw) / "attempt_001"
            attempt.mkdir(parents=True)
            module_name = "platforms.ios.runners.benchmark"
            with mock.patch.dict(sys.modules, {module_name: fake_benchmark}):
                with mock.patch.object(
                    queue,
                    "_load_committed_runtime_defaults",
                    return_value={
                        "appium_host": "127.0.0.1",
                        "appium_port": 4723,
                        "clone_source_udid": "AA112233",
                    },
                ):
                    status, record = queue.default_runner(
                        entry, attempt, platform="ios"
                    )
        self.assertEqual(status, "ERROR")
        self.assertEqual(record["exit_code"], 0)

    def test_current_attempt_result_is_used(self) -> None:
        entries = queue.build_plan_entries("ios")
        entry = entries[0]
        fake_benchmark = mock.MagicMock()

        def _write_ok(args):
            out = Path(args.output_root)
            out.mkdir(parents=True, exist_ok=True)
            (out / "result.json").write_text(
                json.dumps({"task_id": entry["task_id"], "status": "PASS"}),
                encoding="utf-8",
            )
            return 0

        fake_benchmark.run_benchmark_command = mock.MagicMock(side_effect=_write_ok)
        with tempfile.TemporaryDirectory(prefix="runner-") as raw:
            attempt = Path(raw) / "attempt_002"
            attempt.mkdir(parents=True)
            module_name = "platforms.ios.runners.benchmark"
            with mock.patch.dict(sys.modules, {module_name: fake_benchmark}):
                with mock.patch.object(
                    queue,
                    "_load_committed_runtime_defaults",
                    return_value={
                        "appium_host": "127.0.0.1",
                        "appium_port": 4723,
                        "clone_source_udid": "AA112233",
                    },
                ):
                    status, _ = queue.default_runner(entry, attempt, platform="ios")
        self.assertEqual(status, "PASS")


class ResumeExpiryTests(unittest.TestCase):
    def test_resume_expires_drifted_entry_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="resume-") as raw:
            results = Path(raw) / "ios"
            payload, resumed = queue.init_or_resume_queue(
                platform="ios", results_root=results
            )
            self.assertFalse(resumed)
            payload["entries"][0]["status"] = "skipped_valid"
            payload["entries"][0]["effective_max_steps"] = -999
            queue.save_queue(results / "queue.json", payload)
            refreshed, resumed_again = queue.init_or_resume_queue(
                platform="ios", results_root=results
            )
            self.assertTrue(resumed_again)
            self.assertEqual(refreshed["entries"][0]["status"], "pending")
            self.assertGreater(refreshed["entries"][0]["effective_max_steps"], 0)


class ImplementationHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="impl-hash-"))
        self.results = self.tmp / "results" / "ios"
        self.gate = _write_gate(self.tmp / "gate.json")

    def _run(self, runner: FakeRunner, **kwargs):
        params = {
            "platform": "ios",
            "results_root": self.results,
            "gate_path": self.gate,
            "runner": runner,
            "preflight_fn": _ok_preflight,
        }
        params.update(kwargs)
        return queue.run_queue(**params)

    def _task_dir(self, task_id: str) -> Path:
        return self.results / queue.safe_task_dir(task_id)

    def test_missing_impl_hash_verdict_is_rejected(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        queue.audit_confirm_pass(
            task_dir, _expected_for_task(task_id), "auditor"
        )
        legacy = dict(queue.read_verdict(task_dir))
        del legacy["task_implementation_sha256"]
        (task_dir / "verdict.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        runner = FakeRunner({})
        self._run(runner, limit=1)
        self.assertIn(task_id, runner.calls)

    def test_impl_change_invalidates_only_affected_task(self) -> None:
        entries = queue.build_plan_entries("ios")
        first, second = entries[0]["task_id"], entries[1]["task_id"]
        for task_id in (first, second):
            task_dir = self._task_dir(task_id)
            task_dir.mkdir(parents=True, exist_ok=True)
            queue.audit_confirm_pass(
                task_dir, _expected_for_task(task_id), "auditor"
            )
        # Simulate an initializer/evaluator change landing after the audit
        # for the second task only: its stored hash goes stale while the
        # first task's fingerprint still matches current sources.
        tampered = dict(queue.read_verdict(self._task_dir(second)))
        tampered["task_implementation_sha256"] = "0" * 64
        (self._task_dir(second) / "verdict.json").write_text(
            json.dumps(tampered), encoding="utf-8"
        )
        runner = FakeRunner({})
        self._run(runner, limit=5)
        self.assertNotIn(first, runner.calls)
        self.assertIn(second, runner.calls)

    def test_impl_hash_binds_task_and_transitive_deps(self) -> None:
        entries = {e["task_id"]: e for e in queue.build_plan_entries("ios")}
        first = next(iter(entries.values()))
        task_file = queue._resolve_task_file(first["task_path"])
        files = {
            p.resolve().as_posix()
            for p in queue.task_dependency_files(task_file)
        }
        self.assertIn(task_file.resolve().as_posix(), files)
        # The evaluator seed plus its transitive repo-local imports are
        # part of the closure (evaluator -> core.evaluation base).
        self.assertTrue(
            any(p.endswith(".py") and "/evaluators/" in p for p in files)
        )
        self.assertTrue(
            any(p.endswith("core/evaluation/base.py") for p in files)
        )
        with tempfile.TemporaryDirectory(prefix="impl-bind-") as raw:
            twin = Path(raw) / "twin.yaml"
            twin.write_text(
                task_file.read_text(encoding="utf-8") + "\n# twin\n",
                encoding="utf-8",
            )
            self.assertNotEqual(
                queue.task_implementation_hash(twin),
                queue.task_implementation_hash(task_file),
            )

    def test_git_head_change_does_not_invalidate(self) -> None:
        entries = queue.build_plan_entries("ios")
        task_id = entries[0]["task_id"]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        queue.audit_confirm_pass(
            task_dir, _expected_for_task(task_id), "auditor"
        )
        before = queue.code_version_hash("ios")
        with mock.patch.object(
            queue.subprocess, "run", side_effect=AssertionError("no git reads")
        ):
            after = queue.code_version_hash("ios")
            self.assertEqual(before, after)
            runner = FakeRunner({})
            self._run(runner, limit=1)
        self.assertNotIn(task_id, runner.calls)

    def test_platform_code_sets_are_disjoint(self) -> None:
        ios_files = {
            p.resolve().as_posix() for p in queue.platform_code_files("ios")
        }
        macos_files = {
            p.resolve().as_posix() for p in queue.platform_code_files("macos")
        }
        ios_only = {p for p in ios_files if "/platforms/ios/" in p}
        macos_only = {p for p in macos_files if "/platforms/macos/" in p}
        self.assertTrue(ios_only)
        self.assertTrue(macos_only)
        self.assertFalse(ios_only & macos_files)
        self.assertFalse(macos_only & ios_files)

    def test_missing_module_hash_never_matches(self) -> None:
        entries = queue.build_plan_entries("ios")
        expected = _expected_for_task(entries[0]["task_id"])
        tampered = dict(expected)
        tampered["task_implementation_sha256"] = "missing:gone_module"
        self.assertFalse(queue._evidence_matches(tampered, expected))
        self.assertFalse(queue._evidence_matches(expected, tampered))


class PrecheckEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="precheck-"))

    def _gate_payload(self, gate: Path) -> tuple[dict, Path]:
        payload = json.loads(gate.read_text(encoding="utf-8"))
        return payload, Path(payload["initial_fail_evidence"])

    def test_unhashed_string_evidence_rejected(self) -> None:
        gate = _write_gate(self.tmp / "gate.json")
        _, evidence_path = self._gate_payload(gate)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        first = next(iter(evidence))
        evidence[first] = "FAIL"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(queue.GateError):
            queue.run_queue(
                platform="ios",
                results_root=self.tmp / "results" / "ios",
                gate_path=gate,
                limit=1,
                runner=FakeRunner({}),
                preflight_fn=_ok_preflight,
            )

    def test_stale_precheck_task_hash_rejected(self) -> None:
        gate = _write_gate(self.tmp / "gate.json")
        _, evidence_path = self._gate_payload(gate)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        first = next(iter(evidence))
        evidence[first]["task_sha256"] = "0" * 64
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(queue.GateError):
            queue.run_queue(
                platform="ios",
                results_root=self.tmp / "results" / "ios",
                gate_path=gate,
                limit=1,
                runner=FakeRunner({}),
                preflight_fn=_ok_preflight,
            )

    def test_stale_precheck_impl_hash_rejected(self) -> None:
        gate = _write_gate(self.tmp / "gate.json")
        _, evidence_path = self._gate_payload(gate)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        first = next(iter(evidence))
        evidence[first]["task_implementation_sha256"] = "0" * 64
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(queue.GateError):
            queue.run_queue(
                platform="ios",
                results_root=self.tmp / "results" / "ios",
                gate_path=gate,
                limit=1,
                runner=FakeRunner({}),
                preflight_fn=_ok_preflight,
            )


class TaskSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="selection-"))
        self.results = self.tmp / "results" / "ios"
        entries = queue.build_plan_entries("ios")
        self.first = entries[0]["task_id"]
        self.second = entries[1]["task_id"]

    def test_selection_runs_only_selected_tasks(self) -> None:
        gate = _write_gate(
            self.tmp / "gate.json", task_ids=[self.first, self.second]
        )
        runner = FakeRunner({})
        summary = queue.run_queue(
            platform="ios",
            results_root=self.results,
            gate_path=gate,
            limit=5,
            runner=runner,
            preflight_fn=_ok_preflight,
            task_ids=[self.first],
        )
        self.assertEqual(runner.calls, [self.first])
        self.assertEqual(summary["selected_task_ids"], [self.first])
        persisted = queue.load_queue(self.results / "queue.json")
        self.assertEqual(len(persisted["entries"]), 48)

    def test_partial_evidence_blocks_full_run_but_allows_selection(self) -> None:
        gate = _write_gate(self.tmp / "gate.json", task_ids=[self.first])
        with self.assertRaises(queue.GateError):
            queue.run_queue(
                platform="ios",
                results_root=self.results,
                gate_path=gate,
                limit=1,
                runner=FakeRunner({}),
                preflight_fn=_ok_preflight,
            )
        runner = FakeRunner({})
        queue.run_queue(
            platform="ios",
            results_root=self.results,
            gate_path=gate,
            limit=1,
            runner=runner,
            preflight_fn=_ok_preflight,
            task_ids=[self.first],
        )
        self.assertIn(self.first, runner.calls)

    def test_unknown_task_id_rejected(self) -> None:
        gate = _write_gate(self.tmp / "gate.json", task_ids=[self.first])
        with self.assertRaises(queue.QueueError):
            queue.run_queue(
                platform="ios",
                results_root=self.results,
                gate_path=gate,
                limit=1,
                runner=FakeRunner({}),
                preflight_fn=_ok_preflight,
                task_ids=["no.such.task"],
            )


if __name__ == "__main__":
    unittest.main()
