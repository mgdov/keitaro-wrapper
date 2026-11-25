import httpx
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.keitaro import KeitaroClient


def test_api_key_sent_only_to_configured_backend_host():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[])
    client = KeitaroClient(Settings(keitaro_api_key='unit-test-secret'), httpx.MockTransport(handler))
    assert client.get('/offers') == []
    assert calls[0].headers['Api-Key'] == 'unit-test-secret'
    assert calls[0].url.path == '/admin_api/v1/offers'


@pytest.mark.parametrize('kind', ['http', 'network', 'bad-json'])
def test_upstream_failures_do_not_expose_secrets(kind):
    def handler(request):
        if kind == 'network': raise httpx.ReadTimeout('unit-test-secret', request=request)
        if kind == 'http': return httpx.Response(403, text='unit-test-secret')
        return httpx.Response(200, text='not JSON')
    client = KeitaroClient(Settings(keitaro_api_key='unit-test-secret'), httpx.MockTransport(handler))
    with pytest.raises(HTTPException) as error:
        client.get('/offers')
    assert error.value.status_code == 502
    assert 'unit-test-secret' not in error.value.detail
