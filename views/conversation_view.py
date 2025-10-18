from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Conversation, Users, Friendship, Message
from sqlalchemy import or_, and_
from datetime import datetime

conversation_bp = Blueprint('conversation_bp', __name__)


@conversation_bp.route('/conversations/with/<int:friend_id>', methods=['POST'])
@jwt_required()
def create_or_get_conversation(friend_id):
    """Create a new conversation or return existing one between current user and friend"""
    current_user_id = get_jwt_identity()
    
    if current_user_id == friend_id:
        return jsonify({'error': 'Cannot create conversation with yourself'}), 400
    
    # Check if users are friends
    friendship = Friendship.query.filter(
        and_(
            or_(
                and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == friend_id),
                and_(Friendship.requester_id == friend_id, Friendship.addressee_id == current_user_id)
            ),
            Friendship.status == 'accepted'
        )
    ).first()
    
    if not friendship:
        return jsonify({'error': 'You must be friends to start a conversation'}), 403
    
    # Check if conversation already exists (either direction)
    conversation = Conversation.query.filter(
        or_(
            and_(Conversation.user1_id == current_user_id, Conversation.user2_id == friend_id),
            and_(Conversation.user1_id == friend_id, Conversation.user2_id == current_user_id)
        )
    ).first()
    
    if conversation:
        # Reactivate if was deleted
        if not conversation.is_active:
            conversation.is_active = True
            conversation.updated_at = datetime.utcnow()
            db.session.commit()
        
        return jsonify({
            'conversation_id': conversation.id,
            'existing': True
        }), 200
    
    # Create new conversation (always user with lower ID as user1 for consistency)
    if current_user_id < friend_id:
        new_conversation = Conversation(
            user1_id=current_user_id,
            user2_id=friend_id,
            is_active=True
        )
    else:
        new_conversation = Conversation(
            user1_id=friend_id,
            user2_id=current_user_id,
            is_active=True
        )
    
    db.session.add(new_conversation)
    db.session.commit()
    
    return jsonify({
        'conversation_id': new_conversation.id,
        'existing': False
    }), 201


@conversation_bp.route('/conversations/<conversation_id>/pin', methods=['POST'])
@jwt_required()
def pin_conversation(conversation_id):
    """Pin or unpin a conversation for the current user"""
    current_user_id = get_jwt_identity()
    data = request.get_json() or {}
    pin_state = bool(data.get('pinned', True))
    
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
    
    # Set pin state for appropriate user
    if conversation.user1_id == current_user_id:
        conversation.is_pinned_by_user1 = pin_state
    else:
        conversation.is_pinned_by_user2 = pin_state
    
    conversation.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'message': 'Pin state updated successfully',
        'pinned': pin_state
    }), 200


@conversation_bp.route('/conversations/<conversation_id>', methods=['DELETE'])
@jwt_required()
def delete_conversation(conversation_id):
    """Soft delete a conversation (mark as inactive)"""
    current_user_id = get_jwt_identity()
    
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
    
    # Soft delete - mark as inactive
    conversation.is_active = False
    conversation.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'message': 'Conversation deleted successfully'
    }), 200


@conversation_bp.route('/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    """Get all active conversations for the current user"""
    current_user_id = get_jwt_identity()
    
    conversations = Conversation.query.filter(
        and_(
            or_(
                Conversation.user1_id == current_user_id,
                Conversation.user2_id == current_user_id
            ),
            Conversation.is_active == True
        )
    ).order_by(Conversation.updated_at.desc()).all()
    
    result = []
    for conv in conversations:
        # Determine the other user
        other_user_id = conv.user2_id if conv.user1_id == current_user_id else conv.user1_id
        other_user = Users.query.get(other_user_id)
        
        if not other_user:
            continue
        
        # Determine if pinned for current user
        is_pinned = conv.is_pinned_by_user1 if conv.user1_id == current_user_id else conv.is_pinned_by_user2
        
        result.append({
            'conversation_id': conv.id,
            'other_user': {
                'id': other_user.id,
                'username': other_user.username,
                'first_name': other_user.first_name,
                'last_name': other_user.last_name,
                'avatar': other_user.avatar,
                'display_name': other_user.display_name
            },
            'last_message_preview': conv.last_message_preview,
            'updated_at': conv.updated_at.isoformat(),
            'is_pinned': is_pinned
        })
    
    return jsonify({
        'conversations': result,
        'count': len(result)
    }), 200
