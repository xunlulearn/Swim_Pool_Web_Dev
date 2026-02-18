from datetime import datetime, timezone
from threading import Lock

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required, current_user
from app.models.report import PoolReport
from app.extensions import db

live_status_bp = Blueprint('live_status', __name__, url_prefix='/api/live-status')
_report_cache = None
_report_cache_at = None
_report_cache_lock = Lock()


def _get_cache_ttl_seconds():
    try:
        return int(current_app.config.get('LIVE_STATUS_CACHE_SECONDS', 30))
    except (TypeError, ValueError):
        return 30


def _get_cached_reports(*, allow_stale=False):
    ttl_seconds = _get_cache_ttl_seconds()
    with _report_cache_lock:
        if _report_cache is None:
            return None
        if allow_stale:
            return list(_report_cache)
        if ttl_seconds <= 0 or _report_cache_at is None:
            return None
        age = (datetime.now(timezone.utc) - _report_cache_at).total_seconds()
        if age > ttl_seconds:
            return None
        return list(_report_cache)


def _set_cached_reports(rows):
    global _report_cache
    global _report_cache_at
    with _report_cache_lock:
        _report_cache = list(rows)
        _report_cache_at = datetime.now(timezone.utc)


def _invalidate_cache():
    global _report_cache
    global _report_cache_at
    with _report_cache_lock:
        _report_cache = None
        _report_cache_at = None

@live_status_bp.route('/', methods=['GET'])
def get_reports():
    # Always show the latest 10 reports on the homepage feed.
    cached = _get_cached_reports()
    if cached is not None:
        return jsonify(cached)

    try:
        reports = (
            PoolReport.query
            .order_by(PoolReport.created_at.desc())
            .limit(10)
            .all()
        )

        results = []
        for r in reports:
            # Calculate relative time string strictly for display if needed here,
            # or just send ISO timestamp and let JS handle it (preferred)
            results.append(r.to_dict())
        _set_cached_reports(results)
        return jsonify(results)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to load live-status reports.")
        stale = _get_cached_reports(allow_stale=True)
        if stale is not None:
            return jsonify(stale)
        return jsonify([])

@live_status_bp.route('/', methods=['POST'])
@login_required
def submit_report():
    if not current_user.is_verified:
        return jsonify({"error": "Verified account required"}), 403
        
    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({"error": "Invalid data"}), 400
        
    status = data['status']
    if status not in ['Open', 'Closed']:
        return jsonify({"error": "Invalid status value"}), 400
        
    # Rate limit check (optional/simple): prevent spam
    # existing_report = PoolReport.query.filter_by(user_id=current_user.id)...
    # For now, just allow.
    
    report = PoolReport(status=status, user_id=current_user.id)
    db.session.add(report)
    db.session.commit()
    _invalidate_cache()
    
    return jsonify(report.to_dict()), 201
