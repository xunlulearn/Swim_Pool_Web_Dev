import pytest

from app import create_app, db


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_homepage_exposes_chatbot_starter_questions(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-starter-questions-en="Can I go swimming now?' in html
    assert "How does lightning affect pool status?" in html
    assert "\u73b0\u5728\u9002\u5408\u53bb\u6e38\u6cf3\u5417\uff1f" in html
