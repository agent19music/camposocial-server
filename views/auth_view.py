from models import db, Users, TokenBlocklist, Seller
from flask import request, jsonify, Blueprint
from werkzeug.security import check_password_hash, generate_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from sqlalchemy import func
import base64
import requests
import secrets
import string
import os

auth_bp = Blueprint('auth_bp', __name__)

# Routes

@auth_bp.route('/check-username', methods=['POST'])
def check_username():
    try:
        data = request.get_json() or {}
        username = (data.get('username') or '').strip()
        if not username:
            return jsonify({"error": "Username is required"}), 400
        if len(username) < 3 or len(username) > 20:
            return jsonify({"available": False}), 200
        import re
        if not re.match(r'^[A-Za-z0-9_]+$', username):
            return jsonify({"available": False}), 200
        exists = Users.query.filter(func.lower(Users.username) == username.lower()).first()
        return jsonify({"available": exists is None}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Login user
@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username:
        return jsonify(message="Username is required"), 400

    user = Users.query.filter_by(username=username).first()
    if user:
        if check_password_hash(user.password, password):
            access_token = create_access_token(identity=user.id)
            return jsonify(access_token=access_token, user_id=user.id), 200
        return jsonify(message="Invalid username or password"), 401
    else:
        return jsonify({"error": "User doesn't exist!"}), 404

# Get logged in user
@auth_bp.route("/authenticated_user", methods=["GET"])
@jwt_required()
def authenticated_user():
    current_user_id = get_jwt_identity()  # getting current user id
    user = Users.query.get(current_user_id)

    if user:
        # Encoding binary image data to base64 string for JSON serialization
        # image_url_base64 = base64.b64encode(user.image_url).decode('utf-8') if user.image_url else None
        
        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'category': user.category,
            'avatar': user.avatar if user.avatar else None,
            'phone_no': user.phone_no,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'course': user.category,
            'joined': user.created_at,
            'display_name': user.display_name,
            'is_seller': Seller.query.filter_by(user_id=user.id).first() is not None
        }
        return jsonify(user_data), 200
    else:
        return jsonify({"error": "User not found"}), 404

# Logout user
@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    jwt = get_jwt()
    jti = jwt['jti']

    token_b = TokenBlocklist(jti=jti)
    db.session.add(token_b)
    db.session.commit()

    return jsonify({"success": "Logged out successfully!"}), 200

# Reset password
@auth_bp.route("/reset_password", methods=["POST"])
def reset_password():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    new_password = data.get('new_password')

    user = Users.query.filter_by(username=username, email=email).first()

    if user:
        # Update the password
        user.password = generate_password_hash(new_password)
        db.session.commit()

        return jsonify({"message": "Password reset successfully"}), 200
    else:
        return jsonify({"error": "Invalid username or email"}), 404

# Helper function to generate random username
def generate_random_username(first_name, last_name):
    base = f"{first_name.lower()}{last_name.lower()}"
    random_suffix = ''.join(secrets.choice(string.digits) for _ in range(4))
    return f"{base}{random_suffix}"

# Enhanced OAuth handlers for multiple providers
@auth_bp.route("/oauth/google/callback", methods=["POST"])
def google_oauth_callback():
    return handle_oauth_callback('google')

