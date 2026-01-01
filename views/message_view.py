from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Message, Conversation, Users, Reaction, MessageMedia, Friendship
from models_blocking import UserActivity
from sqlalchemy import or_, and_, desc, func
from datetime import datetime
import json
import os
import hashlib
from websocket_handlers import socketio_instance, notify_new_message
from redis_config import get_redis_client

message_bp = Blueprint('message_bp', __name__)
redis_client = get_redis_client()

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

def _ensure_conversation(current_user_id: int, other_user_id: int) -> Conversation:
    """Fetch or create a deterministic conversation between two users."""
    if current_user_id == other_user_id:
        raise ValueError("Cannot start conversation with yourself")

    user_low, user_high = sorted([current_user_id, other_user_id])

    conversation = Conversation.query.filter(
        and_(
            Conversation.user1_id == user_low,
            Conversation.user2_id == user_high
        )
    ).first()

    if not conversation:
        conversation = Conversation(user1_id=user_low, user2_id=user_high)
        db.session.add(conversation)
        db.session.flush()

    return conversation

def _serialize_message(message: Message, current_user_id: int) -> dict:
    # Use the existing 'author' relationship from Users model
    sender = message.author if hasattr(message, 'author') else Users.query.get(message.user_id)
    media_payload = [
        {
            'id': media.id,
            'file_id': media.file_id,
            'url': media.url,
            'type': media.media_type,
            'metadata': media.file_metadata or {}
        }
        for media in message.media_items
    ]

    reaction_payload = [
        {
            'user_id': reaction.user_id,
            'reaction_type': reaction.reaction_type,
            'timestamp': reaction.timestamp.isoformat() + 'Z',  # UTC marker
        }
        for reaction in message.reactions
    ]

    return {
        'id': message.id,
        'conversation_id': message.conversation_id,
        'sender_id': message.user_id,
        'sender_username': sender.username if sender else None,
        'sender_avatar': sender.avatar if sender else None,
        'sender_public_key': sender.public_key if sender else None,  # For E2EE decryption
        'content': None if message.is_encrypted else message.encrypted_content,
        'ciphertext': message.encrypted_content,
        'nonce': getattr(message, 'nonce', None),  # For E2EE decryption
        'media': media_payload,
        'reply_to': message.reply_to_id,
        'encrypted': message.is_encrypted,
        'timestamp': message.timestamp.isoformat() + 'Z',  # UTC marker for proper JS Date parsing
        'is_read': bool(getattr(message, 'read_at', None)),
        'is_own': message.user_id == current_user_id,
        'reactions': reaction_payload,
        'is_deleted': message.is_deleted
    }

def _invalidate_conversation_cache(user_id):
    """Invalidate conversation list cache for a user"""
    if redis_client:
        try:
            redis_client.delete(f"user:{user_id}:conversations")
        except Exception as e:
            print(f"Redis error: {e}")

