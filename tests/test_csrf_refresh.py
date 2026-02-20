import re
import time

import pytest

from app import create_app, db


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = 1

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _extract_meta_csrf(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_csrf_refresh_endpoint_returns_token(client):
    response = client.get("/api/csrf-token")
    assert response.status_code == 200

    payload = response.get_json()
    token = payload.get("csrf_token") if isinstance(payload, dict) else ""
    assert isinstance(token, str)
    assert token.strip() != ""


def test_expired_csrf_token_can_be_refreshed(client):
    home = client.get("/")
    token = _extract_meta_csrf(home.get_data(as_text=True))

    time.sleep(2.1)
    expired_response = client.post(
        "/api/chat",
        headers={"X-CSRFToken": token},
        json={"message": "hello"},
    )
    assert expired_response.status_code == 400
    assert expired_response.get_json() == {"error": "Invalid or missing CSRF token."}

    refreshed_response = client.get("/api/csrf-token")
    refreshed_payload = refreshed_response.get_json()
    refreshed_token = (
        refreshed_payload.get("csrf_token") if isinstance(refreshed_payload, dict) else ""
    )
    assert isinstance(refreshed_token, str)
    assert refreshed_token.strip() != ""

    retry_response = client.post(
        "/api/chat",
        headers={"X-CSRFToken": refreshed_token},
        json={"message": "hello"},
    )
    # CSRF passed; endpoint now fails at auth layer because user is anonymous.
    assert retry_response.status_code == 401

