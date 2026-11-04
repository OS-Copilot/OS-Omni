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


# ---------------------------------------------------------------------------
# Live guest path: the guest evidence script runs (here as a local subprocess)
# against a PhotoFixtures directory, exactly as it does inside the macOS guest.
# The reference entries then carry ``expected_sha256`` (the reference PNG's own
# integrity digest); that digest must not be demanded of the export.
# ---------------------------------------------------------------------------
import shutil
import struct
import subprocess
import sys
import zlib

from evaluators.cua_review.evaluators.macos.openphotoedit_rgb import (
    OpenPhotoEditRgbEvaluator,
    decode_png,
)


class _LocalGuestController:
    """Runs the evaluator's guest script with this interpreter, read-only."""

    def run_python_script(self, code: str, timeout: int = 90) -> dict:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=max(timeout, 300),
        )
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def _encode_png(width: int, height: int, rgb: bytes, *, level: int = 1) -> bytes:
    """Minimal RGB8 PNG writer (filter 0) -- different bytes from the fixtures' encoder."""
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, level))
        + chunk(b"IEND", b"")
    )


def _synthetic_rgb(width: int, height: int, seed: int) -> bytes:
    # Deterministic noise (LCG), kept in 8..247 so +/- shifts never clip, and
    # incompressible enough to stay above the evaluator's 4096-byte minimum.
    state = seed * 2654435761 & 0xFFFFFFFF
    out = bytearray(width * height * 3)
    for index in range(len(out)):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        out[index] = 8 + (state >> 16) % 240
    return bytes(out)


def _shift(rgb: bytes, delta: int) -> bytes:
    return bytes(max(0, min(255, value + delta)) for value in rgb)


def _live_params(fixtures: Path, references: dict[str, tuple[str, bytes]], width: int, height: int) -> dict:
    return {
        "profile_id": "openphotoedit-export-only-v1",
        "fixture_dir": str(fixtures),
        "exports_dirs": [str(fixtures.parent / "Desktop")],
        "expected_width": width,
        "expected_height": height,
        "expected_filenames": list(references),
        "expected_sha256": {},
        "reference_images": {
            export: {"name": name, "expected_sha256": hashlib.sha256(raw).hexdigest()}
            for export, (name, raw) in references.items()
        },
        "marker_mae_tolerance": 3.0,
        "marker_peak_tolerance": 12.0,
        "image_mae_tolerance": 3.0,
        "median_tolerance": 3.0,
    }


def _run_live(tmp_path: Path, exports: dict[str, bytes], references: dict[str, tuple[str, bytes]],
              width: int, height: int, *, tamper_reference: str | None = None):
    fixtures = tmp_path / "PhotoFixtures"
    fixtures.mkdir()
    params = _live_params(fixtures, references, width, height)
    for _export, (name, raw) in references.items():
        data = raw
        if tamper_reference == name:
            data = _encode_png(width, height, _shift(decode_png(raw)["rgb"], 1))
        (fixtures / name).write_bytes(data)
    for name, raw in exports.items():
        (fixtures / name).write_bytes(raw)
    result = OpenPhotoEditRgbEvaluator().evaluate(
        {"params": params, "controller": _LocalGuestController()}
    )
    return result


SYN_W, SYN_H = 120, 64


@pytest.fixture()
def synthetic_refs() -> dict[str, tuple[str, bytes]]:
    return {
        "first.png": ("First.reference.png", _encode_png(SYN_W, SYN_H, _synthetic_rgb(SYN_W, SYN_H, 1), level=9)),
        "second.png": ("Second.reference.png", _encode_png(SYN_W, SYN_H, _synthetic_rgb(SYN_W, SYN_H, 2), level=9)),
    }


def test_live_reencoded_pixel_identical_exports_pass_on_tolerance(tmp_path, synthetic_refs) -> None:
    exports = {
        export: _encode_png(SYN_W, SYN_H, decode_png(raw)["rgb"], level=1)
        for export, (_name, raw) in synthetic_refs.items()
    }
    assert all(exports[e] != synthetic_refs[e][1] for e in exports)  # bytes differ
    result = _run_live(tmp_path, exports, synthetic_refs, SYN_W, SYN_H)
    assert result.status == EvalStatus.PASS, result.message
    assert result.metadata["validation_mode"] == "reference_tolerance"
    for check in result.metadata["checks"]:
        if "filename" in check:
            assert "exact_sha256" not in check["metrics"]
            assert check["metrics"]["reference"]["sha256_matched"] is True


