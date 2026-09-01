import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import create_app, db
from app.blueprints.chatbot import ChatbotConfigError
from app.blueprints import chatbot as chatbot_module
from app.models.user import User


class _FakeGraph:
    def __init__(self, result=None, error=None):
        self._result = result or {}
        self._error = error
        self.invocations = []

    def invoke(self, state):
        self.invocations.append(state)
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


@pytest.fixture
def user_id(app):
    with app.app_context():
        user = User(
            email="chatbot@example.com",
            username="chatbot_tester",
            is_verified=True,
        )
        user.password = "password123"
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def auth_client(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    return client


def test_chat_requires_login(client):
    response = client.post("/api/chat", json={"message": "pool hours?"})
    data = response.get_json()

    assert response.status_code == 401
    assert data["login_required"] is True


def test_chat_success_returns_reply_sources_and_feedback_metadata(auth_client, mocker):
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        return_value=_FakeGraph(
            result={
                "answer": "test reply",
                "sources": ["https://ntupool.org/"],
                "quick_questions": [
                    "Is the pool open right now?",
                    "How can I submit a manual pool report?",
                ],
            }
        ),
    )
    mocker.patch(
        "app.blueprints.chatbot._persist_chatbot_exchange",
        return_value={
            "conversation_id": "93ab65e7-18cc-4913-8521-5ca4c2410f2b",
            "message_counter": 10,
            "feedback_required": True,
        },
    )

    response = auth_client.post("/api/chat", json={"message": "pool hours?"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["reply"] == "test reply"
    assert data["sources"] == ["https://ntupool.org/"]
    assert data["message_counter"] == 10
    assert data["feedback_required"] is True
    assert data["conversation_id"] == "93ab65e7-18cc-4913-8521-5ca4c2410f2b"
    assert data["quick_questions"] == [
        "Is the pool open right now?",
        "How can I submit a manual pool report?",
    ]
    assert "feedback_prompt" in data


def test_static_hard_kb_answer_skips_graph_and_homepage_weather(auth_client, mocker):
    mocker.patch("app.blueprints.chatbot._check_burst_limit", return_value=True)
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        side_effect=AssertionError("hard KB should bypass graph construction"),
    )
    mocker.patch(
        "app.blueprints.chatbot._build_homepage_context",
        side_effect=AssertionError("static answer should not fetch live weather"),
    )
    mocker.patch(
        "app.blueprints.chatbot._persist_chatbot_exchange",
        return_value={
            "conversation_id": "93ab65e7-18cc-4913-8521-5ca4c2410f2b",
            "message_counter": 1,
            "feedback_required": False,
        },
    )

    response = auth_client.post("/api/chat", json={"message": "周末泳池营业时间是什么？"})
    data = response.get_json()

    assert response.status_code == 200
    assert "8:00" in data["reply"]
    assert data["sources"] == ["app://hard-kb/hours-weekend"]


def test_explicit_out_of_scope_answer_skips_graph_and_homepage_weather(auth_client, mocker):
    mocker.patch("app.blueprints.chatbot._check_burst_limit", return_value=True)
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        side_effect=AssertionError("explicit fallback should bypass graph construction"),
    )
    mocker.patch(
        "app.blueprints.chatbot._build_homepage_context",
        side_effect=AssertionError("explicit fallback should not fetch live weather"),
    )
    mocker.patch(
        "app.blueprints.chatbot._persist_chatbot_exchange",
        return_value={
            "conversation_id": "93ab65e7-18cc-4913-8521-5ca4c2410f2b",
            "message_counter": 1,
            "feedback_required": False,
        },
    )

    response = auth_client.post("/api/chat", json={"message": "请预测明天比特币价格"})
    data = response.get_json()

    assert response.status_code == 200
    assert "不在我的支持范围" in data["reply"]
    assert data["sources"] == []


def test_chat_passes_homepage_context_to_rag_app(auth_client, mocker):
    fake_graph = _FakeGraph(result={"answer": "The pool is open."})
    mocker.patch("app.blueprints.chatbot.get_rag_app", return_value=fake_graph)
    mocker.patch(
        "app.blueprints.chatbot._persist_chatbot_exchange",
        return_value={
            "conversation_id": "93ab65e7-18cc-4913-8521-5ca4c2410f2b",
            "message_counter": 1,
            "feedback_required": False,
        },
    )
    mocker.patch(
        "app.blueprints.chatbot._build_homepage_context",
        return_value=[
            "Current homepage status: OPEN.",
            "Lightning trend 20 min <= 15 km total: 0 strikes.",
        ],
    )

    response = auth_client.post(
        "/api/chat",
        json={
            "message": "\u5f53\u524d\u6cf3\u6c60\u662f\u5f00\u653e\u7684\u5417",
            "page_context": {
                "selected_lightning_radius": "15km",
                "selected_lightning_window": "20m",
            },
        },
    )

    assert response.status_code == 200
    assert fake_graph.invocations[0] == {
        "question": "\u5f53\u524d\u6cf3\u6c60\u662f\u5f00\u653e\u7684\u5417",
        "page_context": [
            "Current homepage status: OPEN.",
            "Lightning trend 20 min <= 15 km total: 0 strikes.",
        ],
    }


