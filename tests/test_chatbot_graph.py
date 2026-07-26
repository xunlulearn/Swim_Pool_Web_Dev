import json

import pytest

from langchain_core.documents import Document

from app.services.chatbot import graph as graph_module
from app.services.chatbot import hard_kb


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


class _IntentLLM:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, _messages):
        return _FakeResponse(self.payload)


class _FailingLLM:
    def __init__(self, message="model call failed"):
        self.message = message

    def invoke(self, _messages):
        raise RuntimeError(self.message)


def test_classify_intent_uses_model_json():
    intent = graph_module._classify_intent(
        "show me latest community posts",
        _IntentLLM('{"intent":"database","reason":"asks for latest posts"}'),
    )
    assert intent == graph_module.INTENT_DATABASE


def test_rag_prompt_hides_internal_context_labels():
    assert "Do not mention reference context numbers" in graph_module.RAG_SYSTEM_PROMPT
    assert "Do not answer with only one word" in graph_module.RAG_SYSTEM_PROMPT
    assert "If a live metric is unknown" in graph_module.RAG_SYSTEM_PROMPT


def test_classify_intent_falls_back_to_heuristics_on_invalid_json():
    intent = graph_module._classify_intent(
        "hello there",
        _IntentLLM("not json"),
    )
    assert intent == graph_module.INTENT_SMALL_TALK


def test_classify_intent_routes_site_contact_query_to_knowledge_base():
    intent = graph_module._classify_intent(
        "\u5982\u4f55\u8054\u7cfb\u7f51\u7ad9\u5f00\u53d1\u8005\uff1f",
        _IntentLLM("not json"),
    )
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


def test_classify_intent_overrides_model_fallback_when_kb_signal_is_strong():
    intent = graph_module._classify_intent(
        "\u7f51\u7ad9\u5f00\u53d1\u8005\u90ae\u7bb1\u662f\u4ec0\u4e48\uff1f",
        _IntentLLM('{"intent":"fallback","reason":"unclear"}'),
    )
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


def test_classify_intent_overrides_model_capability_when_kb_signal_is_strong():
    intent = graph_module._classify_intent(
        "How does lightning affect pool status?",
        _IntentLLM('{"intent":"capability","reason":"asks about assistant help"}'),
    )
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


def test_classify_intent_uses_original_question_when_translation_looks_capability():
    intent = graph_module._classify_intent(
        "What can you do?",
        _IntentLLM('{"intent":"capability","reason":"asks about assistant help"}'),
        fallback_question="\u95ea\u7535\u4f1a\u5982\u4f55\u5f71\u54cd\u6cf3\u6c60\u72b6\u6001\uff1f",
    )
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


@pytest.mark.parametrize(
    ("question", "expected_intent"),
    [
        ("How does lightning affect pool status?", graph_module.INTENT_KNOWLEDGE_BASE),
        ("What are the pool opening hours on weekends?", graph_module.INTENT_KNOWLEDGE_BASE),
        ("Do I need to log in to submit a report?", graph_module.INTENT_KNOWLEDGE_BASE),
        ("How many reports are needed to override weather status?", graph_module.INTENT_KNOWLEDGE_BASE),
        ("List latest manual reports from today", graph_module.INTENT_DATABASE),
        ("\u73b0\u5728\u9002\u5408\u53bb\u6e38\u6cf3\u5417\uff1f", graph_module.INTENT_KNOWLEDGE_BASE),
        ("\u9700\u8981\u591a\u5c11\u6761\u4e0a\u62a5\u624d\u80fd\u8986\u76d6\u5929\u6c14\u72b6\u6001\uff1f", graph_module.INTENT_KNOWLEDGE_BASE),
        ("\u5217\u51fa\u4eca\u5929\u6700\u65b0\u7684\u624b\u52a8\u4e0a\u62a5", graph_module.INTENT_DATABASE),
    ],
)
@pytest.mark.parametrize("bad_model_intent", ["capability", "small_talk", "fallback"])
def test_domain_questions_override_non_domain_model_drift(
    question, expected_intent, bad_model_intent
):
    intent = graph_module._merge_model_intent_with_heuristic(question, bad_model_intent)
    assert intent == expected_intent


