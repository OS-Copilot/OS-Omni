from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections import Counter
from pathlib import Path

import yaml

from core.evaluation import BaseEvaluator, load_evaluator
from core.init import BaseInitializer, load_initializer
from core.specs.loader import load_task_spec
from tools.import_cua_tasks_review import _model_instruction, _ordered_requirements

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tasks" / "v1" / "cua_tasks_review_manifest.json"
INSTRUCTION_MAP_PATH = REPO_ROOT / "tasks" / "v1" / "cua_tasks_review_instructions.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_cua_review_manifest_covers_all_generated_tasks() -> None:
    manifest = _manifest()
    entries = manifest["tasks"]
    generated = [REPO_ROOT / entry["task_path"] for entry in entries]

    # 12 imported tasks were later rebuilt outside the review pack (Windows OpenPhotoEdit -> GIMP and
    # OpenNavigation, iOS OpenPhotoEdit; commit 5cad99f) and carry no cua_tasks_review provenance.
    assert manifest["task_count"] == 200
    assert len(entries) == 200
    assert len(generated) == 200
    assert all(path.is_file() for path in generated)
    assert manifest["platform_counts"] == {
        "android": 48,
        "ios": 30,
        "linux": 58,
        "macos": 33,
        "windows": 31,
    }
    assert manifest["extraction_counts"] == {
        "reconstructed_artifacts": 1,
        "reconstructed_flat_args": 4,
        "repaired_partial_snapshot": 1,
        "task_snapshot": 194,
    }
    # PR #19 restores six Windows workflows verbatim (preserve_original_instruction in the map).
    assert manifest["instruction_summary_source_counts"] == {
        "generated_english_natural_language": 194,
        "preserved_source_instruction": 6,
    }
    assert {entry["task_path"] for entry in entries} == {
        path.relative_to(REPO_ROOT).as_posix() for path in generated
    }
    # Web tasks run on the Linux VM but live in their own release track folder.
    assert all(
        Path(entry["task_path"]).parent.name
        in ({entry["platform"], "web"} if entry["platform"] == "linux" else {entry["platform"]})
        for entry in entries
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

    assert len(task_ids) == 200
    assert len(set(task_ids)) == 200
    assert all(task_id == task_id.lower() for task_id in task_ids)
    assert Counter(spec.platform for spec in specs) == {
        "android": 48,
        "ios": 30,
        "linux": 58,
        "macos": 33,
        "windows": 31,
    }


def test_instructions_are_english_natural_language_with_current_hashes() -> None:
    records = json.loads(INSTRUCTION_MAP_PATH.read_text(encoding="utf-8"))[
        "instructions"
    ]
    for entry in _manifest()["tasks"]:
        spec = load_task_spec(entry["task_path"])
        provenance = spec.metadata["cua_tasks_review"]
        assert provenance["source_instruction_sha256"]
        assert spec.instruction == records[spec.task_id]["instruction"]
        preserved = provenance["instruction_format"] == "original_numbered_workflow"
        if preserved:
            # Kept verbatim on purpose (PR #19); the English-brief style rules below do not apply.
            assert records[spec.task_id].get("preserve_original_instruction") is True
        else:
            assert provenance["instruction_format"] == "english_natural_language"
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
        # Evaluators bind to the source instruction the runners pass them, or (when a task's brief was
        # rewritten after review, e.g. ios.opennote.live_music_visuals_three_notes_495011 in 5cad99f) to the
        # current English instruction.
        source = provenance["source_instruction"]
        assert (
            hashlib.sha256(source.encode("utf-8")).hexdigest()
            == provenance["source_instruction_sha256"]
        )
        evaluation_params = spec.evaluation.params
        if "expected_instruction_sha256" in evaluation_params:
            assert evaluation_params["expected_instruction_sha256"] in {
                hashlib.sha256(text.encode("utf-8")).hexdigest()
                for text in (source, source.rstrip("\n") + "\n", spec.instruction)
            }


def test_english_instruction_map_covers_imported_tasks() -> None:
    payload = json.loads(INSTRUCTION_MAP_PATH.read_text(encoding="utf-8"))
    records = payload["instructions"]
    task_ids = {entry["task_id"] for entry in _manifest()["tasks"]}

    assert payload["style_version"] == 2
    # Briefs of reviewed tasks outside the current selection are kept for reuse.
    assert set(records) >= task_ids
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


def test_every_cua_review_evaluator_loads_through_the_runner_loader() -> None:
    manifest = _manifest()

    assert manifest["unresolved_evaluator_task_count"] == 0
    for entry in manifest["tasks"]:
        spec = load_task_spec(entry["task_path"])
        assert spec.evaluation.evaluator_id == entry["evaluator_id"]
        assert isinstance(load_evaluator(entry["evaluator_id"]), BaseEvaluator)


# Tasks whose release initializer was replaced on purpose in 5cad99f (consolidated source sync): Maily seeds its
# benchmark mailbox, and the iOS OpenDriver driver tasks start from a cleaned backend state.
DELIBERATELY_REPLACED_INITIALIZERS = {
    "ios.maily.instruction_3_1": "initializers.ios.maily_benchmark_seed:MailyBenchmarkSeedInitializer",
    "ios.maily.instruction_3_2": "initializers.ios.maily_benchmark_seed:MailyBenchmarkSeedInitializer",
    "ios.maily.instruction_3_3": "initializers.ios.maily_benchmark_seed:MailyBenchmarkSeedInitializer",
    "ios.opendriver.driver_payout_trip_support_profile": "evaluators.cua_review.initializers.ios.opendriver_clean:OpenDriverCleanIOSInitializer",
    "ios.opendriver.driver_requests_insurance_support_payout": "evaluators.cua_review.initializers.ios.opendriver_clean:OpenDriverCleanIOSInitializer",
}


def test_every_cua_review_initializer_loads_through_the_runner_loader() -> None:
    manifest = _manifest()

    assert manifest["unresolved_initializer_task_count"] == 0
    assert manifest["implementation_ready_count"] == manifest["task_count"]
    for entry in manifest["tasks"]:
        spec = load_task_spec(entry["task_path"])
        assert spec.init.initializer_id == entry["initializer_id"]
        assert isinstance(load_initializer(entry["initializer_id"]), BaseInitializer)
        task = yaml.safe_load((REPO_ROOT / entry["task_path"]).read_text(encoding="utf-8"))
        original = task["metadata"]["cua_tasks_review"].get("original_initializer_id")
        if entry["task_id"] in DELIBERATELY_REPLACED_INITIALIZERS:
            # The release initializer stays recorded as provenance; the task now uses a replacement.
            assert original and entry["initializer_id"] == DELIBERATELY_REPLACED_INITIALIZERS[entry["task_id"]]
        elif entry["initializer_id"].startswith("evaluators.cua_review."):
            assert original and entry["initializer_id"] == f"evaluators.cua_review.{original}"
        else:
            assert original is None


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
