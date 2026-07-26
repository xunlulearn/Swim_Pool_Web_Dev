from collections import deque
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
import json
import re
import time
from uuid import UUID

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from flask_login import current_user

try:
    from supabase import create_client
except Exception:  # pragma: no cover - dependency may be missing in lightweight test env
    create_client = None

try:
    from app.services.chatbot import ChatbotConfigError, get_rag_app
except Exception as import_error:
    class ChatbotConfigError(RuntimeError):
        pass

    def get_rag_app(*_args, **_kwargs):
        raise ChatbotConfigError(f"Chatbot dependencies are unavailable: {import_error}")


chatbot_bp = Blueprint("chatbot", __name__)

MAX_MESSAGE_LENGTH = 2000
FEEDBACK_INTERVAL = 5
MAX_USER_AGENT_LENGTH = 500
MAX_FEEDBACK_COMMENT_LENGTH = 500
MAX_PAGE_CONTEXT_ITEMS = 12
MAX_PAGE_CONTEXT_ITEM_LENGTH = 500
DEFAULT_CHAT_LOG_TABLE = "chatbot_conversations"
DEFAULT_UNKNOWN_REPLY = (
    "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u65e0\u6cd5\u4ece\u5b98\u7f51\u5185\u5bb9\u4e2d"
    "\u786e\u8ba4\u8be5\u95ee\u9898\uff0c\u8bf7\u4ee5 ntupool.org \u7684\u6700\u65b0\u516c\u544a\u4e3a\u51c6\u3002"
)
DEFAULT_FEEDBACK_PROMPT = (
    "\u8bf7\u60a8\u5bf9\u6211\u8fdb\u884c\u6ee1\u610f\u5ea6\u8bc4\u5206\uff0c\u5e2e\u52a9\u6211\u4ee5\u540e\u53d8\u5f97\u66f4\u52a0\u806a\u660e\u3002"
)


RATE_LIMIT_ERROR = (
    "You are sending messages too quickly. Please wait a moment and try again. "
    "发送得太快啦，请稍等一下再试。"
)
DAILY_LIMIT_ERROR = (
    "You have reached today's chat limit. Please come back tomorrow. "
    "今天的对话次数已用完，请明天再来。"
)

_rate_lock = Lock()
_rate_buckets: dict[int, deque] = {}


def _check_burst_limit(user_id: int) -> bool:
    """Best-effort in-memory sliding window (per serverless instance)."""
    try:
        limit = int(current_app.config.get("CHATBOT_BURST_LIMIT_PER_MINUTE") or 8)
    except (TypeError, ValueError):
        limit = 8
    if limit <= 0:
        return True

    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets.setdefault(user_id, deque())
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        # Keep the map from growing without bound.
        if len(_rate_buckets) > 2000:
            stale = [
                key for key, values in _rate_buckets.items()
                if not values or now - values[-1] > 300
            ]
            for key in stale:
                _rate_buckets.pop(key, None)
    return True


