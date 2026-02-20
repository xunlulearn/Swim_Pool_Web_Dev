import os
import sys
from pathlib import Path

# Ensure sample weather mode is enabled for local visual review.
os.environ["USE_SAMPLE_WEATHER_DATA"] = "true"
os.environ["FORCE_SAMPLE_WEATHER_DATA"] = "true"
os.environ.setdefault("FLASK_CONFIG", "development")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app, db
from app.models.user import User

app = create_app("development")
app.config["USE_SAMPLE_WEATHER_DATA"] = True
app.config["FORCE_SAMPLE_WEATHER_DATA"] = True
app.config["DEBUG"] = True


def setup_data():
    with app.app_context():
        db.create_all()
        user = User.query.filter_by(email="browser@e.ntu.edu.sg").first()
        if user is None:
            user = User(username="browser_agent", email="browser@e.ntu.edu.sg")
            db.session.add(user)

        user.password = "password123"
        user.is_verified = True
        db.session.commit()


if __name__ == "__main__":
    setup_data()
    print(
        "Sample server config:",
        f"USE_SAMPLE_WEATHER_DATA={app.config.get('USE_SAMPLE_WEATHER_DATA')}",
        f"DEBUG={app.config.get('DEBUG')}",
        flush=True,
    )
    app.run(host="127.0.0.1", port=5001, debug=True, use_reloader=False)
