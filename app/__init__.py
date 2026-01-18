from flask import Flask, render_template
from datetime import datetime, timedelta, timezone
from .config import config
from .extensions import db, mail, login_manager

# Singapore Timezone (UTC+8)
SGT = timezone(timedelta(hours=8))

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Jinja2 filter: Convert UTC to Singapore Time
    @app.template_filter('sgt')
    def to_singapore_time(dt):
        """Convert UTC datetime to Singapore Time (UTC+8)"""
        if dt is None:
            return ''
        # Assume dt is naive UTC, make it aware then convert
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(SGT)

    # Initialize extensions
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

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

    return app