def test_homepage_context_includes_lightning_trend_safety_guidance(mocker, app):
    class _State:
        name = "GREEN"
        value = "Open"

    class _WeatherEngine:
        def get_overall_status(self):
            return (
                _State(),
                "Pool is Open",
                {
                    "min_distance_km": 999,
                    "lightning_count": 0,
                    "rainfall_rate": 0,
                },
            )

        def get_lightning_history(self):
            return {"charts": {}, "metadata": {}}

    mocker.patch("app.services.weather_engine.weather_engine", _WeatherEngine())
    with app.app_context():
        lines = __import__(
            "app.blueprints.chatbot",
            fromlist=["_build_homepage_context"],
        )._build_homepage_context()

    safety_text = " ".join(lines).lower()
    assert "lightning trend worsens" in safety_text
    assert "leave the water" in safety_text
    assert "15 km" in safety_text
    assert "next 30 minutes" in safety_text
    assert "nearest lightning" in safety_text


def test_chat_stream_success_returns_deltas_and_final_payload(auth_client, mocker):
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        return_value=_FakeGraph(
            result={
                "answer": "test reply",
                "sources": ["https://ntupool.org/"],
                "quick_questions": [
                    "Is the pool open right now?",
                    "How can I submit a manual pool report?",
                ],
            }
        ),
    )
    mocker.patch(
        "app.blueprints.chatbot._persist_chatbot_exchange",
        return_value={
            "conversation_id": "93ab65e7-18cc-4913-8521-5ca4c2410f2b",
            "message_counter": 11,
            "feedback_required": False,
        },
    )

    response = auth_client.post("/api/chat/stream", json={"message": "pool hours?"})
    payload_lines = [
        json.loads(line)
        for line in response.get_data(as_text=True).splitlines()
        if line.strip()
    ]

    assert response.status_code == 200
    assert any(item.get("type") == "status" for item in payload_lines)
    assert any(item.get("type") == "delta" for item in payload_lines)
    final_item = payload_lines[-1]
    assert final_item["type"] == "final"
    assert final_item["reply"] == "test reply"
    assert final_item["sources"] == ["https://ntupool.org/"]
    assert final_item["quick_questions"] == [
        "Is the pool open right now?",
        "How can I submit a manual pool report?",
    ]


def test_chat_stream_requires_login(client):
    response = client.post("/api/chat/stream", json={"message": "pool hours?"})
    data = response.get_json()

    assert response.status_code == 401
    assert data["login_required"] is True


def test_chat_empty_message_returns_400(auth_client):
    response = auth_client.post("/api/chat", json={"message": "   "})
    data = response.get_json()

    assert response.status_code == 400
    assert "message" in data["error"]


def test_chat_internal_error_returns_500(auth_client, mocker):
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        return_value=_FakeGraph(error=RuntimeError("boom")),
    )

    response = auth_client.post("/api/chat", json={"message": "trigger error"})
    data = response.get_json()

    assert response.status_code == 500
    assert data["error"] == "Internal chatbot error."


def test_chat_config_error_returns_503(auth_client, mocker):
    mocker.patch(
        "app.blueprints.chatbot.get_rag_app",
        side_effect=ChatbotConfigError("missing env"),
    )

    response = auth_client.post("/api/chat", json={"message": "missing config"})
    data = response.get_json()

    assert response.status_code == 503
    assert data["error"] == "Chatbot is not configured."


def test_chat_feedback_requires_login(client):
    response = client.post(
        "/api/chat/feedback",
        json={
            "conversation_id": str(uuid.uuid4()),
            "rating": 5,
        },
    )
    data = response.get_json()

    assert response.status_code == 401
    assert data["login_required"] is True


def test_chat_feedback_success(auth_client, mocker, user_id):
    save_feedback = mocker.patch("app.blueprints.chatbot._save_chatbot_feedback")
    conversation_id = str(uuid.uuid4())

    response = auth_client.post(
        "/api/chat/feedback",
        json={
            "conversation_id": conversation_id,
            "rating": 4,
            "comment": "Great answer quality.",
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["conversation_id"] == conversation_id
    assert data["rating"] == 4
    assert data["comment"] == "Great answer quality."
    save_feedback.assert_called_once_with(
        user_id=user_id,
        conversation_id=conversation_id,
        rating=4,
        comment="Great answer quality.",
    )


def test_chat_feedback_invalid_rating_returns_400(auth_client):
    response = auth_client.post(
        "/api/chat/feedback",
        json={
            "conversation_id": str(uuid.uuid4()),
            "rating": 7,
        },
    )
    data = response.get_json()

    assert response.status_code == 400
    assert "rating" in data["error"]


def test_chat_log_writes_are_serialized(monkeypatch):
    active = 0
    max_active = 0
    probe_lock = threading.Lock()

    def fake_persist(**_kwargs):
        nonlocal active, max_active
        with probe_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with probe_lock:
            active -= 1
        return {"conversation_id": "test", "message_counter": 1, "feedback_required": False}

    monkeypatch.setattr(chatbot_module, "_persist_chatbot_exchange_unlocked", fake_persist)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda value: chatbot_module._persist_chatbot_exchange(
                    user_id=value,
                    message="q",
                    reply="a",
                    sources=[],
                ),
                range(4),
            )
        )

    assert len(results) == 4
    assert max_active == 1
