from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

os.environ.setdefault("USER_AGENT", "NTUPoolKnowledgeSync/1.0")

from langchain_community.document_loaders import WebBaseLoader
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from supabase import Client, create_client

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # Backward compatibility with older LangChain layouts.
    from langchain.text_splitter import RecursiveCharacterTextSplitter


DEFAULT_SITEMAP_URL = "https://ntupool.org/sitemap.xml"
DEFAULT_WEBSITE_FALLBACK_URLS = [
    "https://ntupool.org/",
    "https://ntupool.org/social/",
    "https://ntupool.org/auth/login",
    "https://ntupool.org/auth/register",
    "https://ntupool.org/weather/status",
    "https://ntupool.org/api/live-status/",
]
DEFAULT_KNOWLEDGE_BASE_DIR = "knowledge_base"
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_TOP_K = 3
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_TABLE_NAME = "pool_documents"
DEFAULT_MATCH_FUNCTION = "match_documents"
INGEST_NAMESPACE = "ntupool_kb_sync_v1"
POST_VECTOR_COLUMNS = ("id", "title", "body", "category", "author_id", "created_at")
COMMENT_VECTOR_COLUMNS = (
    "id",
    "post_id",
    "body",
    "author_id",
    "parent_id",
    "reply_to_user_id",
    "created_at",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync chatbot knowledge into Supabase pgvector. "
            "Sources: ntupool sitemap, runtime status, community data, backend snapshot, local markdown."
        )
    )
    parser.add_argument("--sitemap-url", type=str, default=DEFAULT_SITEMAP_URL)
    parser.add_argument("--max-urls", type=int, default=300)
    parser.add_argument("--kb-dir", type=str, default=DEFAULT_KNOWLEDGE_BASE_DIR)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--max-posts", type=int, default=0, help="0 means no limit.")
    parser.add_argument("--max-comments", type=int, default=0, help="0 means no limit.")
    parser.add_argument("--max-reports", type=int, default=0, help="0 means no limit.")
    parser.add_argument("--no-website", action="store_true")
    parser.add_argument("--no-community", action="store_true")
    parser.add_argument("--no-backend", action="store_true")
    parser.add_argument("--no-markdown", action="store_true")
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Force delete all rows in this ingest namespace and rebuild from scratch.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug-query", type=str, default="")
    return parser.parse_args()


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        key_str = str(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key_str] = value
            continue
        clean[key_str] = str(value)
    return clean


def normalize_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if compact:
            lines.append(compact)
    return "\n".join(lines)


def _format_timestamp(value: Any) -> str:
    if value is None:
        return "unknown"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _resolve_public_author_name(user: Any, fallback_user_id: Any) -> str:
    if user is None:
        return f"user:{fallback_user_id}" if fallback_user_id is not None else "unknown_user"

    nickname = normalize_text(str(getattr(user, "nickname", "") or ""))
    username = normalize_text(str(getattr(user, "username", "") or ""))
    if nickname:
        return nickname
    if username:
        return username
    return f"user:{fallback_user_id}" if fallback_user_id is not None else "unknown_user"


def build_post_vector_document(post: Any) -> Document | None:
    title = normalize_text(str(getattr(post, "title", "") or ""))
    body = normalize_text(str(getattr(post, "body", "") or ""))
    if not title and not body:
        return None

    author_id = getattr(post, "author_id", None)
    author_name = _resolve_public_author_name(getattr(post, "author", None), author_id)
    post_id = getattr(post, "id", "")
    category = str(getattr(post, "category", "") or "general")
    created_at = _format_timestamp(getattr(post, "created_at", None))

    content = "\n".join(
        [
            "# Community Post",
            "- Table: posts",
            f"- Post ID: {post_id}",
            f"- Category: {category}",
            f"- Author ID: {author_id}",
            f"- Author Name: {author_name}",
            f"- Created At: {created_at}",
            f"- Selected Columns: {', '.join(f'posts.{col}' for col in POST_VECTOR_COLUMNS)}",
            "",
            "## Title",
            title or "(empty)",
            "",
            "## Body",
            body or "(empty)",
        ]
    )
    return Document(
        page_content=content,
        metadata={
            "source_type": "community_post",
            "source": f"app://community/post/{post_id}",
            "table": "posts",
            "post_id": post_id,
            "category": category,
            "selected_columns": ",".join(POST_VECTOR_COLUMNS),
        },
    )


