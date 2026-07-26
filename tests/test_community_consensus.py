"""Community consensus must be driven by humans, never by bot echo."""

from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.report import PoolReport
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _add_reports(*, count, status, is_bot, start_index=0):
    now = datetime.utcnow()
    for index in range(count):
        user = User(
            email=f'{"bot" if is_bot else "human"}{start_index + index}@example.com',
            username=f'{"bot" if is_bot else "human"}_user_{start_index + index}',
            is_verified=True,
            is_bot=is_bot,
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(PoolReport(
            status=status,
            user_id=user.id,
            created_at=now - timedelta(minutes=1 + index),
        ))
    db.session.commit()


def test_bot_reports_alone_never_form_consensus(app):
    from app.services.weather_engine import weather_engine

    with app.app_context():
        _add_reports(count=5, status='Open', is_bot=True)

        assert weather_engine._get_community_consensus() is None


def test_five_fresh_human_reports_form_consensus(app):
    from app.services.weather_engine import weather_engine

    with app.app_context():
        _add_reports(count=5, status='Closed', is_bot=False)

        assert weather_engine._get_community_consensus() == 'Closed'


def test_bot_reports_do_not_dilute_human_consensus(app):
    from app.services.weather_engine import weather_engine

    with app.app_context():
        # Five agreeing humans...
        _add_reports(count=5, status='Closed', is_bot=False)
        # ...and a fresher bot disagreeing (echoing the weather engine).
        _add_reports(count=1, status='Open', is_bot=True, start_index=100)

        # The bot report must not break the human consensus.
        assert weather_engine._get_community_consensus() == 'Closed'
