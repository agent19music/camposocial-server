"""
Migration script to add conversation metadata fields
Run this after updating models.py
"""

from app import app, db
from models import Conversation
from sqlalchemy import text

def run_migration():
    """Add new fields to conversation table"""
    with app.app_context():
        print("🔧 Starting migration...")
        
        try:
            # Check if fields already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('conversations')]
            
            print(f"📋 Current columns: {columns}")
            
            # Add missing columns
            if 'is_active' not in columns:
                print("➕ Adding is_active column...")
                db.session.execute(text(
                    "ALTER TABLE conversations ADD COLUMN is_active BOOLEAN DEFAULT TRUE NOT NULL"
                ))
                print("✅ Added is_active")
            
            if 'is_pinned_by_user1' not in columns:
                print("➕ Adding is_pinned_by_user1 column...")
                db.session.execute(text(
                    "ALTER TABLE conversations ADD COLUMN is_pinned_by_user1 BOOLEAN DEFAULT FALSE NOT NULL"
                ))
                print("✅ Added is_pinned_by_user1")
            
            if 'is_pinned_by_user2' not in columns:
                print("➕ Adding is_pinned_by_user2 column...")
                db.session.execute(text(
                    "ALTER TABLE conversations ADD COLUMN is_pinned_by_user2 BOOLEAN DEFAULT FALSE NOT NULL"
                ))
                print("✅ Added is_pinned_by_user2")
            
            if 'last_message_id' not in columns:
                print("➕ Adding last_message_id column...")
                db.session.execute(text(
                    "ALTER TABLE conversations ADD COLUMN last_message_id INTEGER"
                ))
                print("✅ Added last_message_id")
            
            if 'last_message_preview' not in columns:
                print("➕ Adding last_message_preview column...")
                db.session.execute(text(
                    "ALTER TABLE conversations ADD COLUMN last_message_preview VARCHAR(200)"
                ))
                print("✅ Added last_message_preview")
            
            db.session.commit()
            print("✅ Migration completed successfully!")
            
            # Verify
            inspector = db.inspect(db.engine)
            new_columns = [col['name'] for col in inspector.get_columns('conversations')]
            print(f"📋 Updated columns: {new_columns}")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {e}")
            raise

if __name__ == '__main__':
    run_migration()
