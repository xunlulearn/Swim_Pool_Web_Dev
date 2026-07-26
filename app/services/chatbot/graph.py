from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
import json
import os
from pathlib import Path
import random
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

from app.services.chatbot import hard_kb


INTENT_SMALL_TALK = "small_talk"
INTENT_DATABASE = "database"
INTENT_KNOWLEDGE_BASE = "knowledge_base"
INTENT_CAPABILITY = "capability"
INTENT_FALLBACK = "fallback"
VALID_INTENTS = {
    INTENT_SMALL_TALK,
    INTENT_DATABASE,
    INTENT_KNOWLEDGE_BASE,
    INTENT_CAPABILITY,
    INTENT_FALLBACK,
}

RAG_SYSTEM_PROMPT = (
    "You are the official customer assistant for NTU Pool (ntupool.org). "
    "Answer strictly from the provided reference context only. "
    "If the context is insufficient, clearly say you do not know and suggest checking ntupool.org. "
    "Do not mention reference context numbers or internal context labels. "
    "For live pool decision questions, answer directly with go, wait, leave water, or keep monitoring, "
    "then cite the relevant status, lightning, trend, and rainfall facts. "
    "Do not answer with only one word; include a brief reason and the next action. "
    "If a live metric is unknown, say which metric is unavailable and still use any known pool status, "
    "trend, rainfall, and operating-hours facts to guide the user. "
    "The reference context may be in a different language than the user; "
    "answer with the facts regardless of the context language."
)

SMALL_TALK_SYSTEM_PROMPT = (
    "You are the official customer assistant for NTU Pool (ntupool.org). "
    "This is casual conversation. Reply naturally and briefly."
)

INTENT_SYSTEM_PROMPT = (
    "You are an intent classifier for NTU Pool assistant. "
    "Classify the user message into exactly one intent and return JSON only.\n\n"
    "Valid intents:\n"
    '- "small_talk": greeting/chitchat/emotion with no factual query.\n'
    '- "database": asks about dynamic app database records: community posts/comments/likes/collections/manual pool reports.\n'
    '- "knowledge_base": asks about ntupool.org website knowledge, policies, operations, weather/source rules, or app feature rules documented in KB.\n'
    '- "capability": asks what this assistant can do, what to ask, or how it can help on ntupool.org.\n'
    '- "fallback": anything outside scope or unclear.\n\n'
    'Return exactly this schema: {"intent":"small_talk|database|knowledge_base|capability|fallback","reason":"short reason"}.\n'
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
    "Keep the answer concise."
)

TRANSLATE_TO_ENGLISH_SYSTEM_PROMPT = (
    "Translate the user message into natural English for backend intent classification and retrieval. "
    "Preserve intent, named entities, proper nouns, and numbers exactly. "
    "Return only the translated English text."
)

TRANSLATE_FROM_ENGLISH_PROMPT_TEMPLATE = (
    "Translate the assistant text into {target_language}. "
    "Preserve meaning, numbers, and named entities exactly. "
    "Return only the translated text."
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
DEFAULT_LOW_CONFIDENCE_SCORE_WINDOW = 0.06
DEFAULT_LOW_CONFIDENCE_MAX_DOCS = 3
DEFAULT_MAX_CONTEXT_CHARS = 4000
DEFAULT_DB_TOOL_MAX_CALLS = 4
MODEL_KIND_INTENT = "intent"
MODEL_KIND_QA = "qa"
DEFAULT_INTENT_LLM_FAILURE_TABLE = "chatbot_intent_model_failures"
DEFAULT_QA_LLM_FAILURE_TABLE = "chatbot_qa_model_failures"
MAX_MODEL_FAILURE_TEXT_LENGTH = 2000

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

LANGUAGE_LABELS = {
    "en": "English",
    "zh": "Simplified Chinese",
}

GREETING_QUICK_QUESTIONS_EN = [
    "Is the pool open right now?",
    "How can I submit a manual pool report?",
    "What are the pool opening hours on weekdays and weekends?",
]

STARTER_QUICK_QUESTIONS_EN = [
    "Can I go swimming now?",
    "How does lightning affect pool status?",
    "How can I submit a manual pool report?",
]

CAPABILITY_ANSWER_EN = (
    "I am the NTU Pool Assistant for ntupool.org. I can help with live pool status, "
    "whether it is sensible to go swimming now, lightning and rainfall risk, opening hours, "
    "manual pool reports, community posts, account usage, and swimming-related website rules. "
    "For current safety decisions, I use the homepage status, lightning trend, rainfall, and "
    "operating-hours context when it is available. Always follow on-site lifeguard instructions."
)

CAPABILITY_ANSWER_ZH = (
    "我是 NTU Pool (ntupool.org) 的官方助手。我可以帮你了解泳池实时状态、现在适不适合去游泳、"
    "闪电和降雨风险、开放时间、手动上报、社区帖子、账号使用以及网站相关规则。"
    "涉及当前安全判断时，我会结合首页状态、闪电趋势、降雨量和开放时段信息。"
    "请始终以现场救生员的指示为准。"
)


def _capability_answer_for_language(language: str) -> str:
    return CAPABILITY_ANSWER_ZH if language == "zh" else CAPABILITY_ANSWER_EN


def _reply_language_instruction(language: str) -> str:
    label = LANGUAGE_LABELS.get(language, "the user's language")
    return f" Reply in {label}."

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FAQ_MARKDOWN_PATH = PROJECT_ROOT / "knowledge_base" / "faq.md"
FAQ_QUESTION_LINE_RE = re.compile(r"^\s*###\s*Q:\s*(.+?)\s*$")

UNKNOWN_GUIDE_QUESTION_SYSTEM_PROMPT = (
    "You write follow-up questions for NTU Pool assistant when a previous answer was not enough. "
    "Based on the user's question and reference snippets, generate exactly 3 concise user-style questions "
    "that are likely answerable from the snippets. "
    "Keep each question under 90 characters and avoid duplicates or yes/no-only variants. "
    'Return JSON only in this exact schema: {"questions":["q1","q2","q3"]}.'
)

GENERAL_QUICK_QUESTIONS_EN = [
    "Is the pool open right now?",
    "How does the lightning warning rule work?",
    "How can I submit a manual pool report?",
]

REPORT_QUICK_QUESTIONS_EN = [
    "How can I submit a manual pool report?",
    "Who is allowed to submit a manual report?",
    "How many reports are needed to override weather status?",
]

HOURS_QUICK_QUESTIONS_EN = [
    "What are the pool opening hours on weekdays?",
    "What are the opening hours on weekends and public holidays?",
    "Why does the system show outside operating hours?",
]

WEATHER_QUICK_QUESTIONS_EN = [
    "How does the lightning closure rule work?",
    "How long is the lightning cooldown before reopening?",
    "How does heavy rain affect pool status?",
]

QUICK_QUESTION_ZH_MAP = {
    "Is the pool open right now?": "\u73b0\u5728\u6cf3\u6c60\u5f00\u653e\u5417\uff1f",
    "Can I go swimming now?": "\u73b0\u5728\u9002\u5408\u53bb\u6e38\u6cf3\u5417\uff1f",
    "How does lightning affect pool status?": "\u95ea\u7535\u4f1a\u5982\u4f55\u5f71\u54cd\u6cf3\u6c60\u72b6\u6001\uff1f",
    "How can I submit a manual pool report?": "\u6211\u8be5\u5982\u4f55\u63d0\u4ea4\u624b\u52a8\u6cf3\u6c60\u4e0a\u62a5\uff1f",
    "What are the pool opening hours on weekdays and weekends?": "\u5de5\u4f5c\u65e5\u548c\u5468\u672b\u7684\u6cf3\u6c60\u5f00\u653e\u65f6\u95f4\u662f\u4ec0\u4e48\uff1f",
    "How does the lightning warning rule work?": "\u95ea\u7535\u9884\u8b66\u89c4\u5219\u662f\u600e\u6837\u7684\uff1f",
    "Who is allowed to submit a manual report?": "\u8c01\u53ef\u4ee5\u63d0\u4ea4\u624b\u52a8\u4e0a\u62a5\uff1f",
    "How many reports are needed to override weather status?": "\u9700\u8981\u591a\u5c11\u6761\u4e0a\u62a5\u624d\u80fd\u8986\u76d6\u5929\u6c14\u72b6\u6001\uff1f",
    "What are the pool opening hours on weekdays?": "\u5de5\u4f5c\u65e5\u7684\u6cf3\u6c60\u5f00\u653e\u65f6\u95f4\u662f\u4ec0\u4e48\uff1f",
    "What are the opening hours on weekends and public holidays?": "\u5468\u672b\u548c\u516c\u5171\u5047\u671f\u7684\u5f00\u653e\u65f6\u95f4\u662f\u4ec0\u4e48\uff1f",
    "Why does the system show outside operating hours?": "\u4e3a\u4ec0\u4e48\u7cfb\u7edf\u4f1a\u663e\u793a\u8d85\u51fa\u5f00\u653e\u65f6\u6bb5\uff1f",
    "How does the lightning closure rule work?": "\u95ea\u7535\u5173\u95ed\u89c4\u5219\u662f\u600e\u6837\u7684\uff1f",
    "How long is the lightning cooldown before reopening?": "\u95ea\u7535\u540e\u591a\u4e45\u53ef\u4ee5\u91cd\u65b0\u5f00\u653e\uff1f",
    "How does heavy rain affect pool status?": "\u5927\u96e8\u4f1a\u5982\u4f55\u5f71\u54cd\u6cf3\u6c60\u72b6\u6001\uff1f",
}

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

KEYWORD_OVERLAP_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "what",
    "when",
    "where",
    "why",
    "how",
    "who",
    "which",
    "of",
    "to",
    "for",
    "on",
    "in",
    "at",
    "by",
    "from",
    "with",
    "and",
    "or",
    "cover",
    "covers",
    "window",
    "time",
}

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
    "report",
    "reports",
    "feed",
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
    "opening",
    "close",
    "closing",
    "weather",
    "lightning",
    "rain",
    "ntupool",
    "website",
    "official",
    "policy",
    "api",
    "community",
    "account",
    "profile",
    "guest",
    "member",
    "verify",
    "verification",
    "register",
    "login",
    "amber",
    "green",
    "red",
    "lane",
    "locker",
    "src",
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
    "\u72b6\u6001",
    "\u6cf3\u9053",
    "\u50a8\u7269\u67dc",
    "\u4f1a\u5458",
    "\u6e38\u5ba2",
    "\u6ce8\u518c",
    "\u767b\u5f55",
    "\u9a8c\u8bc1",
    "\u8d26\u53f7",
    "\u4e2a\u4eba\u4e3b\u9875",
    "\u5047\u671f",
    "\u5047\u65e5",
    "\u65f6\u6bb5",
)

