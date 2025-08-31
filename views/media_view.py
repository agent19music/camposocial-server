import os
import io
import hashlib
import mimetypes
from flask import Blueprint, request, jsonify, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps
import cv2
import numpy as np
from models import db, Users, Message, Conversation
from sqlalchemy import or_, and_
from datetime import datetime
import boto3
from botocore.exceptions import NoCredentialsError
import magic
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

media_bp = Blueprint('media_bp', __name__)

# Configuration
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/tmp/uploads')
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_EXTENSIONS = {
    'image': ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'],
    'video': ['mp4', 'avi', 'mov', 'webm', 'mkv'],
    'audio': ['mp3', 'wav', 'ogg', 'm4a', 'aac'],
    'document': ['pdf', 'doc', 'docx', 'txt', 'xls', 'xlsx', 'ppt', 'pptx']
}

# Thumbnail settings
THUMBNAIL_SIZES = {
    'small': (150, 150),
    'medium': (400, 400),
    'large': (800, 800)
}

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'thumbnails'), exist_ok=True)

def get_file_type(filename):
    """Determine file type from extension"""
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    for file_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return file_type
    return None

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in sum(ALLOWED_EXTENSIONS.values(), [])

def generate_encryption_key(user_id, file_id):
    """Generate a unique encryption key for each file"""
    salt = f"{user_id}-{file_id}".encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(os.environ.get('SECRET_KEY', 'default-key').encode()))
    return key

def encrypt_file(file_data, user_id, file_id):
    """Encrypt file data"""
    key = generate_encryption_key(user_id, file_id)
    f = Fernet(key)
    return f.encrypt(file_data)

def decrypt_file(encrypted_data, user_id, file_id):
    """Decrypt file data"""
    key = generate_encryption_key(user_id, file_id)
    f = Fernet(key)
    return f.decrypt(encrypted_data)

def generate_image_thumbnail(image_path, size):
    """Generate thumbnail for image"""
    try:
        img = Image.open(image_path)
        
        # Convert RGBA to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                rgb_img.paste(img, mask=img.split()[3])
            else:
                rgb_img.paste(img)
            img = rgb_img
        
        # Apply EXIF orientation
        img = ImageOps.exif_transpose(img)
        
        # Generate thumbnail
        img.thumbnail(size, Image.LANCZOS)
        
        # Save thumbnail
        thumb_filename = f"thumb_{size[0]}x{size[1]}_{os.path.basename(image_path)}"
        thumb_path = os.path.join(UPLOAD_FOLDER, 'thumbnails', thumb_filename)
        img.save(thumb_path, 'JPEG', quality=85, optimize=True)
        
        return thumb_path
    except Exception as e:
        print(f"Error generating image thumbnail: {str(e)}")
        return None

def generate_video_thumbnail(video_path):
    """Generate thumbnail from video first frame"""
    try:
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        
        if ret:
            # Save frame as image
            thumb_filename = f"thumb_video_{os.path.basename(video_path)}.jpg"
            thumb_path = os.path.join(UPLOAD_FOLDER, 'thumbnails', thumb_filename)
            cv2.imwrite(thumb_path, frame)
            cap.release()
            
            # Generate different sizes
            return generate_image_thumbnail(thumb_path, THUMBNAIL_SIZES['medium'])
        
        cap.release()
        return None
    except Exception as e:
        print(f"Error generating video thumbnail: {str(e)}")
        return None

def compress_image(image_path, quality=85):
    """Compress image to reduce file size"""
    try:
        img = Image.open(image_path)
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                rgb_img.paste(img, mask=img.split()[3])
            else:
                rgb_img.paste(img)
            img = rgb_img
        
        # Resize if too large
        max_dimension = 2048
        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        
        # Save compressed version
        compressed_path = image_path.replace('.', '_compressed.')
        img.save(compressed_path, 'JPEG', quality=quality, optimize=True)
        
        # Replace original if compressed is smaller
        if os.path.getsize(compressed_path) < os.path.getsize(image_path):
            os.replace(compressed_path, image_path)
        else:
            os.remove(compressed_path)
        
        return True
    except Exception as e:
        print(f"Error compressing image: {str(e)}")
        return False

