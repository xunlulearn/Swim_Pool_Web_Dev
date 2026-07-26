"""Chatbot self-test battery.

Runs curated questions through the REAL production RAG pipeline (embedding,
Supabase retrieval, LLM) and records per-question diagnostics: resolved
intent, retrieval size, sources, latency, and the answer itself. Triggered
one question at a time via the authenticated cron endpoint so each request
stays well inside serverless time limits; results accumulate in
chatbot_selftest_runs and are readable from the public report endpoint.
"""

import json
import time
from datetime import datetime

from app.extensions import db
from app.models.selftest import ChatbotSelftestRun


# (id, language, expected_route_hint, question)
# expected_route_hint is what a correct router SHOULD do — recorded in the
# report so mismatches are visible at a glance. Hints: small_talk, database,
# knowledge_base, capability, fallback.
SELFTEST_QUESTIONS = [
    ('zh-live-decision', 'zh', 'knowledge_base', '现在适合去游泳吗？'),
    ('zh-hours', 'zh', 'knowledge_base', '工作日泳池几点开放？'),
    ('zh-report-rule', 'zh', 'knowledge_base', '需要多少条上报才能覆盖天气状态？'),
    ('zh-register', 'zh', 'knowledge_base', '怎么注册账号？收不到验证码怎么办？'),
    ('zh-search-howto', 'zh', 'knowledge_base', '怎么在社区里搜索帖子？'),
    ('zh-profile-howto', 'zh', 'knowledge_base', '怎么修改昵称和上传头像？'),
    ('zh-guest-policy', 'zh', 'knowledge_base', '游客不登录可以做什么？'),
    ('zh-db-posts', 'zh', 'database', '列出最新的社区帖子'),
    ('zh-db-count-today', 'zh', 'database', '今天有多少条上报？'),
    ('zh-capability', 'zh', 'capability', '你能做什么？'),
    ('zh-smalltalk', 'zh', 'small_talk', '你好'),
    ('zh-outofscope', 'zh', 'fallback', '帮我写一个Python爬虫程序'),
    ('en-hours-weekend', 'en', 'knowledge_base',
     'What are the pool opening hours on weekends and public holidays?'),
    ('en-lightning-cooldown', 'en', 'knowledge_base',
     'How long is the lightning cooldown before reopening?'),
    ('en-search-howto', 'en', 'knowledge_base',
     'How do I search for posts in the community?'),
    ('en-report-rule', 'en', 'knowledge_base',
     'How many reports are needed to override weather status?'),
    ('en-saved-posts', 'en', 'knowledge_base', 'Where can I see the posts I saved?'),
    ('en-db-reports', 'en', 'database', 'Show me the latest manual pool reports'),
    ('en-live-decision', 'en', 'knowledge_base', 'Is it safe to swim right now?'),
    ('en-smalltalk', 'en', 'small_talk', 'hello'),
    ('en-outofscope', 'en', 'fallback', 'What is the capital of France?'),
]


def selftest_total():
    return len(SELFTEST_QUESTIONS)


def _get_or_create_run(run_key):
    run = ChatbotSelftestRun.query.filter_by(run_key=run_key).first()
    if run is None:
        run = ChatbotSelftestRun(
            run_key=run_key,
            total_questions=selftest_total(),
            results_json='[]',
        )
        db.session.add(run)
        db.session.commit()
    return run


def run_selftest_question(run_key, index):
    """Execute one battery question through the real pipeline and record it."""
    if index < 0 or index >= selftest_total():
        return {'ok': False, 'error': f'index out of range 0..{selftest_total() - 1}'}

    case_id, language, expected, question = SELFTEST_QUESTIONS[index]
    record = {
        'index': index,
        'id': case_id,
        'language': language,
        'expected_route': expected,
        'question': question,
        'ran_at': datetime.utcnow().isoformat(),
    }

    started = time.perf_counter()
    try:
        from app.blueprints.chatbot import _build_homepage_context
        from app.services.chatbot import get_rag_app

        rag_app = get_rag_app()
        state = rag_app.invoke({
            'question': question,
            'page_context': _build_homepage_context(),
        })
        state = state if isinstance(state, dict) else {}
        answer = str(state.get('answer') or '').strip()
        record.update({
            'ok': True,
            'elapsed_ms': int((time.perf_counter() - started) * 1000),
            'intent': state.get('intent'),
            'mode': state.get('mode'),
            'route_matches_expectation': state.get('intent') == expected,
            'context_chunks': len(state.get('context') or []),
            'question_en': state.get('question_en') or '',
            'sources': list(state.get('sources') or [])[:6],
            'answer': answer[:600],
            'answer_language': (
                'zh' if any('一' <= ch <= '鿿' for ch in answer) else 'en'
            ) if answer else '',
            'quick_questions': list(state.get('quick_questions') or [])[:3],
        })
    except Exception as exc:  # record the failure, never crash the endpoint
        record.update({
            'ok': False,
            'elapsed_ms': int((time.perf_counter() - started) * 1000),
            'error': f'{type(exc).__name__}: {exc}'[:400],
        })

    run = _get_or_create_run(run_key)
    try:
        results = json.loads(run.results_json or '[]')
        if not isinstance(results, list):
            results = []
    except json.JSONDecodeError:
        results = []
    results = [item for item in results if item.get('index') != index]
    results.append(record)
    results.sort(key=lambda item: item.get('index', 0))
    run.results_json = json.dumps(results, ensure_ascii=False)
    run.total_questions = selftest_total()
    db.session.commit()

    return {
        'ok': bool(record.get('ok')),
        'run_key': run_key,
        'index': index,
        'total': selftest_total(),
        'completed': len(results),
        'case': case_id,
    }


def latest_selftest_report():
    run = ChatbotSelftestRun.query.order_by(ChatbotSelftestRun.created_at.desc()).first()
    if run is None:
        return None
    try:
        results = json.loads(run.results_json or '[]')
    except json.JSONDecodeError:
        results = []
    ok_results = [item for item in results if item.get('ok')]
    latencies = sorted(item.get('elapsed_ms', 0) for item in ok_results)
    median_ms = latencies[len(latencies) // 2] if latencies else None
    return {
        'run_key': run.run_key,
        'started_at': run.created_at.isoformat() if run.created_at else None,
        'updated_at': run.updated_at.isoformat() if run.updated_at else None,
        'total_questions': run.total_questions,
        'completed': len(results),
        'succeeded': len(ok_results),
        'route_mismatches': [
            item.get('id') for item in ok_results
            if not item.get('route_matches_expectation')
        ],
        'median_elapsed_ms': median_ms,
        'results': results,
    }