DATABASE_LOOKUP_HINTS = (
    "latest",
    "newest",
    "recent",
    "list",
    "show",
    "find",
    "search",
    "query",
    "fetch",
    "count",
    "number of",
    "how many",
    "today",
    "yesterday",
    "this week",
    "this month",
    "id ",
    " by ",
    "\u6700\u65b0",
    "\u6700\u8fd1",
    "\u4eca\u5929",
    "\u6628\u5929",
    "\u672c\u5468",
    "\u8fd9\u5468",
    "\u672c\u6708",
    "\u5217\u51fa",
    "\u663e\u793a",
    "\u6709\u54ea\u4e9b",
    "\u67e5\u4e00\u4e0b",
)

POLICY_QUESTION_HINTS = (
    "who can",
    "who is allowed",
    "can i",
    "am i allowed",
    "allowed",
    "eligible",
    "eligibility",
    "policy",
    "requirement",
    "requirements",
    "condition",
    "conditions",
    "rule",
    "rules",
    "must",
    "need to",
    "requires",
    "required",
    "verified",
    "verification",
    "login",
    "logged in",
    "register",
    "registered",
    "\u8c01\u53ef\u4ee5",
    "\u8c01\u80fd",
    "\u5141\u8bb8",
    "\u53ef\u4e0d\u53ef\u4ee5",
    "\u80fd\u4e0d\u80fd",
    "\u662f\u5426\u53ef\u4ee5",
    "\u5fc5\u987b",
    "\u8981\u6c42",
    "\u6761\u4ef6",
    "\u6743\u9650",
    "\u89c4\u5219",
    "\u8ba4\u8bc1",
    "\u53ef\u4ee5",
    "\u80fd\u5426",
    "\u53ef\u5426",
)

POLICY_DOMAIN_HINTS = (
    "pool",
    "swim",
    "swimming",
    "weather",
    "lightning",
    "rain",
    "report",
    "manual report",
    "pool report",
    "submit report",
    "ntupool",
    "\u6cf3\u6c60",
    "\u6e38\u6cf3",
    "\u5929\u6c14",
    "\u95ea\u7535",
    "\u96f7\u7535",
    "\u4e0b\u96e8",
    "\u4e0a\u62a5",
    "\u624b\u52a8\u4e0a\u62a5",
    "\u5e16\u5b50",
    "\u8bc4\u8bba",
    "\u793e\u533a",
)

