from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Message, Conversation, Users
from sqlalchemy import or_, and_, func
from datetime import datetime
import json

message_advanced_bp = Blueprint('message_advanced_bp', __name__)

class MessageHistory(db.Model):
    """Track message edit history"""
    __tablename__ = 'message_history'
    
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    original_content = db.Column(db.Text, nullable=False)
    edited_at = db.Column(db.DateTime, default=datetime.utcnow)
    edited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    message = db.relationship('Message', backref='edit_history')
    editor = db.relationship('Users')

@message_advanced_bp.route('/messages/<int:message_id>/edit', methods=['PUT'])
@jwt_required()
def edit_message(message_id):
    """Edit a message with history tracking"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data or 'content' not in data:
        return jsonify({'error': 'New content is required'}), 400
    
    message = Message.query.get(message_id)
    
    if not message:
        return jsonify({'error': 'Message not found'}), 404
    
    # Check if user owns the message
    if message.user_id != current_user_id:
        return jsonify({'error': 'You can only edit your own messages'}), 403
    
    # Check if message is too old to edit (e.g., 24 hours)
    time_diff = datetime.utcnow() - message.timestamp
    if time_diff.total_seconds() > 86400:  # 24 hours
        return jsonify({'error': 'Message is too old to edit'}), 400
    
    # Save original content to history
    history = MessageHistory(
        message_id=message_id,
        original_content=message.encrypted_content,
        edited_by=current_user_id
    )
    db.session.add(history)
    
    # Update message content
    new_content = data['content']
    # In production, encrypt the new content
    message.encrypted_content = json.dumps({
        'content': new_content,
        'edited': True,
        'edited_at': datetime.utcnow().isoformat()
    })
    
    db.session.commit()
    
    return jsonify({
        'message': 'Message edited successfully',
        'message_id': message_id,
        'edited_at': history.edited_at.isoformat()
    }), 200

@message_advanced_bp.route('/messages/<int:message_id>/delete', methods=['DELETE'])
@jwt_required()
def soft_delete_message(message_id):
    """Soft delete a message"""
    current_user_id = get_jwt_identity()
    
    message = Message.query.get(message_id)
    
    if not message:
        return jsonify({'error': 'Message not found'}), 404
    
    # Check if user owns the message or is admin
    if message.user_id != current_user_id:
        return jsonify({'error': 'You can only delete your own messages'}), 403
    
    # Soft delete - mark as deleted but keep in database
    message.is_deleted = True
    message.encrypted_content = json.dumps({
        'content': 'This message has been deleted',
        'deleted': True,
        'deleted_at': datetime.utcnow().isoformat()
    })
    
    db.session.commit()
    
    return jsonify({
        'message': 'Message deleted successfully',
        'message_id': message_id
    }), 200

@message_advanced_bp.route('/messages/search', methods=['GET'])
@jwt_required()
def search_messages():
    """Search messages within conversations"""
    current_user_id = get_jwt_identity()
    query = request.args.get('q', '').strip()
    conversation_id = request.args.get('conversation_id')
    limit = min(int(request.args.get('limit', 50)), 100)
    
    if not query or len(query) < 2:
        return jsonify({'error': 'Search query must be at least 2 characters'}), 400
    
    # Build search query
    search_query = Message.query.join(Conversation)
    
    # Filter by conversation if specified
    if conversation_id:
        search_query = search_query.filter(Message.conversation_id == conversation_id)
    else:
        # Only search in conversations user has access to
        search_query = search_query.filter(
            or_(
                Conversation.user1_id == current_user_id,
                Conversation.user2_id == current_user_id
            )
        )
    
    # Search in message content (note: this searches encrypted content in production)
    # In a real implementation, you'd need to decrypt messages client-side
    search_query = search_query.filter(
        and_(
            Message.encrypted_content.ilike(f'%{query}%'),
            Message.is_deleted == False
        )
    )
    
    # Order by relevance and limit
    results = search_query.order_by(Message.timestamp.desc()).limit(limit).all()
    
    # Format results
    search_results = []
    for msg in results:
        conversation = Conversation.query.get(msg.conversation_id)
        other_user = conversation.get_other_user(current_user_id)
        
        search_results.append({
            'message_id': msg.id,
            'conversation_id': msg.conversation_id,
            'content_preview': msg.encrypted_content[:100],  # Preview only
            'timestamp': msg.timestamp.isoformat(),
            'user_id': msg.user_id,
            'conversation_with': {
                'id': other_user.id,
                'name': f"{other_user.first_name} {other_user.last_name}",
                'avatar': other_user.avatar
            }
        })
    
    return jsonify({
        'query': query,
        'results_count': len(search_results),
        'results': search_results
    }), 200

@message_advanced_bp.route('/messages/<int:message_id>/forward', methods=['POST'])
@jwt_required()
def forward_message(message_id):
    """Forward a message to another conversation"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data or 'conversation_id' not in data:
        return jsonify({'error': 'Target conversation ID is required'}), 400
    
    # Get original message
    original_message = Message.query.get(message_id)
    
    if not original_message:
        return jsonify({'error': 'Message not found'}), 404
    
    # Verify user has access to original message
    original_conversation = Conversation.query.get(original_message.conversation_id)
    if not (original_conversation.user1_id == current_user_id or 
            original_conversation.user2_id == current_user_id):
        return jsonify({'error': 'Access denied to original message'}), 403
    
    # Verify user has access to target conversation
    target_conversation_id = data['conversation_id']
    target_conversation = Conversation.query.get(target_conversation_id)
    
    if not target_conversation:
        return jsonify({'error': 'Target conversation not found'}), 404
    
    if not (target_conversation.user1_id == current_user_id or 
            target_conversation.user2_id == current_user_id):
        return jsonify({'error': 'Access denied to target conversation'}), 403
    
    # Create forwarded message
    forwarded_content = json.dumps({
        'forwarded': True,
        'original_message_id': message_id,
        'original_sender_id': original_message.user_id,
        'content': json.loads(original_message.encrypted_content),
        'forwarded_at': datetime.utcnow().isoformat()
    })
    
    forwarded_message = Message(
        encrypted_content=forwarded_content,
        user_id=current_user_id,
        conversation_id=target_conversation_id,
        is_encrypted=original_message.is_encrypted
    )
    
    db.session.add(forwarded_message)
    db.session.commit()
    
    return jsonify({
        'message': 'Message forwarded successfully',
        'forwarded_message_id': forwarded_message.id,
        'target_conversation_id': target_conversation_id
    }), 201

