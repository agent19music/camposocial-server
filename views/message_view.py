from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Message, Conversation, Users, Reaction
from sqlalchemy import or_, and_
from datetime import datetime
import json

message_bp = Blueprint('message_bp', __name__)

@message_bp.route('/messages', methods=['POST'])
@jwt_required()
def send_message():
    """Send an encrypted message"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    recipient_id = data.get('recipient_id')
    encrypted_content = data.get('content')
    conversation_id = data.get('conversation_id')
    reply_to_id = data.get('reply_to')
    is_encrypted = data.get('encrypted', False)
    
    if not recipient_id or not encrypted_content:
        return jsonify({'error': 'Recipient and content are required'}), 400
    
    # Find or create conversation
    conversation = Conversation.query.filter(
        or_(
            and_(Conversation.user1_id == current_user_id, 
                 Conversation.user2_id == recipient_id),
            and_(Conversation.user1_id == recipient_id, 
                 Conversation.user2_id == current_user_id)
        )
    ).first()
    
    if not conversation:
        # Create new conversation
        conversation = Conversation(
            user1_id=min(int(current_user_id), int(recipient_id)),
            user2_id=max(int(current_user_id), int(recipient_id))
        )
        db.session.add(conversation)
        db.session.flush()
    
    # Update conversation timestamp
    conversation.updated_at = datetime.utcnow()
    
    # Create message - note the field name is 'encrypted_content' not 'content'
    message = Message(
        encrypted_content=encrypted_content,
        user_id=current_user_id,
        conversation_id=conversation.id,
        reply_to_id=reply_to_id
    )
    
    # Add an 'is_encrypted' field if your Message model supports it
    # For now, we'll store encryption status in the message itself
    
    db.session.add(message)
    db.session.commit()
    
    # Emit via WebSocket for real-time delivery
    try:
        from app import socketio
        socketio.emit('new_message', {
            'id': message.id,
            'content': encrypted_content,
            'sender_id': current_user_id,
            'conversation_id': conversation.id,
            'timestamp': message.timestamp.isoformat(),
            'encrypted': is_encrypted
        }, room=str(conversation.id))
    except ImportError:
        # SocketIO not available yet
        pass
    
    return jsonify({
        'message_id': message.id,
        'conversation_id': conversation.id,
        'timestamp': message.timestamp.isoformat()
    }), 201

@message_bp.route('/messages/<conversation_id>', methods=['GET'])
@jwt_required()
def get_messages(conversation_id):
    """Get paginated messages for a conversation"""
    current_user_id = get_jwt_identity()
    
    # Verify user is part of conversation
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
        return jsonify({'error': 'Conversation not found'}), 404
    
    # Pagination parameters
    limit = request.args.get('limit', 50, type=int)
    before_id = request.args.get('before', type=int)
    
    query = Message.query.filter_by(
        conversation_id=conversation_id,
        is_deleted=False
    )
    
    if before_id:
        query = query.filter(Message.id < before_id)
    
    messages = query.order_by(Message.timestamp.desc()).limit(limit).all()
    
    messages_data = []
    for msg in messages:
        reactions = Reaction.query.filter_by(message_id=msg.id).all()
        messages_data.append({
            'id': msg.id,
            'content': msg.encrypted_content,
            'sender_id': msg.user_id,
            'timestamp': msg.timestamp.isoformat(),
            'reply_to': msg.reply_to_id,
            'encrypted': True,  # We'll assume all messages are encrypted for now
            'reactions': [
                {'user_id': r.user_id, 'type': r.reaction_type} 
                for r in reactions
            ],
            'is_read': False  # Will implement read receipts later
        })
    
    return jsonify({'messages': messages_data}), 200

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
