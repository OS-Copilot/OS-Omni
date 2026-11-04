"""Calibrated input photos for the four v1 Android OpenPhoto tasks.

The briefs of ``android.openphoto.{clown,coastal,cooking,guitar}_dual_calibrated_export_*``
name photos "with a three-color calibration area in the upper-right corner",
and the evaluators read median RGB values from fixed boxes in that corner of
the exported JPGs.  The emulator snapshot does not contain such photos (its
``portrait_17.jpg`` is a guitar, ``portrait_20.jpg`` a fish-hatchery class,
and no picture carries calibration stripes), so each task's initializer
installs the inputs itself, from the base photos bundled under
``assets/android/openphoto``:

* the base photo is the one the brief describes (see ``provenance.json``);
* three opaque patches in unclipped primaries -- RGB 190/40/40, 40/190/40 and
  40/40/190 -- are drawn over the evaluator's sample boxes, padded by
  ``PATCH_PADDING`` px so the app's local blurs (radius <= 9) and the export's
  4:2:0 chroma stay inside the patch for most box pixels;
* the result is encoded as JPEG quality 98, 4:4:4, and pushed to the file name
  the brief cites, then handed to the media scanner so the Photo Picker lists it.

The construction is deterministic: with the reference Pillow/libjpeg-turbo the
cooking and guitar fixtures are byte-identical to the inputs the benchmark-v2
reference exports were made from on a GPU emulator with the original APK.
The colours are unclipped on purpose: pure 255/0 stripes stay saturated
through most edits, so an unedited export would match an edited profile.
"""

from __future__ import annotations

import hashlib
import io
import json
import shlex
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw

#: Repository root (``evaluators/cua_review/platforms/android`` is four levels down).
REPO_ROOT = Path(__file__).resolve().parents[4]

#: Bundled base photos.
ASSET_DIR = REPO_ROOT / "assets" / "android" / "openphoto"

#: Calibration patch colours, keyed like the evaluators' ``sample_boxes``.
CALIBRATION_RGB: Mapping[str, tuple[int, int, int]] = {
    "red": (190, 40, 40),
    "green": (40, 190, 40),
    "blue": (40, 40, 190),
}

#: Pixels each patch extends beyond its sample box on every side.
PATCH_PADDING = 8

#: Fixture encoding (Pillow ``save`` keywords).
FIXTURE_JPEG_QUALITY = 98
FIXTURE_JPEG_SUBSAMPLING = 0

#: File the evaluators read to exclude exports that existed before the run.
BASELINE_FILENAME = "openphoto_calibrated_baseline.json"

DEFAULT_EXPORT_DIR = "/sdcard/Pictures/OpenPhotoEdit"

PORTRAIT_BOXES: Mapping[str, tuple[int, int, int, int]] = {
    "red": (826, 194, 846, 294),
    "green": (866, 194, 886, 294),
    "blue": (906, 194, 926, 294),
}


@dataclass(frozen=True)
class FixtureTarget:
    """One calibrated input photo a task installs."""

    profile_id: str
    device_path: str
    asset: str
    asset_sha256: str
    description: str


@dataclass(frozen=True)
class TaskFixture:
    """The calibrated inputs of one task."""

    task_id: str
    dimensions: tuple[int, int]
    sample_boxes: Mapping[str, tuple[int, int, int, int]]
    targets: tuple[FixtureTarget, ...]


