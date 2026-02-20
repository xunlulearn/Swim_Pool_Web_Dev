from datetime import datetime, timedelta, timezone

from app.services.weather_engine import PoolStatus, WeatherEngine


def _build_latest_payload():
    return {
        "code": 0,
        "data": {
            "records": [
                {
                    "datetime": "2026-02-20T15:00:00+08:00",
                    "item": {
                        "readings": [
                            {
                                "location": {
                                    "latitude": "1.349383588",
                                    "longitude": "103.6877553",
                                },
                            },
                            {
                                "location": {
                                    "latitude": "1.549383588",
                                    "longitude": "103.6877553",
                                },
                            },
                            {
                                "location": {
                                    "latitude": "1.749383588",
                                    "longitude": "103.6877553",
                                },
                            },
                        ]
                    },
                },
                {
                    "datetime": "2026-02-20T14:55:00+08:00",
                    "item": {
                        "readings": [
                            {
                                "location": {
                                    "latitude": "1.349383588",
                                    "longitude": "103.6877553",
                                },
                            }
                        ]
                    },
                },
            ]
        },
    }


def test_lightning_status_and_radar_share_latest_snapshot(monkeypatch):
    engine = WeatherEngine()
    payload = _build_latest_payload()

    monkeypatch.setattr(
        engine,
        "_fetch_lightning_payload",
        lambda: (payload, "live_api", None),
    )

    status, _, details = engine.get_lightning_status()
    radar = engine.get_lightning_radar_data()

    assert status == PoolStatus.RED
    assert details["lightning_count_basis"] == "within_30km_latest_snapshot"
    assert details["lightning_count"] == 2
    assert details["min_distance_km"] == radar["metrics"]["nearest_distance_km"]
    assert details["lightning_count"] == radar["metrics"]["within_radius_count"]
    assert radar["metrics"]["total_valid_count"] == 3
    assert len(radar["points"]) == 2


def test_lightning_history_uses_latest_snapshot_override():
    engine = WeatherEngine()
    now_sgt = datetime(2026, 2, 20, 15, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    records = [
        {
            "datetime": (now_sgt - timedelta(minutes=1)).isoformat(),
            "item": {
                "readings": [
                    {
                        "location": {
                            "latitude": "1.949383588",
                            "longitude": "103.6877553",
                        }
                    }
                ]
            },
        }
    ]
    latest_snapshot = {
        "observation_time_sgt": (now_sgt - timedelta(minutes=1)).isoformat(),
        "metrics": {
            "within_15km_count": 2,
            "within_30km_count": 3,
        },
    }

    charts, _ = engine._build_lightning_history_charts(
        records,
        now_sgt,
        latest_snapshot=latest_snapshot,
    )

    assert sum(charts["20m"]["counts_15km"]) == 2
    assert sum(charts["20m"]["counts_30km"]) == 3
