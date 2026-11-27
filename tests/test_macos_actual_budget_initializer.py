import json
from types import SimpleNamespace

from core.init import InitStatus
from initializers.macos.actual_budget import ActualBudgetInitializer


class FakeController:
    def __init__(self):
        self.calls = []
        self.python_calls = 0
        self.template_has_budget = False
        self.budget_created = False
        self.window_geometry = {"x": 40, "y": 40, "width": 1500, "height": 960}

    def run_bash_script(self, script, timeout=None):
        self.calls.append(("bash", script))
        return {"status": "success", "returncode": 0, "output": ""}

    def run_python_script(self, script, timeout=None):
        if "has_last_budget" in script:
            self.calls.append(("budget_check", script))
            return {"stdout": json.dumps({"has_last_budget": self.template_has_budget or self.budget_created})}
        self.python_calls += 1
        label = "seed" if self.python_calls == 1 else "verify"
        self.calls.append((label, script))
        return {"stdout": json.dumps({"status": "pass", "message": "ok"})}

    def launch_app(self, app_name):
        self.calls.append(("launch", app_name))

    def upload_file(self, local_path, remote_path):
        self.calls.append(("upload", (local_path, remote_path)))

    def execute_action(self, action, ui_nodes):
        self.calls.append(("bootstrap", action))
        self.budget_created = True
        return {"success": True}

    def observe(self, include_ui_tree=True, include_screenshot_data=False):
        x, y, width, height = (self.window_geometry[key] for key in ("x", "y", "width", "height"))
        return SimpleNamespace(
            width=1920,
            height=1080,
            ui_nodes=[{
                "type": "AXWindow",
                "description": "Actual",
                "text": "Actual",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }],
        )


def test_actual_fallback_bootstraps_blank_budget_before_seeding_payees(monkeypatch, tmp_path):
    monkeypatch.setattr("initializers.macos.actual_budget.time.sleep", lambda *_: None)
    controller = FakeController()
    task = SimpleNamespace(source_file=str(tmp_path / "task.yaml"))

    result = ActualBudgetInitializer().initialize(
        {"controller": controller, "params": {"wait_ms": 0}, "task": task}
    )

    assert result.status == InitStatus.PASS
    labels = [label for label, _ in controller.calls]
    assert labels.index("launch") < labels.index("bootstrap") < labels.index("seed")
    assert labels.index("seed") < labels.index("verify")
    assert result.metadata["used_template_restore"] is False
    reset_script = next(script for label, script in controller.calls if label == "bash")
    assert '"syncServerConfig":null' in reset_script
    assert '"server-url":null' in reset_script
    assert '"did-bootstrap":true' in reset_script
    bootstrap_actions = [value for label, value in controller.calls if label == "bootstrap"]
    assert bootstrap_actions == [
        {"type": "tap", "target": {"x": 996, "y": 708}}
    ]


def test_actual_fallback_bootstrap_tracks_fullscreen_window_geometry(monkeypatch, tmp_path):
    monkeypatch.setattr("initializers.macos.actual_budget.time.sleep", lambda *_: None)
    controller = FakeController()
    controller.window_geometry = {"x": 0, "y": 0, "width": 1920, "height": 1080}
    task = SimpleNamespace(source_file=str(tmp_path / "task.yaml"))

    result = ActualBudgetInitializer().initialize(
        {"controller": controller, "params": {"wait_ms": 0}, "task": task}
    )

    assert result.status == InitStatus.PASS
    assert ("bootstrap", {"type": "tap", "target": {"x": 1166, "y": 708}}) in controller.calls


def test_actual_template_path_with_live_budget_skips_ui_bootstrap(monkeypatch, tmp_path):
    monkeypatch.setattr("initializers.macos.actual_budget.time.sleep", lambda *_: None)
    controller = FakeController()
    controller.template_has_budget = True
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "blank-budget-template.zip").write_bytes(b"zip")
    (task_dir / "global-store.blank.json").write_text("{}", encoding="utf-8")
    task = SimpleNamespace(source_file=str(task_dir / "task.yaml"))

    initializer = ActualBudgetInitializer()
    initializer.DEFAULT_TEMPLATE_ARCHIVE = "blank-budget-template.zip"
    initializer.DEFAULT_GLOBAL_STORE_TEMPLATE = "global-store.blank.json"
    result = initializer.initialize(
        {"controller": controller, "params": {"wait_ms": 0}, "task": task}
    )

    assert result.status == InitStatus.PASS
    labels = [label for label, _ in controller.calls]
    assert "bootstrap" not in labels
    assert labels.index("launch") < labels.index("seed") < labels.index("verify")
    assert result.metadata["used_template_restore"] is True


def test_actual_template_path_bootstraps_when_installed_version_drops_budget(monkeypatch, tmp_path):
    monkeypatch.setattr("initializers.macos.actual_budget.time.sleep", lambda *_: None)
    controller = FakeController()
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "blank-budget-template.zip").write_bytes(b"zip")
    (task_dir / "global-store.blank.json").write_text(
        json.dumps({"lastBudget": "old-template-budget"}), encoding="utf-8"
    )
    task = SimpleNamespace(source_file=str(task_dir / "task.yaml"))
    initializer = ActualBudgetInitializer()
    initializer.DEFAULT_TEMPLATE_ARCHIVE = "blank-budget-template.zip"
    initializer.DEFAULT_GLOBAL_STORE_TEMPLATE = "global-store.blank.json"

    result = initializer.initialize(
        {"controller": controller, "params": {"wait_ms": 0}, "task": task}
    )

    assert result.status == InitStatus.PASS
    labels = [label for label, _ in controller.calls]
    assert labels.index("launch") < labels.index("budget_check") < labels.index("bootstrap")
    assert labels.index("bootstrap") < labels.index("seed") < labels.index("verify")
    assert result.metadata["used_template_restore"] is True


def test_actual_reset_keeps_server_unconfigured_but_skips_first_run_wizard():
    script = ActualBudgetInitializer._build_reset_script(
        document_root="~/Documents/Actual",
        state_root="~/Library/Application Support/Actual",
    )

    assert '"syncServerConfig":null' in script
    assert '"server-url":null' in script
    assert '"did-bootstrap":true' in script
    assert '"lastBudget"' not in script


def test_actual_launch_retries_transient_launchservices_error(monkeypatch, tmp_path):
    monkeypatch.setattr("initializers.macos.actual_budget.time.sleep", lambda *_: None)

    class FlakyController(FakeController):
        def launch_app(self, app_name):
            self.calls.append(("launch", app_name))
            raise RuntimeError("open -a failed with -609")

    controller = FlakyController()
    task = SimpleNamespace(source_file=str(tmp_path / "task.yaml"))

    result = ActualBudgetInitializer().initialize(
        {"controller": controller, "params": {"wait_ms": 0}, "task": task}
    )

    assert result.status == InitStatus.PASS
    fallback_launch = [
        script for label, script in controller.calls
        if label == "bash" and "open -a" in script
    ]
    assert fallback_launch