def build_comment_vector_document(comment: Any, post: Any) -> Document | None:
    body = normalize_text(str(getattr(comment, "body", "") or ""))
    if not body:
        return None

    comment_id = getattr(comment, "id", "")
    post_id = getattr(comment, "post_id", "")
    author_id = getattr(comment, "author_id", None)
    created_at = _format_timestamp(getattr(comment, "created_at", None))
    parent_id = getattr(comment, "parent_id", None)
    reply_to_user_id = getattr(comment, "reply_to_user_id", None)
    author_name = _resolve_public_author_name(getattr(comment, "author", None), author_id)
    reply_to_user_name = ""
    if reply_to_user_id is not None:
        reply_to_user_name = _resolve_public_author_name(
            getattr(comment, "reply_to_user", None),
            reply_to_user_id,
        )
    post_title = normalize_text(str(getattr(post, "title", "") or ""))

    lines = [
        "# Community Comment",
        "- Table: comments",
        f"- Comment ID: {comment_id}",
        f"- Post ID: {post_id}",
        f"- Author ID: {author_id}",
        f"- Author Name: {author_name}",
        f"- Created At: {created_at}",
        f"- Parent Comment ID: {parent_id if parent_id is not None else ''}",
        f"- Selected Columns: {', '.join(f'comments.{col}' for col in COMMENT_VECTOR_COLUMNS)}",
    ]
    if reply_to_user_id is not None:
        lines.append(f"- Reply To User ID: {reply_to_user_id}")
        lines.append(f"- Reply To User Name: {reply_to_user_name}")
    if post_title:
        lines.extend(["", "## Related Post Title", post_title])
    lines.extend(["", "## Body", body])

    return Document(
        page_content="\n".join(lines),
        metadata={
            "source_type": "community_comment",
            "source": f"app://community/post/{post_id}#comment-{comment_id}",
            "table": "comments",
            "post_id": post_id,
            "comment_id": comment_id,
            "selected_columns": ",".join(COMMENT_VECTOR_COLUMNS),
        },
    )


def build_vector_store() -> tuple[Client, SupabaseVectorStore, str]:
    require_env("OPENAI_API_KEY")
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    embed_model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL).strip() or DEFAULT_EMBED_MODEL
    table_name = os.getenv("SUPABASE_DOCS_TABLE", DEFAULT_TABLE_NAME).strip() or DEFAULT_TABLE_NAME
    match_function = os.getenv("SUPABASE_MATCH_FUNCTION", DEFAULT_MATCH_FUNCTION).strip() or DEFAULT_MATCH_FUNCTION

    if openai_base_url:
        os.environ["OPENAI_BASE_URL"] = openai_base_url

    client: Client = create_client(supabase_url, supabase_key)
    embeddings = OpenAIEmbeddings(model=embed_model)
    vector_store = SupabaseVectorStore(
        client=client,
        embedding=embeddings,
        table_name=table_name,
        query_name=match_function,
    )
    return client, vector_store, table_name


def validate_ntupool_urls(urls: list[str]) -> list[str]:
    valid_urls: list[str] = []
    for raw_url in urls:
        parsed = urlparse(raw_url)
        host = parsed.netloc.lower()
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"Invalid URL scheme for {raw_url}")
        if host != "ntupool.org" and not host.endswith(".ntupool.org"):
            raise ValueError(f"Only ntupool.org URLs are allowed: {raw_url}")
        valid_urls.append(raw_url)
    return valid_urls


def load_urls_from_sitemap(sitemap_url: str, max_urls: int) -> list[str]:
    parsed = urlparse(sitemap_url)
    host = parsed.netloc.lower()
    if host != "ntupool.org" and not host.endswith(".ntupool.org"):
        raise ValueError(f"Sitemap must be hosted on ntupool.org: {sitemap_url}")
    if max_urls <= 0:
        raise ValueError("--max-urls must be greater than 0")

    response = requests.get(sitemap_url, timeout=60)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    urls: list[str] = []
    seen: set[str] = set()

    for elem in root.iter():
        if not elem.tag.lower().endswith("loc"):
            continue
        loc = "".join(elem.itertext()).strip()
        if not loc:
            continue
        validated = validate_ntupool_urls([loc])[0]
        if validated in seen:
            continue
        seen.add(validated)
        urls.append(validated)
        if len(urls) >= max_urls:
            break
    return urls