BACKEND_RULE_CORE_HINTS = (
    "logic",
    "architecture",
    "architectural",
    "design",
    "workflow",
    "flow",
    "pipeline",
    "strategy",
    "rule",
    "rules",
    "table",
    "tables",
    "schema",
    "field",
    "fields",
    "column",
    "columns",
    "sync",
    "ingest",
    "ingestion",
    "incremental",
    "update",
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
    "how does",
    "how do",
    "how works",
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
    "knowledge",
    "knowledge base",
    "kb",
    "sync",
    "supabase",
    "postgres",
    "table",
    "match_documents",
    "pool_documents",
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

LIVE_POOL_DECISION_HINTS = (
    "right now",
    "currently",
    "current",
    "now",
    "go to pool",
    "head to pool",
    "go swimming",
    "leave the pool",
    "should i go",
    "should we go",
    "should i leave",
    "is it safe",
    "safe to swim",
    "open now",
    "\u73b0\u5728",
    "\u5f53\u524d",
    "\u6b64\u523b",
    "\u9002\u5408",
    "\u5b89\u5168",
    "\u8981\u4e0d\u8981",
    "\u8be5\u4e0d\u8be5",
    "\u80fd\u4e0d\u80fd",
    "\u53bb\u6cf3\u6c60",
    "\u53bb\u6e38\u6cf3",
    "\u524d\u5f80",
    "\u79bb\u5f00",
    "\u8d70\u5417",
)

LIVE_POOL_DOMAIN_HINTS = (
    "pool",
    "swim",
    "swimming",
    "lightning",
    "rain",
    "weather",
    "\u6cf3\u6c60",
    "\u6e38\u6cf3",
    "\u96f7\u7535",
    "\u95ea\u7535",
    "\u4e0b\u96e8",
    "\u5929\u6c14",
    "\u6cf3\u9053",
    "\u6c34",
    "\u6c60",
)

LIVE_CONTEXT_FOLLOWUP_HINTS = (
    "go there",
    "go later",
    "in 30 minutes",
    "minutes later",
    "what changes",
    "what should i watch",
    "watch",
    "monitor",
    "leave",
    "go",
    "safe",
    "risk",
    "\u8fc7\u53bb",
    "\u7b49\u4e0b",
    "\u4e00\u4f1a",
    "\u5206\u949f\u540e",
    "\u72b6\u6001\u53d8\u5316",
    "\u91cd\u70b9\u770b",
    "\u5173\u6ce8",
    "\u89c2\u5bdf",
    "\u98ce\u9669",
    "\u79bb\u5f00",
)

REPORT_SUBMISSION_HINTS = (
    "submit",
    "submission",
    "send report",
    "file report",
    "make report",
    "report manually",
    "\u63d0\u4ea4",
    "\u5982\u4f55",
    "\u600e\u4e48",
    "\u600e\u6837",
    "\u6211\u8be5",
)

REPORT_DOMAIN_HINTS = (
    "report",
    "manual report",
    "pool report",
    "\u4e0a\u62a5",
    "\u624b\u52a8\u4e0a\u62a5",
    "\u6cf3\u6c60\u4e0a\u62a5",
)

REPORT_RULE_HINTS = (
    "override weather",
    "override status",
    "weather status",
    "reports are needed",
    "reports needed",
    "needed to override",
    "consensus",
    "unanimous",
    "distinct users",
    "\u8986\u76d6",
    "\u5929\u6c14\u72b6\u6001",
    "\u9700\u8981\u591a\u5c11",
    "\u591a\u5c11\u6761",
    "\u51e0\u6761",
    "\u5171\u8bc6",
    "\u4e00\u81f4",
)

CAPABILITY_QUESTION_HINTS = (
    "what can you do",
    "what do you do",
    "how can you help",
    "what can i ask",
    "what should i ask",
    "what are your capabilities",
    "your capabilities",
    "assistant help",
    "help me use this",
    "what are you for",
    "how do i use you",
    "\u4f60\u80fd\u505a\u4ec0\u4e48",
    "\u4f60\u53ef\u4ee5\u505a\u4ec0\u4e48",
    "\u4f60\u80fd\u5e72\u4ec0\u4e48",
    "\u4f60\u4f1a\u4ec0\u4e48",
    "\u53ef\u4ee5\u95ee\u4f60\u4ec0\u4e48",
    "\u6211\u80fd\u95ee\u4f60\u4ec0\u4e48",
    "\u4f60\u80fd\u5e2e\u6211\u4ec0\u4e48",
    "\u600e\u4e48\u7528\u4f60",
    "\u4f7f\u7528\u5e2e\u52a9",
)

CAPABILITY_QUESTION_EXACT_COMPACT = {
    "help",
    "\u5e2e\u52a9",
    "\u4f60\u80fd\u505a\u4ec0\u4e48",
    "\u4f60\u53ef\u4ee5\u505a\u4ec0\u4e48",
    "\u4f60\u80fd\u5e72\u4ec0\u4e48",
    "\u4f60\u4f1a\u4ec0\u4e48",
}


class ChatbotConfigError(RuntimeError):
    pass


class GraphState(TypedDict, total=False):
    question: str
    original_question: NotRequired[str]
    question_en: NotRequired[str]
    input_language: NotRequired[str]
    page_context: NotRequired[list[str]]
    intent: NotRequired[str]
    mode: NotRequired[str]
    context: NotRequired[list[str]]
    kb_chunks: NotRequired[int]
    answer: NotRequired[str]
    sources: NotRequired[list[str]]
    quick_questions: NotRequired[list[str]]
    hard_kb_id: NotRequired[str]
    hard_kb_score: NotRequired[float]


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


@lru_cache(maxsize=1)
def _get_cached_logging_supabase_client(supabase_url: str, service_role_key: str):
    return create_client(supabase_url, service_role_key)


def _model_failure_table_name(model_kind: str) -> str:
    if model_kind == MODEL_KIND_INTENT:
        return (
            os.getenv("SUPABASE_INTENT_LLM_FAILURE_TABLE", "").strip()
            or DEFAULT_INTENT_LLM_FAILURE_TABLE
        )
    return (
        os.getenv("SUPABASE_QA_LLM_FAILURE_TABLE", "").strip()
        or DEFAULT_QA_LLM_FAILURE_TABLE
    )


def _resolve_llm_model_name(llm: Any) -> str:
    model_name = str(
        getattr(llm, "model_name", "") or getattr(llm, "model", "") or ""
    ).strip()
    return model_name or "unknown"


def _truncate_failure_text(text: str, *, max_length: int = MAX_MODEL_FAILURE_TEXT_LENGTH) -> str:
    value = str(text or "").strip()
    if len(value) <= max_length:
        return value
    return value[: max(0, max_length - 1)] + "…"


def _normalize_failure_metadata(raw_metadata: Any) -> dict[str, Any]:
    if not isinstance(raw_metadata, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in raw_metadata.items():
        if not isinstance(key, str):
            continue
        item_key = key.strip()
        if not item_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            normalized[item_key] = value
            continue
        normalized[item_key] = str(value)
    return normalized


def _record_model_failure(
    *,
    model_kind: str,
    llm: Any,
    operation: str,
    error_type: str,
    error_message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        return

    table_name = _model_failure_table_name(model_kind)
    if not table_name:
        return

    payload = {
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "model_name": _resolve_llm_model_name(llm),
        "operation": str(operation or "").strip() or "unknown_operation",
        "error_type": _truncate_failure_text(error_type),
        "error_message": _truncate_failure_text(error_message),
        "metadata": _normalize_failure_metadata(metadata or {}),
    }
    try:
        client = _get_cached_logging_supabase_client(supabase_url, service_role_key)
        client.table(table_name).insert(payload).execute()
    except Exception:
        # Logging must never block chatbot main flow.
        pass


def _invoke_llm_with_failure_logging(
    *,
    llm: Any,
    model_kind: str,
    operation: str,
    messages: list[Any],
    metadata: dict[str, Any] | None = None,
) -> Any:
    try:
        return llm.invoke(messages)
    except Exception as exc:
        _record_model_failure(
            model_kind=model_kind,
            llm=llm,
            operation=operation,
            error_type=type(exc).__name__,
            error_message=str(exc),
            metadata=metadata,
        )
        raise


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_CJK_RE = re.compile(r"[一-鿿]")


def _hint_is_cjk(hint: str) -> bool:
    return bool(_CJK_RE.search(hint or ""))


@lru_cache(maxsize=4096)
def _hint_pattern(hint: str):
    """Word-boundary matcher for an ASCII hint token.

    A trailing optional plural suffix keeps singular hints matching plural
    text ("report" -> "reports") without reintroducing fragment matches
    ("api" must not match "capital").
    """
    escaped = re.escape(hint)
    prefix = r"\b" if hint[:1].isalnum() else ""
    if hint[-1:].isalpha():
        suffix = r"(?:s|es)?\b"
    elif hint[-1:].isalnum():
        suffix = r"\b"
    else:
        suffix = ""
    return re.compile(prefix + escaped + suffix)


def _contains_hint(text: str, hints) -> bool:
    """Hint matching with word boundaries for ASCII, substring for CJK.

    Plain substring matching used to fire on fragments: "api" matched
    "c-api-tal", "dev" matched "device", "open" matched "opening" — routing
    unrelated questions into site-knowledge answers. CJK has no word
    boundaries, so those hints keep substring semantics.
    """
    lowered = (text or "").lower()
    if not lowered:
        return False
    for hint in hints:
        if not hint:
            continue
        if _hint_is_cjk(hint):
            if hint in lowered:
                return True
        elif _hint_pattern(hint.lower()).search(lowered):
            return True
    return False


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


def _looks_like_quick_question(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    if len(value) > 90:
        return False
    if "\n" in value:
        return False
    if re.search(r"[?？]\s*$", value):
        return True
    if value.endswith("\u5417"):
        return True

    lowered = value.lower()
    en_prefixes = ("how ", "what ", "why ", "when ", "where ", "who ", "can ", "is ", "are ")
    zh_prefixes = (
        "\u5982\u4f55",
        "\u600e\u4e48",
        "\u4e3a\u4ec0\u4e48",
        "\u591a\u5c11",
        "\u662f\u5426",
        "\u8c01",
        "\u54ea",
        "\u53ef\u4e0d\u53ef\u4ee5",
        "\u80fd\u5426",
        "\u73b0\u5728",
    )
    return lowered.startswith(en_prefixes) or value.startswith(zh_prefixes)


def _normalize_quick_questions(raw: Any, *, max_items: int = 3) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        if not _looks_like_quick_question(text):
            continue
        if text in values:
            continue
        values.append(text)
        if len(values) >= max(1, max_items):
            break
    return values


def _extract_text_content(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    return str(raw or "").strip()


def _translate_to_english(text: str, intent_llm: Any, qa_llm: Any) -> str:
    source = (text or "").strip()
    if not source:
        return ""
    if _detect_language(source) == "en":
        return source

    translate_messages = [
        SystemMessage(content=TRANSLATE_TO_ENGLISH_SYSTEM_PROMPT),
        HumanMessage(content=source),
    ]

    model_chain = [
        (MODEL_KIND_INTENT, intent_llm, "translate_to_english.intent_primary"),
        (MODEL_KIND_QA, qa_llm, "translate_to_english.qa_fallback"),
    ]
    for model_kind, model_client, operation in model_chain:
        try:
            response = _invoke_llm_with_failure_logging(
                llm=model_client,
                model_kind=model_kind,
                operation=operation,
                messages=translate_messages,
                metadata={"source_language": _detect_language(source)},
            )
            translated = _extract_text_content(getattr(response, "content", ""))
            if translated and _detect_language(translated) == "en":
                return translated
            _record_model_failure(
                model_kind=model_kind,
                llm=model_client,
                operation=f"{operation}.validation",
                error_type="TranslationValidationError",
                error_message="Translation output is empty or not English.",
                metadata={
                    "source_language": _detect_language(source),
                    "translated_preview": _truncate_failure_text(translated, max_length=120),
                },
            )
        except Exception:
            continue

    _record_model_failure(
        model_kind=MODEL_KIND_QA,
        llm=qa_llm,
        operation="translate_to_english.exhausted_fallbacks",
        error_type="TranslationFallbackExhausted",
        error_message="Both intent and QA models failed to provide usable English translation.",
        metadata={"source_language": _detect_language(source)},
    )
    return source


def _translate_from_english(text: str, target_language: str, llm: ChatOpenAI) -> str:
    source = (text or "").strip()
    if not source:
        return ""
    if target_language == "en":
        return source

    language_label = LANGUAGE_LABELS.get(target_language, "the user's language")
    system_prompt = TRANSLATE_FROM_ENGLISH_PROMPT_TEMPLATE.format(
        target_language=language_label
    )
    try:
        response = _invoke_llm_with_failure_logging(
            llm=llm,
            model_kind=MODEL_KIND_QA,
            operation="translate_from_english.qa",
            messages=[
                SystemMessage(content=system_prompt),
                HumanMessage(content=source),
            ],
            metadata={"target_language": target_language},
        )
        translated = _extract_text_content(getattr(response, "content", ""))
        if translated:
            return translated
    except Exception:
        pass
    return source


def _translate_quick_questions(
    quick_questions: list[str], *, target_language: str, llm: ChatOpenAI
) -> list[str]:
    normalized = _normalize_quick_questions(quick_questions)
    if not normalized:
        return []
    if target_language == "en":
        return normalized

    if target_language == "zh":
        mapped: list[str] = []
        missing: list[str] = []
        for item in normalized:
            resolved = QUICK_QUESTION_ZH_MAP.get(item, "").strip()
            if resolved:
                mapped.append(resolved)
            else:
                missing.append(item)

        translated_missing: list[str] = []
        for item in missing:
            localized = _translate_from_english(item, target_language, llm).strip()
            if localized:
                translated_missing.append(localized)

        return _normalize_quick_questions(mapped + translated_missing)

    translated: list[str] = []
    for item in normalized:
        localized = _translate_from_english(item, target_language, llm).strip()
        if not localized:
            continue
        if localized not in translated:
            translated.append(localized)
    return _normalize_quick_questions(translated)


@lru_cache(maxsize=1)
def _load_faq_questions() -> tuple[str, ...]:
    if not FAQ_MARKDOWN_PATH.exists():
        return tuple()

    questions: list[str] = []
    try:
        with FAQ_MARKDOWN_PATH.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                match = FAQ_QUESTION_LINE_RE.match(raw_line)
                if not match:
                    continue
                question = match.group(1).strip()
                if not question:
                    continue
                if not _looks_like_quick_question(question):
                    continue
                if question in questions:
                    continue
                questions.append(question)
    except Exception:
        return tuple()
    return tuple(questions)


def _word_tokens_for_similarity(text: str) -> set[str]:
    value = (text or "").strip().lower()
    if not value:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value)
        if len(token) >= 2 and token not in KEYWORD_OVERLAP_STOPWORDS
    }


def _token_jaccard_ratio(query_text: str, candidate_text: str) -> float:
    query_tokens = _word_tokens_for_similarity(query_text)
    candidate_tokens = _word_tokens_for_similarity(candidate_text)
    if not query_tokens or not candidate_tokens:
        return 0.0
    intersection = len(query_tokens & candidate_tokens)
    union = len(query_tokens | candidate_tokens)
    if union <= 0:
        return 0.0
    return intersection / union


def _faq_question_relevance_score(query_text: str, candidate_text: str) -> float:
    query = (query_text or "").strip()
    candidate = (candidate_text or "").strip()
    if not query or not candidate:
        return 0.0

    overlap_ratio = _keyword_overlap_ratio(query, candidate)
    jaccard_ratio = _token_jaccard_ratio(query, candidate)
    sequence_ratio = SequenceMatcher(None, query.lower(), candidate.lower()).ratio()

    normalized_query = " ".join(re.findall(r"[a-z0-9]+", query.lower()))
    normalized_candidate = " ".join(re.findall(r"[a-z0-9]+", candidate.lower()))
    contains_bonus = 0.2 if normalized_query and normalized_query in normalized_candidate else 0.0

    return (
        overlap_ratio * 0.58
        + jaccard_ratio * 0.27
        + sequence_ratio * 0.15
        + contains_bonus
    )


def _related_faq_quick_questions(
    question: str,
    *,
    generated_hints: list[str] | None = None,
    count: int = 3,
) -> list[str]:
    desired = max(1, int(count))
    faq_questions = list(_load_faq_questions())
    if not faq_questions:
        fallback = _quick_questions_for_unanswerable(question)
        return _normalize_quick_questions(fallback, max_items=desired)

    query = (question or "").strip()
    hints = _normalize_quick_questions(generated_hints or [], max_items=desired)
    for seeded in _quick_questions_for_unanswerable(query):
        if seeded not in hints:
            hints.append(seeded)

    scored: list[tuple[str, float, float, float]] = []
    for faq_question in faq_questions:
        query_score = _faq_question_relevance_score(query, faq_question)
        hint_score = 0.0
        for hint in hints:
            hint_score = max(hint_score, _faq_question_relevance_score(hint, faq_question))
        combined_score = query_score + (hint_score * 0.4)
        scored.append((faq_question, combined_score, query_score, hint_score))

    scored.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)

    selected: list[str] = []
    for faq_question, _combined_score, _query_score, _hint_score in scored:
        if faq_question in selected:
            continue
        selected.append(faq_question)
        if len(selected) >= desired:
            break

    if len(selected) < desired:
        for faq_question in faq_questions:
            if faq_question in selected:
                continue
            selected.append(faq_question)
            if len(selected) >= desired:
                break

    return _normalize_quick_questions(selected, max_items=desired)


def _random_faq_quick_questions(*, count: int = 3) -> list[str]:
    desired = max(1, int(count))
    faq_questions = list(_load_faq_questions())
    sampled: list[str] = []
    if len(faq_questions) >= desired:
        sampled = random.sample(faq_questions, desired)
    else:
        sampled = faq_questions[:]

    resolved = _normalize_quick_questions(sampled, max_items=desired)
    if len(resolved) >= desired:
        return resolved

    fallback = _normalize_quick_questions(
        GREETING_QUICK_QUESTIONS_EN,
        max_items=max(desired, len(GREETING_QUICK_QUESTIONS_EN)),
    )
    for item in fallback:
        if item in resolved:
            continue
        resolved.append(item)
        if len(resolved) >= desired:
            break
    return resolved


def _generate_quick_questions_from_context(
    *,
    question: str,
    context_chunks: list[str],
    llm: ChatOpenAI,
    max_context_chars: int,
) -> list[str]:
    normalized_context = [chunk.strip() for chunk in (context_chunks or []) if str(chunk).strip()]
    if not normalized_context:
        return []

    context_text = _truncate_context(normalized_context, max(1200, max_context_chars // 2))
    if not context_text:
        return []

    try:
        response = _invoke_llm_with_failure_logging(
            llm=llm,
            model_kind=MODEL_KIND_QA,
            operation="generate_quick_questions_from_context.qa",
            messages=[
                SystemMessage(content=UNKNOWN_GUIDE_QUESTION_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"User question:\n{(question or '').strip()}\n\n"
                        f"Reference snippets:\n{context_text}\n\n"
                        "Return JSON only."
                    )
                ),
            ],
            metadata={"context_chunks": len(normalized_context)},
        )
        payload = _extract_json_object(_extract_text_content(getattr(response, "content", "")))
        if not payload:
            return []
        raw_questions = payload.get("questions")
        if not isinstance(raw_questions, list):
            return []
        cleaned = _normalize_quick_questions(raw_questions, max_items=3)
        if not cleaned:
            return []
        source_question = (question or "").strip().lower()
        deduped: list[str] = []
        for item in cleaned:
            if item.strip().lower() == source_question:
                continue
            if item in deduped:
                continue
            deduped.append(item)
            if len(deduped) >= 3:
                break
        return deduped
    except Exception:
        return []


def _quick_questions_from_similar_context(
    *,
    question: str,
    context_chunks: list[str],
    vector_store: SupabaseVectorStore,
    llm: ChatOpenAI,
    top_k: int,
    min_score: float,
    max_context_chars: int,
) -> list[str]:
    query = (question or "").strip()
    context: list[str] = [chunk.strip() for chunk in (context_chunks or []) if str(chunk).strip()]

    if not context and query:
        for doc, score in _search_with_optional_scores(vector_store, query, max(top_k, 5)):
            if score is not None and score < min_score:
                continue
            _append_doc_to_context(doc, context, [])
            if len(context) >= max(top_k, 3):
                break

    if not context and query:
        for doc, _score in _search_with_optional_scores(vector_store, query, max(top_k, 3)):
            _append_doc_to_context(doc, context, [])
            if len(context) >= max(top_k, 3):
                break

    generated = _generate_quick_questions_from_context(
        question=query,
        context_chunks=context,
        llm=llm,
        max_context_chars=max_context_chars,
    )
    return _related_faq_quick_questions(
        query,
        generated_hints=generated,
        count=3,
    )


def _quick_questions_for_unanswerable(question: str) -> list[str]:
    lowered = (question or "").strip().lower()
    if not lowered:
        return GENERAL_QUICK_QUESTIONS_EN

    report_tokens = (
        "report",
        "manual report",
        "pool report",
        "submit report",
        "report manually",
    )
    if _contains_hint(lowered, report_tokens):
        return REPORT_QUICK_QUESTIONS_EN

    hour_tokens = (
        "opening hours",
        "operating hours",
        "open time",
        "close time",
        "weekday",
        "weekend",
        "public holiday",
        "hours",
    )
    if _contains_hint(lowered, hour_tokens):
        return HOURS_QUICK_QUESTIONS_EN

    weather_tokens = (
        "lightning",
        "rain",
        "weather",
        "open now",
        "closed now",
        "status",
    )
    if _contains_hint(lowered, weather_tokens):
        return WEATHER_QUICK_QUESTIONS_EN

    return GENERAL_QUICK_QUESTIONS_EN


def _looks_like_capability_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False

    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lowered)
    if compact in CAPABILITY_QUESTION_EXACT_COMPACT:
        return True
    return _contains_hint(lowered, CAPABILITY_QUESTION_HINTS)


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


# Signals that scope a query to CONCRETE STORED RECORDS (a time window or an
# explicit listing verb). Counting words are deliberately excluded: "how many
# reports are NEEDED to override" is a rule requirement, not a row count.
RECORD_SCOPE_HINTS = (
    "latest",
    "newest",
    "recent",
    "today",
    "yesterday",
    "this week",
    "this month",
    "list ",
    "show me",
    "最新",       # 最新
    "最近",       # 最近
    "今天",       # 今天
    "昨天",       # 昨天
    "本周",       # 本周
    "这周",       # 这周
    "本月",       # 本月
    "列出",       # 列出
    "有哪些",  # 有哪些
)


# Unambiguous record-lookup signals: these describe WHICH rows to fetch,
# unlike soft verbs (search/find/show/list) that also appear in how-to
# phrasing. Used to veto the how-to guard.
STRONG_DATABASE_LOOKUP_HINTS = (
    "latest",
    "newest",
    "recent",
    "count",
    "number of",
    "how many",
    "today",
    "yesterday",
    "this week",
    "this month",
    "最新",       # 最新
    "最近",       # 最近
    "多少条",  # 多少条
    "几条",       # 几条
    "今天",       # 今天
    "昨天",       # 昨天
)

HOWTO_QUESTION_PATTERNS = (
    re.compile(r"\bhow (do|can|could|would|should) (i|you|we|one)\b"),
    re.compile(r"\bhow to\b"),
    re.compile(r"\bwhere (do|can|should) (i|you|we)\b"),
    re.compile(r"\bis there a way to\b"),
    re.compile(r"\bwhat is the way to\b"),
)
HOWTO_ZH_HINTS = (
    "怎么",       # 怎么
    "如何",       # 如何
    "怎样",       # 怎样
    "在哪里",  # 在哪里
    "哪里可以",  # 哪里可以
    "怎么才能",  # 怎么才能
)
# Site features a usage question can be about. Deliberately includes the
# database entity nouns: "how do I search for posts" is documentation about
# a feature, not a request to fetch post records.
SITE_USAGE_DOMAIN_HINTS = (
    "search",
    "profile",
    "account",
    "message",
    "avatar",
    "nickname",
    "password",
    "notification",
    "bookmark",
    "collect",
    "搜索",       # 搜索
    "个人主页",  # 个人主页
    "账号",       # 账号
    "私信",       # 私信
    "头像",       # 头像
    "昵称",       # 昵称
    "密码",       # 密码
    "收藏",       # 收藏
) + DATABASE_HINTS + KNOWLEDGE_BASE_HINTS


def _looks_like_howto_question(question: str) -> bool:
    """True for 'how do I ...' style questions with no record-lookup intent.

    Only STRONG lookup signals veto: soft verbs like "search"/"find"/"show"
    are part of normal how-to phrasing ("how do I search for posts"), so
    using them as a veto would push usage questions back into the database
    path — the exact misroute this guard exists to prevent.
    """
    text = (question or "").strip()
    if not text:
        return False
    lowered = text.lower()
    # "how many posts are there" is a count lookup, not a usage question.
    if _contains_hint(lowered, STRONG_DATABASE_LOOKUP_HINTS):
        return False
    if re.search(r"\b(id|#)\s*\d+\b", lowered):
        return False
    if any(pattern.search(lowered) for pattern in HOWTO_QUESTION_PATTERNS):
        return True
    return _contains_hint(text, HOWTO_ZH_HINTS)


def _looks_like_site_usage_question(question: str) -> bool:
    """A how-to question about a site feature is documentation, not data.

    Without this guard, merely naming an entity ('posts', 'comments',
    '上报') routed usage questions into the database tool path, which then
    queried real records and answered 'no useful data' to questions like
    'How do I search for posts in the community?'.
    """
    if not _looks_like_howto_question(question):
        return False
    lowered = (question or "").strip().lower()
    return _contains_hint(lowered, SITE_USAGE_DOMAIN_HINTS)


def _has_database_lookup_intent(lowered_question: str) -> bool:
    if _contains_hint(lowered_question, DATABASE_LOOKUP_HINTS):
        return True
    if re.search(r"\b(id|#)\s*\d+\b", lowered_question):
        return True
    return False


def _looks_like_report_submission_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False
    if _has_database_lookup_intent(lowered):
        return False
    has_report_domain = _contains_hint(lowered, REPORT_DOMAIN_HINTS)
    has_submission_signal = _contains_hint(lowered, REPORT_SUBMISSION_HINTS)
    return has_report_domain and has_submission_signal


def _looks_like_report_rule_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False
    has_report_domain = _contains_hint(lowered, REPORT_DOMAIN_HINTS)
    has_rule_signal = _contains_hint(lowered, REPORT_RULE_HINTS)
    if not (has_report_domain and has_rule_signal):
        return False
    # "今天有多少条上报？" counts stored rows; "需要多少条上报才能覆盖天气状态？"
    # states a requirement. Only a concrete record scope (time window or
    # listing verb) means the user wants data rather than documentation —
    # counting words alone appear in both phrasings.
    return not _contains_hint(lowered, RECORD_SCOPE_HINTS)


def _looks_like_policy_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False

    has_policy_signal = _contains_hint(lowered, POLICY_QUESTION_HINTS)
    starts_like_policy = bool(
        re.match(
            r"^\s*(who can|who is allowed|can (i|a |an |the )?(guest|guests|user|users|member|members|student|students)?\s*|am i allowed|do i need to|must i|what (is|are) (the )?(policy|rules?))\b",
            lowered,
        )
    )
    if not (has_policy_signal or starts_like_policy):
        return False

    # Polite phrasing does not make a record lookup a policy question:
    # "可以给我看最新的帖子吗？" scopes concrete rows despite the "可以".
    if _contains_hint(lowered, RECORD_SCOPE_HINTS):
        return False

    has_domain_signal = _contains_hint(lowered, POLICY_DOMAIN_HINTS) or _looks_like_kb_question(
        question
    )
    return has_domain_signal


def _looks_like_database_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False

    has_database_signal = _contains_hint(lowered, DATABASE_HINTS)
    if not has_database_signal:
        return False

    # Policy/rules questions should stay in KB unless there is an explicit
    # record-lookup intent (latest/list/count/id/time-window).
    if _looks_like_policy_question(question) and not _has_database_lookup_intent(lowered):
        return False
    # "How do I <verb> <entity>" is a usage question about a feature, not a
    # request to fetch records of that entity.
    if _looks_like_site_usage_question(question):
        return False
    return True


def _looks_like_kb_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False
    return _contains_hint(lowered, KNOWLEDGE_BASE_HINTS)


def _looks_like_live_pool_decision_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False
    has_domain_signal = _contains_hint(lowered, LIVE_POOL_DOMAIN_HINTS)
    has_decision_signal = _contains_hint(lowered, LIVE_POOL_DECISION_HINTS)
    return has_domain_signal and has_decision_signal


def _looks_like_live_context_followup_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False
    return _contains_hint(lowered, LIVE_CONTEXT_FOLLOWUP_HINTS)


def _normalize_page_context_chunks(raw_context: Any) -> list[str]:
    if isinstance(raw_context, str):
        candidates = [raw_context]
    elif isinstance(raw_context, list):
        candidates = raw_context
    else:
        return []

    chunks: list[str] = []
    total_chars = 0
    for item in candidates:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in chunks:
            continue
        if len(text) > 900:
            text = text[:899] + "\u2026"
        if total_chars + len(text) > 3000:
            break
        chunks.append(text)
        total_chars += len(text)
        if len(chunks) >= 10:
            break
    return chunks


def _is_backend_rules_question(question: str) -> bool:
    lowered = (question or "").strip().lower()
    if not lowered:
        return False

    has_domain_signal = _contains_hint(lowered, BACKEND_RULE_DOMAIN_HINTS)
    has_core_signal = _contains_hint(lowered, BACKEND_RULE_CORE_HINTS)
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
        "capability": INTENT_CAPABILITY,
        "capabilities": INTENT_CAPABILITY,
        "assistant_capability": INTENT_CAPABILITY,
        "help": INTENT_CAPABILITY,
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
    if _looks_like_capability_question(question):
        return INTENT_CAPABILITY
    if _is_small_talk_heuristic(question):
        return INTENT_SMALL_TALK
    if _looks_like_live_pool_decision_question(question):
        return INTENT_KNOWLEDGE_BASE
    # Follow-ups about going later / what to watch are live-status questions
    # even without an explicit pool noun ("我30分钟后过去合适吗？").
    if _looks_like_live_context_followup_question(question):
        return INTENT_KNOWLEDGE_BASE
    if _is_backend_rules_question(question):
        return INTENT_KNOWLEDGE_BASE
    if _looks_like_report_submission_question(question):
        return INTENT_KNOWLEDGE_BASE
    if _looks_like_report_rule_question(question):
        return INTENT_KNOWLEDGE_BASE
    if _looks_like_policy_question(question):
        return INTENT_KNOWLEDGE_BASE
    # Usage/how-to questions are documentation, even when they name a
    # database entity ("how do I search for posts").
    if _looks_like_site_usage_question(question):
        return INTENT_KNOWLEDGE_BASE
    if _looks_like_database_question(question):
        return INTENT_DATABASE
    if _looks_like_kb_question(question):
        return INTENT_KNOWLEDGE_BASE
    return INTENT_FALLBACK


def _merge_model_intent_with_heuristic(
    question: str,
    model_intent: str | None,
    fallback_question: str = "",
) -> str:
    normalized_model_intent = _normalize_intent(model_intent)
    heuristic_intent = _heuristic_intent(question)
    fallback_heuristic_intent = (
        _heuristic_intent(fallback_question)
        if (fallback_question or "").strip()
        else INTENT_FALLBACK
    )
    domain_heuristic_intent = (
        heuristic_intent
        if heuristic_intent in {INTENT_DATABASE, INTENT_KNOWLEDGE_BASE}
        else fallback_heuristic_intent
        if fallback_heuristic_intent in {INTENT_DATABASE, INTENT_KNOWLEDGE_BASE}
        else INTENT_FALLBACK
    )

    if (
        normalized_model_intent in {INTENT_CAPABILITY, INTENT_SMALL_TALK, INTENT_FALLBACK}
        and domain_heuristic_intent != INTENT_FALLBACK
    ):
        return domain_heuristic_intent

    if _looks_like_capability_question(question) or _looks_like_capability_question(
        fallback_question
    ):
        return INTENT_CAPABILITY

    if normalized_model_intent == INTENT_CAPABILITY and heuristic_intent != INTENT_FALLBACK:
        return heuristic_intent

    if (
        normalized_model_intent == INTENT_SMALL_TALK
        and heuristic_intent in {INTENT_CAPABILITY, INTENT_DATABASE, INTENT_KNOWLEDGE_BASE}
    ):
        return heuristic_intent

    # Live status/decision questions are easy for small intent models to mistake
    # as casual wording; keep them on the context-backed path.
    if (
        _looks_like_live_pool_decision_question(question)
        and normalized_model_intent in {INTENT_SMALL_TALK, INTENT_FALLBACK}
    ):
        return INTENT_KNOWLEDGE_BASE

    # Policy/rules questions should stay in KB flow even when model drifts to DB.
    if _looks_like_policy_question(question) and normalized_model_intent == INTENT_DATABASE:
        return INTENT_KNOWLEDGE_BASE

    # Guardrail: when model says fallback but heuristics strongly detect an in-scope query,
    # trust heuristics to avoid false fallback and route into DB/RAG flow.
    if normalized_model_intent == INTENT_FALLBACK and heuristic_intent != INTENT_FALLBACK:
        return heuristic_intent
    if normalized_model_intent in VALID_INTENTS:
        return normalized_model_intent
    return heuristic_intent


def _confident_heuristic_intent(question: str, fallback_question: str = "") -> str | None:
    """Return an intent when heuristics alone are confident, else None.

    This runs BEFORE any intent-model call: most real questions match a
    deterministic rule, so the (potentially slow, potentially flaky) intent
    model is only consulted for genuinely ambiguous messages.
    """
    text = (question or "").strip()
    fallback_text = (fallback_question or "").strip()
    primary = _heuristic_intent(text) if text else INTENT_FALLBACK
    secondary = _heuristic_intent(fallback_text) if fallback_text else INTENT_FALLBACK
    domain = (
        primary
        if primary in {INTENT_DATABASE, INTENT_KNOWLEDGE_BASE}
        else secondary
        if secondary in {INTENT_DATABASE, INTENT_KNOWLEDGE_BASE}
        else None
    )

    if primary == INTENT_CAPABILITY:
        # A domain signal in the paired question overrides a capability-looking
        # phrasing (mirrors _merge_model_intent_with_heuristic).
        return domain or INTENT_CAPABILITY
    if primary == INTENT_SMALL_TALK:
        return INTENT_SMALL_TALK
    if domain is not None:
        return domain
    return None


def _classify_intent(
    question: str, intent_llm: ChatOpenAI, fallback_question: str = ""
) -> str:
    text = (question or "").strip()
    fallback_text = (fallback_question or "").strip()
    if not text and not fallback_text:
        return INTENT_FALLBACK

    confident = _confident_heuristic_intent(text or fallback_text, fallback_text if text else "")
    if confident is not None:
        return confident

    if text:
        try:
            response = _invoke_llm_with_failure_logging(
                llm=intent_llm,
                model_kind=MODEL_KIND_INTENT,
                operation="classify_intent.intent",
                messages=[
                    SystemMessage(content=INTENT_SYSTEM_PROMPT),
                    HumanMessage(content=text),
                ],
                metadata={"question_preview": _truncate_failure_text(text, max_length=120)},
            )
            raw = response.content
            raw_text = raw if isinstance(raw, str) else str(raw)
            payload = _extract_json_object(raw_text)
            if payload:
                resolved = _merge_model_intent_with_heuristic(
                    text,
                    str(payload.get("intent", "")),
                    fallback_question=fallback_text,
                )
                if resolved != INTENT_FALLBACK:
                    return resolved
            else:
                _record_model_failure(
                    model_kind=MODEL_KIND_INTENT,
                    llm=intent_llm,
                    operation="classify_intent.intent.parse_json",
                    error_type="IntentPayloadParseError",
                    error_message="Intent model response is not valid JSON.",
                    metadata={"raw_preview": _truncate_failure_text(raw_text, max_length=180)},
                )
        except Exception:
            pass

    heuristic_primary = _heuristic_intent(text) if text else INTENT_FALLBACK
    if heuristic_primary != INTENT_FALLBACK:
        return heuristic_primary
    if fallback_text:
        return _heuristic_intent(fallback_text)
    return INTENT_FALLBACK


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
    # With ANN indexes (for example IVFFLAT), a tiny candidate pool can miss
    # the true nearest chunk. Pull a wider pool, then filter/rerank downstream.
    search_k = max(int(top_k or 0) * 4, 24)

    if hasattr(vector_store, "similarity_search_with_relevance_scores"):
        try:
            pairs = vector_store.similarity_search_with_relevance_scores(question, k=search_k)
            if pairs:
                return [(doc, _coerce_score(score)) for doc, score in pairs]
        except Exception:
            pass

    if hasattr(vector_store, "similarity_search_with_score"):
        try:
            pairs = vector_store.similarity_search_with_score(question, k=search_k)
            # Some vector stores return distance-like scores where lower is better.
            # Keep compatibility by skipping threshold filtering for this branch.
            if pairs:
                return [(doc, None) for doc, _score in pairs]
        except Exception:
            pass

    if hasattr(vector_store, "similarity_search"):
        try:
            docs = vector_store.similarity_search(question, k=search_k)
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
            "match_count": search_k,
            "filter": {},
        },
    ).execute()

    rows = (response.data or []) if hasattr(response, "data") else []
    if not rows and search_k < 64:
        # Retry once with a wider neighborhood to reduce false-empty retrieval.
        retry_k = max(search_k * 2, 48)
        retry_response = client.rpc(
            query_name,
            {
                "query_embedding": query_embedding,
                "match_count": retry_k,
                "filter": {},
            },
        ).execute()
        rows = (retry_response.data or []) if hasattr(retry_response, "data") else []

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
    if text in context:
        return
    context.append(text)

    metadata = getattr(doc, "metadata", {}) or {}
    source = metadata.get("source") or metadata.get("url")
    if source and source not in sources:
        sources.append(str(source))


