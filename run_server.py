from app import create_app, db
from app.models.user import User

app = create_app()

def setup_data():
    with app.app_context():
        db.create_all()
        # Ensure a verified user exists for the browser agent to use
        if not User.query.filter_by(email='browser@e.ntu.edu.sg').first():
            u = User(username='browser_agent', email='browser@e.ntu.edu.sg', password='password')
            u.is_verified = True
            db.session.add(u)
            db.session.commit()
            print("Created browser test user.")

if __name__ == "__main__":
    setup_data()
    app.run(port=5000, debug=False)
