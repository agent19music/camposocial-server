from models import db, Users, Events, Friendship
from flask import request, jsonify, Blueprint
from werkzeug.security import generate_password_hash
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

@user_bp.route("/signup", methods=["POST"])
def add_users():
    try:
        data = request.get_json()

        required_fields = ["username", "email", "password", "first_name", "last_name", "category"]
        for field in required_fields:
            if field not in data:
                return jsonify({"message": f"{field} is required"}), 400

        existing_user = Users.query.filter(or_(Users.username == data["username"], Users.email == data["email"])).first()
        if existing_user:
            return jsonify({"message": "Username or email already exists"}), 400

        hashed_password = generate_password_hash(data["password"])

        new_user = Users(
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            username=data['username'],
            email=data["email"],
            password=hashed_password,
            category=data.get("category"),
           
        )

        db.session.add(new_user)
        db.session.commit()

        return jsonify({"message": "User added successfully"}), 201
    except AssertionError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        print(str(e))
        db.session.rollback()
        return jsonify({"message": "Internal Server Error"}), 500
    

@user_bp.route('/users', methods=['GET'])
@jwt_required()
def get_all_users():
    # Get the current user's identity from the JWT
    user_identity = get_jwt_identity()
    current_user = Users.query.filter_by(id=user_identity).first()

    if not current_user:
        return jsonify(message="Current user not found"), 404

    # Fetch all users
    users = Users.query.all()
    if users:
        all_users = []
        for user in users:
            # Skip the current user in the response
            if user.id == current_user.id:
                continue

            # Calculate mutual friends
            mutual_friends_count = len(current_user.get_friend_ids() & user.get_friend_ids())

            # Determine friendship status
            friendship = Friendship.query.filter(
                (Friendship.user_id == current_user.id) & (Friendship.friend_id == user.id)
                | (Friendship.user_id == user.id) & (Friendship.friend_id == current_user.id)
            ).first()

            if friendship:
                if friendship.status == 'accepted':
                    friendship_status = 'friend'
                elif friendship.user_id == current_user.id:
                    friendship_status = 'request_sent'
                elif friendship.friend_id == current_user.id:
                    friendship_status = 'request_received'
            else:
                friendship_status = 'none'

            # Add user details
            all_users.append({
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'username': user.username,
                'phone_no': user.phone_no,
                'category': user.category,
                'photoUrl': user.avatar if user.avatar else None,
                'id': user.id,
                'mutual_friends': mutual_friends_count,
                'friendship_status': friendship_status  # Add status to response
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
            'image_url': user.image_url if user.image_url else None,
            'gender': user.gender
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
            'image_url': user.image_url if user.image_url else None,
            'gender': user.gender
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
    user.first_name = data.get('first_name', user.first_name)
    user.last_name = data.get('last_name', user.last_name)
    user.username = data.get('username', user.username)
    user.email = data.get('email', user.email)
    user.phone_no = data.get('phone_no', user.phone_no)
    user.category = data.get('category', user.category)
    user.gender = data.get('gender', user.gender)

    # Handle image upload to R2
    image_file = request.files.get('profile_image')  # Expecting a file input with name 'profile_image'
    
    if image_file:
        # Create an image key (filename) for the uploaded object
        image_key = f'profile_images/{current_user}/{image_file.filename}'
        
        try:
            # Upload image to R2 bucket
            s3_client.upload_fileobj(image_file, R2_BUCKET_NAME, image_key)

            # You can store the image key or a full URL in the user's profile
            r2_image_url = f"{IMAGE_PREFIX}/{image_key}"
            user.image_url = r2_image_url
        except Exception as e:
            return jsonify({'error': f"Failed to upload image: {str(e)}"}), 500

    # Commit changes to the database
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

@user_bp.route('/friends', methods=['GET'])
@jwt_required()
def get_friends():
    user_id = get_jwt_identity()  # Authenticated user's ID
    friends = Friendship.query.filter(
        ((Friendship.user_id == user_id) | (Friendship.friend_id == user_id)),
        Friendship.status == 'accepted'
    ).all()

    friends_list = [
        {
            'id': friend.friend_id if friend.user_id == user_id else friend.user_id,
            'username': friend.friend.username if friend.user_id == user_id else friend.user.username,
            'photoUrl': friend.friend.avatar if friend.user_id == user_id else friend.user.avatar,
            'course': friend.friend.category if friend.user_id == user_id else friend.user.category,
        }
        for friend in friends
    ]

    return jsonify({'friends': friends_list}), 200

@user_bp.route('/friends/block', methods=['POST'])
@jwt_required()
def block_user():
    user_id = get_jwt_identity()  # Authenticated user's ID
    data = request.get_json()
    target_id = data.get('target_id')
    action = data.get('action')  # 'block' or 'unblock'

    if not target_id or action not in ['block', 'unblock']:
        return jsonify({"error": "Target ID and valid action ('block' or 'unblock') are required"}), 400

    friendship = Friendship.query.filter(
        ((Friendship.user_id == user_id) & (Friendship.friend_id == target_id)) |
        ((Friendship.user_id == target_id) & (Friendship.friend_id == user_id))
    ).first()

    if not friendship:
        friendship = Friendship(user_id=user_id, friend_id=target_id, status='blocked' if action == 'block' else 'pending')
        db.session.add(friendship)
    else:
        if action == 'block':
            friendship.status = 'blocked'
        elif action == 'unblock':
            if friendship.status != 'blocked':
                return jsonify({"error": "User is not blocked"}), 400
            friendship.status = 'pending'  # Reset to pending or remove entirely based on your logic

    db.session.commit()

    return jsonify({"message": f"User {'blocked' if action == 'block' else 'unblocked'} successfully"}), 200

@user_bp.route('/friends/remove', methods=['DELETE'])
@jwt_required()
def remove_friend():
    user_id = get_jwt_identity()  # Authenticated user's ID
    data = request.get_json()
    friend_id = data.get('friend_id')

    if not friend_id:
        return jsonify({"error": "Friend ID is required"}), 400

    friendship = Friendship.query.filter(
        ((Friendship.user_id == user_id) & (Friendship.friend_id == friend_id)) |
        ((Friendship.user_id == friend_id) & (Friendship.friend_id == user_id)),
        Friendship.status == 'accepted'
    ).first()

    if not friendship:
        return jsonify({"error": "Friendship not found"}), 404

    db.session.delete(friendship)
    db.session.commit()

    return jsonify({"message": "Friend removed successfully"}), 200

@user_bp.route('/friends/add', methods=['POST'])
@jwt_required()
def add_friend():
    user_id = get_jwt_identity()  # Authenticated user's ID
    data = request.get_json()
    requester_id = data.get('requester_id')

    if not requester_id:
        return jsonify({"error": "Requester ID is required"}), 400

    friend_request = Friendship.query.filter_by(user_id=requester_id, friend_id=user_id, status='pending').first()
    if not friend_request:
        return jsonify({"error": "No pending friend request from this user"}), 404

    friend_request.status = 'accepted'
    db.session.commit()

    return jsonify({"message": "Friend request accepted"}), 200

@user_bp.route('/friends/send-request', methods=['POST'])
@jwt_required()
def send_friend_request():
    sender_id = get_jwt_identity()  # Authenticated user's ID
    data = request.get_json()
    recipient_id = data.get('recipient_id')

    if not recipient_id:
        return jsonify({"error": "Recipient ID is required"}), 400

    if sender_id == recipient_id:
        return jsonify({"error": "You cannot send a friend request to yourself"}), 400

    existing_request = Friendship.query.filter_by(user_id=sender_id, friend_id=recipient_id).first()
    if existing_request:
        return jsonify({"error": "Friend request already sent"}), 400

    new_request = Friendship(user_id=sender_id, friend_id=recipient_id, status='pending')
    db.session.add(new_request)
    db.session.commit()

    return jsonify({"message": "Friend request sent successfully"}), 201

@user_bp.route('/friends/pending', methods=['GET'])
@jwt_required()
def get_pending_requests():
    user_id = get_jwt_identity()  # Authenticated user's ID
    
    # Fetch all friend requests where the user is the recipient and the status is 'pending'
    pending_requests = Friendship.query.filter_by(friend_id=user_id, status='pending').all()

    if not pending_requests:
        return jsonify({"message": "No pending friend requests"}), 404

    # Serialize the results
    requests_list = [
        {
            'id': request.user_id,  # ID of the sender
            'username': request.user.username,  # Username of the sender
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            'photoUrl': request.user.avatar
        }
        for request in pending_requests
    ]

    return jsonify({"pending_requests": requests_list}), 200

@user_bp.route('/friends/reject', methods=['DELETE'])
@jwt_required()
def reject_friend_request():
    user_id = get_jwt_identity()  # Authenticated user's ID
    data = request.get_json()
    requester_id = data.get('requester_id')

    if not requester_id:
        return jsonify({"error": "Requester ID is required"}), 400

    # Find the pending friend request
    friend_request = Friendship.query.filter_by(
        user_id=requester_id,
        friend_id=user_id,
        status='pending'
    ).first()

    if not friend_request:
        return jsonify({"error": "No pending friend request from this user"}), 404

    # Delete the friend request to reject it
    db.session.delete(friend_request)
    db.session.commit()

    return jsonify({"message": "Friend request rejected successfully"}), 200






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
