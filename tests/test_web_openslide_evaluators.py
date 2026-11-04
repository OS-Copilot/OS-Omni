"""OpenSlide Web tasks (QA70, QA71): objects are found by how they were made, not by their default text and size."""

from __future__ import annotations

import copy
import json
import struct
import subprocess
import sys

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.linux import openslide_qa71_training_701512 as qa71

DECK_MS = 1790000000000  # template applied (deck created)
LAYOUT_MS = DECK_MS + 60_000  # Section Header re-applied on slide 2


def _b36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while value:
        value, rest = divmod(value, 36)
        out = digits[rest] + out
    return out or "0"


def _obj(ms: int, tag: str, kind: str, **fields):
    style = {"fontFamily": "Arial", "fontSize": 32, "color": "#111827", "fill": "#ffffff", "bold": False,
             "italic": False, "underline": False, "align": "left", "border": "#172033"}
    style.update(fields.pop("style", {}))
    row = {"id": "obj-%s-%s" % (_b36(ms), tag), "type": kind, "x": 120, "y": 110, "w": 360, "h": 90, "z": 1,
           "text": "", "src": "", "alt": "", "shape": "rounded", "fit": "cover", "animation": "none", "style": style}
    row.update(fields)
    return row


def _deck(title: str = qa71.FINAL_TITLE) -> dict:
    """The final deck of a correct run (shaped like the saved Opus 5.5 end state)."""
    centered = {"fontSize": 32, "align": "center"}
    slide = lambda layout, objects, **extra: {"id": "slide-%s" % layout, "layout": layout, "transition": "push",
                                             "notes": "", "comments": [], "objects": objects, **extra}
    return {
        "id": "deck-qa71", "title": title, "theme": "sunrise", "size": "wide",
        "slides": [
            slide("title", [_obj(DECK_MS, "t1", "text", text="QA71 Training", style={"fontSize": 54, "bold": True})]),
            slide("section", [
                _obj(LAYOUT_MS, "bg", "shape", x=0, y=0, w=960, h=540, z=0),
                _obj(LAYOUT_MS, "st", "text", x=120, y=210, w=720, h=88,
                     text="Section title", style={"fontSize": 56, "bold": True, "align": "center"}),
                _obj(LAYOUT_MS + 9_000, "tb", "text", z=2, text="Text box", style=centered),
                _obj(LAYOUT_MS + 20_000, "tq", "table", z=3, alt="qa71 agenda table", animation="appear"),
            ]),
            slide("title-content", [
                _obj(DECK_MS, "s3", "text", text="Slide title"),
                _obj(LAYOUT_MS + 40_000, "l1", "line", y=400, w=380, h=4, z=2),
                _obj(LAYOUT_MS + 45_000, "l2", "line", y=270, w=380, h=4, z=3),
                _obj(LAYOUT_MS + 90_000, "kc", "text", z=4, text="Knowledge Check", style=centered),
            ], notes="qa71 trainer note",
                comments=[{"id": "comment-1", "author": "You", "text": "qa71 training comment"}]),
            slide("title-content", [_obj(DECK_MS, "s4", "text", text="Slide title")]),
            slide("section", [_obj(DECK_MS, "s5", "shape", w=960, h=540, z=0)]),
        ],
    }


def _judge(deck: dict) -> dict:
    return qa71.evaluate_observed({"target_versions": [deck], "final_title_count": 1, "sources": [], "errors": []})


def _check(verdict: dict, check_id: str) -> dict:
    return next(row for row in verdict["checks"] if row["check_id"] == check_id)


def test_reference_deck_passes():
    verdict = _judge(_deck())
    assert verdict["status"] == "PASS", verdict["failures"]


def test_text_box_with_typed_text_and_new_size_is_still_the_inserted_text_box():
    deck = _deck()
    box = deck["slides"][1]["objects"][2]
    box.update(text="Agenda: onboarding, tools, review", h=140, w=520)
    verdict = _judge(deck)
    check = _check(verdict, "slide2.inserted_text_style")
    assert check["passed"], check
    assert [row["text"] for row in check["actual"]["candidates"]] == ["Agenda: onboarding, tools, review"]
    assert verdict["status"] == "PASS", verdict["failures"]


