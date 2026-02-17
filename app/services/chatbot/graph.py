from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, NotRequired, TypedDict
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph
from supabase import create_client


INTENT_SMALL_TALK = "small_talk"
INTENT_DATABASE = "database"
INTENT_KNOWLEDGE_BASE = "knowledge_base"
INTENT_FALLBACK = "fallback"
VALID_INTENTS = {
    INTENT_SMALL_TALK,
    INTENT_DATABASE,
    INTENT_KNOWLEDGE_BASE,
    INTENT_FALLBACK,
}

RAG_SYSTEM_PROMPT = (
    "You are the official customer assistant for NTU Pool (ntupool.org). "
    "Answer strictly from the provided reference context only. "
    "If the context is insufficient, clearly say you do not know and suggest checking ntupool.org. "
    "Always reply in the same language as the user."
)

SMALL_TALK_SYSTEM_PROMPT = (
    "You are the official customer assistant for NTU Pool (ntupool.org). "
    "This is casual conversation. Reply naturally and briefly, and use the same language as the user."
)

INTENT_SYSTEM_PROMPT = (
    "You are an intent classifier for NTU Pool assistant. "
    "Classify the user message into exactly one intent and return JSON only.\n\n"
    "Valid intents:\n"
    '- "small_talk": greeting/chitchat/emotion with no factual query.\n'
    '- "database": asks about dynamic app database records: community posts/comments/likes/collections/manual pool reports.\n'
    '- "knowledge_base": asks about ntupool.org website knowledge, policies, operations, weather/source rules, or app feature rules documented in KB.\n'
    '- "fallback": anything outside scope or unclear.\n\n'
    'Return exactly this schema: {"intent":"small_talk|database|knowledge_base|fallback","reason":"short reason"}.\n'
    "Do not answer the user question."
)

DATABASE_TOOL_SELECTION_PROMPT = (
    "You must answer NTU Pool database queries by calling tools first. "
    "Always call one or more tools before writing a final answer. "
    "Prefer tools about posts/comments/reports when relevant."
)

DATABASE_SUMMARY_PROMPT = (
    "You are the NTU Pool assistant. "
    "You will receive a user question and JSON tool results fetched from the database. "
    "Answer strictly from the tool results. If no useful data exists, say so clearly. "
    "Keep the answer concise and in the same language as the user."
)

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_INTENT_MODEL = "liquid/lfm-2.5-1.2b-thinking:free"
DEFAULT_INTENT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TABLE = "pool_documents"
DEFAULT_MATCH_FUNCTION = "match_documents"
DEFAULT_TOP_K = 3
DEFAULT_MIN_SCORE = 0.45
DEFAULT_FALLBACK_MIN_SCORE = 0.25
DEFAULT_MAX_CONTEXT_CHARS = 4000
DEFAULT_DB_TOOL_MAX_CALLS = 4

DEFAULT_UNKNOWN_REPLY_ZH = (
    "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u65e0\u6cd5\u4ece\u53ef\u7528\u5185\u5bb9\u4e2d\u786e\u8ba4\u8fd9\u4e2a\u95ee\u9898\uff0c"
    "\u8bf7\u4ee5 ntupool.org \u7684\u6700\u65b0\u4fe1\u606f\u4e3a\u51c6\u3002"
)
DEFAULT_UNKNOWN_REPLY_EN = (
    "Sorry, I cannot confirm this from available content right now. "
    "Please refer to the latest information on ntupool.org."
)
DEFAULT_UNKNOWN_REPLY = DEFAULT_UNKNOWN_REPLY_ZH

DEFAULT_FALLBACK_REPLY_ZH = (
    "\u8fd9\u4e2a\u95ee\u9898\u6682\u4e0d\u5728\u6211\u7684\u652f\u6301\u8303\u56f4\u5185\u3002"
    "\u4f60\u53ef\u4ee5\u95ee\u6211\uff1a\u95f2\u804a\u3001\u793e\u533a\u5e16\u5b50/\u4e0a\u62a5\u6570\u636e\u5e93\u67e5\u8be2\uff0c"
    "\u6216 ntupool.org \u7ad9\u70b9\u77e5\u8bc6\u95ee\u9898\u3002"
)
DEFAULT_FALLBACK_REPLY_EN = (
    "This question is currently outside my supported scope. "
    "You can ask me small talk, database queries about community posts/reports, "
    "or ntupool.org knowledge questions."
)

DEFAULT_DATABASE_EMPTY_REPLY_ZH = (
    "\u6211\u5df2\u67e5\u8be2\u6570\u636e\u5e93\uff0c\u4f46\u6ca1\u6709\u627e\u5230\u53ef\u7528\u6570\u636e\u6765\u56de\u7b54\u8fd9\u4e2a\u95ee\u9898\u3002"
)
DEFAULT_DATABASE_EMPTY_REPLY_EN = (
    "I queried the database but could not find useful data for this question."
)

