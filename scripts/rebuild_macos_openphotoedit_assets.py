#!/usr/bin/env python3
"""Rebuild the missing macOS OpenPhotoEdit fixture set from versioned sources.

The original macOS1 PhotoFixtures directory was missing. The PNG sources in
``tasks/v1/macos/assets/openphotoedit/generated`` were generated with the
built-in OpenAI ImageGen tool; this script deterministically creates the JPEG
fixtures, orientation variants, RGB calibration patches and their manifest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "tasks/v1/macos/assets/openphotoedit"
SOURCE_ROOT = ASSET_ROOT / "generated"
FIXTURE_ROOT = ASSET_ROOT / "PhotoFixtures"
OUTPUT_SIZE = (2512, 832)
MARKER_FRACTION = (0.645, 0.026, 0.712, 0.227)
GRID_COLORS = [
    ["#F00020", "#00D030", "#2030F0"],
    ["#F0D020", "#D020E0", "#00D0E0"],
    ["#F07818", "#6020D0", "#202020"],
]

GENERATED_SOURCES = {
    "anime_portrait.png": {
        "purpose": "Anime portrait / soft cream source",
        "prompt": "Use case: benchmark photo-editing source asset. Asset type: original wide landscape illustration for a desktop photo-editing task, later saved as a JPEG. Scene/backdrop: softly lit pale cream interior with a large window, subtle garden blur outside, uncluttered background. Subject: a thoughtful young anime-style woman with dark brown shoulder-length hair and a cream knit blouse, shown in a tasteful three-quarter portrait from shoulders up, hands outside frame, calm expression. Style/medium: polished hand-painted animation-film illustration with delicate linework and natural skin shading. Composition/framing: panoramic 3:1 landscape crop, portrait subject placed just left of center with ample light background and room across width, keep upper-right corner quiet and uncluttered for a separate RGB calibration patch. Lighting/mood: diffused morning light, soft elegant portrait. Palette: warm ivory, muted blue, natural dark brown. Constraints: distinct clean neutral source, no filters, no calibration patch, no text, no logo, no watermark, no extra people.",
    },
    "anime_floral.png": {
        "purpose": "Anime floral composite source",
        "prompt": "Use case: benchmark photo-editing source asset. Asset type: wide landscape source image for a real photo-editing task, to be saved as a JPEG and edited later. Scene/backdrop: an elegant field of delicate blue, white, and pale pink flowers with soft natural depth of field. Subject: a single young anime-style woman with dark hair in a simple cream coat, shown from chest up among the flowers, calm neutral expression, refined hand-painted animation-film illustration style. Composition/framing: extremely wide panoramic 3:1 landscape composition, subject centered slightly left, preserve rich scene detail across the full width, leave the upper-right corner calm and uncluttered for a small calibration patch that will be added separately. Lighting/mood: soft overcast daylight, gentle and readable. Palette: cool blue flowers balanced by cream and soft green. Constraints: original clean source image, no image-processing look or filter, no calibration blocks, no text, no logos, no watermark, no extra faces, natural consistent anatomy.",
    },
    "blue_floral.png": {
        "purpose": "Blue floral still-life source",
        "prompt": "Use case: benchmark photo-editing source asset. Asset type: wide landscape original photograph for a desktop photo-editing task. Scene/backdrop: a lush arrangement of blue delphinium, pale-blue hydrangea, white daisies, a few lavender blossoms, and deep green leaves on a light stone garden table. Subject: a refined blue floral arrangement, no people. Style/medium: natural editorial still-life photography with realistic petals and leaf texture. Composition/framing: very wide panoramic 3:1 landscape image, dense flowers across frame but maintain calm negative space at the upper-right corner for a small RGB calibration patch added separately; crisp central detail. Lighting/mood: soft morning daylight, cool and serene. Constraints: unedited neutral source photo, no filters, no text, no watermark, no labels, no logos.",
    },
    "fruit_pair.png": {
        "purpose": "Fruit product source",
        "prompt": "Use case: benchmark photo-editing source asset. Asset type: wide landscape original commercial product photograph for a desktop photo-editing task. Scene/backdrop: a carefully arranged pair of ripe fruit on a clean warm-neutral tabletop with a softly blurred orchard background. Subject: one glossy red apple and one deep purple plum, small green leaf, realistic natural fruit textures with tiny dew droplets, tasteful premium grocery campaign photography. Composition/framing: very wide panoramic 3:1 landscape, fruit pairing placed near center-left with ample environment visible across width, keep upper-right corner relatively uncluttered for a separate small calibration patch. Lighting/mood: soft studio daylight, realistic highlights, neutral unedited source. Constraints: no people, no labels, no text, no logo, no watermark, no filter effect.",
    },
}

FIXTURE_SOURCES = {
    "Anime-Portrait.jpg": ("anime_portrait.png", None),
    "Anime-Portrait-Mirror.jpg": ("anime_portrait.png", "mirror"),
    "Anime-Floral-Composite.jpg": ("anime_floral.png", None),
    "Blue-Floral.jpg": ("blue_floral.png", None),
    "Blue-Floral-Mirror.jpg": ("blue_floral.png", "mirror"),
    "Blue-Floral-Rotated.jpg": ("blue_floral.png", "rotate180"),
    "Fruit-Pair.jpg": ("fruit_pair.png", None),
    "Fruit-Pair-Rotated.jpg": ("fruit_pair.png", "rotate180"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fit_source(image: Image.Image) -> Image.Image:
    """Center-crop the generated 3:1 artwork to the published 2512x832 frame."""
    image = image.convert("RGB")
    target_ratio = OUTPUT_SIZE[0] / OUTPUT_SIZE[1]
    source_ratio = image.width / image.height
    if source_ratio < target_ratio:
        new_height = max(1, round(image.width / target_ratio))
        top = max(0, (image.height - new_height) // 2)
        image = image.crop((0, top, image.width, top + new_height))
    elif source_ratio > target_ratio:
        new_width = max(1, round(image.height * target_ratio))
        left = max(0, (image.width - new_width) // 2)
        image = image.crop((left, 0, left + new_width, image.height))
    return image.resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)


def add_calibration_grid(image: Image.Image) -> dict[str, Any]:
    width, height = image.size
    left, top, right, bottom = MARKER_FRACTION
    box = (
        round(width * left),
        round(height * top),
        round(width * right),
        round(height * bottom),
    )
    x0, y0, x1, y1 = box
    cell = 48
    gap = 4
    grid_width = cell * 3 + gap * 2
    grid_height = cell * 3 + gap * 2
    start_x = x0 + ((x1 - x0) - grid_width) // 2
    start_y = y0 + ((y1 - y0) - grid_height) // 2
    draw = ImageDraw.Draw(image)
    draw.rectangle(box, fill=(248, 248, 248))
    for row, colors in enumerate(GRID_COLORS):
        for column, color in enumerate(colors):
            x = start_x + column * (cell + gap)
            y = start_y + row * (cell + gap)
            rgb = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=rgb)
    return {"fraction": list(MARKER_FRACTION), "pixel_box": list(box), "grid": [3, 3], "colors": GRID_COLORS}


def main() -> int:
    missing = [name for name in GENERATED_SOURCES if not (SOURCE_ROOT / name).is_file()]
    if missing:
        raise SystemExit(f"generated source file(s) missing: {', '.join(missing)}")
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Any] = {}
    for filename, (source_name, transform) in FIXTURE_SOURCES.items():
        source_path = SOURCE_ROOT / source_name
        with Image.open(source_path) as source:
            image = fit_source(source)
        if transform == "mirror":
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        elif transform == "rotate180":
            image = image.transpose(Image.Transpose.ROTATE_180)
        marker = add_calibration_grid(image)
        output_path = FIXTURE_ROOT / filename
        image.save(output_path, format="JPEG", quality=96, subsampling=0, optimize=True)
        generated[filename] = {
            "source": source_name,
            "transform": transform or "identity",
            "sha256": sha256(output_path),
            "bytes": output_path.stat().st_size,
            "dimensions": list(OUTPUT_SIZE),
            "marker": marker,
        }

    sources = {
        name: {
            **info,
            "sha256": sha256(SOURCE_ROOT / name),
            "bytes": (SOURCE_ROOT / name).stat().st_size,
            "dimensions": list(Image.open(SOURCE_ROOT / name).size),
        }
        for name, info in GENERATED_SOURCES.items()
    }
    manifest = {
        "schema_version": 1,
        "fixture_version": "rgb-calibration-v3-author-rebuilt",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            "tool": "OpenAI built-in ImageGen",
            "raw_sources_directory": "tasks/v1/macos/assets/openphotoedit/generated",
            "rebuild_script": "scripts/rebuild_macos_openphotoedit_assets.py",
            "note": (
                "The original rgb-calibration-v2 source fixtures and references were absent. "
                "These replacement scenes preserve the requested anime portrait, floral still-life, "
                "and fruit product-editing semantics. Source images and all derived file hashes "
                "are recorded here."
            ),
        },
        "output_dimensions": list(OUTPUT_SIZE),
        "marker_box_fraction": list(MARKER_FRACTION),
        "marker_grid": [3, 3],
        "sources": sources,
        "fixtures": generated,
    }
    manifest_path = FIXTURE_ROOT / "CalibrationManifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"fixture_count": len(generated), "manifest": str(manifest_path), "sha256": sha256(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