def _keyword_overlap_ratio(query_text: str, candidate_text: str) -> float:
    query = (query_text or "").strip().lower()
    candidate = (candidate_text or "").strip().lower()
    if not query or not candidate:
        return 0.0

    query_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", query)
        if len(token) >= 3 and token not in KEYWORD_OVERLAP_STOPWORDS
    }
    if not query_tokens:
        return 0.0

    candidate_tokens = set(re.findall(r"[a-z0-9]+", candidate))
    if not candidate_tokens:
        return 0.0

    overlap = len(query_tokens & candidate_tokens)
    return overlap / max(1, len(query_tokens))


def _select_low_confidence_fallback_docs(
    matched: list[tuple[Any, float | None]],
    *,
    top_k: int,
    query_text: str = "",
) -> list[Any]:
    if not matched:
        return []

    max_docs = max(1, min(int(top_k or 0), DEFAULT_LOW_CONFIDENCE_MAX_DOCS))
    scored_pairs = [(doc, score) for doc, score in matched if score is not None]
    if not scored_pairs:
        return [doc for doc, _score in matched[:max_docs]]

    best_score = max(score for _doc, score in scored_pairs)
    if best_score < DEFAULT_FALLBACK_MIN_SCORE:
        return []

    band_floor = max(DEFAULT_FALLBACK_MIN_SCORE, best_score - DEFAULT_LOW_CONFIDENCE_SCORE_WINDOW)
    narrowed = [(doc, score) for doc, score in scored_pairs if score >= band_floor]
    if not narrowed:
        narrowed = [max(scored_pairs, key=lambda item: item[1])]

    # Some providers do not guarantee ordering; enforce high-score-first.
    narrowed.sort(key=lambda item: item[1], reverse=True)
    selected_docs = [doc for doc, _score in narrowed[:max_docs]]
    if len(selected_docs) >= max_docs:
        return selected_docs

    selected_texts = {
        (getattr(doc, "page_content", "") or "").strip()
        for doc in selected_docs
        if (getattr(doc, "page_content", "") or "").strip()
    }
    lexical_candidates: list[tuple[Any, float, float]] = []
    for doc, score in scored_pairs:
        if score < DEFAULT_FALLBACK_MIN_SCORE:
            continue
        text = (getattr(doc, "page_content", "") or "").strip()
        if not text or text in selected_texts:
            continue
        overlap = _keyword_overlap_ratio(query_text, text)
        if overlap <= 0:
            continue
        lexical_candidates.append((doc, overlap, score))

    lexical_candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
    for doc, _overlap, _score in lexical_candidates:
        selected_docs.append(doc)
        if len(selected_docs) >= max_docs:
            break

    return selected_docs


