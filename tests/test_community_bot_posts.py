from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.content import Post
from app.models.user import User


def _contains_cjk(value):
    return any('一' <= char <= '鿿' for char in value)


# 2026-06-11 is a Thursday (weekday schedule 07:00-21:30 SGT).
# 10:30 UTC == 18:30 SGT, comfortably inside the buffered window.
IN_WINDOW_NOW = datetime(2026, 6, 11, 10, 30, 0)
# 19:00 UTC == 03:00 SGT next day: middle of the night.
NIGHT_NOW = datetime(2026, 6, 11, 19, 0, 0)
# 23:10 UTC (prev day) == 07:10 SGT: open, but within the 30-min edge buffer.
EDGE_NOW = datetime(2026, 6, 10, 23, 10, 0)


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


def _force_act(monkeypatch):
    """Make every probability gate fire deterministically."""
    from app.services import community_bot

    monkeypatch.setattr(community_bot.random, 'random', lambda: 0.0)


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


def test_ensure_bot_accounts_skips_resync_when_seeded(app):
    from app.services.community_bot import ensure_bot_accounts

    with app.app_context():
        first = ensure_bot_accounts()
        second = ensure_bot_accounts()

        assert first['created'] == 50
        assert second == {'created': 0, 'updated': 0, 'skipped': True}


def test_chinese_bot_accounts_use_chinese_post_templates(app):
    from app.models.bot import BotAccount
    from app.services.community_bot import CHINESE_PERSONA_KEYS, _build_post, ensure_bot_accounts

    with app.app_context():
        ensure_bot_accounts()

        for account in BotAccount.query.filter(BotAccount.persona_key.in_(CHINESE_PERSONA_KEYS)).all():
            title, body = _build_post(account, now=IN_WINDOW_NOW)

            assert _contains_cjk(title)
            assert _contains_cjk(body)


def test_community_post_tick_creates_post_and_activity_log(app, monkeypatch):
    from app.models.bot import BotAccount, BotActivityLog, BotDailyPostPlan
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick

    _force_act(monkeypatch)

    with app.app_context():
        ensure_bot_accounts()
        db.session.add(BotDailyPostPlan(day='2026-06-11', target_count=2))
        for account in BotAccount.query.all():
            account.next_run_at = IN_WINDOW_NOW - timedelta(minutes=5)
        db.session.commit()

        result = run_community_post_tick(now=IN_WINDOW_NOW)

        assert result['ok'] is True
        assert result['action'] == 'posted'
        assert Post.query.count() == 1
        post = Post.query.first()
        assert post.author.is_bot is True
        assert post.category in {'general', 'squad', 'lostfound', 'tutorial'}
        assert BotActivityLog.query.filter_by(status='posted', post_id=post.id).count() >= 1
        # Post timestamps are scattered off the exact tick boundary but
        # never into the future.
        assert post.created_at <= IN_WINDOW_NOW
        assert post.created_at >= IN_WINDOW_NOW - timedelta(minutes=20)


def test_community_post_tick_skips_outside_operating_hours(app, monkeypatch):
    from app.models.report import PoolReport
    from app.services.community_bot import run_community_post_tick

    _force_act(monkeypatch)

    with app.app_context():
        result = run_community_post_tick(now=NIGHT_NOW)

        assert result['ok'] is True
        assert result['action'] == 'skipped'
        assert result['reason'] == 'outside_operating_hours'
        assert Post.query.count() == 0
        assert PoolReport.query.count() == 0


def test_community_post_tick_skips_inside_opening_edge_buffer(app, monkeypatch):
    from app.services.community_bot import run_community_post_tick

    _force_act(monkeypatch)

    with app.app_context():
        result = run_community_post_tick(now=EDGE_NOW)

        assert result['action'] == 'skipped'
        assert result['reason'] == 'outside_operating_hours'
        assert Post.query.count() == 0


