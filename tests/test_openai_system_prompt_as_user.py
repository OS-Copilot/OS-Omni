from __future__ import annotations

from core.llm.providers.base import ProviderRequest
from core.llm.providers.openai_adapter import OpenAIAdapter
from core.llm.providers.utils import fold_system_into_first_user
from core.llm.types import Message, ModelSpec, ProviderCredentials, TextPart


def _request(metadata: dict) -> ProviderRequest:
    return ProviderRequest(
        model_spec=ModelSpec(
            model_id="openlux_kimi_k3",
            provider="openai",
            model_name="kimi-k3",
            api_key_env="OPENLUX_KIMI_API_KEY",
            metadata=metadata,
        ),
        credentials=ProviderCredentials("test-key", "https://example.test/v1"),
        messages=[
            Message("system", [TextPart("Task: rewrite app.ini.")]),
            Message("user", [TextPart("Step 1 screenshot.")]),
            Message("assistant", [TextPart("pyautogui.click(1, 2)")]),
            Message("user", [TextPart("Step 2 screenshot.")]),
        ],
        response_mode="json_text",
    )


def test_flag_moves_system_prompt_into_first_user_message():
    payload = OpenAIAdapter()._build_chat_completions_payload(
        _request({"reasoning_effort": "none", "system_prompt_as_user": True})
    )

    assert [message["role"] for message in payload["messages"]] == ["user", "assistant", "user"]
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "Task: rewrite app.ini."},
        {"type": "text", "text": "Step 1 screenshot."},
    ]
    assert payload["messages"][2]["content"] == [{"type": "text", "text": "Step 2 screenshot."}]


def test_without_flag_system_message_is_sent_as_is():
    payload = OpenAIAdapter()._build_chat_completions_payload(_request({"reasoning_effort": "none"}))

    assert [message["role"] for message in payload["messages"]] == ["system", "user", "assistant", "user"]


def test_fold_without_user_message_turns_system_into_user():
    messages = [{"role": "system", "content": [{"type": "text", "text": "Task."}]}]

    assert fold_system_into_first_user(messages) == [{"role": "user", "content": [{"type": "text", "text": "Task."}]}]


def test_fold_without_system_message_is_unchanged():
    messages = [{"role": "user", "content": [{"type": "text", "text": "Hi."}]}]

    assert fold_system_into_first_user(messages) is messages
