from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.report import PoolReport
from app.models.user import User


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = False
    # The report cache is module-global; disable it so tests stay isolated.
    app.config["LIVE_STATUS_CACHE_SECONDS"] = 0

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _add_report(user, *, created_at, status="Closed"):
    db.session.add(user)
    db.session.flush()
    db.session.add(PoolReport(status=status, user_id=user.id, created_at=created_at))
    db.session.commit()


def test_live_status_reports_use_profile_display_name(client, app):
    with app.app_context():
        _add_report(
            User(
                email="bot_gabriel_lane4@ntupool.local",
                username="bot_gabriel_lane4",
                nickname="Gabriel Lee",
                is_verified=True,
                is_bot=True,
            ),
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )

    response = client.get("/api/live-status/")

    assert response.status_code == 200
    assert response.get_json()[0]["user"] == "Gabriel Lee"


def test_live_status_hides_reports_older_than_24_hours(client, app):
    with app.app_context():
        _add_report(
            User(
                email="old@example.com",
                username="old_reporter",
                is_verified=True,
            ),
            created_at=datetime.utcnow() - timedelta(hours=30),
        )
        _add_report(
            User(
                email="fresh@example.com",
                username="fresh_reporter",
                is_verified=True,
            ),
            created_at=datetime.utcnow() - timedelta(hours=2),
            status="Open",
        )

    response = client.get("/api/live-status/")

    assert response.status_code == 200
    payload = response.get_json()
    assert [row["user"] for row in payload] == ["fresh_reporter"]
    assert payload[0]["status"] == "Open"
