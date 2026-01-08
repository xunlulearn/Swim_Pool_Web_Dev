from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from app.models.report import PoolReport
from app.extensions import db
from datetime import datetime, timedelta

live_status_bp = Blueprint('live_status', __name__, url_prefix='/api/live-status')

@live_status_bp.route('/', methods=['GET'])
def get_reports():
    # Only show reports from last 24 hours to keep query light, 
    # but frontend will dim > 2 hours.
    since = datetime.utcnow() - timedelta(hours=24)
    reports = PoolReport.query.filter(PoolReport.created_at >= since)\
        .order_by(PoolReport.created_at.desc())\
        .limit(10).all()
    
    results = []
    for r in reports:
        # Calculate relative time string strictly for display if needed here, 
        # or just send ISO timestamp and let JS handle it (preferred)
        results.append(r.to_dict())
        
    return jsonify(results)

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
    
    return jsonify(report.to_dict()), 201