@pytest.mark.parametrize(
    ("original_question", "expected_intent"),
    [
        ("\u95ea\u7535\u4f1a\u5982\u4f55\u5f71\u54cd\u6cf3\u6c60\u72b6\u6001\uff1f", graph_module.INTENT_KNOWLEDGE_BASE),
        ("\u9700\u8981\u591a\u5c11\u6761\u4e0a\u62a5\u624d\u80fd\u8986\u76d6\u5929\u6c14\u72b6\u6001\uff1f", graph_module.INTENT_KNOWLEDGE_BASE),
        ("\u5217\u51fa\u4eca\u5929\u6700\u65b0\u7684\u624b\u52a8\u4e0a\u62a5", graph_module.INTENT_DATABASE),
    ],
)
def test_original_question_domain_signal_overrides_bad_capability_translation(
    original_question, expected_intent
):
    intent = graph_module._classify_intent(
        "What can you do?",
        _IntentLLM('{"intent":"capability","reason":"bad translation drift"}'),
        fallback_question=original_question,
    )
    assert intent == expected_intent


def test_heuristic_intent_routes_policy_question_to_knowledge_base():
    intent = graph_module._heuristic_intent("Can I submit a pool report without login?")
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


def test_heuristic_intent_routes_chinese_report_submission_to_knowledge_base():
    intent = graph_module._heuristic_intent(
        "\u6211\u8be5\u5982\u4f55\u63d0\u4ea4\u624b\u52a8\u6cf3\u6c60\u4e0a\u62a5\uff1f"
    )
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


def test_heuristic_intent_routes_report_lookup_to_database():
    intent = graph_module._heuristic_intent("List the latest manual reports from today")
    assert intent == graph_module.INTENT_DATABASE


def test_merge_model_intent_prefers_kb_for_policy_question():
    intent = graph_module._merge_model_intent_with_heuristic(
        "Who is allowed to submit a pool report?",
        "database",
    )
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


def test_is_backend_rules_question_detects_lightning_logic_query():
    assert graph_module._is_backend_rules_question(
        "\u96f7\u7535\u9884\u8b66\u7684\u903b\u8f91\u662f\u600e\u4e48\u8bbe\u7f6e\u7684"
    )


def test_is_backend_rules_question_detects_chatbot_sync_architecture_query():
    assert graph_module._is_backend_rules_question(
        "How does chatbot knowledge sync incremental update work?"
    )


def test_classify_intent_routes_chatbot_architecture_query_to_knowledge_base():
    intent = graph_module._classify_intent(
        "Which Supabase tables are used by chatbot?",
        _IntentLLM("not json"),
    )
    assert intent == graph_module.INTENT_KNOWLEDGE_BASE


