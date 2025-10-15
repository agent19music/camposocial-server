from flask_socketio import emit, join_room, leave_room, disconnect
from flask_jwt_extended import decode_token
from flask import request
from datetime import datetime
from models import db, Users, Friendship, Conversation, EnhancedNotification, Yap
from models_blocking import UserActivity
from sqlalchemy import or_, and_
import json

# Store for user connections - improved for scalability
active_users = {}  # {user_id: [socket_ids]}
user_rooms = {}    # {socket_id: user_id}
user_connections = {}  # Keep for backwards compatibility

# Store for notification counters per user
notification_counters = {}

# Store for yap counters per user
yap_counters = {}

# Global socketio instance - will be set by register_socket_handlers
socketio_instance = None

def authenticate_socket(auth_token):
    """Authenticate WebSocket connection using JWT token"""
    try:
        decoded = decode_token(auth_token)
        return decoded['sub']  # Returns user_id
    except Exception as e:
        print(f"Socket authentication failed: {e}")
        return None

def update_user_activity_status(user_id, is_online):
    """Update user activity in database"""
    try:
        activity = UserActivity.query.filter_by(user_id=user_id).first()
        if not activity:
            activity = UserActivity(user_id=user_id)
            db.session.add(activity)
        
        activity.last_seen = datetime.utcnow()
        activity.is_online = is_online
        activity.current_status = 'available' if is_online else 'offline'
        
        db.session.commit()
        print(f"Updated activity for user {user_id}: {'online' if is_online else 'offline'}")
        
    except Exception as e:
        print(f"Error updating user activity: {e}")
        db.session.rollback()

def notify_friends_status_change(user_id, is_online):
    """Notify friends when user comes online/offline"""
    try:
        # Get user's friends
        friends = db.session.query(Friendship).filter(
            and_(
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id
                ),
                Friendship.status == 'accepted'
            )
        ).all()
        
        user = Users.query.get(user_id)
        
        for friendship in friends:
            friend_id = friendship.addressee_id if friendship.requester_id == user_id else friendship.requester_id
            
            if socketio_instance:
                socketio_instance.emit('friend_status_change', {
                    'user_id': user_id,
                    'username': user.username,
                    'is_online': is_online,
                    'timestamp': datetime.utcnow().isoformat()
                }, room=f'user_{friend_id}')
                
    except Exception as e:
        print(f"Error notifying friends of status change: {e}")

