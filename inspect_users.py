from app import create_app, db
from app.models.user import User

app = create_app()

def inspect_users():
    with app.app_context():
        users = User.query.all()
        print(f"Total Users: {len(users)}")
        for u in users:
            print(f"User: {u.username}, Email: {u.email}, Verified: {u.is_verified}")

if __name__ == "__main__":
    inspect_users()