def test_graph_small_talk_skips_retrieval(monkeypatch):
    def _should_not_search(_store, _question, _top_k):
        raise AssertionError("retrieval should not run for small talk")

    monkeypatch.setattr(graph_module, "_search_with_optional_scores", _should_not_search)

    llm = _FakeLLM(reply="hi there")
    intent_llm = _IntentLLM('{"intent":"small_talk","reason":"greeting"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "hi"})
    assert result["answer"] == "hi there"
    assert result.get("sources", []) == []
    # Every reply now ends with three clickable hard-KB suggestions so the
    # user always has a guided next step.
    assert len(result["quick_questions"]) == 3
    canonical = {
        hard_kb.question_for(entry, lang)
        for entry in hard_kb.HARD_KB_ENTRIES
        for lang in ("zh", "en")
    }
    assert set(result["quick_questions"]) <= canonical


def test_graph_capability_question_returns_domain_answer_without_generic_identity(monkeypatch):
    def _should_not_search(_store, _question, _top_k):
        raise AssertionError("retrieval should not run for assistant capability questions")

    monkeypatch.setattr(graph_module, "_search_with_optional_scores", _should_not_search)

    llm = _FakeLLM(reply="I am a large language model, trained by Google.")
    intent_llm = _IntentLLM('{"intent":"small_talk","reason":"asks about assistant ability"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "What can you do?"})

    assert "NTU Pool" in result["answer"]
    assert "Google" not in result["answer"]
    assert result.get("sources", []) == []
    assert result["quick_questions"] == [
        "Can I go swimming now?",
        "How does lightning affect pool status?",
        "How can I submit a manual pool report?",
    ]


def test_graph_chinese_capability_question_routes_to_domain_answer(monkeypatch):
    monkeypatch.setattr(graph_module, "_search_with_optional_scores", lambda _s, _q, _k: [])
    monkeypatch.setattr(
        graph_module,
        "_translate_to_english",
        lambda question, intent_llm, qa_llm: "What can you do?",
    )
    monkeypatch.setattr(
        graph_module,
        "_translate_from_english",
        lambda text, target_language, llm: text,
    )

    llm = _FakeLLM(reply="I am a large language model, trained by Google.")
    intent_llm = _IntentLLM('{"intent":"small_talk","reason":"asks about assistant ability"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "\u4f60\u80fd\u505a\u4ec0\u4e48\uff1f"})

    assert "NTU Pool" in result["answer"]
    assert "Google" not in result["answer"]
    assert result["quick_questions"][0] == "\u73b0\u5728\u9002\u5408\u53bb\u6e38\u6cf3\u5417\uff1f"


def test_graph_knowledge_base_path_returns_unknown_when_no_context(monkeypatch):
    monkeypatch.setattr(graph_module, "_search_with_optional_scores", lambda _s, _q, _k: [])

    llm = _FakeLLM(reply="should not be used")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"website query"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "what is the pool evacuation procedure during a storm?"})
    assert result["answer"] == graph_module.DEFAULT_UNKNOWN_REPLY_EN
    assert result.get("sources", []) == []
    assert len(result.get("quick_questions", [])) == 3


def test_graph_knowledge_base_path_uses_retrieved_context(monkeypatch):
    doc = Document(
        page_content="Pool opening hours are listed on ntupool.org.",
        metadata={"source": "https://ntupool.org/"},
    )
    monkeypatch.setattr(
        graph_module,
        "_search_with_optional_scores",
        lambda _store, _question, _top_k: [(doc, 0.8)],
    )

    llm = _FakeLLM(reply="KB answer")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"official info"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "pool open close time"})
    assert result["answer"] == "KB answer"
    assert result["sources"] == ["https://ntupool.org/"]
    # Every reply now ends with three clickable hard-KB suggestions so the
    # user always has a guided next step.
    assert len(result["quick_questions"]) == 3
    canonical = {
        hard_kb.question_for(entry, lang)
        for entry in hard_kb.HARD_KB_ENTRIES
        for lang in ("zh", "en")
    }
    assert set(result["quick_questions"]) <= canonical


def test_graph_uses_homepage_context_for_live_pool_decision(monkeypatch):
    monkeypatch.setattr(graph_module, "_search_with_optional_scores", lambda _s, _q, _k: [])

    llm = _FakeLLM(reply="The pool is open, and lightning risk is low, so it is reasonable to go.")
    intent_llm = _IntentLLM('{"intent":"fallback","reason":"decision request"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke(
        {
            "question": "\u73b0\u5728\u9002\u5408\u53bb\u6cf3\u6c60\u5417\uff1f",
            "page_context": [
                "Current homepage status: OPEN.",
                "Nearest lightning: >15km.",
                "Lightning trend 20 min <= 15 km total: 0 strikes.",
            ],
        }
    )

    assert "reasonable to go" in result["answer"]
    assert result["sources"] == ["app://homepage/live-status"]
    # Live-decision questions are answered from page context, so no
    # translation retry is spent: the first model call is the answer itself.
    assert "Current homepage status: OPEN." in llm.calls[0][-1].content


