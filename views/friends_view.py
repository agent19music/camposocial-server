from models import db, Users, Friendship, Conversation, Message
from models_blocking import UserActivity, BlockedUser
from flask import request, jsonify, Blueprint, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, and_, func, not_
from datetime import datetime, timedelta
from websocket_handlers import notify_friend_request, notify_friend_request_response

friends_bp = Blueprint('friends_bp', __name__)

# Helper Functions

def is_blocked(user1_id, user2_id):
    """Check if there's a blocking relationship between two users"""
    return BlockedUser.query.filter(
        or_(
            and_(BlockedUser.blocker_id == user1_id, BlockedUser.blocked_id == user2_id),
            and_(BlockedUser.blocker_id == user2_id, BlockedUser.blocked_id == user1_id)
        )
    ).first() is not None

def update_user_activity(user_id, is_online=True):
    """Update user's activity status"""
    activity = UserActivity.query.filter_by(user_id=user_id).first()
    if not activity:
        activity = UserActivity(user_id=user_id)
        db.session.add(activity)
    
    activity.last_seen = datetime.utcnow()
    activity.is_online = is_online
    if is_online:
        activity.current_status = 'available'
    db.session.commit()
    return activity

def ensure_conversation(user1_id, user2_id):
    """Ensure a conversation exists between two users"""
    user_low, user_high = sorted([user1_id, user2_id])
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
    
    conversation.updated_at = datetime.utcnow()
    return conversation

# Routes

@friends_bp.route('/friends', methods=['GET'])
@jwt_required()
def get_friends():
    """Get list of accepted friends for current user"""
    current_user_id = int(get_jwt_identity())
    
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
        friend_id = friendship.addressee_id if friendship.requester_id == current_user_id else friendship.requester_id
        friend = Users.query.get(friend_id)

        if not friend:
            continue

        activity = UserActivity.query.filter_by(user_id=friend.id).first()
        is_online = bool(activity and activity.is_online)
        last_seen = activity.last_seen.isoformat() if activity and activity.last_seen else None

        conversation = Conversation.query.filter(
            or_(
                and_(Conversation.user1_id == current_user_id, Conversation.user2_id == friend.id),
                and_(Conversation.user1_id == friend.id, Conversation.user2_id == current_user_id)
            )
        ).first()

        friends.append({
            'id': friend.id,
            'username': friend.username,
            'first_name': friend.first_name,
            'last_name': friend.last_name,
            'avatar': friend.avatar,
            'display_name': friend.display_name or f"{friend.first_name} {friend.last_name}",
            'is_online': is_online,
            'last_seen': last_seen,
            'is_close_friend': friendship.is_close_friend,
            'friendship_id': friendship.id,
            'since': friendship.updated_at.isoformat(),
            'conversation_id': conversation.id if conversation else None
        })

    return jsonify({'friends': friends}), 200

@friends_bp.route('/friends/pending', methods=['GET'])
@jwt_required()
def get_pending_friend_requests():
    """Get pending friend requests (both sent and received)"""
    current_user_id = int(get_jwt_identity())
    
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
        'pending_requests': received,  # Client expects pending_requests
        'received': received,  # Keep for backward compatibility
        'sent': sent
    }), 200

@friends_bp.route('/friends/search', methods=['GET'])
@jwt_required()
def search_users():
    """Search for users by username, name, or email"""
    current_user_id = int(get_jwt_identity())
    query = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 50)
    
    if not query or len(query) < 2:
        return jsonify({'error': 'Search query must be at least 2 characters'}), 400
    
    # Get list of blocked user IDs
    blocked_ids = db.session.query(BlockedUser.blocked_id).filter_by(blocker_id=current_user_id).subquery()
    blocking_ids = db.session.query(BlockedUser.blocker_id).filter_by(blocked_id=current_user_id).subquery()
    
    # Search users excluding blocked relationships and self
    users = Users.query.filter(
        and_(
            Users.id != current_user_id,
            Users.id.notin_(blocked_ids),
            Users.id.notin_(blocking_ids),
            or_(
                Users.username.ilike(f'%{query}%'),
                Users.first_name.ilike(f'%{query}%'),
                Users.last_name.ilike(f'%{query}%'),
                Users.email.ilike(f'%{query}%'),
                Users.display_name.ilike(f'%{query}%')
            )
        )
    ).limit(limit).all()
    
    results = []
    for user in users:
        # Check friendship status
        friendship = Friendship.query.filter(
            or_(
                and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == user.id),
                and_(Friendship.requester_id == user.id, Friendship.addressee_id == current_user_id)
            )
        ).first()
        
        friendship_status = None
        if friendship:
            if friendship.status == 'accepted':
                friendship_status = 'friends'
            elif friendship.status == 'pending':
                if friendship.requester_id == current_user_id:
                    friendship_status = 'request_sent'
                else:
                    friendship_status = 'request_received'
        
        # Get user activity
        activity = UserActivity.query.filter_by(user_id=user.id).first()
        
        results.append({
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'avatar': user.avatar,
            'display_name': user.display_name or f"{user.first_name} {user.last_name}",
            'bio': user.bio,
            'friendship_status': friendship_status,
            'is_online': activity.is_online if activity else False,
            'last_seen': activity.last_seen.isoformat() if activity else None
        })
    
    return jsonify({'results': results, 'count': len(results)}), 200

