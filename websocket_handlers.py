from flask_socketio import emit, join_room, leave_room, disconnect
from flask_jwt_extended import decode_token
from flask import request
from datetime import datetime
from models import db, Users, Friendship, Conversation
from sqlalchemy import or_, and_
import json

# Store for user connections
user_connections = {}

def authenticate_socket(auth_token):
    """Authenticate WebSocket connection using JWT token"""
    try:
        decoded = decode_token(auth_token)
        return decoded['sub']  # Returns user_id
    except Exception as e:
        print(f"Socket authentication failed: {e}")
        return None

def register_socket_handlers(socketio):
    """Register all WebSocket event handlers"""
    
    @socketio.on('authenticate')
    def handle_authenticate(data):
        """Authenticate user and set up their connection"""
        auth_token = data.get('token')
        user_id = authenticate_socket(auth_token)
        
        if not user_id:
            emit('error', {'message': 'Authentication failed'})
            disconnect()
            return
        
        # Store user's socket ID
        user_connections[user_id] = request.sid
        
        # Join user's personal room for notifications
        join_room(f'user_{user_id}')
        
        # Get user's conversations and join those rooms
        conversations = Conversation.query.filter(
            or_(
                Conversation.user1_id == user_id,
                Conversation.user2_id == user_id
            )
        ).all()
        
        for conv in conversations:
            join_room(str(conv.id))
        
        emit('authenticated', {'user_id': user_id})
        
        # Notify friends of online status
        notify_friends_status(user_id, 'online')
        
        print(f"User {user_id} authenticated with socket {request.sid}")
    
    @socketio.on('typing')
    def handle_typing(data):
        """Handle typing indicators"""
        conversation_id = data.get('conversation_id')
        user_id = data.get('user_id')
        is_typing = data.get('is_typing', False)
        
        if not conversation_id or not user_id:
            return
        
        # Emit to everyone in conversation except sender
        emit('typing_indicator', {
            'user_id': user_id,
            'is_typing': is_typing,
            'conversation_id': conversation_id
        }, room=str(conversation_id), include_self=False)
        
        print(f"User {user_id} {'is' if is_typing else 'stopped'} typing in conversation {conversation_id}")
    
    @socketio.on('message_read')
    def handle_message_read(data):
        """Handle message read receipts"""
        message_ids = data.get('message_ids', [])
        user_id = data.get('user_id')
        conversation_id = data.get('conversation_id')
        
        if not message_ids or not user_id or not conversation_id:
            return
        
        # TODO: Update read status in database
        # For now, just broadcast to other participants
        
        emit('messages_read', {
            'message_ids': message_ids,
            'reader_id': user_id,
            'read_at': datetime.utcnow().isoformat()
        }, room=str(conversation_id), include_self=False)
        
        print(f"User {user_id} read {len(message_ids)} messages in conversation {conversation_id}")
    
    @socketio.on('presence_update')
    def handle_presence_update(data):
        """Update user's presence status"""
        user_id = data.get('user_id')
        status = data.get('status', 'online')  # online, away, offline
        
        if not user_id:
            return
        
        # Update user's last seen time
        user = Users.query.get(user_id)
        if user:
            # You might want to add a last_seen field to Users model
            pass
        
        # Notify friends of status change
        notify_friends_status(user_id, status)
        
        print(f"User {user_id} status updated to {status}")
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle user disconnection"""
        # Find user by socket ID
        user_id = None
        for uid, sid in user_connections.items():
            if sid == request.sid:
                user_id = uid
                break
        
        if user_id:
            # Remove from connections
            del user_connections[user_id]
            
            # Notify friends of offline status
            notify_friends_status(user_id, 'offline')
            
            print(f"User {user_id} disconnected")

def notify_friends_status(user_id, status):
    """Notify all friends about user's online status"""
    try:
        # Get all accepted friendships
        friendships = Friendship.query.filter(
            and_(
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id
                ),
                Friendship.status == 'accepted'
            )
        ).all()
        
        for friendship in friendships:
            friend_id = friendship.addressee_id if friendship.requester_id == user_id else friendship.requester_id
            
            # Emit to friend's personal room
            emit('friend_status_update', {
                'user_id': user_id,
                'status': status,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'user_{friend_id}', namespace='/')
            
        print(f"Notified {len(friendships)} friends about user {user_id} status: {status}")
    except Exception as e:
        print(f"Error notifying friends status: {e}")

def emit_to_user(user_id, event, data):
    """Emit an event to a specific user"""
    if user_id in user_connections:
        emit(event, data, room=user_connections[user_id])
    else:
        # User might be offline, could queue the message
        print(f"User {user_id} is not connected")

def broadcast_to_conversation(conversation_id, event, data, exclude_user=None):
    """Broadcast an event to all users in a conversation"""
    room = str(conversation_id)
    if exclude_user:
        emit(event, data, room=room, skip_sid=user_connections.get(exclude_user))
    else:
        emit(event, data, room=room)
