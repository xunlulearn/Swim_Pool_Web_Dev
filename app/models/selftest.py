from datetime import datetime

from app.extensions import db


class ChatbotSelftestRun(db.Model):
    """Latest chatbot self-test results, accumulated one question per request.

    Each Actions-triggered run gets a run_key; per-question cron calls append
    into results_json so no single serverless request runs long enough to hit
    platform timeouts.
    """

    __tablename__ = 'chatbot_selftest_runs'

    id = db.Column(db.Integer, primary_key=True)
    run_key = db.Column(db.String(80), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    total_questions = db.Column(db.Integer, nullable=False, default=0)
    results_json = db.Column(db.Text, nullable=False, default='[]')