@media_bp.route('/media/upload', methods=['POST'])
@jwt_required()
def upload_media():
    """Upload and encrypt media files"""
    current_user_id = get_jwt_identity()
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    conversation_id = request.form.get('conversation_id')
    
    if not conversation_id:
        return jsonify({'error': 'Conversation ID required'}), 400
    
    # Verify user has access to conversation
    conversation = Conversation.query.filter(
        and_(
            Conversation.id == conversation_id,
            or_(
                Conversation.user1_id == current_user_id,
                Conversation.user2_id == current_user_id
            )
        )
    ).first()
    
    if not conversation:
        return jsonify({'error': 'Conversation not found or access denied'}), 404
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > MAX_FILE_SIZE:
        return jsonify({'error': f'File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB'}), 400
    
    # Generate unique file ID
    file_id = hashlib.sha256(f"{current_user_id}-{datetime.utcnow().isoformat()}-{file.filename}".encode()).hexdigest()[:16]
    
    # Secure filename
    filename = secure_filename(file.filename)
    file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    secure_name = f"{file_id}.{file_extension}"
    
    # Determine file type
    file_type = get_file_type(filename)
    
    # Save original file temporarily
    temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{secure_name}")
    file.save(temp_path)
    
    # Compress images
    if file_type == 'image':
        compress_image(temp_path)
    
    # Read file data for encryption
    with open(temp_path, 'rb') as f:
        file_data = f.read()
    
    # Encrypt file
    encrypted_data = encrypt_file(file_data, current_user_id, file_id)
    
    # Save encrypted file
    encrypted_path = os.path.join(UPLOAD_FOLDER, f"enc_{secure_name}")
    with open(encrypted_path, 'wb') as f:
        f.write(encrypted_data)
    
    # Generate thumbnails
    thumbnail_urls = {}
    if file_type == 'image':
        for size_name, size in THUMBNAIL_SIZES.items():
            thumb_path = generate_image_thumbnail(temp_path, size)
            if thumb_path:
                thumbnail_urls[size_name] = f"/media/thumbnail/{file_id}/{size_name}"
    elif file_type == 'video':
        thumb_path = generate_video_thumbnail(temp_path)
        if thumb_path:
            thumbnail_urls['medium'] = f"/media/thumbnail/{file_id}/medium"
    
    # Clean up temporary file
    os.remove(temp_path)
    
    # Store media metadata in database
    media_metadata = {
        'file_id': file_id,
        'filename': filename,
        'file_type': file_type,
        'file_size': file_size,
        'mime_type': mimetypes.guess_type(filename)[0],
        'thumbnails': thumbnail_urls,
        'uploaded_at': datetime.utcnow().isoformat(),
        'encrypted': True
    }
    
    return jsonify({
        'message': 'File uploaded successfully',
        'media': media_metadata
    }), 201

@media_bp.route('/media/download/<file_id>', methods=['GET'])
@jwt_required()
def download_media(file_id):
    """Download and decrypt media file"""
    current_user_id = get_jwt_identity()
    
    # Find encrypted file
    encrypted_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.startswith(f"enc_{file_id}")]
    
    if not encrypted_files:
        return jsonify({'error': 'File not found'}), 404
    
    encrypted_path = os.path.join(UPLOAD_FOLDER, encrypted_files[0])
    
    # Read encrypted data
    with open(encrypted_path, 'rb') as f:
        encrypted_data = f.read()
    
    try:
        # Decrypt file
        decrypted_data = decrypt_file(encrypted_data, current_user_id, file_id)
        
        # Determine mime type
        file_extension = encrypted_files[0].split('.')[-1] if '.' in encrypted_files[0] else ''
        mime_type = mimetypes.guess_type(f"file.{file_extension}")[0] or 'application/octet-stream'
        
        # Return decrypted file
        return send_file(
            io.BytesIO(decrypted_data),
            mimetype=mime_type,
            as_attachment=True,
            download_name=f"download_{file_id}.{file_extension}"
        )
    except Exception as e:
        return jsonify({'error': 'Failed to decrypt file'}), 403

