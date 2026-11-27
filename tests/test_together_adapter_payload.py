from core.llm.providers.together_adapter import TogetherAdapter
from core.llm.providers.base import ProviderRequest
from core.llm.types import Message, ModelSpec, ProviderCredentials, TextPart


def _payload(metadata=None):
    spec = ModelSpec(
        model_id="together_test",
        provider="together",
        model_name="org/model",
        api_key_env="TOGETHER_API_KEY",
        base_url="https://api.together.xyz/v1",
        metadata=dict(metadata or {}),
    )
    request = ProviderRequest(
        model_spec=spec,
        credentials=ProviderCredentials(api_key="k", base_url=spec.base_url),
        messages=[Message(role="user", parts=[TextPart(text="hi")])],
        response_mode="json_text",
    )
    return TogetherAdapter(client=object())._build_payload(request)


def test_extra_body_fields_are_sent_at_top_level():
    payload = _payload()

    assert "extra_body" not in payload
    assert payload["top_k"] == 20
    assert payload["min_p"] == 0.0
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}


def test_enable_thinking_false_reaches_chat_template_kwargs():
    payload = _payload({"enable_thinking": False})

    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.8


def test_metadata_extra_body_is_merged_without_overriding_explicit_keys():
    payload = _payload({"extra_body": {"top_k": 5, "model": "other", "chat_template_kwargs": {"x": 1}}})

    assert payload["top_k"] == 5
    assert payload["model"] == "org/model"
    assert payload["chat_template_kwargs"] == {"enable_thinking": True, "x": 1}