@message_bp.route('/messages', methods=['POST'])
@jwt_required()
def send_message():
    """Send a message with real-time delivery"""
    try:
        current_user_id = get_jwt_identity()
        payload = request.get_json() or {}

        recipient_id = payload.get('recipient_id')
        raw_content = payload.get('content')
        nonce = payload.get('nonce')  # E2EE nonce for decryption
        encrypted_flag = bool(payload.get('encrypted', False))
        provided_conversation_id = payload.get('conversation_id')
        reply_to = payload.get('reply_to')
        media_payload = payload.get('media', [])

        if not recipient_id:
            return jsonify({'error': 'recipient_id is required'}), 400

        if not raw_content:
            return jsonify({'error': 'content is required'}), 400

        if int(recipient_id) == current_user_id:
            return jsonify({'error': 'Cannot message yourself'}), 400

        # Ensure conversation exists (either via provided id or deterministic lookup)
        if provided_conversation_id:
            conversation = Conversation.query.filter(
                and_(
                    Conversation.id == provided_conversation_id,
                    or_(
                        Conversation.user1_id == current_user_id,
                        Conversation.user2_id == current_user_id
                    )
                )
            ).first()
            if not conversation:
                return jsonify({'error': 'Conversation not found or access denied'}), 404
            other_user_id = conversation.get_other_user(current_user_id).id
        else:
            other_user_id = int(recipient_id)
            conversation = _ensure_conversation(current_user_id, other_user_id)

        conversation.updated_at = datetime.utcnow()

        message = Message(
            encrypted_content=raw_content,
            nonce=nonce,  # Store E2EE nonce
            user_id=current_user_id,
            conversation_id=conversation.id,
            reply_to_id=reply_to,
            is_encrypted=encrypted_flag,
        )

        db.session.add(message)
        db.session.flush()

        attachments = []
        for media_item in media_payload:
            if not isinstance(media_item, dict):
                continue
            file_id = media_item.get('file_id') or media_item.get('id')
            url = media_item.get('url')
            media_type = media_item.get('type')
            meta = media_item.get('metadata')

            if not (file_id and url and media_type):
                continue

            media_model = MessageMedia(
                message_id=message.id,
                file_id=str(file_id),
                url=url,
                media_type=media_type,
                file_metadata=meta if isinstance(meta, dict) else None,
            )
            db.session.add(media_model)
            attachments.append(media_model)

        db.session.commit()

        serialized = _serialize_message(message, current_user_id)

        preview = '[Encrypted message]' if encrypted_flag else raw_content[:100] + '...' if len(raw_content) > 100 else raw_content
        conversation.last_message_preview = preview
        conversation.last_message_id = message.id
        db.session.commit()

        # Invalidate cache for both users
        _invalidate_conversation_cache(current_user_id)
        _invalidate_conversation_cache(other_user_id)

        if socketio_instance:
            socketio_instance.emit('new_message', serialized, room=str(conversation.id))
            socketio_instance.emit('message_delivered', {
                'conversation_id': conversation.id,
                'message_id': message.id,
                'delivered_at': datetime.utcnow().isoformat()
            }, room=f'user_{current_user_id}')

        notify_new_message(current_user_id, other_user_id, serialized)

        return jsonify({
            'message': 'Message sent successfully',
            'message_id': message.id,
            'conversation_id': conversation.id,
            'message_data': serialized,
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to send message: {str(e)}'}), 500

@message_bp.route('/conversations/<conversation_id>/messages', methods=['GET'])
@jwt_required()
def get_messages(conversation_id):
    """Get messages for a conversation"""
    try:
        current_user_id = get_jwt_identity()
        
        # Verify user is part of this conversation
        conversation = Conversation.query.filter_by(id=conversation_id).first()
        if not conversation or (conversation.user1_id != current_user_id and conversation.user2_id != current_user_id):
            return jsonify({'error': 'Conversation not found'}), 404
        
        limit = request.args.get('limit', 50, type=int)
        before_id = request.args.get('before', type=int)

        query = Message.query.filter_by(conversation_id=conversation.id).order_by(desc(Message.timestamp))

        if before_id:
            pivot_message = Message.query.get(before_id)
            if pivot_message and pivot_message.conversation_id == conversation.id:
                query = query.filter(Message.timestamp < pivot_message.timestamp)

        messages = query.limit(limit).all()

        serialized = [_serialize_message(message, current_user_id) for message in messages]

        return jsonify({
            'messages': serialized,
            'count': len(serialized),
            'conversation_id': conversation.id,
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to get messages: {str(e)}'}), 500

@message_bp.route('/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    """Get user's conversation summaries with caching"""
    try:
        current_user_id = get_jwt_identity()
        
        # Try to get from cache
        cache_key = f"user:{current_user_id}:conversations"
        if redis_client:
            cached_data = redis_client.get(cache_key)
            if cached_data:
                return jsonify(json.loads(cached_data)), 200

        conversations = Conversation.query.filter(
            or_(
                Conversation.user1_id == current_user_id,
                Conversation.user2_id == current_user_id
            )
        ).order_by(desc(Conversation.updated_at)).all()

        summaries = []
        for conv in conversations:
            other_user = conv.get_other_user(current_user_id)
            if not other_user:
                continue

            last_message = Message.query.filter_by(conversation_id=conv.id).order_by(desc(Message.timestamp)).first()
            activity = UserActivity.query.filter_by(user_id=other_user.id).first()
            friendship = Friendship.query.filter(
                and_(
                    or_(
                        and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == other_user.id),
                        and_(Friendship.requester_id == other_user.id, Friendship.addressee_id == current_user_id)
                    ),
                    Friendship.status == 'accepted'
                )
            ).first()
            
            # Get sender's public key for E2EE decryption on client
            sender_public_key = None
            if last_message:
                sender = Users.query.get(last_message.user_id)
                sender_public_key = sender.public_key if sender else None

            summaries.append({
                'conversation_id': conv.id,
                'friend': {
                    'id': other_user.id,
                    'username': other_user.username,
                    'display_name': other_user.display_name or f"{other_user.first_name} {other_user.last_name}",
                    'first_name': other_user.first_name,
                    'last_name': other_user.last_name,
                    'avatar': other_user.avatar,
                    'is_online': bool(activity and activity.is_online),
                    'last_seen': (activity.last_seen.isoformat() + 'Z') if activity and activity.last_seen else None,
                    'is_close_friend': friendship.is_close_friend if friendship else False,
                    'friendship_id': friendship.id if friendship else None,
                },
                'last_message': {
                    'id': last_message.id if last_message else None,
                    # Return raw ciphertext for client-side decryption
                    'content': last_message.encrypted_content if last_message else None,
                    'is_encrypted': last_message.is_encrypted if last_message else False,
                    'nonce': getattr(last_message, 'nonce', None) if last_message else None,
                    'sender_public_key': sender_public_key,
                    'sender_id': last_message.user_id if last_message else None,
                    'timestamp': (last_message.timestamp.isoformat() + 'Z') if last_message else None,
                } if last_message else None,
                'unread_count': 0,
                'updated_at': conv.updated_at.isoformat() + 'Z',
            })

        response_data = {'conversations': summaries}
        
        # Cache the result for 60 seconds (or until invalidated)
        if redis_client:
            redis_client.setex(cache_key, 60, json.dumps(response_data))

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({'error': f'Failed to get conversations: {str(e)}'}), 500


@message_bp.route('/conversations/with/<int:friend_id>', methods=['POST'])
@jwt_required()
def ensure_conversation(friend_id: int):
    """Create or fetch conversation with friend_id and return metadata."""
    current_user_id = get_jwt_identity()

    if current_user_id == friend_id:
        return jsonify({'error': 'Cannot create conversation with yourself'}), 400

    conversation = _ensure_conversation(current_user_id, friend_id)
    conversation.updated_at = datetime.utcnow()
    db.session.commit()
    
    # Invalidate cache
    _invalidate_conversation_cache(current_user_id)

    other_user = Users.query.get(friend_id)
    activity = UserActivity.query.filter_by(user_id=friend_id).first()
    friendship = Friendship.query.filter(
        and_(
            or_(
                and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == friend_id),
                and_(Friendship.requester_id == friend_id, Friendship.addressee_id == current_user_id)
            ),
            Friendship.status == 'accepted'
        )
    ).first()

    return jsonify({
        'conversation_id': conversation.id,
        'friend': {
            'id': other_user.id,
            'username': other_user.username,
            'display_name': other_user.display_name or f"{other_user.first_name} {other_user.last_name}",
            'first_name': other_user.first_name,
            'last_name': other_user.last_name,
            'avatar': other_user.avatar,
        },
        'is_online': bool(activity and activity.is_online),
        'last_seen': (activity.last_seen.isoformat() + 'Z') if activity and activity.last_seen else None,
        'is_close_friend': bool(friendship and friendship.is_close_friend),
        'friendship_id': friendship.id if friendship else None,
        'updated_at': conversation.updated_at.isoformat() + 'Z',
    }), 200

@message_bp.route('/messages/<int:message_id>/reactions', methods=['POST'])
@jwt_required()
def add_reaction(message_id):
    """Add reaction to a message"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    reaction_type = data.get('reaction_type')
    
    if not reaction_type:
        return jsonify({'error': 'Reaction type is required'}), 400
    
    # Verify message exists and user has access
    message = Message.query.get(message_id)
    if not message:
        return jsonify({'error': 'Message not found'}), 404
    
    # Check if user already reacted
    existing = Reaction.query.filter_by(
        message_id=message_id,
        user_id=current_user_id
    ).first()
    
    if existing:
        existing.reaction_type = reaction_type
        existing.timestamp = datetime.utcnow()
    else:
        reaction = Reaction(
            message_id=message_id,
            user_id=current_user_id,
            reaction_type=reaction_type
        )
        db.session.add(reaction)
    
    db.session.commit()
    
    # Emit reaction update via WebSocket
    try:
        payload = {
            'message_id': message_id,
            'user_id': current_user_id,
            'reaction_type': reaction_type,
            'conversation_id': message.conversation_id,
        }
        if socketio_instance:
            socketio_instance.emit('reaction_added', payload, room=str(message.conversation_id))
    except Exception:
        pass
    
    return jsonify({'success': True}), 200

@message_bp.route('/messages/<int:message_id>', methods=['DELETE'])
@jwt_required()
def delete_message(message_id):
    """Soft delete a message"""
    current_user_id = get_jwt_identity()
    
    message = Message.query.filter_by(
        id=message_id,
        user_id=current_user_id
    ).first()
    
    if not message:
        return jsonify({'error': 'Message not found or unauthorized'}), 404
    
    message.is_deleted = True
    db.session.commit()
    
    # Emit deletion via WebSocket
    try:
        if socketio_instance:
            socketio_instance.emit('message_deleted', {
                'message_id': message_id,
                'conversation_id': message.conversation_id
            }, room=str(message.conversation_id))
    except Exception:
        pass
    
    return jsonify({'success': True}), 200

@message_bp.route('/messages/<int:message_id>', methods=['PUT'])
@jwt_required()
def edit_message(message_id):
    """Edit a message (within 15 minutes of sending)"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    new_content = data.get('content')
    
    if not new_content:
        return jsonify({'error': 'Content is required'}), 400
    
    message = Message.query.filter_by(
        id=message_id,
        user_id=current_user_id
    ).first()
    
    if not message:
        return jsonify({'error': 'Message not found or unauthorized'}), 404
    
    # Check if message is within edit window (15 minutes)
    time_diff = datetime.utcnow() - message.timestamp
    if time_diff.total_seconds() > 900:  # 15 minutes
        return jsonify({'error': 'Edit window has expired'}), 400
    
    # Save original content to history
    history = MessageHistory(
        message_id=message_id,
        original_content=message.encrypted_content,
        edited_by=current_user_id
    )
    db.session.add(history)

    message.encrypted_content = new_content
    # Could add an 'edited' flag here if the model supports it
    db.session.commit()
    
    # Emit edit via WebSocket
    try:
        if socketio_instance:
            socketio_instance.emit('message_edited', {
                'message_id': message_id,
                'new_content': new_content,
                'conversation_id': message.conversation_id
            }, room=str(message.conversation_id))
    except Exception:
        pass
    
    return jsonify({'success': True}), 200

@message_bp.route('/keys', methods=['POST'])
@jwt_required()
def upload_public_key():
    """Upload user's public encryption key"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    public_key = data.get('public_key')
    
    if not public_key:
        return jsonify({'error': 'Public key is required'}), 400
    
    user = Users.query.get(current_user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    user.public_key = public_key
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Public key uploaded'}), 200

@message_bp.route('/keys/<int:user_id>', methods=['GET'])
@jwt_required()
def get_public_key(user_id):
    """Get a user's public encryption key"""
    user = Users.query.get(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    if not user.public_key:
        return jsonify({'error': 'User has no public key'}), 404
    
    return jsonify({'public_key': user.public_key}), 200

# --- Advanced Features Merged Below ---

@message_bp.route('/messages/search', methods=['GET'])
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

@message_bp.route('/messages/<int:message_id>/forward', methods=['POST'])
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
        'content': json.loads(original_message.encrypted_content) if original_message.encrypted_content.startswith('{') else original_message.encrypted_content,
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
    
    # Invalidate cache
    _invalidate_conversation_cache(current_user_id)
    _invalidate_conversation_cache(target_conversation.get_other_user(current_user_id).id)

    return jsonify({
        'message': 'Message forwarded successfully',
        'forwarded_message_id': forwarded_message.id,
        'target_conversation_id': target_conversation_id
    }), 201

@message_bp.route('/messages/<int:message_id>/history', methods=['GET'])
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

@message_bp.route('/messages/location', methods=['POST'])
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
    
    # Invalidate cache
    _invalidate_conversation_cache(current_user_id)
    _invalidate_conversation_cache(conversation.get_other_user(current_user_id).id)

    return jsonify({
        'message': 'Location shared successfully',
        'message_id': location_message.id,
        'location': location_data
    }), 201

@message_bp.route('/messages/voice', methods=['POST'])
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
    
    # Invalidate cache
    _invalidate_conversation_cache(current_user_id)
    _invalidate_conversation_cache(conversation.get_other_user(current_user_id).id)

    return jsonify({
        'message': 'Voice message sent successfully',
        'message_id': voice_message.id,
        'voice_data': voice_data
    }), 201

@message_bp.route('/messages/bulk-delete', methods=['POST'])
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

@message_bp.route('/messages/clear-conversation/<conversation_id>', methods=['DELETE'])
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