def test_section_title_placeholder_is_not_an_inserted_text_box():
    deck = _deck()
    objects = deck["slides"][1]["objects"]
    del objects[2]  # no text box inserted; the layout's own title restyled instead
    objects[1]["style"].update(fontSize=32, bold=False, align="center")
    check = _check(_judge(deck), "slide2.inserted_text_style")
    assert not check["passed"] and check["actual"]["count"] == 0


def test_inserted_text_box_still_needs_32_point_centered_text():
    deck = _deck()
    deck["slides"][1]["objects"][2]["style"]["fontSize"] = 24
    assert not _check(_judge(deck), "slide2.inserted_text_style")["passed"]
    deck = _deck()
    deck["slides"][1]["objects"][2]["style"]["align"] = "left"
    assert not _check(_judge(deck), "slide2.inserted_text_style")["passed"]


def test_any_one_well_formatted_inserted_text_box_is_enough():
    deck = _deck()
    extra = _obj(LAYOUT_MS + 12_000, "x2", "text", z=5, text="Text box")  # a second, unformatted box
    deck["slides"][1]["objects"].append(extra)
    check = _check(_judge(deck), "slide2.inserted_text_style")
    assert check["passed"] and check["actual"]["count"] == 2


def test_comment_may_be_on_any_slide_but_must_exist():
    deck = _deck()
    comment = deck["slides"][2].pop("comments")
    deck["slides"][2]["comments"] = []
    deck["slides"][0]["comments"] = comment
    assert _check(_judge(deck), "deck.comment")["passed"]
    deck["slides"][0]["comments"] = [{"id": "c", "text": "another comment"}]
    assert not _check(_judge(deck), "deck.comment")["passed"]


def test_knowledge_check_text_is_compared_without_surrounding_whitespace():
    deck = _deck()
    deck["slides"][2]["objects"][3]["text"] = "Knowledge Check\n"
    assert _check(_judge(deck), "slide3.knowledge_check")["passed"]
    deck["slides"][2]["objects"][3]["style"]["fontSize"] = 28
    assert not _check(_judge(deck), "slide3.knowledge_check")["passed"]


# --- the guest read: Chrome's Local Storage LevelDB log, replayed by the evaluator's own script ---

_BLOCK = 32768
_KEY = b"_file://\x00\x01openslide.decks.v1"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _log(documents: list[list[dict]]) -> bytes:
    out = bytearray()
    for sequence, decks in enumerate(documents, start=1):
        value = b"\x01" + json.dumps(decks).encode("utf-8")
        payload = struct.pack("<QI", sequence, 1) + b"\x01" + _varint(len(_KEY)) + _KEY + _varint(len(value)) + value
        first = True
        while True:
            left = _BLOCK - len(out) % _BLOCK
            if left <= 7:
                out += b"\x00" * left
                continue
            fragment, payload = payload[:left - 7], payload[left - 7:]
            kind = (1 if not payload else 2) if first else (4 if not payload else 3)
            out += struct.pack("<IHB", 0, len(fragment), kind) + fragment
            first = False
            if not payload:
                break
    return bytes(out)


class _LocalGuest:
    def run_python_script(self, code, timeout=60):
        done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=timeout)
        return {"stdout": done.stdout, "stderr": done.stderr, "returncode": done.returncode}


def test_guest_read_follows_the_deck_through_its_rename(tmp_path):
    final = _deck()
    one_line = copy.deepcopy(final)
    one_line["title"] = "qa71-training"
    del one_line["slides"][2]["objects"][2]
    two_lines = copy.deepcopy(final)
    two_lines["title"] = "qa71-training"
    other = {"id": "deck-other", "title": "Product pitch", "slides": []}
    (tmp_path / "000003.log").write_bytes(_log([[one_line, other], [two_lines, other], [final, other]]))

    result = qa71.OpenSlideQa71Training701512Evaluator().evaluate(
        {"controller": _LocalGuest(), "params": {"profile_dir": str(tmp_path)}})
    assert result.status == EvalStatus.PASS, result.message
    lines = _check(result.metadata, "slide3.copy_paste_lines")["actual"]
    assert lines["history_counts"] == [1, 2, 2]  # the pre-rename generations are part of the deck's history
    assert result.metadata["ruleset_sha256"] == qa71.RULESET_SHA256


