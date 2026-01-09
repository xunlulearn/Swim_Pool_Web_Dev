import pytest
from app import create_app, db
from app.models.user import User
import io

@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:' # Use in-memory DB for speed
    app.config['WTF_CSRF_ENABLED'] = False # Disable CSRF for easier testing
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_profile_update(client, app):
    # 1. Create and Login User
    with app.app_context():
        user = User(email='test@example.com', username='testuser')
        user.password = 'password123'
        user.is_verified = True
        user.nickname = 'OldNick'
        db.session.add(user)
        db.session.commit()

    # Login
    client.post('/auth/login', data={
        'email': 'test@example.com', 
        'password': 'password123'
    }, follow_redirects=True)

    # 2. Update Profile (Nickname + Avatar)
    avatar_data = b'fake_image_bytes'
    data = {
        'nickname': 'NewNick',
        'avatar': (io.BytesIO(avatar_data), 'avatar.png')
    }
    response = client.post('/social/profile/edit', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    assert b'Profile updated successfully' in response.data

    # 3. Verify DB
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        assert user.nickname == 'NewNick'
        assert user.avatar == avatar_data
        assert user.avatar_mimetype == 'image/png'

def test_password_reset_flow(client, app):
    # 1. Create User
    with app.app_context():
        user = User(email='reset@example.com', username='resetuser')
        user.password = 'oldpass'
        user.is_verified = True
        db.session.add(user)
        db.session.commit()

    # 2. Request Password Reset
    response = client.post('/auth/password/reset-request', data={'email': 'reset@example.com'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'verification code has been sent' in response.data

    # 3. Get OTP from DB
    with app.app_context():
        user = User.query.filter_by(email='reset@example.com').first()
        otp = user.otp_code
        assert otp is not None

    # 4. Reset Password
    response = client.post('/auth/password/reset', data={
        'otp': otp,
        'password': 'newpass123',
        'confirm': 'newpass123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Your password has been updated' in response.data

    # 5. Login with New Password
    response = client.post('/auth/login', data={
        'email': 'reset@example.com',
        'password': 'newpass123'
    }, follow_redirects=True)
    assert b'Login' not in response.data # Should be redirected to index/dashboard
    # Checking for element on index page to confirm login? Or just check current_user
    # Simpler: check if we are redirected to index.
    # Actually client.post follows redirects, so we check response.request.path or content
    
    # Let's check if we can access protected route
    response = client.get('/social/profile', follow_redirects=True)
    assert response.status_code == 200
    assert b'resetuser' in response.data
