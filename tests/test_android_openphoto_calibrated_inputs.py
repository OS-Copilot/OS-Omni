"""Scan row AND-051: the v1 Android OpenPhoto calibrated-export tasks were impossible.

Their initializers only launched the app, the snapshot photos carry no
calibration area (and two of the cited file names show other subjects), and
the expected stripe medians came from a lost snapshot.  The initializers now
install calibrated inputs built from bundled base photos, and the expected
medians are what the app's export path produces from those inputs:

* cooking/guitar: the benchmark-v2 exports of the original APK on a GPU
  emulator, made from inputs these initializers reproduce exactly;
* clown/coastal: ``tools/openphoto_android_edit_model.py``, a port of
  ``BitmapEditor.applyParams`` that these tests check against those device
  exports.
"""

from __future__ import annotations

import hashlib
import io
import shlex
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import yaml
from PIL import Image

from core.evaluation import EvalStatus
from core.init import InitStatus, load_initializer
from evaluators.cua_review.platforms.android import openphoto_calibration as calibration
from tools import openphoto_android_edit_model as model

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID_TASKS = REPO_ROOT / "tasks" / "v1" / "android"
REFERENCES = REPO_ROOT / "local_eval" / "benchmark-v2" / "references"
APP = "com.killt.openphotoedit"

TASK_FILES = {
    "clown": "openphoto_clown_dual_calibrated_export_20260804.yaml",
    "coastal": "openphoto_coastal_dual_calibrated_export_20260803.yaml",
    "cooking": "openphoto_cooking_dual_calibrated_export_20260804.yaml",
    "guitar": "openphoto_guitar_dual_calibrated_export_20260804.yaml",
}
DEVICE_PROFILES = {
    "indoor_cooking_portrait_20", "outdoor_cooking_portrait_16",
    "electric_guitar_portrait_21", "wood_guitar_portrait_17",
}

#: Per-channel [min, max] stripe medians (before the export JPEG) over every
#: slider value that displays the requested label: interval corners plus 512
#: random points, seed 1 -- ``python -m tools.openphoto_android_edit_model``.
LABEL_RANGES: dict[str, dict[str, list[list[int]]]] = {
    "clown_side_portrait_17": {"red": [[215, 220], [16, 21], [19, 24]], "green": [[42, 45], [214, 218], [41, 44]],
                               "blue": [[9, 14], [18, 24], [214, 218]]},
    "clown_front_portrait_16": {"red": [[212, 217], [0, 0], [2, 2]], "green": [[19, 21], [211, 214], [18, 20]],
                                "blue": [[24, 26], [25, 27], [215, 219]]},
    "standing_coast_landscape_18": {"red": [[185, 188], [30, 32], [33, 35]], "green": [[34, 36], [186, 188], [37, 40]],
                                    "blue": [[5, 9], [7, 10], [176, 180]]},
    "seated_coast_landscape_17": {"red": [[220, 225], [45, 48], [45, 48]], "green": [[47, 50], [219, 224], [42, 45]],
                                  "blue": [[26, 31], [24, 29], [218, 222]]},
    "indoor_cooking_portrait_20": {"red": [[228, 233], [48, 51], [46, 50]], "green": [[46, 50], [223, 228], [40, 44]],
                                   "blue": [[52, 55], [50, 53], [225, 231]]},
    "outdoor_cooking_portrait_16": {"red": [[214, 219], [44, 47], [44, 47]], "green": [[28, 34], [220, 226], [26, 32]],
                                    "blue": [[46, 49], [45, 48], [212, 217]]},
    "electric_guitar_portrait_21": {"red": [[224, 230], [37, 40], [38, 41]], "green": [[31, 35], [221, 226], [31, 35]],
                                    "blue": [[0, 5], [7, 13], [224, 231]]},
    "wood_guitar_portrait_17": {"red": [[220, 225], [45, 50], [38, 41]], "green": [[48, 52], [210, 214], [35, 39]],
                                "blue": [[48, 52], [41, 44], [201, 205]]},
}

