from __future__ import annotations

from core.llm.providers.macos_script_oracle_adapter import MacOSScriptOracleAdapter


def test_macos_script_oracle_code_adapter_text_wraps_bash_action_as_python() -> None:
    text = MacOSScriptOracleAdapter._code_adapter_text(
        {
            "type": "run_bash_script",
            "script": "echo ok",
            "timeout": 5,
            "assistant_text": "Run the smoke script.",
        }
    )

    assert text.startswith("Run the smoke script.\n```python\n")
    assert "subprocess.run(['/bin/bash', path]" in text
    assert "echo ok" in text
