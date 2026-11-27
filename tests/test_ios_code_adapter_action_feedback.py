from __future__ import annotations

from types import SimpleNamespace

from platforms.ios.runners.base_episode import BaseEpisodeRunner


class _PromptBuilder:
    def __init__(self, **_kwargs):
        pass


class _Controller:
    def __init__(self, result):
        self.result = result

    def run_python_script(self, _code, *, timeout):
        assert timeout == 120
        return self.result


class _Runner(BaseEpisodeRunner):
    def _initialize_task(self, task, run_dir):  # pragma: no cover - not used here
        raise NotImplementedError

    def _observe(self, *, include_ui_tree=True, include_screenshot=True):  # pragma: no cover
        raise NotImplementedError

    def _build_observation_addition_info(self, observation):  # pragma: no cover
        return {}

    @property
    def platform_name(self):
        return "ios"


def _runner(tmp_path, result):
    return _Runner(
        controller=_Controller(result),
        llm_client=object(),
        model_id="deepseek_flash",
        action_mode="code_adapter",
        observation_mode="screenshot_only",
        output_dir=str(tmp_path),
        prompt_builder_cls=_PromptBuilder,
    )


def test_python_stdout_is_available_to_the_next_model_step(tmp_path):
    runner = _runner(
        tmp_path,
        {
            "status": "success",
            "message": "Appium Python code executed",
            "output": "{'width': 440, 'height': 956}\n",
            "error": "",
            "return_code": 0,
        },
    )

    result, success, error, _latency = runner._execute_action(
        1, {"type": "python_code", "code": "print(driver.get_window_size())"}, []
    )

    assert success and error is None
    assert result["stdout"] == "{'width': 440, 'height': 956}"
    next_prompt = runner._build_extra_step_prompt(SimpleNamespace())
    assert "status: SUCCESS" in next_prompt
    assert "stdout:\n{'width': 440, 'height': 956}" in next_prompt


def test_python_errors_are_available_to_the_next_model_step(tmp_path):
    runner = _runner(
        tmp_path,
        {
            "status": "error",
            "message": "ReadTimeoutError: WDA command timed out",
            "output": "partial output",
            "error": "ReadTimeoutError: WDA command timed out",
            "return_code": -1,
        },
    )

    _result, success, _error, _latency = runner._execute_action(
        1, {"type": "python_code", "code": "driver.page_source"}, []
    )

    assert not success
    next_prompt = runner._build_extra_step_prompt(SimpleNamespace())
    assert "status: ERROR" in next_prompt
    assert "ReadTimeoutError: WDA command timed out" in next_prompt
    assert "stdout:\npartial output" in next_prompt


def test_previous_action_feedback_is_bounded():
    rendered = BaseEpisodeRunner._render_action_feedback(
        {"status": "SUCCESS", "result": "x" * 6000}, limit=5000
    )
    assert len(rendered) < 5100
    assert rendered.endswith("[previous action output truncated]")
