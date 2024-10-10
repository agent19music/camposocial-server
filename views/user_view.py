from models import db, Users, Events
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
                'image_url': user.image_url if user.image_url else None,
                'gender': user.gender
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
