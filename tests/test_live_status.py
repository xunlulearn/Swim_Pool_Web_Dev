from datetime import datetime

import pytest

from app import create_app, db
from app.models.report import PoolReport
from app.models.user import User


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_live_status_reports_use_profile_display_name(client, app):
    with app.app_context():
        user = User(
            email="bot_gabriel_lane4@ntupool.local",
            username="bot_gabriel_lane4",
            nickname="Gabriel Lee",
            is_verified=True,
            is_bot=True,
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            PoolReport(
                status="Closed",
                user_id=user.id,
                created_at=datetime(2026, 6, 11, 13, 53, 3),
            )
        )
        db.session.commit()

    response = client.get("/api/live-status/")

    assert response.status_code == 200
    assert response.get_json()[0]["user"] == "Gabriel Lee"
