"""Chatbot self-test battery: endpoints, accumulation, and public report."""

import json

import pytest

from app import create_app, db


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['CRON_SECRET'] = 'test-cron-secret'

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _fake_rag_app(answer='测试答案', intent='knowledge_base'):
    class _App:
        def invoke(self, _payload):
            return {
                'answer': answer,
                'intent': intent,
                'mode': intent,
                'context': ['chunk'],
                'sources': ['kb://test'],
                'quick_questions': [],
            }

    return _App()


def test_selftest_endpoint_requires_secret(client):
    response = client.get('/api/cron/chatbot-selftest?run=r1&index=0')

    assert response.status_code == 404


def test_selftest_runs_question_and_public_report_shows_it(client, app, monkeypatch):
    from app.services.chatbot import selftest as selftest_module

    monkeypatch.setattr(
        'app.services.chatbot.get_rag_app', lambda **_kw: _fake_rag_app()
    )
    monkeypatch.setattr(
        'app.blueprints.chatbot._build_homepage_context', lambda *_a, **_k: []
    )

    response = client.get(
        '/api/cron/chatbot-selftest?run=r1&index=0',
        headers={'Authorization': 'Bearer test-cron-secret'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True
    assert payload['completed'] == 1
    assert payload['total'] == selftest_module.selftest_total()

    report = client.get('/api/chatbot-selftest/latest')
    assert report.status_code == 200
    data = report.get_json()
    assert data['run_key'] == 'r1'
    assert data['completed'] == 1
    first = data['results'][0]
    assert first['question'] == '现在适合去游泳吗？'
    assert first['intent'] == 'knowledge_base'
    assert first['route_matches_expectation'] is True
    assert first['answer'] == '测试答案'
    assert first['answer_language'] == 'zh'
    assert 'elapsed_ms' in first


def test_selftest_records_pipeline_errors_without_crashing(client, app, monkeypatch):
    def _boom(**_kw):
        raise RuntimeError('pipeline exploded')

    monkeypatch.setattr('app.services.chatbot.get_rag_app', _boom)
    monkeypatch.setattr(
        'app.blueprints.chatbot._build_homepage_context', lambda *_a, **_k: []
    )

    response = client.get(
        '/api/cron/chatbot-selftest?run=r2&index=1',
        headers={'Authorization': 'Bearer test-cron-secret'},
    )

    assert response.status_code == 200
    assert response.get_json()['ok'] is False

    report = client.get('/api/chatbot-selftest/latest').get_json()
    assert report['succeeded'] == 0
    assert 'pipeline exploded' in report['results'][0]['error']


def test_selftest_rerunning_same_index_replaces_not_duplicates(client, app, monkeypatch):
    monkeypatch.setattr(
        'app.services.chatbot.get_rag_app', lambda **_kw: _fake_rag_app()
    )
    monkeypatch.setattr(
        'app.blueprints.chatbot._build_homepage_context', lambda *_a, **_k: []
    )

    for _ in range(2):
        client.get(
            '/api/cron/chatbot-selftest?run=r3&index=2',
            headers={'Authorization': 'Bearer test-cron-secret'},
        )

    report = client.get('/api/chatbot-selftest/latest').get_json()
    assert report['completed'] == 1


def test_selftest_index_validation(client):
    from app.services.chatbot.selftest import selftest_total

    response = client.get(
        f'/api/cron/chatbot-selftest?run=r4&index={selftest_total()}',
        headers={'Authorization': 'Bearer test-cron-secret'},
    )

    assert response.status_code == 400


def test_battery_covers_both_languages_and_all_route_kinds():
    from app.services.chatbot.selftest import SELFTEST_QUESTIONS

    languages = {case[1] for case in SELFTEST_QUESTIONS}
    routes = {case[2] for case in SELFTEST_QUESTIONS}
    assert languages == {'zh', 'en'}
    assert {'knowledge_base', 'database', 'capability', 'small_talk', 'fallback'} <= routes
    # Unique ids
    ids = [case[0] for case in SELFTEST_QUESTIONS]
    assert len(ids) == len(set(ids))