def test_guest_read_without_the_final_title_fails(tmp_path):
    renamed_late = _deck(title="qa71-training")
    (tmp_path / "000003.log").write_bytes(_log([[renamed_late]]))
    result = qa71.OpenSlideQa71Training701512Evaluator().evaluate(
        {"controller": _LocalGuest(), "params": {"profile_dir": str(tmp_path)}})
    assert result.status == EvalStatus.FAIL
    assert "deck.title" in result.metadata["failures"]


def test_task_metadata_records_the_current_ruleset_digest():
    import yaml
    from pathlib import Path

    task = yaml.safe_load(Path(__file__).resolve().parents[1].joinpath(
        "tasks/v1/web/openslide_qa71_training_701512.yaml").read_text(encoding="utf-8"))
    assert task["metadata"]["ruleset_sha256"] == qa71.RULESET_SHA256


# --- QA70 -------------------------------------------------------------------------------------------

from evaluators.cua_review.evaluators.linux import openslide_leveldb as reader  # noqa: E402
from evaluators.linux import openslide_qa70_review_199367 as qa70  # noqa: E402

COMPARISON_MS = DECK_MS + 120_000  # Comparison layout applied to slide 3


def _comparison(ms: int, tag: str) -> list[dict]:
    box = {"fill": "#0b4f6c", "border": "#118ab2"}
    return [
        _obj(ms, tag + "t", "text", x=70, y=44, w=820, h=56, text="Comparison", style={"fontSize": 40, "bold": True}),
        _obj(ms, tag + "a", "shape", x=80, y=136, w=360, h=270, style=box),
        _obj(ms, tag + "b", "shape", x=520, y=136, w=360, h=270, style=box),
        _obj(ms, tag + "c", "text", x=105, y=162, w=310, h=190, text="Option A\n- Detail\n- Detail"),
        _obj(ms, tag + "d", "text", x=545, y=162, w=310, h=190, text="Option B\n- Detail\n- Detail"),
    ]


def _qa70_deck() -> dict:
    """The final deck of the saved Opus 5.5 run (which passes)."""
    pink = {"fill": "#ffd7c8", "border": "#c43e1c"}
    slide = lambda layout, objects, **extra: {"id": "slide-%s" % layout, "layout": layout, "transition": "fade",
                                             "notes": "", "comments": [], "objects": objects, **extra}
    return {
        "id": "deck-qa70", "title": qa70.FINAL_TITLE, "theme": "marine", "size": "wide",
        "slides": [
            slide("title", [_obj(DECK_MS, "t1", "text", text="QA70 Review")]),
            slide("title-content", [
                _obj(DECK_MS, "t2", "text", text="Metrics"),
                _obj(DECK_MS + 30_000, "ch", "chart", z=3, alt="qa70 chart", animation="fade"),
            ]),
            slide("comparison", _comparison(COMPARISON_MS, "c3") + [
                _obj(COMPARISON_MS + 9_000, "p1", "shape", x=170, y=155, w=260, h=140, z=2, style=pink),
                _obj(COMPARISON_MS + 20_000, "p2", "shape", x=560, y=155, w=260, h=140, z=3, style=pink),
            ]),
            slide("comparison", _comparison(DECK_MS, "c4") + [
                _obj(COMPARISON_MS + 90_000, "tb", "table", x=80, y=130, w=800, h=360, z=4),
            ], notes="qa70 speaker note\nDecision owners locked for Friday review",
                comments=[{"id": "c2", "text": "quarterly decision matrix owner review"}, {"id": "c1", "text": "qa70 comment"}]),
        ],
    }


def _qa70_judge(*decks: dict) -> dict:
    return qa70.evaluate_observed({"target_versions": list(decks), "final_title_count": 1, "sources": [], "errors": []})


