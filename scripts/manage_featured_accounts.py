#!/usr/bin/env python3
"""
Management script for featured accounts with engagement multipliers.

Usage:
    python scripts/manage_featured_accounts.py create --username "campus_voice" --display-name "Campus Voice" --multiplier 46
    python scripts/manage_featured_accounts.py update --username "campus_voice" --multiplier 50
    python scripts/manage_featured_accounts.py list
    python scripts/manage_featured_accounts.py remove --username "campus_voice"
"""

import argparse
import json
import os
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from werkzeug.security import generate_password_hash
from models import db, Users
from app import create_app

# Path to credentials file (gitignored)
CREDENTIALS_FILE = Path(__file__).parent.parent / 'featured_accounts_credentials.json'


def generate_secure_password(length=16):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password


def load_credentials():
    """Load credentials from JSON file."""
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_credentials(credentials):
    """Save credentials to JSON file."""
    with open(CREDENTIALS_FILE, 'w') as f:
        json.dump(credentials, f, indent=2)
    print(f"Credentials saved to {CREDENTIALS_FILE}")


def create_featured_account(username, display_name, email=None, bio=None, 
                           avatar_url=None, header_image_url=None, multiplier=46.0):
    """Create a new featured account."""
    app, _ = create_app()
    with app.app_context():
        # Check if username already exists
        existing_user = Users.query.filter_by(username=username).first()
        if existing_user:
            print(f"Error: Username '{username}' already exists.")
            return False
        
        # Generate email if not provided
        if not email:
            email = f"featured_{username}@camposocial.local"
        else:
            # Check if email already exists
            existing_email = Users.query.filter_by(email=email).first()
            if existing_email:
                print(f"Error: Email '{email}' already exists.")
                return False
        
        # Generate secure password
        password = generate_secure_password()
        password_hash = generate_password_hash(password)
        
        # Create user
        new_user = Users(
            username=username,
            email=email,
            password=password_hash,
            display_name=display_name,
            bio=bio or "",
            avatar=avatar_url,
            yap_header_img=header_image_url,
            engagement_multiplier=multiplier,
            email_verified=True,
            profile_completed=True,
            is_oauth_user=False
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            
            # Save credentials
            credentials = load_credentials()
            credentials[username] = {
                'email': email,
                'password': password,
                'multiplier': multiplier,
                'created_at': datetime.utcnow().isoformat()
            }
            save_credentials(credentials)
            
            print(f"✓ Featured account created successfully!")
            print(f"  Username: {username}")
            print(f"  Display Name: {display_name}")
            print(f"  Email: {email}")
            print(f"  Engagement Multiplier: {multiplier}x")
            print(f"  Password: {password}")
            print(f"  (Credentials saved to {CREDENTIALS_FILE})")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"Error creating account: {str(e)}")
            return False


def update_featured_account(username, multiplier=None, bio=None, 
                            avatar_url=None, header_image_url=None, display_name=None):
    """Update an existing featured account."""
    app, _ = create_app()
    with app.app_context():
        user = Users.query.filter_by(username=username).first()
        if not user:
            print(f"Error: User '{username}' not found.")
            return False
        
        updated = False
        
        if multiplier is not None:
            user.engagement_multiplier = multiplier
            updated = True
            print(f"  Updated multiplier to {multiplier}x")
        
        if bio is not None:
            user.bio = bio
            updated = True
            print(f"  Updated bio")
        
        if avatar_url is not None:
            user.avatar = avatar_url
            updated = True
            print(f"  Updated avatar")
        
        if header_image_url is not None:
            user.yap_header_img = header_image_url
            updated = True
            print(f"  Updated header image")
        
        if display_name is not None:
            user.display_name = display_name
            updated = True
            print(f"  Updated display name to '{display_name}'")
        
        if not updated:
            print("No updates specified.")
            return False
        
        try:
            db.session.commit()
            
            # Update credentials file if multiplier changed
            if multiplier is not None:
                credentials = load_credentials()
                if username in credentials:
                    credentials[username]['multiplier'] = multiplier
                    credentials[username]['updated_at'] = datetime.utcnow().isoformat()
                    save_credentials(credentials)
            
            print(f"✓ Account '{username}' updated successfully!")
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"Error updating account: {str(e)}")
            return False


