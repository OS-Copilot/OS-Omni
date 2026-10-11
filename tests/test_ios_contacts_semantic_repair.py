"""Semantic repair pins for the two iOS Contacts tasks (option (a) preserve).

Independent, device-free fixture checks only. No GUI, no model calls, no
formal logs/results inspected. Two layers:

1. YAML pins: instructions must state First/Last splits explicitly
   (audit option (a)) and every present_contacts spec with a stated
   phone/email set must opt in to exact channel equality. Absent-contact
   stale-value guards must NOT carry exact flags (subset matching).
2. Fixture checks: ``IOSContactsStore.contact_matches_spec`` /
   ``assert_state`` (with ``list_contacts`` stubbed to in-memory
   fixtures) must PASS the canonical correct refs and FAIL every defect
   class: wrong First/Last split, wrong name/company/phone/email, extra
   phone/email, missing contact, extra contact. The absent old-phone
   guard must still work, and the default (no exact flags) must remain
   legacy subset behavior.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from platforms.ios.contacts_store import (
    IOSContactRecord,
    IOSContactsStore,
    coerce_contact_specs,
)

REPO = Path(__file__).resolve().parent.parent
ADD_CARD_YAML = REPO / "tasks" / "v1" / "ios" / "contacts_add_contact_card.yaml"
RECONCILE_YAML = REPO / "tasks" / "v1" / "ios" / "contacts_reconcile_multi_field_directory.yaml"


def _record(first, last, org="", phones=(), emails=(), note="", rowid=1):
    return IOSContactRecord(
        rowid=rowid,
        first_name=first,
        last_name=last,
        organization=org,
        note=note,
        phones=tuple(phones),
        emails=tuple(emails),
        guid=f"fixture-{rowid}",
    )


def _store_with(records):
    store = IOSContactsStore.__new__(IOSContactsStore)
    store.list_contacts = lambda: list(records)  # noqa: E731
    return store


def _load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# Canonical correct fixtures ------------------------------------------------

ADD_SPEC_DICT = {
    "first_name": "Bench",
    "last_name": "Courier",
    "organization": "Bench Logistics",
    "phones": ["555-010-2486"],
    "emails": ["courier@bench-example.test"],
    "exact_phones": True,
    "exact_emails": True,
}
ADD_CORRECT = _record(
    "Bench", "Courier", "Bench Logistics",
    ["555-010-2486"], ["courier@bench-example.test"],
)

LOGISTICS_CORRECT = _record(
    "Bench", "Logistics", "Bench Logistics Desk",
    ["555-010-4400", "555-010-4401"], ["logistics@bench-example.test"],
    note="Use loading dock entrance.", rowid=1,
)
CATERING_CORRECT = _record(
    "Bench", "Catering Lead", "Bench Catering",
    ["555-010-4510"], ["catering-lead@bench-example.test"], rowid=2,
)
SECURITY_CORRECT = _record(
    "Bench", "Security", "North Gate Team",
    ["555-010-4620", "555-010-4621"], ["security@bench-example.test"],
    note="Badge desk closes at 21:00.", rowid=3,
)
OFFICE_CORRECT = _record(
    "Bench", "Office", "Bench HQ",
    ["555-010-4333"], ["office@bench-example.test"],
    note="Keep this record unchanged.", rowid=4,
)


def _reconcile_specs():
    doc = _load_yaml(RECONCILE_YAML)
    return coerce_contact_specs(doc["evaluation"]["params"]["present_contacts"])


# 1. YAML pins ----------------------------------------------------------------

def test_add_card_yaml_clarifies_name_split_and_exact_channels():
    doc = _load_yaml(ADD_CARD_YAML)
    instruction = doc["instruction"]
    assert "first name Bench" in instruction
    assert "last name Courier" in instruction
    specs = doc["evaluation"]["params"]["present_contacts"]
    assert len(specs) == 1
    spec = specs[0]
    assert spec["first_name"] == "Bench" and spec["last_name"] == "Courier"
    assert spec.get("exact_phones") is True
    assert spec.get("exact_emails") is True


def test_reconcile_yaml_clarifies_name_splits_preserves_catering_and_exact():
    doc = _load_yaml(RECONCILE_YAML)
    instruction = doc["instruction"]
    for last in ("Logistics", "Catering Lead", "Venue Old", "Security", "Office"):
        assert f"last name {last}" in instruction, last
    assert "Bench Catering" in instruction
    assert "unchanged as Bench Catering" in instruction
    present = doc["evaluation"]["params"]["present_contacts"]
    assert len(present) == 4
    for spec in present:
        assert spec.get("exact_phones") is True
        assert spec.get("exact_emails") is True
    absent = doc["evaluation"]["params"]["absent_contacts"]
    assert len(absent) == 5
    for spec in absent:
        assert spec.get("exact_phones") in (None, False), spec
        assert spec.get("exact_emails") in (None, False), spec


# 2. add_contact_card fixture checks -------------------------------------------

def test_add_card_correct_ref_passes():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    assert IOSContactsStore.contact_matches_spec(ADD_CORRECT, spec) is True


def test_add_card_wrong_split_explicitly_fails():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    degenerate = _record(
        "Bench Courier", "", "Bench Logistics",
        ["555-010-2486"], ["courier@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(degenerate, spec) is False


def test_add_card_wrong_name_fails():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    swapped = _record(
        "Courier", "Bench", "Bench Logistics",
        ["555-010-2486"], ["courier@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(swapped, spec) is False


def test_add_card_wrong_company_fails():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    wrong_org = _record(
        "Bench", "Courier", "Bench Logistics Desk",
        ["555-010-2486"], ["courier@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(wrong_org, spec) is False


def test_add_card_wrong_phone_fails():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    wrong_phone = _record(
        "Bench", "Courier", "Bench Logistics",
        ["555-010-2487"], ["courier@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(wrong_phone, spec) is False


def test_add_card_wrong_email_fails():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    wrong_email = _record(
        "Bench", "Courier", "Bench Logistics",
        ["555-010-2486"], ["courier@bench-example.example"],
    )
    assert IOSContactsStore.contact_matches_spec(wrong_email, spec) is False


def test_add_card_extra_phone_fails_under_exact():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    extra = _record(
        "Bench", "Courier", "Bench Logistics",
        ["555-010-2486", "555-010-9999"], ["courier@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(extra, spec) is False


def test_add_card_extra_email_fails_under_exact():
    (spec,) = coerce_contact_specs([ADD_SPEC_DICT])
    extra = _record(
        "Bench", "Courier", "Bench Logistics",
        ["555-010-2486"],
        ["courier@bench-example.test", "extra@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(extra, spec) is False


def test_add_card_default_remains_legacy_subset():
    (legacy,) = coerce_contact_specs([
        {k: v for k, v in ADD_SPEC_DICT.items()
         if k not in ("exact_phones", "exact_emails")}
    ])
    assert legacy.exact_phones is False and legacy.exact_emails is False
    superset = _record(
        "Bench", "Courier", "Bench Logistics",
        ["555-010-2486", "555-010-9999"],
        ["courier@bench-example.test", "extra@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(superset, legacy) is True


def test_add_card_missing_contact_fails_assert_state():
    doc = _load_yaml(ADD_CARD_YAML)
    store = _store_with([])
    result = store.assert_state(doc["evaluation"]["params"])
    assert result["status"] == "fail"


def test_add_card_extra_contact_fails_assert_state():
    doc = _load_yaml(ADD_CARD_YAML)
    duplicate = _record(
        "Bench", "Courier", "Bench Logistics",
        ["555-010-2486"], ["courier@bench-example.test"], rowid=2,
    )
    store = _store_with([ADD_CORRECT, duplicate])
    result = store.assert_state(doc["evaluation"]["params"])
    assert result["status"] == "fail"


# 3. reconcile fixture checks ---------------------------------------------------

def test_reconcile_correct_refs_pass_assert_state():
    doc = _load_yaml(RECONCILE_YAML)
    store = _store_with(
        [LOGISTICS_CORRECT, CATERING_CORRECT, SECURITY_CORRECT, OFFICE_CORRECT]
    )
    result = store.assert_state(doc["evaluation"]["params"])
    assert result["status"] == "pass", result["failures"]


def test_reconcile_three_token_wrong_split_fails():
    specs = _reconcile_specs()
    catering_spec = next(s for s in specs if s.last_name == "Catering Lead")
    resplit = _record(
        "Bench Catering", "Lead", "Bench Catering",
        ["555-010-4510"], ["catering-lead@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(resplit, catering_spec) is False


def test_reconcile_security_wrong_split_fails():
    specs = _reconcile_specs()
    security_spec = next(s for s in specs if s.last_name == "Security")
    degenerate = _record(
        "Bench Security", "", "North Gate Team",
        ["555-010-4620", "555-010-4621"], ["security@bench-example.test"],
        note="Badge desk closes at 21:00.",
    )
    assert IOSContactsStore.contact_matches_spec(degenerate, security_spec) is False


def test_reconcile_catering_company_change_fails():
    specs = _reconcile_specs()
    catering_spec = next(s for s in specs if s.last_name == "Catering Lead")
    changed = _record(
        "Bench", "Catering Lead", "Other Co",
        ["555-010-4510"], ["catering-lead@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(changed, catering_spec) is False


def test_reconcile_extra_phone_fails_under_exact():
    specs = _reconcile_specs()
    logistics_spec = next(s for s in specs if s.last_name == "Logistics")
    extra = _record(
        "Bench", "Logistics", "Bench Logistics Desk",
        ["555-010-4400", "555-010-4401", "555-010-9999"],
        ["logistics@bench-example.test"],
        note="Use loading dock entrance.",
    )
    assert IOSContactsStore.contact_matches_spec(extra, logistics_spec) is False


def test_reconcile_extra_email_fails_under_exact():
    specs = _reconcile_specs()
    security_spec = next(s for s in specs if s.last_name == "Security")
    extra = _record(
        "Bench", "Security", "North Gate Team",
        ["555-010-4620", "555-010-4621"],
        ["security@bench-example.test", "extra@bench-example.test"],
        note="Badge desk closes at 21:00.",
    )
    assert IOSContactsStore.contact_matches_spec(extra, security_spec) is False


def test_reconcile_absent_old_phone_guard_still_works():
    doc = _load_yaml(RECONCILE_YAML)
    params = doc["evaluation"]["params"]
    stale = _record(
        "Bench", "Logistics", "Bench Logistics Desk",
        ["555-010-4400", "555-010-4401", "555-010-4000"],
        ["logistics@bench-example.test"],
        note="Use loading dock entrance.", rowid=1,
    )
    store = _store_with(
        [stale, CATERING_CORRECT, SECURITY_CORRECT, OFFICE_CORRECT]
    )
    result = store.assert_state(params)
    assert result["status"] == "fail"
    assert any("555-010-4000" in failure or "Logistics" in failure
               for failure in result["failures"])
    clean_store = _store_with(
        [LOGISTICS_CORRECT, CATERING_CORRECT, SECURITY_CORRECT, OFFICE_CORRECT]
    )
    clean = clean_store.assert_state(params)
    assert clean["status"] == "pass", clean["failures"]


def test_reconcile_absent_guards_remain_subset_matching():
    doc = _load_yaml(RECONCILE_YAML)
    absent_specs = coerce_contact_specs(doc["evaluation"]["params"]["absent_contacts"])
    assert all(s.exact_phones is False and s.exact_emails is False
               for s in absent_specs)
    old_phone_spec = next(
        s for s in absent_specs
        if s.last_name == "Logistics" and "555-010-4000" in s.phones
    )
    stale_among_new = _record(
        "Bench", "Logistics", "Bench Logistics Desk",
        ["555-010-4400", "555-010-4000"], ["logistics@bench-example.test"],
    )
    assert IOSContactsStore.contact_matches_spec(
        stale_among_new, old_phone_spec) is True


def test_reconcile_missing_contact_fails_assert_state():
    doc = _load_yaml(RECONCILE_YAML)
    store = _store_with([LOGISTICS_CORRECT, CATERING_CORRECT, OFFICE_CORRECT])
    result = store.assert_state(doc["evaluation"]["params"])
    assert result["status"] == "fail"


def test_reconcile_extra_contact_fails_assert_state():
    doc = _load_yaml(RECONCILE_YAML)
    extra = _record(
        "Bench", "Extra", "Bench HQ", ["555-010-0000"],
        ["extra@bench-example.test"], rowid=5,
    )
    store = _store_with(
        [LOGISTICS_CORRECT, CATERING_CORRECT, SECURITY_CORRECT,
         OFFICE_CORRECT, extra]
    )
    result = store.assert_state(doc["evaluation"]["params"])
    assert result["status"] == "fail"


def test_reconcile_note_literals_are_explicit_and_strict():
    instruction = _load_yaml(RECONCILE_YAML)['instruction']
    assert '"Use loading dock entrance."' in instruction
    assert '"Badge desk closes at 21:00."' in instruction
    spec = next(s for s in _reconcile_specs() if s.last_name == 'Logistics')
    without_period = _record('Bench', 'Logistics', 'Bench Logistics Desk',
        ['555-010-4400', '555-010-4401'], ['logistics@bench-example.test'],
        note='Use loading dock entrance')
    assert IOSContactsStore.contact_matches_spec(without_period, spec) is False
    assert IOSContactsStore.contact_matches_spec(LOGISTICS_CORRECT, spec) is True
