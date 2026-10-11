from pathlib import Path
import json
import yaml
import pytest
from core.llm.providers.openai_adapter import OpenAIAdapter
from core.llm.providers.base import ProviderRequest
from core.llm.types import ModelSpec, ProviderCredentials, Message, TextPart


def request(effort):
    entry = yaml.safe_load((Path(__file__).parents[1]/'configs/models.yaml').read_text())['models']['deepseek_flash']
    return ProviderRequest(model_spec=ModelSpec(model_id='deepseek_flash', **entry), credentials=ProviderCredentials('never-log-test-key','https://api.deepseek.com'), messages=[Message('user',[TextPart('never-log-test-prompt')])], response_mode='json_text', parameters={'reasoning_effort':effort}, timeout_seconds=10)


def test_guard_rejects_thinking_before_network(tmp_path,monkeypatch):
    monkeypatch.setenv('OS_OMNI_DEEPSEEK_REQUEST_AUDIT',str(tmp_path/'audit.jsonl'))
    a=OpenAIAdapter();monkeypatch.setattr(a,'_request_json',lambda *args: pytest.fail('must not request'))
    monkeypatch.setattr(a,'_build_payload',lambda *args,**kw: {'model':'deepseek-flash','reasoning':{'effort':'high'}})
    with pytest.raises(ValueError,match='reasoning.effort=none'):a.invoke(request('high'))


def test_actual_payload_verified_and_audit_contains_no_credentials_or_prompt(tmp_path,monkeypatch):
    p=tmp_path/'audit.jsonl';monkeypatch.setenv('OS_OMNI_DEEPSEEK_REQUEST_AUDIT',str(p));a=OpenAIAdapter()
    def send(url,key,payload,timeout):
        assert payload['model']=='deepseek-flash' and payload['reasoning']['effort']=='none'
        return {'id':'response-id','output':[]}
    monkeypatch.setattr(a,'_request_json',send);monkeypatch.setattr(a,'_build_result',lambda *args,**kw:None);a.invoke(request('none'))
    text=p.read_text();assert 'never-log' not in text
    assert json.loads(text.splitlines()[1])['reasoning_items']==0


def test_actual_ios_system_contract_survives_responses_conversion(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from platforms.ios.agent.prompt_builder import IOSPromptBuilder
    prompt = IOSPromptBuilder(observation_mode='screenshot_only', tool_calling=False).build_system_prompt(task=SimpleNamespace(goal='Neutral GUI interface probe.'))
    req = request('none')
    req.messages.insert(0, Message('system', [TextPart(prompt)]))
    p = tmp_path / 'audit.jsonl'
    monkeypatch.setenv('OS_OMNI_DEEPSEEK_REQUEST_AUDIT', str(p))
    adapter = OpenAIAdapter()
    def send(url, key, payload, timeout):
        assert payload['input'][0]['role'] == 'system'
        assert 'import modules' in payload['input'][0]['content'][0]['text']
        return {'id': 'neutral', 'output': []}
    monkeypatch.setattr(adapter, '_request_json', send)
    monkeypatch.setattr(adapter, '_build_result', lambda *args, **kwargs: None)
    adapter.invoke(req)
    record = json.loads(p.read_text().splitlines()[0])
    assert record['ios_import_prohibition_transmitted'] is True
    assert len(record['system_instruction_sha256']) == 1
    assert prompt not in p.read_text()


def test_ios_planner_session_sends_system_contract_to_actual_adapter(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.llm.llm_client import LLMClientManager
    from platforms.ios.agent.prompt_builder import IOSPromptBuilder
    from platforms.ios.agent.planners.reflection_pyautogui_planner import ReflectionPyAutoGUIPlanner
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'neutral-test-key')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    p = tmp_path / 'audit.jsonl'
    monkeypatch.setenv('OS_OMNI_DEEPSEEK_REQUEST_AUDIT', str(p))
    manager = LLMClientManager.from_default_models_yaml()
    adapter = OpenAIAdapter()
    def send(url, key, payload, timeout):
        assert payload['input'][0]['role'] == 'system'
        text = payload['input'][0]['content'][0]['text']
        assert 'import modules' in text and 'Do not create a new driver' in text
        return {'id': 'neutral', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '```WAIT```'}]}]}
    monkeypatch.setattr(adapter, '_request_json', send)
    manager.register_provider_adapter(adapter)
    system = IOSPromptBuilder(observation_mode='screenshot_only', tool_calling=False).build_system_prompt(task=SimpleNamespace(goal='Neutral probe.'))
    planner = ReflectionPyAutoGUIPlanner(manager, 'deepseek_flash', system, history_window=3)
    result = planner.decide('Neutral observation.')
    assert result.action['type'] == 'wait'
    assert json.loads(p.read_text().splitlines()[0])['ios_import_prohibition_transmitted'] is True
