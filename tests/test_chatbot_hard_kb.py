"""Hard knowledge base: instant curated answers + guided suggestion chips.

Contract under test:
  * a semantically equivalent question returns the curated answer with ZERO
    model calls;
  * live/current-situation and record-lookup questions never match a static
    entry;
  * every canonical question round-trips (so a clicked suggestion chip always
    resolves instantly);
  * every reply carries exactly three suggestions in the user's language.
"""

import pytest

from app.services.chatbot import graph as graph_module
from app.services.chatbot import hard_kb


class _ExplodingLLM:
    """Any use of this means the hard-KB short circuit failed."""

    def invoke(self, _messages):
        raise AssertionError("no model call may happen for a hard-KB hit")

    def bind_tools(self, _tools):
        return self


def _build_app():
    return graph_module._build_graph(
        llm=_ExplodingLLM(),
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )


# --- data integrity ---------------------------------------------------------

def test_hard_kb_has_fifty_four_bilingual_entries():
    assert hard_kb.hard_kb_size() == 54
    ids = [entry["id"] for entry in hard_kb.HARD_KB_ENTRIES]
    assert len(ids) == len(set(ids)), "entry ids must be unique"
    for entry in hard_kb.HARD_KB_ENTRIES:
        assert entry.get("topic"), f"{entry['id']} needs topic anchors"
        for lang in ("zh", "en"):
            assert entry[lang]["q"].strip(), f"{entry['id']} missing {lang} question"
            assert entry[lang]["a"].strip(), f"{entry['id']} missing {lang} answer"
            assert len(entry[lang]["q"]) <= 90, f"{entry['id']} {lang} question too long for a chip"


def test_chinese_entries_are_chinese_and_english_entries_are_english():
    def has_cjk(text):
        return any("一" <= ch <= "鿿" for ch in text)

    for entry in hard_kb.HARD_KB_ENTRIES:
        assert has_cjk(entry["zh"]["q"]), entry["id"]
        assert has_cjk(entry["zh"]["a"]), entry["id"]
        assert not has_cjk(entry["en"]["q"]), entry["id"]
        assert not has_cjk(entry["en"]["a"]), entry["id"]


# --- matching ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("question", "expected_ids"),
    [
        # The user's own example, plus paraphrases of it.
        ("受雷电影响场馆关闭后，多长时间会重新开放？", {"lightning-cooldown"}),
        ("打雷关闭之后要等多久才能再游？", {"lightning-cooldown"}),
        ("闪电冷却多久", {"lightning-cooldown"}),
        ("How long until the pool reopens after lightning?", {"lightning-cooldown"}),
        ("lightning cooldown", {"lightning-cooldown"}),
        # Other topics, loosely worded.
        ("工作日几点开门？", {"hours-weekday"}),
        ("周末泳池几点开放", {"hours-weekend"}),
        ("公共假期是不是和周末一样的时间？", {"holiday-schedule", "hours-weekend"}),
        ("需要几条上报才能覆盖天气？", {"report-consensus"}),
        ("怎么提交上报", {"report-how"}),
        ("为什么我的NTU邮箱收不到验证码", {"ntu-email", "otp-not-received"}),
        ("怎么重置密码", {"reset-password"}),
        ("社区怎么搜索帖子", {"search-posts"}),
        ("怎么改昵称和头像", {"profile-edit"}),
        ("不登录能干什么", {"guest-permissions"}),
        ("下雨多大会关闭泳池", {"rain-rule"}),
        ("怎么私信别人", {"private-message"}),
        ("How do I report inappropriate content?", {"report-content"}),
        ("what does amber mean", {"status-colors"}),
        ("how often does status update", {"refresh-rate"}),
        ("where can i see saved posts", {"like-save"}),
        ("is this open source", {"tech-stack"}),
        # Regression coverage from the 50-question production evaluation.
        ("系统怎么判断泳池是开放还是关闭？", {"status-priority"}),
        ("15公里内出现闪电会怎样？", {"lightning-threshold"}),
        ("暴雨结束后要等多久才能重开？", {"rain-rule"}),
        ("雷达图覆盖泳池周围多大范围？", {"radar-map"}),
        ("Manual Report 有什么用？", {"report-how"}),
        ("提交人工报告时要填哪些信息？", {"report-how"}),
        ("人工报告是匿名的吗？", {"report-who"}),
        ("人工报告超过多久会被标成过时？", {"report-visibility"}),
        ("一个人能靠反复报告改变泳池状态吗？", {"report-abuse"}),
        ("周末泳池营业时间是什么？", {"hours-weekend"}),
        ("NTU 游泳池在哪里？", {"pool-entry"}),
        ("使用泳池需要付费吗？", {"pool-entry"}),
        ("进入泳池需要带什么证件？", {"pool-entry"}),
        ("泳帽和泳镜是强制的吗？", {"pool-attire"}),
        ("谁可以发布帖子和评论？", {"create-post"}),
        ("被封禁的用户还能发送私信吗？", {"private-message"}),
        ("为什么外面看起来晴天，网页却显示关闭？", {"status-sunny-closed"}),
        ("非营业时间天气很好，状态会显示开放吗？", {"hours-outside"}),
        ("雷暴时泳池如何疏散？", {"lightning-threshold"}),
        ("忘记密码后能不验证邮箱直接改密码吗？", {"reset-password"}),
        ("评论可以楼中楼回复多少层？", {"comment-reply"}),
        ("谁可以置顶帖子和封禁用户？", {"admin-moderation"}),
    ],
)
def test_paraphrases_match_the_right_entry(question, expected_ids):
    match = hard_kb.match_hard_kb(question)
    assert match is not None, f"no match for {question!r}"
    assert match[0]["id"] in expected_ids


