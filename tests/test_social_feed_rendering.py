import re

import pytest

from app import create_app, db
from app.models.content import Post
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_bot_post(avatar_url=None):
    bot = User(
        email='bot_daniel_koh@ntupool.local',
        username='bot_daniel_koh',
        nickname='Daniel Koh',
        is_bot=True,
        avatar_url=avatar_url,
    )
    bot.password = 'password123'
    db.session.add(bot)
    db.session.flush()
    post = Post(
        title='Quick pool check for today',
        body='Planning a short swim later.',
        author_id=bot.id,
    )
    db.session.add(post)
    db.session.commit()
    return post.id


def _seed_posts(count, category='general'):
    author = User(
        email='pager@example.com',
        username='pager',
        nickname='Pager',
    )
    author.password = 'password123'
    db.session.add(author)
    db.session.flush()
    for index in range(count):
        db.session.add(Post(
            title=f'Paged post {index + 1}',
            body='Testing pagination rendering.',
            category=category,
            author_id=author.id,
        ))
    db.session.commit()


def test_feed_bot_fallback_avatar_uses_display_name_initial(client, app):
    with app.app_context():
        _seed_bot_post()

    response = client.get('/social/')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(r'<div class="w-10 h-10[^"]*">\s*D\s*</div>', html)


def test_feed_bot_avatar_url_renders_image(client, app):
    avatar_url = 'https://api.dicebear.com/10.x/lorelei/svg?seed=ntupool-daniel_src'
    with app.app_context():
        _seed_bot_post(avatar_url=avatar_url)

    response = client.get('/social/')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'src="{avatar_url}"' in html
    assert not re.search(r'<div class="w-10 h-10[^"]*">\s*D\s*</div>', html)


def test_feed_hides_ai_experiment_badge_for_bot_posts(client, app):
    with app.app_context():
        _seed_bot_post()

    response = client.get('/social/')

    assert response.status_code == 200
    assert 'AI experiment' not in response.get_data(as_text=True)


def test_post_detail_uses_display_name_avatar_initial_and_hides_experiment_badge(client, app):
    with app.app_context():
        post_id = _seed_bot_post()

    response = client.get(f'/social/post/{post_id}')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'AI experiment' not in html
    assert re.search(r'<div class="w-10 h-10[^"]*">\s*D\s*</div>', html)


def test_post_detail_bot_avatar_url_renders_image(client, app):
    avatar_url = 'https://api.dicebear.com/10.x/lorelei/svg?seed=ntupool-daniel_src'
    with app.app_context():
        post_id = _seed_bot_post(avatar_url=avatar_url)

    response = client.get(f'/social/post/{post_id}')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'src="{avatar_url}"' in html


def test_feed_pagination_renders_direct_page_jump_preserving_category(client, app):
    with app.app_context():
        _seed_posts(41, category='squad')

    response = client.get('/social/?category=squad&page=2')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<form action="/social/" method="get"' in html
    assert 'name="category" value="squad"' in html
    assert 'name="page"' in html
    assert 'value="2"' in html
    assert 'max="3"' in html
    assert 'Go' in html
