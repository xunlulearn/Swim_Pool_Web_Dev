from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.content import Post
from app.models.user import User


def _contains_cjk(value):
    return any('\u4e00' <= char <= '\u9fff' for char in value)


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
    from app.services.community_bot import CHINESE_PERSONA_KEYS, ensure_bot_accounts

    with app.app_context():
        result = ensure_bot_accounts()

        assert result['created'] == 50
        assert BotAccount.query.count() == 50
        assert User.query.filter_by(is_bot=True).count() == 50
        assert BotAccount.query.filter_by(enabled=True).count() == 50
        avatar_urls = [user.avatar_url for user in User.query.filter_by(is_bot=True).all()]
        assert all(url for url in avatar_urls)
        assert len(set(avatar_urls)) == 50
        assert not any('robohash.org' in url for url in avatar_urls)
        assert not any('/bottts' in url for url in avatar_urls)
        assert not any('/avataaars' in url for url in avatar_urls)
        assert not any('/open-peeps' in url for url in avatar_urls)
        assert not any('/notionists' in url for url in avatar_urls)
        assert not any('/big-smile' in url for url in avatar_urls)
        assert not any('/adventurer' in url for url in avatar_urls)
        assert any('picsum.photos' in url for url in avatar_urls)
        assert any('loremflickr.com/96/96/landscape' in url for url in avatar_urls)
        assert any('loremflickr.com/96/96/cat' in url for url in avatar_urls)
        assert any('loremflickr.com/96/96/ocean' in url for url in avatar_urls)
        assert any('/pixel-art/svg' in url for url in avatar_urls)
        assert any('/shapes/svg' in url for url in avatar_urls)
        chinese_accounts = BotAccount.query.filter(BotAccount.persona_key.in_(CHINESE_PERSONA_KEYS)).all()
        assert len(chinese_accounts) == 20
        assert all(_contains_cjk(account.display_name) for account in chinese_accounts)
        assert all(_contains_cjk(account.voice) for account in chinese_accounts)
        assert all(_contains_cjk(account.user.nickname) for account in chinese_accounts)


def test_chinese_bot_accounts_use_chinese_post_templates(app):
    from app.models.bot import BotAccount
    from app.services.community_bot import CHINESE_PERSONA_KEYS, _build_post, ensure_bot_accounts

    with app.app_context():
        ensure_bot_accounts()

        for account in BotAccount.query.filter(BotAccount.persona_key.in_(CHINESE_PERSONA_KEYS)).all():
            title, body = _build_post(account)

            assert _contains_cjk(title)
            assert _contains_cjk(body)


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


def test_community_post_tick_records_homepage_pool_status_report(app, monkeypatch):
    from app.models.bot import BotAccount, BotDailyPostPlan
    from app.models.report import PoolReport
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick
    from app.services.weather_engine import PoolStatus, weather_engine

    now = datetime(2026, 6, 11, 10, 30, 0)

    monkeypatch.setattr(
        weather_engine,
        "get_overall_status",
        lambda: (PoolStatus.GREEN, "Pool is Open", {"reason": "test"}),
    )

    with app.app_context():
        ensure_bot_accounts()
        db.session.add(BotDailyPostPlan(day='2026-06-11', target_count=2))
        for account in BotAccount.query.all():
            account.next_run_at = now - timedelta(minutes=5)
        db.session.commit()

        result = run_community_post_tick(now=now)

        assert result['ok'] is True
        assert result['action'] == 'posted'

        post = Post.query.first()
        report = PoolReport.query.one()
        assert report.user_id == post.author_id
        assert report.status == "Open"
        assert report.created_at == now


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