@message_advanced_bp.route('/messages/<int:message_id>/history', methods=['GET'])
@jwt_required()
def get_message_history(message_id):
    """Get edit history for a message"""
    current_user_id = get_jwt_identity()
    
    message = Message.query.get(message_id)
    
    if not message:
        return jsonify({'error': 'Message not found'}), 404
    
    # Verify user has access to the conversation
    conversation = Conversation.query.get(message.conversation_id)
    if not (conversation.user1_id == current_user_id or 
            conversation.user2_id == current_user_id):
        return jsonify({'error': 'Access denied'}), 403
    
    # Get edit history
    history = MessageHistory.query.filter_by(message_id=message_id)\
                                  .order_by(MessageHistory.edited_at.desc()).all()
    
    history_data = []
    for edit in history:
        editor = Users.query.get(edit.edited_by)
        history_data.append({
            'edited_at': edit.edited_at.isoformat(),
            'edited_by': {
                'id': editor.id,
                'name': f"{editor.first_name} {editor.last_name}"
            },
            'original_content': edit.original_content  # In production, this would be decrypted
        })
    
    return jsonify({
        'message_id': message_id,
        'current_content': message.encrypted_content,
        'edit_count': len(history_data),
        'history': history_data
    }), 200

@message_advanced_bp.route('/messages/location', methods=['POST'])
@jwt_required()
def share_location():
    """Share location in a conversation"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    required_fields = ['conversation_id', 'latitude', 'longitude']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'conversation_id, latitude, and longitude are required'}), 400
    
    conversation_id = data['conversation_id']
    
    # Verify user has access to conversation
    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    
    if not (conversation.user1_id == current_user_id or 
            conversation.user2_id == current_user_id):
        return jsonify({'error': 'Access denied'}), 403
    
    # Create location message
    location_data = {
        'type': 'location',
        'latitude': data['latitude'],
        'longitude': data['longitude'],
        'address': data.get('address', ''),
        'timestamp': datetime.utcnow().isoformat()
    }
    
    location_message = Message(
        encrypted_content=json.dumps(location_data),
        user_id=current_user_id,
        conversation_id=conversation_id,
        is_encrypted=False  # Location data might not need encryption
    )
    
    db.session.add(location_message)
    db.session.commit()
    
    return jsonify({
        'message': 'Location shared successfully',
        'message_id': location_message.id,
        'location': location_data
    }), 201

@message_advanced_bp.route('/messages/voice', methods=['POST'])
@jwt_required()
def send_voice_message():
    """Send a voice message"""
    current_user_id = get_jwt_identity()
    
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400
    
    audio_file = request.files['audio']
    conversation_id = request.form.get('conversation_id')
    duration = request.form.get('duration', 0)
    
    if not conversation_id:
        return jsonify({'error': 'Conversation ID is required'}), 400
    
    # Verify user has access to conversation
    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    
    if not (conversation.user1_id == current_user_id or 
            conversation.user2_id == current_user_id):
        return jsonify({'error': 'Access denied'}), 403
    
    # Save audio file (in production, this would be encrypted and stored properly)
    import os
    import hashlib
    
    # Generate unique filename
    file_id = hashlib.sha256(f"{current_user_id}-{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]
    file_extension = audio_file.filename.rsplit('.', 1)[1].lower() if '.' in audio_file.filename else 'webm'
    filename = f"voice_{file_id}.{file_extension}"
    
    # Create upload directory if it doesn't exist
    upload_dir = os.environ.get('UPLOAD_FOLDER', '/tmp/uploads/voice')
    os.makedirs(upload_dir, exist_ok=True)
    
    # Save file
    file_path = os.path.join(upload_dir, filename)
    audio_file.save(file_path)
    
    # Create voice message
    voice_data = {
        'type': 'voice',
        'file_id': file_id,
        'duration': duration,
        'url': f"/media/voice/{file_id}",
        'timestamp': datetime.utcnow().isoformat()
    }
    
    voice_message = Message(
        encrypted_content=json.dumps(voice_data),
        user_id=current_user_id,
        conversation_id=conversation_id,
        is_encrypted=False  # Audio file itself would be encrypted
    )
    
    db.session.add(voice_message)
    db.session.commit()
    
    return jsonify({
        'message': 'Voice message sent successfully',
        'message_id': voice_message.id,
        'voice_data': voice_data
    }), 201

@message_advanced_bp.route('/messages/bulk-delete', methods=['POST'])
@jwt_required()
def bulk_delete_messages():
    """Delete multiple messages at once"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data or 'message_ids' not in data:
        return jsonify({'error': 'message_ids array is required'}), 400
    
    message_ids = data['message_ids']
    if not isinstance(message_ids, list) or len(message_ids) == 0:
        return jsonify({'error': 'message_ids must be a non-empty array'}), 400
    
    deleted_count = 0
    errors = []
    
    for msg_id in message_ids:
        message = Message.query.get(msg_id)
        
        if not message:
            errors.append(f"Message {msg_id} not found")
            continue
        
        # Check ownership
        if message.user_id != current_user_id:
            errors.append(f"Cannot delete message {msg_id} - not owner")
            continue
        
        # Soft delete
        message.is_deleted = True
        message.encrypted_content = json.dumps({
            'content': 'This message has been deleted',
            'deleted': True,
            'deleted_at': datetime.utcnow().isoformat()
        })
        deleted_count += 1
    
    db.session.commit()
    
    return jsonify({
        'message': f'{deleted_count} messages deleted successfully',
        'deleted_count': deleted_count,
        'errors': errors if errors else None
    }), 200

@message_advanced_bp.route('/messages/clear-conversation/<conversation_id>', methods=['DELETE'])
@jwt_required()
def clear_conversation(conversation_id):
    """Clear all messages in a conversation for the current user"""
    current_user_id = get_jwt_identity()
    
    # Verify user has access to conversation
    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    
    if not (conversation.user1_id == current_user_id or 
            conversation.user2_id == current_user_id):
        return jsonify({'error': 'Access denied'}), 403
    
    # In a real app, you might want to keep messages but hide them for this user
    # For now, we'll soft delete all messages from current user
    messages = Message.query.filter_by(
        conversation_id=conversation_id,
        user_id=current_user_id,
        is_deleted=False
    ).all()
    
    for message in messages:
        message.is_deleted = True
        message.encrypted_content = json.dumps({
            'content': 'This message has been deleted',
            'deleted': True,
            'deleted_at': datetime.utcnow().isoformat()
        })
    
    db.session.commit()
    
    return jsonify({
        'message': 'Conversation cleared successfully',
        'deleted_count': len(messages)
    }), 200
