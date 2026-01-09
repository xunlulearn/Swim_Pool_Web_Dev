"""
增量迁移脚本 - 仅添加新列，不清空数据
用于将 Profile Management 功能的新字段同步到 Supabase
"""
from app import create_app, db
from app.models.user import User
from app.models.content import Post, Comment
from app.models.report import PoolReport
from app.models.content_report import ContentReport
from app.models.interaction import Like, Collection
from sqlalchemy import text, inspect

app = create_app()

# 定义需要添加的新列 (表名, 列名, SQL类型, 默认值)
NEW_COLUMNS = [
    ('users', 'nickname', 'VARCHAR(64)', "''"),
    ('users', 'avatar', 'BYTEA', 'NULL'),  # PostgreSQL BLOB type
    ('users', 'avatar_mimetype', 'VARCHAR(32)', 'NULL'),
]

with app.app_context():
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    print(f"🔄 正在连接数据库...")
    print(f"Target Database: {db_uri.split('@')[-1] if '@' in db_uri else db_uri}")

    if db_uri.startswith('sqlite'):
        print("\n" + "="*50)
        print("❌ 错误：检测到正在使用 SQLite 本地数据库！")
        print("请在 .env 中设置 DATABASE_URL 为 Supabase 连接字符串。")
        print("="*50)
        exit(1)
        
    print("✅ 检测到 PostgreSQL 数据库，准备执行增量迁移...\n")
    
    inspector = inspect(db.engine)
    
    # 检查 users 表是否存在
    existing_tables = inspector.get_table_names()
    if 'users' not in existing_tables:
        print("⚠️  users 表不存在，执行完整 create_all()...")
        db.create_all()
        print("✅ 所有表已创建！")
    else:
        # 获取 users 表现有的列
        existing_columns = [col['name'] for col in inspector.get_columns('users')]
        print(f"📊 users 表现有列: {existing_columns}")
        
        # 逐个检查并添加新列
        with db.engine.connect() as conn:
            for table, col_name, col_type, default in NEW_COLUMNS:
                if col_name in existing_columns:
                    print(f"⏭️  列 '{col_name}' 已存在，跳过。")
                else:
                    print(f"➕ 添加列 '{col_name}' ({col_type})...")
                    try:
                        if default == 'NULL':
                            sql = f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_type};'
                        else:
                            sql = f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_type} DEFAULT {default};'
                        conn.execute(text(sql))
                        conn.commit()
                        print(f"   ✅ 成功添加 '{col_name}'")
                    except Exception as e:
                        print(f"   ❌ 添加 '{col_name}' 失败: {e}")
        
        # 同时确保其他新表也存在 (如果有)
        db.create_all()
        print("\n✅ 增量迁移完成！")
    
    # 验证
    inspector = inspect(db.engine)
    final_columns = [col['name'] for col in inspector.get_columns('users')]
    print(f"\n🔍 最终 users 表列: {final_columns}")
    
    required = ['nickname', 'avatar', 'avatar_mimetype']
    missing = [c for c in required if c not in final_columns]
    if missing:
        print(f"⚠️  警告: 以下列仍然缺失: {missing}")
    else:
        print("🎉 所有 Profile 相关列已就绪！")