from __future__ import annotations

import contextlib
import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from core.evaluation import EvalStatus
from evaluators.macos.photos import PhotosStateEvaluator, normalize_text


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


def observation(*, bundle_id: str = "com.apple.Photos", texts: list[str] | None = None) -> SimpleNamespace:
    ui_nodes = [
        {"id": f"n{index}", "type": "AXStaticText", "text": text}
        for index, text in enumerate(texts or [], start=1)
    ]
    return SimpleNamespace(
        foreground_app="Photos",
        foreground_bundle_id=bundle_id,
        ui_nodes=ui_nodes,
    )


def create_photos_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE ZASSET (
                Z_PK INTEGER PRIMARY KEY,
                ZFILENAME TEXT,
                ZDIRECTORY TEXT,
                ZFAVORITE INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ZADDITIONALASSETATTRIBUTES (
                ZASSET INTEGER,
                ZORIGINALFILENAME TEXT,
                ZTITLE TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ZGENERICALBUM (
                Z_PK INTEGER PRIMARY KEY,
                ZTITLE TEXT,
                ZCACHEDCOUNT INTEGER,
                ZKIND INTEGER
            )
            """
        )
        conn.execute("CREATE TABLE Z_30ASSETS (Z_30ALBUMS INTEGER, Z_3ASSETS INTEGER)")
        assets = [
            (1, "asset-1.png", "1", 1, "client_receipt_blue_final_774.png"),
            (2, "asset-2.png", "2", 1, "client_receipt_green_final_610.png"),
            (3, "asset-3.png", "3", 1, "client_receipt_red_final_203.png"),
        ]
        for pk, filename, directory, favorite, original in assets:
            conn.execute(
                "INSERT INTO ZASSET (Z_PK, ZFILENAME, ZDIRECTORY, ZFAVORITE) VALUES (?, ?, ?, ?)",
                (pk, filename, directory, favorite),
            )
            conn.execute(
                "INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET, ZORIGINALFILENAME, ZTITLE) VALUES (?, ?, ?)",
                (pk, original, ""),
            )
        conn.execute(
            "INSERT INTO ZGENERICALBUM (Z_PK, ZTITLE, ZCACHEDCOUNT, ZKIND) VALUES (?, ?, ?, ?)",
            (10, "Receipt Finals", 3, 2),
        )
        for pk in (1, 2, 3):
            conn.execute("INSERT INTO Z_30ASSETS (Z_30ALBUMS, Z_3ASSETS) VALUES (?, ?)", (10, pk))
        conn.commit()
    finally:
        conn.close()


def test_normalize_text_collapses_whitespace_and_case() -> None:
    assert normalize_text(" Final   Client\nSet ") == "final client set"


def test_photos_evaluator_passes_sqlite_assets_favorites_and_album(tmp_path: Path) -> None:
    db_path = tmp_path / "Photos.sqlite"
    create_photos_db(db_path)

    evaluator = PhotosStateEvaluator()
    result = evaluator.evaluate(
        {
            "controller": FakeController(observation=observation(texts=["Photos", "Receipt Finals"])),
            "params": {
                "db_path": str(db_path),
                "required_texts": ["Receipt Finals"],
                "min_node_count": 1,
                "expected_assets": [
                    "client_receipt_blue_final_774.png",
                    "client_receipt_green_final_610.png",
                    "client_receipt_red_final_203.png",
                ],
                "exact_asset_set": True,
                "favorite_assets": [
                    "client_receipt_blue_final_774.png",
                    "client_receipt_green_final_610.png",
                    "client_receipt_red_final_203.png",
                ],
                "albums": [
                    {
                        "title": "Receipt Finals",
                        "expected_assets": [
                            "client_receipt_blue_final_774.png",
                            "client_receipt_green_final_610.png",
                            "client_receipt_red_final_203.png",
                        ],
                        "exact_assets": True,
                        "min_count": 3,
                    }
                ],
            },
        }
    )

    assert result.status == EvalStatus.PASS
    assert result.metadata["sqlite"]["status"] == "pass"


def test_photos_evaluator_fails_forbidden_imported_asset(tmp_path: Path) -> None:
    db_path = tmp_path / "Photos.sqlite"
    create_photos_db(db_path)

    evaluator = PhotosStateEvaluator()
    result = evaluator.evaluate(
        {
            "controller": FakeController(observation=observation(texts=["Photos"])),
            "params": {
                "db_path": str(db_path),
                "min_node_count": 1,
                "forbidden_assets": ["client_receipt_blue_final_774.png"],
            },
        }
    )

    assert result.status == EvalStatus.FAIL
    assert "forbidden asset was imported: client_receipt_blue_final_774.png" in str(result.message)


def test_v1_photos_task_keeps_exact_asset_evaluation() -> None:
    favorite_hard = yaml.safe_load(Path("tasks/v1/macos/photos_favorite_receipts_hard.yaml").read_text())

    assert favorite_hard["metadata"]["difficulty"] == "hard"
    assert favorite_hard["metadata"]["human_steps"] >= 40
    assert "single_app" in favorite_hard["metadata"]["tags"]
    assert "evaluator_backed" in favorite_hard["metadata"]["tags"]
    assert favorite_hard["init"]["params"]["mode"] == "open"
    assert favorite_hard["evaluation"]["params"]["exact_asset_set"] is True
    assert favorite_hard["evaluation"]["params"]["albums"][0]["exact_assets"] is True