def _select_near_threshold_support_docs(
    matched: list[tuple[Any, float | None]],
    *,
    min_score: float,
    top_k: int,
    selected_sources: list[str],
    max_extra_docs: int = 2,
    query_text: str = "",
) -> list[Any]:
    if not matched or max_extra_docs <= 0:
        return []

    desired = max(0, min(int(top_k or 0), int(max_extra_docs)))
    if desired <= 0:
        return []

    source_set = {str(item).strip() for item in (selected_sources or []) if str(item).strip()}

    same_source_candidates: list[tuple[Any, float, float]] = []
    if source_set:
        for doc, score in matched:
            if score is None:
                continue
            score_value = float(score)
            if score_value >= min_score:
                continue
            if score_value < DEFAULT_FALLBACK_MIN_SCORE:
                continue
            metadata = getattr(doc, "metadata", {}) or {}
            source = str(metadata.get("source") or metadata.get("url") or "").strip()
            if source in source_set:
                overlap = _keyword_overlap_ratio(
                    query_text, (getattr(doc, "page_content", "") or "")
                )
                same_source_candidates.append((doc, overlap, score_value))
        if same_source_candidates:
            same_source_candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
            return [doc for doc, _overlap, _score in same_source_candidates[:desired]]

    lower_bound = max(DEFAULT_FALLBACK_MIN_SCORE, float(min_score) - 0.12)

    candidates: list[tuple[Any, float, float]] = []
    for doc, score in matched:
        if score is None:
            continue
        score_value = float(score)
        if score_value >= min_score:
            continue
        if score_value < lower_bound:
            continue
        overlap = _keyword_overlap_ratio(query_text, (getattr(doc, "page_content", "") or ""))
        candidates.append((doc, overlap, score_value))

    if not candidates:
        return []

    candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
    ordered = candidates
    return [doc for doc, _overlap, _score in ordered[:desired]]


