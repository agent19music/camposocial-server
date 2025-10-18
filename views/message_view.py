from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Message, Conversation, Users, Reaction, MessageMedia, Friendship
from models_blocking import UserActivity
from sqlalchemy import or_, and_, desc
from datetime import datetime
import json
from websocket_handlers import socketio_instance


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
    sender = Users.query.get(message.user_id)
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
            'timestamp': reaction.timestamp.isoformat(),
        }
        for reaction in message.reactions
    ]

    return {
        'id': message.id,
        'conversation_id': message.conversation_id,
        'sender_id': message.user_id,
        'sender_username': sender.username if sender else None,
        'sender_avatar': sender.avatar if sender else None,
        'content': None if message.is_encrypted else message.encrypted_content,
        'ciphertext': message.encrypted_content,
        'media': media_payload,
        'reply_to': message.reply_to_id,
        'encrypted': message.is_encrypted,
        'timestamp': message.timestamp.isoformat(),
        'is_read': bool(message.read_at),
        'is_own': message.user_id == current_user_id,
        'reactions': reaction_payload,
    }

message_bp = Blueprint('message_bp', __name__)

@message_bp.route('/messages', methods=['POST'])
@jwt_required()
def send_message():
    """Send a message with real-time delivery"""
    try:
        current_user_id = get_jwt_identity()
        payload = request.get_json() or {}

        recipient_id = payload.get('recipient_id')
        raw_content = payload.get('content')
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

        # CRITICAL FIX: Send real-time notification to CONVERSATION ROOM (not user rooms)
        # This ensures both sender and recipient receive the message if they're in the conversation
        if socketio_instance:
            # Emit to conversation room - all participants will receive
            socketio_instance.emit('new_message', serialized, room=str(conversation.id))

            socketio_instance.emit('message_delivered', {
                'conversation_id': conversation.id,
                'message_id': message.id,
                'delivered_at': datetime.utcnow().isoformat()
            }, room=f'user_{current_user_id}')
            print(f"✅ Message {message.id} emitted to conversation room {conversation.id}")

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
    """Get user's conversation summaries"""
    try:
        current_user_id = get_jwt_identity()

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
                    'last_seen': activity.last_seen.isoformat() if activity and activity.last_seen else None,
                    'is_close_friend': friendship.is_close_friend if friendship else False,
                    'friendship_id': friendship.id if friendship else None,
                },
                'last_message': {
                    'id': last_message.id if last_message else None,
                    'content': last_message.encrypted_content if last_message else None,
                    'sender_id': last_message.user_id if last_message else None,
                    'timestamp': last_message.timestamp.isoformat() if last_message else None,
                } if last_message else None,
                'unread_count': 0,
                'updated_at': conv.updated_at.isoformat(),
            })

        return jsonify({'conversations': summaries}), 200

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
        'last_seen': activity.last_seen.isoformat() if activity and activity.last_seen else None,
        'is_close_friend': bool(friendship and friendship.is_close_friend),
        'friendship_id': friendship.id if friendship else None,
        'updated_at': conversation.updated_at.isoformat(),
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
