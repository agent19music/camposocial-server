from models import db, YapMedia, Yap, Users, Like, Reply, Badge, UserBadge, Community
from flask import request, jsonify, Blueprint, make_response
from werkzeug.security import generate_password_hash
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func, case
from datetime import datetime, timedelta
import base64
import os
import boto3
import re
from websocket_handlers import notify_new_yap
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from sqlalchemy import desc
from botocore.exceptions import NoCredentialsError
load_dotenv()

yap_bp = Blueprint('yap', __name__)


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

r2_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

def upload_media_to_r2(file_content, file_name, content_type):
    try:
        # Upload the file to R2
        r2_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=file_name,
            Body=file_content,
            ContentType=content_type
        )
        return f"{R2_ENDPOINT_URL}/{R2_BUCKET_NAME}/{file_name}"

    except NoCredentialsError:
        raise Exception("R2 credentials are incorrect or missing.")
    except Exception as e:
        raise Exception(f"An error occurred while uploading to R2: {str(e)}")

@yap_bp.route('/add_yap', methods=['POST'])
@jwt_required()
def add_yap():
    try:
        data = request.form  # Use form data to handle text and file uploads
        files = request.files.getlist('media')  # Get media files (images/videos)
        
        # Get user from JWT
        user_id = get_jwt_identity()

        # Yap content and location (optional)
        content = data.get('content')
        location = data.get('location', None)
        original_yap_id = data.get('original_yap_id', None)
        poll_id = data.get('poll_id', None)  # Optional poll reference

        if not content:
            return jsonify({"error": "Content is required"}), 400

        # List to hold media URLs after successful upload
        uploaded_media = []

        # Handle media uploads if any
        if files:
            for file in files:
                if file:
                    filename = secure_filename(file.filename)
                    file_ext = filename.split('.')[-1].lower()

                    # Validate media type
                    if file_ext not in ['jpg', 'jpeg', 'png', 'gif', 'mp4', 'mov', 'avif', 'webp']:
                        return jsonify({"error": f"Invalid file type: {file_ext}"}), 400

                    # Set media type
                    media_type = 'image' if file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'avif'] else 'video'

                    # Define the S3 (R2) file path
                    s3_path = f"yaps/{user_id}/{filename}"

                    # Upload the file to the R2 bucket
                    try:
                        s3_client.upload_fileobj(
                            file,
                            os.getenv('R2_BUCKET_NAME'),
                            s3_path,
                            ExtraArgs={'ACL': 'public-read'}
                        )
                    except Exception as e:
                        return jsonify({"error": f"Error uploading media: {str(e)}"}), 500

                    # Generate the R2 URL for the uploaded media
                    r2_url = f"{IMAGE_PREFIX}/{s3_path}"

                    # Add the uploaded media details to the list
                    uploaded_media.append({
                        "media_url": r2_url,
                        "media_type": media_type
                    })

        # Now add the Yap to the database since media uploads are successful
        new_yap = Yap(
            content=content,
            user_id=user_id,
            location=location,
            original_yap_id=original_yap_id,
            poll_id=poll_id,  # Link to poll if provided
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        db.session.add(new_yap)
        db.session.flush()  # Flush to get new_yap.id

        # Add media entries to the database (if any were uploaded)
        for media in uploaded_media:
            new_media = YapMedia(
                yap_id=new_yap.id,
                media_url=media['media_url'],
                media_type=media['media_type']
            )
            db.session.add(new_media)

        # Extract and process hashtags from content
        import re
        from models import Hashtag, YapHashtag
        hashtag_pattern = r'#(\w+)'
        hashtags = re.findall(hashtag_pattern, content)
        
        for hashtag_name in hashtags:
            hashtag_name = hashtag_name.lower()
            
            # Check if hashtag exists, create if not
            hashtag = Hashtag.query.filter_by(name=hashtag_name).first()
            if not hashtag:
                hashtag = Hashtag(name=hashtag_name)
                db.session.add(hashtag)
                db.session.flush()  # Get hashtag ID
            
            # Link hashtag to yap
            yap_hashtag = YapHashtag(yap_id=new_yap.id, hashtag_id=hashtag.id)
            db.session.add(yap_hashtag)

        # Extract and process @mentions from content
        from models import YapMention, Notification, Follow
        mention_pattern = r'@(\w+)'
        mentions = re.findall(mention_pattern, content)
        
        mentioned_user_ids = set()  # Track to avoid duplicate mentions
        for username in mentions:
            # Find the mentioned user
            mentioned_user = Users.query.filter(func.lower(Users.username) == username.lower()).first()
            if not mentioned_user or mentioned_user.id == user_id or mentioned_user.id in mentioned_user_ids:
                continue  # Skip if user not found, self-mention, or duplicate
            
            # Check if user allows being tagged based on who_can_tag setting
            can_tag = False
            tag_setting = mentioned_user.who_can_tag or 'everyone'
            
            if tag_setting == 'everyone':
                can_tag = True
            elif tag_setting == 'followers':
                # Check if current user follows the mentioned user
                is_follower = Follow.query.filter_by(
                    follower_id=user_id,
                    following_id=mentioned_user.id
                ).first() is not None
                can_tag = is_follower
            # 'nobody' = can_tag stays False
            
            if can_tag:
                # Create mention record
                yap_mention = YapMention(
                    yap_id=new_yap.id,
                    mentioned_user_id=mentioned_user.id
                )
                db.session.add(yap_mention)
                mentioned_user_ids.add(mentioned_user.id)
                
                # Create notification for the mentioned user
                notification = Notification(
                    type='MENTION',
                    recipient_id=mentioned_user.id,
                    sender_id=user_id,
                    yap_id=new_yap.id
                )
                db.session.add(notification)

        # Commit the session to finalize changes
        db.session.commit()

        # Broadcast new yap to followers
        from websocket_handlers import broadcast_new_yap_to_followers
        broadcast_new_yap_to_followers(new_yap.id, user_id)

        return jsonify({
            "message": "Yap added successfully!",
            "yap_id": new_yap.id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@yap_bp.route('/yaps', methods=['GET'])
def fetch_yaps():
    try:
        # Get pagination parameters (if provided)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        # Fetch yaps with pagination, ordering by creation date (newest first)
        # Filter out soft-deleted yaps and private community yaps
        yaps = Yap.query.outerjoin(Community, Yap.community_id == Community.id).filter(
            or_(Yap.is_deleted == False, Yap.is_deleted.is_(None)),
            or_(
                Yap.community_id.is_(None),  # Regular yaps
                Community.privacy_type == 'public'  # Only public community yaps
            )
        ).order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)

        # Serialize yaps into JSON format
        yaps_list = []
        for yap in yaps.items:
            # Get user's displayed badges
            user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                UserBadge.user_id == yap.user_id,
                UserBadge.is_displayed == True
            ).order_by(UserBadge.display_order).limit(3).all()
            
            badges_data = []
            for user_badge, badge in user_badges:
                badges_data.append({
                    'id': badge.id,
                    'name': badge.name,
                    'image_url': badge.image_url,
                    'is_animated': badge.is_animated
                })
            
            # If this is a retweet, get original yap data
            original_yap_data = None
            if yap.original_yap_id:
                original_yap = Yap.query.get(yap.original_yap_id)
                if original_yap:
                    # Get original user's badges
                    original_user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                        UserBadge.user_id == original_yap.user_id,
                        UserBadge.is_displayed == True
                    ).order_by(UserBadge.display_order).limit(3).all()
                    
                    original_badges_data = []
                    for user_badge, badge in original_user_badges:
                        original_badges_data.append({
                            'id': badge.id,
                            'name': badge.name,
                            'image_url': badge.image_url,
                            'is_animated': badge.is_animated
                        })
                    
                    original_yap_data = {
                        'id': original_yap.id,
                        'content': original_yap.content,
                        'timestamp': original_yap.created_at,
                        'updated_at': original_yap.updated_at,
                        'location': original_yap.location,
                        'user_id': original_yap.user_id,
                        'display_name': original_yap.user.display_name,
                        'community': original_yap.community,
                        'username': original_yap.user.username,
                        'avatar': original_yap.user.avatar,
                        'original_yap_id': original_yap.original_yap_id,
                        'replies_count': len(original_yap.replies),
                        'likes_count': len(original_yap.likes),
                        'retweets_count': len(original_yap.retweets),
                        'badges': original_badges_data,
                        'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in original_yap.media] if original_yap.media else [],
                        'hashtags': [hashtag.hashtag.name for hashtag in original_yap.hashtags] if original_yap.hashtags else []
                    }
            
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name' : yap.user.display_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'original_yap': original_yap_data,
                'is_retweet': bool(yap.original_yap_id),
                'is_quote': bool(yap.original_yap_id and yap.content.strip()),
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'badges': badges_data,
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else [],
                'community': {
                    'slug': yap.community.slug,
                    'name': yap.community.name,
                    'icon_image': yap.community.icon_image
                } if yap.community_id else None
            })

        # Return JSON response with pagination info
        return jsonify({
            'yaps': yaps_list,
            'page': yaps.page,
            'pages': yaps.pages,
            'total_yaps': yaps.total,
            'has_next': yaps.has_next,
            'has_prev': yaps.has_prev
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@yap_bp.route('/yaps/<string:yap_id>', methods=['GET'])
def get_specific_yap(yap_id):
    try:
        yap = Yap.query.get(yap_id)
        if not yap:
            return jsonify({'error': 'Yap not found'}), 404

        # Get user's displayed badges
        user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
            UserBadge.user_id == yap.user_id,
            UserBadge.is_displayed == True
        ).order_by(UserBadge.display_order).limit(3).all()
        
        badges_data = []
        for user_badge, badge in user_badges:
            badges_data.append({
                'id': badge.id,
                'name': badge.name,
                'image_url': badge.image_url,
                'is_animated': badge.is_animated
            })

        # If this is a retweet, get original yap data
        original_yap_data = None
        if yap.original_yap_id:
            original_yap = Yap.query.get(yap.original_yap_id)
            if original_yap:
                # Get original user's badges
                original_user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                    UserBadge.user_id == original_yap.user_id,
                    UserBadge.is_displayed == True
                ).order_by(UserBadge.display_order).limit(3).all()
                
                original_badges_data = []
                for user_badge, badge in original_user_badges:
                    original_badges_data.append({
                        'id': badge.id,
                        'name': badge.name,
                        'image_url': badge.image_url,
                        'is_animated': badge.is_animated
                    })
                
                original_yap_data = {
                    'id': original_yap.id,
                    'content': original_yap.content,
                    'timestamp': original_yap.created_at,
                    'updated_at': original_yap.updated_at,
                    'location': original_yap.location,
                    'user_id': original_yap.user_id,
                    'display_name': original_yap.user.display_name,
                    'username': original_yap.user.username,
                    'avatar': original_yap.user.avatar,
                    'original_yap_id': original_yap.original_yap_id,
                    'replies_count': len(original_yap.replies),
                    'likes_count': len(original_yap.likes),
                    'retweets_count': len(original_yap.retweets),
                    'badges': original_badges_data,
                    'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in original_yap.media] if original_yap.media else [],
                    'hashtags': [hashtag.hashtag.name for hashtag in original_yap.hashtags] if original_yap.hashtags else []
                }

        # Serialize yap with its replies
        yap_data = {
            'id': yap.id,
            'content': yap.content,
            'timestamp': yap.created_at,
            'updated_at': yap.updated_at,
            'location': yap.location,
            'user_id': yap.user_id,
            'display_name': yap.user.display_name,
            'username': yap.user.username,
            'avatar': yap.user.avatar,
            'original_yap_id': yap.original_yap_id,
            'original_yap': original_yap_data,
            'is_retweet': bool(yap.original_yap_id),
            'is_quote': bool(yap.original_yap_id and yap.content.strip()),
            'replies': [{
                'id': reply.id,
                'content': reply.content,
                'created_at': reply.created_at,
                'parent_reply_id': reply.parent_reply_id,
                'user': {
                    'id': str(reply.user.id),
                    'username': reply.user.username,
                    'display_name': reply.user.display_name,
                    'avatar': reply.user.avatar
                },
                'likes_count': len([like for like in yap.likes if like.reply_id == reply.id]) if hasattr(reply, 'id') else 0,
                'child_replies_count': len(reply.child_replies) if hasattr(reply, 'child_replies') else 0,
                'child_replies': [{
                    'id': child.id,
                    'content': child.content,
                    'created_at': child.created_at,
                    'parent_reply_id': child.parent_reply_id,
                    'user': {
                        'id': str(child.user.id),
                        'username': child.user.username,
                        'display_name': child.user.display_name,
                        'avatar': child.user.avatar
                    },
                    'likes_count': 0  # Will be fetched separately if needed
                } for child in reply.child_replies[:3]] if hasattr(reply, 'child_replies') else []
            } for reply in yap.replies if not reply.parent_reply_id],  # Only top-level replies
            'replies_count': len(yap.replies),
            'likes_count': len(yap.likes),
            'retweets_count': len(yap.retweets),
            'badges': badges_data,
            'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
            'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else []
        }

        return jsonify(yap_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

@yap_bp.route('/users/<int:user_id>/yaps', methods=['GET'])
def get_user_yaps(user_id):
    try:
        # Get pagination parameters (if provided)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        # Fetch user's yaps with pagination, ordering by creation date (newest first)
        # Filter out private community yaps
        yaps = Yap.query.outerjoin(Community, Yap.community_id == Community.id).filter(
            Yap.user_id == user_id,
            or_(
                Yap.community_id.is_(None),  # Regular yaps
                Community.privacy_type == 'public'  # Only public community yaps
            )
        ).order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)

        # Serialize yaps into JSON format
        yaps_list = []
        for yap in yaps.items:
            # If this is a retweet, get original yap data
            original_yap_data = None
            if yap.original_yap_id:
                original_yap = Yap.query.get(yap.original_yap_id)
                if original_yap:
                    # Get original user's badges
                    original_user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                        UserBadge.user_id == original_yap.user_id,
                        UserBadge.is_displayed == True
                    ).order_by(UserBadge.display_order).limit(3).all()
                    
                    original_badges_data = []
                    for user_badge, badge in original_user_badges:
                        original_badges_data.append({
                            'id': badge.id,
                            'name': badge.name,
                            'image_url': badge.image_url,
                            'is_animated': badge.is_animated
                        })
                    
                    original_yap_data = {
                        'id': original_yap.id,
                        'content': original_yap.content,
                        'timestamp': original_yap.created_at,
                        'updated_at': original_yap.updated_at,
                        'location': original_yap.location,
                        'user_id': original_yap.user_id,
                        'display_name': original_yap.user.display_name,
                        'username': original_yap.user.username,
                        'avatar': original_yap.user.avatar,
                        'original_yap_id': original_yap.original_yap_id,
                        'replies_count': len(original_yap.replies),
                        'likes_count': len(original_yap.likes),
                        'retweets_count': len(original_yap.retweets),
                        'badges': original_badges_data,
                        'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in original_yap.media] if original_yap.media else [],
                        'hashtags': [hashtag.hashtag.name for hashtag in original_yap.hashtags] if original_yap.hashtags else []
                    }
            
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name': yap.user.display_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'original_yap': original_yap_data,
                'is_retweet': bool(yap.original_yap_id),
                'is_quote': bool(yap.original_yap_id and yap.content.strip()),
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else [],
                'community': {
                    'slug': yap.community.slug,
                    'name': yap.community.name,
                    'icon_image': yap.community.icon_image
                } if yap.community_id else None
            })

        return jsonify({
            'yaps': yaps_list,
            'page': yaps.page,
            'pages': yaps.pages,
            'total_yaps': yaps.total,
            'has_next': yaps.has_next,
            'has_prev': yaps.has_prev
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Like/Unlike Yap endpoint
@yap_bp.route('/yaps/<string:yap_id>/like', methods=['POST'])
@jwt_required()
def toggle_like_yap(yap_id):
    try:
        user_id = get_jwt_identity()
        
        # Check if yap exists
        yap = Yap.query.get(yap_id)
        if not yap:
            return jsonify({'error': 'Yap not found'}), 404
            
        # Check if user already liked this yap
        existing_like = Like.query.filter_by(user_id=user_id, yap_id=yap_id).first()
        
        if existing_like:
            # Unlike the yap
            db.session.delete(existing_like)
            db.session.commit()
            return jsonify({
                'message': 'Yap unliked successfully',
                'liked': False,
                'likes_count': len(yap.likes)
            }), 200
        else:
            # Like the yap
            new_like = Like(user_id=user_id, yap_id=yap_id)
            db.session.add(new_like)
            
            # Create notification for the yap author (if not self-like)
            if yap.user_id != user_id:
                from models import Notification
                notification = Notification(
                    type='LIKE',
                    recipient_id=yap.user_id,
                    sender_id=user_id,
                    yap_id=yap_id
                )
                db.session.add(notification)
            
            db.session.commit()
            
            # Send real-time notification if not self-like
            if yap.user_id != user_id:
                from websocket_handlers import notify_yap_like
                notify_yap_like(yap.user_id, user_id, yap_id)
            
            return jsonify({
                'message': 'Yap liked successfully',
                'liked': True,
                'likes_count': len(yap.likes)
            }), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Add Reply to Yap endpoint
@yap_bp.route('/yaps/<string:yap_id>/reply', methods=['POST'])
@jwt_required()
def add_reply(yap_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        content = data.get('content')
        parent_reply_id = data.get('parent_reply_id')  # For threaded replies
        
        if not content:
            return jsonify({'error': 'Content is required'}), 400
            
        # Check if yap exists
        yap = Yap.query.get(yap_id)
        if not yap:
            return jsonify({'error': 'Yap not found'}), 404
            
        # Create new reply
        new_reply = Reply(
            content=content,
            user_id=user_id,
            yap_id=yap_id,
            parent_reply_id=parent_reply_id
        )
        
        db.session.add(new_reply)
        
        # Create notification for the yap author (if not self-reply)
        if yap.user_id != user_id:
            from models import Notification
            notification = Notification(
                type='REPLY',
                recipient_id=yap.user_id,
                sender_id=user_id,
                yap_id=yap_id,
                reply_id=new_reply.id
            )
            db.session.add(notification)
        
        db.session.commit()
        
        # Send real-time notification if not self-reply
        if yap.user_id != user_id:
            from websocket_handlers import notify_new_reply
            notify_new_reply(yap.user_id, user_id, yap_id, content)
        
        # Return the new reply with user info
        user = Users.query.get(user_id)
        return jsonify({
            'message': 'Reply added successfully',
            'reply': {
                'id': new_reply.id,
                'content': new_reply.content,
                'created_at': new_reply.created_at,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar
                },
                'parent_reply_id': parent_reply_id
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Like/Unlike Reply endpoint
@yap_bp.route('/replies/<int:reply_id>/like', methods=['POST'])
@jwt_required()
def toggle_like_reply(reply_id):
    try:
        user_id = get_jwt_identity()
        
        # Check if reply exists
        reply = Reply.query.get(reply_id)
        if not reply:
            return jsonify({'error': 'Reply not found'}), 404
            
        # Check if user already liked this reply
        existing_like = Like.query.filter_by(user_id=user_id, reply_id=reply_id).first()
        
        if existing_like:
            # Unlike the reply
            db.session.delete(existing_like)
            db.session.commit()
            # Get updated count
            likes_count = Like.query.filter_by(reply_id=reply_id).count()
            return jsonify({
                'message': 'Reply unliked successfully',
                'liked': False,
                'likes_count': likes_count
            }), 200
        else:
            # Like the reply
            new_like = Like(user_id=user_id, reply_id=reply_id)
            db.session.add(new_like)
            
            # Create notification for the reply author (if not self-like)
            if reply.user_id != user_id:
                from models import Notification
                notification = Notification(
                    type='LIKE',
                    recipient_id=reply.user_id,
                    sender_id=user_id,
                    reply_id=reply_id
                )
                db.session.add(notification)
            
            db.session.commit()
            
            # Get updated count
            likes_count = Like.query.filter_by(reply_id=reply_id).count()
            
            return jsonify({
                'message': 'Reply liked successfully',
                'liked': True,
                'likes_count': likes_count
            }), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Retweet Yap endpoint (Pure retweet - no content)
@yap_bp.route('/yaps/<string:yap_id>/retweet', methods=['POST'])
@jwt_required()
def retweet_yap(yap_id):
    try:
        user_id = get_jwt_identity()
        
        # Check if original yap exists
        original_yap = Yap.query.get(yap_id)
        if not original_yap:
            return jsonify({'error': 'Yap not found'}), 404
            
        # Check if user already retweeted this yap (both pure and quote retweets)
        existing_retweet = Yap.query.filter_by(user_id=user_id, original_yap_id=yap_id).first()
        if existing_retweet:
            return jsonify({'error': 'You have already retweeted this yap'}), 400
            
        # Create pure retweet (empty content)
        new_retweet = Yap(
            content='',  # Empty content for pure retweets
            user_id=user_id,
            original_yap_id=yap_id
        )
        
        db.session.add(new_retweet)
        
        # Create notification for the original yap author (if not self-retweet)
        if original_yap.user_id != user_id:
            from models import Notification
            notification = Notification(
                type='RETWEET',
                recipient_id=original_yap.user_id,
                sender_id=user_id,
                yap_id=yap_id
            )
            db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Yap retweeted successfully',
            'retweet_id': new_retweet.id,
            'retweets_count': len(original_yap.retweets),
            'is_quote': False
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Quote Tweet endpoint (Retweet with user commentary)
@yap_bp.route('/yaps/<string:yap_id>/quote', methods=['POST'])
@jwt_required()
def quote_tweet_yap(yap_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        # Check if original yap exists
        original_yap = Yap.query.get(yap_id)
        if not original_yap:
            return jsonify({'error': 'Yap not found'}), 404
            
        # Check if user already retweeted this yap (both pure and quote retweets)
        existing_retweet = Yap.query.filter_by(user_id=user_id, original_yap_id=yap_id).first()
        if existing_retweet:
            return jsonify({'error': 'You have already retweeted this yap'}), 400
            
        # Get quote content - must have content for quote tweets
        quote_content = data.get('content', '').strip()
        if not quote_content:
            return jsonify({'error': 'Quote content is required'}), 400
            
        # Create quote retweet
        new_quote = Yap(
            content=quote_content,
            user_id=user_id,
            original_yap_id=yap_id
        )
        
        db.session.add(new_quote)
        
        # Create notification for the original yap author (if not self-quote)
        if original_yap.user_id != user_id:
            from models import Notification
            notification = Notification(
                type='QUOTE',
                recipient_id=original_yap.user_id,
                sender_id=user_id,
                yap_id=yap_id
            )
            db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Quote tweet posted successfully',
            'quote_id': new_quote.id,
            'retweets_count': len(original_yap.retweets),
            'is_quote': True
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Get trending yaps (algorithmic feed)
@yap_bp.route('/yaps/trending', methods=['GET'])
@jwt_required()
def get_trending_yaps():
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Calculate trending score based on engagement in last 24 hours
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        # Complex trending algorithm
        trending_yaps = db.session.query(
            Yap,
            (
                # Like weight: 1 point each
                func.count(Like.id).filter(Like.created_at >= twenty_four_hours_ago) * 1 +
                # Reply weight: 3 points each (higher engagement)
                func.count(Reply.id).filter(Reply.created_at >= twenty_four_hours_ago) * 3 +
                # Retweet weight: 2 points each
                func.count(Yap.id).filter(Yap.original_yap_id == Yap.id, Yap.created_at >= twenty_four_hours_ago) * 2 +
                # Recency bonus: newer yaps get slight boost
                case(
                    (Yap.created_at >= twenty_four_hours_ago, 5),
                    (Yap.created_at >= datetime.utcnow() - timedelta(hours=48), 2),
                    else_=0
                )
            ).label('trending_score')
        ).outerjoin(Like, Like.yap_id == Yap.id
        ).outerjoin(Reply, Reply.yap_id == Yap.id
        ).outerjoin(Community, Yap.community_id == Community.id
        ).filter(
            Yap.created_at >= datetime.utcnow() - timedelta(days=7),  # Only yaps from last week
            or_(Yap.is_deleted == False, Yap.is_deleted.is_(None)),
            or_(
                Yap.community_id.is_(None),  # Regular yaps
                Community.privacy_type == 'public'  # Only public community yaps
            )
        ).group_by(Yap.id
        ).order_by(func.count(Like.id).desc(), Yap.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # Serialize trending yaps
        yaps_list = []
        for yap, trending_score in trending_yaps.items:
            # Get user's displayed badges
            user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                UserBadge.user_id == yap.user_id,
                UserBadge.is_displayed == True
            ).order_by(UserBadge.display_order).limit(3).all()
            
            badges_data = []
            for user_badge, badge in user_badges:
                badges_data.append({
                    'id': badge.id,
                    'name': badge.name,
                    'image_url': badge.image_url,
                    'is_animated': badge.is_animated
                })
            
            # If this is a retweet, get original yap data
            original_yap_data = None
            if yap.original_yap_id:
                original_yap = Yap.query.get(yap.original_yap_id)
                if original_yap:
                    # Get original user's badges
                    original_user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                        UserBadge.user_id == original_yap.user_id,
                        UserBadge.is_displayed == True
                    ).order_by(UserBadge.display_order).limit(3).all()
                    
                    original_badges_data = []
                    for user_badge, badge in original_user_badges:
                        original_badges_data.append({
                            'id': badge.id,
                            'name': badge.name,
                            'image_url': badge.image_url,
                            'is_animated': badge.is_animated
                        })
                    
                    original_yap_data = {
                        'id': original_yap.id,
                        'content': original_yap.content,
                        'timestamp': original_yap.created_at,
                        'updated_at': original_yap.updated_at,
                        'location': original_yap.location,
                        'user_id': original_yap.user_id,
                        'display_name': original_yap.user.display_name,
                        'username': original_yap.user.username,
                        'avatar': original_yap.user.avatar,
                        'original_yap_id': original_yap.original_yap_id,
                        'replies_count': len(original_yap.replies),
                        'likes_count': len(original_yap.likes),
                        'retweets_count': len(original_yap.retweets),
                        'badges': original_badges_data,
                        'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in original_yap.media] if original_yap.media else [],
                        'hashtags': [hashtag.hashtag.name for hashtag in original_yap.hashtags] if original_yap.hashtags else []
                    }
            
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name': yap.user.display_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'original_yap': original_yap_data,
                'is_retweet': bool(yap.original_yap_id),
                'is_quote': bool(yap.original_yap_id and yap.content.strip()),
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'trending_score': float(trending_score) if trending_score else 0,
                'badges': badges_data,
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else []
            })
        
        return jsonify({
            'yaps': yaps_list,
            'page': trending_yaps.page,
            'pages': trending_yaps.pages,
            'total_yaps': trending_yaps.total,
            'has_next': trending_yaps.has_next,
            'has_prev': trending_yaps.has_prev
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Get hashtag suggestions
@yap_bp.route('/hashtags/suggestions', methods=['GET'])
@jwt_required()
def get_hashtag_suggestions():
    try:
        query = request.args.get('q', '').lower()
        limit = request.args.get('limit', 10, type=int)
        
        from models import Hashtag, YapHashtag
        
        if query:
            # Search hashtags that start with query
            hashtags = db.session.query(
                Hashtag.name,
                func.count(YapHashtag.id).label('usage_count')
            ).join(YapHashtag
            ).filter(
                Hashtag.name.ilike(f'{query}%')
            ).group_by(Hashtag.name
            ).order_by(func.count(YapHashtag.id).desc()
            ).limit(limit).all()
        else:
            # Get trending hashtags from last 7 days
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            hashtags = db.session.query(
                Hashtag.name,
                func.count(YapHashtag.id).label('usage_count')
            ).join(YapHashtag
            ).join(Yap, Yap.id == YapHashtag.yap_id
            ).filter(
                Yap.created_at >= seven_days_ago
            ).group_by(Hashtag.name
            ).order_by(func.count(YapHashtag.id).desc()
            ).limit(limit).all()
        
        suggestions = [{'name': hashtag.name, 'usage_count': hashtag.usage_count} for hashtag in hashtags]
        
        return jsonify({'hashtags': suggestions}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Get who to follow suggestions
@yap_bp.route('/yaps/who-to-follow/suggestions', methods=['GET'])
@jwt_required()
def get_who_to_follow_suggestions():
    try:
        current_user_id = get_jwt_identity()
        limit = request.args.get('limit', 10, type=int)
        
        from models import Follow, Users, Yap, Like, Reply
        
        # Get users that the current user already follows
        following_ids = db.session.query(Follow.following_id).filter_by(follower_id=current_user_id).all()
        following_ids = [f.following_id for f in following_ids]
        following_ids.append(current_user_id)  # Exclude self
        
        # Get mutual connections (users followed by people the current user follows)
        mutual_connections = db.session.query(
            Follow.following_id,
            func.count(Follow.follower_id).label('mutual_count')
        ).filter(
            Follow.follower_id.in_(following_ids),
            ~Follow.following_id.in_(following_ids)
        ).group_by(Follow.following_id).order_by(
            func.count(Follow.follower_id).desc()
        ).limit(limit * 2).all()
        
        # Get popular users (users with most followers who aren't already followed)
        popular_users = db.session.query(
            Users.id,
            func.count(Follow.follower_id).label('follower_count')
        ).outerjoin(Follow, Follow.following_id == Users.id
        ).filter(
            ~Users.id.in_(following_ids)
        ).group_by(Users.id).order_by(
            func.count(Follow.follower_id).desc()
        ).limit(limit * 2).all()
        
        # Get active users (users who posted recently)
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        active_users = db.session.query(
            Users.id,
            func.count(Yap.id).label('recent_yaps')
        ).outerjoin(Yap, Yap.user_id == Users.id
        ).filter(
            ~Users.id.in_(following_ids),
            or_(Yap.created_at >= seven_days_ago, Yap.id.is_(None))
        ).group_by(Users.id).order_by(
            func.count(Yap.id).desc()
        ).limit(limit * 2).all()
        
        # Combine and score the suggestions
        suggestions = {}
        
        # Add mutual connections with high weight
        for user_id, mutual_count in mutual_connections:
            suggestions[user_id] = {
                'user_id': user_id,
                'score': mutual_count * 3,  # High weight for mutual connections
                'reason': 'mutual_connections'
            }
        
        # Add popular users with medium weight
        for user_id, follower_count in popular_users:
            if user_id in suggestions:
                suggestions[user_id]['score'] += follower_count * 2
                suggestions[user_id]['reason'] = 'popular_and_mutual'
            else:
                suggestions[user_id] = {
                    'user_id': user_id,
                    'score': follower_count * 2,
                    'reason': 'popular'
                }
        
        # Add active users with medium weight
        for user_id, recent_yaps in active_users:
            if user_id in suggestions:
                suggestions[user_id]['score'] += recent_yaps * 1
            else:
                suggestions[user_id] = {
                    'user_id': user_id,
                    'score': recent_yaps * 1,
                    'reason': 'active'
                }
        
        # Sort by score and get user details
        sorted_suggestions = sorted(suggestions.values(), key=lambda x: x['score'], reverse=True)[:limit]
        
        # Get user details for the top suggestions
        user_ids = [s['user_id'] for s in sorted_suggestions]
        users = Users.query.filter(Users.id.in_(user_ids)).all()
        user_dict = {user.id: user for user in users}
        
        # Format the response
        suggestions_data = []
        for suggestion in sorted_suggestions:
            user = user_dict.get(suggestion['user_id'])
            if user:
                # Get follower and following counts
                follower_count = Follow.query.filter_by(following_id=user.id).count()
                following_count = Follow.query.filter_by(follower_id=user.id).count()
                
                suggestions_data.append({
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name or f"{user.first_name} {user.last_name}",
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'avatar': user.avatar,
                    'bio': user.bio,
                    'category': user.category,
                    'follower_count': follower_count,
                    'following_count': following_count,
                    'reason': suggestion['reason'],
                    'score': suggestion['score']
                })
        
        return jsonify({
            'suggestions': suggestions_data,
            'total': len(suggestions_data)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# Get location suggestions
@yap_bp.route('/locations/suggestions', methods=['GET'])
@jwt_required()
def get_location_suggestions():
    try:
        query = request.args.get('q', '').lower()
        limit = request.args.get('limit', 10, type=int)
        
        # Get popular locations from recent yaps
        from datetime import datetime, timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        if query:
            locations = db.session.query(
                Yap.location,
                func.count(Yap.location).label('usage_count')
            ).filter(
                Yap.location.ilike(f'%{query}%'),
                Yap.location.isnot(None),
                Yap.created_at >= thirty_days_ago
            ).group_by(Yap.location
            ).order_by(func.count(Yap.location).desc()
            ).limit(limit).all()
        else:
            # Popular campus locations (you can customize this list)
            default_locations = [
                'Main Campus', 'Library', 'Student Center', 'Cafeteria', 'Dormitories',
                'Sports Complex', 'Lecture Halls', 'Computer Lab', 'Study Room', 'Parking Lot'
            ]
            locations = [(loc, 0) for loc in default_locations[:limit]]
        
        suggestions = [{'name': location[0], 'usage_count': location[1]} for location in locations if location[0]]
        
        return jsonify({'locations': suggestions}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Get user replies for profile page
@yap_bp.route('/yap/profile/<string:username>/replies', methods=['GET'])
def get_user_replies(username):
    try:
        # Find user by username
        user = Users.query.filter_by(username=username).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # Fetch all replies by this user with the parent yap info
        replies = Reply.query.filter_by(user_id=user.id).order_by(desc(Reply.created_at)).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Serialize replies with parent yap context
        replies_list = []
        for reply in replies.items:
            # Get the parent yap
            parent_yap = Yap.query.get(reply.yap_id)
            if not parent_yap:
                continue  # Skip if parent yap no longer exists
            
            # Get parent yap author badges
            parent_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                UserBadge.user_id == parent_yap.user_id,
                UserBadge.is_displayed == True
            ).order_by(UserBadge.display_order).limit(3).all()
            
            parent_badges_data = []
            for user_badge, badge in parent_badges:
                parent_badges_data.append({
                    'id': badge.id,
                    'name': badge.name,
                    'image_url': badge.image_url,
                    'is_animated': badge.is_animated
                })
            
            # Format reply with parent yap context
            replies_list.append({
                'id': reply.id,
                'content': reply.content,
                'created_at': reply.created_at,
                'parent_reply_id': reply.parent_reply_id,
                'user': {
                    'id': str(reply.user.id),
                    'username': reply.user.username,
                    'display_name': reply.user.display_name,
                    'avatar': reply.user.avatar
                },
                'parent_yap': {
                    'id': parent_yap.id,
                    'content': parent_yap.content,
                    'timestamp': parent_yap.created_at,
                    'user_id': parent_yap.user_id,
                    'display_name': parent_yap.user.display_name,
                    'username': parent_yap.user.username,
                    'avatar': parent_yap.user.avatar,
                    'replies_count': len(parent_yap.replies),
                    'likes_count': len(parent_yap.likes),
                    'retweets_count': len(parent_yap.retweets),
                    'badges': parent_badges_data,
                    'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in parent_yap.media] if parent_yap.media else []
                }
            })
        
        return jsonify({
            'replies': replies_list,
            'page': replies.page,
            'pages': replies.pages,
            'total_replies': replies.total,
            'has_next': replies.has_next,
            'has_prev': replies.has_prev
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500




# Get user profile for yap profile screen
@yap_bp.route('/yap/profile/<string:username>', methods=['GET'])
def get_user_profile(username):
    try:
        # Find user by username
        user = Users.query.filter_by(username=username).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        from models import Follow, Badge, UserBadge
        
        # Get follower and following counts
        follower_count = Follow.query.filter_by(following_id=user.id).count()
        following_count = Follow.query.filter_by(follower_id=user.id).count()
        
        # Get user's displayed badges
        user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
            UserBadge.user_id == user.id,
            UserBadge.is_displayed == True
        ).order_by(UserBadge.display_order).limit(3).all()
        
        badges_data = []
        for user_badge, badge in user_badges:
            badges_data.append({
                'id': badge.id,
                'name': badge.name,
                'image_url': badge.image_url,
                'is_animated': badge.is_animated
            })
        
        # Get pagination parameters for user's yaps
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # Fetch user's yaps with pagination, filtering out private community yaps
        yaps = Yap.query.outerjoin(Community, Yap.community_id == Community.id).filter(
            Yap.user_id == user.id,
            or_(
                Yap.community_id.is_(None),  # Regular yaps
                Community.privacy_type == 'public'  # Only public community yaps
            )
        ).order_by(desc(Yap.created_at)).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Serialize user's yaps
        yaps_list = []
        for yap in yaps.items:
            # Get user's displayed badges for the yap author (retweeter)
            user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                UserBadge.user_id == yap.user_id,
                UserBadge.is_displayed == True
            ).order_by(UserBadge.display_order).limit(3).all()
            
            badges_data = []
            for user_badge, badge in user_badges:
                badges_data.append({
                    'id': badge.id,
                    'name': badge.name,
                    'image_url': badge.image_url,
                    'is_animated': badge.is_animated
                })
            
            # If this is a retweet, get original yap data
            original_yap_data = None
            if yap.original_yap_id:
                original_yap = Yap.query.get(yap.original_yap_id)
                if original_yap:
                    # Get original user's badges
                    original_user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                        UserBadge.user_id == original_yap.user_id,
                        UserBadge.is_displayed == True
                    ).order_by(UserBadge.display_order).limit(3).all()
                    
                    original_badges_data = []
                    for user_badge, badge in original_user_badges:
                        original_badges_data.append({
                            'id': badge.id,
                            'name': badge.name,
                            'image_url': badge.image_url,
                            'is_animated': badge.is_animated
                        })
                    
                    original_yap_data = {
                        'id': original_yap.id,
                        'content': original_yap.content,
                        'timestamp': original_yap.created_at,
                        'updated_at': original_yap.updated_at,
                        'location': original_yap.location,
                        'user_id': original_yap.user_id,
                        'display_name': original_yap.user.display_name,
                        'username': original_yap.user.username,
                        'avatar': original_yap.user.avatar,
                        'original_yap_id': original_yap.original_yap_id,
                        'replies_count': len(original_yap.replies),
                        'likes_count': len(original_yap.likes),
                        'retweets_count': len(original_yap.retweets),
                        'badges': original_badges_data,
                        'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in original_yap.media] if original_yap.media else [],
                        'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else []
                    }
            
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name': yap.user.display_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'original_yap': original_yap_data,
                'is_retweet': bool(yap.original_yap_id),
                'is_quote': bool(yap.original_yap_id and yap.content.strip()),
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'badges': badges_data,
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else [],
                'community': {
                    'slug': yap.community.slug,
                    'name': yap.community.name,
                    'icon_image': yap.community.icon_image
                } if yap.community_id else None
            })
        
        # Prepare user profile data
        profile_data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'display_name': user.display_name,
                'bio': user.bio,
                'avatar': user.avatar,
                'category': user.category,
                'join_date': user.created_at,
                'follower_count': follower_count,
                'following_count': following_count,
                'yap_header_img': user.yap_header_img,
                'badges': badges_data
            },
            'yaps': {
                'items': yaps_list,
                'page': yaps.page,
                'pages': yaps.pages,
                'total_yaps': yaps.total,
                'has_next': yaps.has_next,
                'has_prev': yaps.has_prev
            }
        }
        
        return jsonify(profile_data), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Toggle follow/unfollow user
@yap_bp.route('/users/<string:username>/follow', methods=['POST'])
@jwt_required()
def toggle_follow_user(username):
    try:
        current_user_id = get_jwt_identity()
        
        # Find the user to follow/unfollow
        target_user = Users.query.filter_by(username=username).first()
        if not target_user:
            return jsonify({'error': 'User not found'}), 404
        
        # Prevent self-following
        if target_user.id == current_user_id:
            return jsonify({'error': 'You cannot follow yourself'}), 400
        
        from models import Follow
        
        # Check if already following
        existing_follow = Follow.query.filter_by(
            follower_id=current_user_id,
            following_id=target_user.id
        ).first()
        
        if existing_follow:
            # Unfollow
            db.session.delete(existing_follow)
            db.session.commit()
            
            # Get updated counts
            follower_count = Follow.query.filter_by(following_id=target_user.id).count()
            following_count = Follow.query.filter_by(follower_id=target_user.id).count()
            
            return jsonify({
                'message': f'Successfully unfollowed @{username}',
                'is_following': False,
                'follower_count': follower_count,
                'following_count': following_count
            }), 200
        else:
            # Follow
            new_follow = Follow(
                follower_id=current_user_id,
                following_id=target_user.id
            )
            db.session.add(new_follow)
            
            # Create notification for the followed user
            from models import Notification
            notification = Notification(
                type='FOLLOW',
                recipient_id=target_user.id,
                sender_id=current_user_id
            )
            db.session.add(notification)
            
            db.session.commit()
            
            # Get updated counts
            follower_count = Follow.query.filter_by(following_id=target_user.id).count()
            following_count = Follow.query.filter_by(follower_id=target_user.id).count()
            
            return jsonify({
                'message': f'Successfully followed @{username}',
                'is_following': True,
                'follower_count': follower_count,
                'following_count': following_count
            }), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Check if current user is following another user
@yap_bp.route('/users/<string:username>/follow-status', methods=['GET'])
@jwt_required()
def check_follow_status(username):
    try:
        current_user_id = get_jwt_identity()
        
        # Find the target user
        target_user = Users.query.filter_by(username=username).first()
        if not target_user:
            return jsonify({'error': 'User not found'}), 404
        
        from models import Follow
        
        # Check if following
        is_following = Follow.query.filter_by(
            follower_id=current_user_id,
            following_id=target_user.id
        ).first() is not None
        
        # Get counts
        follower_count = Follow.query.filter_by(following_id=target_user.id).count()
        following_count = Follow.query.filter_by(follower_id=target_user.id).count()
        
        return jsonify({
            'is_following': is_following,
            'follower_count': follower_count,
            'following_count': following_count
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Get personalized feed for user (following + algorithmic)
@yap_bp.route('/yaps/feed', methods=['GET'])
@jwt_required()
def get_personalized_feed():
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        feed_type = request.args.get('type', 'mixed')  # 'following', 'trending', 'mixed'
        
        from models import Follow, MutedUser
        from models_blocking import BlockedUser
        from datetime import datetime, timedelta
        
        # Get muted and blocked user IDs to filter from feed
        muted_user_ids = [m.muted_id for m in MutedUser.query.filter_by(muter_id=user_id).all()]
        blocked_user_ids = [b.blocked_id for b in BlockedUser.query.filter_by(blocker_id=user_id).all()]
        blocked_by_ids = [b.blocker_id for b in BlockedUser.query.filter_by(blocked_id=user_id).all()]
        excluded_user_ids = set(muted_user_ids + blocked_user_ids + blocked_by_ids)
        
        # Base filter for non-deleted yaps, excluded users, and private community yaps
        base_filter = [
            or_(Yap.is_deleted == False, Yap.is_deleted.is_(None)),
            or_(
                Yap.community_id.is_(None),  # Regular yaps
                Community.privacy_type == 'public'  # Only public community yaps
            )
        ]
        if excluded_user_ids:
            base_filter.append(~Yap.user_id.in_(excluded_user_ids))
        
        if feed_type == 'following':
            # Get yaps from users the current user follows
            following_user_ids = db.session.query(Follow.following_id).filter_by(follower_id=user_id).all()
            following_ids = [f.following_id for f in following_user_ids] + [user_id]
            # Remove excluded users from following list
            following_ids = [uid for uid in following_ids if uid not in excluded_user_ids]
            
            yaps = Yap.query.outerjoin(Community, Yap.community_id == Community.id).filter(
                Yap.user_id.in_(following_ids),
                *base_filter
            ).order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)
            
        elif feed_type == 'trending':
            # Use the trending algorithm
            return get_trending_yaps()
            
        else:  # mixed feed - simplified version
            # For now, return all recent yaps ordered by creation date with some basic prioritization
            recent_cutoff = datetime.utcnow() - timedelta(days=7)
            
            # Simple query to get recent yaps, prioritizing those with engagement
            yaps = Yap.query.outerjoin(Community, Yap.community_id == Community.id).filter(
                Yap.created_at >= recent_cutoff,
                *base_filter
            ).order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)
        
        # Serialize yaps
        yaps_list = []
        for yap in yaps.items:
            # Get user's displayed badges
            user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                UserBadge.user_id == yap.user_id,
                UserBadge.is_displayed == True
            ).order_by(UserBadge.display_order).limit(3).all()
            
            badges_data = []
            for user_badge, badge in user_badges:
                badges_data.append({
                    'id': badge.id,
                    'name': badge.name,
                    'image_url': badge.image_url,
                    'is_animated': badge.is_animated
                })
            
            # If this is a retweet, get original yap data
            original_yap_data = None
            if yap.original_yap_id:
                original_yap = Yap.query.get(yap.original_yap_id)
                if original_yap:
                    # Get original user's badges
                    original_user_badges = db.session.query(UserBadge, Badge).join(Badge).filter(
                        UserBadge.user_id == original_yap.user_id,
                        UserBadge.is_displayed == True
                    ).order_by(UserBadge.display_order).limit(3).all()
                    
                    original_badges_data = []
                    for user_badge, badge in original_user_badges:
                        original_badges_data.append({
                            'id': badge.id,
                            'name': badge.name,
                            'image_url': badge.image_url,
                            'is_animated': badge.is_animated
                        })
                    
                    original_yap_data = {
                        'id': original_yap.id,
                        'content': original_yap.content,
                        'timestamp': original_yap.created_at,
                        'updated_at': original_yap.updated_at,
                        'location': original_yap.location,
                        'user_id': original_yap.user_id,
                        'display_name': original_yap.user.display_name,
                        'username': original_yap.user.username,
                        'avatar': original_yap.user.avatar,
                        'original_yap_id': original_yap.original_yap_id,
                        'replies_count': len(original_yap.replies),
                        'likes_count': len(original_yap.likes),
                        'retweets_count': len(original_yap.retweets),
                        'badges': original_badges_data,
                        'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in original_yap.media] if original_yap.media else [],
                        'hashtags': [hashtag.hashtag.name for hashtag in original_yap.hashtags] if original_yap.hashtags else []
                    }
            
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name': yap.user.display_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'original_yap': original_yap_data,
                'is_retweet': bool(yap.original_yap_id),
                'is_quote': bool(yap.original_yap_id and yap.content.strip()),
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'badges': badges_data,
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else [],
                'community': {
                    'slug': yap.community.slug,
                    'name': yap.community.name,
                    'icon_image': yap.community.icon_image
                } if yap.community_id else None
            })
        
        return jsonify({
            'yaps': yaps_list,
            'page': yaps.page,
            'pages': yaps.pages,
            'total_yaps': yaps.total,
            'has_next': yaps.has_next,
            'has_prev': yaps.has_prev,
            'feed_type': feed_type
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Delete Yap endpoint (soft delete)
@yap_bp.route('/yaps/<string:yap_id>', methods=['DELETE'])
@jwt_required()
def delete_yap(yap_id):
    try:
        user_id = get_jwt_identity()
        
        # Find the yap
        yap = Yap.query.get(yap_id)
        if not yap:
            return jsonify({'error': 'Yap not found'}), 404
        
        # Check ownership - only the author can delete their yap
        if yap.user_id != user_id:
            return jsonify({'error': 'You can only delete your own yaps'}), 403
        
        # Soft delete the yap
        yap.soft_delete()
        db.session.commit()
        
        return jsonify({
            'message': 'Yap deleted successfully',
            'yap_id': yap_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Mute user endpoint
@yap_bp.route('/users/<string:username>/mute', methods=['POST'])
@jwt_required()
def toggle_mute_user(username):
    try:
        current_user_id = get_jwt_identity()
        
        # Find the user to mute
        target_user = Users.query.filter_by(username=username).first()
        if not target_user:
            return jsonify({'error': 'User not found'}), 404
        
        # Prevent self-muting
        if target_user.id == current_user_id:
            return jsonify({'error': 'You cannot mute yourself'}), 400
        
        from models import MutedUser
        
        # Check if already muted
        existing_mute = MutedUser.query.filter_by(
            muter_id=current_user_id,
            muted_id=target_user.id
        ).first()
        
        if existing_mute:
            # Unmute the user
            db.session.delete(existing_mute)
            db.session.commit()
            return jsonify({
                'message': f'User @{username} unmuted successfully',
                'muted': False,
                'username': username
            }), 200
        else:
            # Mute the user
            new_mute = MutedUser(
                muter_id=current_user_id,
                muted_id=target_user.id
            )
            db.session.add(new_mute)
            db.session.commit()
            return jsonify({
                'message': f'User @{username} muted successfully',
                'muted': True,
                'username': username
            }), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Get muted users list
@yap_bp.route('/users/muted', methods=['GET'])
@jwt_required()
def get_muted_users():
    try:
        current_user_id = get_jwt_identity()
        
        from models import MutedUser
        
        muted_users = MutedUser.query.filter_by(muter_id=current_user_id).all()
        
        muted_list = []
        for mute in muted_users:
            user = Users.query.get(mute.muted_id)
            if user:
                muted_list.append({
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar,
                    'muted_at': mute.created_at.isoformat()
                })
        
        return jsonify({'muted_users': muted_list}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Block user endpoint
@yap_bp.route('/users/<string:username>/block', methods=['POST'])
@jwt_required()
def toggle_block_user(username):
    try:
        current_user_id = get_jwt_identity()
        
        # Find the user to block
        target_user = Users.query.filter_by(username=username).first()
        if not target_user:
            return jsonify({'error': 'User not found'}), 404
        
        # Prevent self-blocking
        if target_user.id == current_user_id:
            return jsonify({'error': 'You cannot block yourself'}), 400
        
        from models import Follow
        from models_blocking import BlockedUser
        
        # Check if already blocked
        existing_block = BlockedUser.query.filter_by(
            blocker_id=current_user_id,
            blocked_id=target_user.id
        ).first()
        
        if existing_block:
            # Unblock the user
            db.session.delete(existing_block)
            db.session.commit()
            return jsonify({
                'message': f'User @{username} unblocked successfully',
                'blocked': False,
                'username': username
            }), 200
        else:
            # Block the user
            new_block = BlockedUser(
                blocker_id=current_user_id,
                blocked_id=target_user.id
            )
            db.session.add(new_block)
            
            # Also unfollow in both directions
            Follow.query.filter_by(follower_id=current_user_id, following_id=target_user.id).delete()
            Follow.query.filter_by(follower_id=target_user.id, following_id=current_user_id).delete()
            
            db.session.commit()
            return jsonify({
                'message': f'User @{username} blocked successfully',
                'blocked': True,
                'username': username
            }), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Get blocked users list
@yap_bp.route('/users/blocked', methods=['GET'])
@jwt_required()
def get_blocked_users():
    try:
        current_user_id = get_jwt_identity()
        
        from models_blocking import BlockedUser
        
        blocked_users = BlockedUser.query.filter_by(blocker_id=current_user_id).all()
        
        blocked_list = []
        for block in blocked_users:
            user = Users.query.get(block.blocked_id)
            if user:
                blocked_list.append({
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'avatar': user.avatar,
                    'blocked_at': block.created_at.isoformat()
                })
        
        return jsonify({'blocked_users': blocked_list}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Check mute/block status for a user
@yap_bp.route('/users/<string:username>/moderation-status', methods=['GET'])
@jwt_required()
def get_moderation_status(username):
    try:
        current_user_id = get_jwt_identity()
        
        target_user = Users.query.filter_by(username=username).first()
        if not target_user:
            return jsonify({'error': 'User not found'}), 404
        
        from models import MutedUser
        from models_blocking import BlockedUser
        
        is_muted = MutedUser.query.filter_by(
            muter_id=current_user_id,
            muted_id=target_user.id
        ).first() is not None
        
        is_blocked = BlockedUser.query.filter_by(
            blocker_id=current_user_id,
            blocked_id=target_user.id
        ).first() is not None
        
        return jsonify({
            'username': username,
            'is_muted': is_muted,
            'is_blocked': is_blocked
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500