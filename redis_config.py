"""Redis configuration and helper functions for the Flask application."""

import os
import redis
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_redis_client():
    """
    Creates and returns a Redis client instance with connection pooling.
    
    Returns:
        redis.Redis: A Redis client instance
    """
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    redis_db = int(os.getenv('REDIS_DB', 0))
    
    # Create a connection pool for better performance
    pool = redis.ConnectionPool(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        decode_responses=True,  # Automatically decode responses to strings
        max_connections=50,
        socket_connect_timeout=5,
        socket_timeout=5
    )
    
    return redis.Redis(connection_pool=pool)

def test_redis_connection():
    """
    Tests the Redis connection and returns the status.
    
    Returns:
        tuple: (bool, str) - Connection status and message
    """
    try:
        client = get_redis_client()
        client.ping()
        return True, "Redis connection successful"
    except redis.ConnectionError as e:
        return False, f"Redis connection failed: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

# Example cache decorators
def cache_key_wrapper(prefix=""):
    """
    Creates a cache key with an optional prefix.
    
    Args:
        prefix (str): Optional prefix for the cache key
    
    Returns:
        str: Formatted cache key
    """
    def make_key(*args, **kwargs):
        key_parts = [prefix] if prefix else []
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}:{v}" for k, v in sorted(kwargs.items()))
        return ":".join(key_parts)
    return make_key

# Common Redis operations
class RedisCache:
    """Simple Redis cache wrapper with common operations."""
    
    def __init__(self):
        self.client = get_redis_client()
    
    def get(self, key):
        """Get value from cache."""
        return self.client.get(key)
    
    def set(self, key, value, expire=None):
        """Set value in cache with optional expiration time in seconds."""
        if expire:
            return self.client.setex(key, expire, value)
        return self.client.set(key, value)
    
    def delete(self, key):
        """Delete key from cache."""
        return self.client.delete(key)
    
    def exists(self, key):
        """Check if key exists in cache."""
        return self.client.exists(key)
    
    def flush_all(self):
        """Clear all keys from the current database."""
        return self.client.flushdb()
    
    def get_json(self, key):
        """Get JSON value from cache."""
        import json
        value = self.client.get(key)
        if value:
            return json.loads(value)
        return None
    
    def set_json(self, key, value, expire=None):
        """Set JSON value in cache."""
        import json
        json_value = json.dumps(value)
        return self.set(key, json_value, expire)

# Initialize a global cache instance (optional)
# cache = RedisCache()
