from models import db, YapMedia, Yap, Users, Like, Reply
from flask import request, jsonify, Blueprint, make_response
from werkzeug.security import generate_password_hash
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func, case
from datetime import datetime, timedelta
import base64
import os
import boto3
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from sqlalchemy import desc
from botocore.exceptions import NoCredentialsError
load_dotenv()

yap_bp = Blueprint('yap', __name__)


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

        # Commit the session to finalize changes
        db.session.commit()

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
        yaps = Yap.query.order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)

        # Serialize yaps into JSON format
        yaps_list = []
        for yap in yaps.items:
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name' : yap.user.first_name + ' '+ yap.user.last_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else []
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


@yap_bp.route('/api/yaps/<string:yap_id>', methods=['GET'])
def get_specific_yap(yap_id):
    try:
        yap = Yap.query.get(yap_id)
        if not yap:
            return jsonify({'error': 'Yap not found'}), 404

        # Serialize yap with its replies
        yap_data = {
            'id': yap.id,
            'content': yap.content,
            'created_at': yap.created_at,
            'updated_at': yap.updated_at,
            'location': yap.location,
            'user_id': yap.user_id,
            'display_name' : yap.user.first_name + yap.user.last_name,
            'username': yap.user.username,
            'original_yap_id': yap.original_yap_id,
            'replies': [{
                'id': reply.id,
                'content': reply.content,
                'created_at': reply.created_at,
                'user_id': reply.user_id,
                'username': reply.user.username  # Include the username of the reply's author
            } for reply in yap.replies],
            'likes_count': len(yap.likes),
            'media': [{'id': media.id, 'url': media.url} for media in yap.media] if yap.media else [],
            'hashtags': [hashtag.tag for hashtag in yap.hashtags] if yap.hashtags else []
        }

        return jsonify(yap_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

@yap_bp.route('/api/users/<int:user_id>/yaps', methods=['GET'])
def get_user_yaps(user_id):
    try:
        # Get pagination parameters (if provided)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        # Fetch user's yaps with pagination, ordering by creation date (newest first)
        yaps = Yap.query.filter_by(user_id=user_id).order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)

        # Serialize yaps into JSON format
        yaps_list = []
        for yap in yaps.items:
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name': yap.user.first_name + ' ' + yap.user.last_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else []
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
                    'display_name': f"{user.first_name} {user.last_name}",
                    'avatar': user.avatar
                },
                'parent_reply_id': parent_reply_id
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Retweet Yap endpoint
@yap_bp.route('/yaps/<string:yap_id>/retweet', methods=['POST'])
@jwt_required()
def retweet_yap(yap_id):
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
            
        # Get retweet content - empty string means pure retweet
        retweet_content = data.get('content', '').strip()
        
        # Create retweet - for pure retweets (empty content), we'll handle display differently
        new_retweet = Yap(
            content=retweet_content,
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
            'is_quote': bool(retweet_content)  # Indicate if it's a quote tweet
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
        ).filter(
            Yap.created_at >= datetime.utcnow() - timedelta(days=7)  # Only yaps from last week
        ).group_by(Yap.id
        ).order_by(func.count(Like.id).desc(), Yap.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # Serialize trending yaps
        yaps_list = []
        for yap, trending_score in trending_yaps.items:
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name': yap.user.first_name + ' ' + yap.user.last_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'trending_score': float(trending_score) if trending_score else 0,
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


# Get personalized feed for user (following + algorithmic)
@yap_bp.route('/yaps/feed', methods=['GET'])
@jwt_required()
def get_personalized_feed():
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        feed_type = request.args.get('type', 'mixed')  # 'following', 'trending', 'mixed'
        
        from models import Follow
        from datetime import datetime, timedelta
        
        if feed_type == 'following':
            # Get yaps from users the current user follows
            following_user_ids = db.session.query(Follow.following_id).filter_by(follower_id=user_id).all()
            following_ids = [f.following_id for f in following_user_ids] + [user_id]
            
            yaps = Yap.query.filter(
                Yap.user_id.in_(following_ids)
            ).order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)
            
        elif feed_type == 'trending':
            # Use the trending algorithm
            return get_trending_yaps()
            
        else:  # mixed feed - simplified version
            # For now, return all recent yaps ordered by creation date with some basic prioritization
            recent_cutoff = datetime.utcnow() - timedelta(days=7)
            
            # Simple query to get recent yaps, prioritizing those with engagement
            yaps = Yap.query.filter(
                Yap.created_at >= recent_cutoff
            ).order_by(desc(Yap.created_at)).paginate(page=page, per_page=per_page, error_out=False)
        
        # Serialize yaps
        yaps_list = []
        for yap in yaps.items:
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'timestamp': yap.created_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'display_name': yap.user.first_name + ' ' + yap.user.last_name,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'original_yap_id': yap.original_yap_id,
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'retweets_count': len(yap.retweets),
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.hashtag.name for hashtag in yap.hashtags] if yap.hashtags else []
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
