"""Shared abstract episode runner with platform hooks."""

from __future__ import annotations

import logging
import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.llm.llm_client import LLMClientManager

from platforms.linux.agent.planners.reflection_pyautogui_planner import ReflectionPyAutoGUIPlanner
from platforms.linux.core.logger import EpisodeLogger
from platforms.linux.core.runtime_types import EpisodeResult, TerminalReason
from platforms.linux.runners.evaluation import evaluation_to_episode_outcome, run_task_evaluation
from platforms.linux.runners.initialization import initialization_to_episode_failure_message


# Windows keyboard events from pyautogui carry scan code 0, so apps that read scan codes (SDL,
# hence the scrcpy phone window) drop letters, digits and shortcuts. OS_OMNI_KEY_SCANCODES fills
# in the real scan code (and the extended-key flag for navigation keys) on Windows guests.
_WINDOWS_SCANCODE_PRELUDE = """import sys
if sys.platform == 'win32':
    import ctypes
    _osomni_user32 = ctypes.windll.user32
    _osomni_keybd_event = _osomni_user32.keybd_event
    _osomni_extended = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5}
    def _osomni_scancode_keybd_event(vk, scan, flags, extra):
        if not scan:
            scan = _osomni_user32.MapVirtualKeyW(vk, 0)
            if vk in _osomni_extended:
                flags |= 0x1
        return _osomni_keybd_event(vk, scan, flags, extra)
    _osomni_user32.keybd_event = _osomni_scancode_keybd_event
"""


