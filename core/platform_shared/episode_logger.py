"""Helper for logging episodic trajectories."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .runtime_types import EpisodeResult, StepRecord


class EpisodeLogger:
    """Collects and persists step records during an episode."""

    def __init__(self, task_id: str, output_dir: str = "run"):
        self.task_id = task_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.trajectory_path = self.output_dir / "trajectory.jsonl"
        self.step_records: List[StepRecord] = []
        self.start_time = datetime.now().astimezone()
        self._current_step = 0

    @staticmethod
    def iso_now() -> str:
        return datetime.now().astimezone().isoformat(timespec="microseconds")

    def log_step(self, step_record: StepRecord) -> None:
        self.step_records.append(step_record)
        self._current_step = step_record.step_index
        with self.trajectory_path.open("a", encoding="utf-8") as fh:
            fh.write(step_record.to_jsonl_line())
            fh.write("\n")

    def set_current_step(self, step_index: int) -> None:
        self._current_step = max(0, int(step_index))

    def create_step_record(
        self,
        observation: Dict[str, Any],
        prompt: str,
        llm_response: str,
        action_parse: Dict[str, Any],
        action_execution: Optional[Dict[str, Any]],
        latency_ms: float,
        llm_reasoning: Optional[Dict[str, Any]] = None,
    ) -> StepRecord:
        self._current_step += 1
        return StepRecord(
            step_index=self._current_step,
            timestamp=self.iso_now(),
            observation=observation,
            prompt=prompt,
            llm_response=llm_response,
            llm_reasoning=llm_reasoning,
            action_parse=action_parse,
            action_execution=action_execution,
            latency_ms=latency_ms,
        )

    def finalize(
        self,
        *,
        platform: str,
        model_id: str,
        status: str,
        episode_result: Dict[str, Any],
        initializer: Optional[Dict[str, Any]],
        evaluation: Optional[Dict[str, Any]],
        final_observation: Dict[str, Any],
    ) -> EpisodeResult:
        end_time = datetime.now().astimezone()
        latency_ms = (end_time - self.start_time).total_seconds() * 1000

        return EpisodeResult(
            task_id=self.task_id,
            platform=platform,
            model_id=model_id,
            status=status,
            started_at=self.start_time.isoformat(timespec="microseconds"),
            ended_at=end_time.isoformat(timespec="microseconds"),
            steps_taken=self._current_step,
            latency_ms=latency_ms,
            episode_result=episode_result,
            initializer=initializer,
            evaluation=evaluation,
            final_observation=final_observation,
        )

    @property
    def current_step(self) -> int:
        return self._current_step
