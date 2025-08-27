from models import db, Users, Events
from flask import request, jsonify, Blueprint
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func
import base64
import os
import boto3
from dotenv import load_dotenv
load_dotenv()

user_bp = Blueprint('user_bp', __name__)


R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL')
IMAGE_PREFIX = os.getenv('IMAGE_PREFIX')


s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)    

# Manual signup removed - OAuth only authentication

@user_bp.route('/users', methods=['GET'])
def get_all_users():
    users = Users.query.all()
    if users:
        all_users = []
        for user in users:
            all_users.append({
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'username': user.username,
                'phone_no': user.phone_no,
                'category': user.category,
                'image_url': user.avatar if user.avatar else None,
            })
        return jsonify({'users': all_users})
    else:
        return jsonify(message="No users found"), 404


# Route to get a specific user by id
@user_bp.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = Users.query.get(user_id)
    if user:
        return jsonify({'user': {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,    
            'username': user.username,
            'phone_no': user.phone_no,
            'category': user.category,
            'image_url': user.avatar if user.avatar else None,
            'display_name': user.display_name,
            'bio': user.bio
        }})
    else:
        return jsonify(message="User not found"), 404

@user_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    current_user_id = get_jwt_identity()
    user = Users.query.get(current_user_id)
    
    if user:
        # Serialize user data
        user_data = {
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'username': user.username,
            'email': user.email,
            'phone_no': user.phone_no,
            'category': user.category,
            'image_url': user.avatar if user.avatar else None,
            'display_name': user.display_name,
            'bio': user.bio
        }
        return jsonify(user_data), 200
    else:
        return jsonify(message="User not found"), 404

@user_bp.route('/update-profile', methods=['PUT'])
@jwt_required()
def update_profile():
    current_user = get_jwt_identity()
    user = Users.query.filter_by(id=current_user).first()
    
    if not user:
        return jsonify(message="User not found"), 404
    
    data = request.form  # Use request.form for handling form data

    # Username change with validation and uniqueness check
    new_username = data.get('username')
    if new_username and new_username != user.username:
        uname = new_username.strip()
        if len(uname) < 3 or len(uname) > 20:
            return jsonify({'error': 'Username must be between 3 and 20 characters'}), 400
        import re
        if not re.match(r'^[A-Za-z0-9_]+$', uname):
            return jsonify({'error': 'Username can only contain letters, numbers, and underscores'}), 400
        from sqlalchemy import func
        existing = Users.query.filter(func.lower(Users.username) == uname.lower()).first()
        if existing and existing.id != user.id:
            return jsonify({'error': 'Username already taken'}), 409
        user.username = uname

    user.first_name = data.get('first_name', user.first_name)
    user.display_name = data.get('display_name', user.display_name)
    user.last_name = data.get('last_name', user.last_name)
    user.bio = data.get('bio', user.bio)
    user.email = data.get('email', user.email)
    user.phone_no = data.get('phone_no', user.phone_no)
    user.category = data.get('category', user.category)


    # Handle image upload to R2
    image_file = request.files.get('profile_image')  # Expecting a file input with name 'profile_image'
    
    if image_file and image_file.filename:
        image_key = f'profile_images/{current_user}/{secure_filename(image_file.filename)}'
        
        try:
            s3_client.upload_fileobj(image_file, R2_BUCKET_NAME, image_key)
            r2_image_url = f"{IMAGE_PREFIX}/{image_key}"
            user.avatar = r2_image_url
        except Exception as e:
            return jsonify({'error': f"Failed to upload image: {str(e)}"}), 500

    db.session.commit()

    return jsonify({'message': 'Profile updated successfully'})


# Delete user
@user_bp.route("/deleteuser", methods=["DELETE"])
@jwt_required()
def delete_user():
    current_user_id = get_jwt_identity()
    user = Users.query.get(current_user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"message": "User deleted successfully"}), 200
    else:
        return jsonify({"message": "User you are trying to delete is not found!"}), 404

@user_bp.route('/user-events', methods=['GET'])
@jwt_required()
def get_user_events():
    current_user = get_jwt_identity()
    user_events = Events.query.filter_by(user_id=current_user).all()
    
    output = []
    for event in user_events:
        event_data = {
            'id': event.id,
            'title': event.title,
            'description': event.description,
            'poster': event.image_url if event.image_url else None,
            'start_time': event.start_time.strftime('%I:%M %p'),  # Format start time
            'end_time': event.end_time.strftime('%I:%M %p'),  # Format end time
            'date': event.date_of_event.strftime('%d %b %Y'),  # Format date
            'entry_fee': event.entry_fee,
            'category': event.category,
            'comments': [{
                'id': comment.id,
                'text': comment.text,
                'username': comment.user.username,
                'dateCreated': comment.created_at
            } for comment in event.comments]
        }
        output.append(event_data)
    
    return jsonify({'user_events': output})

# @user_bp.route('/user-fun_times', methods=['GET'])
# @jwt_required()
# def get_user_fun_times():
#     current_user = get_jwt_identity()
#     user_fun_times = Fun_times.query.filter_by(user_id=current_user).all()

#     output = []
#     for fun_time in user_fun_times:
#         total_likes = db.session.query(func.count(Likes.id)).filter(Likes.fun_time_id == fun_time.id).scalar()
#         fun_time_data = {
#             'funtimeId': fun_time.id,
#             'description': fun_time.description,
#             'image_url':fun_time.image_url if fun_time.image_url else None,
#             'category': fun_time.category,
#             'total_likes': total_likes,
#             'comments': [{
#                 'id': comment.id,
#                 'text': comment.text,
#                 'username': comment.user.username,
#                 'dateCreated': comment.created_at
#             } for comment in fun_time.comments]
#         }
#         output.append(fun_time_data)

#     return jsonify({'user_fun_times': output})