def code_prelude() -> str:
    """Python run in the guest before each action's code."""
    prelude = (
        "import pyautogui, time\n"
        "pyautogui.PAUSE = 0\n"
        "pyautogui.FAILSAFE = False\n"
    )
    if os.environ.get("OS_OMNI_KEY_SCANCODES", "").strip() in {"1", "true", "yes"}:
        prelude += _WINDOWS_SCANCODE_PRELUDE
    # SDL windows (the scrcpy phone) read a button press at the last cursor position they were told
    # about; on Windows the move message can arrive after the press. OS_OMNI_POINTER_SETTLE moves the
    # cursor first and waits this many seconds before every press and release, also when the cursor
    # was moved by an earlier call (moveTo, then click or dragTo).
    settle = float(os.environ.get("OS_OMNI_POINTER_SETTLE", "0") or 0)
    if settle > 0:
        prelude += (
            "def _osomni_settled(press):\n"
            "    def settled(x=None, y=None, *args, **kwargs):\n"
            "        if x is not None or y is not None:\n"
            "            pyautogui.moveTo(*pyautogui._normalizeXYArgs(x, y))\n"
            "            x = y = None\n"
            f"        time.sleep({settle!r})\n"
            "        return press(x, y, *args, **kwargs)\n"
            "    return settled\n"
            "pyautogui.click = _osomni_settled(pyautogui.click)\n"
            "pyautogui.mouseDown = _osomni_settled(pyautogui.mouseDown)\n"
            "pyautogui.mouseUp = _osomni_settled(pyautogui.mouseUp)\n"
        )
    # Text typed into a mirrored phone (scrcpy) loses characters when keys are sent
    # back to back; OS_OMNI_MIN_TYPE_INTERVAL sets a minimum per-character interval.
    min_interval = float(os.environ.get("OS_OMNI_MIN_TYPE_INTERVAL", "0") or 0)
    if min_interval > 0:
        prelude += (
            "_osomni_write = pyautogui.write\n"
            "def _osomni_paced_write(message, interval=0.0, *args, **kwargs):\n"
            f"    return _osomni_write(message, max(float(interval or 0), {min_interval!r}), *args, **kwargs)\n"
            "pyautogui.write = pyautogui.typewrite = _osomni_paced_write\n"
        )
    return prelude


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
        observation_mode: str = "screenshot_only",
        save_trajectory: bool = True,
        output_dir: str,
        prompt_builder_cls: Any,
        history_window: int = 5,
        run_dir: Optional[Path] = None,
        step_settle_seconds: float = 0.3,
        client_password: str | None = None,
        logger_obj: Optional[logging.Logger] = None,
        resume_from_trajectory: Optional[Path] = None,
        skip_initialization: bool = False,
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
        self._resume_from_trajectory = Path(resume_from_trajectory) if resume_from_trajectory else None
        self._skip_initialization = bool(skip_initialization)

        if self.action_mode != "code_adapter":
            raise ValueError(
                f"Unsupported action_mode: {self.action_mode}. Expected code_adapter."
            )
        self.prompt_builder = prompt_builder_cls(
            observation_mode=self.observation_mode,
            tool_calling=False,
            action_mode=self.action_mode,
            client_password=client_password,
        )

    @classmethod
    def _normalize_observation_mode(cls, raw_mode: str) -> str:
        normalized = str(raw_mode or "").strip().lower()
        if not normalized:
            return "screenshot_only"
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
        return path.exists()

    def _max_runtime_recoveries_per_step(self) -> int:
        return 0

    def _is_recoverable_runtime_error(self, error: Exception | str) -> bool:
        return False

    def _recover_runtime_after_error(
        self,
        *,
        phase: str,
        current_step: int,
        error: Exception | str,
    ) -> bool:
        return False

    def _reflection_pyautogui_planner_cls(self) -> Any:
        return ReflectionPyAutoGUIPlanner

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
        include_screenshot = self._include_screenshot_for_llm()
        for recovery_attempt in range(self._max_runtime_recoveries_per_step() + 1):
            try:
                observation = self._observe(
                    include_ui_tree=self._include_ui_tree_for_llm(),
                    include_screenshot=include_screenshot,
                )
                break
            except Exception as e:
                self._logger.error("[Step %d] Observe failed: %s", current_step, e)
                can_recover = (
                    recovery_attempt < self._max_runtime_recoveries_per_step()
                    and self._is_recoverable_runtime_error(e)
                )
                if not can_recover:
                    return None
                recovered = self._recover_runtime_after_error(
                    phase="observe",
                    current_step=current_step,
                    error=e,
                )
                if not recovered:
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

    def _execute_action(self, current_step: int, action_parsed: Dict[str, Any], ui_nodes: List[Dict[str, Any]]):
        self._logger.info("[Step %d] Action: %s", current_step, action_parsed)
        action_start = time.time()
        action_error = None
        try:
            if str(action_parsed.get("type") or "").strip() == "python_code":
                timeout_seconds = max(1, int(action_parsed.get("timeout_seconds", 30) or 30))
                code = str(action_parsed.get("code") or "").strip()
                prelude = code_prelude()
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
                    "return_code": raw_result.get("return_code"),
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
            if self._is_recoverable_runtime_error(e):
                self._recover_runtime_after_error(
                    phase="action",
                    current_step=current_step,
                    error=e,
                )
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

    def _run_task_evaluation(
        self,
        *,
        task: Any,
        final_observation: Any,
        run_dir: Path,
        trajectory_path: Optional[Path],
    ) -> Any:
        return run_task_evaluation(
            task=task,
            controller=self.controller,
            final_observation=final_observation,
            model_id=self.model_id,
            run_dir=run_dir,
            trajectory_path=trajectory_path,
            logger_obj=self._logger,
        )

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

    def _load_resume_records(self, run_dir: Path) -> Tuple[int, List[Dict[str, Any]]]:
        trajectory_path = self._resume_from_trajectory
        if trajectory_path is None:
            return 0, []
        if not trajectory_path.is_absolute():
            trajectory_path = (run_dir / trajectory_path).resolve()
        if not trajectory_path.is_file():
            raise FileNotFoundError(f"Resume trajectory not found: {trajectory_path}")

        records: List[Dict[str, Any]] = []
        with trajectory_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
        if not records:
            return 0, []
        last_step = max(int(record.get("step_index") or 0) for record in records)
        seeded = [
            record
            for record in records[-self.history_window :]
            if str(record.get("prompt") or "").strip()
            and str(record.get("llm_response") or "").strip()
        ]
        return last_step, seeded

    def _seed_action_planner_from_records(
        self,
        action_planner: Any,
        records: List[Dict[str, Any]],
        run_dir: Path,
    ) -> None:
        if not records or not hasattr(action_planner, "seed_history_steps"):
            return
        seeded_steps: List[List[Dict[str, Any]]] = []
        for record in records:
            parts: List[Dict[str, str]] = [{"type": "text", "text": str(record.get("prompt") or "")}]
            observation = record.get("observation")
            screenshot_path = None
            if isinstance(observation, dict):
                screenshot_path = observation.get("screenshot_path")
            if screenshot_path:
                path = Path(str(screenshot_path))
                if not path.is_absolute():
                    path = (run_dir / path).resolve()
                if path.is_file():
                    parts.append({"type": "image", "path": str(path)})
            seeded_steps.append(
                [
                    {"role": "user", "parts": parts},
                    {
                        "role": "assistant",
                        "parts": [{"type": "text", "text": str(record.get("llm_response") or "[empty response]")}],
                    },
                ]
            )
        action_planner.seed_history_steps(seeded_steps)
        self._logger.info("Seeded LLM history with %d resumed steps.", len(seeded_steps))

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

        if os.environ.get("HELLOWORLD_SKIP_FINAL_OBSERVATION", "").strip().lower() in {"1", "true", "yes"}:
            final_observation, final_screenshot = None, None
        else:
            final_observation, final_screenshot = self._observe_final_state()
        final_observation_artifact = self._build_observation_artifact(
            final_observation,
            screenshot_path=final_screenshot,
            include_ui_tree=True,
            run_dir=run_dir,
        )

        evaluation_run = None
        if not skip_evaluation:
            evaluation_run = self._run_task_evaluation(
                task=task,
                final_observation=final_observation,
                run_dir=run_dir,
                trajectory_path=ep_logger.trajectory_path,
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

        resume_last_step, resume_records = self._load_resume_records(run_dir)
        if resume_last_step:
            ep_logger.set_current_step(resume_last_step)
            self._logger.info("Resuming episode from step %d.", resume_last_step)

        initialization_run = None
        if self._skip_initialization:
            self._logger.info("Skipping task initialization for resumed episode.")
        else:
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
        session_metadata = {"task_id": task.id, "task_instruction": task.goal}
        planner_cls = self._reflection_pyautogui_planner_cls()
        action_planner = planner_cls(
            llm_client=self.llm_client,
            model_id=self.model_id,
            system_prompt=action_system_prompt,
            history_window=self.history_window,
            session_metadata=session_metadata,
        )
        self._seed_action_planner_from_records(action_planner, resume_records, run_dir)
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

            step_prompt = self.prompt_builder.build_step_prompt(observation=observation)

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
                else:
                    self._logger.warning("[Step %d] PARSE ERROR (continuing)", current_step)

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
                    time.sleep(self.step_settle_seconds)
                    continue

            assert action_parsed is not None
            action_result, action_success, action_error, action_latency = self._execute_action(
                current_step,
                action_parsed,
                observation.ui_nodes,
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

            time.sleep(self.step_settle_seconds)

        return self._finalize_episode(
            task=task,
            ep_logger=ep_logger,
            terminal_reason=terminal_reason,
            episode_message=episode_message,
            run_dir=run_dir,
            initialization_run=initialization_run,
        )
