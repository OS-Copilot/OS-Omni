#!/usr/bin/env python3
"""Build independent no-edit PNG references from versioned OpenPhotoEdit JPEGs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tasks/v1/macos/assets/openphotoedit/PhotoFixtures"
SOURCES = {
    "Anime-Portrait.jpg": "Anime-Portrait.reference.png",
    "Anime-Portrait-Mirror.jpg": "Anime-Portrait-Mirror.reference.png",
    "Anime-Floral-Composite.jpg": "Anime-Floral-Composite.reference.png",
    "Blue-Floral.jpg": "Blue-Floral.reference.png",
    "Blue-Floral-Mirror.jpg": "Blue-Floral-Mirror.reference.png",
    "Blue-Floral-Rotated.jpg": "Blue-Floral-Rotated.reference.png",
    "Fruit-Pair.jpg": "Fruit-Pair.reference.png",
    "Fruit-Pair-Rotated.jpg": "Fruit-Pair-Rotated.reference.png",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest_path = FIXTURES / "CalibrationManifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    refs = {}
    for source_name, reference_name in SOURCES.items():
        source = FIXTURES / source_name
        reference = FIXTURES / reference_name
        with Image.open(source) as image:
            image.convert("RGB").save(reference, format="PNG", optimize=False)
        refs[reference_name] = {
            "source": source_name,
            "transform": "identity/no-edit export reference",
            "sha256": sha256(reference),
            "bytes": reference.stat().st_size,
            "dimensions": list(Image.open(reference).size),
        }
    manifest["evaluation_references"] = refs
    manifest["evaluation_revision"] = {
        "version": "openphotoedit-export-only-v1",
        "rationale": "Original edited-output hashes and RGB reference files were absent. The task was revised to test source identification and lossless PNG export, with independent pixel references generated from the versioned replacement JPEGs.",
        "generator": "scripts/rebuild_macos_openphotoedit_references.py",
        "comparison": "RGB pixel comparison with small decoder tolerance; wrong-source or edited output fails.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, item in refs.items():
        print(f"{name} sha256={item['sha256']} dimensions={item['dimensions']}")


if __name__ == "__main__":
    main()
