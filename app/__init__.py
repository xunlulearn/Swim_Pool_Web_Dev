import os
import hmac
import secrets
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, session
from datetime import datetime, timedelta, timezone
from itsdangerous import URLSafeTimedSerializer, BadData
from .config import config
from .extensions import db, mail, login_manager

# Singapore Timezone (UTC+8)
SGT = timezone(timedelta(hours=8))

def create_app(config_name=None):
    if config_name is None:
        config_name = (
            os.environ.get('FLASK_CONFIG')
            or os.environ.get('APP_ENV')
            or ('production' if (os.environ.get('FLASK_ENV') or '').lower() == 'production' else 'development')
        )
    if config_name not in config:
        config_name = 'default'

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    if config_name == 'production':
        secret_key = app.config.get('SECRET_KEY') or ''
        if secret_key in {'', 'dev-key-please-change', 'change-me-in-production'}:
            raise RuntimeError('SECRET_KEY must be set to a strong value in production.')
        if not app.config.get('SQLALCHEMY_DATABASE_URI'):
            raise RuntimeError('SQLALCHEMY_DATABASE_URI must be set in production.')
    
    # Jinja2 filter: Convert UTC to Singapore Time
    @app.template_filter('sgt')
    def to_singapore_time(dt):
        """Convert UTC datetime to Singapore Time (UTC+8)"""
        if dt is None:
            # 返回当前时间作为默认值，避免后续 .strftime() 调用失败
            dt = datetime.utcnow()
        # Assume dt is naive UTC, make it aware then convert
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(SGT)

    # Initialize extensions
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

    def csrf_error_response():
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': 'Invalid or missing CSRF token.'}), 400
        flash('Your session expired. Please try again.', 'error')
        return redirect(request.referrer or url_for('index'))

    def get_csrf_serializer():
        return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='csrf-token')

    def generate_csrf_token():
        raw_token = session.get('_csrf_token')
        if not raw_token:
            raw_token = secrets.token_urlsafe(32)
            session['_csrf_token'] = raw_token
        return get_csrf_serializer().dumps(raw_token)

    def is_valid_csrf_token(token):
        if not token:
            return False
        try:
            raw_token = get_csrf_serializer().loads(
                token,
                max_age=int(app.config.get('WTF_CSRF_TIME_LIMIT') or 3600),
            )
        except BadData:
            return False

        session_token = session.get('_csrf_token')
        if not session_token:
            return False
        return hmac.compare_digest(raw_token, session_token)

    @app.before_request
    def enforce_csrf_protection():
        if not app.config.get('WTF_CSRF_ENABLED', True):
            return None
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None
        if request.endpoint == 'static':
            return None

        csrf_token = (
            request.form.get('csrf_token')
            or request.headers.get('X-CSRFToken')
            or request.headers.get('X-CSRF-Token')
        )
        if not is_valid_csrf_token(csrf_token):
            return csrf_error_response()
        return None

    app.jinja_env.globals['csrf_token'] = generate_csrf_token

    # Register blueprints
    from .blueprints.weather import weather_bp
    app.register_blueprint(weather_bp)
    
    from .blueprints.auth import auth_bp
    app.register_blueprint(auth_bp)

    from .blueprints.social import social_bp
    app.register_blueprint(social_bp)

    from .blueprints.misc import misc_bp
    app.register_blueprint(misc_bp)

    from .blueprints.live_status import live_status_bp
    app.register_blueprint(live_status_bp)

    @app.route('/')
    def index():
        return render_template('index.html')

    # Context processor: inject unread message count into all templates
    @app.context_processor
    def inject_unread_count():
        from flask_login import current_user
        unread_message_count = 0
        if current_user.is_authenticated and current_user.is_verified:
            from .models.private_message import PrivateMessage
            unread_message_count = PrivateMessage.query.filter_by(
                receiver_id=current_user.id,
                is_read=False
            ).count()
        return dict(unread_message_count=unread_message_count)

    return app
