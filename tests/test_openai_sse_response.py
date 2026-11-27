from __future__ import annotations

import json

import httpx
import pytest

from core.llm.errors import LLMClientError, LLMErrorCode
from core.llm.providers.openai_adapter import OpenAIAdapter
from core.llm.providers.utils import aggregate_chat_completion_sse


def _sse(*chunks: dict) -> str:
    lines = [f"data: {json.dumps(chunk)}" for chunk in chunks]
    return "\n\n".join(lines + ["data: [DONE]"]) + "\n\n"


def _chunk(delta: dict, finish_reason: str | None = None, **extra) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "kimi-k3",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        **extra,
    }


STREAM = _sse(
    _chunk({"role": "assistant", "reasoning_content": "Look at "}),
    _chunk({"reasoning_content": "the sidebar."}),
    _chunk({"content": "Click it.\n```python\n"}),
    _chunk({"content": "pyautogui.click(10, 20)\n```"}),
    _chunk({}, finish_reason="stop", usage={"prompt_tokens": 5, "completion_tokens": 7}),
)


def _adapter_returning(body: str, content_type: str) -> OpenAIAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    return OpenAIAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_aggregate_rebuilds_content_reasoning_and_usage():
    data = aggregate_chat_completion_sse(STREAM)

    assert data["object"] == "chat.completion"
    assert data["model"] == "kimi-k3"
    message = data["choices"][0]["message"]
    assert message["content"] == "Click it.\n```python\npyautogui.click(10, 20)\n```"
    assert message["reasoning_content"] == "Look at the sidebar."
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"] == {"prompt_tokens": 5, "completion_tokens": 7}


def test_aggregate_joins_streamed_tool_call_arguments():
    body = _sse(
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "click", "arguments": '{"x": 1'}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": ', "y": 2}'}}]}),
        _chunk({}, finish_reason="tool_calls"),
    )

    message = aggregate_chat_completion_sse(body)["choices"][0]["message"]

    assert message["tool_calls"] == [
        {"type": "function", "id": "call_1", "function": {"name": "click", "arguments": '{"x": 1, "y": 2}'}}
    ]


@pytest.mark.parametrize("body", ["", "<html>Bad Gateway</html>", "data: not-json\n\n", 'data: {"type": "ping"}\n\n'])
def test_aggregate_returns_none_for_non_chat_streams(body):
    assert aggregate_chat_completion_sse(body) is None


def test_adapter_accepts_unrequested_sse_reply():
    adapter = _adapter_returning(STREAM, "text/event-stream")

    data = adapter._request_json("https://example.test/v1/chat/completions", "key", {"model": "kimi-k3"}, 5)
    result = adapter._build_chat_completions_result(data)

    assert result.text == "Click it.\n```python\npyautogui.click(10, 20)\n```"
    assert result.finish_reason == "stop"


def test_adapter_still_rejects_other_non_json_replies():
    adapter = _adapter_returning("<html>Bad Gateway</html>", "text/html")
    adapter.transient_retry_base_delay_seconds = 0

    with pytest.raises(LLMClientError) as excinfo:
        adapter._request_json("https://example.test/v1/chat/completions", "key", {"model": "kimi-k3"}, 5)

    assert excinfo.value.code == LLMErrorCode.INVALID_PROVIDER_RESPONSE


@pytest.mark.parametrize('body', [
    STREAM.rsplit('data: [DONE]', 1)[0],
    ': keepalive\n\n' + STREAM.rsplit('data: [DONE]', 1)[0],
    _sse(_chunk({'content': 'Incomplete action'})),
])
def test_requested_stream_rejects_missing_terminal_event(body):
    adapter = _adapter_returning(body, 'text/event-stream')
    adapter.transient_retry_attempts = 0
    with pytest.raises(LLMClientError) as excinfo:
        adapter._request_json('https://example.test/v1/chat/completions', 'key', {'model': 'qwen3.8-max', 'stream': True}, 5)
    assert excinfo.value.code == LLMErrorCode.INVALID_PROVIDER_RESPONSE


def test_requested_stream_preserves_complete_text_and_usage():
    adapter = _adapter_returning(STREAM, 'text/event-stream')
    data = adapter._request_json('https://example.test/v1/chat/completions', 'key', {'model': 'qwen3.8-max', 'stream': True}, 5)
    assert data['choices'][0]['finish_reason'] == 'stop'
    assert data['usage']['completion_tokens'] == 7


def test_requested_stream_accepts_done_without_optional_space():
    body = STREAM.replace('data: [DONE]', 'data:[DONE]')
    adapter = _adapter_returning(body, 'Text/Event-Stream')
    data = adapter._request_json('https://example.test/v1/chat/completions', 'key',
                                 {'model': 'qwen3.8-max', 'stream': True}, 5)
    assert data['choices'][0]['finish_reason'] == 'stop'


def test_explicit_no_thinking_rejects_reasoning_in_raw_response():
    from core.llm.providers.base import ProviderRequest
    from core.llm.types import Message, ModelSpec, ProviderCredentials, TextPart

    adapter = _adapter_returning(STREAM, 'text/event-stream')
    request = ProviderRequest(
        model_spec=ModelSpec('qwen_test', 'openai', 'qwen3.8-max', 'TEST_KEY',
                             metadata={'enable_thinking': False, 'stream': True}),
        credentials=ProviderCredentials('test-key', 'https://example.test/v1'),
        messages=[Message('user', [TextPart('Return OK')])], response_mode='json_text',
        parameters={'reasoning_effort': 'none', 'max_output_tokens': 16384},
    )
    with pytest.raises(LLMClientError) as excinfo:
        adapter.invoke(request)
    assert excinfo.value.code == LLMErrorCode.INVALID_PROVIDER_RESPONSE
    assert 'reasoning_content' in excinfo.value.message


def test_native_thinking_uses_flat_effort_without_generic_summary():
    from core.llm.providers.base import ProviderRequest
    from core.llm.types import Message, ModelSpec, ProviderCredentials, TextPart

    request = ProviderRequest(
        model_spec=ModelSpec('qwen_low', 'openai', 'qwen3.8-max', 'TEST_KEY',
                             metadata={'enable_thinking': True, 'stream': True}),
        credentials=ProviderCredentials('test-key', 'https://example.test/v1'),
        messages=[Message('user', [TextPart('Return OK')])], response_mode='json_text',
        parameters={'reasoning_effort': 'low', 'max_output_tokens': 16384},
    )
    adapter = _adapter_returning(STREAM, 'text/event-stream')
    payload = adapter._build_chat_completions_payload(request)
    assert payload['enable_thinking'] is True
    assert payload['reasoning_effort'] == 'low'
    assert 'reasoning' not in payload
    assert adapter.invoke(request).text