SMALL_TALK_EXACT = {
    "hi",
    "hello",
    "hey",
    "yo",
    "sup",
    "whatsup",
    "howareyou",
    "goodmorning",
    "goodafternoon",
    "goodevening",
    "thanks",
    "thankyou",
    "thx",
    "\u4f60\u597d",
    "\u60a8\u597d",
    "\u55e8",
    "\u54c8\u55bd",
    "\u5728\u5417",
    "\u65e9\u4e0a\u597d",
    "\u4e0b\u5348\u597d",
    "\u665a\u4e0a\u597d",
    "\u8c22\u8c22",
    "\u8f9b\u82e6\u4e86",
}

SMALL_TALK_PREFIX = (
    "hi",
    "hello",
    "hey",
    "yo",
    "sup",
    "howareyou",
    "\u4f60\u597d",
    "\u60a8\u597d",
    "\u55e8",
    "\u54c8\u55bd",
    "\u5728\u5417",
)

DATABASE_HINTS = (
    "post",
    "posts",
    "comment",
    "comments",
    "like",
    "likes",
    "collection",
    "collections",
    "manual report",
    "pool report",
    "latest post",
    "\u5e16\u5b50",
    "\u8bc4\u8bba",
    "\u70b9\u8d5e",
    "\u6536\u85cf",
    "\u4e0a\u62a5",
    "\u793e\u533a",
)

KNOWLEDGE_BASE_HINTS = (
    "pool",
    "swim",
    "swimming",
    "status",
    "open",
    "close",
    "weather",
    "lightning",
    "rain",
    "ntupool",
    "website",
    "official",
    "policy",
    "api",
    "contact",
    "developer",
    "dev",
    "maintainer",
    "author",
    "support",
    "help",
    "about",
    "team",
    "github",
    "email",
    "gmail",
    "wechat",
    "open-source",
    "opensource",
    "\u6cf3\u6c60",
    "\u5f00\u653e",
    "\u5173\u95ed",
    "\u5929\u6c14",
    "\u95ea\u7535",
    "\u4e0b\u96e8",
    "\u5b98\u7f51",
    "\u89c4\u5219",
    "\u8054\u7cfb",
    "\u5f00\u53d1\u8005",
    "\u4f5c\u8005",
    "\u7ef4\u62a4\u8005",
    "\u90ae\u7bb1",
    "\u90ae\u4ef6",
    "\u5fae\u4fe1",
    "\u5ba2\u670d",
    "\u652f\u6301",
    "\u5e2e\u52a9",
    "\u5173\u4e8e",
    "\u9879\u76ee",
    "\u5f00\u6e90",
)

BACKEND_RULE_CORE_HINTS = (
    "logic",
    "rule",
    "rules",
    "configured",
    "setting",
    "settings",
    "threshold",
    "persistence",
    "window",
    "consensus",
    "runtime",
    "config",
    "configuration",
    "top_k",
    "min score",
    "max context",
    "how set",
    "\u903b\u8f91",
    "\u89c4\u5219",
    "\u8bbe\u7f6e",
    "\u9608\u503c",
    "\u7a97\u53e3",
    "\u6301\u7eed",
    "\u591a\u4e45",
    "\u914d\u7f6e",
    "\u53c2\u6570",
)

BACKEND_RULE_DOMAIN_HINTS = (
    "lightning",
    "lightening",
    "rain",
    "rainfall",
    "weather",
    "report",
    "pool status",
    "chatbot",
    "rag",
    "retrieval",
    "embedding",
    "vector",
    "api",
    "\u96f7\u7535",
    "\u95ea\u7535",
    "\u4e0b\u96e8",
    "\u964d\u96e8",
    "\u5929\u6c14",
    "\u4e0a\u62a5",
    "\u6cf3\u6c60\u72b6\u6001",
    "\u673a\u5668\u4eba",
    "\u77e5\u8bc6\u5e93",
    "\u68c0\u7d22",
    "\u5411\u91cf",
    "\u63a5\u53e3",
)


class ChatbotConfigError(RuntimeError):
    pass


class GraphState(TypedDict, total=False):
    question: str
    intent: NotRequired[str]
    mode: NotRequired[str]
    context: NotRequired[list[str]]
    answer: NotRequired[str]
    sources: NotRequired[list[str]]


_graph_lock = threading.Lock()
_cached_graph: Any | None = None
_cached_key: tuple[Any, ...] | None = None


def _require(name: str, fallback: str = "") -> str:
    value = os.getenv(name, fallback).strip()
    if not value:
        raise ChatbotConfigError(f"Missing required environment variable: {name}")
    return value


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ChatbotConfigError(f"Invalid float value for {name}: {raw}") from exc


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ChatbotConfigError(f"Invalid integer value for {name}: {raw}") from exc


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _detect_language(text: str) -> str:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    if cjk_count > latin_count:
        return "zh"
    if latin_count > 0:
        return "en"
    return "zh"


def _unknown_reply_for_question(question: str) -> str:
    if _detect_language(question) == "en":
        return DEFAULT_UNKNOWN_REPLY_EN
    return DEFAULT_UNKNOWN_REPLY_ZH


def _fallback_reply_for_question(question: str) -> str:
    if _detect_language(question) == "en":
        return DEFAULT_FALLBACK_REPLY_EN
    return DEFAULT_FALLBACK_REPLY_ZH


def _database_empty_reply_for_question(question: str) -> str:
    if _detect_language(question) == "en":
        return DEFAULT_DATABASE_EMPTY_REPLY_EN
    return DEFAULT_DATABASE_EMPTY_REPLY_ZH