def _check_daily_limit(user_id: int) -> bool:
    """Cap per-user daily messages via the Supabase conversation log.

    Fails open: if the query cannot run (network, missing column), the
    message is allowed rather than blocking the user.
    """
    try:
        limit = int(current_app.config.get("CHATBOT_DAILY_MESSAGE_LIMIT") or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return True

    try:
        client = _get_supabase_client()
        day_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        response = (
            client.table(_get_chat_log_table_name())
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("created_at", day_start.isoformat())
            .limit(1)
            .execute()
        )
        return int(response.count or 0) < limit
    except Exception:
        current_app.logger.warning(
            "Chatbot daily-limit check failed; allowing message.", exc_info=True
        )
        return True


def _rate_limit_error_response():
    return jsonify({"error": RATE_LIMIT_ERROR, "rate_limited": True}), 429


def _daily_limit_error_response():
    return jsonify({"error": DAILY_LIMIT_ERROR, "rate_limited": True}), 429


@lru_cache(maxsize=1)
def _get_cached_supabase_client(supabase_url: str, service_role_key: str):
    return create_client(supabase_url, service_role_key)


def _get_chat_log_table_name() -> str:
    return current_app.config.get("SUPABASE_CHAT_LOG_TABLE") or DEFAULT_CHAT_LOG_TABLE


def _get_supabase_client():
    if create_client is None:
        raise ChatbotConfigError("Supabase client dependency is unavailable.")
    supabase_url = current_app.config.get("SUPABASE_URL")
    service_role_key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        raise ChatbotConfigError("Missing Supabase credentials for chatbot logging.")
    return _get_cached_supabase_client(supabase_url, service_role_key)


def _normalize_sources(raw_sources) -> list[str]:
    if not isinstance(raw_sources, list):
        return []

    sources: list[str] = []
    for item in raw_sources:
        if not isinstance(item, str):
            continue
        source = item.strip()
        if source:
            sources.append(source)
    return sources


def _normalize_quick_questions(raw_values) -> list[str]:
    if not isinstance(raw_values, list):
        return []

    def _looks_like_question(value: str) -> bool:
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

    values: list[str] = []
    for item in raw_values:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in values:
            continue
        if not _looks_like_question(text):
            continue
        values.append(text)
        if len(values) >= 3:
            break
    return values


def _parse_conversation_id(raw_value):
    if not isinstance(raw_value, str):
        return None
    conversation_id = raw_value.strip()
    if not conversation_id:
        return None
    try:
        return str(UUID(conversation_id))
    except ValueError:
        return None


def _extract_message_from_request():
    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload, dict):
        return "", ("Request JSON body is required.", 400)

    message = payload.get("message")
    if not isinstance(message, str):
        return "", ("`message` must be a string.", 400)

    message = message.strip()
    if not message:
        return "", ("`message` cannot be empty.", 400)
    if len(message) > MAX_MESSAGE_LENGTH:
        return "", (f"`message` cannot exceed {MAX_MESSAGE_LENGTH} characters.", 400)
    return message, None


def _append_context_line(lines: list[str], text: str) -> None:
    value = str(text or "").strip()
    if not value:
        return
    if len(value) > MAX_PAGE_CONTEXT_ITEM_LENGTH:
        value = value[: MAX_PAGE_CONTEXT_ITEM_LENGTH - 1] + "..."
    if value not in lines and len(lines) < MAX_PAGE_CONTEXT_ITEMS:
        lines.append(value)


def _normalize_client_page_context(raw_context) -> list[str]:
    lines: list[str] = []
    if isinstance(raw_context, str):
        _append_context_line(lines, raw_context)
        return lines
    if isinstance(raw_context, list):
        for item in raw_context:
            if isinstance(item, str):
                _append_context_line(lines, item)
        return lines
    if not isinstance(raw_context, dict):
        return lines

    selected_radius = str(raw_context.get("selected_lightning_radius") or "").strip()
    selected_window = str(raw_context.get("selected_lightning_window") or "").strip()
    if selected_radius or selected_window:
        _append_context_line(
            lines,
            (
                "User is viewing lightning trend filters: "
                f"radius={selected_radius or 'unknown'}, window={selected_window or 'unknown'}."
            ),
        )

    for key in ("status_text", "status_message", "nearest_lightning", "lightning_count", "rainfall"):
        value = raw_context.get(key)
        if isinstance(value, str) and value.strip():
            label = key.replace("_", " ").title()
            _append_context_line(lines, f"Visible homepage {label}: {value.strip()}.")

    trend_summary = raw_context.get("lightning_trend_summary")
    if isinstance(trend_summary, str) and trend_summary.strip():
        _append_context_line(lines, f"Visible lightning trend summary: {trend_summary.strip()}.")

    return lines