def register_socket_handlers(socketio):
    """Register all WebSocket event handlers"""
    global socketio_instance
    socketio_instance = socketio
    
    @socketio.on('authenticate')
    def handle_authenticate(data):
        """Authenticate user and set up their connection"""
        auth_token = data.get('token')
        user_id = authenticate_socket(auth_token)
        
        if not user_id:
            emit('error', {'message': 'Authentication failed'})
            disconnect()
            return
        
        # Store user's socket ID in improved structure
        if user_id not in active_users:
            active_users[user_id] = []
        active_users[user_id].append(request.sid)
        user_rooms[request.sid] = user_id
        
        # Keep backwards compatibility
        user_connections[user_id] = request.sid
        
        # Initialize notification counters for the user
        if user_id not in notification_counters:
            notification_counters[user_id] = {
                'friend_requests': 0,
                'yap_notifications': 0,
                'general_notifications': 0
            }
        
        # Initialize yap counters for the user
        if user_id not in yap_counters:
            yap_counters[user_id] = {
                'new_yaps_count': 0,
                'last_seen_yap_time': datetime.utcnow()
            }
        
        # Join user's personal room for notifications
        join_room(f'user_{user_id}')
        
        # Update user activity - ONLINE
        update_user_activity_status(user_id, True)
        
        # Send current notification counts
        send_notification_counts(user_id)
        
        # Send current yap counts
        send_yap_counts(user_id)
        
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
        notify_friends_status_change(user_id, True)
        
        print(f"User {user_id} authenticated with socket {request.sid}")
    
    @socketio.on('connect')
    def handle_connect(auth):
        """Handle WebSocket connection with JWT authentication"""
        try:
            if not auth or 'token' not in auth:
                print("No token provided")
                disconnect()
                return False
            
            token = auth['token']
            if token.startswith('Bearer '):
                token = token[7:]
            
            try:
                decoded_token = decode_token(token)
                user_id = decoded_token['sub']
            except Exception as e:
                print(f"Token decode error: {e}")
                disconnect()
                return False
            
            session_id = request.sid
            
            # Update session tracking
            if user_id not in active_users:
                active_users[user_id] = []
            active_users[user_id].append(session_id)
            user_rooms[session_id] = user_id
            
            # Join user room for notifications
            join_room(f'user_{user_id}')
            
            # Update user activity - ONLINE
            update_user_activity_status(user_id, True)
            
            # Notify friends of online status
            notify_friends_status_change(user_id, True)
            
            emit('connected', {'status': 'success', 'user_id': user_id})
            print(f"User {user_id} connected with session {session_id}")
            
        except Exception as e:
            print(f"Connection error: {e}")
            disconnect()
            return False
    
    @socketio.on('message')
    def handle_message(data):
        """Handle real-time message sending"""
        session_id = request.sid
        if session_id not in user_rooms:
            return
        
        sender_id = user_rooms[session_id]
        recipient_id = data.get('recipient_id')
        message_content = data.get('content')
        conversation_id = data.get('conversation_id')
        
        # Emit to recipient if online
        emit('new_message', {
            'sender_id': sender_id,
            'content': message_content,
            'conversation_id': conversation_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{recipient_id}')
    
    @socketio.on('typing')
    def handle_typing(data):
        """Handle typing indicators"""
        session_id = request.sid
        if session_id not in user_rooms:
            return
        
        sender_id = user_rooms[session_id]
        recipient_id = data.get('recipient_id')
        is_typing = data.get('is_typing', False)
        
        emit('user_typing', {
            'user_id': sender_id,
            'is_typing': is_typing
        }, room=f'user_{recipient_id}')
        
        # Also handle conversation-based typing (for backwards compatibility)
        conversation_id = data.get('conversation_id')
        user_id = data.get('user_id')
        
        if conversation_id and user_id:
            # Emit to everyone in conversation except sender
            emit('typing_indicator', {
                'user_id': user_id,
                'is_typing': is_typing,
                'conversation_id': conversation_id
            }, room=str(conversation_id), include_self=False)
        
        print(f"User {sender_id} {'is' if is_typing else 'stopped'} typing")
    
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
    
    @socketio.on('mark_yaps_seen')
    def handle_mark_yaps_seen(data):
        """Mark yaps as seen for the authenticated user"""
        auth_token = data.get('token')
        user_id = authenticate_socket(auth_token)
        
        if not user_id:
            emit('error', {'message': 'Authentication required'})
            return
        
        mark_yaps_as_seen(user_id)
        print(f"User {user_id} marked yaps as seen")
    
    @socketio.on('mark_friend_requests_seen')
    def handle_mark_friend_requests_seen(data):
        """Mark friend requests as seen for the authenticated user"""
        auth_token = data.get('token')
        user_id = authenticate_socket(auth_token)
        
        if not user_id:
            emit('error', {'message': 'Authentication required'})
            return
        
        mark_friend_requests_as_seen(user_id)
        print(f"User {user_id} marked friend requests as seen")
    
    @socketio.on('get_notification_counts')
    def handle_get_notification_counts(data):
        """Get current notification counts for the authenticated user"""
        auth_token = data.get('token')
        user_id = authenticate_socket(auth_token)
        
        if not user_id:
            emit('error', {'message': 'Authentication required'})
            return
        
        send_notification_counts(user_id)
        send_yap_counts(user_id)
        print(f"Sent notification counts to user {user_id}")
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle user disconnection"""
        session_id = request.sid
        
        if session_id in user_rooms:
            user_id = user_rooms[session_id]
            
            # Remove session from tracking
            if user_id in active_users:
                active_users[user_id] = [sid for sid in active_users[user_id] if sid != session_id]
                
                # If no more sessions, mark user offline
                if not active_users[user_id]:
                    del active_users[user_id]
                    update_user_activity_status(user_id, False)
                    notify_friends_status_change(user_id, False)
            
            del user_rooms[session_id]
            leave_room(f'user_{user_id}')
            
            # Update backwards compatibility dict
            if user_id in user_connections and user_connections[user_id] == session_id:
                del user_connections[user_id]
            
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

def send_notification_counts(user_id):
    """Send current notification counts to a user"""
    try:
        # Get unread friend requests count
        friend_requests_count = Friendship.query.filter_by(
            addressee_id=user_id,
            status='pending'
        ).count()
        
        # Get all pending friend requests with full data
        pending_requests = Friendship.query.filter_by(
            addressee_id=user_id,
            status='pending'
        ).all()
        
        requests_data = []
        for request in pending_requests:
            requester = Users.query.get(request.requester_id)
            if requester:
                requests_data.append({
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
        
        # Get unread general notifications count
        general_notifications_count = EnhancedNotification.query.filter_by(
            recipient_id=user_id,
            is_read=False
        ).count()
        
        # Update counters
        notification_counters[user_id] = {
            'friend_requests': friend_requests_count,
            'general_notifications': general_notifications_count
        }
        
        # Emit to user's personal room
        emit('notification_counts_update', {
            'friend_requests': friend_requests_count,
            'general_notifications': general_notifications_count,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
        # Also emit the full pending requests data
        emit('pending_requests_update', {
            'pending_requests': requests_data,
            'count': friend_requests_count,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
    except Exception as e:
        print(f"Error sending notification counts to user {user_id}: {e}")

def send_yap_counts(user_id):
    """Send current new yaps count to a user"""
    try:
        # Get user's last seen yap time (you might want to store this in the database)
        last_seen_time = yap_counters.get(user_id, {}).get('last_seen_yap_time', datetime.utcnow())
        
        # Get new yaps count since last seen
        new_yaps_count = Yap.query.filter(
            Yap.created_at > last_seen_time,
            Yap.author_id != user_id  # Don't count user's own yaps
        ).count()
        
        # Get recent yaps with author info for the "2 new yaps (with avatars)" feature
        recent_yaps = Yap.query.filter(
            Yap.created_at > last_seen_time,
            Yap.author_id != user_id
        ).order_by(Yap.created_at.desc()).limit(5).all()
        
        recent_authors = []
        for yap in recent_yaps:
            author_info = {
                'id': yap.author.id,
                'username': yap.author.username,
                'avatar': yap.author.avatar,
                'display_name': yap.author.display_name or f"{yap.author.first_name} {yap.author.last_name}"
            }
            if author_info not in recent_authors:
                recent_authors.append(author_info)
        
        # Update counters
        yap_counters[user_id]['new_yaps_count'] = new_yaps_count
        
        # Emit to user's personal room
        emit('yap_counts_update', {
            'new_yaps_count': new_yaps_count,
            'recent_authors': recent_authors[:3],  # Limit to 3 authors for UI
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
    except Exception as e:
        print(f"Error sending yap counts to user {user_id}: {e}")

def notify_friend_request(recipient_id, sender_id):
    """Send real-time notification for new friend request"""
    try:
        if not socketio_instance:
            return
            
        sender = Users.query.get(sender_id)
        if not sender:
            return
        
        # Get the actual friendship request
        friendship = Friendship.query.filter_by(
            requester_id=sender_id,
            addressee_id=recipient_id,
            status='pending'
        ).first()
        
        if not friendship:
            return
        
        # Send simplified real-time notification
        socketio_instance.emit('friend_request', {
            'sender': {
                'id': sender.id,
                'username': sender.username,
                'first_name': sender.first_name,
                'last_name': sender.last_name,
                'avatar': sender.avatar,
                'display_name': sender.display_name or f"{sender.first_name} {sender.last_name}"
            },
            'friendship_id': friendship.id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{recipient_id}')
        
        print(f"Sent friend request notification to user {recipient_id} from {sender.username}")
        
    except Exception as e:
        print(f"Error notifying friend request: {e}")

def notify_new_yap(yap_id, author_id):
    """Send real-time notification for new yap to all users (except author)"""
    try:
        yap = Yap.query.get(yap_id)
        if not yap:
            return
        
        author = Users.query.get(author_id)
        if not author:
            return
        
        # Get all connected users except the author
        for user_id, socket_id in user_connections.items():
            if user_id != author_id:
                # Increment yap counter for each user
                if user_id not in yap_counters:
                    yap_counters[user_id] = {'new_yaps_count': 0, 'last_seen_yap_time': datetime.utcnow()}
                yap_counters[user_id]['new_yaps_count'] += 1
                
                # Emit real-time yap notification
                emit('new_yap_notification', {
                    'yap': {
                        'id': yap.id,
                        'content': yap.content[:100] + '...' if len(yap.content) > 100 else yap.content
                    },
                    'author': {
                        'id': author.id,
                        'username': author.username,
                        'avatar': author.avatar,
                        'display_name': author.display_name or f"{author.first_name} {author.last_name}"
                    },
                    'new_yaps_count': yap_counters[user_id]['new_yaps_count'],
                    'timestamp': datetime.utcnow().isoformat()
                }, room=f'user_{user_id}')
        
        print(f"Sent new yap notification for yap {yap_id} by {author.username}")
        
    except Exception as e:
        print(f"Error notifying new yap: {e}")

def mark_yaps_as_seen(user_id):
    """Mark yaps as seen for a user (reset counter)"""
    try:
        if user_id in yap_counters:
            yap_counters[user_id]['new_yaps_count'] = 0
            yap_counters[user_id]['last_seen_yap_time'] = datetime.utcnow()
        
        # Emit updated counts
        emit('yap_counts_update', {
            'new_yaps_count': 0,
            'recent_authors': [],
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
    except Exception as e:
        print(f"Error marking yaps as seen for user {user_id}: {e}")

def notify_friend_request_response(requester_id, recipient_id, action, friendship_id):
    """Send real-time notification when a friend request is accepted/declined"""
    try:
        if action not in ['accepted', 'declined'] or not socketio_instance:
            return
            
        recipient = Users.query.get(recipient_id)
        if not recipient:
            return
        
        # Notify the original requester
        socketio_instance.emit('friend_request_response', {
            'action': action,
            'friendship_id': friendship_id,
            'recipient': {
                'id': recipient.id,
                'username': recipient.username,
                'first_name': recipient.first_name,
                'last_name': recipient.last_name,
                'avatar': recipient.avatar,
                'display_name': recipient.display_name or f"{recipient.first_name} {recipient.last_name}"
            },
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{requester_id}')
        
        print(f"Sent friend request {action} notification to user {requester_id}")
        
    except Exception as e:
        print(f"Error notifying friend request response: {e}")
        
        print(f"Sent friend request {action} notification to user {requester_id}")
        
    except Exception as e:
        print(f"Error notifying friend request response: {e}")

def get_user_pending_requests(user_id):
    """Get formatted pending requests for a user"""
    try:
        pending_requests = Friendship.query.filter_by(
            addressee_id=user_id,
            status='pending'
        ).all()
        
        requests_data = []
        for request in pending_requests:
            requester = Users.query.get(request.requester_id)
            if requester:
                requests_data.append({
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
        
        return requests_data
        
    except Exception as e:
        print(f"Error getting pending requests for user {user_id}: {e}")
        return []

def mark_friend_requests_as_seen(user_id):
    """Mark friend requests as seen for a user (reset counter)"""
    try:
        if user_id in notification_counters:
            notification_counters[user_id]['friend_requests'] = 0
        
        # Get updated pending requests count from database
        actual_count = Friendship.query.filter_by(
            addressee_id=user_id,
            status='pending'
        ).count()
        
        # Emit updated counts
        emit('notification_counts_update', {
            'friend_requests': 0,  # Reset to 0 since user has seen them
            'general_notifications': notification_counters.get(user_id, {}).get('general_notifications', 0),
            'actual_pending_count': actual_count,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
    except Exception as e:
        print(f"Error marking friend requests as seen for user {user_id}: {e}")

def notify_new_follower(followed_user_id, follower_id):
    """Send real-time notification when someone follows a user"""
    try:
        follower = Users.query.get(follower_id)
        if not follower or not socketio_instance:
            return
            
        # Emit to the followed user
        socketio_instance.emit('new_follower', {
            'follower_id': follower_id,
            'follower_name': follower.display_name or f"{follower.first_name} {follower.last_name}",
            'follower_avatar': follower.avatar,
            'follower_username': follower.username,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{followed_user_id}')
        
        print(f"Sent new follower notification to user {followed_user_id} from {follower.username}")
        
    except Exception as e:
        print(f"Error notifying new follower: {e}")

def notify_new_reply(yap_author_id, reply_author_id, yap_id, reply_content):
    """Send real-time notification when someone replies to a yap"""
    try:
        # Don't notify if user replies to their own yap
        if yap_author_id == reply_author_id or not socketio_instance:
            return
            
        reply_author = Users.query.get(reply_author_id)
        if not reply_author:
            return
            
        # Truncate reply content for notification
        truncated_content = reply_content[:100] + "..." if len(reply_content) > 100 else reply_content
        
        # Emit to the yap author
        socketio_instance.emit('new_reply', {
            'reply_author_id': reply_author_id,
            'reply_author_name': reply_author.display_name or f"{reply_author.first_name} {reply_author.last_name}",
            'reply_author_avatar': reply_author.avatar,
            'reply_author_username': reply_author.username,
            'yap_id': yap_id,
            'reply_content': truncated_content,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{yap_author_id}')
        
        print(f"Sent new reply notification to user {yap_author_id} from {reply_author.username}")
        
    except Exception as e:
        print(f"Error notifying new reply: {e}")

# Enhanced notification functions
def notify_new_message(sender_id, recipient_id, message_data):
    """Send real-time message notification"""
    if socketio_instance and recipient_id in active_users:
        socketio_instance.emit('new_message', {
            'sender_id': sender_id,
            'message': message_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{recipient_id}')

def get_online_users():
    """Get list of currently online users"""
    return list(active_users.keys())

def is_user_online(user_id):
    """Check if a specific user is online"""
    return user_id in active_users

def notify_yap_like(yap_author_id, liker_id, yap_id):
    """Send real-time notification when someone likes a yap"""
    try:
        # Don't notify if user likes their own yap
        if yap_author_id == liker_id or not socketio_instance:
            return
            
        liker = Users.query.get(liker_id)
        if not liker:
            return
            
        # Emit to the yap author
        socketio_instance.emit('yap_liked', {
            'liker_id': liker_id,
            'liker_name': liker.display_name or f"{liker.first_name} {liker.last_name}",
            'liker_avatar': liker.avatar,
            'liker_username': liker.username,
            'yap_id': yap_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{yap_author_id}')
        
        print(f"Sent yap like notification to user {yap_author_id} from {liker.username}")
        
    except Exception as e:
        print(f"Error notifying yap like: {e}")

def broadcast_new_yap_to_followers(yap_id, author_id):
    """Notify followers about a new yap from someone they follow"""
    try:
        if not socketio_instance:
            return
            
        yap = Yap.query.get(yap_id)
        author = Users.query.get(author_id)
        if not yap or not author:
            return
        
        # Get followers (people who sent friend requests to this user that were accepted)
        followers_query = db.session.query(Friendship).filter(
            Friendship.addressee_id == author_id,
            Friendship.status == 'accepted'
        ).all()
        
        # Also get people this user accepted requests from  
        following_query = db.session.query(Friendship).filter(
            Friendship.requester_id == author_id,
            Friendship.status == 'accepted'
        ).all()
        
        # Combine both sets of connections
        all_connections = set()
        for friendship in followers_query:
            all_connections.add(friendship.requester_id)
        for friendship in following_query:
            all_connections.add(friendship.addressee_id)
        
        # Notify each connected user
        for user_id in all_connections:
            socketio_instance.emit('new_yap_from_following', {
                'yap_id': yap_id,
                'author_id': author_id,
                'author_name': author.display_name or f"{author.first_name} {author.last_name}",
                'author_avatar': author.avatar,
                'author_username': author.username,
                'yap_preview': yap.content[:100] + "..." if len(yap.content) > 100 else yap.content,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'user_{user_id}')
        
        print(f"Broadcasted new yap {yap_id} to {len(all_connections)} followers")
        
    except Exception as e:
        print(f"Error broadcasting new yap to followers: {e}")
