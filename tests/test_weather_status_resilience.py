import pytest

from app import create_app
from app.services.weather_engine import PoolStatus, WeatherEngine


def test_overall_status_skips_weather_calls_outside_operating_hours(monkeypatch):
    engine = WeatherEngine()
    hours_message = "Pool Closed - Outside Operating Hours (Weekday 07:00-21:30)"

    monkeypatch.setattr(engine, "_is_operating_hours", lambda: (False, hours_message))
    monkeypatch.setattr(engine, "get_lightning_status", pytest.fail)
    monkeypatch.setattr(engine, "get_rainfall_status", pytest.fail)

    status, message, details = engine.get_overall_status()

    assert status == PoolStatus.RED
    assert message == hours_message
    assert details["reason"] == "operating_hours"
    assert details["data_source"] == "degraded"


def test_live_weather_requests_use_configured_timeout(monkeypatch):
    app = create_app("testing")
    app.config.update(WEATHER_API_TIMEOUT_SECONDS=3)
    engine = WeatherEngine()
    timeouts = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "code": 0,
                "data": {
                    "records": [{"datetime": "2026-02-20T15:00:00+08:00", "item": {}}],
                    "stations": [
                        {
                            "id": "S44",
                            "name": "NTU",
                            "location": {
                                "latitude": engine.SRC_LAT,
                                "longitude": engine.SRC_LON,
                            },
                        }
                    ],
                    "readings": [{"data": [{"stationId": "S44", "value": 0.1}]}],
                },
            }

    def fake_get(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return FakeResponse()

    monkeypatch.setattr("app.services.weather_engine.requests.get", fake_get)

    with app.app_context():
        engine._fetch_lightning_payload()
        rainfall_rate, _, _ = engine.get_rainfall_status()

    assert timeouts == [3, 3]
    assert rainfall_rate == pytest.approx(1.2)
