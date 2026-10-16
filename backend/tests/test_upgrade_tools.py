import asyncio

import pytest

from backend.app import feature_config, tools


def test_weather_queries_city_suffix_and_normalizes_chinese_region(monkeypatch):
    calls = []

    async def request(method, url, **kwargs):
        calls.append(kwargs['params'])
        if 'geocoding' in url:
            assert kwargs['params']['name'] == '贺州市'
            assert kwargs['params']['countryCode'] == 'CN'
            return {
                'results': [
                    {
                        'id': 1,
                        'name': '贺州市',
                        'country_code': 'CN',
                        'admin1': '广西',
                        'feature_code': 'PPLA2',
                        'latitude': 24.4,
                        'longitude': 111.5,
                    }
                ]
            }
        return {'current': {'temperature_2m': 25, 'time': '2026-10-16T08:00'}}

    monkeypatch.setattr(tools, 'request_json', request)
    result = asyncio.run(tools.weather(tools.WeatherArgs(city='贺州', country='中国', region='广西壮族自治区'), 12))
    assert result['ok'] and result['location']['city'] == '贺州市'
    assert len(calls) == 2


@pytest.mark.parametrize('provider,result', [('tavily', {'results': []}), ('wikipedia', {'query': {'search': []}})])
def test_empty_search_is_never_reported_as_success(monkeypatch, provider, result):
    async def request(*args, **kwargs):
        return result

    monkeypatch.setattr(tools, 'request_json', request)
    settings = feature_config.ToolsConfig(search_provider=provider, api_key='test-key')
    result = asyncio.run(tools.web_search(tools.SearchArgs(query='Python'), settings))
    assert result['ok'] is False and result['code'] == 'no_results' and result['sources'] == []


def test_wikipedia_business_error_is_not_empty_success(monkeypatch):
    async def request(*args, **kwargs):
        return {'error': {'code': 'badrequest', 'info': 'do-not-echo-private'}}

    monkeypatch.setattr(tools, 'request_json', request)
    with pytest.raises(tools.ToolServiceError) as error:
        asyncio.run(
            tools.web_search(tools.SearchArgs(query='Python'), feature_config.ToolsConfig(search_provider='wikipedia'))
        )
    assert error.value.code == 'upstream_business'
    assert 'private' not in error.value.message
