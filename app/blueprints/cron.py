import hmac

from flask import Blueprint, current_app, jsonify, request

from app.services.weather_engine import weather_engine

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