#: Export JPEG round trip (measured <= 1) plus model-vs-device error (<= 2,
#: see ``test_model_reproduces_the_device_reference_exports``).
MODEL_ALLOWANCE = 3


def _task(key: str) -> dict[str, Any]:
    return yaml.safe_load((ANDROID_TASKS / TASK_FILES[key]).read_text(encoding="utf-8"))


def _profiles(key: str) -> dict[str, dict[str, Any]]:
    return {p["profile_id"]: p for p in _task(key)["evaluation"]["params"]["profiles"]}


def _all_targets():
    return [(key, target) for key, spec in calibration.TASK_FIXTURES.items() for target in spec.targets]


def _fixture_array(key: str, target) -> np.ndarray:
    spec = calibration.TASK_FIXTURES[key]
    return np.asarray(calibration.decode_fixture(calibration.build_fixture_bytes(spec, target)))


def _max_delta(actual: dict[str, list[int]], expected: dict[str, list[int]]) -> int:
    return max(abs(int(actual[s][c]) - int(expected[s][c])) for s in expected for c in range(3))


def _crop_medians(key: str, fixture: np.ndarray, params: dict[str, float]) -> dict[str, list[int]]:
    """Stripe medians of the modelled export (before JPEG) from a crop around the boxes."""

    boxes = calibration.TASK_FIXTURES[key].sample_boxes
    left = min(b[0] for b in boxes.values()) - 24
    top = min(b[1] for b in boxes.values()) - 24
    right = max(b[2] for b in boxes.values()) + 24
    bottom = max(b[3] for b in boxes.values()) + 24
    height, width = fixture.shape[:2]
    lip = model._detect_lip_region(fixture) if params.get("lipColor") else None
    result = model.to_8bit(model.apply_params(fixture[top:bottom, left:right], params, origin=(left, top),
                                              full_size=(width, height), lip_region=lip))
    local = {s: (b[0] - left, b[1] - top, b[2] - left, b[3] - top) for s, b in boxes.items()}
    return model.stripe_medians(result, local)


# ------------------------------------------------------------- fixtures
@pytest.mark.parametrize(("key", "target"), _all_targets(), ids=lambda v: getattr(v, "profile_id", v))
def test_bundled_base_photos_are_the_recorded_files(key, target) -> None:
    path = calibration.asset_path(target)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == target.asset_sha256
    with Image.open(path) as image:
        assert image.size == tuple(calibration.TASK_FIXTURES[key].dimensions)


@pytest.mark.parametrize("key", sorted(TASK_FILES))
def test_task_yaml_is_bound_to_the_installed_inputs(key) -> None:
    task = _task(key)
    spec = calibration.TASK_FIXTURES[key]
    params = task["evaluation"]["params"]
    assert task["task_id"] == spec.task_id
    assert task["init"]["params"]["required_source_files"] == [t.device_path for t in spec.targets]
    module_name, class_name = task["init"]["initializer_id"].split(":")
    initializer = getattr(__import__(module_name, fromlist=[class_name]), class_name)
    assert initializer.FIXTURE_KEY == key
    assert params["source_binding"] == {"fixture_key": key, "min_correlation": 0.9}
    assert params["channel_tolerance"] == 12
    assert params["expected_dimensions"] == list(spec.dimensions)
    assert {s: tuple(b) for s, b in params["sample_boxes"].items()} == dict(spec.sample_boxes)
    assert [(p["profile_id"], p["source_file"]) for p in params["profiles"]] == [
        (t.profile_id, t.device_path.rsplit("/", 1)[1]) for t in spec.targets
    ]
    for stripe, rgb in calibration.CALIBRATION_RGB.items():
        assert 30 <= min(rgb) and max(rgb) <= 200, "patches must stay unclipped through the recipes"


