from __future__ import annotations

import contextlib
import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.evaluation import EvalStatus
from evaluators.macos.maps import MapsStateEvaluator, normalize_text


class FakeController:
    def __init__(
        self,
        *,
        observation: Any | None = None,
        observe_error: Exception | None = None,
        bash_output: str = "",
    ) -> None:
        self.observation = observation
        self.observe_error = observe_error
        self.bash_output = bash_output

    def observe(self, *, include_ui_tree: bool, include_screenshot_data: bool) -> Any:
        assert include_ui_tree is True
        assert include_screenshot_data is False
        if self.observe_error is not None:
            raise self.observe_error
        return self.observation

    def run_bash_script(self, script: str, timeout: int = 30, working_dir: str | None = None) -> dict[str, Any]:
        return {"returncode": 0, "stdout": self.bash_output, "output": self.bash_output, "success": True}

    def run_python_script(self, code: str, timeout: int = 30, working_dir: str | None = None) -> dict[str, Any]:
        stdout = io.StringIO()
        namespace: dict[str, Any] = {"__name__": "__main__"}
        with contextlib.redirect_stdout(stdout):
            exec(code, namespace)
        return {"returncode": 0, "stdout": stdout.getvalue(), "output": stdout.getvalue(), "success": True}


def observation(*, bundle_id: str = "com.apple.Maps", texts: list[str] | None = None) -> SimpleNamespace:
    ui_nodes = [
        {"id": f"n{index}", "type": "AXStaticText", "text": text}
        for index, text in enumerate(texts or [], start=1)
    ]
    return SimpleNamespace(
        foreground_app="Maps",
        foreground_bundle_id=bundle_id,
        ui_nodes=ui_nodes,
    )


def test_normalize_text_collapses_whitespace_and_case() -> None:
    assert normalize_text(" Ferry   Building\nMarketplace ") == "ferry building marketplace"


def test_maps_evaluator_passes_foreground_required_text_and_groups() -> None:
    evaluator = MapsStateEvaluator()
    result = evaluator.evaluate(
        {
            "controller": FakeController(
                observation=observation(
                        texts=[
                            "Ferry Building Marketplace",
                            "Directions",
                            "San Francisco CA 94111",
                            "Share",
                        ]
                )
            ),
            "params": {
                "required_texts": ["Ferry Building Marketplace", "Directions"],
                "any_text_groups": [["San Francisco CA 94111", "37.79550° N"], ["Share", "Add"]],
                "min_node_count": 2,
            },
        }
    )

    assert result.status == EvalStatus.PASS


def test_maps_evaluator_fails_wrong_foreground_bundle() -> None:
    evaluator = MapsStateEvaluator()
    result = evaluator.evaluate(
        {
            "controller": FakeController(
                observation=observation(
                    bundle_id="com.apple.TextEdit",
                    texts=["Ferry Building Marketplace", "Directions", "Share"],
                )
            ),
            "params": {"required_texts": ["Ferry Building Marketplace"], "min_node_count": 1},
        }
    )

    assert result.status == EvalStatus.FAIL
    assert "expected foreground bundle" in str(result.message)


def test_maps_evaluator_fails_missing_required_text() -> None:
    evaluator = MapsStateEvaluator()
    result = evaluator.evaluate(
        {
            "controller": FakeController(observation=observation(texts=["Ferry Building Marketplace"])),
            "params": {"required_texts": ["Ferry Building Marketplace", "Directions"], "min_node_count": 1},
        }
    )

    assert result.status == EvalStatus.FAIL
    assert "missing required text" in str(result.message)


def test_maps_evaluator_uses_system_events_fallback_text() -> None:
    evaluator = MapsStateEvaluator()
    fallback_output = "\n".join(
        [
            "Maps",
            "com.apple.Maps",
            "----MAPS_TEXT----",
            "Palace of Fine Arts",
            "Walking",
            "Directions",
        ]
    )
    result = evaluator.evaluate(
        {
            "controller": FakeController(observe_error=RuntimeError("AX unavailable"), bash_output=fallback_output),
            "params": {"required_texts": ["Palace of Fine Arts", "Walking"], "min_node_count": 0},
        }
    )

    assert result.status == EvalStatus.PASS
    assert result.metadata["foreground_bundle_id"] == "com.apple.Maps"


def create_maps_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE ZCOLLECTION (ZTITLE TEXT)")
        conn.execute("CREATE TABLE ZHISTORYITEM (ZQUERY TEXT)")
        conn.execute("INSERT INTO ZCOLLECTION (ZTITLE) VALUES (?)", ("SF Field Briefing",))
        conn.execute("INSERT INTO ZHISTORYITEM (ZQUERY) VALUES (?)", ("Ferry Building Marketplace San Francisco",))
        conn.execute("INSERT INTO ZHISTORYITEM (ZQUERY) VALUES (?)", ("Palace of Fine Arts San Francisco",))
        conn.commit()
    finally:
        conn.close()


def test_maps_task_metadata_tracks_windows_aligned_hard_step_budget() -> None:
    import yaml

    route = yaml.safe_load(Path("tasks/macos/maps_walking_route_sf_hard.yaml").read_text())
    guide = yaml.safe_load(Path("tasks/macos/maps_sf_landmark_briefing_hard.yaml").read_text())

    assert "initial_url" not in route["init"]["params"]
    assert route["metadata"]["difficulty"] == "hard"
    assert route["metadata"]["human_steps"] >= 35
    assert "single_app" in route["metadata"]["tags"]
    assert "evaluator_backed" in route["metadata"]["tags"]

    assert guide["metadata"]["difficulty"] == "hard"
    assert guide["metadata"]["human_steps"] >= 40
    assert "Coit Tower" in guide["evaluation"]["params"]["required_texts"]
    assert ["3601 Lyon St", "3601 Lyon Street", "Palace of Fine Arts"] in guide["evaluation"]["params"]["any_text_groups"]
    assert ["Ferry Building Marketplace", "Ferry Building"] in guide["evaluation"]["params"]["any_text_groups"]


def test_maps_evaluator_sqlite_collection_and_history_pass(tmp_path: Path) -> None:
    db_path = tmp_path / "MapsSync_0.0.1"
    create_maps_db(db_path)

    evaluator = MapsStateEvaluator()
    result = evaluator.evaluate(
        {
            "controller": FakeController(observation=observation(texts=["SF Field Briefing", "Guides"])),
            "params": {
                "required_texts": ["SF Field Briefing"],
                "min_node_count": 1,
                "sqlite": {
                    "db_path": str(db_path),
                    "collections": ["SF Field Briefing"],
                    "history_queries": ["Ferry Building Marketplace", "Palace of Fine Arts"],
                },
            },
        }
    )

    assert result.status == EvalStatus.PASS
    assert result.metadata["sqlite"]["status"] == "pass"


def test_maps_evaluator_sqlite_collection_missing_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "MapsSync_0.0.1"
    create_maps_db(db_path)

    evaluator = MapsStateEvaluator()
    result = evaluator.evaluate(
        {
            "controller": FakeController(observation=observation(texts=["SF Field Briefing", "Guides"])),
            "params": {
                "required_texts": ["SF Field Briefing"],
                "min_node_count": 1,
                "sqlite": {
                    "db_path": str(db_path),
                    "collections": ["Missing Guide"],
                },
            },
        }
    )

    assert result.status == EvalStatus.FAIL
    assert "missing collection title: Missing Guide" in str(result.message)
