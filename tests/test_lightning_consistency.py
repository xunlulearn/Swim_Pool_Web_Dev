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


def test_lightning_history_error_keeps_latest_snapshot_alignment(monkeypatch):
    engine = WeatherEngine()
    stale_now = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    stale_charts, _ = engine._build_lightning_history_charts([], stale_now)
    stale_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observation_time_sgt": stale_now.isoformat(),
        "distance_options_km": [15, 30],
        "window_options": ["20m", "1h", "12h"],
        "charts": stale_charts,
        "metadata": {
            "data_source": "live_api",
            "requests_made": 1,
            "records_loaded": 1,
            "coverage_start_sgt": None,
            "coverage_end_sgt": stale_now.isoformat(),
            "oldest_counted_point_sgt": None,
            "full_12h_coverage": False,
            "truncated": False,
            "rate_limited": False,
            "error": None,
            "warning": None,
            "stale_cache": False,
        },
    }
    engine._set_cached_lightning_history(stale_payload)
    engine._lightning_history_cache_at = datetime.now(timezone.utc) - timedelta(seconds=120)

    latest_observed_at = (
        datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0) - timedelta(minutes=1)
    )
    latest_snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observation_time_sgt": latest_observed_at.isoformat(),
        "data_source": "live_api",
        "stale_cache": False,
        "source_error": None,
        "metrics": {
            "within_15km_count": 4,
            "within_30km_count": 9,
        },
    }

    monkeypatch.setattr(engine, "get_lightning_snapshot", lambda: latest_snapshot)
    payload = engine.get_lightning_history()

    assert payload["observation_time_sgt"] == latest_snapshot["observation_time_sgt"]
    assert sum(payload["charts"]["20m"]["counts_30km"]) == 9
    assert payload["metadata"]["error"] == "no_persisted_data"
    assert payload["metadata"]["stale_cache"] is False
