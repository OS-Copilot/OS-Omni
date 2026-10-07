import ast

import pytest

from platforms.linux.agent.planners.qwen_computer_use_planner import parse_qwen_call, qwen_action


def test_native_xml_coordinates_map_to_actual_screen():
    call = parse_qwen_call("""Action: Open the folder.
<tool_call><function=computer_use>
<parameter=action>double_click</parameter>
<parameter=coordinate>[828,385]</parameter>
</function></tool_call>""")
    assert "doubleClick(1590, 416)" in qwen_action(call, 1920, 1080)["code"]
    assert "doubleClick(1060, 308)" in qwen_action(call, 1280, 800)["code"]


@pytest.mark.parametrize("coordinate", [[1001, 0], [-1, 500], [float("nan"), 0], [float("inf"), 0]])
def test_invalid_coordinates_never_produce_input(coordinate):
    with pytest.raises(ValueError):
        qwen_action({"action": "left_click", "coordinate": coordinate}, 1920, 1080)


def test_screen_edge_is_clamped_to_last_pixel():
    assert "click(1919, 1079)" in qwen_action({"action": "left_click", "coordinate": [1000, 1000]}, 1920, 1080)["code"]


def test_typed_text_is_data_and_cannot_add_python_statements():
    text = "'); __import__('os').system('unexpected'); #\nnext line"
    action = qwen_action({"action": "type", "text": text}, 1920, 1080)
    syntax = ast.parse(action["code"])
    assert len(syntax.body) == 2
    assert syntax.body[1].value.func.attr == "write"
    assert syntax.body[1].value.args[0].value == text


def test_key_chord_and_modified_click_release_modifiers():
    code = qwen_action({"action": "key", "keys": ["Control_L", "C"]}, 1920, 1080)["code"]
    assert "hotkey('ctrl', 'c')" in code
    code = qwen_action({"action": "left_click", "coordinate": [500, 500], "text": "ctrl+shift"}, 1920, 1080)["code"]
    assert code.splitlines()[-2:] == ["pyautogui.keyUp('shift')", "pyautogui.keyUp('ctrl')"]


@pytest.mark.parametrize("raw", ['["ctrl", "s"]', "[ctrl, s]", "['ctrl', 's']", "ctrl+s"])
def test_key_chord_accepts_the_schema_example_spelling(raw):
    # The tool schema itself shows the chord as [ctrl, c], so models copy that form.
    call = "<tool_call>\n<function=computer_use>\n<parameter=action>key</parameter>\n" \
        f"<parameter=keys>{raw}</parameter>\n</function>\n</tool_call>"
    params = parse_qwen_call(call)
    assert params["keys"] == ["ctrl", "s"]
    assert "hotkey('ctrl', 's')" in qwen_action(params, 1920, 1080)["code"]


@pytest.mark.parametrize("raw", ["[]", "[ , ]", '{"a": 1}'])
def test_empty_or_malformed_key_chords_are_rejected(raw):
    call = "<tool_call><function=computer_use><parameter=action>key</parameter>" \
        f"<parameter=keys>{raw}</parameter></function></tool_call>"
    with pytest.raises(ValueError):
        parse_qwen_call(call)


def test_termination_and_malformed_tool_calls():
    assert qwen_action({"action": "terminate", "status": "failure"}, 1920, 1080)["type"] == "fail"
    with pytest.raises(ValueError):
        qwen_action({"action": "terminate", "status": "maybe"}, 1920, 1080)
    with pytest.raises(ValueError):
        parse_qwen_call("<tool_call><function=execute_shell>pwd</function></tool_call>")
    with pytest.raises(ValueError):
        parse_qwen_call("<tool_call>one</tool_call><tool_call>two</tool_call>")


def test_less_than_is_typed_with_shift_comma():
    # pyautogui maps "<" to the pc105 extra key, which types ">" on the guest keymap.
    code = qwen_action({"action": "type", "text": "<h1>a</h1>"}, 1920, 1080)["code"]
    assert code.splitlines()[1:] == [
        "pyautogui.hotkey('shift', ',')",
        "pyautogui.write('h1>a', interval=0.02)",
        "pyautogui.hotkey('shift', ',')",
        "pyautogui.write('/h1>', interval=0.02)",
    ]


def test_wait_time_wrapped_in_a_list_is_accepted():
    assert qwen_action({"action": "wait", "time": "[2.0]"}, 1920, 1080) == {"type": "wait", "ms": 2000}
