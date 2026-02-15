import pytest
from datetime import datetime, timedelta

from app import create_app, db
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def create_user(email='user@example.com', username='user1', password='password123', verified=False):
    user = User(email=email, username=username, is_verified=verified)
    user.password = password
    db.session.add(user)
    db.session.commit()
    return user


def test_login_no_super_admin_backdoor(client, app):
    response = client.post(
        '/auth/login',
        data={'email': '563431770@qq.com', 'password': 'anything'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Invalid email or password.' in response.data

    with app.app_context():
        assert User.query.filter_by(email='563431770@qq.com').first() is None


def test_auth_routes_handle_missing_email_without_500(client):
    response_login = client.post('/auth/login', data={'password': 'x'}, follow_redirects=True)
    assert response_login.status_code == 200

    response_register = client.post(
        '/auth/register',
        data={'username': 'u1', 'password': 'password123', 'password_confirm': 'password123'},
        follow_redirects=True,
    )
    assert response_register.status_code == 200

    response_reset = client.post('/auth/password/reset-request', data={}, follow_redirects=True)
    assert response_reset.status_code == 200


def test_password_reset_flow_has_same_entry_for_existing_and_missing_account(client, app):
    with app.app_context():
        create_user(email='exists@example.com', username='exists_user', verified=True)

    response_existing = client.post(
        '/auth/password/reset-request',
        data={'email': 'exists@example.com'},
        follow_redirects=True,
    )
    assert response_existing.status_code == 200
    assert response_existing.request.path == '/auth/password/reset'

    other_client = app.test_client()
    response_missing = other_client.post(
        '/auth/password/reset-request',
        data={'email': 'missing@example.com'},
        follow_redirects=True,
    )
    assert response_missing.status_code == 200
    assert response_missing.request.path == '/auth/password/reset'


def test_auth_token_checks_purpose_and_expiry(app):
    with app.app_context():
        user = create_user(email='token@example.com', username='token_user', verified=True)
        token = user.generate_auth_token(purpose='email_confirm')

        assert User.verify_auth_token(token, purpose='email_confirm', max_age=60).id == user.id
        assert User.verify_auth_token(token, purpose='password_reset', max_age=60) is None
        assert User.verify_auth_token(token, purpose='email_confirm', max_age=-1) is None


def test_verify_otp_locks_after_too_many_attempts(client, app):
    with app.app_context():
        user = create_user(email='otp@example.com', username='otp_user', verified=False)
        user.otp_code = '123456'
        user.otp_expiry = datetime.utcnow() + timedelta(minutes=10)
        db.session.commit()
        user_id = user.id

    client.post('/auth/login', data={'email': 'otp@example.com', 'password': 'password123'}, follow_redirects=True)

    with client.session_transaction() as session:
        session['otp_flow'] = 'verify'
        session['otp_user_id'] = user_id
        session['otp_attempts'] = 0

    response = None
    for _ in range(5):
        response = client.post('/auth/verify', data={'otp_code': '000000'}, follow_redirects=True)

    assert response is not None
    assert response.status_code == 200
    assert b'Too many failed attempts' in response.data

    with app.app_context():
        updated = User.query.filter_by(email='otp@example.com').first()
        assert updated.otp_code is None