TASK_FIXTURES: Mapping[str, TaskFixture] = {
    "clown": TaskFixture(
        task_id="android.openphoto.clown_dual_calibrated_export_20260804",
        dimensions=(960, 1280),
        sample_boxes={
            "red": (820, 160, 840, 260),
            "green": (860, 160, 880, 260),
            "blue": (900, 160, 920, 260),
        },
        targets=(
            FixtureTarget(
                "clown_side_portrait_17",
                "/sdcard/Pictures/portrait_17.jpg",
                "clown_side_face.jpg",
                "b6237067e7ca26eb618ca8f8d4cb7b09bb931ac8c2e5cdf2928146bbd9c5ad91",
                "clown-makeup side-face portrait",
            ),
            FixtureTarget(
                "clown_front_portrait_16",
                "/sdcard/Pictures/portrait_16.jpg",
                "clown_front_face.jpg",
                "c70ca0ab1b961103079b3ef5fcc520804d2ede1d0660a39d029d375ae0d9760a",
                "clown-makeup front-face portrait",
            ),
        ),
    ),
    "coastal": TaskFixture(
        task_id="android.openphoto.coastal_dual_calibrated_export_20260803",
        dimensions=(1280, 800),
        sample_boxes={
            "red": (906, 34, 926, 134),
            "green": (946, 34, 966, 134),
            "blue": (986, 34, 1006, 134),
        },
        targets=(
            FixtureTarget(
                "standing_coast_landscape_18",
                "/sdcard/Pictures/landscape_18.jpg",
                "coast_cliff_standing.jpg",
                "155842efc58fdec30599c2be0946ca466cfd3e5f44dc040d40a7bf00caf94922",
                "man standing at the cliff edge looking into the distance",
            ),
            FixtureTarget(
                "seated_coast_landscape_17",
                "/sdcard/Pictures/landscape_17.jpg",
                "coast_cliff_seated.jpg",
                "8ea2c8d59f727635d124a229399bda48a1d62611343bd0c137e4eeb5b61bd878",
                "the same man sitting at the cliff edge",
            ),
        ),
    ),
    "cooking": TaskFixture(
        task_id="android.openphoto.cooking_dual_calibrated_export_20260804",
        dimensions=(960, 1280),
        sample_boxes=PORTRAIT_BOXES,
        targets=(
            FixtureTarget(
                "indoor_cooking_portrait_20",
                "/sdcard/Pictures/portrait_20.jpg",
                "indoor_cooking.jpg",
                "64d99e6f89093caa99d16edf93bb965ebc0f23e8cdca9e7ad7a44e8df6de504d",
                "indoor cooking: several people preparing food around cookware",
            ),
            FixtureTarget(
                "outdoor_cooking_portrait_16",
                "/sdcard/Pictures/portrait_16.jpg",
                "outdoor_cooking.jpg",
                "1c73ef0e70326052e84f352ebe7af0f5e744fa05ffeb2139f750b49c34a9d60d",
                "outdoor cooking: several people around an outdoor cooking area",
            ),
        ),
    ),
    "guitar": TaskFixture(
        task_id="android.openphoto.guitar_dual_calibrated_export_20260804",
        dimensions=(960, 1280),
        sample_boxes=PORTRAIT_BOXES,
        targets=(
            FixtureTarget(
                "electric_guitar_portrait_21",
                "/sdcard/Pictures/portrait_21.jpg",
                "blue_electric_guitar.jpg",
                "3a3fda010a1c08174c0866c1135194eabcbdd38fc4278f451186af72f90043d1",
                "blue electric guitar close-up",
            ),
            FixtureTarget(
                "wood_guitar_portrait_17",
                "/sdcard/Pictures/portrait_17.jpg",
                "wood_guitar_red_fabric.jpg",
                "d1da7952c2d4a1afe2d2c69c63db9ec226ea673943ba5564c368967349bdd597",
                "wood guitar lying on red fabric",
            ),
        ),
    ),
}


class FixtureError(RuntimeError):
    """Raised when a calibrated input cannot be built or installed."""


# ------------------------------------------------------------ building
def asset_path(target: FixtureTarget, *, asset_dir: Path | None = None) -> Path:
    return Path(asset_dir or ASSET_DIR) / target.asset