@pytest.mark.parametrize("profile_id", sorted(DEVICE_PROFILES))
def test_cooking_and_guitar_inputs_reproduce_the_device_reference_inputs(profile_id) -> None:
    reference = REFERENCES / profile_id / "input.jpg"
    if not reference.is_file():
        pytest.skip("benchmark-v2 reference input not present")
    key, target = next((k, t) for k, t in _all_targets() if t.profile_id == profile_id)
    with Image.open(reference) as image:
        expected = np.asarray(image.convert("RGB"))
    assert np.array_equal(_fixture_array(key, target), expected)


# ---------------------------------------------------------------- model
@pytest.mark.parametrize("profile_id", sorted(DEVICE_PROFILES))
def test_model_reproduces_the_device_reference_exports(profile_id) -> None:
    import json

    folder = REFERENCES / profile_id
    if not (folder / "result.json").is_file():
        pytest.skip("benchmark-v2 reference exports not present")
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    assert model.recipe_params(tuple(step) for step in result["recipe"]) == model.recipe_params(
        model.TASK_RECIPES[profile_id]
    )
    key, target = next((k, t) for k, t in _all_targets() if t.profile_id == profile_id)
    fixture = _fixture_array(key, target)
    boxes = calibration.TASK_FIXTURES[key].sample_boxes
    # The untouched export is reproduced exactly, JPEG round trip included.
    assert model.model_export_medians(fixture, {}, boxes) == result["unedited_median_rgb"]
    # The device export lies inside the modelled range of label-preserving slider values.
    ranges = LABEL_RANGES[profile_id]
    for stripe, rgb in result["expected_median_rgb"].items():
        for channel, value in enumerate(rgb):
            low, high = ranges[stripe][channel]
            assert low - 1 <= value <= high + 1, (stripe, channel, value, ranges[stripe][channel])
    # The repeat export was identical, and a whole-image comparison stays close.
    assert result["repeat_median_rgb"] == result["expected_median_rgb"]
    params = model.recipe_params(model.TASK_RECIPES[profile_id])
    modelled = model.export_jpeg_roundtrip(model.to_8bit(model.apply_params(fixture, params)))
    with Image.open(folder / "correct.jpg") as image:
        device = np.asarray(image.convert("RGB")).astype(int)
    assert np.abs(modelled.astype(int) - device).mean() < 3.0


@pytest.mark.parametrize(("key", "target"), _all_targets(), ids=lambda v: getattr(v, "profile_id", v))
def test_label_ranges_are_the_models(key, target) -> None:
    params = model.recipe_params(model.TASK_RECIPES[target.profile_id])
    fixture = _fixture_array(key, target)
    sliders = [k for k, v in params.items() if k != "filterId" and v]
    corners = [params]
    for pick in (0, 1):
        trial = dict(params)
        trial.update({k: model.displayed_value_interval(params[k])[pick] for k in sliders})
        corners.append(trial)
    ranges = LABEL_RANGES[target.profile_id]
    for trial in corners:
        for stripe, rgb in _crop_medians(key, fixture, trial).items():
            for channel, value in enumerate(rgb):
                low, high = ranges[stripe][channel]
                assert low - 1 <= value <= high + 1, (stripe, channel, value)


@pytest.mark.parametrize(("key", "target"), _all_targets(), ids=lambda v: getattr(v, "profile_id", v))
def test_expected_medians_accept_every_label_preserving_setting(key, target) -> None:
    profile = _profiles(key)[target.profile_id]
    expected = profile["expected_median_rgb"]
    tolerance = _task(key)["evaluation"]["params"]["channel_tolerance"]
    ranges = LABEL_RANGES[target.profile_id]
    for stripe in ("red", "green", "blue"):
        for channel in range(3):
            low, high = ranges[stripe][channel]
            worst = max(abs(low - expected[stripe][channel]), abs(high - expected[stripe][channel]))
            assert worst + MODEL_ALLOWANCE <= tolerance, (stripe, channel, worst)
    if target.profile_id in DEVICE_PROFILES and (REFERENCES / target.profile_id / "result.json").is_file():
        import json

        device = json.loads((REFERENCES / target.profile_id / "result.json").read_text(encoding="utf-8"))
        assert expected == device["expected_median_rgb"]