@auth_bp.route("/oauth/github/callback", methods=["POST", "GET"])
def github_oauth_callback():
    if request.method == "GET":
        # Handle GitHub redirect
        code = request.args.get('code')
        if not code:
            return jsonify({"error": "Authorization code not provided"}), 400
        
        # Exchange code for access token
        client_id = os.environ.get('GITHUB_CLIENT_ID')
        client_secret = os.environ.get('GITHUB_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            return jsonify({"error": "GitHub OAuth credentials not configured"}), 500
        
        token_response = requests.post('https://github.com/login/oauth/access_token', {
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code
        }, headers={'Accept': 'application/json'})
        
        if token_response.status_code != 200:
            return jsonify({"error": "Failed to exchange code for token"}), 400
            
        token_data = token_response.json()
        access_token = token_data.get('access_token')
        
        if not access_token:
            error_description = token_data.get('error_description', 'Unknown error')
            return jsonify({"error": f"Failed to get access token: {error_description}"}), 400
        
        return handle_oauth_callback('github', access_token)
    else:
        # Handle POST request with code from frontend
        data = request.get_json()
        code = data.get('code') if data else None
        
        if code:
            # Exchange code for access token (same logic as GET)
            client_id = os.environ.get('GITHUB_CLIENT_ID')
            client_secret = os.environ.get('GITHUB_CLIENT_SECRET')
            
            if not client_id or not client_secret:
                return jsonify({"error": "GitHub OAuth credentials not configured"}), 500
            
            token_response = requests.post('https://github.com/login/oauth/access_token', {
                'client_id': client_id,
                'client_secret': client_secret,
                'code': code
            }, headers={'Accept': 'application/json'})
            
            if token_response.status_code != 200:
                return jsonify({"error": "Failed to exchange code for token"}), 400
                
            token_data = token_response.json()
            access_token = token_data.get('access_token')
            
            if not access_token:
                error_description = token_data.get('error_description', 'Unknown error')
                return jsonify({"error": f"Failed to get access token: {error_description}"}), 400
            
            return handle_oauth_callback('github', access_token)
        else:
            return handle_oauth_callback('github')

@auth_bp.route("/oauth/twitter/callback", methods=["POST"])
def twitter_oauth_callback():
    return handle_oauth_callback('twitter')

def handle_oauth_callback(provider, token=None):
    """Unified OAuth callback handler for all providers"""
    try:
        print(f"[DEBUG] Starting OAuth callback for provider: {provider}")
        
        if provider == 'google':
            data = request.get_json()
            print(f"[DEBUG] Received data: {data}")
            
            if not data:
                print("[ERROR] No data received in request")
                return jsonify({"error": "No data provided"}), 400
            
            # Handle both direct access_token and Google OAuth response structure
            access_token = token or data.get('access_token')
            
            # Check for Google OAuth response structure (from useGoogleLogin)
            if not access_token and data and 'code' in data:
                print("[DEBUG] Exchanging authorization code for access token")
                # Exchange authorization code for access token
                client_id = os.environ.get('GOOGLE_CLIENT_ID')
                client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
                
                if not client_id or not client_secret:
                    print("[ERROR] Google OAuth credentials not configured")
                    return jsonify({"error": "Google OAuth credentials not configured"}), 500
                
                token_response = requests.post('https://oauth2.googleapis.com/token', {
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'code': data.get('code'),
                    'grant_type': 'authorization_code',
                    'redirect_uri': data.get('redirect_uri', 'postmessage')
                })
                
                print(f"[DEBUG] Token response status: {token_response.status_code}")
                print(f"[DEBUG] Token response: {token_response.text}")
                
                if token_response.status_code == 200:
                    token_data = token_response.json()
                    access_token = token_data.get('access_token')
                else:
                    print(f"[ERROR] Failed to exchange code for token: {token_response.text}")
                    return jsonify({"error": f"Failed to exchange code for token: {token_response.text}"}), 400
            
            if not access_token:
                print("[ERROR] No access token found")
                return jsonify({"error": "Access token is required"}), 400
            
            # Get user info from Google
            print(f"[DEBUG] Getting user info with access token: {access_token[:20] if len(access_token) > 20 else access_token}...")
            
            # Use the Google People API which is more reliable
            response = requests.get(
                'https://people.googleapis.com/v1/people/me',
                headers={'Authorization': f'Bearer {access_token}'},
                params={'personFields': 'names,emailAddresses,photos'}
            )
            
            print(f"[DEBUG] People API response status: {response.status_code}")
            print(f"[DEBUG] People API response: {response.text}")
            
            # If People API fails, try the OAuth2 userinfo endpoint
            if response.status_code != 200:
                print("[DEBUG] Trying OAuth2 userinfo endpoint...")
                response = requests.get(
                    'https://www.googleapis.com/oauth2/v2/userinfo',
                    headers={'Authorization': f'Bearer {access_token}'}
                )
                print(f"[DEBUG] OAuth2 response status: {response.status_code}")
                print(f"[DEBUG] OAuth2 response: {response.text}")
                
                # If that also fails, try the older endpoint
                if response.status_code != 200:
                    print("[DEBUG] Trying older Google API endpoint...")
                    response = requests.get(
                        f'https://www.googleapis.com/oauth2/v1/userinfo?access_token={access_token}'
                    )
                    print(f"[DEBUG] Older endpoint response status: {response.status_code}")
                    print(f"[DEBUG] Older endpoint response: {response.text}")
            
            if response.status_code != 200:
                error_msg = f"Failed to get user info from Google. Status: {response.status_code}, Response: {response.text}"
                print(f"[ERROR] {error_msg}")
                return jsonify({"error": error_msg}), 400
            
            user_info = response.json()
            print(f"[DEBUG] Parsed user info: {user_info}")
            
            # Handle different API response formats
            if 'emailAddresses' in user_info:  # People API format
                emails = user_info.get('emailAddresses', [])
                primary_email = next((e['value'] for e in emails if e.get('metadata', {}).get('primary')), None)
                email = primary_email or (emails[0]['value'] if emails else None)
                
                names = user_info.get('names', [])
                primary_name = next((n for n in names if n.get('metadata', {}).get('primary')), {})
                first_name = primary_name.get('givenName', '')
                last_name = primary_name.get('familyName', '')
                
                photos = user_info.get('photos', [])
                primary_photo = next((p for p in photos if p.get('metadata', {}).get('primary')), {})
                avatar = primary_photo.get('url')
                
                # For People API, we need to get the ID from a different source or use email as identifier
                oauth_id = email  # Using email as ID since People API doesn't directly provide numeric ID
                
            else:  # OAuth2 userinfo API format
                oauth_id = user_info.get('id')
                email = user_info.get('email')
                first_name = user_info.get('given_name', '')
                last_name = user_info.get('family_name', '')
                avatar = user_info.get('picture')
            
            print(f"[DEBUG] User info: email={email}, oauth_id={oauth_id}, name={first_name} {last_name}")
            
        elif provider == 'github':
            data = request.get_json() if not token else None
            access_token = token or (data.get('access_token') if data else None)
            
            if not access_token:
                return jsonify({"error": "Access token is required"}), 400
            
            # Get user info from GitHub
            response = requests.get(
                'https://api.github.com/user',
                headers={'Authorization': f'token {access_token}'}
            )
            
            if response.status_code != 200:
                return jsonify({"error": "Failed to get user info from GitHub"}), 400
            
            user_info = response.json()
            oauth_id = str(user_info.get('id'))
            email = user_info.get('email')
            name_parts = (user_info.get('name') or '').split(' ', 1)
            first_name = name_parts[0] if name_parts else user_info.get('login', '')
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            avatar = user_info.get('avatar_url')
            
            # If email is null, get it from the emails endpoint
            if not email:
                email_response = requests.get(
                    'https://api.github.com/user/emails',
                    headers={'Authorization': f'token {access_token}'}
                )
                if email_response.status_code == 200:
                    emails = email_response.json()
                    primary_email = next((e['email'] for e in emails if e['primary']), None)
                    email = primary_email or (emails[0]['email'] if emails else None)
            
        elif provider == 'twitter':
            # Twitter OAuth 2.0 implementation would go here
            return jsonify({"error": "Twitter OAuth not fully implemented yet"}), 501
        
        if not email:
            return jsonify({"error": f"Email not provided by {provider}"}), 400
        
        # Check if user exists by OAuth ID first, then by email
        existing_user = Users.query.filter_by(oauth_provider=provider, oauth_id=oauth_id).first()
        if not existing_user:
            existing_user = Users.query.filter_by(email=email).first()
        
        if existing_user:
            # Update OAuth info if it's missing
            if not existing_user.oauth_provider:
                existing_user.oauth_provider = provider
                existing_user.oauth_id = oauth_id
                existing_user.is_oauth_user = True
                db.session.commit()
            
            # User exists, log them in
            access_token = create_access_token(identity=existing_user.id)
            return jsonify({
                "access_token": access_token,
                "is_profile_complete": existing_user.profile_completed
            }), 200
        else:
            # Create new user
            username = generate_random_username(first_name or 'user', last_name or 'name')
            
            # Ensure username is unique
            while Users.query.filter_by(username=username).first():
                username = generate_random_username(first_name or 'user', last_name or 'name')
            
            new_user = Users(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                avatar=avatar,
                display_name=None,  # Force user to choose custom display name
                oauth_provider=provider,
                oauth_id=oauth_id,
                is_oauth_user=True,
                profile_completed=False  # Always require profile completion for new OAuth users
            )
            
            db.session.add(new_user)
            db.session.commit()
            
            access_token = create_access_token(identity=new_user.id)
            
            return jsonify({
                "access_token": access_token,
                "is_profile_complete": False
            }), 201
            
    except Exception as e:
        print(f"[ERROR] OAuth authentication failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "OAuth authentication failed", "details": str(e)}), 500

# Complete profile after OAuth signup
@auth_bp.route("/user/complete-profile", methods=["POST"])
@jwt_required()
def complete_profile():
    current_user_id = get_jwt_identity()
    user = Users.query.get(current_user_id)
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    data = request.get_json() or {}

    # If user hasn't completed profile yet, enforce required fields
    if not user.profile_completed:
        if not data.get('username') or not data.get('display_name'):
            return jsonify({"error": "username and display_name are required"}), 400

    # Username handling
    new_username = data.get('username')
    if new_username and new_username != user.username:
        uname = new_username.strip()
        if len(uname) < 3 or len(uname) > 20:
            return jsonify({"error": "Username must be between 3 and 20 characters"}), 400
        # Allow letters, numbers, underscores
        import re
        if not re.match(r'^[A-Za-z0-9_]+$', uname):
            return jsonify({"error": "Username can only contain letters, numbers, and underscores"}), 400
        existing = Users.query.filter(func.lower(Users.username) == uname.lower()).first()
        if existing and existing.id != user.id:
            return jsonify({"error": "Username already taken"}), 409
        user.username = uname
    
    # Update user profile
    if 'first_name' in data and data['first_name']:
        user.first_name = data['first_name']
    if 'last_name' in data and data['last_name']:
        user.last_name = data['last_name']
    if 'category' in data and data['category']:
        user.category = data['category']
    if 'phone_no' in data:
        user.phone_no = data['phone_no']
    if 'display_name' in data and data['display_name']:
        user.display_name = data['display_name']
    if 'bio' in data:
        user.bio = data['bio']
    
    # Mark profile as completed
    user.profile_completed = True
    
    db.session.commit()
    
    return jsonify({"message": "Profile completed successfully"}), 200
