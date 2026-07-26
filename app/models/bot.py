from app.extensions import db
from .utils import TimestampMixin


class BotAccount(TimestampMixin, db.Model):
    __tablename__ = 'bot_accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    persona_key = db.Column(db.String(64), nullable=False, unique=True)
    display_name = db.Column(db.String(64), nullable=False)
    archetype = db.Column(db.String(40), nullable=False)
    voice = db.Column(db.String(160), nullable=False)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    daily_weight = db.Column(db.Integer, default=1, nullable=False)
    last_post_at = db.Column(db.DateTime)
    next_run_at = db.Column(db.DateTime)

    user = db.relationship('User', backref=db.backref('bot_account', uselist=False))


class BotDailyPostPlan(TimestampMixin, db.Model):
    __tablename__ = 'bot_daily_post_plans'

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False, unique=True)
    target_count = db.Column(db.Integer, nullable=False)
    # Daily targets for non-post bot activity (nullable so legacy rows load;
    # the scheduler backfills them lazily).
    report_target_count = db.Column(db.Integer)
    comment_target_count = db.Column(db.Integer)
    like_target_count = db.Column(db.Integer)


class BotActivityLog(db.Model):
    __tablename__ = 'bot_activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    bot_account_id = db.Column(db.Integer, db.ForeignKey('bot_accounts.id'))
    action_type = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=db.func.now())

    bot_account = db.relationship('BotAccount', backref=db.backref('activity_logs', lazy='dynamic'))
    post = db.relationship('Post')
