"""Community feed keyword search."""

from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.content import Post
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')

    with app.app_context():
        db.create_all()
        author = User(
            email='author@example.com',
            username='author_user',
            is_verified=True,
            nickname='Author',
        )
        db.session.add(author)
        db.session.flush()

        now = datetime.utcnow()
        posts = [
            Post(title='Freestyle breathing tips', body='Exhale slowly underwater.',
                 category='tutorial', author_id=author.id,
                 created_at=now - timedelta(hours=3), updated_at=now - timedelta(hours=3)),
            Post(title='Lost goggles at SRC', body='Black goggles near lane 4.',
                 category='lostfound', author_id=author.id,
                 created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=2)),
            Post(title='晚上有人游泳吗', body='想找搭子一起自由泳。',
                 category='squad', author_id=author.id,
                 created_at=now - timedelta(hours=1), updated_at=now - timedelta(hours=1)),
            Post(title='Deleted secret post', body='freestyle hidden',
                 category='general', author_id=author.id, is_deleted=True,
                 created_at=now, updated_at=now),
        ]
        db.session.add_all(posts)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_search_matches_title_case_insensitively(client):
    response = client.get('/social/?q=FREESTYLE')

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Freestyle breathing tips' in html
    assert 'Lost goggles at SRC' not in html


def test_search_matches_body_text(client):
    response = client.get('/social/?q=lane 4')

    html = response.get_data(as_text=True)
    assert 'Lost goggles at SRC' in html
    assert 'Freestyle breathing tips' not in html


def test_search_supports_chinese_keywords(client):
    response = client.get('/social/?q=搭子')

    html = response.get_data(as_text=True)
    assert '晚上有人游泳吗' in html
    assert 'Lost goggles at SRC' not in html


def test_search_excludes_soft_deleted_posts(client):
    response = client.get('/social/?q=hidden')

    html = response.get_data(as_text=True)
    assert 'Deleted secret post' not in html
    assert 'No posts match' in html


def test_search_combines_with_category_filter(client):
    response = client.get('/social/?q=freestyle&category=lostfound')

    html = response.get_data(as_text=True)
    assert 'Freestyle breathing tips' not in html


def test_sql_wildcards_are_escaped(client):
    response = client.get('/social/?q=%25')  # a literal '%'

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    # '%' appears in no post, so nothing should match.
    assert 'No posts match' in html


def test_empty_query_shows_normal_feed(client):
    response = client.get('/social/?q=')

    html = response.get_data(as_text=True)
    assert 'Freestyle breathing tips' in html
    assert 'Lost goggles at SRC' in html
