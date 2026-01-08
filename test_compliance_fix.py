from app import create_app, db
from app.models import User, Group

app = create_app()

def test_compliance():
    with app.app_context():
        # Use in-memory DB for testing if possible, or just use the current config
        # Assuming dev config uses sqlite or similar. 
        # For safety, let's just inspect the models without committing if we can, 
        # or create tables if they don't exist.
        db.create_all()
        
        # 1. Test Group Creation & Relationship
        print("Testing Group Model...")
        u = User.query.filter_by(username='test_compliance_user').first()
        if not u:
            u = User(username='test_compliance_user', email='test@e.ntu.edu.sg', password='password')
            db.session.add(u)
        
        g = Group.query.filter_by(name='Test Group').first()
        if not g:
            g = Group(name='Test Group', created_by_id=u.id)
            db.session.add(g)
            
        if g not in u.groups:
            u.groups.append(g)
            
        db.session.commit()
        
        # Verify
        u_fresh = User.query.filter_by(username='test_compliance_user').first()
        print(f"User Groups: {u_fresh.groups.all()}")
        assert len(u_fresh.groups.all()) > 0
        print("✅ Group integration verified.")
        
        # 2. Test IAM Auth File Check
        print("Checking auth.py for uncommented verification email...")
        with open('app/blueprints/auth.py', 'r') as f:
            content = f.read()
            if '        send_verification_email(user)' in content and '# send_verification_email(user)' not in content:
                print("✅ Email Verification Enabled (Uncommented).")
            else:
                 # It might be indented. check for the line without #
                 lines = content.split('\n')
                 found = False
                 for line in lines:
                     if 'send_verification_email(user)' in line and '#' not in line.strip()[0:2]:
                         found = True
                         break
                 if found:
                     print("✅ Email Verification Enabled (Uncommented).")
                 else:
                     print("❌ Email Verification still commented out or missing.")

if __name__ == "__main__":
    test_compliance()
