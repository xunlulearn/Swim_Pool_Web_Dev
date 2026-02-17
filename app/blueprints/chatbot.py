from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request
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
FEEDBACK_INTERVAL = 10
MAX_USER_AGENT_LENGTH = 500
DEFAULT_CHAT_LOG_TABLE = "chatbot_conversations"
DEFAULT_UNKNOWN_REPLY = (
    "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u65e0\u6cd5\u4ece\u5b98\u7f51\u5185\u5bb9\u4e2d"
    "\u786e\u8ba4\u8be5\u95ee\u9898\uff0c\u8bf7\u4ee5 ntupool.org \u7684\u6700\u65b0\u516c\u544a\u4e3a\u51c6\u3002"
)
DEFAULT_FEEDBACK_PROMPT = (
    "\u4f60\u5df2\u7d2f\u8ba1 10 \u6761\u5bf9\u8bdd\uff0c\u8bf7\u4e3a\u672c\u6b21\u56de\u7b54\u6253\u5206\uff081-5 \u661f\uff09\u3002"
)


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


def _save_chatbot_feedback(*, user_id: int, conversation_id: str, rating: int) -> None:
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

    update_payload = {
        "rating_score": rating,
        "rating_submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    update_response = (
        client.table(table_name)
        .update(update_payload)
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not (update_response.data or []):
        raise RuntimeError("Supabase update returned no rows.")


@chatbot_bp.route("/api/chat", methods=["POST"])
def chat():
    if not current_user.is_authenticated:
        return jsonify({"error": "Please log in to chat with the assistant.", "login_required": True}), 401

    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload, dict):
        return jsonify({"error": "Request JSON body is required."}), 400

    message = payload.get("message")
    if not isinstance(message, str):
        return jsonify({"error": "`message` must be a string."}), 400

    message = message.strip()
    if not message:
        return jsonify({"error": "`message` cannot be empty."}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"`message` cannot exceed {MAX_MESSAGE_LENGTH} characters."}), 400

    try:
        rag_app = get_rag_app(
            top_k=current_app.config.get("CHATBOT_TOP_K"),
            min_score=current_app.config.get("CHATBOT_MIN_SCORE"),
            max_context_chars=current_app.config.get("CHATBOT_MAX_CONTEXT_CHARS"),
        )
        result = rag_app.invoke({"question": message})
    except ChatbotConfigError as exc:
        current_app.logger.warning("Chatbot configuration error: %s", exc)
        return jsonify({"error": "Chatbot is not configured."}), 503
    except Exception:
        current_app.logger.exception("Unexpected error in /api/chat.")
        return jsonify({"error": "Internal chatbot error."}), 500

    reply = result.get("answer") if isinstance(result, dict) else None
    if not isinstance(reply, str) or not reply.strip():
        reply = DEFAULT_UNKNOWN_REPLY
    else:
        reply = reply.strip()

    sources = _normalize_sources(result.get("sources", []) if isinstance(result, dict) else [])

    try:
        log_record = _persist_chatbot_exchange(
            user_id=current_user.id,
            message=message,
            reply=reply,
            sources=sources,
        )
    except ChatbotConfigError as exc:
        current_app.logger.warning("Chatbot logging configuration error: %s", exc)
        return jsonify({"error": "Chatbot is not configured."}), 503
    except Exception:
        current_app.logger.exception("Unexpected error while persisting chatbot conversation.")
        return jsonify({"error": "Failed to save chatbot conversation."}), 500

    response_payload = {
        "reply": reply,
        "sources": sources,
        "conversation_id": log_record["conversation_id"],
        "message_counter": log_record["message_counter"],
        "feedback_required": log_record["feedback_required"],
    }
    if log_record["feedback_required"]:
        response_payload["feedback_prompt"] = DEFAULT_FEEDBACK_PROMPT

    return jsonify(response_payload), 200


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

    try:
        _save_chatbot_feedback(
            user_id=current_user.id,
            conversation_id=conversation_id,
            rating=rating,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except ChatbotConfigError as exc:
        current_app.logger.warning("Chatbot feedback configuration error: %s", exc)
        return jsonify({"error": "Chatbot is not configured."}), 503
    except Exception:
        current_app.logger.exception("Unexpected error while saving chatbot feedback.")
        return jsonify({"error": "Failed to save chatbot feedback."}), 500

    return jsonify({"ok": True, "conversation_id": conversation_id, "rating": rating}), 200
