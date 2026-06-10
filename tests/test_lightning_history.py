from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.extensions import db
from app.models.lightning_history import LightningHistorySnapshot
from app.services.weather_engine import PoolStatus, WeatherEngine


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
    assert charts["12h"]["bar_count"] == 61
    assert len(charts["12h"]["labels"]) == 61
    assert len(charts["12h"]["counts_15km"]) == 61
    assert len(charts["12h"]["counts_30km"]) == 61
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


def test_lightning_history_uses_persisted_store_when_live_fetch_is_limited(app, monkeypatch):
    engine = WeatherEngine()
    now_sgt = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
    observation_time = (now_sgt - timedelta(minutes=2)).replace(microsecond=0)
    record = {
        "datetime": observation_time.isoformat(),
        "item": {
            "readings": [
                {"location": {"latitude": "1.349383588", "longitude": "103.6877553"}},
                {"location": {"latitude": "1.429383588", "longitude": "103.6877553"}},
            ]
        },
    }
    snapshot_payload = {
        "code": 0,
        "data": {
            "records": [record],
        },
    }

    monkeypatch.setattr(
        engine,
        "_fetch_lightning_payload",
        lambda: (snapshot_payload, "live_api", None),
    )
    monkeypatch.setattr(
        engine,
        "_fetch_lightning_records_for_history",
        lambda now_sgt, cutoff_sgt: (
            [record],
            {
                "data_source": "live_api",
                "request_count": 1,
                "truncated": False,
                "rate_limited": False,
                "error": None,
                "coverage_start": observation_time,
            },
        ),
    )

    with app.app_context():
        db.create_all()
        db.session.query(LightningHistorySnapshot).delete()
        db.session.commit()

        first_payload = engine.get_lightning_history()
        assert first_payload["metadata"]["persisted_records_loaded"] >= 1
        assert db.session.query(LightningHistorySnapshot).count() >= 1
        stored_row = db.session.query(LightningHistorySnapshot).first()
        assert stored_row is not None
        assert stored_row.points_30km_json is not None

        engine._lightning_history_cache = None
        engine._lightning_history_cache_at = None
        engine._lightning_snapshot_cache = None
        engine._lightning_snapshot_cache_at = None

        monkeypatch.setattr(
            engine,
            "_fetch_lightning_records_for_history",
            lambda now_sgt, cutoff_sgt: (
                [],
                {
                    "data_source": "live_api",
                    "request_count": 1,
                    "truncated": False,
                    "rate_limited": True,
                    "error": "rate_limited",
                    "coverage_start": None,
                },
            ),
        )

        second_payload = engine.get_lightning_history()
        assert second_payload["metadata"]["history_basis"] == "persisted_store"
        assert second_payload["metadata"]["persisted_records_loaded"] >= 1
        assert sum(second_payload["charts"]["20m"]["counts_30km"]) >= 1


def test_persist_lightning_snapshot_prunes_rows_older_than_24_hours(app):
    engine = WeatherEngine()
    now_utc = datetime(2026, 6, 10, 12, 20, 0, tzinfo=timezone.utc)
    old_utc = now_utc - timedelta(hours=24, minutes=1)
    kept_utc = now_utc - timedelta(hours=23, minutes=59)

    with app.app_context():
        db.create_all()
        db.session.query(LightningHistorySnapshot).delete()
        db.session.add_all(
            [
                LightningHistorySnapshot(
                    observed_at_utc=old_utc.replace(tzinfo=None),
                    observed_at_sgt=old_utc.astimezone(engine.SGT).isoformat(),
                    within_15km_count=0,
                    within_30km_count=1,
                    total_valid_count=1,
                    data_source="live_api",
                ),
                LightningHistorySnapshot(
                    observed_at_utc=kept_utc.replace(tzinfo=None),
                    observed_at_sgt=kept_utc.astimezone(engine.SGT).isoformat(),
                    within_15km_count=0,
                    within_30km_count=2,
                    total_valid_count=2,
                    data_source="live_api",
                ),
            ]
        )
        db.session.commit()

        written = engine._persist_lightning_snapshot_points(
            [
                {
                    "time": now_utc,
                    "counts_15km": 0,
                    "counts_30km": 3,
                    "total_valid_count": 3,
                    "nearest_distance_km": 20.0,
                }
            ],
            data_source="live_api",
        )

        assert written == 1
        observed_times = {
            row.observed_at_utc.replace(tzinfo=timezone.utc)
            for row in LightningHistorySnapshot.query.all()
        }
        assert old_utc not in observed_times
        assert kept_utc in observed_times
        assert now_utc in observed_times


def test_lightning_cooldown_is_consistent_across_engine_instances(app, monkeypatch):
    with app.app_context():
        db.create_all()
        db.session.query(LightningHistorySnapshot).delete()
        db.session.commit()

        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        observed_at_utc = (now_utc - timedelta(minutes=1)).replace(tzinfo=None)
        observed_at_sgt = (now_utc - timedelta(minutes=1)).astimezone(
            timezone(timedelta(hours=8))
        ).isoformat()
        db.session.add(
            LightningHistorySnapshot(
                observed_at_utc=observed_at_utc,
                observed_at_sgt=observed_at_sgt,
                within_15km_count=3,
                within_30km_count=10,
                total_valid_count=10,
                nearest_distance_km=5.0,
                data_source="persisted_store",
                points_30km_json="[]",
            )
        )
        db.session.commit()

        engines = [WeatherEngine(), WeatherEngine()]
        for engine in engines:
            monkeypatch.setattr(engine, "_is_operating_hours", lambda: (True, None))
            monkeypatch.setattr(engine, "_get_community_consensus", lambda: None)
            monkeypatch.setattr(engine, "get_rainfall_status", lambda: (0.0, None, None))
            monkeypatch.setattr(
                engine,
                "get_lightning_status",
                lambda: (
                    PoolStatus.GREEN,
                    "No lightning nearby - Pool is Open",
                    {
                        "min_distance_km": 999.0,
                        "lightning_count": 0,
                        "data_source": "persisted_store",
                        "observation_time_sgt": observed_at_sgt,
                        "lightning_count_basis": "within_30km_latest_snapshot",
                    },
                ),
            )

            status, message, details = engine.get_overall_status()
            assert status == PoolStatus.RED
            assert "Estimated" in message
            assert details.get("reason") == "lightning"
