from platforms.macos.host.agent.planners.reflection_pyautogui_planner import (
    _normalize_osworld_code,
    build_python_action,
)


def test_top_level_semicolons_are_split_into_lines():
    code = "pyautogui.click(1, 2); time.sleep(0.5)"

    assert _normalize_osworld_code(code) == "pyautogui.click(1, 2)\ntime.sleep(0.5)"


def test_semicolon_inside_indented_block_keeps_original_code():
    code = "for i in range(3):\n    pyautogui.press('down'); time.sleep(0.1)\npyautogui.press('enter')"

    normalized = _normalize_osworld_code(code)

    assert normalized == code
    compile(normalized, "<action>", "exec")


def test_semicolon_inside_nested_blocks_keeps_original_code():
    code = "for i in range(2):\n    for j in range(2):\n        a(); b()\n    c(); d()\ne()"

    assert _normalize_osworld_code(code) == code


def test_inconsistent_dedent_is_passed_through_to_runtime():
    code = "if True:\n        a()\n    b()"

    assert _normalize_osworld_code(code) == code


def test_build_python_action_accepts_semicolon_inside_loop():
    raw = "Move down three rows.\n\n```python\nfor i in range(3):\n    pyautogui.press('down'); time.sleep(0.1)\n```"

    action, ok, _, error = build_python_action(raw)

    assert ok is True
    assert error is None
    assert action["type"] == "python_code"
    assert action["code"] == "for i in range(3):\n    pyautogui.press('down'); time.sleep(0.1)"
