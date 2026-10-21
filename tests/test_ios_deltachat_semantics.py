"""Repaired semantic pins for the four iOS DeltaChat tasks (ruleset 2.1).

Device-free checks only. Opaque single-line stand-ins stand for the unknown
historical source messages (each is exactly one logical line, matching every
evaluator's resolver: unknown source resolves to ``None``, never to extra
lines). Two layers:

1. Canonical reference pins: evaluator line specs, title handling, and task
   YAML text must match the instruction-authoritative references
   (4_4: 7/18, 4_3: 6/18 plus forward, 4_2: 13/2, 4_1: 7/7).
2. Isolated fixture checks: each evaluator's pure byte helpers must PASS the
   canonical references and FAIL every defect class (wrong source, wrong
   order, missing line, wrong attachment bytes, empty init baseline).
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import yaml

from evaluators.ios import deltachat_launch_checklist_saved_messages_4_3 as e43
from evaluators.ios import deltachat_mobile_qa_brief_saved_messages_4_1 as e41
from evaluators.ios import deltachat_route_approval_saved_messages_4_2 as e42
from evaluators.ios import deltachat_route_handoff_saved_messages_4_4 as e44

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "tasks" / "v1" / "ios"

# Opaque single-line stand-ins for the unknown historical messages.
MEI = "Mei Chen route update route_final_blue_1740 confirmed"
NORA = "Nora QA verify nav_bar_search_token_nora_2606 ok"
ALICE = "Alice Design anchor design_search_anchor_alice_avatar placed"
BOB = "Bob Ops launch ops_launch_green_2026 go"

# Superseded (original) ruleset digests, kept as history.
OLD_DIGESTS = {
    "4_4": "4dd7f27a4bd97fd7c09dbd38e7accc51ee8c9a3355c0c7a2f4bad284792e38dd",
    "4_3": "e25e6ed3a0274424173024e3e9c74b3862d04914f76e2616c7b5c4f87327d3da",
    "4_2": "5e028658778e12437fcb0f9d4cad7f3b7131a3a95d1dc6c08ce0a19e175a56e4",
    "4_1": "015147a2b9cadd45340ecbd96d02bae347cbfeedb5d348db3762b9e286b86a57",
}

# Canonical instruction-authoritative content references.
CANON_44_V1 = [
    "# Handoff log", "Route handoff", MEI, "Owner Mei",
    NORA, "Receiver Nora", "Status offered",
]
CANON_44_V2 = CANON_44_V1 + [
    "Design packet", ALICE, "Sender Alice", "Ops receipt", BOB,
    "Receiver Bob", "Closure logged", "Monitor Bob", "Escalation Mei",
    "Status accepted", "Archive local",
]
CANON_43_V1 = [
    "# Launch gate", "Readiness draft", BOB, "Build 166", "Owner Bob",
    "Ops green",
]
CANON_43_V2 = CANON_43_V1 + [
    "Cutover route", MEI, "Window 1740", "Mobile verifier", NORA,
    "Gate ship ready", "Decision proceed", "Support Nora",
    "Evidence linked", "Risk no Sev1", "Monitor active", "Status ready",
]
CANON_42_FIRST = [
    "# Route gate", "Status pending", "Decision evidence", MEI,
    "Design condition", ALICE, "Ops condition", BOB, "Release verifier",
    NORA, "Decision approve", "Owner Mei", "Condition green",
]
CANON_42_SECOND = ["# Route follow-up", "Approved by Mei"]
CANON_41_FIRST = [
    "# Mobile brief", NORA, "Scope build 166", "Owner Alice",
    "Design decision", ALICE, "Gate mobile ready",
]
CANON_41_SECOND = [
    "# Mobile risks", BOB, "Risk no Sev1", "Ops green", "Route decision",
    MEI, "Gate ship ready",
]


def line_spec_entries(path: Path, name: str) -> list:
    """Resolve a V*_LINE_SPEC / *_LINES constant to its entry list."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == name:
            target = node.value
            break
    assert target is not None, f"{name} not found in {path.name}"

    def eval_tuple(node):
        items = []
        for elt in node.elts:
            if isinstance(elt, ast.Tuple):
                items.append(tuple(ast.literal_eval(e) for e in elt.elts))
            else:
                items.append(ast.literal_eval(elt))
        return items

    if isinstance(target, ast.Tuple):
        return eval_tuple(target)
    if isinstance(target, ast.BinOp) and isinstance(target.op, ast.Add):
        left = target.left
        assert isinstance(left, ast.Name)
        base = line_spec_entries(path, left.id)
        assert isinstance(target.right, ast.Tuple)
        return base + eval_tuple(target.right)
    raise AssertionError(f"unsupported spec shape for {name} in {path.name}")


