from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app import feature_config, main, reminders, runtime, tools, weather_care
from backend.app.store import Store


def test_rest_reminders_vary_without_repeating_the_previous_message():
    first = reminders.poll(immediate=True)['event']['text']
    second = reminders.poll(immediate=True)['event']['text']
    assert first and second and first != second


def test_weather_care_uses_saved_city_and_cached_weather_without_blocking_poll(tmp_path, monkeypatch):
    store = Store(tmp_path / 'care.sqlite3')
    store.initialize()
    store.update_user_profile({'city': '南宁'})
    monkeypatch.setattr(runtime, 'store', store)
    started, release = Event(), Event()
    calls = []

    async def weather(args, timeout):
        calls.append(args.city)
        started.set()
        release.wait(2)
        return {
            'ok': True,
            'location': {'city': args.city},
            'current': {'time': datetime.now(timezone.utc).isoformat(), 'temperature_2m': 18, 'precipitation': 2},
            'condition': '小雨',
            'timezone': 'UTC',
            'sources': [{'title': '天气来源', 'url': 'https://api.open-meteo.com/'}],
        }

    monkeypatch.setattr(tools, 'weather', weather)
    feature_config.update({'reminders': {'enabled': True, 'quiet_start': '00:00', 'quiet_end': '00:00'}})
    with TestClient(main.app) as client:
        try:
            first = client.get('/api/reminders/poll')
            assert first.status_code == 200 and first.json()['event'] is None
            assert started.wait(1), 'weather refresh was not scheduled'
        finally:
            release.set()
        import time

        for _ in range(50):
            event = client.post('/api/reminders/test').json()['event']
            if event.get('weather'):
                break
            time.sleep(0.01)
        assert '南宁' in event['text'] and '雨' in event['text']
        assert event['weather']['sources'][0]['url'] == 'https://api.open-meteo.com/'
        assert calls == ['南宁']


def test_cached_weather_stops_being_used_when_the_observation_is_too_old(tmp_path, monkeypatch):
    store = Store(tmp_path / 'stale-care.sqlite3')
    store.initialize()
    store.update_user_profile({'city': '南宁'})
    monkeypatch.setattr(runtime, 'store', store)
    clock = [datetime.now(timezone.utc).timestamp()]
    monkeypatch.setattr(weather_care, 'time', SimpleNamespace(time=lambda: clock[0]))
    observed = (datetime.now(timezone.utc) - timedelta(minutes=100)).isoformat()

    async def weather(args, timeout):
        return {
            'ok': True,
            'location': {'city': args.city},
            'current': {'time': observed, 'temperature_2m': 18},
            'condition': '晴',
            'timezone': 'UTC',
            'sources': [],
        }

    monkeypatch.setattr(tools, 'weather', weather)
    feature_config.update({'reminders': {'enabled': True, 'quiet_start': '00:00', 'quiet_end': '00:00'}})
    with TestClient(main.app) as client:
        import time

        event = {}
        for _ in range(50):
            event = client.post('/api/reminders/test').json()['event']
            if event.get('weather'):
                break
            time.sleep(0.01)
        assert event.get('weather'), 'initial bounded-age observation should be usable'
        clock[0] += 30 * 60
        reminders.reset()
        late = client.post('/api/reminders/test').json()['event']
        assert 'weather' not in late
        assert '18℃' not in late['text']


def test_invalid_weather_values_do_not_break_ordinary_care(tmp_path, monkeypatch):
    store = Store(tmp_path / 'bad-weather.sqlite3')
    store.initialize()
    store.update_user_profile({'city': '南宁'})
    monkeypatch.setattr(runtime, 'store', store)
    returned = Event()

    async def weather(args, timeout):
        returned.set()
        return {
            'ok': True,
            'current': {
                'time': datetime.now(timezone.utc).isoformat(),
                'temperature_2m': 18,
                'precipitation': 'unavailable',
            },
            'condition': '晴',
            'timezone': 'UTC',
        }

    monkeypatch.setattr(tools, 'weather', weather)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        import time

        client.post('/api/reminders/test')
        assert returned.wait(1)
        for _ in range(5):
            response = client.post('/api/reminders/test')
            assert response.status_code == 200
            assert 'weather' not in response.json()['event']
            time.sleep(0.01)


def test_ambiguous_weather_city_gives_a_profile_correction_hint_and_keeps_ordinary_reminders(tmp_path, monkeypatch):
    import time

    store = Store(tmp_path / 'ambiguous.sqlite3')
    store.initialize()
    store.update_user_profile({'city': '朝阳'})
    monkeypatch.setattr(runtime, 'store', store)

    async def weather(args, timeout):
        return {'ok': False, 'code': 'ambiguous_location', 'message': '发现多个同名地点，请选择国家和地区。'}

    monkeypatch.setattr(tools, 'weather', weather)
    with TestClient(main.app) as client:
        for _ in range(50):
            data = client.post('/api/reminders/test').json()
            if data.get('weather_notice'):
                break
            time.sleep(0.01)
        assert '记忆空间' in data.get('weather_notice', '')
        assert data['event']['text'] and 'weather' not in data['event']
