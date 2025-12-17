"""
Redis-backed presence management for multi-session support.

This module provides atomic, scalable presence tracking that works across
multiple server instances and survives restarts.

Key structures in Redis:
- user:{user_id}:sockets -> SET of socket IDs
- socket:{sid}:user -> user ID (for reverse lookup)
- user:{user_id}:status -> HASH { is_online, last_seen, current_status }
- presence:online_users -> SET of user IDs currently online
"""

import json
import logging
from datetime import datetime
from typing import Optional, Set, Dict, Any, List
from redis_config import get_redis_client

logger = logging.getLogger(__name__)

# Key prefixes
USER_SOCKETS_KEY = "user:{user_id}:sockets"
SOCKET_USER_KEY = "socket:{sid}:user"
USER_STATUS_KEY = "user:{user_id}:status"
ONLINE_USERS_KEY = "presence:online_users"

# TTL for socket entries (auto-cleanup if server crashes)
SOCKET_TTL_SECONDS = 300  # 5 minutes - refreshed by heartbeats

# Rate limiting keys
RATE_LIMIT_KEY = "ratelimit:{user_id}:{action}"
RATE_LIMIT_WINDOW = 60  # 1 minute window


class PresenceManager:
    """
    Manages user presence state in Redis for multi-session support.
    
    Ensures:
    - Multiple sockets per user are tracked correctly
    - User only goes offline when ALL sockets disconnect
    - State survives server restarts
    - Works across multiple server instances
    """
    
    def __init__(self, redis_client=None):
        self._redis = redis_client
    
    @property
    def redis(self):
        """Lazy Redis client initialization."""
        if self._redis is None:
            self._redis = get_redis_client()
        return self._redis
    
    def _user_sockets_key(self, user_id: int) -> str:
        return USER_SOCKETS_KEY.format(user_id=user_id)
    
    def _socket_user_key(self, sid: str) -> str:
        return SOCKET_USER_KEY.format(sid=sid)
    
    def _user_status_key(self, user_id: int) -> str:
        return USER_STATUS_KEY.format(user_id=user_id)
    
    def register_socket(self, user_id: int, socket_id: str) -> bool:
        """
        Register a new socket connection for a user.
        
        Returns True if this is the user's first socket (they just came online).
        """
        try:
            pipe = self.redis.pipeline()
            
            # Add socket to user's socket set
            user_sockets_key = self._user_sockets_key(user_id)
            pipe.sadd(user_sockets_key, socket_id)
            pipe.expire(user_sockets_key, SOCKET_TTL_SECONDS)
            
            # Create reverse mapping for disconnect lookup
            socket_user_key = self._socket_user_key(socket_id)
            pipe.set(socket_user_key, str(user_id), ex=SOCKET_TTL_SECONDS)
            
            # Check if user was previously offline (first socket)
            was_offline = not self.redis.sismember(ONLINE_USERS_KEY, str(user_id))
            
            # Mark user as online
            pipe.sadd(ONLINE_USERS_KEY, str(user_id))
            
            # Update status
            status_key = self._user_status_key(user_id)
            now = datetime.utcnow().isoformat()
            pipe.hset(status_key, mapping={
                'is_online': '1',
                'last_seen': now,
                'current_status': 'available',
                'socket_count': str(self.get_socket_count(user_id) + 1)
            })
            pipe.expire(status_key, SOCKET_TTL_SECONDS * 2)
            
            pipe.execute()
            
            logger.info(f"[Presence] User {user_id} registered socket {socket_id[:8]}... (was_offline={was_offline})")
            return was_offline
            
        except Exception as e:
            logger.error(f"[Presence] Error registering socket for user {user_id}: {e}")
            return False
    
    def unregister_socket(self, socket_id: str) -> tuple[Optional[int], bool]:
        """
        Unregister a socket connection.
        
        Returns:
            (user_id, went_offline) - user_id of the socket owner, and whether
            they went fully offline (no more sockets).
        """
        try:
            # Get user ID from socket
            socket_user_key = self._socket_user_key(socket_id)
            user_id_str = self.redis.get(socket_user_key)
            
            if not user_id_str:
                logger.warning(f"[Presence] Socket {socket_id[:8]}... not found in Redis")
                return None, False
            
            user_id = int(user_id_str)
            
            pipe = self.redis.pipeline()
            
            # Remove socket from user's set
            user_sockets_key = self._user_sockets_key(user_id)
            pipe.srem(user_sockets_key, socket_id)
            
            # Remove reverse mapping
            pipe.delete(socket_user_key)
            
            pipe.execute()
            
            # Check remaining sockets
            remaining = self.redis.scard(user_sockets_key)
            went_offline = remaining == 0
            
            if went_offline:
                # No more sockets - mark user offline
                self.redis.srem(ONLINE_USERS_KEY, str(user_id))
                
                status_key = self._user_status_key(user_id)
                now = datetime.utcnow().isoformat()
                self.redis.hset(status_key, mapping={
                    'is_online': '0',
                    'last_seen': now,
                    'current_status': 'offline',
                    'socket_count': '0'
                })
                # Keep status around for a while for "last seen" queries
                self.redis.expire(status_key, 86400)  # 24 hours
                
                logger.info(f"[Presence] User {user_id} went OFFLINE (all sockets disconnected)")
            else:
                # Update socket count
                status_key = self._user_status_key(user_id)
                self.redis.hset(status_key, 'socket_count', str(remaining))
                logger.info(f"[Presence] User {user_id} disconnected socket {socket_id[:8]}... ({remaining} remaining)")
            
            return user_id, went_offline
            
        except Exception as e:
            logger.error(f"[Presence] Error unregistering socket {socket_id}: {e}")
            return None, False
    
    def refresh_socket(self, socket_id: str) -> bool:
        """
        Refresh TTL for a socket (called on heartbeat).
        Returns True if socket exists, False otherwise.
        """
        try:
            socket_user_key = self._socket_user_key(socket_id)
            user_id_str = self.redis.get(socket_user_key)
            
            if not user_id_str:
                return False
            
            user_id = int(user_id_str)
            
            pipe = self.redis.pipeline()
            
            # Refresh all TTLs
            pipe.expire(self._user_sockets_key(user_id), SOCKET_TTL_SECONDS)
            pipe.expire(socket_user_key, SOCKET_TTL_SECONDS)
            pipe.expire(self._user_status_key(user_id), SOCKET_TTL_SECONDS * 2)
            
            # Update last_seen
            pipe.hset(self._user_status_key(user_id), 'last_seen', datetime.utcnow().isoformat())
            
            pipe.execute()
            return True
            
        except Exception as e:
            logger.error(f"[Presence] Error refreshing socket {socket_id}: {e}")
            return False
    
    def get_user_from_socket(self, socket_id: str) -> Optional[int]:
        """Get user ID from socket ID."""
        try:
            user_id_str = self.redis.get(self._socket_user_key(socket_id))
            return int(user_id_str) if user_id_str else None
        except Exception as e:
            logger.error(f"[Presence] Error getting user from socket: {e}")
            return None
    
    def get_socket_count(self, user_id: int) -> int:
        """Get number of active sockets for a user."""
        try:
            return self.redis.scard(self._user_sockets_key(user_id))
        except Exception as e:
            logger.error(f"[Presence] Error getting socket count: {e}")
            return 0
    
    def get_user_sockets(self, user_id: int) -> Set[str]:
        """Get all socket IDs for a user."""
        try:
            return self.redis.smembers(self._user_sockets_key(user_id))
        except Exception as e:
            logger.error(f"[Presence] Error getting user sockets: {e}")
            return set()
    
    def is_user_online(self, user_id: int) -> bool:
        """Check if user has any active sockets."""
        try:
            return self.redis.sismember(ONLINE_USERS_KEY, str(user_id))
        except Exception as e:
            logger.error(f"[Presence] Error checking online status: {e}")
            return False
    
    def get_online_users(self) -> Set[int]:
        """Get set of all online user IDs."""
        try:
            return {int(uid) for uid in self.redis.smembers(ONLINE_USERS_KEY)}
        except Exception as e:
            logger.error(f"[Presence] Error getting online users: {e}")
            return set()
    
    def get_user_status(self, user_id: int) -> Dict[str, Any]:
        """Get full status info for a user."""
        try:
            status = self.redis.hgetall(self._user_status_key(user_id))
            if not status:
                return {
                    'is_online': False,
                    'last_seen': None,
                    'current_status': 'offline',
                    'socket_count': 0
                }
            
            return {
                'is_online': status.get('is_online') == '1',
                'last_seen': status.get('last_seen'),
                'current_status': status.get('current_status', 'offline'),
                'socket_count': int(status.get('socket_count', 0))
            }
        except Exception as e:
            logger.error(f"[Presence] Error getting user status: {e}")
            return {'is_online': False, 'last_seen': None, 'current_status': 'offline', 'socket_count': 0}
    
    def update_user_status(self, user_id: int, status: str) -> bool:
        """Update user's current status (available, away, busy, dnd)."""
        try:
            status_key = self._user_status_key(user_id)
            self.redis.hset(status_key, 'current_status', status)
            return True
        except Exception as e:
            logger.error(f"[Presence] Error updating status: {e}")
            return False
    
    def check_rate_limit(self, user_id: int, action: str, max_requests: int = 30) -> bool:
        """
        Check if user is within rate limit for an action.
        Returns True if request is allowed, False if rate limited.
        """
        try:
            key = RATE_LIMIT_KEY.format(user_id=user_id, action=action)
            current = self.redis.incr(key)
            
            if current == 1:
                self.redis.expire(key, RATE_LIMIT_WINDOW)
            
            return current <= max_requests
            
        except Exception as e:
            logger.error(f"[Presence] Error checking rate limit: {e}")
            return True  # Allow on error
    
    def cleanup_stale_sockets(self) -> int:
        """
        Clean up any stale socket entries.
        Called periodically or on server startup.
        Returns count of cleaned entries.
        """
        try:
            cleaned = 0
            # This is handled by TTL, but we can do explicit cleanup if needed
            online_users = self.get_online_users()
            
            for user_id in online_users:
                socket_count = self.get_socket_count(user_id)
                if socket_count == 0:
                    self.redis.srem(ONLINE_USERS_KEY, str(user_id))
                    cleaned += 1
                    logger.info(f"[Presence] Cleaned stale online entry for user {user_id}")
            
            return cleaned
        except Exception as e:
            logger.error(f"[Presence] Error cleaning stale sockets: {e}")
            return 0
    
    def get_presence_stats(self) -> Dict[str, Any]:
        """Get presence system statistics for monitoring."""
        try:
            online_count = self.redis.scard(ONLINE_USERS_KEY)
            
            # Sample socket counts for online users
            online_users = list(self.get_online_users())[:100]  # Sample first 100
            total_sockets = sum(self.get_socket_count(uid) for uid in online_users)
            
            return {
                'online_users': online_count,
                'sampled_sockets': total_sockets,
                'avg_sockets_per_user': total_sockets / max(len(online_users), 1),
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"[Presence] Error getting stats: {e}")
            return {'error': str(e)}


# Global instance - lazy initialized
_presence_manager: Optional[PresenceManager] = None


def get_presence_manager() -> PresenceManager:
    """Get or create the global presence manager instance."""
    global _presence_manager
    if _presence_manager is None:
        _presence_manager = PresenceManager()
    return _presence_manager