def resolve(entries: list, sources: dict) -> list | None:
    lines = []
    for entry in entries:
        if isinstance(entry, str):
            lines.append(entry)
        else:
            kind, value = entry
            if kind == "literal":
                lines.append(value)
            elif value in sources:
                item = sources[value]
                lines.append(item["text"] if isinstance(item, dict) else item)
            else:
                return None
    return lines


def src(*names: str) -> dict:
    texts = {
        "mei_copy": MEI, "nora_copy": NORA, "alice_copy": ALICE,
        "bob_copy": BOB, "mei": MEI, "nora": NORA, "alice": ALICE,
        "bob": BOB,
    }
    return {name: {"text": texts[name]} for name in names}


P44 = Path(e44.__file__)
P43 = Path(e43.__file__)
P42 = Path(e42.__file__)
P41 = Path(e41.__file__)


# ---------------------------------------------------------------------------
# 4_4 handoff: canonical 7/18 in instruction order (Nora source before label)
# ---------------------------------------------------------------------------

def test_44_v1_is_seven_content_lines_without_title():
    v1 = line_spec_entries(P44, "V1_LINE_SPEC")
    assert len(v1) == 7
    assert v1[0] == ("literal", "# Handoff log")
    assert all("Handoff Log 0728" not in str(entry) for entry in v1)


def test_44_v2_appends_eleven_for_eighteen_total():
    v1 = line_spec_entries(P44, "V1_LINE_SPEC")
    v2 = line_spec_entries(P44, "V2_LINE_SPEC")
    assert len(v2) - len(v1) == 11
    assert len(v2) == 18
    assert 7 + 11 == 18  # the instruction's old "17" was arithmetic error


def test_44_nora_source_precedes_receiver_label():
    v1 = line_spec_entries(P44, "V1_LINE_SPEC")
    resolved = resolve(v1, src("mei_copy", "nora_copy", "alice_copy", "bob_copy"))
    assert resolved == CANON_44_V1
    assert resolved.index(NORA) < resolved.index("Receiver Nora")


def test_44_v2_source_order_mei_nora_alice_bob():
    v2 = line_spec_entries(P44, "V2_LINE_SPEC")
    resolved = resolve(v2, src("mei_copy", "nora_copy", "alice_copy", "bob_copy"))
    assert resolved == CANON_44_V2
    positions = [resolved.index(t) for t in (MEI, NORA, ALICE, BOB)]
    assert positions == sorted(positions)


def test_44_canonical_fixture_passes_exact_bytes():
    sources = src("mei_copy", "nora_copy", "alice_copy", "bob_copy")
    lines = e44.DeltaChatRouteHandoffStateEvaluator._resolve_line_spec(
        list(e44.V1_LINE_SPEC), sources
    )
    assert lines == CANON_44_V1
    raw = e44.DeltaChatRouteHandoffStateEvaluator._expected_bytes(lines)
    assert raw == "\n".join(CANON_44_V1).encode("utf-8")
    assert not raw.endswith(b"\n")
    assert raw.count(b"\n") == len(CANON_44_V1) - 1
    assert b"\r" not in raw
    assert e44.DeltaChatRouteHandoffStateEvaluator._logical_lines(raw) == CANON_44_V1
    lines2 = e44.DeltaChatRouteHandoffStateEvaluator._resolve_line_spec(
        list(e44.V2_LINE_SPEC), sources
    )
    assert lines2 == CANON_44_V2
    raw2 = e44.DeltaChatRouteHandoffStateEvaluator._expected_bytes(lines2)
    assert raw2.startswith(raw + b"\n")  # v1 is the exact prefix of v2
    assert hashlib.sha256(raw).digest() != hashlib.sha256(raw2).digest()