def discover_route_urls(base_origin: str) -> list[str]:
    urls = set(DEFAULT_WEBSITE_FALLBACK_URLS)
    try:
        app = create_flask_app()
    except Exception as exc:
        logging.warning("Route discovery skipped: failed to create Flask app (%s)", exc)
        return sorted(urls)

    with app.app_context():
        for rule in app.url_map.iter_rules():
            if "GET" not in rule.methods:
                continue
            if rule.endpoint == "static":
                continue
            if "<" in rule.rule:
                continue
            path = rule.rule if rule.rule.startswith("/") else f"/{rule.rule}"
            urls.add(f"{base_origin.rstrip('/')}{path}")
    return sorted(urls)


def collect_website_documents(sitemap_url: str, max_urls: int) -> list[Document]:
    parsed = urlparse(sitemap_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://ntupool.org"
    fallback_urls = discover_route_urls(base_origin=base_origin)

    try:
        urls = load_urls_from_sitemap(sitemap_url, max_urls)
        if not urls:
            raise RuntimeError("Sitemap returned zero URLs.")
    except Exception as exc:
        logging.warning(
            "Failed to load sitemap (%s). Falling back to URL list: %s",
            exc,
            fallback_urls,
        )
        urls = fallback_urls

    try:
        loader = WebBaseLoader(web_paths=urls)
        loaded_docs = loader.load()
    except Exception as exc:
        if urls == fallback_urls:
            raise
        logging.warning(
            "Website crawl failed for sitemap URLs (%s). Retrying with fallback URL list: %s",
            exc,
            fallback_urls,
        )
        loader = WebBaseLoader(web_paths=fallback_urls)
        loaded_docs = loader.load()
    docs: list[Document] = []

    for doc in loaded_docs:
        metadata = dict(doc.metadata or {})
        source = str(metadata.get("source") or metadata.get("url") or "").strip()
        title = str(metadata.get("title") or "").strip()
        text = normalize_text(doc.page_content or "")
        if not text:
            continue
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source_type": "website_page",
                    "source": source or "https://ntupool.org/",
                    "title": title,
                },
            )
        )
    return docs


def collect_markdown_documents(kb_dir: Path) -> list[Document]:
    docs: list[Document] = []
    if not kb_dir.exists():
        logging.warning("Knowledge base folder does not exist yet: %s", kb_dir)
        return docs

    for path in sorted(kb_dir.rglob("*.md")):
        if path.is_dir():
            continue
        relative = path.relative_to(kb_dir).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore")
        text = normalize_text(content)
        if not text:
            continue

        docs.append(
            Document(
                page_content=f"# Knowledge File: {relative}\n\n{text}",
                metadata={
                    "source_type": "local_markdown",
                    "source": f"kb://{relative}",
                    "path": relative,
                },
            )
        )
    return docs


