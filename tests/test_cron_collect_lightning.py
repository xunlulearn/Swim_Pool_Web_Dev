import pytest

from app import create_app, db


@pytest.fixture
def app():
    app = create_app("testing")
    app.config.update(CRON_SECRET="test-cron-secret")

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_collect_lightning_cron_rejects_missing_secret(client):
    response = client.get("/api/cron/collect-lightning")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found."}


def test_collect_lightning_cron_rejects_invalid_secret(client):
    response = client.get("/api/cron/collect-lightning?secret=wrong")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Not found."}


def test_collect_lightning_cron_triggers_collection_with_valid_query_secret(
    client,
    monkeypatch,
):
    import app.blueprints.cron as cron_blueprint

    calls = []

    def fake_collect():
        calls.append("called")
        return {"ok": True, "snapshot": {"data_source": "live_api"}}

    monkeypatch.setattr(
        cron_blueprint.weather_engine,
        "collect_and_store_latest_lightning_snapshot",
        fake_collect,
    )

    response = client.get("/api/cron/collect-lightning?secret=test-cron-secret")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert calls == ["called"]


def test_collect_lightning_cron_accepts_bearer_secret(client, monkeypatch):
    import app.blueprints.cron as cron_blueprint

    monkeypatch.setattr(
        cron_blueprint.weather_engine,
        "collect_and_store_latest_lightning_snapshot",
        lambda: {"ok": True, "snapshot": {"data_source": "live_api"}},
    )

    response = client.get(
        "/api/cron/collect-lightning",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
