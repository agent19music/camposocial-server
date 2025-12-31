"""
WebSocket event handlers with Redis-backed multi-session presence support.

This module handles all real-time communication via Socket.IO with proper
support for multiple browser sessions per user.
"""

from flask_socketio import emit, join_room, leave_room, disconnect
from flask_jwt_extended import decode_token
from flask import request, session
from datetime import datetime
import logging
from models import db, Users, Friendship, Conversation, EnhancedNotification, Yap, Message, OfflineNotification
from models_blocking import UserActivity
from sqlalchemy import or_, and_
from presence import get_presence_manager, PresenceManager

logger = logging.getLogger(__name__)

# Global socketio instance - will be set by register_socket_handlers
socketio_instance = None

# Conversation room memberships (still per-socket, but now properly tracked)
# This is fine as in-memory since it's per-socket and managed by Socket.IO rooms
conversation_memberships = {}  # {socket_id: set(conversation_ids)}

# Event constants
HEARTBEAT_ACK_EVENT = 'heartbeat_ack'
JOIN_CONVERSATION_EVENT = 'join_conversation'
LEAVE_CONVERSATION_EVENT = 'leave_conversation'
CONVERSATION_JOINED_EVENT = 'conversation_joined'
CONVERSATION_LEFT_EVENT = 'conversation_left'


def get_presence() -> PresenceManager:
    """Get the presence manager instance."""
    return get_presence_manager()


def authenticate_socket(auth_token: str) -> int | None:
    """Authenticate WebSocket connection using JWT token."""
    try:
        decoded = decode_token(auth_token)
        return decoded['sub']  # Returns user_id
    except Exception as e:
        logger.error(f"Socket authentication failed: {e}")
        return None


def update_user_activity_db(user_id: int, is_online: bool):
    """Update user activity in database (for persistence across restarts)."""
    try:
        activity = UserActivity.query.filter_by(user_id=user_id).first()
        if not activity:
            activity = UserActivity(user_id=user_id)
            db.session.add(activity)
        
        activity.last_seen = datetime.utcnow()
        activity.is_online = is_online
        activity.current_status = 'available' if is_online else 'offline'
        
        db.session.commit()
        logger.info(f"[DB] Updated activity for user {user_id}: {'online' if is_online else 'offline'}")
        
    except Exception as e:
        logger.error(f"Error updating user activity in DB: {e}")
        db.session.rollback()


def refresh_user_last_seen_db(user_id: int):
    """Update only the last_seen timestamp in database."""
    try:
        activity = UserActivity.query.filter_by(user_id=user_id).first()
        if not activity:
            activity = UserActivity(user_id=user_id)
            db.session.add(activity)
        
        activity.last_seen = datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        logger.error(f"Error refreshing user {user_id} last_seen: {exc}")
        db.session.rollback()


def _authorize_conversation(user_id: int, conversation_id: str) -> Conversation | None:
    """Return conversation if user participates; otherwise None."""
    if not conversation_id:
        return None
    
    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return None
    
    if conversation.user1_id != user_id and conversation.user2_id != user_id:
        return None
    
    return conversation


def notify_friends_status_change(user_id: int, is_online: bool):
    """Notify friends when user comes online/offline."""
    try:
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
        if not user:
            return
        
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
        logger.error(f"Error notifying friends of status change: {e}")


def emit_to_user_room(user_id: int, event: str, payload: dict) -> bool:
    """
    Emit an event to a user's personal room.
    All of the user's sockets receive this event.
    """
    if not socketio_instance:
        return False
    
    presence = get_presence()
    if presence.is_user_online(user_id):
        socketio_instance.emit(event, payload, room=f'user_{user_id}')
        return True
    
    return False


def queue_offline_notification(recipient_id: int, notification_type: str, payload: dict):
    """Queue a notification for delivery when user comes online."""
    try:
        import json
        record = OfflineNotification(
            recipient_id=recipient_id,
            type=notification_type,
            payload=json.dumps(payload) if isinstance(payload, dict) else payload
        )
        db.session.add(record)
        db.session.commit()
    except Exception as exc:
        logger.error(f"Error queuing offline notification for user {recipient_id}: {exc}")
        db.session.rollback()


