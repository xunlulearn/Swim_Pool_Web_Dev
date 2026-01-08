import os
from app import create_app, db

# -------------------------------------------------------
# ⚠️ 请把下面这行换成你刚才填在 GCP 里的那个完整 Supabase 链接
# 格式：postgresql://postgres...:密码@...:6543/postgres
# -------------------------------------------------------
remote_db_url = "postgresql://postgres.rbtrvefqdvxqboaqgnfy:Ltc3.141592654@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

# 强制让 Flask 使用这个远程地址，而不是本地地址
os.environ['DATABASE_URL'] = remote_db_url

app = create_app()

with app.app_context():
    print(f"正在连接到: {remote_db_url.split('@')[1]}") # 只打印后半部分防止泄露密码
    print("正在创建数据表...")
    try:
        db.create_all()
        print("✅ 成功！数据表已在 Supabase 远程数据库中创建完成！")
    except Exception as e:
        print(f"❌ 出错了: {e}")