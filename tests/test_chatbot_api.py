import pytest

from app import create_app, db
from app.blueprints.chatbot import ChatbotConfigError


class _FakeGraph:
    def __init__(self, result=None, error=None):
        self._result = result or {}
        self._error = error

    def invoke(self, _state):
        if self._error is not None:
            raise self._error
        return self._result


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


def test_chat_success_returns_reply_and_sources(client, mocker):
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        return_value=_FakeGraph(
            result={
                "answer": "test reply",
                "sources": ["https://ntupool.org/"],
            }
        ),
    )

    response = client.post("/api/chat", json={"message": "pool hours?"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["reply"] == "test reply"
    assert data["sources"] == ["https://ntupool.org/"]


def test_chat_empty_message_returns_400(client):
    response = client.post("/api/chat", json={"message": "   "})
    data = response.get_json()

    assert response.status_code == 400
    assert "message" in data["error"]


def test_chat_internal_error_returns_500(client, mocker):
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        return_value=_FakeGraph(error=RuntimeError("boom")),
    )

    response = client.post("/api/chat", json={"message": "trigger error"})
    data = response.get_json()

    assert response.status_code == 500
    assert data["error"] == "Internal chatbot error."


def test_chat_config_error_returns_503(client, mocker):
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        side_effect=ChatbotConfigError("missing env"),
    )

    response = client.post("/api/chat", json={"message": "missing config"})
    data = response.get_json()

    assert response.status_code == 503
    assert data["error"] == "Chatbot is not configured."