@friends_bp.route('/friends/request', methods=['POST'])
@jwt_required()
def send_friend_request():
    """Send a friend request with blocking check"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    
    if not data or 'user_id' not in data:
        return jsonify({'error': 'User ID is required'}), 400
    
    target_user_id = data['user_id']
    
    if target_user_id == current_user_id:
        return jsonify({'error': 'Cannot send friend request to yourself'}), 400
    
    # Check if blocked
    if is_blocked(current_user_id, target_user_id):
        return jsonify({'error': 'Cannot send friend request to blocked user'}), 403
    
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
            if existing_friendship.requester_id == current_user_id:
                return jsonify({'error': 'Friend request already sent'}), 400
            else:
                # Auto-accept if both users sent requests to each other
                existing_friendship.status = 'accepted'
                existing_friendship.updated_at = datetime.utcnow()
                db.session.commit()
                
                # Ensure conversation exists
                conversation = ensure_conversation(current_user_id, target_user_id)
                db.session.commit()
                
                # Notify both users
                payload = {
                    'id': target_user.id,
                    'username': target_user.username,
                    'first_name': target_user.first_name,
                    'last_name': target_user.last_name,
                    'avatar': target_user.avatar,
                    'display_name': target_user.display_name or f"{target_user.first_name} {target_user.last_name}",
                    'is_online': True, # Should verify actual status
                    'friendship_id': existing_friendship.id,
                    'conversation_id': conversation.id,
                }
                notify_friend_request_response(current_user_id, target_user_id, 'accepted', existing_friendship.id, payload)
                
                current_user = Users.query.get(current_user_id)
                payload_requester = {
                    'id': current_user.id,
                    'username': current_user.username,
                    'first_name': current_user.first_name,
                    'last_name': current_user.last_name,
                    'avatar': current_user.avatar,
                    'display_name': current_user.display_name or f"{current_user.first_name} {current_user.last_name}",
                    'is_online': True,
                    'friendship_id': existing_friendship.id,
                    'conversation_id': conversation.id,
                }
                notify_friend_request_response(target_user_id, current_user_id, 'accepted', existing_friendship.id, payload_requester)
                
                return jsonify({
                    'message': 'Friend request automatically accepted (mutual request)',
                    'friendship_id': existing_friendship.id,
                    'conversation_id': conversation.id
                }), 200
    
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
    current_user_id = int(get_jwt_identity())
    
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

    requester = Users.query.get(friendship.requester_id)
    addressee = Users.query.get(current_user_id)

    if requester and addressee:
        # Automatically create conversation
        conversation = ensure_conversation(requester.id, addressee.id)
        db.session.commit()

        # Invalidate cache if redis is available (import locally to avoid circular dep)
        try:
            from redis_config import get_redis_client
            redis_client = get_redis_client()
            if redis_client:
                redis_client.delete(f"user:{requester.id}:conversations")
                redis_client.delete(f"user:{addressee.id}:conversations")
        except ImportError:
            pass

        payload = {
            'id': addressee.id,
            'username': addressee.username,
            'first_name': addressee.first_name,
            'last_name': addressee.last_name,
            'avatar': addressee.avatar,
            'display_name': addressee.display_name or f"{addressee.first_name} {addressee.last_name}",
            'is_online': True,
            'friendship_id': friendship.id,
            'conversation_id': conversation.id,
        }
        notify_friend_request_response(friendship.requester_id, current_user_id, 'accepted', friendship.id, payload)
        
        payload_requester = {
            'id': requester.id,
            'username': requester.username,
            'first_name': requester.first_name,
            'last_name': requester.last_name,
            'avatar': requester.avatar,
            'display_name': requester.display_name or f"{requester.first_name} {requester.last_name}",
            'is_online': True,
            'friendship_id': friendship.id,
            'conversation_id': conversation.id,
        }
        notify_friend_request_response(current_user_id, friendship.requester_id, 'accepted', friendship.id, payload_requester)
    
    return jsonify({'message': 'Friend request accepted'}), 200

@friends_bp.route('/friends/request/<int:request_id>/decline', methods=['POST'])
@jwt_required()
def decline_friend_request(request_id):
    """Decline a friend request"""
    current_user_id = int(get_jwt_identity())
    
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

    notify_friend_request_response(friendship.requester_id, current_user_id, 'declined', friendship.id)
    notify_friend_request_response(current_user_id, friendship.requester_id, 'declined', friendship.id)

    return jsonify({'message': 'Friend request declined'}), 200

@friends_bp.route('/friends/<int:friend_id>/remove', methods=['DELETE'])
@jwt_required()
def remove_friend(friend_id):
    """Remove a friend"""
    current_user_id = int(get_jwt_identity())

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

    notify_friend_request_response(friend_id, current_user_id, 'removed', friendship.id)
    notify_friend_request_response(current_user_id, friend_id, 'removed', friendship.id)

    return jsonify({'message': 'Friend removed successfully'}), 200


@friends_bp.route('/friends/<int:friend_id>/close', methods=['POST'])
@jwt_required()
def toggle_close_friend(friend_id):
    """Toggle close friend status"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    is_close = bool(data.get('is_close', True))

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

    friendship.is_close_friend = is_close
    friendship.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'message': 'Close friend status updated', 'is_close_friend': friendship.is_close_friend}), 200