def test_44_init_baseline_state_stays_fail():
    cls = e44.DeltaChatRouteHandoffStateEvaluator
    assert cls._resolve_line_spec(list(e44.V1_LINE_SPEC), {}) is None
    assert cls._logical_lines(b"") != CANON_44_V1
    assert cls._logical_lines(b"") != CANON_44_V2


def test_44_wrong_source_order_missing_and_attachment_fail():
    cls = e44.DeltaChatRouteHandoffStateEvaluator
    sources = src("mei_copy", "nora_copy", "alice_copy", "bob_copy")
    good = cls._expected_bytes(
        cls._resolve_line_spec(list(e44.V2_LINE_SPEC), sources)
    )
    # Wrong source: Alice text pasted where Mei belongs.
    bad_sources = dict(sources, mei_copy={"text": ALICE})
    bad = cls._expected_bytes(
        cls._resolve_line_spec(list(e44.V2_LINE_SPEC), bad_sources)
    )
    assert bad != good
    # Wrong order: Nora label before the Nora source (the old trace order).
    reordered = list(CANON_44_V1)
    reordered[4], reordered[5] = reordered[5], reordered[4]
    assert "\n".join(reordered).encode("utf-8") != cls._expected_bytes(
        cls._resolve_line_spec(list(e44.V1_LINE_SPEC), sources)
    )
    # Missing line.
    assert "\n".join(CANON_44_V1[1:]).encode("utf-8") != cls._expected_bytes(
        cls._resolve_line_spec(list(e44.V1_LINE_SPEC), sources)
    )
    # Wrong attachment: v1 bytes are not the v2 revision; trailing LF differs.
    v1_raw = cls._expected_bytes(
        cls._resolve_line_spec(list(e44.V1_LINE_SPEC), sources)
    )
    assert v1_raw != good
    assert good + b"\n" != good
    assert cls._logical_lines(good + b"\n") != CANON_44_V2
    # Old defect: filename title prepended is strict wrong content here.
    titled = ("Handoff Log 0728\n" + "\n".join(CANON_44_V1)).encode("utf-8")
    assert cls._logical_lines(titled) != CANON_44_V1


# ---------------------------------------------------------------------------
# 4_3 launch checklist: 6/18 plus exactly two attachments and one forward
# ---------------------------------------------------------------------------

def test_43_note_totals_six_and_eighteen():
    v1 = line_spec_entries(P43, "V1_LINE_SPEC")
    v2 = line_spec_entries(P43, "V2_LINE_SPEC")
    assert len(v1) == 6
    assert len(v2) == 18
    resolved = resolve(v2, src("bob_copy", "mei_copy", "nora_copy"))
    assert resolved == CANON_43_V2