def _is_small_talk_heuristic(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False

    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lowered)
    if not compact:
        return False
    if compact in SMALL_TALK_EXACT:
        return True
    if len(compact) <= 24 and any(compact.startswith(prefix) for prefix in SMALL_TALK_PREFIX):
        return True
    return False


def _looks_like_database_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in DATABASE_HINTS)


def _looks_like_kb_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in KNOWLEDGE_BASE_HINTS)


def _is_backend_rules_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False

    has_domain_signal = any(token in lowered for token in BACKEND_RULE_DOMAIN_HINTS)
    has_core_signal = any(token in lowered for token in BACKEND_RULE_CORE_HINTS)
    if has_domain_signal and has_core_signal:
        return True

    # Explicit common phrases should pass directly.
    direct_phrases = (
        "lightning alert logic",
        "lightning warning logic",
        "weather status logic",
        "\u96f7\u7535\u9884\u8b66\u903b\u8f91",
        "\u95ea\u7535\u9884\u8b66\u903b\u8f91",
        "\u5929\u6c14\u72b6\u6001\u903b\u8f91",
    )
    return any(phrase in lowered for phrase in direct_phrases)


def _normalize_intent(value: str | None) -> str:
    lowered = (value or "").strip().lower()
    mapping = {
        "small_talk": INTENT_SMALL_TALK,
        "smalltalk": INTENT_SMALL_TALK,
        "chat": INTENT_SMALL_TALK,
        "chitchat": INTENT_SMALL_TALK,
        "database": INTENT_DATABASE,
        "database_query": INTENT_DATABASE,
        "db": INTENT_DATABASE,
        "knowledge_base": INTENT_KNOWLEDGE_BASE,
        "knowledge": INTENT_KNOWLEDGE_BASE,
        "kb": INTENT_KNOWLEDGE_BASE,
        "rag": INTENT_KNOWLEDGE_BASE,
        "website_knowledge": INTENT_KNOWLEDGE_BASE,
        "fallback": INTENT_FALLBACK,
        "other": INTENT_FALLBACK,
        "unknown": INTENT_FALLBACK,
    }
    return mapping.get(lowered, INTENT_FALLBACK)


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _heuristic_intent(question: str) -> str:
    if _is_small_talk_heuristic(question):
        return INTENT_SMALL_TALK
    if _looks_like_database_question(question):
        return INTENT_DATABASE
    if _looks_like_kb_question(question):
        return INTENT_KNOWLEDGE_BASE
    return INTENT_FALLBACK


def _merge_model_intent_with_heuristic(question: str, model_intent: str | None) -> str:
    normalized_model_intent = _normalize_intent(model_intent)
    heuristic_intent = _heuristic_intent(question)

    # Guardrail: when model says fallback but heuristics strongly detect an in-scope query,
    # trust heuristics to avoid false fallback and route into DB/RAG flow.
    if normalized_model_intent == INTENT_FALLBACK and heuristic_intent != INTENT_FALLBACK:
        return heuristic_intent
    if normalized_model_intent in VALID_INTENTS:
        return normalized_model_intent
    return heuristic_intent


def _classify_intent(question: str, intent_llm: ChatOpenAI) -> str:
    text = (question or "").strip()
    if not text:
        return INTENT_FALLBACK

    try:
        response = intent_llm.invoke(
            [
                SystemMessage(content=INTENT_SYSTEM_PROMPT),
                HumanMessage(content=text),
            ]
        )
        raw = response.content
        raw_text = raw if isinstance(raw, str) else str(raw)
        payload = _extract_json_object(raw_text)
        if payload:
            return _merge_model_intent_with_heuristic(
                text,
                str(payload.get("intent", "")),
            )
    except Exception:
        pass

    return _heuristic_intent(text)


def _load_docs_by_source_type(
    vector_store: SupabaseVectorStore, *, source_type: str, limit: int
) -> list[Document]:
    client = getattr(vector_store, "_client", None)
    table_name = str(getattr(vector_store, "table_name", DEFAULT_TABLE) or DEFAULT_TABLE)
    if client is None:
        return []

    try:
        response = (
            client.table(table_name)
            .select("content,metadata")
            .contains("metadata", {"source_type": source_type})
            .limit(max(1, int(limit)))
            .execute()
        )
    except Exception:
        return []

    rows = (response.data or []) if hasattr(response, "data") else []
    docs: list[Document] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        docs.append(Document(page_content=content, metadata=metadata))
    return docs