def test_community_post_tick_randomized_wait_skips_without_burning_quota(app, monkeypatch):
    from app.models.bot import BotDailyPostPlan
    from app.services import community_bot
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick

    # Gate never fires this tick.
    monkeypatch.setattr(community_bot.random, 'random', lambda: 0.999999)

    with app.app_context():
        ensure_bot_accounts()
        db.session.add(BotDailyPostPlan(
            day='2026-06-11',
            target_count=2,
            report_target_count=2,
            comment_target_count=2,
            like_target_count=2,
        ))
        db.session.commit()

        result = run_community_post_tick(now=IN_WINDOW_NOW)

        assert result['action'] == 'skipped'
        assert result['reason'] == 'randomized_wait'
        assert Post.query.count() == 0


def test_bot_report_is_decoupled_from_posting(app, monkeypatch):
    from app.models.bot import BotDailyPostPlan
    from app.models.report import PoolReport
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick
    from app.services.weather_engine import PoolStatus, weather_engine

    _force_act(monkeypatch)
    monkeypatch.setattr(
        weather_engine,
        "get_overall_status",
        lambda: (PoolStatus.GREEN, "Pool is Open", {"reason": "test"}),
    )

    with app.app_context():
        ensure_bot_accounts()
        db.session.add(BotDailyPostPlan(
            day='2026-06-11',
            target_count=0,  # no posts today
            report_target_count=3,
            comment_target_count=0,
            like_target_count=0,
        ))
        db.session.commit()

        result = run_community_post_tick(now=IN_WINDOW_NOW)

        # No post was made, yet a report still went out.
        assert result['action'] == 'skipped'
        assert result['report']['action'] == 'posted'
        report = PoolReport.query.one()
        reporter = db.session.get(User, report.user_id)
        assert reporter.is_bot is True
        assert report.status == "Open"
        assert report.created_at <= IN_WINDOW_NOW


def test_bot_report_uses_closed_status_when_engine_red(app, monkeypatch):
    from app.models.bot import BotDailyPostPlan
    from app.models.report import PoolReport
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick
    from app.services.weather_engine import PoolStatus, weather_engine

    _force_act(monkeypatch)
    monkeypatch.setattr(
        weather_engine,
        "get_overall_status",
        lambda: (PoolStatus.RED, "Pool Closed due to Lightning Alert", {"reason": "lightning"}),
    )

    with app.app_context():
        ensure_bot_accounts()
        db.session.add(BotDailyPostPlan(
            day='2026-06-11',
            target_count=0,
            report_target_count=1,
            comment_target_count=0,
            like_target_count=0,
        ))
        db.session.commit()

        run_community_post_tick(now=IN_WINDOW_NOW)

        assert PoolReport.query.one().status == "Closed"


def test_build_post_matches_time_bucket(app):
    from app.models.bot import BotAccount
    from app.services import community_bot
    from app.services.community_bot import _build_post, ensure_bot_accounts

    # 01:00 UTC == 09:00 SGT -> morning bucket.
    morning_now = datetime(2026, 6, 11, 1, 0, 0)

    with app.app_context():
        ensure_bot_accounts()
        account = BotAccount.query.filter_by(persona_key='daniel_src').one()  # zh general

        zh_general = community_bot.CHINESE_POST_TEMPLATES['general']
        morning_titles = {
            title for title, _ in (
                zh_general[community_bot.BUCKET_ANY] + zh_general[community_bot.BUCKET_MORNING]
            )
        }
        evening_titles = {title for title, _ in zh_general[community_bot.BUCKET_EVENING]}

        for _ in range(20):
            title, _body = _build_post(account, now=morning_now)
            assert title in morning_titles
            assert title not in evening_titles


def test_build_post_avoids_recently_used_titles(app):
    from app.models.bot import BotAccount
    from app.services.community_bot import _build_post, ensure_bot_accounts

    with app.app_context():
        ensure_bot_accounts()
        account = BotAccount.query.filter_by(persona_key='daniel_src').one()

        seen = set()
        # Simulate several days of posting; each chosen title is persisted
        # as a bot post, so the next pick must avoid it while options last.
        for _ in range(3):
            title, body = _build_post(account, now=IN_WINDOW_NOW)
            assert title not in seen
            seen.add(title)
            db.session.add(Post(
                title=title,
                body=body,
                category='general',
                author_id=account.user_id,
                created_at=IN_WINDOW_NOW,
                updated_at=IN_WINDOW_NOW,
            ))
            db.session.commit()