@pytest.mark.parametrize(
    "question",
    [
        # Live situation: must go through the real pipeline.
        "现在泳池开放吗？",
        "现在适合去游泳吗",
        "Is the pool open right now?",
        "Is it safe to swim now?",
        "今天泳池人多吗",
        # Record lookups: must reach the database path.
        "今天有多少条上报？",
        "列出最新的社区帖子",
        "最近的上报有哪些",
        "show me the latest posts",
        # Out of scope.
        "帮我写一个Python爬虫",
        "推荐几部电影",
        "What is the capital of France?",
        "What is the swim cap policy for long hair?",
    ],
)
def test_dynamic_and_out_of_scope_questions_never_match(question):
    assert hard_kb.match_hard_kb(question) is None


def test_every_canonical_question_round_trips():
    """A clicked suggestion chip must always resolve to its own entry."""
    failures = []
    for entry in hard_kb.HARD_KB_ENTRIES:
        for lang in ("zh", "en"):
            question = hard_kb.question_for(entry, lang)
            match = hard_kb.match_hard_kb(question)
            if match is None or match[0]["id"] != entry["id"]:
                failures.append((entry["id"], lang, match[0]["id"] if match else None))
    assert not failures, f"chips that do not resolve to themselves: {failures}"


def test_every_variant_matches_its_own_entry():
    failures = []
    for entry in hard_kb.HARD_KB_ENTRIES:
        for variant in entry.get("variants", ()):
            match = hard_kb.match_hard_kb(variant)
            if match is None or match[0]["id"] != entry["id"]:
                failures.append((entry["id"], variant, match[0]["id"] if match else None))
    assert not failures, f"variants matching the wrong entry: {failures}"


def test_topic_anchor_does_not_match_word_fragments():
    """'api' must not fire inside 'capital'."""
    entry = next(e for e in hard_kb.HARD_KB_ENTRIES if e["id"] == "data-source")
    assert hard_kb._has_topic_anchor("what is the data source", entry) is True
    assert hard_kb._has_topic_anchor("What is the capital of France?", entry) is False


# --- graph integration ------------------------------------------------------

def test_hard_kb_hit_answers_without_any_model_call():
    app = _build_app()

    result = app.invoke({
        "question": "受雷电影响场馆关闭后，多长时间会重新开放？",
        "page_context": ["Current homepage pool status: GREEN (Open)."],
    })

    assert result["hard_kb_id"] == "lightning-cooldown"
    assert "45 分钟" in result["answer"]
    assert result["sources"] == ["app://hard-kb/lightning-cooldown"]


def test_hard_kb_answer_follows_question_language():
    app = _build_app()

    zh = app.invoke({"question": "闪电冷却多久"})
    en = app.invoke({"question": "How long is the lightning cooldown?"})

    assert zh["hard_kb_id"] == en["hard_kb_id"] == "lightning-cooldown"
    assert "45 分钟" in zh["answer"]
    assert "45-minute" in en["answer"]


def test_mixed_domain_term_question_still_answers_in_chinese():
    app = _build_app()

    result = app.invoke({"question": "Nearest Lightning 是什么意思？"})

    assert result["hard_kb_id"] == "nearest-lightning"
    assert "最近" in result["answer"]
    assert any("一" <= ch <= "鿿" for ch in result["answer"])


def test_hard_kb_hit_returns_three_suggestions_in_the_same_language():
    app = _build_app()

    result = app.invoke({"question": "怎么重置密码"})
    suggestions = result["quick_questions"]

    assert len(suggestions) == 3
    canonical_zh = {hard_kb.question_for(e, "zh") for e in hard_kb.HARD_KB_ENTRIES}
    assert set(suggestions) <= canonical_zh
    # Never suggest the question just answered.
    assert hard_kb.question_for(
        next(e for e in hard_kb.HARD_KB_ENTRIES if e["id"] == "reset-password"), "zh"
    ) not in suggestions


def test_suggestions_are_clickable_round_trip():
    """Every suggested chip, when sent back, answers from the hard KB."""
    app = _build_app()
    result = app.invoke({"question": "怎么重置密码"})

    for suggestion in result["quick_questions"]:
        follow_up = app.invoke({"question": suggestion})
        assert follow_up.get("hard_kb_id"), f"chip did not resolve: {suggestion}"
        assert follow_up["answer"].strip()


def test_live_question_still_uses_the_normal_pipeline(monkeypatch):
    """A current-situation question must not be short-circuited."""
    monkeypatch.setattr(
        graph_module, "_search_with_optional_scores", lambda _s, _q, _k: []
    )

    class _LLM:
        def __init__(self):
            self.calls = []

        def invoke(self, messages):
            self.calls.append(messages)

            class _R:
                content = "现在状态为开放，可以前往。"
                tool_calls = []

            return _R()

        def bind_tools(self, _t):
            return self

    llm = _LLM()
    app = graph_module._build_graph(
        llm=llm,
        intent_llm=_ExplodingLLM(),
        vector_store=object(),
        top_k=3,
        min_score=0.65,
        max_context_chars=4000,
        db_tool_max_calls=3,
    )

    result = app.invoke({
        "question": "现在适合去游泳吗？",
        "page_context": ["Current homepage pool status: GREEN (Open)."],
    })

    assert result.get("hard_kb_id") is None
    assert llm.calls, "live question must reach the model"
    # Suggestions are still attached to guide the user.
    assert len(result["quick_questions"]) == 3


def test_suggested_questions_excludes_requested_ids():
    picks = hard_kb.suggested_questions("en", count=3, exclude_ids=("reset-password",))
    excluded = hard_kb.question_for(
        next(e for e in hard_kb.HARD_KB_ENTRIES if e["id"] == "reset-password"), "en"
    )
    assert excluded not in picks
    assert len(picks) == 3
