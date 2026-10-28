import asyncio
import json

import httpx
import pytest

from app import research, search
from app.errors import APIError


def install_client(monkeypatch, module, factory, handler):
    monkeypatch.setattr(module, factory, lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize('parts', [1, {}, [{'text': 7}], [{'text': []}]])
def test_malformed_gemini_parts_fail_as_upstream_errors(monkeypatch, parts):
    install_client(monkeypatch, research, 'gemini_client', lambda request:
                   httpx.Response(200, json={'candidates': [{'content': {'parts': parts}}]}))
    with pytest.raises(APIError) as error:
        asyncio.run(research.gemini_generate('synthetic-key', {}))
    assert error.value.status_code == 502


@pytest.mark.parametrize('field,value', [
    ('link', {}), ('link', 'https://['), ('link', 'javascript:alert(1)'),
    ('link', 'https://example.org:bad'), ('title', []), ('snippet', 42),
])
def test_malformed_search_fields_are_rejected(field, value):
    with pytest.raises(APIError) as error:
        search.normalize_payload({'organic_results': [{field: value}]}, 'question')
    assert error.value.status_code == 502


@pytest.mark.parametrize('provider', ['serpapi', 'gemini'])
def test_provider_error_body_is_not_returned(client, monkeypatch, provider):
    sentinel = 'synthetic-secret-must-not-escape'
    if provider == 'serpapi':
        monkeypatch.setenv('SERPAPI_API_KEY', sentinel)
        install_client(monkeypatch, search, 'serpapi_client', lambda request:
                       httpx.Response(200, json={'error': sentinel}))
        response = client.get('/search', params={'q': 'example'})
    else:
        monkeypatch.setenv('GEMINI_API_KEY', sentinel)
        install_client(monkeypatch, research, 'gemini_client', lambda request:
                       httpx.Response(200, json={'error': {'message': sentinel}}))
        response = client.post('/research', json={'question': 'example'})
    assert response.status_code == 502
    assert sentinel not in response.text


@pytest.mark.parametrize('failure', ['http500', 'invalid_json', 'connection'])
def test_synthesis_failure_preserves_collected_evidence(client, monkeypatch, failure):
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-key')
    monkeypatch.setenv('SERPAPI_API_KEY', 'synthetic-key')
    install_client(monkeypatch, search, 'serpapi_client', lambda request:
                   httpx.Response(200, json={'organic_results': [
                       {'link': 'https://example.org/evidence', 'title': 'Evidence'}]}))

    def gemini(request):
        if json.loads(request.content).get('generationConfig'):
            return httpx.Response(200, json={'candidates': [{'content': {'parts': [
                {'text': json.dumps({'queries': ['one angle', 'another aspect']})} ]}}]})
        if failure == 'connection':
            raise httpx.ConnectError('synthetic error')
        if failure == 'invalid_json':
            return httpx.Response(200, text='not json')
        return httpx.Response(500)

    install_client(monkeypatch, research, 'gemini_client', gemini)
    response = client.post('/research', json={'question': 'example'})
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'degraded'
    assert body['answer'] is None
    assert len(body['sources']) == 1


def test_uppercase_scheme_cannot_bypass_citation_provenance():
    assert research.inline_urls_not_in_evidence('See HTTPS://example.org/unknown', []) == [
        'HTTPS://example.org/unknown']