def get_runtime_config_snapshot(chunk_size: int, chunk_overlap: int) -> str:
    from app.services.weather_engine import WeatherEngine

    max_content_length = int(os.getenv("MAX_CONTENT_LENGTH") or (2 * 1024 * 1024))
    max_size_mb = max_content_length / (1024 * 1024)
    chatbot_top_k = int(os.getenv("CHATBOT_TOP_K") or 3)
    chatbot_min_score = float(os.getenv("CHATBOT_MIN_SCORE") or 0.45)
    chatbot_max_chars = int(os.getenv("CHATBOT_MAX_CONTEXT_CHARS") or 4000)
    embed_model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL).strip() or DEFAULT_EMBED_MODEL
    chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    docs_table = os.getenv("SUPABASE_DOCS_TABLE", DEFAULT_TABLE_NAME).strip() or DEFAULT_TABLE_NAME
    match_function = os.getenv("SUPABASE_MATCH_FUNCTION", DEFAULT_MATCH_FUNCTION).strip() or DEFAULT_MATCH_FUNCTION

    lines = [
        "# NTU Pool Backend Non-sensitive Knowledge (Auto Snapshot)",
        "",
        "## Weather Data Sources",
        f"- Lightning API: {WeatherEngine.LIGHTNING_API_URL}",
        f"- Rainfall API: {WeatherEngine.RAINFALL_API_URL}",
        "- Frontend status endpoint: /weather/status",
        "- Live report API: GET /api/live-status/ and POST /api/live-status/",
        "",
        "## Pool Status Rules (Code-level)",
        f"- Lightning close threshold: <= {WeatherEngine.LIGHTNING_WARN_THRESHOLD} km",
        f"- Lightning hard-close threshold: <= {WeatherEngine.LIGHTNING_CLOSE_THRESHOLD} km",
        f"- Rain warning threshold: > {WeatherEngine.RAINFALL_WARN_THRESHOLD} mm/h",
        "- Lightning close persistence window: 45 minutes",
        "- Rain close persistence window: 30 minutes",
        "- Community consensus rule: 30 minutes window, latest 5 reports, 5 distinct users, unanimous status, valid for 10 minutes",
        "",
        "## User Roles and Permission Rules",
        "- Role values: user, admin",
        "- Verified account required: create/edit/delete post, comment/reply, like/save, submit live status report, private messaging",
        "- Admin-only actions: pin/unpin post, ban/unban user, content report moderation dashboard",
        "",
        "## Upload and Content Limits",
        f"- MAX_CONTENT_LENGTH: {max_content_length} bytes (~{max_size_mb:.2f} MB)",
        "- Avatar/Post/Comment image MIME types: image/jpeg, image/png",
        "",
        "## Chatbot RAG Runtime Settings",
        f"- Chat model: {chat_model}",
        f"- Embedding model: {embed_model}",
        f"- Vector table: {docs_table}",
        f"- Match function: {match_function}",
        f"- Retrieval top_k: {chatbot_top_k}",
        f"- Retrieval min score: {chatbot_min_score}",
        f"- Max context chars: {chatbot_max_chars}",
        "",
        "## Ingestion Settings (This Sync Script)",
        f"- Chunk size: {chunk_size}",
        f"- Chunk overlap: {chunk_overlap}",
        "- Sync strategy: incremental update by doc hash (changed/new/deleted docs only)",
        "",
        "## Sensitive Data Exclusion",
        "- Chatbot KB should not include passwords, secret keys, mail credentials, or private tokens.",
    ]
    return "\n".join(lines)


