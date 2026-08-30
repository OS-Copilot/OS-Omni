from evaluators.linux.deltachat import normalize_message_text as normalize_linux_message_text
from evaluators.macos.deltachat import normalize_message_text as normalize_macos_message_text


def _normalizers():
    return (normalize_macos_message_text, normalize_linux_message_text)


def test_normalize_message_text_trims_trailing_newline():
    for normalize_message_text in _normalizers():
        assert normalize_message_text("Confirmed for 3 PM in Cedar-3.\n") == "Confirmed for 3 PM in Cedar-3."


def test_normalize_message_text_collapses_whitespace_runs():
    for normalize_message_text in _normalizers():
        assert normalize_message_text("Please  own\tticket SR-88\n") == "Please own ticket SR-88"


def test_normalize_message_text_preserves_meaningful_text_difference():
    for normalize_message_text in _normalizers():
        assert normalize_message_text("Confirmed for 3 PM") != normalize_message_text("Confirmed for 4 PM")