@friends_bp.route('/friends/<int:friend_id>/block', methods=['POST'])
@jwt_required()
def block_friend(friend_id):
    """Block a user and remove existing friendship."""
    current_user_id = int(get_jwt_identity())

    if friend_id == current_user_id:
        return jsonify({'error': 'Cannot block yourself'}), 400

    target_user = Users.query.get(friend_id)
    if not target_user:
        return jsonify({'error': 'User not found'}), 404

    existing_block = BlockedUser.query.filter_by(blocker_id=current_user_id, blocked_id=friend_id).first()
    if existing_block:
        return jsonify({'message': 'User already blocked'}), 200

    block = BlockedUser(blocker_id=current_user_id, blocked_id=friend_id)
    db.session.add(block)

    friendship = Friendship.query.filter(
        or_(
            and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == friend_id),
            and_(Friendship.requester_id == friend_id, Friendship.addressee_id == current_user_id)
        )
    ).first()
    if friendship:
        db.session.delete(friendship)

    db.session.commit()

    return jsonify({'message': 'User blocked successfully'}), 200


@friends_bp.route('/friends/<int:friend_id>/unblock', methods=['POST'])
@jwt_required()
def unblock_friend(friend_id):
    """Unblock a previously blocked user."""
    current_user_id = int(get_jwt_identity())

    block = BlockedUser.query.filter_by(blocker_id=current_user_id, blocked_id=friend_id).first()

    if not block:
        return jsonify({'error': 'User is not blocked'}), 404

    db.session.delete(block)
    db.session.commit()

    return jsonify({'message': 'User unblocked successfully'}), 200

@friends_bp.route('/friends/block', methods=['POST'])
@jwt_required()
def block_user():
    """Block a user (JSON body version)"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    
    if not data or 'user_id' not in data:
        return jsonify({'error': 'User ID is required'}), 400
    
    target_user_id = data['user_id']
    reason = data.get('reason', '')
    
    if target_user_id == current_user_id:
        return jsonify({'error': 'Cannot block yourself'}), 400
    
    # Check if user exists
    target_user = Users.query.get(target_user_id)
    if not target_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if already blocked
    existing_block = BlockedUser.query.filter_by(
        blocker_id=current_user_id,
        blocked_id=target_user_id
    ).first()
    
    if existing_block:
        return jsonify({'error': 'User is already blocked'}), 400
    
    # Create block relationship
    block = BlockedUser(
        blocker_id=current_user_id,
        blocked_id=target_user_id,
        reason=reason
    )
    
    # Remove any existing friendship
    friendship = Friendship.query.filter(
        or_(
            and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == target_user_id),
            and_(Friendship.requester_id == target_user_id, Friendship.addressee_id == current_user_id)
        )
    ).first()
    
    if friendship:
        db.session.delete(friendship)
    
    db.session.add(block)
    db.session.commit()
    
    return jsonify({'message': 'User blocked successfully'}), 200

@friends_bp.route('/friends/unblock', methods=['POST'])
@jwt_required()
def unblock_user():
    """Unblock a user (JSON body version)"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    
    if not data or 'user_id' not in data:
        return jsonify({'error': 'User ID is required'}), 400
    
    target_user_id = data['user_id']
    
    block = BlockedUser.query.filter_by(
        blocker_id=current_user_id,
        blocked_id=target_user_id
    ).first()
    
    if not block:
        return jsonify({'error': 'User is not blocked'}), 404
    
    db.session.delete(block)
    db.session.commit()
    
    return jsonify({'message': 'User unblocked successfully'}), 200

