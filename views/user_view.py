from models import db, Users, Events, Follow, Community
from flask import request, jsonify, Blueprint
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
import base64
import os
import boto3
from dotenv import load_dotenv
load_dotenv()

user_bp = Blueprint('user_bp', __name__)


R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID') or os.getenv('AWS_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY')
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
    user.university = data.get('university', user.university)
    user.faculty = data.get('faculty', user.faculty)
    user.course = data.get('course', user.course)

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

    # LOGIC: Auto-Award University Badge (if university is set)
    badge_award_result = None
    if user.university:
        try:
            from views.badges_view import auto_award_university_badge
            
            logger.info(f"Update profile: Attempting badge auto-award for user {user.id}, university: {user.university}")
            
            badge_award_result = auto_award_university_badge(
                user_id=user.id, 
                university_name=user.university,
                commit=False  # We'll commit with the profile update
            )
            
            if badge_award_result['success']:
                if badge_award_result['already_owned']:
                    logger.info(f"User {user.id} already has university badge")
                else:
                    logger.info(f"Badge {badge_award_result['badge_id']} will be awarded to user {user.id}")
            else:
                logger.warning(f"Badge award failed in update_profile: {badge_award_result['message']}")
                
        except ImportError as e:
            logger.error(f"Could not import badge award function: {e}")
        except Exception as e:
            logger.error(f"Error in badge award during profile update: {str(e)}", exc_info=True)

    db.session.commit()

    response = {'message': 'Profile updated successfully'}
    
    # Include badge info if award was attempted
    if badge_award_result and badge_award_result['success'] and not badge_award_result.get('already_owned'):
        response['badge_awarded'] = True
        response['badge_info'] = {
            'badge_id': badge_award_result.get('badge_id'),
            'badge_name': badge_award_result.get('badge_name')
        }
    
    return jsonify(response)


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


import logging
logger = logging.getLogger(__name__)

@user_bp.route('/complete-profile', methods=['POST'])
@jwt_required()
def complete_profile():
    """
    Complete user profile after OAuth signup.
    Auto-awards university badge if university is set.
    """
    badge_award_result = None
    
    try:
        current_user_id = get_jwt_identity()
        user = Users.query.get(current_user_id)
        
        if not user:
            logger.warning(f"Complete profile: User {current_user_id} not found")
            return jsonify({'error': 'User not found'}), 404
            
        data = request.get_json()
        logger.info(f"Complete profile request for user {current_user_id}: {data}")
        
        # Basic fields
        if 'username' in data:
            username = data['username'].strip()
            # Validate username
            import re
            if not re.match(r'^[a-z0-9_]+$', username):
                return jsonify({'error': 'Username can only contain lowercase letters, numbers, and underscores'}), 400
            
            # Check uniqueness
            existing = Users.query.filter(Users.username == username).first()
            if existing and existing.id != user.id:
                 return jsonify({'error': 'Username already taken'}), 400
                 
            user.username = username
            
        if 'display_name' in data:
            user.display_name = data['display_name']
            
        if 'category' in data:
            user.category = data['category']
            
        if 'phone_no' in data:
            user.phone_no = data['phone_no']
            
        if 'bio' in data:
            user.bio = data['bio']
            
        # University fields
        if 'university' in data:
            user.university = data['university']
            
        if 'faculty' in data:
            user.faculty = data['faculty']
            
        if 'course' in data:
            user.course = data['course']
            
        user.profile_completed = True
        
        # LOGIC: Auto-Award University Badge using the centralized helper
        if user.university:
            try:
                from views.badges_view import auto_award_university_badge
                
                logger.info(f"Attempting to auto-award university badge for user {user.id}, university: {user.university}")
                
                # Don't commit here - we'll commit everything together
                badge_award_result = auto_award_university_badge(
                    user_id=user.id, 
                    university_name=user.university,
                    commit=False
                )
                
                if badge_award_result['success']:
                    if badge_award_result['already_owned']:
                        logger.info(f"User {user.id} already has badge: {badge_award_result['badge_name']}")
                    else:
                        logger.info(f"Badge {badge_award_result['badge_id']} will be awarded to user {user.id}")
                else:
                    logger.warning(f"Badge award failed: {badge_award_result['message']}")
                    
            except ImportError as e:
                logger.error(f"Could not import badge award function: {e}")
                badge_award_result = {'success': False, 'message': 'Badge system temporarily unavailable'}
            except Exception as e:
                logger.error(f"Error in badge award logic: {str(e)}", exc_info=True)
                badge_award_result = {'success': False, 'message': str(e)}
        
        # Commit all changes together
        db.session.commit()
        logger.info(f"Profile completed and committed for user {user.id}")
        
        response_data = {
            'message': 'Profile completed successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'is_profile_complete': True
            }
        }
        
        # Include badge award info in response
        if badge_award_result:
            response_data['badge_awarded'] = badge_award_result['success'] and not badge_award_result.get('already_owned', False)
            response_data['badge_info'] = {
                'badge_id': badge_award_result.get('badge_id'),
                'badge_name': badge_award_result.get('badge_name'),
                'message': badge_award_result.get('message')
            }
        
        return jsonify(response_data), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error completing profile for user {current_user_id}: {str(e)}", exc_info=True)
        return jsonify({'error': 'Failed to complete profile. Please try again.'}), 500



# Delete user
@user_bp.route("/deleteuser", methods=["DELETE"])
@jwt_required()
def delete_user():
    current_user_id = get_jwt_identity()
    user = Users.query.get(current_user_id)
    
    if not user:
        return jsonify({"message": "User you are trying to delete is not found!"}), 404

    # Check for critical dependencies (like owned communities)
    owned_communities = Community.query.filter_by(created_by=user.id).all()
    if owned_communities:
        community_names = ", ".join([c.name for c in owned_communities])
        return jsonify({
            "message": f"Unable to delete account. You are the owner of the following communities: {community_names}. Please transfer ownership or delete them first."
        }), 400

    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"message": "User deleted successfully"}), 200
    except IntegrityError as e:
        db.session.rollback()
        # Log error in production
        print(f"Delete Account IntegrityError: {str(e)}")
        # Check for other common constraints
        return jsonify({
            "message": "Unable to delete account due to existing data relationships. Please clear your created data (e.g. Polls, Orders) first or contact support."
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"An error occurred: {str(e)}"}), 500

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