def test_graph_live_pool_decision_overrides_model_small_talk(monkeypatch):
    monkeypatch.setattr(graph_module, "_search_with_optional_scores", lambda _s, _q, _k: [])
    monkeypatch.setattr(
        graph_module,
        "_translate_to_english",
        lambda question, intent_llm, qa_llm: "Is the pool open right now? Can I go swimming now?",
    )
    monkeypatch.setattr(
        graph_module,
        "_translate_from_english",
        lambda text, target_language, llm: text,
    )

    llm = _FakeLLM(reply="Use the current homepage status and lightning trend before going.")
    intent_llm = _IntentLLM('{"intent":"small_talk","reason":"friendly phrasing"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke(
        {
            "question": "\u5f53\u524d\u6cf3\u6c60\u5f00\u653e\u5417\uff1f\u6211\u73b0\u5728\u53ef\u4ee5\u8fc7\u53bb\u6e38\u6cf3\u5417\uff1f",
            "page_context": ["Current homepage pool status: GREEN (Open)."],
        }
    )

    assert result["sources"] == ["app://homepage/live-status"]
    assert "current homepage pool status" in llm.calls[0][-1].content.lower()


def test_graph_page_context_routes_time_followup_to_live_status(monkeypatch):
    monkeypatch.setattr(graph_module, "_search_with_optional_scores", lambda _s, _q, _k: [])
    monkeypatch.setattr(
        graph_module,
        "_translate_to_english",
        lambda question, intent_llm, qa_llm: "I plan to go there in 30 minutes. What changes should I watch?",
    )
    monkeypatch.setattr(
        graph_module,
        "_translate_from_english",
        lambda text, target_language, llm: text,
    )

    llm = _FakeLLM(reply="Watch the pool status, lightning distance, and 20-minute lightning trend.")
    intent_llm = _IntentLLM('{"intent":"fallback","reason":"ambiguous follow-up"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke(
        {
            "question": "\u6211\u51c6\u590730\u5206\u949f\u540e\u8fc7\u53bb\uff0c\u9700\u8981\u91cd\u70b9\u770b\u54ea\u4e9b\u72b6\u6001\u53d8\u5316\uff1f",
            "page_context": [
                "Current homepage pool status: GREEN (Open).",
                "Lightning trend chart total for Last 20 Minutes: <=15 km 0 strikes, <=30 km 0 strikes.",
            ],
        }
    )

    assert result["sources"] == ["app://homepage/live-status"]
    assert "Lightning trend chart total" in llm.calls[0][-1].content


def test_graph_known_answer_still_offers_hard_kb_suggestions_for_zh(monkeypatch):
    doc = Document(
        page_content="Follow the register page flow on ntupool.org to create an account.",
        metadata={"source": "https://ntupool.org/"},
    )
    monkeypatch.setattr(
        graph_module,
        "_search_with_optional_scores",
        lambda _store, _question, _top_k: [(doc, 0.88)],
    )
    monkeypatch.setattr(
        graph_module,
        "_translate_to_english",
        lambda question, intent_llm, qa_llm: "How do I register an account?",
    )
    monkeypatch.setattr(
        graph_module,
        "_translate_from_english",
        lambda text, target_language, llm: text,
    )

    llm = _FakeLLM(reply="Use the Register page on ntupool.org.")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"account question"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "\u6cf3\u6c60\u7684\u50a8\u7269\u67dc\u9700\u8981\u62bc\u91d1\u5417\uff1f"})
    assert result["answer"] == "Use the Register page on ntupool.org."
    # Every reply now ends with three clickable hard-KB suggestions so the
    # user always has a guided next step.
    assert len(result["quick_questions"]) == 3
    canonical = {
        hard_kb.question_for(entry, lang)
        for entry in hard_kb.HARD_KB_ENTRIES
        for lang in ("zh", "en")
    }
    assert set(result["quick_questions"]) <= canonical


def test_graph_unknown_answer_returns_three_related_faq_questions(monkeypatch):
    monkeypatch.setattr(graph_module, "_search_with_optional_scores", lambda _s, _q, _k: [])
    monkeypatch.setattr(
        graph_module,
        "_translate_to_english",
        lambda question, intent_llm, qa_llm: "How do I register?",
    )
    monkeypatch.setattr(
        graph_module,
        "_translate_from_english",
        lambda text, target_language, llm: text,
    )

    llm = _FakeLLM(reply="unused")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"registration query"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "\u6cf3\u6c60\u6709\u63d0\u4f9b\u6bdb\u5dfe\u670d\u52a1\u5417\uff1f"})
    faq_questions = set(graph_module._load_faq_questions())
    faq_questions_zh = {
        localized
        for original, localized in graph_module.QUICK_QUESTION_ZH_MAP.items()
        if original in faq_questions
    }
    # Chinese question now receives the Chinese unknown reply directly.
    assert result["answer"] == graph_module.DEFAULT_UNKNOWN_REPLY_ZH
    assert len(result["quick_questions"]) == 3
    assert all(
        item in faq_questions or item in faq_questions_zh for item in result["quick_questions"]
    )
    assert "How do I register an account?" in result["quick_questions"]


