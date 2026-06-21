from sqlalchemy import event

import pytest

from app import create_app, db
from app.models.content import Comment, Post
from app.models.interaction import Like
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


def _seed_feed_posts(count=6):
    users = []
    posts = []
    for index in range(count):
        user = User(
            email=f'user{index}@example.com',
            username=f'user{index}',
            nickname=f'User {index}',
            avatar=b'a' * 2048,
            avatar_mimetype='image/png',
        )
        user.password = 'password123'
        db.session.add(user)
        users.append(user)

    db.session.flush()

    for index, user in enumerate(users):
        post = Post(
            title=f'Post {index}',
            body='A community post body.',
            author_id=user.id,
            image=b'i' * 2048,
            image_mimetype='image/png',
        )
        db.session.add(post)
        posts.append(post)

    db.session.flush()

    for post in posts:
        db.session.add(Comment(body='hello', author_id=post.author_id, post_id=post.id))
        db.session.add(Like(user_id=post.author_id, post_id=post.id))

    db.session.commit()
    return users, posts


def test_feed_does_not_inline_blob_images(client, app):
    with app.app_context():
        _seed_feed_posts(count=1)

    response = client.get('/social/')

    assert response.status_code == 200
    assert b'data:image/' not in response.data
    assert b'/social/media/post/' in response.data
    assert b'/social/media/user/' in response.data


def test_feed_uses_batched_queries_for_counts_and_authors(client, app):
    with app.app_context():
        _seed_feed_posts(count=6)

    statements = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)

    with app.app_context():
        event.listen(db.engine, 'before_cursor_execute', record_statement)
        try:
            response = client.get('/social/')
        finally:
            event.remove(db.engine, 'before_cursor_execute', record_statement)

    assert response.status_code == 200
    assert len(statements) <= 6


def test_feed_media_endpoints_stream_blob_images(client, app):
    with app.app_context():
        users, posts = _seed_feed_posts(count=1)
        user_id = users[0].id
        post_id = posts[0].id

    avatar_response = client.get(f'/social/media/user/{user_id}/avatar')
    post_image_response = client.get(f'/social/media/post/{post_id}/image')

    assert avatar_response.status_code == 200
    assert avatar_response.mimetype == 'image/png'
    assert avatar_response.data == b'a' * 2048
    assert post_image_response.status_code == 200
    assert post_image_response.mimetype == 'image/png'
    assert post_image_response.data == b'i' * 2048
