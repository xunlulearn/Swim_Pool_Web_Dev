from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.services.weather_engine import WeatherEngine


@pytest.fixture
def app():
    app = create_app("testing")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_build_lightning_history_charts_counts_by_radius_and_window():
    engine = WeatherEngine()
    now_sgt = datetime(2026, 2, 20, 15, 0, 0, tzinfo=timezone(timedelta(hours=8)))

    records = [
        {
            "datetime": (now_sgt - timedelta(minutes=2)).isoformat(),
            "item": {
                "readings": [
                    {
                        "location": {"latitude": "1.4394", "longitude": "103.6878"},
                    },
                ]
            },
        },
        {
            "datetime": (now_sgt - timedelta(minutes=20)).isoformat(),
            "item": {
                "readings": [
                    {
                        "location": {"latitude": "1.5294", "longitude": "103.6878"},
                    }
                ]
            },
        },
        {
            "datetime": (now_sgt - timedelta(hours=2)).isoformat(),
            "item": {
                "readings": [
                    {
                        "location": {"latitude": "1.5294", "longitude": "103.6878"},
                    }
                ]
            },
        },
        {
            "datetime": (now_sgt - timedelta(hours=1)).isoformat(),
            "item": {
                "readings": [
                    {
                        "location": {"latitude": "1.7994", "longitude": "103.6878"},
                    }
                ]
            },
        },
        {
            "datetime": (now_sgt - timedelta(hours=25)).isoformat(),
            "item": {
                "readings": [
                    {
                        "location": {"latitude": "1.4394", "longitude": "103.6878"},
                    }
                ]
            },
        },
    ]

    charts, oldest_counted = engine._build_lightning_history_charts(records, now_sgt)

    assert charts["20m"]["snapshot_count"] == 2
    assert sum(charts["20m"]["counts_15km"]) == 1
    assert sum(charts["20m"]["counts_30km"]) == 2

    assert charts["1h"]["snapshot_count"] == 3
    assert sum(charts["1h"]["counts_15km"]) == 1
    assert sum(charts["1h"]["counts_30km"]) == 2

    assert charts["12h"]["snapshot_count"] == 4
    assert charts["12h"]["bar_count"] == 60
    assert len(charts["12h"]["labels"]) == 60
    assert len(charts["12h"]["counts_15km"]) == 60
    assert len(charts["12h"]["counts_30km"]) == 60
    assert sum(charts["12h"]["counts_15km"]) == 1
    assert sum(charts["12h"]["counts_30km"]) == 3

    assert oldest_counted == (now_sgt - timedelta(hours=2))


def test_lightning_history_endpoint_contract(client, monkeypatch):
    import app.blueprints.weather as weather_blueprint

    sample_payload = {
        "generated_at": "2026-02-20T07:00:00+00:00",
        "observation_time_sgt": "2026-02-20T15:00:00+08:00",
        "distance_options_km": [15, 30],
        "window_options": ["20m", "1h", "12h"],
        "charts": {
            "20m": {
                "display_label": "Last 20 Minutes",
                "labels": ["14:51", "14:52"],
                "counts_15km": [0, 2],
                "counts_30km": [1, 3],
                "totals": {"15km": 2, "30km": 4},
                "snapshot_count": 2,
                "bar_count": 2,
            }
        },
        "metadata": {
            "data_source": "sample_data",
            "requests_made": 0,
            "records_loaded": 1,
            "coverage_start_sgt": "2026-02-20T14:50:00+08:00",
            "coverage_end_sgt": "2026-02-20T15:00:00+08:00",
            "oldest_counted_point_sgt": "2026-02-20T14:58:00+08:00",
            "full_12h_coverage": False,
            "truncated": False,
            "rate_limited": False,
            "error": None,
            "warning": None,
            "stale_cache": False,
        },
    }

    monkeypatch.setattr(
        weather_blueprint.weather_engine,
        "get_lightning_history",
        lambda: sample_payload,
    )

    response = client.get("/weather/lightning-history")
    assert response.status_code == 200
    assert response.headers["Cache-Control"].startswith("no-store")

    body = response.get_json()
    assert body["distance_options_km"] == [15, 30]
    assert body["window_options"] == ["20m", "1h", "12h"]
    assert "20m" in body["charts"]
