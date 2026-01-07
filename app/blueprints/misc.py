from flask import Blueprint

misc_bp = Blueprint('misc', __name__)

@misc_bp.route('/locker')
def locker():
    return "Locker Status"
