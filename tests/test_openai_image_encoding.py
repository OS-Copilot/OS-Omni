import base64
import io

from PIL import Image

from core.llm.providers.openai_adapter import OpenAIAdapter
from core.llm.providers.base import ProviderRequest
from core.llm.types import ImagePart, Message, ModelSpec, ProviderCredentials, TextPart


def test_jpeg_transport_preserves_dimensions_original_and_request_parameters(tmp_path):
    path = tmp_path / 'screen.png'
    Image.new('RGB', (1920, 1080), '#386fa4').save(path)
    original = path.read_bytes()
    def payload(metadata):
        spec = ModelSpec(model_id='test', provider='openai', model_name='qwen3.8-max',
                         api_key_env='TEST_KEY', metadata=metadata)
        request = ProviderRequest(model_spec=spec, credentials=ProviderCredentials('test'),
                                  messages=[Message('user', [TextPart('Inspect screenshot'), ImagePart(str(path))])],
                                  response_mode='json_text', parameters={'reasoning_effort': 'none', 'max_output_tokens': 16384})
        return OpenAIAdapter()._build_payload(request)
    default = payload({})
    default_url = default['messages'][0]['content'][1]['image_url']['url']
    assert default_url.startswith('data:image/png;base64,')
    assert base64.b64decode(default_url.split(',')[1]) == original
    encoded = payload({'image_jpeg_quality': 85, 'stream': True, 'enable_thinking': False})
    assert encoded['stream'] is True
    assert encoded['enable_thinking'] is False
    assert 'reasoning' not in encoded
    assert 'stream' not in default
    jpeg_url = encoded['messages'][0]['content'][1]['image_url']['url']
    assert jpeg_url.startswith('data:image/jpeg;base64,')
    with Image.open(io.BytesIO(base64.b64decode(jpeg_url.split(',')[1]))) as image:
        assert image.format == 'JPEG'
        assert image.size == (1920, 1080)
    assert path.read_bytes() == original
    assert encoded['model'] == 'qwen3.8-max'
    assert encoded['reasoning_effort'] == 'none'
    assert encoded['max_completion_tokens'] == 16384
    assert encoded['messages'][0]['content'][0] == default['messages'][0]['content'][0]
