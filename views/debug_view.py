"""
Debug and admin endpoints for monitoring system state.

These endpoints are protected and should only be accessible to admins in production.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import logging

from models import Users
from presence import get_presence_manager
from redis_config import test_redis_connection, get_redis_client

logger = logging.getLogger(__name__)

debug_bp = Blueprint('debug_bp', __name__)


def is_admin(user_id: int) -> bool:
    """Check if user is an admin. Implement your own logic here."""
    # For now, allow user_id 1 (first user) as admin
    # In production, check against an admin role or flag
    return user_id == 1


@debug_bp.route('/debug/health', methods=['GET'])
def health_check():
    """Basic health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'camposocial-server'
    })


@debug_bp.route('/debug/redis', methods=['GET'])
@jwt_required()
def redis_status():
    """Check Redis connection status."""
    user_id = get_jwt_identity()
    if not is_admin(user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    success, message = test_redis_connection()
    
    return jsonify({
        'redis_connected': success,
        'message': message,
        'timestamp': datetime.utcnow().isoformat()
    })


@debug_bp.route('/debug/presence', methods=['GET'])
@jwt_required()
def presence_overview():
    """Get overview of presence system state."""
    user_id = get_jwt_identity()
    if not is_admin(user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        presence = get_presence_manager()
        stats = presence.get_presence_stats()
        
        return jsonify({
            'success': True,
            'stats': stats,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting presence overview: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@debug_bp.route('/debug/presence/user/<int:target_user_id>', methods=['GET'])
@jwt_required()
def user_presence(target_user_id: int):
    """Get detailed presence info for a specific user."""
    user_id = get_jwt_identity()
    if not is_admin(user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        presence = get_presence_manager()
        
        status = presence.get_user_status(target_user_id)
        sockets = list(presence.get_user_sockets(target_user_id))
        
        # Truncate socket IDs for display
        sockets_display = [f"{s[:8]}..." for s in sockets]
        
        user = Users.query.get(target_user_id)
        
        return jsonify({
            'success': True,
            'user_id': target_user_id,
            'username': user.username if user else None,
            'presence': {
                'is_online': status['is_online'],
                'last_seen': status['last_seen'],
                'current_status': status['current_status'],
                'socket_count': status['socket_count'],
                'sockets': sockets_display
            },
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting user presence: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@debug_bp.route('/debug/presence/online', methods=['GET'])
@jwt_required()
def online_users():
    """Get list of all currently online users."""
    user_id = get_jwt_identity()
    if not is_admin(user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        presence = get_presence_manager()
        online_ids = presence.get_online_users()
        
        # Get usernames for online users
        users_info = []
        for uid in list(online_ids)[:100]:  # Limit to first 100
            user = Users.query.get(uid)
            if user:
                status = presence.get_user_status(uid)
                users_info.append({
                    'user_id': uid,
                    'username': user.username,
                    'socket_count': status['socket_count'],
                    'status': status['current_status']
                })
        
        return jsonify({
            'success': True,
            'total_online': len(online_ids),
            'users': users_info,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting online users: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@debug_bp.route('/debug/presence/cleanup', methods=['POST'])
@jwt_required()
def cleanup_presence():
    """Manually trigger cleanup of stale presence entries."""
    user_id = get_jwt_identity()
    if not is_admin(user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        presence = get_presence_manager()
        cleaned = presence.cleanup_stale_sockets()
        
        return jsonify({
            'success': True,
            'cleaned_entries': cleaned,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error cleaning up presence: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@debug_bp.route('/debug/redis/keys', methods=['GET'])
@jwt_required()
def redis_keys():
    """Get count of Redis keys by pattern (for debugging)."""
    user_id = get_jwt_identity()
    if not is_admin(user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        redis = get_redis_client()
        
        patterns = {
            'user_sockets': 'user:*:sockets',
            'socket_users': 'socket:*:user',
            'user_status': 'user:*:status',
            'rate_limits': 'ratelimit:*',
            'online_users': 'presence:online_users'
        }
        
        counts = {}
        for name, pattern in patterns.items():
            if pattern.endswith('*'):
                keys = redis.keys(pattern)
                counts[name] = len(keys)
            else:
                counts[name] = 1 if redis.exists(pattern) else 0
        
        return jsonify({
            'success': True,
            'key_counts': counts,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting Redis keys: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


