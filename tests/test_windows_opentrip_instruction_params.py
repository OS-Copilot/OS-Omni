"""Windows OpenTrip: the graded bookings say what the instruction says, booking by booking.

windows.opentrip.v2_task_01 asked for an Economy cabin on its first booking while the evaluator
params required Business (taken from the source GUI steps the agent never sees).  The checkout's
payment select has no preselected value, so it opens on its first option, Alipay
(app.asar shared/seed-data.json paymentMethods); a booking whose payment the instruction does not
name is graded as Alipay.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = sorted((ROOT / "tasks/v1/windows").glob("opentrip_*.yaml"))
PAYMENTS = {"bank card": "card", "wechat pay": "wechat", "alipay": "alipay"}
ORDINALS = ("first", "second", "third", "fourth", "fifth")


def _segments(instruction: str) -> list[str]:
    parts = re.split(r"\bThe (first|second|third|fourth|fifth) booking\b", instruction)
    found = parts[1::2]
    assert tuple(found) == ORDINALS[:len(found)]
    return [segment.split("Upon completion")[0] for segment in parts[2::2]]


@pytest.mark.parametrize("path", TASKS, ids=[p.stem for p in TASKS])
def test_required_bookings_follow_the_instruction(path):
    task = yaml.safe_load(path.read_text(encoding="utf8"))
    bookings = task["evaluation"]["params"]["required_bookings"]
    segments = _segments(task["instruction"])
    assert len(segments) == len(bookings)
    for segment, booking in zip(segments, bookings):
        text = segment.lower()
        assert booking["note"] in segment
        named = [pid for label, pid in PAYMENTS.items() if label in text]
        assert [booking["payment_id"]] == (named or ["alipay"]), booking["label"]
        if booking["type"] == "flight":
            cabins = {cabin for cabin in ("economy", "business") if cabin in text}
            assert cabins == {booking["cabin"]}, booking["label"]
            assert booking["flight_no"] in segment
        else:
            assert booking["hotel_name"] in segment
            assert booking["room_name"] in segment