@pytest.mark.parametrize(("key", "target"), _all_targets(), ids=lambda v: getattr(v, "profile_id", v))
def test_unedited_wrong_exposure_and_other_recipe_exports_miss_the_profile(key, target) -> None:
    profiles = _profiles(key)
    expected = profiles[target.profile_id]["expected_median_rgb"]
    tolerance = _task(key)["evaluation"]["params"]["channel_tolerance"]
    fixture = _fixture_array(key, target)
    params = model.recipe_params(model.TASK_RECIPES[target.profile_id])
    other = next(p for p in profiles if p != target.profile_id)
    negatives = {
        "unedited": {},
        "wrong_exposure": dict(params, exposure=35.0),
        "other_profile_recipe": model.recipe_params(model.TASK_RECIPES[other]),
    }
    for name, trial in negatives.items():
        delta = _max_delta(_crop_medians(key, fixture, trial), expected)
        # The two cooking recipes are close (nominal miss 15), so the other
        # recipe only has to miss nominally; the rest must miss with margin.
        margin = 0 if name == "other_profile_recipe" else MODEL_ALLOWANCE
        assert delta - margin > tolerance, (name, delta)


#: Recipe operations no benchmark-v2 device export exercises.
_DEVICE_UNVALIDATED = {"smoothSkin", "whiten", "rosy", "lipColor", "coolTone"}


@pytest.mark.parametrize(("key", "target"), [(k, t) for k, t in _all_targets() if k in ("clown", "coastal")],
                         ids=lambda v: getattr(v, "profile_id", v))
def test_modelled_medians_rest_on_device_validated_operations(key, target) -> None:
    """Portrait tools and Cool Tone are only modelled; they barely touch the stripes."""

    fixture = _fixture_array(key, target)
    params = model.recipe_params(model.TASK_RECIPES[target.profile_id])
    validated = {k: v for k, v in params.items() if k not in _DEVICE_UNVALIDATED}
    assert set(params) - set(validated), "recipe uses no unvalidated operation"
    assert _max_delta(_crop_medians(key, fixture, params), _crop_medians(key, fixture, validated)) <= 1


# ------------------------------------------------------------ evaluator
class _ExportController:
    """adb stand-in that serves local JPGs as OpenPhotoEdit exports."""

    def __init__(self, exports: dict[str, Path]) -> None:
        self.exports = exports

    def execute_adb(self, args: list[str]) -> str:
        if args[:1] == ["pull"]:
            shutil.copyfile(self.exports[args[1]], args[2])
            return "1 file pulled"
        if args[:1] == ["shell"] and "OpenPhotoEdit_*.jpg" in args[-1]:
            return "\n".join(f"{remote}\t{path.stat().st_size}\t{1000 + index}"
                             for index, (remote, path) in enumerate(self.exports.items()))
        return ""


def _final_editor() -> SimpleNamespace:
    nodes = [{"text": label, "package": APP} for label in ("Export", "Edit", "Filters", "Landscape", "HSL")]
    return SimpleNamespace(ui_nodes=nodes, foreground_app=APP, foreground_bundle_id=APP, foreground_window="")


def _evaluate(key: str, exports: dict[str, Path]):
    task = _task(key)
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":")
    evaluator = getattr(__import__(module_name, fromlist=[class_name]), class_name)()
    return evaluator.evaluate({
        "controller": _ExportController(exports),
        "params": task["evaluation"]["params"],
        "final_observation": _final_editor(),
    })


def _write_jpeg(path: Path, pixels: np.ndarray) -> Path:
    Image.fromarray(pixels, "RGB").save(path, format="JPEG", quality=model.EXPORT_JPEG_QUALITY,
                                        subsampling=model.EXPORT_JPEG_SUBSAMPLING)
    return path


