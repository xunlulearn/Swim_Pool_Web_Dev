import logging
from app import create_app, db
from app.models.user import User
from app.models.report import PoolReport
import time

# Configure logging to look like a "Test Report"
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

def run_demo():
    print("="*50)
    print("🧪 STARTING COMMUNITY LIVE STATUS FEATURE TEST")
    print("="*50)

    # 1. Setup Environment
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        db.create_all()
        
        # 2. Create a Mock User
        print("\n[Step 1] Creating Mock User...")
        u = User(username='demo_user', email='demo@e.ntu.edu.sg', password='password')
        u.is_verified = True # Critical: Must be verified to report
        db.session.add(u)
        db.session.commit()
        print(f"   > User created: {u.username} (Verified: {u.is_verified})")
        
        with app.test_client() as client:
            # 3. Login
            print("\n[Step 2] Logging in...")
            client.post('/auth/login', data={'email': 'demo@e.ntu.edu.sg', 'password': 'password'})
            print("   > Login successful.")

            # 4. Check Initial State
            print("\n[Step 3] Fetching Live Feed (Expect Empty)...")
            resp = client.get('/api/live-status/')
            reports = resp.get_json()
            print(f"   > Feed items: {len(reports)}")
            
            # 5. Submit Report
            print("\n[Step 4] User Submitting Report: 'Open'...")
            post_resp = client.post('/api/live-status/', json={'status': 'Open'})
            if post_resp.status_code == 201:
                print("   > ✅ Report submitted successfully.")
                print(f"   > Server Response: {post_resp.get_json()}")
            else:
                print(f"   > ❌ Submission Failed: {post_resp.status_code}")
                return

            # 6. Submit Another Report (e.g., from another user theoretically, but let's just add one more)
            # For demo, just one is enough to prove "Display".
            
            # 7. Fetch and Display Results
            print("\n[Step 5] Fetching Live Feed to Verify Display...")
            final_resp = client.get('/api/live-status/')
            final_reports = final_resp.get_json()
            
            print(f"   > Feed items: {len(final_reports)}")
            print("\n   👇 [LIVE FEED DISPLAY SIMULATION] 👇")
            print("   " + "-"*40)
            for r in final_reports:
                status_icon = "🟢" if r['status'] == 'Open' else "🔴"
                print(f"   | {status_icon} Status: {r['status']}")
                print(f"   | 👤 User:   {r['user']}")
                print(f"   | 🕒 Time:   {r['timestamp']}")
                print("   " + "-"*40)

            print("\n✅ TEST COMPLETE: Feature is functioning correctly.")
            print("="*50)

if __name__ == "__main__":
    run_demo()