def test_qa70_reference_deck_passes():
    verdict = _qa70_judge(_qa70_deck())
    assert verdict["status"] == "PASS", verdict["failures"]


def test_qa70_resized_shape_and_its_duplicate_are_still_found():
    deck = _qa70_deck()
    for shape in deck["slides"][2]["objects"][-2:]:
        shape.update(w=300, h=180)
    check = _check(_qa70_judge(deck), "slide3.copy_paste_move")
    assert check["passed"], check
    deck["slides"][2]["objects"][-1]["w"] = 320  # no longer a duplicate of the first
    assert not _check(_qa70_judge(deck), "slide3.copy_paste_move")["passed"]


def test_qa70_recoloured_layout_boxes_are_not_the_inserted_shapes():
    deck = _qa70_deck()
    objects = deck["slides"][2]["objects"]
    del objects[-2:]
    for box in objects[1:3]:
        box["style"]["fill"] = "#ffd7c8"
    check = _check(_qa70_judge(deck), "slide3.copy_paste_move")
    assert not check["passed"] and check["actual"]["count"] == 0


def test_qa70_slide2_title_and_slide3_layout_are_checked():
    deck = _qa70_deck()
    deck["slides"][1]["objects"][0]["text"] = "Slide title"
    assert not _check(_qa70_judge(deck), "slide2.title")["passed"]
    deck = _qa70_deck()
    deck["slides"][2]["layout"] = "title-content"
    assert not _check(_qa70_judge(deck), "slide3.layout")["passed"]


def test_qa70_notes_order_from_history_or_from_the_final_text():
    final = _qa70_deck()
    # compacted store: only the last generation survives, the final notes hold both notes in order
    assert _check(_qa70_judge(final), "slide4.notes_sequence")["passed"]

    replaced = _qa70_deck()
    replaced["slides"][3]["notes"] = "Decision owners locked for Friday review"
    assert not _check(_qa70_judge(replaced), "slide4.notes_sequence")["passed"]
    first = copy.deepcopy(replaced)
    first["slides"][3]["notes"] = "qa70 speaker note"
    assert _check(_qa70_judge(first, replaced), "slide4.notes_sequence")["passed"]  # history shows both

    only_first = _qa70_deck()
    only_first["slides"][3]["notes"] = "qa70 speaker note"
    assert not _check(_qa70_judge(only_first), "slide4.notes_sequence")["passed"]


def test_qa70_guest_read_and_task_digest(tmp_path):
    import yaml
    from pathlib import Path

    final = _qa70_deck()
    seed = copy.deepcopy(final)
    seed["title"] = "Business review"
    (tmp_path / "000003.log").write_bytes(_log([[seed], [final]]))
    task = yaml.safe_load(Path(__file__).resolve().parents[1].joinpath(
        "tasks/v1/web/openslide_qa70_review_199367.yaml").read_text(encoding="utf-8"))
    params = dict(task["evaluation"]["params"], profile_dir=str(tmp_path))
    assert params["expected_ruleset_sha256"] == task["metadata"]["ruleset_sha256"] == qa70.RULESET_SHA256
    result = qa70.OpenSlideQa70Review199367Evaluator().evaluate({"controller": _LocalGuest(), "params": params})
    assert result.status == EvalStatus.PASS, result.message
    assert result.metadata["history_version_count"] == 2  # the generation before the title was set is followed too


def test_shared_helpers_follow_the_deck_id_and_skip_layout_placeholders():
    renamed = {"id": "d1", "title": "draft"}
    history = {"versions": [{"decks": [renamed]}, {"decks": [dict(renamed, title="final"), {"id": "d2", "title": "x"}]}]}
    versions, count = reader.final_deck_versions(history, "final")
    assert [deck["title"] for deck in versions] == ["draft", "final"] and count == 1
    assert reader.final_deck_versions(history, "missing") == ([], 0)
    assert reader.final_deck_versions({"versions": [{"decks": None}]}, "final") == ([], 0)

    slide = _qa70_deck()["slides"][2]
    assert [obj["id"][-2:] for obj in reader.added_objects(slide, "shape")] == ["p1", "p2"]
    no_ids = {"objects": [dict(obj, id="") for obj in slide["objects"]]}
    assert len(reader.added_objects(no_ids, "shape")) == 2  # z > 1 fallback


