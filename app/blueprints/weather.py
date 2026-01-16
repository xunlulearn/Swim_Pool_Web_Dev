from flask import Blueprint, jsonify

weather_bp = Blueprint('weather', __name__, url_prefix='/weather')

from app.services.weather_engine import weather_engine

@weather_bp.route('/status')
def status():
    state, message, details = weather_engine.get_overall_status()
    
    return jsonify({
        "status": state.name, # "RED", "GREEN", "AMBER"
        "display_text": state.value, # "Closed", "Open", "Warning"
        "message": message,
        "details": details,
        "disclaimer": "Data has 1-3 min delay; actual status subject to lifeguard instruction."
    })
