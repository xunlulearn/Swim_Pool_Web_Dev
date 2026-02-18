from app import create_app, db
from app.models.user import User

app = create_app()

def setup_data():
    with app.app_context():
        db.create_all()
        # Ensure a verified test user exists and always has a known password.
        user = User.query.filter_by(email='browser@e.ntu.edu.sg').first()
        if user is None:
            user = User(username='browser_agent', email='browser@e.ntu.edu.sg')
            db.session.add(user)

        user.password = 'password123'
        user.is_verified = True
        db.session.commit()
        print("Ensured browser test user: browser@e.ntu.edu.sg / password123")

if __name__ == "__main__":
    setup_data()
    app.run(port=5001, debug=True)
