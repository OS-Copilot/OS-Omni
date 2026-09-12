from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections import Counter
from pathlib import Path

from core.specs.loader import load_task_spec
from tools.import_cua_tasks_review import _model_instruction, _ordered_requirements

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tasks" / "cua_tasks_review_manifest.json"
INSTRUCTION_MAP_PATH = REPO_ROOT / "tasks" / "cua_tasks_review_instructions.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_cua_review_manifest_covers_all_generated_tasks() -> None:
    manifest = _manifest()
    entries = manifest["tasks"]
    generated = [REPO_ROOT / entry["task_path"] for entry in entries]

    assert manifest["task_count"] == 303
    assert len(entries) == 303
    assert len(generated) == 303
    assert all(path.is_file() for path in generated)
    assert manifest["platform_counts"] == {
        "android": 60,
        "ios": 36,
        "linux": 131,
        "macos": 35,
        "windows": 41,
    }
    assert manifest["extraction_counts"] == {
        "reconstructed_artifacts": 1,
        "reconstructed_flat_args": 4,
        "repaired_partial_snapshot": 1,
        "task_snapshot": 297,
    }
    assert manifest["instruction_summary_source_counts"] == {
        "generated_english_natural_language": 303,
    }
    assert {entry["task_path"] for entry in entries} == {
        path.relative_to(REPO_ROOT).as_posix() for path in generated
    }
    assert all(
        Path(entry["task_path"]).parent.name == entry["platform"] for entry in entries
    )
    assert not any("cua_tasks_review" in entry["task_path"] for entry in entries)
    assert not any("cua_tasks_review" in entry["evaluator_id"] for entry in entries)
    assert not any(
        (REPO_ROOT / "tasks" / platform / "cua_tasks_review").exists()
        for platform in ("android", "ios", "linux", "macos", "windows")
    )


def test_all_cua_review_tasks_satisfy_task_spec_schema() -> None:
    specs = [load_task_spec(entry["task_path"]) for entry in _manifest()["tasks"]]
    task_ids = [spec.task_id for spec in specs]

    assert len(task_ids) == 303
    assert len(set(task_ids)) == 303
    assert all(task_id == task_id.lower() for task_id in task_ids)
    assert Counter(spec.platform for spec in specs) == {
        "android": 60,
        "ios": 36,
        "linux": 131,
        "macos": 35,
        "windows": 41,
    }


def test_instructions_are_english_natural_language_with_current_hashes() -> None:
    records = json.loads(INSTRUCTION_MAP_PATH.read_text(encoding="utf-8"))[
        "instructions"
    ]
    for entry in _manifest()["tasks"]:
        spec = load_task_spec(entry["task_path"])
        provenance = spec.metadata["cua_tasks_review"]
        assert provenance["instruction_format"] == "english_natural_language"
        assert provenance["source_instruction_sha256"]
        assert spec.instruction == records[spec.task_id]["instruction"]
        assert not re.search(r"[\u3400-\u9fff]", spec.instruction)
        assert not re.search(r"(?m)^\s*(?:[-*#]|\d+[.)])\s+", spec.instruction)
        prose = re.sub(r'`[^`]*`|"[^"\n]*"|“[^”\n]*”', "", spec.instruction)
        assert not re.search(
            r"(?i)\b(?:double[- ]click|click|tap|scroll|swipe)(?:s|ed|ing)?\b|"
            r"\bwait\s+(?:for|until)\b|\[step\s+\d+\]",
            prose,
        )
        assert not re.match(r"^\s*1[.)、]", spec.instruction)
        current_hash = hashlib.sha256(spec.instruction.encode("utf-8")).hexdigest()
        metadata = spec.metadata
        for key in (
            "instruction_sha256",
            "canonical_instruction_sha256",
            "current_instruction_sha256",
        ):
            if key in metadata:
                assert metadata[key] == current_hash
        evaluation_params = spec.evaluation.params
        if "expected_instruction_sha256" in evaluation_params:
            assert evaluation_params["expected_instruction_sha256"] == current_hash


def test_english_instruction_map_exactly_covers_imported_tasks() -> None:
    payload = json.loads(INSTRUCTION_MAP_PATH.read_text(encoding="utf-8"))
    records = payload["instructions"]
    task_ids = {entry["task_id"] for entry in _manifest()["tasks"]}

    assert payload["style_version"] == 2
    assert len(records) == 303
    assert set(records) == task_ids
    assert all(record["style_version"] == 2 for record in records.values())


def test_model_instruction_preserves_every_source_requirement_in_order() -> None:
    source = """在 OpenNote 中完成以下操作，不要改变指定文本。
1. 点击 New note。
2. 在标题中输入 `Release checklist`。
3. 输入第一行 `Owner: Maya`，并按键盘 Return 键。
4. 输入第二行 `Due: 2026-09-15`。
5. 保存，并让该笔记保持打开状态。"""
    task = {
        "task_id": "linux.opennote.release_checklist",
        "instruction": source,
        "metadata": {"description": "Create the requested release checklist note."},
    }

    instruction = _model_instruction(task)
    positions = [instruction.index(item) for item in _ordered_requirements(source)]

    assert positions == sorted(positions)
    assert "并按键盘 Return 键" in instruction


def test_implementation_ready_entries_have_importable_classes() -> None:
    ready = [entry for entry in _manifest()["tasks"] if entry["implementation_ready"]]

    assert ready
    for entry in ready:
        for key in ("initializer_id", "evaluator_id"):
            import_id = entry[key]
            if not import_id:
                continue
            module_name, class_name = import_id.split(":", 1)
            module = importlib.import_module(module_name)
            assert getattr(module, class_name) is not None


def test_normalized_legacy_ids_keep_original_id_in_manifest() -> None:
    normalized = {
        entry["task_id"]: entry["original_task_id"]
        for entry in _manifest()["tasks"]
        if "original_task_id" in entry
    }

    assert normalized == {
        "ios.opendriver.11-1": "ios.OpenDriver.11-1",
        "ios.opendriver.11-2": "ios.OpenDriver.11-2",
    }