@pytest.mark.parametrize("key", sorted(TASK_FILES))
def test_evaluator_passes_modelled_exports_and_rejects_the_wrong_photo(tmp_path, key) -> None:
    spec = calibration.TASK_FIXTURES[key]
    first, second = spec.targets
    fixtures = {t.profile_id: _fixture_array(key, t) for t in spec.targets}

    def export(photo, recipe_of, name):
        params = model.recipe_params(model.TASK_RECIPES[recipe_of])
        pixels = model.to_8bit(model.apply_params(fixtures[photo], params))
        return _write_jpeg(tmp_path / name, pixels)

    right = {
        "/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_1.jpg": export(first.profile_id, first.profile_id, "a.jpg"),
        "/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_2.jpg": export(second.profile_id, second.profile_id, "b.jpg"),
    }
    passed = _evaluate(key, right)
    assert passed.status == EvalStatus.PASS, passed.metadata["failures"]
    for evidence in passed.metadata["file_evidence"]:
        assert max(evidence["source_correlations"].values()) >= 0.95

    swapped = {
        "/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_1.jpg": export(second.profile_id, first.profile_id, "c.jpg"),
        "/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_2.jpg": export(first.profile_id, second.profile_id, "d.jpg"),
    }
    failed = _evaluate(key, swapped)
    assert failed.status == EvalStatus.FAIL
    assert "all_expected_profiles_matched" in failed.metadata["failures"]
    for evidence in failed.metadata["file_evidence"]:
        assert any(s["max_channel_delta"] <= 12 and not s["source_bound"] for s in evidence["profile_scores"])

    # A correct export is not hidden by a closer-matching export of the wrong photo.
    mixed = dict(right)
    mixed["/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_0.jpg"] = export(second.profile_id, first.profile_id, "e.jpg")
    assert _evaluate(key, mixed).status == EvalStatus.PASS


@pytest.mark.parametrize("key", ["cooking", "guitar"])
def test_evaluator_passes_the_real_device_exports(key) -> None:
    spec = calibration.TASK_FIXTURES[key]
    folders = [REFERENCES / t.profile_id for t in spec.targets]
    if not all((folder / "correct.jpg").is_file() for folder in folders):
        pytest.skip("benchmark-v2 reference exports not present")
    exports = {f"/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_{i}.jpg": folder / "correct.jpg"
               for i, folder in enumerate(folders)}
    result = _evaluate(key, exports)
    assert result.status == EvalStatus.PASS, result.metadata["failures"]
    for name in ("unedited-negative.jpg", "wrong-exposure-negative.jpg"):
        negative = dict(exports)
        negative["/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_0.jpg"] = folders[0] / name
        assert _evaluate(key, negative).status == EvalStatus.FAIL, name


# ----------------------------------------------------------- initializer
class _Device:
    """adb stand-in with a file system, a media scanner and MediaStore rows."""

    def __init__(self, *, exports=(), scanner_works=True, truncate_pushes=False, content_provider=True) -> None:
        # The snapshot already holds (and indexes) other pictures under the cited names.
        self.files: dict[str, bytes] = {f"/sdcard/Pictures/{n}": b"old" for n in
                                        ("portrait_16.jpg", "portrait_17.jpg", "portrait_20.jpg", "portrait_21.jpg",
                                         "landscape_17.jpg", "landscape_18.jpg")}
        self.media_sizes: dict[str, int] = {path.rsplit("/", 1)[1]: 3 for path in self.files}
        self.events: list[tuple[str, str]] = []
        self.exports = list(exports)
        self.scanner_works = scanner_works
        self.truncate_pushes = truncate_pushes
        self.content_provider = content_provider
        self.broadcasts: list[str] = []
        self.serial = "emulator-5554"

    def is_connected(self) -> bool:
        return True

    def foreground_package(self) -> str:
        return APP

    def execute_adb(self, args: list[str]) -> str:
        if args[0] == "push":
            data = Path(args[1]).read_bytes()
            self.files[args[2]] = data[:-1] if self.truncate_pushes else data
            self.events.append(("push", args[2]))
            return "1 file pushed"
        if args[:3] == ["shell", "pm", "path"]:
            return f"package:/data/app/{APP}/base.apk"
        if args[:3] == ["shell", "am", "broadcast"]:
            path = args[-1].removeprefix("file://")
            self.broadcasts.append(path)
            if self.scanner_works:
                name = path.rsplit("/", 1)[1]
                if path in self.files:
                    self.media_sizes[name] = len(self.files[path])
                else:
                    self.media_sizes.pop(name, None)
            return "Broadcast completed: result=0"
        command = args[-1]
        if command.startswith("rm -f "):
            path = shlex.split(command)[2]
            self.files.pop(path, None)
            self.events.append(("rm", path))
            return ""
        if command.startswith("wc -c <"):
            path = shlex.split(command)[3]
            return str(len(self.files[path])) if path in self.files else ""
        if command.startswith("sha256sum "):
            path = shlex.split(command)[1]
            return f"{hashlib.sha256(self.files[path]).hexdigest()}  {path}" if path in self.files else ""
        if command.startswith("content query"):
            if not self.content_provider:
                return ""
            name = shlex.split(command)[-1].split("'")[1]
            size = self.media_sizes.get(name)
            return f"Row: 0 _display_name={name}, _size={size}" if size else "No result found."
        if command.startswith("if [ -d") and "OpenPhotoEdit_*.jpg" in command:
            return "\n".join(self.exports)
        return ""