def test_qa70_duplicate_must_sit_in_the_right_comparison_box():
    deck = _qa70_deck()
    assert _check(_qa70_judge(deck), "slide3.copy_paste_move")["actual"]["right_copy_centre"] == [690.0, 225.0]
    deck["slides"][2]["objects"][-1]["x"] = 250  # right of the original, but still in the left box
    check = _check(_qa70_judge(deck), "slide3.copy_paste_move")
    assert not check["passed"] and check["actual"]["x"] == [170.0, 250.0]
    deck["slides"][2]["objects"][-1].update(x=700, y=300)  # centre 830,370: inside 520..880 x 136..406
    assert _check(_qa70_judge(deck), "slide3.copy_paste_move")["passed"]
    deck["slides"][2]["objects"][-1].update(y=420)  # below the comparison box
    assert not _check(_qa70_judge(deck), "slide3.copy_paste_move")["passed"]


# --- QA70 rehearsal: read from the presenter overlay in the screenshots --------------------------

_BUTTONS = {"previous": (873, 948), "next": (1005, 1050), "close": (1064, 1117)}
_SLIDE_COLOURS = {1: (7, 59, 76), 2: (90, 30, 30), 3: (30, 90, 30), 4: (30, 30, 90)}


def _screenshot(path, presenter_slide=None):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1920, 1080), (243, 244, 246))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 69, 1079), fill=(40, 40, 40))  # dock
    if presenter_slide:
        draw.rectangle((70, 114, 1919, 1079), fill=(17, 24, 39))
        draw.rectangle((355, 266, 1314, 805), fill=_SLIDE_COLOURS[presenter_slide])
        draw.rectangle((70, 959, 1919, 1011), fill=(11, 16, 32))
        for x0, x1 in _BUTTONS.values():
            draw.rectangle((x0, 970, x1, 1001), fill=(255, 255, 255))
        draw.text((962, 980), "%d / 4" % presenter_slide, fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _click(name):
    x0, x1 = _BUTTONS[name]
    return "pyautogui.click(%d, 986)\ntime.sleep(1)\n" % ((x0 + x1) // 2)


def _run(tmp_path, steps, final_slide=None):
    """steps: (screen before the step: None for the editor or a presenter slide, reflection, code)."""
    rows = []
    for index, (screen, reflection, code) in enumerate(steps, start=1):
        shot = "screenshots/step_%d.png" % index
        _screenshot(tmp_path / shot, screen)
        rows.append({"step_index": index, "observation": {"screenshot_path": shot}, "llm_response": reflection,
                     "action_parse": {"action": {"code": code}}, "action_execution": {"status": "SUCCESS"}})
    _screenshot(tmp_path / "screenshots/final.png", final_slide)
    (tmp_path / "trajectory.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    check = qa70._collect_trajectory_process({"run_dir": str(tmp_path)}, 4)["checks"][0]
    assert check["check_id"] == "slideshow.rehearse_navigation"
    return check


_OPEN = (None, "I'll click From Start to begin the slideshow from the first slide.", "pyautogui.click(410, 258)\n")
_EDIT = (None, "Next I'll open Insert.", "pyautogui.click(526, 207)\n")


def test_qa70_rehearsal_seen_in_the_presenter_passes(tmp_path):
    check = _run(tmp_path, [
        (None, "I'll click Rehearse on the Slide Show tab.", "pyautogui.click(488, 274)\n"), _OPEN,
        (1, "The show is on slide 1 of 4. Next twice.", _click("next") * 2),
        (3, "Now on slide 3 of 4; Close ends the rehearsal.", _click("close")),
        _EDIT,
    ])
    assert check["passed"], check["actual"]
    session = check["actual"]["sessions"][0]
    assert (session["opened_by_step"], session["furthest_slide"], session["closed_by_step"]) == (2, 3, 4)
    assert session["advance_seen_on_screen"] is True


def test_qa70_words_about_rehearse_next_and_close_are_not_a_rehearsal(tmp_path):
    # The saved Opus 5.5 run's steps 1, 2, 4 and 23 satisfied the old word match this way.
    check = _run(tmp_path, [
        (None, "The brief names Google Slides-style features (template, rehearse).", "pyautogui.click(34, 66)\n"),
        (None, "Next I'll open Templates.", "pyautogui.click(1297, 148)\n"),
        (None, "Next I'll rename the presentation.", "pyautogui.click(495, 140)\n"),
        (None, "I'll close the picker and press Next.", "pyautogui.press('esc')\npyautogui.press('right')\n"),
    ])
    assert not check["passed"] and check["actual"]["sessions"] == []


def test_qa70_rehearsal_must_advance_two_slides_and_close(tmp_path):
    back = _run(tmp_path / "back", [_OPEN, (1, "Next, then Previous.", _click("next") + _click("previous")),
                                    (1, "Close.", _click("close")), _EDIT])
    assert not back["passed"] and back["actual"]["sessions"][0]["furthest_slide"] == 2
    one = _run(tmp_path / "one", [_OPEN, (1, "Next.", _click("next")), (2, "Close.", _click("close")), _EDIT])
    assert not one["passed"]
    open_at_end = _run(tmp_path / "open", [_OPEN, (1, "Next twice.", _click("next") * 2)], final_slide=3)
    assert not open_at_end["passed"] and open_at_end["actual"]["sessions"][0]["closed_by_step"] is None


def test_qa70_rehearsal_from_start_keys_and_current_slide(tmp_path):
    keys = _run(tmp_path / "keys", [
        (None, "Start the show.", "pyautogui.press('f5')\n"),
        (1, "Advance twice and leave.", "pyautogui.press('right')\npyautogui.press('right')\npyautogui.press('esc')\n"),
        _EDIT,
    ])
    assert keys["passed"], keys["actual"]
    assert keys["actual"]["sessions"][0]["advance_seen_on_screen"] is None  # no screenshot between the keys
    current = _run(tmp_path / "current", [
        (None, "I'll click Current to present from the current slide.", "pyautogui.click(470, 258)\n"),
        (1, "Next twice.", _click("next") * 2), (3, "Close.", _click("close")), _EDIT,
    ])
    assert not current["passed"] and current["actual"]["sessions"][0]["from_start"] is False
    shift = _run(tmp_path / "shift", [
        (None, "Start the show.", "pyautogui.hotkey('shift', 'f5')\n"),
        (1, "Next twice.", _click("next") * 2), (3, "Close.", _click("close")), _EDIT,
    ])
    assert not shift["passed"]


def test_qa70_rehearsal_advances_must_show_on_screen(tmp_path):
    # Next was clicked, but the next presenter screenshot still shows the first slide.
    check = _run(tmp_path, [_OPEN, (1, "Next.", _click("next")), (1, "Next.", _click("next")),
                            (1, "Close.", _click("close")), _EDIT])
    assert not check["passed"] and check["actual"]["sessions"][0]["advance_seen_on_screen"] is False


def test_qa70_pyautogui_inputs_are_read_in_order():
    code = ("import pyautogui\nfor _ in range(2):\n    pyautogui.click(1026, 986)\n"
            "pyautogui.moveTo(1089, 986)\npyautogui.click()\npyautogui.press(['right', 'pgdn'], presses=2)\n"
            "pyautogui.typewrite(' a')\npyautogui.hotkey('shift', 'f5')\n")
    assert qa70._inputs(code) == [
        ("click", (1026.0, 986.0)), ("click", (1026.0, 986.0)), ("click", (1089.0, 986.0)),
        ("key", "right"), ("key", "pagedown"), ("key", "right"), ("key", "pagedown"),
        ("key", "space"), ("key", "a"), ("key", "shift+f5"),
    ]
    assert qa70._inputs("not python(") == []
