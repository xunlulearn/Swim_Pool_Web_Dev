from flask import Flask, render_template
from .config import config
from .extensions import db, mail, login_manager

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

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

    @app.route('/')
    def index():
        return render_template('index.html')

    return app