@friends_bp.route('/friends/blocked', methods=['GET'])
@jwt_required()
def get_blocked_users():
    """Get list of blocked users"""
    current_user_id = int(get_jwt_identity())
    
    blocked_relationships = BlockedUser.query.filter_by(blocker_id=current_user_id).all()
    
    blocked_users = []
    for relationship in blocked_relationships:
        user = Users.query.get(relationship.blocked_id)
        if user:
            blocked_users.append({
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'avatar': user.avatar,
                'display_name': user.display_name or f"{user.first_name} {user.last_name}",
                'blocked_at': relationship.created_at.isoformat(),
                'reason': relationship.reason
            })
    
    return jsonify({'blocked_users': blocked_users}), 200

@friends_bp.route('/friends/mutual/<int:user_id>', methods=['GET'])
@jwt_required()
def get_mutual_friends(user_id):
    """Get mutual friends between current user and another user"""
    current_user_id = int(get_jwt_identity())
    
    if user_id == current_user_id:
        return jsonify({'error': 'Cannot get mutual friends with yourself'}), 400
    
    # Check if blocked
    if is_blocked(current_user_id, user_id):
        return jsonify({'error': 'Cannot view mutual friends with blocked user'}), 403
    
    # Get current user's friends
    current_user_friends = db.session.query(
        func.coalesce(Friendship.requester_id, Friendship.addressee_id)
    ).filter(
        and_(
            or_(
                Friendship.requester_id == current_user_id,
                Friendship.addressee_id == current_user_id
            ),
            Friendship.status == 'accepted'
        )
    ).subquery()
    
    # Get target user's friends
    target_user_friends = db.session.query(
        func.coalesce(Friendship.requester_id, Friendship.addressee_id)
    ).filter(
        and_(
            or_(
                Friendship.requester_id == user_id,
                Friendship.addressee_id == user_id
            ),
            Friendship.status == 'accepted'
        )
    ).subquery()
    
    # Find mutual friends
    mutual_friend_ids = db.session.query(
        Friendship.requester_id
    ).filter(
        and_(
            Friendship.requester_id.in_(current_user_friends),
            Friendship.requester_id.in_(target_user_friends),
            Friendship.requester_id != current_user_id,
            Friendship.requester_id != user_id
        )
    ).union(
        db.session.query(
            Friendship.addressee_id
        ).filter(
            and_(
                Friendship.addressee_id.in_(current_user_friends),
                Friendship.addressee_id.in_(target_user_friends),
                Friendship.addressee_id != current_user_id,
                Friendship.addressee_id != user_id
            )
        )
    ).distinct().all()
    
    mutual_friends = []
    for (friend_id,) in mutual_friend_ids:
        friend = Users.query.get(friend_id)
        if friend:
            activity = UserActivity.query.filter_by(user_id=friend_id).first()
            mutual_friends.append({
                'id': friend.id,
                'username': friend.username,
                'first_name': friend.first_name,
                'last_name': friend.last_name,
                'avatar': friend.avatar,
                'display_name': friend.display_name or f"{friend.first_name} {friend.last_name}",
                'is_online': activity.is_online if activity else False
            })
    
    return jsonify({'mutual_friends': mutual_friends, 'count': len(mutual_friends)}), 200

@friends_bp.route('/friends/activity/update', methods=['POST'])
@jwt_required()
def update_activity_status():
    """Update user's activity status"""
    current_user_id = int(get_jwt_identity())
    data = request.get_json()
    
    status = data.get('status', 'available')
    status_message = data.get('status_message', '')
    
    if status not in ['available', 'away', 'busy', 'offline']:
        return jsonify({'error': 'Invalid status'}), 400
    
    activity = update_user_activity(current_user_id, status != 'offline')
    activity.current_status = status
    activity.status_message = status_message[:255] if status_message else None
    db.session.commit()
    
    # Broadcast status update to friends
    friends = Friendship.query.filter(
        and_(
            or_(
                Friendship.requester_id == current_user_id,
                Friendship.addressee_id == current_user_id
            ),
            Friendship.status == 'accepted'
        )
    ).all()
    
    for friendship in friends:
        friend_id = friendship.addressee_id if friendship.requester_id == current_user_id else friendship.requester_id
        # TODO: Emit socket event when socketio is available
        # socketio.emit('friend_status_update', {
        #     'user_id': current_user_id,
        #     'status': status,
        #     'status_message': status_message,
        #     'is_online': status != 'offline'
        # }, room=f'user_{friend_id}')
    
    return jsonify({
        'message': 'Activity status updated',
        'status': status,
        'status_message': status_message
    }), 200

