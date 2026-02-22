from datetime import datetime

from app.extensions import db


class LightningHistorySnapshot(db.Model):
    __tablename__ = "lightning_history_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    observed_at_utc = db.Column(db.DateTime, nullable=False, unique=True, index=True)
    observed_at_sgt = db.Column(db.String(40), nullable=False)
    within_15km_count = db.Column(db.Integer, nullable=False, default=0)
    within_30km_count = db.Column(db.Integer, nullable=False, default=0)
    total_valid_count = db.Column(db.Integer, nullable=False, default=0)
    nearest_distance_km = db.Column(db.Float)
    data_source = db.Column(db.String(32), nullable=False, default="live_api")
    points_30km_json = db.Column(db.Text)
    source_record_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