def deliver_offline_notifications(user_id: int):
    """Deliver any queued offline notifications to a user."""
    try:
        queued = OfflineNotification.query.filter_by(
            recipient_id=user_id, 
            delivered_at=None
        ).order_by(OfflineNotification.created_at.asc()).all()
        
        if not queued:
            return
        
        import json
        for record in queued:
            payload = record.payload
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except:
                    pass
            
            if emit_to_user_room(user_id, record.type, payload):
                record.delivered_at = datetime.utcnow()
        
        db.session.commit()
    except Exception as exc:
        logger.error(f"Error delivering offline notifications to user {user_id}: {exc}")
        db.session.rollback()


def register_socket_handlers(socketio):
    """Register all WebSocket event handlers."""
    global socketio_instance
    socketio_instance = socketio
    
    @socketio.on('connect')
    def handle_connect(auth):
        """Handle WebSocket connection with JWT authentication."""
        try:
            if not auth or 'token' not in auth:
                logger.warning("Connection rejected: No token provided")
                disconnect()
                return False
            
            token = auth['token']
            if token.startswith('Bearer '):
                token = token[7:]
            
            try:
                decoded_token = decode_token(token)
                user_id = decoded_token['sub']
            except Exception as e:
                logger.warning(f"Connection rejected: Token decode error: {e}")
                disconnect()
                return False
            
            socket_id = request.sid
            session['user_id'] = user_id
            
            # Register socket in Redis presence system
            presence = get_presence()
            was_offline = presence.register_socket(user_id, socket_id)
            
            # Initialize conversation memberships for this socket
            conversation_memberships[socket_id] = set()
            
            # Join user's personal room for notifications
            join_room(f'user_{user_id}')
            logger.info(f"[WS] User {user_id} joined room user_{user_id} (socket: {socket_id[:8]}...)")
            
            # Update database if user just came online
            if was_offline:
                update_user_activity_db(user_id, True)
                notify_friends_status_change(user_id, True)
            
            # Get user's conversations and send list
            conversations = Conversation.query.filter(
                or_(
                    Conversation.user1_id == user_id,
                    Conversation.user2_id == user_id
                )
            ).all()
            
            joined = [str(conv.id) for conv in conversations]
            
            emit('conversation_list', {
                'conversations': joined,
                'timestamp': datetime.utcnow().isoformat()
            }, room=socket_id)
            
            # Send current notification counts
            try:
                send_notification_counts(user_id)
            except Exception as e:
                logger.warning(f"Failed to send notification counts: {e}")
            
            # Send current yap counts
            try:
                send_yap_counts(user_id)
            except Exception as e:
                logger.warning(f"Failed to send yap counts: {e}")
            
            # Deliver any queued offline notifications
            try:
                deliver_offline_notifications(user_id)
            except Exception as e:
                logger.warning(f"Failed to deliver offline notifications: {e}")
            
            # Send success confirmation
            emit('connected', {
                'status': 'success',
                'user_id': user_id,
                'socket_id': socket_id[:8],
                'rooms_joined': len(joined) + 1,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            socket_count = presence.get_socket_count(user_id)
            logger.info(f"[WS] User {user_id} connected (socket: {socket_id[:8]}..., total sockets: {socket_count})")
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            disconnect()
            return False
    
    @socketio.on('heartbeat')
    def handle_heartbeat(_data=None):
        """Handle heartbeat pings from clients to maintain presence."""
        socket_id = request.sid
        
        presence = get_presence()
        user_id = presence.get_user_from_socket(socket_id)
        
        if not user_id:
            return
        
        # Refresh socket TTL in Redis
        presence.refresh_socket(socket_id)
        
        # Also update DB last_seen periodically
        refresh_user_last_seen_db(user_id)
        
        emit(HEARTBEAT_ACK_EVENT, {
            'timestamp': datetime.utcnow().isoformat()
        }, room=socket_id)
    
    @socketio.on(JOIN_CONVERSATION_EVENT)
    def handle_join_conversation(data):
        """Handle explicit conversation room join requests."""
        socket_id = request.sid
        
        presence = get_presence()
        user_id = presence.get_user_from_socket(socket_id)
        
        if not user_id:
            return
        
        conversation_id = data.get('conversation_id') if isinstance(data, dict) else None
        
        conversation = _authorize_conversation(user_id, conversation_id)
        if not conversation:
            emit('conversation_join_error', {
                'conversation_id': conversation_id,
                'message': 'Conversation not found or access denied.'
            }, room=socket_id)
            return
        
        room_name = str(conversation.id)
        join_room(room_name)
        
        if socket_id in conversation_memberships:
            conversation_memberships[socket_id].add(room_name)
        
        emit(CONVERSATION_JOINED_EVENT, {
            'conversation_id': room_name,
            'timestamp': datetime.utcnow().isoformat()
        }, room=socket_id)
    
    @socketio.on(LEAVE_CONVERSATION_EVENT)
    def handle_leave_conversation(data):
        """Handle explicit conversation room leave requests."""
        socket_id = request.sid
        
        presence = get_presence()
        user_id = presence.get_user_from_socket(socket_id)
        
        if not user_id:
            return
        
        conversation_id = data.get('conversation_id') if isinstance(data, dict) else None
        if not conversation_id:
            return
        
        room_name = str(conversation_id)
        if room_name in conversation_memberships.get(socket_id, set()):
            leave_room(room_name)
            conversation_memberships[socket_id].discard(room_name)
            emit(CONVERSATION_LEFT_EVENT, {
                'conversation_id': room_name,
                'timestamp': datetime.utcnow().isoformat()
            }, room=socket_id)
    
    @socketio.on('typing')
    def handle_typing(data):
        """Handle typing indicators with rate limiting."""
        socket_id = request.sid
        
        presence = get_presence()
        sender_id = presence.get_user_from_socket(socket_id)
        
        if not sender_id:
            return
        
        # Rate limit typing events (30 per minute per user)
        if not presence.check_rate_limit(sender_id, 'typing', max_requests=30):
            return
        
        recipient_id = data.get('recipient_id')
        is_typing = data.get('is_typing', False)
        conversation_id = data.get('conversation_id')
        
        if recipient_id:
            emit('user_typing', {
                'user_id': sender_id,
                'is_typing': is_typing,
                'conversation_id': conversation_id  # Include conversation_id for proper filtering
            }, room=f'user_{recipient_id}')
        
        if conversation_id:
            room_name = str(conversation_id)
            if room_name in conversation_memberships.get(socket_id, set()):
                emit('typing_indicator', {
                    'user_id': sender_id,
                    'is_typing': is_typing,
                    'conversation_id': conversation_id
                }, room=room_name, include_self=False)
        
        logger.debug(f"User {sender_id} {'is' if is_typing else 'stopped'} typing")
    
    @socketio.on('message_read')
    def handle_message_read(data):
        """Handle message read receipts."""
        message_ids = data.get('message_ids', [])
        user_id = data.get('user_id')
        conversation_id = data.get('conversation_id')
        
        if not message_ids or not user_id or not conversation_id:
            return
        
        emit('messages_read', {
            'message_ids': message_ids,
            'reader_id': user_id,
            'read_at': datetime.utcnow().isoformat()
        }, room=str(conversation_id), include_self=False)
        
        logger.debug(f"User {user_id} read {len(message_ids)} messages in conversation {conversation_id}")
    
    @socketio.on('presence_update')
    def handle_presence_update(data):
        """Update user's presence status."""
        socket_id = request.sid
        
        presence = get_presence()
        user_id = presence.get_user_from_socket(socket_id)
        
        if not user_id:
            return
        
        status = data.get('status', 'available')
        presence.update_user_status(user_id, status)
        
        # Notify friends
        notify_friends_status(user_id, status)
        
        logger.debug(f"User {user_id} status updated to {status}")
    
    @socketio.on('mark_yaps_seen')
    def handle_mark_yaps_seen(data):
        """Mark yaps as seen for the authenticated user."""
        user_id = session.get('user_id')
        
        if not user_id:
            emit('error', {'message': 'Authentication required'})
            return
        
        mark_yaps_as_seen(user_id)
        logger.debug(f"User {user_id} marked yaps as seen")
    
    @socketio.on('mark_friend_requests_seen')
    def handle_mark_friend_requests_seen(data):
        """Mark friend requests as seen for the authenticated user."""
        user_id = session.get('user_id')
        
        if not user_id:
            emit('error', {'message': 'Authentication required'})
            return
        
        mark_friend_requests_as_seen(user_id)
        logger.debug(f"User {user_id} marked friend requests as seen")
    
    @socketio.on('get_notification_counts')
    def handle_get_notification_counts(data):
        """Get current notification counts for the authenticated user."""
        user_id = session.get('user_id')
        
        if not user_id:
            emit('error', {'message': 'Authentication required'})
            return
        
        send_notification_counts(user_id)
        send_yap_counts(user_id)
        logger.debug(f"Sent notification counts to user {user_id}")
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle user disconnection."""
        socket_id = request.sid
        
        presence = get_presence()
        user_id, went_offline = presence.unregister_socket(socket_id)
        
        if user_id:
            # Leave user's personal room
            leave_room(f'user_{user_id}')
            
            # Leave all conversation rooms for this socket
            for room_name in list(conversation_memberships.get(socket_id, set())):
                leave_room(room_name)
            conversation_memberships.pop(socket_id, None)
            
            # If user went fully offline, update DB and notify friends
            if went_offline:
                update_user_activity_db(user_id, False)
                notify_friends_status_change(user_id, False)
            
            remaining = presence.get_socket_count(user_id)
            logger.info(f"[WS] User {user_id} disconnected socket {socket_id[:8]}... (remaining: {remaining})")


def notify_friends_status(user_id: int, status: str):
    """Notify all friends about user's online status."""
    try:
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
            
            emit('friend_status_update', {
                'user_id': user_id,
                'status': status,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'user_{friend_id}', namespace='/')
            
        logger.debug(f"Notified {len(friendships)} friends about user {user_id} status: {status}")
    except Exception as e:
        logger.error(f"Error notifying friends status: {e}")


def broadcast_to_conversation(conversation_id: str, event: str, data: dict, exclude_user: int = None):
    """Broadcast an event to all users in a conversation."""
    room = str(conversation_id)
    # Note: exclude_user is deprecated, use include_self=False instead
    emit(event, data, room=room)


def send_notification_counts(user_id: int):
    """Send current notification counts to a user."""
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
        
        # Emit to user's personal room (reaches ALL their sockets)
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
        logger.error(f"Error sending notification counts to user {user_id}: {e}")


# In-memory yap counters - these are per-user and fine as in-memory
# since they're transient display state, not critical data
yap_counters = {}


def send_yap_counts(user_id: int):
    """Send current new yaps count to a user."""
    try:
        last_seen_time = yap_counters.get(user_id, {}).get('last_seen_yap_time', datetime.utcnow())
        
        new_yaps_count = Yap.query.filter(
            Yap.created_at > last_seen_time,
            Yap.user_id != user_id
        ).count()
        
        recent_yaps = Yap.query.filter(
            Yap.created_at > last_seen_time,
            Yap.user_id != user_id
        ).order_by(Yap.created_at.desc()).limit(5).all()
        
        recent_authors = []
        for yap in recent_yaps:
            author_info = {
                'id': yap.user.id,
                'username': yap.user.username,
                'avatar': yap.user.avatar,
                'display_name': yap.user.display_name or f"{yap.user.first_name} {yap.user.last_name}"
            }
            if author_info not in recent_authors:
                recent_authors.append(author_info)
        
        yap_counters[user_id] = {
            'new_yaps_count': new_yaps_count,
            'last_seen_yap_time': yap_counters.get(user_id, {}).get('last_seen_yap_time', datetime.utcnow())
        }
        
        emit('yap_counts_update', {
            'new_yaps_count': new_yaps_count,
            'recent_authors': recent_authors[:3],
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
    except Exception as e:
        logger.error(f"Error sending yap counts to user {user_id}: {e}")


def mark_yaps_as_seen(user_id: int):
    """Mark yaps as seen for a user (reset counter)."""
    try:
        yap_counters[user_id] = {
            'new_yaps_count': 0,
            'last_seen_yap_time': datetime.utcnow()
        }
        
        emit('yap_counts_update', {
            'new_yaps_count': 0,
            'recent_authors': [],
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
    except Exception as e:
        logger.error(f"Error marking yaps as seen for user {user_id}: {e}")


def mark_friend_requests_as_seen(user_id: int):
    """Mark friend requests as seen for a user."""
    try:
        actual_count = Friendship.query.filter_by(
            addressee_id=user_id,
            status='pending'
        ).count()
        
        emit('notification_counts_update', {
            'friend_requests': 0,
            'general_notifications': 0,
            'actual_pending_count': actual_count,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{user_id}')
        
    except Exception as e:
        logger.error(f"Error marking friend requests as seen for user {user_id}: {e}")


def notify_friend_request(recipient_id: int, sender_id: int):
    """Send real-time notification for new friend request."""
    try:
        sender = Users.query.get(sender_id)
        if not sender:
            return
        
        friendship = Friendship.query.filter_by(
            requester_id=sender_id,
            addressee_id=recipient_id,
            status='pending'
        ).first()
        
        if not friendship:
            return
        
        payload = {
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
        }
        
        delivered = emit_to_user_room(recipient_id, 'friend_request', payload)
        
        if not delivered:
            queue_offline_notification(recipient_id, 'friend_request', payload)
        
        logger.info(f"Sent friend request notification to user {recipient_id} from {sender.username}")
        
    except Exception as e:
        logger.error(f"Error notifying friend request: {e}")


def notify_friend_request_response(requester_id: int, recipient_id: int, action: str, friendship_id: int, friend_payload: dict = None):
    """Send real-time notification when a friend request is accepted/declined."""
    try:
        if action not in ['accepted', 'declined', 'removed']:
            return
        
        recipient = Users.query.get(recipient_id)
        if not recipient:
            return
        
        payload = {
            'action': action,
            'friendship_id': friendship_id,
            'timestamp': datetime.utcnow().isoformat(),
            'friend': friend_payload
        }
        
        delivered = emit_to_user_room(requester_id, 'friend_request_response', payload)
        
        if not delivered:
            queue_offline_notification(requester_id, 'friend_request_response', payload)
        
        logger.info(f"Sent friend request {action} notification to user {requester_id}")
        
    except Exception as e:
        logger.error(f"Error notifying friend request response: {e}")


def notify_new_yap(yap_id: int, author_id: int):
    """Send real-time notification for new yap to all online users (except author)."""
    try:
        yap = Yap.query.get(yap_id)
        if not yap:
            return
        
        author = Users.query.get(author_id)
        if not author:
            return
        
        presence = get_presence()
        online_users = presence.get_online_users()
        
        for user_id in online_users:
            if user_id != author_id:
                if user_id not in yap_counters:
                    yap_counters[user_id] = {'new_yaps_count': 0, 'last_seen_yap_time': datetime.utcnow()}
                yap_counters[user_id]['new_yaps_count'] += 1
                
                emit_to_user_room(user_id, 'new_yap_notification', {
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
                })
        
        logger.info(f"Sent new yap notification for yap {yap_id} to {len(online_users) - 1} users")
        
    except Exception as e:
        logger.error(f"Error notifying new yap: {e}")


def notify_new_message(sender_id: int, recipient_id: int, message_data: dict):
    """Send real-time message notification."""
    delivered = emit_to_user_room(recipient_id, 'new_message', message_data)
    
    if not delivered:
        queue_offline_notification(recipient_id, 'new_message', message_data)


def notify_new_follower(followed_user_id: int, follower_id: int):
    """Send real-time notification when someone follows a user."""
    try:
        follower = Users.query.get(follower_id)
        if not follower or not socketio_instance:
            return
        
        socketio_instance.emit('new_follower', {
            'follower_id': follower_id,
            'follower_name': follower.display_name or f"{follower.first_name} {follower.last_name}",
            'follower_avatar': follower.avatar,
            'follower_username': follower.username,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{followed_user_id}')
        
        logger.info(f"Sent new follower notification to user {followed_user_id} from {follower.username}")
        
    except Exception as e:
        logger.error(f"Error notifying new follower: {e}")


def notify_new_reply(yap_author_id: int, reply_author_id: int, yap_id: int, reply_content: str):
    """Send real-time notification when someone replies to a yap."""
    try:
        if yap_author_id == reply_author_id or not socketio_instance:
            return
        
        reply_author = Users.query.get(reply_author_id)
        if not reply_author:
            return
        
        truncated_content = reply_content[:100] + "..." if len(reply_content) > 100 else reply_content
        
        socketio_instance.emit('new_reply', {
            'reply_author_id': reply_author_id,
            'reply_author_name': reply_author.display_name or f"{reply_author.first_name} {reply_author.last_name}",
            'reply_author_avatar': reply_author.avatar,
            'reply_author_username': reply_author.username,
            'yap_id': yap_id,
            'reply_content': truncated_content,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{yap_author_id}')
        
        logger.info(f"Sent new reply notification to user {yap_author_id} from {reply_author.username}")
        
    except Exception as e:
        logger.error(f"Error notifying new reply: {e}")


def notify_yap_like(yap_author_id: int, liker_id: int, yap_id: int):
    """Send real-time notification when someone likes a yap."""
    try:
        if yap_author_id == liker_id or not socketio_instance:
            return
        
        liker = Users.query.get(liker_id)
        if not liker:
            return
        
        socketio_instance.emit('yap_liked', {
            'liker_id': liker_id,
            'liker_name': liker.display_name or f"{liker.first_name} {liker.last_name}",
            'liker_avatar': liker.avatar,
            'liker_username': liker.username,
            'yap_id': yap_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{yap_author_id}')
        
        logger.info(f"Sent yap like notification to user {yap_author_id} from {liker.username}")
        
    except Exception as e:
        logger.error(f"Error notifying yap like: {e}")


def broadcast_new_yap_to_followers(yap_id: int, author_id: int):
    """Notify followers about a new yap from someone they follow."""
    try:
        if not socketio_instance:
            return
        
        yap = Yap.query.get(yap_id)
        author = Users.query.get(author_id)
        if not yap or not author:
            return
        
        followers_query = db.session.query(Friendship).filter(
            Friendship.addressee_id == author_id,
            Friendship.status == 'accepted'
        ).all()
        
        following_query = db.session.query(Friendship).filter(
            Friendship.requester_id == author_id,
            Friendship.status == 'accepted'
        ).all()
        
        all_connections = set()
        for friendship in followers_query:
            all_connections.add(friendship.requester_id)
        for friendship in following_query:
            all_connections.add(friendship.addressee_id)
        
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
        
        logger.info(f"Broadcasted new yap {yap_id} to {len(all_connections)} followers")
        
    except Exception as e:
        logger.error(f"Error broadcasting new yap to followers: {e}")


# Public API functions
def get_online_users() -> set:
    """Get set of currently online user IDs."""
    return get_presence().get_online_users()


def is_user_online(user_id: int) -> bool:
    """Check if a specific user is online."""
    return get_presence().is_user_online(user_id)


def get_user_pending_requests(user_id: int) -> list:
    """Get formatted pending requests for a user."""
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
        logger.error(f"Error getting pending requests for user {user_id}: {e}")
        return []