def test_43_saved_outputs_require_three_v1_v2_forward():
    text = P43.read_text(encoding="utf-8")
    assert "exactly_three_outputs" in text
    assert "len(ordered_rows) == 3" in text
    doc = yaml.safe_load(
        (TASKS / "deltachat_launch_checklist_saved_messages_4_3.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert "exactly three new items" in doc["instruction"]
    assert "exactly two new items" not in doc["instruction"]
    assert "readiness-draft attachment" in doc["instruction"]


def test_43_canonical_fixture_passes():
    sources = src("bob_copy", "mei_copy", "nora_copy")
    cls = e43.DeltaChatLaunchChecklistStateEvaluator
    v1 = cls._resolve_line_spec(list(e43.V1_LINE_SPEC), sources)
    v2 = cls._resolve_line_spec(list(e43.V2_LINE_SPEC), sources)
    assert v1 == CANON_43_V1
    assert v2 == CANON_43_V2
    assert cls._logical_lines("\n".join(v1)) == CANON_43_V1
    assert cls._logical_lines("\n".join(v2)) == CANON_43_V2
    # Explicit app-managed title prefixes normalize; wrong titles do not.
    assert cls._logical_lines("Launch Gate 0728# Launch gate\nReadiness draft") == [
        "# Launch gate", "Readiness draft",
    ]
    assert cls._logical_lines("Wrong Title# Launch gate\nReadiness draft") != [
        "# Launch gate", "Readiness draft",
    ]


def test_43_init_baseline_state_stays_fail():
    cls = e43.DeltaChatLaunchChecklistStateEvaluator
    assert cls._resolve_line_spec(list(e43.V1_LINE_SPEC), {}) is None
    assert cls._logical_lines("") != CANON_43_V1
    assert cls._logical_lines("") != CANON_43_V2


def test_43_wrong_source_order_missing_and_attachment_fail():
    cls = e43.DeltaChatLaunchChecklistStateEvaluator
    sources = src("bob_copy", "mei_copy", "nora_copy")
    good = "\n".join(
        cls._resolve_line_spec(list(e43.V2_LINE_SPEC), sources)
    ).encode("utf-8")
    bad_sources = dict(sources, mei_copy={"text": BOB})
    bad = "\n".join(
        cls._resolve_line_spec(list(e43.V2_LINE_SPEC), bad_sources)
    ).encode("utf-8")
    assert bad != good
    reordered = list(CANON_43_V2)
    reordered[2], reordered[7] = reordered[7], reordered[2]
    assert "\n".join(reordered).encode("utf-8") != good
    assert "\n".join(CANON_43_V2[:-1]).encode("utf-8") != good
    v1_raw = "\n".join(
        cls._resolve_line_spec(list(e43.V1_LINE_SPEC), sources)
    ).encode("utf-8")
    assert v1_raw != good  # readiness draft alone is not the final revision
    assert hashlib.sha256(good + b"\n").digest() != hashlib.sha256(good).digest()


# ---------------------------------------------------------------------------
# 4_2 route approval: content-only 13/2 with explicit title normalizer
# ---------------------------------------------------------------------------

def test_42_first_note_is_thirteen_content_lines():
    spec = line_spec_entries(P42, "FIRST_NOTE_LINE_SPEC")
    assert len(spec) == 13
    assert spec[0] == ("literal", "# Route gate")
    resolved = resolve(spec, src("mei", "alice", "bob", "nora"))
    assert resolved == CANON_42_FIRST


def test_42_second_note_is_two_content_lines():
    spec = line_spec_entries(P42, "SECOND_NOTE_LINES")
    assert list(spec) == CANON_42_SECOND


def test_42_title_prefixes_normalize_explicitly_only():
    cls = e42.DeltaChatRouteApprovalStateEvaluator
    body = "\n".join(CANON_42_FIRST).encode("utf-8")
    assert cls._logical_lines(body) == CANON_42_FIRST
    for prefix in (b"Route Gate 0728", b"Route Gate 0728\n"):
        assert cls._logical_lines(prefix + body) == CANON_42_FIRST
    # An arbitrary wrong prefix is never trimmed: strict wrong content FAILs.
    assert cls._logical_lines(b"Other Title" + body) != CANON_42_FIRST
    second = "\n".join(CANON_42_SECOND).encode("utf-8")
    assert cls._logical_lines(b"Route Followup 28" + second) == CANON_42_SECOND
    assert cls._logical_lines(b"Route Followup 28\n" + second) == CANON_42_SECOND


def test_42_canonical_fixture_passes_exact_bytes():
    sources = src("mei", "alice", "bob", "nora")
    cls = e42.DeltaChatRouteApprovalStateEvaluator
    lines = cls._resolve_line_spec(list(e42.FIRST_NOTE_LINE_SPEC), sources)
    assert lines == CANON_42_FIRST
    raw = cls._expected_bytes(lines)
    assert raw == "\n".join(CANON_42_FIRST).encode("utf-8")
    assert not raw.endswith(b"\n")
    assert raw.count(b"\n") == 12
    assert b"\r" not in raw
    assert cls._logical_lines(raw) == CANON_42_FIRST
    raw2 = cls._expected_bytes(list(e42.SECOND_NOTE_LINES))
    assert raw2 == b"# Route follow-up\nApproved by Mei"
    assert cls._logical_lines(raw2) == CANON_42_SECOND


def test_42_init_baseline_state_stays_fail():
    cls = e42.DeltaChatRouteApprovalStateEvaluator
    assert cls._resolve_line_spec(list(e42.FIRST_NOTE_LINE_SPEC), {}) is None
    assert cls._logical_lines(b"") != CANON_42_FIRST
    assert cls._logical_lines(b"") != CANON_42_SECOND


def test_42_wrong_source_order_missing_and_attachment_fail():
    cls = e42.DeltaChatRouteApprovalStateEvaluator
    sources = src("mei", "alice", "bob", "nora")
    good = cls._expected_bytes(
        cls._resolve_line_spec(list(e42.FIRST_NOTE_LINE_SPEC), sources)
    )
    bad_sources = dict(sources, bob={"text": MEI})
    assert cls._expected_bytes(
        cls._resolve_line_spec(list(e42.FIRST_NOTE_LINE_SPEC), bad_sources)
    ) != good
    reordered = list(CANON_42_FIRST)
    reordered[3], reordered[5] = reordered[5], reordered[3]
    assert "\n".join(reordered).encode("utf-8") != good
    assert "\n".join(CANON_42_FIRST[:-1]).encode("utf-8") != good
    # Old defect: merged title+heading literal is not the canonical bytes.
    assert b"Route Gate 0728# Route gate\nStatus pending" != b"# Route gate\nStatus pending"
    assert good + b"\n" != good
    assert cls._logical_lines(good + b"\n") != CANON_42_FIRST


# ---------------------------------------------------------------------------
# 4_1 mobile brief: content-only 7/7 with explicit title normalizer
# ---------------------------------------------------------------------------

def test_41_notes_are_seven_content_lines_each():
    first = line_spec_entries(P41, "FIRST_NOTE_LINE_SPEC")
    second = line_spec_entries(P41, "SECOND_NOTE_LINE_SPEC")
    assert len(first) == 7
    assert len(second) == 7
    assert first[0] == ("literal", "# Mobile brief")
    assert second[0] == ("literal", "# Mobile risks")
    all_sources = src("nora_copy", "alice_copy", "bob_copy", "mei_copy")
    assert resolve(first, all_sources) == CANON_41_FIRST
    assert resolve(second, all_sources) == CANON_41_SECOND


def test_41_title_prefixes_normalize_explicitly_only():
    cls = e41.DeltaChatMobileQABriefStateEvaluator
    body = "\n".join(CANON_41_FIRST).encode("utf-8")
    assert cls._logical_lines(body) == CANON_41_FIRST
    assert cls._logical_lines(b"Mobile Brief 0728" + body) == CANON_41_FIRST
    assert cls._logical_lines(b"Mobile Brief 0728\n" + body) == CANON_41_FIRST
    assert cls._logical_lines(b"Other Title" + body) != CANON_41_FIRST
    body2 = "\n".join(CANON_41_SECOND).encode("utf-8")
    assert cls._logical_lines(b"Mobile Risks 0728" + body2) == CANON_41_SECOND


def test_41_canonical_fixtures_pass():
    sources = src("nora_copy", "alice_copy", "bob_copy", "mei_copy")
    cls = e41.DeltaChatMobileQABriefStateEvaluator
    first = cls._resolve_line_spec(list(e41.FIRST_NOTE_LINE_SPEC), sources)
    second = cls._resolve_line_spec(list(e41.SECOND_NOTE_LINE_SPEC), sources)
    assert first == CANON_41_FIRST
    assert second == CANON_41_SECOND
    raw1 = cls._expected_bytes(first)
    raw2 = cls._expected_bytes(second)
    assert raw1 == "\n".join(CANON_41_FIRST).encode("utf-8")
    assert raw2 == "\n".join(CANON_41_SECOND).encode("utf-8")
    assert cls._logical_lines(raw1) == CANON_41_FIRST
    assert cls._logical_lines(raw2) == CANON_41_SECOND


def test_41_init_baseline_state_stays_fail():
    cls = e41.DeltaChatMobileQABriefStateEvaluator
    assert cls._resolve_line_spec(list(e41.FIRST_NOTE_LINE_SPEC), {}) is None
    assert cls._logical_lines(b"") != CANON_41_FIRST
    assert cls._logical_lines(b"") != CANON_41_SECOND


def test_41_wrong_source_order_missing_and_attachment_fail():
    cls = e41.DeltaChatMobileQABriefStateEvaluator
    sources = src("nora_copy", "alice_copy", "bob_copy", "mei_copy")
    good1 = cls._expected_bytes(
        cls._resolve_line_spec(list(e41.FIRST_NOTE_LINE_SPEC), sources)
    )
    good2 = cls._expected_bytes(
        cls._resolve_line_spec(list(e41.SECOND_NOTE_LINE_SPEC), sources)
    )
    bad_sources = dict(sources, nora_copy={"text": BOB})
    assert cls._expected_bytes(
        cls._resolve_line_spec(list(e41.FIRST_NOTE_LINE_SPEC), bad_sources)
    ) != good1
    reordered = list(CANON_41_FIRST)
    reordered[1], reordered[5] = reordered[5], reordered[1]
    assert "\n".join(reordered).encode("utf-8") != good1
    assert "\n".join(CANON_41_SECOND[1:]).encode("utf-8") != good2
    assert good1 != good2  # distinct note revisions
    assert cls._logical_lines(good1 + b"\n") != CANON_41_FIRST


# ---------------------------------------------------------------------------
# Cross-task ruleset binding and single-line source rule
# ---------------------------------------------------------------------------

def _task_doc(name: str) -> dict:
    return yaml.safe_load((TASKS / name).read_text(encoding="utf-8"))


def test_ruleset_digests_bound_and_versioned():
    for task_file, module, key in (
        ("deltachat_route_handoff_saved_messages_4_4.yaml", e44, "4_4"),
        ("deltachat_launch_checklist_saved_messages_4_3.yaml", e43, "4_3"),
        ("deltachat_route_approval_saved_messages_4_2.yaml", e42, "4_2"),
        ("deltachat_mobile_qa_brief_saved_messages_4_1.yaml", e41, "4_1"),
    ):
        doc = _task_doc(task_file)
        assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == module.RULESET_SHA256
        assert module.RULESET_SHA256 != OLD_DIGESTS[key]
        assert module.RULESET_SPEC["schema_version"] == "2.1"
        assert module.RULESET_SPEC["supersedes_ruleset_sha256"] == OLD_DIGESTS[key]


def test_instruction_hashes_match_edited_instructions():
    for name in (
        "deltachat_route_handoff_saved_messages_4_4.yaml",
        "deltachat_launch_checklist_saved_messages_4_3.yaml",
        "deltachat_route_approval_saved_messages_4_2.yaml",
        "deltachat_mobile_qa_brief_saved_messages_4_1.yaml",
    ):
        doc = _task_doc(name)
        digest = doc["metadata"].get("instruction_sha256")
        if digest is not None:
            assert digest == hashlib.sha256(
                doc["instruction"].encode("utf-8")
            ).hexdigest()


def test_42_binding_drops_historical_harness_pins():
    doc = _task_doc("deltachat_route_approval_saved_messages_4_2.yaml")
    params = doc["evaluation"]["params"]
    for stale in (
        "source_simulator_name", "ios_device_profile",
        "delta_chat_short_version", "delta_chat_build_version",
        "fsnotes_short_version", "fsnotes_build_version",
    ):
        assert stale not in params
    assert "historical_binding_diagnostic" in e42.RULESET_SPEC
    assert "stable_binding" not in e42.RULESET_SPEC


def test_each_source_occupies_exactly_one_logical_line():
    for text in (MEI, NORA, ALICE, BOB):
        assert "\n" not in text
    raw = "\n".join(CANON_44_V2).encode("utf-8")
    assert not raw.endswith(b"\n")
    assert len(raw.decode("utf-8").split("\n")) == len(CANON_44_V2)
