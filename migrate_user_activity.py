#!/usr/bin/env python3
"""
Migration script to create UserActivity table
"""
from app import create_app
from models import db
from models_blocking import UserActivity

def migrate_user_activity():
    """Create UserActivity table if it doesn't exist"""
    app, _ = create_app()
    
    with app.app_context():
        try:
            # Create the table
            db.create_all()
            print("✅ UserActivity table created successfully")
            
            # Check if table was created
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'user_activity' in tables:
                print("✅ UserActivity table confirmed in database")
                
                # Check columns
                columns = [col['name'] for col in inspector.get_columns('user_activity')]
                expected_columns = ['id', 'user_id', 'last_seen', 'is_online', 'current_status', 'status_message']
                
                for col in expected_columns:
                    if col in columns:
                        print(f"✅ Column '{col}' exists")
                    else:
                        print(f"❌ Column '{col}' missing")
                        
            else:
                print("❌ UserActivity table not found in database")
                
        except Exception as e:
            print(f"❌ Error creating UserActivity table: {e}")

if __name__ == "__main__":
    migrate_user_activity()
