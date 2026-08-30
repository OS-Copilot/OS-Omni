from evaluators.macos.textedit import _normalize_text


def test_textedit_normalize_trims_trailing_newline():
    assert _normalize_text("Follow-up:\n") == "Follow-up:"


def test_textedit_normalize_trims_line_end_spaces():
    assert _normalize_text("Owner: Riley   \nStatus: ready\t\n") == "Owner: Riley\nStatus: ready"


def test_textedit_normalize_preserves_line_structure():
    assert _normalize_text("Owner: Riley\nStatus: ready") != _normalize_text("Owner: Riley Status: ready")
