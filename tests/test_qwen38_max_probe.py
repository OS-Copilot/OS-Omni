import hashlib
import json

import httpx
from PIL import Image
import pytest

from core.llm.providers.openai_adapter import OpenAIAdapter
from core.llm.providers.utils import image_path_to_data_url
from core.llm.types import ModelSpec, ProviderCredentials
from tools.windows.probe_qwen38_max import (
    make_cases, restore_images, run_probes, validate_replay,
)


def spec(thinking=True):
    return ModelSpec("test", "openai", "qwen3.8-max", "TEST_KEY",
                     max_output_tokens=16384, metadata={
                         "enable_thinking": thinking, "reasoning_effort": "low" if thinking else "none",
                         "image_jpeg_quality": 85, "stream": True,
                     })


def adapter(handler):
    client = OpenAIAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.transient_retry_attempts = 0
    return client


def response(reasoning=""):
    return {"model": "qwen3.8-max", "choices": [{
        "message": {"role": "assistant", "content": "OK", "reasoning_content": reasoning},
        "finish_reason": "stop",
    }]}


def test_probe_keeps_text_history_but_only_one_current_image(tmp_path):
    image = tmp_path / "desktop.png"
    Image.new("RGB", (1920, 1080)).save(image)
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["model"] == "qwen3.8-max"
        assert payload["reasoning_effort"] == "low"
        assert payload["enable_thinking"] is True
        assert "reasoning" not in payload
        return httpx.Response(200, json=response("thinking is allowed for low"))

    results = run_probes(adapter(handler), spec(), ProviderCredentials("test-key", "https://example.test/v1"),
                         make_cases("all", image, 0))
    assert all(item["success"] and item["actions_executed"] is False for item in results)
    image_counts = [sum(part["type"] == "image_url" for message in payload["messages"]
                        for part in message["content"]) for payload in calls]
    assert image_counts == [0, 1, 1]
    assert [m["role"] for m in calls[-1]["messages"]] == ["user", "assistant", "user"]
    assert "data:image" not in json.dumps(results)


def test_no_thinking_probe_rejects_hidden_reasoning_and_stops(tmp_path):
    image = tmp_path / "desktop.png"
    Image.new("RGB", (10, 10)).save(image)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response("must not be accepted"))

    results = run_probes(adapter(handler), spec(False), ProviderCredentials("test-key", "https://example.test/v1"),
                         make_cases("all", image, 0))
    assert len(calls) == 1
    assert results[0]["success"] is False
    assert "reasoning_content" in results[0]["error"]


def test_probe_redacts_key_from_provider_error_details():
    secret = "fake-test-credential"
    client = adapter(lambda request: httpx.Response(500, text=secret))
    results = run_probes(client, spec(), ProviderCredentials(secret, "https://example.test/v1"),
                         make_cases("text", None, 0))
    assert results[0]["success"] is False
    assert secret not in json.dumps(results)
    assert "[REDACTED]" in results[0]["details"]


def test_replay_restores_exact_image_digest_without_mutating_evidence(tmp_path):
    image = tmp_path / "screenshot.png"
    Image.new("RGB", (1920, 1080), "blue").save(image)
    uri = image_path_to_data_url(str(image), jpeg_quality=85)
    reference = {"inline_image_sha256": hashlib.sha256(uri.encode()).hexdigest(), "chars": len(uri)}
    original = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": reference}},
    ]}]}
    restored = restore_images(original, tmp_path, 85)
    assert restored["messages"][0]["content"][0]["image_url"]["url"] == uri
    assert original["messages"][0]["content"][0]["image_url"]["url"] == reference


def test_replay_rejects_other_models_before_inference():
    payload = {"model": "some-other-model"}
    with pytest.raises(ValueError, match="model"):
        validate_replay(payload, spec())


def test_replay_truncated_stream_is_an_error():
    model = spec()
    payload = {"model": "qwen3.8-max", "reasoning_effort": "low", "enable_thinking": True,
               "max_completion_tokens": 16384, "stream": True, "messages": []}
    body = 'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
    client = adapter(lambda request: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"}))
    results = run_probes(client, model, ProviderCredentials("test-key", "https://example.test/v1"),
                         [("replay", payload)])
    assert results[0]["success"] is False
    assert "terminal event" in results[0]["error"]


def test_empty_complete_reply_is_not_a_successful_probe():
    data = response()
    data["choices"][0]["message"]["content"] = ""
    client = adapter(lambda request: httpx.Response(200, json=data))
    results = run_probes(client, spec(), ProviderCredentials("test-key", "https://example.test/v1"),
                         make_cases("text", None, 0))
    assert results[0]["success"] is False
