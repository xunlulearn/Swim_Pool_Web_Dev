from app.extensions import db
from datetime import datetime

class PoolReport(db.Model):
    __tablename__ = 'pool_reports'

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(10), nullable=False) # "Open", "Closed"
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to User for displaying name
    user = db.relationship('User', backref=db.backref('reports', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'user': self.user.username, # simplified for now
            'timestamp': self.created_at.isoformat()
        }
