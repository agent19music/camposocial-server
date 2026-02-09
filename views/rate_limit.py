from functools import wraps
from flask import request, jsonify, g
from redis_config import get_redis_client
import time
import logging

logger = logging.getLogger(__name__)

def rate_limit(limit=30, window=60, key_prefix="rl"):
    """
    Rate limit decorator using Redis sliding window.
    limit: Number of requests allowed
    window: Time window in seconds
    key_prefix: Prefix for Redis key
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            try:
                # Flask-JWT-Extended puts user in current_user or verify_jwt_in_request puts it in context
                # We'll use request.remote_addr as fallback
                from flask_jwt_extended import get_jwt_identity
                try:
                    user_id = get_jwt_identity()
                except:
                    user_id = None
                
                identifier = user_id if user_id else request.remote_addr
                key = f"{key_prefix}:{identifier}:{request.endpoint}"
                
                redis = get_redis_client()
                if not redis:
                    # Fail open if Redis is down
                    return f(*args, **kwargs)
                
                now = time.time()
                window_start = now - window
                
                # Check current count first (optimization)
                # We use a pipeline to ensure atomicity of cleanup and counting
                pipe = redis.pipeline()
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zcard(key)
                results = pipe.execute()
                
                current_count = results[1]
                
                if current_count >= limit:
                    logger.warning(f"Rate limit exceeded for {identifier} on {request.endpoint}")
                    return jsonify({
                        'error': 'Rate limit exceeded. Please slow down.',
                        'retry_after': window 
                    }), 429
                
                # Add current request
                # Expiry should be window size
                pipe = redis.pipeline()
                pipe.zadd(key, {str(now): now})
                pipe.expire(key, window)
                pipe.execute()
                    
            except Exception as e:
                # Log usage error but don't block request
                # logger.error(f"Rate limit check failed: {e}")
                pass
                
            return f(*args, **kwargs)
        return wrapped
    return decorator