def _build_runtime_backend_snapshot_doc() -> Document | None:
    try:
        from app.services.weather_engine import WeatherEngine
    except Exception:
        return None

    max_content_length = int(os.getenv("MAX_CONTENT_LENGTH") or (2 * 1024 * 1024))
    max_size_mb = max_content_length / (1024 * 1024)
    chatbot_top_k = int(os.getenv("CHATBOT_TOP_K") or DEFAULT_TOP_K)
    chatbot_min_score = float(os.getenv("CHATBOT_MIN_SCORE") or DEFAULT_MIN_SCORE)
    chatbot_max_chars = int(os.getenv("CHATBOT_MAX_CONTEXT_CHARS") or DEFAULT_MAX_CONTEXT_CHARS)
    embed_model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL).strip() or DEFAULT_EMBED_MODEL
    chat_model = os.getenv("OPENAI_CHAT_MODEL", DEFAULT_CHAT_MODEL).strip() or DEFAULT_CHAT_MODEL
    docs_table = os.getenv("SUPABASE_DOCS_TABLE", DEFAULT_TABLE).strip() or DEFAULT_TABLE
    match_function = (
        os.getenv("SUPABASE_MATCH_FUNCTION", DEFAULT_MATCH_FUNCTION).strip()
        or DEFAULT_MATCH_FUNCTION
    )

    lines = [
        "# NTU Pool Runtime Non-sensitive Rules Snapshot",
        "",
        "## Weather Data Sources",
        f"- Lightning API: {WeatherEngine.LIGHTNING_API_URL}",
        f"- Rainfall API: {WeatherEngine.RAINFALL_API_URL}",
        "",
        "## Pool Status Rules (Code-level)",
        f"- Lightning close threshold: <= {WeatherEngine.LIGHTNING_WARN_THRESHOLD} km",
        f"- Lightning hard-close threshold: <= {WeatherEngine.LIGHTNING_CLOSE_THRESHOLD} km",
        f"- Rain warning threshold: > {WeatherEngine.RAINFALL_WARN_THRESHOLD} mm/h",
        "- Lightning close persistence window: 45 minutes",
        "- Rain close persistence window: 30 minutes",
        "- Community consensus rule: 30 minutes window, latest 5 reports, 5 distinct users, unanimous status, valid for 10 minutes",
        "",
        "## Chatbot Runtime Settings",
        f"- Chat model: {chat_model}",
        f"- Embedding model: {embed_model}",
        f"- Vector table: {docs_table}",
        f"- Match function: {match_function}",
        f"- Retrieval top_k: {chatbot_top_k}",
        f"- Retrieval min score: {chatbot_min_score}",
        f"- Max context chars: {chatbot_max_chars}",
        "",
        "## Upload and Content Limits",
        f"- MAX_CONTENT_LENGTH: {max_content_length} bytes (~{max_size_mb:.2f} MB)",
    ]

    return Document(
        page_content="\n".join(lines),
        metadata={
            "source_type": "backend_runtime_live",
            "source": "app://backend/runtime_snapshot_live",
        },
    )


def _load_backend_priority_docs(vector_store: SupabaseVectorStore, top_k: int) -> list[Document]:
    docs: list[Document] = []
    seen_sources: set[str] = set()

    runtime_doc = _build_runtime_backend_snapshot_doc()
    if runtime_doc is not None:
        docs.append(runtime_doc)
        source = str((runtime_doc.metadata or {}).get("source") or "").strip()
        if source:
            seen_sources.add(source)

    for source_type in ("backend_non_sensitive", "realtime_status_snapshot"):
        for doc in _load_docs_by_source_type(
            vector_store,
            source_type=source_type,
            limit=max(int(top_k or 0), 8),
        ):
            source = str((getattr(doc, "metadata", {}) or {}).get("source") or "").strip()
            if source and source in seen_sources:
                continue
            docs.append(doc)
            if source:
                seen_sources.add(source)
    return docs


