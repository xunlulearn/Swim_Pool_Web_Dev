import argparse
import logging
import os
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from dotenv import load_dotenv
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_openai import OpenAIEmbeddings
import requests
from supabase import Client, create_client

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # Backward compatibility with older LangChain layouts.
    from langchain.text_splitter import RecursiveCharacterTextSplitter


DEFAULT_URLS = [
    "https://ntupool.org/",
]
DEFAULT_SITEMAP_URL = "https://ntupool.org/sitemap.xml"

DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_TABLE_NAME = "pool_documents"
DEFAULT_MATCH_FUNCTION = "match_documents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest ntupool.org web content into Supabase pgvector."
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Web URL to ingest. Repeat --url to add multiple pages.",
    )
    parser.add_argument(
        "--sitemap-url",
        type=str,
        default=DEFAULT_SITEMAP_URL,
        help="Sitemap URL used when --url is not provided.",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=200,
        help="Maximum URLs loaded from sitemap.",
    )
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Top-k used only for optional debug search preview.",
    )
    parser.add_argument(
        "--debug-query",
        type=str,
        default="",
        help="Optional query for retrieval preview after ingestion.",
    )
    return parser.parse_args()


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


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


def build_vector_store() -> SupabaseVectorStore:
    require_env("OPENAI_API_KEY")
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    embed_model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    table_name = os.getenv("SUPABASE_DOCS_TABLE", DEFAULT_TABLE_NAME)
    match_function = os.getenv("SUPABASE_MATCH_FUNCTION", DEFAULT_MATCH_FUNCTION)

    client: Client = create_client(supabase_url, supabase_key)
    if openai_base_url:
        os.environ["OPENAI_BASE_URL"] = openai_base_url
    embeddings = OpenAIEmbeddings(model=embed_model)
    return SupabaseVectorStore(
        client=client,
        embedding=embeddings,
        table_name=table_name,
        query_name=match_function,
    )


def _extract_text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def load_urls_from_sitemap(sitemap_url: str, max_urls: int) -> list[str]:
    parsed = urlparse(sitemap_url)
    host = parsed.netloc.lower()
    if host != "ntupool.org" and not host.endswith(".ntupool.org"):
        raise ValueError(f"Sitemap must be hosted on ntupool.org: {sitemap_url}")

    response = requests.get(sitemap_url, timeout=15)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    urls: list[str] = []
    seen: set[str] = set()

    for elem in root.iter():
        if not elem.tag.lower().endswith("loc"):
            continue
        loc = _extract_text(elem)
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


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv()
    args = parse_args()

    if args.max_urls <= 0:
        raise ValueError("--max-urls must be greater than 0")

    if args.url:
        urls = validate_ntupool_urls(args.url)
    else:
        try:
            urls = load_urls_from_sitemap(args.sitemap_url, args.max_urls)
            if not urls:
                logging.warning("Sitemap returned zero URLs, fallback to default home URL.")
                urls = DEFAULT_URLS
        except Exception as exc:
            logging.warning("Failed to load sitemap (%s). Fallback to default home URL.", exc)
            urls = DEFAULT_URLS
        urls = validate_ntupool_urls(urls)

    logging.info("Loading %s page(s)...", len(urls))

    loader = WebBaseLoader(web_paths=urls)
    raw_docs = loader.load()
    if not raw_docs:
        logging.error("No documents were loaded. Exiting.")
        return 1

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    chunks = splitter.split_documents(raw_docs)
    if not chunks:
        logging.error("Document splitter produced zero chunks. Exiting.")
        return 1

    for idx, doc in enumerate(chunks):
        doc.metadata = dict(doc.metadata or {})
        doc.metadata.setdefault("source", doc.metadata.get("source", ""))
        doc.metadata["chunk"] = idx

    vector_store = build_vector_store()
    ids = vector_store.add_documents(chunks)
    logging.info("Inserted %s chunk(s) into Supabase.", len(ids))

    if args.debug_query:
        logging.info("Running debug search preview (top_k=%s)...", args.top_k)
        preview_docs = vector_store.similarity_search(args.debug_query, k=args.top_k)
        for i, doc in enumerate(preview_docs, start=1):
            source = (doc.metadata or {}).get("source", "unknown")
            snippet = doc.page_content.strip().replace("\n", " ")[:140]
            logging.info("[%s] source=%s snippet=%s", i, source, snippet)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.error("Ingestion failed: %s", exc)
        raise SystemExit(1) from exc