def _format_metric(value, fallback: str = "unknown") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _first_present(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _chart_total(window_data: dict, key: str) -> int:
    totals = window_data.get("totals") if isinstance(window_data, dict) else {}
    if isinstance(totals, dict) and key in totals:
        try:
            return int(round(float(totals[key] or 0)))
        except (TypeError, ValueError):
            return 0
    series_key = f"counts_{key}"
    values = window_data.get(series_key, []) if isinstance(window_data, dict) else []
    if not isinstance(values, list):
        return 0
    total = 0
    for value in values:
        try:
            total += int(round(float(value or 0)))
        except (TypeError, ValueError):
            continue
    return total


def _summarize_lightning_history(history_payload: dict) -> list[str]:
    if not isinstance(history_payload, dict):
        return []

    lines: list[str] = []
    observation_time = history_payload.get("observation_time_sgt")
    if observation_time:
        _append_context_line(lines, f"Lightning trend observation time (SGT): {observation_time}.")

    charts = history_payload.get("charts")
    if isinstance(charts, dict):
        for window_key in ("20m", "1h", "12h"):
            window_data = charts.get(window_key)
            if not isinstance(window_data, dict):
                continue
            label = window_data.get("display_label") or window_key
            total_15 = _chart_total(window_data, "15km")
            total_30 = _chart_total(window_data, "30km")
            _append_context_line(
                lines,
                (
                    "Lightning trend chart total for "
                    f"{label}: <=15 km {total_15} strikes, <=30 km {total_30} strikes."
                ),
            )

    metadata = history_payload.get("metadata")
    if isinstance(metadata, dict):
        warning = metadata.get("warning") or metadata.get("error")
        if warning:
            _append_context_line(lines, f"Lightning trend data note: {warning}.")
    return lines


def _build_homepage_context(client_page_context=None) -> list[str]:
    lines: list[str] = []
    try:
        from app.services.weather_engine import weather_engine

        state, message, details = weather_engine.get_overall_status()
        details = details if isinstance(details, dict) else {}
        _append_context_line(
            lines,
            (
                "Current homepage pool status: "
                f"{getattr(state, 'name', state)} ({getattr(state, 'value', state)}). "
                f"Message: {message}"
            ),
        )
        _append_context_line(
            lines,
            (
                "Decision guide: GREEN/OPEN means going is generally reasonable if onsite "
                "lifeguards allow it; AMBER/WARNING means use caution and keep monitoring; "
                "RED/CLOSED means do not enter the water, and users already at the pool "
                "should leave the water and follow lifeguard instructions."
            ),
        )
        _append_context_line(
            lines,
            (
                "Lightning trend safety guide: if the lightning trend worsens, the chart "
                "turns red, or lightning appears within 15 km, users at the pool should "
                "leave the water immediately and follow lifeguard instructions; users "
                "planning to go should wait and keep monitoring until conditions are safe."
            ),
        )
        _append_context_line(
            lines,
            (
                "Future visit guide: for a trip in the next 30 minutes, watch the homepage "
                "pool status, nearest lightning distance, lightning count, 20-minute and "
                "1-hour lightning trend totals for 15 km and 30 km, and rainfall rate before "
                "leaving for the pool."
            ),
        )
        _append_context_line(
            lines,
            (
                "Current weather metrics: "
                f"nearest lightning={_format_metric(_first_present(details.get('min_distance_km'), details.get('lightning_dist')))} km; "
                f"lightning count={_format_metric(details.get('lightning_count'))}; "
                f"rainfall={_format_metric(details.get('rainfall_rate'))} mm/h; "
                f"observation time SGT={_format_metric(details.get('observation_time_sgt'))}."
            ),
        )
        data_note = details.get("lightning_warning") or details.get("source_error")
        if data_note:
            _append_context_line(lines, f"Current weather data note: {data_note}.")

        for history_line in _summarize_lightning_history(weather_engine.get_lightning_history()):
            _append_context_line(lines, history_line)
    except Exception:
        current_app.logger.exception("Failed to build homepage context for chatbot.")

    for line in _normalize_client_page_context(client_page_context):
        _append_context_line(lines, line)
    return lines


def _build_chat_response_payload(message: str, client_page_context=None):
    try:
        rag_app = get_rag_app(
            top_k=current_app.config.get("CHATBOT_TOP_K"),
            min_score=current_app.config.get("CHATBOT_MIN_SCORE"),
            max_context_chars=current_app.config.get("CHATBOT_MAX_CONTEXT_CHARS"),
        )
        result = rag_app.invoke(
            {
                "question": message,
                "page_context": _build_homepage_context(client_page_context),
            }
        )
    except ChatbotConfigError as exc:
        current_app.logger.warning("Chatbot configuration error: %s", exc)
        return None, ("Chatbot is not configured.", 503)
    except Exception:
        current_app.logger.exception("Unexpected error in /api/chat.")
        return None, ("Internal chatbot error.", 500)

    reply = result.get("answer") if isinstance(result, dict) else None
    if not isinstance(reply, str) or not reply.strip():
        reply = DEFAULT_UNKNOWN_REPLY
    else:
        reply = reply.strip()

    sources = _normalize_sources(result.get("sources", []) if isinstance(result, dict) else [])
    quick_questions = _normalize_quick_questions(
        result.get("quick_questions", []) if isinstance(result, dict) else []
    )

    try:
        log_record = _persist_chatbot_exchange(
            user_id=current_user.id,
            message=message,
            reply=reply,
            sources=sources,
        )
    except ChatbotConfigError as exc:
        current_app.logger.warning("Chatbot logging configuration error: %s", exc)
        return None, ("Chatbot is not configured.", 503)
    except Exception:
        current_app.logger.exception("Unexpected error while persisting chatbot conversation.")
        return None, ("Failed to save chatbot conversation.", 500)

    response_payload = {
        "reply": reply,
        "sources": sources,
        "conversation_id": log_record["conversation_id"],
        "message_counter": log_record["message_counter"],
        "feedback_required": log_record["feedback_required"],
        "quick_questions": quick_questions,
    }
    if log_record["feedback_required"]:
        response_payload["feedback_prompt"] = DEFAULT_FEEDBACK_PROMPT
    return response_payload, None


def _iter_reply_chunks(text: str, *, chunk_size: int = 24):
    normalized = (text or "").strip()
    if not normalized:
        return
    start = 0
    step = max(1, int(chunk_size))
    while start < len(normalized):
        end = min(start + step, len(normalized))
        yield normalized[start:end]
        start = end


def _stream_event(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _persist_chatbot_exchange(*, user_id: int, message: str, reply: str, sources: list[str]) -> dict:
    client = _get_supabase_client()
    table_name = _get_chat_log_table_name()

    count_response = (
        client.table(table_name)
        .select("id", count="exact")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    message_counter = int(count_response.count or 0) + 1
    feedback_required = message_counter % FEEDBACK_INTERVAL == 0

    user_agent = (request.headers.get("User-Agent") or "").strip()
    if len(user_agent) > MAX_USER_AGENT_LENGTH:
        user_agent = user_agent[:MAX_USER_AGENT_LENGTH]

    insert_payload = {
        "user_id": user_id,
        "user_message": message,
        "assistant_message": reply,
        "sources": sources,
        "message_counter": message_counter,
        "feedback_requested": feedback_required,
        "request_ip": request.remote_addr,
        "user_agent": user_agent,
    }
    insert_response = client.table(table_name).insert(insert_payload).execute()
    rows = insert_response.data or []
    if not rows:
        raise RuntimeError("Supabase insert returned no rows.")

    conversation_id = rows[0].get("id")
    if not conversation_id:
        raise RuntimeError("Supabase insert did not return conversation id.")

    return {
        "conversation_id": conversation_id,
        "message_counter": message_counter,
        "feedback_required": feedback_required,
    }


def _save_chatbot_feedback(
    *, user_id: int, conversation_id: str, rating: int, comment: str
) -> None:
    client = _get_supabase_client()
    table_name = _get_chat_log_table_name()

    lookup_response = (
        client.table(table_name)
        .select("id, feedback_requested, rating_score")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = lookup_response.data or []
    if not rows:
        raise ValueError("Conversation record not found.")

    row = rows[0]
    if not row.get("feedback_requested"):
        raise ValueError("This answer does not require feedback yet.")
    if row.get("rating_score") is not None:
        raise ValueError("Rating has already been submitted.")

    update_payload: dict[str, object] = {
        "rating_score": rating,
        "rating_submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if comment:
        update_payload["rating_comment"] = comment

    def _run_update(payload: dict[str, object]):
        return (
            client.table(table_name)
            .update(payload)
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .execute()
        )

    try:
        update_response = _run_update(update_payload)
    except Exception:
        # Keep rating flow working even before schema migration adds rating_comment.
        if "rating_comment" not in update_payload:
            raise
        fallback_payload = dict(update_payload)
        fallback_payload.pop("rating_comment", None)
        current_app.logger.warning(
            "chatbot_conversations.rating_comment column is unavailable; saved score without text."
        )
        update_response = _run_update(fallback_payload)

    if not (update_response.data or []):
        raise RuntimeError("Supabase update returned no rows.")


@chatbot_bp.route("/api/chat", methods=["POST"])
def chat():
    if not current_user.is_authenticated:
        return jsonify({"error": "Please log in to chat with the assistant.", "login_required": True}), 401

    message, validation_error = _extract_message_from_request()
    if validation_error is not None:
        error_text, status_code = validation_error
        return jsonify({"error": error_text}), status_code

    if not _check_burst_limit(current_user.id):
        return _rate_limit_error_response()
    if not _check_daily_limit(current_user.id):
        return _daily_limit_error_response()

    payload = request.get_json(silent=True) or {}
    response_payload, error = _build_chat_response_payload(
        message,
        payload.get("page_context") if isinstance(payload, dict) else None,
    )
    if error is not None:
        error_text, status_code = error
        return jsonify({"error": error_text}), status_code
    return jsonify(response_payload), 200


@chatbot_bp.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    if not current_user.is_authenticated:
        return jsonify({"error": "Please log in to chat with the assistant.", "login_required": True}), 401

    message, validation_error = _extract_message_from_request()
    if validation_error is not None:
        error_text, status_code = validation_error
        return jsonify({"error": error_text}), status_code

    if not _check_burst_limit(current_user.id):
        return _rate_limit_error_response()
    if not _check_daily_limit(current_user.id):
        return _daily_limit_error_response()

    def generate_stream():
        # Emit a first frame immediately so the client can show active progress.
        yield _stream_event({"type": "status", "stage": "thinking"})

        payload = request.get_json(silent=True) or {}
        response_payload, error = _build_chat_response_payload(
            message,
            payload.get("page_context") if isinstance(payload, dict) else None,
        )
        if error is not None:
            error_text, status_code = error
            yield _stream_event({"type": "error", "error": error_text, "status_code": status_code})
            return

        yield _stream_event({"type": "status", "stage": "typing"})
        for chunk in _iter_reply_chunks(response_payload.get("reply", "")):
            yield _stream_event({"type": "delta", "delta": chunk})
            # Keep chunks visibly progressive for the user instead of bursting all at once.
            time.sleep(0.018)

        final_payload = dict(response_payload)
        final_payload["type"] = "final"
        yield _stream_event(final_payload)

    return Response(
        stream_with_context(generate_stream()),
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Prevent reverse proxies from buffering stream chunks.
            "X-Accel-Buffering": "no",
        },
    )


@chatbot_bp.route("/api/chat/feedback", methods=["POST"])
def submit_feedback():
    if not current_user.is_authenticated:
        return jsonify({"error": "Please log in to submit feedback.", "login_required": True}), 401

    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload, dict):
        return jsonify({"error": "Request JSON body is required."}), 400

    conversation_id = _parse_conversation_id(payload.get("conversation_id"))
    if not conversation_id:
        return jsonify({"error": "`conversation_id` must be a valid UUID string."}), 400

    raw_rating = payload.get("rating")
    try:
        rating = int(raw_rating)
    except (TypeError, ValueError):
        return jsonify({"error": "`rating` must be an integer between 1 and 5."}), 400
    if rating < 1 or rating > 5:
        return jsonify({"error": "`rating` must be between 1 and 5."}), 400

    raw_comment = payload.get("comment", "")
    if raw_comment is None:
        comment = ""
    elif isinstance(raw_comment, str):
        comment = raw_comment.strip()
    else:
        return jsonify({"error": "`comment` must be a string."}), 400

    if len(comment) > MAX_FEEDBACK_COMMENT_LENGTH:
        return jsonify(
            {"error": f"`comment` cannot exceed {MAX_FEEDBACK_COMMENT_LENGTH} characters."}
        ), 400

    try:
        _save_chatbot_feedback(
            user_id=current_user.id,
            conversation_id=conversation_id,
            rating=rating,
            comment=comment,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except ChatbotConfigError as exc:
        current_app.logger.warning("Chatbot feedback configuration error: %s", exc)
        return jsonify({"error": "Chatbot is not configured."}), 503
    except Exception:
        current_app.logger.exception("Unexpected error while saving chatbot feedback.")
        return jsonify({"error": "Failed to save chatbot feedback."}), 500

    return jsonify(
        {"ok": True, "conversation_id": conversation_id, "rating": rating, "comment": comment}
    ), 200