def _search_with_optional_scores(
    vector_store: SupabaseVectorStore, question: str, top_k: int
) -> list[tuple[Any, float | None]]:
    if hasattr(vector_store, "similarity_search_with_relevance_scores"):
        try:
            pairs = vector_store.similarity_search_with_relevance_scores(question, k=top_k)
            if pairs:
                return [(doc, _coerce_score(score)) for doc, score in pairs]
        except Exception:
            pass

    if hasattr(vector_store, "similarity_search_with_score"):
        try:
            pairs = vector_store.similarity_search_with_score(question, k=top_k)
            # Some vector stores return distance-like scores where lower is better.
            # Keep compatibility by skipping threshold filtering for this branch.
            if pairs:
                return [(doc, None) for doc, _score in pairs]
        except Exception:
            pass

    if hasattr(vector_store, "similarity_search"):
        try:
            docs = vector_store.similarity_search(question, k=top_k)
            if docs:
                return [(doc, None) for doc in docs]
        except Exception:
            pass

    embedding_model = getattr(vector_store, "embeddings", None) or getattr(
        vector_store, "_embedding", None
    )
    client = getattr(vector_store, "_client", None)
    query_name = getattr(vector_store, "query_name", DEFAULT_MATCH_FUNCTION)
    if embedding_model is None or client is None:
        return []

    query_embedding = embedding_model.embed_query(question)
    response = client.rpc(
        query_name,
        {
            "query_embedding": query_embedding,
            "match_count": top_k,
            "filter": {},
        },
    ).execute()

    rows = (response.data or []) if hasattr(response, "data") else []
    results: list[tuple[Any, float | None]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        results.append(
            (
                Document(page_content=content, metadata=metadata),
                _coerce_score(row.get("similarity")),
            )
        )
    return results


def _truncate_context(context_chunks: list[str], max_chars: int) -> str:
    if not context_chunks:
        return ""
    merged = "\n\n".join(
        f"[Context {idx}] {chunk}" for idx, chunk in enumerate(context_chunks, start=1)
    )
    return merged[:max_chars]


def _append_doc_to_context(doc: Any, context: list[str], sources: list[str]) -> None:
    text = (getattr(doc, "page_content", "") or "").strip()
    if not text:
        return
    context.append(text)

    metadata = getattr(doc, "metadata", {}) or {}
    source = metadata.get("source") or metadata.get("url")
    if source and source not in sources:
        sources.append(str(source))


def _build_vector_store(
    *,
    supabase_url: str,
    supabase_key: str,
    embed_model: str,
    table_name: str,
    query_name: str,
) -> SupabaseVectorStore:
    client = create_client(supabase_url, supabase_key)
    embeddings = OpenAIEmbeddings(model=embed_model)
    return SupabaseVectorStore(
        client=client,
        embedding=embeddings,
        table_name=table_name,
        query_name=query_name,
    )


def _build_llm(*, model: str, api_key: str, base_url: str) -> ChatOpenAI:
    kwargs: dict[str, Any] = {"model": model, "temperature": 0}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def _clamp_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _safe_iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _safe_text(value: Any, *, max_chars: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def _db_get_latest_posts(limit: int = 5, category: str = "") -> str:
    try:
        from app.models import Post
    except Exception as exc:
        return json.dumps({"error": f"Failed to import Post model: {exc}", "sources": []})

    safe_limit = _clamp_int(limit, minimum=1, maximum=20, default=5)
    query = Post.query.filter(Post.is_deleted.is_(False))
    normalized_category = str(category or "").strip().lower()
    if normalized_category:
        query = query.filter(Post.category == normalized_category)

    posts = query.order_by(Post.created_at.desc()).limit(safe_limit).all()

    data: list[dict[str, Any]] = []
    sources: list[str] = []
    for post in posts:
        post_id = int(getattr(post, "id", 0) or 0)
        source = f"app://community/post/{post_id}" if post_id else ""
        author = getattr(getattr(post, "author", None), "username", "") or ""
        like_count = post.likes.count() if hasattr(post, "likes") else 0
        comment_count = (
            post.comments.filter_by(is_deleted=False).count() if hasattr(post, "comments") else 0
        )
        item = {
            "id": post_id,
            "title": _safe_text(getattr(post, "title", ""), max_chars=120),
            "category": str(getattr(post, "category", "") or ""),
            "author": str(author),
            "created_at": _safe_iso(getattr(post, "created_at", None)),
            "like_count": int(like_count),
            "comment_count": int(comment_count),
            "source": source,
        }
        data.append(item)
        if source:
            sources.append(source)

    return json.dumps(
        {"tool": "db_get_latest_posts", "data": data, "sources": sources},
        ensure_ascii=False,
    )


def _db_search_posts(keyword: str, limit: int = 5) -> str:
    text = str(keyword or "").strip()
    if not text:
        return json.dumps(
            {"tool": "db_search_posts", "data": [], "sources": [], "error": "keyword is required"},
            ensure_ascii=False,
        )

    try:
        from sqlalchemy import or_
        from app.models import Post
    except Exception as exc:
        return json.dumps({"error": f"Failed to import DB dependencies: {exc}", "sources": []})

    safe_limit = _clamp_int(limit, minimum=1, maximum=20, default=5)
    pattern = f"%{text}%"
    posts = (
        Post.query.filter(Post.is_deleted.is_(False))
        .filter(or_(Post.title.ilike(pattern), Post.body.ilike(pattern)))
        .order_by(Post.created_at.desc())
        .limit(safe_limit)
        .all()
    )

    data: list[dict[str, Any]] = []
    sources: list[str] = []
    for post in posts:
        post_id = int(getattr(post, "id", 0) or 0)
        source = f"app://community/post/{post_id}" if post_id else ""
        item = {
            "id": post_id,
            "title": _safe_text(getattr(post, "title", ""), max_chars=120),
            "snippet": _safe_text(getattr(post, "body", ""), max_chars=180),
            "category": str(getattr(post, "category", "") or ""),
            "created_at": _safe_iso(getattr(post, "created_at", None)),
            "source": source,
        }
        data.append(item)
        if source:
            sources.append(source)

    return json.dumps(
        {"tool": "db_search_posts", "data": data, "sources": sources},
        ensure_ascii=False,
    )


def _db_get_post_detail(post_id: int) -> str:
    safe_post_id = _clamp_int(post_id, minimum=1, maximum=2_000_000_000, default=0)
    if safe_post_id <= 0:
        return json.dumps(
            {"tool": "db_get_post_detail", "data": None, "sources": [], "error": "invalid post_id"},
            ensure_ascii=False,
        )

    try:
        from app.models import Post
    except Exception as exc:
        return json.dumps({"error": f"Failed to import Post model: {exc}", "sources": []})

    post = Post.query.filter(Post.is_deleted.is_(False), Post.id == safe_post_id).first()
    if post is None:
        return json.dumps(
            {"tool": "db_get_post_detail", "data": None, "sources": [], "error": "post not found"},
            ensure_ascii=False,
        )

    author = getattr(getattr(post, "author", None), "username", "") or ""
    like_count = post.likes.count() if hasattr(post, "likes") else 0
    comment_count = (
        post.comments.filter_by(is_deleted=False).count() if hasattr(post, "comments") else 0
    )
    source = f"app://community/post/{safe_post_id}"
    data = {
        "id": safe_post_id,
        "title": str(getattr(post, "title", "") or ""),
        "body": _safe_text(getattr(post, "body", ""), max_chars=1200),
        "category": str(getattr(post, "category", "") or ""),
        "author": str(author),
        "created_at": _safe_iso(getattr(post, "created_at", None)),
        "like_count": int(like_count),
        "comment_count": int(comment_count),
        "source": source,
    }
    return json.dumps(
        {"tool": "db_get_post_detail", "data": data, "sources": [source]},
        ensure_ascii=False,
    )


def _db_get_forum_stats() -> str:
    try:
        from app.models import Collection, Comment, Like, PoolReport, Post
    except Exception as exc:
        return json.dumps({"error": f"Failed to import models: {exc}", "sources": []})

    payload = {
        "post_count": Post.query.filter(Post.is_deleted.is_(False)).count(),
        "comment_count": Comment.query.filter(Comment.is_deleted.is_(False)).count(),
        "like_count": Like.query.count(),
        "collection_count": Collection.query.count(),
        "pool_report_count": PoolReport.query.count(),
    }
    return json.dumps(
        {
            "tool": "db_get_forum_stats",
            "data": payload,
            "sources": ["db://forum/stats"],
        },
        ensure_ascii=False,
    )


def _db_get_recent_pool_reports(limit: int = 10) -> str:
    try:
        from app.models import PoolReport
    except Exception as exc:
        return json.dumps({"error": f"Failed to import PoolReport model: {exc}", "sources": []})

    safe_limit = _clamp_int(limit, minimum=1, maximum=30, default=10)
    reports = PoolReport.query.order_by(PoolReport.created_at.desc()).limit(safe_limit).all()

    data: list[dict[str, Any]] = []
    sources: list[str] = []
    for report in reports:
        report_id = int(getattr(report, "id", 0) or 0)
        source = f"app://pool-report/{report_id}" if report_id else ""
        user_name = getattr(getattr(report, "user", None), "username", "") or ""
        item = {
            "id": report_id,
            "status": str(getattr(report, "status", "") or ""),
            "user": str(user_name),
            "created_at": _safe_iso(getattr(report, "created_at", None)),
            "source": source,
        }
        data.append(item)
        if source:
            sources.append(source)

    return json.dumps(
        {
            "tool": "db_get_recent_pool_reports",
            "data": data,
            "sources": sources,
        },
        ensure_ascii=False,
    )


def _build_database_tools() -> list[StructuredTool]:
    return [
        StructuredTool.from_function(
            func=_db_get_latest_posts,
            name="db_get_latest_posts",
            description=(
                "Get latest community posts from the database. "
                "Args: limit (1-20), category(optional)."
            ),
        ),
        StructuredTool.from_function(
            func=_db_search_posts,
            name="db_search_posts",
            description="Search posts by keyword in title/body. Args: keyword, limit (1-20).",
        ),
        StructuredTool.from_function(
            func=_db_get_post_detail,
            name="db_get_post_detail",
            description="Get detailed info for one post. Args: post_id.",
        ),
        StructuredTool.from_function(
            func=_db_get_forum_stats,
            name="db_get_forum_stats",
            description="Get aggregate forum stats: posts/comments/likes/collections/reports counts.",
        ),
        StructuredTool.from_function(
            func=_db_get_recent_pool_reports,
            name="db_get_recent_pool_reports",
            description="Get latest manual pool status reports. Args: limit (1-30).",
        ),
    ]


def _normalize_source_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value and value not in values:
            values.append(value)
    return values


def _parse_tool_output(raw: str, fallback_tool: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"tool": fallback_tool, "data": raw, "sources": []}

    if not isinstance(payload, dict):
        return {"tool": fallback_tool, "data": payload, "sources": []}

    return {
        "tool": str(payload.get("tool") or fallback_tool),
        "data": payload.get("data"),
        "error": payload.get("error"),
        "sources": _normalize_source_list(payload.get("sources")),
    }


def _run_database_tool_use(question: str, llm: ChatOpenAI, max_tool_calls: int) -> tuple[str, list[str]]:
    tools = _build_database_tools()
    tool_lookup = {tool.name: tool for tool in tools}
    tool_enabled_llm = llm.bind_tools(tools)

    messages: list[Any] = [
        SystemMessage(content=DATABASE_TOOL_SELECTION_PROMPT),
        HumanMessage(content=question),
    ]
    executed_results: list[dict[str, Any]] = []
    sources: list[str] = []
    call_budget = _clamp_int(max_tool_calls, minimum=1, maximum=8, default=4)
    call_count = 0

    while call_count < call_budget:
        ai_message = tool_enabled_llm.invoke(messages)
        messages.append(ai_message)
        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            break

        for tool_call in tool_calls:
            if call_count >= call_budget:
                break

            if isinstance(tool_call, dict):
                tool_name = str(tool_call.get("name") or "").strip()
                tool_args = tool_call.get("args")
                tool_call_id = str(tool_call.get("id") or f"call_{uuid4().hex}")
            else:
                tool_name = ""
                tool_args = {}
                tool_call_id = f"call_{uuid4().hex}"

            if not isinstance(tool_args, dict):
                tool_args = {}

            tool = tool_lookup.get(tool_name)
            if tool is None:
                raw_output = json.dumps(
                    {"error": f"Unknown tool: {tool_name}", "sources": []},
                    ensure_ascii=False,
                )
            else:
                try:
                    raw_result = tool.invoke(tool_args)
                    if isinstance(raw_result, str):
                        raw_output = raw_result
                    else:
                        raw_output = json.dumps(raw_result, ensure_ascii=False, default=str)
                except Exception as exc:
                    raw_output = json.dumps(
                        {"error": f"Tool execution failed: {exc}", "sources": []},
                        ensure_ascii=False,
                    )

            parsed = _parse_tool_output(raw_output, fallback_tool=tool_name or "unknown_tool")
            executed_results.append(
                {
                    "tool": parsed["tool"],
                    "args": tool_args,
                    "result": parsed.get("data"),
                    "error": parsed.get("error"),
                }
            )
            for source in parsed.get("sources", []):
                if source not in sources:
                    sources.append(source)

            messages.append(ToolMessage(content=raw_output, tool_call_id=tool_call_id))
            call_count += 1

    if not executed_results:
        raw_output = _db_search_posts(keyword=question, limit=5)
        parsed = _parse_tool_output(raw_output, fallback_tool="db_search_posts")
        executed_results.append(
            {
                "tool": parsed["tool"],
                "args": {"keyword": question, "limit": 5},
                "result": parsed.get("data"),
                "error": parsed.get("error"),
            }
        )
        for source in parsed.get("sources", []):
            if source not in sources:
                sources.append(source)

    summary_payload = {
        "question": question,
        "tool_results": executed_results,
    }

    try:
        summary_response = llm.invoke(
            [
                SystemMessage(content=DATABASE_SUMMARY_PROMPT),
                HumanMessage(content=json.dumps(summary_payload, ensure_ascii=False)),
            ]
        )
        raw_answer = summary_response.content
        answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
        answer = answer.strip()
    except Exception:
        answer = ""

    if not answer:
        has_non_empty_result = any(item.get("result") for item in executed_results)
        if has_non_empty_result:
            answer = _unknown_reply_for_question(question)
        else:
            answer = _database_empty_reply_for_question(question)

    return answer, sources


def _build_graph(
    *,
    llm: ChatOpenAI,
    intent_llm: ChatOpenAI,
    vector_store: SupabaseVectorStore,
    top_k: int,
    min_score: float,
    max_context_chars: int,
    db_tool_max_calls: int,
) -> Any:
    def intent_node(state: GraphState) -> GraphState:
        question = (state.get("question") or "").strip()
        intent = _classify_intent(question, intent_llm)
        return {"intent": intent}

    def retrieve_node(state: GraphState) -> GraphState:
        question = (state.get("question") or "").strip()
        intent = _normalize_intent(state.get("intent"))
        if not question:
            return {"mode": INTENT_FALLBACK, "context": [], "sources": []}

        if intent in {INTENT_SMALL_TALK, INTENT_DATABASE, INTENT_FALLBACK}:
            return {"mode": intent, "context": [], "sources": []}

        is_backend_rules = _is_backend_rules_question(question)
        context: list[str] = []
        sources: list[str] = []

        if is_backend_rules:
            # Backend rule/config questions should prioritize runtime + backend snapshots
            # instead of relying only on vector similarity.
            for doc in _load_backend_priority_docs(vector_store, top_k):
                _append_doc_to_context(doc, context, sources)
            if context:
                return {"mode": INTENT_KNOWLEDGE_BASE, "context": context, "sources": sources}

        matched = _search_with_optional_scores(vector_store, question, top_k)

        for doc, score in matched:
            if score is not None and score < min_score:
                continue
            _append_doc_to_context(doc, context, sources)

        # If all candidates were filtered by score, keep top docs only when
        # the best similarity is still reasonably close to the configured band.
        if not context and matched:
            scored = [score for _doc, score in matched if score is not None]
            best_score = max(scored) if scored else None
            allow_fallback = best_score is None or best_score >= DEFAULT_FALLBACK_MIN_SCORE
            if allow_fallback:
                for doc, _score in matched:
                    _append_doc_to_context(doc, context, sources)
                    if len(context) >= top_k:
                        break

        return {"mode": INTENT_KNOWLEDGE_BASE, "context": context, "sources": sources}

    def generate_node(state: GraphState) -> GraphState:
        mode = _normalize_intent(state.get("mode"))
        question = (state.get("question") or "").strip()
        context_list = state.get("context", []) or []
        unknown_reply = _unknown_reply_for_question(question)

        if mode == INTENT_SMALL_TALK:
            response = llm.invoke(
                [
                    SystemMessage(content=SMALL_TALK_SYSTEM_PROMPT),
                    HumanMessage(content=question),
                ]
            )
            raw_answer = response.content
            answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
            return {"answer": answer.strip() or unknown_reply, "sources": []}

        if mode == INTENT_DATABASE:
            try:
                answer, db_sources = _run_database_tool_use(
                    question=question,
                    llm=llm,
                    max_tool_calls=db_tool_max_calls,
                )
            except Exception:
                answer = _database_empty_reply_for_question(question)
                db_sources = []
            return {"answer": answer, "sources": db_sources}

        if mode == INTENT_KNOWLEDGE_BASE:
            if not context_list:
                return {"answer": unknown_reply, "sources": []}

            context_text = _truncate_context(context_list, max_context_chars)
            response = llm.invoke(
                [
                    SystemMessage(content=RAG_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"User question:\n{question}\n\n"
                            f"Reference context:\n{context_text}\n\n"
                            "Answer using only the reference context."
                        )
                    ),
                ]
            )
            raw_answer = response.content
            answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
            answer = answer.strip() or unknown_reply
            return {"answer": answer, "sources": state.get("sources", [])}

        return {"answer": _fallback_reply_for_question(question), "sources": []}

    graph = StateGraph(GraphState)
    graph.add_node("intent_node", intent_node)
    graph.add_node("retrieve_node", retrieve_node)
    graph.add_node("generate_node", generate_node)
    graph.add_edge(START, "intent_node")
    graph.add_edge("intent_node", "retrieve_node")
    graph.add_edge("retrieve_node", "generate_node")
    graph.add_edge("generate_node", END)
    return graph.compile()


def get_rag_app(
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    max_context_chars: int | None = None,
) -> Any:
    global _cached_graph
    global _cached_key

    load_dotenv()

    openai_key = _require("OPENAI_API_KEY")
    openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    supabase_url = _require("SUPABASE_URL")
    supabase_key = _require("SUPABASE_SERVICE_ROLE_KEY")

    chat_model = os.getenv("OPENAI_CHAT_MODEL", DEFAULT_CHAT_MODEL).strip() or DEFAULT_CHAT_MODEL
    embed_model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL).strip() or DEFAULT_EMBED_MODEL
    table_name = os.getenv("SUPABASE_DOCS_TABLE", DEFAULT_TABLE).strip() or DEFAULT_TABLE
    query_name = (
        os.getenv("SUPABASE_MATCH_FUNCTION", DEFAULT_MATCH_FUNCTION).strip()
        or DEFAULT_MATCH_FUNCTION
    )

    intent_api_key = (
        os.getenv("CHATBOT_INTENT_API_KEY", "").strip()
        or os.getenv("OPENROUTER_API_KEY", "").strip()
        or openai_key
    )
    intent_base_url = (
        os.getenv("CHATBOT_INTENT_BASE_URL", "").strip()
        or os.getenv("OPENROUTER_BASE_URL", "").strip()
        or DEFAULT_INTENT_BASE_URL
    )
    intent_model = os.getenv("CHATBOT_INTENT_MODEL", DEFAULT_INTENT_MODEL).strip() or DEFAULT_INTENT_MODEL

    resolved_top_k = top_k if top_k is not None else _get_int_env("CHATBOT_TOP_K", DEFAULT_TOP_K)
    resolved_min_score = (
        min_score if min_score is not None else _get_float_env("CHATBOT_MIN_SCORE", DEFAULT_MIN_SCORE)
    )
    resolved_max_chars = (
        max_context_chars
        if max_context_chars is not None
        else _get_int_env("CHATBOT_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS)
    )
    db_tool_max_calls = _get_int_env("CHATBOT_DB_TOOL_MAX_CALLS", DEFAULT_DB_TOOL_MAX_CALLS)

    if resolved_top_k <= 0:
        raise ChatbotConfigError("CHATBOT_TOP_K must be greater than 0.")
    if resolved_max_chars <= 0:
        raise ChatbotConfigError("CHATBOT_MAX_CONTEXT_CHARS must be greater than 0.")
    if db_tool_max_calls <= 0:
        raise ChatbotConfigError("CHATBOT_DB_TOOL_MAX_CALLS must be greater than 0.")

    cache_key = (
        openai_key,
        openai_base_url,
        supabase_url,
        supabase_key,
        chat_model,
        embed_model,
        table_name,
        query_name,
        resolved_top_k,
        resolved_min_score,
        resolved_max_chars,
        intent_api_key,
        intent_base_url,
        intent_model,
        db_tool_max_calls,
    )

    if _cached_graph is not None and _cached_key == cache_key:
        return _cached_graph

    with _graph_lock:
        if _cached_graph is not None and _cached_key == cache_key:
            return _cached_graph

        os.environ["OPENAI_API_KEY"] = openai_key
        if openai_base_url:
            os.environ["OPENAI_BASE_URL"] = openai_base_url

        vector_store = _build_vector_store(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            embed_model=embed_model,
            table_name=table_name,
            query_name=query_name,
        )
        llm = _build_llm(model=chat_model, api_key=openai_key, base_url=openai_base_url)
        intent_llm = _build_llm(
            model=intent_model,
            api_key=intent_api_key,
            base_url=intent_base_url,
        )
        _cached_graph = _build_graph(
            llm=llm,
            intent_llm=intent_llm,
            vector_store=vector_store,
            top_k=resolved_top_k,
            min_score=resolved_min_score,
            max_context_chars=resolved_max_chars,
            db_tool_max_calls=db_tool_max_calls,
        )
        _cached_key = cache_key
        return _cached_graph
