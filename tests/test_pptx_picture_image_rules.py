"""PptxCompareEvaluator.picture_image_rules: each slide must show the instructed source image."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.linux.pptx_compare import PptxCompareEvaluator

ROOT = Path(__file__).resolve().parents[1]
BOX = (1_000_000, 800_000, 4_000_000, 3_000_000)


def _sources(tmp_path: Path) -> list[Path]:
    from PIL import Image, ImageDraw

    paths = []
    # Same red background on every image, like the kiosk template pictures; only the drawing differs.
    for index in range(1, 4):
        image = Image.new("RGB", (240, 180), (180, 20, 40))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20 * index, 30, 20 * index + 70, 120), fill=(250, 250, 250))
        draw.text((10, 150), f"slide {index}", fill=(0, 0, 0))
        path = tmp_path / f"pic{index}.png"
        image.save(path)
        paths.append(path)
    return paths


def _deck(tmp_path: Path, images: list, alts: list[str]) -> str:
    from pptx import Presentation

    prs = Presentation()
    for image, alt in zip(images, alts):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        stream = io.BytesIO(image) if isinstance(image, bytes) else str(image)
        picture = slide.shapes.add_picture(stream, *BOX)
        picture._element.nvPicPr.cNvPr.set("descr", alt)
    path = tmp_path / "deck.pptx"
    prs.save(path)
    return str(path)


def _rules(sources: list[Path]) -> list[dict]:
    return [{"slide_index": i, "source_path": str(path)} for i, path in enumerate(sources, start=1)]


def _alt_rules(sources: list[Path]) -> list[dict]:
    return [{"slide_index": i, "picture_index": 1, "descr": path.name} for i, path in enumerate(sources, start=1)]


def test_the_instructed_pictures_pass(tmp_path) -> None:
    sources = _sources(tmp_path)
    deck = _deck(tmp_path, sources, [path.name for path in sources])
    meta = PptxCompareEvaluator._validate_picture_images(deck, _rules(sources), None)
    assert [entry["match"] for entry in meta["pictures"]] == ["exact"] * 3


def test_a_swapped_picture_with_the_right_alt_text_fails(tmp_path) -> None:
    sources = _sources(tmp_path)
    # Slide 1 holds pic3.png but its description says pic1.png.
    swapped = [sources[2], sources[1], sources[2]]
    deck = _deck(tmp_path, swapped, [path.name for path in sources])
    # Before picture_image_rules this deck passed: count and alt text are all right.
    PptxCompareEvaluator._validate_picture_alt_text(deck, _alt_rules(sources))
    with pytest.raises(AssertionError, match=r"slide 1 picture 1 is not .*pic1\.png.*closest source .*pic3\.png"):
        PptxCompareEvaluator._validate_picture_images(deck, _rules(sources), None)


def test_a_re_encoded_copy_of_the_source_passes(tmp_path) -> None:
    from PIL import Image

    sources = _sources(tmp_path)
    buffer = io.BytesIO()
    Image.open(sources[0]).convert("RGB").resize((120, 90)).save(buffer, "JPEG", quality=60)
    deck = _deck(tmp_path, [buffer.getvalue(), sources[1], sources[2]], ["pic1.png", "pic2.png", "pic3.png"])
    meta = PptxCompareEvaluator._validate_picture_images(deck, _rules(sources), None)
    assert [entry["match"] for entry in meta["pictures"]] == ["pixels", "exact", "exact"]
    assert meta["pictures"][0]["mean_diff"][str(sources[0])] <= PptxCompareEvaluator.PICTURE_MAX_MEAN_DIFF


def test_a_linked_picture_is_identified_by_its_target_name(tmp_path) -> None:
    from pptx import Presentation
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.oxml.ns import qn

    sources = _sources(tmp_path)
    deck = _deck(tmp_path, sources, [path.name for path in sources])
    prs = Presentation(deck)
    for slide, target in zip(prs.slides, ["pic1.png", "pic3.png", "pic3.png"]):
        blip = slide.shapes[0]._element.blipFill.blip
        del blip.attrib[qn("r:embed")]
        blip.set(qn("r:link"), slide.part.relate_to(f"file:///home/user/Desktop/{target}", RT.IMAGE, is_external=True))
    prs.save(deck)
    rules = _rules(sources)
    meta = PptxCompareEvaluator._validate_picture_images(deck, rules[:1], None)
    assert meta["pictures"][0]["match"] == "linked"
    with pytest.raises(AssertionError, match="slide 2 picture 1 has no embedded image matching .*pic2.png"):
        PptxCompareEvaluator._validate_picture_images(deck, rules, None)


def test_a_missing_picture_fails(tmp_path) -> None:
    sources = _sources(tmp_path)
    deck = _deck(tmp_path, sources[:2], ["pic1.png", "pic2.png"])
    with pytest.raises(AssertionError, match="missing picture 1 on slide 3"):
        PptxCompareEvaluator._validate_picture_images(deck, _rules(sources), None)


def test_evaluate_runs_the_rules_only_when_asked(tmp_path) -> None:
    sources = _sources(tmp_path)
    alts = [path.name for path in sources]
    deck = _deck(tmp_path, [sources[2], sources[1], sources[2]], alts)
    base = {"actual_path": deck, "expected_path": deck, "options": {"examine_shape": False},
            "picture_alt_rules": _alt_rules(sources)}
    evaluator = PptxCompareEvaluator()
    assert evaluator.evaluate({"params": base}).status == EvalStatus.PASS
    wrong = evaluator.evaluate({"params": {**base, "picture_image_rules": _rules(sources)}})
    assert wrong.status == EvalStatus.FAIL and "pic1.png" in wrong.message
    good_deck = _deck(tmp_path, sources, alts)
    good = evaluator.evaluate({"params": {**base, "actual_path": good_deck, "expected_path": good_deck,
                                          "picture_image_rules": _rules(sources)}})
    assert good.status == EvalStatus.PASS
    assert [entry["match"] for entry in good.metadata["picture_image_rules"]["pictures"]] == ["exact"] * 3


def test_sources_are_read_from_the_guest(tmp_path) -> None:
    sources = _sources(tmp_path)
    deck = _deck(tmp_path, sources, [path.name for path in sources])

    class Guest:
        calls: list[str] = []

        def get_file(self, path):
            self.calls.append(path)
            return (tmp_path / Path(path).name).read_bytes()

    guest = Guest()
    rules = [{"slide_index": i, "source_path": f"/home/user/Desktop/pic{i}.png"} for i in range(1, 4)]
    meta = PptxCompareEvaluator._validate_picture_images(deck, rules, guest)
    assert guest.calls == [f"/home/user/Desktop/pic{i}.png" for i in range(1, 4)]
    assert [entry["match"] for entry in meta["pictures"]] == ["exact"] * 3


def test_six_image_task_checks_every_slide_against_its_desktop_picture() -> None:
    task = yaml.safe_load((ROOT / "tasks/v1/linux/impress_create_six_image_slides_hard.yaml").read_text())
    rules = task["evaluation"]["params"]["picture_image_rules"]
    assert [(rule["slide_index"], rule["source_path"]) for rule in rules] == [
        (i, f"/home/user/Desktop/pic{i}.png") for i in range(1, 7)
    ]
    seeded = {item["path"] for item in task["init"]["params"]["seed_downloads"]}
    assert {rule["source_path"] for rule in rules} <= seeded