def list_featured_accounts():
    """List all featured accounts."""
    app, _ = create_app()
    with app.app_context():
        # Get all users with multiplier > 1.0
        featured_users = Users.query.filter(
            Users.engagement_multiplier > 1.0
        ).order_by(Users.engagement_multiplier.desc()).all()
        
        if not featured_users:
            print("No featured accounts found.")
            return
        
        print(f"\nFeatured Accounts (Total: {len(featured_users)}):")
        print("-" * 80)
        
        for user in featured_users:
            print(f"Username: {user.username}")
            print(f"  Display Name: {user.display_name}")
            print(f"  Email: {user.email}")
            print(f"  Engagement Multiplier: {user.engagement_multiplier}x")
            print(f"  Bio: {user.bio or '(empty)'}")
            print(f"  Created: {user.created_at}")
            print()


def remove_featured_status(username):
    """Remove featured status by setting multiplier back to 1.0."""
    app, _ = create_app()
    with app.app_context():
        user = Users.query.filter_by(username=username).first()
        if not user:
            print(f"Error: User '{username}' not found.")
            return False
        
        if user.engagement_multiplier == 1.0:
            print(f"User '{username}' is not a featured account (multiplier is already 1.0).")
            return False
        
        try:
            user.engagement_multiplier = 1.0
            db.session.commit()
            
            # Update credentials file
            credentials = load_credentials()
            if username in credentials:
                credentials[username]['multiplier'] = 1.0
                credentials[username]['removed_at'] = datetime.utcnow().isoformat()
                save_credentials(credentials)
            
            print(f"✓ Featured status removed from '{username}' (multiplier set to 1.0)")
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"Error removing featured status: {str(e)}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description='Manage featured accounts with engagement multipliers'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Create command
    create_parser = subparsers.add_parser('create', help='Create a new featured account')
    create_parser.add_argument('--username', required=True, help='Username (must be unique)')
    create_parser.add_argument('--display-name', required=True, dest='display_name', help='Display name')
    create_parser.add_argument('--email', help='Email address (auto-generated if not provided)')
    create_parser.add_argument('--bio', help='Bio text')
    create_parser.add_argument('--avatar-url', dest='avatar_url', help='Avatar image URL')
    create_parser.add_argument('--header-image-url', dest='header_image_url', help='Header image URL')
    create_parser.add_argument('--multiplier', type=float, default=46.0, help='Engagement multiplier (default: 46.0)')
    
    # Update command
    update_parser = subparsers.add_parser('update', help='Update an existing featured account')
    update_parser.add_argument('--username', required=True, help='Username to update')
    update_parser.add_argument('--multiplier', type=float, help='New engagement multiplier')
    update_parser.add_argument('--bio', help='New bio text')
    update_parser.add_argument('--avatar-url', dest='avatar_url', help='New avatar image URL')
    update_parser.add_argument('--header-image-url', dest='header_image_url', help='New header image URL')
    update_parser.add_argument('--display-name', dest='display_name', help='New display name')
    
    # List command
    subparsers.add_parser('list', help='List all featured accounts')
    
    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove featured status (set multiplier to 1.0)')
    remove_parser.add_argument('--username', required=True, help='Username to remove featured status from')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'create':
        create_featured_account(
            username=args.username,
            display_name=args.display_name,
            email=args.email,
            bio=args.bio,
            avatar_url=args.avatar_url,
            header_image_url=args.header_image_url,
            multiplier=args.multiplier
        )
    elif args.command == 'update':
        update_featured_account(
            username=args.username,
            multiplier=args.multiplier,
            bio=args.bio,
            avatar_url=args.avatar_url,
            header_image_url=args.header_image_url,
            display_name=args.display_name
        )
    elif args.command == 'list':
        list_featured_accounts()
    elif args.command == 'remove':
        remove_featured_status(username=args.username)


if __name__ == '__main__':
    main()
