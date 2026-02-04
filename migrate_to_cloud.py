"""
Database Migration Script: Sync Local Changes to Cloud Database
Date: 2026-02-04
Purpose: Add new tables and columns without overwriting existing data

New additions:
1. comments table: parent_id, reply_to_user_id columns (for nested replies)
2. private_messages table (for direct messaging)
3. comment_likes table (for comment likes)

Usage:
1. Set CLOUD_DATABASE_URL in .env (uncomment the Supabase line)
2. Run: python migrate_to_cloud.py
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

load_dotenv()

# Cloud database URL (Supabase)
CLOUD_DATABASE_URL = "postgresql://postgres.rbtrvefqdvxqboaqgnfy:Ltc3.141592654@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

def get_existing_columns(engine, table_name):
    """Get list of existing column names for a table"""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return []
    return [col['name'] for col in inspector.get_columns(table_name)]

def get_existing_tables(engine):
    """Get list of existing table names"""
    inspector = inspect(engine)
    return inspector.get_table_names()

def migrate():
    print("=" * 60)
    print("Database Migration: Sync to Cloud")
    print("=" * 60)
    
    engine = create_engine(CLOUD_DATABASE_URL)
    existing_tables = get_existing_tables(engine)
    
    print(f"\nExisting tables: {existing_tables}")
    
    with engine.connect() as conn:
        # ============================================
        # 1. Add new columns to 'comments' table
        # ============================================
        if 'comments' in existing_tables:
            print("\n[1/3] Checking 'comments' table...")
            existing_cols = get_existing_columns(engine, 'comments')
            
            # Add parent_id column for nested replies
            if 'parent_id' not in existing_cols:
                print("  - Adding 'parent_id' column...")
                conn.execute(text("""
                    ALTER TABLE comments 
                    ADD COLUMN parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE
                """))
                print("    ✓ Added 'parent_id'")
            else:
                print("  - 'parent_id' already exists, skipping")
            
            # Add reply_to_user_id column
            if 'reply_to_user_id' not in existing_cols:
                print("  - Adding 'reply_to_user_id' column...")
                conn.execute(text("""
                    ALTER TABLE comments 
                    ADD COLUMN reply_to_user_id INTEGER REFERENCES users(id)
                """))
                print("    ✓ Added 'reply_to_user_id'")
            else:
                print("  - 'reply_to_user_id' already exists, skipping")
        else:
            print("\n[1/3] 'comments' table not found, skipping column additions")

        # ============================================
        # 2. Create 'private_messages' table
        # ============================================
        print("\n[2/3] Checking 'private_messages' table...")
        if 'private_messages' not in existing_tables:
            print("  - Creating 'private_messages' table...")
            conn.execute(text("""
                CREATE TABLE private_messages (
                    id SERIAL PRIMARY KEY,
                    sender_id INTEGER NOT NULL REFERENCES users(id),
                    receiver_id INTEGER NOT NULL REFERENCES users(id),
                    body TEXT NOT NULL,
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            # Create indexes for faster query
            conn.execute(text("""
                CREATE INDEX idx_pm_sender ON private_messages(sender_id)
            """))
            conn.execute(text("""
                CREATE INDEX idx_pm_receiver ON private_messages(receiver_id)
            """))
            print("    ✓ Created 'private_messages' table with indexes")
        else:
            print("  - 'private_messages' table already exists, skipping")

        # ============================================
        # 3. Create 'comment_likes' table
        # ============================================
        print("\n[3/3] Checking 'comment_likes' table...")
        if 'comment_likes' not in existing_tables:
            print("  - Creating 'comment_likes' table...")
            conn.execute(text("""
                CREATE TABLE comment_likes (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    comment_id INTEGER NOT NULL REFERENCES comments(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_comment_like UNIQUE (user_id, comment_id)
                )
            """))
            print("    ✓ Created 'comment_likes' table")
        else:
            print("  - 'comment_likes' table already exists, skipping")

        # Commit all changes
        conn.commit()
    
    print("\n" + "=" * 60)
    print("✓ Migration completed successfully!")
    print("=" * 60)
    print("\nSummary of changes applied:")
    print("  - comments.parent_id (nested replies)")
    print("  - comments.reply_to_user_id (reply target user)")
    print("  - private_messages table (direct messaging)")
    print("  - comment_likes table (comment likes)")
    print("\nNo existing data was modified or deleted.")


if __name__ == '__main__':
    try:
        migrate()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        print("\nPlease check:")
        print("  1. Cloud database URL is correct")
        print("  2. Database is accessible")
        print("  3. Required tables (users, comments) exist")
