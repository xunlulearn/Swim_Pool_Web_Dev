"""Retrieval recovery mechanisms must stay alive when page context exists.

Root cause these tests guard against: `context` used to be seeded with the
live homepage page_context, and every retrieval-quality heuristic measured
that merged list. Since page context is always present in production, all
recovery paths were permanently dead — the visible symptom being a KB chunk
holding a "### Q:" heading whose "**A:**" body landed in the next chunk,
answered with "I don't know".
"""

import pytest

from langchain_core.documents import Document

from app.services.chatbot import graph as graph_module


PAGE_CONTEXT = [
    "Current homepage pool status: GREEN (Open).",
    "Decision guide: GREEN/OPEN means going is generally reasonable.",
    "Current weather metrics: nearest lightning=20 km; rainfall=0 mm/h.",
    "Lightning trend chart total for Last 20 Minutes: <=15 km 0 strikes.",
    "Lightning trend observation time (SGT): 2026-07-26 19:00.",
    "Future visit guide: watch the homepage pool status before leaving.",
]


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.tool_calls = []


class _FakeLLM:
    def __init__(self, reply='answer'):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return _FakeResponse(self.reply)

    def bind_tools(self, _tools):
        return self


class _ExplodingLLM:
    def invoke(self, _messages):
        raise AssertionError('intent LLM should not be called')


def _build(llm, monkeypatch, search_results, top_k=3, min_score=0.65):
    monkeypatch.setattr(
        graph_module,
        '_search_with_optional_scores',
        lambda _store, _q, _k: list(search_results),
    )
    return graph_module._build_graph(
        llm=llm,
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=top_k,
        min_score=min_score,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )


def test_usage_questions_are_not_routed_to_the_database(monkeypatch):
    """Naming an entity must not turn a how-to question into a record lookup.

    Production failure: 'How do I search for posts in the community?' hit the
    'posts' database hint, queried real post records, and answered that it
    could not find any information.
    """
    for question in (
        'How do I search for posts in the community?',
        '怎么在社区里搜索帖子？',
        'How do I create a post?',
        'How can I report inappropriate content?',
        '如何修改我的昵称和头像？',
    ):
        assert graph_module._heuristic_intent(question) == graph_module.INTENT_KNOWLEDGE_BASE, question

    for question in (
        'show me the latest posts',
        '列出最新的社区帖子',
        'How many posts are there in total?',
        'Show me the latest manual pool reports',
        'search posts about goggles',
    ):
        assert graph_module._heuristic_intent(question) == graph_module.INTENT_DATABASE, question


def test_split_qa_chunk_pulls_in_its_answer_chunk(monkeypatch):
    """The exact production failure: question-only chunk scores highest."""
    question_chunk = Document(
        page_content=(
            '**A:** The homepage shows the latest 10 report rows by submission time.\n\n'
            '---\n\n'
            '### Q: How do I search for posts in the community?'
        ),
        metadata={'source': 'kb://website_guide.md'},
    )
    answer_chunk = Document(
        page_content=(
            '**A:** Use the search box at the top of the Community page. '
            'It matches keywords in post titles and content.'
        ),
        metadata={'source': 'kb://website_guide.md'},
    )

    llm = _FakeLLM(reply='Use the search box at the top of the Community page.')
    rag_app = _build(
        llm, monkeypatch,
        [(question_chunk, 0.91), (answer_chunk, 0.42)],  # answer below threshold
    )

    result = rag_app.invoke({
        'question': 'How do I appeal a moderation decision on this website?',
        'page_context': PAGE_CONTEXT,
    })

    prompt = llm.calls[-1][-1].content
    # The answer body must reach the model, not just the question heading.
    assert 'Use the search box' in prompt
    assert result['kb_chunks'] >= 2


def test_page_context_does_not_disable_low_confidence_fallback(monkeypatch):
    weak_doc = Document(
        page_content='Lost items are kept at the SRC counter for two weeks.',
        metadata={'source': 'kb://faq.md'},
    )

    llm = _FakeLLM(reply='They are kept at the counter.')
    # Score far below min_score: only the low-confidence fallback can recover it.
    rag_app = _build(llm, monkeypatch, [(weak_doc, 0.30)])

    result = rag_app.invoke({
        'question': 'What is the towel service arrangement at the pool?',
        'page_context': PAGE_CONTEXT,
    })

    assert result['kb_chunks'] == 1
    assert 'kept at the SRC counter' in llm.calls[-1][-1].content


