from app.extensions import db


class PrivateMessage(db.Model):
    """私信模型"""
    __tablename__ = 'private_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')

    def to_dict(self):
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'sender': self.sender.nickname or self.sender.username,
            'receiver_id': self.receiver_id,
            'receiver': self.receiver.nickname or self.receiver.username,
            'body': self.body,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
