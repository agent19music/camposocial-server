from models import db, Users, TokenBlocklist
from flask import request, jsonify, Blueprint
from werkzeug.security import check_password_hash, generate_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
import base64

auth_bp = Blueprint('auth_bp', __name__)

# Routes

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
            return jsonify(access_token=access_token), 200
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
            'display_name': user.display_name
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

# Confirm user email
@auth_bp.route("/confirm_email", methods=["POST"])
def confirm_email():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')

    user = Users.query.filter_by(username=username, email=email).first()

    if user:
        return jsonify({"message": "Email confirmed"}), 200
    else:
        return jsonify({"error": "Invalid username or email"}), 404

# Reset password
@auth_bp.route("/reset_password", methods=["POST"])
def reset_password():
    data = request.get_json()
    username = data.get('username')
    new_password = data.get('new_password')

    user = Users.query.filter_by(username=username).first()

    if user:
        # Update the password
        user.password = generate_password_hash(new_password)
        db.session.commit()

        return jsonify({"message": "Password reset successfully"}), 200
    else:
        return jsonify({"error": "Invalid username or email"}), 404
    