def test_page_context_does_not_disable_backend_snapshot_fallback(monkeypatch):
    backend_doc = Document(
        page_content='Lightning close threshold: <= 15.0 km',
        metadata={'source': 'app://backend/non_sensitive_snapshot'},
    )
    monkeypatch.setattr(
        graph_module, '_load_backend_priority_docs', lambda _s, _k: [backend_doc]
    )

    llm = _FakeLLM(reply='The threshold is 15 km.')
    rag_app = _build(llm, monkeypatch, [])  # vector search returns nothing

    result = rag_app.invoke({
        'question': 'What is the vector retrieval top_k configured in the backend rules?',
        'page_context': PAGE_CONTEXT,
    })

    assert result['kb_chunks'] == 1
    assert 'Lightning close threshold' in llm.calls[-1][-1].content


def test_chinese_kb_question_still_gets_translation_retry_with_page_context(monkeypatch):
    """Non-live Chinese questions must keep the translated-retrieval retry."""
    en_doc = Document(
        page_content='**A:** The consensus rule needs 5 reports from 5 different users.',
        metadata={'source': 'kb://website_guide.md'},
    )
    searches = []

    def _fake_search(_store, question, _k):
        searches.append(question)
        if question == 'How many reports are needed to override weather status?':
            return [(en_doc, 0.88)]
        return []

    monkeypatch.setattr(graph_module, '_search_with_optional_scores', _fake_search)
    monkeypatch.setattr(
        graph_module, '_translate_to_english',
        lambda *_a, **_k: 'How many reports are needed to override weather status?',
    )

    llm = _FakeLLM(reply='需要 5 位不同用户的一致上报。')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({
        'question': '泳池的水温一般维持在多少度？',
        'page_context': PAGE_CONTEXT,
    })

    assert len(searches) == 2  # original query, then translated query
    assert result['kb_chunks'] == 1
    assert 'consensus rule needs 5 reports' in llm.calls[-1][-1].content


def test_live_decision_question_skips_translation_retry(monkeypatch):
    """Latency guard: live questions are answered from page context."""
    searches = []

    def _fake_search(_store, question, _k):
        searches.append(question)
        return []

    monkeypatch.setattr(graph_module, '_search_with_optional_scores', _fake_search)

    def _no_translate(*_a, **_k):
        raise AssertionError('live-decision questions must not spend a translation call')

    monkeypatch.setattr(graph_module, '_translate_to_english', _no_translate)

    llm = _FakeLLM(reply='现在可以去，状态为开放。')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({
        'question': '现在适合去游泳吗？',
        'page_context': PAGE_CONTEXT,
    })

    assert len(searches) == 1
    assert 'Current homepage pool status' in llm.calls[0][-1].content
    assert result['sources'] == ['app://homepage/live-status']


def test_page_context_still_reaches_the_model_alongside_kb_chunks(monkeypatch):
    kb_doc = Document(
        page_content='**A:** Weekday hours are 07:00-21:30.',
        metadata={'source': 'kb://operating_hours_and_holidays.md'},
    )

    llm = _FakeLLM(reply='Weekday hours are 07:00-21:30.')
    rag_app = _build(llm, monkeypatch, [(kb_doc, 0.9)])

    result = rag_app.invoke({
        'question': 'What is the swim cap policy for long hair?',
        'page_context': PAGE_CONTEXT,
    })

    prompt = llm.calls[-1][-1].content
    assert 'Current homepage pool status' in prompt   # live context preserved
    assert 'Weekday hours are 07:00-21:30' in prompt  # kb chunk present
    assert result['sources'][0] == 'app://homepage/live-status'
    assert 'kb://operating_hours_and_holidays.md' in result['sources']


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('### Q: How do I search for posts in the community?', True),
        ('## Q: 需要多少条上报？', True),
        ('**A:** Use the search box at the top.', False),
        ('Weekday hours are 07:00-21:30.', False),
    ],
)
def test_question_tail_detection(text, expected):
    assert graph_module._chunk_ends_on_question(text) is expected


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('**A:** Use the search box.', True),
        ('A: 用页面顶部的搜索框。', True),
        ('答：使用搜索框。', True),
        ('### Q: something?', False),
    ],
)
def test_answer_head_detection(text, expected):
    assert graph_module._chunk_starts_with_answer(text) is expected
