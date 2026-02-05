from datetime import datetime
from app.extensions import db


class TimestampMixin:
    """Mixin 类，为模型添加 created_at 和 updated_at 时间戳字段"""
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


