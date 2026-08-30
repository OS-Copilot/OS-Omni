"""Android episode runner base class.

Standalone copy of the shared BaseEpisodeRunner logic, with Android-specific
imports.  The eval-override fix (episode ERROR + eval PASS → PASS) is
included here.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.llm.llm_client import LLMClientManager

from platforms.android.agent.planners.reflection_adb_planner import (
    ReflectionAdbPlanner,
    scale_screenshot_only_adb_coordinates,
)
from platforms.android.core.logger import EpisodeLogger
from platforms.android.core.runtime_types import EpisodeResult, TerminalReason
from platforms.android.runners.evaluation import evaluation_to_episode_outcome, run_task_evaluation
from platforms.android.runners.initialization import initialization_to_episode_failure_message


_SCREENSHOT_ONLY_COORDINATE_UPSCALE_ENV = "ANDROID_SCREENSHOT_ONLY_COORDINATE_UPSCALE"
_SCREENSHOT_ONLY_VISION_LONG_EDGE_ENV = "ANDROID_SCREENSHOT_ONLY_VISION_LONG_EDGE"
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}


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
        )

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
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

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
    ) -> Optional[Tuple[Any, float, str, Optional[List[str]]]]:
        self._logger.info("[Step %d] Observing...", current_step)
        obs_start = time.time()
        try:
            include_screenshot = self._include_screenshot_for_llm()
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

    def _build_extra_step_prompt(self, observation: Any) -> Optional[str]:
        if self.observation_mode != "screenshot_only":
            return None

        width = getattr(observation, "width", None)
        height = getattr(observation, "height", None)
        if width and height and self.action_mode == "code_adapter":
            return (
                f"Current screenshot coordinate system is {int(width)}x{int(height)}. "
                "Use integer pixel coordinates in adb shell input commands."
            )
        return None

    def _execute_action(self, current_step: int, action_parsed: Dict[str, Any], ui_nodes: List[Dict[str, Any]]):
        self._logger.info("[Step %d] Action: %s", current_step, action_parsed)
        action_start = time.time()
        action_error = None
        try:
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

    def _maybe_upscale_screenshot_only_adb_coordinates(
        self,
        action_parsed: Dict[str, Any],
        observation: Any,
    ) -> Dict[str, Any]:
        if self.action_mode != "code_adapter" or self.observation_mode != "screenshot_only":
            return action_parsed
        if str(os.environ.get(_SCREENSHOT_ONLY_COORDINATE_UPSCALE_ENV, "0")).strip().lower() in _FALSE_ENV_VALUES:
            return action_parsed

        vision_long_edge_raw = os.environ.get(_SCREENSHOT_ONLY_VISION_LONG_EDGE_ENV, "2048")
        try:
            vision_long_edge = float(vision_long_edge_raw)
        except (TypeError, ValueError):
            vision_long_edge = 2048.0

        transformed, metadata = scale_screenshot_only_adb_coordinates(
            action_parsed,
            screen_width=int(getattr(observation, "width", 0) or 0),
            screen_height=int(getattr(observation, "height", 0) or 0),
            vision_long_edge=vision_long_edge,
        )
        if metadata:
            self._logger.info(
                "Applied screenshot-only adb coordinate upscale: scale=%.6f commands=%s",
                metadata["scale"],
                metadata["commands_changed"],
            )
        return transformed

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
                controller=self.controller,
                final_observation=final_observation,
                model_id=self.model_id,
                run_dir=run_dir,
                trajectory_path=ep_logger.trajectory_path,
                logger_obj=self._logger,
            )

        episode_result = self._build_episode_result(terminal_reason, episode_message)
        final_status = episode_result["status"]
        final_message = episode_message

        if final_status != "ERROR" and evaluation_run is not None:
            final_status, final_message = evaluation_to_episode_outcome(evaluation_run.result)
            if final_status == "PASS":
                self._logger.info("Final episode verdict is PASS from evaluator.")
            else:
                self._logger.info(
                    "Final episode verdict is %s from evaluator.",
                    evaluation_run.result.status.value,
                )
        elif final_status == "ERROR" and evaluation_run is not None:
            # Even when the episode ended with an error (e.g. observe failure),
            # we still check the eval – if it PASSES, the task actually succeeded.
            eval_status, eval_message = evaluation_to_episode_outcome(evaluation_run.result)
            if eval_status == "PASS":
                final_status = "PASS"
                final_message = eval_message
                self._logger.info(
                    "Episode had error but evaluator says PASS – overriding to PASS."
                )
            else:
                self._logger.info(
                    "Episode error confirmed by evaluator (%s).",
                    evaluation_run.result.status.value,
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
        action_planner = ReflectionAdbPlanner(
            llm_client=self.llm_client,
            model_id=self.model_id,
            system_prompt=action_system_prompt,
            history_window=self.history_window,
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

            obs_result = self._observe_step(current_step)
            if obs_result is None:
                terminal_reason = TerminalReason.FAIL_ERROR
                episode_message = "Observe failed"
                break
            observation, obs_latency, screenshot_path, step_images = obs_result

            step_prompt = self.prompt_builder.build_step_prompt(
                observation=observation,
                extra_step_prompt=self._build_extra_step_prompt(observation),
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
                    self._logger.error("[Step %d] LLM PROVIDER ERROR: %s", current_step, parse_error)
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
            action_parsed = self._maybe_upscale_screenshot_only_adb_coordinates(
                action_parsed,
                observation,
            )
            action_validation_error = None
            if hasattr(self.controller, "validate_action_for_observation_mode"):
                action_validation_error = self.controller.validate_action_for_observation_mode(
                    action_parsed,
                    observation_mode=self.observation_mode,
                )
            if action_validation_error:
                terminal_reason = TerminalReason.FAIL_PARSE
                episode_message = (
                    f"Invalid action for {self.observation_mode} "
                    f"({action_decision.mode_used}/{action_decision.adapter}): {action_validation_error}"
                )
                self._logger.warning("[Step %d] ACTION VALIDATION ERROR: %s", current_step, action_validation_error)
                step_record = ep_logger.create_step_record(
                    observation=observation_artifact,
                    prompt=step_prompt,
                    llm_response=llm_response,
                    llm_reasoning=action_decision.llm_reasoning,
                    action_parse=self._build_action_parse_payload(
                        action_parsed=action_parsed,
                        parse_success=False,
                        error=action_validation_error,
                    ),
                    action_execution=None,
                    latency_ms=obs_latency + llm_latency,
                )
                ep_logger.log_step(step_record)
                break
            action_result, action_success, action_error, action_latency = self._execute_action(
                current_step,
                action_parsed,
                observation.ui_nodes,
            )
            is_terminal = bool((action_result or {}).get("terminal")) if isinstance(action_result, dict) else False
            action_type = action_parsed.get("type", "")

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

            time.sleep(self.step_settle_seconds)

        return self._finalize_episode(
            task=task,
            ep_logger=ep_logger,
            terminal_reason=terminal_reason,
            episode_message=episode_message,
            run_dir=run_dir,
            initialization_run=initialization_run,
        )
