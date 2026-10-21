from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
import yaml

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.macos.openphotoedit_macos1_fruit_product_film_exports import (
    OpenPhotoEditFruitProductFilmEvaluator,
)


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/v1/macos/openphotoedit_macos1_fruit_product_film_exports.yaml"
FIXTURES = ROOT / "tasks/v1/macos/assets/openphotoedit/PhotoFixtures"


def _png_evidence(path: Path, name: str) -> dict:
    raw = path.read_bytes()
    return {
        "name": name,
        "exists": True,
        "readable": True,
        "size_bytes": len(raw),
        "dimensions": [2512, 832],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "data": base64.b64encode(raw).decode("ascii"),
    }


def _collected(outputs: dict[str, Path]) -> dict:
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    names = {name for name, _ in task["evaluation"]["params"]["reference_images"].items()}
    refs = {
        "fruit-warm.png": FIXTURES / "Fruit-Pair.reference.png",
        "fruit-film.png": FIXTURES / "Fruit-Pair-Rotated.reference.png",
    }
    images = {name: _png_evidence(path, name) for name, path in outputs.items()}
    fixture_files = {
        name: _png_evidence(path, name) for name, path in refs.items() if name in names
    }
    return {
        "images": images,
        "fixtures": {
            "PhotoFixtures": {
                "path": "~/Desktop/PhotoFixtures",
                "files": fixture_files,
            }
        },
    }


def _evaluate(outputs: dict[str, Path]):
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    return OpenPhotoEditFruitProductFilmEvaluator().evaluate(
        {
            "task": task,
            "params": task["evaluation"]["params"],
            "collected_state": _collected(outputs),
        }
    )


def test_correct_no_edit_exports_pass() -> None:
    result = _evaluate(
        {
            "fruit-warm.png": FIXTURES / "Fruit-Pair.reference.png",
            "fruit-film.png": FIXTURES / "Fruit-Pair-Rotated.reference.png",
        }
    )
    assert result.status == EvalStatus.PASS


@pytest.mark.parametrize(
    "outputs",
    [
        {
            "fruit-warm.png": FIXTURES / "Fruit-Pair-Rotated.reference.png",
            "fruit-film.png": FIXTURES / "Fruit-Pair.reference.png",
        },
        {"fruit-warm.png": FIXTURES / "Fruit-Pair.reference.png"},
    ],
)
def test_wrong_source_or_missing_export_fails(outputs: dict[str, Path]) -> None:
    result = _evaluate(outputs)
    assert result.status == EvalStatus.FAIL
