"""LLM-generated bot content: template-anchored, validated, always falls
back to static templates on any failure. The API is never touched in tests —
requests.post is mocked."""

import json
from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.content import Post
from app.models.user import User


IN_WINDOW_NOW = datetime(2026, 6, 11, 10, 30, 0)  # 18:30 SGT, Thursday


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _chat_response(content):
    return _FakeResponse({'choices': [{'message': {'content': content}}]})


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['COMMUNITY_BOT_LLM_CONTENT'] = True
    app.config['OPENAI_API_KEY'] = 'test-key'
    app.config['OPENAI_CHAT_MODEL'] = 'gpt-4o-mini'

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _get_bot(persona_key):
    from app.models.bot import BotAccount
    from app.services.community_bot import ensure_bot_accounts

    ensure_bot_accounts()
    return BotAccount.query.filter_by(persona_key=persona_key).one()


def test_post_uses_llm_variant_when_generation_succeeds(app, monkeypatch):
    from app.services import community_bot

    captured = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured['url'] = url
        captured['timeout'] = timeout
        captured['model'] = json['model']
        return _chat_response(
            '{"title": "傍晚想去松松地游一会", "body": "今天想慢慢游二十分钟就好，有同学时间合适的话一起呀。"}'
        )

    monkeypatch.setattr(community_bot.requests, 'post', _fake_post)

    with app.app_context():
        account = _get_bot('avery_laps')  # Chinese squad persona
        title, body, source = community_bot._build_post(account, now=IN_WINDOW_NOW)

        assert source == 'llm'
        assert title == '傍晚想去松松地游一会'
        assert '一起' in body
        assert captured['timeout'] == community_bot.LLM_TIMEOUT_SECONDS
        assert captured['model'] == 'gpt-4o-mini'
        assert captured['url'].endswith('/chat/completions')


def test_post_falls_back_to_template_on_api_failure(app, monkeypatch):
    from app.services import community_bot

    def _boom(*_args, **_kwargs):
        raise community_bot.requests.exceptions.ConnectionError('down')

    monkeypatch.setattr(community_bot.requests, 'post', _boom)

    with app.app_context():
        account = _get_bot('avery_laps')
        title, body, source = community_bot._build_post(account, now=IN_WINDOW_NOW)

        assert source == 'template'
        # Falls back to a real static template for the bot's language.
        candidates = community_bot._template_candidates(
            account, community_bot._time_bucket(IN_WINDOW_NOW)
        )
        assert (title, body) in candidates


def test_post_falls_back_when_language_mismatch(app, monkeypatch):
    from app.services import community_bot

    monkeypatch.setattr(
        community_bot.requests, 'post',
        lambda *a, **k: _chat_response('{"title": "English title", "body": "English body only."}'),
    )

    with app.app_context():
        account = _get_bot('avery_laps')  # Chinese persona must get CJK content
        _title, _body, source = community_bot._build_post(account, now=IN_WINDOW_NOW)

        assert source == 'template'


def test_post_falls_back_when_title_recently_used(app, monkeypatch):
    from app.services import community_bot

    with app.app_context():
        account = _get_bot('avery_laps')
        db.session.add(Post(
            title='重复标题测试', body='b', category='squad',
            author_id=account.user_id,
            created_at=IN_WINDOW_NOW - timedelta(days=1),
            updated_at=IN_WINDOW_NOW - timedelta(days=1),
        ))
        db.session.commit()

        monkeypatch.setattr(
            community_bot.requests, 'post',
            lambda *a, **k: _chat_response('{"title": "重复标题测试", "body": "撞车了的正文。"}'),
        )
        _title, _body, source = community_bot._build_post(account, now=IN_WINDOW_NOW)

        assert source == 'template'


def test_post_falls_back_when_variant_plans_for_a_past_time_of_day(app, monkeypatch):
    from app.services import community_bot

    # 12:30 UTC == 20:30 SGT -> evening bucket; "早上想去" is nonsense then.
    evening_now = datetime(2026, 6, 11, 12, 30, 0)
    monkeypatch.setattr(
        community_bot.requests, 'post',
        lambda *a, **k: _chat_response('{"title": "早上人少想去划几圈", "body": "上午没课想慢慢游一会儿。"}'),
    )

    with app.app_context():
        account = _get_bot('avery_laps')
        _title, _body, source = community_bot._build_post(account, now=evening_now)

        assert source == 'template'


def test_morning_variant_may_plan_for_tonight(app, monkeypatch):
    from app.services import community_bot

    # 01:00 UTC == 09:00 SGT -> morning bucket; planning "今晚" ahead is human.
    morning_now = datetime(2026, 6, 11, 1, 0, 0)
    monkeypatch.setattr(
        community_bot.requests, 'post',
        lambda *a, **k: _chat_response('{"title": "今晚有人约游泳吗", "body": "想提前约个今晚的放松局，慢速友好。"}'),
    )

    with app.app_context():
        account = _get_bot('avery_laps')
        title, _body, source = community_bot._build_post(account, now=morning_now)

        assert source == 'llm'
        assert title == '今晚有人约游泳吗'