def test_bot_comments_prioritize_unanswered_human_posts(app, monkeypatch):
    from app.models.bot import BotDailyPostPlan
    from app.models.content import Comment
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick

    _force_act(monkeypatch)

    with app.app_context():
        ensure_bot_accounts()
        human = User(
            email='human@example.com', username='human_user',
            is_verified=True, nickname='Human',
        )
        db.session.add(human)
        db.session.flush()
        human_post = Post(
            title='有人知道储物柜怎么租吗？',
            body='第一次去 SRC，想问一下储物柜是投币的还是要去前台登记？',
            category='general',
            author_id=human.id,
            created_at=IN_WINDOW_NOW - timedelta(hours=3),
            updated_at=IN_WINDOW_NOW - timedelta(hours=3),
        )
        db.session.add(human_post)
        db.session.add(BotDailyPostPlan(
            day='2026-06-11',
            target_count=0,
            report_target_count=0,
            comment_target_count=2,
            like_target_count=0,
        ))
        db.session.commit()

        result = run_community_post_tick(now=IN_WINDOW_NOW)

        assert result['comment']['action'] == 'posted'
        assert result['comment']['post_id'] == human_post.id
        comment = Comment.query.one()
        commenter = db.session.get(User, comment.author_id)
        assert commenter.is_bot is True
        # Chinese post gets a Chinese-persona reply.
        assert _contains_cjk(comment.body)
        assert comment.author_id != human_post.author_id


def test_bot_likes_prefer_human_posts_and_never_duplicate(app, monkeypatch):
    from app.models.bot import BotDailyPostPlan
    from app.models.interaction import Like
    from app.services.community_bot import ensure_bot_accounts, run_community_post_tick

    _force_act(monkeypatch)

    with app.app_context():
        ensure_bot_accounts()
        human = User(
            email='human@example.com', username='human_user',
            is_verified=True, nickname='Human',
        )
        db.session.add(human)
        db.session.flush()
        human_post = Post(
            title='First swim done!',
            body='Finally managed 20 laps without stopping. Feels great.',
            category='general',
            author_id=human.id,
            created_at=IN_WINDOW_NOW - timedelta(hours=2),
            updated_at=IN_WINDOW_NOW - timedelta(hours=2),
        )
        db.session.add(human_post)
        db.session.add(BotDailyPostPlan(
            day='2026-06-11',
            target_count=0,
            report_target_count=0,
            comment_target_count=0,
            like_target_count=5,
        ))
        db.session.commit()

        first = run_community_post_tick(now=IN_WINDOW_NOW)
        second = run_community_post_tick(now=IN_WINDOW_NOW + timedelta(minutes=30))

        assert first['like']['action'] == 'posted'
        assert first['like']['post_id'] == human_post.id
        assert second['like']['action'] == 'posted'
        likes = Like.query.all()
        # No duplicate (user, post) pair.
        assert len({(like.user_id, like.post_id) for like in likes}) == len(likes)
        likers = {db.session.get(User, like.user_id).is_bot for like in likes}
        assert likers == {True}


def test_first_community_post_tick_seeds_accounts_and_posts(app, monkeypatch):
    from app.models.bot import BotActivityLog
    from app.services.community_bot import run_community_post_tick

    _force_act(monkeypatch)

    with app.app_context():
        result = run_community_post_tick(now=IN_WINDOW_NOW)

        assert result['ok'] is True
        assert result['action'] == 'posted'
        assert User.query.filter_by(is_bot=True).count() == 50
        assert Post.query.count() == 1
        assert BotActivityLog.query.filter_by(
            action_type='create_post', status='posted'
        ).count() == 1


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