@media_bp.route('/media/thumbnail/<file_id>/<size>', methods=['GET'])
@jwt_required()
def get_thumbnail(file_id, size):
    """Get thumbnail for media file"""
    if size not in ['small', 'medium', 'large']:
        return jsonify({'error': 'Invalid thumbnail size'}), 400
    
    # Find thumbnail file
    thumb_files = [f for f in os.listdir(os.path.join(UPLOAD_FOLDER, 'thumbnails')) 
                   if file_id in f and f"thumb_{THUMBNAIL_SIZES[size][0]}x{THUMBNAIL_SIZES[size][1]}" in f]
    
    if not thumb_files:
        # Try video thumbnail
        thumb_files = [f for f in os.listdir(os.path.join(UPLOAD_FOLDER, 'thumbnails'))
                      if file_id in f and 'thumb_video' in f]
    
    if not thumb_files:
        return jsonify({'error': 'Thumbnail not found'}), 404
    
    thumb_path = os.path.join(UPLOAD_FOLDER, 'thumbnails', thumb_files[0])
    
    return send_file(thumb_path, mimetype='image/jpeg')

@media_bp.route('/media/gallery/<conversation_id>', methods=['GET'])
@jwt_required()
def get_conversation_media(conversation_id):
    """Get all media files in a conversation"""
    current_user_id = get_jwt_identity()
    
    # Verify user has access to conversation
    conversation = Conversation.query.filter(
        and_(
            Conversation.id == conversation_id,
            or_(
                Conversation.user1_id == current_user_id,
                Conversation.user2_id == current_user_id
            )
        )
    ).first()
    
    if not conversation:
        return jsonify({'error': 'Conversation not found or access denied'}), 404
    
    # Get messages with media
    messages = Message.query.filter(
        and_(
            Message.conversation_id == conversation_id,
            Message.encrypted_content.like('%"media":%')  # Simple check for media content
        )
    ).order_by(Message.timestamp.desc()).all()
    
    media_items = []
    for message in messages:
        # Parse message content for media
        # This is a simplified version - in production, you'd properly parse the encrypted content
        media_items.append({
            'message_id': message.id,
            'timestamp': message.timestamp.isoformat(),
            'user_id': message.user_id
        })
    
    return jsonify({
        'conversation_id': conversation_id,
        'media_count': len(media_items),
        'media': media_items
    }), 200

@media_bp.route('/media/upload/progress', methods=['POST'])
@jwt_required()
def upload_progress():
    """Track upload progress (WebSocket implementation recommended)"""
    data = request.get_json()
    upload_id = data.get('upload_id')
    progress = data.get('progress', 0)
    
    # In production, this would update a Redis cache or similar
    # and broadcast progress via WebSocket
    
    return jsonify({
        'upload_id': upload_id,
        'progress': progress,
        'status': 'uploading' if progress < 100 else 'complete'
    }), 200

@media_bp.route('/media/delete/<file_id>', methods=['DELETE'])
@jwt_required()
def delete_media(file_id):
    """Delete media file"""
    current_user_id = get_jwt_identity()
    
    # Find and delete encrypted file
    encrypted_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.startswith(f"enc_{file_id}")]
    
    if not encrypted_files:
        return jsonify({'error': 'File not found'}), 404
    
    # Delete encrypted file
    encrypted_path = os.path.join(UPLOAD_FOLDER, encrypted_files[0])
    os.remove(encrypted_path)
    
    # Delete thumbnails
    thumb_files = [f for f in os.listdir(os.path.join(UPLOAD_FOLDER, 'thumbnails')) if file_id in f]
    for thumb_file in thumb_files:
        os.remove(os.path.join(UPLOAD_FOLDER, 'thumbnails', thumb_file))
    
    return jsonify({'message': 'Media deleted successfully'}), 200
