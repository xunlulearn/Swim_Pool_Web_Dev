from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_login import LoginManager
from flask import current_app

db = SQLAlchemy()
mail = Mail()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    from app.models.user import User
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        db.session.rollback()
        try:
            current_app.logger.exception('Failed to load user from session.')
        except Exception:
            pass
        return None
