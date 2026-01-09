from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask import current_app
from app.extensions import db
from .utils import TimestampMixin


class User(UserMixin, TimestampMixin, db.Model):
    """用户模型，支持角色区分和封禁功能"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    username = db.Column(db.String(64), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255))
    is_verified = db.Column(db.Boolean, default=False)
    avatar_url = db.Column(db.String(255))
    
    # 角色与封禁 (product2.4.md)
    role = db.Column(db.String(20), default='user')  # 'user' | 'admin'
    is_banned = db.Column(db.Boolean, default=False)
    
    # Profile Fields
    nickname = db.Column(db.String(64), default='')
    avatar = db.Column(db.LargeBinary) # BLOB storage for avatar image
    avatar_mimetype = db.Column(db.String(32)) # e.g. 'image/jpeg'
    
    # OTP Fields
    otp_code = db.Column(db.String(6))
    otp_expiry = db.Column(db.DateTime)
    
    # Relationships
    posts = db.relationship('Post', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    likes = db.relationship('Like', backref='user', lazy='dynamic')
    collections = db.relationship('Collection', backref='user', lazy='dynamic')
    content_reports = db.relationship('ContentReport', backref='reporter', lazy='dynamic', 
                                       foreign_keys='ContentReport.reporter_id')

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def generate_auth_token(self, expiration=3600):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        return s.dumps({'confirm': self.id})

    @staticmethod
    def verify_auth_token(token):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token)
        except:
            return None
        return User.query.get(data['confirm'])
    
    def is_admin(self):
        """检查用户是否为管理员"""
        return self.role == 'admin'
    
    def __repr__(self):
        return f'<User {self.username}>'