def test_graph_knowledge_base_low_confidence_fallback_keeps_near_best_docs(monkeypatch):
    best_doc = Document(
        page_content="During storms, lifeguards whistle and everyone must evacuate immediately.",
        metadata={"source": "kb://storm-evacuation"},
    )
    near_doc = Document(
        page_content="After lightning, the pool remains closed during a cooldown window.",
        metadata={"source": "kb://lightning-cooldown"},
    )
    noisy_doc = Document(
        page_content="Community report consensus uses recent submissions.",
        metadata={"source": "kb://community-reports"},
    )
    monkeypatch.setattr(
        graph_module,
        "_search_with_optional_scores",
        lambda _store, _question, _top_k: [
            (best_doc, 0.386),
            (near_doc, 0.352),
            (noisy_doc, 0.281),
        ],
    )

    llm = _FakeLLM(reply="KB answer from fallback")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"procedure query"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=6,
        min_score=0.6,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "What is the pool evacuation procedure during a storm?"})
    assert result["answer"] == "KB answer from fallback"
    assert result["sources"] == ["kb://storm-evacuation", "kb://lightning-cooldown"]


def test_graph_knowledge_base_adds_near_threshold_support_chunks_when_context_is_thin(monkeypatch):
    doc_question = Document(
        page_content="### Q: What is the pool evacuation procedure during a storm?",
        metadata={"source": "kb://faq.md"},
    )
    doc_answer = Document(
        page_content=(
            "**A:** Lifeguards blow whistles and everyone must exit the water. "
            "Reopen only after cooldown."
        ),
        metadata={"source": "kb://faq.md"},
    )
    monkeypatch.setattr(
        graph_module,
        "_search_with_optional_scores",
        lambda _store, _question, _top_k: [
            (doc_question, 0.72),
            (doc_answer, 0.53),
        ],
    )

    llm = _FakeLLM(reply="KB answer with procedure")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"procedure query"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=6,
        min_score=0.6,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "What is the pool evacuation procedure during a storm?"})
    assert result["answer"] == "KB answer with procedure"
    assert result["sources"] == ["kb://faq.md"]

    llm_prompt = llm.calls[0][-1].content
    assert "Lifeguards blow whistles" in llm_prompt


def test_graph_backend_rules_question_falls_back_to_backend_priority_docs_when_vector_empty(monkeypatch):
    backend_doc = Document(
        page_content="Lightning close threshold: <= 15.0 km",
        metadata={"source": "app://backend/non_sensitive_snapshot"},
    )

    monkeypatch.setattr(graph_module, "_search_with_optional_scores", lambda _s, _q, _k: [])
    monkeypatch.setattr(
        graph_module,
        "_load_backend_priority_docs",
        lambda _store, _top_k: [backend_doc],
    )

    llm = _FakeLLM(reply="backend rule answer")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"backend rules"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke(
        {"question": "\u96f7\u7535\u9884\u8b66\u7684\u903b\u8f91\u662f\u600e\u4e48\u8bbe\u7f6e\u7684"}
    )
    assert result["answer"] == "backend rule answer"
    assert result["sources"] == ["app://backend/non_sensitive_snapshot"]


def test_graph_backend_rules_question_prefers_vector_context_when_available(monkeypatch):
    backend_doc = Document(
        page_content="Lightning close threshold: <= 15.0 km",
        metadata={"source": "app://backend/non_sensitive_snapshot"},
    )
    kb_doc = Document(
        page_content="Lightning Count is from the latest NEA batch and has no fixed cumulative window.",
        metadata={"source": "kb://faq.md"},
    )

    monkeypatch.setattr(
        graph_module,
        "_search_with_optional_scores",
        lambda _store, _question, _top_k: [(kb_doc, 0.72)],
    )
    monkeypatch.setattr(
        graph_module,
        "_load_backend_priority_docs",
        lambda _store, _top_k: [backend_doc],
    )

    llm = _FakeLLM(reply="vector rule answer")
    intent_llm = _IntentLLM('{"intent":"knowledge_base","reason":"backend rules"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke(
        {"question": "\u5411\u91cf\u68c0\u7d22\u7684 top_k \u53c2\u6570\u662f\u600e\u4e48\u914d\u7f6e\u7684"}
    )
    assert result["answer"] == "vector rule answer"
    assert result["sources"] == ["kb://faq.md"]


