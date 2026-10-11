"""Check the promised simple Python builtins without broadening GUI capabilities."""
from types import SimpleNamespace
from pathlib import Path
from platforms.ios.runtime_env.action_engine import iOSActionEngine

class Driver:
    def __init__(self):
        self.calls = 0
    def get_window_size(self):
        self.calls += 1
        return {"width": 440, "height": 956}

def engine():
    driver = Driver()
    return iOSActionEngine(SimpleNamespace(driver=driver)), driver

def test_repr_is_available_for_driver_value_debugging():
    executor, driver = engine()
    result = executor.run_python_script("print(repr(driver.get_window_size()))")
    assert result["status"] == "success", result
    assert result["terminal"] is False
    assert result["output"] == "{'width': 440, 'height': 956}\n"
    assert driver.calls == 1

def test_repr_does_not_enable_imports_or_execute_prior_calls():
    executor, driver = engine()
    result = executor.run_python_script("print(repr(driver.get_window_size()))\nimport time")
    assert result["status"] == "error"
    assert result["terminal"] is True
    assert "imports are not available" in result["error"]
    assert driver.calls == 0

def test_repr_does_not_enable_host_file_access(tmp_path):
    executor, driver = engine()
    target = tmp_path / "unauthorized"
    result = executor.run_python_script(f"print(repr(driver.get_window_size()))\nopen({str(target)!r}, 'w')")
    assert result["status"] == "error"
    assert not target.exists()