def collect_backend_snapshot_document(chunk_size: int, chunk_overlap: int) -> Document:
    content = get_runtime_config_snapshot(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return Document(
        page_content=content,
        metadata={
            "source_type": "backend_non_sensitive",
            "source": "app://backend/non_sensitive_snapshot",
        },
    )


def create_flask_app():
    from app import create_app

    config_name = (
        os.environ.get("FLASK_CONFIG")
        or os.environ.get("APP_ENV")
        or ("production" if (os.environ.get("FLASK_ENV") or "").lower() == "production" else "development")
    )
    return create_app(config_name)


def collect_community_and_runtime_documents(
    *,
    max_posts: int,
    max_comments: int,
    max_reports: int,
) -> tuple[list[Document], dict[str, int]]:
    from app.models import Comment, PoolReport, Post
    from app.services.weather_engine import weather_engine

    app = create_flask_app()
    docs: list[Document] = []
    counters = {"posts": 0, "comments": 0, "reports": 0, "realtime_snapshots": 0}

    with app.app_context():
        # Runtime weather snapshot document (includes latest manual report snapshot).
        status, message, details = weather_engine.get_overall_status()
        details_payload = dict(details or {})
        if "timestamp" in details_payload:
            details_payload.pop("timestamp")
        latest_reports = (
            PoolReport.query.order_by(PoolReport.created_at.desc()).limit(10).all()
        )
        open_count = sum(1 for item in latest_reports if item.status == "Open")
        closed_count = sum(1 for item in latest_reports if item.status == "Closed")
        report_lines = []
        for item in latest_reports:
            report_lines.append(
                f"- [{item.created_at.isoformat() if item.created_at else 'unknown_time'}] "
                f"{item.status} by {item.user.username if item.user else f'user:{item.user_id}'}"
            )
        snapshot_content = "\n".join(
            [
                "# Runtime Pool Status Snapshot",
                f"- Status Enum: {status.name}",
                f"- Display Text: {status.value}",
                f"- Message: {normalize_text(message or '')}",
                f"- Details JSON: {json.dumps(details_payload, ensure_ascii=False)}",
                "",
                "## Latest Manual Reports (up to 10)",
                f"- Open count: {open_count}",
                f"- Closed count: {closed_count}",
                *report_lines,
            ]
        )
        docs.append(
            Document(
                page_content=snapshot_content,
                metadata={
                    "source_type": "realtime_status_snapshot",
                    "source": "app://weather/status",
                },
            )
        )
        counters["realtime_snapshots"] += 1

        # Community posts + comments.
        post_query = Post.query.filter_by(is_deleted=False).order_by(Post.created_at.desc())
        if max_posts > 0:
            post_query = post_query.limit(max_posts)
        posts = post_query.all()

        total_comments = 0
        for post in posts:
            post_doc = build_post_vector_document(post)
            if post_doc is not None:
                docs.append(post_doc)
                counters["posts"] += 1

            comment_query = post.comments.filter_by(is_deleted=False).order_by(Comment.created_at.asc())
            for comment in comment_query:
                if max_comments > 0 and total_comments >= max_comments:
                    break
                total_comments += 1
                comment_doc = build_comment_vector_document(comment, post)
                if comment_doc is not None:
                    docs.append(comment_doc)
                    counters["comments"] += 1
            if max_comments > 0 and total_comments >= max_comments:
                logging.info("Reached max-comments limit (%s), stopping comment ingestion.", max_comments)
                break

        # Manual pool reports.
        report_query = PoolReport.query.order_by(PoolReport.created_at.desc())
        if max_reports > 0:
            report_query = report_query.limit(max_reports)
        reports = report_query.all()
        for report in reports:
            reporter = report.user.username if report.user else f"user:{report.user_id}"
            report_text = "\n".join(
                [
                    f"# Live Pool Report {report.id}",
                    f"- Status: {report.status}",
                    f"- Reporter: {reporter}",
                    f"- Timestamp: {report.created_at.isoformat() if report.created_at else 'unknown'}",
                ]
            )
            docs.append(
                Document(
                    page_content=report_text,
                    metadata={
                        "source_type": "manual_pool_report",
                        "source": f"app://live-status/report/{report.id}",
                        "report_id": report.id,
                    },
                )
            )
            counters["reports"] += 1

        since_24h = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
        reports_24h = (
            PoolReport.query.filter(PoolReport.created_at >= since_24h)
            .order_by(PoolReport.created_at.desc())
            .all()
        )
        if reports_24h:
            open_24h = sum(1 for item in reports_24h if item.status == "Open")
            close_24h = sum(1 for item in reports_24h if item.status == "Closed")
            summary_text = "\n".join(
                [
                    "# Live Pool Reports Summary (Last 24h)",
                    f"- Report count: {len(reports_24h)}",
                    f"- Open reports: {open_24h}",
                    f"- Closed reports: {close_24h}",
                    "",
                    "## Latest 10 Entries",
                    *[
                        (
                            f"- {item.created_at.isoformat() if item.created_at else 'unknown'} "
                            f"| {item.status} | {item.user.username if item.user else f'user:{item.user_id}'}"
                        )
                        for item in reports_24h[:10]
                    ],
                ]
            )
            docs.append(
                Document(
                    page_content=summary_text,
                    metadata={
                        "source_type": "manual_pool_report_summary",
                        "source": "app://live-status/summary-24h",
                    },
                )
            )

    return docs, counters


def _stable_json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_doc_key(metadata: dict[str, Any], content: str) -> str:
    source_type = str(metadata.get("source_type") or "unknown")
    source = str(metadata.get("source") or "").strip()
    if source:
        return f"{source_type}::{source}"
    content_digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:20]
    return f"{source_type}::content:{content_digest}"


def compute_doc_hash(content: str, metadata: dict[str, Any]) -> str:
    stable_metadata = {
        key: value
        for key, value in metadata.items()
        if key not in {"chunk", "synced_at", "doc_hash", "doc_key"}
    }
    payload = {
        "content": content,
        "metadata": stable_metadata,
    }
    return hashlib.sha256(_stable_json_dumps(payload).encode("utf-8")).hexdigest()


