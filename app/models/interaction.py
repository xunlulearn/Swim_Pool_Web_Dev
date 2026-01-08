from app.extensions import db


class Like(db.Model):
    """点赞表，防止重复点赞"""
    __tablename__ = 'likes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_like'),)


class Collection(db.Model):
    """收藏表，防止重复收藏"""
    __tablename__ = 'collections'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_collection'),)
