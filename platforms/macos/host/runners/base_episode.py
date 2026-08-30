"""Shared abstract episode runner with platform hooks."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.benchmark_policy import DEFAULT_PROMPT_PROFILE, normalize_prompt_profile
from core.llm.llm_client import LLMClientManager

from platforms.macos.host.agent.planners.reflection_pyautogui_planner import ReflectionPyAutoGUIPlanner
from platforms.macos.host.core.logger import EpisodeLogger
from platforms.macos.host.core.runtime_types import EpisodeResult, TerminalReason
from platforms.macos.host.runners.evaluation import evaluation_to_episode_outcome, run_task_evaluation
from platforms.macos.host.runners.initialization import initialization_to_episode_failure_message


class BaseEpisodeRunner(ABC):
    """Executes one task episode with platform-specific environment hooks."""

    VALID_OBSERVATION_MODES = {
        "screenshot_only",
        "a11y_tree_only",
        "screenshot_and_a11y_tree",
    }

    def __init__(
        self,
        *,
        controller: Any,
        llm_client: LLMClientManager,
        model_id: str,
        action_mode: str = "code_adapter",
        observation_mode: str = "screenshot_and_a11y_tree",
        save_trajectory: bool = True,
        output_dir: str,
        prompt_builder_cls: Any,
        history_window: int = 5,
        prompt_profile: str = DEFAULT_PROMPT_PROFILE,
        run_dir: Optional[Path] = None,
        step_settle_seconds: float = 0.3,
        logger_obj: Optional[logging.Logger] = None,
    ) -> None:
        self.controller = controller
        self.llm_client = llm_client
        self.model_id = str(model_id).strip()
        if not self.model_id:
            raise ValueError("model_id cannot be empty")
        self.action_mode = action_mode
        self.observation_mode = self._normalize_observation_mode(observation_mode)
        self.save_trajectory = save_trajectory
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.history_window = history_window
        self.prompt_profile = normalize_prompt_profile(prompt_profile)
        self.step_settle_seconds = step_settle_seconds
        self._run_dir = Path(run_dir) if run_dir is not None else None
        self._logger = logger_obj or logging.getLogger(self.__class__.__module__)

        if self.action_mode != "code_adapter":
            raise ValueError(
                f"Unsupported action_mode: {self.action_mode}. Expected code_adapter."
            )
        self.prompt_builder = prompt_builder_cls(
            observation_mode=self.observation_mode,
            tool_calling=False,
            action_mode=self.action_mode,
            prompt_profile=self.prompt_profile,
        )
        self._last_auto_eval_feedback: Optional[str] = None

    @classmethod
    def _normalize_observation_mode(cls, raw_mode: str) -> str:
        normalized = str(raw_mode or "").strip().lower()
        if not normalized:
            return "screenshot_and_a11y_tree"
        if normalized not in cls.VALID_OBSERVATION_MODES:
            raise ValueError(
                "Unsupported observation_mode: "
                f"{raw_mode}. Expected one of: screenshot_only, a11y_tree_only, screenshot_and_a11y_tree."
            )
        return normalized

    def _include_ui_tree_for_llm(self) -> bool:
        return self.observation_mode in {"a11y_tree_only", "screenshot_and_a11y_tree"}

    def _include_screenshot_for_llm(self) -> bool:
        return self.observation_mode in {"screenshot_only", "screenshot_and_a11y_tree"}

    @abstractmethod
    def _initialize_task(self, task: Any, run_dir: Path) -> Any:
        """Prepare initial environment state for the task."""

    @abstractmethod
    def _observe(self, *, include_ui_tree: bool = True, include_screenshot: bool = True) -> Any:
        """Read current environment observation."""

    @abstractmethod
    def _build_evaluator_context(
        self,
        *,
        task: Any,
        final_observation: Any,
        run_dir: Path,
    ) -> Mapping[str, Any]:
        """Build evaluator context for the current task run."""

    @abstractmethod
    def _build_observation_addition_info(self, observation: Any) -> Dict[str, Any]:
        """Build protocol addition_info from a raw observation."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Protocol platform name."""

    def _capture_screenshot(self, prefix: str) -> Tuple[str, Optional[List[str]]]:
        screenshot_path = ""
        step_images = None
        try:
            shot = self.controller.save_screenshot(prefix)
            if shot:
                screenshot_path = shot
                if self._include_screenshot_for_llm() and self._should_attach_image(shot):
                    step_images = [shot]
        except Exception as e:
            self._logger.warning("Screenshot failed for '%s': %s", prefix, e)
        return screenshot_path, step_images

    def _should_attach_image(self, screenshot_path: str) -> bool:
        path = Path(screenshot_path)
        return path.exists()

    @staticmethod
    def _normalize_optional_path_ref(raw_path: Optional[str], run_dir: Path) -> Optional[str]:
        if not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            return str(path)
        try:
            return str(path.resolve().relative_to(run_dir.resolve()))
        except ValueError:
            return str(path)

    def _build_observation_artifact(
        self,
        observation: Optional[Any],
        *,
        screenshot_path: Optional[str],
        include_ui_tree: bool,
        run_dir: Path,
    ) -> Dict[str, Any]:
        if observation is None:
            return {
                "screenshot_path": self._normalize_optional_path_ref(screenshot_path, run_dir),
                "a11y_tree": None,
                "addition_info": {},
            }

        return {
            "screenshot_path": self._normalize_optional_path_ref(screenshot_path, run_dir),
            "a11y_tree": list(getattr(observation, "ui_nodes", [])) if include_ui_tree else None,
            "addition_info": self._build_observation_addition_info(observation),
        }

    def _observe_step(
        self,
        current_step: int,
        task: Any,
    ) -> Optional[Tuple[Any, float, str, Optional[List[str]]]]:
        self._logger.info("[Step %d] Observing...", current_step)
        obs_start = time.time()
        try:
            include_screenshot = self._include_screenshot_for_llm() and bool(
                getattr(task, "include_screenshot", True)
            )
            observation = self._observe(
                include_ui_tree=self._include_ui_tree_for_llm(),
                include_screenshot=include_screenshot,
            )
        except Exception as e:
            self._logger.error("[Step %d] Observe failed: %s", current_step, e)
            return None
        obs_latency = (time.time() - obs_start) * 1000

        screenshot_path = ""
        step_images = None
        if include_screenshot:
            screenshot_path, step_images = self._capture_screenshot(f"step_{current_step}")
            if not screenshot_path:
                self._logger.warning("[Step %d] screenshot missing", current_step)

        return observation, obs_latency, screenshot_path, step_images

    def _plan_action(
        self,
        current_step: int,
        action_planner: Any,
        step_prompt: str,
        step_images: Optional[List[str]],
        step_timeout_seconds: Optional[float] = None,
    ):
        self._logger.info("[Step %d] Querying LLM...", current_step)
        llm_start = time.time()
        try:
            action_decision = action_planner.decide(
                step_prompt,
                images=step_images,
                timeout_seconds=step_timeout_seconds,
            )
        except Exception as e:
            self._logger.error("[Step %d] LLM call failed: %s", current_step, e)
            return None
        llm_latency = (time.time() - llm_start) * 1000
        self._logger.info(
            "[Step %d] LLM response (%.0fms, mode=%s, adapter=%s): %s",
            current_step,
            llm_latency,
            action_decision.mode_used,
            action_decision.adapter,
            action_decision.raw_response,
        )
        return action_decision, llm_latency

    @staticmethod
    def _build_python_action_prelude(observation: Optional[Any]) -> str:
        prelude_lines = [
            "import pyautogui, time",
            "pyautogui.PAUSE = 0",
            "pyautogui.FAILSAFE = False",
        ]

        screenshot_width = int(getattr(observation, "width", 0) or 0) if observation is not None else 0
        screenshot_height = int(getattr(observation, "height", 0) or 0) if observation is not None else 0
        if screenshot_width > 0 and screenshot_height > 0:
            prelude_lines.extend(
                [
                    f"__HELLOWORLD_SCREENSHOT_WIDTH = {screenshot_width}",
                    f"__HELLOWORLD_SCREENSHOT_HEIGHT = {screenshot_height}",
                    "__HELLOWORLD_GUI_WIDTH, __HELLOWORLD_GUI_HEIGHT = pyautogui.size()",
                    "__HELLOWORLD_SCALE_X = (__HELLOWORLD_GUI_WIDTH / __HELLOWORLD_SCREENSHOT_WIDTH) if __HELLOWORLD_SCREENSHOT_WIDTH else 1.0",
                    "__HELLOWORLD_SCALE_Y = (__HELLOWORLD_GUI_HEIGHT / __HELLOWORLD_SCREENSHOT_HEIGHT) if __HELLOWORLD_SCREENSHOT_HEIGHT else 1.0",
                    "def __helloworld_scale_value(value, scale):",
                    "    if isinstance(value, (int, float)):",
                    "        return int(round(float(value) * scale))",
                    "    return value",
                    "def __helloworld_wrap_xy(func):",
                    "    def wrapper(x=None, y=None, *args, **kwargs):",
                    "        if isinstance(x, (tuple, list)) and len(x) >= 2 and y is None:",
                    "            sx = __helloworld_scale_value(x[0], __HELLOWORLD_SCALE_X)",
                    "            sy = __helloworld_scale_value(x[1], __HELLOWORLD_SCALE_Y)",
                    "            return func(sx, sy, *args, **kwargs)",
                    "        if isinstance(x, (int, float)) and isinstance(y, (int, float)):",
                    "            x = __helloworld_scale_value(x, __HELLOWORLD_SCALE_X)",
                    "            y = __helloworld_scale_value(y, __HELLOWORLD_SCALE_Y)",
                    "        return func(x, y, *args, **kwargs)",
                    "    return wrapper",
                    "def __helloworld_wrap_rel(func):",
                    "    def wrapper(xOffset=None, yOffset=None, *args, **kwargs):",
                    "        if isinstance(xOffset, (int, float)):",
                    "            xOffset = __helloworld_scale_value(xOffset, __HELLOWORLD_SCALE_X)",
                    "        if isinstance(yOffset, (int, float)):",
                    "            yOffset = __helloworld_scale_value(yOffset, __HELLOWORLD_SCALE_Y)",
                    "        return func(xOffset, yOffset, *args, **kwargs)",
                    "    return wrapper",
                    "pyautogui.click = __helloworld_wrap_xy(pyautogui.click)",
                    "pyautogui.doubleClick = __helloworld_wrap_xy(pyautogui.doubleClick)",
                    "pyautogui.rightClick = __helloworld_wrap_xy(pyautogui.rightClick)",
                    "pyautogui.middleClick = __helloworld_wrap_xy(pyautogui.middleClick)",
                    "pyautogui.moveTo = __helloworld_wrap_xy(pyautogui.moveTo)",
                    "pyautogui.dragTo = __helloworld_wrap_xy(pyautogui.dragTo)",
                    "pyautogui.mouseDown = __helloworld_wrap_xy(pyautogui.mouseDown)",
                    "pyautogui.mouseUp = __helloworld_wrap_xy(pyautogui.mouseUp)",
                    "pyautogui.moveRel = __helloworld_wrap_rel(pyautogui.moveRel)",
                    "pyautogui.dragRel = __helloworld_wrap_rel(pyautogui.dragRel)",
                ]
            )

        return "\n".join(prelude_lines)

    def _execute_action(
        self,
        current_step: int,
        action_parsed: Dict[str, Any],
        ui_nodes: List[Dict[str, Any]],
        *,
        observation: Optional[Any] = None,
        default_python_timeout_seconds: int = 120,
    ):
        self._logger.info("[Step %d] Action: %s", current_step, action_parsed)
        action_start = time.time()
        action_error = None
        try:
            if str(action_parsed.get("type") or "").strip() == "python_code":
                timeout_seconds = max(
                    1,
                    int(action_parsed.get("timeout_seconds", default_python_timeout_seconds) or default_python_timeout_seconds),
                )
                code = str(action_parsed.get("code") or "").strip()
                prelude = self._build_python_action_prelude(observation)
                raw_result = self.controller.run_python_script(f"{prelude}\n{code}\n", timeout=timeout_seconds)
                stdout = str(raw_result.get("output") or "").strip()
                stderr = str(raw_result.get("error") or "").strip()
                status = str(raw_result.get("status") or "").strip().lower()
                terminal = False
                terminal_action_type = None
                message = stdout or stderr or "Python code executed"
                for line in stdout.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("__HELLOWORLD_DONE__:"):
                        terminal = True
                        terminal_action_type = "success"
                        message = stripped.split(":", 1)[1].strip() or "Task completed"
                        break
                    if stripped.startswith("__HELLOWORLD_FAIL__:"):
                        terminal = True
                        terminal_action_type = "fail"
                        message = stripped.split(":", 1)[1].strip() or "Task failed"
                        break
                action_result = {
                    "success": status == "success" and terminal_action_type != "fail",
                    "message": message,
                    "terminal": terminal,
                    "terminal_action_type": terminal_action_type,
                    "stdout": stdout or None,
                    "stderr": stderr or None,
                    "return_code": raw_result.get("return_code", raw_result.get("returncode")),
                }
                action_success = bool(action_result.get("success", False))
            else:
                action_result = self.controller.execute_action(action_parsed, ui_nodes)
                action_success = bool(action_result.get("success", False))
        except Exception as e:
            action_result = None
            action_success = False
            action_error = str(e)
            self._logger.error("[Step %d] ACTION ERROR: %s", current_step, e)
        action_latency = (time.time() - action_start) * 1000
        result_message = ""
        if isinstance(action_result, dict):
            result_message = str(action_result.get("message", ""))
        elif action_error:
            result_message = action_error
        self._logger.info("[Step %d] Result: %s", current_step, result_message)
        return action_result, action_success, action_error, action_latency

    def _observe_final_state(self) -> Tuple[Optional[Any], Optional[str]]:
        final_observation = None
        final_screenshot = None

        try:
            final_observation = self._observe(include_ui_tree=True, include_screenshot=True)
        except Exception:
            pass

        try:
            shot = self.controller.save_screenshot("final")
            final_screenshot = shot or None
        except Exception:
            pass

        return final_observation, final_screenshot

    def _maybe_complete_from_evaluation(
        self,
        *,
        task: Any,
        run_dir: Path,
    ) -> Optional[str]:
        if not bool(getattr(task, "auto_evaluate_after_action", False)):
            return None

        latest_observation = None
        try:
            latest_observation = self._observe(include_ui_tree=True, include_screenshot=False)
        except Exception:
            latest_observation = None

        evaluation_run = run_task_evaluation(
            task=task,
            build_context=lambda: self._build_evaluator_context(
                task=task,
                final_observation=latest_observation,
                run_dir=run_dir,
            ),
            model_id=self.model_id,
            run_dir=run_dir,
            logger_obj=self._logger,
        )
        if evaluation_run is None:
            return None

        eval_status, eval_message = evaluation_to_episode_outcome(evaluation_run.result)
        if eval_status == "PASS":
            self._last_auto_eval_feedback = None
            return eval_message or evaluation_run.result.message or "Task evaluator passed after action."
        if eval_message:
            compact_message = " ".join(str(eval_message).split())
            if len(compact_message) > 600:
                compact_message = compact_message[:597] + "..."
            self._last_auto_eval_feedback = (
                "Previous auto-evaluator check is still failing. "
                f"Current mismatch summary: {compact_message}. "
                "Keep the already-correct edits and continue toward the missing targets; do not undo unless the mismatch explicitly says a label is wrong."
            )
        return None

    @staticmethod
    def _is_provider_failure(error_text: Optional[str]) -> bool:
        text = str(error_text or "").upper()
        if not text:
            return False
        markers = (
            "PROVIDER_REQUEST_FAILED",
            "TIMEOUT",
            "ENV_MISSING",
            "INVALID_PROVIDER_RESPONSE",
            "HTTPSTATUSERROR",
            "STATUS=",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _terminal_reason_to_status(terminal_reason: TerminalReason) -> str:
        if terminal_reason == TerminalReason.SUCCESS:
            return "PASS"
        if terminal_reason == TerminalReason.FAIL_ERROR:
            return "ERROR"
        return "FAIL"

    def _build_episode_result(self, terminal_reason: TerminalReason, message: Optional[str]) -> Dict[str, Any]:
        return {
            "status": self._terminal_reason_to_status(terminal_reason),
            "message": message,
        }

    def _build_action_parse_payload(
        self,
        *,
        action_parsed: Optional[Dict[str, Any]],
        parse_success: bool,
        error: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "status": "SUCCESS" if parse_success else "ERROR",
            "action": action_parsed,
            "error": error,
        }

    def _build_action_execution_payload(
        self,
        *,
        action_result: Optional[Dict[str, Any]],
        action_success: bool,
        action_error: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if action_result is None and action_error is None:
            return None
        if action_success and isinstance(action_result, dict):
            return {
                "status": "SUCCESS",
                "result": action_result.get("message"),
                "error": None,
            }
        error_message = action_error
        if error_message is None and isinstance(action_result, dict):
            error_message = action_result.get("message")
        return {
            "status": "ERROR",
            "result": None,
            "error": error_message,
        }

    def _finalize_episode(
        self,
        *,
        task: Any,
        ep_logger: EpisodeLogger,
        terminal_reason: Optional[TerminalReason],
        episode_message: Optional[str],
        run_dir: Path,
        initialization_run: Optional[Any] = None,
        skip_evaluation: bool = False,
    ) -> EpisodeResult:
        if terminal_reason is None:
            terminal_reason = TerminalReason.FAIL_ERROR
            episode_message = "Unexpected termination"

        final_observation, final_screenshot = self._observe_final_state()
        final_observation_artifact = self._build_observation_artifact(
            final_observation,
            screenshot_path=final_screenshot,
            include_ui_tree=True,
            run_dir=run_dir,
        )

        evaluation_run = None
        if not skip_evaluation:
            evaluation_run = run_task_evaluation(
                task=task,
                build_context=lambda: self._build_evaluator_context(
                    task=task,
                    final_observation=final_observation,
                    run_dir=run_dir,
                ),
                model_id=self.model_id,
                run_dir=run_dir,
                trajectory_path=ep_logger.trajectory_path,
                logger_obj=self._logger,
            )

        episode_result = self._build_episode_result(terminal_reason, episode_message)
        final_status = episode_result["status"]
        final_message = episode_message

        if terminal_reason == TerminalReason.SUCCESS and evaluation_run is not None:
            final_status, final_message = evaluation_to_episode_outcome(evaluation_run.result)
            if final_status == "PASS":
                self._logger.info("Final episode verdict is PASS from evaluator.")
            else:
                self._logger.info(
                    "Final episode verdict is %s from evaluator.",
                    evaluation_run.result.status.value,
                )
        elif terminal_reason == TerminalReason.FAIL_MAX_STEPS and evaluation_run is not None:
            eval_status, eval_message = evaluation_to_episode_outcome(evaluation_run.result)
            if eval_status == "PASS":
                final_status = "PASS"
                final_message = (
                    eval_message
                    or evaluation_run.result.message
                    or "Task evaluator passed after reaching the step limit."
                )
                self._logger.info(
                    "Episode hit max steps but evaluator says PASS – overriding to PASS."
                )
            else:
                self._logger.info(
                    "Episode hit max steps and evaluator confirms %s.",
                    evaluation_run.result.status.value,
                )
        elif evaluation_run is not None:
            self._logger.info(
                "Episode terminated with %s; evaluator summary recorded but final status is not upgraded.",
                terminal_reason.value,
            )

        result = ep_logger.finalize(
            platform=self.platform_name,
            model_id=self.model_id,
            status=final_status,
            episode_result={
                "status": episode_result["status"],
                "message": final_message if final_message is not None else episode_result["message"],
            },
            initializer=initialization_run.summary if initialization_run is not None else None,
            evaluation=evaluation_run.summary if evaluation_run is not None else None,
            final_observation=final_observation_artifact,
        )

        output_path = run_dir / "result.json"
        result.save(str(output_path))
        self._logger.info("Result written to: %s", output_path)

        status_text = "✓ PASS" if result.success else f"✗ {result.status}"
        self._logger.info("=" * 60)
        self._logger.info("Episode Complete: %s", status_text)
        self._logger.info("Steps: %d, Time: %.1fms", result.steps_taken, result.latency_ms)
        if result.failure_message:
            self._logger.info("Failure: %s", result.failure_message)
        self._logger.info("=" * 60)

        return result

    def run_episode(self, task: Any) -> EpisodeResult:
        """Run one episode and return the final result summary."""
        self._logger.info("=" * 60)
        self._logger.info("Starting Episode: %s", task.id)
        self._logger.info("Goal: %s", task.goal)
        self._logger.info("=" * 60)

        if self._run_dir is not None:
            run_dir = self._run_dir
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = self.output_dir / f"{task.id}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        screenshots_dir = run_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.controller.update_screenshot_dir(str(screenshots_dir))

        ep_logger = EpisodeLogger(
            task_id=task.id,
            output_dir=str(run_dir),
        )

        initialization_run = self._initialize_task(task, run_dir)
        if initialization_run is not None:
            init_failure_message = initialization_to_episode_failure_message(initialization_run.result)
            if init_failure_message is None:
                self._logger.info("Task initialization completed successfully.")
            else:
                self._logger.error("Task initialization failed: %s", init_failure_message)
                return self._finalize_episode(
                    task=task,
                    ep_logger=ep_logger,
                    terminal_reason=TerminalReason.FAIL_ERROR,
                    episode_message=f"Initializer failed: {init_failure_message}",
                    run_dir=run_dir,
                    initialization_run=initialization_run,
                    skip_evaluation=True,
                )

        action_system_prompt = self.prompt_builder.build_system_prompt(
            task=task,
            action_rules=None,
        )

        self._logger.info("Building LLM Agent...")
        session_metadata = {"task_id": task.id}
        action_planner = ReflectionPyAutoGUIPlanner(
            llm_client=self.llm_client,
            model_id=self.model_id,
            system_prompt=action_system_prompt,
            history_window=self.history_window,
            session_metadata=session_metadata,
        )
        self._logger.info("LLM Agent is ready!")

        terminal_reason: Optional[TerminalReason] = None
        episode_message: Optional[str] = None

        while True:
            current_step = ep_logger.current_step + 1

            if current_step > task.max_steps:
                terminal_reason = TerminalReason.FAIL_MAX_STEPS
                episode_message = f"Exceeded max steps ({task.max_steps})"
                self._logger.warning("[Step %d] MAX STEPS EXCEEDED", current_step)
                break

            obs_result = self._observe_step(current_step, task)
            if obs_result is None:
                terminal_reason = TerminalReason.FAIL_ERROR
                episode_message = "Observe failed"
                break
            observation, obs_latency, screenshot_path, step_images = obs_result

            step_prompt = self.prompt_builder.build_step_prompt(
                observation=observation,
                extra_step_prompt=self._last_auto_eval_feedback,
            )

            plan_result = self._plan_action(
                current_step,
                action_planner,
                step_prompt,
                step_images,
                getattr(task, "step_timeout_seconds", None),
            )
            if plan_result is None:
                terminal_reason = TerminalReason.FAIL_ERROR
                episode_message = "LLM call failed"
                break

            action_decision, llm_latency = plan_result
            llm_response = action_decision.raw_response
            action_parsed = action_decision.action
            parse_success = action_decision.parse_success
            parse_error = action_decision.error or (None if parse_success else llm_response)

            observation_artifact = self._build_observation_artifact(
                observation,
                screenshot_path=screenshot_path,
                include_ui_tree=self._include_ui_tree_for_llm(),
                run_dir=run_dir,
            )

            if not parse_success:
                if self._is_provider_failure(parse_error):
                    terminal_reason = TerminalReason.FAIL_ERROR
                    episode_message = (
                        f"LLM provider error ({action_decision.mode_used}/{action_decision.adapter}): "
                        f"{parse_error}"
                    )
                    self._logger.error("[Step %d] LLM PROVIDER ERROR", current_step)
                else:
                    terminal_reason = TerminalReason.FAIL_PARSE
                    episode_message = (
                        f"Failed to parse action ({action_decision.mode_used}/{action_decision.adapter}): "
                        f"{parse_error}"
                    )
                    self._logger.warning("[Step %d] PARSE ERROR", current_step)

                step_record = ep_logger.create_step_record(
                    observation=observation_artifact,
                    prompt=step_prompt,
                    llm_response=llm_response,
                    llm_reasoning=action_decision.llm_reasoning,
                    action_parse=self._build_action_parse_payload(
                        action_parsed=None,
                        parse_success=False,
                        error=parse_error,
                    ),
                    action_execution=None,
                    latency_ms=obs_latency + llm_latency,
                )
                ep_logger.log_step(step_record)
                break

            assert action_parsed is not None
            action_result, action_success, action_error, action_latency = self._execute_action(
                current_step,
                action_parsed,
                observation.ui_nodes,
                observation=observation,
                default_python_timeout_seconds=max(1, int(getattr(task, "step_timeout_seconds", 120) or 120)),
            )
            is_terminal = bool((action_result or {}).get("terminal")) if isinstance(action_result, dict) else False
            action_type = action_parsed.get("type", "")
            if action_type == "python_code" and isinstance(action_result, dict):
                terminal_action_type = action_result.get("terminal_action_type")
                if terminal_action_type in {"success", "fail"}:
                    action_type = str(terminal_action_type)

            if is_terminal:
                if action_type == "success":
                    terminal_reason = TerminalReason.SUCCESS
                    if isinstance(action_result, dict):
                        episode_message = action_result.get("message")
                elif action_type == "fail":
                    terminal_reason = TerminalReason.FAIL_LLM
                    if isinstance(action_result, dict):
                        episode_message = action_result.get("message", "LLM reported failure")

            step_record = ep_logger.create_step_record(
                observation=observation_artifact,
                prompt=step_prompt,
                llm_response=llm_response,
                llm_reasoning=action_decision.llm_reasoning,
                action_parse=self._build_action_parse_payload(
                    action_parsed=action_parsed,
                    parse_success=True,
                    error=None,
                ),
                action_execution=self._build_action_execution_payload(
                    action_result=action_result,
                    action_success=action_success,
                    action_error=action_error,
                ),
                latency_ms=obs_latency + llm_latency + action_latency,
            )
            ep_logger.log_step(step_record)

            if is_terminal:
                break

            early_success_message = self._maybe_complete_from_evaluation(
                task=task,
                run_dir=run_dir,
            )
            if early_success_message is not None:
                terminal_reason = TerminalReason.SUCCESS
                episode_message = early_success_message
                self._logger.info(
                    "[Step %d] Early success from evaluator after action.",
                    current_step,
                )
                break

            time.sleep(self.step_settle_seconds)

        return self._finalize_episode(
            task=task,
            ep_logger=ep_logger,
            terminal_reason=terminal_reason,
            episode_message=episode_message,
            run_dir=run_dir,
            initialization_run=initialization_run,
        )
