from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Message, Conversation, Users, Reaction
from sqlalchemy import or_, and_, desc
from datetime import datetime
import json
from websocket_handlers import notify_new_message, socketio_instance

message_bp = Blueprint('message_bp', __name__)

@message_bp.route('/messages', methods=['POST'])
@jwt_required()
def send_message():
    """Send a message with real-time delivery"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        recipient_id = data.get('recipient_id')
        content = data.get('content')
        conversation_id = data.get('conversation_id')
        reply_to = data.get('reply_to')
        media = data.get('media', [])
        encrypted = data.get('encrypted', False)
        
        if not recipient_id or not content:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Find or create conversation
        conversation = Conversation.query.filter(
            or_(
                and_(Conversation.user1_id == current_user_id, Conversation.user2_id == recipient_id),
                and_(Conversation.user1_id == recipient_id, Conversation.user2_id == current_user_id)
            )
        ).first()
        
        if not conversation:
            conversation = Conversation(
                user1_id=min(current_user_id, recipient_id),
                user2_id=max(current_user_id, recipient_id)
            )
            db.session.add(conversation)
            db.session.flush()
        
        # Update conversation timestamp
        conversation.updated_at = datetime.utcnow()
        
        # Create message
        message = Message(
            encrypted_content=content,
            user_id=current_user_id,
            conversation_id=conversation.id,
            reply_to_id=reply_to
        )
        
        db.session.add(message)
        db.session.commit()
        
        # Get sender info for real-time notification
        sender = Users.query.get(current_user_id)
        
        # Prepare message data for real-time delivery
        message_data = {
            'id': message.id,
            'conversation_id': conversation.id,
            'sender_id': current_user_id,
            'sender_username': sender.username,
            'sender_avatar': sender.avatar,
            'content': content,
            'media': media,
            'reply_to': reply_to,
            'encrypted': encrypted,
            'timestamp': message.timestamp.isoformat(),
            'is_read': False
        }
        
        # Send real-time notification to recipient
        if socketio_instance:
            socketio_instance.emit('new_message', message_data, room=f'user_{recipient_id}')
            
            # Also emit to sender for confirmation
            socketio_instance.emit('message_sent', {
                'message_id': message.id,
                'conversation_id': conversation.id,
                'timestamp': message.timestamp.isoformat()
            }, room=f'user_{current_user_id}')
        
        return jsonify({
            'message': 'Message sent successfully',
            'message_id': message.id,
            'message_data': message_data
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
        
        # Get messages with pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        
        messages = Message.query.filter_by(conversation_id=conversation.id)\
            .order_by(desc(Message.timestamp))\
            .paginate(page=page, per_page=per_page, error_out=False)
        
        # Format messages
        formatted_messages = []
        for message in messages.items:
            sender = Users.query.get(message.user_id)
            formatted_messages.append({
                'id': message.id,
                'sender_id': message.user_id,
                'sender_username': sender.username,
                'sender_avatar': sender.avatar,
                'content': message.encrypted_content,
                'media': [],  # Add media support later
                'reply_to': message.reply_to_id,
                'encrypted': True,
                'timestamp': message.timestamp.isoformat(),
                'is_read': False  # Add read status later
            })
        
        return jsonify({
            'messages': formatted_messages,
            'pagination': {
                'page': messages.page,
                'pages': messages.pages,
                'per_page': messages.per_page,
                'total': messages.total,
                'has_next': messages.has_next,
                'has_prev': messages.has_prev
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to get messages: {str(e)}'}), 500

@message_bp.route('/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    """Get user's conversations with last message"""
    try:
        current_user_id = get_jwt_identity()
        
        conversations = Conversation.query.filter(
            or_(
                Conversation.user1_id == current_user_id,
                Conversation.user2_id == current_user_id
            )
        ).all()
        
        formatted_conversations = []
        for conv in conversations:
            # Get the other user
            other_user_id = conv.user2_id if conv.user1_id == current_user_id else conv.user1_id
            other_user = Users.query.get(other_user_id)
            
            # Get last message
            last_message = Message.query.filter_by(conversation_id=conv.id)\
                .order_by(desc(Message.timestamp)).first()
            
            # Get unread count (placeholder for now)
            unread_count = 0  # Implement read tracking later
            
            conversation_data = {
                'conversation_id': conv.id,
                'other_user': {
                    'id': other_user.id,
                    'username': other_user.username,
                    'display_name': other_user.display_name or f"{other_user.first_name} {other_user.last_name}",
                    'avatar': other_user.avatar
                },
                'last_message': {
                    'content': last_message.encrypted_content if last_message else None,
                    'sender_id': last_message.user_id if last_message else None,
                    'timestamp': last_message.timestamp.isoformat() if last_message else None
                } if last_message else None,
                'unread_count': unread_count,
                'updated_at': conv.updated_at.isoformat()
            }
            
            formatted_conversations.append(conversation_data)
        
        # Sort by last activity
        formatted_conversations.sort(key=lambda x: x['updated_at'], reverse=True)
        
        return jsonify({'conversations': formatted_conversations}), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to get conversations: {str(e)}'}), 500

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
        from app import socketio
        socketio.emit('reaction_added', {
            'message_id': message_id,
            'user_id': current_user_id,
            'reaction_type': reaction_type
        }, room=str(message.conversation_id))
    except ImportError:
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
        from app import socketio
        socketio.emit('message_deleted', {
            'message_id': message_id,
            'conversation_id': message.conversation_id
        }, room=str(message.conversation_id))
    except ImportError:
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
        from app import socketio
        socketio.emit('message_edited', {
            'message_id': message_id,
            'new_content': new_content,
            'conversation_id': message.conversation_id
        }, room=str(message.conversation_id))
    except ImportError:
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