def test_graph_database_path_uses_tool_pipeline(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "_run_database_tool_use",
        lambda question, llm, max_tool_calls, reply_language="en": (
            f"DB summary for: {question}",
            ["app://community/post/100"],
        ),
    )

    llm = _FakeLLM(reply="unused")
    intent_llm = _IntentLLM('{"intent":"database","reason":"post query"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "latest post?"})
    assert result["answer"] == "DB summary for: latest post?"
    assert result["sources"] == ["app://community/post/100"]


def test_graph_database_query_keeps_original_language_and_reply_language(monkeypatch):
    """Community content is bilingual, so DB tool-use must see the original
    question (an English translation would miss Chinese posts) and must be
    asked to answer in the user's language."""
    monkeypatch.setattr(
        graph_module,
        "_translate_from_english",
        lambda text, target_language, llm: text,
    )

    captured = {}

    def _fake_run_database_tool_use(question, llm, max_tool_calls, reply_language="en"):
        captured["question"] = question
        captured["reply_language"] = reply_language
        return "\u6570\u636e\u5e93\u67e5\u8be2\u7ed3\u679c", []

    monkeypatch.setattr(graph_module, "_run_database_tool_use", _fake_run_database_tool_use)

    llm = _FakeLLM(reply="unused")
    intent_llm = _IntentLLM('{"intent":"database","reason":"report query"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "\u5217\u51fa\u6700\u65b0\u7684\u624b\u52a8\u4e0a\u62a5"})
    assert captured["question"] == "\u5217\u51fa\u6700\u65b0\u7684\u624b\u52a8\u4e0a\u62a5"
    assert captured["reply_language"] == "zh"
    assert result["answer"] == "\u6570\u636e\u5e93\u67e5\u8be2\u7ed3\u679c"


def test_translate_quick_questions_uses_deterministic_zh_mapping():
    translated = graph_module._translate_quick_questions(
        [
            "Is the pool open right now?",
            "How can I submit a manual pool report?",
            "What are the pool opening hours on weekdays and weekends?",
        ],
        target_language="zh",
        llm=_FakeLLM(reply="unused"),
    )

    assert translated == [
        "\u73b0\u5728\u6cf3\u6c60\u5f00\u653e\u5417\uff1f",
        "\u6211\u8be5\u5982\u4f55\u63d0\u4ea4\u624b\u52a8\u6cf3\u6c60\u4e0a\u62a5\uff1f",
        "\u5de5\u4f5c\u65e5\u548c\u5468\u672b\u7684\u6cf3\u6c60\u5f00\u653e\u65f6\u95f4\u662f\u4ec0\u4e48\uff1f",
    ]


def test_translate_to_english_falls_back_to_qa_model_when_intent_model_fails(monkeypatch):
    captured_failures = []

    def _capture_failure(**kwargs):
        captured_failures.append(kwargs)

    monkeypatch.setattr(graph_module, "_record_model_failure", _capture_failure)

    translated = graph_module._translate_to_english(
        "\u6cf3\u6c60\u6709\u63d0\u4f9b\u6bdb\u5dfe\u670d\u52a1\u5417\uff1f",
        _FailingLLM("intent model timeout"),
        _FakeLLM(reply="How do I register an account?"),
    )

    assert translated == "How do I register an account?"
    assert any(item["model_kind"] == graph_module.MODEL_KIND_INTENT for item in captured_failures)


def test_translate_to_english_logs_validation_failure_before_fallback(monkeypatch):
    captured_failures = []

    def _capture_failure(**kwargs):
        captured_failures.append(kwargs)

    monkeypatch.setattr(graph_module, "_record_model_failure", _capture_failure)

    translated = graph_module._translate_to_english(
        "\u6cf3\u6c60\u6709\u63d0\u4f9b\u6bdb\u5dfe\u670d\u52a1\u5417\uff1f",
        _FakeLLM(reply="\u6cf3\u6c60\u6709\u63d0\u4f9b\u6bdb\u5dfe\u670d\u52a1\u5417\uff1f"),
        _FakeLLM(reply="How do I register an account?"),
    )

    assert translated == "How do I register an account?"
    assert any(
        item["error_type"] == "TranslationValidationError" for item in captured_failures
    )


def test_graph_fallback_path_returns_fallback_reply():
    llm = _FakeLLM(reply="unused")
    intent_llm = _IntentLLM('{"intent":"fallback","reason":"out of scope"}')
    rag_app = graph_module._build_graph(
        llm=llm,
        intent_llm=intent_llm,
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = rag_app.invoke({"question": "write a C compiler from scratch"})
    assert "outside my supported scope" in result["answer"]
    assert result.get("sources", []) == []
    assert len(result["quick_questions"]) == 3
    assert set(result["quick_questions"]).issubset(set(graph_module._load_faq_questions()))


def test_search_with_optional_scores_falls_through_when_first_method_returns_empty():
    doc = Document(
        page_content="fallback doc",
        metadata={"source": "app://backend/non_sensitive_snapshot"},
    )

    class _ProbeStore:
        def similarity_search_with_relevance_scores(self, _question, k=3):
            assert k >= 3
            return []

        def similarity_search_with_score(self, _question, k=3):
            assert k >= 3
            return [(doc, 0.42)]

    results = graph_module._search_with_optional_scores(_ProbeStore(), "test", 3)
    assert len(results) == 1
    assert results[0][0].page_content == "fallback doc"
    assert results[0][1] is None


def test_search_with_optional_scores_retries_rpc_when_first_result_is_empty():
    calls: list[int] = []

    class _FakeEmbeddings:
        def embed_query(self, _question):
            return [0.1, 0.2, 0.3]

    class _FakeRPC:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            class _Resp:
                data = self.payload

            return _Resp()

    class _FakeClient:
        def rpc(self, _query_name, params):
            calls.append(int(params.get("match_count", 0)))
            if len(calls) == 1:
                return _FakeRPC([])
            return _FakeRPC(
                [
                    {
                        "content": "retried doc",
                        "metadata": {"source": "kb://faq.md"},
                        "similarity": 0.7,
                    }
                ]
            )

    class _ProbeStore:
        embeddings = _FakeEmbeddings()
        _client = _FakeClient()
        query_name = "match_documents"

    results = graph_module._search_with_optional_scores(_ProbeStore(), "test", 3)
    assert calls == [24, 48]
    assert len(results) == 1
    assert results[0][0].page_content == "retried doc"
    assert results[0][1] == 0.7


def test_run_database_tool_use_executes_tool_call_and_summarizes(monkeypatch):
    def _fake_tool() -> str:
        return json.dumps(
            {"tool": "db_fake", "data": {"value": 1}, "sources": ["db://fake"]},
            ensure_ascii=False,
        )

    fake_tool = graph_module.StructuredTool.from_function(
        func=_fake_tool,
        name="db_fake",
        description="fake db tool",
    )
    monkeypatch.setattr(graph_module, "_build_database_tools", lambda: [fake_tool])

    class _BoundLLM:
        def __init__(self):
            self.round = 0

        def invoke(self, _messages):
            self.round += 1
            if self.round == 1:
                return _FakeResponse(
                    content="",
                    tool_calls=[{"id": "call_1", "name": "db_fake", "args": {}}],
                )
            return _FakeResponse(content="done", tool_calls=[])

    class _ToolLLM:
        def __init__(self):
            self.bound = _BoundLLM()

        def bind_tools(self, _tools):
            return self.bound

        def invoke(self, _messages):
            return _FakeResponse(content="summary from db")

    answer, sources = graph_module._run_database_tool_use(
        question="show stats",
        llm=_ToolLLM(),
        max_tool_calls=3,
    )

    assert answer == "summary from db"
    assert sources == ["db://fake"]
