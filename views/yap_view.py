from models import db, YapMedia, Yap, Users
from flask import request, jsonify, Blueprint, make_response
from werkzeug.security import generate_password_hash
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, func
from datetime import datetime
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
                'media': [{'id': media.id, 'url': media.media_url, 'type': media.media_type} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.tag for hashtag in yap.hashtags] if yap.hashtags else []
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
        # Fetch the user by user_id
        user = Users.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Fetch all yaps by the user
        yaps = Yap.query.filter_by(user_id=user_id).order_by(desc(Yap.created_at)).all()

        # Serialize yaps into JSON format
        yaps_list = []
        for yap in yaps:
            yaps_list.append({
                'id': yap.id,
                'content': yap.content,
                'created_at': yap.created_at,
                'updated_at': yap.updated_at,
                'location': yap.location,
                'user_id': yap.user_id,
                'username': yap.user.username,  
                'display_name' : yap.user.first_name + yap.user.last_name,
                'original_yap_id': yap.original_yap_id,
                'replies_count': len(yap.replies),
                'likes_count': len(yap.likes),
                'media': [{'id': media.id, 'url': media.url} for media in yap.media] if yap.media else [],
                'hashtags': [hashtag.tag for hashtag in yap.hashtags] if yap.hashtags else []
            })

        return jsonify({
            'user': {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'image_url': user.image_url
            },
            'yaps': yaps_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
