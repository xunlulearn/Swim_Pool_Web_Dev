from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Dropping all tables with CASCADE...")
    
    # 使用原生 SQL 删除所有表（CASCADE）
    db.session.execute(text("DROP SCHEMA public CASCADE"))
    db.session.execute(text("CREATE SCHEMA public"))
    db.session.commit()
    
    print("Recreating all tables...")
    db.create_all()
    print("Database reset complete.")
