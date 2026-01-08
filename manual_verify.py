from app import create_app, db
from app.models.user import User

app = create_app()

def verify_all():
    with app.app_context():
        # Verify liti specifically, or just all unverified for dev convenience
        users = User.query.filter_by(is_verified=False).all()
        for u in users:
            u.is_verified = True
            print(f"Manually verifying user: {u.username}")
        
        db.session.commit()
        print("All users verified.")

if __name__ == "__main__":
    verify_all()