QUESTION_TAIL_RE = re.compile(
    r"(?:^|\n)\s*(?:#{2,4}\s*)?(?:Q\s*[:：]|问\s*[:：])?[^\n]*[?？]\s*$"
)
ANSWER_HEAD_RE = re.compile(r"^\s*(?:\*\*)?(?:A\s*[:：]|答\s*[:：])")


def _chunk_ends_on_question(text: str) -> bool:
    """True when a chunk trails off on a question with no answer body."""
    value = (text or "").strip()
    if not value:
        return False
    return bool(QUESTION_TAIL_RE.search(value))


def _chunk_starts_with_answer(text: str) -> bool:
    return bool(ANSWER_HEAD_RE.match((text or "").lstrip()))


def _select_answer_completion_docs(
    matched: list[tuple[Any, float | None]],
    *,
    selected_texts: list[str],
    max_extra_docs: int = 2,
) -> list[Any]:
    """Recover answers for selected chunks that end on a question heading.

    Markdown FAQ files chunked by size can place "### Q: ..." at the tail of
    one chunk and "**A:** ..." at the head of the next. The question chunk
    then scores highest for the user's query while containing no answer at
    all. This pulls in same-source candidates that begin with an answer.
    """
    if max_extra_docs <= 0 or not selected_texts:
        return []

    if not any(_chunk_ends_on_question(text) for text in selected_texts):
        return []

    selected_lookup = set(selected_texts)
    extras: list[Any] = []
    for doc, _score in matched:
        text = (getattr(doc, "page_content", "") or "").strip()
        if not text or text in selected_lookup:
            continue
        if not _chunk_starts_with_answer(text):
            continue
        extras.append(doc)
        selected_lookup.add(text)
        if len(extras) >= max_extra_docs:
            break
    return extras


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


