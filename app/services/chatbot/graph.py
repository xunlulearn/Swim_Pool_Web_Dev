from __future__ import annotations

import os
import threading
from typing import Any, NotRequired, TypedDict

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph
from supabase import create_client


SYSTEM_PROMPT = (
    "\u4f60\u662f NTU \u6e38\u6cf3\u6c60\u5b98\u7f51\uff08ntupool.org\uff09\u7684\u5b98\u65b9\u5ba2\u670d\u52a9\u624b\u3002"
    "\u4f60\u5fc5\u987b\u4e25\u683c\u57fa\u4e8e\u63d0\u4f9b\u7684 context \u56de\u7b54\u3002"
    "\u5982\u679c context \u4e0d\u8db3\u6216\u627e\u4e0d\u5230\u7b54\u6848\uff0c\u8bf7\u660e\u786e\u8bf4\u4e0d\u77e5\u9053\uff0c\u5e76\u5efa\u8bae\u7528\u6237\u67e5\u770b\u5b98\u7f51\u3002"
    "\u8bf7\u4f7f\u7528\u7b80\u6d01\u4e2d\u6587\u3002"
)

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_TABLE = "pool_documents"
DEFAULT_MATCH_FUNCTION = "match_documents"
DEFAULT_TOP_K = 3
DEFAULT_MIN_SCORE = 0.65
DEFAULT_MAX_CONTEXT_CHARS = 4000
DEFAULT_UNKNOWN_REPLY = (
    "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u65e0\u6cd5\u4ece\u5b98\u7f51\u5185\u5bb9\u4e2d"
    "\u786e\u8ba4\u8be5\u95ee\u9898\uff0c\u8bf7\u4ee5 ntupool.org \u7684\u6700\u65b0\u516c\u544a\u4e3a\u51c6\u3002"
)


class ChatbotConfigError(RuntimeError):
    pass


class GraphState(TypedDict, total=False):
    question: str
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


def _search_with_optional_scores(
    vector_store: SupabaseVectorStore, question: str, top_k: int
) -> list[tuple[Any, float | None]]:
    if hasattr(vector_store, "similarity_search_with_relevance_scores"):
        try:
            pairs = vector_store.similarity_search_with_relevance_scores(question, k=top_k)
            return [(doc, _coerce_score(score)) for doc, score in pairs]
        except Exception:
            pass

    if hasattr(vector_store, "similarity_search_with_score"):
        try:
            pairs = vector_store.similarity_search_with_score(question, k=top_k)
            # Some vector stores return distance-like scores where lower is better.
            # Keep compatibility by skipping threshold filtering for this branch.
            return [(doc, None) for doc, _score in pairs]
        except Exception:
            pass

    if hasattr(vector_store, "similarity_search"):
        try:
            docs = vector_store.similarity_search(question, k=top_k)
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


def _build_graph(
    *,
    chat_model: str,
    vector_store: SupabaseVectorStore,
    top_k: int,
    min_score: float,
    max_context_chars: int,
) -> Any:
    llm = ChatOpenAI(model=chat_model)

    def retrieve_node(state: GraphState) -> GraphState:
        question = (state.get("question") or "").strip()
        if not question:
            return {"context": [], "sources": []}

        matched = _search_with_optional_scores(vector_store, question, top_k)
        context: list[str] = []
        sources: list[str] = []

        for doc, score in matched:
            if score is not None and score < min_score:
                continue

            text = (getattr(doc, "page_content", "") or "").strip()
            if not text:
                continue
            context.append(text)

            metadata = getattr(doc, "metadata", {}) or {}
            source = metadata.get("source") or metadata.get("url")
            if source and source not in sources:
                sources.append(source)

        return {"context": context, "sources": sources}

    def generate_node(state: GraphState) -> GraphState:
        context_list = state.get("context", [])
        question = (state.get("question") or "").strip()

        if not context_list:
            return {"answer": DEFAULT_UNKNOWN_REPLY}

        context_text = _truncate_context(context_list, max_context_chars)
        response = llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"\u7528\u6237\u95ee\u9898\uff1a{question}\n\n"
                        f"\u53c2\u8003\u5185\u5bb9\uff1a\n{context_text}\n\n"
                        "\u8bf7\u4ec5\u6839\u636e\u53c2\u8003\u5185\u5bb9\u4f5c\u7b54\u3002"
                    )
                ),
            ]
        )

        raw_answer = response.content
        answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
        answer = answer.strip() or DEFAULT_UNKNOWN_REPLY
        return {"answer": answer}

    graph = StateGraph(GraphState)
    graph.add_node("retrieve_node", retrieve_node)
    graph.add_node("generate_node", generate_node)
    graph.add_edge(START, "retrieve_node")
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

    resolved_top_k = top_k if top_k is not None else _get_int_env("CHATBOT_TOP_K", DEFAULT_TOP_K)
    resolved_min_score = (
        min_score if min_score is not None else _get_float_env("CHATBOT_MIN_SCORE", DEFAULT_MIN_SCORE)
    )
    resolved_max_chars = (
        max_context_chars
        if max_context_chars is not None
        else _get_int_env("CHATBOT_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS)
    )

    if resolved_top_k <= 0:
        raise ChatbotConfigError("CHATBOT_TOP_K must be greater than 0.")
    if resolved_max_chars <= 0:
        raise ChatbotConfigError("CHATBOT_MAX_CONTEXT_CHARS must be greater than 0.")

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
        _cached_graph = _build_graph(
            chat_model=chat_model,
            vector_store=vector_store,
            top_k=resolved_top_k,
            min_score=resolved_min_score,
            max_context_chars=resolved_max_chars,
        )
        _cached_key = cache_key
        return _cached_graph
