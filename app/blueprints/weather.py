from flask import Blueprint, jsonify

weather_bp = Blueprint('weather', __name__, url_prefix='/weather')

from app.services.weather_engine import weather_engine

@weather_bp.route('/status')
def status():
    state, message, details = weather_engine.get_overall_status()

    response = jsonify({
        "status": state.name, # "RED", "GREEN", "AMBER"
        "display_text": state.value, # "Closed", "Open", "Warning"
        "message": message,
        "details": details,
        "data_source": details.get("data_source", "live_api"),
        "disclaimer": "Data has 1-3 min delay; actual status subject to lifeguard instruction."
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
