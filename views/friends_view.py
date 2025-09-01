from models import db, Users, Friendship, Conversation, Message
from flask import request, jsonify, Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, and_, func
from datetime import datetime
from websocket_handlers import notify_friend_request, notify_friend_request_response

friends_bp = Blueprint('friends_bp', __name__)

@friends_bp.route('/friends', methods=['GET'])
@jwt_required()
def get_friends():
    """Get list of accepted friends for current user"""
    current_user_id = get_jwt_identity()
    
    # Get all accepted friendships where user is either requester or addressee
    friendships = Friendship.query.filter(
        and_(
            or_(
                Friendship.requester_id == current_user_id,
                Friendship.addressee_id == current_user_id
            ),
            Friendship.status == 'accepted'
        )
    ).all()
    
    friends = []
    for friendship in friendships:
        # Get the friend (the other user in the relationship)
        friend_id = friendship.addressee_id if friendship.requester_id == current_user_id else friendship.requester_id
        friend = Users.query.get(friend_id)
        
        if friend:
            friends.append({
                'id': friend.id,
                'username': friend.username,
                'first_name': friend.first_name,
                'last_name': friend.last_name,
                'avatar': friend.avatar,
                'display_name': friend.display_name or f"{friend.first_name} {friend.last_name}",
                'is_online': False,  # You can implement online status tracking
                'friendship_id': friendship.id,
                'since': friendship.updated_at.isoformat()
            })
    
    return jsonify({'friends': friends}), 200

@friends_bp.route('/friends/pending', methods=['GET'])
@jwt_required()
def get_pending_friend_requests():
    """Get pending friend requests (both sent and received)"""
    current_user_id = get_jwt_identity()
    
    # Get received friend requests (pending)
    received_requests = Friendship.query.filter_by(
        addressee_id=current_user_id,
        status='pending'
    ).all()
    
    # Get sent friend requests (pending)
    sent_requests = Friendship.query.filter_by(
        requester_id=current_user_id,
        status='pending'
    ).all()
    
    received = []
    for request in received_requests:
        requester = Users.query.get(request.requester_id)
        if requester:
            received.append({
                'id': request.id,
                'user': {
                    'id': requester.id,
                    'username': requester.username,
                    'first_name': requester.first_name,
                    'last_name': requester.last_name,
                    'avatar': requester.avatar,
                    'display_name': requester.display_name or f"{requester.first_name} {requester.last_name}"
                },
                'created_at': request.created_at.isoformat()
            })
    
    sent = []
    for request in sent_requests:
        addressee = Users.query.get(request.addressee_id)
        if addressee:
            sent.append({
                'id': request.id,
                'user': {
                    'id': addressee.id,
                    'username': addressee.username,
                    'first_name': addressee.first_name,
                    'last_name': addressee.last_name,
                    'avatar': addressee.avatar,
                    'display_name': addressee.display_name or f"{addressee.first_name} {addressee.last_name}"
                },
                'created_at': request.created_at.isoformat()
            })
    
    return jsonify({
        'received': received,
        'sent': sent
    }), 200

@friends_bp.route('/friends/request', methods=['POST'])
@jwt_required()
def send_friend_request():
    """Send a friend request"""
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data or 'user_id' not in data:
        return jsonify({'error': 'User ID is required'}), 400
    
    target_user_id = data['user_id']
    
    if target_user_id == current_user_id:
        return jsonify({'error': 'Cannot send friend request to yourself'}), 400
    
    # Check if target user exists
    target_user = Users.query.get(target_user_id)
    if not target_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if friendship already exists
    existing_friendship = Friendship.query.filter(
        or_(
            and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == target_user_id),
            and_(Friendship.requester_id == target_user_id, Friendship.addressee_id == current_user_id)
        )
    ).first()
    
    if existing_friendship:
        if existing_friendship.status == 'accepted':
            return jsonify({'error': 'You are already friends with this user'}), 400
        elif existing_friendship.status == 'pending':
            return jsonify({'error': 'Friend request already sent or received'}), 400
    
    # Create new friend request
    friendship = Friendship(
        requester_id=current_user_id,
        addressee_id=target_user_id,
        status='pending'
    )
    
    db.session.add(friendship)
    db.session.commit()
    
    # Send real-time notification to the target user
    notify_friend_request(target_user_id, current_user_id)
    
    return jsonify({
        'message': 'Friend request sent successfully',
        'friendship_id': friendship.id
    }), 201

