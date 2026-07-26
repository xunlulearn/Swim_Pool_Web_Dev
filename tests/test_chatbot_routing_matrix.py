"""Routing matrix: the intent heuristics must stay correct across a broad,
bilingual question set.

Each block below encodes a root cause found during live production testing:

* usage vs data      — "How do I search for posts" is documentation, not a
                       request to fetch post records.
* rule vs count      — "how many reports are NEEDED" states a requirement;
                       "how many reports today" counts stored rows.
* bilingual parity   — Chinese questions must hit the same guards as English
                       (the hint lists used to be English-only in places).
* fragment matching  — hints must match whole words: "api" must not fire on
                       "capital", "dev" must not fire on "develop".
"""

import pytest

from app.services.chatbot import graph as graph_module


KB = graph_module.INTENT_KNOWLEDGE_BASE
DB = graph_module.INTENT_DATABASE
ST = graph_module.INTENT_SMALL_TALK
CAP = graph_module.INTENT_CAPABILITY
FB = graph_module.INTENT_FALLBACK


USAGE_QUESTIONS = [
    "How do I like or save a post?",
    "怎么收藏帖子？",
    "How do I reply to a comment?",
    "怎么回复评论？",
    "How do I change my password?",
    "怎么重置密码？",
    "How do I upload an avatar?",
    "怎么上传头像？",
    "How do I submit a manual pool report?",
    "我该如何提交手动上报？",
    "Where can I see my saved posts?",
    "在哪里能看到我收藏的帖子？",
    "How do I delete my own post?",
    "怎么删除自己的帖子？",
    "Is there a way to filter posts by category?",
    "How do I search for posts in the community?",
    "怎么在社区里搜索帖子？",
]

POLICY_QUESTIONS = [
    "Who is allowed to submit a report?",
    "谁可以上报泳池状态？",
    "Do I need to verify my email to post?",
    "发帖需要邮箱验证吗？",
    "Can guests browse the community?",
    "游客可以浏览社区吗？",
]

RULES_AND_HOURS_QUESTIONS = [
    "What time does the pool close on Sunday?",
    "周日泳池几点关门？",
    "How does heavy rain affect pool status?",
    "大雨会怎么影响泳池状态？",
    "What does AMBER status mean?",
    "黄色状态是什么意思？",
    "Is the pool open on public holidays?",
    "公共假期泳池开放吗？",
    "需要多少条上报才能覆盖天气状态？",
    "How many reports are needed to override weather status?",
]

LIVE_DECISION_QUESTIONS = [
    "Can I go swimming now?",
    "现在能去游泳吗？",
    "Is it safe to swim right now?",
    "我30分钟后过去合适吗？",
]

DATABASE_QUESTIONS = [
    "What are the latest 5 posts?",
    "最新的5条帖子是什么？",
    "How many reports were submitted today?",
    "今天有多少条上报？",
    "Show me post id 12",
    "显示帖子 id 12",
    "What are the most recent pool reports?",
    "最近的泳池上报有哪些？",
    "List posts in the lost and found category",
    "Search posts about goggles",
    "show me the latest posts",
    "列出最新的社区帖子",
    "可以给我看最新的帖子吗？",
]

SMALL_TALK_QUESTIONS = ["hi", "你好", "thanks", "谢谢", "good morning"]

CAPABILITY_QUESTIONS = ["What can you do?", "你能帮我什么？", "what can I ask you?"]

OUT_OF_SCOPE_QUESTIONS = [
    "Write me a Python web scraper",
    "帮我写一份简历",
    "What is the capital of France?",
    "推荐几部电影",
    "How do I develop a mobile app?",
    "今天股市怎么样？",
]


@pytest.mark.parametrize("question", USAGE_QUESTIONS)
def test_usage_questions_route_to_knowledge_base(question):
    assert graph_module._heuristic_intent(question) == KB


@pytest.mark.parametrize("question", POLICY_QUESTIONS)
def test_policy_questions_route_to_knowledge_base(question):
    assert graph_module._heuristic_intent(question) == KB


@pytest.mark.parametrize("question", RULES_AND_HOURS_QUESTIONS)
def test_rules_and_hours_route_to_knowledge_base(question):
    assert graph_module._heuristic_intent(question) == KB


@pytest.mark.parametrize("question", LIVE_DECISION_QUESTIONS)
def test_live_decision_questions_route_to_knowledge_base(question):
    assert graph_module._heuristic_intent(question) == KB


@pytest.mark.parametrize("question", DATABASE_QUESTIONS)
def test_record_lookups_route_to_database(question):
    assert graph_module._heuristic_intent(question) == DB


@pytest.mark.parametrize("question", SMALL_TALK_QUESTIONS)
def test_small_talk_routes_correctly(question):
    assert graph_module._heuristic_intent(question) == ST


@pytest.mark.parametrize("question", CAPABILITY_QUESTIONS)
def test_capability_questions_route_correctly(question):
    assert graph_module._heuristic_intent(question) == CAP


@pytest.mark.parametrize("question", OUT_OF_SCOPE_QUESTIONS)
def test_out_of_scope_questions_fall_back(question):
    assert graph_module._heuristic_intent(question) == FB


# --- hint matching semantics -------------------------------------------------

@pytest.mark.parametrize(
    ("text", "hints", "expected"),
    [
        # Fragments must NOT match.
        ("What is the capital of France?", ("api",), False),
        ("How do I develop a mobile app?", ("dev",), False),
        ("That was really helpful", ("help",), False),
        ("I need a new device", ("dev",), False),
        # Whole words and plurals MUST match.
        ("the api is down", ("api",), True),
        ("show me the reports", ("report",), True),
        ("latest posts please", ("post",), True),
        ("who likes this", ("like",), True),
        # CJK keeps substring semantics (no word boundaries in Chinese).
        ("怎么在社区里搜索帖子？", ("帖子",), True),
        ("今天有多少条上报？", ("上报",), True),
        ("完全无关的问题", ("帖子",), False),
    ],
)
def test_hint_matching_uses_word_boundaries(text, hints, expected):
    assert graph_module._contains_hint(text, hints) is expected


def test_every_hint_list_has_both_languages():
    """Guards against reintroducing an English-only decision list."""
    bilingual_lists = {
        "KNOWLEDGE_BASE_HINTS": graph_module.KNOWLEDGE_BASE_HINTS,
        "DATABASE_HINTS": graph_module.DATABASE_HINTS,
        "DATABASE_LOOKUP_HINTS": graph_module.DATABASE_LOOKUP_HINTS,
        "POLICY_QUESTION_HINTS": graph_module.POLICY_QUESTION_HINTS,
        "POLICY_DOMAIN_HINTS": graph_module.POLICY_DOMAIN_HINTS,
        "RECORD_SCOPE_HINTS": graph_module.RECORD_SCOPE_HINTS,
        "LIVE_POOL_DOMAIN_HINTS": graph_module.LIVE_POOL_DOMAIN_HINTS,
        "LIVE_POOL_DECISION_HINTS": graph_module.LIVE_POOL_DECISION_HINTS,
    }
    for name, hints in bilingual_lists.items():
        has_cjk = any(graph_module._hint_is_cjk(hint) for hint in hints)
        has_ascii = any(not graph_module._hint_is_cjk(hint) for hint in hints)
        assert has_cjk, f"{name} has no Chinese entries"
        assert has_ascii, f"{name} has no English entries"
