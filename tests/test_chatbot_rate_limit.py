"""Per-user chatbot rate limiting."""

import pytest

from app import create_app, db
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['CHATBOT_BURST_LIMIT_PER_MINUTE'] = 2
    app.config['CHATBOT_DAILY_MESSAGE_LIMIT'] = 0  # daily check off here

    with app.app_context():
        db.create_all()
        user = User(
            email='chat@example.com',
            username='chat_user',
            is_verified=True,
        )
        user.password = 'password123'
        db.session.add(user)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def auth_client(app):
    client = app.test_client()
    client.post(
        '/auth/login',
        data={'email': 'chat@example.com', 'password': 'password123'},
        follow_redirects=True,
    )
    return client


def test_burst_limit_returns_429(auth_client, mocker):
    # Reset the module-global bucket so other tests cannot interfere.
    from app.blueprints import chatbot as chatbot_bp

    chatbot_bp._rate_buckets.clear()

    mocker.patch.object(
        chatbot_bp,
        '_build_chat_response_payload',
        return_value=({'reply': 'ok', 'sources': [], 'conversation_id': 'x',
                       'message_counter': 1, 'feedback_required': False,
                       'quick_questions': []}, None),
    )

    first = auth_client.post('/api/chat', json={'message': 'hello'})
    second = auth_client.post('/api/chat', json={'message': 'hello again'})
    third = auth_client.post('/api/chat', json={'message': 'one too many'})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.get_json()['rate_limited'] is True


def test_burst_limit_disabled_when_zero(auth_client, mocker):
    from app.blueprints import chatbot as chatbot_bp

    chatbot_bp._rate_buckets.clear()
    auth_client.application.config['CHATBOT_BURST_LIMIT_PER_MINUTE'] = 0

    mocker.patch.object(
        chatbot_bp,
        '_build_chat_response_payload',
        return_value=({'reply': 'ok', 'sources': [], 'conversation_id': 'x',
                       'message_counter': 1, 'feedback_required': False,
                       'quick_questions': []}, None),
    )

    for _ in range(5):
        response = auth_client.post('/api/chat', json={'message': 'hello'})
        assert response.status_code == 200
