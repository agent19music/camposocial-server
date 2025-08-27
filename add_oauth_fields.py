#!/usr/bin/env python3
"""
Script to add OAuth fields to the Users table if they don't exist.
This ensures the database is ready for OAuth authentication.
"""

import sqlite3
import os

def add_oauth_fields():
    """Add OAuth fields to the Users table if they don't exist."""
    
    # Get database path
    db_path = 'test.db'
    
    if not os.path.exists(db_path):
        print(f"Database {db_path} does not exist. Please run your Flask app first to create it.")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Get current columns
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        # OAuth fields to add
        oauth_fields = [
            ("oauth_provider", "VARCHAR(50)"),
            ("oauth_id", "VARCHAR(255)"),
            ("is_oauth_user", "BOOLEAN DEFAULT 0"),
            ("profile_completed", "BOOLEAN DEFAULT 0")
        ]
        
        fields_added = []
        
        for field_name, field_type in oauth_fields:
            if field_name not in column_names:
                try:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {field_name} {field_type}")
                    fields_added.append(field_name)
                    print(f"✓ Added field: {field_name}")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        print(f"✗ Error adding field {field_name}: {e}")
            else:
                print(f"• Field already exists: {field_name}")
        
        if fields_added:
            conn.commit()
            print(f"\n✓ Successfully added {len(fields_added)} OAuth fields to the database")
        else:
            print("\n• All OAuth fields already exist in the database")
        
        # Verify the changes
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        print("\nCurrent Users table columns:")
        oauth_cols = [col for col in column_names if 'oauth' in col.lower() or col == 'profile_completed']
        for col in oauth_cols:
            print(f"  - {col}")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("Adding OAuth fields to database...")
    print("-" * 40)
    success = add_oauth_fields()
    print("-" * 40)
    if success:
        print("✓ Database is ready for OAuth authentication!")
    else:
        print("✗ Failed to prepare database for OAuth")
