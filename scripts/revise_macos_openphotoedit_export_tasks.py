#!/usr/bin/env python3
"""Re-scope unreproducible OpenPhotoEdit tasks to independently verifiable exports."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tasks/v1/macos/assets/openphotoedit/PhotoFixtures"
TASKS = {
    "openphotoedit_macos1_fruit_product_film_exports.yaml": [
        ("Fruit-Pair.jpg", "fruit-warm.png"),
        ("Fruit-Pair-Rotated.jpg", "fruit-film.png"),
    ],
    "openphotoedit_macos1_floral_warm_night_exports.yaml": [
        ("Blue-Floral.jpg", "floral-warm.png"),
        ("Blue-Floral-Mirror.jpg", "floral-night.png"),
    ],
    "openphotoedit_macos1_anime_clean_floral_cool_exports.yaml": [
        ("Anime-Floral-Composite.jpg", "anime-clean.png"),
        ("Blue-Floral-Rotated.jpg", "floral-cool.png"),
    ],
    "openphotoedit_macos1_anime_soft_cream_exports.yaml": [
        ("Anime-Portrait.jpg", "anime-soft.png"),
        ("Anime-Portrait-Mirror.jpg", "anime-cream.png"),
    ],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    for filename, pairs in TASKS.items():
        path = ROOT / "tasks/v1/macos" / filename
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        outputs = []
        references = {}
        for source, output in pairs:
            reference = source.removesuffix(".jpg") + ".reference.png"
            outputs.append(output)
            references[output] = {
                "name": reference,
                "expected_sha256": digest(FIXTURES / reference),
            }
        step_text = "\n".join(
            f"Open {source} in OpenPhotoEdit and export the image as a PNG named {output} in PhotoFixtures, without applying edits."
            for source, output in pairs
        )
        task["instruction"] = (
            "In OpenPhotoEdit, create exact no-edit PNG exports from the specified source images. "
            "Select each source by its filename, preserve its appearance and orientation, and save "
            "the PNG into ~/Desktop/PhotoFixtures.\n\n"
            + step_text
            + "\n\nLeave OpenPhotoEdit open on the editor page for the second source."
        )
        task["init"]["params"]["fixture_version"] = "rgb-calibration-v3-author-rebuilt"
        task["evaluation"]["params"] = {
            "profile_id": "openphotoedit-export-only-v1",
            "fixture_dir": "~/Desktop/PhotoFixtures",
            "expected_width": 2512,
            "expected_height": 832,
            "expected_filenames": outputs,
            "expected_sha256": {},
            "reference_images": references,
            "marker_mae_tolerance": 3.0,
            "marker_peak_tolerance": 12.0,
            "image_mae_tolerance": 3.0,
            "median_tolerance": 3.0,
        }
        metadata = task.setdefault("metadata", {})
        metadata["description"] = "Identify the requested replacement source images and export exact no-edit PNG copies."
        metadata["difficulty"] = "medium"
        metadata["evaluation_standard"] = (
            "Both named PNGs must match their independent source-pixel references at 2512x832; "
            "wrong source, altered pixels, missing or corrupt export fails."
        )
        metadata["verifier_rules"] = {
            "primary_business_evidence": [
                "Each requested PNG exists, is readable, and has the dimensions of its source.",
                "RGB pixels match the independently decoded source reference within documented decoder tolerance.",
            ],
            "negative_cases": [
                "Wrong source, rotated source, missing output, malformed PNG, or visible pixel edits fail.",
            ],
            "evaluator_is_read_only": True,
            "evaluation_revision": "openphotoedit-export-only-v1",
        }
        metadata["initializer_message"] = (
            "The initializer restores versioned source and reference assets only when missing, opens OpenPhotoEdit, "
            "and removes only this task's stale target exports to provide a fresh starting state."
        )
        path.write_text(yaml.safe_dump(task, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
