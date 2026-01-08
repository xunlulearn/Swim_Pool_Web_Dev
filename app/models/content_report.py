from app.extensions import db


class ContentReport(db.Model):
    """内容举报表"""
    __tablename__ = 'content_reports'
    
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    target_type = db.Column(db.String(20), nullable=False)  # 'post' | 'comment'
    target_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(100), nullable=False)  # 广告、辱骂、无关内容等
    status = db.Column(db.String(20), default='pending')  # pending, resolved, rejected
    created_at = db.Column(db.DateTime, default=db.func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'reporter': self.reporter.username,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'reason': self.reason,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
