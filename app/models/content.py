from app.extensions import db
from .utils import TimestampMixin


class Post(TimestampMixin, db.Model):
    """帖子模型，支持软删除、置顶、分类"""
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(255))
    category = db.Column(db.String(20), default='general')  # general, squad, lostfound, tutorial
    is_pinned = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)  # 软删除标记
    view_count = db.Column(db.Integer, default=0)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    comments = db.relationship('Comment', backref='post', lazy='dynamic')
    likes = db.relationship('Like', backref='post', lazy='dynamic')
    collections = db.relationship('Collection', backref='post', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body,
            'category': self.category,
            'author': self.author.username,
            'author_id': self.author_id,
            'is_pinned': self.is_pinned,
            'view_count': self.view_count,
            'like_count': self.likes.count(),
            'comment_count': self.comments.filter_by(is_deleted=False).count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'image_url': self.image_url
        }


class Comment(TimestampMixin, db.Model):
    """评论模型，支持软删除"""
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)  # 软删除标记
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'body': self.body,
            'author': self.author.username,
            'author_id': self.author_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