def test_llm_disabled_never_calls_api(app, monkeypatch):
    from app.services import community_bot

    app.config['COMMUNITY_BOT_LLM_CONTENT'] = False

    def _must_not_call(*_args, **_kwargs):
        raise AssertionError('requests.post must not be called when disabled')

    monkeypatch.setattr(community_bot.requests, 'post', _must_not_call)

    with app.app_context():
        account = _get_bot('avery_laps')
        _title, _body, source = community_bot._build_post(account, now=IN_WINDOW_NOW)

        assert source == 'template'


def test_at_most_one_llm_call_per_tick(app, monkeypatch):
    from app.services import community_bot

    calls = []

    def _fake_post(*_args, **_kwargs):
        calls.append(1)
        return _chat_response('{"title": "唯一一次调用", "body": "预算内的生成内容。"}')

    monkeypatch.setattr(community_bot.requests, 'post', _fake_post)

    with app.app_context():
        account = _get_bot('avery_laps')
        tick_state = {'llm_calls': 0}

        first = community_bot._build_post(account, now=IN_WINDOW_NOW, tick_state=tick_state)
        second = community_bot._build_post(account, now=IN_WINDOW_NOW, tick_state=tick_state)

        assert first[2] == 'llm'
        assert second[2] == 'template'  # budget spent, no second API call
        assert len(calls) == 1


def test_comment_reacts_to_post_content_via_llm(app, monkeypatch):
    from app.services import community_bot

    captured = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured['user_prompt'] = json['messages'][1]['content']
        return _chat_response('{"comment": "蛙泳收腿慢一点真的有用，我之前也是这个问题。"}')

    monkeypatch.setattr(community_bot.requests, 'post', _fake_post)

    with app.app_context():
        account = _get_bot('chloe_kickboard')  # Chinese tutorial persona
        human = User(email='h@example.com', username='human_x', is_verified=True)
        db.session.add(human)
        db.session.flush()
        post = Post(
            title='蛙泳蹬腿总是不对怎么办',
            body='收腿的时候总感觉很别扭，有没有简单的纠正方法？',
            category='tutorial', author_id=human.id,
            created_at=IN_WINDOW_NOW - timedelta(hours=1),
            updated_at=IN_WINDOW_NOW - timedelta(hours=1),
        )
        db.session.add(post)
        db.session.commit()

        body, source = community_bot._compose_comment(post, account, 'zh')

        assert source == 'llm'
        assert '蛙泳' in body
        # The post content was actually shown to the model.
        assert '蛙泳蹬腿总是不对怎么办' in captured['user_prompt']


def test_comment_falls_back_to_static_template_on_bad_output(app, monkeypatch):
    from app.services import community_bot

    monkeypatch.setattr(
        community_bot.requests, 'post',
        lambda *a, **k: _chat_response('not json at all'),
    )

    with app.app_context():
        account = _get_bot('chloe_kickboard')
        human = User(email='h@example.com', username='human_x', is_verified=True)
        db.session.add(human)
        db.session.flush()
        post = Post(
            title='打卡', body='今天游了一公里。', category='general',
            author_id=human.id,
            created_at=IN_WINDOW_NOW, updated_at=IN_WINDOW_NOW,
        )
        db.session.add(post)
        db.session.commit()

        body, source = community_bot._compose_comment(post, account, 'zh')

        assert source == 'template'
        assert body in community_bot.COMMENT_TEMPLATES['general']['zh']


def test_comment_targets_come_from_first_page_only(app, monkeypatch):
    from app.services import community_bot

    with app.app_context():
        account = _get_bot('daniel_src')
        bot_ids = community_bot._bot_user_ids()
        human = User(email='h@example.com', username='human_x', is_verified=True)
        db.session.add(human)
        db.session.flush()

        # A pinned announcement (newest) and an old lonely post beyond page 1.
        pinned = Post(
            title='置顶公告', body='b', category='general', author_id=human.id,
            is_pinned=True,
            created_at=IN_WINDOW_NOW - timedelta(minutes=5),
            updated_at=IN_WINDOW_NOW - timedelta(minutes=5),
        )
        db.session.add(pinned)
        old_post = Post(
            title='第21条以后的旧帖', body='b', category='general', author_id=human.id,
            created_at=IN_WINDOW_NOW - timedelta(days=2),
            updated_at=IN_WINDOW_NOW - timedelta(days=2),
        )
        db.session.add(old_post)
        # 20 newer bot posts push the old post off page 1.
        from app.models.bot import BotAccount
        bots = BotAccount.query.limit(20).all()
        for index, bot in enumerate(bots):
            db.session.add(Post(
                title=f'页面填充帖 {index}', body='b', category='general',
                author_id=bot.user_id,
                created_at=IN_WINDOW_NOW - timedelta(hours=1, minutes=index),
                updated_at=IN_WINDOW_NOW - timedelta(hours=1, minutes=index),
            ))
        db.session.commit()

        chosen = set()
        for _ in range(30):
            target = community_bot._select_comment_target(IN_WINDOW_NOW, bot_ids)
            assert target is not None
            chosen.add(target.id)

        assert pinned.id not in chosen       # pinned excluded
        assert old_post.id not in chosen     # beyond first page excluded
