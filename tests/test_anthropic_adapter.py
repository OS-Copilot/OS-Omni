from __future__ import annotations

import json

import httpx
import pytest

from core.llm.errors import LLMClientError, LLMErrorCode
from core.llm.providers.anthropic_adapter import DEFAULT_MAX_TOKENS, AnthropicAdapter
from core.llm.providers.base import ProviderRequest
from core.llm.types import ImagePart, Message, ModelSpec, ProviderCredentials, TextPart

MESSAGE_REPLY = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "Click Save.\n```python\npyautogui.click(1, 2)\n```"},
    ],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 120, "output_tokens": 340},
}


def _request(tmp_path, metadata: dict, *, max_output_tokens=None) -> ProviderRequest:
    image = tmp_path / "step.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    parameters = {} if max_output_tokens is None else {"max_output_tokens": max_output_tokens}
    return ProviderRequest(
        model_spec=ModelSpec(
            model_id="claude_opus_5_5_high",
            provider="anthropic",
            model_name="claude-opus-5-5",
            api_key_env="OPUS55_API_KEY",
            metadata=metadata,
        ),
        credentials=ProviderCredentials("test-key", "https://gateway.test"),
        messages=[
            Message("system", [TextPart("Task: rewrite app.ini.")]),
            Message("user", [TextPart("Step 1 screenshot."), ImagePart(str(image))]),
            Message("assistant", [TextPart("pyautogui.click(1, 2)")]),
            Message("user", [TextPart("Step 2 screenshot.")]),
        ],
        response_mode="json_text",
        parameters=parameters,
        timeout_seconds=180,
    )


def _adapter(handler) -> AnthropicAdapter:
    return AnthropicAdapter(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_request_uses_messages_api_with_effort_and_returns_text(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=MESSAGE_REPLY)

    result = _adapter(handler).invoke(_request(tmp_path, {"effort": "high"}))

    body = seen["body"]
    assert seen["url"] == "https://gateway.test/v1/messages"
    assert seen["api_key"] == "test-key"
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS
    assert body["output_config"] == {"effort": "high"}
    assert body["system"] == "Task: rewrite app.ini."
    assert "thinking" not in body and "temperature" not in body
    assert [message["role"] for message in body["messages"]] == ["user", "assistant", "user"]
    image_block = body["messages"][0]["content"][1]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/jpeg"

    assert result.text == MESSAGE_REPLY["content"][1]["text"]
    assert result.finish_reason == "end_turn"
    assert result.usage["output_tokens"] == 340
    assert result.assistant_message.parts[0].text == result.text


def test_without_effort_no_output_config_and_max_tokens_override(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=MESSAGE_REPLY)

    _adapter(handler).invoke(_request(tmp_path, {}, max_output_tokens=4096))

    assert "output_config" not in seen["body"]
    assert seen["body"]["max_tokens"] == 4096


def test_http_error_becomes_provider_request_failed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}})

    with pytest.raises(LLMClientError) as excinfo:
        _adapter(handler).invoke(_request(tmp_path, {"effort": "high"}))

    assert excinfo.value.code == LLMErrorCode.PROVIDER_REQUEST_FAILED
    assert excinfo.value.details["status_code"] == 400


def test_tool_calling_mode_is_rejected(tmp_path):
    request = _request(tmp_path, {"effort": "high"})
    request.response_mode = "tool_calling"

    with pytest.raises(LLMClientError) as excinfo:
        AnthropicAdapter().invoke(request)

    assert excinfo.value.code == LLMErrorCode.MODE_NOT_SUPPORTED
