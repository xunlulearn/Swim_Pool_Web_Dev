from app.extensions import db
from .utils import TimestampMixin

class Post(TimestampMixin, db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(255))
    visibility = db.Column(db.String(20), default='public') # public, friends
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'body': self.body,
            'author': self.author.username,
            'timestamp': self.created_at,
            'image_url': self.image_url
        }

class Comment(TimestampMixin, db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