@friends_bp.route('/friends/activity/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user_activity(user_id):
    """Get a user's activity status"""
    current_user_id = int(get_jwt_identity())
    
    # Check if blocked
    if is_blocked(current_user_id, user_id):
        return jsonify({'error': 'Cannot view activity of blocked user'}), 403
    
    # Check if friends (optional: only allow friends to see activity)
    friendship = Friendship.query.filter(
        and_(
            or_(
                and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == user_id),
                and_(Friendship.requester_id == user_id, Friendship.addressee_id == current_user_id)
            ),
            Friendship.status == 'accepted'
        )
    ).first()
    
    if not friendship and user_id != current_user_id:
        return jsonify({'error': 'Can only view activity of friends'}), 403
    
    activity = UserActivity.query.filter_by(user_id=user_id).first()
    
    if not activity:
        return jsonify({
            'user_id': user_id,
            'is_online': False,
            'last_seen': None,
            'status': 'offline',
            'status_message': None
        }), 200
    
    # Consider user offline if last seen > 5 minutes ago
    is_online = activity.is_online and (datetime.utcnow() - activity.last_seen).seconds < 300
    
    return jsonify({
        'user_id': user_id,
        'is_online': is_online,
        'last_seen': activity.last_seen.isoformat(),
        'status': activity.current_status if is_online else 'offline',
        'status_message': activity.status_message
    }), 200

@friends_bp.route('/friends/online', methods=['GET'])
@jwt_required()
def get_online_friends():
    """Get list of online friends"""
    current_user_id = int(get_jwt_identity())
    
    # Get all accepted friendships
    friendships = Friendship.query.filter(
        and_(
            or_(
                Friendship.requester_id == current_user_id,
                Friendship.addressee_id == current_user_id
            ),
            Friendship.status == 'accepted'
        )
    ).all()
    
    online_friends = []
    for friendship in friendships:
        friend_id = friendship.addressee_id if friendship.requester_id == current_user_id else friendship.requester_id
        
        # Check if friend is online
        activity = UserActivity.query.filter_by(user_id=friend_id).first()
        if activity and activity.is_online and (datetime.utcnow() - activity.last_seen).seconds < 300:
            friend = Users.query.get(friend_id)
            if friend:
                online_friends.append({
                    'id': friend.id,
                    'username': friend.username,
                    'first_name': friend.first_name,
                    'last_name': friend.last_name,
                    'avatar': friend.avatar,
                    'display_name': friend.display_name or f"{friend.first_name} {friend.last_name}",
                    'status': activity.current_status,
                    'status_message': activity.status_message,
                    'last_seen': activity.last_seen.isoformat()
                })
    
    return jsonify({'online_friends': online_friends, 'count': len(online_friends)}), 200

@friends_bp.route('/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    """Get all conversations for current user"""
    current_user_id = int(get_jwt_identity())
    
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
        
        activity = UserActivity.query.filter_by(user_id=other_user.id).first()
        is_online = bool(activity and activity.is_online)
        last_seen = activity.last_seen.isoformat() if activity and activity.last_seen else None

        friendship = Friendship.query.filter(
            and_(
                or_(
                    and_(Friendship.requester_id == current_user_id, Friendship.addressee_id == other_user.id),
                    and_(Friendship.requester_id == other_user.id, Friendship.addressee_id == current_user_id)
                ),
                Friendship.status == 'accepted'
            )
        ).first()

        conversations_data.append({
            'conversation_id': conv.id,
            'friend': {
                'id': other_user.id,
                'username': other_user.username,
                'first_name': other_user.first_name,
                'last_name': other_user.last_name,
                'avatar': other_user.avatar,
                'is_online': is_online,
                'last_seen': last_seen,
                'is_close_friend': friendship.is_close_friend if friendship else False,
                'friendship_id': friendship.id if friendship else None,
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
    current_user_id = int(get_jwt_identity())
    
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
    current_user_id = int(get_jwt_identity())
    
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