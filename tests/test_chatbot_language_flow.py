"""New chatbot flow: heuristic-first routing, native-language answers,
lazy retrieval translation. These tests pin the latency contract: the hot
path must not spend LLM calls on translation or intent classification when
deterministic logic suffices."""

import pytest

from langchain_core.documents import Document

from app.services.chatbot import graph as graph_module


class _FakeResponse:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeLLM:
    def __init__(self, reply="stub reply"):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return _FakeResponse(self.reply)

    def bind_tools(self, _tools):
        return self


class _ExplodingLLM:
    """An intent model that must never be reached."""

    def invoke(self, _messages):
        raise AssertionError("intent LLM should not be called for confident heuristics")


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("hello", graph_module.INTENT_SMALL_TALK),
        ("你好", graph_module.INTENT_SMALL_TALK),
        ("What is the pool lane etiquette for overtaking?", graph_module.INTENT_KNOWLEDGE_BASE),
        ("现在适合去游泳吗？", graph_module.INTENT_KNOWLEDGE_BASE),
        ("show me the latest posts", graph_module.INTENT_DATABASE),
        ("列出今天最新的手动上报", graph_module.INTENT_DATABASE),
        ("你能做什么？", graph_module.INTENT_CAPABILITY),
    ],
)
def test_confident_heuristics_never_touch_intent_model(question, expected):
    assert graph_module._classify_intent(question, _ExplodingLLM()) == expected


def test_ambiguous_question_still_consults_intent_model():
    class _IntentLLM:
        def __init__(self):
            self.called = False

        def invoke(self, _messages):
            self.called = True
            return _FakeResponse('{"intent":"fallback","reason":"out of scope"}')

    intent_llm = _IntentLLM()
    intent = graph_module._classify_intent("write a C compiler from scratch", intent_llm)

    assert intent_llm.called is True
    assert intent == graph_module.INTENT_FALLBACK


def _build_app(llm, intent_llm, monkeypatch, search_results):
    monkeypatch.setattr(
        graph_module,
        "_search_with_optional_scores",
        lambda _store, _question, _top_k: list(search_results),
    )
    return graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )


def test_chinese_kb_answer_uses_single_llm_call_and_language_instruction(monkeypatch):
    doc = Document(
        page_content="工作日开放时间为 07:00-21:30。",
        metadata={"source": "kb://hours"},
    )
    llm = _FakeLLM(reply="工作日的开放时间是早上 7 点到晚上 9 点半。")
    rag_app = _build_app(llm, _ExplodingLLM(), monkeypatch, [(doc, 0.9)])

    result = rag_app.invoke({"question": "泳池的更衣室是怎么安排的？"})

    # Exactly ONE model call: the answer generation. No translate-in,
    # no intent call, no translate-out.
    assert len(llm.calls) == 1
    system_prompt = llm.calls[0][0].content
    assert "Reply in Simplified Chinese." in system_prompt
    assert result["answer"] == "工作日的开放时间是早上 7 点到晚上 9 点半。"


def test_second_chance_translated_retrieval_recovers_english_chunks(monkeypatch):
    en_doc = Document(
        page_content="Weekday opening hours are 07:00-21:30.",
        metadata={"source": "kb://hours-en"},
    )
    search_calls = []

    def _fake_search(_store, question, _top_k):
        search_calls.append(question)
        # First (Chinese) query misses; the translated query hits.
        if question == "What are the weekday opening hours?":
            return [(en_doc, 0.88)]
        return []

    monkeypatch.setattr(graph_module, "_search_with_optional_scores", _fake_search)
    monkeypatch.setattr(
        graph_module,
        "_translate_to_english",
        lambda text, intent_llm, qa_llm: "What are the weekday opening hours?",
    )

    llm = _FakeLLM(reply="工作日 07:00-21:30 开放。")
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "泳池的更衣室是怎么安排的？"})

    assert search_calls == ["泳池的更衣室是怎么安排的？", "What are the weekday opening hours?"]
    assert result["answer"] == "工作日 07:00-21:30 开放。"
    assert result["sources"] == ["kb://hours-en"]


def test_english_question_never_triggers_retrieval_translation(monkeypatch):
    search_calls = []

    def _fake_search(_store, question, _top_k):
        search_calls.append(question)
        return []

    monkeypatch.setattr(graph_module, "_search_with_optional_scores", _fake_search)

    def _no_translate(*_args, **_kwargs):
        raise AssertionError("translation must not run for English questions")

    monkeypatch.setattr(graph_module, "_translate_to_english", _no_translate)

    llm = _FakeLLM(reply="unused")
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "What is the pool lane etiquette for overtaking?"})

    # Retrieval ran with the English question only (extra entries come from
    # the quick-question helper, never from a translation retry).
    assert search_calls[0] == "What is the pool lane etiquette for overtaking?"
    assert result["answer"] == graph_module.DEFAULT_UNKNOWN_REPLY_EN


def test_localize_safety_net_translates_when_model_ignores_language(monkeypatch):
    doc = Document(page_content="Hours info.", metadata={"source": "kb://hours"})
    translated = {}

    def _fake_translate_from_english(text, target_language, _llm):
        translated["text"] = text
        translated["target"] = target_language
        return "工作日 07:00-21:30 开放。"

    monkeypatch.setattr(
        graph_module, "_translate_from_english", _fake_translate_from_english
    )

    # Model wrongly answers in English despite the zh instruction.
    llm = _FakeLLM(reply="Weekday hours are 07:00-21:30.")
    rag_app = _build_app(llm, _ExplodingLLM(), monkeypatch, [(doc, 0.9)])

    result = rag_app.invoke({"question": "泳池的更衣室是怎么安排的？"})

    assert translated["target"] == "zh"
    assert result["answer"] == "工作日 07:00-21:30 开放。"


def test_chinese_capability_answer_is_static_chinese():
    llm = _FakeLLM(reply="should not be used")
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "你能做什么？"})

    assert result["answer"] == graph_module.CAPABILITY_ANSWER_ZH
    assert "NTU Pool" in result["answer"]
    assert len(llm.calls) == 0