def _build_llm(
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> ChatOpenAI:
    kwargs: dict[str, Any] = {"model": model, "temperature": 0}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
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


def _display_name(user: Any) -> str:
    """Public display name for a user.

    Always prefers the profile nickname over the internal username so that
    system accounts (bot_*) are never surfaced verbatim to end users.
    """
    if user is None:
        return "Unknown"
    nickname = str(getattr(user, "nickname", "") or "").strip()
    if nickname:
        return nickname
    username = str(getattr(user, "username", "") or "").strip()
    if not username:
        return "Unknown"
    if username.startswith("bot_"):
        # Fallback for a seeded account whose nickname is missing.
        return username[4:].replace("_", " ").title()
    return username


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
        author = _display_name(getattr(post, "author", None))
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

    author = _display_name(getattr(post, "author", None))
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
        user_name = _display_name(getattr(report, "user", None))
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


def _run_database_tool_use(
    question: str,
    llm: ChatOpenAI,
    max_tool_calls: int,
    reply_language: str = "en",
) -> tuple[str, list[str]]:
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
        ai_message = _invoke_llm_with_failure_logging(
            llm=tool_enabled_llm,
            model_kind=MODEL_KIND_QA,
            operation="database_tool_use.qa_tool_planner",
            messages=messages,
            metadata={"call_count": call_count, "call_budget": call_budget},
        )
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
        summary_response = _invoke_llm_with_failure_logging(
            llm=llm,
            model_kind=MODEL_KIND_QA,
            operation="database_tool_use.qa_summary",
            messages=[
                SystemMessage(
                    content=DATABASE_SUMMARY_PROMPT
                    + _reply_language_instruction(reply_language)
                ),
                HumanMessage(content=json.dumps(summary_payload, ensure_ascii=False)),
            ],
            metadata={"tool_results_count": len(executed_results)},
        )
        raw_answer = summary_response.content
        answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
        answer = answer.strip()
    except Exception:
        answer = ""

    if not answer:
        has_non_empty_result = any(item.get("result") for item in executed_results)
        if reply_language == "zh":
            answer = (
                DEFAULT_UNKNOWN_REPLY_ZH
                if has_non_empty_result
                else DEFAULT_DATABASE_EMPTY_REPLY_ZH
            )
        else:
            answer = (
                DEFAULT_UNKNOWN_REPLY_EN
                if has_non_empty_result
                else DEFAULT_DATABASE_EMPTY_REPLY_EN
            )

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
    def hard_kb_node(state: GraphState) -> GraphState:
        """Answer curated questions instantly, with zero model calls.

        A confident hard-KB hit short-circuits the whole pipeline: no intent
        classification, no retrieval, no generation. Clicking a suggestion
        chip always lands here because the chip text is the canonical
        question itself.
        """
        question = (state.get("question") or "").strip()
        if not question:
            return {}

        # "What can you do?" has its own purpose-built static answer that
        # also states the assistant's identity; do not shadow it here.
        if _looks_like_capability_question(question):
            return {}

        match = hard_kb.match_hard_kb(question)
        if match is None:
            return {}

        entry, score = match
        language = _detect_language(question)
        return {
            "answer": hard_kb.answer_for(entry, language),
            "sources": ["app://hard-kb/" + entry["id"]],
            "mode": INTENT_KNOWLEDGE_BASE,
            "intent": INTENT_KNOWLEDGE_BASE,
            "input_language": language,
            "original_question": question,
            "hard_kb_id": entry["id"],
            "hard_kb_score": round(float(score), 3),
            "quick_questions": hard_kb.suggested_questions(
                language, count=3, exclude_ids=(entry["id"],)
            ),
        }

    def route_after_hard_kb(state: GraphState) -> str:
        return END if state.get("hard_kb_id") else "preprocess_node"

    def preprocess_node(state: GraphState) -> GraphState:
        # No upfront translation: intent heuristics are bilingual, the QA
        # model answers natively in the user's language, and retrieval only
        # translates lazily when a first-pass search comes back empty. This
        # removes two LLM round-trips from the hot path.
        original_question = (state.get("question") or "").strip()
        page_context = _normalize_page_context_chunks(state.get("page_context", []))
        if not original_question:
            return {
                "question": "",
                "original_question": "",
                "input_language": "en",
                "page_context": page_context,
            }

        return {
            "question": original_question,
            "original_question": original_question,
            "input_language": _detect_language(original_question),
            "page_context": page_context,
        }

    def intent_node(state: GraphState) -> GraphState:
        question = (state.get("question") or "").strip()
        original_question = (state.get("original_question") or "").strip()
        page_context = _normalize_page_context_chunks(state.get("page_context", []))
        if page_context and (
            _looks_like_live_pool_decision_question(question)
            or _looks_like_live_pool_decision_question(original_question)
            or _looks_like_live_context_followup_question(question)
            or _looks_like_live_context_followup_question(original_question)
        ):
            return {"intent": INTENT_KNOWLEDGE_BASE}

        intent = _classify_intent(question, intent_llm)
        return {"intent": intent}

    def retrieve_node(state: GraphState) -> GraphState:
        question = (state.get("question") or "").strip()
        original_question = (state.get("original_question") or "").strip()
        input_language = str(state.get("input_language") or "en")
        intent = _normalize_intent(state.get("intent"))
        page_context = _normalize_page_context_chunks(state.get("page_context", []))
        retrieval_question = question or original_question
        if not retrieval_question:
            return {"mode": INTENT_FALLBACK, "context": [], "sources": []}

        if intent in {INTENT_SMALL_TALK, INTENT_DATABASE, INTENT_CAPABILITY, INTENT_FALLBACK}:
            return {"mode": intent, "context": [], "sources": []}

        is_backend_rules = _is_backend_rules_question(question) or _is_backend_rules_question(
            original_question
        )
        # CRITICAL: keep retrieved KB chunks in their OWN list. Live page
        # context is always present in production (homepage status lines), so
        # measuring retrieval quality on a merged list made every recovery
        # heuristic below permanently dead — the classic symptom being a KB
        # chunk that holds a "### Q:" heading whose "**A:**" landed in the
        # next chunk, answered with "I don't know". All thin-context checks
        # must therefore look at kb_context, never at the merged context.
        kb_context: list[str] = []
        sources: list[str] = ["app://homepage/live-status"] if page_context else []
        backend_priority_docs: list[Document] = []
        question_en = ""
        min_kb_chunks = min(2, max(1, top_k))

        if is_backend_rules:
            # Keep backend snapshots as fallback context for backend-rule questions.
            # Do not skip vector retrieval; KB chunks may hold the actual answer.
            backend_priority_docs = _load_backend_priority_docs(vector_store, top_k)

        matched = _search_with_optional_scores(vector_store, retrieval_question, top_k)

        # Second chance for non-English questions: when nothing clears the
        # score threshold, translate the query once (QA model, bounded) and
        # merge the English-query matches in. Most KB chunks are English, so
        # this recovers questions the multilingual embedding missed.
        #
        # Skipped for live status/decision questions that already carry page
        # context: those are answered from the live homepage signals, so an
        # extra translation round-trip would only add latency. This is a
        # narrow, question-type-based guard — NOT "page context exists",
        # which is what previously disabled every recovery path here.
        answered_from_live_context = bool(page_context) and (
            _looks_like_live_pool_decision_question(question)
            or _looks_like_live_pool_decision_question(original_question)
            or _looks_like_live_context_followup_question(question)
            or _looks_like_live_context_followup_question(original_question)
        )
        if input_language != "en" and not answered_from_live_context:
            has_confident_match = any(
                score is not None and score >= min_score for _doc, score in matched
            )
            if not has_confident_match:
                question_en = _translate_to_english(retrieval_question, llm, llm).strip()
                if question_en and question_en != retrieval_question:
                    seen_texts = {
                        (getattr(doc, "page_content", "") or "").strip()
                        for doc, _score in matched
                    }
                    for doc, score in _search_with_optional_scores(
                        vector_store, question_en, top_k
                    ):
                        text = (getattr(doc, "page_content", "") or "").strip()
                        if text in seen_texts:
                            continue
                        matched.append((doc, score))
                        seen_texts.add(text)

        for doc, score in matched:
            if score is not None and score < min_score:
                continue
            _append_doc_to_context(doc, kb_context, sources)

        # If thresholding leaves only a thin context, include a couple of
        # near-threshold chunks (prefer same source) to recover split Q/A pairs.
        if kb_context and len(kb_context) < min_kb_chunks:
            for doc in _select_near_threshold_support_docs(
                matched,
                min_score=min_score,
                top_k=top_k,
                selected_sources=sources,
                max_extra_docs=min(2, max(0, top_k - len(kb_context))),
                query_text=retrieval_question,
            ):
                _append_doc_to_context(doc, kb_context, sources)

        # If all candidates were filtered by score, keep only a narrow,
        # near-best subset to reduce noisy mixed context.
        if not kb_context and matched:
            for doc in _select_low_confidence_fallback_docs(
                matched,
                top_k=top_k,
                query_text=retrieval_question,
            ):
                _append_doc_to_context(doc, kb_context, sources)

        if kb_context and len(kb_context) < min_kb_chunks:
            for doc in _select_near_threshold_support_docs(
                matched,
                min_score=min_score,
                top_k=top_k,
                selected_sources=sources,
                max_extra_docs=min(2, max(0, top_k - len(kb_context))),
                query_text=retrieval_question,
            ):
                _append_doc_to_context(doc, kb_context, sources)

        # Adjacent-chunk repair: when a selected chunk ends on a question
        # heading with no answer body, pull in same-source neighbours that
        # start with an answer. Defends against any future chunking that
        # splits a Q/A pair, independent of the splitter used at sync time.
        if kb_context:
            for doc in _select_answer_completion_docs(
                matched,
                selected_texts=kb_context,
                max_extra_docs=2,
            ):
                _append_doc_to_context(doc, kb_context, sources)

        if not kb_context and backend_priority_docs:
            for doc in backend_priority_docs:
                _append_doc_to_context(doc, kb_context, sources)
                if len(kb_context) >= top_k:
                    break

        # Live page context first (it is the freshest, most specific signal),
        # then the retrieved knowledge chunks.
        context = list(page_context) + kb_context

        return {
            "mode": INTENT_KNOWLEDGE_BASE,
            "context": context,
            "sources": sources,
            "kb_chunks": len(kb_context),
            "question_en": question_en,
        }

    def generate_node(state: GraphState) -> GraphState:
        mode = _normalize_intent(state.get("mode"))
        question = (state.get("question") or "").strip()
        original_question = (state.get("original_question") or "").strip()
        input_language = str(state.get("input_language") or "en")
        # English retrieval query (if one was computed) ranks related FAQ
        # entries better than raw non-English text.
        faq_rank_question = (state.get("question_en") or "").strip() or question or original_question
        context_list = state.get("context", []) or []
        unknown_reply = _unknown_reply_for_question(original_question or question)
        language_line = _reply_language_instruction(input_language)

        if mode == INTENT_CAPABILITY:
            return {
                "answer": _capability_answer_for_language(input_language),
                "sources": [],
                "quick_questions": STARTER_QUICK_QUESTIONS_EN,
            }

        if mode == INTENT_SMALL_TALK:
            response = _invoke_llm_with_failure_logging(
                llm=llm,
                model_kind=MODEL_KIND_QA,
                operation="generate_answer.small_talk.qa",
                messages=[
                    SystemMessage(content=SMALL_TALK_SYSTEM_PROMPT + language_line),
                    HumanMessage(content=question),
                ],
                metadata={"mode": INTENT_SMALL_TALK},
            )
            raw_answer = response.content
            answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
            answer = answer.strip() or unknown_reply
            quick_questions: list[str] = []
            if answer == unknown_reply:
                quick_questions = _quick_questions_from_similar_context(
                    question=faq_rank_question,
                    context_chunks=[],
                    vector_store=vector_store,
                    llm=llm,
                    top_k=top_k,
                    min_score=min_score,
                    max_context_chars=max_context_chars,
                )
            return {
                "answer": answer,
                "sources": [],
                "quick_questions": quick_questions,
            }

        if mode == INTENT_DATABASE:
            try:
                answer, db_sources = _run_database_tool_use(
                    question=question,
                    llm=llm,
                    max_tool_calls=db_tool_max_calls,
                    reply_language=input_language,
                )
            except Exception:
                answer = _database_empty_reply_for_question(original_question or question)
                db_sources = []

            quick_questions: list[str] = []
            if answer in {
                DEFAULT_UNKNOWN_REPLY_EN,
                DEFAULT_UNKNOWN_REPLY_ZH,
                DEFAULT_DATABASE_EMPTY_REPLY_EN,
                DEFAULT_DATABASE_EMPTY_REPLY_ZH,
            }:
                quick_questions = _quick_questions_from_similar_context(
                    question=faq_rank_question,
                    context_chunks=[],
                    vector_store=vector_store,
                    llm=llm,
                    top_k=top_k,
                    min_score=min_score,
                    max_context_chars=max_context_chars,
                )
            return {
                "answer": answer,
                "sources": db_sources,
                "quick_questions": quick_questions,
            }

        if mode == INTENT_KNOWLEDGE_BASE:
            if not context_list:
                return {
                    "answer": unknown_reply,
                    "sources": [],
                    "quick_questions": _quick_questions_from_similar_context(
                        question=faq_rank_question,
                        context_chunks=[],
                        vector_store=vector_store,
                        llm=llm,
                        top_k=top_k,
                        min_score=min_score,
                        max_context_chars=max_context_chars,
                    ),
                }

            context_text = _truncate_context(context_list, max_context_chars)
            response = _invoke_llm_with_failure_logging(
                llm=llm,
                model_kind=MODEL_KIND_QA,
                operation="generate_answer.knowledge_base.qa",
                messages=[
                    SystemMessage(content=RAG_SYSTEM_PROMPT + language_line),
                    HumanMessage(
                        content=(
                            f"User question:\n{question}\n\n"
                            f"Reference context:\n{context_text}\n\n"
                            "Answer using only the reference context."
                        )
                    ),
                ],
                metadata={"mode": INTENT_KNOWLEDGE_BASE, "context_chunks": len(context_list)},
            )
            raw_answer = response.content
            answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
            answer = answer.strip() or unknown_reply
            quick_questions: list[str] = []
            if answer == unknown_reply:
                quick_questions = _quick_questions_from_similar_context(
                    question=faq_rank_question,
                    context_chunks=context_list,
                    vector_store=vector_store,
                    llm=llm,
                    top_k=top_k,
                    min_score=min_score,
                    max_context_chars=max_context_chars,
                )
            return {
                "answer": answer,
                "sources": state.get("sources", []),
                "quick_questions": quick_questions,
            }

        return {
            "answer": _fallback_reply_for_question(original_question or question),
            "sources": [],
            "quick_questions": _quick_questions_from_similar_context(
                question=faq_rank_question,
                context_chunks=context_list,
                vector_store=vector_store,
                llm=llm,
                top_k=top_k,
                min_score=min_score,
                max_context_chars=max_context_chars,
            ),
        }

    def localize_node(state: GraphState) -> GraphState:
        input_language = str(state.get("input_language") or "en")
        raw_answer = _extract_text_content(state.get("answer", ""))
        # Hard-KB answers already carry their suggestions and need no
        # localisation (they are stored per language).
        if state.get("hard_kb_id"):
            return {}
        answer = raw_answer or _unknown_reply_for_question(
            state.get("original_question") or ""
        )

        # Answers are generated directly in the user's language, so this is
        # only a safety net: translate when the model ignored the language
        # instruction (for example an English answer to a Chinese question).
        if (
            input_language != "en"
            and answer
            and _detect_language(answer) == "en"
        ):
            answer = _translate_from_english(answer, input_language, llm)

        base_quick_questions = _normalize_quick_questions(state.get("quick_questions", []))
        quick_questions = _translate_quick_questions(
            base_quick_questions,
            target_language=input_language,
            llm=llm,
        )
        if not quick_questions and input_language == "en":
            quick_questions = base_quick_questions

        # Every reply ends with three clickable suggestions drawn from the
        # hard KB, so the user always has a guided next step and each chip
        # resolves instantly on click.
        if len(quick_questions) < 3:
            for suggestion in hard_kb.suggested_questions(input_language, count=3):
                if suggestion not in quick_questions:
                    quick_questions.append(suggestion)
                if len(quick_questions) >= 3:
                    break

        return {
            "answer": answer,
            "quick_questions": quick_questions[:3],
        }

    graph = StateGraph(GraphState)
    graph.add_node("hard_kb_node", hard_kb_node)
    graph.add_node("preprocess_node", preprocess_node)
    graph.add_node("intent_node", intent_node)
    graph.add_node("retrieve_node", retrieve_node)
    graph.add_node("generate_node", generate_node)
    graph.add_node("localize_node", localize_node)
    graph.add_edge(START, "hard_kb_node")
    graph.add_conditional_edges(
        "hard_kb_node",
        route_after_hard_kb,
        {END: END, "preprocess_node": "preprocess_node"},
    )
    graph.add_edge("preprocess_node", "intent_node")
    graph.add_edge("intent_node", "retrieve_node")
    graph.add_edge("retrieve_node", "generate_node")
    graph.add_edge("generate_node", "localize_node")
    graph.add_edge("localize_node", END)
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
        llm = _build_llm(
            model=chat_model,
            api_key=openai_key,
            base_url=openai_base_url,
            timeout=45.0,
        )
        # The intent model is only a tie-breaker for ambiguous questions;
        # keep its latency strictly bounded so a slow/free-tier model can
        # never stall the whole conversation.
        intent_llm = _build_llm(
            model=intent_model,
            api_key=intent_api_key,
            base_url=intent_base_url,
            timeout=10.0,
            max_retries=1,
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
