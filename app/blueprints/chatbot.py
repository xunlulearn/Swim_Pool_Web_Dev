from flask import Blueprint, current_app, jsonify, request

try:
    from app.services.chatbot import ChatbotConfigError, get_rag_app
except Exception as import_error:
    class ChatbotConfigError(RuntimeError):
        pass

    def get_rag_app(*_args, **_kwargs):
        raise ChatbotConfigError(f"Chatbot dependencies are unavailable: {import_error}")


chatbot_bp = Blueprint("chatbot", __name__)

MAX_MESSAGE_LENGTH = 2000
DEFAULT_UNKNOWN_REPLY = (
    "\u62b1\u6b49\uff0c\u6211\u6682\u65f6\u65e0\u6cd5\u4ece\u5b98\u7f51\u5185\u5bb9\u4e2d"
    "\u786e\u8ba4\u8be5\u95ee\u9898\uff0c\u8bf7\u4ee5 ntupool.org \u7684\u6700\u65b0\u516c\u544a\u4e3a\u51c6\u3002"
)


@chatbot_bp.route("/api/chat", methods=["POST"])
def chat():
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

    sources = result.get("sources", []) if isinstance(result, dict) else []
    if not isinstance(sources, list):
        sources = []

    return jsonify({"reply": reply, "sources": sources}), 200
