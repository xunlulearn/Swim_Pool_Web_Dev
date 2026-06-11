from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.content import Post
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['CRON_SECRET'] = 'test-cron-secret'

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_ensure_bot_accounts_creates_50_enabled_bot_users(app):
    from app.models.bot import BotAccount
    from app.services.community_bot import ensure_bot_accounts

    with app.app_context():
        result = ensure_bot_accounts()

        assert result['created'] == 50
        assert BotAccount.query.count() == 50
        assert User.query.filter_by(is_bot=True).count() == 50
        assert BotAccount.query.filter_by(enabled=True).count() == 50


def test_community_post_tick_creates_post_and_activity_log(app):
    from app.models.bot import BotAccount, BotActivityLog, BotDailyPostPlan
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick

    now = datetime(2026, 6, 11, 10, 30, 0)

    with app.app_context():
        ensure_bot_accounts()
        db.session.add(BotDailyPostPlan(day='2026-06-11', target_count=2))
        for account in BotAccount.query.all():
            account.next_run_at = now - timedelta(minutes=5)
        db.session.commit()

        result = run_community_post_tick(now=now)

        assert result['ok'] is True
        assert result['action'] == 'posted'
        assert Post.query.count() == 1
        post = Post.query.first()
        assert post.author.is_bot is True
        assert post.category in {'general', 'squad', 'lostfound', 'tutorial'}
        assert BotActivityLog.query.filter_by(status='posted', post_id=post.id).count() == 1


def test_first_community_post_tick_seeds_accounts_and_posts(app):
    from app.models.bot import BotActivityLog
    from app.services.community_bot import run_community_post_tick

    now = datetime(2026, 6, 11, 10, 30, 0)

    with app.app_context():
        result = run_community_post_tick(now=now)

        assert result['ok'] is True
        assert result['action'] == 'posted'
        assert User.query.filter_by(is_bot=True).count() == 50
        assert Post.query.count() == 1
        assert BotActivityLog.query.filter_by(status='posted').count() == 1


def test_community_post_cron_requires_secret(client):
    response = client.get('/api/cron/community-posts')

    assert response.status_code == 404


def test_community_post_cron_runs_with_bearer_secret(client, app):
    from app.models.bot import BotAccount, BotDailyPostPlan

    now = datetime.utcnow()

    with app.app_context():
        db.session.add(BotDailyPostPlan(day=(now + timedelta(hours=8)).date().isoformat(), target_count=2))
        db.session.commit()

    response = client.get(
        '/api/cron/community-posts',
        headers={'Authorization': 'Bearer test-cron-secret'},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert data['action'] in {'posted', 'skipped'}

    with app.app_context():
        assert BotAccount.query.count() == 50