@pytest.mark.parametrize("key", sorted(TASK_FILES))
def test_initializer_installs_the_calibrated_inputs_and_records_the_baseline(tmp_path, key) -> None:
    task = _task(key)
    spec = calibration.TASK_FIXTURES[key]
    old_export = "/sdcard/Pictures/OpenPhotoEdit/OpenPhotoEdit_20260101_000000.jpg"
    device = _Device(exports=[old_export])
    initializer = load_initializer(task["init"]["initializer_id"])
    params = dict(task["init"]["params"], wait_ms=1)
    result = initializer.initialize({"controller": device, "params": params, "run_dir": tmp_path, "task": None})
    assert result.status == InitStatus.PASS, result.message
    for target in spec.targets:
        assert device.files[target.device_path] == calibration.build_fixture_bytes(spec, target)
        assert device.broadcasts.count(target.device_path) == 2  # retire the old row, index the new file
        assert device.events.index(("rm", target.device_path)) < device.events.index(("push", target.device_path))
    baseline = yaml.safe_load((tmp_path / calibration.BASELINE_FILENAME).read_text(encoding="utf-8"))
    assert baseline["paths"] == [old_export]
    assert [f["device_path"] for f in baseline["fixtures"]] == [t.device_path for t in spec.targets]
    assert all(f["media_store_indexed"] for f in baseline["fixtures"])
    assert all(f["previous_media_row_retired"] for f in baseline["fixtures"])
    assert result.metadata["read_only"] is False


def test_initializer_fails_when_a_push_does_not_land(tmp_path) -> None:
    task = _task("clown")
    result = load_initializer(task["init"]["initializer_id"]).initialize(
        {"controller": _Device(truncate_pushes=True), "params": dict(task["init"]["params"], wait_ms=1),
         "run_dir": tmp_path}
    )
    assert result.status == InitStatus.ERROR
    assert "calibrated input photos could not be installed" in result.message


def test_fixture_install_fails_when_mediastore_never_indexes_the_inputs(tmp_path) -> None:
    with pytest.raises(calibration.FixtureError, match="MediaStore did not index"):
        calibration.install_task_fixtures(_Device(scanner_works=False), "guitar", run_dir=tmp_path,
                                          media_scan_timeout_seconds=0.0, retire_timeout_seconds=0.0,
                                          poll_seconds=0.0)


def test_fixture_install_tolerates_a_shell_without_content_provider_access(tmp_path) -> None:
    baseline = calibration.install_task_fixtures(_Device(content_provider=False), "cooking", run_dir=tmp_path,
                                                 media_scan_timeout_seconds=0.0)
    assert [f["media_store_indexed"] for f in baseline["fixtures"]] == [None, None]
    assert [f["previous_media_row_retired"] for f in baseline["fixtures"]] == [None, None]
