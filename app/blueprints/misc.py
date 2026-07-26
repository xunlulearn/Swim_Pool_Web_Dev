from flask import Blueprint, jsonify

misc_bp = Blueprint('misc', __name__)

@misc_bp.route('/locker')
def locker():
    return "Locker Status"


@misc_bp.route('/api/chatbot-selftest/latest')
def chatbot_selftest_latest():
    """Public read-only report of the most recent chatbot self-test run.

    Contains only the curated test questions, routing diagnostics, and
    answers — no user data or secrets — so it is safe to expose for
    external verification and regression analysis.
    """
    from app.services.chatbot.selftest import latest_selftest_report

    report = latest_selftest_report()
    if report is None:
        response = jsonify({'status': 'no_runs_yet'})
    else:
        response = jsonify(report)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Robots-Tag'] = 'noindex'
    return response