def test_live_small_decoder_noise_within_tolerance_passes(tmp_path, synthetic_refs) -> None:
    exports = {
        export: _encode_png(SYN_W, SYN_H, _shift(decode_png(raw)["rgb"], 2))
        for export, (_name, raw) in synthetic_refs.items()
    }
    result = _run_live(tmp_path, exports, synthetic_refs, SYN_W, SYN_H)
    assert result.status == EvalStatus.PASS, result.message


@pytest.mark.parametrize("case", ["visible_edit", "swapped_sources", "missing_export", "tampered_reference"])
def test_live_negative_cases_still_fail(tmp_path, synthetic_refs, case: str) -> None:
    pixels = {export: decode_png(raw)["rgb"] for export, (_name, raw) in synthetic_refs.items()}
    tamper = None
    if case == "visible_edit":
        exports = {e: _encode_png(SYN_W, SYN_H, _shift(rgb, 25)) for e, rgb in pixels.items()}
    elif case == "swapped_sources":
        exports = {
            "first.png": _encode_png(SYN_W, SYN_H, pixels["second.png"]),
            "second.png": _encode_png(SYN_W, SYN_H, pixels["first.png"]),
        }
    elif case == "missing_export":
        exports = {"first.png": _encode_png(SYN_W, SYN_H, pixels["first.png"])}
    else:
        exports = {e: _encode_png(SYN_W, SYN_H, rgb) for e, rgb in pixels.items()}
        tamper = "First.reference.png"
    result = _run_live(tmp_path, exports, synthetic_refs, SYN_W, SYN_H, tamper_reference=tamper)
    assert result.status == EvalStatus.FAIL, result.message


def test_live_explicit_export_digest_keeps_exact_mode(tmp_path, synthetic_refs) -> None:
    exports = {
        export: _encode_png(SYN_W, SYN_H, decode_png(raw)["rgb"], level=1)
        for export, (_name, raw) in synthetic_refs.items()
    }
    fixtures = tmp_path / "PhotoFixtures"
    fixtures.mkdir()
    params = _live_params(fixtures, synthetic_refs, SYN_W, SYN_H)
    # A profile that declares the export's own digest is still judged byte-exactly.
    params["expected_sha256"] = {"first.png": hashlib.sha256(b"other bytes").hexdigest()}
    for _export, (name, raw) in synthetic_refs.items():
        (fixtures / name).write_bytes(raw)
    for name, raw in exports.items():
        (fixtures / name).write_bytes(raw)
    result = OpenPhotoEditRgbEvaluator().evaluate(
        {"params": params, "controller": _LocalGuestController()}
    )
    assert result.status == EvalStatus.FAIL
    assert "does not match the confirmed artifact" in result.message


def test_live_real_fixture_reencoded_exports_pass_with_task_params(tmp_path) -> None:
    """The shipped v1 fruit task: a pixel-faithful re-encode of each source now passes."""
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    params = dict(task["evaluation"]["params"])
    fixtures = tmp_path / "PhotoFixtures"
    fixtures.mkdir()
    for path in FIXTURES.iterdir():
        if path.name.endswith(".reference.png"):
            shutil.copy2(path, fixtures / path.name)
    exports = {}
    for export, entry in params["reference_images"].items():
        decoded = decode_png((FIXTURES / entry["name"]).read_bytes())
        exports[export] = _encode_png(decoded["width"], decoded["height"], decoded["rgb"], level=1)
        (fixtures / export).write_bytes(exports[export])
    params["fixture_dir"] = str(fixtures)
    params["exports_dirs"] = [str(tmp_path / "Desktop")]
    result = OpenPhotoEditFruitProductFilmEvaluator().evaluate(
        {"params": params, "controller": _LocalGuestController()}
    )
    assert result.status == EvalStatus.PASS, result.message
    assert result.metadata["validation_mode"] == "reference_tolerance"