def attach_sync_metadata(docs: list[Document], synced_at: str) -> None:
    for doc in docs:
        content = (doc.page_content or "").strip()
        metadata = sanitize_metadata(dict(doc.metadata or {}))
        metadata["ingest_namespace"] = INGEST_NAMESPACE
        metadata["synced_at"] = synced_at
        metadata["doc_key"] = build_doc_key(metadata=metadata, content=content)
        metadata["doc_hash"] = compute_doc_hash(content=content, metadata=metadata)
        doc.metadata = metadata
        doc.page_content = content


def split_documents(docs: list[Document], chunk_size: int, chunk_overlap: int) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = splitter.split_documents(docs)

    source_chunk_counter: dict[str, int] = {}
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        doc_key = str(metadata.get("doc_key") or "")
        if not doc_key:
            fallback_content = (chunk.page_content or "").strip()
            doc_key = build_doc_key(metadata=metadata, content=fallback_content)
            metadata["doc_key"] = doc_key
        index = source_chunk_counter.get(doc_key, 0)
        source_chunk_counter[doc_key] = index + 1
        metadata["chunk"] = index
        chunk.metadata = sanitize_metadata(metadata)
    return chunks


def build_current_doc_index(chunks: list[Document]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        doc_key = str(metadata.get("doc_key") or "").strip()
        if not doc_key:
            continue
        doc_hash = str(metadata.get("doc_hash") or "").strip()
        entry = index.setdefault(doc_key, {"doc_hash": doc_hash, "chunks": []})
        entry["chunks"].append(chunk)
    return index


def _fetch_rows_paged(
    client: Client,
    table_name: str,
    *,
    namespace: str | None,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    start = 0
    rows: list[dict[str, Any]] = []
    while True:
        query = client.table(table_name).select("id,metadata")
        if namespace:
            query = query.contains("metadata", {"ingest_namespace": namespace})
        response = query.range(start, start + page_size - 1).execute()
        batch = response.data or []
        if not isinstance(batch, list):
            break
        rows.extend([item for item in batch if isinstance(item, dict)])
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def fetch_existing_namespace_rows(client: Client, table_name: str, namespace: str) -> list[dict[str, Any]]:
    try:
        return _fetch_rows_paged(client, table_name, namespace=namespace)
    except Exception as exc:
        logging.warning(
            "Namespace-filter query failed (%s). Falling back to full scan for namespace filtering.",
            exc,
        )
        all_rows = _fetch_rows_paged(client, table_name, namespace=None)
        scoped_rows: list[dict[str, Any]] = []
        for row in all_rows:
            metadata = row.get("metadata")
            if isinstance(metadata, dict) and metadata.get("ingest_namespace") == namespace:
                scoped_rows.append(row)
        return scoped_rows


def build_existing_doc_index(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    index: dict[str, dict[str, Any]] = {}
    legacy_ids: list[str] = []
    namespace_ids: list[str] = []

    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        namespace_ids.append(row_id)

        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            legacy_ids.append(row_id)
            continue

        doc_key = str(metadata.get("doc_key") or "").strip()
        doc_hash = str(metadata.get("doc_hash") or "").strip()
        if not doc_key or not doc_hash:
            legacy_ids.append(row_id)
            continue

        entry = index.setdefault(doc_key, {"doc_hash": doc_hash, "ids": []})
        if entry["doc_hash"] != doc_hash:
            entry["doc_hash"] = ""
        entry["ids"].append(row_id)

    return index, legacy_ids, namespace_ids


def delete_rows_by_ids(client: Client, table_name: str, ids: list[str], batch_size: int = 200) -> int:
    cleaned = [item for item in ids if item]
    if not cleaned:
        return 0

    total = 0
    for idx in range(0, len(cleaned), batch_size):
        batch = cleaned[idx : idx + batch_size]
        response = (
            client.table(table_name)
            .delete(count="exact", returning="minimal")
            .in_("id", batch)
            .execute()
        )
        if hasattr(response, "count") and response.count is not None:
            total += int(response.count)
        else:
            total += len(batch)
    return total


def delete_namespace_rows(client: Client, table_name: str, namespace: str) -> int:
    try:
        response = (
            client.table(table_name)
            .delete(count="exact", returning="minimal")
            .contains("metadata", {"ingest_namespace": namespace})
            .execute()
        )
        if hasattr(response, "count") and response.count is not None:
            return int(response.count)
    except Exception as exc:
        logging.warning("Namespace delete by metadata filter failed: %s", exc)

    fallback_rows = fetch_existing_namespace_rows(client, table_name, namespace)
    fallback_ids = [str(row.get("id") or "").strip() for row in fallback_rows]
    return delete_rows_by_ids(client, table_name, fallback_ids)


def preview_retrieval(vector_store: SupabaseVectorStore, query: str, top_k: int) -> None:
    if not query.strip():
        return
    logging.info("Debug retrieval preview (top_k=%s): %s", top_k, query)
    try:
        docs = vector_store.similarity_search(query, k=top_k)
        for idx, doc in enumerate(docs, start=1):
            source = (doc.metadata or {}).get("source", "unknown")
            snippet = normalize_text(doc.page_content or "")[:180]
            logging.info("[%s] source=%s snippet=%s", idx, source, snippet)
        return
    except Exception as exc:
        logging.warning("Vector store preview failed via similarity_search: %s", exc)

    try:
        embedding_model = getattr(vector_store, "embeddings", None) or getattr(
            vector_store, "_embedding", None
        )
        client = getattr(vector_store, "_client", None)
        query_name = getattr(vector_store, "query_name", DEFAULT_MATCH_FUNCTION)
        if embedding_model is None or client is None:
            logging.warning("Preview skipped: vector store lacks embedding model/client.")
            return

        query_embedding = embedding_model.embed_query(query)
        response = client.rpc(
            query_name,
            {
                "query_embedding": query_embedding,
                "match_count": top_k,
                "filter": {},
            },
        ).execute()
        rows = (response.data or []) if hasattr(response, "data") else []
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            source = (row.get("metadata") or {}).get("source", "unknown")
            snippet = normalize_text(str(row.get("content") or ""))[:180]
            logging.info("[%s] source=%s snippet=%s", idx, source, snippet)
    except Exception as exc:
        logging.warning("Vector store preview failed via RPC fallback: %s", exc)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv()
    args = parse_args()
    if not os.getenv("USER_AGENT"):
        os.environ["USER_AGENT"] = "NTUPoolKnowledgeSync/1.0"

    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be greater than 0")
    if args.chunk_overlap < 0:
        raise ValueError("--chunk-overlap must be >= 0")
    if args.chunk_overlap >= args.chunk_size:
        raise ValueError("--chunk-overlap must be smaller than --chunk-size")

    kb_dir = (Path(__file__).resolve().parent / args.kb_dir).resolve()
    synced_at = datetime.now(timezone.utc).isoformat()
    raw_docs: list[Document] = []
    source_counts = {
        "website_pages": 0,
        "community_posts": 0,
        "community_comments": 0,
        "manual_reports": 0,
        "runtime_snapshots": 0,
        "backend_snapshots": 0,
        "markdown_files": 0,
    }

    if not args.no_website:
        try:
            website_docs = collect_website_documents(args.sitemap_url, args.max_urls)
            raw_docs.extend(website_docs)
            source_counts["website_pages"] = len(website_docs)
            logging.info("Collected website documents: %s", len(website_docs))
        except Exception as exc:
            logging.warning("Website ingestion skipped due to error: %s", exc)

    if not args.no_community:
        try:
            community_docs, counters = collect_community_and_runtime_documents(
                max_posts=args.max_posts,
                max_comments=args.max_comments,
                max_reports=args.max_reports,
            )
            raw_docs.extend(community_docs)
            source_counts["community_posts"] = counters["posts"]
            source_counts["community_comments"] = counters["comments"]
            source_counts["manual_reports"] = counters["reports"]
            source_counts["runtime_snapshots"] = counters["realtime_snapshots"]
            logging.info(
                "Collected community/runtime documents: posts=%s comments=%s reports=%s snapshots=%s",
                counters["posts"],
                counters["comments"],
                counters["reports"],
                counters["realtime_snapshots"],
            )
        except Exception:
            logging.exception("Community/runtime ingestion skipped due to error.")

    if not args.no_backend:
        try:
            backend_doc = collect_backend_snapshot_document(
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
            raw_docs.append(backend_doc)
            source_counts["backend_snapshots"] = 1
            logging.info("Collected backend snapshot document.")
        except Exception:
            logging.exception("Backend snapshot ingestion skipped due to error.")

    if not args.no_markdown:
        markdown_docs = collect_markdown_documents(kb_dir)
        raw_docs.extend(markdown_docs)
        source_counts["markdown_files"] = len(markdown_docs)
        logging.info("Collected markdown documents: %s", len(markdown_docs))

    raw_docs = [doc for doc in raw_docs if (doc.page_content or "").strip()]
    if not raw_docs:
        logging.error("No documents collected from any source. Aborting.")
        return 1

    attach_sync_metadata(raw_docs, synced_at=synced_at)
    chunks = split_documents(
        raw_docs,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    if not chunks:
        logging.error("Splitter produced zero chunks. Aborting.")
        return 1

    current_doc_index = build_current_doc_index(chunks)
    if not current_doc_index:
        logging.error("No valid doc_key/doc_hash found after splitting. Aborting.")
        return 1

    logging.info(
        "Prepared %s raw docs -> %s chunks across %s logical docs.",
        len(raw_docs),
        len(chunks),
        len(current_doc_index),
    )
    logging.info("Source summary: %s", json.dumps(source_counts, ensure_ascii=False))

    if args.dry_run:
        logging.info("Dry run enabled. Vector DB was not modified.")
        return 0

    client, vector_store, table_name = build_vector_store()
    chunks_to_insert: list[Document] = []
    deleted_count = 0

    if args.full_rebuild:
        deleted_count = delete_namespace_rows(client, table_name, INGEST_NAMESPACE)
        chunks_to_insert = chunks
        logging.info(
            "Full rebuild mode: deleted %s existing chunk(s) in namespace '%s'.",
            deleted_count,
            INGEST_NAMESPACE,
        )
    else:
        existing_rows = fetch_existing_namespace_rows(client, table_name, INGEST_NAMESPACE)
        existing_doc_index, legacy_ids, _namespace_ids = build_existing_doc_index(existing_rows)
        current_keys = set(current_doc_index.keys())
        existing_keys = set(existing_doc_index.keys())

        if legacy_ids:
            deleted_count = delete_namespace_rows(client, table_name, INGEST_NAMESPACE)
            chunks_to_insert = chunks
            logging.info(
                "Detected %s legacy chunk(s) without doc_key/doc_hash; "
                "ran one-time namespace rebuild (deleted=%s).",
                len(legacy_ids),
                deleted_count,
            )
        else:
            new_keys = current_keys - existing_keys
            removed_keys = existing_keys - current_keys
            changed_keys = {
                key
                for key in (current_keys & existing_keys)
                if str(existing_doc_index[key].get("doc_hash") or "")
                != str(current_doc_index[key].get("doc_hash") or "")
            }
            unchanged_keys = (current_keys & existing_keys) - changed_keys

            ids_to_delete: list[str] = []
            for key in sorted(removed_keys | changed_keys):
                ids_to_delete.extend(existing_doc_index[key].get("ids", []))
            deleted_count = delete_rows_by_ids(client, table_name, ids_to_delete)

            insert_keys = sorted(new_keys | changed_keys)
            for key in insert_keys:
                chunks_to_insert.extend(current_doc_index[key]["chunks"])

            logging.info(
                "Incremental sync plan: docs total=%s unchanged=%s new=%s changed=%s removed=%s",
                len(current_keys),
                len(unchanged_keys),
                len(new_keys),
                len(changed_keys),
                len(removed_keys),
            )
            logging.info(
                "Incremental sync actions: delete_chunks=%s insert_chunks=%s",
                deleted_count,
                len(chunks_to_insert),
            )

    inserted_count = 0
    if chunks_to_insert:
        inserted_ids = vector_store.add_documents(chunks_to_insert)
        inserted_count = len(inserted_ids)
    logging.info(
        "Sync complete for table '%s' (namespace=%s): deleted=%s inserted=%s current_total_chunks=%s",
        table_name,
        INGEST_NAMESPACE,
        deleted_count,
        inserted_count,
        len(chunks),
    )

    preview_retrieval(vector_store, args.debug_query, args.top_k)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("Knowledge sync failed.")
        raise SystemExit(1)
