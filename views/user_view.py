from models import db, Users, Events, Follow
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
@jwt_required()
def get_all_users():
    current_user_id = get_jwt_identity()
    users = Users.query.filter(Users.id != current_user_id).all()  # Exclude current user
    
    all_users = []
    for user in users:
        all_users.append({
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'username': user.username,
            'phone_no': user.phone_no,
            'category': user.category,
            'avatar': user.avatar if user.avatar else None,
            'display_name': user.display_name,
            'bio': user.bio
        })
    return jsonify({'users': all_users})

@user_bp.route('/users/search', methods=['GET'])
@jwt_required()
def search_users():
    current_user_id = get_jwt_identity()
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({'users': []})
    
    # Search by username or display_name (case insensitive)
    users = Users.query.filter(
        Users.id != current_user_id,  # Exclude current user
        or_(
            func.lower(Users.username).contains(func.lower(query)),
            func.lower(Users.display_name).contains(func.lower(query)),
            func.lower(Users.first_name).contains(func.lower(query)),
            func.lower(Users.last_name).contains(func.lower(query))
        )
    ).limit(20).all()
    
    search_results = []
    for user in users:
        search_results.append({
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'username': user.username,
            'phone_no': user.phone_no,
            'category': user.category,
            'avatar': user.avatar if user.avatar else None,
            'display_name': user.display_name,
            'bio': user.bio
        })
    
    return jsonify({'users': search_results})


# Route to get a specific user by id
@user_bp.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = Users.query.get(user_id)
    if user:
        # Get follower and following counts
        followers_count = len(user.followers)
        following_count = len(user.following)
        yaps_count = len(user.yaps)
        
        return jsonify({'user': {
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,    
            'username': user.username,
            'phone_no': user.phone_no,
            'category': user.category,
            'avatar': user.avatar if user.avatar else None,
            'display_name': user.display_name,
            'bio': user.bio,
            'followers_count': followers_count,
            'following_count': following_count,
            'yaps_count': yaps_count
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

    # Handle profile image upload to R2
    image_file = request.files.get('profile_image')
    if image_file and image_file.filename:
        image_key = f'profile_images/{current_user}/{secure_filename(image_file.filename)}'
        try:
            s3_client.upload_fileobj(image_file, R2_BUCKET_NAME, image_key)
            r2_image_url = f"{IMAGE_PREFIX}/{image_key}"
            user.avatar = r2_image_url
        except Exception as e:
            return jsonify({'error': f"Failed to upload profile image: {str(e)}"}), 500

    # Handle header image upload to R2
    header_image = request.files.get('header_image')
    if header_image and header_image.filename:
        header_key = f'header_images/{current_user}/{secure_filename(header_image.filename)}'
        try:
            s3_client.upload_fileobj(header_image, R2_BUCKET_NAME, header_key)
            r2_header_url = f"{IMAGE_PREFIX}/{header_key}"
            user.yap_header_img = r2_header_url
        except Exception as e:
            return jsonify({'error': f"Failed to upload header image: {str(e)}"}), 500

    db.session.commit()

    return jsonify({'message': 'Profile updated successfully'})


# Get user settings
@user_bp.route('/settings', methods=['GET'])
@jwt_required()
def get_settings():
    current_user_id = get_jwt_identity()
    user = Users.query.get(current_user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'notifications': {
            'push': user.notify_push if user.notify_push is not None else True,
            'email': user.notify_email if user.notify_email is not None else True,
            'messages': user.notify_messages if user.notify_messages is not None else True
        },
        'privacy': {
            'who_can_tag': user.who_can_tag or 'everyone',
            'is_private': user.is_private if user.is_private is not None else False
        }
    }), 200


# Update user settings
@user_bp.route('/settings', methods=['PUT'])
@jwt_required()
def update_settings():
    current_user_id = get_jwt_identity()
    user = Users.query.get(current_user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    
    # Update notification settings
    if 'notifications' in data:
        notifications = data['notifications']
        if 'push' in notifications:
            user.notify_push = bool(notifications['push'])
        if 'email' in notifications:
            user.notify_email = bool(notifications['email'])
        if 'messages' in notifications:
            user.notify_messages = bool(notifications['messages'])
    
    # Update privacy settings
    if 'privacy' in data:
        privacy = data['privacy']
        if 'who_can_tag' in privacy:
            tag_setting = privacy['who_can_tag']
            if tag_setting in ['everyone', 'followers', 'nobody']:
                user.who_can_tag = tag_setting
            else:
                return jsonify({'error': 'Invalid who_can_tag value'}), 400
        if 'is_private' in privacy:
            user.is_private = bool(privacy['is_private'])
    
    db.session.commit()
    
    return jsonify({'message': 'Settings updated successfully'}), 200


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

# Follow/Unfollow endpoints
@user_bp.route('/users/<int:user_id>/follow', methods=['POST'])
@jwt_required()
def follow_user(user_id):
    current_user_id = get_jwt_identity()
    
    if current_user_id == user_id:
        return jsonify({'error': 'You cannot follow yourself'}), 400
    
    user_to_follow = Users.query.get(user_id)
    if not user_to_follow:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if already following
    existing_follow = Follow.query.filter_by(
        follower_id=current_user_id,
        following_id=user_id
    ).first()
    
    if existing_follow:
        return jsonify({'error': 'Already following this user'}), 400
    
    # Create follow relationship
    new_follow = Follow(follower_id=current_user_id, following_id=user_id)
    db.session.add(new_follow)
    
    # Create notification
    from models import Notification
    notification = Notification(
        type='FOLLOW',
        recipient_id=user_id,
        sender_id=current_user_id
    )
    db.session.add(notification)
    
    db.session.commit()
    
    return jsonify({
        'message': 'Successfully followed user',
        'followers_count': len(user_to_follow.followers)
    }), 200

@user_bp.route('/users/<int:user_id>/unfollow', methods=['POST'])
@jwt_required()
def unfollow_user(user_id):
    current_user_id = get_jwt_identity()
    
    if current_user_id == user_id:
        return jsonify({'error': 'You cannot unfollow yourself'}), 400
    
    user_to_unfollow = Users.query.get(user_id)
    if not user_to_unfollow:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if following
    existing_follow = Follow.query.filter_by(
        follower_id=current_user_id,
        following_id=user_id
    ).first()
    
    if not existing_follow:
        return jsonify({'error': 'Not following this user'}), 400
    
    # Remove follow relationship
    db.session.delete(existing_follow)
    db.session.commit()
    
    return jsonify({
        'message': 'Successfully unfollowed user',
        'followers_count': len(user_to_unfollow.followers)
    }), 200

@user_bp.route('/users/<int:user_id>/follow-status', methods=['GET'])
@jwt_required()
def get_follow_status(user_id):
    current_user_id = get_jwt_identity()
    
    if current_user_id == user_id:
        return jsonify({'is_following': False, 'can_follow': False}), 200
    
    existing_follow = Follow.query.filter_by(
        follower_id=current_user_id,
        following_id=user_id
    ).first()
    
    return jsonify({
        'is_following': existing_follow is not None,
        'can_follow': True
    }), 200

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