def build_fixture_bytes(spec: TaskFixture, target: FixtureTarget, *, asset_dir: Path | None = None) -> bytes:
    """Return the calibrated JPEG for ``target``; raises ``FixtureError`` on a bad asset."""

    path = asset_path(target, asset_dir=asset_dir)
    if not path.is_file():
        raise FixtureError(f"bundled base photo is missing: {path.name}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != target.asset_sha256:
        raise FixtureError(f"bundled base photo {path.name} has sha256 {digest}, expected {target.asset_sha256}")
    with Image.open(io.BytesIO(raw)) as opened:
        photo = opened.convert("RGB")
    if photo.size != tuple(spec.dimensions):
        raise FixtureError(f"{path.name} is {photo.size[0]}x{photo.size[1]}, expected "
                           f"{spec.dimensions[0]}x{spec.dimensions[1]}")
    draw = ImageDraw.Draw(photo)
    for stripe, box in spec.sample_boxes.items():
        x1, y1, x2, y2 = box
        draw.rectangle(
            (x1 - PATCH_PADDING, y1 - PATCH_PADDING, x2 + PATCH_PADDING, y2 + PATCH_PADDING),
            fill=CALIBRATION_RGB[stripe],
        )
    buffer = io.BytesIO()
    photo.save(buffer, format="JPEG", quality=FIXTURE_JPEG_QUALITY, subsampling=FIXTURE_JPEG_SUBSAMPLING)
    return buffer.getvalue()


def decode_fixture(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as opened:
        return opened.convert("RGB")


# ------------------------------------------------------- source binding
#: Edge of one luminance cell of the source-binding thumbnail, in pixels.
SOURCE_THUMBNAIL_CELL = 40

#: Default minimum correlation between an export and the photo it was made from.
DEFAULT_MIN_SOURCE_CORRELATION = 0.9


def source_thumbnail(image: Image.Image, sample_boxes: Mapping[str, Any]) -> list[float]:
    """Coarse luminance grid of ``image`` without the cells that hold the calibration area.

    The calibration patches are identical in both photos of a task, so they
    are left out; what remains identifies the photo and survives the tonal
    edits (exposure, contrast, HSL, filters) the recipes apply.
    """

    width, height = image.size
    columns = max(1, width // SOURCE_THUMBNAIL_CELL)
    rows = max(1, height // SOURCE_THUMBNAIL_CELL)
    grid = list(image.convert("L").resize((columns, rows), Image.BOX).tobytes())
    x1 = min(int(box[0]) for box in sample_boxes.values()) - PATCH_PADDING
    y1 = min(int(box[1]) for box in sample_boxes.values()) - PATCH_PADDING
    x2 = max(int(box[2]) for box in sample_boxes.values()) + PATCH_PADDING
    y2 = max(int(box[3]) for box in sample_boxes.values()) + PATCH_PADDING
    cell_w, cell_h = width / columns, height / rows
    values: list[float] = []
    for row in range(rows):
        for column in range(columns):
            overlaps = not (column * cell_w >= x2 or (column + 1) * cell_w <= x1
                            or row * cell_h >= y2 or (row + 1) * cell_h <= y1)
            if not overlaps:
                values.append(float(grid[row * columns + column]))
    return values


def normalized_correlation(first: list[float], second: list[float]) -> float:
    if len(first) != len(second) or not first:
        return 0.0
    mean_a = sum(first) / len(first)
    mean_b = sum(second) / len(second)
    da = [value - mean_a for value in first]
    db = [value - mean_b for value in second]
    denominator = (sum(v * v for v in da) * sum(v * v for v in db)) ** 0.5
    return sum(a * b for a, b in zip(da, db)) / denominator if denominator > 0 else 0.0


_SOURCE_THUMBNAILS: dict[str, dict[str, list[float]]] = {}


def source_thumbnails(task_key: str) -> dict[str, list[float]]:
    """Thumbnails of the task's installed inputs, keyed by profile id (cached)."""

    if task_key not in _SOURCE_THUMBNAILS:
        spec = TASK_FIXTURES[task_key]
        _SOURCE_THUMBNAILS[task_key] = {
            target.profile_id: source_thumbnail(decode_fixture(build_fixture_bytes(spec, target)), spec.sample_boxes)
            for target in spec.targets
        }
    return _SOURCE_THUMBNAILS[task_key]


def source_correlations(image: Image.Image, task_key: str) -> dict[str, float]:
    """Correlation of an export with each of the task's input photos, keyed by profile id."""

    spec = TASK_FIXTURES[task_key]
    if image.size != tuple(spec.dimensions):
        return {target.profile_id: 0.0 for target in spec.targets}
    exported = source_thumbnail(image, spec.sample_boxes)
    return {
        profile_id: round(normalized_correlation(exported, reference), 4)
        for profile_id, reference in source_thumbnails(task_key).items()
    }


# ----------------------------------------------------------- installing
def _q(value: str) -> str:
    return shlex.quote(str(value))


def _remote_size(controller: Any, remote_path: str) -> int | None:
    output = str(controller.execute_adb(["shell", f"wc -c < {_q(remote_path)} 2>/dev/null"]) or "").strip()
    try:
        return int(output.split()[0])
    except (IndexError, ValueError):
        return None


def _remote_sha256(controller: Any, remote_path: str) -> str | None:
    output = str(controller.execute_adb(["shell", f"sha256sum {_q(remote_path)} 2>/dev/null"]) or "").strip()
    token = output.split()[0] if output.split() else ""
    return token.lower() if len(token) == 64 and all(c in "0123456789abcdefABCDEF" for c in token) else None


def _media_store_sizes(controller: Any, display_name: str) -> list[int] | None:
    """Sizes MediaStore records for ``display_name``; ``None`` if it cannot be queried."""

    where = f"_display_name='{display_name}'"
    command = (
        "content query --uri content://media/external/images/media "
        f"--projection _display_name:_size --where {_q(where)}"
    )
    output = str(controller.execute_adb(["shell", command]) or "")
    if "No result found" in output:
        return []
    sizes: list[int] = []
    seen_row = False
    for line in output.splitlines():
        if not line.strip().startswith("Row:"):
            continue
        seen_row = True
        for field in line.split(","):
            key, _, value = field.strip().partition("=")
            if key.strip().endswith("_size"):
                try:
                    sizes.append(int(value.strip()))
                except ValueError:
                    pass
    return sizes if seen_row else None


def _scan(controller: Any, remote_path: str) -> None:
    controller.execute_adb([
        "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", f"file://{remote_path}",
    ])


def _retire_existing(controller: Any, remote_path: str, *, timeout_seconds: float, poll_seconds: float) -> bool | None:
    """Remove the snapshot's file and wait for MediaStore to drop its row (best effort).

    Pushing over an indexed file only updates its MediaStore row, and the
    Photo Picker may keep the old row's thumbnail -- here a different picture.
    Retiring the row first makes the calibrated input a new picker item.
    Returns whether the row is gone, or ``None`` if MediaStore cannot be queried.
    """

    name = remote_path.rsplit("/", 1)[-1]
    controller.execute_adb(["shell", f"rm -f {_q(remote_path)}"])
    _scan(controller, remote_path)
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        sizes = _media_store_sizes(controller, name)
        if sizes is None or not sizes:
            return None if sizes is None else True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_seconds)


def list_exports(controller: Any, export_dir: str = DEFAULT_EXPORT_DIR) -> list[str]:
    command = (
        f"if [ -d {_q(export_dir)} ]; then for f in {_q(export_dir)}/OpenPhotoEdit_*.jpg; do "
        '[ -f "$f" ] && echo "$f"; done; fi'
    )
    output = str(controller.execute_adb(["shell", command]) or "")
    prefix = export_dir.rstrip("/") + "/"
    return sorted({line.strip() for line in output.splitlines() if line.strip().startswith(prefix)})


def install_task_fixtures(
    controller: Any,
    task_key: str,
    *,
    run_dir: str | Path | None = None,
    export_dir: str = DEFAULT_EXPORT_DIR,
    asset_dir: Path | None = None,
    media_scan_timeout_seconds: float = 20.0,
    retire_timeout_seconds: float = 10.0,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    """Install the calibrated inputs of ``task_key`` and record the export baseline.

    The snapshot's file under the name the brief cites is removed and its
    MediaStore row retired (best effort), then every fixture is pushed there,
    verified by size (and SHA-256 where the device has ``sha256sum``) and
    handed to the media scanner; MediaStore is then polled until it reports
    the new sizes.
    Exports already present are written to ``BASELINE_FILENAME`` in
    ``run_dir`` so the evaluator only counts exports made during the run.
    Raises ``FixtureError`` when an input cannot be established.
    """

    spec = TASK_FIXTURES[task_key]
    installed: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="openphoto-fixture-") as tmpdir:
        for target in spec.targets:
            data = build_fixture_bytes(spec, target, asset_dir=asset_dir)
            digest = hashlib.sha256(data).hexdigest()
            local = Path(tmpdir) / Path(target.device_path).name
            local.write_bytes(data)
            remote_dir = target.device_path.rsplit("/", 1)[0]
            controller.execute_adb(["shell", f"mkdir -p {_q(remote_dir)}"])
            retired = _retire_existing(controller, target.device_path, timeout_seconds=retire_timeout_seconds,
                                       poll_seconds=poll_seconds)
            push_output = str(controller.execute_adb(["push", str(local), target.device_path]) or "")
            size = _remote_size(controller, target.device_path)
            if size != len(data):
                raise FixtureError(
                    f"pushing {target.device_path} failed: device size {size}, expected {len(data)} "
                    f"({push_output.strip()[-200:]})"
                )
            remote_digest = _remote_sha256(controller, target.device_path)
            if remote_digest is not None and remote_digest != digest:
                raise FixtureError(f"{target.device_path} on the device has sha256 {remote_digest}, expected {digest}")
            _scan(controller, target.device_path)
            installed.append({
                "profile_id": target.profile_id,
                "device_path": target.device_path,
                "base_photo": f"assets/android/openphoto/{target.asset}",
                "base_photo_sha256": target.asset_sha256,
                "description": target.description,
                "fixture_sha256": digest,
                "fixture_size": len(data),
                "device_sha256_verified": remote_digest is not None,
                "previous_media_row_retired": retired,
            })

    pending = {entry["device_path"]: entry for entry in installed}
    deadline = time.monotonic() + max(0.0, media_scan_timeout_seconds)
    queryable = True
    while pending and queryable:
        for path, entry in list(pending.items()):
            sizes = _media_store_sizes(controller, Path(path).name)
            if sizes is None:
                queryable = False
                break
            if entry["fixture_size"] in sizes:
                entry["media_store_indexed"] = True
                pending.pop(path)
        if not pending or not queryable or time.monotonic() >= deadline:
            break
        time.sleep(poll_seconds)
    if pending and queryable:
        names = ", ".join(sorted(pending))
        raise FixtureError(f"MediaStore did not index the calibrated inputs within "
                           f"{media_scan_timeout_seconds:.0f}s: {names}")
    for entry in pending.values():
        entry["media_store_indexed"] = None  # content provider not queryable from this shell

    existing = list_exports(controller, export_dir)
    baseline = {
        "task_id": spec.task_id,
        "export_dir": export_dir,
        "paths": existing,
        "entries": existing,
        "calibration_rgb": {key: list(value) for key, value in CALIBRATION_RGB.items()},
        "patch_padding": PATCH_PADDING,
        "fixtures": installed,
        "created_at": time.time(),
    }
    if run_dir:
        path = Path(run_dir) / BASELINE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8")
        baseline["baseline_file"] = str(path)
    return baseline


__all__ = [
    "ASSET_DIR",
    "BASELINE_FILENAME",
    "CALIBRATION_RGB",
    "FixtureError",
    "FixtureTarget",
    "PATCH_PADDING",
    "TASK_FIXTURES",
    "TaskFixture",
    "DEFAULT_MIN_SOURCE_CORRELATION",
    "build_fixture_bytes",
    "decode_fixture",
    "install_task_fixtures",
    "list_exports",
    "source_correlations",
    "source_thumbnail",
]