@friends_bp.route('/friends/request/<int:request_id>/accept', methods=['POST'])
@jwt_required()
def accept_friend_request(request_id):
    """Accept a friend request"""
    current_user_id = get_jwt_identity()
    
    friendship = Friendship.query.filter_by(
        id=request_id,
        addressee_id=current_user_id,
        status='pending'
    ).first()
    
    if not friendship:
        return jsonify({'error': 'Friend request not found'}), 404
    
    friendship.status = 'accepted'
    friendship.updated_at = datetime.utcnow()
    db.session.commit()
    
    # Send real-time notification to the requester
    notify_friend_request_response(friendship.requester_id, current_user_id, 'accepted', friendship.id)
    
    return jsonify({'message': 'Friend request accepted'}), 200

@friends_bp.route('/friends/request/<int:request_id>/decline', methods=['POST'])
@jwt_required()
def decline_friend_request(request_id):
    """Decline a friend request"""
    current_user_id = get_jwt_identity()
    
    friendship = Friendship.query.filter_by(
        id=request_id,
        addressee_id=current_user_id,
        status='pending'
    ).first()
    
    if not friendship:
        return jsonify({'error': 'Friend request not found'}), 404
    
    friendship.status = 'declined'
    friendship.updated_at = datetime.utcnow()
    db.session.commit()
    
    # Send real-time notification to the requester
    notify_friend_request_response(friendship.requester_id, current_user_id, 'declined', friendship.id)
    
    return jsonify({'message': 'Friend request declined'}), 200

@friends_bp.route('/friends/<int:friend_id>/remove', methods=['DELETE'])
@jwt_required()
def remove_friend(friend_id):
    """Remove a friend"""
    current_user_id = get_jwt_identity()
    
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
        return jsonify({'error': 'Friendship not found'}), 404
    
    db.session.delete(friendship)
    db.session.commit()
    
    return jsonify({'message': 'Friend removed successfully'}), 200

@friends_bp.route('/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    """Get all conversations for current user"""
    current_user_id = get_jwt_identity()
    
    # Get conversations where user is either user1 or user2
    conversations = Conversation.query.filter(
        or_(
            Conversation.user1_id == current_user_id,
            Conversation.user2_id == current_user_id
        )
    ).order_by(Conversation.updated_at.desc()).all()
    
    conversations_data = []
    for conv in conversations:
        # Get the other user in the conversation
        other_user = conv.get_other_user(current_user_id)
        
        # Get the last message
        last_message = Message.query.filter_by(
            conversation_id=conv.id
        ).order_by(Message.timestamp.desc()).first()
        
        conversations_data.append({
            'conversation_id': conv.id,
            'friend': {
                'id': other_user.id,
                'username': other_user.username,
                'first_name': other_user.first_name,
                'last_name': other_user.last_name,
                'avatar': other_user.avatar,
                'is_online': False  # Implement online status
            },
            'last_message': {
                'content': last_message.encrypted_content if last_message else None,
                'timestamp': last_message.timestamp.isoformat() if last_message else None
            } if last_message else None,
            'updated_at': conv.updated_at.isoformat()
        })
    
    return jsonify({'conversations': conversations_data}), 200

@friends_bp.route('/conversations/<conversation_id>', methods=['GET'])
@jwt_required()
def get_conversation(conversation_id):
    """Get conversation details"""
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
    
    other_user = conversation.get_other_user(current_user_id)
    
    return jsonify({
        'conversation_id': conversation.id,
        'friend_id': other_user.id,
        'first_name': other_user.first_name,
        'last_name': other_user.last_name,
        'avatar': other_user.avatar,
        'is_online': False  # Implement online status
    }), 200

@friends_bp.route('/conversation-exists/<int:friend_id>', methods=['GET'])
@jwt_required()
def conversation_exists(friend_id):
    """Check if conversation exists with a friend"""
    current_user_id = get_jwt_identity()
    
    # Check if conversation exists between current user and friend
    conversation = Conversation.query.filter(
        or_(
            and_(Conversation.user1_id == current_user_id, Conversation.user2_id == friend_id),
            and_(Conversation.user1_id == friend_id, Conversation.user2_id == current_user_id)
        )
    ).first()
    
    if not conversation:
        return jsonify({'exists': False}), 200
    
    # Check if there are any messages in the conversation
    message_count = Message.query.filter_by(conversation_id=conversation.id).count()
    
    return jsonify({
        'exists': message_count > 0,
        'conversation_id': conversation.id if message_count > 0 else None
    }), 200 