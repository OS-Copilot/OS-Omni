"""LNX-062: "repeating every week (Weekly)" accepts the parts Thunderbird stores for a Weekly
event (BYDAY, WKST, ...) but still needs a weekly rule repeating every week (PR #41)."""

from __future__ import annotations

import pytest

from evaluators.linux.thunderbird_calendar_thunderbird2_392495 import _weekly_every_week


@pytest.mark.parametrize("rrule", [
    "RRULE:FREQ=WEEKLY",
    "RRULE:FREQ=WEEKLY;INTERVAL=1",
    "RRULE:FREQ=WEEKLY;BYDAY=FR",
    "RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=FR;WKST=MO",
])
def test_thunderbird_weekly_rules_pass(rrule):
    assert _weekly_every_week([rrule])[0]


@pytest.mark.parametrize("items", [
    ["RRULE:FREQ=DAILY"],
    ["RRULE:FREQ=WEEKLY;INTERVAL=2"],
    ["RRULE:FREQ=WEEKLY;BYDAY=MO,FR"],
    ["RRULE:FREQ=WEEKLY;BYMONTH=7"],
    [],
    ["RRULE:FREQ=WEEKLY", "RRULE:FREQ=WEEKLY"],
])
def test_other_rules_fail(items):
    assert not _weekly_every_week(items)[0]
