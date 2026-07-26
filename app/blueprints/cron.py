import hmac

from flask import Blueprint, current_app, jsonify, request

from app.services.weather_engine import weather_engine
from app.services.community_bot import run_community_post_tick

cron_bp = Blueprint("cron", __name__, url_prefix="/api/cron")


def _request_secret():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ").strip()
    return request.args.get("secret", "").strip()


def _is_valid_cron_secret():
    expected = str(current_app.config.get("CRON_SECRET") or "").strip()
    supplied = _request_secret()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(expected, supplied)


@cron_bp.get("/collect-lightning")
def collect_lightning():
    if not _is_valid_cron_secret():
        return jsonify({"error": "Not found."}), 404

    result = weather_engine.collect_and_store_latest_lightning_snapshot()
    if not result.get("ok"):
        return jsonify({"ok": False, "reason": result.get("reason")}), 502

    return jsonify({"ok": True})


@cron_bp.get("/community-posts")
def community_posts():
    if not _is_valid_cron_secret():
        return jsonify({"error": "Not found."}), 404

    result = run_community_post_tick()
    return jsonify(result)


@cron_bp.get("/chatbot-selftest")
def chatbot_selftest():
    """Run ONE question of the chatbot self-test battery.

    Called in a loop by the chatbot-selftest GitHub Actions workflow with
    ?run=<key>&index=<n>, keeping each serverless request short. Results
    accumulate in chatbot_selftest_runs and are readable at the public
    /api/chatbot-selftest/latest endpoint.
    """
    if not _is_valid_cron_secret():
        return jsonify({"error": "Not found."}), 404

    from app.services.chatbot.selftest import run_selftest_question, selftest_total

    run_key = (request.args.get("run") or "").strip()[:80]
    if not run_key:
        return jsonify({"ok": False, "error": "`run` query param is required."}), 400

    try:
        index = int(request.args.get("index", ""))
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "`index` query param is required.",
            "total": selftest_total(),
        }), 400

    result = run_selftest_question(run_key, index)
    status_code = 200 if result.get("ok") or "index" in result else 400
    return jsonify(result), status_code
