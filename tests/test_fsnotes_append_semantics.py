from pathlib import Path

import pytest

from platforms.ios.fsnotes_store import FSNotesStore


SECTION = '## Decisions\n- Send recap by noon\n- Confirm postmortem room\n'
ORIGINAL = 'Launch retrospective notes.\n\n- Review shipping delays\n- Collect support themes\n'


@pytest.mark.parametrize('content, expected', [
    (ORIGINAL + '\n' + SECTION, True),
    ((ORIGINAL + '\n' + SECTION).replace('\n', '\r\n'), True),
    (SECTION + ORIGINAL, False),
    (ORIGINAL + '\n## Decisions\n- Confirm postmortem room\n- Send recap by noon\n', False),
    (ORIGINAL + '\n' + SECTION + 'Unrequested footer\n', False),
    (ORIGINAL + '\n' + SECTION.replace('## Decisions', 'wrong## Decisions'), False),
])
def test_append_section_order_and_position(tmp_path: Path, content: str, expected: bool):
    store = FSNotesStore(notes_root_path=tmp_path)
    path = store.notes_root_path / 'Launch Retrospective Final.md'
    path.write_text(content)
    note = store._build_note_record(path)
    assert store.note_matches_expectation(note, {'content_ends_with': SECTION}) is expected


def test_legacy_contains_behavior_retained(tmp_path: Path):
    store = FSNotesStore(notes_root_path=tmp_path)
    path = store.notes_root_path / 'Legacy.md'
    path.write_text(SECTION + ORIGINAL)
    assert store.note_matches_expectation(store._build_note_record(path), {'content_contains': ['## Decisions']})
